"""What a /api/v2 handler gets from the map server.

`read` is this request's realm reader (realmread): opened once per request by
the map server, connected on its first read and closed when the handler
returns. Handlers read only through it: `read.rows()` for a table a realm may
not have yet, `read.must()` for one every realm has. `server` is the
map_server module, so a v2 endpoint can reuse an existing payload builder
instead of copying it. Handlers must only read. `shared` is the server's
short-lived build cache (readcache.ReadCache), or None, for a build two
endpoints have in common; without it, build every time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Context:
    read: Any
    server: Any
    shared: Any = None
