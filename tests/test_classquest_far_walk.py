"""The class quest line does not waste the realm's few far walk slots.

Measured on the dev realm on 2026-10-06 at 12:40 New York: of the walk-to-spawn
rows written in 30 minutes, 25 ended `error` ("the realm has as many far walks
under way as it allows", retryable) and 5 applied, and a warrior tank without
Defensive Stance or Taunt was refused for his Thunder Lizard hunt (quest 1498)
while members with nothing to lose were walked first. These tests hold the
bridge to the slots the realm has, to the order that spends them, to a bounded
wait after a refusal, and to a clock that does not charge that wait to the hunt.
"""

import json
import pathlib
import unittest

import classquest
import guildjobs
import guildroute
import guildrun
from test_classquest import KALIMDOR, WARRIOR, class_plan, class_steps, who

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

# Far from Uzzek (186, -3597) and from the lizards: any walk is a far walk.
FAR = dict(x=-282.0, y=-6500.0, map_id=KALIMDOR)
TAKE = dict(quests_done=frozenset({1505}))


def far_member(name, level, tree="", **over):
    return who(name, level=level, tree=tree, **FAR, **TAKE, **over)


def refused(name, reason, age, retryable=True):
    body = {"outcome": "refused", "reason": reason, "retryable": retryable}
    row = {
        "target_name": name,
        "source": "guildjobs:classquest-walk:" + name,
        "status": "error",
        "age": age,
        "result": json.dumps(body, separators=(",", ":")) + "x" * 40,
    }
    return guildjobs.recent_from_rows([row])[0]


class TheSlots(unittest.TestCase):
    def test_a_pass_starts_no_more_walks_than_the_realm_has_slots(self):
        members = [far_member(n, 20) for n in ("Aa", "Bb", "Cc")]
        result = class_plan(members, far_slots=2)
        self.assertEqual(len(class_steps(result)), 2)
        self.assertTrue(any("far walk slot" in n for n in result.notes))

    def test_no_count_holds_nothing_back(self):
        members = [far_member(n, 20) for n in ("Aa", "Bb", "Cc")]
        self.assertEqual(len(class_steps(class_plan(members))), 3)

    def test_a_near_walk_takes_no_slot(self):
        near = who("Near", **TAKE)  # a few hundred yards from Uzzek
        result = class_plan([near], far_slots=0)
        self.assertEqual(len(class_steps(result)), 1)

    def test_a_walk_the_plan_then_refuses_gives_its_slot_back(self):
        members = [far_member("Aa", 20), far_member("Bb", 19)]
        result = class_plan(members, far_slots=1, busy={"Aa"})
        self.assertEqual([s.holder for s in class_steps(result)], ["Bb"])

    def test_the_slots_are_the_ceiling_less_the_rows_open(self):
        self.assertEqual(guildroute.far_slots_free(3, 12), 9)
        self.assertEqual(guildroute.far_slots_free(40, 12), 0)
        self.assertIsNone(guildroute.far_slots_free(None, 12))


class TheOrder(unittest.TestCase):
    def test_a_tank_warrior_is_walked_before_a_higher_level_damage_dealer(self):
        members = [
            far_member("Chillmon", 14, tree="Protection"),
            far_member("Hitter", 30, tree="Arms"),
            far_member("Slasher", 25, tree="Fury"),
        ]
        result = class_plan(members, far_slots=1)
        self.assertEqual([s.holder for s in class_steps(result)], ["Chillmon"])

    def test_the_rest_follow_by_level_highest_first(self):
        members = [
            far_member("Low", 12, tree="Arms"),
            far_member("High", 33, tree="Arms"),
            far_member("Mid", 21, tree="Fury"),
            far_member("Chillmon", 11, tree="Protection"),
        ]
        result = class_plan(members, far_slots=3)
        self.assertEqual(
            [s.holder for s in class_steps(result)], ["Chillmon", "High", "Mid"]
        )

    def test_a_healer_of_any_class_comes_first_too(self):
        priest = who("Mend", class_id=5, tree="Holy")
        self.assertEqual(guildjobs.class_priority(priest), 0)
        druid = who("Bear", class_id=11, tree="Feral Combat")
        self.assertEqual(guildjobs.class_priority(druid), 1)
        self.assertEqual(guildjobs.class_priority(who("Tank", tree="Protection")), 0)
        self.assertEqual(guildjobs.class_priority(who("Arms", tree="Arms")), 1)

    def test_without_a_book_the_order_is_the_old_one(self):
        members = [who("Zz", level=40), who("Aa", level=10)]
        ordered = guildjobs._class_ordered(members, None)
        self.assertEqual([m.name for m in ordered], ["Aa", "Zz"])


class TheBackoff(unittest.TestCase):
    def test_the_refusals_are_read_from_the_result(self):
        row = refused("Aa", classquest.REALM_FULL_REASON, 1)
        self.assertEqual(row.refusal, classquest.REALM_FULL_REASON)
        self.assertTrue(row.retryable)
        self.assertEqual(refused("Aa", "x", 1, retryable=False).retryable, False)

    def test_a_member_the_realm_refused_is_left_alone_a_while(self):
        m = far_member("Aa", 20)
        for reason, wait in (
            (classquest.REALM_FULL_REASON, classquest.REALM_FULL_BACKOFF_MINUTES),
            (classquest.BOT_BUDGET_REASON, classquest.BOT_BUDGET_BACKOFF_MINUTES),
        ):
            soon = (refused("Aa", reason, wait - 1),)
            later = (refused("Aa", reason, wait),)
            self.assertEqual(class_steps(class_plan([m], recent=soon)), [], reason)
            self.assertEqual(len(class_steps(class_plan([m], recent=later))), 1)

    def test_the_wait_is_bounded_by_the_budget_window(self):
        window_minutes = 60
        self.assertLessEqual(classquest.BOT_BUDGET_BACKOFF_MINUTES, window_minutes)
        cooldown = guildjobs.COOLDOWN_MINUTES[classquest.ACTION]
        self.assertGreater(classquest.REALM_FULL_BACKOFF_MINUTES, cooldown)
        self.assertLessEqual(classquest.REALM_FULL_BACKOFF_MINUTES, 30)

    def test_a_retryable_refusal_is_no_failed_hunt(self):
        rows = tuple(
            refused("Aa", classquest.REALM_FULL_REASON, age) for age in (20, 40)
        )
        self.assertFalse(guildjobs.failed_class_walks("Aa", rows))
        gone = tuple(
            refused("Aa", "the first step goes over a drop", age, retryable=False)
            for age in (20, 40)
        )
        self.assertTrue(guildjobs.failed_class_walks("Aa", gone))

    def test_a_refused_hunt_does_not_stall_on_the_waiting(self):
        m = far_member("Aa", 20, quest_log={1498: 3})
        hunts = classquest.Hunts()
        recent = (refused("Aa", classquest.REALM_FULL_REASON, 1),)
        for now in (0.0, 1500.0, 3000.0, 4500.0):
            result = class_plan([m], recent=recent, hunts=hunts, now=now)
            self.assertEqual(class_steps(result), [])
        hunt = hunts.get("Aa")
        self.assertEqual(hunt.tried, ())
        self.assertIsNone(hunt.until)

    def test_a_hunt_waiting_for_a_slot_does_not_stall_either(self):
        m = far_member("Aa", 20, quest_log={1498: 3})
        hunts = classquest.Hunts()
        for now in (0.0, 1500.0, 3000.0, 4500.0):
            class_plan([m], hunts=hunts, now=now, far_slots=0)
        self.assertEqual(hunts.get("Aa").tried, ())
        self.assertIsNone(hunts.get("Aa").until)


class TheDead(unittest.TestCase):
    def test_a_dead_member_gets_no_walk_row(self):
        m = far_member("Deadpan", 20, alive=False)
        result = class_plan([m], far_slots=5)
        self.assertEqual(result.steps, ())
        self.assertIn(classquest.MARK, result.lines["Deadpan"])
        self.assertTrue(any("dead" in n for n in result.notes))

    def test_a_dead_member_keeps_no_slot(self):
        members = [far_member("Deadpan", 40), far_member("Alive", 10)]
        members[0] = far_member("Deadpan", 40, alive=False)
        result = class_plan(members, far_slots=1)
        self.assertEqual([s.holder for s in class_steps(result)], ["Alive"])


class TheWiring(unittest.TestCase):
    def test_the_bridge_reads_health_the_refusal_and_the_open_walks(self):
        self.assertIn("s.health", BRIDGE.split("_JOB_SKILLS_SQL")[0])
        self.assertIn("LEFT(result, 400) AS result", BRIDGE)
        self.assertIn("_JOB_FAR_WALKS_OPEN_SQL", BRIDGE)
        self.assertIn("far_slots=guildroute.far_slots_free(", BRIDGE)
        self.assertIn("alive=guildrun.alive_or_unread(r)", BRIDGE)

    def test_a_row_with_no_snapshot_is_not_read_as_dead(self):
        self.assertTrue(guildrun.alive_or_unread({"health": None}))
        self.assertTrue(guildrun.alive_or_unread({"health": 400}))
        self.assertFalse(guildrun.alive_or_unread({"health": 1, "has_corpse": 1}))
        self.assertEqual(WARRIOR, classquest.WARRIOR)


if __name__ == "__main__":
    unittest.main()
