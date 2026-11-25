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

    def test_quest_356_rows_explain_what_the_ledger_does_not_establish(self):
        # World rows come from questcatalogue's quest, giver, creature-name,
        # and spawn-count reads; objective counters come from OBJECTIVES_SQL.
        row = quest_row(
            356,
            title="Rear Guard Patrol",
            level=11,
            min_level=6,
            sort=85,
            objective1=1529,
            objective_count1=8,
            objective2=1532,
            objective_count2=8,
        )
        ids = "1529, 1532"
        # The fixture's givers sit on map 0, so map 0 is the quest's map and
        # map 1 is elsewhere. Distinct counts per entry and per map catch a
        # swapped column, a swapped entry, or a total that drops a map.
        quest_map, other_map = 0, 1
        horror_on_map = {"entry": 1529, "map": quest_map, "n": 12}
        horror_off_map = {"entry": 1529, "map": other_map, "n": 3}
        spirit_on_map = {"entry": 1532, "map": quest_map, "n": 5}
        spirit_off_map = {"entry": 1532, "map": other_map, "n": 4}
        info = self.catalogue(
            row,
            {
                qc.CREATURE_NAMES_SQL.format(ids=ids): [
                    {"entry": 1529, "name": "Bleeding Horror"},
                    {"entry": 1532, "name": "Wandering Spirit"},
                ],
                qc.SPAWN_COUNTS_SQL.format(ids=ids): [
                    horror_on_map,
                    horror_off_map,
                    spirit_on_map,
                    spirit_off_map,
                ],
            },
        )[0]
        refusal = "the quest giver would not give it: no giver of that quest in reach"
        rows = [
            {"quest": 356, "guid": 7, "character_name": "Quester A", "reason": refusal},
            {"quest": 356, "guid": 8, "character_name": "Quester B", "reason": refusal},
            {
                "quest": 356,
                "guid": 9,
                "character_name": "Quester C",
                "reason": "its objectives did not move for 2 hours of play",
            },
        ]
        objective_counts = [
            {
                "guid": 9,
                "mobcount1": 0,
                "mobcount2": 0,
                "mobcount3": 0,
                "mobcount4": 0,
                "itemcount1": 0,
                "itemcount2": 0,
                "itemcount3": 0,
                "itemcount4": 0,
                "itemcount5": 0,
                "itemcount6": 0,
            }
        ]

        text = qt.body(356, info, rows, objective_counts, "")

        for name, on_map, off_map in (
            ("Bleeding Horror", horror_on_map, horror_off_map),
            ("Wandering Spirit", spirit_on_map, spirit_off_map),
        ):
            self.assertIn(
                "Required creature/object %d x8 (%s): %d spawn(s) on the quest's "
                "map, %d total"
                % (on_map["entry"], name, on_map["n"], on_map["n"] + off_map["n"]),
                text,
            )
        self.assertIn(
            "(Bleeding Horror): 12 spawn(s) on the quest's map, 15 total", text
        )
        self.assertIn(
            "(Wandering Spirit): 5 spawn(s) on the quest's map, 9 total", text
        )
        self.assertIn(
            "The refusal means none matched then; the stored rows do not distinguish "
            "a missing, distant, dead, or otherwise unavailable creature.",
            text,
        )
        self.assertIn("saved objective counters are zero", text)
        self.assertIn("No quester can finish this quest yet.", text)
        self.assertIn("do not identify why the hunt made no progress", text)

    def test_rat_catching_rows_explain_the_take_refusal_without_guessing_why(self):
        row = quest_row(
            quest=416,
            title="Rat Catching",
            level=11,
            min_level=10,
            sort=38,
            item1=3110,
            item_count1=12,
        )
        catalogue = self.catalogue(
            row,
            {
                qc.ITEM_NAMES_SQL.format(ids="3110"): [
                    {"entry": 3110, "name": "Tunnel Rat Ear"}
                ],
                qc.DROP_SQL.format(ids="3110"): [
                    {"item": 3110, "entry": entry}
                    for entry in (1172, 1173, 1174, 1175, 1176, 1177, 1202)
                ],
                qc.REWARD_SQL.format(ids="3110"): [],
                qc.VENDOR_SQL.format(ids="3110"): [],
            },
        )
        reason = qt.NO_GIVER_IN_REACH
        ticket = qt.body(
            416,
            catalogue[0],
            [{"quest": 416, "guid": 7, "character_name": "Tharn", "reason": reason}],
            [],
            "",
        )

        self.assertIn("Required item 3110 x12 (Tunnel Rat Ear)", ticket)
        self.assertIn(
            "creature entries 1172, 1173, 1174, 1175, 1176, 1177, 1202", ticket
        )
        self.assertIn(
            "The take step asks the world for a living creature linked to the quest "
            "within the 20-yard arrival radius.",
            ticket,
        )
        self.assertIn(
            "The refusal means none matched then; the stored rows do not distinguish "
            "a missing, distant, dead, or otherwise unavailable creature.",
            ticket,
        )


if __name__ == "__main__":
    unittest.main()
