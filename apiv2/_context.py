"""What a /api/v2 handler gets from the map server.

`read` is this request's realm reader (realmread, S2): opened once per request
by the map server, connected on its first read and closed when the handler
returns. Handlers read only through it: `read.rows()` for a table a realm may
not have yet, `read.must()` for one every realm has. `families` (S3) is the
map server's `families.Families`: who a read may answer about, the family
guilds, and every family name. `presence` (#718) is a bound reader,
`presence(names) -> {name: {"online", "life", "fresh_at"}}`, for the members
in the world right now. `server` is the map_server module, kept as a narrow
escape hatch for the world data (maps, keywords, catalogue, ...) that is not
reader, families or presence; handlers must only read through it. `shared` is
the server's short-lived build cache (readcache.ReadCache), or None, for a
build two endpoints have in common; without it, build every time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import realmread

# presence(names) -> {name: {"online": bool, "life": str | None, "fresh_at": int | None}}
Presence = Callable[[list[str]], dict]


@dataclass(frozen=True)
class Context:
    # rows() for a table a realm may not have yet (a schema gap reads as no
    # rows); must() for one every realm has (a schema gap raises realmread.Gap).
    read: realmread.Reader
    server: Any
    families: Any = None
    presence: Presence = None
    shared: Any = None
