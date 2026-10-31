"""Exchange adapters for the live mirror (live_mirror.py). One small interface, three implementations:

  thetruetrade  TheTrueTrade USDT-M perpetuals, signed REST (docs: thetruetrade.io/profile/api-management/guide)
  binance       Binance USDT-M futures through CCXT (binanceusdm); optional testnet
  sim           in-memory simulated exchange (dry runs and tests) - never touches the network

All quantities given to / returned by an adapter are in the EXCHANGE's units (contracts of e.g. 1000SHIBUSDT);
live_mirror.py converts the bots' symbols and units with SYMBOLS below. API keys come only from environment variables
(.env on the server): TTT_API_KEY / TTT_API_SECRET, BINANCE_API_KEY / BINANCE_API_SECRET. Use keys WITHOUT withdrawal
permission, restricted to the server's IP.
"""
from __future__ import annotations
import hashlib, hmac, json, math, os, time, urllib.error, urllib.parse, urllib.request
from dataclasses import dataclass, field


@dataclass
class LivePosition:
    symbol: str            # exchange symbol, e.g. BTCUSDT
    side: str              # long / short
    qty: float             # exchange units
    entry: float
    ids: list = field(default_factory=list)   # exchange position ids (TheTrueTrade can hold several per symbol)


class ExchangeError(RuntimeError):
    pass


def bot_to_exchange(symbol: str) -> tuple[str, float]:
    """'BTC/USDT:USDT' -> ('BTCUSDT', 1); 'SHIB/USDT:USDT' -> ('1000SHIBUSDT', 1000): exchange price = price x mult,
    exchange qty = qty / mult."""
    base = symbol.split("/")[0].upper()
    if base in ("SHIB", "PEPE", "FLOKI", "BONK"):
        return f"1000{base}USDT", 1000.0
    return f"{base}USDT", 1.0


def round_step(x: float, step: float) -> float:
    if step <= 0:return x
    return math.floor(x / step + 1e-9) * step


class Adapter:
    name = "base"
    def markets(self) -> dict:raise NotImplementedError          # symbol -> {step, tick, min_qty, min_notional, max_leverage}
    def equity(self) -> float:raise NotImplementedError          # futures account equity in USDT
    def positions(self) -> dict[str, LivePosition]:raise NotImplementedError
    def price(self, symbol: str) -> float:raise NotImplementedError
    def open(self, symbol: str, side: str, qty: float, leverage: int, stop: float | None) -> None:raise NotImplementedError
    def close(self, pos: LivePosition, qty: float | None = None) -> None:raise NotImplementedError   # None = all
    def set_stop(self, pos: LivePosition, stop: float) -> None:raise NotImplementedError
    def close_all(self) -> None:
        for p in self.positions().values():self.close(p)


# ------------------------------------------------------------------------------------------------ TheTrueTrade
class TheTrueTrade(Adapter):
    name = "thetruetrade"

    def __init__(self, key: str | None = None, secret: str | None = None, base: str | None = None, timeout: int = 15):
        self.key = key if key is not None else os.getenv("TTT_API_KEY", "").strip()
        self.secret = secret if secret is not None else os.getenv("TTT_API_SECRET", "").strip()
        self.base = (base or os.getenv("TTT_BASE_URL", "https://apiv2.thetruetrade.io")).rstrip("/")
        self.timeout = timeout;self._markets = None

    @staticmethod
    def sign(secret: str, timestamp: str, method: str, uri: str) -> str:
        return hmac.new(secret.encode(), f"{timestamp}{method.upper()}{uri}".encode(), hashlib.sha256).hexdigest()

    def request(self, method: str, path: str, query: dict | None = None, body: dict | None = None, auth: bool = True):
        uri = path + ("?" + urllib.parse.urlencode(query) if query else "")
        headers = {"Accept": "application/json", "User-Agent": "lbank-live-mirror/1"}
        if auth:
            if not (self.key and self.secret):raise ExchangeError("TTT_API_KEY / TTT_API_SECRET are not set")
            ts = str(int(time.time() * 1000))
            headers.update({"X-API-Key": self.key, "X-Timestamp": ts, "X-Signature": self.sign(self.secret, ts, method, uri)})
        data = None
        if body is not None:
            data = json.dumps(body).encode();headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + uri, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as exc:
            try:detail = json.loads(exc.read()).get("errors")
            except Exception:detail = None
            raise ExchangeError(f"TheTrueTrade {method} {path}: HTTP {exc.code} {detail or ''}".strip()) from None
        except Exception as exc:
            raise ExchangeError(f"TheTrueTrade {method} {path}: {type(exc).__name__}") from None
        return json.loads(raw) if raw else None

    @staticmethod
    def _list(x):
        if isinstance(x, dict):
            for k in ("data", "items", "results", "positions", "assets"):
                if isinstance(x.get(k), list):return x[k]
        return x if isinstance(x, list) else []

    def markets(self) -> dict:
        if self._markets is None:
            out = {}
            for m in self._list(self.request("GET", "/futures/markets", auth=False)):
                if not m.get("isActive", True):continue
                out[m["symbol"]] = dict(step=float(m.get("stepSize") or 0), tick=float(m.get("tickSize") or 0),
                                        min_qty=float(m.get("minOrderSize") or m.get("stepSize") or 0),
                                        min_notional=float(m.get("minOrderValue") or 5), max_leverage=int(m.get("maxLeverage") or 20))
            self._markets = out
        return self._markets

    def price(self, symbol: str) -> float:
        for s in self._list(self.request("GET", "/futures/markets/stats", auth=False)):
            if s.get("symbol") == symbol:return float(s.get("markPrice") or s["lastPrice"])
        raise ExchangeError(f"no price for {symbol}")

    def equity(self) -> float:
        """Futures account equity; never double-count unrealized PnL in totalAssets."""
        response = self.request("GET", "/futures/assets")

        def amount(value, field: str) -> float:
            if isinstance(value, bool):
                raise ExchangeError(f"Invalid TheTrueTrade {field}")
            try:
                result = float(value)
            except (TypeError, ValueError, OverflowError):
                raise ExchangeError(f"Invalid TheTrueTrade {field}") from None
            if not math.isfinite(result) or result < 0:
                raise ExchangeError(f"Invalid TheTrueTrade {field}")
            return result

        if isinstance(response, dict):
            summary = response.get("summary")
            if summary is not None:
                if not isinstance(summary, dict):
                    raise ExchangeError("Invalid TheTrueTrade futures summary")
                if summary.get("totalAssets") is not None:
                    # The endpoint reports account equity here, including floating PnL.
                    return amount(summary["totalAssets"], "summary.totalAssets")
            rows = response.get("assets")
        else:
            rows = response  # Backwards-compatible legacy list response.

        if not isinstance(rows, list):
            raise ExchangeError("Missing TheTrueTrade futures assets")
        usdt = [a for a in rows if isinstance(a, dict)
                and str(a.get("symbol") or a.get("asset") or "").upper() == "USDT"]
        if not usdt:
            raise ExchangeError("USDT futures asset not found")

        # Modern rows expose totalAssets; legacy responses exposed balance.
        modern = [a for a in usdt if a.get("totalAssets") is not None]
        if len(modern) == len(usdt):
            return amount(sum(amount(a["totalAssets"], "assets.totalAssets") for a in modern),
                          "futures equity")
        if modern or any(a.get("balance") is None for a in usdt):
            raise ExchangeError("Incomplete TheTrueTrade futures asset balances")
        balance = sum(amount(a["balance"], "assets.balance") for a in usdt)
        # Only old API responses required adding unrealized PnL separately.
        try:
            upnl = sum(float(p.get("unrealizedPnL") or 0) for p in self._raw_positions())
        except (TypeError, ValueError, OverflowError):
            raise ExchangeError("Invalid TheTrueTrade unrealized PnL") from None
        if not math.isfinite(upnl):
            raise ExchangeError("Invalid TheTrueTrade unrealized PnL")
        return amount(balance + upnl, "futures equity")

    def _raw_positions(self) -> list:
        return [p for p in self._list(self.request("GET", "/futures/positions", {"active": "true"})) if str(p.get("status", "OPEN")).upper() == "OPEN"]

    def positions(self) -> dict[str, LivePosition]:
        out: dict[str, LivePosition] = {}
        for p in self._raw_positions():
            sym = p["symbol"];side = "long" if str(p["side"]).upper() == "LONG" else "short";q = abs(float(p.get("size") or 0))
            if q <= 0:continue
            e = float(p.get("entryPrice") or p.get("averageEntryPrice") or p.get("markPrice") or 0)
            cur = out.get(sym)
            if cur is None:out[sym] = LivePosition(sym, side, q, e, [p["id"]])
            elif cur.side == side:cur.entry = (cur.entry * cur.qty + e * q) / (cur.qty + q);cur.qty += q;cur.ids.append(p["id"])
            else:raise ExchangeError(f"{sym}: long and short positions open at the same time")
        return out

    def _fmt(self, x: float) -> str:
        return f"{x:.12f}".rstrip("0").rstrip(".")

    def open(self, symbol, side, qty, leverage, stop=None):
        body = {"symbol": symbol, "side": "LONG" if side == "long" else "SHORT", "tradeType": "MARKET", "leverage": int(leverage),
                "size": self._fmt(qty), "walletType": "debit"}
        if stop:body.update(stopLoss=self._fmt(stop))
        self.request("POST", "/futures/positions", body=body)

    def close(self, pos, qty=None):
        left = pos.qty if qty is None else qty
        for pid in list(pos.ids):
            if left <= 0:break
            cur = next((float(p["size"]) for p in self._raw_positions() if p["id"] == pid), 0.)
            if cur <= 0:continue
            part = min(cur, left);body = {"orderType": "MARKET"}
            if part < cur - 1e-12:body["size"] = self._fmt(part)
            self.request("POST", f"/futures/positions/{pid}/close", body=body);left -= part

    def set_stop(self, pos, stop):
        for pid in pos.ids:
            self.request("PATCH", f"/futures/positions/{pid}/tpsl", body={"stopLoss": self._fmt(stop), "stopLossOrderType": "STOP_MARKET",
                                                                         "stopLossStrategy": "LATEST_PRICE"})

    def close_all(self):
        self.request("POST", "/futures/positions/close-all", body={})


# ------------------------------------------------------------------------------------------------ Binance USDT-M
class Binance(Adapter):
    name = "binance"

    def __init__(self, testnet: bool | None = None, exchange=None):
        import ccxt
        self.x = exchange or ccxt.binanceusdm({"apiKey": os.getenv("BINANCE_API_KEY", "").strip(), "secret": os.getenv("BINANCE_API_SECRET", "").strip(),
                                                "enableRateLimit": True, "timeout": 15000, "options": {"defaultType": "future"}})
        if testnet if testnet is not None else os.getenv("BINANCE_TESTNET", "0") == "1":
            self.x.set_sandbox_mode(True)
        self._markets = None

    def _sym(self, s: str) -> str:   # BTCUSDT -> BTC/USDT:USDT (ccxt unified)
        return s[:-4] + "/USDT:USDT"

    def markets(self):
        if self._markets is None:
            self.x.load_markets();out = {}
            for m in self.x.markets.values():
                if m.get("swap") and m.get("linear") and m.get("settle") == "USDT" and m.get("active", True):
                    lim = m.get("limits", {});prec = m.get("precision", {})
                    out[m["id"]] = dict(step=float(prec.get("amount") or 0), tick=float(prec.get("price") or 0), min_qty=float((lim.get("amount") or {}).get("min") or 0),
                                        min_notional=float((lim.get("cost") or {}).get("min") or 5), max_leverage=125)
            self._markets = out
        return self._markets

    def price(self, symbol):
        return float(self.x.fetch_ticker(self._sym(symbol))["last"])

    def equity(self):
        b = self.x.fetch_balance();return float(((b.get("info") or {}).get("totalMarginBalance")) or (b.get("total") or {}).get("USDT") or 0)

    def positions(self):
        out = {}
        for p in self.x.fetch_positions():
            q = abs(float(p.get("contracts") or 0))
            if q <= 0:continue
            sym = p["info"]["symbol"];out[sym] = LivePosition(sym, "long" if p["side"] == "long" else "short", q, float(p.get("entryPrice") or 0), [sym])
        return out

    def _cancel_stops(self, symbol):
        for o in self.x.fetch_open_orders(self._sym(symbol)):
            if str(o.get("type", "")).lower() in ("stop_market", "stop") or (o.get("info") or {}).get("closePosition") in (True, "true"):
                self.x.cancel_order(o["id"], self._sym(symbol))

    def _place_stop(self, symbol, side, stop):
        self.x.create_order(self._sym(symbol), "STOP_MARKET", "sell" if side == "long" else "buy", None, None,
                            {"stopPrice": self.x.price_to_precision(self._sym(symbol), stop), "closePosition": True, "workingType": "CONTRACT_PRICE"})

    def open(self, symbol, side, qty, leverage, stop=None):
        s = self._sym(symbol)
        try:self.x.set_leverage(int(leverage), s)
        except Exception:pass
        self.x.create_order(s, "market", "buy" if side == "long" else "sell", self.x.amount_to_precision(s, qty))
        if stop:self._cancel_stops(symbol);self._place_stop(symbol, side, stop)

    def close(self, pos, qty=None):
        s = self._sym(pos.symbol);q = pos.qty if qty is None else qty
        self.x.create_order(s, "market", "sell" if pos.side == "long" else "buy", self.x.amount_to_precision(s, q), None, {"reduceOnly": True})
        if qty is None or q >= pos.qty - 1e-12:self._cancel_stops(pos.symbol)

    def set_stop(self, pos, stop):
        self._cancel_stops(pos.symbol);self._place_stop(pos.symbol, pos.side, stop)


# ------------------------------------------------------------------------------------------------ simulated
class Sim(Adapter):
    """Simulated exchange: fills at the given price feed, keeps positions in memory; used by 'dry' mode and tests."""
    name = "sim"

    def __init__(self, price_fn=None, equity: float = 10000., markets: dict | None = None):
        self.price_fn = price_fn or (lambda s: 100.);self.eq = equity;self.pos: dict[str, LivePosition] = {};self.stops: dict[str, float] = {};self.log = []
        self._m = markets

    def markets(self):
        return self._m or {}

    def price(self, symbol):return float(self.price_fn(symbol))
    def equity(self):return self.eq
    def positions(self):return {k: LivePosition(v.symbol, v.side, v.qty, v.entry, list(v.ids)) for k, v in self.pos.items()}

    def open(self, symbol, side, qty, leverage, stop=None):
        px = self.price(symbol);cur = self.pos.get(symbol)
        if cur and cur.side == side:cur.entry = (cur.entry * cur.qty + px * qty) / (cur.qty + qty);cur.qty += qty
        else:self.pos[symbol] = LivePosition(symbol, side, qty, px, [symbol])
        if stop:self.stops[symbol] = stop
        self.log.append(("open", symbol, side, qty, stop))

    def close(self, pos, qty=None):
        cur = self.pos.get(pos.symbol)
        if not cur:return
        q = cur.qty if qty is None else min(qty, cur.qty);cur.qty -= q;self.log.append(("close", pos.symbol, q))
        if cur.qty <= 1e-12:del self.pos[pos.symbol];self.stops.pop(pos.symbol, None)

    def set_stop(self, pos, stop):
        self.stops[pos.symbol] = stop;self.log.append(("stop", pos.symbol, stop))


def make(name: str) -> Adapter:
    if name == "thetruetrade":return TheTrueTrade()
    if name == "binance":return Binance()
    if name == "sim":return Sim()
    raise ValueError(f"unknown exchange {name!r} (thetruetrade / binance)")
