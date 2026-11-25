"""Player stories for the bridge ship note (#1994).

A pull request may carry an optional `## Player story` section: one sentence
in game terms that names who or what was affected and the effect. The ship
pull request lists one line per included pull request, the story when there
is one and the title when there is not, so the operator reads the ship note
straight from the ship pull request.

Pure functions over (number, title, body) rows; nothing here reads GitHub.
The ship workflow runs it as `python3 playerstory.py < rows.json`.
"""

import re

_HEADING = re.compile(r"^#{2,3}[ \t]+player[ \t]+story[ \t]*:?[ \t]*$", re.I | re.M)
_NEXT_HEADING = re.compile(r"^#{1,6}[ \t]", re.M)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def story(body) -> str:
    """The player story in a pull request body, or "" when it has none.

    The story is the text under the heading up to the next heading, joined on
    one line. An HTML comment (the template's hint) is not a story.
    """
    text = _COMMENT.sub("", str(body or ""))
    found = _HEADING.search(text)
    if not found:
        return ""
    rest = text[found.end() :]
    following = _NEXT_HEADING.search(rest)
    if following:
        rest = rest[: following.start()]
    return " ".join(rest.split())


def line(number, title, body) -> str:
    """One ship note line: the story, else the title when the story is absent."""
    words = story(body) or " ".join(str(title or "").split())
    return "- #%d %s" % (int(number), words)


def collect(rows) -> str:
    """The ship note: one line per (number, title, body) row, in the order given."""
    return "\n".join(line(n, t, b) for n, t, b in rows)


def main(argv=None, stdin=None, stdout=None) -> int:
    """Entry point for the ship workflow: a JSON list of
    {"number", "title", "body"} objects on stdin, the ship note on stdout."""
    import json
    import sys

    rows = json.load(stdin or sys.stdin)
    note = collect((r["number"], r.get("title"), r.get("body")) for r in rows)
    print(note, file=stdout or sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
