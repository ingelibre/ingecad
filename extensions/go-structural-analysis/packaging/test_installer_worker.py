"""Run using the installer runtime against the isolated installed plugin."""
import json
from pathlib import Path
import sys
root=Path(sys.argv[1]); sys.path.insert(0,str(root))
from examples import CATALOG,example
from client import analyze
checks=[]
for key,title,_ in CATALOG:
    try:
        result=analyze(example(key))
        passed=not key.startswith('unstable') and result['version']=='3.2.0'
        checks.append({'key':key,'status':'Passed' if passed else 'Failed','expected':'success'})
    except RuntimeError as exc:
        passed=key.startswith('unstable') and ('unstable' in str(exc).lower() or 'singular' in str(exc).lower())
        checks.append({'key':key,'status':'Passed' if passed else 'Failed','expected':'unstable rejection','message':str(exc)})
report={'python':sys.version.split()[0],'prefix':sys.base_prefix,'checks':checks,'passed':sum(v['status']=='Passed' for v in checks),'failed':sum(v['status']=='Failed' for v in checks)}
Path(sys.argv[2]).write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'passed':report['passed'],'failed':report['failed'],'prefix':report['prefix']}))
if report['failed']: raise SystemExit(1)
