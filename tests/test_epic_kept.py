"""An epic a guild member could wear is never sold or destroyed (#2385).

The case is the dev realm's, read on 2026-11-13: the families sold 16
bind-on-equip classic epics to vendors between 2026-11-03 and 2026-11-12
(Taran Icebreaker, Kang the Decapitator, Hurricane and the rest), every one
of required level 36 to 48, while both family guilds held every class and
many members below that level. Shriveled Heart, which requires level 80, is
the one epic they sold that nobody on the realm can ever wear.

The rule is `bag_pressure.epic_kept`, asked once per row by the bridge's
`_epic_blocks`, which every writer of a `sell` row asks before it writes.
"""

from __future__ import annotations

import asyncio
import pathlib
import re
import sys
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bag_pressure  # noqa: E402
import guildcorps  # noqa: E402
import itemplan_vendor as vendor  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent

WARRIOR, PALADIN, HUNTER, ROGUE, PRIEST, SHAMAN, MAGE = 1, 2, 3, 4, 5, 7, 8
EVERY_CLASS = frozenset({1, 2, 3, 4, 5, 6, 7, 8, 9, 11})

TARAN_GUID = 91750830
HEART_GUID = 77000001


def epic(name="Taran Icebreaker", **kw):
    """A carried epic in the shape the bridge's facts read returns."""
    base = {
        "item_guid": TARAN_GUID,
        "entry": 2915,
        "name": name,
        "quality": 4,
        "required_level": 47,
        "item_class": 2,  # weapon
        "subclass": 5,  # two-handed mace
        "inventory_type": 17,  # two-hand
        "allowable_class": -1,
        "instance_flags": 0,
        "holder_class": WARRIOR,
    }
    base.update(kw)
    return base


def shriveled_heart(**kw):
    base = epic(
        name="Shriveled Heart",
        item_guid=HEART_GUID,
        entry=50309,
        required_level=80,
        item_class=4,
        subclass=0,
        inventory_type=23,  # held in the off hand
    )
    base.update(kw)
    return base


def plate_chest(**kw):
    base = epic(
        name="Icemail Jerkin",
        entry=1981,
        item_class=4,
        subclass=4,
        inventory_type=5,
        required_level=39,
    )
    base.update(kw)
    return base


class EpicKeptTest(unittest.TestCase):
    """The pure rule, one item and the guilds' classes in, a yes or no out."""

    def test_an_epic_a_guild_class_can_wear_is_kept(self):
        self.assertTrue(bag_pressure.epic_kept(epic(), EVERY_CLASS))
        self.assertTrue(bag_pressure.epic_kept(epic(), {WARRIOR}))

    def test_an_epic_above_the_level_cap_is_not_kept(self):
        self.assertFalse(bag_pressure.epic_kept(shriveled_heart(), EVERY_CLASS))

    def test_the_level_cap_itself_is_still_wearable(self):
        self.assertTrue(bag_pressure.epic_kept(epic(required_level=60), {WARRIOR}))
        self.assertFalse(bag_pressure.epic_kept(epic(required_level=61), {WARRIOR}))

    def test_below_epic_is_not_this_rule(self):
        self.assertFalse(bag_pressure.epic_kept(epic(quality=3), EVERY_CLASS))
        self.assertTrue(bag_pressure.epic_kept(epic(quality=5), EVERY_CLASS))

    def test_armour_follows_the_heaviest_type_a_class_reaches(self):
        self.assertFalse(bag_pressure.epic_kept(plate_chest(), {MAGE, PRIEST, ROGUE}))
        self.assertTrue(bag_pressure.epic_kept(plate_chest(), {MAGE, PALADIN}))
        mail = plate_chest(subclass=3)
        self.assertTrue(bag_pressure.epic_kept(mail, {HUNTER}))
        self.assertFalse(bag_pressure.epic_kept(mail, {ROGUE}))

    def test_a_shield_needs_a_shield_class(self):
        shield = epic(
            name="Blackskull Shield", item_class=4, subclass=6, inventory_type=14
        )
        self.assertFalse(bag_pressure.epic_kept(shield, {MAGE, ROGUE}))
        self.assertTrue(bag_pressure.epic_kept(shield, {SHAMAN}))

    def test_a_weapon_follows_the_class_weapon_skills(self):
        wand = epic(name="A Wand", subclass=19, inventory_type=26)
        self.assertFalse(bag_pressure.epic_kept(wand, {WARRIOR, ROGUE}))
        self.assertTrue(bag_pressure.epic_kept(wand, {MAGE}))

    def test_allowable_class_is_honoured(self):
        paladin_only = epic(allowable_class=1 << (PALADIN - 1))
        self.assertFalse(bag_pressure.epic_kept(paladin_only, {WARRIOR}))
        self.assertTrue(bag_pressure.epic_kept(paladin_only, {PALADIN}))

    def test_an_epic_nobody_can_equip_is_not_kept(self):
        self.assertFalse(bag_pressure.epic_kept(epic(item_class=7), EVERY_CLASS))
        self.assertFalse(
            bag_pressure.epic_kept(epic(item_class=4, inventory_type=0), EVERY_CLASS)
        )

    def test_a_soulbound_epic_is_only_ever_its_holders(self):
        bound = plate_chest(instance_flags=1, holder_class=MAGE)
        self.assertFalse(bag_pressure.epic_kept(bound, {WARRIOR, MAGE}))
        bound_warrior = plate_chest(instance_flags=1, holder_class=WARRIOR)
        self.assertTrue(bag_pressure.epic_kept(bound_warrior, {MAGE}))

    def test_a_soulbound_epic_with_no_holder_class_asks_the_guilds(self):
        bound = plate_chest(instance_flags=1, holder_class=None)
        self.assertTrue(bag_pressure.epic_kept(bound, {WARRIOR}))

    def test_unread_facts_keep_the_epic(self):
        self.assertTrue(bag_pressure.epic_kept(epic(), frozenset()))
        self.assertTrue(bag_pressure.epic_kept(epic(), None))
        self.assertTrue(bag_pressure.epic_kept(epic(required_level=None), {MAGE}))
        no_level = epic()
        del no_level["required_level"]
        self.assertTrue(bag_pressure.epic_kept(no_level, {MAGE}))
        self.assertTrue(bag_pressure.epic_kept(epic(quality=None), {MAGE}))

    def test_the_kept_line(self):
        self.assertEqual(
            bag_pressure.epic_kept_line(epic()),
            "kept Taran Icebreaker: an epic a guild member can wear; "
            "routing will place it",
        )


def import_bridge():
    discord = types.ModuleType("discord")
    discord.Client = object
    return fresh_import("bridge", discord=discord, pymysql=PYMYSQL)


class FakeCursor:
    def __init__(self, sink):
        self.sink = sink
        self.lastrowid = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.sink.append((sql, params))
        if "INSERT INTO overseer_command" in sql:
            self.lastrowid = len(self.sink)

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return FakeCursor(self.sink)


class WriterGateTest(unittest.TestCase):
    """The bridge's writers, run for real against a fake world."""

    def setUp(self):
        self.bridge = import_bridge()
        self.sql: list = []
        self.lines: list = []
        self.facts: dict = {}
        bridge = self.bridge
        fake_log = types.SimpleNamespace(
            info=lambda msg, *a: self.lines.append(msg % a if a else msg),
            warning=lambda msg, *a: self.lines.append(msg % a if a else msg),
            exception=lambda msg, *a: self.lines.append(msg % a if a else msg),
        )
        patches = (
            mock.patch.object(
                bridge, "_connect", side_effect=lambda: FakeConnection(self.sql)
            ),
            mock.patch.object(
                bridge,
                "_fetch_epic_facts",
                side_effect=lambda guids: [
                    self.facts[g] for g in guids if g in self.facts
                ],
            ),
            mock.patch.object(bridge, "_guild_classes", return_value=EVERY_CLASS),
            mock.patch.object(bridge, "_held_as_follower", return_value=False),
            mock.patch.object(
                bridge, "_KEEP", types.SimpleNamespace(blocks=lambda h, c: False)
            ),
            mock.patch.object(bridge, "log", fake_log),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def inserts(self):
        return [s for s in self.sql if "INSERT INTO overseer_command" in s[0]]

    @staticmethod
    def candidate(holder, guid, quality=4):
        return bag_pressure.SellCandidate(
            holder=holder,
            item_guid=guid,
            count=1,
            item=bag_pressure.ItemForSale(quality=quality, sell_price=55289),
        )

    def test_the_sale_pass_refuses_an_epic_a_guild_member_can_wear(self):
        self.facts[TARAN_GUID] = epic()
        wrote = self.bridge._insert_sell(self.candidate("Zork", TARAN_GUID))
        self.assertFalse(wrote)
        self.assertEqual(self.inserts(), [])
        self.assertIn(
            "kept Taran Icebreaker: an epic a guild member can wear; "
            "routing will place it",
            self.lines,
        )

    def test_the_sale_pass_still_sells_shriveled_heart(self):
        self.facts[HEART_GUID] = shriveled_heart()
        wrote = self.bridge._insert_sell(self.candidate("Grog", HEART_GUID))
        self.assertTrue(wrote)
        self.assertEqual(len(self.inserts()), 1)

    def test_an_ordinary_sale_is_untouched(self):
        wrote = self.bridge._insert_sell(self.candidate("Grog", 4242, quality=0))
        self.assertTrue(wrote)
        self.assertEqual(len(self.inserts()), 1)

    def test_the_destroy_verb_refuses_an_epic_a_guild_member_can_wear(self):
        self.facts[TARAN_GUID] = epic()
        self.assertFalse(
            self.bridge._insert_destroy(self.candidate("Zork", TARAN_GUID))
        )
        self.assertEqual(self.inserts(), [])

    def test_a_guild_job_sale_or_destroy_row_is_refused_too(self):
        self.facts[TARAN_GUID] = epic()
        for command in ("guid:%d" % TARAN_GUID, "destroy guid:%d count:1" % TARAN_GUID):
            with self.subTest(command=command):
                row = guildcorps.Row("sell", command, "", "guildjobs:sell:Zork")
                self.assertFalse(self.bridge._insert_corps_row("Zork", row))
        self.assertEqual(self.inserts(), [])

    def test_a_guild_job_give_row_is_not_this_rule(self):
        self.facts[TARAN_GUID] = epic()
        row = guildcorps.Row("give", "guid:%d" % TARAN_GUID, "Grug", "guildjobs")
        self.assertTrue(self.bridge._insert_corps_row("Zork", row))

    def test_a_failed_facts_read_writes_nothing(self):
        with mock.patch.object(
            self.bridge, "_fetch_epic_facts", side_effect=RuntimeError("gone")
        ):
            self.assertFalse(
                self.bridge._insert_sell(self.candidate("Zork", TARAN_GUID))
            )
        self.assertEqual(self.inserts(), [])

    def test_the_bag_pressure_release_cannot_sell_an_epic_through_the_route(self):
        """A route sale (#1977, released under pressure by #2305/#2306) goes
        out through the same `_insert_sell`, so the gate refuses it too."""
        self.facts[TARAN_GUID] = epic()
        sale = vendor.Sale(
            holder="Zork",
            name="Taran Icebreaker",
            count=1,
            copper=55289,
            key=("Zork", TARAN_GUID),
            candidate=self.candidate("Zork", TARAN_GUID),
            released=vendor.RELEASED_CONFIRM,
        )
        wrote, asked = asyncio.run(
            self.bridge._queue_route_sales((sale,), ["Zork"], ())
        )
        self.assertEqual((wrote, asked), (0, 1))
        self.assertEqual(self.inserts(), [])


class WritersAskTest(unittest.TestCase):
    """Every bridge writer that can write a `sell` row asks the gate first."""

    WRITERS = (
        "_insert_sell",
        "_insert_destroy",
        "_insert_corps_row",
        "_insert_crafter_row",
    )

    def setUp(self):
        self.source = (HERE / "bridge.py").read_text()

    def body(self, name):
        match = re.search(r"^def %s\(.*?(?=^def |\Z)" % name, self.source, re.S | re.M)
        self.assertIsNotNone(match, name)
        return match.group(0)

    def test_each_sale_writer_asks_before_it_writes(self):
        for name in self.WRITERS:
            with self.subTest(writer=name):
                body = self.body(name)
                ask = body.find("_epic_blocks(")
                write = body.find("INSERT INTO overseer_command")
                self.assertGreater(ask, 0, name)
                self.assertLess(ask, write, name)

    def test_no_other_writer_inserts_a_sell_row(self):
        for match in re.finditer(r"^def (\w+)\(", self.source, re.M):
            name = match.group(1)
            body = self.body(name)
            if "INSERT INTO overseer_command" in body and "'sell'" in body:
                with self.subTest(writer=name):
                    self.assertIn(name, self.WRITERS)


class ReleaseHoldsEpicsTest(unittest.TestCase):
    """The bag-pressure release (#2305, #2306) holds quality 4 itself."""

    def test_the_release_ceiling_stops_below_epic(self):
        self.assertLess(vendor.RELEASE_MAX_QUALITY, bag_pressure.EPIC_QUALITY)


if __name__ == "__main__":
    unittest.main()
