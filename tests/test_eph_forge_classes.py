"""Every table in the characters schema has a forge class.

The forge builds an ephemeral world's database from the nightly backup and
cleans it with one file, `data/forge/table-classes.yaml`. A table with no class in
that file would copy its stale runtime state into every future world without
anyone choosing it, so this test fails when the schema fixture holds a table
the file does not classify (and when the file names a table that is gone).

`tests/fixtures/forge_acore_characters_tables.txt` is the base-table list read
from a live realm's information_schema (names only). Refresh it when a core or
module update adds a table, then classify the new name.
"""

from __future__ import annotations

import pathlib
import unittest

from forge import classes

FIXTURE = (
    pathlib.Path(__file__).parent / "fixtures" / "forge_acore_characters_tables.txt"
)

# The append-only logs the rehearsal clone skips, plus the rows whose stale
# state confounded an earlier scenario run (groups, finder, instance binds,
# corpses, pending commands, standing goals and holds).
MUST_TRUNCATE = {
    "overseer_thought",
    "overseer_command",
    "overseer_jev_judgment",
    "overseer_event",
    "overseer_chat",
    "overseer_economy_sample",
    "overseer_sample",
    "overseer_death",
    "overseer_guild_answer",
    "overseer_guild_ask",
    "overseer_guild_pug_call",
    "groups",
    "group_member",
    "lfg_data",
    "instance",
    "character_instance",
    "corpse",
    "overseer_goal",
    "overseer_family_intent",
    "overseer_operator_hold",
    "overseer_work_order",
}


def schema_tables() -> list[str]:
    return [
        t.strip() for t in FIXTURE.read_text(encoding="utf-8").splitlines() if t.strip()
    ]


class EveryTableIsClassified(unittest.TestCase):
    def setUp(self) -> None:
        self.classes = classes.load_classes(classes.DEFAULT_PATH)
        self.tables = schema_tables()

    def test_fixture_is_a_plain_unique_name_list(self) -> None:
        self.assertGreater(len(self.tables), 100)
        self.assertEqual(len(self.tables), len(set(self.tables)))
        for name in self.tables:
            self.assertRegex(name, r"^[A-Za-z_][A-Za-z0-9_]*$")

    def test_no_table_is_unclassified(self) -> None:
        self.assertEqual(classes.unclassified(self.tables, self.classes), [])

    def test_no_class_names_a_table_the_schema_lacks(self) -> None:
        self.assertEqual(classes.stale(self.tables, self.classes), [])

    def test_a_new_table_is_reported(self) -> None:
        grown = [*self.tables, "brand_new_module_table"]
        self.assertEqual(
            classes.unclassified(grown, self.classes), ["brand_new_module_table"]
        )

    def test_a_dropped_table_is_reported_as_stale(self) -> None:
        shrunk = [t for t in self.tables if t != "corpse"]
        self.assertEqual(classes.stale(shrunk, self.classes), ["corpse"])

    def test_every_class_is_one_of_the_four(self) -> None:
        for name, entry in self.classes.items():
            self.assertIn(entry.kind, classes.KINDS, name)

    def test_stale_state_tables_are_truncated(self) -> None:
        for name in sorted(MUST_TRUNCATE):
            self.assertEqual(self.classes[name].kind, "truncate", name)

    def test_the_roster_job_is_scrubbed_not_dropped(self) -> None:
        entry = self.classes["overseer_roster"]
        self.assertEqual((entry.kind, entry.spec), ("scrub", "neutral-job"))

    def test_the_raid_seats_survive_so_the_lean_keep_set_can_use_them(self) -> None:
        self.assertEqual(self.classes["overseer_raid_seat"].kind, "keep")

    def test_schema_bookkeeping_is_kept(self) -> None:
        for name in ("updates", "updates_include", "_module_sql_applied"):
            self.assertEqual(self.classes[name].kind, "keep", name)

    def test_the_characters_table_keys_on_guid(self) -> None:
        entry = self.classes["characters"]
        self.assertEqual(
            (entry.kind, entry.key, entry.parent), ("per-character", "guid", None)
        )


class ParentChains(unittest.TestCase):
    def setUp(self) -> None:
        self.classes = classes.load_classes(classes.DEFAULT_PATH)

    def test_a_dependent_follows_a_per_character_parent(self) -> None:
        pet_aura = self.classes["pet_aura"]
        self.assertEqual(pet_aura.parent, ("character_pet", "id"))
        self.assertEqual(self.classes["character_pet"].kind, "per-character")

    def test_a_guild_follows_its_members_not_its_leader(self) -> None:
        self.assertEqual(self.classes["guild"].parent, ("guild_member", "guildid"))

    def test_every_parent_is_a_per_character_table(self) -> None:
        for name, entry in self.classes.items():
            if entry.parent is not None:
                parent_table = entry.parent[0]
                self.assertEqual(self.classes[parent_table].kind, "per-character", name)

    def test_trim_order_puts_parents_before_dependents(self) -> None:
        order = [e.table for e in classes.trim_order(self.classes)]
        for name, entry in self.classes.items():
            if entry.parent is not None:
                self.assertLess(order.index(entry.parent[0]), order.index(name), name)

    def test_trim_order_lists_each_per_character_table_once(self) -> None:
        order = [e.table for e in classes.trim_order(self.classes)]
        wanted = [n for n, e in self.classes.items() if e.kind == "per-character"]
        self.assertEqual(sorted(order), sorted(wanted))


class Parser(unittest.TestCase):
    def test_comments_and_blank_lines_are_skipped(self) -> None:
        parsed = classes.parse_classes("# note\n\nupdates: keep\n")
        self.assertEqual(list(parsed), ["updates"])

    def test_unknown_class_is_refused(self) -> None:
        with self.assertRaises(classes.ClassError):
            classes.parse_classes("a: ignore\n")

    def test_duplicate_table_is_refused(self) -> None:
        with self.assertRaises(classes.ClassError):
            classes.parse_classes("a: keep\na: truncate\n")

    def test_per_character_without_a_key_is_refused(self) -> None:
        with self.assertRaises(classes.ClassError):
            classes.parse_classes("a: per-character\n")

    def test_a_parent_that_is_not_classified_is_refused(self) -> None:
        with self.assertRaises(classes.ClassError):
            classes.parse_classes("a: per-character guid > missing.id\n")

    def test_a_parent_cycle_is_refused(self) -> None:
        text = "a: per-character x > b.y\nb: per-character y > a.x\n"
        with self.assertRaises(classes.ClassError):
            classes.parse_classes(text)

    def test_a_key_must_be_a_plain_identifier(self) -> None:
        with self.assertRaises(classes.ClassError):
            classes.parse_classes("a: per-character guid;DROP\n")

    def test_a_scrub_without_a_rule_is_refused(self) -> None:
        with self.assertRaises(classes.ClassError):
            classes.parse_classes("a: scrub\n")


if __name__ == "__main__":
    unittest.main()
