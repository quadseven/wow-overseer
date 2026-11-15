"""Class reagents a guild member buys from a vendor with its own gold (#2622).

Acceptance criteria from #2622:
- A level 60 shaman that knows Reincarnation and carries no Ankh gets a buy
  for one, and one that carries 5 gets none.
- The reagent list comes from the realm's spell data at run time, not a table
  written in code.
- The buy sits behind riding and food in purse.ORDER and never spends below the
  class spell reserve.
- Items that no vendor sells (Soul Shard is made, not bought) are skipped with
  a reason, and profession materials in craftbook.json are out of scope.
"""

import struct
import sys
import types
import unittest
from unittest import mock

import guildjobs
import keep
import purse
import restsupply


REINCARNATION = 20608
ANKH = 17030
GREATER_KINGS = 25898
SYMBOL_OF_KINGS = 21177
WATER_WALKING = 546
FISH_OIL = 17058
SOUL_FIRE = 6353
SOUL_SHARD = 6265
INFERNAL_SPELL = 1122
INFERNAL_STONE = 5565
# Profession spell from craftbook.json (Apprentice Tailor bolt or similar)
FIRST_AID_SPELL = 3275  # Linen Bandage, in craftbook.json


def _make_spell_dbc(rows) -> bytes:
    """Build a minimal 3.3.5a WDBC Spell.dbc binary blob from
    ``(spell_id, ((reagent_id, count), ...))`` rows.

    Field layout matches WoW 3.3.5a Spell.dbc (tools/craftbook_from_dbc.py):
    field 0 = ID, fields 52..59 = Reagent[8], fields 60..67 = ReagentCount[8].
    """
    fields = 234
    record_size = fields * 4
    header = struct.pack("<4s4I", b"WDBC", len(rows), fields, record_size, 1)
    body = bytearray()
    for spell_id, reagents in rows:
        vals = [0] * fields
        vals[0] = int(spell_id)
        for idx, (entry, count) in enumerate(reagents[:8]):
            vals[52 + idx] = int(entry)
            vals[60 + idx] = int(count)
        body.extend(struct.pack("<%di" % fields, *vals))
    return header + bytes(body) + b"\x00"


def _shaman(**over):
    base = dict(
        name="Thrallbot",
        guild="Bonkers",
        role=guildjobs.RAIDER,
        level=60,
        class_id=7,  # shaman
        race=2,  # orc (Horde)
        online=True,
        map_id=1,
        x=1600.0,
        y=-4400.0,
        zone_id=1637,
        money=100000,  # 10g
        eligible=True,
        food=20,
        drink=20,
        free_slots=10,
        skills_read=True,
        known=frozenset({REINCARNATION}),
    )
    base.update(over)
    return guildjobs.Member(**base)


def _vendor_row(
    entry,
    *,
    vendor=3333,
    vendor_name="Zlag",
    item_name="",
    price=2000,
    buy_count=1,
    yards=40.0,
    enemy_group=2,  # Alliance enemy (Horde-friendly)
    map_id=1,
):
    return {
        "vendor": vendor,
        "vendor_name": vendor_name,
        "map_id": map_id,
        "yards": yards,
        "entry": entry,
        "item_name": item_name or ("Item %d" % entry),
        "price": price,
        "buy_count": buy_count,
        "enemy_group": enemy_group,
    }


def _reagent_stack(guid, entry, count, *, item_class=5, subclass=0, price=100):
    return guildjobs.Carried(
        guid=guid,
        entry=entry,
        count=count,
        item_class=item_class,
        subclass=subclass,
        quality=1,
        sell_price=price,
    )


def _load_bridge():
    for key in list(sys.modules):
        if key == "bridge" or key.startswith("discord"):
            sys.modules.pop(key, None)
    discord = types.ModuleType("discord")
    discord.Intents = type(
        "Intents",
        (),
        {"default": staticmethod(lambda: types.SimpleNamespace(message_content=False))},
    )
    discord.Client = object
    discord.app_commands = types.SimpleNamespace(
        CommandTree=lambda *_a, **_kw: object(),
        describe=lambda **_kw: lambda fn: fn,
    )
    discord.ext = types.ModuleType("discord.ext")
    discord.ext.commands = types.ModuleType("discord.ext.commands")
    sys.modules["discord"] = discord
    sys.modules["discord.ext"] = discord.ext
    sys.modules["discord.ext.commands"] = discord.ext.commands
    import bridge

    return bridge


class ClassReagentsTests(unittest.TestCase):
    def test_shaman_with_reincarnation_and_no_ankh_buys_ankh_and_with_5_buys_none(self):
        import classreagents

        dbc = classreagents.parse_spell_dbc(
            _make_spell_dbc([(REINCARNATION, ((ANKH, 1),))])
        )
        shaman_empty = _shaman()
        vendors = [_vendor_row(ANKH, item_name="Ankh", price=2000)]

        plan_empty = guildjobs.plan(
            [shaman_empty],
            class_reagents={
                "Thrallbot": classreagents.Offer(rows=vendors, sold=frozenset({ANKH}))
            },
            spell_reagents=dbc,
        )
        steps = [s for s in plan_empty.steps if s.action == classreagents.ACTION]
        self.assertEqual(1, len(steps))
        step = steps[0]
        self.assertEqual("Thrallbot", step.holder)
        self.assertIn("walk-to-vendor item:%d" % ANKH, step.walk.command)
        buy_cmds = [r.command for r in step.rows if r.kind == "buy"]
        self.assertEqual(["entry:%d count:5 max:10000" % ANKH], buy_cmds)

        shaman_five = _shaman(carried=(_reagent_stack(1, ANKH, 5),))
        plan_five = guildjobs.plan(
            [shaman_five],
            class_reagents={
                "Thrallbot": classreagents.Offer(rows=vendors, sold=frozenset({ANKH}))
            },
            spell_reagents=dbc,
        )
        self.assertEqual(
            [],
            [s for s in plan_five.steps if s.action == classreagents.ACTION],
        )

    def test_shaman_carrying_one_ankh_tops_up_to_small_stock(self):
        import classreagents

        dbc = classreagents.parse_spell_dbc(
            _make_spell_dbc([(REINCARNATION, ((ANKH, 1),))])
        )
        shaman = _shaman(carried=(_reagent_stack(1, ANKH, 1),))
        vendors = [_vendor_row(ANKH, item_name="Ankh", price=2000)]
        buys, why = classreagents.plan(
            shaman, dbc, vendors, sold_entries=frozenset({ANKH}), room=0
        )
        self.assertEqual("", why)
        self.assertEqual(1, len(buys))
        self.assertEqual(ANKH, buys[0].entry)
        self.assertEqual(4, buys[0].count)

    def test_runtime_spell_dbc_and_sql_overlay_with_no_hardcoded_table(self):
        import classreagents

        custom_spell = 99001
        custom_reagent = 99002
        blob = _make_spell_dbc(
            [
                (REINCARNATION, ((ANKH, 1), (-1, 1))),
                (FIRST_AID_SPELL, ((2589, 1),)),
            ]
        )
        from_dbc = classreagents.parse_spell_dbc(blob)
        self.assertEqual(((ANKH, 1),), from_dbc[REINCARNATION])

        sql_rows = [
            {
                "spell_id": custom_spell,
                "Reagent_1": custom_reagent,
                "ReagentCount_1": 2,
                "Reagent_2": 0,
                "ReagentCount_2": 0,
            }
        ]
        from_sql = classreagents.spell_reagents_from_rows(sql_rows)
        merged = classreagents.merge_spell_reagents(
            from_dbc, from_sql, excluded=classreagents.craft_spells()
        )
        self.assertIn(custom_spell, merged)
        self.assertNotIn(FIRST_AID_SPELL, merged)

        bot = _shaman(known=frozenset({custom_spell, FIRST_AID_SPELL}))
        need = classreagents.wanted(bot, merged)
        self.assertEqual({custom_reagent: classreagents.TARGET_STOCK}, need)

    def test_purse_order_sits_behind_riding_and_food_and_keeps_spell_reserve(self):
        import classreagents

        self.assertEqual(
            (purse.SPELLS, purse.RIDING, purse.FOOD, purse.REAGENTS, purse.GEAR),
            purse.ORDER,
        )
        # Level 25, 10g purse, 3g 76s class spells, 4g riding: 2g 24s left for reagents and gear.
        o = purse.order("Bonk", 25, 100000, 37600, 9, 0)
        self.assertEqual(100000 - 37600 - 40000, o.spendable(purse.REAGENTS))
        self.assertEqual(
            [purse.SPELLS, purse.RIDING, purse.FOOD, purse.REAGENTS, purse.GEAR],
            [w.kind for w in o.wants],
        )

        # Hold only spells reserve + 10s: cannot spend below spells reserve.
        dbc = classreagents.parse_spell_dbc(
            _make_spell_dbc([(REINCARNATION, ((ANKH, 1),))])
        )
        broke_order = purse.order("Thrallbot", 60, 51000, 50000, 4, 300)
        broke_shaman = _shaman(money=51000, purse=broke_order)
        vendors = [_vendor_row(ANKH, item_name="Ankh", price=2000)]
        step, why = guildjobs.class_reagents_step(
            broke_shaman,
            classreagents.Offer(rows=vendors, sold=frozenset({ANKH})),
            cap=400,
            spell_reagents=dbc,
        )
        self.assertIsNone(step)
        self.assertIn("afford", why.lower())

        # Hungry / food ahead of class reagents, and riding ahead of class reagents;
        # class reagents ahead of gear.
        food_vendor = [
            {
                "vendor": 3333,
                "vendor_name": "Zlag",
                "map_id": 1,
                "yards": 40.0,
                "entry": 4606,
                "item_name": "Bread",
                "price": 100,
                "buy_count": 5,
                "required_level": 15,
                "category": restsupply.FOOD_CATEGORY,
                "enemy_group": 2,
            }
        ]
        # Non-hungry but low food (2 < 5): food comes BEFORE class reagents.
        low_food_shaman = _shaman(food=2, drink=20)
        plan_food_first = guildjobs.plan(
            [low_food_shaman],
            supply={"Thrallbot": food_vendor},
            class_reagents={
                "Thrallbot": classreagents.Offer(rows=vendors, sold=frozenset({ANKH}))
            },
            spell_reagents=dbc,
        )
        self.assertEqual([restsupply.ACTION], [s.action for s in plan_food_first.steps])

        # With riding owed at level 40, riding comes BEFORE class reagents.
        untrained_rider = _shaman(
            level=40,
            money=2000000,
            skills={purse.RIDING_SKILL: (75, 75)},
            purse=purse.order("Thrallbot", 40, 2000000, 0, 0, 75),
            skills_read=True,
        )
        plan_riding_first = guildjobs.plan(
            [untrained_rider],
            class_reagents={
                "Thrallbot": classreagents.Offer(rows=vendors, sold=frozenset({ANKH}))
            },
            spell_reagents=dbc,
        )
        self.assertEqual(
            [guildjobs.RIDING_ACTION], [s.action for s in plan_riding_first.steps]
        )

        # With riding satisfied and food stocked, class reagents come BEFORE vendor gear.
        gear_offer = (
            dict(
                name="Thrallbot",
                class_id=7,
                level=60,
                purse=100000,
                equipped={},
                equipped_slots=(),
            ),
            [
                {
                    "vendor": 3333,
                    "vendor_name": "Zlag",
                    "name": "Test Mail",
                    "map_id": 1,
                    "yards": 40.0,
                    "entry": 12345,
                    "item_name": "Test Mail",
                    "price": 500,
                    "quality": 2,
                    "item_class": 4,
                    "subclass": 3,
                    "inventory_type": 9,
                    "required_level": 50,
                    "item_level": 55,
                    "enemy_group": 2,
                }
            ],
        )
        plan_before_gear = guildjobs.plan(
            [shaman_empty := _shaman()],
            gear={"Thrallbot": gear_offer},
            class_reagents={
                "Thrallbot": classreagents.Offer(rows=vendors, sold=frozenset({ANKH}))
            },
            spell_reagents=dbc,
        )
        self.assertEqual(
            [classreagents.ACTION], [s.action for s in plan_before_gear.steps]
        )
        self.assertEqual("Thrallbot", shaman_empty.name)

    def test_unvendored_reagent_like_soul_shard_is_skipped_with_reason(self):
        import classreagents

        dbc = classreagents.parse_spell_dbc(
            _make_spell_dbc(
                [
                    (SOUL_FIRE, ((SOUL_SHARD, 1),)),
                    (INFERNAL_SPELL, ((INFERNAL_STONE, 1),)),
                ]
            )
        )
        warlock_shard_only = _shaman(
            name="Guldanbot",
            class_id=9,
            known=frozenset({SOUL_FIRE}),
        )
        buys, why = classreagents.plan(
            warlock_shard_only,
            dbc,
            [],
            sold_entries=frozenset({ANKH, INFERNAL_STONE}),
            room=10,
        )
        self.assertEqual((), buys)
        self.assertIn("6265", why)
        self.assertIn("no vendor", why.lower())

        warlock_mixed = _shaman(
            name="Guldanbot",
            class_id=9,
            known=frozenset({SOUL_FIRE, INFERNAL_SPELL}),
        )
        step, note = guildjobs.class_reagents_step(
            warlock_mixed,
            classreagents.Offer(
                rows=[
                    _vendor_row(INFERNAL_STONE, item_name="Infernal Stone", price=1000)
                ],
                sold=frozenset({INFERNAL_STONE}),
            ),
            cap=400,
            spell_reagents=dbc,
        )
        self.assertIsNotNone(step)
        self.assertEqual(
            [INFERNAL_STONE],
            [
                int(r.command.split()[0].split(":")[1])
                for r in step.rows
                if r.kind == "buy"
            ],
        )
        self.assertIn("6265", note)

    def test_buy_count_stack_hostile_vendor_cooldown_and_vendorsale_protection(self):
        import classreagents

        dbc = classreagents.parse_spell_dbc(
            _make_spell_dbc(
                [
                    (GREATER_KINGS, ((SYMBOL_OF_KINGS, 1),)),
                    (WATER_WALKING, ((FISH_OIL, 1),)),
                ]
            )
        )
        paladin = _shaman(
            name="Utherbot",
            class_id=2,
            race=1,  # Alliance
            known=frozenset({GREATER_KINGS}),
        )
        # Nearest vendor is Horde-only (enemy_group=2, hostile to Alliance), second is friendly (enemy_group=4), buy_count=20.
        vendors = [
            _vendor_row(
                SYMBOL_OF_KINGS,
                vendor=1,
                item_name="Symbol of Kings",
                price=50000,
                buy_count=20,
                yards=10.0,
                enemy_group=2,
            ),
            _vendor_row(
                SYMBOL_OF_KINGS,
                vendor=2,
                item_name="Symbol of Kings",
                price=50000,
                buy_count=20,
                yards=80.0,
                enemy_group=4,
            ),
        ]
        buys, _ = classreagents.plan(
            paladin, dbc, vendors, sold_entries=frozenset({SYMBOL_OF_KINGS}), room=5
        )
        self.assertEqual(1, len(buys))
        self.assertEqual(2, buys[0].vendor)
        self.assertEqual(1, buys[0].count)
        self.assertEqual(20, buys[0].units)

        # Cooldown blocks repeat within 60 minutes.
        recent = [
            guildjobs.Recent(
                "Utherbot",
                classreagents.ACTION,
                10,
                "applied",
                None,
                False,
            )
        ]
        cooled_plan = guildjobs.plan(
            [paladin],
            recent=recent,
            class_reagents={
                "Utherbot": classreagents.Offer(
                    rows=vendors, sold=frozenset({SYMBOL_OF_KINGS})
                )
            },
            spell_reagents=dbc,
        )
        self.assertEqual(
            [], [s for s in cooled_plan.steps if s.action == classreagents.ACTION]
        )

        # vendorsale never sells Fish Oil (class=7 TRADE_GOODS) when member knows Water Walking.
        shaman_ww = _shaman(
            known=frozenset({WATER_WALKING}),
            reagent_entries=classreagents.entries_for_known(
                frozenset({WATER_WALKING}), dbc
            ),
            carried=(
                _reagent_stack(
                    10,
                    FISH_OIL,
                    5,
                    item_class=guildjobs.TRADE_GOODS,
                    subclass=0,
                    price=25,
                ),
            ),
        )
        self.assertEqual([], guildjobs.vendor_stacks(shaman_ww, keep.Reservations()))

    def test_bridge_class_reagent_wiring_and_sold_check(self):
        import classreagents

        bridge = _load_bridge()
        dbc = classreagents.parse_spell_dbc(
            _make_spell_dbc(
                [
                    (REINCARNATION, ((ANKH, 1),)),
                    (SOUL_FIRE, ((SOUL_SHARD, 1),)),
                ]
            )
        )
        shaman = _shaman()
        warlock = _shaman(name="Lockbot", class_id=9, known=frozenset({SOUL_FIRE}))
        client = object.__new__(bridge.Bridge)
        client._class_reagent_read_offset = 0

        with (
            mock.patch.object(
                bridge, "_fetch_sold_reagent_entries", return_value=frozenset({ANKH})
            ),
            mock.patch.object(
                bridge,
                "_fetch_class_reagent_vendors",
                return_value=[_vendor_row(ANKH, item_name="Ankh", price=2000)],
            ) as vendor_mock,
        ):
            offers = self._run_async(
                client._job_class_reagent_offers([shaman, warlock], (), dbc)
            )

        self.assertEqual(1, vendor_mock.call_count)
        self.assertEqual(1, len(offers["Thrallbot"].rows))
        self.assertEqual((), offers["Lockbot"].rows)
        self.assertEqual(frozenset({ANKH}), offers["Lockbot"].sold)

    @staticmethod
    def _run_async(coro):
        import asyncio

        return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
