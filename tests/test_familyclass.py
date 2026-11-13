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

    def test_a_walk_from_ground_that_is_not_read_is_held_not_assumed_near(self):
        move, _blocked = classquest.next_move(book(), member())
        unread = member(x=None)
        self.assertIn("not read", familyclass.holds(unread, move, []))

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

    def test_a_live_run_names_the_hold_for_each_family_member(self):
        holds = familyclass.not_idle_holds(self.ROSTER, live_leaders={"Boss"})
        self.assertEqual(
            holds,
            {
                "Boss": "its family has an active dungeon run",
                "Dwarf": "its family has an active dungeon run",
            },
        )

    def test_an_instance_and_town_errand_name_their_holds(self):
        holds = familyclass.not_idle_holds(
            self.ROSTER, inside={"Dwarf"}, errands={"Other"}
        )
        self.assertEqual(
            holds,
            {
                "Boss": "a family member is still inside an instance",
                "Dwarf": "a family member is still inside an instance",
                "Other": "the member is on a town errand",
            },
        )


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

    def test_a_family_hold_is_visible_only_for_an_owed_class_quest(self):
        m = self.facts()["family_members"][0]
        result = guildjobs.plan(
            [],
            classes=book(),
            family_candidates=[m],
            family_holds={m.name: "its family has an active dungeon run"},
        )
        self.assertEqual(
            result.class_holds[m.name], "its family has an active dungeon run"
        )
        settled = dataclasses.replace(m, class_id=1)
        result = guildjobs.plan(
            [],
            classes=book(),
            family_candidates=[settled],
            family_holds={settled.name: "its family has an active dungeon run"},
        )
        self.assertNotIn(settled.name, result.class_holds)

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

    def _state(self, live, members=None):
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
            return bridge._family_class_state(facts)

    def test_a_family_between_runs_is_idle(self):
        self.assertEqual(self._idle([]), ["Dwarf"])

    def test_a_live_run_of_its_leader_holds_it(self):
        self.assertEqual(self._idle(["Boss"]), [])

    def test_a_live_run_carries_a_named_hold_for_its_owed_family_member(self):
        idle, holds = self._state(["Boss"])
        self.assertEqual(idle, [])
        self.assertEqual(holds["Dwarf"], "its family has an active dungeon run")

    def test_a_member_standing_in_an_instance_holds_it(self):
        inside = self.facts()["family_members"]
        inside = [dataclasses.replace(inside[0], map_id=230)]
        self.assertEqual(self._idle([], inside), [])
        _idle, holds = self._state([], inside)
        self.assertEqual(holds["Dwarf"], "a family member is still inside an instance")

    def test_the_switch_off_plans_nobody(self):
        with mock.patch.dict("os.environ", {"FAMILY_CLASS_STEPS": "off"}):
            self.assertEqual(self._idle([]), [])


class TheLoneStepIsGuardedAgainstTheErrandAndTheGround(unittest.TestCase):
    """wow-overseer#2338: the busy guard, the level check and no boat."""

    def far(self, **over):
        return member(x=-4633.5 + 3000.0, y=-932.0, **over)

    def plan(self, m, danger=None):
        return guildjobs.plan(
            [],
            classes=book(),
            family_members=[m],
            now=1000.0,
            far_slots=None,
            family_danger=danger,
        )

    def test_a_far_giver_with_no_danger_read_is_held_not_assumed_safe(self):
        plan = self.plan(self.far())
        self.assertEqual(plan.steps, ())
        self.assertTrue(any("not read" in n for n in plan.notes))

    def test_a_giver_well_above_the_member_is_not_walked_to(self):
        plan = self.plan(self.far(), {"Dwarf": 59 + familyclass.DANGER_MARGIN})
        self.assertEqual(plan.steps, ())
        self.assertTrue(any("no lone walk" in n for n in plan.notes))

    def test_a_giver_in_the_members_band_is_walked_to(self):
        plan = self.plan(self.far(), {"Dwarf": 59 + familyclass.DANGER_MARGIN - 1})
        self.assertEqual([s.holder for s in plan.steps], ["Dwarf"])

    def test_a_giver_in_reach_needs_no_ground_read(self):
        plan = self.plan(member())
        self.assertEqual([s.holder for s in plan.steps], ["Dwarf"])

    def test_the_claims_busy_set_still_holds_a_member(self):
        plan = guildjobs.plan(
            [],
            classes=book(),
            family_members=[member()],
            now=1000.0,
            far_slots=None,
            busy={"Dwarf"},
        )
        self.assertEqual(plan.steps, ())

    def test_a_boat_crossing_is_not_planned_on_the_lone_path(self):
        m = self.far()
        with mock.patch.object(guildjobs, "across_the_water", return_value=True):
            step, _doing, note = guildjobs.class_step(m, book(), [], CAP)
        self.assertIsNone(step)
        self.assertIn("across the water", note)

    def test_errand_free_drops_the_members_on_an_errand(self):
        a, b = member(name="A"), member(name="B")
        self.assertEqual(familyclass.errand_free([a, b], {"B"}), [a])


class TheBridgeKeepsAnErrandMemberOutOfTheFamilyList(
    TheBridgeReadsTheFamilyAsMembersOfRoleFamily
):
    def test_a_member_on_a_town_errand_is_not_idle(self):
        state = mock.Mock(active=True)
        with mock.patch.dict(bridge._TOWN_ERRANDS, {("Boss", "Dwarf"): state}):
            self.assertEqual(self._idle([]), [])

    def test_an_ended_errand_does_not_hold_it(self):
        state = mock.Mock(active=False)
        with mock.patch.dict(bridge._TOWN_ERRANDS, {("Boss", "Dwarf"): state}):
            self.assertEqual(self._idle([]), ["Dwarf"])

    def test_family_danger_reads_the_giver_ground_of_a_far_member(self):
        far = dataclasses.replace(
            self.facts()["family_members"][0], map_id=0, x=-4633.5 + 3000.0, y=-932.0
        )
        with mock.patch.object(bridge, "_gather_danger", return_value=64) as g:
            out = bridge._family_danger([far], book(), [])
        self.assertEqual(out, {"Dwarf": 64})
        self.assertEqual(g.call_count, 1)

    def test_an_unread_ground_leaves_the_member_out(self):
        far = dataclasses.replace(
            self.facts()["family_members"][0], map_id=0, x=-4633.5 + 3000.0, y=-932.0
        )
        with mock.patch.object(bridge, "_gather_danger", return_value=None):
            self.assertEqual(bridge._family_danger([far], book(), []), {})


if __name__ == "__main__":
    unittest.main()
