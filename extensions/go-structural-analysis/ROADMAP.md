# GO Structural Analysis — v0.1.3 delivery

This release extends the existing v0.1 project and user plugin. Original evidence
and source/plugin backups are retained; the host core and Program Files are unchanged.

| Milestone | Implementation | Executed verification |
|---|---|---|
| v0.1.1 Engineering visualization | Support/release/load symbols, N/V/M/D, deformation, scales, labels, legend, world projection | Live viewport captures, camera transform and picking checks |
| v0.1.2 Result inspector | Member selection, exact x/L with left/right values, four tables, five CSV files, stale results | Automated evaluation/CSV tests and live viewport/editor/save/load/history checks |
| v0.1.3 Solver verification | Segment polynomial extrema, reference benchmarks, sparse LU stability and equilibrium guards, cases/self-weight, material presets | 90 pytest cases, original 19 regression cases included, actual reference comparisons in JSON |

See `TEST_RESULTS_v0.1.3.md` for Passed / Failed / Not Tested and remaining
environment checks. Cold process restart, physical mouse input and an actual
Windows theme change were not executed. Preserve those qualifications when
sharing the release; do not label these checks Passed.

The solver adapter is intentionally pinned to PyNiteFEA 3.2.0. Updating that pin
requires repeating the continuous-segment, transformation, release and load-jump
benchmarks. Nonlinear analysis, combinations and design-code checks are outside
this release's scope.
