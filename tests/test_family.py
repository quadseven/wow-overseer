"""Family-tab builder tests: snapshot rows in, five cards out.

The tab exists because five characters were dying on a loop in a zone thirty
levels above them and the map - 500 dots on a phone - surfaced none of it. So
the cases that matter here are the ones that were invisible: dead, hurt, and
missing, each of which must read as itself and not as the other two.
"""
import unittest

import family
from transform import Geometry

GEO = Geometry.load(".")

# Grug in Elwynn, where the live family actually stands.
ELWYNN = {"guid": 1, "name": "Grug", "level": 19, "race": 1, "class": 1,
          "health": 583, "max_health": 583, "in_combat": 0, "is_bot": 1,
          "group_leader": 1, "map_id": 0, "pos_x": -9000.0, "pos_y": 400.0,
          "age_seconds": 4}


def row(**kw):
    d = dict(ELWYNN)
    d.update(kw)
    return d


def card(payload, name):
    return next(m for m in payload["members"] if m["name"] == name)


class RosterTest(unittest.TestCase):
    def test_roster_is_the_family_table_oldest_first(self):
        names = family.roster()
        self.assertEqual(set(names), set(("Grug", "Ugga", "Og", "Grog", "Bork")))
        # Seniority, which is the same fact head_of_family reads. The father
        # leads the party and must be the first card under the thumb.
        self.assertEqual(names[0], "Grug")
        self.assertEqual(names[-1], "Bork")

    def test_every_member_gets_a_card_even_with_no_rows_at_all(self):
        p = family.build_family([], GEO)
        self.assertEqual(len(p["members"]), 5)
        self.assertEqual(p["here"], 0)
        self.assertEqual(p["expected"], 5)
        self.assertIsNone(p["freshest_seconds"])


class ConditionTest(unittest.TestCase):
    def test_full_health_is_ok(self):
        c = card(family.build_family([row()], GEO), "Grug")
        self.assertEqual(c["condition"], family.OK)
        self.assertEqual(c["health_pct"], 100)
        self.assertTrue(c["present"])

    def test_zero_health_is_dead_and_says_so(self):
        c = card(family.build_family([row(health=0)], GEO), "Grug")
        self.assertEqual(c["condition"], family.DEAD)
        self.assertEqual(c["health_pct"], 0)
        # Dead is PRESENT. A corpse is still in the world, still in the zone
        # that killed it, and still the thing worth looking at - rendering it
        # as "gone" is how the loop stayed invisible.
        self.assertTrue(c["present"])

    def test_a_third_of_health_left_is_hurt(self):
        c = card(family.build_family([row(health=100, max_health=583)], GEO), "Grug")
        self.assertEqual(c["condition"], family.HURT)

    def test_just_above_the_threshold_is_not_cried_over(self):
        health = int(583 * family.HURT_BELOW) + 1
        c = card(family.build_family([row(health=health)], GEO), "Grug")
        self.assertEqual(c["condition"], family.OK)

    def test_missing_row_is_gone_not_dead(self):
        # The distinction the tab is built on: logged out is ordinary, dead
        # is news, and one must never render as the other.
        p = family.build_family([row()], GEO)
        self.assertEqual(card(p, "Bork")["condition"], family.GONE)
        self.assertFalse(card(p, "Bork")["present"])
        self.assertEqual(p["dead"], 0)

    def test_a_gone_member_still_carries_who_they_are(self):
        # A card with no name and no class is not a card; a person scanning
        # five of them needs to know WHICH one is missing.
        c = card(family.build_family([], GEO), "Ugga")
        self.assertEqual(c["role"], "mother")
        self.assertEqual(c["class"], "Priest")

    def test_mid_write_snapshot_is_not_a_corpse(self):
        # max_health 0 with health 0 happens between the module's writes.
        # Reading that as "dead" puts a red card over a healthy character.
        c = card(family.build_family([row(health=200, max_health=0)], GEO), "Grug")
        self.assertEqual(c["condition"], family.OK)

    def test_one_hit_point_never_rounds_away_to_nothing(self):
        c = card(family.build_family([row(health=1, max_health=583)], GEO), "Grug")
        self.assertEqual(c["health_pct"], 1)
        self.assertEqual(c["condition"], family.HURT)

    def test_all_but_one_hit_point_never_rounds_up_to_full(self):
        c = card(family.build_family([row(health=582, max_health=583)], GEO), "Grug")
        self.assertEqual(c["health_pct"], 99)


class WhereAndWhatTest(unittest.TestCase):
    def test_card_carries_zone_level_class_and_combat(self):
        c = card(family.build_family([row(in_combat=1)], GEO), "Grug")
        self.assertEqual(c["level"], 19)
        self.assertEqual(c["class"], "Warrior")
        self.assertEqual(c["faction"], "alliance")
        self.assertTrue(c["combat"])
        self.assertTrue(c["zone"])
        self.assertFalse(c["instance"])

    def test_instance_dweller_says_instance_not_a_guessed_zone(self):
        c = card(family.build_family(
            [row(map_id=34, pos_x=0.0, pos_y=0.0)], GEO), "Grug")
        self.assertTrue(c["instance"])
        self.assertEqual(c["zone"], "inside an instance")

    def test_leader_is_the_world_s_leader_and_carries_the_pov_warning(self):
        # stream.pov_changes_the_family says in as many words that the UI
        # must not hide this: POV on the leader makes the other four follow.
        rows = [row(), row(guid=2, name="Bork", group_leader=1)]
        p = family.build_family(rows, GEO)
        self.assertTrue(card(p, "Grug")["leader"])
        self.assertTrue(card(p, "Grug")["pov_changes_the_family"])
        self.assertFalse(card(p, "Bork")["leader"])
        self.assertFalse(card(p, "Bork")["pov_changes_the_family"])

    def test_leader_outside_the_snapshot_marks_nobody(self):
        # A party led by someone the snapshot has not got must not silently
        # promote whoever happens to sort first.
        p = family.build_family([row(group_leader=999)], GEO)
        self.assertFalse(card(p, "Grug")["leader"])


class HeadlineTest(unittest.TestCase):
    def test_headline_counts_are_what_the_tab_shouts(self):
        rows = [
            row(),
            row(guid=2, name="Ugga", health=0),
            row(guid=3, name="Og", in_combat=1),
        ]
        p = family.build_family(rows, GEO)
        self.assertEqual(p["here"], 3)
        self.assertEqual(p["dead"], 1)
        self.assertEqual(p["in_combat"], 1)

    def test_freshness_is_the_freshest_present_member(self):
        rows = [row(age_seconds=40), row(guid=2, name="Og", age_seconds=6)]
        self.assertEqual(family.build_family(rows, GEO)["freshest_seconds"], 6)


if __name__ == "__main__":
    unittest.main()
