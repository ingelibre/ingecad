# CivilCAD (ARQCOM) — inventario completo y qué puede hacer IngeCAD

Investigado el 2026-09-05 a pedido de Marco («averigua a fondo todo lo que
tiene CivilCAD y dime si se puede implementar eso en IngeCAD»). Este
documento es la referencia para diseñar el complemento de topografía (v0.5)
y los que vengan después. Está en español porque su lector es el ingeniero
que decide el rumbo, no el contribuidor; las notas de implementación que
salgan de acá van en inglés, como todo el código.

Fuentes: la web oficial (civilcad.com.mx: portada, «Rutinas», «Módulo
Topográfico Básico» y las páginas de cada módulo), el folleto oficial
CivilCAD 2025.1 (PDF, enero 2026), la base de conocimiento de ARQCOM, dos
distribuidores (softwaredeingenieria.es, solcom) y, para el mecanismo de
Google Earth, la documentación de CAD-Earth (el mismo problema, resuelto de
otra forma). URLs al final.

---

## 1. Qué es CivilCAD

- **Complemento** para AutoCAD Full 2020-2027, BricsCAD PRO V20-V26 y ZWCAD
  PRO 2020-2026. No es un CAD: se cuelga del menú del CAD anfitrión y sus
  rutinas se tipean en la línea de comandos. Escrito en ARX / Visual LISP.
  **Solo Windows** (10 y 11).
- Hecho por ARQCOM (México) para «el ingeniero civil y topógrafo de habla
  hispana»; declara más de 20 000 usuarios en Latinoamérica. Sus normas de
  referencia son mexicanas: SCT (carreteras), CONAGUA/CNA (agua y drenaje),
  RAN (cuadros de construcción), ADS Mexicana (tuberías pluviales).
- **Precios (folleto 2025.1, pesos mexicanos):**

| licencia | anual | permanente |
|---|---|---|
| Básico (topografía) | $6 895 | $14 800 |
| Redes (agua + alcantarillado) | $10 295 | $25 000 |
| Vialidades (carreteras SCT) | $9 295 | $22 100 |
| Earth (Google Earth) | $8 195 | $18 600 |
| Completo | $13 995 | $36 100 |

  A ~18,5 MXN/USD el «Completo» permanente son unos USD 1 950, más la
  licencia de AutoCAD o BricsCAD que necesita debajo.

- Estructura: un **módulo básico** (topografía, incluido en la licencia) y
  cinco **módulos adicionales** que se compran aparte: Interfase con Google
  Earth, Redes de Agua Potable, Redes de Alcantarillado, Redes de
  Alcantarillado Pluvial ADS, Carreteras SCT (+ exportación al programa
  Curva Masa SCT).

---

## 2. Inventario de rutinas (245, según la página «Rutinas» de la versión 2023)

### 2.1 Módulo Topográfico Básico (incluido)

**Puntos e importación.** Lee archivos por coordenadas, radiaciones,
estación-offset-elevación, coordenadas GPS y libretas electrónicas de
estación total directamente. Exporta puntos en cualquier combinación de
columnas (número, clave, N, E, Z). Dibuja puntos por azimut, ángulos,
deflexiones, perpendicular a línea o eje, intersección de rumbos y azimuts.
Rutinas para anotar, renumerar, modificar, unir, rotar, escalar, localizar y
convertir puntos.

**Texto (19 rutinas).** Estilo de texto, definir altura, escribir,
directriz, arco-texto, separar, editar, intercambiar y reespaciar líneas,
sumar texto, importar/exportar texto, cambiar variables, anotar (líneas,
arcos, áreas), numerar, acotar vértices. Anotación automática individual o
global: rumbo y distancia en líneas; longitud, radio, delta, cuerda y
subtangente en arcos; con prefijo, sufijo, altura y decimales.

**Altimetría / triangulación (16).** Triangulación (Delaunay), de terreno y
de proyecto; invertir, ordenar, revisar, recortar y refinar la
triangulación; dibujar y convertir líneas límite (breaklines) y línea cero;
zonificación por pendientes; proyectar puntos; insertar puntos en la
triangulación; malla 3D.

**Curvas de nivel (4).** Generar curvas de nivel (intervalo y color para
gruesas y delgadas), visualizar curvas, curva Z, anotar curvas de nivel.

**Polígono (7).** Dibujar polígono, corregir polígono, subdivisión de
polígono (por área), centro geométrico, retícula UTM, retícula GPS, dibujar
arco.

**Cuadros (5).** Cuadro de construcción (con un clic sobre el polígono:
rumbo, distancia, azimut, ángulos interiores, coordenadas y superficie;
formato RAN; numeración horaria/antihoraria; con coordenadas UTM-GPS,
factor de convergencia y escala lineal), cuadro de curvas, editor, editar
objetos, sumar áreas.

**Eje de proyecto (2).** Marcar estaciones, anotar elevaciones.

**Perfiles (9).** Dibujar y convertir perfil de terreno y de proyecto;
anotar estación-elevación, pendiente, puntos de inflexión; retícula; curvas
verticales. El perfil anota estación, espesores y elevaciones de corte y
terraplén, volúmenes y ordenadas de curva-masa.

**Secciones / volúmenes (4).** Volúmenes, procesar eje, diseño de taludes
con bermas, procesar secciones (las secciones transversales se dibujan a la
vez y sale un archivo con áreas y volúmenes de corte y terraplén por
estación).

**Plataformas (7).** Dibujar, indicar taludes (distintos para corte y
terraplén, izquierda y derecha, con bermas), línea cero, cálculo de
volúmenes por seccionamiento y por método exacto (prismoidal), puntos de
proyecto.

**Secciones de terreno (5).** Dibujar, convertir, obtener sección de
terreno, reporte de puntos, dibujar puntos.

**Reportes (15).** Indicar colindancias, lotificación y puntos; memoria de
puntos geométricos, memoria técnica, memoria descriptiva, descriptiva-
técnica; resumen de áreas por manzana; localizar punto, colindancia, lote,
manzana; imprimir y editar reporte; capa. Formato: líneas por hoja,
márgenes, encabezados; exporta a Excel y texto delimitado.

**Bloques.** Librería de detalles y bloques editables; 20 estilos de texto.

### 2.2 Módulo Interfase con Google Earth (8)

Obtener malla desde Google Earth (polilínea cerrada + origen, rotación y
espaciado de retícula → malla de triangulación con la elevación de Google
Earth en cada nodo); importar y exportar puntos (marcas de posición con
número y descripción); importar y exportar polígonos y rutas (KML, conserva
color/línea/relleno, como polilínea ligera, pesada o 3D); importar imagen
georreferenciada (recortada al polígono, en retícula para zonas grandes;
BMP/JPEG/TIFF); exportar captura de pantalla como superposición de imagen
(GIF/PNG/BMP/JPEG, opacidad, fondo transparente); reconocer estructura
pluvial. Conversión UTM ↔ geográficas en los diálogos, zona UTM dada o
calculada de la longitud, datum WGS84 / NAD27 / NAD83.

**Cómo saca las cotas, y por qué es frágil.** Requiere Google Earth
**instalado** y conexión a internet: consulta la elevación a través de la
interfaz COM del programa de escritorio. Google eliminó esa interfaz en
Google Earth Pro 7.3 de 64 bits, así que estos productos exigen instalar la
versión de 32 bits (documentado para CAD-Earth, que resolvió el problema
cambiando la fuente de cotas al servidor de terreno de Cesium). Y el propio
distribuidor lo advierte: es un método «recomendado para anteproyectos que
no requieran mucha precisión, ya que los datos que maneja Google Earth son
aproximados por interpolación». Es decir: **la cota de Google Earth es un
DEM global de ~30 m interpolado**, no un levantamiento.

### 2.3 Módulo Redes de Agua Potable (35)

Reconoce circuitos dibujados con líneas; calcula redes abiertas, cerradas y
combinadas; pérdidas por Hazen-Williams, Manning y Darcy-Weisbach, con
Hardy-Cross para la convergencia en circuitos cerrados; balance de cargas en
nodos proporcional a la longitud de tramos o a la población alimentada.
Nodos: numerar, editar número, indicar datos (elevación, gasto,
descripción), nodo de alimentación, calcular elevación de nodos (desde la
triangulación), anotar cotas, insertar/remover/localizar/mostrar nodo,
editar propiedades, generar despiece (cruceros con piezas especiales y
lista de materiales). Tuberías: indicar datos (gasto, unidades alimentadas,
coeficiente de pérdidas mínimas, descripción, color, diámetro, material),
anotar datos, insertar válvula de corte, nodo en tubería, hidrante, bloque,
paso a desnivel; cuadro de simbología, notas y detalles hidráulicos. Tabla de
cálculo hidráulico, iteraciones y resultados en nodos, en su planilla
DataCalc, exportable a Excel y CSV. Lista editable de materiales y
diámetros comerciales.

### 2.4 Módulo Redes de Alcantarillado (18)

Reconoce redes dibujadas con líneas e inserta el símbolo de pozo de visita
en cada vértice; dirección de flujo automática (por rasante de pozos) o
manual; calcula diámetro y pendiente; gasto mínimo, medio y máximo con
pérdidas por conexiones erradas e infiltración; velocidades y tirantes
mínimos y máximos por relación de gasto; anota cotas de terreno, clave,
plantilla y profundidad en pozos, longitud-pendiente-diámetro en tramos,
símbolos de caída libre y adosada; volúmenes de excavación, plantilla y
relleno según diámetro y profundidad media; **editor gráfico de perfiles**
(modificar cotas de terreno, clave y batea, longitud, pendiente y diámetro)
y tabla de resultados. Pozos: numerar, editar número, indicar y calcular
rasante, insertar, remover, localizar. Tuberías: indicar datos, flujo,
cabeza de atarjea, unidades drenadas, área tributaria, área comercial-
industrial-equipamiento, nombre de calle, coeficiente de rugosidad; detalles
sanitarios.

### 2.5 Módulo Alcantarillado Pluvial ADS (39)

Lo mismo que el sanitario más subcuencas (reconocer, agregar, eliminar,
cauce principal), estructuras de captación (insertar en tubería, conectar a
tramo o pozo, nomenclatura, rasante), editor de curvas
intensidad-duración, cuantificación de tubería ADS N-12 y catálogo de
conceptos CNA. Específico de un fabricante mexicano.

### 2.6 Módulo Carreteras SCT (28)

Hojas de captura (nivelación diferencial, seccionamiento por elevación y
por desnivel); curvas horizontales simples y espirales (dibujar, anotar,
editar, eliminar; gráfica de sobreanchos, cuadro y diagrama de curvas;
secciones con sobreelevación y sobreancho); curvas verticales (por
velocidad de proyecto, tiempo de reacción, distancias de visibilidad de
parada y rebase); eje de trazo (cuadro de construcción del eje, separar,
invertir cadenamiento, reporte); curva masa (convertir, línea compensadora
dibujar/mover, sobreacarreos, préstamos y desperdicios, anotar y reportar);
reporte de seccionamiento en formato SCT a Excel; exportación al programa
Curva Masa 3.0 de la SCT.

---

## 3. Lo que IngeCAD ya tiene, lo que se porta de IngeTrazo, lo que hay que escribir

La sorpresa de la investigación es cuánto está hecho. IngeTrazo lleva un
paquete `app/georef/` (Track G) que cubre, **sin Google Earth y sin ninguna
dependencia pip nueva**, el grueso del módulo Google Earth de CivilCAD:

| pieza de IngeTrazo | qué hace | equivalente en CivilCAD |
|---|---|---|
| `georef/datum.py` | UTM directa e inversa (fórmulas propias, sin pyproj) | conversión UTM-GPS |
| `georef/dem.py` | cota en cualquier lat/lon desde **AWS Terrain Tiles** (DEM global libre, sin clave, codificación terrarium) | «Obtener malla desde Google Earth» |
| `georef/tiles.py` + `tile_fetcher.py` | imagen satelital por teselas XYZ (Esri World Imagery, EOX Sentinel-2, OSM), caché en disco | «Importar imagen desde Google Earth» |
| `georef/geoimport.py` | KML / KMZ / GeoJSON → polilíneas (stdlib) | «Importar polígonos desde Google Earth» |
| `georef/points.py` | `parse_points_csv` (P,N,E,Z,D y dialectos de estación total) | importación de puntos |
| `georef/profile.py` | perfil longitudinal del terreno bajo una polilínea, con pendientes y CSV | perfil de terreno |
| `georef/surface.py` | plano de mejor ajuste y superficie drapeada sobre el DEM | plataformas (parcial) |

Verificado además que el **DEM Copernicus GLO-30** (30 m, el mismo orden de
precisión que las cotas de Google Earth) se descarga sin clave por HTTPS
desde el bucket público de AWS: la tesela de Arequipa
(`Copernicus_DSM_COG_10_S17_00_W072_00_DEM.tif`) responde `200 OK`, 40 MB.
Es una segunda fuente por si los Terrain Tiles cambian.

### 3.1 Mapa de factibilidad, capacidad por capacidad

Leyenda: 🟢 existe o se porta · 🟡 hay que escribirlo, es trabajo conocido ·
🔴 grande o fuera de rumbo. Esfuerzo: S = días, M = 1-2 semanas, L = más.

**Topografía básica**

| capacidad | estado | esfuerzo | notas |
|---|---|---|---|
| importar puntos CSV / estación total | 🟢 se porta (`points.py`) | S | ya previsto en la fase 7 del CLAUDE.md; entidades POINT + TEXT en capas |
| dibujar puntos por azimut, deflexión, intersección de rumbos | 🟡 | S | entrada por prompt, como las coordenadas polares que ya existen |
| anotar rumbo/distancia en líneas, datos de arcos | 🟡 | S | TEXT alineado al segmento; hay `tr()` y estilos |
| cuadro de construcción (rumbos, azimuts, ángulos, coordenadas, área) | 🟢 casi | S | `TABLE` existe (`core/tables.py` ya menciona «the topography plugin's coordinate chart») |
| subdivisión de polígono por área | 🟡 | S-M | bisección numérica sobre el polígono; útil para lotización |
| triangulación Delaunay con líneas límite | 🟡 | M | ver §3.2 (la única decisión de dependencia) |
| curvas de nivel desde la TIN, anotadas | 🟡 | S-M | marcha por triángulos, suavizado opcional; etiquetas sobre la curva |
| perfil de terreno sobre un eje | 🟢 se porta (`profile.py`) + TIN | S | de la TIN cuando hay levantamiento, del DEM cuando no |
| secciones transversales por estación | 🟡 | M | corte de la TIN por planos perpendiculares al eje |
| volúmenes corte/relleno por secciones (prismoidal) | 🟡 | S | fórmula conocida; el trabajo es la tabla y el dibujo |
| plataformas con taludes y línea cero, volumen exacto | 🟡 | M | intersección talud-terreno sobre la TIN; volumen TIN contra TIN |
| zonificación por pendientes | 🟡 | S | color por triángulo según pendiente |
| memorias descriptivas / técnicas, resumen de áreas | 🟡 | S-M | texto y CSV; el formato es lo que hay que acordar (Perú, no RAN) |
| retícula UTM con etiquetas | 🟡 | S | |

**«Google Earth»**

| capacidad | estado | esfuerzo | notas |
|---|---|---|---|
| cotas del terreno sobre una malla dentro de un polígono | 🟢 se porta (`dem.py`) | S | la misma clase de dato que Google Earth, sin Google Earth ni Windows |
| imagen satelital georreferenciada bajo el dibujo | 🟢 se porta (`tiles.py`) | M | IngeCAD ya dibuja IMAGE; se inserta como raster georreferenciado o como capa de fondo |
| importar KML/KMZ (polígonos y rutas) | 🟢 se porta (`geoimport.py`) | S | |
| exportar puntos y polígonos a KML/KMZ | 🟡 | S | XML a mano; se abre en Google Earth con doble clic |
| exportar captura del dibujo como superposición en Google Earth | 🟡 | S | `render_image` + KML GroundOverlay |
| conversión UTM ↔ geográficas, datum | 🟢 se porta (`datum.py`) | S | añadir PSAD56 → WGS84 (Molodensky) para planos antiguos del Perú |

**Redes** (un complemento propio, después de topografía)

| capacidad | estado | esfuerzo | notas |
|---|---|---|---|
| reconocer una red dibujada con líneas (nodos, tramos) | 🟡 | S | grafo a partir de LINE/LWPOLYLINE |
| agua potable: Hazen-Williams / Darcy, Hardy-Cross, balance en nodos | 🟡 | M | numérica sencilla; la norma es **RNE OS.050**, no CONAGUA |
| alcantarillado: Manning, tirante, velocidad, tensión tractiva | 🟡 | M | **RNE OS.070**; el editor gráfico de perfiles es lo más largo |
| anotar cotas en pozos y tramos, símbolos | 🟡 | S | bloques + TEXT |
| tabla de cálculo, exportar CSV/Excel | 🟡 | S | `TABLE` + CSV |
| pluvial ADS Mexicana | 🔴 no entra | — | catálogo de un fabricante mexicano |

**Carreteras** (el más grande; v0.7 o después)

| capacidad | estado | esfuerzo | notas |
|---|---|---|---|
| eje con curvas horizontales simples | 🟡 | M | |
| espirales, sobreelevación, sobreancho | 🔴 grande | L | norma peruana **DG-2018** (MTC), no SCT |
| curvas verticales por visibilidad | 🟡 | M | |
| curva masa, línea compensadora, sobreacarreos | 🟡 | M | sale de las secciones/volúmenes de topografía |
| exportación a Curva Masa SCT | 🔴 no entra | — | programa mexicano |

### 3.2 La única decisión técnica de peso: la triangulación

Todo lo demás es numpy y geometría plana. Una TIN de Delaunay de 5 000 a
50 000 puntos con líneas límite (breaklines) tiene tres caminos:

1. **`scipy.spatial.Delaunay`** (Qhull, BSD): rápida, probada, 30-40 MB
   más en el Flatpak/AppImage; se importa sólo cuando el complemento la
   usa. Las líneas límite se imponen después (Delaunay restringida por
   volteo de aristas), que es lo que hace la mayoría.
2. **Implementación propia** (Bowyer-Watson con numpy o barrido): sin
   dependencia, pero 1-2 semanas más y hay que probarla contra Qhull.
3. **Triangle** de Shewchuk: excelente y con restricciones nativas, pero su
   licencia no permite redistribución comercial: **descartado** para un
   GPL que se empaqueta.

Recomendación: **scipy, como dependencia del complemento**, medida en
tamaño y arranque antes de decidir si va en el paquete base o se instala al
activar el complemento. Es la misma regla de siempre: primero medir.

---

## 4. Recomendación: complemento incluido, no función del núcleo

**Complemento, y viene instalado.** La decisión del rumbo del 2026-08-12 se
confirma con el inventario: CivilCAD mismo es un complemento con módulos, y
sus 245 rutinas son casi todas de un oficio (topografía, redes, carreteras).
El núcleo de IngeCAD sigue siendo «el AutoCAD LT que no marea»; topografía
agrega **un menú** («Topografía») y una barra apagable, y el que sólo dibuja
no la ve nunca. Para el usuario no cambia nada: el complemento viene en el
mismo Flatpak, activado por defecto; «complemento» describe cómo está
armado por dentro, no algo que haya que descargar.

Por qué eso conviene, dicho en concreto:

- el contrato de complementos se diseña con este caso real (menú propio,
  comandos en el dispatcher, entidades normales del DXF, acciones headless),
  y después redes y carreteras entran por la misma puerta sin tocar el
  núcleo;
- el DWG que sale es **DWG normal**: puntos, textos, polilíneas 3D, tablas.
  CivilCAD hace lo mismo (sus triangulaciones son 3DFACE y sus curvas
  polilíneas), y por eso sus planos se abren en cualquier CAD; IngeCAD debe
  conservar esa propiedad, que además es la del round-trip conservador;
- scipy o cualquier dependencia pesada queda encapsulada en el complemento.

**Sobre Google Earth, la respuesta honesta:** lo que Marco valora de
CivilCAD («que trabaje con Google Earth») son cuatro cosas: ver la imagen
satelital bajo el plano, sacar cotas del terreno sin levantar, llevar
polígonos ida y vuelta, y mandar el plano a Google Earth para mostrarlo.
Las cuatro se pueden hacer **sin Google Earth instalado** y sin Windows,
con las fuentes libres que IngeTrazo ya usa; la precisión de las cotas es la
misma clase (DEM global de 30 m) que la que Google Earth interpola, y el
propio distribuidor de CivilCAD lo reconoce. Lo único que no se puede hacer
es lo que CivilCAD tampoco puede ya en Google Earth de 64 bits: hablarle al
programa de escritorio. La ida y vuelta con Google Earth queda por **KML/KMZ**,
que Google Earth abre con doble clic.

### 4.1 Orden propuesto

**v0.5 — Topografía (el diferencial civil).** Puntos (CSV, estación total,
por rumbo y distancia), anotación de rumbos y distancias, cuadro de
construcción y de datos técnicos, subdivisión de polígonos, TIN con líneas
límite, curvas de nivel anotadas, perfil de terreno, secciones y volúmenes
por estación, plataformas con taludes y línea cero, retícula UTM, memorias
básicas a CSV. Con el caso municipal completo como DoD (ya escrito en la
fase 7 del CLAUDE.md).

**v0.6 — Terreno y Google Earth.** Imagen satelital georreferenciada, cotas
del DEM sobre una malla, KML/KMZ ida y vuelta, exportación de captura como
superposición, conversión de datum. Casi todo portado de IngeTrazo.

**v0.7 — Redes.** Agua potable (OS.050) y alcantarillado (OS.070) con sus
tablas y perfiles; editor de perfiles de red.

**Después — Carreteras.** Eje, curvas verticales y curva masa primero;
espirales y peraltes por DG-2018 sólo si duele.

**Lo que no entra:** pluvial ADS, exportación a Curva Masa SCT, formato
RAN: son mexicanos. Sus equivalentes peruanos (COFOPRI/SUNARP para memorias
descriptivas, MTC para carreteras) se definen con Marco cuando toque, con un
plano real de cada trámite.

---

## 5. Fuentes

- https://civilcad.com.mx/ (portada, plataformas y módulos)
- https://civilcad.com.mx/rutinas/ (listado de las 245 rutinas)
- https://civilcad.com.mx/modulo-topografico-basico/
- https://civilcad.com.mx/modulo/modulo-interfase-con-google-earth/
- https://civilcad.com.mx/modulo/modulo-redes-de-agua-potable/
- https://civilcad.com.mx/modulo/modulo-redes-de-alcantarillado/
- https://civilcad.com.mx/modulo/modulo-redes-de-alcantarillado-pluvial-ads/
- https://civilcad.com.mx/modulo/modulo-carreteras-sct/
- https://civilcad.com.mx/loginwp/wp-content/uploads/2026/01/CivilCAD-Folleto_0126.pdf (folleto 2025.1: rutinas por módulo, requisitos, precios)
- https://softwaredeingenieria.es/civilcad/modulo-civilcad-de-interfaz-con-google-earth/ (detalle del módulo Google Earth y la advertencia de precisión)
- https://softwaredeingenieria.es/civilcad/requerimientos-del-sistema-para-usar-cad-earth/ (Google Earth Pro 7.3 de 64 bits sin COM; alternativa Cesium)
- https://registry.opendata.aws/copernicus-dem/ y https://copernicus-dem-30m.s3.amazonaws.com/readme.html (DEM libre sin clave)
- https://registry.opendata.aws/terrain-tiles/ (la fuente de cotas que IngeTrazo ya usa)
