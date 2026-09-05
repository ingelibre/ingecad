# Plan: los complementos de IngeCAD (topografía, terreno, redes, carreteras)

Escrito el 2026-09-05 a pedido de Marco («ármame un plan para implementar
todo eso con complementos»), sobre el inventario de CivilCAD
(`docs/topografia-civilcad-inventario.md`) y sobre el código real: cada
punto de enganche que se nombra acá existe hoy y se leyó antes de escribir.
Es el rumbo de la v0.5 a la v0.8; el registro de lo hecho vive en git, como
siempre.

---

## 0. En una pantalla

- **Cuatro complementos, en este orden:** Topografía (v0.5) → Terreno y
  Google Earth (v0.6) → Redes de agua y desagüe (v0.7) → Carreteras (v0.8 o
  después). Antes de todos, **el contrato de complementos y su gestor (P0)**,
  diseñados con Topografía como primer cliente real, no en abstracto.
- **Vienen instalados y activados.** El usuario no descarga nada; ve un menú
  más por complemento y puede apagarlo en Herramientas ▸ Complementos.
- **Lo que produce un complemento es DWG normal:** puntos, textos, 3DFACE,
  polilíneas con elevación, tablas. El plano se abre en AutoCAD, BricsCAD y
  ZWCAD sin IngeCAD, igual que un plano hecho con CivilCAD.
- **Casi todo el módulo Google Earth se porta de IngeTrazo** (`app/georef/`,
  1 518 líneas, sin dependencias nuevas): UTM, cotas de un DEM libre, imagen
  satelital, KML/KMZ, CSV de puntos, perfil. Sin Google Earth instalado.
- **Una sola decisión técnica con peso:** la triangulación de Delaunay
  (scipy, 35 MB comprimidos, contra una implementación propia). Se mide en
  T3 y se decide con números.
- **Estimación honesta:** P0 2 sesiones · Topografía 8-10 · Terreno 4-5 ·
  Redes 6-8 · Carreteras 6+. Al ritmo de este proyecto, v0.5 en 4-6 semanas.

---

## 1. Qué es un complemento en IngeCAD (definición operativa)

Un complemento es **un paquete Python dentro de `plugins/<id>/`** que, al
activarse, agrega al programa:

1. **comandos** en el despachador (`Dispatcher.register`), con sus alias
   opcionales y sus nombres localizados;
2. **herramientas interactivas** (subclases de `tools.base.Tool`) en el
   registro que `ToolController.start_tool` consulta (`ALL_TOOL_CLASSES`);
3. **un menú propio** en la barra, entre *Modify* y *Tools*, con submenús;
4. **una barra de herramientas** opcional, apagable desde View como las
   demás (`_build_toolbars` ya nombra cada barra con `setObjectName`);
5. **una página de opciones** opcional en el diálogo Options;
6. **sus traducciones**, en `plugins/<id>/i18n/<lang>/{ui,commands}.json`,
   con el mismo formato que `i18n/` (el descubridor `core/i18n/packs.py`
   aprende a mirar en las carpetas de los complementos activos).

Y al desactivarse **quita exactamente eso**, sin dejar rastro: es el
invariante que el gestor prueba (§2.4). El núcleo no sabe nada de
topografía; sabe activar y desactivar complementos.

**Lo que NO cambia, y es lo que hace que esto funcione:**

- **Principio 4 del CLAUDE.md, intacto:** toda mutación es un `Command` con
  undo exacto y toda operación es una acción headless. Un complemento
  escribe sus acciones en `plugins/<id>/actions.py` con el mismo patrón que
  `core/actions.py` (`AddEntityCommand("TOPO-PUNTO", factory, layer)`,
  `CompositeCommand` para lo que va junto, como ya hace
  `core/tables.insert_table`). Las herramientas son cáscaras finas sobre
  las acciones, como `tools/draw.py` sobre `actions.add_line`.
- **El documento ezdxf sigue siendo el modelo.** Un complemento no inventa
  un modelo propio: sus objetos son entidades DXF en capas con nombre, y lo
  que necesita recordar (que estos 3DFACE son *una* triangulación, que este
  dibujo está en la zona 19 Sur) va en **XDATA bajo el APPID `INGECAD`** y
  en un diccionario de extensión del documento. Todo eso sobrevive al
  round-trip conservador y no molesta a ningún otro CAD.
- **Idiomas:** lo que se tipea es inglés (`TIN`, `CONTOUR`, `PROFILE`,
  `CTABLE`) con nombre localizado aditivo (`TRIANGULAR`, `CURVAS`,
  `PERFIL`, `CUADRO`), por la misma regla de `docs/i18n.md`. El test de
  cobertura de traducción recorre también los packs de los complementos.
- **El filtro maestro sigue mandando** dentro de cada complemento: entra lo
  que Marco usa del oficio; el clon rutina por rutina de CivilCAD (245) no
  es la meta. Del inventario, entra lo marcado 🟢 y 🟡; lo 🔴 mexicano no.

---

## 2. P0 — El contrato y el gestor (2 sesiones)

### 2.1 Forma del paquete

```
plugins/
├── __init__.py
├── topografia/
│   ├── __init__.py        ← PLUGIN = PluginSpec(...)   (lo único que el núcleo lee)
│   ├── actions.py         ← headless: tin_from_points(), contours(), ...
│   ├── tools.py           ← Tool subclasses: PointsImportTool, ContourTool, ...
│   ├── commands.py        ← handlers del dispatcher (delgados: parsean args, llaman actions)
│   ├── geo.py, tin.py, contours.py, sections.py, volumes.py  ← matemática pura, numpy
│   ├── i18n/es/{ui,commands}.json
│   ├── resources/icons/
│   └── tests/             ← corre con la suite (pytest descubre plugins/*/tests)
├── terreno/
├── redes/
└── carreteras/
```

`PluginSpec` (en `core/plugins.py`, dataclass simple):

```
id, name, version, description
requires: tuple[str, ...]          # módulos pip que necesita ("scipy",) — se comprueban, no se instalan
commands: dict[str, handler]       # {"TIN": run_tin, ...}
tools: dict[str, type[Tool]]       # {"CONTOUR": ContourTool, ...}
aliases: dict[str, str]            # {"CN": "CONTOUR"} — rechazados si pisan DEFAULT_ALIASES
menu: list[MenuItem | Submenu | SEPARATOR]
toolbar: list[ToolbarItem] | None
options_page: Callable | None
i18n_dir: Path | None
on_document_open: Callable | None  # p. ej. leer el datum guardado en el DWG
```

### 2.2 El cargador (`core/plugins.py`)

- **Descubre** `plugins/*/` del paquete y `~/.config/IngeCAD/plugins/*/`
  del usuario (terceros, después; el mismo contrato desde el día uno para
  que no haya dos).
- **Estado** en QSettings: `plugins/<id>/enabled` (los incluidos, `True`
  por defecto; un tercero, `False` hasta que el usuario lo prenda).
- **Activar** = registrar comandos, alias y herramientas, fusionar su pack
  de idioma, reconstruir menús y barras. **Desactivar** = lo inverso.
  Hacen falta tres cosas que hoy no existen y son pequeñas:
  `Dispatcher.unregister`, un registro de herramientas con alta y baja
  (hoy `ALL_TOOL_CLASSES` es un dict de módulo que `start_tool` indexa),
  y un hook en `_build_menus` que inserte los menús de los complementos
  activos antes de *Tools* (la barra se reconstruye entera con
  `menu_bar.clear()`, así que insertar ahí es natural y ya cubre el cambio
  de idioma).
- **Dependencias faltantes**: si `requires` no importa, el complemento se
  lista **deshabilitado con el motivo** («necesita scipy»), nunca rompe el
  arranque. En los paquetes propios (Flatpak, AppImage, Snap) las
  dependencias van incluidas, así que ese estado sólo lo ve quien corre
  desde el código.

### 2.3 El gestor (Herramientas ▸ Complementos…)

Modelo QGIS, sin tienda: una lista con casilla, nombre, versión,
descripción y estado de dependencias; prender y apagar aplica al instante.
Nada de instalar desde internet en la v1 del gestor.

### 2.4 Lo que P0 exige antes de cerrarse (DoD)

- Un complemento de muestra (`plugins/_ejemplo/`, no incluido en release)
  registra un comando, una herramienta, un alias, un menú y un pack `es`.
- **Test del invariante «cero contaminación»:** activar y desactivar cada
  complemento incluido deja el despachador (`known_names()`), el registro
  de herramientas, los menús y los alias **idénticos** al estado previo.
  Sin este test el gestor es decoración.
- El test de cobertura i18n y el de prompts con opciones recorren los packs
  de los complementos.
- Empaquetado: `plugins/` viaja en los tres paquetes — el manifiesto
  Flatpak copia hoy `main.py core views render formats tools resources
  i18n` (hay que agregar `plugins`), el `.spec` de PyInstaller lista
  `resources` e `i18n` en `datas` (ídem), y `main.py --check` informa qué
  complementos encontró.
- `docs/plugins.md` en inglés: el contrato para un contribuidor externo,
  con el ejemplo como tutorial.

---

## 3. TOPOGRAFÍA — `plugins/topografia/` (v0.5, 8-10 sesiones)

El caso que lo define, escrito ya en la fase 7 del CLAUDE.md y confirmado
por el inventario: **CSV del topógrafo → plano de lindero enganchado a los
puntos → cuadro de coordenadas y área → triangulación y curvas → perfil del
eje → DWG al colega**, todo sin AutoCAD.

Convenciones de entidades (las que cualquier CAD entiende):

| objeto | entidad DXF | capa por defecto | XDATA |
|---|---|---|---|
| punto topográfico | POINT en (E, N, Z) + TEXT número / cota / descripción | `TOPO-PUNTOS`, `TOPO-COTAS`, `TOPO-DESC` | id, descripción |
| triangulación | 3DFACE por triángulo | `TOPO-TIN` | id de superficie |
| línea límite (breakline) | LWPOLYLINE / POLYLINE 3D | `TOPO-LIMITES` | id de superficie |
| curva de nivel | LWPOLYLINE con `elevation` | `TOPO-CN-GRUESA`, `TOPO-CN-FINA` | intervalo |
| cuadro de construcción / datos técnicos | líneas + TEXT (`core/tables.insert_table`) | `TOPO-CUADROS` | — |
| eje, estacas, perfil, secciones dibujadas | LWPOLYLINE + TEXT + bloques | `TOPO-EJE`, `TOPO-PERFIL`, `TOPO-SECCIONES` | estación |

### T1 — Puntos (1 sesión)

`PIMPORT` (importar CSV / estación total: P,N,E,Z,D y los dialectos que
`parse_points_csv` de IngeTrazo ya reconoce; diálogo de columnas y de
capas), `PEXPORT`, `PBY` (dibujar punto por rumbo y distancia, azimut,
deflexión, intersección de rumbos: entrada por prompt, como las coordenadas
polares que ya existen), `PRENUM`, `PFIND`. Los puntos entran al índice de
picado y al snap NOD **bit-exacto**.
- **DoD:** un CSV real de un topógrafo de Marco → 500 puntos en sus tres
  capas, un lindero dibujado enganchando NOD a los puntos, y el DWG
  guardado abre en BricsCAD con los mismos puntos.

### T2 — Anotación, cuadros y subdivisión (1-2 sesiones)

`ANNOT` (rumbo y distancia sobre líneas; longitud, radio, delta y cuerda en
arcos; prefijo/sufijo/decimales), `CTABLE` (cuadro de construcción y de
datos técnicos: vértice, Este, Norte, lado, distancia, rumbo/azimut, ángulo
interior, área y perímetro; formato peruano por defecto, columnas
elegibles), `AREASUM`, `SUBDIV` (subdividir un polígono por área con línea
paralela a un lado o por dos puntos, bisección numérica), `UTMGRID`
(retícula UTM con etiquetas).
- **DoD:** el cuadro de un lindero real coincide con el que Marco calculaba
  a mano o con LISP; `SUBDIV` deja dos áreas cuya suma es la original al
  centímetro cuadrado.

### T3 — Triangulación (2 sesiones) ⚠️ la decisión

`TIN` (de puntos seleccionados o de una capa; líneas límite opcionales),
`TINEDIT` (invertir arista, borrar triángulo, recortar por polígono,
insertar punto), `TINCHECK`. La TIN se materializa como 3DFACE con XDATA.
- **La decisión se mide, no se supone.** Dos candidatos:
  1. **scipy.spatial.Delaunay** (Qhull, licencia BSD): 35 MB de wheel,
     ~110 MB instalados. Medir: tamaño del Flatpak y del AppImage antes y
     después, y tiempo de `import scipy.spatial` (la importación va
     diferida al primer `TIN`, nunca al arranque). Las líneas límite se
     imponen después por volteo de aristas.
  2. **Implementación propia** (Bowyer-Watson con numpy o barrido de
     Fortune): cero dependencias, 1-2 sesiones más, y hay que validarla
     contra Qhull sobre los mismos puntos (mismos triángulos salvo casos
     cocirculares).
  Descartado **Triangle** de Shewchuk: su licencia no permite redistribuir
  en un paquete.
- Umbral para elegir: si scipy suma menos del 25 % al Flatpak y la
  importación diferida cuesta menos de 1 s, va scipy. Si no, propia.
- **DoD:** con los puntos reales de T1, la TIN respeta cada línea límite
  (ningún triángulo la cruza, test), 20 000 puntos triangulan en menos de
  2 s, y el DWG con 3DFACE abre en BricsCAD como superficie visible.

### T4 — Curvas de nivel (1 sesión)

`CONTOUR` (intervalo fino y grueso, colores, capa por tipo, marcha por
triángulos; suavizado opcional por spline con la advertencia de que una
curva suavizada puede cruzar otra), `CONTOURLABEL` (cota sobre la curva,
alineada, cada N metros o por clic), `SLOPEZONES` (color por rango de
pendiente).
- **DoD:** las curvas de un terreno real coinciden a ojo con las que Marco
  generaba en CivilCAD para el mismo CSV (**si conserva un DWG hecho con
  CivilCAD, es la referencia dorada**: comparar curva por curva a la misma
  cota); ninguna curva se cruza sin suavizar; el DWG abre con las curvas en
  su elevación en cualquier CAD.

### T5 — Perfiles, secciones y volúmenes por estación (2 sesiones)

`PROFILE` (eje = polilínea; estacas cada N m; perfil del terreno desde la
TIN, dibujado como entidades con retícula, escalas horizontal y vertical
independientes, y además en el panel inferior vivo que ya se planeó —
portar el concepto de `ProfileDock` de IngeTrazo), `GRADELINE` (rasante:
polilínea sobre el perfil; pendientes anotadas; puntos de inflexión),
`SECTIONS` (secciones transversales por estación, ancho a cada lado,
dibujadas en grilla), `VOLUMES` (áreas de corte y relleno por sección,
volumen prismoidal entre estaciones, tabla y CSV; ordenadas de curva masa
listas para Carreteras).
- **DoD:** el perfil de un eje real de Marco con su rasante da los mismos
  volúmenes que el cálculo prismoidal a mano en tres estaciones elegidas;
  export CSV.

### T6 — Plataformas y taludes (1-2 sesiones)

`PLATFORM` (polígono a cota o con pendiente; taludes de corte y relleno
distintos por lado, bermas), `DAYLIGHT` (línea cero: intersección
talud-terreno sobre la TIN), `VOLTIN` (volumen exacto TIN contra TIN,
corte y relleno por separado).
- **DoD:** una plataforma sobre terreno real: la línea cero cierra, y el
  volumen TIN-TIN coincide con el de secciones finas dentro del 2 %.

### T7 — Memorias y reportes (1 sesión)

`MEMORIA` (memoria descriptiva del polígono: vértices, colindancias por
lado, área y perímetro, a texto y CSV), `AREAREPORT` (resumen de áreas por
manzana / lote). **El formato peruano (COFOPRI / SUNARP / municipal) se
define con Marco sobre un trámite real**, no se inventa.
- **DoD de la v0.5 completa = el caso municipal de la fase 7 del
  CLAUDE.md**, de punta a punta, en un plano real, y el DWG resultante
  abierto por un colega en AutoCAD sin una sola entidad rara.

---

## 4. TERRENO Y GOOGLE EARTH — `plugins/terreno/` (v0.6, 4-5 sesiones)

Lo que Marco valora del módulo Google Earth de CivilCAD, hecho con fuentes
libres y **sin Google Earth instalado**. Casi todo se porta de
`ingetrazo/app/georef/` (Qt Network + numpy, ninguna dependencia nueva).

### G1 — Georreferenciación del dibujo (1 sesión)

`GEOREF` (zona UTM y hemisferio, dados o calculados de una longitud
aproximada; datum WGS84 o **PSAD56** con la transformación para planos
antiguos del Perú; se guarda en el diccionario del documento y se lee al
abrir), `LATLON` (leer y tipear coordenadas geográficas en el prompt).
Portar `georef/datum.py` (`utm_forward` / `utm_inverse`, sin pyproj).
- **DoD:** ida y vuelta UTM ↔ lat/lon con error < 1 mm sobre puntos de
  control conocidos de la zona 19S; el datum sobrevive guardar y reabrir.

### G2 — Cotas del terreno (1 sesión)

`DEMPOINTS` (polígono + espaciado → puntos con cota de un DEM global; la
malla se puede pasar directo a `TIN`), `DEMPROFILE` (perfil sin
levantamiento). Fuente primaria: **AWS Terrain Tiles** (terrarium, sin
clave; ya en `georef/dem.py`); de respaldo, **Copernicus GLO-30** por HTTPS
(verificado sin clave para la tesela de Arequipa). Caché en disco.
- **Honestidad en pantalla:** la precisión es la de un DEM de 30 m; el
  comando lo dice al terminar, como lo advierte el propio distribuidor de
  CivilCAD. Es para anteproyecto.
- **DoD:** una malla de 200 × 200 m se baja y triangula en menos de 10 s
  con la caché fría; con la caché caliente, instantáneo.

### G3 — Imagen satelital (1-2 sesiones)

`SATIMAGE` (polígono → mosaico de teselas al zoom pedido, insertado como
**IMAGE georreferenciada** en su capa, recortado al polígono opcionalmente;
fuentes con licencia para este uso: Esri World Imagery, EOX Sentinel-2,
OSM, más plantilla XYZ propia del usuario, como en IngeTrazo). IngeCAD ya
dibuja IMAGE y ya mueve sus cuatro esquinas sin regen.
- **DoD:** un lote real con su imagen debajo, guardado como DWG + JPG al
  lado, abre en BricsCAD con la imagen en su sitio.

### G4 — Ida y vuelta con Google Earth por KML/KMZ (1 sesión)

`KMLIN` (polígonos, rutas y marcadores → polilíneas y puntos, conservando
nombre y color; portar `georef/geoimport.py`), `KMLOUT` (puntos, polilíneas
y polígonos seleccionados → KMZ con nombre, descripción y color; se abre en
Google Earth con doble clic), `KMLOVERLAY` (captura del dibujo como
GroundOverlay, con opacidad; reusa `render_image`).
- **DoD:** un lindero exportado se ve en Google Earth exactamente sobre la
  parcela; el mismo KMZ reimportado devuelve las coordenadas UTM originales
  con error < 1 cm.

**Empaquetado, obligatorio para este complemento:** el Flatpak hoy no tiene
`--share=network` en ejecución (sí tiene wayland, dri y home); hay que
agregarlo en `finish-args` y explicarlo en el metainfo. El Snap ya declara
el plug `network`.

---

## 5. REDES — `plugins/redes/` (v0.7, 6-8 sesiones)

La red se **dibuja con líneas**, como en CivilCAD: el complemento reconoce
el grafo (nodos en los vértices, tramos entre ellos), inserta símbolos y
guarda los datos de cada nodo y tramo en XDATA. Normas de referencia:
**RNE OS.050** (agua para consumo humano) y **OS.070** (aguas residuales),
no CONAGUA.

### R0 — Modelo de red (1 sesión)

`NETRECOGNIZE` (líneas → grafo; nodos numerados; sentido de flujo por
cotas o manual), `NETEDIT` (insertar / quitar nodo, unir tramos), cotas de
nodo desde la TIN de Topografía si existe. Todo headless y con undo.

### R1 — Agua potable (2-3 sesiones)

Datos por nodo (cota, caudal o población), por tramo (diámetro, material,
C de Hazen-Williams o rugosidad); cálculo de redes abiertas, cerradas y
mixtas (Hardy-Cross), presiones en nodos, velocidades en tramos, con los
límites de OS.050 marcados en rojo en la tabla; catálogo editable de
diámetros comerciales; anotación en plano (diámetro-longitud-material en
tramos, cota y presión en nodos), simbología (válvulas, hidrantes,
bloques), tabla de cálculo (`insert_table`) y CSV.
- **DoD:** una red de ejemplo del RNE o de un expediente real da las mismas
  presiones que la hoja de cálculo de Marco, nodo por nodo.

### R2 — Alcantarillado (2-3 sesiones)

Pozos en vértices (numerar, cota de tapa desde la TIN, profundidad), caudal
por tramo (dotación, población, infiltración, conexiones erradas), diseño
de diámetro y pendiente por Manning con tirante, velocidad y **tensión
tractiva** contra OS.070, anotación (cota de terreno, clave y fondo en
pozos; longitud-pendiente-diámetro en tramos), **perfil de la red dibujado**
(terreno y tubería, pozos con profundidades) y editor de rasante sobre ese
perfil, tabla y CSV.
- **DoD:** un colector real diseñado en IngeCAD cumple OS.070 en todos los
  tramos y el perfil dibujado coincide con el del expediente.

### R3 — Cuantificación (1 sesión)

Excavación, cama y relleno por diámetro y profundidad media; lista de
materiales por tramo y nodo; CSV que IngePresupuestos pueda leer (**el
puente al hermano**: metrado de redes sin retipear).

Fuera de alcance: pluvial con catálogo de un fabricante (ADS); si algún día
entra pluvial, es con intensidad-duración de SENAMHI y sin marca.

---

## 6. CARRETERAS — `plugins/carreteras/` (v0.8 o después, 6+ sesiones)

Se apoya en Topografía (eje, perfil, secciones, volúmenes ya existen ahí).
Norma **DG-2018** del MTC, no SCT.

- **C1 — Eje y estacado:** progresivas, cuadro del eje, invertir
  cadenamiento, separar eje.
- **C2 — Curvas horizontales simples:** PI, radio, tangentes; cuadro de
  curvas; anotación de PC/PT.
- **C3 — Curvas verticales:** por longitud o por distancia de visibilidad
  (DG-2018), sobre la rasante de T5.
- **C4 — Curva masa:** de los volúmenes de T5; línea compensadora,
  sobreacarreos, préstamo y desperdicio; reporte.
- **Después, sólo si duele:** espirales, peralte y sobreancho. Es el tramo
  que más se parece al clon rutina por rutina y el rumbo lo descarta hasta
  que un plano real lo pida.

---

## 7. Dependencias, empaquetado y rendimiento

| tema | decisión |
|---|---|
| scipy | se mide en T3 (§3); si entra, va en `requirements.txt` y en los tres paquetes, importada **diferida** desde el complemento |
| red en ejecución | Flatpak: agregar `--share=network`; Snap: ya tiene el plug; AppImage: sin sandbox |
| `plugins/` en los paquetes | manifiesto Flatpak (`cp -a … plugins`), `datas` del `.spec`, Snap hereda del bundle |
| tamaño de una TIN en pantalla | 20 000 puntos ≈ 40 000 3DFACE ≈ 120 000 vértices: nada para el visor (SEDAPAR mueve 7,5 millones) |
| arranque | ningún complemento importa numpy-pesado ni red al arrancar; se registra el `PluginSpec` y el trabajo se importa al primer comando |
| caché de DEM y teselas | `~/.cache/IngeCAD/` con tope de tamaño; nunca en `/tmp` (tmpfs, lección anotada) |

---

## 8. Banco de pruebas y método (lo que hace que el plan sea verificable)

- **El «plano del colega» de topografía:** dos o tres CSV reales de
  topógrafos (con permiso, fuera del repo público) y, si Marco los
  conserva, **DWG hechos con CivilCAD del mismo levantamiento** (TIN,
  curvas, cuadro). Son la referencia dorada: la misma cota, la misma curva.
- **Toda matemática es headless y con test:** Delaunay (propiedad del
  círculo vacío, líneas límite respetadas), curvas (nunca se cruzan; cota
  correcta en cada vértice), volúmenes (prismoidal contra casos cerrados),
  Hardy-Cross (contra un ejemplo resuelto del RNE), Manning (contra tablas).
- **Cada fase cierra con la regla de oro:** DoD cumplido, commiteado, app
  sin regresiones, cero «lo dejo para después». Los tests de un complemento
  viven con él y corren con la suite.
- **Medir antes de creer:** scipy (§3), la red (tiempos con caché fría y
  caliente), la TIN de 20 000 puntos (2 s), el arranque (que no suba).
- **Dogfooding de Marco al final de cada fase**, con su flujo real: lo que
  reporte manda sobre la lista, como pasó con las siete cosas de la v0.4.7.

---

## 9. Decisiones que son de Marco (para cuando toque, no ahora)

1. **Formato de las memorias y cuadros peruanos** (COFOPRI / SUNARP /
   municipio): un ejemplo real de cada uno antes de T7.
2. **Parámetros por defecto de OS.050 / OS.070** (dotaciones, coeficientes,
   velocidades y presiones límite): confirmar contra la edición vigente del
   RNE antes de R1/R2.
3. **Fuentes de imagen satelital**: las tres con licencia van por defecto;
   una plantilla XYZ propia (incluida Google) la pega el usuario bajo su
   responsabilidad, como en QGIS e IngeTrazo. IngeCAD no la trae de fábrica.
4. **Nombre de los comandos localizados** (TRIANGULAR, CURVAS, PERFIL…):
   mi mejor lectura de CivilCAD y de AutoCAD en español; son aditivos, se
   corrigen cambiando una cadena.
5. **Si entra scipy** o se escribe la triangulación propia: con los números
   de T3 en la mano.

---

## 10. Calendario tentativo

| fase | sesiones | entrega |
|---|---|---|
| P0 contrato + gestor | 2 | complemento de muestra, test de cero contaminación, paquetes con `plugins/` |
| T1–T2 puntos, cuadros, subdivisión | 2-3 | **v0.5.0-alpha**: el lindero con su cuadro |
| T3–T4 TIN y curvas | 3 | **v0.5.0-beta**: curvas de nivel de un CSV |
| T5–T7 perfiles, plataformas, memorias | 3-4 | **v0.5.0**: el caso municipal completo |
| G1–G4 terreno y KML | 4-5 | **v0.6.0** |
| R0–R3 redes | 6-8 | **v0.7.0** |
| C1–C4 carreteras | 6+ | **v0.8.0** |

Cada versión se publica sólo con el OK de Marco, como quedó acordado.
