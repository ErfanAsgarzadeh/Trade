"""Persian HTML/PDF report for criteria_study.py and live_monitor_study.py results."""
import sys,json,warnings
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt,matplotlib.ticker as mt
from pathlib import Path
warnings.filterwarnings('ignore')
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from high_cagr.ideas import five_year_make_report as R, live_monitor_study as LM, win_prob_model as W, five_year_report as FY
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import GroupKFold
C=R.C;CR=ROOT/'high_cagr/output/ideas/criteria';MO=ROOT/'high_cagr/output/ideas/live_monitor'
FA={'trend':'روند','momentum':'مومنتوم/نوسان‌نما','volatility':'نوسان','trend quality':'کیفیت روند','volume':'حجم','candle':'شکل کندل','market':'بازار (BTC/breadth)','carry/calendar':'فاندینگ/تقویم','trade':'ساختار معامله (ربات/حد ضرر)'}

def main():
    cr=json.loads((CR/'result.json').read_text());mo=json.loads((MO/'result.json').read_text());sg=pd.read_csv(CR/'single_criteria.csv')
    # 1 single criteria chart
    sg['avg']=(sg.R_train+sg.R_y2024+sg.R_test)/3;top=sg.reindex(sg.avg.abs().sort_values(ascending=False).index).head(15).iloc[::-1]
    fig,ax=plt.subplots(figsize=(8,5.5));y=np.arange(len(top));h=.26
    for i,(c,lab,col) in enumerate((('R_train','train 21-23',C['blue']),('R_y2024','2024',C['gray']),('R_test','test 25-26',C['orange']))):ax.barh(y+(i-1)*h,top[c]*np.sign(top.R_train),h,color=col,label=lab)
    ax.set_yticks(y,top.feature);ax.axvline(0,color=C['ink'],lw=.8);ax.legend(frameon=False,loc='lower right');ax.set_title('Top single criteria: rank correlation with trade R (sign frozen on train)');ax.grid(axis='y',visible=False);img1=R.img(fig)
    # 2 family AUC
    ms=cr['models'];fam=[(k.split(':')[1].split('|')[0],k.split('|')[1],v) for k,v in ms.items() if k.startswith('family:')]
    df=pd.DataFrame([dict(family=f,target=t,test=v['test'],y2024=v['y2024'],train=v['train']) for f,t,v in fam]);fig,axs=plt.subplots(1,2,figsize=(10,3.8),sharey=True)
    for ax,t in zip(axs,('big','win')):
        d=df[df.target==t].sort_values('test');ax.barh(d.family,d.test,color=[C['orange'] if f=='trade' else C['blue'] for f in d.family]);ax.axvline(.5,color=C['ink'],lw=.8);ax.set_xlim(.45,.65);ax.set_title(f'AUC on TEST by criteria family ({t})');ax.grid(axis='y',visible=False)
        for i,(v,f) in enumerate(zip(d.test,d.family)):ax.text(v,i,f' {v:.3f}',va='center',fontsize=8)
    fig.tight_layout();img2=R.img(fig)
    # 3 model table
    rows=[(k,v) for k,v in ms.items() if v['kind']=='model'];
    def mrow(k,v):
        pt=v.get('passed_test');p4=v.get('passed_2024');rep=pt is not None
        return f"<tr><th>{k}</th><td class=n>{v['train']:.3f}</td><td class=n>{v['y2024']:.3f}</td><td class=n>{v['test']:.3f}</td><td class=n>{(str(len(pt))+'/7') if rep else 'کنار گذاشته (گیت)'}</td><td class=n>{(str(len(p4))+'/7') if rep else '–'}</td></tr>"
    tab_models='<div style="overflow-x:auto"><table><tr><th>مدل|هدف</th><th>آموزش (OOF)</th><th>۲۰۲۴</th><th>تست</th><th>سناریو قبول (تست)</th><th>سناریو قبول (۲۰۲۴)</th></tr>'+''.join(mrow(k,v) for k,v in sorted(rows,key=lambda t:t[0]))+'</table></div>'
    # singles & composites passing both
    both=[(k,v) for k,v in ms.items() if 'passed_test' in v and len(v['passed_test'])>=3 and len(v['passed_2024'])>=3]
    tab_both='<table><tr><th>معیار</th><th>هدف</th><th>گیت آموزش/۲۰۲۴</th><th>تست</th><th>سناریو قبول تست</th><th>۲۰۲۴</th><th>بهترین Calmar تست</th></tr>'+''.join(f"<tr><th>{k}</th><td>{v['target']}</td><td class=n>{v['train']:.3f}/{v['y2024']:.3f}</td><td class=n>{v['test']:.3f}</td><td class=n>{len(v['passed_test'])}/7</td><td class=n>{len(v['passed_2024'])}/7</td><td class=n>{v['best_test_calmar']:.1f}</td></tr>" for k,v in sorted(both,key=lambda t:-t[1]['best_test_calmar']))+'</table>'
    cons=cr['composite']
    # 4 monitor bars
    base=mo['base']['test'];rx=mo['reactions'];keys=sorted(rx,key=lambda k:rx[k]['test']['calmar'])
    fig,axs=plt.subplots(1,2,figsize=(10,6.5),sharey=True)
    for ax,(lab,f,fmt) in zip(axs,(('Calmar (TEST)',lambda x:x['test']['calmar'],'{:.1f}'),('Max drawdown % (TEST)',lambda x:x['test']['dd'],'{:.0f}'))):
        v=[f(rx[k]) for k in keys];ax.barh(keys,v,color=[C['teal'] if k.startswith('ML') else C['purple'] for k in keys])
        b=base['calmar'] if 'Calmar' in lab else base['dd'];ax.axvline(b,color=C['neg'],ls='--',lw=1.2)
        for i,val in enumerate(v):ax.text(val,i,' '+fmt.format(val),va='center',fontsize=7,ha='left' if val>=0 else 'right')
        ax.set_title(lab+' (red = no reaction)');ax.grid(axis='y',visible=False);ax.tick_params(axis='y',labelsize=7)
    fig.tight_layout();img4=R.img(fig)
    # 5 equity curves: rebuild a few
    L=FY.ledgers('soft');X,M=LM.build(L);em=M.em.to_numpy();tr=em<W.TRAIN_END;y=(M.future>0).astype(int).to_numpy();Xf=X.fillna(X[tr].median());A=Xf.to_numpy();grp=M.leg.to_numpy();idx=np.where(tr)[0]
    mkm=lambda:make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=3000));oof=np.zeros(len(M))
    for a,b in GroupKFold(5).split(idx,groups=grp[idx]):oof[idx[b]]=mkm().fit(A[idx[a]],y[idx[a]]).predict_proba(A[idx[b]])[:,1]
    p=mkm().fit(A[tr],y[tr]).predict_proba(A)[:,1];p[tr]=oof[tr];srt=np.sort(oof[tr]);pct=np.searchsorted(srt,p,side='right')/len(srt)
    def curve(name):
        if name.startswith('ML'):
            _,_,kind,q=name.split('-');q=float(q);tg=LM.first_trigger(M,X,(pct<q)&(M.k.to_numpy()>=2));trig={j:dict(m=r.m,close=LM.px(L[j]['coin'])[r.m,3],stop=None,rn=None) for j,r in tg.items()}
        else:trig=LM.rule_triggers(L,name.split('-')[1]);kind=LM.kind_of(name.split('-')[1])
        r=W.run_period(LM.apply_reaction(L,trig,kind),[1.]*len(L),W.TEST_START);return r['daily']
    base_d=W.run_period(L,[1.]*len(L),W.TEST_START)['daily'];fig,ax=plt.subplots(figsize=(10,4));x=pd.date_range('2025-01-01',periods=len(base_d))
    ax.plot(x,base_d,color=C['ink'],lw=1.8,label='No reaction')
    for name,col in (('ML-logit-TIGHTEN-0.3',C['teal']),('ML-logit-EXIT-0.1',C['blue']),('RULE-TIME',C['orange']),('RULE-ADVERSE',C['purple'])):ax.plot(x,curve(name),color=col,lw=1.3,label=name)
    ax.set_yscale('log');ax.yaxis.set_major_formatter(mt.FuncFormatter(R.usd));ax.legend(frameon=False,loc='upper left');ax.set_title('TEST 2025-01 .. 2026-10: $10,000 account, with in-trade reactions');img5=R.img(fig)
    def rrow(k):
        t=rx[k]['test'];g=rx[k]['y2024'];b4=mo['base']['y2024'];ok=lambda r,b:'✓' if r['calmar']>b['calmar'] and r['dd']>=b['dd']-2 else '–'
        return f"<tr><th>{k}</th><td class=n>{R.usd(t['final'])}</td><td class=n>{t['dd']:.1f}%</td><td class=n>{t['calmar']:.1f}</td><td class=n>{t['legs_reacted']}</td><td>{ok(t,base)}</td><td class=n>{g['calmar']:.1f}</td><td class=n>{g['dd']:.1f}%</td><td>{ok(g,b4)}</td></tr>"
    tab_rx='<div style="overflow-x:auto"><table><tr><th>واکنش</th><th>موجودی تست</th><th>MDD تست</th><th>Calmar تست</th><th>پوزیشن واکنش‌داده</th><th>قبول</th><th>Calmar ۲۰۲۴</th><th>MDD ۲۰۲۴</th><th>قبول</th></tr>'+f"<tr><th>بدون واکنش (پایه)</th><td class=n>{R.usd(base['final'])}</td><td class=n>{base['dd']:.1f}%</td><td class=n>{base['calmar']:.1f}</td><td>–</td><td>–</td><td class=n>{mo['base']['y2024']['calmar']:.1f}</td><td class=n>{mo['base']['y2024']['dd']:.1f}%</td><td>–</td></tr>"+''.join(rrow(k) for k in sorted(rx,key=lambda k:-rx[k]['test']['calmar']))+'</table></div>'
    mm=mo['models']
    n_single_pass={t:cons[f'single_consistency_{t}'] for t in ('win','big','R')}
    kp=''.join([R.kpi('معیار بررسی‌شده',f"{len(C_ALL())}"),R.kpi('مدل/ترکیب امتیازدهی',f"{len(ms)}"),R.kpi('AUC وضعیت حین معامله (لجستیک، تست)',f"{mm['logit']['auc_test']:.3f}"),R.kpi('واکنش‌های بررسی‌شده',f"{len(rx)}"),R.kpi('نتیجهٔ بهتر در تست و ۲۰۲۴',f"{sum(1 for k in rx if rx[k]['test']['calmar']>base['calmar'] and rx[k]['test']['dd']>=base['dd']-2 and rx[k]['y2024']['calmar']>mo['base']['y2024']['calmar'] and rx[k]['y2024']['dd']>=mo['base']['y2024']['dd']-2)}")])
    body=f"""<h1>معیارهای امتیازدهی معامله و واکنش حین معامله</h1>
<p>همان تقسیم داده و معیار قبولی گزارش‌های قبلی: آموزش ۲۰۲۱-۱۰ تا ۲۰۲۳-۱۲، ۲۰۲۴ برای اطلاع (گیت)، تست ۲۰۲۵-۰۱ تا ۲۰۲۶-۱۰ که فقط یک‌بار دیده شد. قاعدهٔ قبولی: Calmar بالاتر از پایه و MDD حداکثر ۲ واحد درصد بدتر. فهرست معیارها، مدل‌ها و واکنش‌ها قبل از اجرا در سربرگ کدها ثبت شده است.</p>
<div class="kpis">{kp}</div>
<h2>بخش ۱) معیارهای امتیاز ورود</h2>
<p>۴۸ معیار علّی از ۹ خانواده: روند (EMA، MACD، Ichimoku، روند روزانه)، مومنتوم (RSI، Stochastic، CCI، MFI، بازده‌ها، Bollinger %B، Donchian)، نوسان (ATR، Parkinson، BB width)، کیفیت روند (ADX، Kaufman ER، variance ratio)، حجم (حجم نسبی، OBV)، شکل کندل، بازار (BTC، breadth، قدرت نسبی، همبستگی با BTC)، فاندینگ/تقویم، و ساختار معامله. هر معیار تک‌به‌تک، ترکیب بدون وزن (z-score)، ۱۰ مدل یادگیری (لجستیک L2/L1، GBM، جنگل تصادفی، Extra Trees، kNN شبیه‌یابی گذشته، Bayes، LDA، ریج) و مدل هر خانواده امتحان شد. داده‌های احساسات، آن‌چین و دفتر سفارش در مخزن نیست و بررسی نشد.</p>
{R.tag(img1,'ضریب همبستگی رتبه‌ای با R معامله؛ ستون‌های تست/۲۰۲۴ هم‌جهت با آموزش یعنی رابطه پایدار است. همه ضعیف‌اند (زیر ۰٫۱۷).')}
<div class="note"><b>کنترل شانس:</b> از ۴۸ معیار، {n_single_pass['R']['passed_train_and_2024']} معیار در آموزش و ۲۰۲۴ هم‌جهت بودند و {n_single_pass['R']['also_ok_on_test']} معیار در تست هم همان جهت را داشتند (برای هدف R). هم‌جهتی در تست بیشتر از حد شانس (۵۰٪) است، پس ضعف ولی واقعی هست؛ اما معیارها همبسته‌اند (بیشترشان نسخه‌های مختلف «مومنتوم/روند») و اندازهٔ اثر کوچک است.</div>
<p>معیارهای تکی با پایداری بیشتر: فاندینگ (هر چه معامله فاندینگ بیشتری بپردازد بدتر)، نوسان و پهنای باند بولینگر (نوسان کمتر بهتر)، مومنتوم کوتاه‌مدت و همبستگی با BTC. ترکیب ساده top-5: {', '.join(cons['top5'])}.</p>
{R.tag(img2,'AUC هر خانواده در تست. «ساختار معامله» (کدام ربات و چقدر فاصلهٔ حد ضرر) از همهٔ معیارهای بازار قوی‌تر است.')}
<h3>معیارهایی که هم در تست و هم در ۲۰۲۴ حداقل ۳ سناریو را پاس کردند</h3>{tab_both}
<div class="note warn"><b>نکته:</b> قوی‌ترین نتیجه «ساختار معامله» است (AUC تست ۰٫۶)، که فقط می‌گوید معاملات موج‌سوار/ققنوس و حد ضرر پهن‌تر بیشتر معاملهٔ بزرگ می‌دهند. این اطلاعات بازار نیست و ربات‌ها از قبل آن را می‌دانند. معیارهای نوسان هم تا حد زیادی همان فاصلهٔ حد ضرر را نشان می‌دهند. معیارهای واقعاً «وضعیت بازار» (روند، مومنتوم، حجم، شکل کندل) تنها یک لبهٔ خیلی کم می‌دهند و مدل ۴۸‌ویژگی از مدل ۱۴‌ویژگی قبلی بدتر شد (بیش‌برازش).</div>
<details open><summary>جدول همهٔ مدل‌ها (AUC یا همبستگی)</summary>{tab_models}</details>
<h2>بخش ۲) واکنش حین معامله</h2>
<p>در پایان هر کندل ۴ساعته، برای هر پوزیشن باز دوباره امتیاز حساب می‌شود: «آیا نگه‌داشتن از اینجا بهتر از خروج الان است؟» (۴۸ معیار بازار + سود/زیان فعلی بر حسب R، بیشترین سود و زیان تجربه‌شده، پس‌دادن سود، تعداد کندل‌های نگه‌داری، تغییر ATR). مدل لجستیک روی وضعیت‌ها AUC {mm['logit']['auc_train_oof']:.3f} (آموزش)، {mm['logit']['auc_2024']:.3f} (۲۰۲۴) و {mm['logit']['auc_test']:.3f} (تست) دارد؛ یعنی پایدارتر و قوی‌تر از امتیاز ورود (البته بخشی از آن مکانیکی است چون سود فعلی خودش ورودی است). سه واکنش: <b>EXIT</b> خروج کامل در همان کندل، <b>TIGHTEN</b> حد ضرر ۰٫۵R زیر قیمت (طبق جهت)، <b>HALF</b> بستن نصف. محرک: ۱۰/۲۰/۳۰ درصد پایین امتیازهای آموزش. هفت واکنش کلاسیک هم برای مقایسه: BE1، BE2، CHAND (تریل ۳ATR)، TIME، EMA20، GIVEBACK، ADVERSE.</p>
{R.tag(img4)}{R.tag(img5)}{tab_rx}
<div class="note"><b>خوانش:</b> «قبول» یعنی Calmar بالاتر از حالت بدون واکنش و MDD حداکثر ۲ واحد بدتر. اختلاف‌های کوچک (مثلاً Calmar ۹٫۵ در برابر ۹٫۴) در حد نویز است.</div>
<h2>جمع‌بندی</h2>
<ul><li><b>امتیاز ورود:</b> معیار «وضعیت بازار» لبهٔ کم ولی تا حدی پایدار دارد؛ بهترین‌ها فاندینگ، نوسان کم و مومنتوم‌اند. همچنان فقط برای ریسک متغیر یا رد ۲۰٪ پایین و ابتدا در حالت نمایش (paper) مناسب است.</li>
<li><b>واکنش حین معامله:</b> مدل وضعیت‌ها پایدارتر از امتیاز ورود است و واکنش مناسب بیشتر به‌جای خروج کامل، «سفت‌کردن حد ضرر» (TIGHTEN) با آستانهٔ ۳۰٪ است؛ در تست افت را کم و سود را تقریباً حفظ می‌کند و در ۲۰۲۴ هم قبول است. خروج کامل (EXIT) افت را بیشتر کم می‌کند ولی سود را می‌خورد.</li>
<li><b>قواعد کلاسیک ساده:</b> TIME و ADVERSE هم در هر دو دوره قبول شدند و بدون مدل پیاده می‌شوند؛ تریل شاندلیه و EMA20 و GIVEBACK سود را بسیار کم کردند (ربات روندی است و باید بگذارد سود بدود).</li>
<li><b>احتیاط:</b> بیش از ۳۰ واکنش امتحان شد و معیار قبولی ساده است، پس نتیجهٔ بهترین‌ها خوش‌بینانه است. شبیه‌سازی خروج زودهنگام روی کندل‌های ۱دقیقه‌ای با همان هزینه‌ها انجام شد (بررسی فرمول: خطای میانگین کمتر از ۰٫۰۰۱٪ قیمت ورود)، ولی حد ضرر/تریل اصلی شاهین دوباره‌سازی نشده و اجرای زنده جداست.</li></ul>
<p class="cap">کد: <code>criteria_lib.py</code>، <code>criteria_study.py</code>، <code>live_monitor_study.py</code>، <code>criteria_monitor_report.py</code></p>"""
    (MO/'report_fa.html').write_text(R.page('معیارها و واکنش حین معامله',body),encoding='utf-8')
def C_ALL():
    from high_cagr.ideas import criteria_lib as CL;return CL.ALL
if __name__=='__main__':main()
