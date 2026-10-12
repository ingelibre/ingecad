"""Exercise the installed JSON worker, not just imports."""
import json
from pathlib import Path
import sys

root=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(root))
from client import analyze
from model import benchmark
result=analyze(benchmark(),python=sys.argv[2] if len(sys.argv)>2 else None)
case=result['cases']['LC1']
checks={'left_reaction':abs(case['nodes']['N1']['Rz']-30.)<1e-8,
        'right_reaction':abs(case['nodes']['N2']['Rz']-30.)<1e-8,
        'moment':abs(case['members']['B1']['extrema']['M']['min']['value']+45.)<1e-8,
        'deflection':abs(case['members']['B1']['extrema']['d']['min']['value']+.010546875)<1e-10,
        'schema':result['result_schema']==2,'solver':result['version']=='3.2.0'}
print(json.dumps({'status':'Passed' if all(checks.values()) else 'Failed','python':sys.version.split()[0],'solver':result['version'],'checks':checks}))
if not all(checks.values()): raise SystemExit(1)
