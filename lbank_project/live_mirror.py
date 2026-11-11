"""Live mirror: copies the three bots' PAPER positions onto a real exchange account (Binance USDT-M or TheTrueTrade).

The bots are not changed and keep trading on paper. This separate service (docker service lbank-live) reads their
databases every few seconds and makes the exchange account follow them:
  * a NEW paper position (first seen while the mirror runs, or opened at most max_entry_delay_min ago) is opened at market,
    size = paper size x (exchange equity / paper equity) x size_factor, with the paper stop as an exchange stop-loss;
  * paper stop moves (trailing / break-even / profit floor) are copied to the exchange stop;
  * paper reductions (take-profit part) and adds (pyramid) are copied in proportion;
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
import json, logging, math, os, sqlite3, time
from pathlib import Path
import exchanges as X
import live_risk

LOG = logging.getLogger("live_mirror")
DEFAULT = dict(mode="off", exchange="thetruetrade", size_factor=1.0, leverage=5, max_entry_delay_min=30,
               max_position_usd=5000.0, max_positions=40, adopt_existing=False, **live_risk.DEFAULTS)
MODES = ("off", "dry", "live")


def folder() -> Path:
    return Path(os.getenv("RISK_DIR", str(Path(os.getenv("BOT_DB", "data/lbank_ichimoku_bot.db")).resolve().parent)))


def validate(c: dict) -> dict:
    if not isinstance(c, dict):
        raise ValueError('Live config must be an object')
    v = {**DEFAULT, **{k: c[k] for k in DEFAULT if k in c}}
    for key in ('size_factor', 'max_entry_delay_min', 'max_position_usd'):
        if isinstance(v[key], bool) or not isinstance(v[key], (int, float)) or not math.isfinite(v[key]):
            raise ValueError(f'{key} must be finite')
    for key in ('leverage', 'max_positions'):
        if type(v[key]) is not int:
            raise ValueError(f'{key} must be an integer')
    for key in live_risk.KEYS:
        try:
            v[key] = live_risk.positive(v[key])
        except X.ExchangeError:
            raise ValueError(f'{key} must be a positive fraction') from None
        if v[key] > 1:
            raise ValueError('Live risk fractions must be in (0, 1]')
    if v['risk_per_trade_pct'] > v['max_total_open_risk_pct']:
        raise ValueError('risk_per_trade_pct must not exceed max_total_open_risk_pct')
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

    @staticmethod
    def _add_unique(out: dict, symbol: str, value: dict) -> None:
        if symbol in out:
            raise X.ExchangeError(
                f"{symbol}: overlapping paper positions across bots; "
                "Live Mirror cannot safely merge or overwrite ownership"
            )
        out[symbol] = value

    @staticmethod
    def _sleeve_snapshot(name: str, mod) -> tuple[dict, list[dict], float]:
        """Read sleeve config and DB without calling paths()/Store() auto-migrations.

        c3/pa paths() may modify default config values during startup.
        The mirror must NEVER rewrite any bot config when merely observing.
        """
        prefix = {"c3": "C3", "pa": "PA"}[name]
        base = Path(mod.__file__).resolve().parent
        cfg_path = Path(os.getenv(prefix + "_CONFIG", str(base / (name + "_config.json"))))
        db_path = Path(os.getenv(prefix + "_DB", str(base / "data" / (name + "_sleeve.db")))).resolve()
        if not cfg_path.is_file() or not db_path.is_file():
            raise X.ExchangeError(f"{name}: missing PAPER config/database; live sizing blocked")
        config = mod.validate(json.loads(cfg_path.read_text()))
        db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            positions = [dict(x) for x in db.execute(
                "SELECT p.*, COALESCE(m.isolated_leverage,5) AS isolated_leverage "
                "FROM positions p LEFT JOIN position_margin m "
                "ON p.symbol=m.symbol AND p.opened=m.opened"
            )]
            realized = db.execute("SELECT COALESCE(SUM(pnl),0) FROM trades").fetchone()[0]
        finally:
            db.close()
        return config, positions, float(realized)

    def positions(self) -> dict[str, dict]:
        out = {}
        conflicts = set()
        def collect(symbol, value):
            if symbol in conflicts:
                return  # A third bot on the same symbol stays ambiguous.
            try:
                self._add_unique(out, symbol, value)
            except X.ExchangeError:
                out.pop(symbol, None)
                conflicts.add(symbol)

        for p in self.db.positions():
            if p["state"] == self.bot.PENDING:continue
            collect(p["symbol"], dict(bot="main", side=p["side"], qty=float(p["qty"]) * float(p.get("contract_size") or 1), stop=float(p["active_sl"]),
                                      key=f"main|{p['symbol']}|{p.get('signal_ts', 0)}", opened=None))
        for key, mod in (("c3", self.c3), ("pa", self.pa)):
            _, sleeve_positions, _ = self._sleeve_snapshot(key, mod)
            for p in sleeve_positions:
                collect(p["symbol"], dict(bot=key, side=p["side"], qty=float(p["qty"]), stop=float(p["stop"]),
                                          key=f"{key}|{p['symbol']}|{p['opened']}", opened=float(p["opened"])))
        # Conflicts are NOT netted or overwritten. Other independent symbols
        # can be reconciled, but existing ownership on conflicted symbols
        # requires manual resolution before it can be changed.
        self.conflicts = conflicts
        return out

    def equity(self) -> float:
        """Mark-to-market the three PAPER sleeves using public LBank futures prices.

        Realized-only equity understates/overstates the live/paper sizing ratio
        while trades are open. A missing sleeve DB, quote or invalid balance
        is UNKNOWN: never silently omit a bot or fabricate a $1 equity.
        """
        from lbank_candles import fetch_prices, lbank_name

        def number(value, name: str) -> float:
            if isinstance(value, bool):
                raise X.ExchangeError(f"Invalid paper {name}")
            try:
                n = float(value)
            except (TypeError, ValueError, OverflowError):
                raise X.ExchangeError(f"Invalid paper {name}") from None
            if not math.isfinite(n):
                raise X.ExchangeError(f"Invalid paper {name}")
            return n

        total = number(self.seed, "initial equity")
        if total <= 0:
            raise X.ExchangeError("Non-positive paper initial equity")
        with self.db.connect() as db:
            total += number(db.execute(
                "SELECT COALESCE(SUM(pnl_usd),0) FROM trade_history WHERE dry_run=1"
            ).fetchone()[0], "main realized PnL")

        main_open = [p for p in self.db.positions() if p["state"] != self.bot.PENDING]
        sleeves = []
        for name, mod in (("c3", self.c3), ("pa", self.pa)):
            config, sleeve_positions, realized = self._sleeve_snapshot(name, mod)
            total += number(realized, f"{name} realized PnL")
            sleeves.append((name, config, sleeve_positions))

        if main_open or any(positions for _, _, positions in sleeves):
            quotes = fetch_prices()  # GET only; do not use spot or synthetic/demo prices.
            def price(symbol):
                raw = quotes.get(lbank_name(symbol))
                px = number(raw, f"futures quote for {symbol}")
                if px <= 0:
                    raise X.ExchangeError(f"Missing/invalid futures quote for {symbol}")
                return px

            for p in main_open:
                if p.get("dry_run") != 1:
                    raise X.ExchangeError("Main paper position is not dry-run")
                total += number(self.bot.net_pnl(p, price(p["symbol"]), p["qty"]),
                                "main open PnL")
            for name, config, positions in sleeves:
                fee = number(config["round_trip_fee"], f"{name} round trip fee")
                if fee < 0:
                    raise X.ExchangeError(f"Invalid {name} round trip fee")
                for p in positions:
                    side = p["side"]
                    if side not in ("long", "short"):
                        raise X.ExchangeError(f"Invalid {name} position direction")
                    entry = number(p["entry"], f"{name} entry")
                    qty = number(p["qty"], f"{name} quantity")
                    if entry <= 0 or qty <= 0:
                        raise X.ExchangeError(f"Invalid {name} open position")
                    px = price(p["symbol"])
                    sign = 1 if side == "long" else -1
                    total += sign * (px - entry) * qty - (px + entry) * qty * fee / 2

        if not math.isfinite(total) or total <= 0:
            raise X.ExchangeError("Paper equity is invalid or exhausted; entries blocked")
        return total


class Mirror:
    def __init__(self, adapter: X.Adapter, paper, cfg: dict | None = None, now=time.time):
        self.ex, self.paper, self.now = adapter, paper, now
        self.cfg = cfg or read_config()
        # separate state per mode and exchange: a dry run can never forget (orphan) positions of the live account
        self.state_path = folder() / f"live_state_{self.cfg['mode']}_{self.cfg['exchange']}.json";self.log_path = folder() / "live_log.jsonl"
        self.state = self._load()
        self._session_has_completed_cycle = False
        self.wait = lambda s: X.pause(s)

    def _readback(self, esym: str, ok, tries: int = 5):
        """Exchange position after an order, re-read a few times until `ok(position)` (exchanges settle in a moment)."""
        pos = None
        for i in range(tries):
            pos = self.ex.positions().get(esym)
            if ok(pos):return pos
            if i < tries - 1:self.wait(1.0)
        return pos

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
        m = self.ex.markets().get(sym)
        step = m.get("step") if isinstance(m, dict) else None
        if (not isinstance(step, (int, float)) or isinstance(step, bool)
                or not math.isfinite(step) or step <= 0):
            raise X.ExchangeError(f"{sym}: missing/invalid quantity step; order blocked")
        return X.round_step(qty, step)

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
        if self.cfg['mode'] == 'live' and not isinstance(self.ex, X.Sim):
            try:
                live_risk.entry_budget(self.cfg, self.state, self.ex, esym, side,
                                       qty, price, stop, self.now(), self.save)
            except live_risk.RiskLimit as exc:
                self.event("skip", symbol=esym, reason=str(exc))
                return False
        market = self.ex.markets().get(esym)
        if not isinstance(market, dict):
            raise X.ExchangeError(f"{esym}: missing market contract metadata")
        # A missing minOrderSize/minOrderValue is NOT equivalent to stepSize or
        # a fixed $5 minimum. Fail closed until the venue's real limits are known.
        for field in ("step", "min_qty", "min_notional"):
            limit = market.get(field)
            if (not isinstance(limit, (int, float)) or isinstance(limit, bool)
                    or not math.isfinite(limit) or limit <= 0):
                raise X.ExchangeError(f"{esym}: {field} unknown/invalid; order blocked")
        if qty + 1e-12 < market["min_qty"] or qty * price + 1e-12 < market["min_notional"]:
            self.event("skip", symbol=esym, reason="below verified market minima")
            return False
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

    def _submit_entry(self, esym, side, qty, stop, key, before_qty=0.0):
        """Write-ahead journal: no automatic retry after an ambiguous order outcome."""
        if self.state["pending_orders"]:
            raise X.ExchangeError("Unresolved exchange order exists; manual reconciliation required")
        self.state["pending_orders"][esym] = dict(action="open", key=key, side=side, qty=qty,
                                                  stop=stop, attempted_at=self.now())
        self.save()  # Durable BEFORE submitting to the exchange.
        try:
            returned_position_id = self.ex.open(esym, side, qty, self.cfg["leverage"], stop)
            tol = max(1e-10, float(self.ex.markets().get(esym, {}).get("step") or 0) * 0.05)
            observed = self._readback(esym, lambda o: o is not None and o.side == side and abs(o.qty - (before_qty + qty)) <= tol
                                      and (returned_position_id is None or any(str(i) == str(returned_position_id) for i in o.ids)))
            if observed is None or observed.side != side or observed.qty <= 0:
                raise X.ExchangeError(f"{esym}: exchange entry was not confirmed")
            if returned_position_id is not None and not any(
                    str(pid) == str(returned_position_id) for pid in observed.ids):
                raise X.ExchangeError(
                    f"{esym}: newly opened positionId absent from exchange readback"
                )
            market = self.ex.markets().get(esym, {})
            tolerance = max(1e-10, float(market.get("step") or 0) * 0.05)
            expected = before_qty + qty
            if not math.isfinite(observed.qty) or abs(observed.qty - expected) > tolerance:
                raise X.ExchangeError(
                    f"{esym}: entry size not confirmed (expected {expected}, got {observed.qty})"
                )
            self.ex.verify_stop(observed, stop)
        except Exception as exc:
            self.state["paused"] = True
            self.save()
            self.event("order_uncertain", symbol=esym, reason=type(exc).__name__,
                       note="No retry; verify exchange position and stop manually")
            raise X.ExchangeError(f"{esym}: entry outcome/stop unverified; no automatic retry") from exc
        # The caller must durably save ownership BEFORE resolving the journal.
        # A crash between exchange confirmation and state persistence must not
        # leave an unmanaged position that can be silently forgotten.
        return observed

    def _close_verified(self, esym, position, qty=None):
        """Journal a close and verify the remaining exchange quantity before acknowledging it."""
        if self.state["pending_orders"]:
            raise X.ExchangeError("Unresolved order exists; manual reconciliation required")
        initial = float(position.qty)
        closing = initial if qty is None else float(qty)
        if not math.isfinite(closing) or closing <= 0 or closing > initial + 1e-10:
            raise X.ExchangeError(f"{esym}: invalid close quantity")
        self.state["pending_orders"][esym] = dict(
            action="close", qty=closing, before_qty=initial, attempted_at=self.now())
        self.save()
        try:
            self.ex.close(position, qty)
            expected = max(0.0, initial - closing)
            tol = max(1e-10, float((self.ex.markets().get(esym) or {}).get("step") or 0) * 0.05)
            after = self._readback(esym, lambda o: (o is None and expected <= tol) or (o is not None and abs(o.qty - expected) <= tol))
            actual = 0.0 if after is None else after.qty
            if after is not None and (after.side != position.side or not math.isfinite(after.qty)):
                raise X.ExchangeError(f"{esym}: close resulted in wrong side/invalid quantity")
            market = self.ex.markets().get(esym) or {}
            # Exchange quantity precision and partial-fill behavior can vary.
            # A missing/inconsistent confirmation is UNKNOWN, never success.
            tolerance = max(1e-10, float(market.get("step") or 0) * 0.05)
            if not math.isfinite(actual) or abs(actual - expected) > tolerance:
                raise X.ExchangeError(
                    f"{esym}: close not confirmed (expected {expected}, got {actual})")
        except Exception as exc:
            self.state["paused"] = True
            self.save()
            self.event("order_uncertain", symbol=esym, action="close",
                       reason=type(exc).__name__,
                       note="Close may have filled; manual exchange reconciliation required")
            raise X.ExchangeError(f"{esym}: close outcome unverified; never retry automatically") from exc
        del self.state["pending_orders"][esym]
        self.save()

    def _set_stop_verified(self, esym, pos, stop, managed_state):
        """A stop-change response alone does not prove that protection is active."""
        if self.state["pending_orders"]:
            raise X.ExchangeError("Unresolved order exists; manual reconciliation required")
        self.state["pending_orders"][esym] = dict(
            action="set_stop", stop=stop, attempted_at=self.now())
        self.save()
        try:
            self.ex.set_stop(pos, stop)
            actual = self.ex.positions().get(esym)
            if actual is None:
                raise X.ExchangeError(f"{esym}: position missing after stop update")
            self.ex.verify_stop(actual, stop)
        except Exception as exc:
            self.state["paused"] = True
            self.save()
            self.event("order_uncertain", symbol=esym, action="set_stop",
                       reason=type(exc).__name__,
                       note="Stop update not confirmed; manual reconciliation required")
            raise X.ExchangeError(f"{esym}: stop outcome unverified") from exc
        managed_state["stop"] = stop
        self.save()  # Persist verified stop while journal still exists.
        del self.state["pending_orders"][esym]
        self.save()

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
        now = self.now()
        was_running = (self._session_has_completed_cycle and
                       0 <= now - self.state["last_cycle"] < 180)
        paper = self.paper.positions();markets = self.ex.markets();live = self.ex.positions()
        conflicted_exchange_symbols = {X.bot_to_exchange(sym)[0]
                                       for sym in getattr(self.paper, "conflicts", set())}
        eq_live = self.ex.equity();eq_paper = self.paper.equity()
        if (not math.isfinite(eq_live) or not math.isfinite(eq_paper) or
                eq_live <= 0 or eq_paper <= 0):
            raise X.ExchangeError("Invalid live/paper equity: no reconciliation")
        ratio = eq_live / eq_paper * self.cfg["size_factor"]
        if not math.isfinite(ratio) or ratio <= 0:
            raise X.ExchangeError("Invalid live/paper sizing ratio: no reconciliation")
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
        for esym in sorted(conflicted_exchange_symbols):
            self.event("paper_symbol_conflict", symbol=esym,
                       note="Overlapping bot ownership cannot be safely netted; no orders on this symbol")
            if esym in managed:
                self.state["paused"] = True
        for esym in sorted((set(targets) | set(managed)) - conflicted_exchange_symbols):
            try:self._reconcile(esym, targets.get(esym), live.get(esym), ratio, was_running)
            except Exception as exc:
                self.state["errors"] += 1;self.event("error", symbol=esym, error=str(exc)[:300])
                if self.state["errors"] >= 5 and not self.state["paused"]:
                    self.state["paused"] = True;self.event("paused", reason="5 consecutive errors; new entries stopped until settings are saved again")
        self.state["unmanaged"] = sorted(s for s in live if s not in managed)
        self.state["last_cycle"] = now;self.save()
        self._session_has_completed_cycle = True

    def _reconcile(self, esym, t, l, ratio, was_running):
        managed = self.state["managed"];m = managed.get(esym)
        # Position ownership is bound to its side and entry key. If an
        # operator/broker changes the direction or paper record in place,
        # never submit an order against an ambiguous live exposure.
        if m and l is not None and (l.side != m.get("side") or not math.isfinite(l.qty) or l.qty <= 0):
            self.state["paused"] = True
            raise X.ExchangeError(f"{esym}: managed exchange position drift; manual reconciliation required")
        if m and t is not None and m.get("key") == t.get("key") and t.get("side") != m.get("side"):
            self.state["paused"] = True
            raise X.ExchangeError(f"{esym}: PAPER side changed without new trade key; manual reconciliation required")
        if m and l is None:                               # closed on the exchange (stop hit / liquidated / manual)
            self.event("exchange_closed", symbol=esym, note="position no longer on the exchange (stop hit / liquidation / manual); not re-entered")
            self.state.setdefault("skipped", {})[m["key"]] = True;del managed[esym];m = None
        if t is None:
            if m and l is not None:
                self._close_verified(esym, l);self.event("close", symbol=esym, qty=l.qty, reason="paper exit");del managed[esym]
            return
        if m and m["key"] != t["key"] and l is not None:   # a different paper trade now: close the old one first
            self._close_verified(esym, l);self.event("close", symbol=esym, qty=l.qty, reason="paper trade replaced");del managed[esym];m = None;l = None
        if m is None:
            if l is not None:return                        # someone else's position on this symbol: never touch
            if self.state["paused"] or not self._fresh(t, t["first_seen"], was_running):return
            if len(managed) >= self.cfg["max_positions"]:self.event("skip", symbol=esym, reason="max_positions");return
            if self.state.get("skipped", {}).get(t["key"]):return
            px = self.ex.price(esym);q = t["ex_qty"] * ratio;q = min(q, self.cfg["max_position_usd"] / px);q = self._qty(esym, q)
            mk = self.ex.markets().get(esym, {})
            if not isinstance(mk, dict) or any(
                not isinstance(mk.get(field), (int, float))
                or isinstance(mk.get(field), bool)
                or not math.isfinite(mk[field]) or mk[field] <= 0
                for field in ("min_qty", "min_notional")
            ):
                self.state["paused"] = True
                raise X.ExchangeError(f"{esym}: exchange minimum order fields unavailable; entries paused")
            if q <= 0 or q * px < mk["min_notional"] or q < mk["min_qty"]:
                self.event("skip", symbol=esym, reason=f"size {q} below verified exchange minimum");self.state.setdefault("skipped", {})[t["key"]] = True;return
            stop = t["ex_stop"]
            if not self._entry_preflight(esym, t["side"], q, px, stop):
                self.state.setdefault("skipped", {})[t["key"]] = True   # not retried every cycle (no log flood)
                return
            observed = self._submit_entry(esym, t["side"], q, stop, t["key"])
            managed[esym] = dict(key=t["key"], bot=t["bot"], side=t["side"], paper_qty0=t["ex_qty"], live_qty0=observed.qty, stop=stop, opened=self.now())
            self.save()  # Save confirmed ownership while the uncertainty marker still exists.
            del self.state["pending_orders"][esym]
            self.save()
            self.state["errors"] = 0;self.event("open", symbol=esym, bot=t["bot"], side=t["side"], qty=q, price=px, stop=stop)
            return
        # managed & present: follow size and stop
        target_q = self._qty(esym, m["live_qty0"] * t["ex_qty"] / m["paper_qty0"]) if m["paper_qty0"] > 0 else l.qty
        step = self.ex.markets().get(esym, {}).get("step", 0) or 0
        if l.qty - target_q > max(step, l.qty * .02):
            if target_q <= 0:self._close_verified(esym, l);self.event("close", symbol=esym, qty=l.qty, reason="paper reduced to zero");del managed[esym];return
            self._close_verified(esym, l, l.qty - target_q);self.event("reduce", symbol=esym, qty=l.qty - target_q, reason="paper reduced (take-profit part)")
        elif target_q - l.qty > max(step, l.qty * .02) and not self.state["paused"]:
            add = self._qty(esym, min(target_q - l.qty, max(0., self.cfg["max_position_usd"] / self.ex.price(esym) - l.qty)))
            if add > 0:
                px = self.ex.price(esym)
                if self._entry_preflight(esym, l.side, add, px, t["ex_stop"]):
                    self._submit_entry(esym, l.side, add, t["ex_stop"], t["key"], before_qty=l.qty)
                    # Existing ownership is already durable; resolve pending only
                    # after the exchange has acknowledged the protected add.
                    self.save()
                    del self.state["pending_orders"][esym]
                    self.save()
                    self.event("add", symbol=esym, qty=add, reason="paper added (pyramid)")
        s = t["ex_stop"]
        if s > 0 and (m.get("stop") is None or abs(s - m["stop"]) / s > 5e-4):
            px = self.ex.price(esym)
            if (l.side == "long" and s < px) or (l.side == "short" and s > px):
                cur = self.ex.positions().get(esym, l)
                old_stop = m.get("stop")
                self._set_stop_verified(esym, cur, s, m)
                self.event("stop", symbol=esym, stop=s, previous=old_stop)

    def close_managed(self, reason: str):
        live = self.ex.positions()
        for esym in list(self.state["managed"]):
            if esym in live:
                try:self._close_verified(esym, live[esym]);self.event("close", symbol=esym, qty=live[esym].qty, reason=reason)
                except Exception as exc:
                    self.event("error", symbol=esym, error=str(exc)[:300])
                    break  # Do not execute more orders after an ambiguous close.
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
            if cfg["mode"] == "off":
                # Toggling OFF must end the old live session. A quick
                # re-enable cannot inherit a recent last_cycle and adopt an
                # already-open main PAPER position.
                mirror = None
                key = None
            else:
                if cfg["mode"] == "live" and os.getenv("PAPER_DATA_MODE", "demo") == "demo":
                    raise X.ExchangeError("Refusing real orders while PAPER_DATA_MODE is demo/synthetic")
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
    import fcntl
    folder().mkdir(parents=True, exist_ok=True)
    with (folder() / 'live_mirror.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit('Another live mirror owns this runtime; refusing duplicate process')
        run(once="--once" in sys.argv)
