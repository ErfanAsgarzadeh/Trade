"""Shahin risk share in the shared account, without and with the F risk manager (walk-forward AI), from 2022-01-01.
Shahin legs = lab baseline (late-entry gate in the kernel); Mojsavar with profit lock, Ghoghnous soft. Reported, not gated."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr.ideas.frisk import evaluate as F
from high_cagr.ideas.shahin2 import lab as LB
def main():
    main_,_=LB.run(LB.MAIN5,{});O=LB.others();a=F.FOLDS['2022'][0];res={}
    for k in (1.,1.25,1.5,2.):
        legs=[dict(l,risk_scale=l['risk_scale']*k) if l['bot']=='main' else l for l in main_+O];X,y=F.features(legs);pw,diag=F.wf_score(X,y)
        for nm,c in (('no F',{}),('F walk-forward',dict(F.CTRL,g=F.gmap(pw)))):
            r=F.run(legs,c,a);res[f'{k*100:.0f}bp|{nm}']=dict(risk_pct=k,**{x:r[x] for x in ('final','cagr','dd','calmar','mworst','years','trades')},ai=diag if nm!='no F' else None)
            print(k,nm,round(r['cagr'],1),round(r['dd'],1),round(r['calmar'],2),flush=True)
    (LB.OUT/'risk_with_f.json').write_text(json.dumps(res,indent=1,default=float))
if __name__=='__main__':main()
