# Segunda tanda de Track L — 2026-08-06

Cerrada la investigación de los 24+6 fallos del barrido de 1657 planos
(`bench-libredwg-2026-08-04.md`). Resultado: **dos PRs, cuatro issues, uno
retirado, y dos planos propios que ya abren en IngeCAD.**

## Enviado a upstream

| | Qué | Estado |
|---|---|---|
| [PR #1352](https://github.com/LibreDWG/libredwg/pull/1352) | `INSERT.has_attribs` pre-R13 se emitía como `66 128`; +1/−1 en `dwg.spec:749` | abierto |
| [PR #1353](https://github.com/LibreDWG/libredwg/pull/1353) | los registros `JUMP` de R11 se escribían como entidades en `ENTITIES`; +8/−0 en `out_dxf.c` | abierto |
| [#1354](https://github.com/LibreDWG/libredwg/issues/1354) | `REPEAT`/`ENDREP`/`LOAD` como entidades, matriz 3×2 perdida | **cerrado por nosotros** |
| [#1355](https://github.com/LibreDWG/libredwg/issues/1355) | DXF truncado (sin `ENTITIES`, sin `EOF`) con código de salida 0 | abierto + causa raíz |
| [#1356](https://github.com/LibreDWG/libredwg/issues/1356) | handles duplicados: un `GROUP` roba el handle 2 y el archivo entero queda ilegible | abierto + 3er caso |
| [#1357](https://github.com/LibreDWG/libredwg/issues/1357) | una referencia irresoluble termina el layout entero: 93 de 10847 entidades | abierto |

Los dos PRs verificados con `make check` **270 PASS / 0 FAIL** (igual al baseline
del stock) y un barrido de regresión sobre los 146 DWG de `test/test-data` y
`programs/`: **143 idénticos, 3 arreglados, 0 peores, +60 entidades**.

**#1354 se retiró a propósito.** Era correcto pero de poco valor (sin parche,
decisión de diseño, formatos de 1983-92, impacto = una matriz de un punto en un
archivo de pruebas) y competía por la atención de #1355/#1356, que cuestan planos
reales. Cerrar un reporte propio por bajo valor suma criterio.

## Los 14 planos propios que fallaban

| Plano | Ver | Diagnóstico |
|---|---|---|
| `frontal` | AC1032 | DXF truncado → **#1355** |
| `cerco permetrico` | AC1032 | DXF truncado → **#1355** |
| `Planos Constructivos` ×2 | AC1032 | DXF truncado → **#1355** (el mismo dibujo duplicado) |
| `YANAQUIHUA 20163` | AC1021 | handles duplicados → **#1356** · **ya abre** |
| `PTL-026-COFOPRI-01-OJAMOQ` | AC1021 | handles duplicados → **#1356** · **ya abre** |
| `PLANTA Y PERFIL LCCE SEDAPAR` | AC1021 | handles + **#1357** (el escritor se rinde) |
| `AR588` | AC1032 | **no es bug**: 594 clases de Civil 3D, 8784/11040 objetos propietarios |
| `Trocha Santa Chichas` | AC1032 | **no es bug**: ídem |
| `A1 PLANO CLAVE ISPACAS_recover` | ?? | **no es bug**: cabecera no es firma DWG, archivo dañado |
| `Drawing1` ×2 | AC1024 | **no es bug**: dibujos nuevos vacíos (0 entidades) |

Marco los abrió todos en BricsCAD uno por uno. Los tres «no es bug» de Civil 3D
y del archivo dañado **BricsCAD tampoco los abre**, lo que confirma el
descarte. Los demás abren bien allí, así que el fallo es de LibreDWG.

**Cuidado con confundir «trae Civil 3D» con «bloqueado por Civil 3D».** Solo
`AR588` y `Trocha` están bloqueados (miles de objetos propietarios). Los
`Planos Constructivos` y `SEDAPAR` declaran clases de Civil 3D en la cabecera
pero tienen **cero objetos no reconocidos**, y ODA les saca 26 583 y 10 847
entidades: su geometría es corriente y sus fallos son de LibreDWG.

## Causa raíz de #1355 (el truncamiento)

El mapa de objetos (`AcDb:Handles`) de `frontal.dwg` se recorre como tres páginas
de `[2 bytes tamaño][entradas][2 bytes CRC]`:

```
pagina 1:    0 + 2033 + 2 = 2035   CRC 11BD válido
pagina 2: 2035 +  551 + 2 = 2588
pagina 3: 2588 +  513 + 2 = 3103 bytes necesarios
seccion:  size 0xA20       = 2592 bytes disponibles     -> faltan 511
```

La página 1 valida y los **1039 primeros objetos se decodifican limpios**. Luego
el lector se sale del buffer (`bit_read_RC buffer overflow at 2592.0 >= 2592`),
encuentra relleno `0xFF`, y de ahí salen handles basura y un objeto de 4 202 513
bytes en un archivo de 61 KB. Entre los objetos que se pierden están
`LTYPE_CONTROL`, `LAYER_CONTROL` y el `BLOCK_HEADER` de `*Model_Space` — que es
exactamente donde el escritor de DXF muere, tras la tabla `VPORT`.

**Dos arreglos probados y descartados** (documentados en el issue para que nadie
repita el camino):

1. Reservar los 2 bytes del CRC en el bucle (`< section_size - 2`): errores
   4101 → 3, pero el decodificado empeora (974 objetos, sin tablas). El
   `section_size` cuenta su propio campo y no el CRC, así que restar 2 desplaza
   la lectura del CRC y descuadra la página siguiente.
2. Validar el CRC de cada página antes de parsearla: 4101 → 4085, o sea nada.
   La página 2 **pasa** esa validación; la guarda solo salta en la 3.

Que las páginas estén bien formadas y no quepan es lo que apunta al tamaño de
sección y no al bucle. El arreglo correcto necesita la especificación de la
sección.

## No es un agujero del formato

Tasa de fallo del barrido por versión de DWG:

| Versión | Planos | Fallan | % |
|---|---:|---:|---:|
| R2013 | 477 | 1 | 0,2 % |
| R2010 | 322 | 3 | 0,9 % |
| R2004 | 101 | 1 | 1,0 % |
| **R2018** | **606** | **7** | **1,2 %** |
| R2007 | 48 | 4 | 8,3 % |
| R2000 | 62 | 7 | 11,3 % |
| R11/R12 | 8 | 2 | 25 % |

R2018 va bien (98,8 %). Los puntos flojos son **R2007 y R2000**, y ahí caen los
tres planos que más importaban.

## Lo que se arregló en IngeCAD

`formats/dwg_bridge.py`:

- **`_dedupe_handles()`** renumera los handles duplicados del DXF que entrega
  `dwg2dxf`. Con eso `yanaquihua` (11 550) y `cofopri` (5 725) abren con el
  conteo **exacto** de ODA. Se irá cuando #1356 se arregle upstream.
- **`_read_dxf_lines()`/`_write_dxf_lines()`** parten solo por `\n`.
  `str.splitlines()` también parte por `\x85`, y al leer latin-1 el byte 0x85 se
  vuelve `U+0085`: un plano con ese byte (uno real aquí tiene 15) ganaba líneas
  fantasma y descuadraba todos los pares código/valor. **`_strip_null_handles()`
  llevaba con ese bug desde que se escribió.**

166 tests en verde, 4 nuevos y **autocontenidos**: fabrican el fallo con ezdxf en
vez de depender de planos de clientes, así que corren en cualquier máquina.

## Pendiente

- **`sedapar` sigue sin abrir de verdad** (93 de 10 847). Es #1357 y **no se
  puede arreglar desde IngeCAD**: las entidades no están en el DXF. Decisión
  tomada: se espera el arreglo upstream, sin recurrir a ODA como respaldo
  (objetivo de Track L: no depender del conversor propietario).
- **`load_dwg()` muestra un lienzo en blanco sin avisar** cuando el DXF viene
  truncado. Su guarda (`entitydb <= 100 → vacío legítimo`) no cubre ese caso,
  porque un archivo truncado tiene la base de datos diminuta. Señal limpia
  disponible: **un DXF que no termina en `EOF` está truncado**, verificado sobre
  los 146 archivos de upstream (todos terminan en `EOF`) y los 4 planos roros
  (ninguno).
- Reini Urban no commitea desde el 2026-07-25; el proyecto sigue activo con
  Michal Josef Špaček, nameloCmaS y Saddam. Los hilos abiertos sin respuesta son
  ausencia del mantenedor principal, no un juicio: **8 commits de Marco ya están
  en el master de LibreDWG**, tercero en los últimos 60.

## Carpeta de revisión

`~/Proyectos/externos/planos-con-fallo/` (fuera del repo, no se trackea) con los
14 DWG, sus DXF de ODA, un SVG de cada uno, las miniaturas incrustadas y un
`LEEME.txt` con el diagnóstico plano por plano.

---

# Cierre del día: dos bugs arreglados y `vendor/` recompilado

Los dos que eran abordables sin la especificación del formato se arreglaron, no
solo se reportaron.

## PR #1358 — `decode.c`, secciones r2004 (cierra el #1294 de otro usuario)

Dos capas:

1. `num_sections * max_decomp_size` es una **estimación** superior del tamaño
   descomprimido. Cada página trae su propio `StartOffset`, así que lo que el
   buffer tiene que abarcar es `info->size`. En estos archivos la estimación sale
   **1-3 páginas corta** y el archivo se rechaza entero. Ahora se reserva el mayor
   de los dos.
2. Y la de fondo: la guarda que decide si una página cabe comparaba contra el
   tamaño **máximo** de página en vez del real. La última página es más corta, así
   que `dirección + máximo` se pasa del buffer aunque `dirección + real` quepa. Y
   al fallar en una sección comprimida el flujo cae a un `else` cuyo primer
   chequeo es `info->compressed == 2` → **156 páginas buenas perdidas por la
   última**. La expresión correcta ya estaba ocho líneas más abajo en ese mismo
   `else`.

Eso explica por qué **solo fallan algunos r2018**: con estimación generosa hay
holgura y la guarda pasa de milagro; con páginas casi llenas no hay ninguna.

De paso **refuta la hipótesis del hilo** (historial de borrados): `cerco
perimetrico` tiene `HANDSEED` 0x1313 = 4883 para ~2222 entidades, ratio 2,2×
—normal— y fallaba igual.

## PR #1359 — `dwg.c`, referencias irresolubles (cierra el #1357)

`get_next_owned_block_entity` devolvía `NULL` tanto para «se acabó la lista» como
para «esta entrada no resuelve», y quien la llama hace `while (obj)`. Una sola
referencia rota terminaba el layout y todo lo de atrás se perdía en silencio.

**Tres funciones lo tenían**, no una: `get_first_owned_entity` (layout vacío
desde el arranque), `get_next_owned_entity` (la usan `dwggrep` y `dwg2SVG`) y
`get_next_owned_block_entity`.

El daño gordo estaba **en los bloques**, invisible mirando solo el modelspace:
`yanaquihua` 79 311 → 126 500 entidades escritas (decodificadas: 126 503) y
`cofopri` 9 076 → 78 241 (de 78 244).

## `vendor/libredwg` ya no es stock

Recompilado con los cuatro parches. El stock que sustituye queda en
`vendor/libredwg.stock-0.14.8556`. Procedimiento del README seguido entero,
incluido el bench en los dos sentidos antes de cambiar los binarios (190 planos:
`OK` 160 → 166, **0 regresiones**; el 4º parche no mueve el bench porque su
ganancia está en `BLOCKS` y tras el saneado de handles, que el bench no cuenta).

## Estado real de los 7 planos, medido con `load_dwg()`

| Plano | ODA | Antes | Ahora |
|---|---:|---:|---:|
| `yanaquihua` | 11550 | 11550 | **11550** ✓ |
| `cofopri` | 5725 | 5725 | **5725** ✓ |
| `cerco perimetrico` | 2222 | 0 | **2222** ✓ |
| `Planos Constructivos A` | 26583 | 0 | **26583** ✓ |
| `Planos Constructivos B` | 26583 | 0 | **26583** ✓ |
| `sedapar` | 10847 | 93 | **8588** (79%) |
| `frontal` | 1039 | 0 | **0** |

`sedapar` pierde 2259, que son exactamente las referencias cuyos objetos no se
decodifican (~2000 errores `Invalid class index`): bug de fondo del decodificador,
aparte. `frontal` sigue vacío: es el **#1355**, el único de los tres que necesita
la especificación de la sección, y donde dos intentos propios fallaron.

166 tests de IngeCAD en verde con los binarios nuevos.

**Lección de método que costó un dato mal dado:** medir siempre por la ruta que
usa el usuario (`load_dwg`, que va a `vendor/`), no por el árbol de compilación.
Un arreglo que solo existe en `externos/build-libredwg/` no arregla nada para
quien abre un plano en IngeCAD.

---

# Cierre real: cinco parches, `vendor/` recompilado, seis de siete planos abren

## Los dos arreglos que faltaban

**PR #1359 — `dwg.c`, referencias irresolubles (#1357).** `get_next_owned_block_entity`
devolvía `NULL` tanto para «se acabó la lista» como para «esta entrada no resuelve»,
y quien la llama hace `while (obj)`. Una sola referencia rota terminaba el layout.
**Tres funciones lo tenían**: `get_first_owned_entity` (layout vacío desde el
arranque), `get_next_owned_entity` (la usan `dwggrep` y `dwg2SVG`) y
`get_next_owned_block_entity`. El daño gordo estaba **en los bloques**, invisible
mirando solo el modelspace: `yanaquihua` 79 311 → 126 500 entidades escritas,
`cofopri` 9 076 → 78 241.

**PR #1360 — `decode.c`, el mapa de objetos (#1355).** Y aquí **mi diagnóstico
anterior era falso**. Había publicado que el mapa necesitaba 3103 bytes contra
2592 disponibles y que faltaba una página. Volcando el buffer y recorriendo las
páginas con el mismo CRC:

```
pagina 1 @0     2033 bytes  CRC VALIDO   975 entradas, encajan exacto
pagina 2 @2035   551 bytes  CRC VALIDO   195 entradas
@2588              tamano 2              TERMINADOR
```

La sección **no está corta** y **no falta ninguna página**. Lo que hay son **dos
bytes intrusos** en el byte 2173 que no pertenecen al flujo de pares
`(handleoff, offset)`. `bit_read_UMC` falla ahí y el código **usa la basura igual**,
fabricando un objeto de 4 202 513 bytes en un archivo de 61 KB. Resincronizando un
byte más adelante se leen las 195 entradas y se termina **exacto** en el borde de
la página — esa exactitud es la autovalidación.

Mi primer intento resincronizaba ante las tres condiciones de «entrada inválida» y
**rompió `Leader.dwg`** (10 → 0 entidades); dos de ellas son heurísticas que se
disparan en entradas legibles. Refinado a resincronizar solo cuando `!handleoff`.

La corrección está publicada en el #1355 retractando los números falsos.

## Y un bug que no era de LibreDWG: el render

`cofopri` cargaba sus 5725 entidades y se veía **en blanco**. `_world_extents`
tomaba el mínimo y máximo crudos, y ese plano trae un `LAYOUT` con extensión en
`6.7e+301`: `Zoom Extents` encuadraba 10³⁰¹ y todo quedaba bajo un píxel.

Tres intentos, dos malos:

| Intento | Por qué falló |
|---|---|
| Umbral fijo 1e20 | la basura de `sedapar` está en 7,6e19, justo debajo |
| Percentiles 0,5–99,5 | `sedapar` tiene 1,16 % de vértices basura (66 368 de 5,7 M) |
| Cuartiles + margen 100× | recortaba geometría lejana legítima — **lo cazó un test propio** |

Lo que funciona es no inventar el criterio: usar los `$EXTMIN`/`$EXTMAX` que el
propio CAD grabó, que **coinciden exactos con los de ODA en los cinco planos**
aunque entidades individuales traigan basura. Con salvaguarda: si esa caja rechaza
más del 5 % de los vértices está desactualizada y se desconfía de ella.

**Los siete planos encuadran ahora exactamente lo que reporta ODA.**

## Issue #1361, sin parche

`LWPOLYLINE` se desincroniza a mitad de su lista de puntos: **14,4 % de los
vértices** del modelspace de `sedapar` salen cerca de `DBL_MAX` (33 188 de
231 138), mientras ODA lee sus 1 026 048 puntos sin uno malo. Cada polilínea va
bien hasta un índice arbitrario y luego se rompe:

```
handle 11D  2541 puntos  correctos hasta 566,  corruptos del 567
handle 124  8049 puntos  correctos hasta 2521, corruptos del 2522
```

Reportado con reproductor (ya adjunto en el #1356). IngeCAD lo sobrevive
filtrando, pero no lo excusa.

## Estado final de los 7 planos, medido con `load_dwg()`

| Plano | ODA | IngeCAD |
|---|---:|---:|
| `frontal` | 1039 | **1039** ✓ |
| `cerco perimetrico` | 2222 | **2222** ✓ |
| `Planos Constructivos A` | 26583 | **26583** ✓ |
| `Planos Constructivos B` | 26583 | **26583** ✓ |
| `cofopri` | 5725 | **5725** ✓ |
| `yanaquihua` | 11550 | **11550** ✓ |
| `sedapar` | 10847 | 8588 (79 %) |

A `sedapar` le faltan 2259, que son exactamente las referencias cuyos objetos no
se decodifican (~2000 errores `Invalid class index`): el bug de fondo pendiente.

## La lección que costó dos datos mal dados

Le dije dos veces que un plano abría cuando no abría, porque medía en
`externos/build-libredwg/` y lo contaba como si fuera IngeCAD. Son binarios
distintos: la app usa `vendor/`.

**Un arreglo no está terminado hasta que está en `vendor/` y medido con
`load_dwg()`.** Los pasos intermedios son trabajo en curso, no resultados. Y las
tres veces que la cifra no se cumplía, quien lo cazó fue Marco abriendo el plano
en la app.

---

# Sexto parche: los dos planos de SketchUp (PR #1362)

Marco probó `11-segundo piso.dwg` en IngeCAD y no abría. Ni siquiera producía un
DXF: `dwg2dxf` se rendía antes de escribir nada.

```
ERROR: DWG_SENTINEL_R11_LAYER_BEGIN not found at 67586
ERROR: Failed to decode file .../segundo-piso.dwg 0x101
```

## El diagnóstico

El centinela **sí está** en el archivo — 300 bytes antes de donde la dirección
de tabla del encabezado lo pone. Y no es solo ese: en ese plano **todas** las
tablas están corridas hacia atrás, cada una en distinta medida.

| centinela | esperado en | está en | corrido |
|---|---:|---:|---:|
| `BLOCK_BEGIN` | 67286 | 67254 | −32 |
| `LAYER_BEGIN` | 67586 | 67286 | **−300** |
| `STYLE_BEGIN` | 67741 | 67586 | −155 |
| `VIEW_BEGIN` | 67971 | 67363 | **−608** |

## El arreglo ya estaba escrito

`decode_preR13_sentinel` **ya tenía** la ruta de recuperación: si el centinela no
está donde toca, lo busca alrededor, se reposiciona y sigue con un aviso. Pero la
ventana:

```c
size_t pos = MAX (dat->byte, 200) - 200;
size_t len = MIN (dat->size - dat->byte, 400);
// search +- 1000 bytes around
```

±200 — mientras el comentario de la línea siguiente promete ±1000. Los −300 de
`LAYER_BEGIN` quedaban fuera por 116 bytes, así que la recuperación nunca se
disparaba y el archivo entero se perdía. Encima `len` se medía desde `dat->byte`
aunque la búsqueda arrancaba 200 bytes antes, así que la ventana ni siquiera era
simétrica.

Ensanchada a los ±1000 que documenta, y `len` calculado desde `pos`. **Cuarto
arreglo de los seis que consiste en hacer que el código cumpla lo que ya decía de
sí mismo.**

## Resultado, medido con `load_dwg()` sobre `vendor/`

| Plano | antes | después | ODA |
|---|---|---:|---:|
| `10-primer piso.dwg` | ningún archivo | **1246** | 1246 |
| `11-segundo piso.dwg` | ningún archivo | **1459** | 1459 |

Exactos contra ODA los dos. Y la recuperación avisa de cada corrimiento, así que
la rareza del archivo no se oculta:

```
Warning: DWG_SENTINEL_R11_LAYER_BEGIN not found at 67586, but at 67286
```

No perseguí *por qué* las direcciones están corridas en cantidades distintas: la
ruta de recuperación existe justamente para no tener que entender eso archivo por
archivo, y solo fallaba porque miraba en una ventana más chica que la que
anunciaba. Queda dicho en el PR, por si upstream prefiere arreglar el cálculo de
direcciones en su lugar.

## Verificación

- `make check`: 270 PASS / 0 FAIL / 0 SKIP, igual que el stock.
- Los 146 DWG de `test/test-data` y `programs/` reconvertidos antes y después:
  **146 idénticos, 0 peores**. Los r11 de upstream tienen sus centinelas donde el
  encabezado dice, así que ninguno pasa por esta ruta.
- Barrido de 190 planos: `NO_OUTPUT` 3 → 1, `OK` 167 → 169, cero regresiones.

## Estado final de los 9 planos

| Plano | ODA | IngeCAD |
|---|---:|---:|
| `frontal` | 1039 | **1039** ✓ |
| `cerco perimetrico` | 2222 | **2222** ✓ |
| `Planos Constructivos A` | 26583 | **26583** ✓ |
| `Planos Constructivos B` | 26583 | **26583** ✓ |
| `cofopri` | 5725 | **5725** ✓ |
| `yanaquihua` | 11550 | **11550** ✓ |
| `primer piso` | 1246 | **1246** ✓ |
| `segundo piso` | 1459 | **1459** ✓ |
| `sedapar` | 10847 | 8588 (79 %) |

**Ocho de nueve exactos.** El único pendiente es `sedapar`, y lo que le falta
está identificado: las 2259 referencias cuyos objetos no se decodifican
(~2000 errores `Invalid class index`).

## Balance de la tanda: 6 parches, 3 issues

| # | Qué | Estado |
|---|---|---|
| [#1352](https://github.com/LibreDWG/libredwg/pull/1352) | `INSERT.has_attribs` pre-R13 sin normalizar | PR |
| [#1353](https://github.com/LibreDWG/libredwg/pull/1353) | `JUMP` de R11 escrito como entidad | PR |
| [#1358](https://github.com/LibreDWG/libredwg/pull/1358) | secciones r2004 rechazadas por su tamaño declarado — cierra el [#1294](https://github.com/LibreDWG/libredwg/issues/1294) de otro usuario | PR |
| [#1359](https://github.com/LibreDWG/libredwg/pull/1359) | una referencia irresoluble abandonaba el layout entero | PR |
| [#1360](https://github.com/LibreDWG/libredwg/pull/1360) | el mapa de objetos usaba la basura de un `bit_read_UMC` fallido | PR |
| [#1362](https://github.com/LibreDWG/libredwg/pull/1362) | ventana del centinela pre-R13 de ±200 con comentario de ±1000 | PR |
| [#1355](https://github.com/LibreDWG/libredwg/issues/1355) | el issue original de `frontal` | causa raíz corregida en público; la arregla el #1360 |
| [#1356](https://github.com/LibreDWG/libredwg/issues/1356) | handles duplicados en el DXF de salida | abierto |
| [#1361](https://github.com/LibreDWG/libredwg/issues/1361) | `LWPOLYLINE` desincronizado a mitad de lista | abierto, sin parche |

Los **seis** parches nacieron del mismo patrón: el código ya documentaba la
conducta correcta y no la ejecutaba. Los **dos** que intenté deducir del formato
—los dos para el #1355— fallaron, y quedaron escritos en el issue para que nadie
los repita.

---

# Séptimo parche: `sedapar` al 100 % (PR #1363)

El plano que faltaba. Estaba al 79 % —8588 de 10 847— y lo que le sobraba eran
2258 referencias del *Model_Space* que no resolvían a ningún objeto, con ~2000
errores `Invalid class index` de fondo.

## Cómo se acorraló

Cinco medidas, cada una descartando una explicación:

**1. El mapa de objetos está completo y sano.** Instrumenté el bucle de
`read_2007_section_handles` con `fprintf` directo (sin nivel de log): 20 páginas,
los 38 029 bytes consumidos enteros, **los 20 CRC correctos**, y el cierre normal
con la página terminadora de tamaño 2. **12 845 entradas.**

**2. Pero solo 10 662 objetos sobreviven.** `dwg_decode_add_object` decrementa
`num_objects` cuando falla. 12 845 − 10 662 = **2183 fallos**, que es casi
exactamente los 2258 irresolubles.

**3. Las direcciones del mapa son buenas.** Los deltas de handle son 1 en 12 815
de 12 845 entradas, y los de dirección son positivos y monótonos, del orden de
100–9000 bytes. No hay desincronización acumulada: dentro de una racha de 136
fallos consecutivos hay objetos que sí decodifican.

**4. Reimplementé el lector en Python** —MS modular, BS a nivel de bit— sobre la
sección de objetos descomprimida (volcada a disco desde el propio LibreDWG) y
reproduje exactamente sus números: en `addr=141275` sale `MSsize=24148,
type=37521`, igual que su `ERROR: Invalid object type 37521`. Busqué una cabecera
plausible en ±80 bytes alrededor de cada dirección fallida: **ningún
desplazamiento común**. Las direcciones no están corridas; los bytes ahí no son
una cabecera de objeto.

**5. Entropía.** 7,87 bits/byte en las zonas fallidas contra 6,39 en las sanas.
Eso no es un formato mal leído: es **paridad intercalada con datos.**

## La correlación que lo cerró

Miré los descriptores de página de `AcDb:AcDbObjects` (181 páginas) y separé por
`comp_size == uncomp_size`:

| páginas | objetos | fallan | |
|---|---:|---:|---:|
| comprimidas (45) | 10 586 | 0 | **0,0 %** |
| **sin comprimir (136)** | 2259 | 2183 | **96,6 %** |

Ni un objeto de página comprimida falló. Casi ninguno de página sin comprimir
sobrevivió.

## El bug

`read_data_section()` lee «no comprimida» como «no codificada» y la copia cruda:

```c
      // only if compressed. TODO: Isn't there a compressed flag as with 2004+?
      if (section_page->comp_size != section_page->uncomp_size)
        read_data_page (...);
      else
        memcpy (&decomp[section_page->offset], &dat->chain[dat->byte],
                section_page->uncomp_size);
```

Pero la codificación **Reed-Solomon es independiente de la compresión**, y
`read_data_page()` ya las trata por separado: deshace el RS primero y solo
después descomprime, `if (size_comp < size_uncomp)`. Una página sin comprimir
puede seguir estando RS-codificada, y ese `memcpy` entrega las palabras de
código: datos intercalados con paridad.

**Séptimo parche, y el sexto que consiste en hacer que el código cumpla lo que ya
decía de sí mismo** — el `TODO` de ese mismo comentario hacía la pregunta
correcta.

## Cómo distinguir las dos clases de página

El descriptor no trae bandera de compresión (eso es lo que pregunta el `TODO`),
así que `page->size` es la única evidencia: una página RS ocupa
`ceil(comp_size/0xFB) * 0xFF` redondeado a múltiplo de 32, y una guardada tal
cual solo se redondea a 32, así que sale más chica. Sobre las 192 páginas del
archivo:

| | páginas | `page->size` == tamaño RS |
|---|---:|---|
| comprimidas | 51 | sí, todas |
| sin comprimir | 137 | sí, todas |
| sin comprimir | 4 | **no** — `SummaryInfo`, `Preview`, `AppInfo`, `FileDepList` |

Esas cuatro sí están en crudo, y se comprueba: leídas así dan
`LASTSAVEDBY: "Nestor"`, `appinfo_name: "AppInfoDataList"`, `version: "17.0.54.0"`
y fechas `TDCREATE`/`TDUPDATE` coherentes. El parche toma la ruta RS solo cuando
el tamaño calza exacto; cualquier otra cosa conserva la copia cruda de hoy. Las
comprimidas no cambian de comportamiento.

Mi primer intento fue «RS-decodificar siempre», y rompió `SummaryInfo`
(`decode_rs src overflow: 251 > 160`). El dato que faltaba era justamente ese: no
todas las páginas están codificadas.

## Resultado

| | antes | después | ODA |
|---|---:|---:|---:|
| entidades del modelspace | 8588 | **10 847** | 10 847 |
| vértices de `LWPOLYLINE` | 231 138 | **1 026 048** | 1 026 048 |
| vértices cerca de `DBL_MAX` | 33 188 | **0** | 0 |
| coordenadas sobre 1e12 | 45 316 | **0** | 40 |

**Y esto cierra el #1361.** Lo había reportado diciendo que las listas de puntos
de `LWPOLYLINE` «se desincronizaban a mitad de lista». No se desincronizaban: se
leían de palabras de código Reed-Solomon. Por eso el índice de rotura parecía
arbitrario — era donde la polilínea cruzaba a una página sin comprimir. Publicado
como corrección en el issue.

## Verificación

- `make check`: **270 PASS / 0 FAIL / 0 SKIP**, igual que la línea base. Incluye
  los dos tests unitarios de esta zona, `decompress_r2007` y
  `read_data_section: rejects out-of-bounds page->offset`; los dos siguen pasando.
- Los **146** DWG de `test/test-data` y `programs/`: **146 idénticos byte a byte,
  0 peores**. Ninguno guarda una página de datos sin comprimir, así que ninguno
  pasa por la ruta nueva.
- `decode_R2007` solo se alcanza para `R_2007a..R_2007` —R2010+ va por
  `decode_R2004`— así que el radio de impacto es **exactamente los AC1021**. A/B
  sobre **los 47 AC1021** de un corpus de 1657 planos, mismo criterio en los dos
  lados:

  | | antes | después |
  |---|---:|---:|
  | entidades totales | 639 053 | **667 767** (+28 714) |
  | planos que ganan | — | 6 |
  | planos que pierden | — | **0** |
  | sin cambio | — | 41 |

  Tres de los seis pasan de `LOAD_FAIL` a `OK` (+11 550, +10 847, +5725); los
  otros tres ganan entre 182 y 207 entidades.

## Estado final: los 9 planos, medidos con `load_dwg()`

| Plano | ODA | IngeCAD |
|---|---:|---:|
| `frontal` | 1039 | **1039** ✓ |
| `cerco perimetrico` | 2222 | **2222** ✓ |
| `Planos Constructivos A` | 26 583 | **26 583** ✓ |
| `Planos Constructivos B` | 26 583 | **26 583** ✓ |
| `cofopri` | 5725 | **5725** ✓ |
| `yanaquihua` | 11 550 | **11 550** ✓ |
| `primer piso` | 1246 | **1246** ✓ |
| `segundo piso` | 1459 | **1459** ✓ |
| **`sedapar`** | **10 847** | **10 847** ✓ |

**Nueve de nueve exactos.** No queda ningún plano propio que LibreDWG lea peor
que ODA.

## Balance de la tanda: 7 parches, 1 issue

| # | Qué | Estado |
|---|---|---|
| [#1352](https://github.com/LibreDWG/libredwg/pull/1352) | `INSERT.has_attribs` pre-R13 sin normalizar | PR |
| [#1353](https://github.com/LibreDWG/libredwg/pull/1353) | `JUMP` de R11 escrito como entidad | PR |
| [#1358](https://github.com/LibreDWG/libredwg/pull/1358) | secciones r2004 rechazadas por su tamaño declarado — cierra el [#1294](https://github.com/LibreDWG/libredwg/issues/1294) de otro usuario | PR |
| [#1359](https://github.com/LibreDWG/libredwg/pull/1359) | una referencia irresoluble abandonaba el layout entero | PR |
| [#1360](https://github.com/LibreDWG/libredwg/pull/1360) | el mapa de objetos usaba la basura de un `bit_read_UMC` fallido | PR |
| [#1362](https://github.com/LibreDWG/libredwg/pull/1362) | ventana del centinela pre-R13 de ±200 con comentario de ±1000 | PR |
| [#1363](https://github.com/LibreDWG/libredwg/pull/1363) | páginas r2007 sin comprimir copiadas sin deshacer el Reed-Solomon — cierra el #1361 | PR |
| [#1356](https://github.com/LibreDWG/libredwg/issues/1356) | handles duplicados en el DXF de salida | **el único que queda abierto** |

## Lo que enseñó este bug

Los cinco anteriores salieron de leer el código buscando su propia contradicción.
Este no: el código no se contradecía en ninguna línea visible, el `TODO` admitía
la duda y ya está. Salió de **medir y partir la población**: separar los objetos
por la clase de página en la que caen y ver 0,0 % contra 96,6 %. Cuando el código
no delata la causa, la delata la correlación — pero hay que tener la variable
correcta para cruzar, y esa la dio la entropía (7,87 contra 6,39), que dijo
«paridad», no «formato mal leído».

Y el primer intento —RS-decodificar todo— falló y fue útil: el error
`decode_rs src overflow: 251 > 160` señaló las cuatro páginas que de verdad están
en crudo, que es lo que hizo falta para escribir la condición bien.

---

# Octavo parche: el issue #767 de otro usuario, abierto desde 2023 (PR #1364)

Con los nueve planos propios resueltos, el siguiente frente son los issues de
otros. El **#767** salta a la vista porque el síntoma es primo del de `segundo
piso`:

```
ERROR: DWG_SENTINEL_R11_VIEW_BEGIN not found at 34056
ERROR: Failed to decode file ... 0x100
```

Mi PR #1362 **no** lo arregla: ahí los centinelas están corridos 300 bytes, acá
no están. Pero el reproductor es público y el hilo tiene una pista del
mantenedor de 2023: *«Maybe check against the natural address for the sentinel,
when the table.address fails.»*

## Qué le falta al archivo

Busqué las 22 constantes de centinela R11 dentro del archivo, en Python. Faltan
seis:

| centinela | ¿está? |
|---|---|
| `VIEW_BEGIN`, `VIEW_END` | **no** |
| `UCS_BEGIN`, `UCS_END` | **no** |
| `VPORT_BEGIN` | **no** |
| `VPORT_END` | sí, en `0x8518` |
| `APPID_BEGIN` | **no** |
| `APPID_END` | sí, en `0x854D` |
| `BLOCK`, `LAYER`, `STYLE`, `LTYPE`, `DIMSTYLE`, `VX` | sí, los dos |

VIEW, UCS y VPORT son las tres tablas vacías, y el encabezado les da **la misma
dirección** (`0x8518`). El único centinela escrito para el grupo es `VPORT_END`,
que termina ocupando los 16 bytes donde iría `APPID_BEGIN`. DIMSTYLE y VX
también están vacías y **sí** traen sus dos centinelas, así que es el escritor
que es irregular, no una regla del formato. Los avisos que emite el parche
listan exactamente esos seis — confirmación cruzada entre mi análisis en Python
y el decodificador.

## Por qué se puede seguir leyendo

El centinela es un **delimitador, no el localizador**. Los registros salen de
`tbl->address`, que el encabezado declara aparte, y **cada registro de tabla
pre-R13 trae su propio CRC, que el decodificador ya verifica**:

```
crc: B405 [RSx]
 check_CRC 32146-32335 = 189: B405 == B405
```

O sea que una dirección mala se caza por sus propios méritos, no hay que
deducirla del delimitador. Así que: avisar, leer la tabla desde su dirección y
seguir. `DWG_ERR_INVALIDDWG` queda fatal a propósito: eso significa que no se
pudieron leer ni los 16 bytes, o sea que la posición misma es basura.

Y el mensaje `not found` de `decode_preR13_sentinel` pasa de `LOG_ERROR` a
`LOG_WARN`, porque la fatalidad la decide el llamador y el que sí se rinde ya
avisa con `Failed to decode file`. Sin eso, un archivo que ahora convierte
perfecto seguía imprimiendo seis líneas `ERROR` — que cualquier CI o banco que
filtre por «ERROR» lee como fallo. El mío incluido.

## Resultado

| | entidades |
|---|---|
| stock | **ningún archivo** |
| con el parche | **553** |
| ODA 25.6 | 553 |

Las 553 son `LINE`. Y renderizando los dos DXF con el backend SVG de ezdxf, la
salida es **idéntica byte a byte**, 29 433 bytes cada una — así que no coincide
solo la cuenta. Es un auto en planta.

Los otros dos archivos del hilo (el `F.DWG` regenerado de michal-josef-spacek y
el `qq.zip` reparado de leshasoft) ya convertían antes y el parche no los toca,
como corresponde: sus centinelas están todos.

## Verificación

- `make check`: **270 PASS / 0 FAIL / 0 SKIP**, igual que la línea base.
- Los **148** DWG de `test/test-data` y `programs/`: **148 idénticos byte a
  byte, 0 peores**. A ninguno le falta un centinela, así que ninguno pasa por la
  ruta nueva.
- Los **18 planos pre-R13** del corpus de 1657 (4 AC1003, 1 AC1004, 3 AC1006,
  8 AC1009, 2 AC1012): **4115 entidades antes y después, 0 cambios**.
- Compilado sobre un `e405fcff` **limpio** con este parche solo, para no
  apoyarme en los otros siete abiertos. Compone con el #1362 sin solaparse: ese
  ensancha la búsqueda de un centinela que **está** pero corrido; este sobrevive
  a uno que **no está**.

## Balance: 8 parches, 1 issue, y dos de otros usuarios

| # | Qué | De quién |
|---|---|---|
| [#1352](https://github.com/LibreDWG/libredwg/pull/1352) | `INSERT.has_attribs` pre-R13 sin normalizar | mío |
| [#1353](https://github.com/LibreDWG/libredwg/pull/1353) | `JUMP` de R11 escrito como entidad | mío |
| [#1358](https://github.com/LibreDWG/libredwg/pull/1358) | secciones r2004 rechazadas por su tamaño declarado | **cierra el [#1294](https://github.com/LibreDWG/libredwg/issues/1294) de SimonSAMPERE** |
| [#1359](https://github.com/LibreDWG/libredwg/pull/1359) | una referencia irresoluble abandonaba el layout | mío |
| [#1360](https://github.com/LibreDWG/libredwg/pull/1360) | el mapa de objetos usaba la basura de un `bit_read_UMC` fallido | mío |
| [#1362](https://github.com/LibreDWG/libredwg/pull/1362) | ventana del centinela de ±200 con comentario de ±1000 | mío |
| [#1363](https://github.com/LibreDWG/libredwg/pull/1363) | páginas r2007 sin comprimir sin deshacer el Reed-Solomon | mío, cierra el #1361 |
| [#1364](https://github.com/LibreDWG/libredwg/pull/1364) | un centinela de tabla ausente rechazaba el dibujo | **cierra el [#767](https://github.com/LibreDWG/libredwg/issues/767) de weikenxq, de 2023** |
| [#1356](https://github.com/LibreDWG/libredwg/issues/1356) | handles duplicados en el DXF de salida | el único issue mío que queda abierto |

---

# Noveno parche: `dwg2SVG` salía en blanco desde 2022 (PR #1365)

El **#523** llevaba abierto desde noviembre de 2022 con **cuatro personas
reportándolo**, y con los archivos de prueba de LibreDWG mismo:
`dwg2SVG example_r14.dwg` producía un SVG que no muestra nada. El mantenedor
había diagnosticado el síntoma en 2022 (*«viewBox is way too large, and you
cannot see anything there»*) y lo dejó por «otras prioridades».

Eran **cuatro causas independientes**. Cada una sola alcanza para dejar la
página vacía.

## 1. El espacio modelo no se dibujaba

`output_BLOCK_HEADER` devuelve «cuántas entidades del espacio papel imprimimos»
y `output_SVG` recurre al espacio modelo cuando eso es cero. Pero
`output_object` arranca en `int num = 1` y solo la rama `default` lo baja — así
que devuelve 1 para **todo** tipo que reconoce, incluidos `VIEWPORT` y `SEQEND`,
que no dibujan nada. Todo espacio papel tiene un `VIEWPORT`, así que la cuenta
nunca fue cero y el respaldo nunca se activó.

La geometría del modelo **sí** llegaba al archivo — pero solo dentro de
`<defs>`, porque `*Model_Space` también es una entrada de `block_control`. Y
**ningún renderizador dibuja el contenido de `<defs>`**. De ahí que pareciera
vacío estando lleno de `<path>`, y de ahí que otro usuario del hilo descubriera
que borrando las etiquetas `<defs>` aparecía el dibujo: su parche a mano
promovía el espacio modelo fuera del bloque de definiciones.

## 2. Todos los trazos tenían ancho cero

```c
  int lw = dxf_cvt_lweight (ent->linewt);
  return lw < 0 ? 0.1 : (double)(lw * 0.001);
  ...
  printf ("...stroke-width:%.1fpx...", lweight);
```

`dxf_cvt_lweight` da **centésimas de mm**, así que los mm son `lw/100`, no
`lw/1000`. Con el factor de diez de más, una línea de 0,25 mm sale 0,025, que
`%.1f` imprime como **`stroke-width:0.0`**. Y `lw == 0` es legítimo —significa
«la línea más fina»— así que también necesita un ancho visible.

## 3. El `viewBox` era la caja del encabezado, no la del dibujo

`$EXTMIN`/`$EXTMAX` cubren todo el dibujo, incluidos los tipos que este
programa se salta, y los planos reales traen entidades fuera de sus extents
registrados. En `example_r14` la caja del encabezado es **3 540 706 × 2 726 367**
mientras que lo que se emite de verdad mide unos **14 871 × 9702**: todo
colapsaba muy por debajo de un píxel.

## 4. El origen del `viewBox` contradecía las coordenadas

`transform_X` devuelve `x - model_xmin`, así que las coordenadas emitidas viven
en `[0, page_width]`. El `viewBox` arrancaba en `model_xmin`. Invisible en un
plano cuyo `$EXTMIN` es `(0,0)`; fatal en los planos UTM.

## Y de paso el #1012

Ese issue decía que las referencias de los objetos de un bloque deberían ser al
punto de definición, no al de inserción. Tenía razón: `transform_X/Y`
trasladaban **también** las coordenadas dentro de `<defs>`, mientras
`output_INSERT` ya coloca el símbolo con
`translate(transform_X(ins_pt), ...)`. Cada bloque quedaba desplazado por el
origen del modelo dos veces.

## Un error mío que la medición cazó

Mi primer intento fue solo el arreglo del origen del `viewBox` (una línea,
demostrablemente correcta). Medí con un analizador de coordenadas propio y dio
«7 de 40 dentro de la ventana contra 1». Pero al renderizar a PNG y **contar
píxeles con tinta**, dos planos habían pasado de 134 píxeles a **0**: el
`viewBox` mal puesto atrapaba por accidente contenido que cae fuera de los
extents declarados, y mi arreglo cambiaba un accidente por otro.

**La medida de punta a punta contradijo a la medida indirecta, y tenía razón.**
Sin renderizar habría mandado un parche que empeoraba archivos.

Segundo error, también mío: para medir sin emitir, silencié el `printf` con una
macro que salta la llamada. Pero **los argumentos son donde viven
`transform_X`/`transform_Y`** — al no evaluarlos no se medía nada, y la caja
volvía como `DBL_MAX`. La versión buena escribe al dispositivo nulo.

## Resultado

`example_r14.dwg` se ve: marco, pentágono, elipse, arco, círculos, achurado.

Sobre **95 planos reales** del corpus, cada uno renderizado a PNG de 200×200 y
puntuado por píxeles con tinta:

| | stock | con el parche |
|---|---:|---:|
| planos que muestran un dibujo | **1** | **68** |
| de esos, antes en blanco | — | 67 |
| **planos que empeoran** | — | **0** |
| píxeles con tinta, total | 80 | 55 775 |

## Verificación

- `make check`: **270 PASS / 0 FAIL / 0 SKIP**, sin cambio — y las pruebas de
  dwg2SVG están dentro.
- Los **148** DWG de `test/test-data` y `programs/` siguen convirtiendo con
  salida cero y su SVG sigue siendo XML bien formado.

## Dos cosas que no toqué, y lo digo en el PR

- `output_XLINE` imprime sus **parámetros de rayo** (`txmin, tymin, txmax,
  tymax`) en vez de los extremos recortados, así que una XLINE sale como un
  `path` con coordenadas sin sentido. Su autor la marcó `// untested!` y la caja
  de recorte usa `model_ymin` dos veces. Arreglo aparte: no quiero adivinar la
  geometría que se pretendía.
- Los planos con un INSERT a 25 millones de unidades del resto siguen saliendo
  como una manchita. Acotar eso es una decisión de política sobre valores
  atípicos que debe tomar upstream — es el mismo problema que en IngeCAD resolví
  con `_world_extents`, y ahí la política la decido yo; en su programa, no.

## Balance: 9 parches, 4 de ellos para issues de otros

| # | Cierra | De quién |
|---|---|---|
| [#1358](https://github.com/LibreDWG/libredwg/pull/1358) | [#1294](https://github.com/LibreDWG/libredwg/issues/1294) | SimonSAMPERE, jun 2026 |
| [#1364](https://github.com/LibreDWG/libredwg/pull/1364) | [#767](https://github.com/LibreDWG/libredwg/issues/767) | weikenxq, jun **2023** |
| [#1365](https://github.com/LibreDWG/libredwg/pull/1365) | [#523](https://github.com/LibreDWG/libredwg/issues/523) | hoangmt + 3 más, nov **2022** |
| [#1365](https://github.com/LibreDWG/libredwg/pull/1365) | [#1012](https://github.com/LibreDWG/libredwg/issues/1012) | acabrera1000, sep 2024 |

Y los otros cinco (#1352, #1353, #1359, #1360, #1362) más el #1363, que cierra
mi propio #1361.

---

# Décimo parche: cualquier DXF sin salto de línea final se rechazaba (PR #1366)

Buscando otro issue de otros, el **#474** (2022) decía que `dxf2dwg` producía un
DWG que AutoCAD TrueView rechazaba. Al probarlo hoy, **está peor**: no produce
DWG en absoluto.

```
ERROR: Out of memory
ERROR: Failed to decode DXF file: my-drawing.dxf
READ ERROR 0x1000
```

Sobre un archivo de **18 KB**. Eso no es falta de memoria. Marqué los 27 sitios
que emiten ese mensaje en `in_dxf.c` con `__LINE__` y salió el de la línea 886:
`dxf_read_string` devolvió NULL para un grupo `0`, y el llamador lo reporta como
OOM y aborta el archivo entero.

## La causa

```c
  // properly end the buffer for strtol()/... readers
  if (dat.chain[size - 1] != '\n')
    {
      dat.chain[size] = '\n';
      dat.size++;
    }
  dat.chain[size] = '\0';
```

El salto de línea se añade en `chain[size]` y **acto seguido lo sobreescribe el
`'\0'`, en el mismo índice**. `dat.size` ya se incrementó, así que el buffer
termina en `...\n0\0` con el NUL exactamente donde debía estar el salto.

Y `dxf_read_string` se rinde si no encuentra un `'\n'` en lo que queda:

```c
      if (dat->byte >= dat->size
          || !memchr (&dat->chain[dat->byte], '\n', dat->size - dat->byte))
        return;
```

El `calloc` reserva `dat.size + 2` justo para este caso, así que el arreglo es
poner el NUL **después** del salto: `dat.chain[size++] = '\n';`.

**Décimo parche, y el séptimo que consiste en hacer que el código cumpla lo que
ya decía de sí mismo** — el comentario dice literalmente *«properly end the
buffer»* y la línea siguiente lo desarma.

## La clase entera de archivos

No es específico del archivo del #474. **Cualquier DXF cuyo último byte no sea un
salto de línea** se rechaza, sea lo que contenga, porque la pérdida siempre cae
en el par final `0`/`EOF`.

El mismo DXF, diferenciándose solo en ese byte:

| | resultado de `dxf2dwg` |
|---|---|
| termina con salto de línea | DWG de 5139 bytes |
| termina sin él | **falla, ningún archivo** |

Con el parche los dos producen **los mismos 5139 bytes, byte a byte**. Y el
`my-drawing.dxf` del #474 (generado por Maker.js, terminado en `0\nEOF`) pasa a
convertir a un DWG AC1015 de 12 696 bytes.

## Lo que NO arregla, y lo dije en el issue

El DWG que ahora produce **sigue sin abrir**. ODA lo rechaza con
`Null object Id: <object> (0)`, que es exactamente el diagnóstico que dio Reini
Urban en 2022: un DXF mínimo no trae handles, y los handles se usan internamente
para encontrar las entradas de tabla, así que hay que asignarlos. Eso es otro
arreglo. El #474 queda abierto por esa parte.

Lo separé a propósito: «Out of memory» sobre un archivo de 18 KB manda a
cualquiera a buscar en el lugar equivocado, y el bug del salto de línea afecta a
archivos que no tienen nada más de malo.

## Verificación

- `make check`: **270 PASS / 0 FAIL / 0 SKIP**, sin cambio.
- Ocho DXF reales (de 26 KB a 47 MB) por `dxf2dwg` antes y después: **todos los
  DWG idénticos byte a byte**. Dos no producen salida en ninguno de los dos lados
  (ajeno a esto); los otros seis coinciden exacto.
- Compilado y probado sobre un `e405fcff` **limpio** con este parche solo.

## Y dos issues que verifiqué y resultaron ya resueltos

- **[#327](https://github.com/LibreDWG/libredwg/issues/327)** (2021, «ciertos
  textos y las cotas no se ven al convertir»): con su propio reproductor,
  `dwg2dxf` y ODA dan **cero diferencias** en todo el documento — 1224
  LWPOLYLINE, 1117 LINE, 774 INSERT, 483 HATCH, 222 DIMENSION, 111 MTEXT, 82
  ATTDEF, idénticos —, las 111 cotas con su bloque `*D` y sus 561 entidades
  dentro. Renderizados, 411 440 contra 411 444 bytes de SVG. Comentado con los
  números y propuesto cerrar.
- **[#426](https://github.com/LibreDWG/libredwg/issues/426)** (SPLINE sin puntos
  de control): el DWG guarda `scenario: 1`, o sea **solo los puntos de ajuste** —
  LibreDWG lo lee completo y bien; AutoCAD y ODA *calculan* los 5 puntos de
  control y los 9 nudos por interpolación. Verifiqué la parametrización: los
  nudos de ODA `[0,0,0,0, 12.2776, 26.0835×4]` son exactamente las longitudes de
  cuerda acumuladas de los 3 puntos de ajuste. O sea que es una brecha de
  fidelidad real, no una pérdida al decodificar; implementarla es interpolación
  cúbica global con condiciones de borde que habría que adivinar. **Y no cuesta
  el dibujo**: ezdxf renderiza el DXF de LibreDWG y el de ODA *idénticos byte a
  byte*, porque interpola desde los puntos de ajuste. Lo dejé.

---

# Undécimo parche: un surrogado UTF-16 tumbaba un DXF entero (PR #1367)

El **#1021** (2024) reportaba que AutoCAD rechaza el DXF de LibreDWG:

```
Error in in APPID Table
DXF-ReadError auf Line 106298.
Invalid or incomplete DXF input -- drawing canceled.
```

y pegaba nombres de APPID que salían como basura (`AT_JNT_肘౐肘౐ᠺಜ풴ۥ...`)
mientras otros del mismo listado salían perfectos (`AUDIT_I_190703115940-0`).

## Cómo se acorraló

Primer intento de medición: buscar nombres de APPID con bytes no imprimibles
leyendo en latin-1. Dio 15 «corruptos» en 4 de los 5 planos — **y era falso**:
`æ\xa0\x87é«\x98` es UTF-8 de «标高» (cota en chino), perfectamente válido. Mi
lectura en latin-1 me engañó.

El criterio bueno es objetivo y no depende de mi interpretación:

```
$ iconv -f UTF-8 -t UTF-8 Stahl.dxf > /dev/null
iconv: secuencia de octetos no válida
```

**4 de los 5 planos producen un DXF que no es UTF-8 válido.** El de ODA, sobre el
mismo DWG, sí lo es. Y un DXF de R2007 o posterior está especificado como UTF-8.

Decodificando incrementalmente para hallar la posición exacta:

```
byte 333657 -> linea 40604: AT_JNT_\xed\xb4\xb8\xe0\xae\xb5...
```

`\xed\xb4\xb8` es **U+DD38, un surrogado bajo suelto**. Y comparando la lista
completa de APPID contra ODA: 1687 en los dos lados, con **una** diferencia — ese
nombre, que ODA escribe como `$TD_AUDIT_GENERATED_(10E7)`. O sea que el nombre en
el DWG **sí está dañado**, ODA también lo ve inservible y lo reemplaza; la
diferencia es que LibreDWG lo pasa tal cual como UTF-8 ilegal.

## La causa

```c
        else /* if (c < 0x10000) */
          {  /* windows ucs-2 has no D800-DC00 surrogate pairs. go straight up
              */
            str[i++] = (c >> 12) | 0xE0;
```

Los bucles UTF-16 → UTF-8 codifican **cualquier** unidad de código ≥ 0x800 como
tres bytes, incluidos los surrogados D800–DFFF, que la RFC 3629 prohíbe. Y el
decodificador del **mismo archivo** ya lo sabe:

```c
                      // reject overlong encodings and UTF-16 surrogates
                      if (cp >= 0x800 && (cp < 0xD800 || cp > 0xDFFF))
```

**Octavo de los once parches que consiste en hacer que el código cumpla lo que ya
decía de sí mismo** — solo que esta vez la contradicción está entre el lector y el
escritor del mismo archivo.

Un nombre dañado hacía ilegibles **106 000 líneas buenas**.

## El arreglo, y lo que dejé fuera a propósito

Una guarda uniforme (`NO_LONE_SURROGATE`) en los 6 sitios UTF-16: un surrogado
suelto pasa a U+FFFD, que es el sustituto estándar y ocupa **los mismos tres
bytes** — así que ningún bucle cambia de forma y ninguna aritmética de buffer se
mueve.

Lo que **no** hice: combinar un par surrogado genuino en el punto de código
suplementario que representa. Recuperaría más (un emoji o un ideograma raro
saldría bien en vez de dos U+FFFD) y cabría de sobra (4 bytes donde ya se
reservan 6). Lo dejé fuera para que el parche sea una sola cosa verificable, y lo
ofrecí como seguimiento en el PR.

## Resultado

| plano | antes | después |
|---|---|---|
| `Platte.dwg` | UTF-8 inválido | **válido** |
| `Stahl.dwg` | UTF-8 inválido | **válido** |
| `Teile.dwg` | UTF-8 inválido | **válido** |
| `xx17.dwg` | UTF-8 inválido | **válido** |
| `test-trichter.dwg` | válido | válido, **idéntico byte a byte** |

Los cuatro difieren en **exactamente 6 bytes cada uno** — los dos surrogados.

## Verificación

- `make check`: **270 PASS / 0 FAIL / 0 SKIP**. `bit_convert_TU` tiene test
  unitario; sus datos son solo del BMP, así que no se toca.
- Los **146** DWG de `test/test-data` y `programs/`: **146 idénticos byte a
  byte**. Ninguno lleva un surrogado.
- Tres de esos 146 **sí** emiten UTF-8 inválido y el parche los deja en paz a
  propósito: `example_2000`, `example_r13` y `2000/TS1` escriben el signo de
  grados como el byte suelto `0xB0`. Son `$ACADVER AC1015` con `$DWGCODEPAGE
  ANSI_1252`, y un DXF pre-R2007 va en la página de códigos del dibujo, no en
  UTF-8 — así que ahí `0xB0` es correcto. La regla que impone este parche es solo
  sobre las conversiones UTF-16.
- Compilado y probado sobre un `e405fcff` **limpio** con este parche solo.

## Un error de medición que conviene recordar

Casi reporté 15 nombres «corruptos» que estaban bien. La lección: **cuando el
criterio depende de cómo yo decodifico los bytes, el criterio es sospechoso.**
`iconv -f UTF-8` no opina; o el archivo es UTF-8 válido o no lo es. Igual que con
el #523, donde la medida indirecta decía «mejora» y el render decía «empeora».
