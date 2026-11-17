"""List the icon font classes used by app markup and server-rendered HTML."""

from __future__ import annotations

import pathlib
import re

_ICON_CLASS = re.compile(
    r"(?<![\w-])(ph-fill|ph)\s+ph-([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)(?![a-z0-9-])"
)


def icons_in_sources(root: pathlib.Path | None = None) -> dict[str, set[str]]:
    """Return icon names grouped by weight, including the sort caret pair."""
    root = root or pathlib.Path(__file__).resolve().parents[1]
    app = root / "app"
    sources = [
        path
        for path in app.rglob("*")
        if path.is_file() and path.suffix in {".css", ".html", ".js"}
    ]
    sources.extend(path for path in root.glob("*.py") if path.is_file())
    used = {"ph": set(), "ph-fill": set()}
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for weight, name in _ICON_CLASS.findall(text):
            used[weight].add(name)
        if "ph ph-caret-" in text:
            used["ph"].update({"caret-up", "caret-down"})
    return used


def main() -> None:
    for weight, names in sorted(icons_in_sources().items()):
        for name in sorted(names):
            print(f"{weight} ph-{name}")


if __name__ == "__main__":
    main()
