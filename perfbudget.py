"""The performance budget: numbers measured from the files, held in perf-budget.json.

The app's first load is fast because its boot path is small: few modules in a
shallow chain, a few compressed kilobytes, no third-party host, a handful of
requests. This module measures those numbers from the files on disk (no
browser), and `check` compares them with the committed limits. The test that
runs it, tests/test_perf_budget.py, is how CI holds the line.

Raising a limit is allowed and is a visible act: perf-budget.json lists every
change in "raises" with the reason, and the test fails when a limit differs
from the last raise recorded for it.

    python3 perfbudget.py      # print the measured numbers next to the limits
"""

import gzip
import json
import os
import re
import sys

import appbuild

BUDGET_FILE = "perf-budget.json"

_BASE = "__OVERSEER_BASE__/app/__OVERSEER_BUILD__/"
_REF = re.compile(
    r"""<(?:link|script)\b[^>]*?\b(?:href|src)="%s([^"]+)"[^>]*>""" % re.escape(_BASE)
)
_HOST = re.compile(r"""https?://([A-Za-z0-9.-]+)""")
# An XML namespace names no server and fetches nothing.
_NAMESPACE_HOSTS = {"www.w3.org"}
# The level the server compresses static files at (map_server._gzipped).
GZIP_LEVEL = 5


def _read(root, rel):
    with open(os.path.join(root, rel), "rb") as f:
        return f.read()


def _page(root):
    return _read(root, "index.html").decode("utf-8")


def _refs(html):
    """(kind, path under app/) for each local asset the page names at boot."""
    out = []
    for tag in _REF.finditer(html):
        text = tag.group(0)
        path = tag.group(1)
        if 'rel="stylesheet"' in text:
            out.append(("style", path))
        elif 'as="font"' in text:
            out.append(("font", path))
        elif "<script" in text:
            out.append(("script", path))
    return out


def gzip_sizes(root):
    """Compressed bytes, per file, of the scripts and styles the page loads at boot."""
    files = list(appbuild.boot_graph(root))
    files += ["app/" + path for kind, path in _refs(_page(root)) if kind == "style"]
    sizes = {}
    for rel in files:
        if rel not in sizes:
            sizes[rel] = len(gzip.compress(_read(root, rel), GZIP_LEVEL, mtime=0))
    return sizes


def _hosts(root):
    html = _page(root)
    texts = [html]
    for kind, path in _refs(html):
        if kind == "style":
            texts.append(_read(root, "app/" + path).decode("utf-8"))
    hosts = set()
    for text in texts:
        hosts.update(_HOST.findall(text))
    return hosts - _NAMESPACE_HOSTS


def measure(root):
    """The numbers the budget limits, measured from the files under `root`."""
    html = _page(root)
    refs = _refs(html)
    graph = appbuild.boot_graph(root)
    requests = {"app/" + path for _, path in refs} | set(graph)
    fonts = {path for kind, path in refs if kind == "font"}
    return {
        "boot_gzip_bytes": sum(gzip_sizes(root).values()),
        "boot_modules": len(graph),
        "import_depth": appbuild.import_depth(root),
        "third_party_hosts": len(_hosts(root)),
        "font_bytes": sum(os.path.getsize(os.path.join(root, "app", p)) for p in fonts),
        "boot_requests": len(requests),
    }


def check(measured, budget, root=None):
    """The problems, one sentence each; empty when every number is inside its limit."""
    limits = budget.get("limits", {})
    problems = []
    for name, value in measured.items():
        if name not in limits:
            problems.append(
                "%s is %s and the budget has no limit for it; add one to %s with a reason."
                % (name, value, BUDGET_FILE)
            )
        elif value > limits[name]:
            text = "%s is %s, over its limit of %s." % (name, value, limits[name])
            if name == "boot_gzip_bytes" and root:
                biggest = sorted(gzip_sizes(root).items(), key=lambda kv: -kv[1])[:3]
                text += " The biggest files: %s." % ", ".join(
                    "%s (%d)" % kv for kv in biggest
                )
            text += (
                " Make the boot path smaller, or raise the limit in %s with the reason it has to grow."
                % BUDGET_FILE
            )
            problems.append(text)
    return problems


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(root, BUDGET_FILE), encoding="utf-8") as f:
        limits = json.load(f)["limits"]
    for name, value in measure(root).items():
        print("%-20s %8s  (limit %s)" % (name, value, limits.get(name, "none")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
