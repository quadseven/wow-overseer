"""Approved raid seats run the family's bag loop at a town stop (#2609).

Measured on the dev realm on 2026-11-15, over the 81 approved seats outside
nobody's special case: a median of 2 free carried slots, 45 seats at 2 or
fewer, and 0 stacks in any bank. The guild job pass read only the stacks a
vendor could buy, so the unpriced quest stacks that fill the bags were never
in front of it, and nothing planned a bank deposit for a seat at all.

These tests drive the real seams: the item plan (`itemplan_shadow`,
`itemplan_vendor`) for what a seat sells and banks, and `guildjobs.plan` for
the step the seat is sent on.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

import guildcorps
import guildjobs
import itemplan
import itemplan_shadow as shadow
import seatbags
from test_guildjobs import member, only_step, plan

SEAT = "Brug"  # an approved Cave raid seat outside the family


def row(guid, entry, name, quality=1, sell=50, item_class=15, **kw):
    base = {
        "holder": SEAT,
        "item_guid": guid,
        "entry": entry,
        "name": name,
        "quality": quality,
        "count": 1,
        "sell_price": sell,
        "item_class": item_class,
        "bag_family": 0,
        "quest_item": False,
        "reagent": False,
        "profession_needed": False,
    }
    base.update(kw)
    return base


def carried(guid, entry=0, **kw):
    return guildjobs.Carried(
        guid=guid, entry=entry or 1000 + guid, name="item %d" % guid, **kw
    )


def extras_for(rows, bank_free=20):
    templates = {
        r["entry"]: {
            "subclass": 0,
            "bonding": 0,
            "req_level": 1,
            "item_level": 1,
            "container_slots": None,
            "fire_res": 0,
            "required_skill_rank": None,
        }
        for r in rows
    }
    return shadow.Extras(
        templates=templates,
        instance_soulbound={r["item_guid"]: False for r in rows},
        fire_gear=frozenset(),
        open_quest_items={SEAT: frozenset()},
        bank_free={SEAT: bank_free},
    )


def seat(**over):
    base = dict(
        role=guildjobs.RAIDER,
        level=60,
        free_slots=2,
        bag_slots=36,
        alive=True,
    )
    base.update(over)
    return member(SEAT, **base)


BANKER = guildjobs.Spot(
    kind="creature", spawn=777, map_id=0, x=-9010.0, y=110.0, name="Banker"
)


class WhoIsASeat(unittest.TestCase):
    def test_an_approved_seat_outside_the_family_is_a_seat(self):
        self.assertTrue(seatbags.is_seat(seat()))

    def test_a_rename_in_flight_is_still_the_seat(self):
        self.assertTrue(seatbags.is_seat(member("Aalall", role=guildjobs.RAIDER)))

    def test_a_family_head_is_not_a_seat(self):
        self.assertFalse(seatbags.is_seat(member("Grug", role=guildjobs.RAIDER)))

    def test_a_maintenance_member_is_not_a_seat(self):
        self.assertFalse(seatbags.is_seat(member(SEAT)))

    def test_only_a_seat_short_of_room_needs_a_plan(self):
        self.assertTrue(seatbags.needs_plan(seat(free_slots=2)))
        self.assertFalse(seatbags.needs_plan(seat(free_slots=itemplan.TRIGGER_FREE)))
        self.assertFalse(seatbags.needs_plan(seat(online=False)))
        self.assertFalse(seatbags.needs_plan(seat(free_slots=None)))


class WhatThePlanSaysForASeat(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row(1, 100, "Broken Whistle", sell=40),
            row(2, 200, "Tattered Letter", item_class=12, sell=0, quest_item=True),
            row(3, 201, "Old Map", item_class=12, sell=0, quest_item=True),
        ]

    def plan(self, **kw):
        return seatbags.plan_for(
            [SEAT],
            "Cave",
            self.rows,
            {SEAT: 2},
            extras_for(self.rows, **kw),
        )

    def test_a_priced_surplus_stack_is_sold(self):
        got = self.plan()
        self.assertEqual([c.guid for c in got.sales[SEAT]], [1])

    def test_the_unpriced_quest_leftovers_are_banked(self):
        got = self.plan()
        self.assertEqual(sorted(c.guid for c in got.banks[SEAT]), [2, 3])

    def test_a_full_bank_banks_nothing(self):
        got = self.plan(bank_free=0)
        self.assertEqual(got.banks.get(SEAT, ()), ())

    def test_nothing_is_granted_only_what_is_carried_moves(self):
        got = self.plan()
        carried_guids = {r["item_guid"] for r in self.rows}
        moved = {c.guid for c in got.sales[SEAT] + got.banks[SEAT]}
        self.assertLessEqual(moved, carried_guids)

    def test_only_the_seats_named_are_planned(self):
        got = seatbags.plan_for(
            ["Nobody"], "Cave", self.rows, {"Nobody": 2}, extras_for(self.rows)
        )
        self.assertEqual(got.sales, {})
        self.assertEqual(got.banks, {})


class TheStepASeatTakes(unittest.TestCase):
    def test_a_seat_short_of_room_walks_to_a_vendor_and_sells_the_plan(self):
        m = seat(plan_sales=(carried(1, sell_price=40), carried(2, sell_price=30)))
        step = only_step(plan([m]), SEAT)
        self.assertEqual(step.action, guildjobs.SEAT_SELL_ACTION)
        self.assertEqual([r.command for r in step.rows], ["guid:1", "guid:2"])
        self.assertTrue(all(r.kind == "sell" for r in step.rows))
        self.assertTrue(step.walk.command.startswith("walk-to-vendor any"))

    def test_the_ordinary_vendor_visit_sells_the_plan_too(self):
        m = seat(plan_sales=(carried(9, sell_price=40),))
        self.assertIn(9, [c.guid for c in guildjobs.vendor_stacks(m, None)])

    def test_a_seat_with_room_is_left_to_its_ordinary_job(self):
        m = seat(free_slots=20, plan_sales=(carried(1, sell_price=40),))
        step = only_step(plan([m]), SEAT)
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.SEAT_SELL_ACTION)

    def test_a_reserved_stack_is_never_sold(self):
        import keep

        kept = keep.Reservations(guids=frozenset({(SEAT.lower(), 1)}))
        m = seat(plan_sales=(carried(1, sell_price=40), carried(2, sell_price=40)))
        stacks = guildjobs.vendor_stacks(m, kept)
        self.assertEqual([c.guid for c in stacks], [2])

    def test_the_sale_is_not_asked_again_inside_its_cooldown(self):
        m = seat(plan_sales=(carried(1, sell_price=40),))
        recent = (
            guildjobs.Recent(
                name=SEAT,
                action=guildjobs.SEAT_SELL_ACTION,
                age_minutes=5,
                status="applied",
            ),
        )
        step = only_step(plan([m], recent=recent), SEAT)
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.SEAT_SELL_ACTION)

    def test_a_seat_with_nothing_to_sell_banks_at_the_nearest_banker(self):
        m = seat(
            plan_bank=(carried(5, item_class=12), carried(6, item_class=12)),
            banker=BANKER,
        )
        step = only_step(plan([m]), SEAT)
        self.assertEqual(step.action, guildjobs.SEAT_BANK_ACTION)
        self.assertTrue(step.walk.command.startswith("walk-to-spawn creature:777"))
        self.assertEqual(
            [(r.kind, r.command) for r in step.rows],
            [("bank", "deposit guid:5"), ("bank", "deposit guid:6")],
        )

    def test_no_banker_in_reach_means_no_bank_step(self):
        m = seat(plan_bank=(carried(5, item_class=12),))
        step = only_step(plan([m]), SEAT)
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.SEAT_BANK_ACTION)

    def test_a_visit_banks_at_most_the_visit_limit(self):
        many = tuple(carried(100 + i, item_class=12) for i in range(40))
        m = seat(plan_bank=many, banker=BANKER)
        step = only_step(plan([m]), SEAT)
        self.assertEqual(len(step.rows), guildjobs.SEAT_BANK_VISIT)


class TheBankerNearestASeat(unittest.TestCase):
    def test_the_nearest_banker_on_the_map_within_the_cap(self):
        near = guildjobs.Spot("creature", 1, 0, -9010.0, 110.0)
        far = guildjobs.Spot("creature", 2, 0, -5000.0, 100.0)
        other_map = guildjobs.Spot("creature", 3, 1, -9000.0, 100.0)
        got = seatbags.nearest_banker(seat(), [far, other_map, near], 500)
        self.assertEqual(got.spawn, 1)

    def test_none_beyond_the_cap(self):
        far = guildjobs.Spot("creature", 2, 0, -5000.0, 100.0)
        self.assertIsNone(seatbags.nearest_banker(seat(), [far], 500))


class AttachingThePlan(unittest.TestCase):
    def test_attach_puts_the_plan_on_the_seat_and_leaves_others_alone(self):
        rows = [row(1, 100, "Broken Whistle", sell=40)]
        got = seatbags.plan_for([SEAT], "Cave", rows, {SEAT: 2}, extras_for(rows))
        other = member("Someone")
        out = seatbags.attach([seat(), other], got, [BANKER], 500)
        self.assertEqual([c.guid for c in out[0].plan_sales], [1])
        self.assertEqual(out[1], other)

    def test_a_switched_off_bank_attaches_no_banker(self):
        rows = [row(2, 200, "Tattered Letter", item_class=12, sell=0, quest_item=True)]
        got = seatbags.plan_for([SEAT], "Cave", rows, {SEAT: 2}, extras_for(rows))
        out = seatbags.attach([seat()], got, [BANKER], 500, bank=False)
        self.assertEqual(out[0].plan_bank, ())


class TheRelief(unittest.TestCase):
    ON = {"ITEMPLAN_SELL_VENDOR": "on"}

    def setUp(self):
        self.rows = [
            row(1, 100, "Broken Whistle", sell=40),
            row(2, 200, "Tattered Letter", item_class=12, sell=0, quest_item=True),
        ]
        self.reads = []

    def read(self, names):
        self.reads.append(list(names))
        return (
            "Cave",
            self.rows,
            {SEAT: 2},
            extras_for(self.rows),
            (),
            (),
            (),
        )

    def relieve(self, members, now=0.0, memo=None, environ=None):
        return seatbags.relieve(
            members,
            self.read,
            lambda maps: [BANKER],
            500,
            now,
            memo or seatbags.Memo(),
            self.ON if environ is None else environ,
        )

    def test_the_loop_trigger_is_the_plans_trigger(self):
        self.assertEqual(guildjobs.SEAT_LOOP_FREE, itemplan.TRIGGER_FREE)

    def test_a_seat_short_of_room_gets_its_plan_and_a_banker(self):
        out, lines = self.relieve([seat()])
        self.assertEqual([c.guid for c in out[0].plan_sales], [1])
        self.assertEqual([c.guid for c in out[0].plan_bank], [2])
        self.assertEqual(out[0].banker.spawn, 777)
        self.assertEqual(len(lines), 1)
        self.assertIn(SEAT, lines[0])

    def test_nothing_is_read_while_the_vendor_route_is_off(self):
        out, lines = self.relieve([seat()], environ={})
        self.assertEqual(self.reads, [])
        self.assertEqual(out[0].plan_sales, ())
        self.assertEqual(lines, ())

    def test_a_seat_with_room_is_not_read(self):
        self.relieve([seat(free_slots=30)])
        self.assertEqual(self.reads, [])

    def test_a_seat_planned_lately_is_not_read_again(self):
        memo = seatbags.Memo()
        self.relieve([seat()], now=0.0, memo=memo)
        out, _ = self.relieve([seat()], now=60.0, memo=memo)
        self.assertEqual(len(self.reads), 1)
        self.assertEqual([c.guid for c in out[0].plan_sales], [1])
        self.relieve([seat()], now=seatbags.REFRESH_SECONDS + 1, memo=memo)
        self.assertEqual(len(self.reads), 2)

    def test_a_failed_read_leaves_the_members_as_they_were(self):
        self.read = lambda names: None
        out, lines = self.relieve([seat()])
        self.assertEqual(out[0].plan_sales, ())
        self.assertEqual(lines, ())

    def test_the_bank_switch_off_leaves_the_deposits_out(self):
        env = dict(self.ON, GUILD_SEAT_BANK="off")
        out, _ = self.relieve([seat()], environ=env)
        self.assertEqual(out[0].plan_bank, ())
        self.assertEqual([c.guid for c in out[0].plan_sales], [1])

    def test_the_bridge_asks_for_the_relief_before_the_plan(self):
        import pathlib

        text = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        start = text.index("async def _start_guild_job_pass")
        end = text.index("plan = await self._plan_guild_jobs", start)
        self.assertIn("_seat_bag_relief", text[start:end])
        relief = text[text.index("def _seat_bag_relief") :]
        self.assertIn("seatbags.relieve", relief[: relief.index("def _read_seat_bags")])


class TheShape(unittest.TestCase):
    def test_a_member_is_a_dataclass_with_the_plan_fields(self):
        m = replace(seat(), plan_sales=(), plan_bank=(), banker=None)
        self.assertEqual(m.plan_sales, ())
        self.assertIsInstance(guildcorps.Row("bank", "deposit guid:1"), guildcorps.Row)


if __name__ == "__main__":
    unittest.main()
