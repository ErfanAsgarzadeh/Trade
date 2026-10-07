"""POST-HOC exploration (chosen after seeing single-idea results; NOT pre-declared, not a validation)."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import bench, combo
def build(ctx,v):
    pick={'idea2_atr_regime':('A',None)};kw=dict(floor_on=True,floor_trigger=1.0,floor_lock=0.1) if v['giveback'] else {}
    if v['pen']:
        import high_cagr.ideas.idea4_confirmation as m;sig=m.build(ctx,{'mode':'penetration','pen_atr':0.25})['sig']
    else:sig=bench.base_sig()
    return dict(sig=combo.apply_filters(ctx,sig,pick),kwargs=kw)
if __name__=='__main__':
    bench.run_idea('posthoc_atr_combos',{'2A+5A':dict(giveback=True,pen=False),'2A+4B+5A':dict(giveback=True,pen=True)},build,notes='POST-HOC, chosen after seeing results')
