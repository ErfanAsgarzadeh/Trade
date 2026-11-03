"""READ-ONLY LBank futures (perpetual, USDT) account check for the dashboard's "Trading account" panel.

It only asks LBank for the futures account balance (POST /cfd/openApi/v1/prv/account, productGroup=SwapU), signed as
LBank's contract API documentation describes (https://www.lbank.com/en-US/docs/contract.html):
  string = all parameters (incl. signature_method, timestamp, echostr) sorted by name, joined as key=value with '&'
  sign   = HmacSHA256(secret, MD5(string).upper()) as hex; headers carry the same timestamp / signature_method / echostr.
There is NO order placement here: LBank's published contract API does not document order, leverage or position
endpoints, so live futures execution is not available in this build (see LIVE_LIMITATION in lbank_bot.py).
The API key / secret come from the server's .env (LBANK_API_KEY, LBANK_SECRET_KEY) and never leave this module.
"""
from __future__ import annotations
import hashlib, hmac, json, os, secrets, string, time, urllib.request

BASE = "https://lbkperp.lbank.com"


def keys() -> tuple[str, str]:
    return os.getenv("LBANK_API_KEY", "").strip(), os.getenv("LBANK_SECRET_KEY", "").strip()


def key_status() -> dict:
    k, s = keys()
    return dict(configured=bool(k and s), api_key_hint=("…" + k[-4:]) if len(k) >= 8 else None)


def sign(params: dict, secret: str, timestamp: str, echostr: str, method: str = "HmacSHA256") -> str:
    p = {**params, "signature_method": method, "timestamp": timestamp, "echostr": echostr}
    text = "&".join(f"{k}={p[k]}" for k in sorted(p))
    digest = hashlib.md5(text.encode()).hexdigest().upper()
    return hmac.new(secret.encode(), digest.encode(), hashlib.sha256).hexdigest()


def _server_time() -> str:
    try:
        with urllib.request.urlopen(BASE + "/cfd/openApi/v1/pub/getTime", timeout=10) as r:
            data = json.load(r).get("data")
            if isinstance(data, (int, float, str)) and str(data).isdigit():return str(int(data))
    except Exception:
        pass
    return str(int(time.time() * 1000))


def account_check(timeout: int = 15) -> dict:
    """Ask LBank for the futures account; returns {ok, message, balances?}. Never raises, never returns the keys."""
    k, s = keys()
    if not (k and s):
        return dict(ok=False, message="LBANK_API_KEY / LBANK_SECRET_KEY are not set in the server's .env file.")
    ts = _server_time();echo = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(35))
    params = {"api_key": k, "asset": "USDT", "productGroup": "SwapU"}
    body = {**params, "sign": sign(params, s, ts, echo)}
    req = urllib.request.Request(BASE + "/cfd/openApi/v1/prv/account", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "timestamp": ts, "signature_method": "HmacSHA256", "echostr": echo})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as exc:
        return dict(ok=False, message=f"LBank answered HTTP {exc.code}" + (" (this server's region / IP may be blocked, or the key lacks futures permission)" if exc.code in (401, 403) else ""))
    except Exception as exc:
        return dict(ok=False, message=f"Could not reach LBank futures API: {type(exc).__name__}")
    ok = payload.get("result") in (True, "true") or payload.get("error_code") in (0, "0")
    data = payload.get("data")
    out = dict(ok=bool(ok), message=("Connected: LBank accepted the key and returned the futures account." if ok else
                                     f"LBank refused the request: {payload.get('msg') or payload.get('error_code')}"))
    if ok and isinstance(data, (dict, list)):
        rows = data if isinstance(data, list) else [data]
        keep = ("asset", "balance", "available", "availableBalance", "frozen", "unrealisedPnl", "unrealizedPnl", "marginBalance", "equity")
        out["balances"] = [{k2: r[k2] for k2 in keep if k2 in r} for r in rows if isinstance(r, dict)][:10]
    return out
