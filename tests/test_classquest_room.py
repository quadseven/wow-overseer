"""A class quest step makes room in the bags first (guildjobs.class_room_step).

The case is a live one, read 2026-10-06 on the dev realm: a level 20 warrior
(Bigzug) hunted Thunder Lizards for quest 1498 (5 Singed Scale, item 6486),
opened 12 corpses with the item on them and kept none, because the backpack
(16 of 16) and four bags (6, 8, 6 and 6 slots, all used) held no free slot.
The class quest is the first rung of a member's step, so the sale below it never
ran and the member stayed on a hunt that could not succeed.
"""

import pathlib
import unittest

import classquest
import guildjobs
import keep
from test_classquest import book, class_plan, class_steps, who

HERE = pathlib.Path(__file__).resolve().parents[1]
HUNTING = dict(quest_log={1498: 3}, quests_done=frozenset({1505}))
SCALE = 6486


def grey(guid, price=40, entry=2000):
    return guildjobs.Carried(
        guid=guid, entry=entry + guid, count=1, quality=0, sell_price=price, name="Rag"
    )


def cloth(guid, entry, count, price=10):
    return guildjobs.Carried(
        guid=guid,
        entry=entry,
        count=count,
        item_class=guildjobs.TRADE_GOODS,
        subclass=5,
        quality=1,
        sell_price=price,
        name="Cloth",
    )


def full(name="Bigzug", carried=(), **over):
    return who(name, free_slots=0, carried=tuple(carried), **HUNTING, **over)


def room_steps(plan):
    return [s for s in plan.steps if s.action == guildjobs.ROOM_ACTION]


class TheCount(unittest.TestCase):
    def test_bigzugs_bags_are_full(self):
        # backpack 16 of 16; bags of 6, 8, 6 and 6 slots, all used.
        self.assertEqual(guildjobs.free_slots_of(16, [6, 8, 6, 6], 26), 0)

    def test_a_free_slot_is_counted(self):
        self.assertEqual(guildjobs.free_slots_of(15, [6, 8, 6, 6], 26), 1)

    def test_more_used_than_held_is_zero(self):
        self.assertEqual(guildjobs.free_slots_of(16, [], 20), 0)


class TheNeed(unittest.TestCase):
    def need(self, kind, **over):
        m = who(**over)
        move = classquest.Move(kind=kind, quest=1498)
        return guildjobs.class_room_needed(m, move, book())

    def test_five_scales_ask_for_the_cap(self):
        self.assertEqual(self.need(classquest.HUNT), guildjobs.ROOM_CAP)

    def test_one_scale_missing_asks_for_one(self):
        m = dict(carried=(guildjobs.Carried(guid=1, entry=SCALE, count=4),))
        self.assertEqual(self.need(classquest.HUNT, **m), 1)

    def test_a_hand_in_asks_for_one(self):
        self.assertEqual(self.need(classquest.TURN_IN), 1)

    def test_a_take_with_nothing_handed_over_asks_for_none(self):
        self.assertEqual(self.need(classquest.TAKE), 0)


class TheStep(unittest.TestCase):
    def test_a_full_hunter_sells_instead_of_hunting(self):
        m = full(carried=[grey(1), grey(2, price=90)])
        plan = class_plan([m])
        self.assertEqual(class_steps(plan), [])
        (step,) = room_steps(plan)
        self.assertEqual([r.command for r in step.rows], ["guid:2", "guid:1"])
        self.assertTrue(all(r.kind == "sell" for r in step.rows))
        self.assertTrue(step.walk.command.startswith("walk-to-vendor any"))

    def test_the_member_stays_on_its_class_quest_line(self):
        plan = class_plan([full(carried=[grey(1)])])
        self.assertIn("Bigzug", guildjobs.class_held(plan.lines))

    def test_one_grey_stack_is_enough_and_the_sale_bar_is_not_asked(self):
        step = room_steps(class_plan([full(carried=[grey(1, price=1)])]))[0]
        self.assertEqual(len(step.rows), 1)

    def test_a_recent_sale_does_not_stop_it(self):
        recent = [
            guildjobs.Recent(name="Bigzug", action="sell", age_minutes=10, status="ok")
        ]
        plan = class_plan([full(carried=[grey(1)])], recent=recent)
        self.assertEqual(len(room_steps(plan)), 1)

    def test_its_own_recent_step_is_waited_out(self):
        recent = [
            guildjobs.Recent(name="Bigzug", action="room", age_minutes=5, status="ok")
        ]
        plan = class_plan([full(carried=[grey(1)])], recent=recent)
        self.assertEqual(plan.steps, ())
        self.assertIn("Bigzug", guildjobs.class_held(plan.lines))

    def test_the_hunt_waits_for_no_one_when_there_is_room(self):
        m = who(free_slots=3, **HUNTING)
        self.assertEqual(room_steps(class_plan([m])), [])
        self.assertEqual(len(class_steps(class_plan([m]))), 1)

    def test_unread_room_keeps_the_hunt(self):
        m = who(**HUNTING)
        self.assertIsNone(m.free_slots)
        self.assertEqual(len(class_steps(class_plan([m]))), 1)

    def test_the_class_allowance_does_not_stop_it(self):
        takers = [
            who("Taker%d" % i, level=21, quests_done=frozenset({1505}))
            for i in range(guildjobs.CLASSQUEST_STEPS_PER_GUILD)
        ]
        full_one = full(level=19, carried=[grey(1)])
        plan = class_plan(takers + [full_one])
        self.assertEqual(len(class_steps(plan)), guildjobs.CLASSQUEST_STEPS_PER_GUILD)
        self.assertEqual([s.holder for s in room_steps(plan)], ["Bigzug"])


class TheLimits(unittest.TestCase):
    def test_a_reserved_stack_is_kept(self):
        kept = keep.from_rows([{"character_name": "Bigzug", "item_guid": 1}])
        plan = class_plan([full(carried=[grey(1)])], kept=kept)
        self.assertEqual(plan.steps, ())

    def test_the_quest_item_is_never_let_go(self):
        scale = guildjobs.Carried(
            guid=7, entry=SCALE, count=2, quality=0, sell_price=5, name="Scale"
        )
        plan = class_plan([full(carried=[scale])])
        self.assertEqual(plan.steps, ())

    def test_worn_gear_is_not_sold(self):
        sword = guildjobs.Carried(
            guid=8,
            entry=3000,
            item_class=guildjobs.WEAPON,
            quality=1,
            sell_price=50,
            item_level=18,
        )
        plan = class_plan([full(carried=[sword])])
        self.assertEqual(plan.steps, ())

    def test_an_outgrown_white_piece_is_sold(self):
        old = guildjobs.Carried(
            guid=9,
            entry=3001,
            item_class=guildjobs.ARMOR,
            subclass=1,
            quality=1,
            sell_price=50,
            item_level=5,
        )
        self.assertEqual(len(room_steps(class_plan([full(carried=[old])]))), 1)

    def test_with_nothing_to_sell_the_lowest_material_is_destroyed(self):
        bolts = [cloth(11, 2589, 20, price=30), cloth(12, 2592, 5, price=10)]
        step = room_steps(class_plan([full(carried=bolts, money=0)]))[0]
        self.assertEqual([r.command for r in step.rows], ["destroy guid:12 count:5"])
        self.assertIsNone(step.walk)

    def test_with_nothing_at_all_it_is_not_held_and_says_why(self):
        plan = class_plan([full()])
        self.assertEqual(plan.steps, ())
        self.assertNotIn("Bigzug", guildjobs.class_held(plan.lines))
        self.assertTrue(any("nothing it may sell" in n for n in plan.notes))


class TheBridge(unittest.TestCase):
    def test_the_bridge_reads_free_slots_into_the_members(self):
        text = (HERE / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("free_slots=_job_free_slots(", text)
        self.assertIn("free_slots=(free_slots or {}).get(name)", text)


if __name__ == "__main__":
    unittest.main()
