# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Classify a directory of ODA-converted DXFs with dwg_bench's exact criterion.

ODAFileConverter has already turned the DWG corpus into DXF; this walks the
output and classifies each file with the same ezdxf-recover loader and the
same categories as ``dwg_bench.py``, so the two CSVs can be diffed honestly
("medir con el mismo criterio en los dos lados"). A missing DXF next to a
``.dxf.err`` file is ODA's own read failure and classified ODA_FAIL with the
first error line as signature.

Usage:
    python tools/oda_classify.py <oda_dxf_dir> <corpus_dir> [--out oda.csv]
                                 [--workers N]
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def classify_one(dxf_path_str: str, size_mb: float) -> dict:
    dxf_path = Path(dxf_path_str)
    row = {
        "file": dxf_path.with_suffix(".dwg").name,
        "size_mb": size_mb,
        "category": "?",
        "signature": "",
        "entities": 0,
        "seconds": 0.0,
    }
    t0 = time.perf_counter()
    try:
        if not dxf_path.is_file():
            err = dxf_path.with_suffix(".dxf.err")
            row["category"] = "ODA_FAIL"
            if err.is_file():
                for line in err.read_text(errors="replace").splitlines():
                    line = line.strip()
                    if line:
                        row["signature"] = line[:160]
                        break
            return row

        from ezdxf import recover

        try:
            doc, _aud = recover.readfile(dxf_path)
        except Exception as exc:
            row["category"] = "LOAD_FAIL"
            row["signature"] = f"{type(exc).__name__}: {str(exc)[:140]}"
            return row

        n_msp = len(doc.modelspace())
        row["entities"] = n_msp
        if n_msp == 0:
            n_paper = max(
                (len(lay) for lay in doc.layouts if lay.name != "Model"),
                default=0,
            )
            n_blocks = sum(len(b) for b in doc.blocks
                           if not b.name.lower().startswith("*model_space"))
            if n_paper > 0 and n_blocks > 100:
                row["category"] = "PAPERSPACE_ONLY"
                row["entities"] = n_blocks
            elif len(doc.entitydb) > 100:
                row["category"] = "EMPTY_SALVAGE"
            else:
                row["category"] = "EMPTY"
        else:
            row["category"] = "OK"
        return row
    finally:
        row["seconds"] = round(time.perf_counter() - t0, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("oda_dir", type=Path)
    ap.add_argument("corpus", type=Path)
    ap.add_argument("--out", type=Path, default=Path("oda_report.csv"))
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    dwgs = sorted(set(args.corpus.rglob("*.dwg")) | set(args.corpus.rglob("*.DWG")))
    print(f"corpus: {len(dwgs)} DWGs", flush=True)

    jobs = []
    for dwg in dwgs:
        dxf = args.oda_dir / (dwg.stem + ".dxf")
        jobs.append((str(dxf), round(dwg.stat().st_size / 1e6, 1), dwg.name))

    counts: dict[str, int] = {}
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool, \
         open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh, ["file", "size_mb", "category", "signature", "entities", "seconds"])
        writer.writeheader()
        futures = {}
        for dxf, mb, name in jobs:
            fut = pool.submit(classify_one, dxf, mb)
            futures[fut] = name
        for n, fut in enumerate(as_completed(futures), 1):
            name = futures[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = {"file": name, "size_mb": 0, "category": "HARNESS_ERROR",
                       "signature": str(exc)[:140], "entities": 0, "seconds": 0}
            row["file"] = name  # keep the DWG's exact name incl. .DWG case
            counts[row["category"]] = counts.get(row["category"], 0) + 1
            writer.writerow(row)
            fh.flush()
            if n % 200 == 0:
                print(f"--- {n}/{len(jobs)} ({time.perf_counter()-t0:.0f}s) "
                      f"{counts}", flush=True)
    print(f"\nDONE in {time.perf_counter()-t0:.0f}s: {counts}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
