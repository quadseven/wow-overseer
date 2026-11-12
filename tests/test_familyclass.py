"""A family member takes its class quest between runs (wow-overseer#2336).

guildjobs.plan planned a class step only for maintenance, summoner and raider
members and class_step refused a roster family member, so a family paladin
never started the Redemption chain of #2297 and its family kept a single
resurrection source. A member of a family is now planned a TAKE or a TURN_IN
when its family is idle (the bridge reads that), the giver is near enough for
the gap between two runs, and it has made no class walk lately.
"""

import dataclasses
import unittest
from unittest import mock

import classquest
import familyclass
import guildjobs
import guildroute
from test_guildsocial_bridge import bridge
from test_classquest_item_start import (
    TOME_DWARF,
    book,
    paladin,
    tome_in_bags,
)


CAP = guildroute.MAIL_RUN_YARDS


def member(**over):
    """A family paladin, level 59, standing near Tiza with its errand rewarded."""
    base = dict(role=guildjobs.FAMILY, level=59, quests_done=frozenset({2997}))
    base.update(over)
    return paladin(**base)


def recent_walk(minutes, name="Dwarf", status="ok"):
    return guildjobs.Recent(
        name=name,
        action=classquest.ACTION,
        age_minutes=minutes,
        status=status,
        walk=True,
    )


class TheFamilyMemberGetsItsClassStep(unittest.TestCase):
    def test_a_family_paladin_near_tiza_is_planned_the_take(self):
        step, _doing, _note = guildjobs.class_step(member(), book(), [], CAP)
        self.assertIsNotNone(step)
        self.assertEqual([r.command for r in step.rows], ["take quest:1645"])

    def test_the_same_member_in_a_guild_role_is_planned_as_before(self):
        step, _doing, _note = guildjobs.class_step(
            member(role=guildjobs.RAIDER), book(), [], CAP
        )
        self.assertIsNotNone(step)

    def test_the_item_take_has_no_walk_and_needs_no_gap(self):
        m = member(
            quests_done=frozenset({2997, 1645}), carried=tome_in_bags(TOME_DWARF)
        )
        step, _doing, _note = guildjobs.class_step(m, book(), [recent_walk(30)], CAP)
        self.assertIsNotNone(step)
        self.assertEqual([r.command for r in step.rows], ["take quest:1646"])
        self.assertIsNone(step.walk)

    def test_a_giver_on_the_members_map_within_the_bound_is_walked_to(self):
        m = member(x=-4633.5 + 3000.0, y=-932.0)
        step, _doing, _note = guildjobs.class_step(m, book(), [], CAP)
        self.assertIsNotNone(step)
        self.assertIsNotNone(step.walk)


class TheGapBetweenRunsIsKept(unittest.TestCase):
    def test_a_giver_past_the_walk_bound_is_skipped_and_named(self):
        m = member(x=-4633.5 + familyclass.WALK_YARDS + 500.0, y=-932.0)
        step, _doing, note = guildjobs.class_step(m, book(), [], CAP)
        self.assertIsNone(step)
        self.assertIn("too far", note)

    def test_a_giver_on_another_map_is_skipped_not_crossed(self):
        m = member(map_id=1, x=-282.0, y=-4164.0)
        step, _doing, _note = guildjobs.class_step(m, book(), [], CAP)
        self.assertIsNone(step)
        move, _blocked = classquest.next_move(book(), member())
        far = member(map_id=1, x=0.0, y=0.0)
        self.assertIn("another map", familyclass.holds(far, move, []))

    def test_one_class_walk_per_gap(self):
        m = member(x=-4633.5 + 3000.0, y=-932.0)
        step, _doing, note = guildjobs.class_step(
            m, book(), [recent_walk(familyclass.WALK_GAP_MINUTES - 5)], CAP
        )
        self.assertIsNone(step)
        self.assertIn("class walk", note)

    def test_the_walk_is_asked_again_after_the_gap(self):
        m = member(x=-4633.5 + 3000.0, y=-932.0)
        step, _doing, _note = guildjobs.class_step(
            m, book(), [recent_walk(familyclass.WALK_GAP_MINUTES + 5)], CAP
        )
        self.assertIsNotNone(step)

    def test_a_follower_is_planned_no_walk_but_the_step_it_can_make_here(self):
        far = member(x=-4633.5 + 3000.0, y=-932.0, follows=True)
        step, _doing, note = guildjobs.class_step(far, book(), [], CAP)
        self.assertIsNone(step)
        self.assertIn("follower", note)
        near = member(follows=True)
        step, _doing, _note = guildjobs.class_step(near, book(), [], CAP)
        self.assertIsNotNone(step)

    def test_a_dead_family_member_is_planned_nothing(self):
        step, _doing, _note = guildjobs.class_step(member(alive=False), book(), [], CAP)
        self.assertIsNone(step)

    def test_a_hunt_and_a_use_are_never_planned_for_a_family_member(self):
        for kind in (classquest.HUNT, classquest.USE):
            self.assertEqual(
                familyclass.holds(member(), classquest.Move(kind=kind, quest=1), []),
                familyclass.NOT_A_GAP_STEP,
            )

    def test_a_take_and_a_hand_in_are_gap_steps(self):
        for kind in (classquest.TAKE, classquest.TURN_IN):
            self.assertEqual(
                familyclass.holds(member(), classquest.Move(kind=kind, quest=1), []), ""
            )


class ThePlanTakesFamilyMembersOnlyAsAList(unittest.TestCase):
    def plan(self, family, members=()):
        return guildjobs.plan(
            list(members),
            classes=book(),
            family_members=family,
            now=1000.0,
            far_slots=None,
        )

    def test_the_plan_starts_the_family_members_class_step(self):
        plan = self.plan([member()])
        self.assertEqual([s.holder for s in plan.steps], ["Dwarf"])

    def test_a_family_member_given_no_list_is_planned_nothing(self):
        plan = guildjobs.plan([member()], classes=book(), now=1000.0)
        self.assertEqual(plan.steps, ())

    def test_a_family_member_never_owes_a_class_quest_to_the_dungeon_holds(self):
        plan = self.plan([member()])
        self.assertEqual(dict(plan.owed), {})

    def test_the_switch_turns_the_route_off(self):
        self.assertFalse(familyclass.enabled({"FAMILY_CLASS_STEPS": "off"}))
        self.assertTrue(familyclass.enabled({}))


class TheFamilyIsIdleOnlyBetweenRuns(unittest.TestCase):
    ROSTER = [
        {"name": "Boss", "family": "Boss"},
        {"name": "Dwarf", "family": "Boss"},
        {"name": "Other", "family": "Elder"},
    ]

    def test_a_live_run_of_the_leader_holds_the_whole_family(self):
        idle = familyclass.idle_names(self.ROSTER, live_leaders={"Boss"}, inside=())
        self.assertEqual(idle, {"Other"})

    def test_a_member_inside_an_instance_holds_its_family(self):
        idle = familyclass.idle_names(self.ROSTER, live_leaders=(), inside={"Dwarf"})
        self.assertEqual(idle, {"Other"})

    def test_a_family_with_no_run_and_nobody_inside_is_idle(self):
        idle = familyclass.idle_names(self.ROSTER, live_leaders=(), inside=())
        self.assertEqual(idle, {"Boss", "Dwarf", "Other"})


class TheBridgeReadsTheFamilyAsMembersOfRoleFamily(unittest.TestCase):
    def facts(self):
        rows = [
            {
                "name": "Dwarf",
                "guid": 7,
                "guild_name": "Cave",
                "level": 59,
                "class_id": 2,
                "race": 3,
                "online": 1,
                "map_id": 0,
                "group_leader": 0,
            }
        ]
        return bridge._job_facts_from_rows(rows, ["Dwarf"], set(), [], [], [], [], [])

    def test_a_roster_member_is_in_family_members_and_not_in_members(self):
        facts = self.facts()
        self.assertEqual(facts["members"], [])
        self.assertEqual([m.name for m in facts["family_members"]], ["Dwarf"])
        self.assertEqual(facts["family_members"][0].role, guildjobs.FAMILY)

    def _idle(self, live, members=None):
        facts = {"family_members": members or self.facts()["family_members"]}
        roster = [
            {"name": "Dwarf", "family": "Boss"},
            {"name": "Boss", "family": "Boss"},
        ]
        conn = mock.MagicMock()
        cur = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [{"leader_name": n} for n in live]
        with (
            mock.patch.object(bridge, "_connect", return_value=conn),
            mock.patch.object(bridge, "_fetch_queue_roster", return_value=roster),
        ):
            return [m.name for m in bridge._idle_family_members(facts)]

    def test_a_family_between_runs_is_idle(self):
        self.assertEqual(self._idle([]), ["Dwarf"])

    def test_a_live_run_of_its_leader_holds_it(self):
        self.assertEqual(self._idle(["Boss"]), [])

    def test_a_member_standing_in_an_instance_holds_it(self):
        inside = self.facts()["family_members"]
        inside = [dataclasses.replace(inside[0], map_id=230)]
        self.assertEqual(self._idle([], inside), [])

    def test_the_switch_off_plans_nobody(self):
        with mock.patch.dict("os.environ", {"FAMILY_CLASS_STEPS": "off"}):
            self.assertEqual(self._idle([]), [])


if __name__ == "__main__":
    unittest.main()
