# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Join a dwg_bench CSV (LibreDWG) with an oda_classify CSV (ODA) per file.

Both CSVs were produced with the same loader and the same categories, so the
comparison is honest. Files are bucketed:

    PARITY        both OK and entity counts within tolerance
    ODA_BETTER    ODA OK where LibreDWG fails, or reads >tol more entities
    LDWG_BETTER   the reverse
    BOTH_FAIL     neither converter yields a usable drawing
    COUNT_DIFF    both OK but counts differ beyond tolerance (triage list)

Tolerance: 0.5%% relative or 2 entities absolute, whichever is larger —
up-conversion to ACAD2018 legitimately splits/merges a handful of entities.

Usage:
    python tools/oda_vs_libredwg.py <libredwg.csv> <oda.csv> [--out diff.csv]
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

FAIL_CATS = {"SEGFAULT", "TIMEOUT", "NO_OUTPUT", "LOAD_FAIL", "EMPTY_SALVAGE",
             "ODA_FAIL", "HARNESS_ERROR"}
OK_CATS = {"OK", "PAPERSPACE_ONLY", "EMPTY"}


def tol(a: int, b: int) -> bool:
    big = max(a, b)
    return abs(a - b) <= max(2, big * 0.005)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("libredwg_csv", type=Path)
    ap.add_argument("oda_csv", type=Path)
    ap.add_argument("--out", type=Path, default=Path("oda_vs_libredwg.csv"))
    args = ap.parse_args()

    ldwg = {r["file"]: r for r in csv.DictReader(open(args.libredwg_csv))}
    oda = {r["file"]: r for r in csv.DictReader(open(args.oda_csv))}
    common = sorted(set(ldwg) & set(oda))
    print(f"libredwg {len(ldwg)}, oda {len(oda)}, common {len(common)}")

    buckets: dict[str, list] = {}
    rows = []
    for f in common:
        l, o = ldwg[f], oda[f]
        lc, oc = l["category"], o["category"]
        le, oe = int(l["entities"]), int(o["entities"])
        l_ok, o_ok = lc in OK_CATS, oc in OK_CATS
        if l_ok and o_ok:
            if tol(le, oe):
                b = "PARITY"
            elif oe > le:
                b = "ODA_BETTER" if le == 0 else "COUNT_DIFF_ODA"
            else:
                b = "LDWG_BETTER" if oe == 0 else "COUNT_DIFF_LDWG"
        elif o_ok and not l_ok:
            b = "ODA_BETTER"
        elif l_ok and not o_ok:
            b = "LDWG_BETTER"
        else:
            b = "BOTH_FAIL"
        buckets.setdefault(b, []).append(f)
        rows.append({"file": f, "bucket": b, "ldwg_cat": lc, "oda_cat": oc,
                     "ldwg_entities": le, "oda_entities": oe,
                     "delta": oe - le,
                     "ldwg_sig": l["signature"][:80],
                     "oda_sig": o["signature"][:80]})

    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print()
    for b in sorted(buckets, key=lambda k: -len(buckets[k])):
        print(f"{b:16} {len(buckets[b]):5}")
    print()
    for b in ("ODA_BETTER", "COUNT_DIFF_ODA", "LDWG_BETTER", "COUNT_DIFF_LDWG"):
        for f in buckets.get(b, [])[:25]:
            r = next(x for x in rows if x["file"] == f)
            print(f"[{b}] {f}: ldwg {r['ldwg_cat']}/{r['ldwg_entities']} "
                  f"vs oda {r['oda_cat']}/{r['oda_entities']}  {r['ldwg_sig'] or r['oda_sig']}")
    return 0


if __name__ == "__main__":
    return_code = main()
    raise SystemExit(return_code)
