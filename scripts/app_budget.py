"""The app's performance budget: numbers measured from the files, held in
tests/fixtures/app_budgets.json.

The app's first load is fast because its boot path is small: few modules in a
shallow import chain, a few compressed kilobytes, no third-party host and a
handful of requests. `measure` reads those numbers from the files on disk (no
browser) and `check` compares them with the committed limits.
tests/test_app_budget.py runs both, so CI fails when one grows past its limit.

Raising a limit is a visible act: the budget file lists every setting of a
limit under "raises" with its reason, and `unexplained` names a limit whose
newest entry there does not match it.

    python3 scripts/app_budget.py    # the numbers next to the limits; exit 1
                                     # on any problem check or unexplained finds
"""

from __future__ import annotations

import gzip
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import appbuild  # noqa: E402

BUDGET_FILE = os.path.join("tests", "fixtures", "app_budgets.json")

# How map_server._gzipped sends a static script or stylesheet: as it is below
# GZIP_MIN_BYTES, else gzipped at level 9. tests/test_app_budget.py pins both
# against map_server.
GZIP_MIN_BYTES = 4096
GZIP_STATIC_LEVEL = 9

_APP_REF = re.compile(
    r"""<(?:link|script)\b[^>]*?\b(?:href|src)="__OVERSEER_BASE__/app/__OVERSEER_BUILD__/([^"]+)"[^>]*>"""
)
_CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""")
_HOST = re.compile(r"""https?://([A-Za-z0-9.-]+)""")
# An XML namespace names no server and fetches nothing.
_NAMESPACE_HOSTS = {"www.w3.org"}


def _read(root: str, rel: str) -> bytes:
    with open(os.path.join(root, *rel.split("/")), "rb") as f:
        return f.read()


def _page(root: str) -> str:
    return _read(root, "index.html").decode("utf-8")


def stylesheets(root: str) -> list[str]:
    """The app stylesheets the page links, as paths under app/."""
    out = []
    for tag in _APP_REF.finditer(_page(root)):
        if 'rel="stylesheet"' in tag.group(0) and tag.group(1) not in out:
            out.append(tag.group(1))
    return out


def font_files(root: str) -> list[str]:
    """The font files the linked stylesheets name, as paths under app/."""
    out = []
    for sheet in stylesheets(root):
        text = _read(root, "app/" + sheet).decode("utf-8")
        for url in _CSS_URL.findall(text):
            if url.startswith(("data:", "http://", "https://")):
                continue
            rel = os.path.normpath(os.path.join(os.path.dirname(sheet), url))
            rel = rel.replace(os.sep, "/")
            if rel not in out:
                out.append(rel)
    return out


def sent_bytes(body: bytes) -> int:
    """The bytes the server sends for a static script or stylesheet."""
    if len(body) < GZIP_MIN_BYTES:
        return len(body)
    return len(gzip.compress(body, GZIP_STATIC_LEVEL, mtime=0))


def boot_sizes(root: str) -> dict[str, int]:
    """Sent bytes per boot file: every module of the boot graph and every
    stylesheet the page links, as paths under app/."""
    files = appbuild.boot_graph(root) + stylesheets(root)
    return {rel: sent_bytes(_read(root, "app/" + rel)) for rel in dict.fromkeys(files)}


def third_party_hosts(root: str) -> list[str]:
    """The hosts the page and its stylesheets name, other than namespaces."""
    texts = [_page(root)]
    texts += [_read(root, "app/" + s).decode("utf-8") for s in stylesheets(root)]
    hosts = {host for text in texts for host in _HOST.findall(text)}
    return sorted(hosts - _NAMESPACE_HOSTS)


def measure(root: str) -> dict[str, int]:
    """The numbers the budget limits, measured from the files under `root`.

    `boot_requests` counts the page, its stylesheets, the boot graph's
    modules and the fonts those stylesheets name: what a cold load fetches
    before the first draw, data reads aside.
    """
    graph = appbuild.boot_graph(root)
    sheets = stylesheets(root)
    fonts = font_files(root)
    return {
        "boot_sent_bytes": sum(boot_sizes(root).values()),
        "boot_modules": len(graph),
        "import_depth": len(appbuild.deepest_chain(root)),
        "third_party_hosts": len(third_party_hosts(root)),
        "boot_requests": 1 + len(set(graph) | set(sheets) | set(fonts)),
    }


def check(
    measured: dict[str, int], limits: dict[str, int], root: str | None = None
) -> list[str]:
    """One sentence per number over its limit or without one; empty when
    every number is inside the budget."""
    problems = []
    for name, value in measured.items():
        if name not in limits:
            problems.append(
                "%s is %s and %s has no limit for it." % (name, value, BUDGET_FILE)
            )
            continue
        if value <= limits[name]:
            continue
        text = "%s is %s, over its limit of %s." % (name, value, limits[name])
        if name == "boot_sent_bytes" and root:
            biggest = max(boot_sizes(root).items(), key=lambda kv: kv[1])
            text += " The biggest file is app/%s (%d bytes)." % biggest
        if name == "third_party_hosts" and root:
            text += " Hosts: %s." % ", ".join(third_party_hosts(root))
        if name == "import_depth" and root:
            text += " Chain: %s." % " > ".join(appbuild.deepest_chain(root))
        text += (
            " Make the boot path smaller, or raise the limit in %s with an entry"
            ' under "raises" saying why.' % BUDGET_FILE
        )
        problems.append(text)
    return problems


def unexplained(boot: dict) -> list[str]:
    """One sentence per limit whose newest entry under "raises" is missing,
    gives another number, or carries no reason."""
    newest: dict[str, dict] = {}
    for entry in boot.get("raises", []):
        newest[entry.get("name")] = entry
    problems = []
    for name, limit in boot.get("limits", {}).items():
        entry = newest.get(name)
        if entry is None:
            problems.append('%s has no entry under "raises".' % name)
        elif entry.get("limit") != limit:
            problems.append(
                '%s is %s but its newest entry under "raises" says %s; add an entry'
                " with the reason for the change." % (name, limit, entry.get("limit"))
            )
        elif not str(entry.get("reason", "")).strip():
            problems.append('%s\'s newest entry under "raises" gives no reason.' % name)
    return problems


def load(root: str) -> dict:
    with open(os.path.join(root, BUDGET_FILE), encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    root = str(ROOT)
    boot = load(root)["boot"]
    limits = boot["limits"]
    measured = measure(root)
    for name, value in measured.items():
        print("%-18s %8s  (limit %s)" % (name, value, limits.get(name, "none")))
    problems = check(measured, limits, root) + unexplained(boot)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
