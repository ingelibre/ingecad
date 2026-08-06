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
