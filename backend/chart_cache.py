"""
Simple in-memory TTL cache for generated chart PNGs.
"""
from datetime import datetime, timedelta, timezone
from threading import Lock

_cache: dict[str, tuple[bytes, datetime]] = {}
_lock  = Lock()
TTL    = timedelta(minutes=15)


def get(key: str) -> bytes | None:
    with _lock:
        entry = _cache.get(key)
    if entry:
        data, ts = entry
        if datetime.now(timezone.utc) - ts < TTL:
            return data
        with _lock:
            _cache.pop(key, None)
    return None


def put(key: str, data: bytes) -> None:
    with _lock:
        _cache[key] = (data, datetime.now(timezone.utc))


def invalidate(city: str) -> None:
    """Remove all cached charts for a given city."""
    prefix = f"{city}:"
    with _lock:
        for k in [k for k in list(_cache) if k.startswith(prefix)]:
            del _cache[k]
