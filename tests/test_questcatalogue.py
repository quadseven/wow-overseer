"""The quest catalogue (#923): which quests are in the classic ruleset, what
each carries, and the filters the endpoint uses."""

import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import questcatalogue as qc  # noqa: E402

HORDE_ONLY = 2 | 16 | 32 | 128 | 512
ALLIANCE_ONLY = 1 | 4 | 8 | 64 | 1024


def quest(qid, level=10, min_level=8, sort=12, races=0, classes=0, follows=0):
    return {
        "quest": qid,
        "title": "Quest %d" % qid,
        "level": level,
        "min_level": min_level,
        "sort": sort,
        "races": races,
        "classes": classes,
        "follows": follows,
    }


def giver(qid, map_id, role="start"):
    return {"quest": qid, "role": role, "map_id": map_id}


def both_ends(qid, map_id):
    return [giver(qid, map_id), giver(qid, map_id, "end")]


class TheRuleset(unittest.TestCase):
    def ids(self, quests, givers):
        return [q.id for q in qc.build(quests, givers)]

    def test_a_quest_given_and_handed_in_on_a_classic_map_is_in(self):
        self.assertEqual(self.ids([quest(1)], both_ends(1, 0)), [1])
        self.assertEqual(self.ids([quest(2, sort=215)], both_ends(2, 1)), [2])
        # A dungeon's quest handed in inside the dungeon.
        self.assertEqual(self.ids([quest(3)], [giver(3, 0), giver(3, 36, "end")]), [3])

    def test_outland_and_northrend_quests_are_out(self):
        quests = [quest(1, level=58, sort=3483), quest(2, level=60, sort=65)]
        self.assertEqual(self.ids(quests, both_ends(1, 530) + both_ends(2, 571)), [])

    def test_a_breadcrumb_handed_in_beyond_the_portal_is_out(self):
        # Taken in the Blasted Lands, handed in in Hellfire.
        rows = [giver(1, 0), giver(1, 530, "end")]
        self.assertEqual(self.ids([quest(1, level=58, sort=4)], rows), [])

    def test_the_blood_elf_and_draenei_starting_lands_are_in(self):
        quests = [
            quest(1, level=3, sort=3430, races=512),
            quest(2, level=12, sort=3525, races=1024),
            # Map 530 outside the starting lands is still Outland.
            quest(3, level=12, sort=3519),
        ]
        rows = both_ends(1, 530) + both_ends(2, 530) + both_ends(3, 530)
        self.assertEqual(self.ids(quests, rows), [1, 2])

    def test_a_city_npc_also_standing_in_outland_still_gives_a_classic_quest(self):
        rows = [giver(1, 530), giver(1, 0), giver(1, 0, "end")]
        self.assertEqual(self.ids([quest(1, sort=-22)], rows), [1])

    def test_a_quest_over_level_60_is_out(self):
        quests = [
            quest(1, level=61),
            quest(2, level=60, min_level=61),
            quest(3, level=60),
        ]
        rows = both_ends(1, 0) + both_ends(2, 0) + both_ends(3, 0)
        self.assertEqual(self.ids(quests, rows), [3])

    def test_a_scaling_quest_is_judged_on_its_map(self):
        rows = both_ends(1, 0) + both_ends(2, 571)
        self.assertEqual(self.ids([quest(1, level=-1), quest(2, level=-1)], rows), [1])

    def test_an_item_started_quest_is_judged_on_its_end(self):
        self.assertEqual(self.ids([quest(1)], [giver(1, 36, "end")]), [1])
        self.assertEqual(self.ids([quest(2)], [giver(2, 571, "end")]), [])

    def test_a_quest_nobody_gives_or_takes_is_out(self):
        self.assertEqual(self.ids([quest(1)], []), [])

    def test_the_expansion_instances_on_classic_ground_are_out(self):
        # Karazhan's door stands in Deadwind Pass; its map is not classic.
        self.assertEqual(self.ids([quest(1, level=60)], both_ends(1, 532)), [])


class WhatAQuestCarries(unittest.TestCase):
    def test_every_field(self):
        row = quest(
            7,
            level=12,
            min_level=10,
            sort=12,
            races=ALLIANCE_ONLY,
            classes=8,
            follows=6,
        )
        (q,) = qc.build([row], both_ends(7, 0))
        self.assertEqual(
            q.view(),
            {
                "id": 7,
                "title": "Quest 7",
                "level": 12,
                "min_level": 10,
                "zone": 12,
                "zone_name": "Elwynn Forest",
                "faction": "alliance",
                "races": ALLIANCE_ONLY,
                "classes": 8,
                "follows": 6,
            },
        )

    def test_a_class_sort_has_no_zone(self):
        (q,) = qc.build([quest(1, sort=-81)], both_ends(1, 1))
        self.assertIsNone(q.zone)
        self.assertEqual(q.zone_name, "")

    def test_the_faction_comes_off_the_race_mask(self):
        self.assertEqual(qc.faction_of(0), "both")
        self.assertEqual(qc.faction_of(-1), "both")
        self.assertEqual(qc.faction_of(HORDE_ONLY), "horde")
        self.assertEqual(qc.faction_of(2), "horde")
        self.assertEqual(qc.faction_of(ALLIANCE_ONLY), "alliance")
        self.assertEqual(qc.faction_of(1 | 2), "both")


class TheFilters(unittest.TestCase):
    def setUp(self):
        rows = [
            quest(1, level=5, sort=12, races=ALLIANCE_ONLY),
            quest(2, level=15, sort=17, races=HORDE_ONLY),
            quest(3, level=25, sort=17),
            quest(4, level=-1, sort=-22),
        ]
        givers = [r for i in range(1, 5) for r in both_ends(i, 0)]
        self.quests = qc.build(rows, givers)

    def ids(self, **kw):
        return [q.id for q in qc.select(self.quests, **kw)]

    def test_each_side_sees_its_own_and_the_shared_quests(self):
        self.assertEqual(self.ids(faction="horde"), [2, 3, 4])
        self.assertEqual(self.ids(faction="alliance"), [1, 3, 4])
        self.assertEqual(self.ids(faction="both"), [1, 2, 3, 4])
        self.assertEqual(self.ids(), [1, 2, 3, 4])

    def test_zone_and_level_range(self):
        self.assertEqual(self.ids(zone=17), [2, 3])
        self.assertEqual(self.ids(level_min=10, level_max=20), [2, 4])
        self.assertEqual(self.ids(level_max=15), [1, 2, 4])
        self.assertEqual(self.ids(faction="horde", zone=17, level_min=20), [3])


class ReadOncePerProcess(unittest.TestCase):
    def tearDown(self):
        qc.forget()

    def test_kept_after_a_full_read_and_retried_after_an_empty_one(self):
        asked = []
        answers = {qc.QUESTS_SQL: [], qc.GIVERS_SQL: both_ends(1, 0)}

        def read(sql):
            asked.append(sql)
            return answers[sql]

        qc.forget()
        self.assertEqual(qc.load(read), ())
        answers[qc.QUESTS_SQL] = [quest(1)]
        self.assertEqual([q.id for q in qc.load(read)], [1])
        self.assertEqual([q.id for q in qc.load(read)], [1])
        self.assertEqual(len(asked), 4)


if __name__ == "__main__":
    unittest.main()
