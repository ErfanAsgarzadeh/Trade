"""Holdout symbols: continue the stage-2 liquidity ranking (rule in predeclared_round2.json, part C)."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from high_cagr import stage2_select as s2
import ccxt
OUT=ROOT/'high_cagr/output'
def main():
    prev=json.loads((OUT/'stage2_selection.json').read_text());used={c['symbol'] for c in prev['chosen']}|{x[0] for x in prev['skipped_before_10th']}
    syms=[p.rstrip('/').rsplit('/',1)[-1] for p in s2.listing('data/futures/um/monthly/klines/')]
    cands=[s for s in syms if s.endswith('USDT') and s not in s2.EXCLUDE and s[:-4] not in s2.STABLE and s not in used]
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(16) as pool:vols=dict(pool.map(s2.sep2021_volume,cands))
    ranked=sorted([(v,s) for s,v in vols.items() if v],reverse=True)
    ex=ccxt.lbank({'options':{'defaultType':'swap'}});ex.requests_trust_env=True;ex.session.trust_env=True;ex.load_markets()
    lbank={m['base']+m['quote'] for m in ex.markets.values() if m.get('swap') and m.get('linear') and m.get('settle')=='USDT' and m.get('active') is not False}
    chosen,skipped=[],[]
    for v,s in ranked:
        if len(chosen)==10:break
        base=s[:-4]
        if not any(a+'USDT' in lbank for a in {base,base.replace('1000','')}):skipped.append((s,'not on LBank'));continue
        if not s2.months_complete(s):skipped.append((s,'incomplete history'));continue
        if not all(s2.listing(f'data/futures/um/monthly/klines/{s}/1m/{s}-1m-2021-{m:02d}.zip') for m in (8,9)):skipped.append((s,'no 2021-08/09 warm-up'));continue
        chosen.append(dict(symbol=s,sep2021_quote_volume=v));print('PICK',len(chosen),s,flush=True)
    (OUT/'stage3_selection.json').write_text(json.dumps(dict(chosen=chosen,skipped=skipped),indent=1));print('skipped',skipped)
if __name__=='__main__':main()
