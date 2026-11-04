"""World evidence in newly filed broken-quest tickets."""

import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from _stub_modules import PYMYSQL, stub_modules  # noqa: E402

with stub_modules(pymysql=PYMYSQL):
    import questcatalogue as qc
    import questtickets as qt


def quest_row(quest=116, **values):
    row = {
        "quest": quest,
        "title": "Collect Supplies",
        "level": 10,
        "min_level": 8,
        "sort": 12,
        "races": 0,
        "classes": 0,
        "follows": 0,
    }
    row.update(values)
    return row


class WorldRows(unittest.TestCase):
    def catalogue(self, row, answers):
        qc.forget()
        answers = {
            qc.QUESTS_SQL: [row],
            qc.GIVERS_SQL: [
                {"quest": row["quest"], "role": "start", "map_id": 0},
                {"quest": row["quest"], "role": "end", "map_id": 0},
            ],
            **answers,
        }

        def read(sql):
            for query, rows in answers.items():
                if sql == query or sql.startswith(query.split("{ids}")[0]):
                    return rows
            return []

        return qc.load(read)

    def test_item_quest_lists_reward_vendor_and_absent_dropper_rows(self):
        row = quest_row(item1=1262, item_count1=1, item2=1941, item_count2=1)
        catalogue = self.catalogue(
            row,
            {
                qc.ITEM_NAMES_SQL.format(ids="1262, 1941"): [
                    {"entry": 1262, "name": "Finely Woven Cloak"},
                    {"entry": 1941, "name": "Cleverly Written Letter"},
                ],
                qc.DROP_SQL.format(ids="1262, 1941"): [],
                qc.REWARD_SQL.format(ids="1262, 1941"): [{"quest": 117, "item": 1262}],
                qc.VENDOR_SQL.format(ids="1262, 1941"): [{"item": 1941, "entry": 277}],
            },
        )
        text = qt.body(116, catalogue[0], [], [], "")
        self.assertIn("Required item 1262 x1 (Finely Woven Cloak)", text)
        self.assertIn("rewarded by quests 117", text)
        self.assertIn("Required item 1941 x1 (Cleverly Written Letter)", text)
        self.assertIn("sold by vendor entries 277", text)
        self.assertNotIn("no source in the world rows", text)

    def test_required_item_without_any_world_source_says_so(self):
        row = quest_row(item1=1262, item_count1=1)
        catalogue = self.catalogue(
            row,
            {
                qc.ITEM_NAMES_SQL.format(ids="1262"): [
                    {"entry": 1262, "name": "Finely Woven Cloak"}
                ],
                qc.DROP_SQL.format(ids="1262"): [],
                qc.REWARD_SQL.format(ids="1262"): [],
                qc.VENDOR_SQL.format(ids="1262"): [],
            },
        )
        self.assertIn(
            "no source in the world rows", qt.body(116, catalogue[0], [], [], "")
        )

    def test_kill_objective_lists_spawn_counts_in_quest_zone_and_total(self):
        row = quest_row(objective1=124, objective_count1=8)
        catalogue = self.catalogue(
            row,
            {
                qc.CREATURE_NAMES_SQL.format(ids="124"): [
                    {"entry": 124, "name": "Young Thistle Boar"}
                ],
                qc.SPAWN_COUNTS_SQL.format(ids="124"): [
                    {"entry": 124, "zone": 12, "n": 3},
                    {"entry": 124, "zone": 14, "n": 2},
                ],
            },
        )
        text = qt.body(116, catalogue[0], [], [], "")
        self.assertIn("Required creature/object 124 x8 (Young Thistle Boar)", text)
        self.assertIn("3 spawn(s) in zone, 5 total", text)

    def test_previous_quest_and_levels_are_in_world_rows(self):
        info = types.SimpleNamespace(
            title="Quest title",
            zone_name="Zone",
            level=10,
            min_level=8,
            follows=117,
            items=(),
            objectives=(),
        )
        text = qt.body(116, info, [], [], "")
        self.assertIn("QuestLevel: 10; MinLevel: 8", text)
        self.assertIn("Previous quest: 117", text)


if __name__ == "__main__":
    unittest.main()
