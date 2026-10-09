"""The /api/v2 endpoints: new reads the operations app needs.

Every endpoint is a module in this package with a ROUTES table,
`{"/api/v2/<name>": handler}`. A handler is `handler(query, ctx) -> (status,
payload)`: `query` is parse_qs's dict, `ctx` is the map server's context (a
read-only database connection and the existing payload builders), and the
payload is plain JSON data. The map server sends it with the same caching as
every other GET (ETag, revalidated each time).

The modules are found by listing this package, so a new endpoint is a new
file: no shared table to edit, and two endpoints written side by side never
touch the same line. Two modules claiming one path is an error at import,
not a silent override.

Read-only, all of it: nothing under /api/v2 writes to the realm.
"""

from __future__ import annotations

import importlib
import pkgutil

PREFIX = "/api/v2/"


def _collect() -> dict:
    routes: dict = {}
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(__name__ + "." + info.name)
        for path, handler in getattr(module, "ROUTES", {}).items():
            if not path.startswith(PREFIX):
                raise ValueError(f"{info.name}: {path} is not under {PREFIX}")
            if path in routes:
                raise ValueError(f"{path} is claimed twice ({info.name})")
            routes[path] = handler
    return routes


ROUTES = _collect()


def handle(path: str, query: dict, ctx) -> tuple[int, dict]:
    """(status, payload) for one GET under /api/v2/."""
    handler = ROUTES.get(path)
    if handler is None:
        return 404, {"error": "no such endpoint", "endpoints": sorted(ROUTES)}
    return handler(query, ctx)
