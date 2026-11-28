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
            "dropped by creature entries 1172, 1173, 1174, 1175, 1176, 1177, 1202",
            ticket,
        )
        self.assertIn(
            "At that take, the quest command found no live creature giver within "
            "its 20-yard arrival radius.",
            ticket,
        )
        self.assertIn(
            "The creature entries listed above are required-item drop sources, "
            "not evidence of which creature starts the quest.",
            ticket,
        )

    def test_relics_of_wakening_rows_explain_the_take_refusal(self):
        row = quest_row(
            quest=483,
            title="The Relics of Wakening",
            level=9,
            min_level=4,
            sort=141,
            follows=476,
            item1=3405,
            item_count1=1,
            item2=3406,
            item_count2=1,
            item3=3407,
            item_count3=1,
            item4=3408,
            item_count4=1,
        )
        catalogue = self.catalogue(
            row,
            {
                qc.ITEM_NAMES_SQL.format(ids="3405, 3406, 3407, 3408"): [
                    {"entry": 3405, "name": "Raven Claw Talisman"},
                    {"entry": 3406, "name": "Black Feather Quill"},
                    {"entry": 3407, "name": "Sapphire of Sky"},
                    {"entry": 3408, "name": "Rune of Nesting"},
                ],
                qc.DROP_SQL.format(ids="3405, 3406, 3407, 3408"): [],
                qc.REWARD_SQL.format(ids="3405, 3406, 3407, 3408"): [],
                qc.VENDOR_SQL.format(ids="3405, 3406, 3407, 3408"): [],
                qc.OBJECT_LOOT_SQL.format(ids="3405, 3406, 3407, 3408"): [
                    {"item": 3405, "entry": 2740},
                    {"item": 3406, "entry": 2739},
                    {"item": 3407, "entry": 2741},
                    {"item": 3408, "entry": 2742},
                ],
            },
        )
        reason = qt.NO_GIVER_IN_REACH
        ticket = qt.body(
            483,
            catalogue[0],
            [{"quest": 483, "guid": 7, "character_name": "Sylvi", "reason": reason}],
            [],
            "",
        )

        self.assertIn("QuestLevel: 9; MinLevel: 4", ticket)
        self.assertIn("Previous quest: 476", ticket)
        self.assertIn("Required item 3405 x1 (Raven Claw Talisman)", ticket)
        self.assertIn("gameobject loot entries 2740", ticket)
        self.assertIn("Required item 3406 x1 (Black Feather Quill)", ticket)
        self.assertIn("gameobject loot entries 2739", ticket)
        self.assertIn("Required item 3407 x1 (Sapphire of Sky)", ticket)
        self.assertIn("gameobject loot entries 2741", ticket)
        self.assertIn("Required item 3408 x1 (Rune of Nesting)", ticket)
        self.assertIn("gameobject loot entries 2742", ticket)
        self.assertIn("Zone: Teldrassil", ticket)
        self.assertIn(
            "At that take, the quest command found no live creature giver within "
            "its 20-yard arrival radius.",
            ticket,
        )
        self.assertNotIn(
            "The creature entries listed above are required-item drop sources, "
            "not evidence of which creature starts the quest.",
            ticket,
        )

    def test_dead_fields_rows_explain_the_take_refusal_without_guessing_live_state(
        self,
    ):
        # Values come from the ticket's supplied world rows, shaped by
        # questcatalogue.QUESTS_SQL, ITEM_NAMES_SQL, and DROP_SQL. The ledger
        # refusal is written by bridge._record_quest_broken and read through
        # questtickets.BROKEN_SQL; counts use OBJECTIVES_SQL's row shape. The
        # mod-overseer/src/mod_overseer.cpp::QuestCreatureInReach checks for a
        # living creature within its 20-yard arrival radius. This fixture does
        # not invent that creature's live location.
        row = quest_row(
            quest=437,
            title="The Dead Fields",
            level=14,
            min_level=10,
            sort=130,
            item1=3622,
            item_count1=1,
        )
        catalogue = self.catalogue(
            row,
            {
                qc.ITEM_NAMES_SQL.format(ids="3622"): [
                    {"entry": 3622, "name": "Essence of Nightlash"}
                ],
                qc.DROP_SQL.format(ids="3622"): [{"item": 3622, "entry": 1983}],
                qc.REWARD_SQL.format(ids="3622"): [],
                qc.VENDOR_SQL.format(ids="3622"): [],
            },
        )
        reason = qt.NO_GIVER_IN_REACH
        ticket = qt.body(
            437,
            catalogue[0],
            [
                {
                    "quest": 437,
                    "guid": 7,
                    "character_name": "Quester A",
                    "state": "broken",
                    "reason": reason,
                    "ticket": None,
                }
            ],
            [
                {
                    "guid": 7,
                    **{"mobcount%d" % i: 0 for i in range(1, 5)},
                    **{"itemcount%d" % i: 0 for i in range(1, 7)},
                }
            ],
            "",
        )

        self.assertIn("Zone: Silverpine Forest", ticket)
        self.assertIn("QuestLevel: 14; MinLevel: 10", ticket)
        self.assertIn("Required item 3622 x1 (Essence of Nightlash)", ticket)
        self.assertIn("dropped by creature entries 1983", ticket)
        self.assertIn("Reason: " + reason, ticket)
        self.assertIn("Last objective counts: all zero", ticket)
        self.assertIn(
            "At that take, the quest command found no live creature giver within "
            "its 20-yard arrival radius. The stored rows explain the refusal but "
            "do not identify why the lookup found no giver.",
            ticket,
        )
        self.assertIn(
            "The creature entries listed above are required-item drop sources, "
            "not evidence of which creature starts the quest.",
            ticket,
        )
        self.assertNotIn("stored rows confirm the creature relation", ticket)

    def test_mindless_ones_rows_explain_the_stored_stall_without_claiming_a_defect(
        self,
    ):
        # Supplied quest and spawn-count values use questcatalogue.QUESTS_SQL
        # and SPAWN_COUNTS_SQL. The ledger reason is produced by questers.failures
        # and written by bridge._record_quest_broken via questers.BROKEN_SQL;
        # objective counters use the questers.LOG_SQL row shape. The ticket does
        # not supply the quest sort/zone, so the fixture leaves it unspecified.
        row = quest_row(
            quest=364,
            title="The Mindless Ones",
            level=2,
            min_level=1,
            objective1=1501,
            objective_count1=5,
            objective2=1502,
            objective_count2=5,
        )
        catalogue = self.catalogue(
            row,
            {
                qc.CREATURE_NAMES_SQL.format(ids="1501, 1502"): [
                    {"entry": 1501, "name": "Mindless Zombie"},
                    {"entry": 1502, "name": "Wretched Ghoul"},
                ],
                qc.SPAWN_COUNTS_SQL.format(ids="1501, 1502"): [
                    {"entry": 1501, "map": 0, "n": 28},
                    {"entry": 1502, "map": 0, "n": 35},
                ],
            },
        )
        rows = [
            {
                "quest": 364,
                "guid": guid,
                "character_name": "Quester %s" % letter,
                "reason": questers.STALLED,
            }
            for guid, letter in ((7, "A"), (8, "B"), (9, "C"))
        ]
        objectives = [
            {"guid": row["guid"], "mobcount1": 0, "mobcount2": 0} for row in rows
        ]

        text = qt.body(364, catalogue[0], rows, objectives, "")

        self.assertIn("QuestLevel: 2; MinLevel: 1", text)
        self.assertIn("Required creature/object 1501 x5 (Mindless Zombie)", text)
        self.assertIn("28 spawn(s) on the quest's map, 28 total", text)
        self.assertIn("Required creature/object 1502 x5 (Wretched Ghoul)", text)
        self.assertIn("35 spawn(s) on the quest's map, 35 total", text)
        self.assertEqual(text.count("Reason: " + questers.STALLED), 3)
        self.assertEqual(text.count("Last objective counts: all zero"), 3)
        self.assertEqual(
            text.count(
                "The stored reason says a quester made no objective progress for two "
                "hours. These rows list the required objectives and their spawn "
                "counts, but do not identify why that attempt stalled or establish "
                "that the quest cannot be finished."
            ),
            1,
        )

    def test_a_stall_without_objective_rows_is_not_called_reachable(self):
        info = types.SimpleNamespace(
            title="The Mindless Ones",
            zone_name="Tirisfal",
            level=2,
            min_level=1,
            items=(),
            objectives=(),
        )
        rows = [
            {
                "quest": 364,
                "guid": 7,
                "character_name": "Quester A",
                "reason": questers.STALLED,
            }
        ]

        text = qt.body(364, info, rows, [], "")

        self.assertNotIn(
            "The world rows list required objectives and their spawn", text
        )


if __name__ == "__main__":
    unittest.main()
