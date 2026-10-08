"""Replay a historical window through the REAL engines (main bot + C3+D sleeve) and the REAL dashboard, then take screenshots.

Nothing is simulated by a separate model: candles/prices come from the research data (1-minute bars,
high_cagr/prepared*), the bot's Engine.scan/watchdog and the sleeve's scan/watchdog run exactly as in production, only the
clock is controlled. Prices are the 1-minute close (the live bot polls the last price every 15 s), so intraday wicks between
minutes are not seen; funding is not charged. Paper account 10 000 USDT shared by both strategies.

  python replay_demo.py 2026-09-15 3 out_dir     # start date (UTC), days, output directory
"""
from __future__ import annotations
import glob,json,math,os,sys,tempfile,threading,time as _time
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent;sys.path.insert(0,str(HERE))
START_MS=int(pd.Timestamp('2021-10-05',tz='UTC').timestamp()*1000)

class Clock:
    t=0.
    def time(self):return self.t
    def monotonic(self):return self.t
    def sleep(self,s):pass
    def __getattr__(self,n):return getattr(_time,n)
clock=Clock()

def load_prices(symbols):
    out={}
    for s in symbols:
        folder=s.split('/')[0]+'USDT'
        for base in ('prepared','prepared_stage2'):
            f=ROOT/'high_cagr'/base/folder/'prices.npy'
            if f.exists():out[s]=np.load(f,mmap_mode='r');break
        else:raise FileNotFoundError(folder)
    return out

def make_data(prices):
    import lbank_bot as lb
    class ReplayData(lb.MarketData):
        mode='replay'
        def __init__(self):self.lock=threading.RLock();self.cache={};self.exchange=None;self.loaded=True
        def minute(self):return int((clock.t*1000-START_MS)//60000)
        def market(self,symbol):
            if symbol not in prices:raise ValueError(f'No replay data for {symbol}')
            return {'symbol':symbol,'swap':True,'linear':True,'settle':'USDT','contractSize':1.0,'active':True,'limits':{'amount':{'min':1e-6},'cost':{'min':0.0}}}
        def price(self,symbol,cached=False):self.market(symbol);return float(prices[symbol][self.minute()-1,3])
        def precision(self,symbol,q):return math.floor(q*1e6)/1e6
        def funding_mean(self,*a,**k):return None
        def book_fill(self,*a,**k):return None
        def candles(self,symbol,timeframe,limit):
            self.market(symbol);m=lb.TIMEFRAMES[timeframe]//60;i=self.minute();k=i//m;p=prices[symbol]
            lo=max(0,k-limit+1);x=np.asarray(p[lo*m:k*m]).reshape(-1,m,4);ts=START_MS+(np.arange(lo,k))*m*60000
            rows=np.column_stack([ts,x[:,0,0],x[:,:,1].max(1),x[:,:,2].min(1),x[:,-1,3],np.full(len(ts),100.)]).tolist()
            if i>k*m:y=np.asarray(p[k*m:i]);rows.append([START_MS+k*m*60000,float(y[0,0]),float(y[:,1].max()),float(y[:,2].min()),float(y[-1,3]),100.])   # forming candle
            else:o=float(p[k*m,0]);rows.append([START_MS+k*m*60000,o,o,o,o,100.])   # the new candle exists from its first tick (open price only)
            return rows[-limit:]
    return ReplayData()

def main():
    start,days,out=sys.argv[1],int(sys.argv[2]),Path(sys.argv[3]);out.mkdir(parents=True,exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix='replay_'));os.environ.update(BOT_PIN='1234',BOT_CONFIG=str(work/'config.json'),BOT_DB=str(work/'bot.db'),C3_CONFIG=str(work/'c3_config.json'),C3_DB=str(work/'c3.db'),PAPER_EQUITY='10000')
    import lbank_bot as lb,c3_sleeve as C,dashboard_server as ds
    lb.time=C.time=ds.time=clock
    cfg=json.loads((HERE/'config.json').read_text());c3cfg=json.loads((HERE/'c3_config.json').read_text())
    data=make_data(load_prices(cfg['symbols']+c3cfg['symbols']))
    engine=lb.Engine(lb.ConfigStore(),lb.Database(),data,paper_equity=10000)
    C.prepare_config(Path(os.environ['C3_CONFIG']),HERE/'c3_config.json');store=C.Store(Path(os.environ['C3_DB']))
    sleeve=C.Sleeve(C.load(Path(os.environ['C3_CONFIG'])),store,data,base_equity=engine.paper_equity)
    T0=int(pd.Timestamp(start,tz='UTC').timestamp());T1=T0+days*86400
    import uvicorn
    server=uvicorn.Server(uvicorn.Config(ds.create_app(engine),host='127.0.0.1',port=8767,log_level='warning'));threading.Thread(target=server.run,daemon=True).start();_time.sleep(2)
    from playwright.sync_api import sync_playwright
    pw=sync_playwright().start();browser=pw.chromium.launch(executable_path=glob.glob('/opt/pw-browsers/chromium-*/chrome-linux*/chrome')[0],args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1300,'height':900});page.goto('http://127.0.0.1:8767/')
    clock.t=T0;page.fill('#pin','1234');page.click('#connect');page.wait_for_timeout(1500)
    marks={int(h*3600):f'{n:02d}' for n,h in enumerate((1,10,22,34,48,60,days*24),1)}
    shots=[];series=[];times=sorted(set(range(T0+60,T1+1,60))|{b+3 for b in range(T0//14400*14400,T1+1,14400) if T0<b+3<=T1})
    def stamp():return pd.Timestamp(clock.t,unit='s',tz='UTC').strftime('%Y-%m-%d %H:%M UTC')
    def shoot(name,view='all',full=False,sel=None):
        page.evaluate("()=>{if(!window.__t0){window.__t0=1}}");page.click(f'button[data-view={view}]')
        page.evaluate("async()=>{await refresh();await refreshC3();}");page.wait_for_timeout(400)
        page.evaluate("([t,n])=>{document.querySelector('.note').textContent='بازپخش تاریخی با داده واقعی بازار روی موتور واقعی ربات و C3+D (فقط شبیه‌سازی). زمان شبیه‌سازی: '+t;document.getElementById('updated').textContent='زمان شبیه‌سازی: '+t;}",[stamp(),name])
        target=page.locator(sel) if sel else None;path=out/f'{name}.png'
        if target:target.screenshot(path=str(path))
        else:
            box=page.locator('#positions').evaluate("e=>{const r=e.closest('section').getBoundingClientRect();return r.bottom+window.scrollY+16}");page.screenshot(path=str(path),full_page=True,clip={'x':0,'y':0,'width':1300,'height':box})
        shots.append(path.name);print('shot',path.name,stamp(),flush=True)
    last=None
    for t in times:
        clock.t=float(t);engine.watchdog();sleeve.watchdog(clock.t)
        if t%14400==3:
            engine.scan(clock.t);sleeve.scan(clock.t)
        if t%900==0:
            e=engine.paper_equity();s=C.summary(store,sleeve.c,lambda x:data.price(x),e);series.append((t,e-10000,(s['equity_usd']-e) if s['equity_usd'] else 0.))
        k=t-T0
        if k in marks:shoot(f'screen_{marks[k]}_{stamp()[:13].replace(" ","_").replace(":","")}h')
    for v,nm in (('bot','final_bot_only'),('c3','final_c3_only')):shoot(nm,v)
    page.click('button[data-view=all]');page.evaluate("()=>{document.querySelectorAll('details').forEach(d=>d.open=true)}");shoot('final_c3_panel_and_history','all',sel='#c3panel')
    browser.close();pw.stop()
    import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
    a=np.array(series);x=pd.to_datetime(a[:,0],unit='s');fig,ax=plt.subplots(figsize=(11,4.6))
    ax.plot(x,a[:,1],label='Main bot',c='#4e79ff');ax.plot(x,a[:,2],label='C3+D',c='#c06bff');ax.plot(x,a[:,1]+a[:,2],label='Both',c='k',lw=2);ax.axhline(0,c='gray',lw=.6)
    ax.set_title(f'Cumulative P&L, paper account 10,000 USDT - replay from {start} ({days} days)');ax.set_ylabel('USDT (incl. open)');ax.legend();ax.grid(alpha=.3);fig.autofmt_xdate();fig.tight_layout();fig.savefig(out/'pnl_curve.png',dpi=110)
    with lb.Database().connect() as db:bt=db.execute('SELECT symbol,side,pnl_usd FROM trade_history ORDER BY rowid').fetchall()
    with store.db() as db:ct=db.execute('SELECT symbol,side,pnl,reason FROM trades ORDER BY id').fetchall()
    summary=dict(start=start,days=days,bot_closed=len(bt),bot_pnl_closed=sum(r[2] for r in bt),c3_closed=len(ct),c3_pnl_closed=sum(r[2] for r in ct),bot_open=len(engine.db.positions()),c3_open=len(store.positions()),final=series[-1],shots=shots)
    (out/'summary.json').write_text(json.dumps(summary,indent=1,default=float));print(json.dumps(summary,indent=1,default=float))
if __name__=='__main__':main()
