"""A crossing that cannot be seen is never a crossing that succeeded.

Every test here is about one of two things: that an unreadable world produces a
refusal rather than a guess, and that the refusal names the fact it is missing.
The single most important one is
`test_four_on_the_far_map_and_one_unreadable_is_not_an_arrival` - it is the
whole difference between this module and a decision layer that reads an absent
snapshot row as a negative observation.
"""
import json
import os
import unittest

import crossing
import travel

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAMILY = ("Grug", "Ugga", "Og", "Grog", "Bork")

# Wailing Caverns, as entrances.json actually records it. Quoted here so the
# tests below are readable, and pinned against the real file by
# test_the_wailing_caverns_record_is_the_one_this_module_refuses.
WAILING_CAVERNS = "43"


def rows(**where):
    """Snapshot rows in the shape map_server._fetch_family selects.

    `where` maps a name to a map id, or to a (map_id, age_seconds) pair. A name
    left out has no row at all, which is what a logged-out member looks like.
    """
    out = []
    for name, value in where.items():
        map_id, age = value if isinstance(value, tuple) else (value, 5)
        out.append({"name": name, "map_id": map_id, "age_seconds": age})
    return out


def a_crossing(members=FAMILY):
    return crossing.plan(members, crossing.EASTERN_KINGDOMS, crossing.KALIMDOR)


class PlanTests(unittest.TestCase):
    def test_a_crossing_needs_a_roster(self):
        with self.assertRaises(ValueError):
            crossing.plan([], 0, 1)
        with self.assertRaises(ValueError):
            crossing.plan(["", "  "], 0, 1)

    def test_a_crossing_needs_two_different_maps(self):
        with self.assertRaises(ValueError):
            crossing.plan(FAMILY, 1, 1)

    def test_the_roster_is_a_set_of_names(self):
        plan = crossing.plan(["Grug", "Grug", "Ugga"], 0, 1)
        self.assertEqual(plan.members, frozenset({"Grug", "Ugga"}))


class ReadOneMemberTests(unittest.TestCase):
    def setUp(self):
        self.plan = a_crossing()

    def test_a_fresh_row_on_the_origin_map_reads_origin(self):
        reading = crossing.read_member(
            "Grug", {"map_id": 0, "age_seconds": 3}, self.plan)
        self.assertEqual(reading["where"], crossing.ORIGIN)
        self.assertEqual(reading["map_id"], 0)
        self.assertEqual(reading["reason"], "")

    def test_a_fresh_row_on_the_destination_map_reads_destination(self):
        reading = crossing.read_member(
            "Grug", {"map_id": 1, "age_seconds": 3}, self.plan)
        self.assertEqual(reading["where"], crossing.DESTINATION)

    def test_a_third_map_is_elsewhere_and_not_quietly_one_of_the_two(self):
        reading = crossing.read_member(
            "Grug", {"map_id": 43, "age_seconds": 3}, self.plan)
        self.assertEqual(reading["where"], crossing.ELSEWHERE)
        self.assertEqual(reading["map_id"], 43)

    def test_no_row_at_all_is_unreadable_and_not_absent(self):
        """The failure this module exists against, in its smallest form.

        The query behind these rows returns nothing for a member who logged
        out, crashed, or whose worldserver stopped writing snapshots. Reading
        that as "not on the destination map" is how a party gets declared
        aboard, or arrived, on the strength of a query that failed.
        """
        reading = crossing.read_member("Grug", None, self.plan)
        self.assertEqual(reading["where"], crossing.UNREADABLE)
        self.assertIsNone(reading["map_id"])
        self.assertEqual(reading["reason"], "no snapshot row")

    def test_a_stale_row_is_unreadable_however_confidently_it_names_a_map(self):
        reading = crossing.read_member(
            "Grug", {"map_id": 1, "age_seconds": 600}, self.plan)
        self.assertEqual(reading["where"], crossing.UNREADABLE)
        self.assertIn("600 seconds old", reading["reason"])

    def test_the_freshness_boundary_matches_the_query_that_feeds_it(self):
        """`updated_at > NOW() - INTERVAL 60 SECOND` is exclusive at 60.

        Matched exactly rather than approximately: a module that accepted one
        second more than its own query returns would be a third surface
        disagreeing with the map and the family card about who is online, which
        is the disagreement _fetch_family's comment exists to prevent.
        """
        inside = crossing.read_member(
            "Grug",
            {"map_id": 1, "age_seconds": crossing.SNAPSHOT_MAX_AGE_SECONDS - 1},
            self.plan)
        at_limit = crossing.read_member(
            "Grug", {"map_id": 1, "age_seconds": crossing.SNAPSHOT_MAX_AGE_SECONDS},
            self.plan)
        self.assertEqual(inside["where"], crossing.DESTINATION)
        self.assertEqual(at_limit["where"], crossing.UNREADABLE)

    def test_a_row_with_no_age_is_unreadable(self):
        reading = crossing.read_member("Grug", {"map_id": 1}, self.plan)
        self.assertEqual(reading["where"], crossing.UNREADABLE)
        self.assertIn("no age", reading["reason"])

    def test_a_negative_age_is_broken_rather_than_very_fresh(self):
        reading = crossing.read_member(
            "Grug", {"map_id": 1, "age_seconds": -5}, self.plan)
        self.assertEqual(reading["where"], crossing.UNREADABLE)
        self.assertIn("clocks disagree", reading["reason"])

    def test_a_row_with_no_map_or_a_junk_map_is_unreadable(self):
        no_map = crossing.read_member("Grug", {"age_seconds": 1}, self.plan)
        junk = crossing.read_member(
            "Grug", {"map_id": "Kalimdor", "age_seconds": 1}, self.plan)
        self.assertEqual(no_map["where"], crossing.UNREADABLE)
        self.assertEqual(junk["where"], crossing.UNREADABLE)
        self.assertIn("not a number", junk["reason"])


class ReadPartyTests(unittest.TestCase):
    def test_there_is_one_reading_per_member_however_many_rows_arrived(self):
        plan = a_crossing()
        readings = crossing.read_party(plan, rows(Grug=0, Ugga=0))
        self.assertEqual(len(readings), len(FAMILY))
        self.assertEqual([r["name"] for r in readings], sorted(FAMILY))
        missing = {r["name"] for r in readings
                   if r["where"] == crossing.UNREADABLE}
        self.assertEqual(missing, {"Og", "Grog", "Bork"})

    def test_rows_for_names_off_the_roster_are_ignored(self):
        plan = a_crossing(("Grug", "Ugga"))
        readings = crossing.read_party(plan, rows(Grug=0, Ugga=0, Stranger=1))
        self.assertEqual([r["name"] for r in readings], ["Grug", "Ugga"])

    def test_no_rows_at_all_still_produces_a_full_roster_of_refusals(self):
        readings = crossing.read_party(a_crossing(), None)
        self.assertEqual(len(readings), len(FAMILY))
        self.assertTrue(all(r["where"] == crossing.UNREADABLE for r in readings))


class StandingTests(unittest.TestCase):
    def standing_for(self, **where):
        return crossing.standing(crossing.read_party(a_crossing(), rows(**where)))

    def test_everybody_on_the_origin_map_is_assembled(self):
        self.assertEqual(
            self.standing_for(Grug=0, Ugga=0, Og=0, Grog=0, Bork=0),
            crossing.ASSEMBLED)

    def test_everybody_on_the_destination_map_has_arrived(self):
        self.assertEqual(
            self.standing_for(Grug=1, Ugga=1, Og=1, Grog=1, Bork=1),
            crossing.ARRIVED)

    def test_four_on_the_far_map_and_one_unreadable_is_not_an_arrival(self):
        """The headline rule: BLIND outranks a majority reading.

        Four members observed on Kalimdor say nothing whatsoever about the
        fifth. Calling this ARRIVED is the fail-open that hands the party on to
        the next leg with one member still on another continent, where nothing
        in this system can reach them: `follow` only acts while the master is on
        the same map, and both `at:` and `trigger:` aims refuse when the map
        differs.
        """
        self.assertEqual(self.standing_for(Grug=1, Ugga=1, Og=1, Grog=1),
                         crossing.BLIND)

    def test_a_stale_reading_cannot_complete_an_arrival_either(self):
        self.assertEqual(
            self.standing_for(Grug=1, Ugga=1, Og=1, Grog=1, Bork=(1, 900)),
            crossing.BLIND)

    def test_a_party_across_both_maps_is_split(self):
        self.assertEqual(
            self.standing_for(Grug=1, Ugga=1, Og=1, Grog=0, Bork=0),
            crossing.SPLIT)

    def test_a_member_on_a_third_map_outranks_a_split(self):
        """SCATTERED, not SPLIT, and the order is deliberate.

        A member on map 43 is not on the wrong end of this route; they are off
        it. Grading that as SPLIT would describe it in a vocabulary that does
        not fit, and the recovery for the two is not the same.
        """
        self.assertEqual(
            self.standing_for(Grug=1, Ugga=1, Og=0, Grog=0, Bork=43),
            crossing.SCATTERED)

    def test_an_empty_reading_list_is_blind_and_not_arrived(self):
        self.assertEqual(crossing.standing([]), crossing.BLIND)


LEGS_BY_NAME = {leg.name: leg for leg in crossing.LEGS}


class LegTests(unittest.TestCase):
    def test_every_leg_names_a_source_for_every_fact_it_needs(self):
        """A blocker with no source is a refusal nobody can act on."""
        for leg in crossing.LEGS:
            for fact in leg.needs:
                self.assertIn(fact, crossing.FACT_SOURCES,
                              "%s needs %r, which has no source" % (leg.name, fact))

    def test_every_leg_fails_closed_to_an_action_that_does_nothing(self):
        """No leg may fail closed by crossing or by declaring an arrival."""
        for leg in crossing.LEGS:
            self.assertIn(leg.fails_closed_to,
                          (crossing.HOLD, crossing.WAIT, crossing.ALARM),
                          "%s fails closed to %r" % (leg.name, leg.fails_closed_to))

    def test_this_world_can_see_two_of_the_nine_facts(self):
        """Pinned so that adding a fact source without wiring it is visible."""
        self.assertEqual(crossing.OBSERVABLE,
                         frozenset({crossing.FACT_MEMBER_MAP,
                                    crossing.FACT_MEMBER_POSITION}))
        self.assertTrue(crossing.OBSERVABLE < crossing.ALL_FACTS)

    def test_the_first_blocked_leg_is_the_earliest_and_not_the_worst(self):
        blocked = crossing.first_blocked_leg()
        self.assertEqual(blocked.name, "walk to the dock")
        self.assertEqual(crossing.leg_blockers(blocked),
                         (crossing.FACT_DOCK_POSITION,))

    def test_the_walk_on_leg_is_blocked_only_on_the_targets_footing(self):
        """Its member facts exist; the target's z does not."""
        walk_on = LEGS_BY_NAME["walk on"]
        self.assertEqual(crossing.leg_blockers(walk_on),
                         (crossing.FACT_TARGET_FOOTING,))

    def test_nothing_is_blocked_when_every_fact_is_available(self):
        self.assertIsNone(crossing.first_blocked_leg(crossing.ALL_FACTS))


class DecideTests(unittest.TestCase):
    def decide_for(self, available=crossing.OBSERVABLE, **where):
        return crossing.decide(a_crossing(), rows(**where), available)

    def test_an_unreadable_party_waits_and_says_who_and_why(self):
        verdict = self.decide_for(Grug=0, Ugga=0, Og=0, Grog=0)
        self.assertEqual(verdict["action"], crossing.WAIT)
        self.assertEqual(verdict["standing"], crossing.BLIND)
        self.assertEqual(verdict["unreadable"], ("Bork",))
        self.assertIn("Bork", verdict["reason"])
        self.assertIn("no snapshot row", verdict["reason"])

    def test_a_split_party_alarms_and_names_both_halves(self):
        verdict = self.decide_for(Grug=1, Ugga=1, Og=0, Grog=0, Bork=0)
        self.assertEqual(verdict["action"], crossing.ALARM)
        self.assertEqual(verdict["standing"], crossing.SPLIT)
        self.assertEqual(sorted(verdict["ahead"]), ["Grug", "Ugga"])
        self.assertEqual(sorted(verdict["behind"]), ["Bork", "Grog", "Og"])
        self.assertIn("follow", verdict["reason"])

    def test_a_split_party_is_never_told_to_carry_on(self):
        verdict = self.decide_for(Grug=1, Ugga=0, Og=0, Grog=0, Bork=0)
        self.assertNotIn(verdict["action"], (crossing.CROSS, crossing.ARRIVE))

    def test_a_scattered_party_alarms_and_says_which_map(self):
        verdict = self.decide_for(Grug=0, Ugga=0, Og=0, Grog=0, Bork=43)
        self.assertEqual(verdict["action"], crossing.ALARM)
        self.assertEqual(verdict["standing"], crossing.SCATTERED)
        self.assertEqual(verdict["astray"], (("Bork", 43),))
        self.assertIn("map 43", verdict["reason"])

    def test_an_arrival_needs_every_member_seen_on_the_far_map(self):
        verdict = self.decide_for(Grug=1, Ugga=1, Og=1, Grog=1, Bork=1)
        self.assertEqual(verdict["action"], crossing.ARRIVE)

    def test_an_assembled_party_holds_at_the_dock_and_says_what_is_missing(self):
        verdict = self.decide_for(Grug=0, Ugga=0, Og=0, Grog=0, Bork=0)
        self.assertEqual(verdict["standing"], crossing.ASSEMBLED)
        self.assertEqual(verdict["action"], crossing.HOLD)
        self.assertEqual(verdict["leg"], "walk to the dock")
        self.assertEqual(verdict["blocked_on"], (crossing.FACT_DOCK_POSITION,))
        self.assertIn("dock position", verdict["reason"])

    def test_a_world_that_can_see_everything_crosses(self):
        """The machine is not hardcoded to refuse.

        Handed every fact, the same assembled party gets CROSS. That is what
        makes the HOLD above a statement about this deployment's schema rather
        than about this module's opinion, and it is what will fail loudly if
        somebody later short-circuits the fact check.
        """
        verdict = self.decide_for(available=crossing.ALL_FACTS,
                                  Grug=0, Ugga=0, Og=0, Grog=0, Bork=0)
        self.assertEqual(verdict["action"], crossing.CROSS)
        self.assertEqual(verdict["blocked_on"], ())

    def test_being_handed_more_facts_never_turns_blind_into_progress(self):
        """Facts about the world are not readings about the party.

        Granting every fact in the catalogue must not make an unreadable member
        readable. This is the guard against a future caller passing ALL_FACTS
        as a convenience and silently disabling the freshness rule with it.
        """
        verdict = self.decide_for(available=crossing.ALL_FACTS,
                                  Grug=1, Ugga=1, Og=1, Grog=1)
        self.assertEqual(verdict["action"], crossing.WAIT)
        self.assertEqual(verdict["standing"], crossing.BLIND)

    def test_the_verdict_always_carries_a_reading_per_member(self):
        verdict = self.decide_for(Grug=0)
        self.assertEqual(len(verdict["members"]), len(FAMILY))

    def test_say_carries_the_action_and_the_reason(self):
        line = crossing.say(self.decide_for(Grug=0, Ugga=0, Og=0, Grog=0, Bork=0))
        self.assertIn(crossing.HOLD, line)
        self.assertIn("walk to the dock", line)
        self.assertIn("dock position", line)


class AimTests(unittest.TestCase):
    def test_the_aim_is_the_grammar_the_worldserver_parses(self):
        """`m ':' x ',' y ',' z`, with every separator checked on that side."""
        self.assertEqual(crossing.aim_at_place(1, -753.596, -2212.78, 17.5),
                         "at:1:-753.6,-2212.78,17.5")

    def test_a_whole_number_coordinate_keeps_no_trailing_decimals(self):
        self.assertEqual(crossing.aim_at_place(0, -100.0, 25.0, 0.0),
                         "at:0:-100,25,0")

    def test_an_aim_too_long_for_the_column_is_refused_rather_than_truncated(self):
        """VARCHAR(32), and MySQL truncates rather than refusing.

        A truncated aim is written, never parses, and looks exactly like a
        character who did not walk. This is the only place that can still be
        seen.
        """
        with self.assertRaises(ValueError) as caught:
            crossing.aim_at_place(571, -12345.678, -23456.789, -1234.5)
        self.assertIn(str(travel.COLUMN_WIDTH), str(caught.exception))

    def test_the_width_limit_comes_from_travel_and_is_not_a_second_copy(self):
        self.assertEqual(travel.COLUMN_WIDTH, 32)


class ApproachTests(unittest.TestCase):
    def test_the_wailing_caverns_record_is_the_one_this_module_refuses(self):
        """Pinned against the committed file, not against a remembered pair.

        If entrances.json ever gains a z, this test fails and the refusal below
        stops being correct - which is exactly when somebody should be told.
        """
        with open(os.path.join(HERE, "entrances.json"), encoding="utf-8") as f:
            entrances = json.load(f)
        record = entrances[WAILING_CAVERNS]
        self.assertEqual(record["map"], crossing.KALIMDOR)
        self.assertAlmostEqual(record["x"], -753.596, places=3)
        self.assertAlmostEqual(record["y"], -2212.78, places=2)
        self.assertNotIn("z", record)

        verdict = crossing.approach(record)
        self.assertFalse(verdict["usable"])
        self.assertEqual(verdict["aim"], "")
        self.assertIn("no z", verdict["refused"])

    def test_an_entrance_on_the_wrong_map_is_refused(self):
        verdict = crossing.approach({"map": 0, "x": 1.0, "y": 2.0, "z": 3.0},
                                    crossing.KALIMDOR)
        self.assertFalse(verdict["usable"])
        self.assertIn("not the crossing's map", verdict["refused"])

    def test_a_missing_record_is_refused_rather_than_defaulted(self):
        for bad in (None, {}, {"map": 1, "x": 1.0}, {"map": "one", "x": 1, "y": 2}):
            self.assertFalse(crossing.approach(bad)["usable"], bad)

    def test_an_entrance_with_a_measured_z_produces_a_usable_aim(self):
        """The seam works the day the footing is measured, and not before."""
        verdict = crossing.approach(
            {"map": 1, "x": -753.596, "y": -2212.78, "z": 17.5})
        self.assertTrue(verdict["usable"])
        self.assertEqual(verdict["aim"], "at:1:-753.6,-2212.78,17.5")
        self.assertLessEqual(len(verdict["aim"]), travel.COLUMN_WIDTH)

    def test_no_z_is_ever_supplied_by_this_module(self):
        """The refusal is not a placeholder for a number added later here.

        A z belongs to the world database, and the only honest way to get one is
        the `trigger:<id>` aim the C++ side already has, which reads position
        and footing out of the areatrigger table together so the two cannot
        drift. Wailing Caverns' trigger id is not in this repository.
        """
        record = {"map": 1, "x": -753.596, "y": -2212.78}
        self.assertFalse(crossing.approach(record)["usable"])
        self.assertFalse(crossing.approach(dict(record, z=None))["usable"])


if __name__ == "__main__":
    unittest.main()
