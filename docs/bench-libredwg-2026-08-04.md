# Bench LibreDWG — 2026-08-04

Barrido completo del corpus con **LibreDWG 0.14.8556 sin parches**
(`tools/dwg_bench.py`, informe en `~/Proyectos/externos/bench/`).

## Resultado

**1657 planos reales · 19 140 756 entidades convertidas · 111 min de CPU**
(mediana 1,1 s por plano).

| Categoría | Planos | % |
|---|---:|---:|
| OK | 1601 | 96,6 % |
| PAPERSPACE_ONLY | 26 | 1,6 % |
| **→ utilizables** | **1627** | **98,2 %** |
| LOAD_FAIL | 11 | 0,7 % |
| EMPTY_SALVAGE | 10 | 0,6 % |
| EMPTY | 6 | 0,4 % |
| NO_OUTPUT | 3 | 0,2 % |

El corpus son los DWG del archivo personal en pCloud: 2373 archivos, 1645
únicos tras descartar duplicados por (nombre, tamaño) — la mitad de los
repetidos venían del `pCloud Backup` que replica el propio disco.

## Comparación con la versión parcheada

Sobre los mismos 502 planos, `0.14 + 29 parches` contra `0.14.8556` limpio:
categorías **idénticas** (492 OK en ambas), **0** planos pierden entidades,
**23 recuperan más** (+283 en total), mismo tiempo. Esa es la prueba de que
el stack de parches podía retirarse — no «se ve bien», sino «ningún archivo
empeoró».

## Las 9 causas que quedan

24 planos fallan, con solo 9 firmas distintas. **15 de los 24 son archivos de
prueba del propio LibreDWG**, que entraron al corpus a través del respaldo del
disco: son públicos, minúsculos y ya viven en el repo de upstream, así que la
siguiente tanda de reportes **no necesita ningún plano de cliente**.

| Nº | Firma | Origen |
|---:|---|---|
| 5 | `DXFStructureError: Expected DXF entity LWPOLYLINE or SEQEND` | `examples/example_{2004,2007,2010,2013,2018}_new.dwg` |
| 7 | `EMPTY_SALVAGE` sin mensaje | 6× `test-data/*/Helix.dwg`, `PolyLine2D.dwg` + 1 propio |
| 3 | `DXFStructureError: Expected DXF entity JUMP or SEQEND` | `programs/entities_r10.dwg`, `entities.dwg` ×2 |
| 2 | `ERROR: Invalid FIELD.num_childval 805822470` | planos propios (2,2 y 2,3 MB) |
| 2 | `READ ERROR 0x101` | planos propios (0,1 MB) |
| 2 | `expected BLOCK_RECORD(#2) for layout 'Model'` | planos propios (11,3 y 4,0 MB) |
| 1 | `Invalid DXF attribute "paperspace" for entity LAYOUT` | plano propio (7,0 MB) |
| 1 | `READ ERROR 0x800` | plano propio (1,1 MB) |
| 1 | `ERROR: Preview overflow 27176 + 119 > 27279` | `test-data/*/Helix.dwg` |

### Diagnóstico de los tres primeros (2026-08-05)

Resultaron ser **tres bugs distintos**, no uno:

1. **`INSERT` con `66 1` sin `ATTRIB` ni `SEQEND`** (5 fallos, los `example_*_new.dwg`).
   Reportado: [LibreDWG#1351](https://github.com/LibreDWG/libredwg/issues/1351).
   El DWG sí trae el `ATTRIB` y el `SEQEND`; lo que está roto es la cadena:
   `has_attribs=1` y `seqend` válido, pero `first_attrib`/`last_attrib` nulos. En
   `out_dxf.c:2939` (rama r2000) eso provoca un `return` **después** de haber escrito
   el `INSERT` con su `66 1` y **antes** de emitir el `SEQEND`. La rama de r2004+ no
   tiene el problema. Ojo: los archivos se llaman `_2018` pero son **AC1015 (r2000)**.
2. **`66 = 128`** en un `INSERT` pre-R13 — el indicador solo admite 0 o 1. Sin reportar.
3. **Registros `JUMP` que se cuelan** en la sección `ENTITIES` del DXF (pre-R13);
   `JUMP` no es una entidad DXF, es un marcador interno de los DWG R11/R12. Rompe la
   secuencia `POLYLINE VERTEX… SEQEND`. Sin reportar.

Reproducir el nº 1 no necesita ningún archivo: `dwgadd -o x.dwg examples/dwgadd.example`
y luego `dwg2dxf`.

## Reproducir

```sh
python3 tools/dwg_bench.py ~/Proyectos/externos/corpus-dwg --workers 6 \
    --out informe.csv
# y para comparar dos compilaciones sobre el mismo corpus:
python3 tools/dwg_bench.py <corpus> --dwg2dxf <otra-build>/bin/dwg2dxf --out otro.csv
```

Ojo al copiar el corpus desde pCloud: **de uno en uno y un solo hilo**. Leer en
paralelo sobre FUSE es lo que dejó procesos en estado D el 2026-08-03. A 4 MB/s
son unos 40 min para 6,8 GB.
