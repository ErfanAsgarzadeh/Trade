"""TheTrueTrade live certification: one supervised end-to-end test with real money, before the Live mirror may trade.

Run it on the server, inside the live container (keys come from .env, nothing is typed into chat or command lines).
Detached, so a closed SSH window cannot interrupt it; every step is also written to runtime/ttt_certify_log.txt:

    docker compose run -d --name ttt-certify lbank-live python -u ttt_live_certify.py --confirm TEST
    docker logs -f ttt-certify          # Ctrl+C only stops watching; the test continues

Part A is read-only: API host and key, markets and prices of the bots' coins, free margin, open positions, mirror mode.
Part B needs the operator to type TEST and uses a tiny position (about 6-25 USDT notional, default leverage of the
mirror) on one coin:

  B1 open LONG at market with a stop-loss 3% below (escalating the order value only if the exchange rejects it as too small)
  B2 read the position back (id, side, size)
  B3 read the stop back: price, order type, stop order id, and the stop order among the active exchange orders
  B4 move the stop (PATCH tpsl) and read it back
  B5 close one quantity step and read back the rest (the stop must still protect it)
  B6 close the rest and read back that nothing is left
  B7 open again and move the stop very close to the price, then wait until the EXCHANGE closes the position by itself
     (proof that its stop really triggers); on timeout the position is closed and the check fails

Only if every check passes is runtime/ttt_live_certification.json written. The exchange adapter requires it (same API key,
same host, at most 30 days old) before the mirror may open live positions, reads the stop back in the way verified here,
and uses the accepted order value as the minimum order size. The output contains no keys, ids, balances or account data.
Any unexpected state stops the test, closes what the test opened and prints what to check by hand.
"""
from __future__ import annotations
import argparse, json, math, os, signal, sys, time, traceback
from decimal import Decimal, ROUND_CEILING

import exchanges as X
import live_mirror as LM

DEFAULT_SYMBOL = "DOGEUSDT"


class Abort(RuntimeError):
    pass


class Interrupted(BaseException):
    """SIGTERM/SIGHUP/Ctrl+C during the test: still close what the test opened."""


def log_line(text: str, path=None):
    path = path or (X.runtime_dir() / "ttt_certify_log.txt")
    try:
        with open(path, "a") as f:f.write(time.strftime("%Y-%m-%d %H:%M:%S ", time.gmtime()) + text + "\n")
    except OSError:
        pass


def say(text: str):
    print(text, flush=True);log_line(text)


def bot_symbols() -> list[str]:
    out = []
    for name in ("BOT_CONFIG", "C3_CONFIG", "PA_CONFIG"):
        try:
            with open(os.getenv(name, "")) as f:out += json.load(f).get("symbols", [])
        except (OSError, ValueError):
            pass
    return sorted({X.bot_to_exchange(s)[0] for s in out})


def ceil_step(x: float, step: float) -> float:
    d = Decimal(str(step))
    return float((Decimal(str(x)) / d).quantize(Decimal(1), rounding=ROUND_CEILING) * d)


class Certifier:
    def __init__(self, ex: X.TheTrueTrade, symbol: str, notional: float, max_notional: float, leverage: int,
                 trigger_timeout: float, say=print, ask=input, sleep=None, now=None):
        self.ex, self.symbol, self.notional, self.max_notional, self.leverage = ex, symbol, notional, max_notional, leverage
        self.trigger_timeout, self.say, self.ask = trigger_timeout, say, ask
        self.sleep, self.now = sleep or (lambda s: time.sleep(s)), now or (lambda: time.time())
        self.report = dict(version=X.CERT_VERSION, symbol=symbol, leverage=leverage, read_only={}, checks={}, notes=[])
        self.opened: list[str] = []          # position ids this test opened (closed again on any failure)

    # ---------------- helpers
    def ok(self, name: str, passed: bool, note: str = "", section: str = "checks"):
        self.report[section][name] = bool(passed)
        self.say(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f"  ({note})" if note else ""))
        if not passed:raise Abort(f"{name}: {note or 'failed'}")

    def mine(self) -> X.LivePosition | None:
        return self.ex.positions().get(self.symbol)

    def wait_position(self, want_qty: float | None, tries: int = 10) -> X.LivePosition | None:
        """Read positions until the expected size shows (the exchange may need a moment); None = flat."""
        step = self.ex.markets()[self.symbol]["step"];p = None
        for _ in range(tries):
            p = self.mine()
            if want_qty is None and p is None:return None
            if want_qty is not None and p is not None and abs(p.qty - want_qty) <= step * .05 + 1e-12:return p
            self.sleep(1.5)
        return p

    def stop_problems(self, pids, stop, readback) -> list[str]:
        problems = []
        for _ in range(8):
            problems = self.ex.check_stop(self.symbol, pids, stop, readback)
            if not problems:return []
            self.sleep(1.5)
        return problems

    # ---------------- part A: read-only
    def read_only(self, cfg: dict):
        self.say("Part A - read-only checks")
        self.ok("official_api_host", self.ex.base == "https://apiv2.thetruetrade.io", self.ex.base, "read_only")
        self.ok("api_key_present", bool(self.ex.key and self.ex.secret), "TTT_API_KEY / TTT_API_SECRET in .env", "read_only")
        self.ok("mirror_not_live", cfg["mode"] != "live", f"live mirror mode is {cfg['mode']}", "read_only")
        markets = self.ex.markets()
        m = markets.get(self.symbol) or {}
        self.ok("test_market_listed", isinstance(m, dict) and bool(m.get("step")) and bool(m.get("tick")), self.symbol, "read_only")
        self.ok("leverage_allowed", self.leverage <= int(m.get("max_leverage") or 0), f"{self.leverage}x of max {m.get('max_leverage')}x", "read_only")
        wanted = bot_symbols();missing = [s for s in wanted if s not in markets]
        self.report["bot_coins"] = len(wanted);self.report["bot_coins_missing_on_exchange"] = missing
        self.say(f"  [INFO] bot coins listed on TheTrueTrade: {len(wanted) - len(missing)}/{len(wanted)}" + (f"; missing {', '.join(missing)}" if missing else ""))
        self.price = self.ex.price(self.symbol)
        self.ok("price_available", math.isfinite(self.price) and self.price > 0, "", "read_only")
        eq = self.ex.equity();free = self.ex.available_balance()
        self.ok("account_readable", math.isfinite(eq) and eq >= 0 and math.isfinite(free), "futures equity and free margin readable", "read_only")
        need = self.max_notional / self.leverage * 3
        self.ok("free_margin_sufficient", free >= need, f"needs about {need:.2f} USDT free", "read_only")
        pos = self.ex.positions()
        self.ok("positions_readable", isinstance(pos, dict), f"{len(pos)} open position(s) on the account", "read_only")
        self.ok("test_coin_flat", self.symbol not in pos, f"no open {self.symbol} position before the test", "read_only")
        self.equity_before = eq

    # ---------------- part B: lifecycle
    def open_long(self, stop_pct: float) -> tuple[X.LivePosition, float, float]:
        m = self.ex.markets()[self.symbol];notional = self.notional;errors = []
        while notional <= self.max_notional + 1e-9:
            px = self.ex.price(self.symbol)
            qty = ceil_step(notional / px, m["step"]);stop = self.ex.round_price(self.symbol, px * (1 - stop_pct))
            try:
                pid = self.ex.open(self.symbol, "long", qty, self.leverage, stop)
            except X.ExchangeError as exc:
                text = str(exc)
                # The coin was flat before the test, so any position showing up now is the test's own: give the exchange a
                # moment, adopt it for cleanup, and stop (the entry reply could not be confirmed).
                for _ in range(1 if ("HTTP 400" in text or "HTTP 422" in text) else 6):
                    seen = self.mine()
                    if seen is not None:
                        self.opened += [str(i) for i in seen.ids]
                        raise Abort(f"entry reply not confirmed but a position was opened ({text[:200]})")
                    self.sleep(1.5)
                if "HTTP 400" not in text and "HTTP 422" not in text:raise Abort(f"entry failed: {text[:160]}")
                errors.append(text[:160]);self.say(f"  [INFO] order value {notional:.2f} USDT rejected: {text[:120]}")
                notional *= 2;continue
            self.opened.append(str(pid));self.last_notional = qty * px
            self.report["entry_resolution"] = getattr(self.ex, "entry_resolution", None) or "reply_position_id"
            p = self.wait_position(qty)
            self.report["rejected_smaller_orders"] = errors
            return p, qty, stop
        raise Abort(f"no order up to {self.max_notional} USDT was accepted: {errors[-1] if errors else ''}")

    def lifecycle(self):
        self.say("Part B - real position lifecycle")
        m = self.ex.markets()[self.symbol]
        p, qty, stop = self.open_long(.03)
        accepted = self.last_notional
        self.ok("entry_confirmed", p is not None and p.side == "long" and abs(p.qty - qty) <= m["step"] * .05 + 1e-12
                and any(str(i) in self.opened for i in p.ids), f"{qty} contracts, about {accepted:.2f} USDT")
        self.report["min_notional_usd"] = round(accepted * 1.02, 4)
        # B3: which query exposes the stop, and is the stop a real exchange order?
        readback = None;found = {}
        fields = {}
        for query in X.STOP_QUERIES:
            r = None
            for _ in range(6):
                try:
                    rows = {str(r.get("id")): r for r in self.ex.stop_rows(self.symbol, query)}
                except X.ExchangeError as exc:
                    fields[query] = f"error: {str(exc)[:120]}";break
                r = rows.get(self.opened[-1])
                fields[query] = sorted(k for k in r) if r is not None else "position id not in reply"
                if r is not None and X.dec(r.get("stopLoss")) is not None:break
                self.sleep(1.5)
            if r is not None and X.dec(r.get("stopLoss")) is not None:
                found = r;readback = dict(query=query, require_order_id=False, orders_check=False);break
        self.report["position_fields"] = fields
        self.say(f"  [INFO] position fields by query: {json.dumps(fields)}")
        self.ok("stop_readback", readback is not None, "stopLoss reported on the open position" if readback else "no endpoint reports the stop")
        oid = found.get("slOrderId")
        has_oid = not isinstance(oid, bool) and isinstance(oid, (int, str)) and bool(str(oid).strip())
        readback["require_order_id"] = has_oid
        if has_oid:
            try:
                orders = {str(o.get("id")) for o in self.ex.open_orders(self.symbol)}
                readback["orders_check"] = str(oid) in orders
            except X.ExchangeError as exc:
                self.report["notes"].append(f"active orders not readable: {str(exc)[:100]}")
        self.report["readback"] = readback
        self.say(f"  [INFO] stop read from positions?{readback['query']}; stop order id {'reported' if has_oid else 'NOT reported'}; "
                 f"stop order {'found' if readback['orders_check'] else 'not found'} among active orders")
        problems = self.stop_problems(p.ids, stop, readback)
        self.ok("stop_matches_request", not problems, "; ".join(problems))
        # B4 move the stop
        new_stop = self.ex.round_price(self.symbol, self.ex.price(self.symbol) * .98)
        self.ex.set_stop(p, new_stop)
        problems = self.stop_problems(p.ids, new_stop, readback)
        self.ok("stop_moved", not problems, "; ".join(problems))
        # B5 partial close: the smallest possible part (one step), so the rest stays above any exchange minimum. A partial
        # close whose remainder is too small can be turned into a full close by the exchange; the mirror accepts that.
        part = m["step"]
        if qty - part >= m["step"]:
            self.ex.close(p, part)
            rest = self.wait_position(qty - part)
            left = rest.qty if rest else 0
            good = rest is not None and abs(left - (qty - part)) <= m["step"] * .05 + 1e-12
            self.ok("partial_close", good, f"{part} of {qty} closed, {left} left")
            problems = self.stop_problems(rest.ids, new_stop, readback)
            self.ok("stop_kept_after_partial", not problems, "; ".join(problems))
        else:
            self.ok("partial_close", False, "position too small to close one step; raise --notional")
        # B6 full close
        self.ex.close(self.mine())
        self.ok("full_close", self.wait_position(None) is None, "position gone")
        if readback["orders_check"]:
            left = {str(o.get("id")) for o in self.ex.open_orders(self.symbol)}
            self.ok("stop_order_removed_after_close", str(oid) not in left, "")
        # B7 the exchange itself triggers the stop
        p, qty, _ = self.open_long(.03)
        self.ok("second_entry_confirmed", p is not None and abs(p.qty - qty) <= m["step"] * .05 + 1e-12, "")
        tight_pct = .0015
        for attempt in range(3):
            tight = self.ex.round_price(self.symbol, self.ex.price(self.symbol) * (1 - tight_pct))
            try:
                self.ex.set_stop(p, tight);break
            except X.ExchangeError as exc:
                self.say(f"  [INFO] stop {tight_pct:.2%} below rejected ({str(exc)[:100]}); trying wider")
                tight_pct *= 2
        else:
            raise Abort("exchange rejected every close stop")
        problems = self.stop_problems(p.ids, tight, readback)
        self.ok("tight_stop_set", not problems, f"{tight_pct:.2%} below price; " + "; ".join(problems))
        self.say(f"  waiting up to {self.trigger_timeout / 60:.0f} min for the exchange to trigger the stop ...")
        start = self.now();triggered = False
        while self.now() - start < self.trigger_timeout:
            self.sleep(5)
            if self.mine() is None:
                triggered = True;break
        self.report["trigger_wait_s"] = round(self.now() - start)
        if triggered:
            self.opened.pop()          # the exchange closed it; nothing left to clean up
            reason = None
            try:
                rows = {str(r.get("id")): r for r in self.ex.stop_rows(self.symbol, "page")}
                reason = (rows.get(str(p.ids[0])) or {}).get("closingReason")
            except X.ExchangeError:
                pass
            self.report["trigger_closing_reason"] = reason if isinstance(reason, str) else None
        self.ok("stop_triggered", triggered, "closed by the exchange stop" if triggered else "price did not reach the stop in time; run again")

    def cleanup(self):
        """Close whatever this test opened; report anything that could not be confirmed flat."""
        try:
            p = self.mine()
            if p is None and self.opened:   # the exchange may show the position a moment late
                for _ in range(5):
                    self.sleep(1.5);p = self.mine()
                    if p is not None:break
            # The test coin was verified flat before the test and the mirror is not live: whatever is open on it now is ours.
            if p is not None and (self.opened or self.report["read_only"].get("test_coin_flat")):
                self.ex.close(p)
                if self.wait_position(None) is not None:
                    self.say(f"  !! {self.symbol} test position could NOT be confirmed closed - close it by hand in TheTrueTrade")
                    return False
                self.say(f"  test position on {self.symbol} closed")
        except Exception as exc:
            self.say(f"  !! cleanup failed ({type(exc).__name__}: {str(exc)[:120]}) - check {self.symbol} in TheTrueTrade by hand")
            return False
        return True

    def run(self, cfg: dict) -> dict:
        try:
            self.read_only(cfg)
        except Exception as exc:
            self.report.update(passed=False, stopped_at="part A", reason=str(exc)[:200]);return self.report
        est = self.notional / self.leverage
        self.say(f"\nPart B places REAL orders on {self.symbol}: about {self.notional:.0f} USDT notional (margin about {est:.2f} USDT at "
                 f"{self.leverage}x), two short positions, expected cost below 1 USDT (fees and a 0.15-3% stop).")
        if self.ask("Type TEST to continue: ").strip() != "TEST":
            self.report.update(passed=False, stopped_at="confirmation", reason="not confirmed; no order sent");return self.report
        try:
            self.lifecycle()
            self.report["passed"] = True
        except (Exception, Interrupted, KeyboardInterrupt) as exc:
            if not isinstance(exc, (Abort, X.ExchangeError)):
                log_line("unexpected error:\n" + traceback.format_exc())
                exc = f"{type(exc).__name__}: {exc}"
            self.say(f"  stopped: {str(exc)[:200]}")
            self.report.update(passed=False, stopped_at="part B", reason=str(exc)[:200])
            self.report["cleanup_confirmed"] = self.cleanup()
            return self.report
        try:
            eq = self.ex.equity();self.report["test_cost_usdt"] = round(self.equity_before - eq, 4)
        except X.ExchangeError:
            pass
        return self.report


def write_certificate(ex: X.TheTrueTrade, report: dict, now: float | None = None) -> dict:
    cert = dict(version=X.CERT_VERSION, passed=True, created_at=time.time() if now is None else now, base=ex.base,
                key_fingerprint=X.key_fingerprint(ex.key), symbol=report["symbol"], leverage=report["leverage"],
                min_notional_usd=report["min_notional_usd"], readback=report["readback"],
                checks={k: report["checks"].get(k) is True for k in X.CERT_REQUIRED_CHECKS},
                trigger_closing_reason=report.get("trigger_closing_reason"))
    path = X.runtime_dir() / X.CERT_NAME;tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cert, indent=1));os.chmod(tmp, 0o600);tmp.replace(path)
    return cert


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TheTrueTrade live certification (real tiny orders after typing TEST)")
    ap.add_argument("--symbol", default=DEFAULT_SYMBOL, help="exchange symbol of the test coin (default DOGEUSDT)")
    ap.add_argument("--notional", type=float, default=6.0, help="first order value tried, USDT (default 6)")
    ap.add_argument("--max-notional", type=float, default=25.0, help="largest order value tried, USDT (default 25)")
    ap.add_argument("--trigger-minutes", type=float, default=20.0, help="how long to wait for the exchange to trigger the stop")
    ap.add_argument("--confirm", default=None, help="TEST = confirm the real orders up front (for a detached run)")
    a = ap.parse_args(argv)
    def stop(signum, frame):
        raise Interrupted(f"signal {signum}")
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    log_line("---- certification run started")
    cfg = LM.read_config()
    ex = X.TheTrueTrade()
    ask = (lambda prompt: (say(prompt + a.confirm) or a.confirm)) if a.confirm is not None else input
    c = Certifier(ex, a.symbol.upper(), a.notional, a.max_notional, int(cfg["leverage"]), a.trigger_minutes * 60, say=say, ask=ask)
    report = c.run(cfg)
    if report.get("passed"):
        cert = write_certificate(ex, report)
        say(f"\nCERTIFIED: live entries on TheTrueTrade are allowed for this API key until "
              f"{time.strftime('%Y-%m-%d', time.gmtime(cert['created_at'] + X.CERT_MAX_AGE_DAYS * 86400))}; "
              f"minimum order value {cert['min_notional_usd']} USDT.")
    else:
        say(f"\nNOT CERTIFIED ({report.get('stopped_at')}): {report.get('reason')}")
    say(json.dumps({k: v for k, v in report.items()}, indent=1))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
