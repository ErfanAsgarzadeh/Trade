"""Build the public five-year marketing snapshot from the frozen replay output.

This reproduces aggregation/serialization, not the minute execution backtest.
A bounded, inspectable daily CSV is shipped with the frontend; no client or
private account information is part of this dataset.
"""
import argparse
import calendar
import csv
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SEED=10000.0
START='2021-01-01'
END='2025-12-31'
ORIGINAL_SHA='7fb17a785e0df92f0336bf006eaf065eb71441a18e8ee28237c4c2ec21c35c9f'
ENGINE_SHA='c85965e5d5476b9656357cfd6a575841dd777087de51570048ba800c44b87240'


def build(source):
    raw_hash=hashlib.sha256(Path(source).read_bytes()).hexdigest()
    previous=ROOT/'public/backtest/five-year-summary.json'
    known={ORIGINAL_SHA}
    if previous.exists():known.add(json.loads(previous.read_text())['provenance']['public_csv_sha256'])
    if raw_hash not in known:raise ValueError('Unreviewed replay input; review provenance before updating this public snapshot')
    rows=[]
    with Path(source).open(newline='') as stream:
        for raw in csv.DictReader(stream):
            stamp=raw.get('date') or raw.get('')
            if START<=stamp[:10]<=END:
                rows.append(dict(date=stamp,equity=float(raw.get('equity',raw.get('day_close_equity'))),
                                 worst_minute_dd_pct=float(raw['worst_minute_dd_pct'])))
    assert len(rows)==1826 and rows[0]['date'][:10]==START and rows[-1]['date'][:10]==END
    assert len({r['date'][:10] for r in rows})==1826
    import math
    assert all(math.isfinite(r['equity']) and r['equity']>0 and -100<=r['worst_minute_dd_pct']<=0 for r in rows)
    text=io.StringIO(newline='');writer=csv.DictWriter(text,fieldnames=['date','equity','worst_minute_dd_pct'],lineterminator='\n');writer.writeheader();writer.writerows(rows)
    csv_bytes=text.getvalue().encode();(ROOT/'public/backtest/five-year-daily.csv').write_bytes(csv_bytes)
    monthly=[];previous=SEED
    for year in range(2021,2026):
        for month in range(1,13):
            end=f'{year}-{month:02}-{calendar.monthrange(year,month)[1]}'
            row=next(r for r in rows if r['date'][:10]==end)
            monthly.append(dict(month=end[:7],equity=row['equity'],return_pct=(row['equity']/previous-1)*100))
            previous=row['equity']
    annual=[];previous=SEED
    for year in range(2021,2026):
        row=next(r for r in rows if r['date'][:10]==f'{year}-12-31')
        annual.append(dict(year=year,equity=row['equity'],return_pct=(row['equity']/previous-1)*100));previous=row['equity']
    end=rows[-1]['equity'];dd=-min(r['worst_minute_dd_pct'] for r in rows)
    assert abs(SEED*math.prod(1+m['return_pct']/100 for m in monthly)-end)<1e-6
    result=dict(schema=1,start=START,end=END,timezone='UTC',days=len(rows),initial=SEED,final=end,
                return_pct=(end/SEED-1)*100,cagr_pct=((end/SEED)**.2-1)*100,max_minute_dd_pct=dd,
                scenario='all_three_no_f_no_withdrawals',execution='historical_simulation',currency='USD',
                daily=[[r['date'][:10],round(r['equity'],6)] for r in rows],annual=annual,monthly=monthly,
                assumptions=dict(fee_bps_per_side=6,slippage_bps_per_fill=2,leverage=5,margin_cap_pct=80,
                                 f_enabled=False,withdrawals=False,profit_reinvestment=True,usdt_usd=1),
                provenance=dict(original_replay_csv_sha256=ORIGINAL_SHA,engine_sha256=ENGINE_SHA,
                                public_csv_sha256=hashlib.sha256(csv_bytes).hexdigest(),
                                source='Frozen current_backtest/output/comparison_singles/all_daily.csv',
                                market_data='Binance USDⓈ-M futures; modeled execution, not a live LBank account',
                                curve='Daily close equity; log scale',drawdown='Worst minute-close drawdown, including initial seed'))
    encoded=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    (ROOT/'public/backtest/five-year-summary.json').write_text(encoded)
    print(json.dumps({k:result[k] for k in ('days','initial','final','return_pct','max_minute_dd_pct')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=ROOT/'public/backtest/five-year-daily.csv')
    build(parser.parse_args().source)
