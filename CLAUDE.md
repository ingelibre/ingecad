# IngeCAD — CAD 2D libre estilo AutoCAD clásico

**Autor:** Marco Sumari Tellez · **Licencia:** GPL-3.0-or-later · **Repo destino:** `github.com/ingelibre/ingecad`
**Hermanos:** [IngeTrazo](../ingetrazo/) (modelador 3D/BIM) · [IngePresupuestos](../ingepresupuestos-pyside6/) (presupuestos)

> Plan fundacional definido el 2026-07-16 (conversación estratégica completa en memoria de Claude: `[[project-ingecad-nuevo-hermano-2d]]`). Este archivo guarda el **rumbo** (visión, principios, fases + DoD); el registro de lo hecho vive en los commits de git. No duplicar acá lo que git ya registra.

---

## 🧭 Visión de producto

**Qué es:** el "AutoCAD LT libre" para Linux — visor/editor 2D de DWG/DXF para el ingeniero que viene de AutoCAD: dibujo rápido con comandos de teclado idénticos a AutoCAD, interfaz clásica pre-ribbon, y apertura **fiel** de los DWG que mandan los colegas. Con capacidades de elevación para el oficio civil (puntos topográficos con cota, terrenos con pendiente, carreteras) — datos de elevación, NO modelado 3D.

**Qué NO es:** no es un clon de AutoCAD feature-por-feature (esa es la receta para nunca shippear — lección de IngeTrazo). AutoCAD tiene cientos de funciones que ni Marco usa. El scope es SU flujo real: **línea, círculo, polilínea, polígono, bloques, capas, hatch, trim, offset, extend, move/copy/rotate, zoom, capas, puntos topográficos, área, imprimir a escala.** Nada más hasta que duela.

**El filtro maestro (heredado del ecosistema):** *"¿le sirve al ingeniero que abre el plano de un colega y dibuja rápido con el teclado?"* Si una feature no pasa ese filtro, no entra.

**La tesis de adopción:** la migración desde AutoCAD debe ser **cero fricción de memoria muscular** — mismos aliases (`M`+Enter = MOVE), misma command line, misma selección ventana/crossing, mismos osnaps. El usuario tipea lo de siempre y funciona.

**Reparto con IngeTrazo (no competir contra el hermano):** IngeCAD = el plano 2D que se firma e imprime (lindero, cuadro de coordenadas, planta). IngeTrazo = el 3D (terreno, modelo, BIM → metrado → IngePresupuestos). Mismo CSV topográfico entra a ambos. Puente entre ellos: DXF.

---

## 📐 Principios arquitectónicos (NO negociables)

1. **El documento ezdxf ES el modelo.** No inventar un modelo de datos propio: se editan las entidades ezdxf directamente (envueltas en Commands) y se guarda con ezdxf. Esto garantiza la propiedad más valiosa del producto: **round-trip conservador** — todo lo que IngeCAD no entiende (proxies de Civil 3D, XDATA, diccionarios, 3DSOLID) se preserva **intacto** al reescribir. "Le devolví el plano sano al colega" es la promesa central.
2. **DWG jamás se parsea dentro del app.** Dos satélites como procesos externos (patrón skp2dae de IngeTrazo): **LibreDWG** (GPL-3, embebible y EMBEBIDO — lectura hasta r2018 de fábrica, escritura r2000) y **ODA File Converter** (freeware propietario, instalación opcional de un clic, NUNCA bundlear — da export r2013/r2018). El usuario abre `.dwg` con doble clic y nunca ve el DXF intermedio.
3. **Coordenadas verdaderas float64 en el modelo; float32 solo en el render.** Los planos reales vienen en UTM (~500 000 Este). DXF/ezdxf guardan doubles — el archivo nunca pierde precisión. El viewport resta un **origen de vista** (centro del dibujo) antes de subir a GPU y lo suma al leer el mouse. El gotcha ya se sufrió en IngeTrazo (`SceneDatum`); acá el fix vive solo en el render.
4. **Toda mutación pasa por Command** (undo/redo exacto) y **todo comando es una acción headless** (`actions.move(...)`, no lógica pegada al evento de teclado/mouse). Es el invariante AI-native del ecosistema, y de paso da macros/scripts gratis — a los usuarios de AutoCAD (LISP) les importa.
5. **2D con Z latente.** DXF es 3D nativo: toda entidad tiene Z y OCS (que un visor correcto debe manejar igual — círculos con extrusión invertida existen en planos reales). El modelo conserva Z siempre; la cámara es ortográfica en planta. Agregar vista isométrica después = solo display (la `OrbitCamera` de IngeTrazo está a un copy de distancia). **3DSOLID (ACIS) jamás se interpreta** — se preserva intacto en el round-trip.
6. **Linux/Wayland first.** Heredar los gotchas resueltos de IngeTrazo: `glClear` explícito en `paintGL`, FBO propio si hace falta, DPR físico vs lógico, re-establecer estado GL tras QPainter, MSAA en el FBO de escena. Windows después, con el pipeline CI ya probado (spec PyInstaller + Inno) — pero ninguna decisión puede ROMPER Windows, solo diferirlo.
7. **Interfaz clásica pre-ribbon, para siempre.** Barra de menús (Archivo/Edición/Ver/Insertar/Formato/Herramientas/Dibujo/Acotar/Modificar) + toolbars acoplables (Draw a la izquierda, Modify a la derecha) + **ventana de comandos abajo** (historial + prompt) + status bar con toggles (FORZC/REJILLA/ORTO/POLAR/REFENT). Fondo de modelo oscuro por defecto. El ribbon no existe ni existirá.
8. **Idioma:** código, comentarios, docstrings y commits en **inglés** (contributors); UI bilingüe con el motor `tr()` + `es.json` portado de IngeTrazo (`core/i18n.py`). Los nombres de comando aceptan el inglés de AutoCAD (`LINE`, `TRIM`) — es lo que la memoria muscular del usuario ya sabe — y los menús se traducen.

---

## 🛠 Stack

| Capa | Elección |
|---|---|
| Lenguaje | Python 3.12 (versión de referencia CI, igual que IngeTrazo) |
| UI | PySide6 (Qt 6) |
| Render | QOpenGLWidget + VBOs batcheados por capa/color (patrón IngeTrazo, versión 2D) |
| Kernel de documento | **ezdxf** (MIT) — parsing, modelo, escritura DXF |
| Motor de "regen" | **`ezdxf.addons.drawing`** frontend (resuelve bloques/MTEXT/linetypes/hatches/cotas) → backend GL propio que emite arrays de vértices |
| DWG | LibreDWG (`dwg2dxf`/`dxf2dwg`, embebido) + ODA File Converter (satélite opcional) |
| Math/lotes | NumPy |
| Tests | pytest + banco de DWG reales |

Sin deps pesadas nuevas. Nada de OpenCascade, nada de kernels BRep.

---

## 📁 Layout del repo (espejo de IngeTrazo)

```
ingecad/
├── main.py                    ← entry point Qt (abre argv[1] — asociación .dwg/.dxf)
├── CLAUDE.md                  ← este archivo
├── LICENSE (GPL-3) / README.md / AUTHORS / CONTRIBUTING.md
├── core/
│   ├── document.py            ← wrapper fino del ezdxf doc + versioning + dirty
│   ├── actions.py             ← capa de acciones headless (move, trim, offset…)
│   ├── commands.py            ← Command ABC + History (portado de IngeTrazo)
│   ├── aliases.py             ← tabla de aliases AutoCAD (compatible acad.pgp)
│   ├── snap.py                ← osnaps (END/MID/CEN/NOD/INT/PER/TAN/NEA) + polar/orto
│   ├── i18n.py                ← portado de IngeTrazo
│   └── geo.py                 ← puntos topográficos, área, cuadro de coordenadas, perfil
├── views/
│   ├── main_window.py         ← menús + toolbars clásicas + status bar
│   ├── viewport.py            ← canvas GL 2D (pan/zoom, origen de vista, pick)
│   ├── command_line.py        ← ventana de comandos (prompt + historial + autocompletado)
│   └── layers_panel.py        ← administrador de capas
├── render/
│   ├── backend.py             ← backend GL para ezdxf.addons.drawing (emite vértices)
│   └── batches.py             ← VBOs por capa/color, culling por rect de vista
├── formats/
│   ├── dwg_bridge.py          ← satélites LibreDWG / ODA (detección, conversión, instalador)
│   └── pdf_out.py             ← imprimir/PDF a escala
├── tools/                     ← tools interactivas (line, circle, trim…) sobre actions
├── resources/ (shaders, iconos, linetypes, patrones de hatch)
├── i18n/ (en.json identidad, es.json)
└── tests/
```

---

## 🥇 Regla de oro (idéntica a IngeTrazo, no negociable)

Una fase NO está terminada hasta cumplir las 3: **(1)** su DoD pasa, **(2)** está commiteada y la app arranca sin regresiones, **(3)** cero "lo dejo para después" dentro de la fase. No se abre la siguiente hasta esas tres.

**Banco de pruebas vivo (el "plano del colega" — equivalente a la casita de IngeTrazo):** coleccionar DWG reales que mandan los colegas (con permiso, sin trackear al repo público) y arrancar cada sesión preguntando *"¿qué parte del plano del colega todavía se ve/edita mal?"*. Los gaps aparecen solos dogfoodeando, no desde la lista abstracta.

---

## 🚧 Fases hacia v0.1

**FASE 0 — Esqueleto** *(≈1 sesión)*
Repo + GPL-3 + layout + venv + ventana con viewport GL vacío: pan (botón medio), zoom a la rueda (al cursor), fondo oscuro, ejes/UCS icon. CI mínima (pytest).
- **DoD:** arranca en Wayland nativo sin glitches; pan/zoom suave; `pytest` verde en CI.

**FASE 1 — Visor fiel (el go/no-go del proyecto)** *(la incógnita — atacarla primero)*
`ezdxf.addons.drawing` frontend → backend GL propio: VBOs por capa/color, culling por rect de vista, origen de vista float64→float32. Render fiel de: LINE/PLINE/CIRCLE/ARC/ELLIPSE, bloques (INSERT anidados), TEXT/MTEXT con formato, linetypes a escala, HATCH (patrones + solid), cotas (como las guarda el archivo), colores ByLayer/ByBlock, capas on/off, OCS. Zoom extents / window / previo.
- 📌 El pick va detrás de una abstracción (índice NumPy después, como IngeTrazo — no construirlo aún).
- **DoD:** 10 DWG reales de colegas (convertidos con `dwg2dxf` a mano por ahora) se ven **idénticos** a AutoCAD/DWG FastView lado a lado; un plano de ~200k entidades hace pan/zoom fluido en Wayland. Si esto pasa, el proyecto es viable; todo lo demás es trabajo conocido.

**FASE 2 — DWG de fábrica** *(cierra el caso de uso #1: "me mandan un DWG")*
`formats/dwg_bridge.py`: LibreDWG embebido (binario `dwg2dxf` empaquetado — GPL con GPL, sin conflicto) → abrir `.dwg` transparente (conversión a temp, el usuario nunca ve el DXF). Guardar como `.dwg` r2000 vía `dxf2dwg`. Detector + **instalador de un clic** del ODA File Converter (patrón skp2dae validado) → export r2013/r2018. Asociación de archivos `.dwg`/`.dxf` en el `.desktop`.
- **DoD:** doble clic en un `.dwg` → abre; "Guardar como DWG" → el colega lo abre en AutoCAD (aviso TrustedDWG documentado en README como esperado e inofensivo). Rutas con acentos (gotcha ya cazado en skp2dae).

**FASE 3 — Command line + aliases AutoCAD** *(la tesis de migración)*
`views/command_line.py` (prompt abajo, historial, autocompletado) + `core/aliases.py` con los aliases exactos de `acad.pgp`: `L`=LINE, `C`=CIRCLE, `A`=ARC, `PL`=PLINE, `REC`=RECTANG, `POL`=POLYGON, `E`=ERASE, `M`=MOVE, `CO`/`CP`=COPY, `RO`=ROTATE, `O`=OFFSET, `TR`=TRIM, `EX`=EXTEND, `MI`=MIRROR, `SC`=SCALE, `B`=BLOCK, `I`=INSERT, `H`=HATCH, `LA`=LAYER, `Z`=ZOOM (con `Z`→`E`/`W`/`P`), `U`, `DI`=DIST, `AA`=AREA, `LI`=LIST, `X`=EXPLODE, `F`=FILLET. Semántica AutoCAD: Espacio/Enter ejecutan, Enter en vacío repite el último comando, Esc cancela, tipear con selección previa opera sobre ella (noun-verb) o pide selección (verb-noun). Soporte de archivo PGP del usuario para aliases custom. Todo comando despacha a `core/actions.py` (headless).
- **DoD:** un usuario de AutoCAD ejecuta `L`, `C`, `Z`+`E`, `E` sin leer documentación y se siente en casa. Tests headless de la tabla de aliases y del parser del prompt.

**FASE 4 — Dibujo con snap (el "feel")**
Osnaps AutoCAD con sus marcadores AutoSnap (cuadrado END, triángulo MID, círculo CEN, X NOD, cruz INT, PER, TAN, NEA) + toggle F3 + ORTO (F8) + POLAR (F10) + entrada por coordenadas: absolutas `10,5`, relativas `@10,5`, polares `@10<45`, y distancia directa (apuntar + tipear número). Tools: LINE, CIRCLE (centro-radio/2P/3P), ARC (3P), PLINE, RECTANG, POLYGON. Undo/redo integrado.
- Reusar la maquinaria conceptual del snap de IngeTrazo (threshold px, prioridades) simplificada a 2D.
- **DoD:** dibujar una planta simple solo con teclado + mouse, snaps exactos, coordenadas por prompt; undo limpio de cada paso.

**FASE 5 — Edición (el scope del usuario, completo)**
ERASE, MOVE, COPY (múltiple), ROTATE (con referencia), SCALE, MIRROR, OFFSET (distancia + través), **TRIM/EXTEND** (con selección de bordes y modo rápido Shift-alterna como AutoCAD moderno), FILLET (radio 0 = esquina). Selección: click, **ventana (izq→der, azul) / crossing (der→izq, verde)** con los colores de AutoCAD, Shift quita de la selección, grips básicos (mover vértice/estirar) si el costo es razonable — si no, a v0.2.
- **DoD:** flujo completo de edición de un plano real sin tocar menús; TRIM/EXTEND se sienten como AutoCAD (el listón más alto de la fase).

**FASE 6 — Capas, propiedades, bloques y hatch**
Panel de capas (`LA`): crear/renombrar, color, linetype, on/off/freeze/lock, capa actual. Propiedades de entidad (panel lateral estilo bandeja IngeTrazo): color/capa/linetype ByLayer. Bloques: `I` (insertar con escala/rotación), `B` (crear desde selección), explode. `H`: SOLID + patrones ANSI básicos + escala/ángulo.
- **DoD:** el scope declarado del usuario ("bloques, capas, hatch") operativo end-to-end y round-trip al DWG.

**FASE 7 — Topografía + elevación (el diferencial civil)** ⭐
`core/geo.py`: **import CSV de puntos** (reusar/portar `parse_points_csv` de IngeTrazo — P,N,E,Z,desc, dialectos de estación total) → entidades `POINT` en (E,N,Z) + `TEXT` (número/cota/desc) en capas `PUNTOS`/`COTAS`/`DESC`; snap NOD cae bit-exacto. `AA` sobre polilínea cerrada. **Cuadro de datos técnicos automático** (seleccionar polilínea → tabla de vértices con Este/Norte, lados, distancias, rumbos/azimuts, área y perímetro, como entidades en el plano — lo que en AutoCAD todos arman a mano o con LISPs). **Perfil de elevación** de una polilínea cuyos vértices tienen Z (carreteras/pendientes): panel inferior estación/cota con pendientes, export CSV/PNG (portar el concepto de `ProfileDock` de IngeTrazo).
- **DoD:** caso municipal completo sin AutoCAD: CSV del topógrafo → plano de lindero snapeado a los puntos → cuadro de coordenadas + área → perfil del eje con pendientes → DWG al colega.

**FASE 8 — Salida** 🏁 *(cierra v0.1)*
Imprimir / **exportar PDF a escala** (1:100, 1:500…, tamaño de papel, área por ventana), export PNG hi-res (patrón `render_image` de IngeTrazo). Layouts/espacio papel completo se difiere a v0.2 — escala directa desde modelo cubre el 80%.
- **DoD:** un plano imprimible a escala exacta verificable con regla. **= v0.1 usable real.**

**Después de v0.1 (candidatos v0.2, no abrir antes):** grips completos, DIMENSION propias (crear cotas), espacio papel/layouts, MATCHPROP, PURGE, arrays, empaquetado Windows (pipeline IngeTrazo), AppImage/Flatpak, más patrones de hatch, LISP-like scripting sobre `actions`.

---

## 🔩 Track L — LibreDWG (paralelo, NO bloquea ninguna fase)

Objetivo de largo plazo: que el ecosistema libre no dependa del conversor de ODA. Rampa por confianza creciente:

1. **L1 — Usar y reportar:** IngeCAD usa LibreDWG desde F2; cada DWG real que falle → minimizar + issue upstream con repro.
2. **L2 — Harness de fuzzing round-trip:** generar miles de DXF con ezdxf → `dxf2dwg` → `dwg2dxf` → comparar entidad a entidad (la metodología del fuzz bench de IngeTrazo aplicada a otro dominio; es lo que LibreDWG no tiene y el aporte de más valor por esfuerzo).
3. **L3 — Patches quirúrgicos** asistidos por IA sobre los fallos que L1/L2 destapen.
4. **L4 — El writer r2013/r2018** (el hueco histórico, spec ODA pública como guía). Aporte mayor; solo encararlo cuando L1-L3 hayan construido confianza con el mantenedor.

Si upstream tarda o rechaza: **fork amistoso** (`tuxiasumari/libredwg`) — IngeCAD empaqueta el fork, los PRs se siguen ofreciendo upstream, divergencia mínima.

### ✅ Balance de la primera tanda (2026-07-16 → 2026-08-04)

**Los 12 PRs (#1311–#1322) están TODOS en el master de upstream.** Verificado: nuestro
`af364d4c` es ancestro de `origin/master`, y los siete commits del 2026-07-26 firmados por
Reini Urban corresponden uno a uno a nuestros temas. Cuatro se fusionaron como PR
(#1311, #1313, #1315, #1318); el resto los **reimplementó él a partir de nuestra
descripción**. Consecuencia práctica: **el stack de 29 parches de `tools/libredwg-patches/`
quedó obsoleto** — reconstruir `vendor/libredwg` desde un release reciente en vez de desde
`0.14 + parches`.

⚠️ **La pregunta del CLA está respondida: SÍ hace falta.** Textual del mantenedor al cerrar
#1317 y #1320: *«Excellent. But too big. Needs a CLA»* / *«Fixed independently by myself,
thanks to your description. Dont want to wait for the CLA»*. O sea: **los parches chicos
entran como PR; los grandes NO se fusionan sin cesión de copyright a la FSF** — como mucho
los reescribe el mantenedor y el crédito queda en el agradecimiento. Antes de encarar **L4
(el writer r2013/r2018)**, que es por definición un aporte grande, hay que decidir si se
firma el CLA de la FSF; si no, ese trabajo solo puede vivir en el fork.

Los cuatro PRs que seguían abiertos sin motivo (#1312, #1314, #1319, #1321) se **cerraron
el 2026-08-04** apuntando al commit que los reemplaza. De la primera tanda no queda ninguno
abierto.

### ✅ Segunda tanda (2026-08-06) — detalle en `docs/bugs-libredwg-2026-08-06.md`

Los 30 fallos del barrido quedaron clasificados y luego **arreglados**: **13 PRs**
(#1352, #1353, #1358, #1359, #1360, #1362, #1363, #1364, #1365, #1366, #1367, #1368,
#1369), **1 issue vivo sin parche** (#1356),
**1 retirado a propósito** (#1354, correcto pero de bajo valor) y **5 planos que no eran
bugs** (2 bloqueados por objetos propietarios de Civil 3D —que BricsCAD tampoco abre—,
1 archivo dañado, 2 dibujos vacíos de verdad). El #1358 cierra además el
[#1294](https://github.com/LibreDWG/libredwg/issues/1294), issue de otro usuario parado
desde junio de 2026 por falta de reproductor compartible; y el #1364 cierra el
[#767](https://github.com/LibreDWG/libredwg/issues/767), **abierto desde junio de 2023** —
Reini Urban había esbozado el rumbo ahí y nadie lo había tomado.

**Los 9 planos propios que fallaban abren ahora exactos contra ODA**, `sedapar` incluido
(10 847 = 10 847). No queda ningún plano propio que LibreDWG lea peor que ODA. El último,
el #1363, era el gordo: `read_data_section` copiaba en crudo las páginas r2007 **sin
comprimir** sin deshacer su codificación Reed-Solomon, y 136 de las 181 páginas de objetos
de `sedapar` están así. Cierra también el #1361.

**El formato no es el problema:** R2018 falla en el 1,2% (7 de 606 planos), R2013 en el 0,2%.
Los puntos flojos son **R2007 (8,3%) y R2000 (11,3%)**.

**Lección de método, más valiosa que los bugs:** comparar siempre contra **ODA File
Converter** y contra **BricsCAD** antes de reportar. En este barrido eso descartó 5 de 14
«bugs» y evitó dos falsos positivos míos. Y medir con el **mismo criterio en los dos lados**
(entidades del modelspace del DXF de cada conversor); mezclar medidas distintas produjo dos
cifras erróneas que hubo que retractar.

⚠️ **`vendor/libredwg` YA NO es stock.** Se compila de `0.14.8556` **más los 13 parches**,
todos abiertos como PR upstream; cada uno desaparece en cuanto se fusione y tomemos un
release nuevo. El árbol de build lleva un `NO-ES-STOCK-LEEME.txt` que lo advierte, y el
detalle vive en `tools/libredwg-patches/README.md`. IngeCAD lleva además un saneado del DXF
recibido (`_dedupe_handles`), que se irá cuando #1356 aterrice.

**Seis de los 7 parches comparten un patrón**: el código ya documentaba la conducta correcta
y no la ejecutaba (tres líneas hermanas ya normalizaban el flag; el `else` de 8 líneas abajo
ya calculaba el tamaño bueno; el `bit_read_UMC` fallido ya se detectaba y luego se ignoraba;
el comentario ya prometía ±1000; `read_data_page` ya separaba RS de compresión y su único
llamador las confundía). Los **dos** arreglos que intenté deducir del formato —los dos para
el #1355— fallaron. Regla de oro: **buscar la contradicción interna del código antes de
inventar semántica del formato.**

**El séptimo (#1363) salió por otra vía y vale como segundo método**: ahí el código no se
contradecía, el `TODO` admitía la duda y nada más. Salió de **medir y partir la población** —
separar los objetos por la clase de página en la que caen y ver 0,0 % de fallo contra 96,6 %—
con la entropía (7,87 contra 6,39 bits/byte) señalando «paridad intercalada», no «formato mal
leído». Cuando el código no delata la causa, la delata la correlación; lo difícil es tener la
variable correcta para cruzar.

**Y una regla de medición, que costó decirle dos veces a Marco que un plano abría cuando no:**
un arreglo no está terminado hasta que está en `vendor/` y medido con `load_dwg()`. Medir en
`externos/build-libredwg/` es trabajo en curso, no resultado — son binarios distintos.

**El frente ahora son los issues de otros**, y ahí van **8 de los 13 parches**: el #1294
(jun 2026), el #767 (jun **2023**), y el #523 + #1012 con el PR #1365. El #523 llevaba
**cuatro años** abierto con cuatro personas reportándolo, y el reproductor era el propio
archivo de prueba de LibreDWG. Método que funcionó: buscar issues cuyo síntoma sea primo de
uno ya resuelto, y no dar por sentado que el parche propio los cubre —el #1362 NO arreglaba
el #767, aunque el mensaje de error fuera idéntico.

⚠️ **Y la lección de medición, que vale para todo el proyecto: medir de punta a punta, y
con un criterio que no dependa de mi interpretación.** Mi primer parche ahí era demostrablemente correcto (una línea) y
mi analizador de coordenadas decía «7 de 40 mejoran contra 1». Al **renderizar a PNG y contar
píxeles con tinta**, dos planos habían pasado de 134 píxeles a 0. La medida indirecta y la
real se contradijeron y ganó la real. En el #1021 casi reporté 15 nombres «corruptos» que
estaban perfectos, porque los leí en latin-1 cuando eran UTF-8; el criterio bueno era
`iconv -f UTF-8`, que no opina. Es la misma familia que la regla de `vendor/`: el resultado
es lo que ve el usuario, no lo que dice el paso intermedio ni cómo yo decodifico los bytes.

**Y verificar issues viejos vale tanto como arreglarlos.** Cuatro de los que abrí resultaron
ya resueltos (#327, #426, #663, #973); comentar con números y proponer cerrar le ahorra
tiempo a todo el que los lea después. En los cuatro medí **campo por campo contra ODA**, no
solo los conteos — y en el #663 eso evitó que reportara como defecto los handles nulos del
DIMSTYLE, porque ODA escribe más que LibreDWG.

**Y el criterio de regresión hay que elegirlo según el parche.** Para el #1369 (marcas de
tiempo) comparar los DXF byte a byte no sirve: cambian los 151 planos que tienen fecha. El
criterio bueno fue «¿alguna línea NO numérica cambia?» (ninguna) más «¿cuántas líneas cambia
como máximo un archivo?» (12 = 6 variables × 2 lados) y «¿todas van precedidas de un `$TD`?»
(sí). Un «146 idénticos» no siempre es la prueba correcta.

**Siguiente objetivo:** ya no hay bug de lectura propio pendiente. Queda el #1356 (handles
duplicados en el DXF emitido, 1150 en `sedapar`), que IngeCAD sortea con `_dedupe_handles`, y
dos cosas propias: que `load_dwg()` avise en vez de mostrar lienzo blanco cuando el DXF llega
truncado, y que LibreDWG descarta `ACAD_PROXY_ENTITY` por completo (explica 3 de las 5
pérdidas parciales silenciosas). Con la lectura resuelta, el siguiente frente real de Track L
es la **escritura** (L4: r2013/r2018) — y eso exige decidir el CLA.

### ✅ Tercera tanda (2026-08-09) — la ESCRITURA, cazada por fuzzing (L2 write)

El barrido de lectura estaba agotado, así que se construyó el complemento que faltaba:
**`tools/dwg_fuzz.py`**, el harness round-trip del write path (ezdxf → `dxf2dwg` →
`dwg2dxf` → comparar el modelspace huella a huella). Cada dibujo deriva de su semilla
por un *spec* JSON, así que un fallo se reproduce desde el entero y se reduce quitando
entradas del spec sin perturbar al resto. 2000 semillas corren en 15 s.

**Primera campaña: el 94 % de los dibujos NO sobrevivía el viaje.** De ahí salieron
**8 bugs de raíz distinta, los 8 con parche y PR: #1370–#1377**, todos verificados
también contra el master de upstream (idéntica distribución de fallos que el vendor):

- **#1370 (el grave):** `in_postprocess_SEQEND` re-envolvía un handle *relativo* como
  absoluto → `INSERT.first_attrib = 2` (¡la tabla LTYPE!) → **AutoCAD/ODA rechazaban
  entero cualquier DWG nuestro con bloques con atributos**. La promesa central del
  producto («le devolví el plano sano al colega») estaba rota para ese caso y nadie lo
  sabía porque LibreDWG sí leía su propio archivo.
- **#1371:** los subentes (ATTRIB/VERTEX/SEQEND) se archivaban en la cadena del bloque
  con entmode 2; AutoCAD los guarda con entmode 0, owner = entidad padre y fuera de la
  cadena. ODA descartaba los ATTRIBs y el último vértice de cada polilínea.
- **#1372:** `out_dxf` avisaba «stale subentity»… y lo escribía igual → vértices
  duplicados al re-exportar. (El caso SEQEND de arriba ya hacía `return 0`.)
- **#1373:** un BLOCK_HEADER sin BLOCK abortaba TODO el export DXF en r2004+ (por eso
  el writer r2004 «perdía» el 100 % de los dibujos); r2000 sobrevivía el mismo dibujo.
- **#1374:** SPLINE de solo fit-points → scenario 1 vacío. La línea correcta estaba
  **comentada** en el handler del 74.
- **#1375:** DXF r2007+ es UTF-8, pero `dynapi_set_helper` hace memcpy crudo a campos
  codepage → mojibake en todo string no-ASCII (`CAÑERÍA` → `CAÃ‘ERÃ...`).
- **#1376:** al bajar a r2000, `bit_downconvert_CMC` pisaba el índice ACI válido con una
  búsqueda inversa por RGB que devuelve el primer match — y la paleta tiene RGB
  repetidos: **170→5, 10→1: re-coloreo silencioso**.
- **#1377:** el handler 420 dejaba método 0 (inválido) y nunca ponía el flag 0x80 que
  el encoding r2004+ exige para escribir el rgb → todo true color perdido.

**Con los 8: la campaña pasa de 5,6 % OK a 90 % — r2000 y r2004 al 100 %** (lo restante
es el writer r14, pre-R13, otra historia). Verificación: `make check` upstream 254/254;
bench de los 1657 DWG reales contra la base stock: **0 empeoran**, 10 mejoran (+118 788
entidades, las ganancias ya conocidas de la 2ª tanda); ODA lee ahora completo lo que
escribimos (ATTRIB=1, VERTEX=3/3, sin errores); cada parche compila aislado en árbol
limpio.

**Método nuevo que quedó validado — la referencia ODA campo a campo:** cuando el formato
no está documentado, convertir el MISMO DXF con ODA a DWG, leer ambos con `dwgread -O
json` y comparar entidad a entidad. Así salieron entmode/owner/cadena correctos (#1371)
sin especular; mi primer intento (heredar entmode 2 del padre, «plausible») era
exactamente lo contrario de lo que AutoCAD hace, y solo la referencia lo delató.
Y la de siempre, tres veces más: la contradicción interna primero — la línea comentada
(#1374), el «stale» que avisa y escribe igual (#1372), el `dwg_dup_handleref` de al lado
que ya usaba `absolute_ref` (#1370).

⚠️ **Pendiente decidido a propósito:** `vendor/` sigue en `0.14.8556 + 13`; estos 8 NO
están en vendor todavía. El #1370/#1371 afectan el «Guardar como DWG» de IngeCAD hoy
(un plano del colega con bloques con atributos se re-guarda ilegible para AutoCAD), así
que la próxima re-vendorización debería ir a base `0.14.8566` (ya trae 5 de los 13) +
los 8 no fusionados de la 2ª tanda + estos 8. El harness quedó commiteado
(`tools/dwg_fuzz.py`); la cola conocida: writer r14 (~200/2000 fallos, nicho) y el
duplicado huérfano de `*Model_Space` que `in_dxf` deja al importar (hoy solo inocuo
gracias a #1373).

---

## 🧪 Tests (desde el día uno)

- **Round-trip conservador (el invariante sagrado):** abrir → tocar UNA entidad → guardar → re-abrir → todo lo NO tocado es byte/valor-idéntico (incl. entidades desconocidas y XDATA). Corre sobre el banco de DWG reales.
- **Fidelidad de render:** para cada archivo del banco, snapshot del render rasterizado vs referencia aprobada (regresión visual).
- **Aliases/acciones headless:** cada comando testeable sin GUI (la capa `actions` lo garantiza).
- **Fuzz de comandos** (más adelante, patrón IngeTrazo): secuencias aleatorias seeded de dibujar/editar/undo con invariantes (documento válido, undo→redo reproduce fingerprint).

---

## ⚠️ Gotchas heredados de IngeTrazo (releer antes de tocar el render)

- Wayland exige `glClear` explícito en `paintGL`; QPainter contamina el estado GL (re-establecer todo por frame); FBO propio si el depth/formato miente; tamaños en píxeles físicos (`devicePixelRatioF`); MSAA en el FBO de escena, no en el widget; `QMatrix4x4 * QVector4D` no bindea (usar `.map()`); Wayland puede intercalar frames viejos bajo ráfagas (cosmético, escape `QT_QPA_PLATFORM=xcb`).
- Satélites: Wine re-encodea argv (rutas con acentos → ruta temp ASCII) — aplica si algún satélite fuera .exe; LibreDWG es nativo Linux así que este gotcha probablemente no aplica, pero el patrón de sanitización ya existe en IngeTrazo.
- QSettings necesita `setOrganizationName/setApplicationName` fijados para persistir donde corresponde.
- **Íconos de tipo de archivo (.dwg/.dxf) — la búsqueda de íconos es TEMA-MAYOR (gotcha caro, 2026-07-20).** Instalar el ícono de mimetype SOLO en `hicolor` NO alcanza cuando el tipo tiene un genérico que el tema activo provee: freedesktop recorre **tema por tema** (Yaru antes que hicolor) y prueba TODOS los nombres de fallback dentro de cada tema. Como `.dwg`/`.dxf` son `image/vnd.*`, su fallback incluye `image-x-generic`, que **Yaru sí tiene** → lo elige antes de llegar a nuestro `image-vnd.dwg` en hicolor (último). Fix: `install-desktop.sh` instala los PNGs de mimetype en el **tema activo (`gsettings ... icon-theme`) y sus padres** (`Inherits` del `index.theme`), no solo en hicolor. Además: MIME propio con `weight/priority="90"` para ganarle a otro paquete CAD que reclame la extensión/magic (un BricsCAD instalado toma `*.dwg` + magic `AC10` con prioridad 80). Diagnóstico definitivo: `Gtk.IconTheme.lookup_by_gicon` con GTK **4.0** (Nautilus 50 es GTK4) sobre el GIcon real del archivo — dice exactamente qué PNG se elige. Y limpiar `~/.cache/thumbnails` + `nautilus -q` porque `image/*` intenta miniatura y cachea la fallida.

---

## 🌐 Sitio web — ingecad.org (2026-08-07)

**Publicado**: https://ingecad.org (y `www`), Cloudflare Worker con assets estáticos.
Repo **aparte**: `~/Proyectos/ingecad/web` → github.com/ingelibre/ingecad-web (público), y
`web/` está en el `.gitignore` de este repo — la misma separación que usan
`ingelibre/ingetrazo-web` y `ingelibre/ingepresupuestos-web`: un cambio de copy no dispara el
CI del producto ni al revés. **El `git push` NO publica**: publica `npx wrangler deploy`.

Las convenciones (paleta, capturas, qué se promete) viven en `web/CLAUDE.md`. Tres cosas que
conviene no re-descubrir:

- **Acento del producto: Lime `#479B1B`**, el eje Y del propio icono. Azul = IngeTrazo,
  naranja = IngePresupuestos, y esos dos solo aparecen en la sección puente.
- **Cómo se capturan las pantallas**: bajo Wayland `QScreen.grabWindow()` devuelve **negro**
  (un cliente X11 no puede leer la pantalla) y el `import` de ImageMagick tampoco sirve. Lo
  que funciona es `win.grab()` con `DISPLAY=:0 QT_QPA_PLATFORM=xcb`, que trae el árbol de
  widgets **con el FBO del visor dentro**, a 2×. Para escribir comandos en la captura hay que
  apuntar a `win.command_line.input`, no al contenedor.
- **El sitio solo afirma lo que la app hace hoy**, y la sección «Status» del `README.md` es la
  fuente de verdad del copy. Hay un FAQ que dice explícitamente que la topografía es v0.2.

## 🗓 Sesión 2026-08-07 — v0.1.3 (borrar borra también en pantalla)

Icono nuevo (el lápiz fuera, cursor de mira) y **un bug propio que Marco cazó
dogfoodeando**: cortar una selección grande dejaba el original, y borrarla se veía
parcial. El documento sí quedaba correcto — era **display**.

El visor quita geometría editada sin regenerar, poniendo a cero el alfa de los
tramos de vértices de la entidad, que busca en un mapa `handle → tramos`
(`scene.handle_ranges`). **`hide_handles` hace `continue` en silencio cuando un
handle no está en el mapa**, y el mapa tenía tres huecos:

1. **Todo el contenido de bloque quedaba sin dueño.** El frontend de dibujo expande
   un `INSERT` en copias **virtuales** cuyo `handle` es `None`. Y aunque tuvieran
   uno, el handle de una entidad de definición de bloque no sirve acá: la selección
   y el índice de picado solo manejan la entidad del modelspace. Ahora se atribuye
   a **la entidad más externa que tenga handle**.
2. **`exit_entity` borraba el contexto en vez de restaurarlo**, así que lo que el
   padre dibujaba *después* de un hijo anidado también salía sin dueño (y sin
   `kind`, lo que además mal-clasificaba su bucket para el culling de texto).
3. **El lote de líneas gruesas nunca registró dueños**: `_pack_thick` era el único
   empaquetador llamado sin el mapa, así que toda entidad con grosor > 0,25 mm era
   inocultable, con bloques o sin ellos.

Medido borrando todas las entidades del modelspace y contando vértices que siguen
dibujados: `casa.dwg` dejaba el **75,9 %** del plano en pantalla, el tijeral 26,7 %,
la iglesia de Yanaquihua 13,2 %, `sedapar` 1,9 %. Los cuatro dan **0 %** ahora, y el
tiempo de construcción de escena no cambia.

⚠️ **La lección de método, que es la de siempre en otra forma:** el test de cobertura
que ya existía corría sobre un documento sintético **sin bloques y sin líneas
gruesas**, o sea sobre el único caso que no fallaba. Por eso el hueco sobrevivió a
la suite. El invariante nuevo (`test_handle_ranges_cover_every_vertex_of_every_batch`)
exige primero que el dibujo **llegue a los cuatro lotes** y después que no quede ni
un vértice sin dueño; y se verificó al revés, revirtiendo el arreglo para confirmar
que los cinco tests fallan sin él. Un test que pasa no prueba nada si también pasaría
con el código roto.

Y el bug se disfrazaba porque **se curaba solo**: el `_merge_timer` regenera a los
2,5 s de la última edición. En un plano chico eso es un parpadeo; en `sedapar`, donde
la regeneración tarda ~10 s y cada edición reinicia la cuenta, se ve permanente. Un
fallo que se autocorrige tarde es más difícil de creer que uno que no se corrige.

## 🗓 Sesión 2026-08-06/07 — v0.1.2 (los planos del colega abren)

Release `v0.1.2`, **con AppImage** — el primer binario descargable del proyecto. Los **nueve**
planos que fallaban abren ahora leyendo exactamente lo que lee ODA (eran 2 de 9), y
`vendor/libredwg` va con **13 parches**, todos enviados upstream y cada uno verificado en un
árbol limpio con el parche solo.

**Empaquetado (`packaging/` + `.github/workflows/release.yml`):** PyInstaller *onedir* dentro
de un AppImage, 112 MB. Se compila en **ubuntu-22.04 a propósito**: un AppImage se enlaza
contra la glibc de la máquina que lo hizo, así que hacerlo en la más nueva daría un archivo que
solo arranca en las más nuevas. Dos piezas que lo hacen posible y hay que conservar:
`core/paths.py` (un `app_root()` que lee `sys._MEIPASS`, porque un bundle sintetiza `__file__` y
los cuatro sitios que derivaban rutas de él apuntaban a la nada) y
`tools/libredwg-patches/build-vendor.sh` (reconstruye `vendor/` desde el tarball limpio + el
parche combinado; `vendor/` está en `.gitignore`, así que sin esto un clon no tiene
conversores). **`main.py --check`** es el autodiagnóstico que el CI verifica: cazó dos
directorios ausentes en el primer intento. Sobre 190 planos reales, stock contra
los 13: **12 mejoran, 0 empeoran, +87 314 entidades**. El DWG que escribe `dxf2dwg` es byte a
byte idéntico en ambos casos, así que guardar no se toca. Detalle en `CHANGELOG.md`, el
catálogo en `tools/libredwg-patches/README.md` y la sesión completa —con las mediciones y los
dos callejones sin salida— en `docs/bugs-libredwg-2026-08-06.md`.

## 🗓 Sesión 2026-07-20 — v0.1.1 (integración con el escritorio)

Release `v0.1.1` (tag + release en `ingelibre/ingecad`; sin binarios Windows aún — solo `tests.yml`). Instalado y verificado en la PC del usuario. Lo hecho (detalle en commits `503d85c`/`22b176a`):
- **Ícono de app renovado** (el usuario mejoró `resources/ingecad.svg`) + PNG/ICO rasterizados regenerados a `resources/icons/`.
- **Íconos de documento branded para `.dwg`/`.dxf`** (`scripts/gen_doc_icons.py`, patrón IngeTrazo/IngePresupuestos: hoja + etiqueta DWG/DXF + insignia de IngeCAD → hicolor mimetypes + `.ico`) + paquete MIME `resources/mime/ingecad.xml`. Ver el gotcha "tema-mayor" arriba — fue el bug real por el que "no se veían".

**Pendiente estratégico anotado: publicar a Flathub** (IngeCAD + IngeTrazo). Media: capturas PNG (1ª estática) + videos opcionales WebM/MKV VP9/AV1 sin audio <10 MiB (⇒ ~10-30s). Difícil: empaquetar PySide6+Qt6+GL **y compilar LibreDWG vendorizado** dentro del manifest Flatpak. App-ID candidato `io.github.ingelibre.IngeCAD`. Debe pasar `appstreamcli validate` (warnings fatales).

---

## 📊 Estimación honesta

F0 ≈ 1 sesión · **F1 ≈ 2-4 semanas** (la incógnita; ezdxf.drawing elimina el grueso del riesgo) · F2 ≈ 1 semana · F3-F6 ≈ 4-6 semanas con foco · F7 ≈ 1-2 semanas (mucho se porta de IngeTrazo) · F8 ≈ 1 semana. **v0.1 ≈ 2-3 meses** a ritmo IngeTrazo. Lejos de "años" porque el motor duro (parsear/renderizar fiel) lo aportan ezdxf y LibreDWG — IngeCAD es integración + UX, que es donde Marco ya demostró velocidad.
