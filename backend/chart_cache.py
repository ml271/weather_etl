"""
In-Memory TTL Cache for Generated Chart PNGs
=============================================

Provides a simple thread-safe key/value store for Matplotlib-rendered PNG
bytes. Because chart generation is CPU-intensive (Matplotlib renders in-process
at 100 dpi), caching prevents redundant re-renders on every dashboard page
load or refresh.

Cache design:
  - Storage: plain Python ``dict`` keyed by a string identifier.
  - TTL: 15 minutes from the time of insertion. Stale entries are evicted
    lazily on the next ``get()`` call rather than via a background thread.
  - Thread safety: a single ``threading.Lock`` guards all read and write
    operations so the cache is safe for multi-threaded Uvicorn workers.
  - Invalidation: the ``invalidate()`` function removes all entries whose
    key starts with a given city prefix. It is called by the Airflow load
    task after a successful data import and by the ``POST /charts/cache-clear``
    endpoint.

Cache key conventions (set by callers in main.py):
  - Hourly plot:  ``"<city>:hourly:<hours>:st<soil_t>:sm<soil_m>"``
  - Day detail:   ``"<city>:day:<YYYY-MM-DD>"``

Author: <project maintainer>
"""

from datetime import datetime, timedelta, timezone
from threading import Lock

# Internal store: maps cache_key → (png_bytes, insertion_timestamp_utc)
_cache: dict[str, tuple[bytes, datetime]] = {}

# Single lock protecting all mutations to _cache. Using a module-level lock
# is safe because chart_cache is imported once and shared across all threads.
_lock  = Lock()

# Time-to-live: cached images are considered stale after 15 minutes.
# This matches the Airflow ETL schedule (@hourly) so charts are always at most
# one pipeline run behind.
TTL    = timedelta(minutes=15)


def get(key: str) -> bytes | None:
    """Return cached PNG bytes for ``key`` if they exist and are not stale.

    Performs a lazy eviction: if the entry exists but its TTL has expired it
    is removed from the cache and ``None`` is returned, prompting the caller
    to regenerate and re-insert the chart.

    Args:
        key: Cache key to look up (see module docstring for naming conventions).

    Returns:
        The cached PNG bytes if the entry exists and is within its TTL, or
        ``None`` if the key is absent or the entry has expired.
    """
    with _lock:
        entry = _cache.get(key)
    if entry:
        data, ts = entry
        if datetime.now(timezone.utc) - ts < TTL:
            return data
        # Entry has expired — evict it so the next request regenerates the chart
        with _lock:
            _cache.pop(key, None)
    return None


def put(key: str, data: bytes) -> None:
    """Insert or overwrite a cache entry with the current UTC timestamp.

    Args:
        key: Cache key under which to store the bytes.
        data: PNG image bytes produced by Matplotlib's ``savefig()``.
    """
    with _lock:
        _cache[key] = (data, datetime.now(timezone.utc))


def invalidate(city: str) -> None:
    """Remove all cached chart entries for a given city.

    Scans all keys in the cache and deletes those whose prefix matches
    ``"<city>:"``. This is intentionally a prefix match so that both
    ``hourly`` and ``day`` chart variants are cleared in a single call.

    Args:
        city: The city name whose cache entries should be invalidated.
            Must match the city prefix used when the entry was inserted.
    """
    prefix = f"{city}:"
    with _lock:
        # Build the list of matching keys first to avoid mutating the dict
        # while iterating over it.
        for k in [k for k in list(_cache) if k.startswith(prefix)]:
            del _cache[k]
