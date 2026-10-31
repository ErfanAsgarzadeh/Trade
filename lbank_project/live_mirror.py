"""Live mirror: copies the three bots' PAPER positions onto a real exchange account (Binance USDT-M or TheTrueTrade).

The bots are not changed and keep trading on paper. This separate service (docker service lbank-live) reads their
databases every few seconds and makes the exchange account follow them:
  * a NEW paper position (first seen while the mirror runs, or opened at most max_entry_delay_min ago) is opened at market,
    size = paper size x (exchange equity / paper equity) x size_factor, with the paper stop as an exchange stop-loss;
  * paper stop moves (trailing / break-even / profit floor) are copied to the exchange stop;
  * paper reductions (take-profit part, F cuts) and adds (pyramid) are copied in proportion;
  * a paper exit closes the exchange position.
Only positions the mirror opened itself are ever touched; anything else on the account is left alone.
Positions that were already open when the mirror was switched on are NOT copied (they would be entered late).

Settings: runtime/live_config.json (dashboard: Settings > Live execution)
  mode            off (default) | dry (simulated exchange, logs what it would do) | live (real orders)
  exchange        thetruetrade | binance
  size_factor     extra multiplier on the proportional size (default 1.0; e.g. 0.1 = one tenth)
  leverage        isolated leverage per order (default 5, the bots' setting)
  max_entry_delay_min, max_position_usd (notional cap per position), max_positions
Keys: .env only (TTT_API_KEY/TTT_API_SECRET or BINANCE_API_KEY/BINANCE_API_SECRET[/BINANCE_TESTNET=1]).
Files: runtime/live_state_<mode>_<exchange>.json (managed positions), runtime/live_log.jsonl (every action), runtime/live_command.json.
"""
from __future__ import annotations
import json, logging, math, os, time
from pathlib import Path
import exchanges as X

LOG = logging.getLogger("live_mirror")
DEFAULT = dict(mode="off", exchange="thetruetrade", size_factor=1.0, leverage=5, max_entry_delay_min=30,
               max_position_usd=5000.0, max_positions=40, adopt_existing=False)
MODES = ("off", "dry", "live")


def folder() -> Path:
    return Path(os.getenv("RISK_DIR", str(Path(os.getenv("BOT_DB", "data/lbank_ichimoku_bot.db")).resolve().parent)))


def validate(c: dict) -> dict:
    v = {**DEFAULT, **{k: c[k] for k in DEFAULT if k in c}}
    if v["mode"] not in MODES:raise ValueError("mode must be off, dry or live")
    if v["exchange"] not in ("thetruetrade", "binance"):raise ValueError("exchange must be thetruetrade or binance")
    if not (isinstance(v["size_factor"], (int, float)) and 0 < v["size_factor"] <= 3):raise ValueError("size_factor must be in (0, 3]")
    if not (isinstance(v["leverage"], int) and 1 <= v["leverage"] <= 20):raise ValueError("leverage must be an integer 1..20")
    if not (isinstance(v["max_entry_delay_min"], (int, float)) and 1 <= v["max_entry_delay_min"] <= 240):raise ValueError("max_entry_delay_min must be 1..240")
    if not (isinstance(v["max_position_usd"], (int, float)) and v["max_position_usd"] > 0):raise ValueError("max_position_usd must be > 0")
    if not (isinstance(v["max_positions"], int) and 1 <= v["max_positions"] <= 100):raise ValueError("max_positions must be 1..100")
    if not isinstance(v["adopt_existing"], bool):raise ValueError("adopt_existing must be true or false")
    return v


def read_config() -> dict:
    try:return validate(json.loads((folder() / "live_config.json").read_text()))
    except Exception:return dict(DEFAULT)


def write_config(c: dict) -> dict:
    v = validate(c);p = folder() / "live_config.json";p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp");tmp.write_text(json.dumps(v, indent=1));tmp.replace(p);return v


class Paper:
    """Read-only view of the three bots' paper positions (exchange-independent units: base asset quantity)."""
    def __init__(self):
        import lbank_bot as bot, c3_sleeve, pa_sleeve
        self.bot, self.c3, self.pa = bot, c3_sleeve, pa_sleeve
        self.db = bot.Database();self.seed = float(os.getenv("PAPER_EQUITY", "10000"))
        try:self.seed = float(self.db.runtime_all().get("paper_initial_equity", self.seed))
        except Exception:pass

    def positions(self) -> dict[str, dict]:
        out = {}
        for p in self.db.positions():
            if p["state"] == self.bot.PENDING:continue
            out[p["symbol"]] = dict(bot="main", side=p["side"], qty=float(p["qty"]) * float(p.get("contract_size") or 1), stop=float(p["active_sl"]),
                                    key=f"main|{p['symbol']}|{p.get('signal_ts', 0)}", opened=None)
        for key, mod in (("c3", self.c3), ("pa", self.pa)):
            for p in mod.paths()[1].positions():
                out[p["symbol"]] = dict(bot=key, side=p["side"], qty=float(p["qty"]), stop=float(p["stop"]), key=f"{key}|{p['symbol']}|{p['opened']}", opened=float(p["opened"]))
        return out

    def equity(self) -> float:
        """Paper equity from closed trades (no prices needed); the size ratio does not need open P&L precision."""
        with self.db.connect() as db:
            r = float(db.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM trade_history WHERE dry_run=1").fetchone()[0])
        for mod in (self.c3, self.pa):
            try:
                with mod.paths()[1].db() as db:r += float(db.execute("SELECT COALESCE(SUM(pnl),0) FROM trades").fetchone()[0])
            except Exception:pass
        return max(1.0, self.seed + r)


class Mirror:
    def __init__(self, adapter: X.Adapter, paper, cfg: dict | None = None, now=time.time):
        self.ex, self.paper, self.now = adapter, paper, now
        self.cfg = cfg or read_config()
        # separate state per mode and exchange: a dry run can never forget (orphan) positions of the live account
        self.state_path = folder() / f"live_state_{self.cfg['mode']}_{self.cfg['exchange']}.json";self.log_path = folder() / "live_log.jsonl"
        self.state = self._load()

    # ---------------- persistence
    def _load(self) -> dict:
        if not self.state_path.is_file():
            s = {}
        else:
            try:
                s = json.loads(self.state_path.read_text())
                if not isinstance(s, dict):
                    raise ValueError("mirror state is not a dictionary")
                if not isinstance(s.get("managed", {}), dict) or not isinstance(s.get("pending_orders", {}), dict):
                    raise ValueError("invalid managed or pending order state")
            except (OSError, ValueError, TypeError) as exc:
                # NEVER silently reset live ownership when state is corrupt.
                if self.cfg["mode"] == "live":
                    raise X.ExchangeError(f"Cannot load live mirror state: {type(exc).__name__}") from None
                s = {}
        s.setdefault("managed", {});s.setdefault("seen", {});s.setdefault("errors", 0);s.setdefault("paused", False);s.setdefault("last_cycle", 0)
        s.setdefault("pending_orders", {})
        if s["pending_orders"]:
            s["paused"] = True  # Durable uncertainty survives restart and config edits.
        return s

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True);tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1));tmp.replace(self.state_path)

    def event(self, kind: str, **kw):
        row = dict(t=self.now(), mode=self.cfg["mode"], exchange=self.ex.name, kind=kind, **kw);LOG.info("%s %s", kind, kw)
        with open(self.log_path, "a") as f:f.write(json.dumps(row) + "\n")

    # ---------------- helpers
    def _fresh(self, p: dict, first_seen: float, was_running: bool) -> bool:
        if self.cfg["adopt_existing"]:return True
        limit = self.cfg["max_entry_delay_min"] * 60;now = self.now()
        if p["opened"] is not None:return now - p["opened"] <= limit
        return was_running and now - first_seen <= limit

    def _qty(self, sym: str, qty: float) -> float:
        m = self.ex.markets().get(sym, {});return X.round_step(qty, m.get("step", 0))

    def _entry_preflight(self, esym: str, side: str, qty: float, price: float, stop: float) -> bool:
        """Reject unprotected and underfunded entries without touching order endpoints."""
        if (side not in ("long", "short") or
                not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                        for x in (qty, price, stop)) or qty <= 0 or price <= 0 or stop <= 0 or
                not ((side == "long" and stop < price) or (side == "short" and stop > price))):
            self.state["paused"] = True
            raise X.ExchangeError(f"{esym}: invalid or missing protective stop; entries paused")
        # No entry can be sent unless the venue's active stop can be read back.
        # TheTrueTrade and Binance adapters currently block live orders here.
        self.ex.ensure_protected_entries()
        market = self.ex.markets().get(esym)
        if not isinstance(market, dict):
            raise X.ExchangeError(f"{esym}: missing market contract metadata")
        max_leverage = market.get("max_leverage")
        if max_leverage is not None and self.cfg["leverage"] > max_leverage:
            raise X.ExchangeError(f"{esym}: leverage exceeds exchange maximum")
        available = self.ex.available_balance()
        if not isinstance(available, (float, int)) or isinstance(available, bool) or not math.isfinite(available) or available < 0:
            self.state["paused"] = True
            raise X.ExchangeError("Available margin unavailable or invalid; entries paused")
        # 5% buffer for price drift/fees; never use equity in place of free margin.
        required = qty * price / self.cfg["leverage"] * 1.05
        if required > available + 1e-9:
            self.event("skip", symbol=esym, reason="insufficient available margin",
                       free_margin=round(available, 8), required_margin=round(required, 8))
            return False
        return True

    def _submit_entry(self, esym, side, qty, stop, key):
        """Write-ahead journal: no automatic retry after an ambiguous order outcome."""
        if self.state["pending_orders"]:
            raise X.ExchangeError("Unresolved exchange order exists; manual reconciliation required")
        self.state["pending_orders"][esym] = dict(action="open", key=key, side=side, qty=qty,
                                                  stop=stop, attempted_at=self.now())
        self.save()  # Durable BEFORE submitting to the exchange.
        try:
            self.ex.open(esym, side, qty, self.cfg["leverage"], stop)
            observed = self.ex.positions().get(esym)
            if observed is None or observed.side != side or observed.qty <= 0:
                raise X.ExchangeError(f"{esym}: exchange entry was not confirmed")
            self.ex.verify_stop(observed, stop)
        except Exception as exc:
            self.state["paused"] = True
            self.save()
            self.event("order_uncertain", symbol=esym, reason=type(exc).__name__,
                       note="No retry; verify exchange position and stop manually")
            raise X.ExchangeError(f"{esym}: entry outcome/stop unverified; no automatic retry") from exc
        del self.state["pending_orders"][esym]
        self.save()
        return observed

    # ---------------- one cycle
    def cycle(self):
        if self.cfg["mode"] == "off":return
        cmd = folder() / "live_command.json"
        if cmd.is_file():
            try:c = json.loads(cmd.read_text())
            except Exception:c = {}
            cmd.unlink(missing_ok=True)
            if c.get("close_all"):self.close_managed("dashboard emergency close");self.state["paused"] = True;self.save();return
            if c.get("resume"):
                if self.state["pending_orders"]:
                    self.event("resume_denied", reason="unresolved_order",
                               note="Manual reconciliation required; no automatic retry")
                else:
                    self.state.update(paused=False, errors=0)
                    self.event("resume", note="new entries allowed again")
        if self.state["pending_orders"]:
            self.state["paused"] = True
            self.save()
            return  # Never replay or overwrite an ambiguous order after restart.
        now = self.now();was_running = now - self.state["last_cycle"] < 180
        paper = self.paper.positions();markets = self.ex.markets();live = self.ex.positions()
        eq_live = self.ex.equity();eq_paper = self.paper.equity();ratio = eq_live / eq_paper * self.cfg["size_factor"]
        self.state.update(equity_live=eq_live, equity_paper=eq_paper, ratio=ratio)
        seen = self.state["seen"]
        for k in [k for k in seen if k not in {p["key"] for p in paper.values()}]:del seen[k]
        self.state["skipped"] = {k: v for k, v in self.state.get("skipped", {}).items() if k in seen}
        targets = {}
        for sym, p in paper.items():
            esym, mult = X.bot_to_exchange(sym)
            seen.setdefault(p["key"], now)
            if esym not in markets:continue
            targets[esym] = dict(p, mult=mult, ex_qty=p["qty"] / mult, ex_stop=p["stop"] * mult, first_seen=seen[p["key"]])
        managed = self.state["managed"]
        for esym in sorted(set(targets) | set(managed)):
            try:self._reconcile(esym, targets.get(esym), live.get(esym), ratio, was_running)
            except Exception as exc:
                self.state["errors"] += 1;self.event("error", symbol=esym, error=str(exc)[:300])
                if self.state["errors"] >= 5 and not self.state["paused"]:
                    self.state["paused"] = True;self.event("paused", reason="5 consecutive errors; new entries stopped until settings are saved again")
        self.state["unmanaged"] = sorted(s for s in live if s not in managed)
        self.state["last_cycle"] = now;self.save()

    def _reconcile(self, esym, t, l, ratio, was_running):
        managed = self.state["managed"];m = managed.get(esym)
        if m and l is None:                               # closed on the exchange (stop hit / liquidated / manual)
            self.event("exchange_closed", symbol=esym, note="position no longer on the exchange (stop hit / liquidation / manual); not re-entered")
            self.state.setdefault("skipped", {})[m["key"]] = True;del managed[esym];m = None
        if t is None:
            if m and l is not None:
                self.ex.close(l);self.event("close", symbol=esym, qty=l.qty, reason="paper exit");del managed[esym]
            return
        if m and m["key"] != t["key"] and l is not None:   # a different paper trade now: close the old one first
            self.ex.close(l);self.event("close", symbol=esym, qty=l.qty, reason="paper trade replaced");del managed[esym];m = None;l = None
        if m is None:
            if l is not None:return                        # someone else's position on this symbol: never touch
            if self.state["paused"] or not self._fresh(t, t["first_seen"], was_running):return
            if len(managed) >= self.cfg["max_positions"]:self.event("skip", symbol=esym, reason="max_positions");return
            if self.state.get("skipped", {}).get(t["key"]):return
            px = self.ex.price(esym);q = t["ex_qty"] * ratio;q = min(q, self.cfg["max_position_usd"] / px);q = self._qty(esym, q)
            mk = self.ex.markets().get(esym, {})
            if q <= 0 or q * px < mk.get("min_notional", 5) or q < mk.get("min_qty", 0):
                self.event("skip", symbol=esym, reason=f"size {q} below exchange minimum");self.state.setdefault("skipped", {})[t["key"]] = True;return
            stop = t["ex_stop"]
            if not self._entry_preflight(esym, t["side"], q, px, stop):
                return
            observed = self._submit_entry(esym, t["side"], q, stop, t["key"])
            managed[esym] = dict(key=t["key"], bot=t["bot"], side=t["side"], paper_qty0=t["ex_qty"], live_qty0=observed.qty, stop=stop, opened=self.now())
            self.state["errors"] = 0;self.event("open", symbol=esym, bot=t["bot"], side=t["side"], qty=q, price=px, stop=stop)
            return
        # managed & present: follow size and stop
        target_q = self._qty(esym, m["live_qty0"] * t["ex_qty"] / m["paper_qty0"]) if m["paper_qty0"] > 0 else l.qty
        step = self.ex.markets().get(esym, {}).get("step", 0) or 0
        if l.qty - target_q > max(step, l.qty * .02):
            if target_q <= 0:self.ex.close(l);self.event("close", symbol=esym, qty=l.qty, reason="paper reduced to zero");del managed[esym];return
            self.ex.close(l, l.qty - target_q);self.event("reduce", symbol=esym, qty=l.qty - target_q, reason="paper reduced (take-profit part / F cut)")
        elif target_q - l.qty > max(step, l.qty * .02) and not self.state["paused"]:
            add = self._qty(esym, min(target_q - l.qty, max(0., self.cfg["max_position_usd"] / self.ex.price(esym) - l.qty)))
            if add > 0:
                px = self.ex.price(esym)
                if self._entry_preflight(esym, l.side, add, px, t["ex_stop"]):
                    self._submit_entry(esym, l.side, add, t["ex_stop"], t["key"])
                    self.event("add", symbol=esym, qty=add, reason="paper added (pyramid)")
        s = t["ex_stop"]
        if s > 0 and (m.get("stop") is None or abs(s - m["stop"]) / s > 5e-4):
            px = self.ex.price(esym)
            if (l.side == "long" and s < px) or (l.side == "short" and s > px):
                cur = self.ex.positions().get(esym, l);self.ex.set_stop(cur, s);self.event("stop", symbol=esym, stop=s, previous=m.get("stop"));m["stop"] = s

    def close_managed(self, reason: str):
        live = self.ex.positions()
        for esym in list(self.state["managed"]):
            if esym in live:
                try:self.ex.close(live[esym]);self.event("close", symbol=esym, qty=live[esym].qty, reason=reason)
                except Exception as exc:self.event("error", symbol=esym, error=str(exc)[:300]);continue
            del self.state["managed"][esym]


def adapter_for(cfg: dict) -> X.Adapter:
    if cfg["mode"] == "dry":
        real = X.make(cfg["exchange"])   # public data only (markets, prices); orders go to the simulator
        sim = X.Sim(price_fn=real.price, equity=float(os.getenv("LIVE_DRY_EQUITY", "1000")))
        sim._m = None;sim.markets = real.markets;sim.name = f"dry:{cfg['exchange']}";return sim
    return X.make(cfg["exchange"])


def run(once: bool = False):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    LOG.info("live mirror started; settings in %s", folder() / "live_config.json")
    paper = None;mirror = None;key = None
    while True:
        try:
            cfg = read_config()
            if cfg["mode"] != "off":
                if paper is None:paper = Paper()
                k = (cfg["mode"], cfg["exchange"])
                if mirror is None or key != k:
                    mirror = Mirror(adapter_for(cfg), paper, cfg);key = k;mirror.event("start", note=f"mirror {cfg['mode']} on {cfg['exchange']}")
                mirror.cfg = cfg;mirror.cycle()
        except Exception:
            LOG.exception("mirror cycle failed; retrying")
        if once:return
        time.sleep(10)


if __name__ == "__main__":
    import sys
    run(once="--once" in sys.argv)
