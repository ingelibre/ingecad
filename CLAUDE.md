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

### ✅ Cuarta tanda (2026-08-09, misma sesión extendida) — la cola r14 + el harness ensanchado

Con el fuzz seco en su primera configuración, dos movimientos: cazar la cola r14
(197 fallos ya cosechados) y **ensanchar el harness** — DIMENSION renderizada, MINSERT,
LEADER, ATTDEF, target r12, fuente R12, y comparación del CONTENIDO de los bloques (el
compare de modelspace solo era ciego a la corrupción dentro de definiciones). Salieron
**10 causas raíz más: PRs #1378–#1385** e issue **#1386**:

- **#1378 (cuádruple, r13/r14):** el bit `isbylayerlt` se escribía ANTES del fixup que lo
  calcula (vivía en el spec de handles, que corre después, y encima exigía
  `from_version == R_2000` exacto); el ternario del decoder con la rama `: 3` muerta bajo
  su propio `if`; CONTINUOUS/BYBLOCK sin handle materializado (r14 no tiene esos flags);
  y el grupo 48 (ltype_scale) preso en una puerta `SINCE (R_2000b)` del writer DXF.
  Con los cuatro: r14 pasó de 2 % a 100 % en linetype.
- **#1379:** MTEXT con grupo 50 (rotación, válido, lo escribe el renderer de cotas de
  ezdxf) → «Invalid DXF code» → **aborta el archivo entero**. Una cota en el plano y el
  import devolvía nada.
- **#1380:** `--as r12` **jamás funcionó**: el help lo anuncia como válido pero
  `dwg_version_as` solo conoce «r11» (y el mensaje de error imprimía `argv[1]`:
  «Invalid version '-y'»).
- **#1381:** al escribir r11/r12 desde fuente r13+, los placeholders `0xDEADBEAF` de las
  direcciones de tablas quedaban **sin parchear** (la pasada existía pero estaba bajo
  `from_version < R_13b1`, con un FIXME que pedía una conversión que ya ocurría), y un
  `strcmp` sensible a mayúsculas contra `*MODEL_SPACE` reclasificaba TODA entidad de
  modelspace como contenido de bloque → dibujo vacío.
- **#1382:** `dwg_next_handle` — el comentario promete «el handle más alto» y el bucle
  tomaba el del último objeto con handle no-cero → handles duplicados en imports DXF.
- **#1383:** los macros `VALUE_HANDLE`/`FIELD_HANDLE_N` elegían rama con DOS variables
  distintas (`PRE` por target, `IF_ENCODE_SINCE_R13` por FUENTE): fuente R12 → target
  r2000 no satisfacía ninguna y **no se escribía ni un handle** (225 overflows al releer
  un dibujo de una línea).
- **#1384:** los DXF R12 nombran sus bloques de layout `$MODEL_SPACE`/`$PAPER_SPACE`
  (convención de AutoCAD) y todos los matchers del importer solo conocen `*Model_Space`
  → toda entidad inalcanzable. Normalización en el lector de pares.
- **#1385:** MINSERT de una columna volvía con `70=0` (DXF omite 70/71 cuando valen 1;
  el default va en el hook de completado, NO en el upgrade — ponerlo ahí chocó con la
  protección «already set» del matcher y causó una regresión que la propia campaña cazó
  al instante).
- **#1386 (issue):** lo que queda del writer pre-R13 (offsets de sección de bloques con
  el marcador 0x40000000 filtrado; fuente R12 → r2000 aún estructuralmente coja aunque
  → r2004 ya convierte completo), medido y documentado — territorio WIP de rurban, va
  como datos, no como parche.

**Estado del fuzz tras la tanda: fuente moderna → r2000/r2004 100 %, → r14 100 %**
(los «BLOCKDIFF» restantes eran los 21 bloques de flecha estándar que LibreDWG
materializa — relleno benigno, el harness ahora lo tolera). Todo el residuo (450/2000)
es la vena pre-R13 del #1386. Verificación de siempre: make check 254/254, bench de
1657 planos reales **0 empeoran** (y una lección de proceso: el primer bench de esta
tanda se corrió mientras el árbol seguía recompilándose — contaminado, repetido con el
árbol congelado; los benches de regresión exigen árbol quieto).

**Método nuevo validado: el harness como red de seguridad de mis PROPIOS parches.** El
default de MINSERT mal ubicado (en el upgrade en vez del hook de completado) rompió 671
dibujos — la siguiente campaña lo cazó en 15 segundos y el repro dijo exactamente por
qué («already set to 1» + abort). Fuzz que encuentra bugs ajenos también encuentra los
míos: correr la campaña tras CADA parche, no solo al final.

---

### ✅ Quinta tanda (2026-08-09, sesión extendida) — medir contra ODA, proxy, y arrancar L4

Tres frentes del plan de Marco: (1) medir la paridad real contra ODA, (2) cazar el
gráfico proxy, (3) empezar L4 (el writer moderno) en el fork.

**(1) La medición honesta ODA vs LibreDWG sobre los 1657 planos reales.** Herramientas
nuevas (`tools/oda_classify.py` + `tools/oda_vs_libredwg.py`), con el MISMO criterio
ezdxf en ambos lados —convertir todo el corpus con ODAFileConverter a DXF y clasificar
igual que `dwg_bench`. Resultado: **96,8 % de paridad (1604/1657)**. ODA adelante en 30
(la mayoría NO son bugs de lectura: 7 `Helix` = spline 3D que no interpretamos, ~7 de
Civil 3D/decode r2007 ya conocidos, ~15 `COUNT_DIFF` chicos por la conversión ACAD2018).
Y **LibreDWG adelante en 15** —archivos viejos r11/r13/r2 que ODA rechaza con `OdError`
y nosotros abrimos. Conclusión para el producto: **en lectura ya estamos en paridad
práctica con ODA para el flujo real**; lo que falta es nicho (spline 3D, Civil 3D
propietario, un par de bugs r2007), mapeado archivo por archivo en `oda-vs-ldwg.csv`.

**(2) El gráfico proxy — PR #1387.** `dwg2dxf` descartaba por completo las entidades de
clase no parseable (`UNKNOWN_ENT`: carreteras de Civil 3D, entidades de apps), perdiendo
su gráfico. Ahora las preserva como `ACAD_PROXY_ENTITY` con el blob de gráficos (grupos
90/91/95/70 + 92 tamaño + 310 hex), como hace ODA. **Medido: +181 planos con más
entidades, +112 090, 0 regresiones**, y dos planos de Civil 3D que estaban vacíos ahora
convierten. El frontend de IngeCAD (`ProxyGraphicPolicy.SHOW`) los DIBUJA solo. Es
round-trip-safe: el propio `in_dxf` lo relee (verificado por `make check`). Lección de
método, otra vez el harness atrapándome: mi v1 rompía el reimport (grupo 95 en hex donde
el lector espera decimal) y `make check` lo cazó al instante; el bench de corpus
(DWG→DXF→ezdxf) no habría visto ese fallo porque no ejercita el regreso DXF→DWG. Cada
prueba cubre un tramo distinto; hay que correr las dos.

**(3) L4 arrancado — rama `l4-r2018-writer` en el fork, doc en
`docs/L4-r2018-writer-findings.md`.** El hallazgo que cambia el plan: **LibreDWG YA
escribe r2004/r2010/r2013/r2018 y relee su salida con éxito** —pero ODA la rechaza. Con
ODA como único juez válido: el **writer r2004 YA funciona** (ODA acepta same-version),
así que L4 no es «escribir el contenedor moderno desde cero» sino la capa de
**section-map + page-checksum de r2010/2013/2018**. r2018 está a **un solo CRB
consistente** de distancia («CRC does not match», reproducible con un archivo de UNA
línea). La trampa clásica confirmada en su forma más pura: LibreDWG verifica su propio
CRC malo como bueno (`crc32 => verified`) porque computa igual en escritura y lectura —
por eso su lector NUNCA lo cazará y **solo ODA/AutoCAD sirve de oráculo para L4**.
Descartado que sea el tamaño (r2004 también pesa 1.6 MB por una línea y ODA lo acepta).
Siguiente paso anotado: comparar byte a byte los section-page headers contra una
referencia r2018 escrita por ODA. Y el CLA sigue pendiente: L4 es aporte grande, vive en
el fork hasta madurar.

## 🗓 Sesión 2026-08-22 (quater) — dónde se van los segundos de una regeneración

Marco preguntó por qué IngeCAD usa CPU y casi nada de GPU. **Ya usa la GPU**
(renderer `AMD Radeon 780M (radeonsi)`, OpenGL 4.6 — si fuera software diría
`llvmpipe`), y no hay otra: la 780M integrada es la única del equipo. El reparto
medido en SEDAPAR: **7,5 millones de vértices residentes en GPU** contra **11,6 s
de CPU** por regeneración. La GPU está dormida porque su parte son milisegundos;
lo caro es *preparar* los vértices, y eso ninguna GPU lo hace.

**El perfil (cProfile sobre `build_scene`) desmintió mi hipótesis**: el texto era
el 1,3 %, no el grueso. Lo que apareció, sólo en la vista acumulada, fue
`_flatten_distance` → `bbox.extents` = **5,4 s de 17**: nuestro código recorriendo
las 10 847 entidades **sólo para elegir la tolerancia de aplanado de curvas**.
La cabecera del DXF trae el mismo rectángulo gratis: medido en 4 planos reales da
**la misma tolerancia (razón 1,000-1,002) en 0,01 ms contra 40-950 ms**. Ahora se
usa la cabecera, con guardas (ausente, infinita, degenerada, o el centinela ±1e20
de un dibujo nunca regenerado → se paga la caminata).

⚠️ **Y la lección: el perfilador exageró.** Decía 31 %; la ganancia real es
**SEDAPAR 10,5 → 7,4 s (30 %), COFOPRI 14 %, COBERTURAS 0 %**. cProfile infla el
código Python puro, y además la caminata **calentaba cachés (`lru_cache` de
conversión a Path) que el dibujo reusaba**, así que quitarla no descuenta su
tiempo completo. Dos planos cambian su recuento de vértices en <0,1 % porque la
tolerancia difiere en el tercer decimal.

**El camino LWPOLYLINE, hecho después:** ezdxf construye **un diccionario por
vértice** (`locals()` dentro de `format_point`) y el frontend pide `"xyb"` a
cada polilínea camino de un `Path` — 2 millones de llamadas. El parche
(`core/ezdxf_patches.py`) resuelve el formato **una vez por llamada** en vez de
una por punto: **7,6× más rápido** en microbanco (144 → 19 ms por 200 000
puntos) y **exacto** — verificado contra `format_word` en 15 formatos, incluidos
los raros (`"vb"`, `"bxy"`, `""`, `"XYB"`), 0 diferencias.

**Acumulado de las dos optimizaciones:**

| plano | original | + extents | + LWPOLYLINE |
|---|---|---|---|
| SEDAPAR (10 847) | 10 502 ms | 7 391 ms | **6 443 ms** (1,63×) |
| COFOPRI (5 406) | 2 391 ms | 2 063 ms | **1 823 ms** (1,31×) |
| COBERTURAS (4 228) | 4 917 ms | 4 910 ms | **4 865 ms** (1,01×) |

⚠️ **Y una nota de medición:** los recuentos de vértices **fluctúan ±2 entre
procesos** (resolución de fuentes), así que no sirven como prueba byte-exacta;
dentro de un mismo binario sí son estables (2 143 191 tres veces seguidas). La
prueba exacta del parche es la comparación directa contra `format_point`, no el
conteo.

**Lo que queda del mapa:** construcción de `Path` (~12 %), rellenos/hatch de
nuestro backend (~12 %), aplanado de curvas (~9 %). COBERTURAS no mejora con
ninguna de las dos: su coste está en otra parte, probablemente hatches.

## 🗓 Sesión 2026-08-22 (ter) — ciclado de selección, y un plano que no tenía cotas

**Marco: «no hay como seleccionar esa cota».** El diagnóstico salió de SUS dos
capturas y del archivo que guardó, no de suposiciones: en la primera el panel
decía **Dimension** (su cota) y en la segunda **Text** con altura 1 (un número
del plano). Es decir: **los números de los lotes del COFOPRI no son cotas, son
TEXT escritos a mano.** Cotas reales hay 11 y están en la capa SECCIONES, todas
**con anulaciones XDATA**; la suya no las tenía, y el estilo `DISTAN-G` suprime
las cuatro líneas (`dimse1/2`, `dimsd1/2` = 1, y las variables de cabecera dicen
lo mismo, así que AutoCAD dibujaría igual de pelado). Por eso su cota era casi
impicable: medido, **3,8 % de su caja contra 51 %** de una del archivo.

**Lo que faltaba de verdad era el ciclado de selección.** Su cota y el texto del
plano estaban superpuestos, y picar devolvía siempre el mismo. Ahora
`GeometryIndex.pick_all()` da todos los candidatos **con el mismo orden que
usaba `pick`** —invariante clave: el primer clic sigue seleccionando lo de
siempre, el ciclado sólo alcanza lo que ese clic ya se saltaba— y volver a
clicar en el mismo punto ofrece el siguiente (SELECTIONCYCLING valor 1, sin el
diálogo de lista). Vale igual para las herramientas que pican, que es donde él
se trabó con `MA`. Verificado en su archivo: 2 candidatos, clics alternando.

⚠️ **Tres trampas de fixture, todas del mismo tipo: el test pasaba probando
nada.** (1) Añadir entidades directo al modelspace no las mete en el índice de
picado. (2) Re-adjuntar el documento tampoco basta: como añadir sin Command no
cambia `document.revision`, **el pre-calentador en segundo plano da por vigente
su índice vacío y lo adopta**. Lo correcto es dibujar por Commands, como la app.
(3) El shift-clic seguía ciclando porque yo reseteaba **después** de picar.

**Y un hueco de cobertura que este trabajo destapó:** el refactor de prompts de
la fase I3 sacó **200 cadenas** de las llamadas a `tr()` (ahora van por
`self.prompt("...")`), así que el test de cobertura dejó de vigilarlas sin que
nadie lo notara — contaba 886 en vez de 1086. Estaban todas traducidas, pero la
garantía se había perdido. El escáner ahora también lee el embudo de prompts.

## 🗓 Sesión 2026-08-22 (bis) — acotar en un plano grande tardaba segundos

**Marco lo cazó dogfoodeando**: en un plano real, `DIMLINEAR` dibujaba la cota
correcta pero tardaba 3-5 s en aparecer. Medido: **crear la cota cuesta 1-2 ms;
verla costaba 2 300-2 900 ms** en el COFOPRI de 5 406 entidades y **10 300-16 200
ms** en el SEDAPAR de 10 847. Todo eso era `regen_in_memory()` reteselando el
dibujo entero para mostrar UNA entidad nueva.

**La causa era un comentario que dejó de ser cierto.** El controlador forzaba
ese regen a propósito: *«a dimension renders into an anonymous block … the
overlay can't show it»*. Eso valía antes de que el contenido de bloque se
atribuyera a la entidad más externa con handle (v0.1.3); desde entonces **el
overlay dibuja una cota con el mismo frontend que la escena base** — medido:
1 035 vértices para un DIMLINEAR simple, todos atribuidos a su handle. La
exclusión había quedado obsoleta y nadie volvió a preguntárselo.

Cuatro puntos en `views/tool_controller.py`: `_added_entities` reconoce
`AddDimensionCommand`; crear una cota ya no fuerza regen; el regen que sí queda
es sólo para cotas **pegadas** (que pueden llegar sin su bloque `*D`); y
deshacer/rehacer pasa por el camino quirúrgico. **Resultado: 38-335 ms en el
COFOPRI y 148-293 ms en el SEDAPAR** — de 50 a 70 veces más rápido.

⚠️ **Y otra vez la trampa del medidor, en su forma más peligrosa.** Al probar si
el overlay sabía dibujar una cota conté los vértices con un atributo que no
existe (`batch.verts` en vez de `batch.data`) y **leí 0**. Estuve a un paso de
concluir «el overlay no puede, la exclusión es correcta» y cerrar la
investigación. Lo que lo delató fue el **control**: una LÍNEA normal, que sí se
dibuja seguro, también daba 0. *Un cero sólo significa algo si el control da
distinto de cero.*

**Y el mismo comentario obsoleto estaba en un segundo sitio.** Marco probó `MA`
para copiar el estilo de una cota a la recién dibujada y reportó *«como que no
selecciona esa cota»*. `MatchPropCommand` marcaba `needs_regen` cuando origen y
destino eran cotas, con la misma justificación falsa. **El estilo siempre se
copiaba bien** (verificado: alto de texto 1,75 → 7,5, bloque re-renderizado); lo
que fallaba era que **la pantalla tardaba 2 671 ms en mostrarlo**, y segundos sin
respuesta tras hacer clic se leen como «no lo seleccionó». Ahora: **74 ms**.
Lección: cuando una premisa falsa se arregla, hay que **buscar dónde más está
escrita** — el mismo comentario, palabra por palabra, vivía en `core/modify.py`.

De paso, un defecto que sólo aparece al combinar las dos cosas: aplicar MATCHPROP
a una entidad que **ya viaja en el overlay** la encolaba **dos veces**
(`_pending_render.extend` sin deduplicar, cuando la rama aditiva sí deduplica),
así que se teselaba dos veces en cada refresco.

**Lo que NO cambió, y conviene saberlo:** el motor de snap nunca enganchó a la
geometría de una cota, ni antes ni después — verificado preguntándole
directamente, con reconstrucción completa incluida. No es una regresión de este
arreglo; es una función que no existe.

## 🧭 IDIOMAS — la regla, y el plan (2026-08-22) → `docs/i18n.md`

**El primer contribuidor externo llegó por acá.** Michal Josef Špaček (Red Hat,
Chequia — el mismo de LibreDWG) mandó la traducción al checo y dos issues; el
plan completo y la regla para contribuidores viven en **`docs/i18n.md`**. Lo que
no hay que re-discutir:

- **Todo lo que se lee se traduce; todo lo que se tipea es inglés.** La línea de
  comandos es inglesa en cualquier idioma de la interfaz, porque la tesis del
  producto es la memoria muscular. Los menús y los prompts sí se traducen.
- **La convención de los prompts con opciones: traducir la palabra y dejar la
  letra inglesa entre paréntesis** — `[Copiar(C)/Suprimir(D)]`. ✅ **I0 hecha el
  2026-08-22**: 17 cadenas arregladas (eran 87, cumplían 70) y
  `tests/test_i18n_prompt_keys.py` vigila todos los idiomas. ⚠️ Se aceptan **tres**
  formas, no una: `Suprimir(D)`, las mayúsculas de la palabra como las escribe
  AutoCAD (`CEntro` = CE), o el keyword sin traducir (`3P`, `Ttr`) — contar sólo
  los paréntesis daba 28 rotas cuando eran 17. Y las opciones se comparan **por
  posición**: un cotejo laxo daba por buena `Definir` (que es Set) como
  traducción de `Delete`, porque las dos llevan una D mayúscula.
- ✅ **I2 hecha el 2026-08-22 — un idioma es una carpeta, no un parche.**
  `core/i18n.py` es ahora el paquete `core/i18n/` (API pública intacta: ningún
  llamador se tocó) y `packs.py` descubre `i18n/<lang>/{meta,ui}.json`. Las
  **dos** listas fijas de idiomas —el menú y el combo de Opciones— salieron.
  `maintained` vive en `meta.json`, así que agregar un idioma no toca Python
  **ni los tests**. El layout plano `i18n/<code>.json` sigue cargando (la
  traducción al checo en curso no se rompe). Verificado de punta a punta:
  soltar `i18n/qu/` pone *Runa Simi* en el menú de la ventana real.
- ✅ **I4 hecha el 2026-08-22 — comandos localizados.** `i18n/es/commands.json`
  trae **58 nombres** (LINEA, BORRA, DESPLAZA, RECORTA, ACOLINEAL…) y
  `resolve_name` resuelve en este orden, **con el inglés primero en cada paso**:
  `_` fuerza inglés → alias/nombre inglés → nombre localizado → autocompletado
  (inglés antes que localizado). **El invariante sagrado se sostiene con un
  test que recorre toda `DEFAULT_ALIASES` bajo cada idioma instalado**, y el
  cargador rechaza un pack que nombre un comando inexistente, que pise un token
  inglés o que dé un token a dos comandos — verificado metiendo la colisión a
  propósito. Por eso el pack español **no declara alias**: los de una letra son
  la memoria muscular y ya están todos tomados. ⚠️ Los nombres españoles son mi
  mejor lectura de la AutoCAD en español, no una lista verificada; son
  aditivos, así que uno equivocado no cuesta nada y corregirlo es cambiar una
  cadena.
- ✅ **I1 hecha el 2026-08-22**: las **274 cadenas** sin traducir están
  traducidas (es.json 974 → 1216 claves, cobertura **1110/1110**) y
  `tests/test_i18n_coverage.py` falla sólo para el idioma mantenido (`es`);
  los idiomas de la comunidad se informan, nunca bloquean. Vigila además los
  `{marcadores}` en todos los idiomas, porque `tr()` formatea la traducción.
  ⚠️ **Dos trampas de medición**: (1) 106 cadenas **nunca aparecen dentro de un
  `tr(...)`** — viven en tablas de datos y se traducen por variable
  (`Mode("END", 1, "Endpoint")` → `tr(mode.label)`); un test de claves muertas
  ingenuo pedía borrarlas y habría des-traducido los marcadores de referencia a
  objetos. (2) mi primer humo en español decía «0 etiquetas, 0 sin traducir» y
  parecía verde: no encontraba los menús (`main_window` tiene su propio
  `_menu_bar`). **Un conteo de cero nunca es un aprobado**; el recorrido
  arreglado ve 132.
- ✅ **I3 hecha el 2026-08-22 — `core/i18n/keywords.py`**: la palabra traducida,
  la inglesa, la tecla y la forma global `_` resuelven todas a **la tecla
  inglesa**, leídas de la propia traducción (`Suprimir(D)`), así que un idioma
  nuevo trae sus keywords en su `ui.json` sin tocar Python. ⚠️ **La migración
  salió más chica que lo planeado**: en vez de reescribir las 143 comparaciones,
  se normaliza el token en la puerta (34 `on_option` abren con
  `t = self.option(text) or text.upper()`), y las ramas de siempre siguen
  sirviendo porque la tecla inglesa ya era su primer elemento. Lo que sí cambió
  en todas partes es **de dónde sale el prompt**: los 286 de `tools/` pasan por
  `Tool.prompt(source, **kw)`, que traduce y recuerda la fuente — un prompt con
  `{marcadores}` ya sustituidos no se puede mapear de vuelta, y un prompt sin
  opciones limpia el conjunto, de modo que una `D` tecleada como distancia
  nunca se come un keyword viejo. ⚠️ **Dos hallazgos**: un dígito es parte de la
  tecla (`2P` daba `P` y chocaba con `3P`; lo cazó la suite), y el reescritor
  mecánico tuvo que distinguir sangría colgante de alineada al paréntesis —
  quitar `tr(` de los helpers que **devuelven** prompts producía código
  inválido, porque esos paréntesis sostenían la concatenación implícita; ahí
  `tr(` se convierte en `(`. Cada reescritura re-parseaba su salida antes de
  escribir.

Fases I0-I4 con su DoD en `docs/i18n.md`. **I0 (arreglar las 28 + el test que
las vigila) es lo único urgente**: hasta que la regla se haga cumplir, cada
traducción nueva puede reintroducir el mismo bug.

## 🧭 PRÓXIMA SESIÓN (acordado 2026-08-13, tras la v0.4.0) — tres frentes, en este orden

**1. Edición de bloques (`BEDIT`).** Es el hueco más caro que queda: hoy están `B`
(crear), `I` (insertar) y `X` (explotar), pero **no hay forma de cambiar una
definición** — habría que explotar, editar, re-crear y reinsertar a mano cada
copia. Investigado ya (manual pp. 222-224 y 1607):

- **BEDIT antes que REFEDIT.** El Editor de bloques abre la definición en su
  propio espacio y al cerrar (`BCLOSE`) los cambios bajan a todas las
  inserciones. REFEDIT (editar en contexto, con «conjunto de trabajo») arrastra
  el concepto de xref, que no tenemos: va después, si hace falta.
- **La propagación sale gratis:** las inserciones referencian la definición por
  nombre, así que editarla ya actualiza las cuarenta copias del plano.
- ⚠️ **El trabajo real no es el editor, es generalizar el «espacio actual».**
  Toda la maquinaria asume modelspace: **38 llamadas a `.modelspace()`, 16 en
  `core/actions.py`**, más el índice de picado (`GeometryIndex`), `build_scene` y
  el controlador. Una definición de bloque es un contenedor de entidades igual
  que el modelo, así que el editor es «cambiar cuál es el espacio actual» y dejar
  que dibujar/recortar/acotar sigan andando. Esa generalización es sana por sí
  misma: es la que después permite editar geometría sobre una lámina.
- **Bloques dinámicos NO** (parámetros, acciones, estados de visibilidad): es
  morder el clon feature-por-feature que el rumbo descarta, y el 2D civil no los
  usa. Acceso: Tools ▸ Block Editor y el menú contextual con una inserción
  seleccionada, que es lo que documenta el manual.

**2. Afinar la barra lateral derecha** (pestañas Capas / Propiedades / Paleta).
Marco quiere pulirla; **el detalle se define con él al empezar** — no inventar
requisitos acá. Lo que ya está: los tres administradores como pestañas (no
diálogos modales, ver `[[ui-managers-in-sidebar]]`), y Propiedades muestra ya el
estilo de todo objeto que tenga uno.

**3. Arrancar el complemento de TOPOGRAFÍA (v0.5).** Es el complemento #1 y el
contrato de plugins se diseña CON él, no en abstracto (decisión del rumbo del
2026-08-12). Contenido: importar CSV de puntos con cota, cuadro de datos
técnicos automático (Este/Norte, lados, rumbos, área y perímetro — `TABLE` ya
existe como base) y perfil de elevaciones. El README y el FAQ del sitio ya dicen
«v0.5», así que la promesa pública está alineada.

## 🧭 RUMBO ESTRATÉGICO (2026-08-12) — consolidar, quick wins, y COMPLEMENTOS

Marco revisó los 13 menús de BricsCAD Ultimate (capturas) y validó la dirección. Decisiones:

1. **No perseguir a BricsCAD.** Ultimate marea al usuario (3D, paramétricos, nubes de
   puntos, sheet sets — el civil 2D usa ~20%). El filtro maestro sigue mandando; IngeCAD
   compite siendo *el AutoCAD LT que no marea*, no BricsCAD gratis.
2. **La interfaz clásica se queda** (reafirmado). Ni ribbon ni rediseño: hasta BricsCAD
   corre en modo "Toolbars (Classic)". El crecimiento por disciplinas NO pasa por más
   toolbars en el núcleo, pasa por complementos (abajo).
3. **Quick wins aprobados (en este orden):** barra **Standard** (New/Open/Save/Plot/
   Undo/Copy/Paste/Zoom…) → **IMAGE** (insertar imágenes raster; ezdxf IMAGE/IMAGEDEF,
   render = quad con textura) → **TABLE** (tablas; prerrequisito del cuadro de coordenadas
   de topografía) → **PDF underlay** (calcar sobre PDF; rasterizar con QtPdf, tratar como
   imagen). De paso: **DRAWORDER** y **LAYISO/LAYOFF** (baratos, uso diario).
   REVCLOUD ya existía (auditoría de dibujo); faltaba su ícono en la toolbar Draw.
4. **Arquitectura de COMPLEMENTOS (modelo QGIS) — la decisión estructural.** El núcleo =
   AutoCAD LT (dibujar/editar/imprimir DWG). Cada disciplina civil — topografía,
   movimiento de tierras, carreteras, canales, saneamiento — es un complemento que al
   activarse agrega UN menú propio, opcionalmente una toolbar (apagable), y sus comandos
   en el dispatcher; al desactivarse desaparece todo (cero contaminación para el que solo
   dibuja). Gestor tipo QGIS en Herramientas > Complementos; primero complementos
   incluidos, terceros después. **El principio #4 (acciones headless + dispatcher) ya es
   la infraestructura**: un plugin = paquete Python que registra comandos y su menú. El
   contrato del plugin se diseña CON el primer caso real: **Topografía = complemento #1
   (v0.4)** — no diseñar la API en abstracto.
5. **Scripting: Python sobre `actions`, no LISP.** El equivalente moderno de AutoLISP
   (la rutina del cuadro de coordenadas que todos se pasan) es scripting Python sobre la
   capa de acciones, como QGIS. Un traductor de AutoLISP puede existir algún día; los
   complementos y las macros salen del mismo mecanismo.
6. **Consolidar antes que agregar:** el plano real de dogfooding comando a comando
   (memoria `[[proxima-sesion-plano-vs-bricscad]]`) y la ventana de configuración
   siguen pendientes y van antes de cualquier feature grande nueva.

### 🧭 RUMBO ACORDADO (2026-08-09) — próxima sesión: Layout en IngeCAD, cerrar v0.1 con r2004

Marco validó la recomendación estratégica. **Orden de trabajo decidido:**

1. **Layout (pestañas Model/Paper space como AutoCAD) en IngeCAD** — es feature de la app,
   camino crítico de v0.1 (dims, Model/Layout tabs, PLOT). **ARRANCA ACÁ la próxima sesión.**
2. ~~**Cerrar v0.1 con r2004 para «Guardar como DWG»**~~ — **DESCARTADO 2026-08-10, la
   premisa era falsa para nuestro camino**: el «r2004 ya funciona» de L4 se midió con
   `dwgrewrite` de un modelo decodificado de DWG; el modelo que construye `in_dxf` (el
   camino dxf2dwg que IngeCAD usa) produce un r2004 con el object stream roto que ni
   LibreDWG relee (repro mínimo: DXF de 1 línea → `--as r2004` → ENTITIES vacío; falla
   igual en stock 0.14.8578, en el stack parcheado y en la base pre-ventana). v0.1 cierra
   con r2000 (que abre en todo AutoCAD/BricsCAD desde 2000); el bug r2004 cross-modelo es
   el siguiente objetivo Track L. La re-vendorización sí se hizo: base 0.14.8578 + 17
   (10 nuestros ya absorbidos upstream, #1387 proxies incluido) — detalle en
   `tools/libredwg-patches/README.md`.
3. **r2018 writer propio = Track L de fondo**, sin bloquear el producto: madura en la rama
   local `l4-r2018-writer` sesión a sesión cuando haya ganas. NO es camino crítico porque
   r2004 ya resuelve el guardado. Ver «CONTINUAR L4» abajo para retomarlo.

Cuando Marco diga «continúa», el default es **empezar por Layout** salvo que pida L4 explícito.

### ✅ Sexta tanda (2026-08-09, misma sesión) — la medición ODA, el proxy, y L4 a fondo

Tres frentes cerrados o muy avanzados:

**(1) Paridad ODA medida sobre los 1657 planos = 96,8 %.** Herramientas
`tools/oda_classify.py` + `tools/oda_vs_libredwg.py` (mismo criterio ezdxf en los dos
lados). ODA gana en 30 (casi todo nicho: Helix/spline-3D, Civil 3D, diffs de conteo
por ACAD2018), **LibreDWG gana en 15** (r11/r13/r2 viejos que ODA rechaza). En lectura
ya estamos en paridad práctica para el flujo real. Mapa archivo-por-archivo en
`scratchpad/oda-vs-ldwg.csv`.

**(2) Gráfico proxy — PR #1387 (fusionable).** `dwg2dxf` preserva `UNKNOWN_ENT` como
`ACAD_PROXY_ENTITY` con su gráfico. **+181 planos, +112 090 entidades, 0 regresiones**;
dos planos de Civil 3D que estaban vacíos ahora convierten. El frontend de IngeCAD
(`ProxyGraphicPolicy.SHOW`) los dibuja solo. Round-trip-safe (make check lo verifica).

**(3) L4 — writer r2018, avanzado a fondo con la spec de ODA (rama local
`l4-r2018-writer`, 12 commits, NO pusheada a ningún remoto).** De los tres muros de
r2018: **CRC caído** (era escribir las páginas de datos crudas; se resolvió con el
framing LZ todo-literal `store_R2004_section`), **compresión caída** (por tipo:
FileDepList/AppInfo/Preview raw, el resto LZ, según ODA), y **el directorio de secciones
entero del tercero coincide byte a byte con ODA** — todo verificado contra la
**Open Design Specification for .dwg files v5.4.1** (`scratchpad/oda-spec.txt`, §4.4
section page map, §4.5 section info): num_desc=13, Section Ids posicionales (vacío=0,
datos descendentes N..1), sin describir INFO/SYSTEM_MAP, numeración con hueco de 1
(info_id=N+2, map_id=N+4), páginas ajustadas, elisión de página-cero. **Verificado: r2004
sigue aceptado por ODA, make check 254 verde, LibreDWG relee su salida.**

#### 🔜 CONTINUAR L4 (cuando Marco diga «continúa donde quedamos»)

**Estamos en:** el CONTENEDOR r2018 es spec-correcto de punta a punta. **El único muro
que queda es la GENERACIÓN DE CONTENIDO por-sección.** La elisión de página-cero reveló
que en el camino dxf2dwg, **`AcDb:AppInfo` y `AcDb:RevHistory` salen vacías (todo ceros)
donde ODA les escribe contenido real** — por eso ODA aún dice «needs recovery». Detalle
completo en `docs/L4-r2018-writer-findings.md` (updates 1-6, en el fork).

**Próximo paso concreto:** generar el contenido de `AcDb:AppInfo` (spec pág. 96) y
`AcDb:RevHistory` (pág. 100) para que dejen de ser todo-ceros y coincidan con ODA; luego
verificar sección por sección contra el capítulo R2018 de la spec (pp. 71+). Reproductor:
`min2018.dxf` (una línea) → `dxf2dwg --as r2018` → ODAFileConverter como único juez válido
(el lector de LibreDWG NO sirve de oráculo: valida sus propios CRC malos). Construir sobre
el **stack completo de parches** (no la rama L4 sola: el contenido de las secciones depende
de ellos).

⚠️ **Nada de L4/r2018 está enviado a upstream ni al fork** — vive solo en la rama local.
No contamina nada. Solo se enviará en bloque cuando r2018 abra en AutoCAD/ODA.

**Estimación honesta de r2018:** el contenedor (lo hecho) fue lo tratable. La generación
de contenido byte-exacta para TODAS las secciones + el object-stream es el grueso y lo
incierto: un archivo mínimo aceptado por ODA está a ~3-6 sesiones enfocadas; planos reales
(object-stream completo byte-compatible) es bastante más, porque cualquier diferencia de
codificación dispara «needs recovery». Es el «hueco histórico» del Track L por algo.

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
- **Capturas para verificar el canvas: `win.grab()` compone el QOpenGLWidget SIN el overlay QPainter** (crosshair, borde de viewport activo, marcadores) — al menos bajo xcb-sobre-Wayland. Costó una hora de debugging fantasma (2026-08-10): el borde "no se dibujaba" pero estaba perfecto en pantalla. Para verificar overlays del canvas usar `viewport.grabFramebuffer()` (el FBO sí los contiene); `win.grab()` solo vale para el chrome de widgets.
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

## 🗓 Sesión 2026-08-13 (ter) — v0.4.0: el menú contextual y sus siete comandos

**Método que vale más que el resultado: el menú del clic derecho se construyó
grepeando el manual, no recordándolo.** 93 páginas del Command Reference dicen en
sus «Access Methods» que ese comando aparece en el menú contextual; esa lista es
la especificación. Lo mismo para cada comando nuevo (ISOLATEOBJECTS p. 956,
SELECTSIMILAR p. 1726, ADDSELECTED p. 103, QSELECT p. 1584, GROUP p. 861,
FIND p. 808, QUICKCALC p. 1589, OPTIONS p. 1314).

**Aislamiento de objetos: es SÓLO display.** El manual repite *temporarily*. No
toca el documento, no va al archivo, no entra al undo (UNISOLATEOBJECTS es el
deshacer) y una entidad oculta tampoco se puede picar. Vive en
`document._isolated_hidden` y lo filtran `TolerantFrontend.draw_entity` y
`GeometryIndex`.

**Rendimiento del viewport: 146 ms → 5,2 ms por tick.** El contenido no cambia al
navegar, sólo dónde se pone: el modelo se tesela una vez y cada tick es una
matriz + scissor, como el ghost. ⚠️ **Dos trampas que costaron:** (1) cachear la
escena por `document.revision` la invalida en cada tick, porque mover la vista
marca dirty; se invalida desde el camino de edición. (2) Ocultar el horneado
oculta el de TODOS los viewports (comparten las entidades del modelo), así que
hay que dibujar todos, no sólo el activo.

⚠️ **Y la lección de verificación, otra vez y más fina:** medí «0 de 674 370
píxeles distintos» y era cierto — pero con el viewport activo cubriendo toda la
hoja, o sea el caso que no ejercita el fallo. **Una medida correcta sobre el caso
equivocado da una conclusión falsa.**

**En el modelo NO había nada que optimizar:** 0,6 ms por cuadro incluso con 4,5
millones de vértices; los 16,7 ms por movimiento son el refresco de 60 Hz. Queda
como ajuste opcional (Options ▸ Display), no como cambio impuesto.

**Ctrl+Z no llegaba al dibujo** cuando el foco estaba en la línea de comandos (un
QLineEdit reclama esa tecla para su propio deshacer). Reproducirlo llamando a la
función mostraba todo bien: **el bug sólo aparece si la tecla recorre el camino de
una pulsación real** — los tests nuevos pulsan la tecla, no llaman al método.

**TRIM/EXTEND/FILLET/CHAMFER creaban las piezas sin atributos** (12 sitios), así
que nacían en la capa actual. Se hereda el estilo en el punto único donde aterriza
el reemplazo, XDATA incluido.

**Varias ventanas a la vez: funcionan** (probadas tres). No hay guardia de
instancia única y no hace falta; lo único compartido es QSettings (gana el último
que escribe) y los temporales son únicos por conversión.

## 🗓 Sesión 2026-08-13 (bis) — re-vendorización a 0.14.8580 + 17 PRs

⚠️ **La regla que esta re-vendorización instaura: cada parche se toma del HEAD DEL PR**
(`git fetch origin pull/N/head`), nunca de una rama local. El vendor anterior llevaba un
**borrador viejo de #1375** —el que convertía dentro de `dwg_add_u8_input` sin guarda de
versión de origen— y corrompía el MTEXT de todo dibujo pre-r2007. Lo reporté como bug ajeno
(issue #1393) antes de que la comparación contra stock lo delatara. Una rama local es un
banco de trabajo; el PR es lo que existe upstream.

**Base 0.14.8580** (release del 2026-08-12, que ya absorbió nuestros 9 fusionados) **+ los
17 PRs abiertos**: #1358, #1359, #1360, #1364, #1365, #1368, #1369, #1371, #1372, #1373,
#1375, #1378, #1381, #1382, #1385, #1387, #1392. Los 17 aplican limpios.

**Medido:**
- matriz de acentos **16/16 correctas** (8 lugares × 2 versiones de origen); el vendor viejo
  tenía 7 mal.
- fuzz del camino de escritura, mismas 400 semillas: **OK 15 → 242**, DIFF 231 → 9. El
  residuo es exactamente lo documentado — destino r2004 (LOST 66, el bug cross-modelo) y
  destino r12 (EMPTY 33, hueco pre-R13 #1386); 47 de los 48 RELOAD_FAIL son de origen R12.
  **Para r2000, el destino que IngeCAD usa: 206 OK y cero diferencias de contenido.**
- `make check` 254/254, 682 tests de IngeCAD, `main.py --check` OK.
- el parche combinado reproduce el árbol compilado fuente por fuente desde un tarball
  limpio (así lo hará el CI).

**`core/encoding.py` se simplificó, no se borró.** El escapado `\U+xxxx` del MTEXT ya no
hace falta (PR #1375 bueno carga los acentos), así que el archivo guarda el texto tal como
lo escribió el usuario. Lo que **sí sigue haciendo falta** es el intermedio en R2000:
medido, cuatro planos R12 del banco se guardan con **0 entidades** si se les pasa su propio
DXF y completos si se les pasa R2000. La decodificación de escapes al leer también queda —
AutoCAD escribe `\U+xxxx` por su cuenta y ezdxf no lo interpreta.

## 🗓 Sesión 2026-08-13 — v0.3.2 (los acentos, y por qué existe `core/encoding.py`)

**`core/encoding.py` no es una decisión de diseño: es un vendaje sobre un bug ajeno**
(LibreDWG issue #1393) y se va el día que aterrice el arreglo upstream. Lo que hace y
por qué, para que nadie lo "simplifique" sin saber:

Guardar como DWG corrompía **todo** carácter no ASCII — nombres de capa, de estilo y de
bloque, TEXT, ATTRIB, texto de cota y XDATA — y sólo se salvaba el MTEXT. Medido con un
dibujo que lleva `CAÑERÍA Ø m² Nº45°` en las siete ubicaciones. La causa: un DXF moderno
es UTF-8 y LibreDWG copia esos bytes a un DWG que declara la página de códigos de
Windows, así que AutoCAD decodifica `CAÑERÍA` como `CAÃ‘ERÃA`.

**Ningún camino solo funciona**, y por eso el arreglo tiene dos mitades:

| | intermedio R2018 (lo de antes) | intermedio R2000 |
|---|---|---|
| nombres, TEXT, ATTRIB, cota, XDATA | corrupto | correcto |
| MTEXT | correcto | corrupto (escapes `\U+` con code points equivocados: la `Ñ` sale `х` cirílica) |

Así que: el DXF intermedio sale en R2000 (la versión que el DWG va a tener igual, de modo
que el downgrade no puede costar nada que un r2000 pudiera llevar) **y** el MTEXT lo
pre-escapamos nosotros a `\U+xxxx` — ASCII puro, nada que traducir mal. Al leer un DWG se
decodifican, lo que además arregla los archivos que **AutoCAD mismo** escribe así.

De regalo: cuatro planos R12 que se guardaban **vacíos** (hueco del escritor pre-R13,
issue #1386) ahora salen completos.

⚠️ **Dos lecciones de método, las de siempre en otra forma.** (1) *Medir la matriz completa
antes de elegir el arreglo*: mi primer diagnóstico fue «se pierden caracteres en MTEXT»;
la matriz de siete ubicaciones × dos versiones mostró que lo grave eran los **nombres de
capa** y que el MTEXT era el único que sí funcionaba. (2) *El paso de verificación también
miente*: `git apply` dijo «applied clean» sobre un árbol que no era repo git y no escribió
nada; sólo el comportamiento medido (el valor seguía mal) lo delató. Verificar el
verificador.

**Track L en esta sesión:** 9 de los 17 PRs enviados ya están fusionados en master (con
autoría propia, no reimplementados); **#1387 está APROBADO pero sin fusionar**. Nuevo
**PR #1392**: los valores negativos de XDATA (grupos 1070/1071) volvían como su complemento
sin signo — 2595 valores corruptos en 146 de 200 planos reales. Salió de **ensanchar el
harness de fuzz** (`tools/dwg_fuzz.py`) para que llevara XDATA, grosores y extrusiones
inclinadas: la primera campaña lo cazó. El patrón de causa se repite por octava vez —
*el código ya documentaba la conducta correcta y no la ejecutaba*: la tabla de formatos ya
declaraba esos grupos con signo y el valor le llegaba extendido con ceros.

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
