"""A roster family member learns to ride between runs (ticket 2625).

Read on the dev realm on 2026-11-15: 9 of the 10 level 60 family members held
no Riding skill though each carried far more than the 4 gold Apprentice Riding
costs. guildjobs.riding_step serves guild members off the roster through their
purchase order; a family member has none and was never planned a step, so
nobody walked it to a riding trainer. The walk is the same row, bounded like a
family class step: only between runs, never while following, offline, dead or
fighting.
"""

import unittest

import guildjobs
import guildroute
import familyclass
import purse
from test_classquest import who
from test_classquest_item_start import book

GOLD = 10000
RIDING = purse.RIDING_SKILL


def seat(**over):
    base = dict(
        name="Grugg",
        role=guildjobs.FAMILY,
        level=60,
        money=300 * GOLD,
        skills={},
        eligible=True,
    )
    base.update(over)
    return who(**base)


def ago(minutes, action=guildjobs.RIDING_ACTION, name="Grugg", **over):
    return guildjobs.Recent(
        name=name, action=action, age_minutes=minutes, status="ok", walk=True, **over
    )


class WhoIsWalkedToTheTrainer(unittest.TestCase):
    def step(self, member, recent=()):
        return guildjobs.family_riding_step(member, list(recent))

    def test_a_level_60_member_with_gold_and_no_riding_walks_for_apprentice(self):
        step, _note = self.step(seat())
        self.assertIsNotNone(step)
        self.assertEqual(step.action, guildjobs.RIDING_ACTION)
        command = step.rows[0].command
        self.assertIn("walk-to-trainer skill:%d" % RIDING, command)
        self.assertIn("learn:%d" % purse.APPRENTICE.spell, command)

    def test_the_walk_is_bounded_like_a_family_class_walk(self):
        step, _note = self.step(seat())
        self.assertIn("max:%d" % int(familyclass.WALK_YARDS), step.rows[0].command)

    def test_apprentice_held_and_the_gold_for_journeyman_buys_it(self):
        step, _note = self.step(seat(skills={RIDING: (75, 75)}))
        self.assertIn("learn:%d" % purse.JOURNEYMAN.spell, step.rows[0].command)

    def test_apprentice_held_and_too_little_gold_for_journeyman_waits(self):
        poor = seat(skills={RIDING: (75, 75)}, money=20 * GOLD)
        step, note = self.step(poor)
        self.assertIsNone(step)
        self.assertIn("saves for", note)

    def test_journeyman_held_at_60_wants_nothing_more(self):
        step, _note = self.step(seat(skills={RIDING: (150, 150)}))
        self.assertIsNone(step)

    def test_below_level_20_there_is_no_rank_to_buy(self):
        step, _note = self.step(seat(level=19))
        self.assertIsNone(step)

    def test_a_member_at_40_with_no_riding_buys_apprentice_first(self):
        step, _note = self.step(seat(level=40))
        self.assertIn("learn:%d" % purse.APPRENTICE.spell, step.rows[0].command)

    def test_the_apprentice_fee_leaves_the_member_a_float(self):
        broke = seat(money=purse.APPRENTICE.cost)
        step, note = self.step(broke)
        self.assertIsNone(step)
        self.assertIn("saves for", note)


class WhenItIsHeld(unittest.TestCase):
    def step(self, member, recent=()):
        return guildjobs.family_riding_step(member, list(recent))[0]

    def test_not_while_offline_dead_or_fighting(self):
        for over in (dict(online=False), dict(alive=False), dict(in_combat=True)):
            self.assertIsNone(self.step(seat(**over)), over)

    def test_not_while_following_its_leader(self):
        self.assertIsNone(self.step(seat(follows=True)))

    def test_not_twice_inside_the_riding_cooldown(self):
        self.assertIsNone(self.step(seat(), [ago(30)]))

    def test_asked_again_after_the_cooldown(self):
        self.assertIsNotNone(self.step(seat(), [ago(600)]))

    def test_a_refusal_for_no_trainer_on_the_map_is_not_asked_again_there(self):
        refused = ago(
            600,
            refusal=guildjobs.NO_TRAINER_ON_MAP_REFUSAL,
            skill_id=RIDING,
            map_id=1,
        )
        self.assertIsNone(self.step(seat(map_id=1), [refused]))

    def test_unread_ground_is_not_a_bounded_walk(self):
        self.assertIsNone(self.step(seat(x=None)))


class InThePlan(unittest.TestCase):
    def plan(self, family):
        return guildjobs.plan(
            [],
            classes=book(),
            family_members=family,
            now=1000.0,
            far_slots=None,
        )

    def test_an_idle_family_member_is_planned_the_riding_walk(self):
        plan = self.plan([seat()])
        self.assertEqual([s.action for s in plan.steps], [guildjobs.RIDING_ACTION])
        self.assertEqual([s.holder for s in plan.steps], ["Grugg"])

    def test_a_member_with_riding_is_planned_nothing(self):
        plan = self.plan([seat(skills={RIDING: (150, 150)})])
        self.assertEqual(plan.steps, ())

    def test_the_family_switch_turns_the_walk_off(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {familyclass.ENV_SWITCH: "off"}):
            plan = self.plan([seat()])
        self.assertEqual(plan.steps, ())


class TheGuildStepIsUnchanged(unittest.TestCase):
    def test_a_guild_member_still_needs_its_purchase_order(self):
        member = who(level=60, role=guildjobs.RAIDER, money=300 * GOLD, eligible=True)
        step, _note = guildjobs.riding_step(member, [])
        self.assertIsNone(step)
        self.assertGreater(guildroute.FAR_WALK_YARDS, familyclass.WALK_YARDS)


if __name__ == "__main__":
    unittest.main()
