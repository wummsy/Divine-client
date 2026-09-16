"""Playtime: how long each instance has actually been open in a game window.

Kept per instance, inside the instance folder, so it travels with the instance when it is
exported, imported or moved - and so deleting the instance (``InstanceManager.delete``,
which takes the folder with it) never leaves an orphan number behind in a global file.

The launcher is the only thing that can know this: it starts the process and it reaps it.
So the rule is boring on purpose - one entry per *process*, added when the process is
gone, with the elapsed time measured from when the launcher spawned it. A game that is
force-killed still counts; a game that never started counts zero because nothing is
recorded until a process exists.
"""
import json
import os
import time

FILE = "divine-playtime.json"

MAX_SESSIONS = 400          # a session per launch; nobody needs the ten-thousandth

_active_sessions = {}


def path_for(inst):
    return os.path.join(inst.game_dir, FILE)


def record_session_start(inst_or_id):
    """Mark the beginning of an active game launch session."""
    iid = inst_or_id if isinstance(inst_or_id, str) else getattr(inst_or_id, "id", str(inst_or_id))
    _active_sessions[iid] = time.time()


def record_session_end(inst_or_id, inst=None):
    """Mark the end of an active game launch session and compute total duration."""
    iid = inst_or_id if isinstance(inst_or_id, str) else getattr(inst_or_id, "id", str(inst_or_id))
    start_time = _active_sessions.pop(iid, None)
    if start_time:
        elapsed = int(time.time() - start_time)
        if inst is not None:
            add(inst, elapsed)
        return elapsed
    return 0


def read(inst):
    """``{"total": int, "sessions": [..]}`` - never raises, junk reads as no history."""
    try:
        with open(path_for(inst), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError
        total = int(data.get("total") or 0)
        sessions = [s for s in (data.get("sessions") or [])
                    if isinstance(s, dict) and int(s.get("seconds") or 0) > 0]
        return {"total": total, "sessions": sessions[-MAX_SESSIONS:]}
    except Exception:
        return {"total": 0, "sessions": []}


def write(inst, data):
    tmp = path_for(inst) + ".tmp"
    try:
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"total": int(data.get("total") or 0),
                       "sessions": list(data.get("sessions") or [])[-MAX_SESSIONS:],
                       "updated": int(time.time())}, f, indent=2)
        os.replace(tmp, path_for(inst))
        return True
    except OSError:
        return False


def add(inst, seconds, at=None, label=""):
    """Record one finished session. Returns the new total, or None if it was refused.

    Negative, zero and absurd values are dropped: a clock that jumped (a laptop woken from
    sleep with the game still open) must not turn into "played 61329 h", which is the kind
    of number that makes people stop trusting the whole panel.
    """
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return None
    if seconds <= 0 or seconds > 60 * 60 * 24 * 3:
        return None
    data = read(inst)
    entry = {"at": int(at or time.time()), "seconds": seconds}
    if label:
        entry["label"] = str(label)[:60]
    data["sessions"].append(entry)
    data["total"] = int(data["total"]) + seconds
    if not write(inst, data):
        return None
    return data["total"]


def total(inst):
    return read(inst)["total"]


def last_played(inst):
    """The timestamp of the last finished session, or 0."""
    sessions = read(inst)["sessions"]
    return int(sessions[-1]["at"]) if sessions else 0


def recent(inst, days=7):
    """Seconds played in the last ``days`` days - used for "this week" lines."""
    cut = time.time() - days * 86400
    return sum(int(s.get("seconds") or 0) for s in read(inst)["sessions"]
               if int(s.get("at") or 0) >= cut)


def human(seconds):
    """'48 s' / '12 min' / '3 h 05 m' / '2 d 4 h' - one glance, no chart."""
    try:
        n = int(seconds or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "never played"
    m, s = divmod(n, 60)
    if n < 60:
        return "%d s" % s
    if m < 60:
        return "%d min" % m
    h, m = divmod(m, 60)
    if h < 24:
        return "%d h %02d m" % (h, m)
    d, h = divmod(h, 24)
    return "%d d %d h" % (d, h)


def since(ts):
    """'today', 'yesterday', '4 days ago', 'in 3 s' - never a raw date for recent things."""
    if not ts:
        return "never"
    days = int((time.time() - ts) // 86400)
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return "%d days ago" % days
    if days < 365:
        months = max(1, days // 30)
        return "%d month%s ago" % (months, "" if months == 1 else "s")
    years = max(1, days // 365)
    return "%d year%s ago" % (years, "" if years == 1 else "s")
