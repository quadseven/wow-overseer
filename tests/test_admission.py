"""Dungeon admission as one pure decision (#738).

campaignqueue.decide_admission answers "may this family enter now?" from plain
facts, with the hold clocks passed in rather than read. These tests pin each of
the five gates the bridge's chain applies, the ceilings that release them, and
the order they speak in.
"""

import pathlib
import re
import unittest

import bag_pressure
import campaignqueue as cq

FAMILY = ("Grug", "Bork")
NOW = 10000.0
CEILING = bag_pressure.CAMPAIGN_RESUME_CEILING_SECONDS
DRESSED = {"equipped": ["mainhand"] + ["s%d" % i for i in range(16)], "purse": 50000}
NAKED = {"equipped": ["mainhand", "chest"], "purse": 50000}
ROOMY = {"Grug": 30, "Bork": 30}


def facts(**kw):
    kw.setdefault("free_slots", ROOMY)
    return cq.Facts(**kw)


def decide(**kw):
    return cq.decide_admission(FAMILY, "rfc", facts(**kw), NOW)


class Gates(unittest.TestCase):
    def test_nothing_in_the_way_admits(self):
        self.assertEqual(decide(gear={"Grug": DRESSED}), cq.Admit())

    def test_town_errand_withholds(self):
        verdict = decide(errand_active=True)
        self.assertEqual(verdict.gate, cq.GATE_ERRAND)
        self.assertIn("dungeon:rfc", verdict.reason)

    def test_funded_gear_gap_withholds(self):
        self.assertEqual(decide(gear={"Grug": NAKED}).gate, cq.GATE_GEAR)

    def test_a_member_too_poor_to_buy_does_not_hold_the_run(self):
        poor = dict(NAKED, purse=100)
        self.assertEqual(decide(gear={"Grug": poor}), cq.Admit())

    def test_gear_waiting_in_the_post_funds_the_hold(self):
        poor = dict(NAKED, purse=100)
        verdict = decide(gear={"Grug": poor}, mailed={"Grug": 2})
        self.assertEqual(verdict.gate, cq.GATE_GEAR)

    def test_gear_hold_releases_past_the_ceiling(self):
        since = NOW - CEILING - 1
        self.assertEqual(decide(gear={"Grug": NAKED}, gear_since=since), cq.Admit())

    def test_queue_stall_counts_toward_the_gear_ceiling(self):
        verdict = decide(gear={"Grug": NAKED}, stall=CEILING + 1)
        self.assertEqual(verdict, cq.Admit())

    def test_near_full_bags_withhold(self):
        verdict = decide(free_slots={"Grug": 2, "Bork": 30}, armed=True)
        self.assertEqual(verdict.gate, cq.GATE_BAG_FULL)

    def test_released_hold_is_stuck(self):
        full = {"Grug": 1, "Bork": 30}
        hold = bag_pressure.BagHoldProgress(
            best=(("Grug", 1),), since=NOW - CEILING - 1, seen=NOW - 1, released=True
        )
        verdict = decide(free_slots=full, hold=hold)
        self.assertEqual(verdict.gate, cq.GATE_BAG_STUCK)

    def test_hold_stood_past_the_forget_bound_is_forgotten(self):
        full = {"Grug": 1, "Bork": 30}
        hold = bag_pressure.BagHoldProgress(
            best=(("Grug", 1),),
            since=NOW - bag_pressure.BAG_HOLD_FORGET_SECONDS,
            seen=NOW - 1,
            released=True,
        )
        # Forgotten, so the stuck gate lets go and the next gate speaks.
        verdict = decide(free_slots=full, hold=hold, armed=True)
        self.assertEqual(verdict.gate, cq.GATE_BAG_FULL)

    def test_unarmed_family_short_of_the_resume_floor_waits(self):
        verdict = decide(free_slots={"Grug": 5, "Bork": 30})
        self.assertEqual(verdict.gate, cq.GATE_TOWN_FIRST)

    def test_armed_family_is_not_held_by_the_resume_floor(self):
        self.assertEqual(
            decide(free_slots={"Grug": 5, "Bork": 30}, armed=True), cq.Admit()
        )

    def test_town_first_releases_past_the_ceiling(self):
        verdict = decide(
            free_slots={"Grug": 5, "Bork": 30}, town_since=NOW - CEILING - 1
        )
        self.assertEqual(verdict, cq.Admit())

    def test_errand_speaks_before_gear(self):
        verdict = decide(errand_active=True, gear={"Grug": NAKED})
        self.assertEqual(verdict.gate, cq.GATE_ERRAND)

    def test_unknown_slot_reading_blocks_nothing(self):
        self.assertEqual(decide(free_slots={"Grug": -1}), cq.Admit())

    def test_decision_reads_no_clock_of_its_own(self):
        later = cq.decide_admission(
            FAMILY, "rfc", facts(gear={"Grug": NAKED}, gear_since=NOW), NOW + CEILING
        )
        self.assertEqual(later, cq.Admit())


class ChainNamesTheSameGates(unittest.TestCase):
    """bridge._drive_dungeon passes gate names as literals (campaign tests run
    it without campaignqueue in scope); they must be the module's constants."""

    def test_literals_match_constants(self):
        source = pathlib.Path(cq.__file__).with_name("bridge.py").read_text("utf-8")
        body = source[source.index("def _drive_dungeon(") :]
        used = set(re.findall(r'settle\("([a-z-]+)"\)', body))
        used |= set(re.findall(r'settle\(\s*"([a-z-]+)" if', body))
        used |= set(re.findall(r'else\s*"([a-z-]+)"\)', body))
        gates = {
            cq.GATE_ERRAND,
            cq.GATE_GEAR,
            cq.GATE_BAG_STUCK,
            cq.GATE_BAG_FULL,
            cq.GATE_TOWN_FIRST,
        }
        self.assertEqual(used, gates)


if __name__ == "__main__":
    unittest.main()
