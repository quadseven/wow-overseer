"""A short-lived, single-flight cache for expensive GET builds.

WHY. A cold page load asks for several reads at once, and some of them build
the same thing: /api/v2/roster and /api/v2/stuck are one roster build, and
every open page polls the same handful of reads. Without this, N callers
arriving together make N identical builds against the realm, and each one is
slower for the others' load.

WHAT IT DOES. `get(key, build)` returns what `build()` returned for `key` less
than `ttl` seconds ago, or calls `build()`. Callers that arrive while a build
for the same key is running wait for it and share its result (single flight).

WHAT IT NEVER DOES:
- keep a failure. A build that raises is not stored, and a caller that waited
  on it builds for itself instead, so an error is never handed to anyone who
  did not cause it;
- grow without bound. Expired entries are dropped on every store, and past
  `max_entries` the oldest entry goes.

STALE WINDOW. A cache built with `stale` seconds (or a `get` given its own
`ttl` and `stale`) also keeps an entry for that long past its lifetime. A
caller inside that window is answered at once with the old value, and one
background build refreshes it; callers that arrive meanwhile get the old value
too. A refresh that fails keeps the old value and is tried again by the next
caller. Beyond the window a caller waits for a build, as before. `stale` is 0
by default, so a cache without it behaves as it always did.

The clock is injectable so the expiry is tested without sleeping.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


class _Flight:
    """One build in progress: waiters block on `done`."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.ok = False
        self.value: Any = None


class ReadCache:
    def __init__(
        self,
        ttl: float,
        max_entries: int = 64,
        clock: Callable[[], float] = time.monotonic,
        stale: float = 0.0,
    ) -> None:
        self.ttl = ttl
        self.stale = stale
        self.max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict = {}  # key -> (fresh_until, keep_until, value)
        self._flights: dict = {}  # key -> _Flight

    def get(
        self,
        key: str,
        build: Callable[[], Any],
        ttl: float | None = None,
        stale: float | None = None,
    ) -> Any:
        """build()'s value for `key`, from the last `ttl` seconds when there is one.

        `ttl` and `stale` default to the cache's own; a path may pass its own.
        """
        ttl = self.ttl if ttl is None else ttl
        stale = self.stale if stale is None else stale
        refresh = False
        with self._lock:
            now = self._clock()
            hit = self._entries.get(key)
            if hit is not None and now < hit[0]:
                return hit[2]
            flight = self._flights.get(key)
            if hit is not None and now < hit[1]:
                # Inside the stale window: answer now, refresh once.
                if flight is not None:
                    return hit[2]
                flight = self._flights[key] = _Flight()
                refresh = True
                leader = False
            else:
                leader = flight is None
                if leader:
                    flight = self._flights[key] = _Flight()
        if refresh:
            threading.Thread(
                target=self._refresh, args=(key, build, ttl, stale, flight), daemon=True
            ).start()
            return hit[2]
        if not leader:
            flight.done.wait()
            if flight.ok:
                return flight.value
            # The build this caller waited on failed: try once more on its
            # own, exactly as it would have without the cache.
            return build()
        try:
            value = build()
            flight.ok, flight.value = True, value
            self._store(key, value, ttl, stale)
            return value
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.done.set()

    def _refresh(self, key, build, ttl, stale, flight) -> None:
        """One background build for a stale entry. A failure keeps the old one."""
        try:
            value = build()
            flight.ok, flight.value = True, value
            self._store(key, value, ttl, stale)
        except Exception:
            pass
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.done.set()

    def _store(self, key: str, value: Any, ttl: float, stale: float = 0.0) -> None:
        with self._lock:
            now = self._clock()
            for k in [k for k, e in self._entries.items() if e[1] <= now]:
                del self._entries[k]
            self._entries.pop(key, None)
            while len(self._entries) >= self.max_entries:
                del self._entries[next(iter(self._entries))]
            if ttl > 0:
                self._entries[key] = (now + ttl, now + ttl + max(stale, 0.0), value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
