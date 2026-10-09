"""What a /api/v2 handler gets from the map server.

`connect()` opens a database connection exactly as the map server's own
endpoints do. `server` is the map_server module, so a v2 endpoint can reuse an
existing payload builder instead of copying it. Handlers must only read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Context:
    connect: Callable[[], Any]
    server: Any
