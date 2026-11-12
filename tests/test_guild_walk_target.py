"""The guild page names a blocked class walk's creature by its spawn id (#2199).

`walk-to-spawn creature:N` and `party-walk creature:N` carry a SPAWN id, the
creature table's guid, not a template entry. The page used to look the number
up as an entry, so it named a different creature than the one walked to. The
realm here is the in-memory reader, which answers each statement by the
constant it is built from, so a test shows both which query ran and which name
reached the page. The creatures and ids are invented.
"""

import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import commandwords
    import realmread
    from apiv2 import guild

NOW = 1_800_001_800
# One number, two creatures: the spawn with this guid is one creature, and the
# template with this entry is another.
SHARED = 39536
SPAWN_NAME = "Orgrim's Quartermaster"
ENTRY_NAME = "Wandering Boar"


def step(command, status="error"):
    return {
        "name": "Bonk",
        "command": command,
        "status": status,
        "detail": "refused",
        "result": '{"reason": "no path"}',
        "at": NOW,
    }


def realm(steps, spawns=None, entries=None):
    """The reads `_class_quests` makes, with names answered per table."""
    spawns = {SHARED: SPAWN_NAME} if spawns is None else spawns
    entries = {SHARED: ENTRY_NAME} if entries is None else entries

    def named(table):
        return lambda params: [
            {"id": i, "name": table[i]} for i in params if i in table
        ]

    return realmread.Memory(
        {
            guild._CQ_DONE_SQL: [{"n": 0, "who": 0}],
            guild._CQ_OPEN_SQL: [],
            guild._CQ_STEPS_SQL: steps,
            commandwords.NAMES_SQL["spawn"]: named(spawns),
            commandwords.NAMES_SQL["creature"]: named(entries),
        }
    )


def blocked_row(command, **kw):
    rd = realm([step(command)], **kw)
    out = guild._class_quests(rd, 7, ["Bonk"], {"Bonk": "Warrior"})
    return out["rows"][0], rd


class ABlockedWalkIsNamedBySpawn(unittest.TestCase):
    def test_a_spawn_walk_names_the_creature_at_that_spawn(self):
        row, _ = blocked_row("walk-to-spawn creature:%d near:3" % SHARED)
        self.assertEqual(row["walk_to"], "walking to " + SPAWN_NAME)

    def test_a_party_walk_is_named_the_same_way(self):
        row, _ = blocked_row("party-walk creature:%d" % SHARED)
        self.assertEqual(row["walk_to"], "walking to " + SPAWN_NAME)

    def test_a_spawn_the_world_does_not_hold_says_so_with_its_number(self):
        row, _ = blocked_row("walk-to-spawn creature:%d" % SHARED, spawns={})
        self.assertEqual(
            row["walk_to"],
            "walking to an unnamed creature (%d), which the world database "
            "does not hold" % SHARED,
        )

    def test_a_missing_spawn_is_not_named_by_the_entry_with_its_number(self):
        row, _ = blocked_row("walk-to-spawn creature:%d" % SHARED, spawns={})
        self.assertNotIn(ENTRY_NAME, row["walk_to"])


class TheQueryIsTheSharedOne(unittest.TestCase):
    def test_the_page_reads_spawn_names_with_the_command_words_query(self):
        _, rd = blocked_row("walk-to-spawn creature:%d" % SHARED)
        asked = [sql for sql, _params in rd.asked]
        self.assertIn(commandwords.NAMES_SQL["spawn"].format(holes="%s"), asked)
        self.assertNotIn(commandwords.NAMES_SQL["creature"].format(holes="%s"), asked)

    def test_the_page_keeps_no_copy_of_the_creature_query(self):
        self.assertFalse(hasattr(guild, "_CREATURE_NAMES_SQL"))

    def test_a_command_that_is_not_a_spawn_walk_still_reads_an_entry(self):
        self.assertEqual(commandwords.creature_table("hunt creature:5"), "creature")
        self.assertEqual(
            commandwords.creature_table("walk-to-spawn creature:5"), "spawn"
        )
        self.assertEqual(commandwords.creature_table("party-walk creature:5"), "spawn")


if __name__ == "__main__":
    unittest.main()
