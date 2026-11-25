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
    import questers


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

    def test_gameobject_loot_and_vendor_sale_are_sources(self):
        row = quest_row(item1=2640, item_count1=4, item2=1941, item_count2=1)
        ids = "1941, 2640"
        catalogue = self.catalogue(
            row,
            {
                qc.ITEM_NAMES_SQL.format(ids=ids): [
                    {"entry": 2640, "name": "Miners' Gear"},
                    {"entry": 1941, "name": "Cleverly Written Letter"},
                ],
                qc.DROP_SQL.format(ids=ids): [],
                qc.REWARD_SQL.format(ids=ids): [],
                qc.VENDOR_SQL.format(ids=ids): [{"item": 1941, "entry": 277}],
                qc.OBJECT_LOOT_SQL.format(ids=ids): [{"item": 2640, "entry": 2059}],
            },
        )
        text = qt.body(116, catalogue[0], [], [], "")
        self.assertIn("gameobject loot entries 2059", text)
        self.assertIn("sold by vendor entries 277", text)
        self.assertNotIn("no source in the world rows", text)

    def test_required_item_without_any_world_source_says_so(self):
        row = quest_row(item1=1262, item_count1=1, provided_item=1353)
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

    def test_pyrewood_ambush_ticket_explains_the_event_reason(self):
        # This quest_template row mirrors the ticket's read-only world snapshot.
        # Its ledger reason is written by bridge._record_quest_broken; the
        # producer path is covered in test_guildlevel_event_quests.
        world_row = quest_row(
            452,
            title="Pyrewood Ambush",
            level=15,
            min_level=12,
            sort=130,
        )
        world_row.update(
            {key: 0 for i in range(1, 7) for key in ("item%d" % i, "item_count%d" % i)}
        )
        world_row.update(
            {
                key: 0
                for i in range(1, 5)
                for key in ("objective%d" % i, "objective_count%d" % i)
            }
        )
        info = self.catalogue(world_row, {})[0]
        self.assertEqual(info.min_level, 12)
        self.assertEqual(info.items, ())
        self.assertEqual(info.objectives, ())
        rows = [
            {
                "quest": 452,
                "guid": 7,
                "character_name": "Quester A",
                "state": "broken",
                "reason": questers.SCRIPTED_EVENT,
            },
            {
                "quest": 452,
                "guid": 8,
                "character_name": "Quester B",
                "state": "broken",
                "reason": questers.SCRIPTED_EVENT,
            },
        ]

        text = qt.body(452, info, rows, [], "")

        self.assertIn("- Quest: 452, Pyrewood Ambush", text)
        self.assertIn("- Zone: Silverpine Forest", text)
        self.assertIn("- Level: 15", text)
        self.assertIn("- No required item or creature/object rows.", text)
        self.assertEqual(text.count("Reason: " + questers.SCRIPTED_EVENT), 2)
        self.assertEqual(text.count("Last objective counts: not in the log now"), 2)
        self.assertIn(
            "The world rows list no required item or creature/object objectives, "
            "so the stored reason is the only evidence of how it completes: a scripted event.",
            text,
        )

    def test_quest_start_item_is_a_source_for_its_required_item(self):
        row = quest_row(item1=1353, item_count1=1, provided_item=1353)
        catalogue = self.catalogue(
            row,
            {
                qc.ITEM_NAMES_SQL.format(ids="1353"): [
                    {"entry": 1353, "name": "Shaw's Report"}
                ],
                qc.DROP_SQL.format(ids="1353"): [],
                qc.REWARD_SQL.format(ids="1353"): [],
                qc.VENDOR_SQL.format(ids="1353"): [],
            },
        )
        text = qt.body(116, catalogue[0], [], [], "")
        self.assertIn("provided when this quest is accepted", text)
        self.assertNotIn("no source in the world rows", text)

    def test_kill_objective_counts_spawns_on_the_quest_map_not_by_zone_id(self):
        # creature.zoneId is unset on almost every dev row (zone 0), so a
        # zone filter reads 0 for creatures that stand on the right map.
        row = quest_row(objective1=124, objective_count1=8)
        catalogue = self.catalogue(
            row,
            {
                qc.CREATURE_NAMES_SQL.format(ids="124"): [
                    {"entry": 124, "name": "Young Thistle Boar"}
                ],
                qc.SPAWN_COUNTS_SQL.format(ids="124"): [
                    {"entry": 124, "map": 0, "n": 3},
                    {"entry": 124, "map": 1, "n": 2},
                ],
            },
        )
        text = qt.body(116, catalogue[0], [], [], "")
        self.assertIn("Required creature/object 124 x8 (Young Thistle Boar)", text)
        self.assertIn("3 spawn(s) on the quest's map, 5 total", text)
        self.assertNotIn("in zone", text)

    def test_spawn_sql_groups_by_map_and_never_reads_zone_id(self):
        for sql in (qc.SPAWN_COUNTS_SQL, qc.OBJECT_COUNTS_SQL):
            self.assertNotIn("zoneId", sql)
            self.assertIn("map", sql)

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
