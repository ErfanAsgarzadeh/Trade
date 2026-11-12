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
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

# Live entries on TheTrueTrade need a certification written by ttt_live_certify.py: a real, tiny position whose stop-loss
# was read back, moved, partially closed and actually triggered by the exchange. It is bound to the API key and expires.
CERT_NAME = "ttt_live_certification.json"
CERT_VERSION = 1
CERT_MAX_AGE_DAYS = 30
CERT_REQUIRED_CHECKS = ("entry_confirmed", "stop_readback", "stop_moved", "partial_close", "full_close", "stop_triggered")
STOP_QUERIES = ("active", "page")
# A position that is (still) open on TheTrueTrade; PARTIAL_CLOSED = open with part of it already closed (seen live).
OPEN_STATUSES = ("OPEN", "OPENED", "PARTIAL_CLOSED", "PARTIALLY_CLOSED")


def pause(seconds: float) -> None:
    """Wait between exchange readbacks (replaced by a no-op in tests)."""
    time.sleep(seconds)


def runtime_dir() -> Path:
    """Same folder as live_mirror.folder() (kept here to avoid an import cycle)."""
    return Path(os.getenv("RISK_DIR", str(Path(os.getenv("BOT_DB", "data/lbank_ichimoku_bot.db")).resolve().parent)))


def key_fingerprint(key: str) -> str:
    """Short one-way tag of the API key: binds a certification to the key without storing the key."""
    return hashlib.sha256(("ttt-live-cert:" + key).encode()).hexdigest()[:16]


def dec(value) -> Decimal | None:
    if value is None or isinstance(value, bool):return None
    try:out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):return None
    return out if out.is_finite() else None


@dataclass
class LivePosition:
    symbol: str            # exchange symbol, e.g. BTCUSDT
    side: str              # long / short
    qty: float             # exchange units
    entry: float | None  # None if exchange omits entryPrice; markPrice is NOT the fill price.
    ids: list = field(default_factory=list)   # exchange position ids (TheTrueTrade can hold several per symbol)


class ExchangeError(RuntimeError):
    pass


def _usable_id(v) -> str | None:
    if isinstance(v, bool) or not isinstance(v, (int, str)) or not str(v).strip():return None
    return str(v).strip()


def position_id(response) -> str | None:
    """positionId of an entry reply: top level or one wrapper level (data / result / position / item), positionId or id."""
    layers = [response]
    if isinstance(response, dict):
        layers += [response[k] for k in ("data", "result", "position", "item") if isinstance(response.get(k), dict)]
    for layer in layers:
        if isinstance(layer, dict):
            for key in ("positionId", "positionID", "position_id", "id"):
                pid = _usable_id(layer.get(key))
                if pid:return pid
    if isinstance(response, (int, str)) and not isinstance(response, bool):
        return _usable_id(response)
    return None


def shape(x, depth=0) -> str:
    """Key names and value types of a reply, never its values (safe to log)."""
    if isinstance(x, dict):
        if depth >= 2:return "{...}"
        return "{" + ", ".join(f"{k}: {shape(v, depth + 1)}" for k, v in list(x.items())[:12] if isinstance(k, str)) + "}"
    if isinstance(x, list):return f"[{len(x)} items]"
    return type(x).__name__


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
    def available_balance(self) -> float:
        raise ExchangeError("Available-margin preflight is not supported by this adapter")
    def ensure_protected_entries(self) -> None:
        raise ExchangeError("Exchange stop-loss readback has not been validated; live entries are blocked")
    def verify_stop(self, pos: LivePosition, stop: float) -> None:
        raise ExchangeError("Exchange stop-loss readback is not supported")
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
                # The live API may omit both minimum-order fields. Do NOT turn
                # stepSize into minOrderSize or invent a $5 minimum notional.
                # Unknown limits remain None and must block live entry sizing.
                def optional_positive(field):
                    value = m.get(field)
                    if value is None:
                        return None
                    if isinstance(value, bool):
                        raise ExchangeError(f"Invalid TheTrueTrade market {field}")
                    try:
                        result = float(value)
                    except (TypeError, ValueError, OverflowError):
                        raise ExchangeError(f"Invalid TheTrueTrade market {field}") from None
                    if not math.isfinite(result) or result <= 0:
                        raise ExchangeError(f"Invalid TheTrueTrade market {field}")
                    return result

                out[m["symbol"]] = dict(
                    step=optional_positive("stepSize"),
                    tick=optional_positive("tickSize"),
                    min_qty=optional_positive("minOrderSize"),
                    min_notional=optional_positive("minOrderValue"),
                    max_leverage=int(m.get("maxLeverage") or 20),
                )
            self._markets = out
        try:   # the API reports no minimums: use the order value a real certified entry was accepted at, step as min qty
            cert = self.load_certification()
        except ExchangeError:
            cert = None
        if cert:
            for v in self._markets.values():
                if v["min_notional"] is None:v["min_notional"] = float(cert["min_notional_usd"])
                if v["min_qty"] is None:v["min_qty"] = v["step"]
        return self._markets

    # ---------------- certification (see ttt_live_certify.py)
    def load_certification(self, now: float | None = None) -> dict:
        """The verified facts about this key's account, or ExchangeError. Never trusts a stale, foreign or partial file."""
        path = runtime_dir() / CERT_NAME
        try:c = json.loads(path.read_text())
        except FileNotFoundError:raise ExchangeError("no TheTrueTrade live certification; run ttt_live_certify.py") from None
        except (OSError, ValueError):raise ExchangeError("TheTrueTrade live certification unreadable") from None
        now = time.time() if now is None else now
        try:
            ok = (isinstance(c, dict) and c.get("version") == CERT_VERSION and c.get("passed") is True
                  and all(c["checks"].get(k) is True for k in CERT_REQUIRED_CHECKS)
                  and c["readback"]["query"] in STOP_QUERIES and isinstance(c["readback"]["require_order_id"], bool)
                  and isinstance(c["readback"]["orders_check"], bool))
            age = now - float(c["created_at"])
            min_notional = float(c["min_notional_usd"])
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ExchangeError("TheTrueTrade live certification incomplete") from None
        if not ok:raise ExchangeError("TheTrueTrade live certification did not pass every check")
        if not (0 <= age <= CERT_MAX_AGE_DAYS * 86400):raise ExchangeError("TheTrueTrade live certification expired; run ttt_live_certify.py again")
        if c.get("base") != self.base:raise ExchangeError("TheTrueTrade live certification is for another API host")
        if not self.key or c.get("key_fingerprint") != key_fingerprint(self.key):
            raise ExchangeError("TheTrueTrade live certification is for another API key")
        if not (math.isfinite(min_notional) and min_notional > 0):raise ExchangeError("TheTrueTrade live certification has no minimum order value")
        return c

    def round_price(self, symbol: str, x: float) -> float:
        """Round a trigger price to the market tick (the exchange stores tick-aligned prices)."""
        tick = (self.markets().get(symbol) or {}).get("tick")
        if not tick:return float(x)
        t = Decimal(str(tick))
        return float((Decimal(str(x)) / t).quantize(Decimal(1), rounding=ROUND_HALF_UP) * t)

    def stop_rows(self, symbol: str, query: str) -> list:
        q = {"symbol": symbol, "active": "true"} if query == "active" else {"symbol": symbol, "page": 1}
        rows = self._list(self.request("GET", "/futures/positions", q))
        if not all(isinstance(r, dict) for r in rows):raise ExchangeError("Invalid TheTrueTrade position record")
        return rows

    def open_orders(self, symbol: str) -> list:
        rows = self._list(self.request("GET", "/futures/orders", {"symbol": symbol, "active": "true"}))
        if not all(isinstance(r, dict) for r in rows):raise ExchangeError("Invalid TheTrueTrade order record")
        return rows

    def cancel_order(self, order_id: str) -> None:
        self.request("DELETE", f"/futures/orders/{order_id}")

    def stop_order_ids(self, symbol: str, pids: list) -> list[str]:
        """Current stop order ids (slOrderId) of these positions."""
        out = []
        for r in self.stop_rows(symbol, "active"):
            if str(r.get("id")) in {str(i) for i in pids} and _usable_id(r.get("slOrderId")):
                out.append(_usable_id(r.get("slOrderId")))
        return out

    def check_stop(self, symbol: str, pids: list, stop: float, readback: dict) -> list[str]:
        """Problems with the exchange-side stop of every position id (empty list = verified)."""
        want = dec(self.round_price(symbol, stop));tick = dec((self.markets().get(symbol) or {}).get("tick")) or Decimal(0)
        rows = {str(r.get("id")): r for r in self.stop_rows(symbol, readback["query"])}
        orders = None;problems = []
        for pid in pids:
            r = rows.get(str(pid))
            if r is None:problems.append("position not in stop readback");continue
            if str(r.get("status", "OPEN")).upper() not in OPEN_STATUSES or r.get("isActive") is False:
                problems.append("position not open");continue
            got = dec(r.get("stopLoss"))
            if got is None or got <= 0:problems.append("no stopLoss on position");continue
            if abs(got - want) > tick / 2 + Decimal("1e-12"):problems.append(f"stopLoss differs from requested stop (exchange {got}, requested {want})");continue
            if r.get("stopLossOrderType") not in (None, "STOP_MARKET"):problems.append("stop order type is not STOP_MARKET")
            oid = r.get("slOrderId")
            has_oid = not isinstance(oid, bool) and isinstance(oid, (int, str)) and bool(str(oid).strip())
            if readback["require_order_id"] and not has_oid:problems.append("stop order id missing");continue
            if readback["orders_check"]:
                if orders is None:orders = {str(o.get("id")): o for o in self.open_orders(symbol)}
                if not has_oid or str(oid) not in orders:problems.append("stop order not among active exchange orders")
        return problems

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

    def available_balance(self) -> float:
        """Use *free* margin, never total account equity, for new order budgets."""
        data = self.request("GET", "/futures/assets")
        if isinstance(data, dict) and isinstance(data.get("summary"), dict):
            value = data["summary"].get("availableBalance")
        elif isinstance(data, dict) and isinstance(data.get("assets"), list):
            rows = [a for a in data["assets"] if isinstance(a, dict)
                    and str(a.get("symbol", "")).upper() == "USDT"]
            if len(rows) != 1:
                raise ExchangeError("Missing/ambiguous USDT available balance")
            value = rows[0].get("availableBalance")
        else:
            raise ExchangeError("Unsupported TheTrueTrade available-balance response")
        if isinstance(value, bool) or value is None:
            raise ExchangeError("Missing TheTrueTrade availableBalance")
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ExchangeError("Invalid TheTrueTrade availableBalance") from None
        if not math.isfinite(result) or result < 0:
            raise ExchangeError("Invalid TheTrueTrade availableBalance")
        return result

    def _raw_positions(self) -> list:
        """Read all reported open positions; never mistake an unknown schema for an empty account."""
        response = self.request("GET", "/futures/positions", {"active": "true"})
        if isinstance(response, list):  # Older API shape.
            rows = response
        elif isinstance(response, dict):
            rows = next((response[k] for k in ("items", "positions", "data", "results")
                         if isinstance(response.get(k), list)), None)
        else:
            rows = None
        if rows is None:
            raise ExchangeError("Invalid TheTrueTrade positions response: no position list")
        if isinstance(response, dict) and "meta" in response:
            meta = response["meta"]
            if not isinstance(meta, dict):
                raise ExchangeError("Invalid TheTrueTrade positions pagination metadata")
            for key in ("total", "totalCount", "totalItems"):
                if key not in meta or meta[key] is None:
                    continue
                value = meta[key]
                try:
                    total = int(value)
                except (TypeError, ValueError, OverflowError):
                    raise ExchangeError("Invalid TheTrueTrade positions total") from None
                if isinstance(value, bool) or total < 0 or str(value).strip() != str(total):
                    raise ExchangeError("Invalid TheTrueTrade positions total")
                if total > len(rows):
                    raise ExchangeError("Incomplete TheTrueTrade positions page; no trading until all positions are fetched")
            if meta.get("hasNextPage") is True or meta.get("hasNext") is True or meta.get("nextCursor"):
                raise ExchangeError("TheTrueTrade positions response has another page")
        positions = []
        for p in rows:
            if not isinstance(p, dict):
                raise ExchangeError("Invalid TheTrueTrade position record")
            status = p.get("status")
            active = p.get("isActive")
            if active is not None and not isinstance(active, bool):
                raise ExchangeError("Invalid TheTrueTrade isActive flag")
            if status is None:
                if active is True:
                    positions.append(p)
                    continue
                raise ExchangeError("Missing TheTrueTrade position status")
            if not isinstance(status, str):
                raise ExchangeError("Invalid TheTrueTrade position status")
            status = status.upper()
            if status in OPEN_STATUSES:
                if active is False:
                    raise ExchangeError("Inconsistent TheTrueTrade open position state")
                positions.append(p)
            elif status in ("CLOSED", "CANCELED", "CANCELLED", "LIQUIDATED", "SETTLED"):
                if active is True:
                    raise ExchangeError("Inconsistent TheTrueTrade closed position state")
            else:
                raise ExchangeError(f"Unknown TheTrueTrade position status: {status}")
        return positions

    def positions(self) -> dict[str, LivePosition]:
        """Normalize positions with explicit validation; incomplete snapshots must block trading."""
        out: dict[str, LivePosition] = {}

        def positive(value, field: str) -> float:
            if isinstance(value, bool):
                raise ExchangeError(f"Invalid TheTrueTrade {field}")
            try:
                num = float(value)
            except (TypeError, ValueError, OverflowError):
                raise ExchangeError(f"Invalid TheTrueTrade {field}") from None
            if not math.isfinite(num) or num <= 0:
                raise ExchangeError(f"Invalid TheTrueTrade {field}")
            return num

        for p in self._raw_positions():
            sym = p.get("symbol")
            if not isinstance(sym, str) or not sym.strip():
                raise ExchangeError("Missing TheTrueTrade position symbol")
            raw_side = p.get("side")
            if not isinstance(raw_side, str) or raw_side.upper() not in ("LONG", "SHORT"):
                raise ExchangeError(f"Invalid TheTrueTrade position side for {sym}")
            side = "long" if raw_side.upper() == "LONG" else "short"
            q = positive(p.get("size"), f"position size for {sym}")
            # The API reference's GET /futures/positions example provides
            # markPrice but does NOT promise entryPrice. Never pretend the
            # current mark price is the execution price.
            raw_entry = p.get("entryPrice", p.get("averageEntryPrice"))
            entry = (positive(raw_entry, f"entry price for {sym}")
                     if raw_entry is not None else None)
            pid = p.get("id")
            if pid is None or isinstance(pid, bool) or not isinstance(pid, (int, str)) or not str(pid).strip():
                raise ExchangeError(f"Missing TheTrueTrade position ID for {sym}")
            cur = out.get(sym)
            if cur is None:
                out[sym] = LivePosition(sym, side, q, entry, [pid])
            elif cur.side == side:
                if pid in cur.ids or str(pid) in [str(x) for x in cur.ids]:
                    raise ExchangeError(f"{sym}: duplicate exchange position ID")
                cur.entry = (
                    (cur.entry * cur.qty + entry * q) / (cur.qty + q)
                    if cur.entry is not None and entry is not None else None
                )
                cur.qty += q
                cur.ids.append(pid)
            else:
                raise ExchangeError(f"{sym}: both long and short positions open")
        return out

    def _fmt(self, x: float) -> str:
        return f"{x:.12f}".rstrip("0").rstrip(".")

    def ensure_protected_entries(self) -> None:
        try:self.load_certification()
        except ExchangeError as exc:
            raise ExchangeError(f"Exchange stop-loss readback has not been validated; live entries are blocked ({exc})") from None

    def verify_stop(self, pos: LivePosition, stop: float) -> None:
        try:cert = self.load_certification()
        except ExchangeError as exc:
            raise ExchangeError(f"Exchange stop-loss readback is not supported without a valid certification ({exc})") from None
        for attempt in range(25):  # the exchange can attach or move the stop order 30 s and more after the request
            problems = self.check_stop(pos.symbol, list(pos.ids), stop, cert["readback"])
            if not problems:return
            pause(2.0)
        if problems:raise ExchangeError(f"{pos.symbol}: stop not verified: {'; '.join(sorted(set(problems)))}")

    def open(self, symbol, side, qty, leverage, stop=None):
        # Never issue a naked futures entry. The mirror also requires an independently
        # verified stop-readback capability before it can call this in live mode.
        if not isinstance(stop, (int, float)) or isinstance(stop, bool) or not math.isfinite(stop) or stop <= 0:
            raise ExchangeError("Refusing TheTrueTrade entry without valid stop loss")
        if not isinstance(qty, (int, float)) or isinstance(qty, bool) or not math.isfinite(qty) or qty <= 0:
            raise ExchangeError("Invalid TheTrueTrade entry quantity")
        if side not in ("long", "short"):
            raise ExchangeError("Invalid TheTrueTrade entry side")
        body = {"symbol": symbol, "side": "LONG" if side == "long" else "SHORT", "tradeType": "MARKET", "leverage": int(leverage),
                "size": self._fmt(qty), "walletType": "debit",
                "stopLoss": self._fmt(self.round_price(symbol, stop)),
                "stopLossOrderType": "STOP_MARKET", "stopLossStrategy": "LATEST_PRICE"}
        before = {str(r.get("id")): float(r.get("size") or 0) for r in self._raw_positions() if r.get("symbol") == symbol}
        response = self.request("POST", "/futures/positions", body=body)
        # The API reference documents HTTP 201 {positionId}; the live gateway answers {orderId}. A successful HTTP status
        # without a position we can identify is an ambiguous outcome, NOT confirmation that we own the position.
        pid = position_id(response)
        if pid is None and isinstance(response, dict) and _usable_id(response.get("orderId")):
            pid = self._position_for_order(symbol, str(response["orderId"]).strip(), before, qty)
        if pid is None:
            raise ExchangeError(f"TheTrueTrade entry returned no usable positionId (reply shape: {shape(response)})")
        return pid

    def _position_for_order(self, symbol: str, order_id: str, before: dict, qty: float) -> str | None:
        """Position created by a filled entry order: the order record's position id if the exchange reports one, else the
        one position on this symbol that is new (or, if the exchange nets entries, the one that grew by qty)."""
        self.entry_resolution = None
        for attempt in range(6):
            try:
                for o in self._list(self.request("GET", "/futures/orders", {"symbol": symbol})):
                    if isinstance(o, dict) and str(o.get("id")) == order_id:
                        pid = next((_usable_id(o.get(k)) for k in ("positionId", "positionID", "position_id") if _usable_id(o.get(k))), None)
                        if pid:
                            self.entry_resolution = "order_record";return pid
            except ExchangeError:
                pass
            now = {str(r.get("id")): float(r.get("size") or 0) for r in self._raw_positions() if r.get("symbol") == symbol}
            new = [i for i in now if i not in before]
            if len(new) == 1:
                self.entry_resolution = "new_position";return new[0]
            if len(new) > 1:
                raise ExchangeError(f"{symbol}: several new positions after one entry; cannot tell which is ours")
            step = (self.markets().get(symbol) or {}).get("step") or 0
            grown = [i for i in now if i in before and abs(now[i] - before[i] - qty) <= max(step * .05, 1e-12)]
            if len(grown) == 1:
                self.entry_resolution = "netted_position";return grown[0]
            pause(1.0)
        return None

    def close(self, pos, qty=None):
        left = pos.qty if qty is None else qty
        for pid in list(pos.ids):
            if left <= 0:break
            cur = next((float(p["size"]) for p in self._raw_positions() if p["id"] == pid), 0.)
            if cur <= 0:continue
            part = min(cur, left);body = {"orderType": "MARKET"}
            if part < cur - 1e-12:body["size"] = self._fmt(part)
            reply = self.request("POST", f"/futures/positions/{pid}/close", body=body);left -= part
            self.last_close = {"body": dict(body), "reply_shape": shape(reply)}

    def set_stop(self, pos, stop):
        for pid in pos.ids:
            self.request("PATCH", f"/futures/positions/{pid}/tpsl", body={"stopLoss": self._fmt(self.round_price(pos.symbol, stop)), "stopLossOrderType": "STOP_MARKET",
                                                                         "stopLossStrategy": "LATEST_PRICE"})

    def close_all(self):
        # API reference: no request body for this endpoint.
        self.request("POST", "/futures/positions/close-all")


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

    def available_balance(self):
        b = self.x.fetch_balance()
        value = (b.get("free") or {}).get("USDT")
        if value is None:raise ExchangeError("Binance available USDT balance unavailable")
        try:result = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ExchangeError("Invalid Binance free balance") from None
        if not math.isfinite(result) or result < 0:
            raise ExchangeError("Invalid Binance free balance")
        return result

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
    def available_balance(self):return self.eq
    def ensure_protected_entries(self):return None  # Simulator verifies stops from in-memory state.
    def verify_stop(self, pos, stop):
        actual = self.stops.get(pos.symbol)
        if actual is None or not math.isclose(actual, stop, rel_tol=1e-7, abs_tol=1e-10):
            raise ExchangeError(f"{pos.symbol}: simulated stop loss not confirmed")
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
