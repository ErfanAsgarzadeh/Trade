"""Family 1 of PREDECLARED.md: exit-management grid on the shipped ledger, shared-account replay."""
from pathlib import Path
import sys,json,itertools
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.winrate import ledger as LG, exits as E
def grid():
    v={}
    for a,k in itertools.product((.5,.75,1.,1.5,2.),(0.,.1,.3,.5)):
        if k<a:v[f'lock{a}->{k}']=dict(arm=a,lock=k)
    for t in (1.,1.5,2.):
        v[f'half@{t}']=dict(pfrac=.5,ptarget=t);v[f'half@{t}+lock1->0.1']=dict(pfrac=.5,ptarget=t,arm=1.,lock=.1)
    return v
def main():
    legs=LG.raw_legs();res={'baseline':E.account_stats(E.replay_legs(legs))};b=res['baseline']
    print('BASE',json.dumps(b));fmt=lambda r:f"WR tr {r['win_rate']['train']:.1f} va {r['win_rate']['valid']:.1f} | Calmar tr {r['train'][0]:.2f} va {r['valid'][0]:.2f} | CAGR {r['cagr']:.1f} DD {r['dd']:.1f} PF {r['pf']:.2f}"
    for scope in (('main','c3','pa'),('main',),('c3',),('pa',)):
        for name,kw in grid().items():
            L,n=E.modified_legs(legs,bots=scope,**kw);r=E.account_stats(E.replay_legs(L));r['changed']=n
            key='+'.join(scope)+'|'+name;res[key]=r;print(key,fmt(r),'changed',n,flush=True)
    (LG.OUT/'exits.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
