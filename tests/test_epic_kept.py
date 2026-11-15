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
import equipscore  # noqa: E402
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
            bag_pressure.epic_kept_line(epic(), "Zork"),
            "kept Taran Icebreaker: an epic a guild member can wear; "
            "it stays in Zork's bags until gear routing places it",
        )


FLEETFOOT_GUID = 91300001


def boe_rare(**kw):
    """Fleetfoot Greaves, a bind-on-equip mail rare the families sold, in the
    shape the bridge's facts read returns."""
    base = epic(
        name="Fleetfoot Greaves",
        item_guid=FLEETFOOT_GUID,
        entry=9476,
        quality=3,
        required_level=43,
        item_class=4,
        subclass=3,  # mail
        inventory_type=8,  # feet
        bonding=2,
        holder_class=PRIEST,
    )
    base.update(kw)
    return base


def judge(answer):
    """An upgrade judge that answers `answer` and records what it was asked."""
    asked = []

    def ask(row):
        asked.append(row["item_guid"])
        return answer

    ask.asked = asked
    return ask


class RareKeptTest(unittest.TestCase):
    """A bind-on-equip rare a guild member can wear and would wear over what
    they wear now is kept for routing (#2389); the judge is the caller's."""

    def test_a_boe_rare_that_is_an_upgrade_is_kept(self):
        self.assertTrue(
            bag_pressure.epic_kept(boe_rare(), EVERY_CLASS, upgrade=judge(("Zrog",)))
        )

    def test_a_boe_rare_nobody_would_wear_is_not_kept(self):
        self.assertFalse(
            bag_pressure.epic_kept(boe_rare(), EVERY_CLASS, upgrade=judge(()))
        )

    def test_an_unread_judge_keeps_it(self):
        self.assertTrue(
            bag_pressure.epic_kept(boe_rare(), EVERY_CLASS, upgrade=judge(None))
        )

    def test_a_soulbound_rare_keeps_todays_behaviour(self):
        for row in (boe_rare(bonding=1), boe_rare(instance_flags=1)):
            with self.subTest(bonding=row["bonding"], flags=row["instance_flags"]):
                ask = judge(("Zrog",))
                self.assertFalse(bag_pressure.epic_kept(row, EVERY_CLASS, upgrade=ask))
                self.assertEqual(ask.asked, [])

    def test_a_rare_no_guild_class_can_wear_is_not_asked_about(self):
        ask = judge(("Zrog",))
        self.assertFalse(
            bag_pressure.epic_kept(boe_rare(), {MAGE, PRIEST, ROGUE}, upgrade=ask)
        )
        self.assertEqual(ask.asked, [])

    def test_a_rare_above_the_cap_or_not_gear_is_not_kept(self):
        for row in (boe_rare(required_level=61), boe_rare(item_class=7)):
            self.assertFalse(
                bag_pressure.epic_kept(row, EVERY_CLASS, upgrade=judge(("Zrog",)))
            )

    def test_without_a_judge_a_rare_is_not_this_rule(self):
        self.assertFalse(bag_pressure.epic_kept(boe_rare(), EVERY_CLASS))

    def test_below_rare_is_never_asked(self):
        ask = judge(("Zrog",))
        self.assertFalse(
            bag_pressure.epic_kept(boe_rare(quality=2), EVERY_CLASS, upgrade=ask)
        )
        self.assertEqual(ask.asked, [])

    def test_an_epic_is_kept_without_asking_the_judge(self):
        ask = judge(())
        self.assertTrue(bag_pressure.epic_kept(epic(), EVERY_CLASS, upgrade=ask))
        self.assertEqual(ask.asked, [])

    def test_the_rare_kept_line_names_who_would_wear_it(self):
        self.assertEqual(
            bag_pressure.epic_kept_line(boe_rare(), "Ugga", ("Zrog", "Oz")),
            "kept Fleetfoot Greaves: a bind-on-equip rare that is an upgrade for "
            "Zrog, Oz; it stays in Ugga's bags until gear routing places it",
        )


# equipscore's row shapes, as the bridge's scored-gear and wearer reads return
# them (tests/test_gearrouting.py builds the same).
HUMAN = 1
SHAMAN_SKILLS = "54,413,414,415,433"
AGI, STA = 3, 7


def scored(name, inv, *, holder, slot=None, level=40, req=35, stats=(), **kw):
    row = dict(
        holder=holder,
        equipment_slot=slot,
        item_guid=kw.pop("item_guid", 1),
        entry=kw.pop("entry", 1),
        name=name,
        quality=3,
        item_level=level,
        required_level=req,
        item_class=4,
        item_subclass=3,
        inventory_type=inv,
        allowable_class=-1,
        allowable_race=-1,
        required_skill=0,
        required_skill_rank=0,
        required_spell=0,
        required_reputation=0,
        max_count=0,
        item_flags=0,
        armor=kw.pop("armor", 0),
        block=0,
        dmg_min1=0,
        dmg_max1=0,
        delay=0,
        random_property_id=0,
        enchantments="",
    )
    for n, (kind, amount) in enumerate(stats, start=1):
        row["stat_type%d" % n] = kind
        row["stat_value%d" % n] = amount
    row.update(kw)
    return row


def shaman(name, level=45):
    return dict(
        name=name,
        class_id=SHAMAN,
        level=level,
        race=HUMAN,
        talent_spells="",
        target_tree="Enhancement",
        skills=SHAMAN_SKILLS,
    )


GREAVES = scored(
    "Fleetfoot Greaves",
    8,
    holder="Ugga",
    item_guid=FLEETFOOT_GUID,
    entry=9476,
    level=48,
    req=43,
    stats=((AGI, 12), (STA, 8)),
    armor=180,
)
BETTER = dict(level=60, req=55, stats=((AGI, 30), (STA, 20)), armor=300)
ANTIQUE = dict(level=20, req=15, stats=((STA, 2),), armor=60)


def worn_boots(holder, **kw):
    return scored("Worn Boots", 8, holder=holder, slot=7, item_guid=5, **kw)


class WantedByTest(unittest.TestCase):
    """`equipscore.wanted_by`: who the equip judge would put a piece on."""

    def test_a_member_in_antique_boots_wants_it(self):
        wearers = [shaman("Zrog"), shaman("Oz")]
        worn = [worn_boots("Zrog", **ANTIQUE), worn_boots("Oz", **BETTER)]
        self.assertEqual(equipscore.wanted_by(GREAVES, wearers, worn), ("Zrog",))

    def test_nobody_wants_it_when_everybody_wears_better(self):
        wearers = [shaman("Oz")]
        worn = [worn_boots("Oz", **BETTER)]
        self.assertEqual(equipscore.wanted_by(GREAVES, wearers, worn), ())

    def test_a_member_below_its_level_does_not_want_it_yet(self):
        wearers = [shaman("Zrog", level=30)]
        worn = [worn_boots("Zrog", **ANTIQUE)]
        self.assertEqual(equipscore.wanted_by(GREAVES, wearers, worn), ())

    def test_carried_rows_are_not_worn(self):
        wearers = [shaman("Zrog")]
        rows = [
            worn_boots("Zrog", **ANTIQUE),
            dict(GREAVES, holder="Zrog", item_guid=9),
        ]
        self.assertEqual(equipscore.wanted_by(GREAVES, wearers, rows), ("Zrog",))


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
        self.wanted: dict = {}
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
            mock.patch.object(
                bridge,
                "_rare_wanted_by",
                side_effect=lambda holder, row: self.wanted.get(row["item_guid"], ()),
            ),
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
            "it stays in Zork's bags until gear routing places it",
            self.lines,
        )

    def test_the_sale_pass_refuses_a_boe_rare_a_guild_member_would_wear(self):
        self.facts[FLEETFOOT_GUID] = boe_rare()
        self.wanted[FLEETFOOT_GUID] = ("Zrog",)
        wrote = self.bridge._insert_sell(self.candidate("Ugga", FLEETFOOT_GUID, 3))
        self.assertFalse(wrote)
        self.assertEqual(self.inserts(), [])
        self.assertIn(
            "kept Fleetfoot Greaves: a bind-on-equip rare that is an upgrade for "
            "Zrog; it stays in Ugga's bags until gear routing places it",
            self.lines,
        )

    def test_the_sale_pass_sells_a_boe_rare_nobody_would_wear(self):
        self.facts[FLEETFOOT_GUID] = boe_rare()
        wrote = self.bridge._insert_sell(self.candidate("Ugga", FLEETFOOT_GUID, 3))
        self.assertTrue(wrote)
        self.assertEqual(len(self.inserts()), 1)

    def test_the_sale_pass_sells_a_soulbound_rare_as_today(self):
        self.facts[FLEETFOOT_GUID] = boe_rare(instance_flags=1)
        self.wanted[FLEETFOOT_GUID] = ("Zrog",)
        wrote = self.bridge._insert_sell(self.candidate("Ugga", FLEETFOOT_GUID, 3))
        self.assertTrue(wrote)

    def test_a_failed_upgrade_read_keeps_the_rare(self):
        self.facts[FLEETFOOT_GUID] = boe_rare()
        self.wanted[FLEETFOOT_GUID] = None
        wrote = self.bridge._insert_sell(self.candidate("Ugga", FLEETFOOT_GUID, 3))
        self.assertFalse(wrote)

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
