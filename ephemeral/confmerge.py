"""Merge a decree's config onto the override files the base realm already runs.

The world's `seed-conf` step strips from the dist exactly the keys an override
file names and appends the file, and it refuses a key that appears twice. So a
key we change must be REMOVED from the base file first, never appended beside it.
"""

import re

FILES = {
    "playerbots": "playerbots.overrides.conf",
    "worldserver": "worldserver.overrides.conf",
    "ollama-chat": "ollama-chat.overrides.conf",
    "overseer": "overseer.overrides.conf",
    "dungeon-clear": "dungeon-clear.overrides.conf",
}
PREFIXES = (
    ("Playerbots.", "playerbots"),
    ("AiPlayerbot.", "playerbots"),
    ("OllamaChat.", "ollama-chat"),
    ("Overseer.", "overseer"),
    ("DungeonClear.", "dungeon-clear"),
)
_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_.]*)\s*=\s*(.*?)\s*$")
_BARE = re.compile(r"^-?\d+(\.\d+)?$")


class ConfError(ValueError):
    """A value or key that cannot be written into an override file."""


def group_of(key):
    for prefix, group in PREFIXES:
        if key.startswith(prefix):
            return group
    return "worldserver"


def render_value(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if "\n" in text or "\r" in text or '"' in text:
        raise ConfError("a config value may not hold a quote or a line break")
    return text if _BARE.match(text) else f'"{text}"'


def parse(text):
    """{key: value text} of the live `key = value` lines (comments skipped)."""
    out = {}
    for line in (text or "").splitlines():
        if line.lstrip().startswith(("#", "//")):
            continue
        m = _LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def set_keys(text, changes):
    """The file text with every key in `changes` removed, then appended once."""
    keep = []
    for line in (text or "").splitlines():
        m = _LINE.match(line)
        if m and not line.lstrip().startswith(("#", "//")) and m.group(1) in changes:
            continue
        keep.append(line)
    while keep and not keep[-1].strip():
        keep.pop()
    keep.append("# --- ephemeral world: keys set for this run ---")
    keep += [f"{k} = {render_value(v)}" for k, v in sorted(changes.items())]
    return "\n".join(keep) + "\n"


def merge(source_files, changes):
    """(new files {group: text}, deltas [str]). `changes` is {key: value}."""
    by_group = {}
    for key, value in changes.items():
        by_group.setdefault(group_of(key), {})[key] = value
    files = {g: source_files.get(g, "") for g in source_files}
    deltas = []
    for group, keys in sorted(by_group.items()):
        before = parse(source_files.get(group, ""))
        files[group] = set_keys(source_files.get(group, ""), keys)
        for key, value in sorted(keys.items()):
            old = before.get(key)
            new = render_value(value)
            if old != new:
                deltas.append(
                    f"{key}: {old if old is not None else '(unset)'} -> {new}"
                )
    return files, deltas
