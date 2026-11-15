"""The schema snapshot, the read-only SQL checker, and anchors.yaml validation."""

import unittest

from ephemeral import anchors as anchors_mod
from ephemeral import dbschema

SCHEMA = dbschema.Schema.load()


class SnapshotTest(unittest.TestCase):
    def test_real_names_are_present(self):
        self.assertTrue(SCHEMA.has_column("creature", "id", "acore_world"))
        self.assertFalse(SCHEMA.has_column("creature", "id1", "acore_world"))
        self.assertTrue(SCHEMA.has_column("creature_respawn", "instanceId"))
        self.assertTrue(SCHEMA.has_table("overseer_dungeon_run"))
        self.assertFalse(SCHEMA.has_table("overseer_dungeon_event"))

    def test_from_rows(self):
        s = dbschema.Schema.from_rows(
            [("acore_characters", "t", "a"), ("acore_characters", "t", "b")]
        )
        self.assertEqual(s.columns("t"), ["a", "b"])


class CheckSelectTest(unittest.TestCase):
    def check(self, sql, known=None):
        return dbschema.check_select(sql, SCHEMA, known)

    def test_good_join(self):
        self.assertEqual(
            self.check(
                "SELECT t.name, r.guid FROM creature_respawn r JOIN acore_world.creature c ON c.guid = r.guid "
                "JOIN acore_world.creature_template t ON t.entry = c.id WHERE r.instanceId = @x AND t.name IN ('A', 'B')"
            ),
            [],
        )

    def test_bad_qualified_column(self):
        self.assertTrue(self.check("SELECT c.id1 FROM acore_world.creature c"))

    def test_bad_bare_column(self):
        self.assertTrue(self.check("SELECT nothing FROM characters"))

    def test_select_alias_is_not_a_column(self):
        self.assertEqual(
            self.check("SELECT COUNT(*) AS n FROM characters WHERE level > 1"), []
        )

    def test_strings_are_not_identifiers(self):
        self.assertEqual(
            self.check("SELECT guid FROM characters WHERE name = 'no_such_column'"), []
        )

    def test_comment_is_rejected(self):
        self.assertTrue(self.check("SELECT 1 -- hi"))

    def test_into_outfile_is_rejected(self):
        self.assertTrue(self.check("SELECT guid FROM characters INTO OUTFILE 'x'"))

    def test_other_database_is_rejected(self):
        self.assertTrue(self.check("SELECT * FROM mysql.user"))

    def test_variable_vocabulary(self):
        self.assertTrue(
            self.check(
                "SELECT guid FROM characters WHERE guid = @bad", lambda n: n == "ok"
            )
        )
        self.assertEqual(
            self.check(
                "SELECT guid FROM characters WHERE guid = @ok", lambda n: n == "ok"
            ),
            [],
        )


class AnchorsTest(unittest.TestCase):
    GOOD = {
        "map": 0, "zone": 1, "x": 1.0, "y": 2.0, "z": 3.0, "o": 0.0,
        "provenance": {"source": "overseer_death", "ref": "row 9", "observed": "2026-01-02"},
    }  # fmt: skip

    def problems(self, entries):
        return anchors_mod.validate({"anchors": entries})

    def test_good_entry(self):
        self.assertEqual(self.problems({"a-spot": self.GOOD}), [])

    def test_entry_without_provenance_is_rejected(self):
        bad = {k: v for k, v in self.GOOD.items() if k != "provenance"}
        self.assertTrue(self.problems({"a-spot": bad}))

    def test_partial_provenance_is_rejected(self):
        bad = dict(self.GOOD, provenance={"source": "overseer_death"})
        self.assertTrue(self.problems({"a-spot": bad}))

    def test_missing_coordinate_is_rejected(self):
        bad = {k: v for k, v in self.GOOD.items() if k != "z"}
        self.assertTrue(self.problems({"a-spot": bad}))

    def test_pending_needs_a_todo_and_no_position(self):
        self.assertEqual(
            self.problems({"a-spot": {"pending": True, "todo": "copy it"}}), []
        )
        self.assertTrue(self.problems({"a-spot": {"pending": True}}))
        self.assertTrue(
            self.problems({"a-spot": {"pending": True, "todo": "x", "x": 1}})
        )

    def test_key_must_be_kebab(self):
        self.assertTrue(self.problems({"Bad_Key": self.GOOD}))

    def test_position_of_pending_is_none(self):
        a = anchors_mod.Anchors({"p": {"pending": True, "todo": "x"}, "g": self.GOOD})
        self.assertIsNone(a.position("p"))
        self.assertEqual(a.position("g"), (0, 1, 1.0, 2.0, 3.0, 0.0))


if __name__ == "__main__":
    unittest.main()
