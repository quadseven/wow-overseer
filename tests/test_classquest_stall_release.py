"""A class step that keeps failing lets the level walk go first, a way that
kills is a named blocker, and a ghost is walked nowhere (2026-10-09).

Read on the dev realm on 2026-10-09: 19 guild members stood for 36 minutes and
more in starting zones below their level, every one with its hearthstone bound
there. 13 were held on a class quest step that kept failing (451 class quest
walks ended in error in a day against 145 that arrived; a level 23 member
clicked the same gameobject 8 times in 6 hours to no effect), and the class step
is the first rung, so the walk out of the outgrown zone never ran for them. 83
of the 97 class quest walks that ended "died on the way to the spawn" were
walks to a giver or an ender, which the death hold did not reach; 45 of 207
level walks went to a dead member, and 54 ended in the member's death.

These tests hold the operator's rule (the class quest first) with its one
bound: a run of failed class rows holds the class step for the level walk's
cooldown, the level walk goes ahead of it meanwhile, and the class step is
first again afterwards.
"""

import json
import unittest

import classquest
import guildjobs
import guildlevel
from test_classquest import class_plan, who
from test_guildlevel import member as level_member
from test_guildlevel import plan as level_plan
from test_guildlevel import spawn_of, world

UZZEK = 19732  # the giver of Path of Defense (1498) in test_classquest's book
TAKE_1498 = dict(quests_done=frozenset({1505}))
BARRENS = 17


def row(name, command, action, status, age, body=None, rid=0):
    """One recent row as the bridge reads it (bridge._JOB_RECENT_SQL)."""
    return guildjobs.recent_from_rows(
        [
            {
                "id": rid,
                "target_name": name,
                "command": command,
                "source": guildjobs.source_for(action, name),
                "status": status,
                "age": age,
                "result": json.dumps(body or {}, separators=(",", ":")),
            }
        ]
    )[0]


def written(step_row, status, age, body=None):
    """The recent row the bridge reads back for a row the plan wrote: its own
    source and command, as _JOB_RECENT_SQL returns them."""
    return guildjobs.recent_from_rows(
        [
            {
                "id": 0,
                "target_name": step_row.source.rsplit(":", 1)[1],
                "command": step_row.command,
                "source": step_row.source,
                "status": status,
                "age": age,
                "result": json.dumps(body or {}, separators=(",", ":")),
            }
        ]
    )[0]


def take_failed(age, name="Bigzug"):
    body = {
        "outcome": "refused",
        "reason": "no giver of that quest in reach",
        "retryable": False,
    }
    return row(name, "take quest:1498", classquest.ACTION, "error", age, body)


def take_went(age, name="Bigzug"):
    return row(name, "take quest:1498", classquest.ACTION, "delivered", age)


def walk(age, status="applied", body=None, spawn=UZZEK, name="Bigzug"):
    return row(
        name,
        "walk-to-spawn creature:%d max:20000" % spawn,
        classquest.ACTION + "-walk",
        status,
        age,
        body or {"outcome": "arrived"},
    )


def died(age, spawn=UZZEK, name="Bigzug"):
    body = {
        "outcome": "died",
        "reason": classquest.DEATH_REASON,
        "retryable": True,
    }
    return walk(age, "error", body, spawn, name)


def walled(age, reason=classquest.REALM_FULL_REASON):
    return walk(
        age, "error", {"outcome": "refused", "reason": reason, "retryable": True}
    )


def use_nothing(age):
    body = {
        "outcome": "nothing",
        "reason": "the use changed nothing the character could be read for",
    }
    return row(
        "Bigzug", "use-gameobject 37098", classquest.ACTION, "unchanged", age, body
    )


def hunted(age, kills):
    body = {"outcome": "nothing", "reason": "the clock ran out", "kills": kills}
    return row(
        "Bigzug", "hunt-spawn creature:3130", classquest.ACTION, "unchanged", age, body
    )


def failing(*ages):
    return tuple(take_failed(a) for a in ages)


def hold(recent):
    return guildjobs.class_stall_hold("Bigzug", recent)


def stuck(name="Bigzug", **over):
    """test_classquest's level 20 orc warrior in Durotar, which has outgrown
    it (no Horde band there in test_guildlevel's world), with Path of Defense
    to take from Uzzek 735 yards off."""
    return who(name, **dict(TAKE_1498, **over))


def plan(members, recent=(), **kw):
    kw.setdefault("leveling", world())
    return class_plan(members, recent=tuple(recent), **kw)


def step_of(result, name="Bigzug"):
    steps = [s for s in result.steps if s.holder == name]
    return steps[0] if steps else None


class TheHold(unittest.TestCase):
    def test_three_failed_rows_in_a_row_hold_the_class_step(self):
        self.assertEqual(hold(failing(10, 40, 70)), (110, 3))

    def test_two_do_not(self):
        self.assertEqual(hold(failing(10, 40)), (0, 2))

    def test_the_hold_is_the_level_walks_cooldown_after_the_newest_failure(self):
        self.assertEqual(
            guildjobs.CLASS_STALL_HOLD_MINUTES, guildlevel.COOLDOWN_MINUTES
        )
        newest = guildjobs.CLASS_STALL_HOLD_MINUTES
        self.assertEqual(hold(failing(newest - 1, 150, 160)), (1, 3))
        self.assertEqual(hold(failing(newest, 150, 160)), (0, 3))

    def test_rows_past_the_window_do_not_count(self):
        window = guildjobs.CLASS_STALL_WINDOW_MINUTES
        self.assertEqual(hold(failing(10, 40, window)), (0, 2))

    def test_a_walk_that_arrived_is_no_progress(self):
        recent = (
            take_failed(5),
            walk(6),
            take_failed(30),
            walk(31),
            take_failed(60),
            walk(61),
        )
        self.assertEqual(hold(recent), (115, 3))

    def test_a_death_on_the_way_is_a_failure(self):
        self.assertEqual(hold((died(10), died(40), died(70))), (110, 3))

    def test_a_use_that_changed_nothing_is_a_failure(self):
        recent = (use_nothing(44), use_nothing(85), use_nothing(156))
        self.assertEqual(hold(recent), (76, 3))

    def test_a_refusal_the_module_calls_retryable_is_passed_over(self):
        for reason in (
            classquest.REALM_FULL_REASON,
            classquest.BOT_BUDGET_REASON,
            classquest.HELD_REASON,
            "character is in combat",
            "character is dead",
        ):
            with self.subTest(reason):
                walls = tuple(walled(a, reason) for a in (5, 15, 25, 35))
                self.assertEqual(hold(walls), (0, 0))
                mixed = (walled(5, reason),) + failing(10, 40, 70)
                self.assertEqual(hold(mixed), (110, 3))

    def test_a_take_that_went_through_ends_the_run(self):
        recent = failing(10, 40) + (take_went(50),) + failing(60, 70)
        self.assertEqual(hold(recent), (0, 2))

    def test_a_hunt_that_made_a_kill_ends_the_run(self):
        recent = failing(10, 40) + (hunted(50, kills=2),) + failing(60, 70)
        self.assertEqual(hold(recent), (0, 2))
        self.assertEqual(hold(failing(10, 40) + (hunted(50, kills=0),)), (110, 3))

    def test_another_members_rows_do_not_count(self):
        recent = tuple(take_failed(a, name="Chillmon") for a in (10, 40, 70))
        self.assertEqual(hold(recent), (0, 0))

    def test_rows_before_the_tried_epoch_do_not_count(self):
        old = tuple(
            row(
                "Bigzug",
                "take quest:1498",
                classquest.ACTION,
                "error",
                a,
                {"outcome": "refused", "reason": "no giver of that quest in reach"},
                rid=classquest.TRIED_EPOCH,
            )
            for a in (10, 40, 70)
        )
        self.assertEqual(hold(old), (0, 0))


class TheLevelWalkFirst(unittest.TestCase):
    def test_a_member_whose_class_step_keeps_failing_walks_to_level(self):
        result = plan([stuck()], failing(10, 40, 70))
        step = step_of(result)
        self.assertEqual(step.action, guildlevel.ACTION)
        self.assertIn("creature:%d " % spawn_of("barrens"), step.rows[0].command)
        self.assertEqual(result.lines["Bigzug"], step.said)
        self.assertTrue(
            any("failed 3 times in a row" in n and "110" in n for n in result.notes),
            result.notes,
        )

    def test_without_the_run_the_class_step_is_first(self):
        result = plan([stuck()], failing(10, 40))
        self.assertEqual(step_of(result).action, classquest.ACTION)

    def test_with_the_level_walk_cooling_the_class_step_is_first(self):
        walked = step_of(plan([stuck()], failing(10, 40, 70))).rows[0]
        self.assertEqual(walked.source, "guildjobs:level:Bigzug")
        cooling = written(walked, "applied", 30)
        result = plan([stuck()], failing(10, 40, 70) + (cooling,))
        self.assertEqual(step_of(result).action, classquest.ACTION)

    def test_a_member_whose_zone_still_fits_does_its_class_step(self):
        result = plan([stuck(zone_id=BARRENS)], failing(10, 40, 70))
        self.assertEqual(step_of(result).action, classquest.ACTION)

    def test_once_the_hold_runs_out_the_class_step_is_first_again(self):
        old = guildjobs.CLASS_STALL_HOLD_MINUTES
        result = plan([stuck()], failing(old, old + 20, old + 40))
        self.assertEqual(step_of(result).action, classquest.ACTION)

    def test_a_class_step_that_is_not_failing_keeps_its_member(self):
        recent = failing(10, 40, 70)
        result = plan([stuck(), stuck("Chillmon")], recent)
        self.assertEqual(step_of(result, "Bigzug").action, guildlevel.ACTION)
        self.assertEqual(step_of(result, "Chillmon").action, classquest.ACTION)

    def test_with_the_guilds_level_walks_spent_the_class_step_goes_on(self):
        names = ["W%d" % i for i in range(guildlevel.STEPS_PER_GUILD + 1)]
        crew = [stuck(n, x=-282.0 + i) for i, n in enumerate(names)]
        recent = tuple(take_failed(a, name=n) for n in names for a in (10, 40, 70))
        result = plan(crew, recent)
        actions = sorted(step_of(result, n).action for n in names)
        self.assertEqual(
            actions.count(guildlevel.ACTION), guildlevel.STEPS_PER_GUILD, actions
        )
        self.assertEqual(actions.count(classquest.ACTION), 1, actions)

    def test_nothing_else_comes_before_the_class_step(self):
        source = guildjobs._member_step.__code__.co_names
        self.assertLess(source.index("stalled_level_first"), source.index("class_step"))
        self.assertNotIn("level_step", source[: source.index("class_step")])


class TheGhost(unittest.TestCase):
    def test_a_dead_member_is_walked_nowhere_to_level(self):
        result = level_plan([level_member(alive=False)])
        self.assertEqual([s for s in result.steps if s.action == guildlevel.ACTION], [])
        self.assertTrue(
            any("Cleric is dead and is walked nowhere" in n for n in result.notes),
            result.notes,
        )

    def test_alive_again_it_walks(self):
        result = level_plan([level_member()])
        steps = [s for s in result.steps if s.action == guildlevel.ACTION]
        self.assertEqual(len(steps), 1)
        self.assertIn("creature:%d " % spawn_of("westfall"), steps[0].rows[0].command)

    def test_a_ghost_whose_class_step_is_failing_gets_no_level_walk_either(self):
        result = plan([stuck(alive=False)], failing(10, 40, 70))
        self.assertNotEqual(getattr(step_of(result), "action", ""), guildlevel.ACTION)


class TheDeadlyWay(unittest.TestCase):
    def test_two_deaths_on_the_way_to_the_giver_hold_the_walk_and_name_it(self):
        result = class_plan([stuck()], recent=(died(30), died(200)))
        self.assertIsNone(step_of(result))
        note = [n for n in result.notes if "died 2 times on the way to Uzzek" in n]
        self.assertEqual(len(note), 1, result.notes)
        self.assertIn("Path of Defense", note[0])
        self.assertIn("above level 20", note[0])
        self.assertIn("330 more minute(s)", note[0])
        self.assertNotIn(classquest.MARK, result.lines["Bigzug"])

    def test_the_member_levels_meanwhile(self):
        result = plan([stuck()], (died(30), died(200)))
        self.assertEqual(step_of(result).action, guildlevel.ACTION)

    def test_one_death_is_no_blocker(self):
        result = class_plan([stuck()], recent=(died(200),))
        step = step_of(result)
        self.assertEqual(step.action, classquest.ACTION)
        self.assertIn("creature:%d " % UZZEK, step.walk.command)

    def test_the_hold_ends(self):
        backoff = classquest.DEATH_BACKOFF_MINUTES
        result = class_plan([stuck()], recent=(died(backoff), died(backoff + 60)))
        self.assertEqual(step_of(result).action, classquest.ACTION)

    def test_deaths_on_the_way_elsewhere_do_not_hold_this_giver(self):
        recent = (died(30, spawn=4788), died(200, spawn=4788))
        result = class_plan([stuck()], recent=recent)
        self.assertEqual(step_of(result).action, classquest.ACTION)

    def test_a_member_beside_the_giver_has_no_way_left_to_walk(self):
        beside = stuck(x=186.0 + 30.0, y=-3597.0)
        result = class_plan([beside], recent=(died(30), died(200)))
        self.assertEqual(step_of(result).action, classquest.ACTION)

    def test_the_hunts_packs_keep_their_mark(self):
        rows = (died(30, spawn=4788), died(200, spawn=4788))
        self.assertEqual(guildjobs.refused_marks("Bigzug", rows), {4788: 30})
        self.assertEqual(guildjobs.deadly_ways("Bigzug", rows), {4788: (2, 30)})

    def test_a_hunts_last_pack_that_killed_it_is_not_asked_again(self):
        # Both packs held; the older mark is past SPAWN_RETRY_MINUTES, so
        # roll_oldest asks the lizards again: the way there killed it twice.
        hunter = who(quest_log={1498: 3}, quests_done=frozenset({1505}))
        rows = (
            died(40, spawn=4788),
            died(200, spawn=4788),
            died(10, spawn=12197),
            died(100, spawn=12197),
        )
        result = class_plan([hunter], recent=rows)
        self.assertIsNone(step_of(result))
        self.assertTrue(
            any("died 2 times on the way to Thunder Lizard" in n for n in result.notes),
            result.notes,
        )

    def test_a_hunt_already_at_its_pack_is_not_held(self):
        hunter = who(
            quest_log={1498: 3}, quests_done=frozenset({1505}), x=720.0, y=-4100.0
        )
        rows = (
            died(40, spawn=4788),
            died(200, spawn=4788),
            died(10, spawn=12197),
            died(100, spawn=12197),
        )
        result = class_plan([hunter], recent=rows)
        self.assertIn("Thunder Lizard", result.lines["Bigzug"])
        self.assertFalse(any("on the way to" in n for n in result.notes), result.notes)


def level_died(age, key="westfall", name="Cleric"):
    """A level walk to the hub's flight master that ended in a death."""
    body = {"outcome": "died", "reason": classquest.DEATH_REASON, "retryable": True}
    return row(
        name,
        "walk-to-spawn creature:%d max:20000" % spawn_of(key),
        guildlevel.ACTION,
        "error",
        age,
        body,
    )


class TheDeadlyHub(unittest.TestCase):
    def level_steps(self, recent):
        result = level_plan([level_member()], recent=tuple(recent))
        return [s for s in result.steps if s.action == guildlevel.ACTION], result

    def test_two_deaths_on_the_way_to_the_hub_hold_the_level_walk(self):
        # Past the walk's own cooldown, so only the death hold stands.
        steps, result = self.level_steps([level_died(150), level_died(400)])
        self.assertEqual(steps, [])
        note = [n for n in result.notes if "died 2 times on the way" in n]
        self.assertEqual(len(note), 1, result.notes)
        self.assertIn("Sentinel Hill in Westfall", note[0])
        self.assertIn("210 more minute(s)", note[0])

    def test_one_death_is_no_hold(self):
        steps, _result = self.level_steps([level_died(150)])
        self.assertEqual(len(steps), 1)

    def test_the_hold_ends(self):
        backoff = classquest.DEATH_BACKOFF_MINUTES
        steps, _result = self.level_steps([level_died(backoff), level_died(400)])
        self.assertEqual(len(steps), 1)

    def test_a_death_on_a_class_walk_is_not_a_deadly_hub(self):
        class_deaths = [died(150, spawn=spawn_of("westfall"), name="Cleric")] * 2
        steps, _result = self.level_steps(class_deaths)
        self.assertEqual(len(steps), 1)

    def test_a_stalled_class_steps_level_walk_keeps_the_hold(self):
        walked = step_of(plan([stuck()], failing(10, 40, 70))).rows[0]
        self.assertIn("creature:%d " % spawn_of("barrens"), walked.command)
        body = {"outcome": "died", "reason": classquest.DEATH_REASON}
        deaths = tuple(written(walked, "error", age, body) for age in (150, 400))
        result = plan([stuck()], failing(10, 40, 70) + deaths)
        self.assertEqual(step_of(result).action, classquest.ACTION)


if __name__ == "__main__":
    unittest.main()
