"""A guild jobs walk the realm refused is not asked again every pass (#1295).

Read on the dev realm in the 24 hours to 2026-11-04 05Z: 866 of 888 walk
refusals came from the guild jobs walk path, 723 of them "character is held by
another verb". The class quest walk waits out that refusal
(guildjobs.class_walk_backoff), but every other guild jobs walk (the
`walk-to-spawn` job rows of the farm, door and level steps, and the step
walks to a vendor, a trainer or a mailbox) read only its own cooldown, so a
held level walk was asked again after five minutes and a farm walk after a
walk of another kind was asked at once. These rows are built from the
module's logged refusal, read through guildjobs.recent_from_rows as the
bridge reads them.
"""

import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import classquest  # noqa: E402
import guildjobs  # noqa: E402

H, S = guildjobs.HERBALISM, guildjobs.SKINNING
FAR = 20000


def refused_row(action, command, reason, age, name="Keeper"):
    """One overseer_command row as the bridge reads it (_JOB_RECENT_SQL), with
    the module's refusal in its result."""
    return {
        "id": 700000 + age,
        "source": guildjobs.source_for(action, name),
        "target_name": name,
        "command": command,
        "status": "error",
        "result": '{"outcome":"refused","reason":"%s","retryable":true}' % reason,
        "age": age,
    }


def recent(*rows):
    return guildjobs.recent_from_rows(rows)


def member(**over):
    base = dict(
        name="Keeper",
        guild="Cave",
        role=guildjobs.MAINTENANCE,
        level=12,
        class_id=1,
        race=1,
        online=True,
        map_id=0,
        x=-9000.0,
        y=100.0,
        money=5000,
        eligible=True,
        skills={
            H: (40, 75),
            S: (10, 75),
            guildjobs.FIRST_AID: (40, 75),
            guildjobs.COOKING: (1, 75),
        },
        carried=(
            guildjobs.Carried(
                guid=1,
                entry=7005,
                count=1,
                item_class=2,
                subclass=9,
                quality=1,
                sell_price=5,
                name="Skinning Knife",
            ),
        ),
    )
    base.update(over)
    return guildjobs.Member(**base)


FIELD = guildjobs.Spot("gameobject", 4242, 0, -8000.0, 900.0, "Peacebloom")


def farm_plan(rows, cap=FAR):
    return guildjobs.plan(
        [member()],
        masters={"Cave": "Grug"},
        fields={"Keeper": FIELD},
        recent=recent(*rows),
        cap=cap,
    )


def steps(result):
    return [s for s in result.steps if s.holder == "Keeper"]


HELD_LEVEL_WALK = (
    guildjobs.guildlevel.ACTION,
    "walk-to-spawn creature:90001 max:%d" % FAR,
    classquest.HELD_REASON,
)


class AHeldWalkWaitsOutTheHold(unittest.TestCase):
    def test_the_logged_refusal_reads_as_a_held_walk(self):
        (row,) = recent(refused_row(*HELD_LEVEL_WALK, 3))
        self.assertEqual(row.refusal, "character is held by another verb")
        self.assertEqual(
            guildjobs.job_walk_backoff("Keeper", (row,)),
            (classquest.HELD_REASON, classquest.HELD_BACKOFF_MINUTES - 3),
        )

    def test_a_walk_after_a_held_walk_of_another_kind_waits(self):
        result = farm_plan([refused_row(*HELD_LEVEL_WALK, 3)])
        self.assertEqual(steps(result), [])
        self.assertIn(
            "Keeper waits 9 more minutes to walk: character is held by another verb",
            result.notes,
        )

    def test_a_near_walk_waits_out_the_hold_too(self):
        self.assertEqual(steps(farm_plan([refused_row(*HELD_LEVEL_WALK, 3)], 600)), [])

    def test_the_walk_is_asked_once_the_hold_has_had_its_time(self):
        age = classquest.HELD_BACKOFF_MINUTES
        (step,) = steps(farm_plan([refused_row(*HELD_LEVEL_WALK, age)]))
        self.assertEqual(step.action, "farm")

    def test_a_held_level_walk_is_not_asked_again_after_five_minutes(self):
        # #1464 asks a passing level refusal again after five minutes; the
        # module's hold lasts up to 11.5, so a held one waits the hold out.
        rows = recent(refused_row(*HELD_LEVEL_WALK, 6))
        wall, wait = guildjobs.job_walk_backoff("Keeper", rows)
        self.assertEqual((wall, wait), (classquest.HELD_REASON, 6))

    def test_a_newer_walk_that_was_not_refused_lifts_it(self):
        rows = recent(refused_row(*HELD_LEVEL_WALK, 5)) + (
            guildjobs.Recent(
                "Keeper",
                "post",
                2,
                "delivered",
                command="walk-to-mailbox max:600",
            ),
        )
        self.assertEqual(guildjobs.job_walk_backoff("Keeper", rows), ("", 0))

    def test_another_members_refusal_holds_nobody_else(self):
        rows = [refused_row(*HELD_LEVEL_WALK, 3, name="Other")]
        self.assertEqual(len(steps(farm_plan(rows))), 1)


class TheFarWalkWallsHoldOnlyFarWalks(unittest.TestCase):
    BUDGET = (
        guildjobs.guildlevel.ACTION,
        "walk-to-spawn creature:90001 max:%d" % FAR,
        classquest.BOT_BUDGET_REASON,
    )

    def test_a_far_walk_waits_out_the_bot_budget(self):
        result = farm_plan([refused_row(*self.BUDGET, 5)])
        self.assertEqual(steps(result), [])
        self.assertIn(
            "Keeper waits 25 more minutes to walk: " + classquest.BOT_BUDGET_REASON,
            result.notes,
        )

    def test_a_near_walk_is_not_held_by_the_far_walk_budget(self):
        self.assertEqual(len(steps(farm_plan([refused_row(*self.BUDGET, 5)], 600))), 1)


class AFarAboveRoadLeavesTheSpawn(unittest.TestCase):
    LETHAL = (
        "farm",
        "walk-to-spawn gameobject:4242 max:%d" % FAR,
        classquest.LETHAL_ROAD_REASON,
    )

    def test_the_spawn_is_left_for_the_spawn_refusal_hold(self):
        # Past the farm cooldown (45 minutes), inside SPAWN_REFUSED_MINUTES.
        result = farm_plan([refused_row(*self.LETHAL, 50)])
        self.assertEqual(steps(result), [])
        self.assertIn(
            "Keeper leaves the spawn gameobject:4242 for 70 more minutes: "
            "the road to the spawn crosses ground far above its level",
            result.notes,
        )

    def test_after_the_hold_the_spawn_is_asked_again(self):
        age = classquest.SPAWN_REFUSED_MINUTES
        self.assertEqual(len(steps(farm_plan([refused_row(*self.LETHAL, age)]))), 1)

    def test_another_spawn_is_not_left(self):
        other = ("farm", "walk-to-spawn gameobject:5151 max:%d" % FAR)
        rows = [refused_row(*other, classquest.LETHAL_ROAD_REASON, 50)]
        self.assertEqual(len(steps(farm_plan(rows))), 1)

    def test_the_far_above_road_is_a_spawn_refusal(self):
        self.assertIn(classquest.LETHAL_ROAD_REASON, classquest.SPAWN_REFUSALS)
        self.assertNotIn(classquest.LETHAL_ROAD_REASON, classquest.SPAWN_SHORT_REFUSALS)


if __name__ == "__main__":
    unittest.main()
