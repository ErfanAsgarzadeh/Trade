"""TheTrueTrade live certification, certificate-gated stop readback and a full live mirror cycle, against a simulated
TheTrueTrade REST API (request level: the real adapter code builds and parses every call)."""
import json
import pytest
import exchanges as X
import live_mirror as L
import ttt_live_certify as T


class FakeAPI:
    """In-memory TheTrueTrade: markets, stats, assets, positions (active / page views), orders, open/close/tpsl.
    Stops are real orders here: when the price crosses a position's stopLoss the position is closed by the 'exchange'."""

    def __init__(self, min_notional=5.0, store_stop=True, order_ids=True, list_orders=True, trigger=True, reply=None,
                 fill_records=None):
        self.px = {"DOGEUSDT": 0.2, "BTCUSDT": 80000.0}
        self.markets = [dict(symbol="DOGEUSDT", stepSize="1", tickSize="0.00001", maxLeverage=50, isActive=True),
                        dict(symbol="BTCUSDT", stepSize="0.001", tickSize="0.1", maxLeverage=100, isActive=True)]
        self.pos = {};self.history = {};self.orders = {};self.next_id = 1000
        self.min_notional, self.store_stop, self.order_ids, self.list_orders, self.trigger = min_notional, store_stop, order_ids, list_orders, trigger
        self.calls = [];self.equity = 100.0;self.reply = reply or (lambda pid: {"positionId": pid})
        self.fill_records = fill_records;self.fills = {};self.dust = False

    def _id(self):
        self.next_id += 1;return str(self.next_id)

    def move(self, symbol, factor):
        self.px[symbol] *= factor;self._fire()

    def _fire(self):
        if not self.trigger:return
        for pid, p in list(self.pos.items()):
            sl = p.get("stopLoss")
            if sl is None:continue
            px = self.px[p["symbol"]]
            if (p["side"] == "LONG" and px <= float(sl)) or (p["side"] == "SHORT" and px >= float(sl)):
                self._close(pid, None, "STOP_LOSS")

    def _close(self, pid, size, reason="USER"):
        p = self.pos[pid]
        rest_value = (float(p["size"]) - float(size or 0)) * self.px[p["symbol"]]
        if size is None or float(size) >= float(p["size"]) - 1e-12 or (self.dust and rest_value < self.min_notional):
            del self.pos[pid];self.orders.pop(p.get("slOrderId"), None)
            self.history[pid] = dict(p, status="CLOSED", isActive=False, closingReason=reason)
        else:
            p["size"] = str(float(p["size"]) - float(size))

    def _view(self, p):
        v = dict(p)
        if not self.store_stop:v.pop("stopLoss", None)
        if not self.order_ids:v.pop("slOrderId", None)
        return v

    def request(self, method, path, query=None, body=None, auth=True):
        self.calls.append((method, path, dict(query or {}), body))
        if method == "GET" and path == "/futures/markets":return {"items": self.markets}
        if method == "GET" and path == "/futures/markets/stats":
            return [dict(symbol=s, markPrice=str(v), lastPrice=str(v)) for s, v in self.px.items()]
        if method == "GET" and path == "/futures/assets":return {"summary": dict(totalAssets=str(self.equity), availableBalance=str(self.equity))}
        if method == "GET" and path == "/futures/positions":
            self._fire();q = query or {};sym = q.get("symbol")
            rows = [self._view(p) for p in self.pos.values() if sym in (None, p["symbol"])]
            if q.get("page"):rows = rows + [self._view(h) for h in self.history.values() if sym in (None, h["symbol"])]
            return {"items": rows, "meta": {"total": len(rows), "hasNextPage": False}}
        if method == "GET" and path == "/futures/orders":
            if not self.list_orders:return {"items": []}
            sym = (query or {}).get("symbol")
            rows = [o for o in self.orders.values() if sym in (None, o["symbol"])]
            if not (query or {}).get("active"):rows += [o for o in self.fills.values() if sym in (None, o["symbol"])]
            return {"items": rows}
        if method == "POST" and path == "/futures/positions":
            notional = float(body["size"]) * self.px[body["symbol"]]
            if notional < self.min_notional:raise X.ExchangeError("TheTrueTrade POST /futures/positions: HTTP 400 [{'message': 'Order value too small'}]")
            pid = self._id();p = dict(id=int(pid), symbol=body["symbol"], side=body["side"], status="OPEN", isActive=True,
                                      size=body["size"], leverage=body["leverage"], entryPrice=str(self.px[body["symbol"]]))
            self._set_sl(p, body)
            self.pos[pid] = p;oid = int(self._id())
            if self.fill_records is not None:
                self.fills[oid] = dict(id=oid, symbol=body["symbol"], type="MARKET", status="FILLED",
                                       **({"positionId": int(pid)} if self.fill_records == "with_position" else {}))
            return self.reply(pid) if self.reply.__code__.co_argcount == 1 else self.reply(pid, oid)
        if method == "POST" and path.endswith("/close") and path.startswith("/futures/positions/"):
            pid = path.split("/")[3];self._close(pid, (body or {}).get("size"));return {}
        if method == "PATCH" and path.endswith("/tpsl"):
            pid = path.split("/")[3];p = self.pos[pid];px = self.px[p["symbol"]];sl = float(body["stopLoss"])
            if (p["side"] == "LONG" and sl >= px) or (p["side"] == "SHORT" and sl <= px):
                raise X.ExchangeError("TheTrueTrade PATCH tpsl: HTTP 400 stop on the wrong side of the price")
            self.orders.pop(p.get("slOrderId"), None);self._set_sl(p, body);return {}
        if method == "POST" and path == "/futures/positions/close-all":
            for pid in list(self.pos):self._close(pid, None)
            return {}
        raise AssertionError(f"unexpected call {method} {path}")

    def _set_sl(self, p, body):
        if body.get("stopLoss") is None:return
        oid = "sl" + self._id()
        p.update(stopLoss=body["stopLoss"], stopLossOrderType=body.get("stopLossOrderType"), stopLossStrategy=body.get("stopLossStrategy"), slOrderId=oid)
        self.orders[oid] = dict(id=oid, symbol=p["symbol"], type="STOP_MARKET", status="NEW", triggerPrice=body["stopLoss"])


def adapter(api, key="key-1"):
    t = X.TheTrueTrade(key, "secret")
    t.request = api.request
    return t


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.setenv("RISK_DIR", str(tmp_path))
    for name, f in (("BOT_CONFIG", "config.json"), ("C3_CONFIG", "c3_config.json"), ("PA_CONFIG", "pa_config.json")):
        monkeypatch.setenv(name, str(__import__("pathlib").Path(__file__).parents[1] / f))
    return tmp_path


def certifier(api, ex, answer="TEST", timeout=600, notional=6.0, drop=True):
    clock = [0.0];out = []
    def sleep(s):
        clock[0] += s
        if drop:api.move("DOGEUSDT", 0.9995)      # the market drifts down: a tight long stop is reached within minutes
    c = T.Certifier(ex, "DOGEUSDT", notional, 25.0, 5, timeout, say=out.append, ask=lambda _: answer, sleep=sleep, now=lambda: clock[0])
    return c, out


def test_full_certification_writes_a_bound_certificate_and_unlocks_entries(rt):
    api = FakeAPI();ex = adapter(api)
    c, out = certifier(api, ex)
    report = c.run(L.validate({"mode": "off"}))
    assert report["passed"], (report, out)
    assert all(report["checks"][k] for k in X.CERT_REQUIRED_CHECKS)
    assert report["readback"] == dict(query="active", require_order_id=True, orders_check=True)
    assert not api.pos                                         # nothing left open on the account
    assert report["bot_coins"] == 35
    cert = T.write_certificate(ex, report)
    assert (rt / X.CERT_NAME).stat().st_mode & 0o777 == 0o600
    raw = (rt / X.CERT_NAME).read_text();assert "key-1" not in raw and "secret" not in raw
    fresh = adapter(api)
    fresh.ensure_protected_entries()                           # unlocked
    mk = fresh.markets()["DOGEUSDT"];assert mk["min_qty"] == 1.0 and mk["min_notional"] == pytest.approx(cert["min_notional_usd"])
    assert 6.0 <= cert["min_notional_usd"] <= 6.5
    with pytest.raises(X.ExchangeError, match="another API key"):adapter(api, key="other-key").ensure_protected_entries()
    with pytest.raises(X.ExchangeError, match="expired"):fresh.load_certification(now=cert["created_at"] + 31 * 86400)
    bad = dict(cert, checks=dict(cert["checks"], stop_triggered=False));(rt / X.CERT_NAME).write_text(json.dumps(bad))
    with pytest.raises(X.ExchangeError, match="did not pass"):fresh.ensure_protected_entries()


def test_too_small_orders_escalate_and_the_accepted_value_becomes_the_minimum(rt):
    api = FakeAPI(min_notional=10.0);ex = adapter(api)
    c, out = certifier(api, ex)
    report = c.run(L.validate({"mode": "off"}))
    assert report["passed"] and len(report["rejected_smaller_orders"]) == 1
    assert 12.0 <= report["min_notional_usd"] <= 13.0


@pytest.mark.parametrize("fault,check", [
    (dict(store_stop=False), "stop_readback"),                 # exchange does not report the stop at all
    (dict(trigger=False), "stop_triggered"),                   # stop stored but never executed
])
def test_failed_checks_leave_no_certificate_and_close_the_test_position(rt, fault, check):
    api = FakeAPI(**fault);ex = adapter(api)
    c, out = certifier(api, ex, timeout=300)
    report = c.run(L.validate({"mode": "off"}))
    assert not report["passed"] and report["reason"].startswith(check) and report["cleanup_confirmed"]
    assert not api.pos and not (rt / X.CERT_NAME).exists()
    with pytest.raises(X.ExchangeError, match="stop-loss readback has not been validated"):adapter(api).ensure_protected_entries()


def test_without_order_ids_the_certificate_records_the_weaker_readback(rt):
    api = FakeAPI(order_ids=False);ex = adapter(api)
    c, _ = certifier(api, ex)
    report = c.run(L.validate({"mode": "off"}))
    assert report["passed"] and report["readback"] == dict(query="active", require_order_id=False, orders_check=False)


def test_no_order_without_typed_confirmation_or_with_live_mirror_on(rt):
    api = FakeAPI();ex = adapter(api)
    c, _ = certifier(api, ex, answer="yes")
    report = c.run(L.validate({"mode": "off"}))
    assert not report["passed"] and report["stopped_at"] == "confirmation"
    assert not [x for x in api.calls if x[0] != "GET"]
    c, _ = certifier(api, ex)
    report = c.run(L.validate({"mode": "live"}))
    assert report["stopped_at"] == "part A" and not [x for x in api.calls if x[0] != "GET"]


def test_existing_position_on_the_test_coin_stops_before_any_order(rt):
    api = FakeAPI();ex = adapter(api)
    api.pos["1"] = dict(id=1, symbol="DOGEUSDT", side="SHORT", status="OPEN", isActive=True, size="100", entryPrice="0.2")
    c, _ = certifier(api, ex)
    report = c.run(L.validate({"mode": "off"}))
    assert report["stopped_at"] == "part A" and "test_coin_flat" in report["reason"]
    assert not [x for x in api.calls if x[0] != "GET"] and "1" in api.pos


def certify(rt, api):
    ex = adapter(api);c, _ = certifier(api, ex)
    report = c.run(L.validate({"mode": "off"}));assert report["passed"]
    T.write_certificate(ex, report);return report


def test_verify_stop_detects_a_missing_or_wrong_exchange_stop(rt):
    api = FakeAPI();certify(rt, api)
    t = adapter(api)
    pid = t.open("BTCUSDT", "long", 0.001, 5, 78000.03)        # rounded to the 0.1 tick before sending
    body = [x for x in api.calls if x[0] == "POST" and x[1] == "/futures/positions"][-1][3]
    assert body["stopLoss"] == "78000"
    p = t.positions()["BTCUSDT"];t.verify_stop(p, 78000.0)
    with pytest.raises(X.ExchangeError, match="differs"):t.verify_stop(p, 77000.0)
    api.orders.clear()                                         # stop order vanished on the exchange
    with pytest.raises(X.ExchangeError, match="not among active"):t.verify_stop(p, 78000.0)
    api.pos[pid].pop("stopLoss")
    with pytest.raises(X.ExchangeError, match="no stopLoss"):t.verify_stop(p, 78000.0)


class Book:
    def __init__(self):self.book = {}
    def positions(self):return {k: dict(v) for k, v in self.book.items()}
    def equity(self):return 10000.0


def test_live_mirror_full_cycle_on_certified_thetruetrade(rt):
    api = FakeAPI();certify(rt, api);api.equity = 1000.0
    t = adapter(api);paper = Book();clock = [5_000_000.0]
    m = L.Mirror(t, paper, L.validate({"mode": "live", "exchange": "thetruetrade"}), now=lambda: clock[0])
    def step():clock[0] += 10;m.cycle()
    step()
    paper.book["BTC/USDT:USDT"] = dict(bot="main", side="long", qty=0.05, stop=78000.0, key="main|BTC|1", opened=None)
    step()
    live = t.positions()["BTCUSDT"];assert live.qty == pytest.approx(0.005)       # 0.05 x 1000 / 10000
    assert m.state["managed"]["BTCUSDT"]["stop"] == 78000.0 and not m.state["pending_orders"]
    paper.book["BTC/USDT:USDT"]["stop"] = 79000.0;step()                          # trailing stop copied and read back
    assert float(next(iter(api.pos.values()))["stopLoss"]) == 79000.0 and m.state["managed"]["BTCUSDT"]["stop"] == 79000.0
    paper.book["BTC/USDT:USDT"]["qty"] = 0.025;step()                             # partial exit
    assert t.positions()["BTCUSDT"].qty == pytest.approx(0.002)   # 0.0025 floored to the 0.001 step
    del paper.book["BTC/USDT:USDT"];step()                                        # paper exit
    assert "BTCUSDT" not in t.positions() and not m.state["managed"] and not m.state["paused"]
    paper.book["BTC/USDT:USDT"] = dict(bot="main", side="short", qty=0.0001, stop=82000.0, key="main|BTC|2", opened=None)
    step()                                                                        # below the certified minimum: skipped
    assert "BTCUSDT" not in t.positions()
    kinds = [json.loads(x)["kind"] for x in (rt / "live_log.jsonl").read_text().splitlines()]
    assert kinds.count("open") == 1 and "stop" in kinds and "reduce" in kinds and "close" in kinds and "order_uncertain" not in kinds


def test_live_mirror_pauses_when_the_exchange_drops_the_stop(rt):
    api = FakeAPI();certify(rt, api);api.equity = 1000.0
    api.store_stop = False                                     # after certification the exchange stops reporting stops
    t = adapter(api);paper = Book();clock = [5_000_000.0]
    m = L.Mirror(t, paper, L.validate({"mode": "live", "exchange": "thetruetrade"}), now=lambda: clock[0])
    clock[0] += 10;m.cycle()
    paper.book["BTC/USDT:USDT"] = dict(bot="main", side="long", qty=0.05, stop=78000.0, key="main|BTC|1", opened=None)
    clock[0] += 10;m.cycle()
    assert m.state["paused"] and m.state["pending_orders"]     # unverified stop: no further orders until reviewed


def test_dashboard_unlocks_live_only_with_a_valid_certificate(rt, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from dashboard_server import create_app
    import lbank_bot as lb
    from test_system import FakeData
    monkeypatch.setenv("BOT_PIN", "test-pin-0123456789")
    monkeypatch.setenv("TTT_API_KEY", "key-1");monkeypatch.setenv("TTT_API_SECRET", "secret")
    cfgstore = lb.ConfigStore(tmp_path / "config.json")
    cfgstore.write(json.loads((__import__("pathlib").Path(__file__).parents[1] / "config.json").read_text()))
    engine = lb.Engine(cfgstore, lb.Database(tmp_path / "d.db"), FakeData(), paper_equity=10000)
    H = {"X-Bot-Pin": "test-pin-0123456789"}
    with TestClient(create_app(engine)) as c:
        r = c.put("/api/live/config", headers=H, json={"mode": "live", "confirm": "LIVE"})
        assert r.status_code == 409 and "no TheTrueTrade live certification" in r.json()["detail"]
        assert c.get("/api/live", headers=H).json()["certification"]["valid"] is False
        api = FakeAPI();report = certify(rt, api)
        assert c.get("/api/live", headers=H).json()["certification"]["valid"] is True
        r = c.put("/api/live/config", headers=H, json={"mode": "live", "exchange": "binance", "confirm": "LIVE"})
        assert r.status_code == 409
        r = c.put("/api/live/config", headers=H, json={"mode": "live", "exchange": "thetruetrade", "size_factor": 0.1, "confirm": "LIVE"})
        assert r.status_code == 200 and r.json()["mode"] == "live"


def test_mirror_waits_for_a_position_that_shows_up_a_moment_after_the_fill(rt):
    api = FakeAPI();certify(rt, api);api.equity = 1000.0
    real = api.request;lag = {"n": 0}
    def slow(method, path, query=None, body=None, auth=True):
        if method == "POST" and path == "/futures/positions":lag["n"] = 2
        if method == "GET" and path == "/futures/positions" and lag["n"] > 0:
            lag["n"] -= 1;return {"items": [], "meta": {"total": 0}}
        return real(method, path, query, body, auth)
    api.request = slow
    t = adapter(api);paper = Book();clock = [5_000_000.0]
    m = L.Mirror(t, paper, L.validate({"mode": "live", "exchange": "thetruetrade"}), now=lambda: clock[0])
    clock[0] += 10;m.cycle()
    paper.book["BTC/USDT:USDT"] = dict(bot="main", side="long", qty=0.05, stop=78000.0, key="main|BTC|1", opened=None)
    clock[0] += 10;m.cycle()
    assert "BTCUSDT" in m.state["managed"] and not m.state["paused"] and not m.state["pending_orders"]


def live_mirror(rt, api, **cfg):
    t = adapter(api);paper = Book();clock = [5_000_000.0]
    m = L.Mirror(t, paper, L.validate({"mode": "live", "exchange": "thetruetrade", **cfg}), now=lambda: clock[0])
    def step():clock[0] += 10;m.cycle()
    step();return m, t, paper, step


def kinds_and_reasons(rt):
    rows = [json.loads(x) for x in (rt / "live_log.jsonl").read_text().splitlines()]
    return [(r["kind"], r.get("reason", "")) for r in rows]


def test_live_risk_limits_skip_entries_without_pausing_the_mirror(rt):
    api = FakeAPI();certify(rt, api);api.equity = 1000.0
    m, t, paper, step = live_mirror(rt, api, risk_per_trade_pct=0.005, max_total_open_risk_pct=0.10)
    paper.book["BTC/USDT:USDT"] = dict(bot="main", side="long", qty=0.05, stop=78000.0, key="main|BTC|1", opened=None)
    step()                                                     # risk about 10.8 USDT > 0.5% of 1000: skipped
    assert "BTCUSDT" not in t.positions() and not m.state["paused"] and m.state["errors"] == 0
    assert ("skip", "Live per-trade risk limit exceeded") in kinds_and_reasons(rt)
    step();assert sum(k == "skip" for k, _ in kinds_and_reasons(rt)) == 1   # not retried every 10 s


def test_live_risk_daily_loss_and_foreign_positions_block_new_entries(rt):
    api = FakeAPI();certify(rt, api);api.equity = 1000.0
    m, t, paper, step = live_mirror(rt, api)
    paper.book["BTC/USDT:USDT"] = dict(bot="main", side="long", qty=0.05, stop=78000.0, key="main|BTC|1", opened=None)
    step();assert "BTCUSDT" in t.positions()                    # baseline 1000 recorded
    api.equity = 940.0                                         # -6% today (default limit 5%)
    paper.book["ETH/USDT:USDT"] = dict(bot="c3", side="long", qty=1.0, stop=1900.0, key="c3|ETH|1", opened=None)
    api.px["ETHUSDT"] = 2000.0;api.markets.append(dict(symbol="ETHUSDT", stepSize="0.01", tickSize="0.01", maxLeverage=100, isActive=True))
    t._markets = None;step()
    assert "ETHUSDT" not in t.positions() and any("daily loss" in r for _, r in kinds_and_reasons(rt))
    assert m.state["risk_ledger"]["day_equity"] == 1000.0 and not m.state["paused"]
    api.pos["9"] = dict(id=9, symbol="DOGEUSDT", side="LONG", status="OPEN", isActive=True, size="100", entryPrice="0.2")
    api.equity = 1000.0
    paper.book["ETH/USDT:USDT"]["key"] = "c3|ETH|2";step()      # someone else's position on the account
    assert "ETHUSDT" not in t.positions() and any("not opened by the mirror" in r for _, r in kinds_and_reasons(rt))
    assert "9" in api.pos                                      # never touched


def test_live_config_validates_risk_fractions():
    v = L.validate({})
    assert v["risk_per_trade_pct"] == 0.03 and v["max_daily_loss_pct"] == 0.05
    for bad in ({"max_daily_loss_pct": 0}, {"max_drawdown_pct": 1.5}, {"risk_per_trade_pct": True},
                {"risk_per_trade_pct": 0.2, "max_total_open_risk_pct": 0.1}, {"leverage": 5.0}, {"size_factor": float("nan")}):
        with pytest.raises(ValueError):L.validate(bad)
    with pytest.raises(ValueError):L.validate([])


def test_any_unexpected_error_or_signal_still_closes_the_test_position(rt):
    api = FakeAPI();ex = adapter(api)
    real = ex.check_stop
    def boom(*a, **k):raise ValueError("unexpected reply")
    ex.check_stop = boom                                       # fails right after the first entry
    c, out = certifier(api, ex)
    report = c.run(L.validate({"mode": "off"}))
    assert not report["passed"] and "ValueError" in report["reason"] and report["cleanup_confirmed"] and not api.pos
    ex.check_stop = real
    def interrupted(*a, **k):raise T.Interrupted("signal 1")   # SSH window closed while waiting
    c, out = certifier(api, ex)
    c.sleep = interrupted
    report = c.run(L.validate({"mode": "off"}))
    assert not report["passed"] and report["cleanup_confirmed"] and not api.pos


def test_detached_run_confirms_up_front_and_logs_every_step(rt, monkeypatch):
    api = FakeAPI()
    made = adapter(api)
    monkeypatch.setattr(T.X, "TheTrueTrade", lambda: made)
    clock = [1_800_000_000.0]
    def sleep(s):clock[0] += s;api.move("DOGEUSDT", 0.9995)
    monkeypatch.setattr(T.time, "sleep", sleep);monkeypatch.setattr(T.time, "time", lambda: clock[0])
    assert T.main(["--confirm", "TEST", "--trigger-minutes", "0.5"]) == 0
    log = (rt / "ttt_certify_log.txt").read_text()
    assert "Type TEST to continue: TEST" in log and "[PASS] stop_triggered" in log and "CERTIFIED" in log
    assert "position fields by query" in log and (rt / X.CERT_NAME).exists() and not api.pos



def test_wrapped_entry_reply_is_accepted(rt):
    api = FakeAPI(reply=lambda pid: {"data": {"id": int(pid), "status": "OPEN"}})
    c, _ = certifier(api, adapter(api))
    assert c.run(L.validate({"mode": "off"}))["passed"]


def test_entry_reply_without_id_closes_the_position_it_opened(rt):
    api = FakeAPI(reply=lambda pid: {"success": True, "message": "ok"})
    c, out = certifier(api, adapter(api))
    report = c.run(L.validate({"mode": "off"}))
    assert not report["passed"] and "a position was opened" in report["reason"]
    assert "reply shape: {success: bool, message: str}" in report["reason"]          # key names only, no values
    assert report["cleanup_confirmed"] and not api.pos



@pytest.mark.parametrize("records,how", [("with_position", "order_record"), ("plain", "new_position"), (None, "new_position")])
def test_order_id_reply_is_resolved_to_the_new_position(rt, records, how):
    """The live gateway answers {orderId}: the position comes from the order record, else from the new position id."""
    api = FakeAPI(reply=lambda pid, oid: {"orderId": oid}, fill_records=records)
    c, out = certifier(api, adapter(api))
    report = c.run(L.validate({"mode": "off"}))
    assert report["passed"], (report, out)
    assert report["entry_resolution"] == how and not api.pos


def test_mirror_live_cycle_with_order_id_replies(rt):
    api = FakeAPI(reply=lambda pid, oid: {"orderId": oid});certify(rt, api);api.equity = 1000.0
    m, t, paper, step = live_mirror(rt, api)
    paper.book["BTC/USDT:USDT"] = dict(bot="main", side="long", qty=0.05, stop=78000.0, key="main|BTC|1", opened=None)
    step();assert "BTCUSDT" in m.state["managed"] and not m.state["paused"]
    del paper.book["BTC/USDT:USDT"];step()
    assert not api.pos and not m.state["managed"] and not m.state["paused"]


def test_netted_entry_resolves_to_the_grown_position(rt):
    api = FakeAPI(reply=lambda pid, oid: {"orderId": oid});certify(rt, api)
    t = adapter(api)
    first = t.open("BTCUSDT", "long", 0.002, 5, 78000.0)
    real = api.request
    def netting(method, path, query=None, body=None, auth=True):   # an exchange that adds to the existing position
        if method == "POST" and path == "/futures/positions" and api.pos:
            p = next(iter(api.pos.values()));p["size"] = str(float(p["size"]) + float(body["size"]))
            return {"orderId": 999}
        return real(method, path, query, body, auth)
    api.request = netting;t.request = netting
    assert t.open("BTCUSDT", "long", 0.001, 5, 78000.0) == first and t.entry_resolution == "netted_position"



def test_exchange_that_closes_a_too_small_remainder_still_certifies_and_the_mirror_accepts_it(rt):
    """Like the real exchange: a partial close leaving less than the minimum closes everything."""
    api = FakeAPI();api.dust = True
    report = certify(rt, api);assert report["checks"]["partial_close"]
    api.equity = 1000.0
    m, t, paper, step = live_mirror(rt, api)
    paper.book["BTC/USDT:USDT"] = dict(bot="main", side="long", qty=0.04, stop=78000.0, key="main|BTC|1", opened=None)
    step();assert t.positions()["BTCUSDT"].qty == pytest.approx(0.004)      # 320 USDT live
    api.min_notional = 100.0                                   # the exchange minimum is above the 80 USDT remainder
    paper.book["BTC/USDT:USDT"]["qty"] = 0.01;step()           # reduce to a quarter: 80 USDT left, the exchange closes all
    assert "BTCUSDT" not in t.positions() and not m.state["paused"] and not m.state["pending_orders"]
    kinds = [k for k, _ in kinds_and_reasons(rt)]
    assert "closed_in_full" in kinds and "order_uncertain" not in kinds
