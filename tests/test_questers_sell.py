"""A quester with full bags sells before it takes another quest (#1813).

Questers never sold, so their bags filled, and a quest that hands over an item
on the take waits on a free general bag slot (questers.open_to, #1732). The
sale is the guild members' own (guildjobs.vendor_stacks, vendorsale.py): a
walk to any vendor that buys and a sell row per stack it has no use for, never
a quest item, an upgrade or a stack reserved in overseer_keep."""

import contextlib
import types
import unittest
from unittest import mock

import gear
import guildjobs
import keep
import questers
from test_questers import ELWYNN, giver, quest, world

ARMOR, WEAPON, TRADE_GOODS, QUEST = 4, 2, 7, 12
MEAT = 8
CHEST = 5  # InventoryType: a chest piece


def quester(**kw):
    base = dict(
        name="Mirra",
        level=20,
        race=1,
        class_id=5,
        map_id=0,
        x=10.0,
        y=0.0,
        zone_id=ELWYNN,
        online=True,
        free_slots=0,
    )
    base.update(kw)
    return questers.Member(**base)


def stack(guid, entry, item_class, quality=1, price=10, subclass=0, count=1, **kw):
    return guildjobs.Carried(
        guid=guid,
        entry=entry,
        count=count,
        item_class=item_class,
        subclass=subclass,
        quality=quality,
        sell_price=price,
        name="item %d" % entry,
        **kw,
    )


GREY = stack(1, 500, ARMOR, quality=0, price=7)
MEAT_STACK = stack(2, 501, TRADE_GOODS, subclass=MEAT, price=4, count=5)
QUEST_ITEM = stack(3, 502, QUEST, price=0)
# A cloth chest a level 20 priest would wear: an upgrade over nothing worn.
UPGRADE = stack(
    4,
    503,
    ARMOR,
    subclass=1,
    quality=2,
    price=300,
    item_level=21,
    required_level=16,
    inventory_type=CHEST,
)
# White trade goods a catalogue quest asks for (RequiredItemId).
WANTED = stack(5, 504, TRADE_GOODS, subclass=MEAT, price=3)
RESERVED = stack(6, 505, ARMOR, quality=0, price=50)


def catalogue():
    wants = dict(
        quest(40, ELWYNN, 4, title="Goretusk Liver Pie"), item1=504, item_count1=4
    )
    return world(
        extra_quests=[wants],
        extra_givers=[
            giver(40, "start", 1040, 140, 50, 0),
            giver(40, "end", 1040, 140, 50, 0),
        ],
    )


def worn():
    return gear.CharacterState("Mirra", 5, 20, {})


def kept():
    return keep.from_rows(
        [{"character_name": "Mirra", "item_guid": 6, "item_entry": 505}]
    )


def sale(member, carried, recent=(), worn_gear=None, reservations=None, cat=None):
    return questers.sell_step(
        member,
        carried,
        worn_gear if worn_gear is not None else worn(),
        reservations if reservations is not None else kept(),
        cat or catalogue(),
        recent,
        0,
    )


def sold(step):
    return [r.command for r in step.rows]


class AFullQuesterSells(unittest.TestCase):
    """#1813 criterion 1 and 3: a quester at the floor walks to a vendor."""

    def test_a_full_bag_quester_is_sent_to_a_vendor_and_frees_a_slot(self):
        step = sale(quester(free_slots=0), (GREY, MEAT_STACK, QUEST_ITEM))
        self.assertIsNotNone(step)
        self.assertEqual(step.holder, "Mirra")
        self.assertEqual(step.action, questers.SELL_ACTION)
        self.assertTrue(step.walk.command.startswith("walk-to-vendor any"))
        self.assertEqual(sorted(sold(step)), ["guid:1", "guid:2"])
        self.assertTrue(all(r.kind == "sell" for r in step.rows))
        # Every stack sold is a slot back: the quester ends with room.
        self.assertGreaterEqual(0 + len(step.rows), 1)
        self.assertEqual(
            {guildjobs.action_of(r.source) for r in step.rows}, {questers.SELL_ACTION}
        )

    def test_a_quester_at_the_floor_sells_too(self):
        step = sale(quester(free_slots=questers.SELL_FLOOR), (GREY,))
        self.assertEqual(sold(step), ["guid:1"])

    def test_a_quester_with_room_is_not_sent(self):
        self.assertIsNone(
            sale(quester(free_slots=questers.SELL_FLOOR + 1), (GREY, MEAT_STACK))
        )
        self.assertIsNone(sale(quester(free_slots=12), (GREY, MEAT_STACK)))

    def test_unread_bags_send_nobody(self):
        self.assertIsNone(sale(quester(free_slots=None), (GREY,)))

    def test_an_offline_dead_or_unplaced_quester_is_not_sent(self):
        for who in (
            quester(online=False),
            quester(alive=False),
            quester(map_id=None),
        ):
            self.assertIsNone(sale(who, (GREY,)), who)

    def test_a_sale_just_asked_is_not_asked_again(self):
        source = guildjobs.source_for(questers.SELL_ACTION, "Mirra")
        young = types.SimpleNamespace(
            name="Mirra", action=questers.SELL_ACTION, age_minutes=5, source=source
        )
        self.assertIsNone(sale(quester(), (GREY,), recent=(young,)))
        old = types.SimpleNamespace(
            name="Mirra",
            action=questers.SELL_ACTION,
            age_minutes=questers.SELL_COOLDOWN_MINUTES,
            source=source,
        )
        self.assertIsNotNone(sale(quester(), (GREY,), recent=(old,)))


class WhatAQuesterKeeps(unittest.TestCase):
    """#1813 criterion 2: quest items, upgrades and kept stacks stay."""

    def test_quest_items_upgrades_wanted_and_reserved_stacks_stay(self):
        step = sale(
            quester(),
            (GREY, MEAT_STACK, QUEST_ITEM, UPGRADE, WANTED, RESERVED),
        )
        self.assertEqual(sorted(sold(step)), ["guid:1", "guid:2"])

    def test_gear_is_kept_while_the_worn_gear_is_unread(self):
        step = questers.sell_step(
            quester(), (GREY, UPGRADE), None, kept(), catalogue(), (), 0
        )
        self.assertEqual(sold(step), ["guid:1"])

    def test_nothing_to_part_with_sends_nobody(self):
        self.assertIsNone(sale(quester(), (QUEST_ITEM, UPGRADE, WANTED, RESERVED)))

    def test_unread_reservations_sell_nothing(self):
        self.assertIsNone(
            questers.sell_step(quester(), (GREY,), worn(), None, catalogue(), (), 0)
        )


def run_pass(member, carried):
    """The bridge's quester pass over one quester, its bags read as `carried`."""
    from test_questers_bridge import Pass, bridge

    run = Pass([member])
    asked = []

    def bags(names):
        asked.append(list(names))
        return {member.name: tuple(carried)}, {member.name: worn()}, ()

    with mock.patch.multiple(
        bridge,
        _fetch_quester_bags=bags,
        _KEEP=types.SimpleNamespace(now=lambda: keep.Reservations()),
    ):
        run.run()
    return run, asked


class TheBridgeSendsAFullQuesterToSell(unittest.TestCase):
    """#1813 criterion 1 and 3, through the bridge's own quester pass."""

    def test_a_full_quester_sells_in_place_of_its_take(self):
        run, asked = run_pass(quester(level=2, x=0.0, free_slots=0), (GREY, MEAT_STACK))
        self.assertEqual(asked, [["Mirra"]])
        (step,) = run.started
        self.assertEqual(step.action, questers.SELL_ACTION)
        self.assertEqual(sorted(r.command for r in step.rows), ["guid:1", "guid:2"])
        self.assertTrue(step.walk.command.startswith("walk-to-vendor any"))

    def test_a_quester_with_room_takes_its_quest_and_its_bags_are_not_read(self):
        run, asked = run_pass(quester(level=2, x=0.0, free_slots=8), (GREY, MEAT_STACK))
        self.assertEqual(asked, [])
        (step,) = run.started
        self.assertEqual([r.command for r in step.rows], ["take quest:1"])

    def test_a_full_quester_with_nothing_to_sell_still_moves(self):
        run, _asked = run_pass(quester(level=2, x=0.0, free_slots=0), (QUEST_ITEM,))
        (step,) = run.started
        self.assertEqual([r.command for r in step.rows], ["take quest:1"])


class TheBridgeReadsTheBags(unittest.TestCase):
    def test_carried_worn_and_sale_rows_reach_the_sale(self):
        from test_guildsocial_bridge import bridge

        def rows_for(sql):
            if sql.startswith("SELECT c.guid, c.name"):
                return [{"guid": 7, "name": "Mirra"}]
            if (
                "item_instance ii ON ii.guid = ci.item" in sql
                and "ci.guid AS owner" in sql
            ):
                return [
                    {
                        "owner": 7,
                        "item_guid": 1,
                        "entry": 500,
                        "count": 1,
                        "class": ARMOR,
                        "subclass": 0,
                        "quality": 0,
                        "sell_price": 7,
                        "item_name": "Rag",
                    },
                    {
                        "owner": 8,
                        "item_guid": 9,
                        "entry": 501,
                        "count": 1,
                        "class": ARMOR,
                        "subclass": 0,
                        "quality": 0,
                        "sell_price": 7,
                        "item_name": "Other",
                    },
                ]
            if "equipment_slot" in sql:
                return [
                    {
                        "name": "Mirra",
                        "class_id": 5,
                        "level": 20,
                        "equipment_slot": None,
                        "inventory_type": None,
                        "item_level": None,
                    }
                ]
            if "overseer_command" in sql:
                return [
                    {
                        "id": 1,
                        "target_name": "Mirra",
                        "command": "guid:1",
                        "source": guildjobs.source_for(questers.SELL_ACTION, "Mirra"),
                        "status": "applied",
                        "target_arg": "",
                        "result": "",
                        "age": 3,
                    }
                ]
            return []

        class Cur:
            def execute(self, sql, args=()):
                self.rows = rows_for(sql)

            def fetchall(self):
                return self.rows

        class Conn:
            def cursor(self):
                return contextlib.nullcontext(Cur())

        with mock.patch.object(
            bridge, "_connect", lambda: contextlib.nullcontext(Conn())
        ):
            carried, worn_by, sold = bridge._fetch_quester_bags(["Mirra"])
        self.assertEqual([c.guid for c in carried["Mirra"]], [1])
        self.assertNotIn("Other", str(carried))
        self.assertIn("Mirra", worn_by)
        self.assertEqual(
            [(r.name, r.action) for r in sold], [("Mirra", questers.SELL_ACTION)]
        )
        self.assertIsNone(
            questers.sell_step(
                quester(),
                carried["Mirra"],
                worn_by["Mirra"],
                keep.Reservations(),
                catalogue(),
                sold,
                0,
            )
        )
        self.assertEqual(bridge._fetch_quester_bags([]), ({}, {}, ()))


if __name__ == "__main__":
    unittest.main()
