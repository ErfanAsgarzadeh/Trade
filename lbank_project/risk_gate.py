"""Connects the F risk manager (risk_overlay.py) to the three bots. OFF by default.

Switch: runtime/risk_control.json {"enabled": false, "open_cuts": true, "max_age_hours": 36} (dashboard: Risk manager tab).
While OFF - or while F's decision file is missing, invalid or older than max_age_hours - every function here returns the
neutral value (multiplier 1, keep 100%), so the bots behave exactly as without F.
While ON:
  * entries: each bot multiplies its planned risk by its F multiplier (scale x AI x vol target x brake x losing streak);
    multiplier 0 (AI in the bad zone) = no new entry. Capped at 3.
  * open positions (if open_cuts): F's open-position part (AI multiplier x drawdown brake) is recorded per position at entry;
    when it later falls, the position is cut to new/old of its size (0 = closed), never increased. Positions that were
    already open when F was switched on are recorded at the first check and only cut on a later fall.
"""
from __future__ import annotations
import json, logging, math, os, sqlite3, threading, time
from pathlib import Path

LOG = logging.getLogger("risk_gate")
DEFAULT = {"enabled": False, "open_cuts": True, "max_age_hours": 36}
MAX_MULT = 3.0
_lock = threading.Lock()
_cache: dict = {}


def folder() -> Path:
    return Path(os.getenv("RISK_DIR", str(Path(os.getenv("BOT_DB", "data/lbank_ichimoku_bot.db")).resolve().parent)))


def read_control() -> dict:
    try:
        c = json.loads((folder() / "risk_control.json").read_text())
        return {**DEFAULT, **{k: c[k] for k in DEFAULT if k in c}}
    except Exception:
        return dict(DEFAULT)


def write_control(c: dict) -> dict:
    v = {**DEFAULT, **{k: c[k] for k in DEFAULT if k in c}}
    if not isinstance(v["enabled"], bool) or not isinstance(v["open_cuts"], bool):raise ValueError("enabled / open_cuts must be true or false")
    if not (isinstance(v["max_age_hours"], (int, float)) and 6 <= v["max_age_hours"] <= 72):raise ValueError("max_age_hours must be 6..72")
    p = folder() / "risk_control.json";p.parent.mkdir(parents=True, exist_ok=True);tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(v, indent=1));tmp.replace(p);_cache.clear();return v


def decision(now: float | None = None) -> dict | None:
    """F's current decision if F is ON and the decision is fresh and valid, else None."""
    c = read_control()
    if not c["enabled"]:return None
    p = folder() / "risk_overlay.json"
    try:
        m = p.stat().st_mtime
        if _cache.get("mtime") != m:_cache.update(mtime=m, d=json.loads(p.read_text()))
        d = _cache["d"]
        if (now or time.time()) - float(d["computed_at"]) > c["max_age_hours"] * 3600:
            LOG.warning("F decision is stale; using x1");return None
        for b in ("main", "c3", "pa"):
            if not math.isfinite(float(d["bots"][b]["multiplier"])):return None
        float(d["ai"]["multiplier"]);float(d["brake"]["multiplier"])
        return d
    except Exception as exc:
        LOG.warning("F decision unavailable (%s); using x1", exc);return None


def multiplier(bot: str, now: float | None = None) -> float:
    d = decision(now)
    if d is None:return 1.0
    return float(min(MAX_MULT, max(0.0, d["bots"][bot]["multiplier"])))


def open_part(d: dict) -> float:
    return max(0.0, float(d["ai"]["multiplier"]) * float(d["brake"]["multiplier"]))


def _db():
    p = folder() / "risk_gate.db";p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(p, timeout=30);db.execute("CREATE TABLE IF NOT EXISTS entries(bot TEXT,key TEXT,mult REAL,PRIMARY KEY(bot,key))");return db


def record(bot: str, key: str, now: float | None = None):
    """Called after a position opens: remember F's open-position multiplier at entry."""
    d = decision(now)
    if d is None:return
    with _lock, _db() as db:db.execute("INSERT OR REPLACE INTO entries VALUES(?,?,?)", (bot, str(key), open_part(d)))


def keep_fraction(bot: str, key: str, now: float | None = None) -> float:
    """Fraction of an open position to KEEP now (1 = no change). The caller cuts the rest and then calls mark()."""
    d = decision(now)
    if d is None or not read_control()["open_cuts"]:return 1.0
    cur = open_part(d)
    with _lock, _db() as db:
        row = db.execute("SELECT mult FROM entries WHERE bot=? AND key=?", (bot, str(key))).fetchone()
        if row is None:
            db.execute("INSERT INTO entries VALUES(?,?,?)", (bot, str(key), cur));return 1.0
    old = float(row[0])
    if old <= 0 or cur >= old - 1e-9:return 1.0
    return max(0.0, cur / old)


def mark(bot: str, key: str, now: float | None = None):
    d = decision(now)
    if d is None:return
    with _lock, _db() as db:db.execute("INSERT OR REPLACE INTO entries VALUES(?,?,?)", (bot, str(key), open_part(d)))


def forget(bot: str, key: str):
    try:
        with _lock, _db() as db:db.execute("DELETE FROM entries WHERE bot=? AND key=?", (bot, str(key)))
    except Exception:
        pass


VERSION = 1


def announce():
    """Written by the bot process at start: this bot build reads risk_gate (the dashboard shows whether it does)."""
    p = folder() / "risk_gate_bot.json";p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(version=VERSION, started=time.time(), pid=os.getpid())))


def bot_ready() -> bool:
    try:return json.loads((folder() / "risk_gate_bot.json").read_text()).get("version", 0) >= VERSION
    except Exception:return False


def status(now: float | None = None) -> dict:
    c = read_control();d = None;ready = bot_ready()
    try:d = json.loads((folder() / "risk_overlay.json").read_text())
    except Exception:pass
    age = (now or time.time()) - float(d["computed_at"]) if d else None
    active = c["enabled"] and decision(now) is not None and ready
    return dict(control=c, active=active, bot_ready=ready, decision_age_hours=None if age is None else age / 3600,
                multipliers={b: multiplier(b, now) for b in ("main", "c3", "pa")},
                reason=("F is applied to new entries" + (" and open positions" if c["open_cuts"] else "")) if active else
                ("switched off - the bots trade exactly as without F" if not c["enabled"] else
                 "switched on, but the running bot was started before F support - rebuild/restart lbank-bot once to apply it" if not ready else
                 "switched on, but F's decision is missing or stale - the bots use x1"))
