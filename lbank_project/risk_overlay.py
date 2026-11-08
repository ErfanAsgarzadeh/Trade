"""F risk manager for the three bots (Shahin, Mojsavar, Ghoghnous) - SHADOW MODE service.

It never places, changes or closes an order and never edits a bot config. It only reads the bots' databases and
public market data, and writes three files into the runtime folder:
  risk_overlay.json        today's decision (what F would do)          - shown by the dashboard
  risk_overlay_log.jsonl   one line per day (decision history + shadow account)
  equity_history.jsonl     account equity snapshot about every hour (equity / drawdown chart)

F (research: high_cagr/ideas/dd_lab9.py, final check dd_final2.py 'F (balanced)'):
  * AI regime score: gradient-boosting model (models/risk_ai_r20.json, exported by high_cagr/ideas/risk_model_export.py)
    predicting the three-bot account's return over the next 20 days from daily market + account features
    -> percentile p vs. its training scores: p < 0.30 no new entries (x0), p > 0.70 x1.4, else x1;
       open positions opened at a higher AI multiplier are cut to the new one
  * volatility target: x clip(1% / realised daily vol of the account over 20 days, 0.3, 1.5)
  * drawdown brake: x1 up to 8% drawdown, falling linearly to x0.2 at 14% (applies to new and open positions)
  * per-bot losing streak: last 20 closed trades of a bot sum below -4R -> that bot x0.5
  * global scale x1.41 (risk solved so the worst 2022-24 drawdown was 14%)
Shadow account: the account's own daily return times yesterday's average F multiplier (an estimate; partial
closes of open positions are not simulated). Brake and volatility target are measured on that shadow account.
"""
from __future__ import annotations
import json, logging, math, os, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pandas as pd

LOG = logging.getLogger("risk_overlay")
HERE = Path(__file__).resolve().parent
COINS = ['shib', 'aave', 'ada', 'algo', 'alice', 'atom', 'avax', 'axs', 'bch', 'btc', 'c98', 'celr', 'crv', 'cvc', 'doge', 'dot',
         'egld', 'etc', 'eth', 'fil', 'iost', 'iota', 'ksm', 'link', 'ltc', 'near', 'one', 'sol', 'sushi', 'theta', 'trx', 'uni',
         'vet', 'xrp', 'xtz']
F = dict(scale=1.41, ai_low=.30, ai_high=.70, ai_low_mult=0., ai_high_mult=1.4, vt_target=.01, vt_days=20, vt_lo=.3, vt_hi=1.5,
         brake_start=.08, brake_full=.14, brake_floor=.2, streak_trades=20, streak_r=-4., streak_mult=.5)
BOTS = {"main": "Shahin", "c3": "Mojsavar", "pa": "Ghoghnous"}
KLINE = "https://api.lbkex.com/v2/kline.do?symbol={s}_usdt&size=250&type=day1&time={t}"
FNG = "https://api.alternative.me/fng/?limit=60"
STABLE = "https://stablecoins.llama.fi/stablecoincharts/all"


def runtime_dir() -> Path:
    return Path(os.getenv("RISK_DIR", str(Path(os.getenv("BOT_DB", "data/lbank_ichimoku_bot.db")).resolve().parent)))


def load_model(path: Path | None = None) -> dict:
    return json.loads(Path(path or os.getenv("RISK_MODEL", HERE / "models" / "risk_ai_r20.json")).read_text())


def predict(model: dict, feats: dict) -> float:
    """Same arithmetic as scikit-learn's HistGradientBoostingRegressor.predict (missing values filled by training medians)."""
    x = []
    for name, med in zip(model["features"], model["medians"]):
        try:
            v = float(feats.get(name))
        except (TypeError, ValueError):
            v = math.nan
        x.append(med if not math.isfinite(v) else v)
    s = model["baseline"]
    for t in model["trees"]:
        i = 0
        while not t["leaf"][i]:
            i = t["l"][i] if x[t["f"][i]] <= t["t"][i] else t["r"][i]
        s += t["v"][i]
    return s


def percentile(model: dict, score: float) -> float:
    q = np.asarray(model["quantiles"])
    return float(np.clip(np.interp(score, q, np.linspace(0, 1, len(q))), 0, 1))


# ---------------------------------------------------------------- data
def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": "lbank-risk/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def daily_closes(now: float) -> pd.DataFrame:
    """Daily closes of the 35 coins (LBank spot), complete UTC days only, index = day (UTC date)."""
    out = {}
    for s in COINS:
        try:
            rows = _get(KLINE.format(s=s, t=int(now) - 249 * 86400)).get("data") or []
            if not rows:
                continue
            ser = pd.Series({pd.Timestamp(int(r[0]), unit="s").normalize(): float(r[4]) for r in rows})
            out[s] = ser[ser.index + pd.Timedelta(days=1) <= pd.Timestamp(now, unit="s")]
        except Exception as exc:
            LOG.warning("kline %s failed: %s", s, exc)
    return pd.DataFrame(out).sort_index()


def market_features(P: pd.DataFrame) -> dict:
    """Same definitions as high_cagr/ideas/dd_ai.py features(), evaluated at the last row."""
    f = {}
    if "btc" not in P or len(P) < 31:
        return f
    b = P["btc"]
    for k in (1, 3, 7, 14, 30):
        f[f"btc_r{k}"] = b.pct_change(k).iloc[-1]
    br = b.pct_change()
    f["btc_v7"] = br.rolling(7).std().iloc[-1]; f["btc_v30"] = br.rolling(30).std().iloc[-1]
    f["btc_m50"] = (b / b.rolling(50).mean() - 1).iloc[-1]; f["btc_m200"] = (b / b.rolling(200, min_periods=100).mean() - 1).iloc[-1]
    f["above20"] = (P > P.rolling(20).mean()).mean(1).iloc[-1]; f["above50"] = (P > P.rolling(50).mean()).mean(1).iloc[-1]
    r7 = P.pct_change(7); f["r7_mean"] = r7.mean(1).iloc[-1]; f["r7_disp"] = r7.std(1).iloc[-1]
    R = P.pct_change(); idx = R.mean(1)
    f["corr30"] = float(np.nanmean([R[c].rolling(30).corr(idx).iloc[-1] for c in R]))
    return {k: float(v) for k, v in f.items()}


def funding_feature(now: float) -> float:
    d = Path(os.getenv("FUNDING_DIR", HERE / "data" / "funding"));vals = []
    for p in d.glob("*_funding.csv") if d.is_dir() else []:
        try:
            x = pd.read_csv(p);t = x.timestamp.astype(float);t = np.where(t > 1e11, t / 1000, t)
            vals.append(float(x.funding_rate[(t > now - 3 * 86400) & (t <= now)].sum()))
        except Exception:
            pass
    return float(np.mean(vals)) if vals else float("nan")


def sentiment_features(day: pd.Timestamp) -> dict:
    f = {}
    try:
        fd = pd.Series({pd.Timestamp(int(x["timestamp"]), unit="s").normalize(): float(x["value"]) for x in _get(FNG)["data"]}).sort_index()
        fd = fd[fd.index <= day]
        f["fng"] = float(fd.iloc[-1]); prev = fd[fd.index <= day - pd.Timedelta(days=7)]
        f["fng_chg7"] = float(fd.iloc[-1] - prev.iloc[-1]) if len(prev) else float("nan")
    except Exception as exc:
        LOG.warning("fear & greed failed: %s", exc)
    try:
        sd = pd.Series({pd.Timestamp(int(x["date"]), unit="s").normalize(): float(x["totalCirculatingUSD"]["peggedUSD"]) for x in _get(STABLE, 40)}).sort_index()
        sd = sd[sd.index <= day]; prev = sd[sd.index <= day - pd.Timedelta(days=30)]
        f["stable_g30"] = float(sd.iloc[-1] / prev.iloc[-1] - 1)
    except Exception as exc:
        LOG.warning("stablecoins failed: %s", exc)
    return f


def account_features(daily_eq: list[float]) -> dict:
    e = np.asarray(daily_eq, float)
    if len(e) < 2:
        return {}
    r = pd.Series(e[1:] / e[:-1] - 1);f = {}
    for k in (5, 10, 30):
        if len(r) >= k:f[f"sys_r{k}"] = float(r.iloc[-k:].sum())
    f["sys_dd"] = float(e[-1] / e.max() - 1)
    if len(r) >= 20:f["sys_v20"] = float(r.iloc[-20:].std())
    return f


# ---------------------------------------------------------------- bots (read only)
class QuoteData:
    """Prices for the account equity from LBank's public futures marketData (the feed lbank_candles.py already uses).
    No CCXT market loading (its spot side endpoints can time out), one HTTP call for all contracts, cached 30 s."""
    mode = "csv-lbank"

    def __init__(self):
        self.quotes, self.at = {}, 0.

    def price(self, symbol: str, cached: bool = False) -> float:
        import lbank_candles
        if time.time() - self.at > 30 or not self.quotes:
            self.quotes, self.at = lbank_candles.fetch_prices(), time.time()
        v = self.quotes.get(lbank_candles.lbank_name(symbol))
        if v is None or not math.isfinite(v) or v <= 0:
            raise ValueError(f"no LBank futures quote for {symbol}")
        return float(v)


class Bots:
    """Read-only view of the three bots: equity, open positions, closed trades."""
    def __init__(self):
        import lbank_bot as bot, c3_sleeve, pa_sleeve
        self.bot, self.c3, self.pa = bot, c3_sleeve, pa_sleeve
        data = bot.MarketData() if os.getenv("PAPER_DATA_MODE", "demo") == "demo" else QuoteData()
        self.engine = bot.Engine(bot.ConfigStore(), bot.Database(), data)

    def equity(self) -> float:
        return float(self.engine.paper_equity())

    def risk_pct(self) -> dict:
        r = {"main": self.engine.config.read()["risk_and_exit"]["risk_per_trade_pct"]}
        try:r["c3"] = self.c3.load(self.c3.paths()[0])["risk_per_trade_pct"]
        except Exception:r["c3"] = .004
        try:
            c = self.pa.load(self.pa.paths()[0]);r["pa"] = c["risk_per_trade_pct"] * c.get("volume_multiplier", 1.)
        except Exception:r["pa"] = .006
        return r

    def positions(self) -> list[dict]:
        out = []
        price = lambda s: self.engine.data.price(s, cached=True)
        for p in self.engine.db.positions():
            if p["state"] == self.bot.PENDING:continue
            dist = p.get("root_r_distance") or abs(p["entry_price"] - p["initial_sl"])
            out.append(dict(bot="main", symbol=p["symbol"], side=p["side"], entry=p["entry_price"], dist=dist))
        for key, mod in (("c3", self.c3), ("pa", self.pa)):
            try:
                for p in mod.paths()[1].positions():
                    out.append(dict(bot=key, symbol=p["symbol"], side=p["side"], entry=p["entry"], dist=(p["risk_usd"] / p["qty"]) if p.get("qty") else 0))
            except Exception as exc:
                LOG.warning("%s positions unreadable: %s", key, exc)
        for p in out:
            try:
                px = price(p["symbol"]);p["r"] = (1 if p["side"] == "long" else -1) * (px - p["entry"]) / p["dist"] if p["dist"] else 0.
            except Exception:
                p["r"] = 0.
        return out

    def closed_trades(self) -> list[dict]:
        """All closed trades of the three bots: bot, symbol, side, pnl, closed (unix s)."""
        out = []
        with self.engine.db.connect() as db:
            for s, side, pnl, t in db.execute("SELECT symbol,side,pnl_usd,closed_at FROM trade_history WHERE dry_run=1 ORDER BY closed_at"):
                out.append(dict(bot="main", symbol=s, side=side, pnl=float(pnl), closed=float(t)))
        for key, mod in (("c3", self.c3), ("pa", self.pa)):
            try:
                with mod.paths()[1].db() as db:
                    for s, side, pnl, t in db.execute("SELECT symbol,side,pnl,closed FROM trades ORDER BY closed"):
                        out.append(dict(bot=key, symbol=s, side=side, pnl=float(pnl or 0), closed=float(t or 0)))
            except Exception as exc:
                LOG.warning("%s trades unreadable: %s", key, exc)
        return sorted(out, key=lambda x: x["closed"])


# ---------------------------------------------------------------- decision
def ai_multiplier(p: float) -> tuple[float, str]:
    if p < F["ai_low"]:return F["ai_low_mult"], "bad"
    if p > F["ai_high"]:return F["ai_high_mult"], "good"
    return 1., "normal"


def vol_multiplier(daily_eq: list[float]) -> tuple[float, float | None]:
    e = np.asarray(daily_eq[-(F["vt_days"] + 1):], float)
    if len(e) < F["vt_days"] + 1:return 1., None
    s = float(np.std(e[1:] / e[:-1] - 1))
    return (float(np.clip(F["vt_target"] / s, F["vt_lo"], F["vt_hi"])) if s > 0 else 1.), s


def brake_multiplier(dd: float) -> float:
    if dd <= F["brake_start"]:return 1.
    return max(F["brake_floor"], 1 - (1 - F["brake_floor"]) * (dd - F["brake_start"]) / (F["brake_full"] - F["brake_start"]))


def streaks(trades: list[dict], equity: float, risk_pct: dict) -> dict:
    out = {}
    for b in BOTS:
        t = [x for x in trades if x["bot"] == b][-F["streak_trades"]:]
        unit = max(equity * risk_pct.get(b, .005), 1e-9);r = sum(x["pnl"] for x in t) / unit
        active = len(t) >= F["streak_trades"] and r < F["streak_r"]
        out[b] = dict(trades=len(t), sum_r=round(r, 2), multiplier=F["streak_mult"] if active else 1., active=active)
    return out


def realized_daily(trades: list[dict], seed: float, until: pd.Timestamp) -> list[tuple[str, float]]:
    """Bootstrap of the daily account curve from closed trades (used until enough equity snapshots exist)."""
    if not trades:return []
    s = pd.Series([x["pnl"] for x in trades], index=pd.to_datetime([x["closed"] for x in trades], unit="s").normalize())
    s = s.groupby(level=0).sum();idx = pd.date_range(s.index.min(), until);eq = seed + s.reindex(idx, fill_value=0).cumsum()
    return [(str(d.date()), float(v)) for d, v in eq.items()]


class State:
    def __init__(self, folder: Path):
        self.dir = folder;self.dir.mkdir(parents=True, exist_ok=True)
        self.current = folder / "risk_overlay.json";self.log = folder / "risk_overlay_log.jsonl";self.eqh = folder / "equity_history.jsonl"

    def read_log(self) -> list[dict]:
        if not self.log.is_file():return []
        return [json.loads(l) for l in self.log.read_text().splitlines() if l.strip()]

    def append(self, path: Path, row: dict):
        with open(path, "a") as f:f.write(json.dumps(row) + "\n")

    def write_current(self, d: dict):
        tmp = self.current.with_suffix(".tmp");tmp.write_text(json.dumps(d, indent=1));tmp.replace(self.current)

    def last_snapshot(self) -> float:
        if not self.eqh.is_file():return 0.
        try:return json.loads(self.eqh.read_text().splitlines()[-1])["t"]
        except Exception:return 0.


def clean(x):
    """JSON-safe copy: NaN / inf -> None."""
    if isinstance(x, dict):return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):return [clean(v) for v in x]
    if isinstance(x, (float, np.floating)):return float(x) if math.isfinite(x) else None
    if isinstance(x, np.integer):return int(x)
    return x


def decide(model: dict, bots, state: State, now: float, fetch=True) -> dict:
    day = pd.Timestamp(now, unit="s").normalize() - pd.Timedelta(days=1)   # the UTC day that just closed
    log = state.read_log();equity = bots.equity();trades = bots.closed_trades();risk = bots.risk_pct()
    acct = [r["account_equity"] for r in log if r.get("account_equity")]
    if len(acct) < 31:   # bootstrap from realized trades
        seed = float(bots.engine.paper_seed);boot = [v for d, v in realized_daily(trades, seed, day - pd.Timedelta(days=1))]
        acct = (boot + acct)[-400:]
    acct = acct + [equity]
    pos = bots.positions()
    feats = {}
    data_status = {}
    if fetch:
        P = daily_closes(now);data_status["coins"] = int(P.shape[1]);data_status["last_day"] = str(P.index[-1].date()) if len(P) else None
        feats.update(market_features(P));feats["fund3"] = funding_feature(now);feats.update(sentiment_features(day))
    feats.update(account_features(acct))
    feats["open_long"] = float(sum(p["side"] == "long" for p in pos));feats["open_short"] = float(sum(p["side"] != "long" for p in pos))
    feats["open_R"] = float(sum(p["r"] for p in pos))
    prev_r = [r["features"].get("open_R") for r in log[-5:] if r.get("features")]
    if len(log) >= 5 and prev_r[0] is not None:feats["open_R_chg5"] = feats["open_R"] - prev_r[0]
    data_status["features_missing"] = [f for f in model["features"] if f not in feats or not np.isfinite(feats[f])]
    score = predict(model, feats);p = percentile(model, score);ai_m, zone = ai_multiplier(p)
    # shadow F account: yesterday's account return x yesterday's average F multiplier
    shadow = [r["shadow_equity"] for r in log if r.get("shadow_equity")]
    if log and log[-1].get("account_equity"):
        r_acc = equity / log[-1]["account_equity"] - 1;sh = (shadow[-1] if shadow else log[-1]["account_equity"]) * (1 + r_acc * log[-1].get("avg_multiplier", 1.))
    else:
        sh = equity
    sh_curve = (shadow + [sh]) if shadow else acct[-30:-1] + [sh]
    vol_m, vol = vol_multiplier(sh_curve);hwm = max(sh_curve);dd = 1 - sh / hwm;brake = brake_multiplier(dd)
    st = streaks(trades, equity, risk)
    base = F["scale"] * ai_m * vol_m * brake
    per_bot = {b: dict(name=BOTS[b], base_risk_pct=round(risk[b] * 100, 3), streak=st[b], multiplier=round(base * st[b]["multiplier"], 3),
                       f_risk_pct=round(risk[b] * 100 * base * st[b]["multiplier"], 3)) for b in BOTS}
    prev_ai = log[-1]["ai"]["multiplier"] if log else ai_m
    if ai_m == 0:open_action = "AI in the bad zone: no new entries; positions opened on better days would be closed"
    elif ai_m < prev_ai:open_action = f"AI multiplier fell {prev_ai}->{ai_m}: open positions would be cut to {ai_m / prev_ai:.0%}"
    else:open_action = "keep open positions"
    if brake < 1:open_action += f"; drawdown brake: positions held at {brake:.0%}"
    return clean(dict(mode="shadow", as_of=str(day.date()), computed_at=now, account_equity=equity, shadow_equity=sh,
                ai=dict(score=score, percentile=p, zone=zone, multiplier=ai_m), vol=dict(daily_vol=vol, multiplier=vol_m),
                brake=dict(drawdown_pct=dd * 100, high=hwm, multiplier=brake), scale=F["scale"], combined=base,
                avg_multiplier=float(np.mean([v["multiplier"] for v in per_bot.values()])), bots=per_bot, open_positions_action=open_action,
                open_positions=len(pos), features=feats, data_status=data_status, params=F,
                model=dict(trained_until=model.get("trained_until"), target=model.get("target"))))


def run(once: bool = False):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    state = State(runtime_dir());model = load_model();bots = None
    LOG.info("F risk manager (shadow) started; writing to %s", state.dir)
    while True:
        try:
            if bots is None:bots = Bots()
            now = time.time()
            if now - state.last_snapshot() >= 3300:
                state.append(state.eqh, dict(t=now, equity=bots.equity()))
            log = state.read_log();day = str((pd.Timestamp(now, unit="s").normalize() - pd.Timedelta(days=1)).date())
            utc = datetime.fromtimestamp(now, timezone.utc)
            if (not log or log[-1]["as_of"] < day) and (utc.hour > 0 or utc.minute >= 5):
                d = decide(model, bots, state, now);state.write_current(d);state.append(state.log, d)
                LOG.info("F %s: AI p=%.2f (%s) x%.2f vol x%.2f brake x%.2f -> combined x%.2f", d["as_of"], d["ai"]["percentile"], d["ai"]["zone"],
                         d["ai"]["multiplier"], d["vol"]["multiplier"], d["brake"]["multiplier"], d["combined"])
        except Exception:
            LOG.exception("F cycle failed; retrying")
        if once:return
        time.sleep(300)


if __name__ == "__main__":
    import sys
    run(once="--once" in sys.argv)
