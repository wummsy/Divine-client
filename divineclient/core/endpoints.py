"""Where the Divine services live, and how the launcher survives a DNS hiccup.

The website and the social backend are now served from https://divineclient.wispbyte.org
(one origin: site, news, Discord link pages and the friends API). Older installs
have the raw `http://78.154.103.46:10230` address saved in their config, and the
box still answers on it, so that address stays as a *fallback*: candidates() hands
back the domain first and the legacy address second, and a request only falls
through when the domain genuinely cannot be reached (resolver trouble, a network
that blocks it, or the certificate not being live yet). Nothing else changes for
people who upgraded.

A base set in Settings always wins - it is a deliberate override, not a leftover.
"""
import threading

SITE = "https://divineclient.wispbyte.org"
BASE_URL = SITE

# Kept only so an install whose config still points at the old address (or a
# network where DNS for wispbyte.org is broken) keeps working.
LEGACY = [
    "http://78.154.103.46:10230",
    "http://127.0.0.1:10230",
    "http://localhost:10230",
]

# Anything in here counts as "the user never chose this, it came from an older
# default" - so it is replaced by the current SITE + fallback chain.
INHERITED = {
    "http://78.154.103.46:10230",
    "https://devwummsy.site.je",
    "http://devwummsy.site.je",
}

_lock = threading.Lock()
_last_good = None


def _clean(base):
    return (base or "").strip().rstrip("/")


def current_base(config=None):
    """What to show in Settings: the working base, or the canonical site."""
    with _lock:
        if _last_good:
            return _last_good
    stored = ""
    if config is not None:
        try:
            stored = _clean(config.get("friends_api_base", ""))
        except Exception:
            stored = ""
    if stored and stored.lower() not in INHERITED:
        return stored
    return SITE


def candidates(config=None):
    """Bases to try, in order."""
    out = []
    stored = ""
    if config is not None:
        try:
            stored = _clean(config.get("friends_api_base", ""))
        except Exception:
            stored = ""
    if stored and stored.lower() not in INHERITED:
        out.append(stored)
    for base in [SITE] + list(LEGACY):
        if base not in out:
            out.append(base)
    with _lock:
        good = _last_good
    if not stored and good and good in out and good != out[0]:
        out.remove(good)
        out.insert(0, good)
    return out


def mark_good(base):
    global _last_good
    with _lock:
        _last_good = _clean(base)


def site_url(path=""):
    """An absolute website URL (used for links we hand to a browser)."""
    return SITE + ("/" + path.lstrip("/") if path else "")


def get_json(config, path, timeout=15, params=None, session=None):
    """GET JSON from the first base that answers. Returns None if none do."""
    import requests
    getter = session.get if session is not None else requests.get
    for base in candidates(config):
        try:
            r = getter(base + path, params=params, timeout=timeout)
            if not r.ok:
                continue
            mark_good(base)
            return r.json()
        except Exception:
            continue
    return None


def post_json(config, path, data=None, timeout=5, session=None):
    """POST JSON to the first base that answers. Returns (response_json, status_code, ok)."""
    import requests
    poster = session.post if session is not None else requests.post
    for base in candidates(config):
        try:
            r = poster(base + path, json=data or {}, timeout=timeout)
            mark_good(base)
            try:
                rj = r.json()
            except Exception:
                rj = {"text": r.text}
            return rj, r.status_code, r.ok
        except Exception:
            continue
    return None, 0, False


def get_json_response(config, path, params=None, timeout=5, session=None):
    """GET JSON from the first base that answers. Returns (response_json, status_code, ok)."""
    import requests
    getter = session.get if session is not None else requests.get
    for base in candidates(config):
        try:
            r = getter(base + path, params=params, timeout=timeout)
            mark_good(base)
            try:
                rj = r.json()
            except Exception:
                rj = {"text": r.text}
            return rj, r.status_code, r.ok
        except Exception:
            continue
    return None, 0, False
