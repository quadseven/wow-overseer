"""The pair of strategies that actually picks a resource node up.

`gather` puts a herb or ore node into the loot stack on a timer and `loot` is
what walks to it and opens it - mod-overseer calls them "one diverter with two
names" (mod_overseer.cpp:1867-1875). Between them they are the only way anybody
in this world collects a node.

NOTHING IN THIS REPOSITORY HAS EVER GRANTED EITHER. Measured against the live
`overseer_command` table on 2026-09-13: `nc +gather` appears five times in three
weeks and every row was hand-typed by an operator; `nc +loot` has never been
issued to anybody, once. Neither survives a relog - PlayerbotAI::ResetStrategies
rebuilds from AiFactory on every login and every autonomous default there sits
behind an IsRandomBot gate a named character never passes - so a hand-typed
grant is a fix with an invisible expiry date.

What that looks like after weeks of it, measured live the same day: all five
characters short of the material their own standing recipe needs, and four of
them holding literally none of it. Grog's Mining 1/75 and zero Rough Stone.
Bork's Skinning 12/75 and zero Ruined Leather Scraps. Grug's Mining 8/75 and
zero Rough Stone. `craft_rhythm` had been ordering them out to gather correctly
for a day; they went, walked past everything, and came back with nothing.

Ticket: infra#3769.
"""
import pathlib
import re
import unittest

import goals

BRIDGE = pathlib.Path(__file__).resolve().parent.parent / "bridge.py"


class TheStrategyPairThatPicksThingsUp(unittest.TestCase):
    def test_both_halves_are_granted_and_neither_alone(self):
        """Taking one and leaving the other leaves half of the measured
        behaviour in place: nodes go into the loot stack and nothing walks to
        them."""
        self.assertEqual(goals.GATHER_STRATEGIES, ("nc +gather", "nc +loot"))

    def test_they_reach_the_engine_that_can_act(self):
        """`goals.strategy_for`'s already-measured `co +grind` lesson: both are
        registered on the NON-combat engine (LootNonCombatStrategy.cpp), so a
        command down the combat channel is delivered cleanly, reports success,
        and adds nothing to the engine that moves the character. `voice.py`
        still documents a `co +loot` phrase that cannot work for exactly this
        reason."""
        for command in goals.GATHER_STRATEGIES:
            self.assertTrue(command.startswith("nc +"), command)

    def test_every_branch_can_gather(self):
        """Orthogonal to leads/aimed/travelling by construction, which is why
        it is a fifth flag and not a fifth branch: the leader on a gathering
        trip needs to be able to loot a node exactly as much as the follower
        beside it does."""
        for leads in (True, False):
            for aimed in (True, False):
                for travelling in (True, False):
                    got = goals.life_strategies(
                        leads=leads, aimed=aimed, travelling=travelling,
                        gathering=True)
                    for command in goals.GATHER_STRATEGIES:
                        self.assertIn(command, got)

    def test_gathering_is_purely_additive(self):
        """A parameter that changes the answer for a caller that did not pass
        it is the quiet regression this family of functions cannot afford. Every
        branch returns exactly what it returned before, with the pair appended
        and nothing reordered."""
        for leads in (True, False):
            for aimed in (True, False):
                for travelling in (True, False):
                    base = goals.life_strategies(
                        leads=leads, aimed=aimed, travelling=travelling)
                    withit = goals.life_strategies(
                        leads=leads, aimed=aimed, travelling=travelling,
                        gathering=True)
                    self.assertEqual(withit[:len(base)], base)
                    self.assertEqual(
                        withit[len(base):], list(goals.GATHER_STRATEGIES))

    def test_the_default_is_the_safe_one(self):
        """infra#2812's rule: an un-updated caller cannot hand out a strategy
        by accident."""
        for leads in (True, False):
            self.assertEqual(
                goals.life_strategies(leads=leads),
                goals.life_strategies(leads=leads, gathering=False))

    def test_the_node_chaser_is_added_after_the_wander_is_dropped(self):
        """The unaimed follower branch opens with `nc -new rpg`. A gather grant
        ahead of it would spend a tick with the wander strategy still on and the
        node chaser newly added, which is the one combination that genuinely
        does scatter a follower."""
        commands = goals.life_strategies(leads=False, gathering=True)
        self.assertLess(commands.index("nc -new rpg"),
                        commands.index("nc +gather"))

    def test_nothing_is_added_twice(self):
        """Adding a strategy already present is a no-op at the game's end, but a
        duplicate row is a duplicate `overseer_command` insert every cycle."""
        for leads in (True, False):
            commands = goals.life_strategies(leads=leads, gathering=True)
            self.assertEqual(len(commands), len(set(commands)))

    def test_every_command_still_reaches_an_engine_that_can_act(self):
        for leads in (True, False):
            for gathering in (True, False):
                for cmd in goals.life_strategies(leads=leads,
                                                 gathering=gathering):
                    verb, _, rest = cmd.partition(" ")
                    self.assertIn(verb, ("nc", "co"), cmd)
                    self.assertTrue(rest.startswith(("+", "-")), cmd)


class TheBridgeActuallyHandsThemOut(unittest.TestCase):
    """Asserted against bridge.py as source, the way `test_aimed_names` guards
    the same module and for the same reason: `_give_them_a_life` opens a
    database connection and there is no other seam. A grant nothing calls is
    the inert mechanism this whole change exists to end."""

    def setUp(self):
        self.text = BRIDGE.read_text(encoding="utf-8")

    def test_the_life_pass_hands_out_the_flag(self):
        self.assertIn("gathering=(name in gathering),", self.text)

    def test_the_gathering_set_is_read_from_the_job_column(self):
        """`overseer_roster.job` is per row on the far side - DriveCraft skips
        anyone whose job is not `craft` and the quest gate stands the drive down
        for every non-quest value, both one row at a time."""
        self.assertIn("if mode == craft_rhythm.MODE_GATHER", self.text)

    def test_it_is_read_once_for_the_whole_sweep(self):
        """`head`, `aimed` and `travelling` are each fetched once for the pass
        so the set cannot change underneath a single roster sweep and hand two
        members contradictory strategies. This must be read the same way."""
        start = self.text.index("def _give_them_a_life(")
        rest = self.text[start:]
        body = rest[: re.search(r"\ndef ", rest).start()]
        self.assertEqual(body.count("_standing_jobs()"), 1)
        self.assertLess(body.index("gathering = {"), body.index("for name in driven:"))


if __name__ == "__main__":
    unittest.main()
