"""Which build of the operations app this server would serve now.

A phone keeps a tab open for hours, and the open page goes on running the
scripts it loaded. `page` in /api/realm fingerprints index.html alone, but a
deploy that changes only app/*.js or app/*.css leaves index.html as it was,
so a page comparing that value never learns its code is old.

The build fingerprint covers the page and every script and stylesheet under
app/, by path and content. The page is served with the build it belongs to
(BUILD_PLACEHOLDER in index.html), /api/realm reports the build the server
holds now as `app_build`, and app/update.js offers a refresh when the two
differ.

The fingerprint is kept until a file under app/ changes its size or its
modification time, so the realm poll does not read forty files each time.
"""

from __future__ import annotations

import hashlib
import os

BUILD_PLACEHOLDER = "__OVERSEER_BUILD__"
APP_KINDS = (".js", ".css")

_memo: dict[str, tuple[tuple, str]] = {}


def _app_files(root: str) -> list[str]:
    """index.html and every .js and .css file under app/, relative to root, sorted."""
    out = ["index.html"]
    app = os.path.join(root, "app")
    for here, dirs, files in os.walk(app):
        dirs.sort()
        for name in files:
            if name.endswith(APP_KINDS):
                out.append(os.path.relpath(os.path.join(here, name), root))
    return sorted(out)


def _signature(root: str, files: list[str]) -> tuple:
    sig = []
    for rel in files:
        try:
            st = os.stat(os.path.join(root, rel))
        except OSError:
            sig.append((rel, -1, -1))
            continue
        sig.append((rel, st.st_size, st.st_mtime_ns))
    return tuple(sig)


def fingerprint(root: str) -> str:
    """Twelve hex characters naming the app's files as they sit on disk now."""
    files = _app_files(root)
    sig = _signature(root, files)
    kept = _memo.get(root)
    if kept is not None and kept[0] == sig:
        return kept[1]
    digest = hashlib.sha256()
    for rel in files:
        digest.update(rel.replace(os.sep, "/").encode() + b"\0")
        try:
            with open(os.path.join(root, rel), "rb") as f:
                digest.update(f.read())
        except OSError:
            digest.update(b"missing")
        digest.update(b"\0")
    build = digest.hexdigest()[:12]
    _memo[root] = (sig, build)
    return build


def stamp(html: bytes, build: str) -> bytes:
    """The page with its build substituted in, where it asks for one."""
    return html.replace(BUILD_PLACEHOLDER.encode(), build.encode())
