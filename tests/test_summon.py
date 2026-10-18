"""Automated Ritual of Summoning coordination for the family.

The family has no summoning of its own: the only summon today is the operator's
GM `.summon` shortcut (relay.GM_ALLOWED_PREFIXES), which the progression rules
forbid. This module tests the pure decision half of an automated network:

  * which warlocks are eligible (level 20+, know the ritual, carry a shard);
  * which one to three warlocks converge on the meeting stone;
  * whether the warlocks have gathered at the stone;
  * whether the target arrived at the dungeon entrance, by position before
    and after - never by command status.

The cast itself is issued as an overseer_command row of kind 'summon', never a
GM dot-command. The mod-overseer side performs the actual cast and the stone's
summon; this side decides who goes where and verifies the arrival.

PURE: rows in, decisions out. No MySQL, no Discord, no LLM, no clock.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import travel  # noqa: E402

WARLOCK = 9
MAGE = 8

RITUAL_OF_SUMMONING = 698
SOUL_SHARD = 6265


def member(
    name, class_id=WARLOCK, level=21, spells=None, items=None, map_id=0, x=0.0, y=0.0
):
    """A family member snapshot row, plain dict so the pure module is testable."""
    return {
        "name": name,
        "class_id": class_id,
        "level": level,
        "spells": set(spells or ()),
        "items": set(items or ()),
        "map_id": map_id,
        "pos_x": x,
        "pos_y": y,
    }


def stone(name, map_id, x, y):
    """A meeting stone spawn row (gameobject: map_id, x, y, name)."""
    return {"name": name, "map_id": map_id, "x": x, "y": y}


class EligibleWarlocksTests(unittest.TestCase):
    def test_warlock_level_20_with_ritual_and_shard_is_eligible(self):
        m = member(
            "Locky", level=20, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
        )
        self.assertEqual(travel.eligible_warlocks([m]), [m])

    def test_warlock_below_ritual_level_is_not_eligible(self):
        m = member(
            "Locky", level=19, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
        )
        self.assertEqual(travel.eligible_warlocks([m]), [])

    def test_warlock_without_the_ritual_is_not_eligible(self):
        m = member("Locky", level=21, spells=(), items=(SOUL_SHARD,))
        self.assertEqual(travel.eligible_warlocks([m]), [])

    def test_warlock_without_a_shard_is_not_eligible(self):
        m = member("Locky", level=21, spells=(RITUAL_OF_SUMMONING,), items=())
        self.assertEqual(travel.eligible_warlocks([m]), [])

    def test_non_warlock_is_not_eligible(self):
        m = member(
            "Thak",
            class_id=WARLOCK + 1,
            level=60,
            spells=(RITUAL_OF_SUMMONING,),
            items=(SOUL_SHARD,),
        )
        self.assertEqual(travel.eligible_warlocks([m]), [])

    def test_only_eligible_warlocks_are_returned(self):
        warlock = member(
            "Locky", level=21, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
        )
        underleveled = member(
            "Pip", level=10, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
        )
        mage = member(
            "Zappy",
            class_id=MAGE,
            level=60,
            spells=(RITUAL_OF_SUMMONING,),
            items=(SOUL_SHARD,),
        )
        noshard = member("Shardless", level=21, spells=(RITUAL_OF_SUMMONING,), items=())
        self.assertEqual(
            travel.eligible_warlocks([warlock, underleveled, mage, noshard]),
            [warlock],
        )

    def test_empty_members_returns_empty(self):
        self.assertEqual(travel.eligible_warlocks([]), [])
        self.assertEqual(travel.eligible_warlocks(None), [])


class ChooseSummonersTests(unittest.TestCase):
    def test_picks_highest_level_first(self):
        low = member(
            "Low", level=20, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
        )
        high = member(
            "High", level=60, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
        )
        mid = member(
            "Mid", level=40, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
        )
        self.assertEqual(
            travel.choose_summoners(travel.eligible_warlocks([low, high, mid]), 3),
            ("High", "Mid", "Low"),
        )

    def test_count_one_returns_the_single_best(self):
        low = member(
            "Low", level=20, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
        )
        high = member(
            "High", level=60, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
        )
        self.assertEqual(
            travel.choose_summoners(travel.eligible_warlocks([low, high]), 1),
            ("High",),
        )

    def test_capped_at_three(self):
        members = [
            member(
                "W%d" % i,
                level=20 + i,
                spells=(RITUAL_OF_SUMMONING,),
                items=(SOUL_SHARD,),
            )
            for i in range(5)
        ]
        self.assertEqual(len(travel.choose_summoners(members, 3)), 3)

    def test_out_of_range_count_returns_none(self):
        members = [
            member(
                "W%d" % i,
                level=20 + i,
                spells=(RITUAL_OF_SUMMONING,),
                items=(SOUL_SHARD,),
            )
            for i in range(3)
        ]
        self.assertEqual(travel.choose_summoners(members, 0), ())
        self.assertEqual(travel.choose_summoners(members, 4), ())
        self.assertEqual(travel.choose_summoners(members, -1), ())

    def test_empty_eligible_returns_none(self):
        self.assertEqual(travel.choose_summoners([], 1), ())


class GatheredAtTests(unittest.TestCase):
    def test_all_warlocks_at_the_stone_means_gathered(self):
        s = stone("Ragefire Stone", 8, 100.0, 200.0)
        warlocks = ("Locky", "High")
        positions = {
            "Locky": member("Locky", map_id=8, x=100.0, y=200.0),
            "High": member("High", map_id=8, x=102.0, y=198.0),
        }
        self.assertTrue(travel.gathered_at(warlocks, s, 10, positions))

    def test_one_warlock_away_means_not_gathered(self):
        s = stone("Ragefire Stone", 8, 100.0, 200.0)
        positions = {
            "Locky": member("Locky", map_id=8, x=100.0, y=200.0),
            "High": member("High", map_id=8, x=500.0, y=500.0),
        }
        self.assertFalse(travel.gathered_at(("Locky", "High"), s, 10, positions))

    def test_different_map_means_not_gathered(self):
        s = stone("Ragefire Stone", 8, 100.0, 200.0)
        positions = {
            "Locky": member("Locky", map_id=8, x=100.0, y=200.0),
            "High": member("High", map_id=1, x=100.0, y=200.0),
        }
        self.assertFalse(travel.gathered_at(("Locky", "High"), s, 10, positions))

    def test_no_positions_means_not_gathered(self):
        self.assertFalse(
            travel.gathered_at(("Locky",), stone("S", 8, 0.0, 0.0), 10, {})
        )

    def test_empty_warlock_list_is_vacuously_gathered(self):
        self.assertTrue(travel.gathered_at((), stone("S", 8, 0.0, 0.0), 10, {}))


class TargetArrivedTests(unittest.TestCase):
    def test_target_moved_to_the_stone_counts_as_arrived(self):
        s = stone("Ragefire Stone", 8, 100.0, 200.0)
        before = {"Og": member("Og", map_id=1, x=0.0, y=0.0)}
        after = {"Og": member("Og", map_id=8, x=101.0, y=201.0)}
        self.assertTrue(travel.target_arrived("Og", s, 10, before, after))

    def test_target_already_at_the_stone_is_not_an_arrival(self):
        s = stone("Ragefire Stone", 8, 100.0, 200.0)
        before = {"Og": member("Og", map_id=8, x=100.0, y=200.0)}
        after = {"Og": member("Og", map_id=8, x=100.0, y=200.0)}
        self.assertFalse(travel.target_arrived("Og", s, 10, before, after))

    def test_target_still_far_away_is_not_arrived(self):
        s = stone("Ragefire Stone", 8, 100.0, 200.0)
        before = {"Og": member("Og", map_id=1, x=0.0, y=0.0)}
        after = {"Og": member("Og", map_id=8, x=500.0, y=500.0)}
        self.assertFalse(travel.target_arrived("Og", s, 10, before, after))

    def test_no_after_position_is_not_arrived(self):
        s = stone("Ragefire Stone", 8, 100.0, 200.0)
        before = {"Og": member("Og", map_id=1, x=0.0, y=0.0)}
        self.assertFalse(travel.target_arrived("Og", s, 10, before, {}))


class PlanSummonTests(unittest.TestCase):
    def test_plan_names_the_caster_and_assistants(self):
        s = stone("Ragefire Stone", 8, 100.0, 200.0)
        members = [
            member("Low", level=20, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)),
            member(
                "High", level=60, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
            ),
            member("Mid", level=40, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)),
        ]
        plan = travel.plan_summon("Og", members, s, {}, count=3)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.caster, "High")
        self.assertEqual(plan.assistants, ("Mid", "Low"))
        self.assertEqual(plan.target, "Og")
        self.assertEqual(plan.stone, s)
        self.assertEqual(plan.place, "Ragefire Stone")

    def test_no_eligible_warlocks_returns_none(self):
        s = stone("Ragefire Stone", 8, 100.0, 200.0)
        members = [
            member(
                "Thak",
                class_id=MAGE,
                level=60,
                spells=(RITUAL_OF_SUMMONING,),
                items=(SOUL_SHARD,),
            )
        ]
        self.assertIsNone(travel.plan_summon("Og", members, s, {}, count=1))

    def test_plan_command_is_not_a_gm_dot_command(self):
        s = stone("Ragefire Stone", 8, 100.0, 200.0)
        members = [
            member(
                "Locky", level=21, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
            )
        ]
        plan = travel.plan_summon("Og", members, s, {}, count=1)
        self.assertIsNotNone(plan)
        self.assertFalse(travel.summon_command("Og", plan.caster).startswith("."))


class OneWarlockPlusMeetingStoneTests(unittest.TestCase):
    """The brief's first coordination shape: one warlock plus a meeting stone."""

    def test_one_warlock_at_the_stone_gathers(self):
        s = stone("The Deadmines Stone", 8, 100.0, 200.0)
        members = [
            member(
                "Locky", level=21, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)
            )
        ]
        positions = {"Locky": member("Locky", map_id=8, x=101.0, y=201.0)}
        plan = travel.plan_summon("Og", members, s, positions, count=1)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.caster, "Locky")
        self.assertEqual(plan.assistants, ())
        self.assertTrue(
            travel.gathered_at((plan.caster,) + plan.assistants, s, 10, positions)
        )

    def test_target_summoned_to_the_stone_arrives(self):
        s = stone("The Deadmines Stone", 8, 100.0, 200.0)
        before = {"Og": member("Og", map_id=1, x=0.0, y=0.0)}
        after = {"Og": member("Og", map_id=8, x=100.0, y=200.0)}
        self.assertTrue(travel.target_arrived("Og", s, 10, before, after))


class TwoThreeWarlocksConvergingTests(unittest.TestCase):
    """The brief's second coordination shape: two to three warlocks converging."""

    def test_two_warlocks_converge_on_the_stone(self):
        s = stone("Shadowfang Stone", 8, 100.0, 200.0)
        members = [
            member("A", level=21, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)),
            member("B", level=22, spells=(RITUAL_OF_SUMMONING,), items=(SOUL_SHARD,)),
        ]
        positions = {
            "A": member("A", map_id=8, x=100.0, y=200.0),
            "B": member("B", map_id=8, x=103.0, y=197.0),
        }
        plan = travel.plan_summon("Og", members, s, positions, count=2)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.assistants), 1)
        self.assertTrue(
            travel.gathered_at((plan.caster,) + plan.assistants, s, 10, positions)
        )

    def test_three_warlocks_converge_on_the_stone(self):
        s = stone("Dire Maul Stone", 8, 100.0, 200.0)
        members = [
            member(
                "W%d" % i,
                level=20 + i,
                spells=(RITUAL_OF_SUMMONING,),
                items=(SOUL_SHARD,),
            )
            for i in range(3)
        ]
        positions = {
            m["name"]: member(m["name"], map_id=8, x=100.0, y=200.0) for m in members
        }
        plan = travel.plan_summon("Og", members, s, positions, count=3)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.assistants), 2)
        self.assertTrue(
            travel.gathered_at((plan.caster,) + plan.assistants, s, 10, positions)
        )


if __name__ == "__main__":
    unittest.main()
