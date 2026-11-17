"""Which build of the operations app this server would serve now.

A phone keeps a tab open for hours, and the open page goes on running the
scripts it loaded. `page` in /api/realm fingerprints index.html alone, but a
deploy that changes only an app/*.js, app/*.css or app/*.woff2 file leaves
index.html as it was, so a page comparing that value never learns its code is
old.

The build fingerprint covers the page and every script, stylesheet and font
under app/, by path and content. The page is served with the build it belongs to
(BUILD_PLACEHOLDER in index.html), /api/realm reports the build the server
holds now as `app_build`, and app/update.js offers a refresh when the two
differ.

Each call lists the files and stats them; their contents are read and
hashed again only when a file was added or removed or one changed its size
or modification time, so the realm poll does not hash forty files each time.
"""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import os
import re

BUILD_PLACEHOLDER = "__OVERSEER_BUILD__"
SHELL_PLACEHOLDER = "__OVERSEER_SHELL__"
APP_KINDS = (".js", ".css", ".woff2")
_APP_LINK_PREFIX = re.compile(r"/app/(?:__OVERSEER_BUILD__|[0-9a-f]{12})/(.+)$")

_memo: dict[str, tuple[tuple, str]] = {}


def _app_files(root: str) -> list[str]:
    """index.html and every app script, style and woff2 font, sorted."""
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


class _ShellLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        by_name = {k.lower(): (v or "") for k, v in attrs}
        rels = set(by_name.get("rel", "").split())
        if not rels.intersection(("stylesheet", "modulepreload")):
            return
        href = by_name.get("href", "")
        matched = _APP_LINK_PREFIX.search(href)
        if not matched:
            return
        rel_path = matched.group(1)
        if rel_path not in self.assets:
            self.assets.append(rel_path)


def shell_assets(html: bytes) -> list[str]:
    """Relative paths under app/<build>/ from the page's style and modulepreload links."""
    parser = _ShellLinkParser()
    parser.feed(html.decode("utf-8"))
    parser.close()
    return parser.assets


def stamp_worker(sw: bytes, build: str, index_html: bytes) -> bytes:
    """Stamp build fingerprint and precache shell list into sw.js."""
    assets = json.dumps(shell_assets(index_html)).encode("utf-8")
    return stamp(sw, build).replace(SHELL_PLACEHOLDER.encode(), assets)
