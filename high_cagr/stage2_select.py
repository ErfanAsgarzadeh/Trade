"""Apply the declared stage-2 selection rule (liquidity at the start only)."""
from pathlib import Path
import sys,json,io,zipfile,re,urllib.request,concurrent.futures,time
import ccxt
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'high_cagr/output'
S3='https://s3-ap-northeast-1.amazonaws.com/data.binance.vision';BASE='https://data.binance.vision/'
EXCLUDE={'BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','ADAUSDT','BNBUSDT','DEFIUSDT','BLUEBIRDUSDT','FOOTBALLUSDT'}
STABLE={'USDC','BUSD','TUSD','FDUSD','USDP','DAI'}
def get(url):
    for k in range(5):
        try:return urllib.request.urlopen(url,timeout=60).read()
        except Exception:
            if k==4:raise
            time.sleep(2*(k+1))
def listing(prefix):
    keys,marker=[],''
    while True:
        x=get(f'{S3}?delimiter=/&prefix={prefix}&marker={marker}').decode()
        keys+=re.findall(r'<Prefix>([^<]+)</Prefix>',x)[1:] or [];keys+=re.findall(r'<Key>([^<]+)</Key>',x)
        if '<IsTruncated>true</IsTruncated>' not in x:return keys
        marker=re.search(r'<NextMarker>([^<]+)</NextMarker>',x).group(1)
def sep2021_volume(sym):
    try:raw=get(f'{BASE}data/futures/um/monthly/klines/{sym}/1d/{sym}-1d-2021-09.zip')
    except Exception:return sym,None
    with zipfile.ZipFile(io.BytesIO(raw)) as z:lines=z.read(z.namelist()[0]).decode().splitlines()
    return sym,sum(float(l.split(',')[7]) for l in lines if l[:1].isdigit())
def months_complete(sym):
    keys=set(k.rsplit('/',1)[-1] for k in listing(f'data/futures/um/monthly/klines/{sym}/1m/'))
    need=[f'{sym}-1m-{y}-{m:02d}.zip' for y in range(2021,2027) for m in range(1,13) if (2021,10)<=(y,m)<=(2026,9)]
    days=set(k.rsplit('/',1)[-1] for k in listing(f'data/futures/um/daily/klines/{sym}/1m/'))
    return all(n in keys for n in need) and all(f'{sym}-1m-2026-10-0{d}.zip' in days for d in range(1,5))
def main():
    syms=[p.rstrip('/').rsplit('/',1)[-1] for p in listing('data/futures/um/monthly/klines/')]
    cands=[s for s in syms if s.endswith('USDT') and s not in EXCLUDE and s[:-4] not in STABLE]
    print('USDT perps listed:',len(cands),flush=True)
    with concurrent.futures.ThreadPoolExecutor(16) as pool:vols=dict(pool.map(sep2021_volume,cands))
    ranked=sorted([(v,s) for s,v in vols.items() if v],reverse=True);print('traded in 2021-09:',len(ranked),flush=True)
    ex=ccxt.lbank({'options':{'defaultType':'swap'}});ex.requests_trust_env=True;ex.session.trust_env=True;ex.load_markets()
    lbank={m['base']+m['quote'] for m in ex.markets.values() if m.get('swap') and m.get('linear') and m.get('settle')=='USDT' and m.get('active') is not False}
    chosen,skipped=[],[]
    for v,s in ranked:
        if len(chosen)==10:break
        base=s[:-4];alias={base,base.replace('1000','')}
        if not any(a+'USDT' in lbank for a in alias):skipped.append((s,'not on LBank'));continue
        if not months_complete(s):skipped.append((s,'incomplete 1m history to 2026-10-04'));continue
        chosen.append(dict(symbol=s,sep2021_quote_volume=v))
        print('PICK',len(chosen),s,f'{v/1e9:.1f}B',flush=True)
    result=dict(rule='see predeclared_stage2_universe.json',chosen=chosen,skipped_before_10th=skipped,ranked_top40=[dict(symbol=s,sep2021_quote_volume=v) for v,s in ranked[:40]])
    (OUT/'stage2_selection.json').write_text(json.dumps(result,indent=1));print('skipped:',skipped)
if __name__=='__main__':main()
