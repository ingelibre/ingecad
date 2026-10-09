"""Solver-independent exact result evaluation, freshness, hit tests and CSV."""
import csv
import hashlib
import json
import math
from pathlib import Path

VERSION='0.1.3'
UNITS={'N':'kN','V':'kN','M':'kN.m','d':'m','ux':'m','uz':'m'}

def model_hash(model):
    return hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def is_current(model,result):
    return bool(model and result and result.get('model_hash')==model_hash(model) and result.get('result_schema')==2)

def polynomial(coeff,x):
    value=0.0
    for c in reversed(coeff): value=value*x+c
    return value

def evaluate(member,x,side='right'):
    if side not in ('left','right'): raise ValueError('Inspector side must be left or right')
    L=member['L']
    if not math.isfinite(x) or x < -1e-10 or x>L+1e-10: raise ValueError('Inspector x outside member')
    x=max(0.,min(L,float(x))); segments=member['segments']
    matches=[s for s in segments if s['x1']-1e-10<=x<=s['x2']+1e-10]
    if not matches: raise ValueError('Missing result segment')
    s=matches[0] if side=='left' else matches[-1]; t=max(0.,min(s['x2']-s['x1'],x-s['x1']))
    out={key:polynomial(c,t) for key,c in s['coefficients'].items()}; out['x']=x
    bx,by=member['basis'][0],member['basis'][1]
    out['ux']=bx[0]*out['u']+by[0]*out['d']; out['uz']=bx[1]*out['u']+by[1]*out['d']
    return out

def distance_to_segment(px,py,a,b):
    dx=b[0]-a[0]; dy=b[1]-a[1]; denom=dx*dx+dy*dy
    t=max(0.,min(1.,((px-a[0])*dx+(py-a[1])*dy)/denom)) if denom else 0.
    return math.hypot(px-a[0]-t*dx,py-a[1]-t*dy),t

def pick_member(px,py,projected,tolerance=9):
    hits=[]
    for mid,a,b in projected:
        distance,t=distance_to_segment(px,py,a,b)
        if distance<=tolerance: hits.append((distance,mid,t))
    return min(hits,key=lambda h:h[0])[1:] if hits else None

def export_csv(directory,model,result,case):
    if not is_current(model,result): raise ValueError('Results out of date; Run Analysis before exporting')
    if case not in result['cases']: raise ValueError('Unknown load case')
    root=Path(directory); root.mkdir(parents=True,exist_ok=True); r=result['cases'][case]; paths=[]
    def write(name,headers,rows):
        path=root/(name+'.csv')
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream); writer.writerow(headers); writer.writerows(rows)
        paths.append(str(path))
    write('node_displacements',['Case','Node','UX [m]','UZ [m]','Rotation [rad]'],[[case,n,v['ux'],v['uz'],v['rotation']] for n,v in r['nodes'].items()])
    supports={n['id'] for n in model['nodes'] if n.get('support','Free')!='Free'}
    write('support_reactions',['Case','Node','RX [kN]','RZ [kN]','M_plane [kN.m]'],[[case,n,v['Rx'],v['Rz'],v['My']] for n,v in r['nodes'].items() if n in supports])
    write('member_end_forces',['Case','Member','End','FX_local [kN]','FY_local [kN]','MZ_local [kN.m]'],[[case,mid,end,v['N'],v['V'],v['M']] for mid,m in r['members'].items() for end,v in m['end_forces'].items()])
    write('member_extrema',['Case','Member','Quantity','Unit','Extremum','x [m]','x/L [-]','Side','Value'],[[case,mid,k,UNITS[k],kind,v['x'],v['x']/m['L'],v['side'],v['value']] for mid,m in r['members'].items() for k,e in m['extrema'].items() for kind,v in e.items()])
    write('member_diagrams',['Case','Member','x [m]','Side','N [kN]','V [kN]','M [kN.m]','D_local [m]','UX [m]','UZ [m]'],[[case,mid,p['x'],p.get('side','right'),p['N'],p['V'],p['M'],p['d'],p['ux'],p['uz']] for mid,m in r['members'].items() for p in m['plot']])
    return paths
