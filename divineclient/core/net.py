"""Shared HTTP plumbing: one pooled session, a short-lived result cache, real timeouts.

Two things used to make mod / resource-pack browsing feel slow:

* every request opened a brand new HTTPS connection (no session reuse), so a
  single search page paid a full TLS handshake per request - and a search page is
  1 request for the results plus one per project icon;
* nothing was remembered, so flipping the sort order to "Downloads" and back, or
  reopening the same mod's version list, went to the network again every time.

Everything here is safe to call from a worker thread and deliberately *not* from
the Tk main loop - see ui/imagedesk.py, which is what keeps the downloads off the
UI thread.
"""
import hashlib
import json
import os
import threading
import time

import requests
from requests.adapters import HTTPAdapter

USER_AGENT = "DivineClient/1.0 (Divine Dev Team launcher)"

# (connect, read). A metadata call must not hang the UI for half a minute.
API_TIMEOUT = (6.0, 12.0)
FILE_TIMEOUT = (10.0, 180.0)

CACHE_TTL = 300.0          # seconds; search results
PROJECT_TTL = 1800.0       # project pages change rarely
MAX_ENTRIES = 240          # ~a dozen searches' worth, then it rolls over

_lock = threading.RLock()
_session = None
_cache = {}                # key -> [expires_at, value]
_inflight = {}             # key -> threading.Event (avoid a thundering herd)


def session():
    """One shared Session for the whole process, with connection pooling.

    Pooling is the whole trick: Modrinth answers fast, but the handshake was
    being repeated ~20x per screen before.
    """
    global _session
    with _lock:
        if _session is None:
            s = requests.Session()
            adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20,
                                  max_retries=2, pool_block=False)
            s.mount("http://", adapter)
            s.mount("https://", adapter)
            s.headers.update({"User-Agent": USER_AGENT,
                              "Accept-Encoding": "gzip, deflate"})
            _session = s
        return _session


def cache_key(url, params=None):
    raw = url + "?" + json.dumps(params or {}, sort_keys=True, default=str)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def cache_get(key, allow_stale=False):
    with _lock:
        hit = _cache.get(key)
    if not hit:
        return None
    expires_at, value = hit
    if allow_stale or time.time() < expires_at:
        return value
    return None


def cache_put(key, value, ttl):
    with _lock:
        _cache[key] = [time.time() + ttl, value]
        if len(_cache) > MAX_ENTRIES:
            # roll over the oldest rather than letting it grow forever - entries
            # are small dicts, but a launcher session can browse a lot of mods
            oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[:len(_cache) // 3]
            for k, _v in oldest:
                _cache.pop(k, None)


def cache_clear():
    with _lock:
        _cache.clear()


def cached(func, ttl=CACHE_TTL, stale=True):
    """Memoise a network call by its arguments, with a TTL.

    `stale` means: if the request fails and we have *any* older value, hand that
    back instead of an error. Browsing cached searches offline is better than an
    exception in a label.
    """
    memo = {}

    def wrapper(*args, **kwargs):
        key = json.dumps([func.__name__, [str(a) for a in args],
                          sorted((k, str(v)) for k, v in kwargs.items())],
                         default=str)
        hit = memo.get(key)
        now = time.time()
        if hit:
            expires_at, value = hit
            if now < expires_at:
                return value
        try:
            value = func(*args, **kwargs)
        except Exception:
            if hit and stale:
                return hit[1]
            raise
        memo[key] = (now + ttl, value)
        if len(memo) > MAX_ENTRIES:
            for k in sorted(memo, key=lambda k: memo[k][0])[:len(memo) // 3]:
                memo.pop(k, None)
        return value

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    wrapper.cache = memo
    return wrapper


def get_json(url, params=None, timeout=API_TIMEOUT, ttl=None, key=None, headers=None):
    """GET + parse JSON. Cached for `ttl` seconds when a key (or ttl) is given."""
    use_key = key if key is not None else (cache_key(url, params) if ttl else None)
    if use_key and ttl:
        hit = cache_get(use_key, allow_stale=True)
        if hit is not None and time.time() < cache_entry_expiry(use_key):
            return hit
    r = session().get(url, params=params, timeout=timeout, headers=headers)
    r.raise_for_status()
    data = r.json()
    if use_key and ttl:
        cache_put(use_key, data, ttl)
    return data


def cache_entry_expiry(key):
    with _lock:
        hit = _cache.get(key)
        return hit[0] if hit else 0


def cached_path(url, cache_dir, ext=None):
    """Where `url` would be cached on disk (no download)."""
    name = hashlib.md5(url.encode("utf-8")).hexdigest()
    if ext is None:
        ext = os.path.splitext(url.split("?")[0])[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            ext = ".png"
    return os.path.join(cache_dir, name + ext)


def download(url, dest, timeout=FILE_TIMEOUT, expected_sha256=None, headers=None):
    """Download `url` to `dest` atomically. Returns dest, or None on failure.

    An existing file is left alone (that is the whole point of the cache), and a
    half-written `.part` is never mistaken for a finished file.
    """
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"
    with _lock:
        ev = _inflight.get(dest)
        if ev is not None:
            other = True
        else:
            _inflight[dest] = ev = threading.Event()
            other = False
    if other:
        # another thread is already fetching this exact file: wait for it instead
        # of downloading it twice
        ev.wait(timeout=timeout[1] if isinstance(timeout, tuple) else 120)
        return dest if os.path.exists(dest) else None
    try:
        with session().get(url, stream=True, timeout=timeout, headers=headers) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
        if expected_sha256:
            import hashlib as _h
            h = _h.sha256()
            with open(tmp, "rb") as f:
                for blk in iter(lambda: f.read(1 << 16), b""):
                    h.update(blk)
            if h.hexdigest().lower() != expected_sha256.lower():
                os.remove(tmp)
                raise IOError("downloaded file did not match its expected hash")
        os.replace(tmp, dest)
        return dest
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return None
    finally:
        with _lock:
            _inflight.pop(dest, None)
        ev.set()
