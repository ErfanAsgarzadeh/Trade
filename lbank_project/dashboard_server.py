"""Authenticated Persian RTL control panel for the paper futures engine."""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
import logging
import os
import secrets
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from lbank_bot import (ConfigError, ConfigStore, Database, Engine, INITIAL,
                       LIVE_LIMITATION, LiveUnavailable, MarketData, PENDING,
                       file_lock, net_pnl, position_margin, position_leverage)

LOG = logging.getLogger("dashboard")


class CloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=80)


class CloseAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disable_auto_trade: bool = True


def revision(c: dict) -> str:
    return '"' + hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest() + '"'


def create_app(engine: Engine | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if engine is None:
            application.state.engine = Engine(ConfigStore(), Database(), MarketData())
        else:
            application.state.engine = engine
        yield

    application = FastAPI(title="LBank Ichimoku Paper Dashboard", lifespan=lifespan)

    def authorized(x_bot_pin: str = Header(default="")):
        expected = os.getenv("BOT_PIN", "1234")
        if not expected or not secrets.compare_digest(x_bot_pin.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="PIN نادرست است")

    def bot() -> Engine:
        return application.state.engine

    @application.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @application.exception_handler(ConfigError)
    async def config_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @application.exception_handler(LiveUnavailable)
    async def live_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.get("/", response_class=HTMLResponse)
    def home():
        return HTML

    @application.get("/api/status", dependencies=[Depends(authorized)])
    def status():
        engine = bot()
        c = engine.config.read()
        positions, errors = [], []
        total = 0.0
        for p in engine.db.positions():
            price, pnl, current_r = None, 0.0, 0.0
            try:
                price = engine.data.price(p["symbol"], cached=True)
                if p["state"] != PENDING:
                    pnl = net_pnl(p, price, p["qty"])
                    distance = p.get("root_r_distance", 0) or abs(p["entry_price"] - p["initial_sl"])
                    root_entry = p.get("root_entry_price", 0) or p["entry_price"]
                    current_r = (price - root_entry) * (1 if p["side"] == "long" else -1) / distance if distance else 0.0
                    total += pnl
            except Exception as exc:
                errors.append({"symbol": p["symbol"], "error": str(exc)})
                if p["state"] != PENDING:
                    pnl, current_r = None, None
            positions.append({**p, "live_price": price, "current_r": current_r,
                              "actual_leverage": position_leverage(p, c["risk_and_exit"]["default_isolated_leverage"]),
                              "margin_usd": position_margin(p, c["risk_and_exit"]["default_isolated_leverage"]),
                              "unrealized_pnl_usd": pnl})
        with engine.db.connect() as db:
            realized = db.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM trade_history WHERE dry_run=1").fetchone()[0]
        equity = max(0.0, engine.paper_seed + realized + total) if not errors else None
        engaged = sum(p["margin_usd"] for p in positions if p["state"] != PENDING)
        pending_margin = sum(p["margin_usd"] for p in positions if p["state"] == PENDING)
        allowed = equity * c["risk_and_exit"]["engaged_capital_pct"] if equity is not None else None
        daily, count = engine.db.history_summary(time.time())
        return {"auto_trade_enabled": c["bot_control"]["auto_trade_enabled"],
            "dry_run_mode": c["bot_control"]["dry_run_mode"],
            "strategy_mode": c["strategy_mode"]["mode"],
            "open_positions_count": len(positions),
            "max_open_positions": c["risk_and_exit"]["max_open_positions"],
            "equity_usd": equity, "engaged_margin_usd": engaged,
            "engaged_margin_pct": engaged / equity * 100 if equity else None,
            "allowed_margin_usd": allowed,
            "allowed_margin_pct": c["risk_and_exit"]["engaged_capital_pct"] * 100,
            "margin_budget_utilization_pct": engaged / allowed * 100 if allowed else None,
            "reserved_pending_margin_usd": pending_margin,
            "total_unrealized_pnl": total if not errors else None,
            "daily_realized_pnl": daily, "daily_trades_count": count,
            "positions": positions, "price_errors": errors,
            "runtime": engine.db.runtime_all(), "live_execution_supported": False,
            "data_mode": getattr(engine.data, "mode", "test-fixture"),
            "fill_quality": engine.db.fill_quality_summary(),
            "execution_note": LIVE_LIMITATION}

    @application.post("/api/positions/close", dependencies=[Depends(authorized)])
    def close(payload: CloseRequest):
        try:
            return bot().close_symbol(payload.symbol)
        except KeyError:
            raise HTTPException(404, "پوزیشن پیدا نشد")
        except (ConfigError, LiveUnavailable):
            raise
        except Exception:
            LOG.exception("Close failed for %s", payload.symbol)
            raise HTTPException(503, "بستن پوزیشن انجام نشد؛ پوزیشن حفظ شده است")

    @application.post("/api/positions/close-all", dependencies=[Depends(authorized)])
    def close_all(payload: CloseAllRequest):
        return bot().close_all(payload.disable_auto_trade)

    @application.get("/api/config", dependencies=[Depends(authorized)])
    def get_config(response: Response):
        c = bot().config.read()
        response.headers["ETag"] = revision(c)
        return c

    @application.put("/api/config", dependencies=[Depends(authorized)])
    def put_config(payload: dict, response: Response, if_match: str | None = Header(default=None)):
        engine = bot()
        with file_lock(engine.db.trade_lock):
            current = engine.config.read()
            if if_match is not None and if_match != revision(current):
                raise HTTPException(409, "کانفیگ تغییر کرده است؛ دوباره بارگذاری کنید")
            engine.config.write(payload)
            payload = engine.config.read()
            if not payload["bot_control"]["auto_trade_enabled"]:
                # Pausing cancels unfilled setups immediately; open positions are managed.
                with engine.db.connect() as db:
                    db.execute("DELETE FROM positions WHERE state=?", (PENDING,))
        response.headers["ETag"] = revision(payload)
        return payload

    return application


HTML = r'''<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>مرکز کنترل معاملات LBank</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#141c30;--line:#29344d;--muted:#a4b3ce;--good:#4ee2ad;--bad:#ff7886}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#edf3ff;font-family:Tahoma,Arial,sans-serif;font-size:14px;line-height:1.8}
main{max-width:1450px;margin:auto;padding:28px}header,.row{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
h1{font-size:24px;margin:0}h2{font-size:18px;margin:0 0 16px}p{margin:4px 0;color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:22px;margin-top:20px}
.badge{display:inline-block;padding:4px 12px;border-radius:8px;background:#24324e;direction:ltr;font-size:12px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.kpi strong{display:block;font-size:30px;font-family:Arial;direction:ltr;text-align:right}
input,select,textarea{background:#0b1325;border:1px solid #40516f;color:#fff;border-radius:8px;padding:10px;font:inherit}input[type=checkbox]{width:18px;height:18px;accent-color:#58cab9}
button{border:0;background:#315dc8;color:white;padding:10px 16px;border-radius:8px;cursor:pointer;font:inherit}button:disabled{opacity:.45;cursor:wait}
.danger{background:#ac2b42}.subtle{background:#2a3650}.good{color:var(--good)}.bad{color:var(--bad)}
.scroll{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:12px}th,td{padding:14px 9px;border-bottom:1px solid var(--line);text-align:right}th{color:var(--muted)}
.fields{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}label{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.field{display:flex;flex-direction:column;align-items:stretch}
textarea{width:100%;min-height:360px;direction:ltr;text-align:left;font:12px/1.7 monospace;resize:vertical;margin:16px 0}
#message{display:none;padding:14px;border-radius:10px;margin-top:18px;white-space:pre-wrap;border:1px solid #53688f;background:#1c2940}
.note{border-right:3px solid #d7ac63;padding-right:12px}.muted{color:var(--muted)}details{margin-top:18px}summary{cursor:pointer}footer{margin-top:20px;color:var(--muted)}
@media(max-width:850px){main{padding:14px}.kpis{grid-template-columns:1fr}.fields{grid-template-columns:repeat(2,1fr)}h1{font-size:20px}.panel{padding:16px}}
@media(max-width:450px){.fields{grid-template-columns:1fr}}
</style></head><body><main>
<header><div><h1>مرکز کنترل معاملات LBank</h1><p>ایچیموکو · پرایس اکشن · مدیریت ریسک</p></div>
<div class="row"><input id="pin" type="password" placeholder="PIN" aria-label="PIN" autocomplete="off" size="10">
<button id="connect">اتصال</button><span id="mode" class="badge">—</span><span id="active" class="badge">قطع</span></div></header>
<div id="message" role="status" aria-live="polite"></div>
<section class="panel note">این نسخه معاملات را شبیه‌سازی می‌کند. حالت پیش‌فرض DEMO از قیمت و کندل مصنوعی استفاده می‌کند. ارسال سفارش زندهٔ فیوچرز LBank در اتصال فعلی CCXT پشتیبانی نمی‌شود. سود و زیان با کارمزد تخمینی محاسبه می‌شود.</section>
<div class="kpis"><section class="panel kpi"><p>سود و زیان باز ($)</p><strong id="unrealized">—</strong></section>
<section class="panel kpi"><p>سود و زیان تحقق‌یافتهٔ ۲۴ ساعت ($)</p><strong id="realized">—</strong><p id="trades">—</p></section>
<section class="panel kpi"><p>پوزیشن‌ها و سفارش‌های در انتظار</p><strong id="slots">—</strong><p id="updated">در انتظار اتصال</p></section>
<section class="panel kpi"><p>مارجین درگیر فعلی / بودجه مجاز ($)</p><strong id="margin">—</strong><p id="margin_pct">—</p><p id="pending_margin">—</p></section>
<section class="panel kpi"><p>لغزش واقعی اندازه‌گیری‌شده با دفتر سفارش LBank (bps، میانه / P90)</p><strong id="fq_main">—</strong><p id="fq_detail">—</p></section></div>
<section class="panel"><div class="row"><h2>پوزیشن‌ها</h2><button class="danger" id="panic" disabled>🚨 بستن اضطراری همه پوزیشن‌ها + توقف ربات</button></div>
<div class="scroll"><table><thead><tr><th>نماد</th><th>جهت</th><th>ورود / تریگر</th><th>قیمت زنده</th><th>حد ضرر</th><th>هدف اول</th><th>وضعیت</th><th>R</th><th>سود و زیان ($)</th><th>عملیات</th></tr></thead><tbody id="positions"><tr><td colspan="10">ابتدا PIN را وارد کنید.</td></tr></tbody></table></div></section>
<section class="panel"><div class="row"><h2>تنظیمات</h2><button class="subtle" id="reload" disabled>بارگذاری مجدد</button></div>
<div class="fields"><label><input id="auto" type="checkbox">ورود خودکار</label><label><input id="dry" type="checkbox" checked disabled>حالت شبیه‌سازی (Dry-run)</label>
<label class="field">حالت استراتژی<select id="strategy"><option>MTF</option><option>SINGLE</option></select></label>
<label class="field">ریسک هر معامله (%)<input id="risk" type="number" min="0.1" max="5" step="0.1"></label>
<label class="field">درصد سرمایه مجاز درگیر (%)<input id="engaged" type="number" min="0.01" max="100" step="0.01"></label>
<label class="field">حداکثر پوزیشن هم‌زمان<input id="max_positions" type="number" min="1" max="100" step="1"></label>
<label class="field">مدل اهرم<select id="leverage"><option>DYNAMIC_MARGIN</option><option>FIXED_LEVERAGE</option></select></label>
<label class="field">استراتژی خروج و TP<select id="exit_tp"><option>STOP_TRAIL_DONCHIAN10</option><option>CLOSE_TRAIL_KIJUN</option><option>HYBRID_TRAIL_AND_HARD_TP</option></select></label>
<label class="field">تریل حالت ترکیبی<select id="hybrid_trail"><option>CLOSE_TRAIL_KIJUN</option><option>STOP_TRAIL_DONCHIAN10</option></select></label>
<label class="field">ضریب حد سود قطعی (R، صفر: غیرفعال)<input id="hard_tp" type="number" min="0" max="100" step="0.1"></label>
<label class="field">ضریب ریسک‌فری (R، صفر: غیرفعال)<input id="breakeven" type="number" min="0" max="20" step="0.1"></label>
<label class="field">پریست ایچیموکو<select id="preset"><option>crypto</option><option>standard</option></select></label>
<label class="field">دوره شکست Donchian<select id="donchian_period"><option>20</option><option>10</option></select></label>
<label class="field">استاپ اولیه<select id="initial_stop"><option>ATR2</option><option>KIJUN</option></select></label>
<label><input id="btc_gate" type="checkbox">فیلتر روند بیت‌کوین: وقتی کندل ۴ساعتهٔ BTC داخل ابر Kumo است، آلت‌ها وارد نشوند</label>
<label><input id="atr_regime" type="checkbox">فیلتر رژیم ATR (2A): وقتی ATR کندل سیگنال از میانهٔ ATR شصت کندل ۴ساعتهٔ قبل کمتر است، ورود و افزودن انجام نشود</label>
<label><input id="funding_short" type="checkbox">فیلتر funding: وقتی میانگین funding سه روز گذشته منفی است، شورت جدید باز نشود (نیازمند فایل‌های FUNDING_DIR)</label>
<label class="field">ضریب ATR استاپ اولیه (۲٫۵ فقط همراه V2 و فیلتر BTC آزموده شده)<input id="stop_atr_mult" type="number" min="1" max="5" step="0.1"></label>
<label><input id="pyramid" type="checkbox">افزودن یک‌مرحله‌ای به برنده</label>
<label class="field">ریسک واحد افزوده (کسری از ریسک هر معامله)<input id="pyramid_fraction" type="number" min="0.05" max="1" step="0.05"></label>
<label><input id="safe_pyramid" type="checkbox">افزودن فقط اگر استاپ مشترک، سربه‌سر ترکیبی هر دو واحد (با کارمزد و لغزش) را پوشش دهد</label>
<label><input id="profit_floor" type="checkbox">کف سود: پس از رسیدن به آستانهٔ R استاپ را به ورود ± ضریب قفل ببر</label>
<label><input id="width_filter" type="checkbox">فیلتر پهنای استاپ: ورودهای با استاپ بسیار پهن را رد کن و استاپ نسبتاً پهن را با ریسک کمتر بگیر</label>
<label class="field">رد ورود اگر پهنای استاپ از این مقدار بیشتر باشد (٪)<input id="width_skip" type="number" min="1.2" max="50" step="0.1"></label>
<label class="field">کاهش ریسک اگر پهنای استاپ از این مقدار بیشتر باشد (٪)<input id="width_mid" type="number" min="1.2" max="50" step="0.1"></label>
<label class="field">کسر ریسک برای استاپ نسبتاً پهن<input id="width_fraction" type="number" min="0.05" max="1" step="0.05"></label>
<label class="field">آستانهٔ فعال‌سازی کف سود (R)<input id="floor_trigger" type="number" min="0.1" max="20" step="0.1"></label>
<label class="field">ضریب قفل کف سود (R)<input id="floor_lock" type="number" min="0" max="19.9" step="0.05"></label>
<label class="field">مبنای استاپ ATR2<select id="stop_anchor"><option>SIGNAL</option><option>ENTRY</option></select></label>
<label><input id="breakout" type="checkbox">شکست کندل سیگنال</label><label><input id="barb" type="checkbox">فیلتر Barb Wire</label><label><input id="h2" type="checkbox">پولبک H2 / L2</label></div>
<details><summary>ویرایش کامل JSON</summary><textarea id="editor" aria-label="JSON configuration" spellcheck="false"></textarea></details>
<div class="row" style="margin-top:18px"><p id="dirty">تنظیمات بارگذاری نشده است.</p><button id="save" disabled>ذخیره تنظیمات</button></div></section>
<footer><span id="health">—</span> · توقف ورود، مدیریت پوزیشن‌های باز را متوقف نمی‌کند.</footer>
</main><script>
'use strict';
const $ = id => document.getElementById(id);
let cfg = null, etag = null, connected = false, polling = false;
function message(text, error=false){$('message').style.display='block';$('message').textContent=text;$('message').className=error?'bad':'';}
function target(p){if(p.hard_tp_price>0)return p.hard_tp_price;if(['PURE_KIJUN','HARD_TARGET'].includes(p.exit_scheme))return null;return p.tp1_price;}
function number(v,n=2){return v===null||v===undefined?'—':Number(v).toLocaleString('en-US',{minimumFractionDigits:n,maximumFractionDigits:n});}
async function api(path,method='GET',body=null,match=null){
 const headers={'X-Bot-Pin':$('pin').value};if(body!==null)headers['Content-Type']='application/json';if(match)headers['If-Match']=match;
 const response=await fetch(path,{method,headers,body:body===null?null:JSON.stringify(body)});
 const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
 return {data,etag:response.headers.get('ETag')};
}
function fillControls(){if(!cfg)return;$('auto').checked=cfg.bot_control.auto_trade_enabled;$('dry').checked=cfg.bot_control.dry_run_mode;
 $('strategy').value=cfg.strategy_mode.mode;$('risk').value=cfg.risk_and_exit.risk_per_trade_pct*100;
 $('engaged').value=cfg.risk_and_exit.engaged_capital_pct*100;$('leverage').value=cfg.risk_and_exit.leverage_mode;$('max_positions').value=cfg.risk_and_exit.max_open_positions;
 const settings=cfg.strategy_settings;
 for(const id of ['exit_tp','hybrid_trail','hard_tp','breakeven','preset','donchian_period','initial_stop','pyramid','stop_anchor','pyramid_fraction','safe_pyramid','profit_floor','floor_trigger','floor_lock','width_filter','width_skip','width_mid','width_fraction','stop_atr_mult','btc_gate','funding_short','atr_regime'])$(id).disabled=!settings;
 $('strategy').disabled=!!settings;
 if(settings){$('exit_tp').value=settings.exit_tp_mode;$('hybrid_trail').value=settings.hybrid_trail_mode;$('hard_tp').value=settings.hard_tp_rr;$('breakeven').value=settings.breakeven_trigger_rr;$('preset').value=settings.ichimoku_preset;$('donchian_period').value=settings.donchian_entry_period;$('initial_stop').value=settings.initial_stop_mode;$('pyramid').checked=!!settings.pyramid_enabled;$('stop_anchor').value=settings.initial_stop_anchor;
  $('pyramid_fraction').value=settings.pyramid_risk_fraction;$('safe_pyramid').checked=!!settings.safe_pyramid_enabled;$('profit_floor').checked=!!settings.profit_floor_enabled;$('floor_trigger').value=settings.profit_floor_trigger_r;$('floor_lock').value=settings.profit_floor_lock_r;
  $('width_filter').checked=!!settings.stop_width_filter_enabled;$('width_skip').value=settings.stop_width_skip_pct*100;$('width_mid').value=settings.stop_width_mid_pct*100;$('width_fraction').value=settings.stop_width_mid_risk_fraction;$('stop_atr_mult').value=settings.initial_stop_atr_mult;$('btc_gate').checked=!!settings.btc_regime_filter_enabled;$('funding_short').checked=!!settings.funding_short_filter_enabled;$('atr_regime').checked=!!settings.atr_regime_filter_enabled;}
 $('breakout').checked=cfg.al_brooks_filters.require_signal_bar_breakout;$('barb').checked=cfg.al_brooks_filters.enable_barb_wire_filter;$('h2').checked=cfg.al_brooks_filters.require_h2_l2_pullback;
}
async function loadConfig(){const result=await api('/api/config');cfg=result.data;etag=result.etag;$('editor').value=JSON.stringify(cfg,null,2);fillControls();$('dirty').textContent='تنظیمات ذخیره شده است.';}
function controlsChanged(){if(!cfg)return;try{cfg=JSON.parse($('editor').value);}catch(e){message('ابتدا JSON را اصلاح کنید.',true);fillControls();return;}
 cfg.bot_control.auto_trade_enabled=$('auto').checked;cfg.strategy_mode.mode=$('strategy').value;cfg.risk_and_exit.risk_per_trade_pct=Number($('risk').value)/100;
 cfg.risk_and_exit.engaged_capital_pct=Number($('engaged').value)/100;cfg.risk_and_exit.leverage_mode=$('leverage').value;cfg.risk_and_exit.max_open_positions=Number($('max_positions').value);
 if(cfg.strategy_settings){Object.assign(cfg.strategy_settings,{exit_tp_mode:$('exit_tp').value,hybrid_trail_mode:$('hybrid_trail').value,hard_tp_rr:Number($('hard_tp').value),breakeven_trigger_rr:Number($('breakeven').value),ichimoku_preset:$('preset').value,donchian_entry_period:Number($('donchian_period').value),initial_stop_mode:$('initial_stop').value});}
 if(cfg.strategy_settings){cfg.strategy_settings.pyramid_enabled=$('pyramid').checked;cfg.strategy_settings.initial_stop_anchor=$('stop_anchor').value;
  Object.assign(cfg.strategy_settings,{pyramid_risk_fraction:Number($('pyramid_fraction').value),safe_pyramid_enabled:$('safe_pyramid').checked,profit_floor_enabled:$('profit_floor').checked,profit_floor_trigger_r:Number($('floor_trigger').value),profit_floor_lock_r:Number($('floor_lock').value),
   stop_width_filter_enabled:$('width_filter').checked,stop_width_skip_pct:Number($('width_skip').value)/100,stop_width_mid_pct:Number($('width_mid').value)/100,stop_width_mid_risk_fraction:Number($('width_fraction').value),initial_stop_atr_mult:Number($('stop_atr_mult').value),btc_regime_filter_enabled:$('btc_gate').checked,funding_short_filter_enabled:$('funding_short').checked,atr_regime_filter_enabled:$('atr_regime').checked});}
 cfg.al_brooks_filters.require_signal_bar_breakout=$('breakout').checked;cfg.al_brooks_filters.enable_barb_wire_filter=$('barb').checked;cfg.al_brooks_filters.require_h2_l2_pullback=$('h2').checked;
 $('editor').value=JSON.stringify(cfg,null,2);$('dirty').textContent='تغییرات ذخیره نشده است.';
}
for(const id of ['auto','strategy','risk','breakout','barb','h2','engaged','max_positions','leverage','exit_tp','hybrid_trail','hard_tp','breakeven','preset','donchian_period','initial_stop','pyramid','stop_anchor','pyramid_fraction','safe_pyramid','profit_floor','floor_trigger','floor_lock','width_filter','width_skip','width_mid','width_fraction','stop_atr_mult','btc_gate','funding_short','atr_regime'])$(id).addEventListener('change',controlsChanged);
$('editor').addEventListener('input',()=>{$('dirty').textContent='تغییرات ذخیره نشده است.';});
$('editor').addEventListener('blur',()=>{try{cfg=JSON.parse($('editor').value);fillControls();}catch(e){message('JSON نامعتبر است.',true);}});
function renderFillQuality(fq){const main=$('fq_main'),detail=$('fq_detail');if(!fq||!fq.total){main.textContent='—';main.className='';detail.textContent='هنوز fill ثبت نشده (فقط با PAPER_DATA_MODE=csv-lbank و دفتر سفارش زنده)'+(fq&&fq.last_error?' | خطا: '+fq.last_error:'');return;}
 const f=x=>x?Number(x.median_bps).toFixed(1)+' / '+Number(x.p90_bps).toFixed(1):'—';main.textContent='ورود '+f(fq.entry)+' | خروج '+f(fq.exit);
 const worst=Math.max(fq.entry?fq.entry.median_bps:0,fq.exit?fq.exit.median_bps:0);main.className=worst>fq.assumed_bps_per_fill*2.5?'bad':'';
 detail.textContent='بک‌تست '+fq.assumed_bps_per_fill+' bps فرض کرده؛ '+fq.total+' fill'+(fq.last_error?' | خطا: '+fq.last_error:'');}
function render(s){$('mode').textContent=s.strategy_mode+' / '+(s.dry_run_mode?'DRY-RUN':'LIVE')+' / '+s.data_mode;$('active').textContent=s.auto_trade_enabled?'ورود فعال':'ورود متوقف';
 $('unrealized').textContent=number(s.total_unrealized_pnl);$('realized').textContent=number(s.daily_realized_pnl);$('realized').className=s.daily_realized_pnl<0?'bad':'good';
 $('trades').textContent=s.daily_trades_count+' خروج ثبت‌شده در ۲۴ ساعت';$('slots').textContent=s.open_positions_count+' / '+s.max_open_positions;
 $('margin').textContent=number(s.engaged_margin_usd)+' / '+number(s.allowed_margin_usd);
 $('margin_pct').textContent=number(s.engaged_margin_pct)+'٪ از حساب / '+number(s.allowed_margin_pct)+'٪ مجاز؛ '+number(s.margin_budget_utilization_pct)+'٪ مصرف بودجه';
 $('pending_margin').textContent='مارجین رزروشدهٔ سفارش‌های در انتظار: $'+number(s.reserved_pending_margin_usd);
 renderFillQuality(s.fill_quality);
 $('updated').textContent='آخرین دریافت: '+new Date().toLocaleTimeString('fa-IR');const rows=$('positions');rows.replaceChildren();
 if(!s.positions.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=10;td.textContent='پوزیشن بازی وجود ندارد.';tr.append(td);rows.append(tr);}
 for(const p of s.positions){const tr=document.createElement('tr');const values=[p.symbol,p.side==='long'?'خرید':'فروش',number(p.state==='STATE_PENDING_TRIGGER'?p.trigger_price:p.entry_price,6),number(p.live_price,6),number(p.active_sl,6),number(target(p),6),p.state,number(p.current_r),number(p.unrealized_pnl_usd)];
  values.forEach((v,index)=>{const td=document.createElement('td');td.textContent=v;if(index===0||index>=2)td.dir='ltr';if(index===8&&p.unrealized_pnl_usd!==null)td.className=p.unrealized_pnl_usd<0?'bad':'good';tr.append(td);});
  const td=document.createElement('td'),button=document.createElement('button');button.className='danger';button.textContent=p.state==='STATE_PENDING_TRIGGER'?'لغو':'بستن آنی';
  button.onclick=async()=>{if(!confirm('بستن / لغو '+p.symbol+'؟'))return;button.disabled=true;try{await api('/api/positions/close','POST',{symbol:p.symbol});await refresh();}catch(e){message(e.message,true);}finally{button.disabled=false;}};td.append(button);tr.append(td);rows.append(tr);
 }
 const stamp=s.runtime.watchdog_at;$('health').textContent=stamp?'آخرین بررسی ربات: '+new Date(stamp*1000).toLocaleTimeString('fa-IR'):'ربات هنوز بررسی ثبت نکرده است';
 if(stamp&&Date.now()/1000-stamp>60)$('health').textContent+=' — بررسی ربات عقب افتاده است';
 if(s.price_errors.length)message('قیمت بعضی نمادها دریافت نشد؛ سود و زیان کامل در دسترس نیست.',true);
}
async function refresh(){if(!connected||polling)return;polling=true;try{const result=await api('/api/status');render(result.data);}catch(e){message(e.message,true);}finally{polling=false;}}
$('connect').onclick=async()=>{try{await loadConfig();connected=true;for(const id of ['save','panic','reload'])$(id).disabled=false;await refresh();$('message').style.display='none';}catch(e){connected=false;message(e.message,true);}};
$('pin').addEventListener('input',()=>{connected=false;for(const id of ['save','panic','reload'])$(id).disabled=true;$('active').textContent='قطع';});
$('save').onclick=async()=>{const b=$('save');b.disabled=true;try{const edited=JSON.parse($('editor').value);const result=await api('/api/config','PUT',edited,etag);cfg=result.data;etag=result.etag;fillControls();$('dirty').textContent='تنظیمات ذخیره شده است.';message('تنظیمات ذخیره شد.');await refresh();}catch(e){message(e.message,true);}finally{b.disabled=false;}};
$('reload').onclick=async()=>{try{await loadConfig();message('تنظیمات بارگذاری شد.');}catch(e){message(e.message,true);}};
$('panic').onclick=async()=>{if(!confirm('همهٔ پوزیشن‌ها بسته و ورود خودکار متوقف شود؟'))return;const b=$('panic');b.disabled=true;
 try{const result=await api('/api/positions/close-all','POST',{disable_auto_trade:true});const s=result.data;message(s.errors.length?'ورود متوقف شد؛ '+s.errors.length+' پوزیشن بسته نشد. دوباره تلاش کنید.':'همه پوزیشن‌ها بسته / لغو و ورود متوقف شد.',s.errors.length>0);await loadConfig();await refresh();}catch(e){message(e.message,true);}finally{b.disabled=false;}};
setInterval(refresh,5000);
</script></body></html>'''

app = create_app()
