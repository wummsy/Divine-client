"""Latest-news feed for the home page.

Tries the Divine server first (/api/news); if that's unreachable it falls back to
a small set of built-in entries so the panel is never empty. Results are cached
briefly in memory so switching pages doesn't re-hit the network every time.
"""
import time

_cache = None
_cache_at = 0
_CACHE_TTL = 300  # seconds

# Shown when the server can't be reached. Kept short and factual.
_BUILTIN = [
    {
        "title": "Divine Client v5.0.0 Release",
        "tag": "Release",
        "body": "High-performance Minecraft launcher featuring full version support from 1.0 to 26.2, dynamic instance management, dedicated server controls, and sub-user collaboration.",
    },
    {
        "title": "Integrated Server Hosting",
        "tag": "Feature",
        "body": "Deploy PaperMC, Purpur, Fabric, and Vanilla dedicated servers with 1-click cloud tunneling and live console controls.",
    },
    {
        "title": "Performance & Mod Architecture",
        "tag": "Engine",
        "body": "Optimized runtime memory allocation, Sodium and Iris compatibility, and isolated game directories for smooth gameplay.",
    },
]


def get_news(config, force=False):
    """Return a list of news dicts: {title, tag, body, url?}."""
    global _cache, _cache_at
    now = time.time()
    if not force and _cache is not None and (now - _cache_at) < _CACHE_TTL:
        return _cache
    items = _fetch(config)
    if items:
        _cache = items
        _cache_at = now
        return items
    # keep whatever we had, else built-ins
    return _cache if _cache is not None else list(_BUILTIN)


def _fetch(config):
    try:
        from . import endpoints
        # same address chain as the friends API: canonical site first, legacy
        # ip:port only if the domain could not be reached at all
        data = endpoints.get_json(config, "/api/news", timeout=12)
        if data is None:
            return None
        items = data.get("news") if isinstance(data, dict) else data
        out = []
        for it in (items or []):
            if not isinstance(it, dict):
                continue
            out.append({
                "title": it.get("title", "Update"),
                "tag": it.get("tag", "News"),
                "body": it.get("body", ""),
                "url": it.get("url", ""),
            })
        return out or None
    except Exception:
        return None
