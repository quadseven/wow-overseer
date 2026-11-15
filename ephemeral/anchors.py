"""decrees/anchors.yaml: the ONE place literal coordinates may live.

Every entry is a position a real character stood at, with its provenance. A
guessed z has no navmesh and has already killed a character, so a decree never
carries a coordinate: it names an anchor. An entry whose position has not yet
been copied from its source is `pending: true`; lint warns when a decree uses
one and the seed compiler refuses it.
"""

import pathlib
import re

from .miniyaml import loads

DEFAULT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "decrees" / "anchors.yaml"
)
_KEY = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_NUM = (int, float)
_PROVENANCE = ("source", "ref", "observed")


class Anchors:
    def __init__(self, entries):
        self.entries = entries

    @classmethod
    def load(cls, path=None):
        path = pathlib.Path(path or DEFAULT_PATH)
        doc = loads(path.read_text(encoding="utf-8"))
        return cls((doc or {}).get("anchors") or {})

    def has(self, key):
        return key in self.entries

    def is_pending(self, key):
        return bool(self.entries.get(key, {}).get("pending"))

    def position(self, key):
        """(map, zone, x, y, z, o) of a captured anchor, or None when pending."""
        e = self.entries[key]
        if e.get("pending"):
            return None
        return (e["map"], e.get("zone", 0), e["x"], e["y"], e["z"], e["o"])


def validate(doc):
    """Problems with an anchors document, as a list of strings."""
    problems = []
    if not isinstance(doc, dict) or set(doc) != {"anchors"}:
        return ["anchors.yaml must hold exactly one top-level key: anchors"]
    entries = doc["anchors"] or {}
    if not isinstance(entries, dict):
        return ["anchors must be a mapping"]
    for key, e in entries.items():
        where = f"anchors.{key}"
        if not _KEY.match(str(key)):
            problems.append(f"{where}: key must be kebab-case")
        if not isinstance(e, dict):
            problems.append(f"{where}: must be a mapping")
            continue
        if e.get("pending") is True:
            extra = set(e) - {"pending", "todo"}
            if extra:
                problems.append(
                    f"{where}: a pending anchor holds no position ({sorted(extra)})"
                )
            if not e.get("todo"):
                problems.append(
                    f"{where}: a pending anchor needs `todo` naming the source row to copy"
                )
            continue
        allowed = {"map", "zone", "x", "y", "z", "o", "provenance"}
        for k in sorted(set(e) - allowed):
            problems.append(f"{where}: unknown field {k!r}")
        for k in ("map", "x", "y", "z", "o"):
            if not isinstance(e.get(k), _NUM) or isinstance(e.get(k), bool):
                problems.append(f"{where}: {k} must be a number")
        prov = e.get("provenance")
        if not isinstance(prov, dict):
            problems.append(
                f"{where}: provenance is required (where a real character stood)"
            )
        else:
            for k in _PROVENANCE:
                if not prov.get(k):
                    problems.append(f"{where}: provenance.{k} is required")
            for k in sorted(set(prov) - set(_PROVENANCE) - {"note"}):
                problems.append(f"{where}: unknown provenance field {k!r}")
    return problems
