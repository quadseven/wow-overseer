"""What a /api/v2 handler gets from the map server.

`connect()` opens a database connection exactly as the map server's own
endpoints do. `server` is the map_server module, so a v2 endpoint can reuse an
existing payload builder instead of copying it. Handlers must only read.
`shared` is the server's short-lived build cache (readcache.ReadCache), or
None, for a build two endpoints have in common; without it, build every time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Context:
    connect: Callable[[], Any]
    server: Any
    shared: Any = None
