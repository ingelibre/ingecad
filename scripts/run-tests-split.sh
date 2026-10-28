#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Run the test suite in N processes, each under its own Xvfb, as the CI does.
#
# One process for the whole suite grows slower test after test: what one
# test leaves alive slows the next, and v0.6.5's tag build spent 213 min in
# its Tests step (v0.6.4: 63) and then failed a timing test. Locally the
# suite has always run in four processes; this is that, for CI.
#
#   scripts/run-tests-split.sh [python] [processes]
#
# Test files are dealt round-robin, so the slow families (topography,
# layouts, viewports) spread over every process. Exit status: non-zero if
# any part failed; every part's log is printed at the end.
set -uo pipefail

PY=${1:-python}
N=${2:-4}
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cd "$ROOT"

ls tests/test_*.py | split -n "r/$N" - "$WORK/part_"

# TESTS_GDB=1: each part runs under gdb, which prints every thread's
# NATIVE stack if the interpreter dies (faulthandler only shows the Python
# frames, and the CI's segfaults stopped at processEvents). Signals other
# than the fatal ones pass straight through.
RUN=()
VERBOSE=-q
if [ "${TESTS_GDB:-0}" = 1 ] && command -v gdb >/dev/null; then
    # gdb stops the process before faulthandler prints the Python stack:
    # one line per test names the one that was running
    VERBOSE=-v
    RUN=(gdb -q -batch -return-child-result
         -ex "set pagination off"
         -ex "handle all nostop noprint pass"
         -ex "handle SIGSEGV stop print nopass"
         -ex "handle SIGBUS stop print nopass"
         -ex "handle SIGABRT stop print nopass"
         -ex run -ex "thread apply all bt 40" --args)
fi

pids=()
i=0
for part in "$WORK"/part_*; do
    i=$((i + 1))
    if command -v xvfb-run >/dev/null; then
        # -n: a server number per part; -a would race between parallel starts
        xvfb-run -n $((90 + i)) -s "-screen 0 1600x1000x24" \
            "${RUN[@]}" "$PY" -m pytest "$VERBOSE" -p no:cacheprovider $(cat "$part") \
            > "$part.log" 2>&1 &
    else
        # no Xvfb (a developer's desktop): tests/conftest.py picks offscreen
        "$PY" -m pytest -q -p no:cacheprovider $(cat "$part") \
            > "$part.log" 2>&1 &
    fi
    pids+=($!)
done

status=0
for pid in "${pids[@]}"; do
    wait "$pid" || status=1
done

for log in "$WORK"/part_*.log; do
    echo "::group::$(basename "$log" .log)"
    cat "$log"
    echo "::endgroup::"
    tail -1 "$log"
done
exit $status
