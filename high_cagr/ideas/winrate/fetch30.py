"""Download (SHA-256 verified) and prepare the 30 non-main coins used by Mojsavar (MAIN10) and Ghoghnous (OTHER20),
with the same code as high_cagr/stage2_data.py, so the three-bot ledgers can be rebuilt offline."""
from pathlib import Path
import sys,json,concurrent.futures
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from high_cagr import stage2_data as S
# xuni.NEW + holdout_test.H10 + holdout_test.H2 (copied to avoid importing numba engines)
COINS=['AVAXUSDT','DOTUSDT','ATOMUSDT','FILUSDT','DOGEUSDT','LTCUSDT','AXSUSDT','LINKUSDT','XTZUSDT','ALGOUSDT',
       'ETCUSDT','NEARUSDT','TRXUSDT','CELRUSDT','BCHUSDT','UNIUSDT','ALICEUSDT','SUSHIUSDT','C98USDT','1000SHIBUSDT',
       'THETAUSDT','EGLDUSDT','AAVEUSDT','IOSTUSDT','ONEUSDT','CVCUSDT','CRVUSDT','IOTAUSDT','KSMUSDT','VETUSDT']
def main():
    todo=[s for s in COINS if not (S.PREP/s/'manifest.json').exists()]
    rels=[r for s in todo for r in S.files(s)];print('files',len(rels),flush=True);man=[]
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        for k,(rel,sha,how) in enumerate(pool.map(S.fetch,rels)):
            man.append(dict(file=rel,sha256=sha))
            if k%200==0:print('verified',k,flush=True)
    for s in todo:
        info=S.prepare(s,man);print('PREPARED',s,'missing',info['missing_minutes_in_test'],flush=True)
if __name__=='__main__':main()
