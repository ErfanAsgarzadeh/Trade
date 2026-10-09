"""Persian report for uncertainty.py -> high_cagr/output/ideas/three_bots/uncertainty_fa.html"""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];D=ROOT/'high_cagr/output/ideas/three_bots'
U=json.loads((D/'uncertainty.json').read_text());E=json.loads((D/'uncertainty_extra.json').read_text())
b=U['base']
rows=[('نتیجهٔ بک‌تست',b['cagr'],b['dd'],'base'),
 ('لغزش ۵bps در هر fill',U['U3']['5']['cagr'],U['U3']['5']['dd'],'cost'),
 ('لغزش ۱۰bps',U['U3']['10']['cagr'],U['U3']['10']['dd'],'cost'),
 ('حجم LBank = ۲۰٪ بایننس (اثر بازار)',U['U4']['venue20']['cagr'],U['U4']['venue20']['dd'],'cost'),
 ('لغزش ۲۰bps',U['U3']['20']['cagr'],U['U3']['20']['dd'],'cost'),
 ('بدون ۲۵ معاملهٔ برتر (۰٫۷٪ معاملات)',U['U2R']['25']['cagr'],U['U2R']['25']['dd'],'conc'),
 ('بدون ۱۰۰ معاملهٔ برتر (۲٫۶٪)',U['U2R']['100']['cagr'],U['U2R']['100']['dd'],'conc'),
 ('ققنوس روی ۱۵ ارز دیگر',U['U5']['pa']['cagr'],U['U5']['pa']['dd'],'sel'),
 ('موج‌سوار روی ۲۰ ارز انتخاب‌نشده',U['U5']['c3']['cagr'],U['U5']['c3']['dd'],'sel'),
 ('شاهین روی ۱۰ ارز دیگر',U['U5']['main']['cagr'],U['U5']['main']['dd'],'sel'),
 ('هر سه روی ارزهای انتخاب‌نشده',U['U5']['all']['cagr'],U['U5']['all']['dd'],'sel')]
W,BH,L0=900,30,330;mx=140
def x(v):return L0+(W-L0-60)*max(v,0)/mx
bars=''
for i,(name,c,dd,k) in enumerate(rows):
    y=10+i*BH
    bars+=f'<text x="{L0-10}" y="{y+18}" class="lb" text-anchor="start">{name}</text><rect x="{L0}" y="{y+5}" width="{x(c)-L0:.1f}" height="18" rx="4" class="b {k}"/><text x="{x(c)+6:.1f}" y="{y+19}" class="v">{c:.0f}% · DD {dd:.0f}%</text>'
H=10+len(rows)*BH+10
u1,u1y,u90,u180=U['U1_5y'],U['U1_1y'],E['boot_90d'],E['boot_180d']
tpl=(Path(__file__).with_name('uncertainty_report_template.html')).read_text()
rep={'{{BARS}}':bars,'{{H}}':str(H),'{{W}}':str(W)}
def f(v,d=0):return f'{v:.{d}f}'
vals=dict(B_CAGR=f(b['cagr']),B_DD=f(b['dd'],1),
 U1C5=f(u1['cagr']['5']),U1C50=f(u1['cagr']['50']),U1C95=f(u1['cagr']['95']),U1D50=f(u1['dd']['50']),U1D95=f(u1['dd']['95']),U1P40=f(u1['p_dd40']),U1P30=f(u1['p_dd30']),
 Y1C5=f(u1y['total']['5']),Y1C95=f(u1y['total']['95']),Y1C50=f(u1y['total']['50']),Y1PL=f(u1y['p_loss'],1),
 Q90L=f(u90['total']['5']),Q90H=f(u90['total']['95']),Q90PL=f(u90['p_loss']),Q90DD=f(u90['dd']['95']),
 Q180L=f(u180['total']['5']),Q180H=f(u180['total']['95']),Q180PL=f(u180['p_loss']),Q180DD=f(u180['dd']['95']),
 R10=f(U['U2R']['10']['cagr']),R25=f(U['U2R']['25']['cagr']),R50=f(U['U2R']['50']['cagr']),R100=f(U['U2R']['100']['cagr'],1),
 C5=f(U['U3']['5']['cagr']),C10=f(U['U3']['10']['cagr']),C20=f(U['U3']['20']['cagr']),C20PA=f(U['U3']['20']['pnl']['pa']/1000),
 LB=f(U['U4']['binance']['cagr']),LV=f(U['U4']['venue20']['cagr']),LVPA=f(U['U4']['venue20']['pnl']['pa']/1000),LC05=f(U['U4']['venue20_cap05']['cagr']),LC05PA=f(U['U4']['venue20_cap05']['pnl']['pa']/1000),
 SM=f(U['U5']['main_alone']['cagr'],1),SMD=f(U['U5']['main_alone']['dd']),SC=f(U['U5']['c3_alone']['cagr'],1),SCD=f(U['U5']['c3_alone']['dd']),SP=f(U['U5']['pa_alone']['cagr'],1),SPD=f(U['U5']['pa_alone']['dd']),
 SA=f(U['U5']['all']['cagr']),SAD=f(U['U5']['all']['dd']),SAB5=f(U['U5_all_boot']['cagr']['5']),SAB95=f(U['U5_all_boot']['cagr']['95']),
 H5=f(E['base_x0.5']['cagr']),H5D=f(E['base_x0.5']['dd']),A5=f(E['alt_x0.5']['cagr']),A5D=f(E['alt_x0.5']['dd'],1),
 W12=f(U['U6']['worst']))
for k,v in vals.items():rep['{{'+k+'}}']=v
nm={'BTCUSDT':'BTC','ETHUSDT':'ETH','XRPUSDT':'XRP','ADAUSDT':'ADA','SOLUSDT':'SOL'}
rep['{{M5R}}']=' · '.join(f'{nm[k]} {v:+.0f}R' for k,v in sorted(E['shahin_main5_R_by_coin'].items(),key=lambda z:-z[1]))
rep['{{N10R}}']=' · '.join(f'{k[:-4]} {v:+.0f}R' for k,v in sorted(E['shahin_new10_R_by_coin'].items(),key=lambda z:-z[1]))
for k,v in rep.items():tpl=tpl.replace(k,v)
assert '{{' not in tpl,tpl[tpl.find('{{'):][:40]
(D/'uncertainty_fa.html').write_text(tpl);print('ok')
