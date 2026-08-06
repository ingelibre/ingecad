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
