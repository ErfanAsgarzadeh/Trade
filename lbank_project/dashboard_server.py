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

import c3_sleeve
import pa_sleeve
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


class C3Close(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=80)


class BotToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot: str = Field(pattern="^(main|c3|pa)$")
    enabled: bool


BOT_NAMES = {"main": "شاهین", "c3": "موج‌سوار", "pa": "ققنوس"}


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
        shared = None
        if c["portfolio_risk"]["shared_c3_account"]:
            try:
                shared = engine.shared_paper_account().snapshot()
                equity = shared["equity_usd"]
            except Exception as exc:
                errors.append({"symbol": "موج‌سوار/ققنوس", "error": str(exc)})
                equity = None
        allowed = equity * c["risk_and_exit"]["engaged_capital_pct"] if equity is not None else None
        daily, count = engine.db.history_summary(time.time())
        return {"auto_trade_enabled": c["bot_control"]["auto_trade_enabled"],
            "dry_run_mode": c["bot_control"]["dry_run_mode"],
            "strategy_mode": c["strategy_mode"]["mode"],
            "open_positions_count": len(positions),
            "max_open_positions": c["risk_and_exit"]["max_open_positions"],
            "shared_account_enabled": c["portfolio_risk"]["shared_c3_account"], "shared_account": shared,
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
        result = bot().close_all(payload.disable_auto_trade)
        try:   # emergency stop covers the second strategy too
            cfg, store = c3_paths()
            conf = c3_sleeve.load(cfg)
            if payload.disable_auto_trade and conf["enabled"]:
                c3_sleeve.write_config(cfg, {**conf, "enabled": False})
            closed = c3_sleeve.Sleeve(conf, store, bot().data, base_equity=bot().main_paper_equity,shared_account=bot().shared_paper_account).close_all("emergency")
            result = {**result, "c3": closed}
            result["errors"] = list(result.get("errors", [])) + [c for c in closed if c["result"] == "error"]
        except Exception as exc:
            LOG.exception("C3 emergency close failed")
            result = {**result, "errors": list(result.get("errors", [])) + [{"symbol": "موج‌سوار", "error": str(exc)}]}
        try:   # ... and the third (PA)
            cfg, store = pa_paths()
            conf = pa_sleeve.load(cfg)
            if payload.disable_auto_trade and conf["enabled"]:
                pa_sleeve.write_config(cfg, {**conf, "enabled": False})
            closed = pa_sleeve.Sleeve(conf, store, bot().data, base_equity=bot().main_paper_equity, shared_account=bot().shared_paper_account).close_all("emergency")
            result = {**result, "pa": closed}
            result["errors"] = list(result.get("errors", [])) + [c for c in closed if c["result"] == "error"]
        except Exception as exc:
            LOG.exception("PA emergency close failed")
            result = {**result, "errors": list(result.get("errors", [])) + [{"symbol": "ققنوس", "error": str(exc)}]}
        return result

    def shared_equity(engine, view):
        """On the shared account the equity shown with a sleeve is the whole account (main + C3 + PA)."""
        if view.get("equity_usd") is not None and engine.config.read()["portfolio_risk"]["shared_c3_account"]:
            try:
                view["equity_usd"] = engine.shared_paper_account().equity()
            except Exception as exc:
                view["equity_usd"] = None
                view["price_errors"] = list(view.get("price_errors", [])) + [{"symbol": "shared", "error": str(exc)}]
        return view

    # ---- C3+D (second strategy, same bot process): settings, status, manual close; paper-only like the main bot ----
    def c3_paths():
        here = os.path.dirname(os.path.abspath(c3_sleeve.__file__))
        from pathlib import Path
        cfg = Path(os.getenv("C3_CONFIG", os.path.join(here, "c3_config.json")))
        if cfg.resolve() != Path(here, "c3_config.json").resolve():
            c3_sleeve.prepare_config(cfg, Path(here, "c3_config.json"))
        return cfg, c3_sleeve.Store(Path(os.getenv("C3_DB", os.path.join(here, "data", "c3_sleeve.db"))))

    @application.get("/api/c3/status", dependencies=[Depends(authorized)])
    def c3_status():
        cfg, store = c3_paths()
        engine = bot()
        view = c3_sleeve.summary(store, c3_sleeve.load(cfg), lambda s: engine.data.price(s, cached=True), engine.main_paper_equity(), net_costs=engine.config.read()["portfolio_risk"]["shared_c3_account"])
        view["in_bot"] = os.getenv("C3_IN_BOT", "1") != "0"
        return shared_equity(engine, view)

    @application.get("/api/c3/config", dependencies=[Depends(authorized)])
    def c3_get_config(response: Response):
        cfg, _ = c3_paths()
        c = c3_sleeve.load(cfg)
        response.headers["ETag"] = revision(c)
        return c

    @application.put("/api/c3/config", dependencies=[Depends(authorized)])
    def c3_put_config(payload: dict, response: Response, if_match: str | None = Header(default=None)):
        cfg, _ = c3_paths()
        with file_lock(cfg.with_suffix(".lock")):
            if if_match is not None and if_match != revision(c3_sleeve.load(cfg)):
                raise HTTPException(409, "تنظیمات موج‌سوار تغییر کرده است؛ دوباره بارگذاری کنید")
            try:
                value = c3_sleeve.write_config(cfg, payload)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        response.headers["ETag"] = revision(value)
        return value

    @application.post("/api/c3/close", dependencies=[Depends(authorized)])
    def c3_close(payload: C3Close):
        cfg, store = c3_paths()
        sl = c3_sleeve.Sleeve(c3_sleeve.load(cfg), store, bot().data, base_equity=bot().main_paper_equity,shared_account=bot().shared_paper_account)
        pos = {p["symbol"]: p for p in store.positions()}.get(payload.symbol)
        if not pos:
            raise HTTPException(404, "پوزیشن موج‌سوار پیدا نشد")
        try:
            return {"symbol": payload.symbol, "pnl": sl.close(pos, bot().data.price(payload.symbol), "manual", time.time())}
        except Exception:
            LOG.exception("C3 close failed for %s", payload.symbol)
            raise HTTPException(503, "بستن پوزیشن موج‌سوار انجام نشد؛ پوزیشن حفظ شده است")

    # ---- PA (third strategy, 4h price-action key reversal): same API shape as C3 ----
    def pa_paths():
        return pa_sleeve.paths()

    @application.get("/api/pa/status", dependencies=[Depends(authorized)])
    def pa_status():
        cfg, store = pa_paths()
        engine = bot()
        view = pa_sleeve.summary(store, pa_sleeve.load(cfg), lambda s: engine.data.price(s, cached=True), engine.main_paper_equity(), net_costs=engine.config.read()["portfolio_risk"]["shared_c3_account"])
        view["in_bot"] = pa_sleeve.in_bot()
        return shared_equity(engine, view)

    @application.get("/api/pa/config", dependencies=[Depends(authorized)])
    def pa_get_config(response: Response):
        cfg, _ = pa_paths()
        c = pa_sleeve.load(cfg)
        response.headers["ETag"] = revision(c)
        return c

    @application.put("/api/pa/config", dependencies=[Depends(authorized)])
    def pa_put_config(payload: dict, response: Response, if_match: str | None = Header(default=None)):
        cfg, _ = pa_paths()
        with file_lock(cfg.with_suffix(".lock")):
            if if_match is not None and if_match != revision(pa_sleeve.load(cfg)):
                raise HTTPException(409, "تنظیمات ققنوس تغییر کرده است؛ دوباره بارگذاری کنید")
            try:
                value = pa_sleeve.write_config(cfg, payload)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        response.headers["ETag"] = revision(value)
        return value

    @application.post("/api/pa/close", dependencies=[Depends(authorized)])
    def pa_close(payload: C3Close):
        cfg, store = pa_paths()
        sl = pa_sleeve.Sleeve(pa_sleeve.load(cfg), store, bot().data, base_equity=bot().main_paper_equity, shared_account=bot().shared_paper_account)
        if payload.symbol in store.orders():   # unfilled stop order: cancel
            store.set_order(payload.symbol, None)
            return {"symbol": payload.symbol, "result": "cancelled"}
        pos = {p["symbol"]: p for p in store.positions()}.get(payload.symbol)
        if not pos:
            raise HTTPException(404, "پوزیشن ققنوس پیدا نشد")
        try:
            return {"symbol": payload.symbol, "pnl": sl.close(pos, bot().data.price(payload.symbol), "manual", time.time())}
        except Exception:
            LOG.exception("PA close failed for %s", payload.symbol)
            raise HTTPException(503, "بستن پوزیشن ققنوس انجام نشد؛ پوزیشن حفظ شده است")

    @application.post("/api/bots/toggle", dependencies=[Depends(authorized)])
    def toggle_bot(payload: BotToggle):
        """On/off switch of one bot: off stops NEW entries (and cancels unfilled orders); open positions stay managed."""
        engine = bot()
        if payload.bot == "main":
            with file_lock(engine.db.trade_lock):
                c = engine.config.read()
                c["bot_control"]["auto_trade_enabled"] = payload.enabled
                engine.config.write(c)
                if not payload.enabled:
                    with engine.db.connect() as db:
                        db.execute("DELETE FROM positions WHERE state=?", (PENDING,))
        else:
            module, (cfg, store) = (c3_sleeve, c3_paths()) if payload.bot == "c3" else (pa_sleeve, pa_paths())
            with file_lock(cfg.with_suffix(".lock")):
                module.write_config(cfg, {**module.load(cfg), "enabled": payload.enabled})
            if payload.bot == "pa" and not payload.enabled:
                for symbol in list(store.orders()):
                    store.set_order(symbol, None)
        return {"bot": payload.bot, "name": BOT_NAMES[payload.bot], "enabled": payload.enabled}

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
.view{background:#2a3650}.view.on{background:#315dc8;outline:2px solid #7fa1ff}.tag{display:inline-block;padding:1px 8px;border-radius:6px;background:#24324e;font-size:11px}.tag.c3{background:#3b2f58}.tag.pa{background:#5a3b22}
.bots{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.bot{background:#101829;border:1px solid var(--line);border-radius:14px;padding:16px;min-width:0}
.bot h3{margin:0;font-size:20px}.bot .sub{margin:0 0 10px;font-size:12px}.bot dl{display:grid;grid-template-columns:1fr auto;gap:4px 12px;margin:12px 0 0;font-size:13px}
.bot dt{color:var(--muted)}.bot dd{margin:0;text-align:left;unicode-bidi:plaintext;font-family:Arial}.bot.off{opacity:.65}
.switch{display:inline-flex;align-items:center;gap:8px;cursor:pointer;font-size:13px}.switch input{width:20px;height:20px}
.bot-main{border-top:3px solid #4f7be0}.bot-c3{border-top:3px solid #8a6ad0}.bot-pa{border-top:3px solid #d08a45}
@media(max-width:850px){.bots{grid-template-columns:1fr}}
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
<header><div><h1>مرکز کنترل معاملات LBank</h1><p>سه ربات روی یک حساب: شاهین · موج‌سوار · ققنوس</p></div>
<div class="row"><input id="pin" type="password" placeholder="PIN" aria-label="PIN" autocomplete="off" size="10">
<button id="connect">اتصال</button><span id="mode" class="badge">—</span><span id="active" class="badge">قطع</span></div></header>
<div id="message" role="status" aria-live="polite"></div>
<section class="panel note">این نسخه معاملات را شبیه‌سازی می‌کند. حالت پیش‌فرض DEMO از قیمت و کندل مصنوعی استفاده می‌کند. ارسال سفارش زندهٔ فیوچرز LBank در اتصال فعلی CCXT پشتیبانی نمی‌شود. سود و زیان با کارمزد تخمینی محاسبه می‌شود.</section>
<div class="row" style="margin-top:20px"><div id="views" style="display:flex;gap:8px" role="tablist" aria-label="نمای خلاصه"><button class="view" data-view="all">همه</button> <button class="view" data-view="bot">شاهین</button> <button class="view" data-view="c3">موج‌سوار</button> <button class="view" data-view="pa">ققنوس</button></div><p id="view_note">خلاصه و جدول پوزیشن‌ها بر اساس نمای انتخاب‌شده</p></div>
<div class="kpis"><section class="panel kpi"><p>سرمایهٔ حساب ($)</p><strong id="equity">—</strong><p id="equity_note">—</p></section>
<section class="panel kpi"><p>سود و زیان باز ($)</p><strong id="unrealized">—</strong></section>
<section class="panel kpi"><p>سود و زیان تحقق‌یافتهٔ ۲۴ ساعت ($)</p><strong id="realized">—</strong><p id="trades">—</p></section>
<section class="panel kpi"><p>پوزیشن‌ها و سفارش‌های در انتظار</p><strong id="slots">—</strong><p id="updated_sub">—</p><p id="updated">در انتظار اتصال</p></section>
<section class="panel kpi"><p>مارجین درگیر فعلی / بودجه مجاز ($)</p><strong id="margin">—</strong><p id="margin_pct">—</p><p id="pending_margin">—</p></section>
<section class="panel kpi"><p>لغزش واقعی اندازه‌گیری‌شده با دفتر سفارش LBank (bps، میانه / P90)</p><strong id="fq_main">—</strong><p id="fq_detail">—</p></section></div>
<section class="panel" id="botspanel"><div class="row"><h2>سه ربات</h2><p class="muted">هر سه روی یک حساب paper مشترک کار می‌کنند. خاموش کردن هر ربات فقط ورود جدیدش را متوقف می‌کند؛ پوزیشن‌های باز تا خروج مدیریت می‌شوند. تغییرات بدون ری‌استارت اعمال می‌شوند.</p></div>
<div class="bots">
<article class="bot bot-main" id="card_main"><div class="row"><div><h3>شاهین</h3><p class="sub muted">شکست Donchian و Kumo، کندل ۴ساعته · ۵ ارز اصلی</p></div><label class="switch"><input id="main_enabled" type="checkbox">روشن</label></div>
<dl><dt>ریسک هر معامله</dt><dd id="main_risk_v">—</dd><dt>پوزیشن / سفارش</dt><dd id="main_open">—</dd><dt>سود و زیان باز ($)</dt><dd id="main_unreal">—</dd><dt>سود ۲۴ ساعت ($)</dt><dd id="main_day">—</dd></dl></article>
<article class="bot bot-c3" id="card_c3"><div class="row"><div><h3>موج‌سوار</h3><p class="sub muted">پولبک در روند ۴ساعته با تأیید · ۱۰ ارز</p></div><label class="switch"><input id="c3_enabled" type="checkbox">روشن</label></div>
<dl><dt>ریسک هر معامله</dt><dd id="c3_risk_v">—</dd><dt>پوزیشن باز</dt><dd id="c3_positions">—</dd><dt>سود و زیان باز ($)</dt><dd id="c3_unrealized">—</dd><dt>سود ۲۴ ساعت ($)</dt><dd id="c3_realized">—</dd><dt>کل سود بسته‌شده ($)</dt><dd id="c3_total">—</dd><dt>معاملات</dt><dd id="c3_win">—</dd></dl><p id="c3badge" class="muted" style="font-size:12px">—</p><p id="c3_trades" hidden></p></article>
<article class="bot bot-pa" id="card_pa"><div class="row"><div><h3>ققنوس</h3><p class="sub muted">پرایس‌اکشن Key Reversal ۴ساعته · ۲۰ ارز</p></div><label class="switch"><input id="pa_enabled" type="checkbox">روشن</label></div>
<dl><dt>ریسک هر معامله</dt><dd id="pa_risk_v">—</dd><dt>پوزیشن / سفارش Stop</dt><dd id="pa_positions">—</dd><dt>سود و زیان باز ($)</dt><dd id="pa_unrealized">—</dd><dt>سود ۲۴ ساعت ($)</dt><dd id="pa_realized">—</dd><dt>کل سود بسته‌شده ($)</dt><dd id="pa_total">—</dd><dt>معاملات</dt><dd id="pa_win">—</dd></dl><p id="pabadge" class="muted" style="font-size:12px">—</p><p id="pa_trades" hidden></p></article>
</div>
<details><summary>تنظیمات موج‌سوار</summary>
<div class="fields" style="margin-top:18px">
<label class="field">ریسک هر معامله (%)<input id="c3_risk" type="number" min="0.01" max="1" step="0.01"></label>
<label class="field">حداکثر پوزیشن (۰ = بدون سقف تعداد)<input id="c3_max_positions" type="number" min="0" max="100" step="1"></label>
<label class="field">سقف نُوشنال (فقط در حالت PER_SLOT، ٪ سرمایه)<input id="c3_notional" type="number" min="1" max="100" step="1"></label>
<label class="field">تأیید ورود (تعداد کندل؛ صفر: بدون تأیید)<input id="c3_confirm" type="number" min="0" max="12" step="1"></label>
<label><input id="c3_weekend" type="checkbox">ورود نکردن وقتی کندل سیگنال در آخر هفته بسته می‌شود</label>
<label class="field" style="grid-column:span 2">نمادها (هر خط یکی، مثل AVAX/USDT:USDT)<textarea id="c3_symbols" style="min-height:90px;margin:0" spellcheck="false"></textarea></label></div>
<details><summary>ویرایش کامل JSON تنظیمات موج‌سوار</summary><textarea id="c3_editor" aria-label="Mojsavar JSON configuration" spellcheck="false"></textarea></details>
<div class="row" style="margin-top:18px"><p id="c3_dirty">تنظیمات موج‌سوار بارگذاری نشده است.</p><button id="c3_save" disabled>ذخیره تنظیمات موج‌سوار</button></div>
<details><summary>۲۰ معاملهٔ اخیر موج‌سوار</summary><div class="scroll"><table><thead><tr><th>نماد</th><th>جهت</th><th>ورود</th><th>خروج</th><th>سود و زیان ($)</th><th>دلیل</th></tr></thead><tbody id="c3_hist"></tbody></table></div></details></details>
<details><summary>تنظیمات ققنوس</summary>
<div class="fields" style="margin-top:18px">
<label class="field">ریسک هر معامله (%)<input id="pa_risk" type="number" min="0.01" max="1" step="0.01"></label>
<label class="field" style="grid-column:span 3">نمادها (هر خط یکی، مثل LINK/USDT:USDT)<textarea id="pa_symbols" style="min-height:90px;margin:0" spellcheck="false"></textarea></label></div>
<p class="muted">نسخهٔ C2: ورود با سفارش Stop روی سقف/کف کندل سیگنال تا بسته‌شدن کندل بعد، فقط وقتی بازار آن ارز در حالت کم‌نوسان است (رتبهٔ ATR کمتر از ۰٫۳۵۴ در ۵۰۰ کندل اخیر)؛ کندل سیگنال کوچک‌تر از 1.1 ATR رد می‌شود؛ خروج با استاپ، با ظاهر شدن Key Reversal مخالف، یا بعد از ۳۰ کندل (بدون هدف ثابت).</p>
<details><summary>ویرایش کامل JSON تنظیمات ققنوس</summary><textarea id="pa_editor" aria-label="Ghoghnous JSON configuration" spellcheck="false"></textarea></details>
<div class="row" style="margin-top:18px"><p id="pa_dirty">تنظیمات ققنوس بارگذاری نشده است.</p><button id="pa_save" disabled>ذخیره تنظیمات ققنوس</button></div>
<details><summary>سفارش‌های Stop در انتظار و ۲۰ معاملهٔ اخیر ققنوس</summary><div class="scroll"><table><thead><tr><th>نماد</th><th>جهت</th><th>سطح ورود</th><th>حد ضرر</th></tr></thead><tbody id="pa_orders"></tbody></table>
<table><thead><tr><th>نماد</th><th>جهت</th><th>ورود</th><th>خروج</th><th>سود و زیان ($)</th><th>دلیل</th></tr></thead><tbody id="pa_hist"></tbody></table></div></details></details></section>
<section class="panel"><div class="row"><h2>پوزیشن‌ها (شاهین، موج‌سوار و ققنوس، یک جدول)</h2><button class="danger" id="panic" disabled>🚨 بستن اضطراری همه پوزیشن‌ها (هر سه ربات) + توقف ورود</button></div>
<div class="scroll"><table><thead><tr><th>استراتژی</th><th>نماد</th><th>جهت</th><th>ورود / تریگر</th><th>قیمت زنده</th><th>حد ضرر</th><th>هدف اول</th><th>وضعیت</th><th>R</th><th>سود و زیان ($)</th><th>عملیات</th></tr></thead><tbody id="positions"><tr><td colspan="10">ابتدا PIN را وارد کنید.</td></tr></tbody></table></div></section>
<section class="panel"><div class="row"><h2>تنظیمات شاهین (ربات اصلی)</h2><button class="subtle" id="reload" disabled>بارگذاری مجدد</button></div>
<div class="fields"><label><input id="auto" type="checkbox">ورود خودکار شاهین (همان کلید روشن/خاموش بالا)</label><label><input id="dry" type="checkbox" checked disabled>حالت شبیه‌سازی (Dry-run)</label>
<label class="field">حالت استراتژی<select id="strategy"><option>MTF</option><option>SINGLE</option></select></label>
<label class="field">ریسک هر معامله (%)<input id="risk" type="number" min="0.1" max="5" step="0.1"></label>
<label class="field">درصد سرمایه مجاز درگیر (%)<input id="engaged" type="number" min="0.01" max="100" step="0.01"></label>
<label class="field">حداکثر پوزیشن هم‌زمان<input id="max_positions" type="number" min="1" max="100" step="1"></label>
<label class="field">مدل اهرم<select id="leverage"><option>DYNAMIC_MARGIN</option><option>FIXED_LEVERAGE</option></select></label>
<label class="field">استراتژی خروج و TP<select id="exit_tp"><option>STOP_TRAIL_DONCHIAN10</option><option>CLOSE_TRAIL_KIJUN</option><option>HYBRID_TRAIL_AND_HARD_TP</option></select></label>
<label class="field">تریل حالت ترکیبی<select id="hybrid_trail"><option>CLOSE_TRAIL_KIJUN</option><option>STOP_TRAIL_DONCHIAN10</option></select></label>
<label class="field">حاشیه تریل (ATR؛ صفر: بدون حاشیه)<input id="atr_trail" type="number" min="0" max="5" step="0.05"></label>
<label class="field">ضریب حد سود قطعی (R، صفر: غیرفعال)<input id="hard_tp" type="number" min="0" max="100" step="0.1"></label>
<label class="field">ضریب ریسک‌فری (R، صفر: غیرفعال)<input id="breakeven" type="number" min="0" max="20" step="0.1"></label>
<label class="field">پریست ایچیموکو<select id="preset"><option>crypto</option><option>standard</option></select></label>
<label class="field">دوره شکست Donchian<select id="donchian_period"><option>20</option><option>10</option></select></label>
<label class="field">استاپ اولیه<select id="initial_stop"><option>ATR2</option><option>KIJUN</option></select></label>
<label><input id="btc_gate" type="checkbox">فیلتر روند بیت‌کوین: وقتی کندل ۴ساعتهٔ BTC داخل ابر Kumo است، آلت‌ها وارد نشوند</label>
<label><input id="atr_regime" type="checkbox">فیلتر رژیم ATR (2A): وقتی ATR کندل سیگنال از میانهٔ ATR شصت کندل ۴ساعتهٔ قبل کمتر است، ورود و افزودن انجام نشود</label>
<label><input id="funding_short" type="checkbox">فیلتر funding: وقتی میانگین funding سه روز گذشته منفی است، شورت جدید باز نشود (نیازمند فایل‌های FUNDING_DIR)</label>
<label class="field">ضریب ATR استاپ اولیه (۲٫۵ فقط همراه V2 و فیلتر BTC آزموده شده)<input id="stop_atr_mult" type="number" min="1" max="5" step="0.1"></label>
<label class="field">بودجه مارجین<select id="margin_allocation"><option value="SHARED_POOL">مشترک بدون تقسیم اسلات</option><option value="PER_SLOT">سهم ثابت اسلات</option></select></label>
<label><input id="shared_account" type="checkbox">مدیریت سرمایه و سقف مارجین مشترک سه ربات (شاهین، موج‌سوار، ققنوس)</label>
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
function fillControls(){if(!cfg)return;$('shared_account').checked=!!cfg.portfolio_risk.shared_c3_account;$('margin_allocation').value=cfg.portfolio_risk.margin_allocation_mode;$('auto').checked=cfg.bot_control.auto_trade_enabled;$('dry').checked=cfg.bot_control.dry_run_mode;
 $('strategy').value=cfg.strategy_mode.mode;$('risk').value=cfg.risk_and_exit.risk_per_trade_pct*100;
 $('engaged').value=cfg.risk_and_exit.engaged_capital_pct*100;$('leverage').value=cfg.risk_and_exit.leverage_mode;$('max_positions').value=cfg.risk_and_exit.max_open_positions;
 const settings=cfg.strategy_settings;
 for(const id of ['exit_tp','hybrid_trail','hard_tp','breakeven','preset','donchian_period','initial_stop','pyramid','stop_anchor','pyramid_fraction','safe_pyramid','profit_floor','floor_trigger','floor_lock','width_filter','width_skip','width_mid','width_fraction','stop_atr_mult','btc_gate','funding_short','atr_regime','atr_trail'])$(id).disabled=!settings;
 $('strategy').disabled=!!settings;
 if(settings){$('atr_trail').value=settings.trail_atr_buffer??0;$('exit_tp').value=settings.exit_tp_mode;$('hybrid_trail').value=settings.hybrid_trail_mode;$('hard_tp').value=settings.hard_tp_rr;$('breakeven').value=settings.breakeven_trigger_rr;$('preset').value=settings.ichimoku_preset;$('donchian_period').value=settings.donchian_entry_period;$('initial_stop').value=settings.initial_stop_mode;$('pyramid').checked=!!settings.pyramid_enabled;$('stop_anchor').value=settings.initial_stop_anchor;
  $('pyramid_fraction').value=settings.pyramid_risk_fraction;$('safe_pyramid').checked=!!settings.safe_pyramid_enabled;$('profit_floor').checked=!!settings.profit_floor_enabled;$('floor_trigger').value=settings.profit_floor_trigger_r;$('floor_lock').value=settings.profit_floor_lock_r;
  $('width_filter').checked=!!settings.stop_width_filter_enabled;$('width_skip').value=settings.stop_width_skip_pct*100;$('width_mid').value=settings.stop_width_mid_pct*100;$('width_fraction').value=settings.stop_width_mid_risk_fraction;$('stop_atr_mult').value=settings.initial_stop_atr_mult;$('btc_gate').checked=!!settings.btc_regime_filter_enabled;$('funding_short').checked=!!settings.funding_short_filter_enabled;$('atr_regime').checked=!!settings.atr_regime_filter_enabled;}
 $('breakout').checked=cfg.al_brooks_filters.require_signal_bar_breakout;$('barb').checked=cfg.al_brooks_filters.enable_barb_wire_filter;$('h2').checked=cfg.al_brooks_filters.require_h2_l2_pullback;
}
async function loadConfig(){const result=await api('/api/config');cfg=result.data;etag=result.etag;$('shared_account').checked=!!cfg.portfolio_risk.shared_c3_account;$('margin_allocation').value=cfg.portfolio_risk.margin_allocation_mode;$('editor').value=JSON.stringify(cfg,null,2);fillControls();$('dirty').textContent='تنظیمات ذخیره شده است.';}
function controlsChanged(){if(!cfg)return;try{cfg=JSON.parse($('editor').value);}catch(e){message('ابتدا JSON را اصلاح کنید.',true);fillControls();return;}
 cfg.portfolio_risk.shared_c3_account=$('shared_account').checked;cfg.portfolio_risk.margin_allocation_mode=$('margin_allocation').value;
 cfg.bot_control.auto_trade_enabled=$('auto').checked;cfg.strategy_mode.mode=$('strategy').value;cfg.risk_and_exit.risk_per_trade_pct=Number($('risk').value)/100;
 cfg.risk_and_exit.engaged_capital_pct=Number($('engaged').value)/100;cfg.risk_and_exit.leverage_mode=$('leverage').value;cfg.risk_and_exit.max_open_positions=Number($('max_positions').value);
 if(cfg.strategy_settings){Object.assign(cfg.strategy_settings,{trail_atr_buffer:Number($('atr_trail').value),exit_tp_mode:$('exit_tp').value,hybrid_trail_mode:$('hybrid_trail').value,hard_tp_rr:Number($('hard_tp').value),breakeven_trigger_rr:Number($('breakeven').value),ichimoku_preset:$('preset').value,donchian_entry_period:Number($('donchian_period').value),initial_stop_mode:$('initial_stop').value});}
 if(cfg.strategy_settings){cfg.strategy_settings.pyramid_enabled=$('pyramid').checked;cfg.strategy_settings.initial_stop_anchor=$('stop_anchor').value;
  Object.assign(cfg.strategy_settings,{pyramid_risk_fraction:Number($('pyramid_fraction').value),safe_pyramid_enabled:$('safe_pyramid').checked,profit_floor_enabled:$('profit_floor').checked,profit_floor_trigger_r:Number($('floor_trigger').value),profit_floor_lock_r:Number($('floor_lock').value),
   stop_width_filter_enabled:$('width_filter').checked,stop_width_skip_pct:Number($('width_skip').value)/100,stop_width_mid_pct:Number($('width_mid').value)/100,stop_width_mid_risk_fraction:Number($('width_fraction').value),initial_stop_atr_mult:Number($('stop_atr_mult').value),btc_regime_filter_enabled:$('btc_gate').checked,funding_short_filter_enabled:$('funding_short').checked,atr_regime_filter_enabled:$('atr_regime').checked});}
 cfg.al_brooks_filters.require_signal_bar_breakout=$('breakout').checked;cfg.al_brooks_filters.enable_barb_wire_filter=$('barb').checked;cfg.al_brooks_filters.require_h2_l2_pullback=$('h2').checked;
 $('editor').value=JSON.stringify(cfg,null,2);$('dirty').textContent='تغییرات ذخیره نشده است.';
}
for(const id of ['margin_allocation','shared_account','auto','strategy','risk','breakout','barb','h2','engaged','max_positions','leverage','exit_tp','hybrid_trail','hard_tp','breakeven','preset','donchian_period','initial_stop','pyramid','stop_anchor','pyramid_fraction','safe_pyramid','profit_floor','floor_trigger','floor_lock','width_filter','width_skip','width_mid','width_fraction','stop_atr_mult','btc_gate','funding_short','atr_regime','atr_trail'])$(id).addEventListener('change',controlsChanged);
$('editor').addEventListener('input',()=>{$('dirty').textContent='تغییرات ذخیره نشده است.';});
$('editor').addEventListener('blur',()=>{try{cfg=JSON.parse($('editor').value);fillControls();}catch(e){message('JSON نامعتبر است.',true);}});
function renderFillQuality(fq){const main=$('fq_main'),detail=$('fq_detail');if(!fq||!fq.total){main.textContent='—';main.className='';detail.textContent='هنوز fill ثبت نشده (فقط با PAPER_DATA_MODE=csv-lbank و دفتر سفارش زنده)'+(fq&&fq.last_error?' | خطا: '+fq.last_error:'');return;}
 const f=x=>x?Number(x.median_bps).toFixed(1)+' / '+Number(x.p90_bps).toFixed(1):'—';main.textContent='ورود '+f(fq.entry)+' | خروج '+f(fq.exit);
 const worst=Math.max(fq.entry?fq.entry.median_bps:0,fq.exit?fq.exit.median_bps:0);main.className=worst>fq.assumed_bps_per_fill*2.5?'bad':'';
 detail.textContent='بک‌تست '+fq.assumed_bps_per_fill+' bps فرض کرده؛ '+fq.total+' fill'+(fq.last_error?' | خطا: '+fq.last_error:'');}
let lastBot=null,lastC3=null,lastPA=null,view='all';try{view=localStorage.getItem('view')||'all';}catch(e){}
function setView(v){view=v;try{localStorage.setItem('view',v);}catch(e){}draw();}
for(const b of document.querySelectorAll('.view'))b.onclick=()=>setView(b.dataset.view);
const sumOf=(...x)=>x.some(v=>v===null||v===undefined)?null:x.reduce((p,c)=>p+c,0);
const BOTNAME={bot:'شاهین',c3:'موج‌سوار',pa:'ققنوس'};
function drawSummary(){for(const x of document.querySelectorAll('.view'))x.classList.toggle('on',x.dataset.view===view);
 const S={bot:lastBot,c3:lastC3,pa:lastPA},keys=(view==='all'?['bot','c3','pa']:[view]).filter(k=>S[k]);if(!keys.length)return;
 let un=0,unOk=true,rl=0,tr=0,used=0;const parts=[];
 for(const k of keys){const x=S[k],u=k==='bot'?x.total_unrealized_pnl:x.unrealized_pnl_usd;if(u===null||u===undefined)unOk=false;else un+=u;
  rl+=x.daily_realized_pnl;tr+=x.daily_trades_count;used+=x.engaged_margin_usd||0;
  parts.push(BOTNAME[k]+': '+x.open_positions_count+(k==='bot'?' / '+x.max_open_positions:'')+(k==='pa'&&x.pending_orders&&x.pending_orders.length?' (+'+x.pending_orders.length+' سفارش Stop)':''));}
 const open=keys.reduce((a,k)=>a+S[k].open_positions_count,0);
 $('unrealized').textContent=number(unOk?un:null);$('unrealized').className=unOk&&un<0?'bad':'';$('realized').textContent=number(rl);$('realized').className=rl<0?'bad':'good';$('trades').textContent=tr+' خروج ثبت‌شده در ۲۴ ساعت';
 $('slots').textContent=open+' پوزیشن';$('updated_sub').textContent=parts.join(' · ');
 const b=lastBot,eq=b&&b.shared_account_enabled?b.equity_usd:(lastC3?lastC3.equity_usd:(b?b.equity_usd:null));
 $('equity').textContent=number(eq);$('equity_note').textContent=b&&b.shared_account_enabled?'سرمایهٔ مشترک سه ربات'+(view!=='all'&&view!=='bot'&&S[view]?' · '+BOTNAME[view]+' '+(S[view].realized_total_usd>=0?'+':'')+number(S[view].realized_total_usd)+' سود بسته‌شده':''):'سرمایهٔ paper شاهین (بدون سود و زیان دو ربات دیگر)';
 const allowed=b&&eq?eq*b.allowed_margin_pct/100:null;
 $('margin').textContent=number(used)+(allowed?' / '+number(allowed):'');
 $('margin_pct').textContent=eq?number(used/eq*100)+'٪ از حساب'+(b?' / '+number(b.allowed_margin_pct)+'٪ مجاز (هر سه ربات)':''):'—';
 $('pending_margin').textContent=b&&keys.includes('bot')?'مارجین رزروشدهٔ سفارش‌های در انتظار شاهین: $'+number(b.reserved_pending_margin_usd):'سفارش‌های Stop ققنوس تا فعال شدن مارجین نمی‌گیرند';
 $('fq_main').closest('section').style.display=view==='all'||view==='bot'?'':'none';
 $('view_note').textContent=view==='all'?'هر سه ربات (سرمایه و مارجین مشترک است)':view==='bot'?'فقط شاهین (Donchian + Kumo)':view==='c3'?'فقط موج‌سوار (پولبک روند ۴ساعته)':'فقط ققنوس (Key Reversal ۴ساعته)';
 drawCards();}
function drawCards(){const b=lastBot;
 if(b){$('main_enabled').checked=b.auto_trade_enabled;$('card_main').classList.toggle('off',!b.auto_trade_enabled);$('main_open').textContent=b.open_positions_count+' / '+b.max_open_positions;
  $('main_unreal').textContent=number(b.total_unrealized_pnl);$('main_day').textContent=number(b.daily_realized_pnl);}
 if(cfg)$('main_risk_v').textContent=number(cfg.risk_and_exit.risk_per_trade_pct*100)+'٪';
 if(lastC3)$('card_c3').classList.toggle('off',!lastC3.enabled);if(lastPA)$('card_pa').classList.toggle('off',!lastPA.enabled);}
async function toggleBot(key,on){try{const r=await api('/api/bots/toggle','POST',{bot:key,enabled:on});message(r.data.name+(on?' روشن شد؛ ورود جدید فعال است.':' خاموش شد؛ ورود جدید متوقف و پوزیشن‌های باز مدیریت می‌شوند.'));
  if(key==='main'){await loadConfig();await refresh();}else if(key==='c3'){await loadC3();await refreshC3();}else{await loadPA();await refreshPA();}}catch(e){message(e.message,true);}}
function drawPositions(){const rows=$('positions');rows.replaceChildren();const items=[];
 const want=k=>view==='all'||view===k;
 if(want('bot')&&lastBot)for(const p of lastBot.positions)items.push({kind:'bot',p});
 if(want('c3')&&lastC3)for(const p of lastC3.positions)items.push({kind:'c3',p});
 if(want('pa')&&lastPA)for(const p of lastPA.positions)items.push({kind:'pa',p});
 if(!items.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=11;td.textContent='پوزیشن بازی وجود ندارد.';tr.append(td);rows.append(tr);return;}
 for(const {kind,p} of items){const tr=document.createElement('tr');const tag=document.createElement('td'),sp=document.createElement('span');sp.className='tag'+(kind==='bot'?'':' '+kind);sp.textContent=BOTNAME[kind];tag.append(sp);tr.append(tag);
  const pnl=p.unrealized_pnl_usd;
  const values=kind==='c3'?[p.symbol,p.side==='long'?'خرید':'فروش',number(p.entry,6),number(p.live_price,6),number(p.stop,6),'—','تریل ATR',number(p.current_r),number(pnl)]
   :kind==='pa'?[p.symbol,p.side==='long'?'خرید':'فروش',number(p.entry,6),number(p.live_price,6),number(p.stop,6),p.target?number(p.target,6):'—','خروج: استاپ، برگشت مخالف یا ۳۰ کندل',number(p.current_r),number(pnl)]
   :[p.symbol,p.side==='long'?'خرید':'فروش',number(p.state==='STATE_PENDING_TRIGGER'?p.trigger_price:p.entry_price,6),number(p.live_price,6),number(p.active_sl,6),number(target(p),6),p.state,number(p.current_r),number(pnl)];
  values.forEach((v,index)=>{const td=document.createElement('td');td.textContent=v;if(index===0||index>=2)td.dir='ltr';if(index===8&&pnl!==null)td.className=pnl<0?'bad':'good';tr.append(td);});
  const td=document.createElement('td'),button=document.createElement('button');button.className='danger';const pending=kind==='bot'&&p.state==='STATE_PENDING_TRIGGER';button.textContent=pending?'لغو':'بستن آنی';
  button.onclick=async()=>{if(!confirm('بستن / لغو '+p.symbol+' ('+BOTNAME[kind]+')'+'؟'))return;button.disabled=true;try{await api(kind==='c3'?'/api/c3/close':kind==='pa'?'/api/pa/close':'/api/positions/close','POST',{symbol:p.symbol});await refresh();await refreshC3();await refreshPA();}catch(e){message(e.message,true);}finally{button.disabled=false;}};td.append(button);tr.append(td);rows.append(tr);}}
function draw(){drawSummary();drawPositions();}
function render(s){lastBot=s;$('mode').textContent=s.strategy_mode+' / '+(s.dry_run_mode?'DRY-RUN':'LIVE')+' / '+s.data_mode;$('active').textContent=s.auto_trade_enabled?'ورود فعال':'ورود متوقف';
 renderFillQuality(s.fill_quality);$('updated').textContent='آخرین دریافت: '+new Date().toLocaleTimeString('fa-IR');draw();
 const stamp=s.runtime.watchdog_at;$('health').textContent=stamp?'آخرین بررسی ربات: '+new Date(stamp*1000).toLocaleTimeString('fa-IR'):'ربات هنوز بررسی ثبت نکرده است';
 if(stamp&&Date.now()/1000-stamp>60)$('health').textContent+=' — بررسی ربات عقب افتاده است';
 if(s.price_errors.length)message('قیمت بعضی نمادها دریافت نشد؛ سود و زیان کامل در دسترس نیست.',true);
}
async function refresh(){if(!connected||polling)return;polling=true;try{const result=await api('/api/status');render(result.data);}catch(e){message(e.message,true);}finally{polling=false;}}
$('connect').onclick=async()=>{try{await loadConfig();await loadC3();await loadPA();connected=true;for(const id of ['save','panic','reload','c3_save','pa_save'])$(id).disabled=false;await refresh();await refreshC3();await refreshPA();$('message').style.display='none';}catch(e){connected=false;message(e.message,true);}};
$('pin').addEventListener('input',()=>{connected=false;for(const id of ['save','panic','reload','c3_save','pa_save'])$(id).disabled=true;$('active').textContent='قطع';});
$('save').onclick=async()=>{const b=$('save');b.disabled=true;try{const edited=JSON.parse($('editor').value);const result=await api('/api/config','PUT',edited,etag);cfg=result.data;etag=result.etag;fillControls();$('dirty').textContent='تنظیمات ذخیره شده است.';message('تنظیمات ذخیره شد.');await refresh();}catch(e){message(e.message,true);}finally{b.disabled=false;}};
$('reload').onclick=async()=>{try{await loadConfig();await loadC3();await loadPA();message('تنظیمات بارگذاری شد.');}catch(e){message(e.message,true);}};
$('panic').onclick=async()=>{if(!confirm('همهٔ پوزیشن‌های هر سه ربات بسته و ورود هر سه متوقف شود؟'))return;const b=$('panic');b.disabled=true;
 try{const result=await api('/api/positions/close-all','POST',{disable_auto_trade:true});const s=result.data;message(s.errors.length?'ورود متوقف شد؛ '+s.errors.length+' پوزیشن بسته نشد. دوباره تلاش کنید.':'همه پوزیشن‌ها بسته / لغو و ورود متوقف شد.',s.errors.length>0);await loadConfig();await loadC3();await loadPA();await refresh();await refreshC3();await refreshPA();}catch(e){message(e.message,true);}finally{b.disabled=false;}};

let c3cfg=null,c3etag=null;
const c3n=(v,n=2)=>number(v,n);
function c3Fill(){if(!c3cfg)return;$('c3_enabled').checked=c3cfg.enabled;$('c3_max_positions').value=c3cfg.max_open_positions;$('c3_risk').value=+(c3cfg.risk_per_trade_pct*100).toFixed(4);$('c3_notional').value=+(c3cfg.max_notional_pct*100).toFixed(2);
 $('c3_confirm').value=c3cfg.confirm_bars;$('c3_weekend').checked=c3cfg.skip_weekend;$('c3_symbols').value=c3cfg.symbols.join('\n');$('c3_editor').value=JSON.stringify(c3cfg,null,2);}
async function loadC3(){const r=await api('/api/c3/config');c3cfg=r.data;c3etag=r.etag;c3Fill();$('c3_dirty').textContent='تنظیمات موج‌سوار ذخیره شده است.';}
function c3Changed(){if(!c3cfg)return;try{c3cfg=JSON.parse($('c3_editor').value);}catch(e){message('ابتدا JSON تنظیمات موج‌سوار را اصلاح کنید.',true);c3Fill();return;}
 Object.assign(c3cfg,{max_open_positions:Number($('c3_max_positions').value),risk_per_trade_pct:Number($('c3_risk').value)/100,max_notional_pct:Number($('c3_notional').value)/100,confirm_bars:parseInt($('c3_confirm').value||'0',10),skip_weekend:$('c3_weekend').checked,
  symbols:$('c3_symbols').value.split(/[\s,]+/).filter(Boolean)});$('c3_editor').value=JSON.stringify(c3cfg,null,2);$('c3_dirty').textContent='تغییرات موج‌سوار ذخیره نشده است.';}
for(const id of ['c3_max_positions','c3_risk','c3_notional','c3_confirm','c3_weekend','c3_symbols'])$(id).addEventListener('change',c3Changed);
for(const [id,key] of [['main_enabled','main'],['c3_enabled','c3'],['pa_enabled','pa']])$(id).addEventListener('change',e=>toggleBot(key,e.target.checked));
$('c3_editor').addEventListener('input',()=>{$('c3_dirty').textContent='تغییرات موج‌سوار ذخیره نشده است.';});
$('c3_editor').addEventListener('blur',()=>{try{c3cfg=JSON.parse($('c3_editor').value);c3Fill();}catch(e){message('JSON تنظیمات موج‌سوار نامعتبر است.',true);}});
$('c3_save').onclick=async()=>{const b=$('c3_save');b.disabled=true;try{const edited=JSON.parse($('c3_editor').value);const r=await api('/api/c3/config','PUT',edited,c3etag);c3cfg=r.data;c3etag=r.etag;c3Fill();$('c3_dirty').textContent='تنظیمات موج‌سوار ذخیره شد و در چند ثانیه اعمال می‌شود.';await refreshC3();}catch(e){message(e.message,true);}finally{b.disabled=false;}};
function cell(tr,v,cls,ltr){const td=document.createElement('td');td.textContent=v;if(cls)td.className=cls;if(ltr)td.dir='ltr';tr.append(td);return td;}
function renderC3(s){lastC3=s;$('c3_enabled').checked=s.enabled;$('c3_risk_v').textContent=number(s.risk_per_trade_pct*100)+'٪';$('c3badge').textContent=(s.in_bot?'در حال اجرا داخل ربات':'thread خاموش است (C3_IN_BOT=0)')+' · '+(s.enabled?'ورود فعال':'ورود متوقف');
 $('c3_unrealized').textContent=c3n(s.unrealized_pnl_usd);$('c3_positions').textContent=s.open_positions_count+' از '+s.coins+' ارز';
 $('c3_realized').textContent=c3n(s.daily_realized_pnl);$('c3_realized').className=s.daily_realized_pnl<0?'bad':'good';$('c3_trades').textContent=s.daily_trades_count+' خروج در ۲۴ ساعت';
 $('c3_total').textContent=c3n(s.realized_total_usd);$('c3_total').className=s.realized_total_usd<0?'bad':'good';$('c3_win').textContent=s.trades_total?(s.trades_total+' · برد '+c3n(s.win_rate_pct,1)+'٪'):'—';
 const h=$('c3_hist');h.replaceChildren();for(const x of s.recent_trades){const tr=document.createElement('tr');cell(tr,x.symbol,'',1);cell(tr,x.side==='long'?'خرید':'فروش');cell(tr,c3n(x.entry,6),'',1);cell(tr,c3n(x.exit,6),'',1);cell(tr,c3n(x.pnl),x.pnl<0?'bad':'good',1);cell(tr,x.reason);h.append(tr);}draw();}
async function refreshC3(){if(!connected)return;try{const r=await api('/api/c3/status');renderC3(r.data);}catch(e){message('موج‌سوار: '+e.message,true);}}
let pacfg=null,paetag=null;
function paFill(){if(!pacfg)return;$('pa_enabled').checked=pacfg.enabled;$('pa_risk').value=+(pacfg.risk_per_trade_pct*100).toFixed(4);$('pa_symbols').value=pacfg.symbols.join('\n');$('pa_editor').value=JSON.stringify(pacfg,null,2);}
async function loadPA(){const r=await api('/api/pa/config');pacfg=r.data;paetag=r.etag;paFill();$('pa_dirty').textContent='تنظیمات ققنوس ذخیره شده است.';}
function paChanged(){if(!pacfg)return;try{pacfg=JSON.parse($('pa_editor').value);}catch(e){message('ابتدا JSON تنظیمات ققنوس را اصلاح کنید.',true);paFill();return;}
 Object.assign(pacfg,{risk_per_trade_pct:Number($('pa_risk').value)/100,symbols:$('pa_symbols').value.split(/[\s,]+/).filter(Boolean)});$('pa_editor').value=JSON.stringify(pacfg,null,2);$('pa_dirty').textContent='تغییرات ققنوس ذخیره نشده است.';}
for(const id of ['pa_risk','pa_symbols'])$(id).addEventListener('change',paChanged);
$('pa_editor').addEventListener('input',()=>{$('pa_dirty').textContent='تغییرات ققنوس ذخیره نشده است.';});
$('pa_editor').addEventListener('blur',()=>{try{pacfg=JSON.parse($('pa_editor').value);paFill();}catch(e){message('JSON تنظیمات ققنوس نامعتبر است.',true);}});
$('pa_save').onclick=async()=>{const b=$('pa_save');b.disabled=true;try{const edited=JSON.parse($('pa_editor').value);const r=await api('/api/pa/config','PUT',edited,paetag);pacfg=r.data;paetag=r.etag;paFill();$('pa_dirty').textContent='تنظیمات ققنوس ذخیره شد و در چند ثانیه اعمال می‌شود.';await refreshPA();}catch(e){message(e.message,true);}finally{b.disabled=false;}};
function renderPA(s){lastPA=s;$('pa_enabled').checked=s.enabled;$('pa_risk_v').textContent=number(s.risk_per_trade_pct*100)+'٪';$('pabadge').textContent=(s.in_bot?'در حال اجرا داخل ربات':'thread خاموش است (PA_IN_BOT=0)')+' · '+(s.enabled?'ورود فعال':'ورود متوقف');
 $('pa_unrealized').textContent=c3n(s.unrealized_pnl_usd);$('pa_positions').textContent=s.open_positions_count+' / '+s.pending_orders.length+' ('+s.coins+' ارز)';
 $('pa_realized').textContent=c3n(s.daily_realized_pnl);$('pa_realized').className=s.daily_realized_pnl<0?'bad':'good';$('pa_trades').textContent=s.daily_trades_count+' خروج در ۲۴ ساعت';
 $('pa_total').textContent=c3n(s.realized_total_usd);$('pa_total').className=s.realized_total_usd<0?'bad':'good';$('pa_win').textContent=s.trades_total?(s.trades_total+' · برد '+c3n(s.win_rate_pct,1)+'٪'):'—';
 const o=$('pa_orders');o.replaceChildren();for(const x of s.pending_orders){const tr=document.createElement('tr');cell(tr,x.symbol,'',1);cell(tr,x.side==='long'?'خرید':'فروش');cell(tr,c3n(x.level,6),'',1);cell(tr,c3n(x.stop,6),'',1);o.append(tr);}
 const h=$('pa_hist');h.replaceChildren();for(const x of s.recent_trades){const tr=document.createElement('tr');cell(tr,x.symbol,'',1);cell(tr,x.side==='long'?'خرید':'فروش');cell(tr,c3n(x.entry,6),'',1);cell(tr,c3n(x.exit,6),'',1);cell(tr,c3n(x.pnl),x.pnl<0?'bad':'good',1);cell(tr,x.reason);h.append(tr);}draw();}
async function refreshPA(){if(!connected)return;try{const r=await api('/api/pa/status');renderPA(r.data);}catch(e){message('ققنوس: '+e.message,true);}}
setInterval(()=>{refresh();refreshC3();refreshPA();},5000);
</script></body></html>'''

app = create_app()
