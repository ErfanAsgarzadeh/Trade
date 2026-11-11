"""Authenticated Persian RTL control panel for the paper futures engine."""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Response, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import c3_sleeve
import pa_sleeve
import license_access
from deployment_security import dashboard_secret, LoginThrottle
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


BOT_NAMES = {"main": "Shahin", "c3": "Mojsavar", "pa": "Ghoghnous"}


def revision(c: dict) -> str:
    return '"' + hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest() + '"'


def create_app(engine: Engine | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if engine is None:
            if len(dashboard_secret()) < 16:
                raise ValueError('Set BOT_PIN or BOT_PIN_FILE to a secret of at least 16 characters')
            application.state.engine = Engine(ConfigStore(), Database(), MarketData())
        else:
            application.state.engine = engine
        yield

    application = FastAPI(title="LBank Ichimoku Paper Dashboard", lifespan=lifespan)
    throttle = LoginThrottle()

    async def authorized(request: Request, x_bot_pin: str = Header(default="")):
        client = request.client.host if request.client else 'unknown'
        if throttle.blocked(client):
            raise HTTPException(status_code=429, detail='Too many failed login attempts; retry later')
        expected = dashboard_secret()
        if not expected or not secrets.compare_digest(x_bot_pin.encode(), expected.encode()):
            throttle.failed(client)
            raise HTTPException(status_code=401, detail="Incorrect PIN")
        throttle.succeeded(client)

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

    @application.get('/healthz')
    def health():
        return {'status': 'ok'}

    @application.get('/api/license', dependencies=[Depends(authorized)])
    def license_status():
        return license_access.status()

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
                errors.append({"symbol": "Mojsavar/Ghoghnous", "error": str(exc)})
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
            "execution_note": LIVE_LIMITATION, "license": license_access.status()}

    @application.post("/api/positions/close", dependencies=[Depends(authorized)])
    def close(payload: CloseRequest):
        try:
            return bot().close_symbol(payload.symbol)
        except KeyError:
            raise HTTPException(404, "Position not found")
        except (ConfigError, LiveUnavailable):
            raise
        except Exception:
            LOG.exception("Close failed for %s", payload.symbol)
            raise HTTPException(503, "Could not close the position; it is still open")

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
            result = {**result, "errors": list(result.get("errors", [])) + [{"symbol": "Mojsavar", "error": str(exc)}]}
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
            result = {**result, "errors": list(result.get("errors", [])) + [{"symbol": "Ghoghnous", "error": str(exc)}]}
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
                raise HTTPException(409, "Mojsavar settings changed; reload and try again")
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
            raise HTTPException(404, "Mojsavar position not found")
        try:
            return {"symbol": payload.symbol, "pnl": sl.close(pos, bot().data.price(payload.symbol), "manual", time.time())}
        except Exception:
            LOG.exception("C3 close failed for %s", payload.symbol)
            raise HTTPException(503, "Could not close the Mojsavar position; it is still open")

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
                raise HTTPException(409, "Ghoghnous settings changed; reload and try again")
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
            raise HTTPException(404, "Ghoghnous position not found")
        try:
            return {"symbol": payload.symbol, "pnl": sl.close(pos, bot().data.price(payload.symbol), "manual", time.time())}
        except Exception:
            LOG.exception("PA close failed for %s", payload.symbol)
            raise HTTPException(503, "Could not close the Ghoghnous position; it is still open")

    # ---- performance (all three bots): read only ----
    def runtime_folder():
        from pathlib import Path
        return Path(os.getenv("RISK_DIR", str(bot().db.path.parent)))

    def all_trades():
        out = []
        with bot().db.connect() as db:
            for s, side, pnl, t, e, x, why in db.execute("SELECT symbol,side,pnl_usd,closed_at,entry_price,exit_price,reason FROM trade_history WHERE dry_run=1"):
                out.append(dict(bot="main", symbol=s, side=side, pnl=float(pnl), closed=float(t), entry=e, exit=x, reason=why))
        for key, (_, store) in (("c3", c3_paths()), ("pa", pa_paths())):
            try:
                with store.db() as db:
                    for s, side, pnl, t, e, x, why in db.execute("SELECT symbol,side,pnl,closed,entry,exit,reason FROM trades"):
                        out.append(dict(bot=key, symbol=s, side=side, pnl=float(pnl or 0), closed=float(t or 0), entry=e, exit=x, reason=why))
            except Exception:
                LOG.exception("%s trades unreadable", key)
        return sorted(out, key=lambda x: x["closed"])

    @application.get("/api/performance", dependencies=[Depends(authorized)])
    def performance_view():
        import performance
        return performance.summarize(all_trades(), float(bot().paper_seed), performance.read_snapshots(runtime_folder() / "equity_history.jsonl"))

    @application.get("/api/account", dependencies=[Depends(authorized)])
    def account_view():
        import lbank_account
        return {"mode": "paper", "live_available": False, "keys": lbank_account.key_status(),
                "live_reason": "Live LBank futures execution is not built yet: LBank's published contract API documents no "
                               "order, leverage or position endpoints, and the pinned CCXT adapter only trades spot. "
                               "The bots stay on the paper account."}

    @application.post("/api/account/test", dependencies=[Depends(authorized)])
    def account_test():
        import lbank_account
        return lbank_account.account_check()

    # ---- live execution through the mirror service (live_mirror.py, docker service lbank-live) ----
    @application.get("/api/live", dependencies=[Depends(authorized)])
    def live_view():
        import live_mirror as LM
        cfg = LM.read_config();folder = LM.folder()
        st = {}
        try:st = json.loads((folder / f"live_state_{cfg['mode']}_{cfg['exchange']}.json").read_text())
        except Exception:pass
        log = []
        p = folder / "live_log.jsonl"
        if p.is_file():
            for line in p.read_text().splitlines()[-40:]:
                try:log.append(json.loads(line))
                except Exception:pass
        keys = {"thetruetrade": bool(os.getenv("TTT_API_KEY") and os.getenv("TTT_API_SECRET")),
                "binance": bool(os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"))}
        running = bool(st.get("last_cycle")) and time.time() - st.get("last_cycle", 0) < 120
        unresolved = []
        for exchange in ("thetruetrade", "binance"):
            live_path = folder / f"live_state_live_{exchange}.json"
            if not live_path.is_file():
                continue
            try:
                live_state = json.loads(live_path.read_text())
                for symbol, op in (live_state.get("pending_orders") or {}).items():
                    unresolved.append({"exchange": exchange, "symbol": symbol,
                                       "action": op.get("action", "unknown")})
            except (ValueError, TypeError, AttributeError, OSError):
                unresolved.append({"exchange": exchange, "symbol": "unknown",
                                   "action": "unreadable_live_state"})
        import exchanges as EX
        try:
            cert = EX.TheTrueTrade().load_certification()
            certification = {"valid": True, "created_at": cert["created_at"], "min_notional_usd": cert["min_notional_usd"],
                             "expires_at": cert["created_at"] + EX.CERT_MAX_AGE_DAYS * 86400}
        except EX.ExchangeError as exc:
            certification = {"valid": False, "reason": str(exc)}
        return {"config": cfg, "keys": keys, "running": running, "certification": certification,
                "unresolved_live_operations": unresolved,
                "state": {k: st.get(k) for k in ("managed", "paused", "errors", "equity_live", "equity_paper", "ratio", "unmanaged", "last_cycle")},
                "log": log[::-1]}

    @application.get("/api/live/readiness", dependencies=[Depends(authorized)])
    def live_readiness():
        """Run a strictly read-only TheTrueTrade preflight; this endpoint cannot enable trading."""
        import exchanges as EX
        import live_mirror as LM
        import ttt_live_readiness as readiness

        cfg, status = readiness.load_local_config(LM.folder() / "live_config.json")
        try:
            return readiness.run(EX.TheTrueTrade(), cfg, status)
        except Exception as exc:
            # Do not expose API response bodies, account identifiers, or credentials.
            return {
                "read_only": True,
                "conclusion": "ERROR_NOT_READY",
                "configuration_file_status": status,
                "error_category": "READ_ONLY_EXCHANGE_OR_CONFIG_ERROR",
                "error_type": type(exc).__name__,
                "live_trading_authorized": False,
            }

    @application.put("/api/live/config", dependencies=[Depends(authorized)])
    def live_config(payload: dict):
        import live_mirror as LM
        cur = LM.read_config();new = {**cur, **{k: payload[k] for k in LM.DEFAULT if k in payload}}
        if new["mode"] == "live" and cur["mode"] != "live" and payload.get("confirm") != "LIVE":
            raise HTTPException(422, "Type LIVE to confirm real orders")
        if new["mode"] == "live":
            # Live entries need proven stop protection: only TheTrueTrade with a valid certification from
            # ttt_live_certify.py (real stop readback, move, partial close and exchange-triggered stop) is unlocked.
            import exchanges as EX
            if new["exchange"] != "thetruetrade":
                raise HTTPException(409, "Live execution locked: exchange stop-loss confirmation is not validated for this exchange. Use dry/off.")
            try:
                EX.TheTrueTrade().load_certification()
            except EX.ExchangeError as exc:
                raise HTTPException(409, f"Live execution locked: exchange stop-loss confirmation is not validated ({exc}).")
        try:
            v = LM.write_config(new)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        (LM.folder() / "live_command.json").write_text(json.dumps({"resume": True}))
        LOG.warning("Live mirror settings changed: %s", v)
        return v

    @application.post("/api/live/test", dependencies=[Depends(authorized)])
    def live_test(payload: dict):
        import exchanges as EX
        name = payload.get("exchange", "thetruetrade")
        try:
            a = EX.make(name);m = a.markets();out = {"ok": True, "markets": len(m)}
            try:
                out["equity"] = a.equity();out["positions"] = [dict(symbol=p.symbol, side=p.side, qty=p.qty) for p in a.positions().values()]
                out["message"] = f"Connected to {name}: {len(m)} USDT perpetual markets, futures equity {out['equity']:.2f} USDT."
            except Exception as exc:
                out.update(ok=False, message=f"Public data OK ({len(m)} markets), but the account call failed: {exc}")
            return out
        except Exception as exc:
            return {"ok": False, "message": f"{name}: {exc}"}

    @application.post("/api/live/close-all", dependencies=[Depends(authorized)])
    def live_close_all():
        import live_mirror as LM
        (LM.folder() / "live_command.json").write_text(json.dumps({"close_all": True}))
        return {"queued": True, "note": "The mirror closes every position it opened within ~10 s and stops new entries."}

    @application.post("/api/account/mode", dependencies=[Depends(authorized)])
    def account_mode(payload: dict):
        if payload.get("mode") != "paper":
            raise HTTPException(409, "Live trading is locked in this build; the bots stay on paper.")
        return {"mode": "paper"}

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
                raise HTTPException(409, "Config changed; reload and try again")
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
<html lang="en" dir="ltr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LBank Trading Control Center</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>

*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:radial-gradient(1200px 600px at 10% -10%,var(--page-tint) 0,transparent 60%),radial-gradient(900px 500px at 100% 0,var(--page-tint) 0,transparent 55%),var(--bg);color:var(--text);font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased;font-feature-settings:'tnum' 1,'cv11' 1;min-height:100vh}
main{max-width:1480px;margin:auto;padding:22px 28px 40px}
header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:6px 0 18px}
.brand{display:flex;align-items:center;gap:14px}.logo{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,var(--accent),var(--accent2));display:grid;place-items:center;font-weight:700;font-size:18px;box-shadow:0 8px 24px -8px var(--glow-subtle)}
h1{font-size:21px;margin:0;font-weight:700;letter-spacing:-.02em}h2{font-size:16px;margin:0;font-weight:600;letter-spacing:-.01em}h3{font-size:14px;margin:0;font-weight:600}
p{margin:2px 0;color:var(--muted)}.muted{color:var(--muted)}.small{font-size:12px}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.gap{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.panel{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:16px;padding:20px;margin-top:18px;box-shadow:0 10px 30px -18px var(--shadow-color)}
.badge{display:inline-flex;align-items:center;gap:6px;padding:4px 11px;border-radius:999px;background:var(--surface-elevated);border:1px solid var(--line2);font-size:12px;color:var(--text-primary);white-space:nowrap}
.badge.ok{color:var(--good);border-color:var(--success-border);background:var(--success-background)}.badge.warn{color:var(--warn);border-color:var(--warning-border);background:var(--warning-background)}.badge.bad{color:var(--bad);border-color:var(--error-border);background:var(--error-background)}
.dot{width:8px;height:8px;border-radius:50%;background:currentColor;display:inline-block}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;padding:5px;background:var(--surface-inset);border:1px solid var(--line);border-radius:14px;width:fit-content;max-width:100%;overflow:auto}
.tab{background:transparent;color:var(--muted);padding:8px 16px;border-radius:10px;font-weight:500}.tab:hover{color:var(--text);background:var(--surface-hover)}.tab.on{background:linear-gradient(135deg,var(--primary),var(--primary));color:var(--text-primary);box-shadow:0 6px 18px -8px var(--primary)}
.pane{display:none}.pane.on{display:block;animation:fade .25s ease}@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:18px}.kpis .panel{margin-top:0}
.kpi p:first-child{font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.kpi strong{display:block;font-size:28px;font-weight:650;letter-spacing:-.02em;font-variant-numeric:tabular-nums;margin:6px 0 2px}
.bar{height:6px;border-radius:99px;background:var(--surface-elevated);overflow:hidden;margin-top:8px}.bar>i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--accent),var(--accent2))}
.grid2{display:grid;grid-template-columns:2fr 1fr;gap:18px}.grid2 .panel,.grid3 .panel{margin-top:0}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.chart{position:relative;height:300px;margin-top:12px}.chart.sm{height:200px}
input,select,textarea{background:var(--input);border:1px solid var(--line2);color:var(--text-primary);border-radius:9px;padding:9px 11px;font:inherit}input:focus,select:focus,textarea:focus{outline:2px solid var(--focus-ring);border-color:transparent}
input[type=checkbox]{width:18px;height:18px;accent-color:var(--primary)}
button{border:0;background:var(--primary);color:var(--primary-foreground);padding:9px 15px;border-radius:9px;cursor:pointer;font:inherit;font-weight:500;transition:filter .15s}button:hover{filter:brightness(1.12)}button:disabled{opacity:.45;cursor:not-allowed}
.danger{background:var(--danger-solid)}.subtle{background:var(--surface-elevated);color:var(--text-primary)}.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.view{background:var(--surface-elevated);color:var(--muted)}.view.on{background:var(--primary-soft);color:var(--text-primary);outline:1px solid var(--primary)}
.tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:600;background:var(--primary-soft);color:var(--primary)}.tag.c3{background:var(--ai-soft);color:var(--ai-accent)}.tag.pa{background:var(--premium-soft);color:var(--premium-text)}
.scroll{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:12.5px}th,td{padding:11px 10px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em;position:sticky;top:0;background:var(--panel)}tbody tr:hover{background:var(--surface-hover)}
td[dir=ltr],.mono{font-family:'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace;font-size:12px}.num{text-align:right}
.bots{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:14px}
.bot{background:linear-gradient(180deg,var(--surface-elevated),var(--surface));border:1px solid var(--line);border-radius:16px;padding:18px;min-width:0;position:relative;overflow:hidden}
.bot:before{content:'';position:absolute;inset:0 0 auto 0;height:3px}.bot-main:before{background:var(--main)}.bot-c3:before{background:var(--c3)}.bot-pa:before{background:var(--pa)}
.bot h3{font-size:18px}.bot .sub{margin:0 0 8px;font-size:12px}.bot dl{display:grid;grid-template-columns:1fr auto;gap:6px 12px;margin:12px 0 0;font-size:13px}
.bot dt{color:var(--muted)}.bot dd{margin:0;text-align:right;font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12.5px}.bot.off{opacity:.55}
.switch{display:inline-flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;background:var(--surface-elevated);padding:5px 10px;border-radius:999px}
.fields{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}label{display:flex;gap:8px;align-items:center;flex-wrap:wrap;color:var(--text-primary)}.field{display:flex;flex-direction:column;align-items:stretch;gap:6px;font-size:12.5px}
textarea{width:100%;min-height:340px;direction:ltr;text-align:left;font:12px/1.7 'JetBrains Mono',ui-monospace,monospace;resize:vertical;margin:14px 0}
#message{display:none;padding:12px 14px;border-radius:12px;margin-top:14px;white-space:pre-wrap;border:1px solid var(--border-strong);background:var(--surface-hover)}
.note{border-left:3px solid var(--warn);font-size:13px;color:var(--text-primary)}details{margin-top:16px}summary{cursor:pointer;font-weight:600;color:var(--text-primary)}footer{margin-top:22px;color:var(--muted);font-size:12px}
.gauge{position:relative;height:14px;border-radius:99px;background:linear-gradient(90deg,var(--loss) 0 30%,var(--border) 30% 70%,var(--profit) 70%);margin:14px 0 6px}
.gauge>b{position:absolute;top:-5px;width:4px;height:24px;border-radius:3px;background:var(--text-primary);box-shadow:0 0 0 3px var(--primary-soft);transform:translateX(-2px);transition:left .4s}
.scale{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
.big{font-size:34px;font-weight:700;letter-spacing:-.02em}.pill{padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600}
.pill.good{background:var(--success-background)}.pill.bad{background:var(--error-background)}.pill.normal{background:var(--surface-elevated);color:var(--text-primary)}
.empty{padding:26px;text-align:center;color:var(--muted)}
.mtab td.pos{color:var(--good)}.mtab td.neg{color:var(--bad)}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}.grid3{grid-template-columns:1fr}}
@media(max-width:850px){main{padding:14px}.bots{grid-template-columns:1fr}.fields{grid-template-columns:repeat(2,1fr)}.kpis{grid-template-columns:1fr}}
@media(max-width:450px){.fields{grid-template-columns:1fr}}

.tab.on,.view.on{background:var(--primary);color:var(--primary-foreground);}
.logo{background:var(--brand-gradient);color:var(--primary-foreground);box-shadow:var(--shadow-soft);}
.danger{color:var(--danger-on-solid);}
button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--focus-ring);outline-offset:3px;}
button:disabled{background:var(--disabled-background);color:var(--disabled-foreground);opacity:1;}
.chart canvas{background:var(--chart-background);max-width:100%;}
.panel,.chart,.grid2,.grid3,.kpis,.fields{min-width:0;}
#views{flex-wrap:wrap;}
.scale{flex-wrap:wrap;gap:4px;}
@media(max-width:1100px){.grid2,.grid3{grid-template-columns:minmax(0,1fr);}}
@media(max-width:450px){.fields,.kpis{grid-template-columns:minmax(0,1fr);}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important;}}
</style></head><body><main>
<header><div class="brand"><div class="logo">L</div><div><h1>LBank Trading Control Center</h1><p class="small">Shahin · Mojsavar · Ghoghnous on one paper account · momentum-rank sizing</p></div></div>
<div class="gap"><div class="theme-switcher"><label for="terminal-appearance">Appearance</label><select id="terminal-appearance" data-legacy-theme-switch><option value="dark">Dark</option><option value="light">Light</option><option value="system">System</option></select></div><span id="mode" class="badge">—</span><span id="active" class="badge">Offline</span>
<input id="pin" type="password" placeholder="PIN" aria-label="PIN" autocomplete="off" size="8"><button id="connect">Connect</button></div></header>
<nav class="tabs" role="tablist"><button class="tab" data-tab="overview">Overview</button><button class="tab" data-tab="positions">Positions</button><button class="tab" data-tab="performance">Performance</button><button class="tab" data-tab="settings">Settings</button></nav>
<div id="message" role="status" aria-live="polite"></div>

<section class="pane" data-pane="overview">
<div class="row" style="margin-top:16px"><div id="views" style="display:flex;gap:8px" role="tablist" aria-label="Summary view"><button class="view" data-view="all">All</button> <button class="view" data-view="bot">Shahin</button> <button class="view" data-view="c3">Mojsavar</button> <button class="view" data-view="pa">Ghoghnous</button></div><p id="view_note" class="small">Summary and position table follow the selected view</p></div>
<div class="kpis">
<section class="panel kpi"><p>Account equity ($)</p><strong id="equity">—</strong><p id="equity_note" class="small">—</p><p id="ret_total" class="small">—</p></section>
<section class="panel kpi"><p>Open P&amp;L ($)</p><strong id="unrealized">—</strong><p id="slots_sub" class="small"><span id="slots">—</span> · <span id="updated_sub">—</span></p></section>
<section class="panel kpi"><p>Realized P&amp;L, 24h ($)</p><strong id="realized">—</strong><p id="trades" class="small">—</p><p id="pnl_30d" class="small">—</p></section>
<section class="panel kpi"><p>Drawdown now / max</p><strong id="dd_now">—</strong><p id="dd_max" class="small">—</p><div class="bar"><i id="dd_bar" style="width:0"></i></div></section>
<section class="panel kpi"><p>Margin in use / allowed ($)</p><strong id="margin">—</strong><p id="margin_pct" class="small">—</p><p id="pending_margin" class="small">—</p><div class="bar"><i id="margin_bar" style="width:0"></i></div></section>
<section class="panel kpi"><p>Win rate (all closed trades)</p><strong id="winrate">—</strong><p id="pf" class="small">—</p></section>
<section class="panel kpi"><p>Momentum sizing</p><strong id="mom_state">—</strong><p class="small">New entries: risk x0.5 to x1.5 by 30-day momentum rank</p></section>
<section class="panel kpi"><p>Slippage vs LBank book (bps, median / P90)</p><strong id="fq_main">—</strong><p id="fq_detail" class="small">—</p></section>
</div>
<div class="grid2" style="margin-top:18px"><section class="panel"><div class="row"><h2>Equity and drawdown</h2><span class="small muted" id="eq_src">—</span></div><div class="chart"><canvas id="eq_chart"></canvas></div><div class="chart sm"><canvas id="dd_chart"></canvas></div></section>
<section class="panel"><div class="row"><h2>Daily P&amp;L, last 30 days</h2></div><div class="chart" style="height:520px"><canvas id="daily_chart"></canvas></div></section></div>
<section class="panel" id="botspanel"><div class="row"><h2>Three bots</h2><p class="small">Switching a bot off only stops its new entries; open positions keep being managed. Changes apply without a restart.</p></div>
<div class="bots">
<article class="bot bot-main" id="card_main"><div class="row"><div><h3>Shahin</h3><p class="sub muted">Donchian + Kumo breakout, 4h · 5 major coins</p></div><label class="switch"><input id="main_enabled" type="checkbox">On</label></div>
<dl><dt>Risk per trade</dt><dd id="main_risk_v">—</dd><dt>Positions / orders</dt><dd id="main_open">—</dd><dt>Open P&amp;L ($)</dt><dd id="main_unreal">—</dd><dt>24h profit ($)</dt><dd id="main_day">—</dd></dl></article>
<article class="bot bot-c3" id="card_c3"><div class="row"><div><h3>Mojsavar</h3><p class="sub muted">4h trend pullback with confirmation · 10 coins</p></div><label class="switch"><input id="c3_enabled" type="checkbox">On</label></div>
<dl><dt>Risk per trade</dt><dd id="c3_risk_v">—</dd><dt>Open positions</dt><dd id="c3_positions">—</dd><dt>Open P&amp;L ($)</dt><dd id="c3_unrealized">—</dd><dt>24h profit ($)</dt><dd id="c3_realized">—</dd><dt>Total closed profit ($)</dt><dd id="c3_total">—</dd><dt>Trades</dt><dd id="c3_win">—</dd></dl><p id="c3badge" class="muted" style="font-size:12px">—</p><p id="c3_trades" hidden></p></article>
<article class="bot bot-pa" id="card_pa"><div class="row"><div><h3>Ghoghnous</h3><p class="sub muted">4h price-action Key Reversal · 20 coins</p></div><label class="switch"><input id="pa_enabled" type="checkbox">On</label></div>
<dl><dt>Planned risk per trade</dt><dd id="pa_risk_v">—</dd><dt>Positions / Stop orders</dt><dd id="pa_positions">—</dd><dt>Open P&amp;L ($)</dt><dd id="pa_unrealized">—</dd><dt>24h profit ($)</dt><dd id="pa_realized">—</dd><dt>Total closed profit ($)</dt><dd id="pa_total">—</dd><dt>Trades</dt><dd id="pa_win">—</dd></dl><p id="pabadge" class="muted" style="font-size:12px">—</p><p id="pa_trades" hidden></p></article>
</div></section>
</section>

<section class="pane" data-pane="positions">
<section class="panel"><div class="row"><h2>Open positions (all three bots)</h2><button class="danger" id="panic" disabled>🚨 Emergency close all + stop entries</button></div>
<div class="scroll"><table><thead><tr><th>Strategy</th><th>Symbol</th><th>Side</th><th>Entry / trigger</th><th>Live price</th><th>Stop loss</th><th>Target 1</th><th>Status</th><th>R</th><th>P&amp;L ($)</th><th>Action</th></tr></thead><tbody id="positions"><tr><td colspan="10">Enter the PIN first.</td></tr></tbody></table></div></section>
<section class="panel note">Paper trading only. DEMO mode uses synthetic prices. Live LBank order placement is not supported by the pinned CCXT adapter. P&amp;L uses estimated fees.</section>
</section>

<section class="pane" data-pane="performance">
<div class="grid3" style="margin-top:18px" id="perf_cards"></div>
<section class="panel"><div class="row"><h2>Monthly profit</h2><span class="small muted">closed trades, % of the equity at the start of the month</span></div><div class="scroll"><table class="mtab"><thead><tr><th>Month</th><th class="num">Shahin</th><th class="num">Mojsavar</th><th class="num">Ghoghnous</th><th class="num">Total ($)</th><th class="num">Total (%)</th><th class="num">Trades</th><th class="num">Win %</th></tr></thead><tbody id="monthly"></tbody></table></div></section>
<section class="panel"><div class="row"><h2>Trade log</h2><div class="gap"><select id="hist_filter"><option value="all">All bots</option><option value="main">Shahin</option><option value="c3">Mojsavar</option><option value="pa">Ghoghnous</option></select></div></div>
<div class="scroll" style="max-height:560px"><table><thead><tr><th>Closed (UTC)</th><th>Bot</th><th>Symbol</th><th>Side</th><th class="num">Entry</th><th class="num">Exit</th><th class="num">P&amp;L ($)</th><th>Reason</th></tr></thead><tbody id="hist_all"></tbody></table></div></section>
</section>

<section class="pane" data-pane="settings">
<section class="panel"><div class="row"><h2>Trading account</h2><span class="badge ok" id="acct_mode"><span class="dot"></span>PAPER</span></div>
<div class="grid2" style="grid-template-columns:1fr 1fr;margin-top:14px">
<section class="panel" style="border-color:var(--success-border)"><div class="row"><h3>Paper account</h3><span class="pill good">Active</span></div><p class="small">Simulated fills at live LBank prices with estimated fees. No real money is used.</p></section>
<section class="panel"><div class="row"><h3>🔒 Live LBank futures</h3><span class="pill bad">Locked</span></div>
<p class="small" id="acct_reason">—</p><p class="small">API key on the server: <b id="acct_keys">—</b> (set LBANK_API_KEY and LBANK_SECRET_KEY in the server's .env; keys are never entered in this page)</p>
<div class="gap" style="margin-top:10px"><button class="subtle" id="acct_test" disabled>Test LBank connection (read-only)</button><label class="switch"><input id="acct_live" type="checkbox" disabled>Use the live account</label></div>
<p class="small" id="acct_result"></p></section></div></section>
<section class="panel" id="live_panel"><div class="row"><div><h2>Live execution (exchange mirror)</h2><p class="small">The bots keep trading on paper; the mirror copies their NEW positions, stops, partial exits and exits to a real exchange account, sized by account equity. Positions open before switching on are not copied. Only positions opened by the mirror are ever touched.</p></div><span class="badge" id="lv_badge">—</span></div>
<div class="fields" style="margin-top:14px">
<label class="field">Exchange<select id="lv_exchange"><option value="thetruetrade">TheTrueTrade</option><option value="binance">Binance USDT-M</option></select></label>
<label class="field">Mode<select id="lv_mode"><option value="off">Off</option><option value="dry">Dry run (simulated orders, real prices)</option><option value="live">LIVE (real orders)</option></select></label>
<label class="field">Size factor (1 = same % risk as paper)<input id="lv_size" type="number" min="0.01" max="3" step="0.01"></label>
<label class="field">Leverage<input id="lv_lev" type="number" min="1" max="20" step="1"></label>
<label class="field">Max position size (USD notional)<input id="lv_cap" type="number" min="1" step="1"></label>
<label class="field">Max open positions<input id="lv_maxpos" type="number" min="1" max="100" step="1"></label>
<label class="field">Copy entries up to (minutes late)<input id="lv_delay" type="number" min="1" max="240" step="1"></label>
<label class="field">Max risk per position (% of live equity)<input id="lv_r_trade" type="number" min="0.1" max="100" step="0.1"></label>
<label class="field">Max total open risk (%)<input id="lv_r_total" type="number" min="0.1" max="100" step="0.1"></label>
<label class="field">Daily loss stop for new entries (%)<input id="lv_r_day" type="number" min="0.1" max="100" step="0.1"></label>
<label class="field">Drawdown stop for new entries (%)<input id="lv_r_dd" type="number" min="0.1" max="100" step="0.1"></label>
<label class="field">Max margin usage (%)<input id="lv_r_margin" type="number" min="1" max="100" step="1"></label></div>
<div class="gap" style="margin-top:14px"><button id="lv_save" disabled>Save live settings</button><button class="subtle" id="lv_test" disabled>Test connection</button><button class="subtle" id="lv_readiness" disabled>Read-only readiness audit</button><button class="danger" id="lv_panic" disabled>Close all mirrored positions</button></div>
<p class="small" id="lv_status">—</p><p class="small" id="lv_result"></p>
<div class="scroll"><table><thead><tr><th>Symbol</th><th>Bot</th><th>Side</th><th class="num">Live qty</th><th class="num">Stop</th><th>Opened</th></tr></thead><tbody id="lv_rows"></tbody></table></div>
<details><summary>Mirror log</summary><div class="scroll" style="max-height:320px"><table><tbody id="lv_log"></tbody></table></div></details></section>
<section class="panel"><div class="row"><h2>Shahin settings (main bot)</h2><button class="subtle" id="reload" disabled>Reload</button></div>
<div class="fields"><label><input id="auto" type="checkbox">Shahin auto-entry (same on/off switch as above)</label><label><input id="dry" type="checkbox" checked disabled>Simulation mode (Dry-run)</label>
<label class="field">Strategy mode<select id="strategy"><option>MTF</option><option>SINGLE</option></select></label>
<label class="field">Risk per trade (%)<input id="risk" type="number" min="0.1" max="5" step="0.1"></label>
<label class="field">Allowed engaged capital (%)<input id="engaged" type="number" min="0.01" max="100" step="0.01"></label>
<label class="field">Max concurrent positions<input id="max_positions" type="number" min="1" max="100" step="1"></label>
<label class="field">Leverage model<select id="leverage"><option>DYNAMIC_MARGIN</option><option>FIXED_LEVERAGE</option></select></label>
<label class="field">Exit and TP strategy<select id="exit_tp"><option>STOP_TRAIL_DONCHIAN10</option><option>CLOSE_TRAIL_KIJUN</option><option>HYBRID_TRAIL_AND_HARD_TP</option></select></label>
<label class="field">Hybrid-mode trail<select id="hybrid_trail"><option>CLOSE_TRAIL_KIJUN</option><option>STOP_TRAIL_DONCHIAN10</option></select></label>
<label class="field">Trail buffer (ATR; 0 = none)<input id="atr_trail" type="number" min="0" max="5" step="0.05"></label>
<label class="field">Hard take-profit multiple (R; 0 = off)<input id="hard_tp" type="number" min="0" max="100" step="0.1"></label>
<label class="field">Risk-free multiple (R; 0 = off)<input id="breakeven" type="number" min="0" max="20" step="0.1"></label>
<label class="field">Ichimoku preset<select id="preset"><option>crypto</option><option>standard</option></select></label>
<label class="field">Donchian breakout period<select id="donchian_period"><option>20</option><option>10</option></select></label>
<label class="field">Initial stop<select id="initial_stop"><option>ATR2</option><option>KIJUN</option></select></label>
<label><input id="btc_gate" type="checkbox">Bitcoin trend filter: alts do not enter while BTC's 4h candle is inside the Kumo cloud</label>
<label><input id="atr_regime" type="checkbox">ATR regime filter (2A): no entry or add when the signal candle's ATR is below the median ATR of the previous 60 4h candles</label>
<label><input id="momentum" type="checkbox">Momentum sizing: new-entry risk x0.5 to x1.5 by the coin's 30-day momentum rank among the three bots' coins</label>
<label><input id="late_entry" type="checkbox">Late-entry gate: no new entry when price already moved more than ~16% in the trade direction over the previous 60 4h candles</label>
<label><input id="funding_short" type="checkbox">Funding filter: no new short while the 3-day mean funding is negative (needs FUNDING_DIR files)</label>
<label class="field">Initial-stop ATR multiple (2.5 was only tested together with V2 and the BTC filter)<input id="stop_atr_mult" type="number" min="1" max="5" step="0.1"></label>
<label class="field">Margin budget<select id="margin_allocation"><option value="SHARED_POOL">Shared pool (no slot split)</option><option value="PER_SLOT">Fixed slot share</option></select></label>
<label><input id="shared_account" type="checkbox">Capital management and the shared margin cap of the three bots (Shahin, Mojsavar, Ghoghnous)</label>
<label><input id="pyramid" type="checkbox">One-step add to a winner</label>
<label class="field">Added-unit risk (fraction of risk per trade)<input id="pyramid_fraction" type="number" min="0.05" max="1" step="0.05"></label>
<label><input id="safe_pyramid" type="checkbox">Add only if the shared stop covers the combined break-even of both units (incl. fees and slippage)</label>
<label><input id="profit_floor" type="checkbox">Profit floor: after the R threshold is reached, move the stop to entry ± lock multiple</label>
<label><input id="width_filter" type="checkbox">Stop-width filter: reject entries with a very wide stop and take a fairly wide stop with less risk</label>
<label class="field">Reject entry if the stop width exceeds this (%)<input id="width_skip" type="number" min="1.2" max="50" step="0.1"></label>
<label class="field">Reduce risk if the stop width exceeds this (%)<input id="width_mid" type="number" min="1.2" max="50" step="0.1"></label>
<label class="field">Risk fraction for a fairly wide stop<input id="width_fraction" type="number" min="0.05" max="1" step="0.05"></label>
<label class="field">Profit-floor activation threshold (R)<input id="floor_trigger" type="number" min="0.1" max="20" step="0.1"></label>
<label class="field">Profit-floor lock multiple (R)<input id="floor_lock" type="number" min="0" max="19.9" step="0.05"></label>
<label class="field">ATR2 stop basis<select id="stop_anchor"><option>SIGNAL</option><option>ENTRY</option></select></label>
<label><input id="breakout" type="checkbox">Signal-candle breakout</label><label><input id="barb" type="checkbox">Barb Wire filter</label><label><input id="h2" type="checkbox">H2 / L2 pullback</label></div>
<details><summary>Edit full JSON</summary><textarea id="editor" aria-label="JSON configuration" spellcheck="false"></textarea></details>
<div class="row" style="margin-top:18px"><p id="dirty">Settings not loaded.</p><button id="save" disabled>Save settings</button></div></section>
<section class="panel"><details><summary>Mojsavar settings</summary>
<div class="fields" style="margin-top:18px">
<label class="field">Risk per trade (%)<input id="c3_risk" type="number" min="0.01" max="1" step="0.01"></label>
<label class="field">Max positions (0 = no count cap)<input id="c3_max_positions" type="number" min="0" max="100" step="1"></label>
<label class="field">Notional cap (PER_SLOT mode only, % of equity)<input id="c3_notional" type="number" min="1" max="100" step="1"></label>
<label class="field">Entry confirmation (candles; 0 = none)<input id="c3_confirm" type="number" min="0" max="12" step="1"></label>
<label><input id="c3_weekend" type="checkbox">Skip entries when the signal candle closes on a weekend</label>
<label class="field" style="grid-column:span 2">Symbols (one per line, e.g. AVAX/USDT:USDT)<textarea id="c3_symbols" style="min-height:90px;margin:0" spellcheck="false"></textarea></label></div>
<details><summary>Edit full Mojsavar JSON settings</summary><textarea id="c3_editor" aria-label="Mojsavar JSON configuration" spellcheck="false"></textarea></details>
<div class="row" style="margin-top:18px"><p id="c3_dirty">Mojsavar settings not loaded.</p><button id="c3_save" disabled>Save Mojsavar settings</button></div>
<details><summary>Mojsavar: last 20 trades</summary><div class="scroll"><table><thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&amp;L ($)</th><th>Reason</th></tr></thead><tbody id="c3_hist"></tbody></table></div></details></details><details><summary>Ghoghnous settings</summary>
<div class="fields" style="margin-top:18px">
<label class="field">Base risk (%)<input id="pa_risk" type="number" min="0.01" max="1" step="0.01"></label>
<label class="field">Volume multiplier<input id="pa_volume" type="number" min="0.01" step="0.1"></label>
<label class="field" style="grid-column:span 3">Symbols (one per line, e.g. LINK/USDT:USDT)<textarea id="pa_symbols" style="min-height:90px;margin:0" spellcheck="false"></textarea></label></div>
<p class="muted">Selected paper policy adds a trend exhaustion filter and fuzzy sizing to the low-volatility Key Reversal. Base risk is multiplied by the volume setting and the signal weight. The card shows planned risk before margin limits. Entry is valid for one candle; exits use the stop, an opposite Key Reversal, or 30 candles.</p>
<details><summary>Edit full Ghoghnous JSON settings</summary><textarea id="pa_editor" aria-label="Ghoghnous JSON configuration" spellcheck="false"></textarea></details>
<div class="row" style="margin-top:18px"><p id="pa_dirty">Ghoghnous settings not loaded.</p><button id="pa_save" disabled>Save Ghoghnous settings</button></div>
<details><summary>Ghoghnous: pending Stop orders and last 20 trades</summary><div class="scroll"><table><thead><tr><th>Symbol</th><th>Side</th><th>Entry level</th><th>Stop loss</th></tr></thead><tbody id="pa_orders"></tbody></table>
<table><thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&amp;L ($)</th><th>Reason</th></tr></thead><tbody id="pa_hist"></tbody></table></div></details></details></section>
</section>
<footer><span id="health">—</span> · <span id="updated">Waiting for connection</span> · Stopping entries does not stop management of open positions.</footer>
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
 for(const id of ['exit_tp','hybrid_trail','hard_tp','breakeven','preset','donchian_period','initial_stop','pyramid','stop_anchor','pyramid_fraction','safe_pyramid','profit_floor','floor_trigger','floor_lock','width_filter','width_skip','width_mid','width_fraction','stop_atr_mult','btc_gate','funding_short','atr_regime','late_entry','momentum','atr_trail'])$(id).disabled=!settings;
 $('strategy').disabled=!!settings;
 if(settings){$('atr_trail').value=settings.trail_atr_buffer??0;$('exit_tp').value=settings.exit_tp_mode;$('hybrid_trail').value=settings.hybrid_trail_mode;$('hard_tp').value=settings.hard_tp_rr;$('breakeven').value=settings.breakeven_trigger_rr;$('preset').value=settings.ichimoku_preset;$('donchian_period').value=settings.donchian_entry_period;$('initial_stop').value=settings.initial_stop_mode;$('pyramid').checked=!!settings.pyramid_enabled;$('stop_anchor').value=settings.initial_stop_anchor;
  $('pyramid_fraction').value=settings.pyramid_risk_fraction;$('safe_pyramid').checked=!!settings.safe_pyramid_enabled;$('profit_floor').checked=!!settings.profit_floor_enabled;$('floor_trigger').value=settings.profit_floor_trigger_r;$('floor_lock').value=settings.profit_floor_lock_r;
  $('width_filter').checked=!!settings.stop_width_filter_enabled;$('width_skip').value=settings.stop_width_skip_pct*100;$('width_mid').value=settings.stop_width_mid_pct*100;$('width_fraction').value=settings.stop_width_mid_risk_fraction;$('stop_atr_mult').value=settings.initial_stop_atr_mult;$('btc_gate').checked=!!settings.btc_regime_filter_enabled;$('funding_short').checked=!!settings.funding_short_filter_enabled;$('atr_regime').checked=!!settings.atr_regime_filter_enabled;$('late_entry').checked=!!settings.late_entry_filter_enabled;$('momentum').checked=!!settings.momentum_sizing_enabled;$('mom_state').textContent=settings.momentum_sizing_enabled?'On':'Off';}
 $('breakout').checked=cfg.al_brooks_filters.require_signal_bar_breakout;$('barb').checked=cfg.al_brooks_filters.enable_barb_wire_filter;$('h2').checked=cfg.al_brooks_filters.require_h2_l2_pullback;
}
async function loadConfig(){const result=await api('/api/config');cfg=result.data;etag=result.etag;$('shared_account').checked=!!cfg.portfolio_risk.shared_c3_account;$('margin_allocation').value=cfg.portfolio_risk.margin_allocation_mode;$('editor').value=JSON.stringify(cfg,null,2);fillControls();$('dirty').textContent='Settings saved.';}
function controlsChanged(){if(!cfg)return;try{cfg=JSON.parse($('editor').value);}catch(e){message('Fix the JSON first.',true);fillControls();return;}
 cfg.portfolio_risk.shared_c3_account=$('shared_account').checked;cfg.portfolio_risk.margin_allocation_mode=$('margin_allocation').value;
 cfg.bot_control.auto_trade_enabled=$('auto').checked;cfg.strategy_mode.mode=$('strategy').value;cfg.risk_and_exit.risk_per_trade_pct=Number($('risk').value)/100;
 cfg.risk_and_exit.engaged_capital_pct=Number($('engaged').value)/100;cfg.risk_and_exit.leverage_mode=$('leverage').value;cfg.risk_and_exit.max_open_positions=Number($('max_positions').value);
 if(cfg.strategy_settings){Object.assign(cfg.strategy_settings,{trail_atr_buffer:Number($('atr_trail').value),exit_tp_mode:$('exit_tp').value,hybrid_trail_mode:$('hybrid_trail').value,hard_tp_rr:Number($('hard_tp').value),breakeven_trigger_rr:Number($('breakeven').value),ichimoku_preset:$('preset').value,donchian_entry_period:Number($('donchian_period').value),initial_stop_mode:$('initial_stop').value});}
 if(cfg.strategy_settings){cfg.strategy_settings.pyramid_enabled=$('pyramid').checked;cfg.strategy_settings.initial_stop_anchor=$('stop_anchor').value;
  Object.assign(cfg.strategy_settings,{pyramid_risk_fraction:Number($('pyramid_fraction').value),safe_pyramid_enabled:$('safe_pyramid').checked,profit_floor_enabled:$('profit_floor').checked,profit_floor_trigger_r:Number($('floor_trigger').value),profit_floor_lock_r:Number($('floor_lock').value),
   stop_width_filter_enabled:$('width_filter').checked,stop_width_skip_pct:Number($('width_skip').value)/100,stop_width_mid_pct:Number($('width_mid').value)/100,stop_width_mid_risk_fraction:Number($('width_fraction').value),initial_stop_atr_mult:Number($('stop_atr_mult').value),btc_regime_filter_enabled:$('btc_gate').checked,funding_short_filter_enabled:$('funding_short').checked,atr_regime_filter_enabled:$('atr_regime').checked,late_entry_filter_enabled:$('late_entry').checked,momentum_sizing_enabled:$('momentum').checked});}
 cfg.al_brooks_filters.require_signal_bar_breakout=$('breakout').checked;cfg.al_brooks_filters.enable_barb_wire_filter=$('barb').checked;cfg.al_brooks_filters.require_h2_l2_pullback=$('h2').checked;
 $('editor').value=JSON.stringify(cfg,null,2);$('dirty').textContent='Changes were not saved.';
}
for(const id of ['margin_allocation','shared_account','auto','strategy','risk','breakout','barb','h2','engaged','max_positions','leverage','exit_tp','hybrid_trail','hard_tp','breakeven','preset','donchian_period','initial_stop','pyramid','stop_anchor','pyramid_fraction','safe_pyramid','profit_floor','floor_trigger','floor_lock','width_filter','width_skip','width_mid','width_fraction','stop_atr_mult','btc_gate','funding_short','atr_regime','late_entry','momentum','atr_trail'])$(id).addEventListener('change',controlsChanged);
$('editor').addEventListener('input',()=>{$('dirty').textContent='Changes were not saved.';});
$('editor').addEventListener('blur',()=>{try{cfg=JSON.parse($('editor').value);fillControls();}catch(e){message('Invalid JSON.',true);}});
function renderFillQuality(fq){const main=$('fq_main'),detail=$('fq_detail');if(!fq||!fq.total){main.textContent='—';main.className='';detail.textContent='No fills recorded yet (only with PAPER_DATA_MODE=csv-lbank and the live order book)'+(fq&&fq.last_error?' | Error: '+fq.last_error:'');return;}
 const f=x=>x?Number(x.median_bps).toFixed(1)+' / '+Number(x.p90_bps).toFixed(1):'—';main.textContent='Entry '+f(fq.entry)+' | Exit '+f(fq.exit);
 const worst=Math.max(fq.entry?fq.entry.median_bps:0,fq.exit?fq.exit.median_bps:0);main.className=worst>fq.assumed_bps_per_fill*2.5?'bad':'';
 detail.textContent='Backtest assumed '+fq.assumed_bps_per_fill+' bps; '+fq.total+' fill'+(fq.last_error?' | Error: '+fq.last_error:'');}
let lastBot=null,lastC3=null,lastPA=null,view='all';try{view=localStorage.getItem('view')||'all';}catch(e){}
function setView(v){view=v;try{localStorage.setItem('view',v);}catch(e){}draw();}
for(const b of document.querySelectorAll('.view'))b.onclick=()=>setView(b.dataset.view);
const sumOf=(...x)=>x.some(v=>v===null||v===undefined)?null:x.reduce((p,c)=>p+c,0);
const BOTNAME={bot:'Shahin',c3:'Mojsavar',pa:'Ghoghnous'};
function drawSummary(){for(const x of document.querySelectorAll('.view'))x.classList.toggle('on',x.dataset.view===view);
 const S={bot:lastBot,c3:lastC3,pa:lastPA},keys=(view==='all'?['bot','c3','pa']:[view]).filter(k=>S[k]);if(!keys.length)return;
 let un=0,unOk=true,rl=0,tr=0,used=0;const parts=[];
 for(const k of keys){const x=S[k],u=k==='bot'?x.total_unrealized_pnl:x.unrealized_pnl_usd;if(u===null||u===undefined)unOk=false;else un+=u;
  rl+=x.daily_realized_pnl;tr+=x.daily_trades_count;used+=x.engaged_margin_usd||0;
  parts.push(BOTNAME[k]+': '+x.open_positions_count+(k==='bot'?' / '+x.max_open_positions:'')+(k==='pa'&&x.pending_orders&&x.pending_orders.length?' (+'+x.pending_orders.length+' Stop orders)':''));}
 const open=keys.reduce((a,k)=>a+S[k].open_positions_count,0);
 $('unrealized').textContent=number(unOk?un:null);$('unrealized').className=unOk&&un<0?'bad':'';$('realized').textContent=number(rl);$('realized').className=rl<0?'bad':'good';$('trades').textContent=tr+' exits recorded in 24h';
 $('slots').textContent=open+' positions';$('updated_sub').textContent=parts.join(' · ');
 const b=lastBot,eq=b&&b.shared_account_enabled?b.equity_usd:(lastC3?lastC3.equity_usd:(b?b.equity_usd:null));
 $('equity').textContent=number(eq);$('equity_note').textContent=b&&b.shared_account_enabled?'Shared capital of the three bots'+(view!=='all'&&view!=='bot'&&S[view]?' · '+BOTNAME[view]+' '+(S[view].realized_total_usd>=0?'+':'')+number(S[view].realized_total_usd)+' Closed profit':''):'Shahin paper capital (excluding the other two bots\' P&L)';
 const allowed=b&&eq?eq*b.allowed_margin_pct/100:null;
 $('margin').textContent=number(used)+(allowed?' / '+number(allowed):'');
 $('margin_pct').textContent=eq?number(used/eq*100)+'% of account'+(b?' / '+number(b.allowed_margin_pct)+'% allowed (all three bots)':''):'—';
 $('pending_margin').textContent=b&&keys.includes('bot')?'Margin reserved for Shahin\'s pending orders: $'+number(b.reserved_pending_margin_usd):'Ghoghnous Stop orders reserve no margin until triggered';
 $('fq_main').closest('section').style.display=view==='all'||view==='bot'?'':'none';
 $('view_note').textContent=view==='all'?'All three bots (capital and margin are shared)':view==='bot'?'Shahin only (Donchian + Kumo)':view==='c3'?'Mojsavar only (4h trend pullback)':'Ghoghnous only (4h Key Reversal)';
 drawCards();}
function drawCards(){const b=lastBot;
 if(b){$('main_enabled').checked=b.auto_trade_enabled;$('card_main').classList.toggle('off',!b.auto_trade_enabled);$('main_open').textContent=b.open_positions_count+' / '+b.max_open_positions;
  $('main_unreal').textContent=number(b.total_unrealized_pnl);$('main_day').textContent=number(b.daily_realized_pnl);}
 if(cfg)$('main_risk_v').textContent=number(cfg.risk_and_exit.risk_per_trade_pct*100)+'%';
 if(lastC3)$('card_c3').classList.toggle('off',!lastC3.enabled);if(lastPA)$('card_pa').classList.toggle('off',!lastPA.enabled);}
async function toggleBot(key,on){try{const r=await api('/api/bots/toggle','POST',{bot:key,enabled:on});message(r.data.name+(on?' switched on; new entries are enabled.':' switched off; new entries are stopped and open positions stay managed.'));
  if(key==='main'){await loadConfig();await refresh();}else if(key==='c3'){await loadC3();await refreshC3();}else{await loadPA();await refreshPA();}}catch(e){message(e.message,true);}}
function drawPositions(){const rows=$('positions');rows.replaceChildren();const items=[];
 const want=k=>view==='all'||view===k;
 if(want('bot')&&lastBot)for(const p of lastBot.positions)items.push({kind:'bot',p});
 if(want('c3')&&lastC3)for(const p of lastC3.positions)items.push({kind:'c3',p});
 if(want('pa')&&lastPA)for(const p of lastPA.positions)items.push({kind:'pa',p});
 if(!items.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=11;td.textContent='No open positions.';tr.append(td);rows.append(tr);return;}
 for(const {kind,p} of items){const tr=document.createElement('tr');const tag=document.createElement('td'),sp=document.createElement('span');sp.className='tag'+(kind==='bot'?'':' '+kind);sp.textContent=BOTNAME[kind];tag.append(sp);tr.append(tag);
  const pnl=p.unrealized_pnl_usd;
  const values=kind==='c3'?[p.symbol,p.side==='long'?'Buy':'Sell',number(p.entry,6),number(p.live_price,6),number(p.stop,6),'—','ATR trail',number(p.current_r),number(pnl)]
   :kind==='pa'?[p.symbol,p.side==='long'?'Buy':'Sell',number(p.entry,6),number(p.live_price,6),number(p.stop,6),p.target?number(p.target,6):'—','Exit: stop, opposite reversal or 30 candles',number(p.current_r),number(pnl)]
   :[p.symbol,p.side==='long'?'Buy':'Sell',number(p.state==='STATE_PENDING_TRIGGER'?p.trigger_price:p.entry_price,6),number(p.live_price,6),number(p.active_sl,6),number(target(p),6),p.state,number(p.current_r),number(pnl)];
  values.forEach((v,index)=>{const td=document.createElement('td');td.textContent=v;if(index===0||index>=2)td.dir='ltr';if(index===8&&pnl!==null)td.className=pnl<0?'bad':'good';tr.append(td);});
  const td=document.createElement('td'),button=document.createElement('button');button.className='danger';const pending=kind==='bot'&&p.state==='STATE_PENDING_TRIGGER';button.textContent=pending?'Cancel':'Close now';
  button.onclick=async()=>{if(!confirm('Close / cancel '+p.symbol+' ('+BOTNAME[kind]+')'+'?'))return;button.disabled=true;try{await api(kind==='c3'?'/api/c3/close':kind==='pa'?'/api/pa/close':'/api/positions/close','POST',{symbol:p.symbol});await refresh();await refreshC3();await refreshPA();}catch(e){message(e.message,true);}finally{button.disabled=false;}};td.append(button);tr.append(td);rows.append(tr);}}
function draw(){drawSummary();drawPositions();}
function render(s){lastBot=s;$('mode').textContent=s.strategy_mode+' / '+(s.dry_run_mode?'DRY-RUN':'LIVE')+' / '+s.data_mode;$('active').textContent=s.license&&!s.license.entries_allowed?'License '+s.license.state+' · entries blocked':s.auto_trade_enabled?'Entries on':'Entries off';
 renderFillQuality(s.fill_quality);$('updated').textContent='Last update: '+new Date().toLocaleTimeString('en-GB');draw();
 const stamp=s.runtime.watchdog_at;$('health').textContent=stamp?'Last bot check: '+new Date(stamp*1000).toLocaleTimeString('en-GB'):'The bot has not logged a check yet';
 if(stamp&&Date.now()/1000-stamp>60)$('health').textContent+=' — the bot check is lagging';
 if(s.price_errors.length)message('Some symbol prices were not received; full P&L is unavailable.',true);
}
async function refresh(){if(!connected||polling)return;polling=true;try{const result=await api('/api/status');render(result.data);}catch(e){message(e.message,true);}finally{polling=false;}}
$('connect').onclick=async()=>{try{await loadConfig();await loadC3();await loadPA();connected=true;for(const id of ['save','panic','reload','c3_save','pa_save'])$(id).disabled=false;await refresh();await refreshC3();await refreshPA();$('message').style.display='none';}catch(e){connected=false;message(e.message,true);}};
$('pin').addEventListener('input',()=>{connected=false;for(const id of ['save','panic','reload','c3_save','pa_save'])$(id).disabled=true;$('active').textContent='Offline';});
$('save').onclick=async()=>{const b=$('save');b.disabled=true;try{const edited=JSON.parse($('editor').value);const result=await api('/api/config','PUT',edited,etag);cfg=result.data;etag=result.etag;fillControls();$('dirty').textContent='Settings saved.';message('Settings saved.');await refresh();}catch(e){message(e.message,true);}finally{b.disabled=false;}};
$('reload').onclick=async()=>{try{await loadConfig();await loadC3();await loadPA();message('Settings loaded.');}catch(e){message(e.message,true);}};
$('panic').onclick=async()=>{if(!confirm('Close all positions of all three bots and stop all entries?'))return;const b=$('panic');b.disabled=true;
 try{const result=await api('/api/positions/close-all','POST',{disable_auto_trade:true});const s=result.data;message(s.errors.length?'Entries stopped; '+s.errors.length+' No position was closed. Try again.':'All positions closed / cancelled and entries stopped.',s.errors.length>0);await loadConfig();await loadC3();await loadPA();await refresh();await refreshC3();await refreshPA();}catch(e){message(e.message,true);}finally{b.disabled=false;}};

let c3cfg=null,c3etag=null;
const c3n=(v,n=2)=>number(v,n);
function c3Fill(){if(!c3cfg)return;$('c3_enabled').checked=c3cfg.enabled;$('c3_max_positions').value=c3cfg.max_open_positions;$('c3_risk').value=+(c3cfg.risk_per_trade_pct*100).toFixed(4);$('c3_notional').value=+(c3cfg.max_notional_pct*100).toFixed(2);
 $('c3_confirm').value=c3cfg.confirm_bars;$('c3_weekend').checked=c3cfg.skip_weekend;$('c3_symbols').value=c3cfg.symbols.join('\n');$('c3_editor').value=JSON.stringify(c3cfg,null,2);}
async function loadC3(){const r=await api('/api/c3/config');c3cfg=r.data;c3etag=r.etag;c3Fill();$('c3_dirty').textContent='Mojsavar settings saved.';}
function c3Changed(){if(!c3cfg)return;try{c3cfg=JSON.parse($('c3_editor').value);}catch(e){message('Fix the Mojsavar settings JSON first.',true);c3Fill();return;}
 Object.assign(c3cfg,{max_open_positions:Number($('c3_max_positions').value),risk_per_trade_pct:Number($('c3_risk').value)/100,max_notional_pct:Number($('c3_notional').value)/100,confirm_bars:parseInt($('c3_confirm').value||'0',10),skip_weekend:$('c3_weekend').checked,
  symbols:$('c3_symbols').value.split(/[\s,]+/).filter(Boolean)});$('c3_editor').value=JSON.stringify(c3cfg,null,2);$('c3_dirty').textContent='Mojsavar changes were not saved.';}
for(const id of ['c3_max_positions','c3_risk','c3_notional','c3_confirm','c3_weekend','c3_symbols'])$(id).addEventListener('change',c3Changed);
for(const [id,key] of [['main_enabled','main'],['c3_enabled','c3'],['pa_enabled','pa']])$(id).addEventListener('change',e=>toggleBot(key,e.target.checked));
$('c3_editor').addEventListener('input',()=>{$('c3_dirty').textContent='Mojsavar changes were not saved.';});
$('c3_editor').addEventListener('blur',()=>{try{c3cfg=JSON.parse($('c3_editor').value);c3Fill();}catch(e){message('Mojsavar settings JSON is invalid.',true);}});
$('c3_save').onclick=async()=>{const b=$('c3_save');b.disabled=true;try{const edited=JSON.parse($('c3_editor').value);const r=await api('/api/c3/config','PUT',edited,c3etag);c3cfg=r.data;c3etag=r.etag;c3Fill();$('c3_dirty').textContent='Mojsavar settings saved; they apply within seconds.';await refreshC3();}catch(e){message(e.message,true);}finally{b.disabled=false;}};
function cell(tr,v,cls,ltr){const td=document.createElement('td');td.textContent=v;if(cls)td.className=cls;if(ltr)td.dir='ltr';tr.append(td);return td;}
function renderC3(s){lastC3=s;$('c3_enabled').checked=s.enabled;$('c3_risk_v').textContent=number(s.risk_per_trade_pct*100)+'%';$('c3badge').textContent=(s.in_bot?'running inside the bot':'thread is off (C3_IN_BOT=0)')+' · '+(s.enabled?'Entries on':'Entries off');
 $('c3_unrealized').textContent=c3n(s.unrealized_pnl_usd);$('c3_positions').textContent=s.open_positions_count+' of '+s.coins+' coins';
 $('c3_realized').textContent=c3n(s.daily_realized_pnl);$('c3_realized').className=s.daily_realized_pnl<0?'bad':'good';$('c3_trades').textContent=s.daily_trades_count+' exits in 24h';
 $('c3_total').textContent=c3n(s.realized_total_usd);$('c3_total').className=s.realized_total_usd<0?'bad':'good';$('c3_win').textContent=s.trades_total?(s.trades_total+' · wins '+c3n(s.win_rate_pct,1)+'%'):'—';
 const h=$('c3_hist');h.replaceChildren();for(const x of s.recent_trades){const tr=document.createElement('tr');cell(tr,x.symbol,'',1);cell(tr,x.side==='long'?'Buy':'Sell');cell(tr,c3n(x.entry,6),'',1);cell(tr,c3n(x.exit,6),'',1);cell(tr,c3n(x.pnl),x.pnl<0?'bad':'good',1);cell(tr,x.reason);h.append(tr);}draw();}
async function refreshC3(){if(!connected)return;try{const r=await api('/api/c3/status');renderC3(r.data);}catch(e){message('Mojsavar: '+e.message,true);}}
let pacfg=null,paetag=null;
function paFill(){if(!pacfg)return;$('pa_enabled').checked=pacfg.enabled;$('pa_risk').value=+(pacfg.risk_per_trade_pct*100).toFixed(4);$('pa_volume').value=pacfg.volume_multiplier;$('pa_symbols').value=pacfg.symbols.join('\n');$('pa_editor').value=JSON.stringify(pacfg,null,2);}
async function loadPA(){const r=await api('/api/pa/config');pacfg=r.data;paetag=r.etag;paFill();$('pa_dirty').textContent='Ghoghnous settings saved.';}
function paChanged(){if(!pacfg)return;try{pacfg=JSON.parse($('pa_editor').value);}catch(e){message('Fix the Ghoghnous settings JSON first.',true);paFill();return;}
 Object.assign(pacfg,{risk_per_trade_pct:Number($('pa_risk').value)/100,volume_multiplier:Number($('pa_volume').value),symbols:$('pa_symbols').value.split(/[\s,]+/).filter(Boolean)});$('pa_editor').value=JSON.stringify(pacfg,null,2);$('pa_dirty').textContent='Ghoghnous changes were not saved.';}
for(const id of ['pa_risk','pa_volume','pa_symbols'])$(id).addEventListener('change',paChanged);
$('pa_editor').addEventListener('input',()=>{$('pa_dirty').textContent='Ghoghnous changes were not saved.';});
$('pa_editor').addEventListener('blur',()=>{try{pacfg=JSON.parse($('pa_editor').value);paFill();}catch(e){message('Ghoghnous settings JSON is invalid.',true);}});
$('pa_save').onclick=async()=>{const b=$('pa_save');b.disabled=true;try{const edited=JSON.parse($('pa_editor').value);const r=await api('/api/pa/config','PUT',edited,paetag);pacfg=r.data;paetag=r.etag;paFill();$('pa_dirty').textContent='Ghoghnous settings saved; they apply within seconds.';await refreshPA();}catch(e){message(e.message,true);}finally{b.disabled=false;}};
function renderPA(s){lastPA=s;$('pa_enabled').checked=s.enabled;$('pa_risk_v').textContent=number(s.planned_risk_min*100)+'–'+number(s.planned_risk_max*100)+'%';$('pabadge').textContent=(s.in_bot?'running inside the bot':'thread is off (PA_IN_BOT=0)')+' · '+(s.enabled?'Entries on':'Entries off')+' · '+s.strategy_variant+' · volume ×'+number(s.volume_multiplier);
 $('pa_unrealized').textContent=c3n(s.unrealized_pnl_usd);$('pa_positions').textContent=s.open_positions_count+' / '+s.pending_orders.length+' ('+s.coins+' coins)';
 $('pa_realized').textContent=c3n(s.daily_realized_pnl);$('pa_realized').className=s.daily_realized_pnl<0?'bad':'good';$('pa_trades').textContent=s.daily_trades_count+' exits in 24h';
 $('pa_total').textContent=c3n(s.realized_total_usd);$('pa_total').className=s.realized_total_usd<0?'bad':'good';$('pa_win').textContent=s.trades_total?(s.trades_total+' · wins '+c3n(s.win_rate_pct,1)+'%'):'—';
 const o=$('pa_orders');o.replaceChildren();for(const x of s.pending_orders){const tr=document.createElement('tr');cell(tr,x.symbol,'',1);cell(tr,x.side==='long'?'Buy':'Sell');cell(tr,c3n(x.level,6),'',1);cell(tr,c3n(x.stop,6),'',1);o.append(tr);}
 const h=$('pa_hist');h.replaceChildren();for(const x of s.recent_trades){const tr=document.createElement('tr');cell(tr,x.symbol,'',1);cell(tr,x.side==='long'?'Buy':'Sell');cell(tr,c3n(x.entry,6),'',1);cell(tr,c3n(x.exit,6),'',1);cell(tr,c3n(x.pnl),x.pnl<0?'bad':'good',1);cell(tr,x.reason);h.append(tr);}draw();}
async function refreshPA(){if(!connected)return;try{const r=await api('/api/pa/status');renderPA(r.data);}catch(e){message('Ghoghnous: '+e.message,true);}}
setInterval(()=>{refresh();refreshC3();refreshPA();},5000);

// ---------------- tabs and performance (added) ----------------
const charts={};let tab='overview';try{tab=localStorage.getItem('tab')||'overview';}catch(e){}
function setTab(t){tab=t;try{localStorage.setItem('tab',t);}catch(e){}
 for(const b of document.querySelectorAll('.tab'))b.classList.toggle('on',b.dataset.tab===t);
 for(const p of document.querySelectorAll('.pane'))p.classList.toggle('on',p.dataset.pane===t);
 for(const c of Object.values(charts))if(c)c.resize();}
for(const b of document.querySelectorAll('.tab'))b.onclick=()=>setTab(b.dataset.tab);
setTab(tab);
const themeColor=name=>typeof getComputedStyle==='function'?getComputedStyle(document.documentElement).getPropertyValue('--'+name).trim():'';
const BOTCOL={get main(){return themeColor('primary');},get c3(){return themeColor('ai-accent');},get pa(){return themeColor('premium-accent');}};
const money=v=>v===null||v===undefined?'—':(v<0?'-$':'$')+Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=(v,n=1)=>v===null||v===undefined||!isFinite(v)?'—':(v>0?'+':'')+Number(v).toFixed(n)+'%';
const cls=v=>v>0?'good':v<0?'bad':'';
const day=t=>new Date(t*1000).toISOString().slice(0,10);
function chart(id,cfg){if(typeof Chart==='undefined')return null;if(charts[id])charts[id].destroy();
 Chart.defaults.color=themeColor('chart-axis');Chart.defaults.borderColor=themeColor('border');Chart.defaults.font.family='Inter';
 Chart.defaults.plugins.tooltip.backgroundColor=themeColor('surface-elevated');Chart.defaults.plugins.tooltip.titleColor=themeColor('text-primary');Chart.defaults.plugins.tooltip.bodyColor=themeColor('text-primary');Chart.defaults.plugins.tooltip.borderColor=themeColor('border-strong');Chart.defaults.plugins.tooltip.borderWidth=1;
 charts[id]=new Chart($(id),cfg);return charts[id];}
const baseOpts=(extra={})=>Object.assign({responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{boxWidth:10,boxHeight:10}}},scales:{x:{grid:{display:false},ticks:{maxTicksLimit:8,maxRotation:0}},y:{grid:{color:themeColor('border')}}}},extra);
let lastPerf=null;
if(typeof window!=='undefined')window.addEventListener('trade:appearancechange',()=>{
 if(lastPerf)renderPerf(lastPerf);
});
function td(tr,v,c,num){const x=document.createElement('td');x.textContent=v;if(c)x.className=c;if(num){x.classList.add('num');x.dir='ltr';}tr.append(x);return x;}
function renderPerf(p){lastPerf=p;const a=p.all,eqNow=(()=>{try{return Number(String($('equity').textContent).replace(/,/g,''));}catch(e){return null;}})();
 const eq=isFinite(eqNow)&&eqNow>0?eqNow:(p.realized_curve.length?p.realized_curve.at(-1).equity:p.seed);
 $('ret_total').textContent='Since start: '+pct((eq/p.seed-1)*100)+' on $'+number(p.seed,0);$('ret_total').className='small '+cls(eq-p.seed);
 $('pnl_30d').textContent='7 days '+money(a.pnl_7d)+' · 30 days '+money(a.pnl_30d);
 $('dd_now').textContent=pct(p.drawdown_now);$('dd_now').className=p.drawdown_now<-10?'bad':p.drawdown_now<-5?'warn':'';$('dd_max').textContent='Max '+pct(p.drawdown_max)+' · F target: stay above -15%';
 $('dd_bar').style.width=Math.min(100,-p.drawdown_now/15*100)+'%';
 $('winrate').textContent=a.win_rate===null?'—':number(a.win_rate,1)+'%';$('pf').textContent=a.trades+' trades · profit factor '+(a.profit_factor?number(a.profit_factor):'—')+' · avg win '+money(a.avg_win)+' / loss '+money(a.avg_loss);
 // equity + drawdown
 const pts=p.snapshots.length>=2?p.snapshots.map(s=>({t:s.t,v:s.equity})):p.realized_curve.map(s=>({t:s.t,v:s.equity}));
 $('eq_src').textContent=p.snapshots.length>=2?'hourly account snapshots (incl. open P&L)':'closed trades only (snapshots start with the F service)';
 if(pts.length){let pk=-Infinity;const dd=pts.map(x=>{pk=Math.max(pk,x.v);return (x.v/pk-1)*100;});const lab=pts.map(x=>new Date(x.t*1000).toISOString().slice(0,10));
  chart('eq_chart',{type:'line',data:{labels:lab,datasets:[{label:'Equity ($)',data:pts.map(x=>x.v),borderColor:themeColor('chart-equity'),backgroundColor:themeColor('chart-fill')+'20',fill:true,pointRadius:0,tension:.2,borderWidth:2}]},options:baseOpts({plugins:{legend:{display:false}}})});
  chart('dd_chart',{type:'line',data:{labels:lab,datasets:[{label:'Drawdown (%)',data:dd,borderColor:themeColor('loss'),backgroundColor:themeColor('loss')+'20',fill:true,pointRadius:0,borderWidth:1.5},{label:'-15% limit',data:dd.map(()=>-15),borderColor:themeColor('warning'),borderDash:[5,5],pointRadius:0,borderWidth:1}]},options:baseOpts({scales:{x:{display:false},y:{grid:{color:themeColor('border')},suggestedMin:-16,max:0}}})});}
 // daily bars
 const days=[];for(let i=29;i>=0;i--)days.push(new Date(Date.now()-i*86400000).toISOString().slice(0,10));
 chart('daily_chart',{type:'bar',data:{labels:days.map(d=>d.slice(5)),datasets:['main','c3','pa'].map(b=>({label:BOTNAME[b==='main'?'bot':b],data:days.map(d=>(p.daily[d]||{})[b]||0),backgroundColor:days.map(d=>((p.daily[d]||{})[b]||0)<0?themeColor('loss'):themeColor('profit')),borderRadius:3,stack:'s'}))},options:baseOpts({indexAxis:'y',scales:{x:{stacked:true,grid:{color:themeColor('border')}},y:{stacked:true,grid:{display:false},ticks:{autoSkip:false,font:{size:10}}}}})});
 // per-bot cards
 const pc=$('perf_cards');pc.replaceChildren();
 for(const [k,b] of Object.entries(p.bots)){const s=document.createElement('section');s.className='panel bot bot-'+k;
  s.innerHTML='<h3></h3><dl><dt>Closed profit</dt><dd></dd><dt>Trades · win rate</dt><dd></dd><dt>Profit factor</dt><dd></dd><dt>Avg win / avg loss</dt><dd></dd><dt>Best / worst</dt><dd></dd><dt>7 days / 30 days</dt><dd></dd></dl>';
  s.querySelector('h3').textContent=b.name;const dd_=s.querySelectorAll('dd');dd_[0].textContent=money(b.total);dd_[0].className=cls(b.total);
  dd_[1].textContent=b.trades+' · '+(b.win_rate===null?'—':number(b.win_rate,1)+'%');dd_[2].textContent=b.profit_factor?number(b.profit_factor):'—';
  dd_[3].textContent=money(b.avg_win)+' / '+money(b.avg_loss);dd_[4].textContent=money(b.best)+' / '+money(b.worst);dd_[5].textContent=money(b.pnl_7d)+' / '+money(b.pnl_30d);pc.append(s);}
 // monthly
 const m=$('monthly');m.replaceChildren();const ms=Object.entries(p.monthly).reverse();
 if(!ms.length){const tr=document.createElement('tr');td(tr,'No closed trades yet.','empty').colSpan=8;m.append(tr);}
 for(const [k,r] of ms){const tr=document.createElement('tr');td(tr,k);for(const b of ['main','c3','pa'])td(tr,number(r[b]),r[b]>0?'pos':r[b]<0?'neg':'',1);td(tr,number(r.total),r.total>0?'pos':'neg',1);td(tr,pct(r.pct,2),r.pct>0?'pos':'neg',1);td(tr,r.trades,'',1);td(tr,number(r.win_rate,1),'',1);m.append(tr);}
 drawHist();}
function drawHist(){if(!lastPerf)return;const f=$('hist_filter').value,h=$('hist_all');h.replaceChildren();
 const rows=lastPerf.recent.filter(x=>f==='all'||x.bot===f);
 if(!rows.length){const tr=document.createElement('tr');td(tr,'No closed trades yet.','empty').colSpan=8;h.append(tr);return;}
 for(const x of rows){const tr=document.createElement('tr');td(tr,new Date(x.closed*1000).toISOString().slice(0,16).replace('T',' '),'mono');
  const t=document.createElement('td'),sp=document.createElement('span');sp.className='tag'+(x.bot==='main'?'':' '+x.bot);sp.textContent=x.name;t.append(sp);tr.append(t);
  td(tr,x.symbol,'mono');td(tr,x.side==='long'?'Buy':'Sell');td(tr,number(x.entry,6),'',1);td(tr,number(x.exit,6),'',1);td(tr,number(x.pnl),x.pnl<0?'bad':'good',1);td(tr,x.reason||'');h.append(tr);}}
$('hist_filter').addEventListener('change',drawHist);
async function loadPerf(){if(!connected)return;try{renderPerf((await api('/api/performance')).data);}catch(e){message('Performance: '+e.message,true);}}
const _drawSummary=drawSummary;drawSummary=function(){_drawSummary();
 const S=[lastBot,lastC3,lastPA].filter(Boolean),used=S.reduce((a,x)=>a+(x.engaged_margin_usd||0),0),b=lastBot;
 const eq=b&&b.shared_account_enabled?b.equity_usd:(b?b.equity_usd:null),allowed=b&&eq?eq*b.allowed_margin_pct/100:null;
 if(allowed)$('margin_bar').style.width=Math.min(100,used/allowed*100)+'%';};
const _connect=$('connect').onclick;$('connect').onclick=async()=>{await _connect();await loadPerf();};
setInterval(loadPerf,60000);
async function loadAccount(){if(!connected)return;try{const a=(await api('/api/account')).data;$('acct_reason').textContent=a.live_reason;
 $('acct_keys').textContent=a.keys.configured?'configured '+(a.keys.api_key_hint||''):'not configured';$('acct_test').disabled=!a.keys.configured;$('acct_live').disabled=!a.live_available;}catch(e){message('Account: '+e.message,true);}}
$('acct_test').onclick=async()=>{const b=$('acct_test');b.disabled=true;$('acct_result').textContent='Asking LBank…';
 try{const r=(await api('/api/account/test','POST',{})).data;$('acct_result').textContent=r.message+(r.balances&&r.balances.length?' · '+r.balances.map(x=>Object.entries(x).map(([k,v])=>k+': '+v).join(', ')).join(' | '):'');$('acct_result').className='small '+(r.ok?'good':'bad');}
 catch(e){$('acct_result').textContent=e.message;$('acct_result').className='small bad';}finally{b.disabled=false;}};
const _connect2=$('connect').onclick;$('connect').onclick=async()=>{await _connect2();await loadAccount();};
let lv=null;
function lvFill(c){$('lv_exchange').value=c.exchange;$('lv_mode').value=c.mode;$('lv_size').value=c.size_factor;$('lv_lev').value=c.leverage;$('lv_cap').value=c.max_position_usd;$('lv_maxpos').value=c.max_positions;$('lv_delay').value=c.max_entry_delay_min;LV_RISK.forEach(([id,k])=>{$(id).value=+(c[k]*100).toFixed(2);});}
const LV_RISK=[['lv_r_trade','risk_per_trade_pct'],['lv_r_total','max_total_open_risk_pct'],['lv_r_day','max_daily_loss_pct'],['lv_r_dd','max_drawdown_pct'],['lv_r_margin','max_margin_usage_pct']];
function renderLive(d){lv=d;const c=d.config,s=d.state||{};if(document.activeElement===null||!document.activeElement.id||!document.activeElement.id.startsWith('lv_'))lvFill(c);
 $('lv_badge').textContent=c.mode.toUpperCase()+' · '+c.exchange+(d.running?' · running':c.mode!=='off'?' · service not running':'')+(d.certification&&d.certification.valid?' · TTT certified':' · not certified for live');$('lv_badge').title=d.certification&&!d.certification.valid?d.certification.reason:'';$('lv_badge').className='badge '+((d.unresolved_live_operations||[]).length?'bad':c.mode==='live'?'bad':c.mode==='dry'?'warn':'');
 $('lv_status').textContent='API key on the server for '+c.exchange+': '+(d.keys[c.exchange]?'configured':'NOT configured')+(s.equity_live!=null?' · exchange equity '+number(s.equity_live)+' USDT · paper equity '+number(s.equity_paper)+' · size ratio '+number(s.ratio,4):'')+(s.paused?' · NEW ENTRIES PAUSED':'')+(s.unmanaged&&s.unmanaged.length?' · other positions on the account (not touched): '+s.unmanaged.join(', '):'')+(d.unresolved_live_operations&&d.unresolved_live_operations.length?' · ⚠ UNRESOLVED LIVE OPERATIONS: '+d.unresolved_live_operations.map(x=>x.exchange+'/'+x.symbol+'/'+x.action).join(', ')+' · MANUAL RECONCILIATION REQUIRED':'');
 const r=$('lv_rows');r.replaceChildren();const m=s.managed||{};const ks=Object.keys(m);
 if(!ks.length){const tr=document.createElement('tr');td(tr,'No mirrored positions.','empty').colSpan=6;r.append(tr);}
 for(const k of ks){const x=m[k],tr=document.createElement('tr');td(tr,k,'mono');td(tr,BOTNAME[x.bot==='main'?'bot':x.bot]||x.bot);td(tr,x.side==='long'?'Buy':'Sell');td(tr,number(x.live_qty0,6),'',1);td(tr,x.stop?number(x.stop,6):'—','',1);td(tr,new Date(x.opened*1000).toISOString().slice(0,16).replace('T',' '),'mono');r.append(tr);}
 const lg=$('lv_log');lg.replaceChildren();for(const e of d.log){const tr=document.createElement('tr');td(tr,new Date(e.t*1000).toISOString().slice(5,16).replace('T',' '),'mono');td(tr,e.mode+' / '+e.exchange);td(tr,e.kind,e.kind==='error'?'bad':'');td(tr,[e.symbol,e.side,e.qty,e.stop,e.reason,e.error,e.note].filter(v=>v!==undefined&&v!==null).join(' · '));lg.append(tr);}}
async function loadLive(){if(!connected)return;try{renderLive((await api('/api/live')).data);}catch(e){message('Live: '+e.message,true);}}
$('lv_save').onclick=async()=>{const body={exchange:$('lv_exchange').value,mode:$('lv_mode').value,size_factor:Number($('lv_size').value),leverage:parseInt($('lv_lev').value,10),max_position_usd:Number($('lv_cap').value),max_positions:parseInt($('lv_maxpos').value,10),max_entry_delay_min:Number($('lv_delay').value)};LV_RISK.forEach(([id,k])=>{body[k]=Number($(id).value)/100;});
 if(body.mode==='live'&&(!lv||lv.config.mode!=='live')){const t=prompt('Real orders with real money on '+body.exchange+'. Type LIVE to confirm.');if(t!=='LIVE'){message('Live mode not confirmed; nothing changed.',true);return;}body.confirm='LIVE';}
 try{await api('/api/live/config','PUT',body);message('Live settings saved ('+body.mode+' on '+body.exchange+').');await loadLive();}catch(e){message(e.message,true);}};
$('lv_test').onclick=async()=>{$('lv_result').textContent='Testing…';try{const r=(await api('/api/live/test','POST',{exchange:$('lv_exchange').value})).data;$('lv_result').textContent=r.message;$('lv_result').className='small '+(r.ok?'good':'bad');}catch(e){$('lv_result').textContent=e.message;$('lv_result').className='small bad';}};
$('lv_readiness').onclick=async()=>{
 $('lv_result').textContent='Running read-only TheTrueTrade readiness audit…';
 try{
  const r=(await api('/api/live/readiness')).data;
  const labels={
   LOCAL_LIVE_CONFIG_NOT_VALIDATED:'Live configuration is missing or invalid.',
   LIVE_MIRROR_MUST_BE_OFF_FOR_AUDIT:'Set the mirror to Off before running this audit.',
   EXCHANGE_CONFIG_NOT_THETRUETRADE:'The selected exchange is not TheTrueTrade.',
   NON_OFFICIAL_API_BASE:'The API base URL is not the official TheTrueTrade endpoint.',
   ADAPTER_NOT_THETRUETRADE:'The selected adapter is not TheTrueTrade.',
   NEW_ENTRY_STOP_READBACK_NOT_IMPLEMENTED:'The exchange stop-loss cannot yet be independently read back after entry.',
   STOP_MOVE_READBACK_NOT_IMPLEMENTED:'Trailing stop updates cannot yet be independently verified.',
   RISK_BASED_POSITION_SIZING_NOT_IMPLEMENTED:'Live risk-based position sizing is not yet enforced.',
   THREE_BOT_SAME_SYMBOL_POSITION_OWNERSHIP_NOT_RESOLVED:'Same-symbol ownership across bots is not resolved.',
   LIVE_RISK_POLICY_FIELDS_NOT_CONFIGURED:'Required live risk-policy settings are missing.',
   ADOPT_EXISTING_POSITIONS_ENABLED:'Adopting pre-existing exchange positions is unsafe.',
   EXCHANGE_ORDER_MINIMUMS_UNVERIFIED:'One or more exchange order minimums are not verified.',
   EXISTING_REAL_POSITIONS_NEED_INDEPENDENT_REVIEW:'Existing exchange positions need independent review.'
  };
  const blockers=(r.blockers||[]).map(x=>labels[x]||x);
  $('lv_result').textContent=(r.conclusion||'NOT_READY')+' — '+(blockers.length?blockers.join(' '):'No blockers were reported; this audit does not authorize live trading.');
  $('lv_result').className='small '+(r.live_trading_authorized?'good':'bad');
 }catch(e){$('lv_result').textContent='Readiness audit failed: '+e.message;$('lv_result').className='small bad';}
};
$('lv_panic').onclick=async()=>{if(!confirm('Close every position the mirror opened on the exchange and stop new entries?'))return;try{const r=(await api('/api/live/close-all','POST',{})).data;message(r.note);}catch(e){message(e.message,true);}};
const _connect3=$('connect').onclick;$('connect').onclick=async()=>{await _connect3();for(const id of ['lv_save','lv_test','lv_readiness','lv_panic'])$(id).disabled=false;await loadLive();};
setInterval(loadLive,15000);
</script></body></html>'''

_THEME_ASSETS = Path(__file__).with_name('frontend') / 'public' / 'portal-assets'
HTML = HTML.replace('<title>',
    '<style id="titanium-tokens">' + (_THEME_ASSETS / 'titanium.css').read_text() + '</style>'
    + '<script id="trade-appearance-init">' + (_THEME_ASSETS / 'appearance.js').read_text() + '</script><title>', 1)

app = create_app()
