"""The bridge writes no command a player could not do.

Every overseer_command row the bridge writes must be a natural player action.
GM-style grants are allowed only on operator-only or test-only paths that are
explicitly marked with `natural-only: <why>`.

Command verb classification (the exhaustive list the PR carries):

NATURAL player actions
  - auras            API probe: read-only aura list
  - bags             probe: read-only bag contents
  - bank             guild-bank gold deposit / withdraw
  - bg-queue         queue for a battleground
  - buy              buy an auction listing
  - cross-to-map     class-quest zone crossing
  - deposit          bank a single item
  - destroy          destroy a surplus item
  - dungeon:*        dungeon-finder campaign keyword
  - e                equip an item (mod-playerbots command)
  - entry            vendor purchase by item entry
  - finder-run       guild-run via the dungeon finder
  - gear             probe: read-only equipped gear
  - guid             give/trade an item by guid
  - list             list an item on the auction house
  - meter            API probe: read-only meter sample
  - party-up         class-quest group formation
  - party-walk       class-quest group walk
  - quest            share a quest
  - recall           hearthstone recall
  - sell             sell an item to a vendor
  - send             mail an item or money
  - spells           probe: read-only spell list
  - state            probe: read-only character state
  - strategies       probe: read-only bot strategies
  - take             take a quest from a giver
  - take-item        take an item from mail
  - talents          probe: read-only talents
  - train            job mode: train professions and class skills
  - train-weapon     train a weapon skill at a trainer
  - turnin           hand a quest in
  - up               alias for party-up in some class-quest paths
  - use              use an item, recipe, or hearthstone
  - use-item-here    class-quest use-item-on-self
  - use-item-on      class-quest use-item-on-creature
  - use-gameobject   class-quest use-gameobject
  - walk-to-mailbox  guild-route mailbox walk
  - walk-to-spawn    guild-job walk to a spawn
  - walk-to-trainer  guild-corps walk to a trainer
  - farm, fish, grind, gear hunt, craft, town run, rest, reputation,
    guild business, raid prep    job-mode names

GRANT verbs (operator-only/test-only, all flow through _insert_gm)
  - additem, appear, aura, cast, damage, die, freeze, gm, go, group,
    learn, levelup, modify, playerbots, recall, revive, summon, tele,
    unaura, unfreeze, unlearn, unstuck, maxskill
    (the exact set is derived from relay.py's GM_ALLOWED_PREFIXES and
    GM_DENIED_LEAVES in the test itself)
"""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Files that contain INSERT INTO overseer_command writers.
COMMAND_SOURCES = (
    "bridge.py",
    "map_server.py",
    "attunestep.py",
    "dungeonquests.py",
    "tools/probe.py",
    "tools/push_party_status.py",
)

# Natural command verbs known to be written as literals.  This is not the
# exhaustive list (most commands are built dynamically by the modules the
# bridge calls); the full classification lives in this file's module docstring.
KNOWN_NATURAL_LITERALS = frozenset(
    {
        "auras",
        "meter",
        "use",
    }
)


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _grant_verbs() -> frozenset[str]:
    """GM verbs a player cannot do, taken from relay.py's allow/deny lists."""
    src = _read("relay.py")
    verbs: set[str] = set()
    for pattern in (
        r"GM_ALLOWED_PREFIXES = frozenset\(\s*\{(.*?)\}\s*\)",
        r"GM_DENIED_LEAVES = frozenset\(\s*\{(.*?)\}\s*\)",
    ):
        m = re.search(pattern, src, re.DOTALL)
        if not m:
            continue
        for phrase in re.findall(r'"([^"]+)"', m.group(1)):
            verbs.add(phrase.split()[0].lower())
    return frozenset(verbs)


GRANT_VERBS = _grant_verbs()


def _function_block(src: str, signature: str) -> str:
    """Return one def's body, stopping at the next def at the same indent."""
    start = src.index(signature)
    indent = len(src[:start].rsplit("\n", 1)[-1])
    lines = src[start:].split("\n")
    out = [lines[0]]
    for line in lines[1:]:
        if line.strip() and not line.startswith(" " * (indent + 1)):
            break
        out.append(line)
    return "\n".join(out)


def _insert_command_values(src: str) -> list[tuple[int, str | None, str]]:
    """(line_number, column_name, literal) for literal values in INSERT INTO
    overseer_command statements.  column_name is the column the literal fills.
    """
    found: list[tuple[int, str | None, str]] = []
    for m in re.finditer(r"INSERT INTO overseer_command", src):
        line_no = src[: m.start()].count("\n") + 1
        # The SQL plus its parameter tuple is always inside the next 800 chars.
        window = src[m.start() : m.start() + 800]

        # Column list: the first parenthesised list after the table name.
        col_match = re.search(r"\(([^)]+)\)", window)
        if not col_match:
            continue
        columns = [c.strip() for c in col_match.group(1).split(",")]

        # VALUES list: the second parenthesised list, after the word VALUES.
        values_match = re.search(r"VALUES\s*\(([^)]+)\)", window, re.IGNORECASE)
        if not values_match:
            continue
        # Split on commas that are not inside single-quoted literals.
        values = [
            v.strip()
            for v in re.split(
                r",(?=(?:[^'\"]*['\"][^'\"]*['\"])*[^'\"]*$)", values_match.group(1)
            )
        ]

        for col, val in zip(columns, values):
            if val.startswith("'") and val.endswith("'"):
                lit = val[1:-1].strip()
                if lit:
                    found.append((line_no, col, lit))
    return found


def _command_verb(lit: str) -> str | None:
    """Return the verb of a queued command literal, or None if it is not one."""
    if lit.startswith("."):
        return lit.lstrip(".").split()[0].lower()
    # Simple lower-case words (including hyphenated ones) are command verbs.
    if re.fullmatch(r"[a-z][a-z-]*", lit):
        return lit
    return None


class BridgeWritesOnlyNaturalCommands(unittest.TestCase):
    def test_deny_list_is_populated_from_relay(self):
        self.assertTrue(GRANT_VERBS)
        # A few examples the brief names explicitly.
        for verb in ("additem", "learn", "levelup", "tele", "aura"):
            self.assertIn(verb, GRANT_VERBS)

    def test_gm_command_insert_path_is_marked(self):
        """The only path that queues arbitrary GM commands must be marked."""
        src = _read("bridge.py")
        block = _function_block(src, "def _insert_gm(")
        self.assertIn(
            "natural-only:",
            block,
            "_insert_gm must carry a natural-only marker explaining why no "
            "member reaches it",
        )

    def test_no_unmarked_grant_literal_queued(self):
        """Any GM-style command literal written to overseer_command must be
        on a path marked as operator-only or test-only.
        """
        for name in COMMAND_SOURCES:
            src = _read(name)
            for line_no, col, lit in _insert_command_values(src):
                if col != "command":
                    continue
                verb = _command_verb(lit)
                if verb not in GRANT_VERBS:
                    continue
                # The marker may live on the INSERT line or in the surrounding
                # function; either is acceptable.
                window = "\n".join(
                    src.splitlines()[max(0, line_no - 15) : line_no + 15]
                )
                self.assertIn(
                    "natural-only:",
                    window,
                    f"{name}:{line_no}: unmarked grant command {lit!r}",
                )

    def test_command_verbs_are_collected_and_classified(self):
        """Collect every literal command verb the bridge writes and assert that
        any grant verb in the collection is marked.  New literal verbs force an
        update to this test, which is the keep-it-that-way mechanism.
        """
        natural: set[str] = set()
        grant: set[str] = set()
        for name in COMMAND_SOURCES:
            src = _read(name)
            for _line_no, col, lit in _insert_command_values(src):
                if col != "command":
                    continue
                verb = _command_verb(lit)
                if verb is None:
                    continue
                window = "\n".join(
                    src.splitlines()[max(0, _line_no - 15) : _line_no + 15]
                )
                if "natural-only:" in window:
                    grant.add(verb)
                else:
                    natural.add(verb)

        # The GM path is dynamic, so it does not surface as a literal; record
        # every verb its allowlist admits as a marked grant.
        grant.update(GRANT_VERBS)

        self.assertTrue(
            grant.issubset(GRANT_VERBS),
            f"Unclassified grant verbs: {sorted(grant - GRANT_VERBS)}",
        )

        # Every natural literal must be in the known set; an unknown literal
        # means the classification list in the module docstring needs updating.
        self.assertEqual(
            natural,
            KNOWN_NATURAL_LITERALS,
            "Literal natural command verbs changed. Update KNOWN_NATURAL_LITERALS "
            "and the full classification list in this file's docstring.",
        )
