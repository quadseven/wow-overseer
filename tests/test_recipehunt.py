"""Vendor recipes and Cenarion / Timbermaw reputation turn-ins (#2423)."""

from __future__ import annotations

import asyncio
import json
import pathlib
import unittest
from unittest import mock

import bridge
import guildcorps
import guildjobs
import recipehunt


CRAFTBOOK = json.loads(
    (pathlib.Path(__file__).resolve().parents[1] / "craftbook.json").read_text(
        encoding="utf-8"
    )
)


ALLIANCE_RACE = 1  # Human
HORDE_RACE = 2  # Orc
EK = 0
KALIMDOR = 1


def _crafter(name="Og", **over):
    base = dict(
        name=name,
        guild="Cave",
        level=60,
        race=HORDE_RACE,
        map_id=KALIMDOR,
        alchemy=0,
        enchanting=0,
        learned=frozenset(),
        held=(),
        item_counts=(),
        in_log=frozenset(),
        rewarded=frozenset(),
        standing=(),
        money=100_000,
        free_slots=4,
        stocks=frozenset(),
    )
    base.update(over)
    return recipehunt.Crafter(**base)


class CatalogTest(unittest.TestCase):
    def test_all_seven_vendor_recipes_match_craftbook_and_gates(self):
        self.assertEqual(7, len(recipehunt.VENDOR_RECIPES))
        by_item = {r.item_entry: r for r in recipehunt.VENDOR_RECIPES}
        expected = {
            6055: (171, 165, 7257, 1500, None, 0),
            13478: (171, 265, 17554, 13000, None, 0),
            13501: (171, 295, 17580, 30000, None, 0),
            16221: (333, 275, 20026, 16000, None, 0),
            16224: (333, 285, 20015, 20000, None, 0),
            19445: (333, 290, 23800, 30000, recipehunt.FACTION_TIMBERMAW, 9000),
            20732: (333, 300, 25081, 40000, recipehunt.FACTION_CENARION, 3000),
        }
        self.assertEqual(set(expected), set(by_item))
        for item_entry, (
            skill,
            rank,
            spell,
            price,
            faction,
            target,
        ) in expected.items():
            recipe = by_item[item_entry]
            self.assertEqual(skill, recipe.skill_id)
            self.assertEqual(rank, recipe.skill_rank)
            self.assertEqual(spell, recipe.spell_id)
            self.assertEqual(price, recipe.price)
            self.assertEqual(faction, recipe.rep_faction)
            self.assertEqual(target, recipe.rep_standing)
            self.assertIn(str(spell), CRAFTBOOK[str(skill)])


class EffectiveStandingTest(unittest.TestCase):
    def test_timbermaw_starts_at_hostile_base_and_cenarion_starts_neutral(self):
        self.assertEqual(
            0, recipehunt.effective_standing(recipehunt.FACTION_CENARION, 0)
        )
        self.assertEqual(
            3000, recipehunt.effective_standing(recipehunt.FACTION_CENARION, 3000)
        )
        self.assertEqual(
            -3500, recipehunt.effective_standing(recipehunt.FACTION_TIMBERMAW, 0)
        )
        self.assertEqual(
            -2515, recipehunt.effective_standing(recipehunt.FACTION_TIMBERMAW, 985)
        )
        self.assertEqual(
            9000, recipehunt.effective_standing(recipehunt.FACTION_TIMBERMAW, 12500)
        )


class FamilyPlannerTest(unittest.TestCase):
    def test_learns_carried_recipe_before_buying_anything(self):
        c = _crafter(
            "Ugga",
            alchemy=300,
            enchanting=0,
            held=((13501, 9001),),
            stocks=frozenset({13501, 13478}),
        )
        turn = recipehunt.plan_family_crafter(c)
        self.assertIsNotNone(turn.errand)
        self.assertEqual("cast", turn.errand.kind)
        self.assertEqual("use guid:9001", turn.errand.command)

    def test_enforces_gold_floor_without_granting_gold(self):
        floor = guildjobs.recipe_purse_floor(60)
        c_short = _crafter(
            "Oz",
            enchanting=275,
            map_id=KALIMDOR,
            money=16000 + floor - 1,
            stocks=frozenset({16221}),
        )
        turn_short = recipehunt.plan_family_crafter(c_short)
        self.assertIsNone(turn_short.errand)
        self.assertIn("gold", turn_short.note)
        c_ok = _crafter(
            "Oz",
            enchanting=275,
            map_id=KALIMDOR,
            money=16000 + floor,
            stocks=frozenset({16221}),
        )
        turn_ok = recipehunt.plan_family_crafter(c_ok)
        self.assertIsNotNone(turn_ok.errand)
        self.assertEqual("buy", turn_ok.errand.kind)
        self.assertEqual("entry:16221 count:1 max:16000", turn_ok.errand.command)

    def test_checks_bag_slot_and_walk_when_vendor_not_in_reach(self):
        c_walk = _crafter("Oz", enchanting=275, map_id=KALIMDOR, stocks=frozenset())
        turn_walk = recipehunt.plan_family_crafter(c_walk)
        self.assertIsNone(turn_walk.errand)
        self.assertEqual(16221, turn_walk.walk_vendor_item)
        c_full = _crafter(
            "Oz",
            enchanting=275,
            map_id=KALIMDOR,
            free_slots=0,
            stocks=frozenset({16221}),
        )
        turn_full = recipehunt.plan_family_crafter(c_full)
        self.assertIsNone(turn_full.errand)
        self.assertIn("bag slot", turn_full.note)

    def test_uses_faction_specific_vendors_for_elixir_of_superior_defense(self):
        known = frozenset({7257})
        c_horde = _crafter(
            "Ugga",
            race=HORDE_RACE,
            alchemy=265,
            learned=known,
            map_id=EK,
            stocks=frozenset(),
        )
        t_horde = recipehunt.plan_family_crafter(c_horde)
        self.assertEqual(0, t_horde.walk_vendor_item)
        self.assertIn("map", t_horde.note)
        c_ally = _crafter(
            "GrugAlch",
            race=ALLIANCE_RACE,
            alchemy=265,
            learned=known,
            map_id=EK,
            stocks=frozenset(),
        )
        t_ally = recipehunt.plan_family_crafter(c_ally)
        self.assertEqual(13478, t_ally.walk_vendor_item)

    def test_cenarion_reputation_drives_8318_then_8319_then_buys_20732(self):
        # Need 20732: skill 300, holds 10 Twilight Texts, not Friendly yet.
        # First turn-in is 8318 when 8318 is not rewarded yet.
        known = frozenset({20026, 20015})
        c_first = _crafter(
            "Og",
            enchanting=300,
            learned=known,
            standing=((recipehunt.FACTION_CENARION, 500),),
            item_counts=((20404, 10),),
        )
        t_take = recipehunt.plan_family_crafter(c_first, nearby_spawns={15306: 91001})
        self.assertIsNotNone(t_take.errand)
        self.assertEqual("quest", t_take.errand.kind)
        self.assertEqual("take quest:8318", t_take.errand.command)
        # In quest log -> turnin quest:8318
        c_turnin = _crafter(
            "Og",
            enchanting=300,
            learned=known,
            standing=((recipehunt.FACTION_CENARION, 500),),
            item_counts=((20404, 10),),
            in_log=frozenset({8318}),
        )
        t_done = recipehunt.plan_family_crafter(c_turnin, nearby_spawns={15306: 91001})
        self.assertEqual("turnin quest:8318", t_done.errand.command)
        # Once 8318 is rewarded -> uses repeatable 8319
        c_rep = _crafter(
            "Og",
            enchanting=300,
            learned=known,
            standing=((recipehunt.FACTION_CENARION, 1500),),
            item_counts=((20404, 10),),
            rewarded=frozenset({8318}),
        )
        t_rep = recipehunt.plan_family_crafter(c_rep, nearby_spawns={15306: 91001})
        self.assertEqual("take quest:8319", t_rep.errand.command)
        # Far from Bor Wildmane -> walk to NPC 15306, no quest row yet
        t_far = recipehunt.plan_family_crafter(c_rep, nearby_spawns={})
        self.assertIsNone(t_far.errand)
        self.assertEqual(15306, t_far.walk_npc_entry)
        # Once Friendly (3000) -> buys 20732
        c_friendly = _crafter(
            "Og",
            enchanting=300,
            learned=known,
            standing=((recipehunt.FACTION_CENARION, 3000),),
            item_counts=((20404, 10),),
            stocks=frozenset({20732}),
        )
        t_buy = recipehunt.plan_family_crafter(c_friendly)
        self.assertEqual("entry:20732 count:1 max:40000", t_buy.errand.command)

    def test_timbermaw_honored_gate_and_turnins(self):
        known = frozenset({20026, 20015, 25081})
        c_unhonored = _crafter(
            "Og",
            enchanting=290,
            learned=known,
            standing=((recipehunt.FACTION_TIMBERMAW, 985),),
            item_counts=((21377, 5),),
            rewarded=frozenset({8460}),
        )
        t_rep = recipehunt.plan_family_crafter(
            c_unhonored, nearby_spawns={11554: 92001}
        )
        self.assertEqual("take quest:8466", t_rep.errand.command)
        # Without prerequisite 8460 rewarded, does not emit broken take quest:8466
        c_locked = _crafter(
            "Og",
            enchanting=290,
            learned=known,
            standing=((recipehunt.FACTION_TIMBERMAW, 985),),
            item_counts=((21377, 5),),
            rewarded=frozenset(),
        )
        t_locked = recipehunt.plan_family_crafter(
            c_locked, nearby_spawns={11554: 92001}
        )
        self.assertIsNone(t_locked.errand)
        self.assertIn("prerequisite", t_locked.note)
        # At Honored (raw 12500 -> effective 9000) -> buys 19445
        c_honored = _crafter(
            "Og",
            enchanting=290,
            learned=known,
            standing=((recipehunt.FACTION_TIMBERMAW, 12500),),
            stocks=frozenset({19445}),
        )
        t_buy = recipehunt.plan_family_crafter(c_honored)
        self.assertEqual("entry:19445 count:1 max:30000", t_buy.errand.command)

    def test_blocked_command_is_skipped(self):
        c = _crafter("Oz", enchanting=275, map_id=KALIMDOR, stocks=frozenset({16221}))
        turn = recipehunt.plan_family_crafter(
            c,
            blocked=frozenset({("Oz", "entry:16221 count:1 max:16000")}),
        )
        self.assertIsNone(turn.errand)
        self.assertIn("pending", turn.note)


class GuildStepPlannerTest(unittest.TestCase):
    def test_plans_corps_step_with_walk_to_vendor_and_buy(self):
        c = _crafter(
            "Scribe", guild="HordeCorp", alchemy=295, map_id=EK, stocks=frozenset()
        )
        step = recipehunt.plan_corps_step(c)
        self.assertIsInstance(step, guildcorps.Step)
        self.assertEqual("Scribe", step.holder)
        self.assertEqual("job", step.walk.kind)
        self.assertIn("walk-to-vendor item:13501", step.walk.command)
        self.assertEqual("buy", step.rows[0].kind)
        self.assertEqual("entry:13501 count:1 max:30000", step.rows[0].command)

    def test_plans_corps_step_for_reputation_turnin_with_walk_to_spawn(self):
        known = frozenset({20026, 20015})
        c = _crafter(
            "Ench",
            guild="AllyCorp",
            enchanting=300,
            learned=known,
            map_id=KALIMDOR,
            standing=((recipehunt.FACTION_CENARION, 100),),
            item_counts=((20404, 10),),
        )
        step = recipehunt.plan_corps_step(c, npc_spawns={15306: 77701})
        self.assertIsNotNone(step)
        self.assertEqual("job", step.walk.kind)
        self.assertIn("walk-to-spawn creature:77701", step.walk.command)
        self.assertEqual(
            ["take quest:8318", "turnin quest:8318"], [r.command for r in step.rows]
        )
        for row in step.rows:
            self.assertEqual("quest", row.kind)

    def test_guild_step_never_triggers_for_family_member_when_filtered_or_busy(self):
        c = _crafter(
            "Ench",
            guild="AllyCorp",
            enchanting=300,
            learned=frozenset({20026, 20015}),
            map_id=KALIMDOR,
        )
        steps, _notes = recipehunt.plan_guild_steps([c], busy={"Ench"}, recent=set())
        self.assertEqual([], steps)


class BridgeWiringTest(unittest.IsolatedAsyncioTestCase):
    def _bridge(self):
        br = bridge.Bridge.__new__(bridge.Bridge)
        br._corps_steps = {}
        br._mail_walk_tasks = set()
        br._mail_walk_task_done = lambda _t: None
        return br

    async def test_family_recipe_hunt_refuses_when_blocked_table_unread(self):
        br = self._bridge()
        written = []
        with (
            mock.patch.object(
                bridge, "_fetch_purses", return_value={"Oz": (60, 100_000)}
            ),
            mock.patch.object(
                bridge, "_fetch_recipehunt_skills", return_value={"Oz": {333: 275}}
            ),
            mock.patch.object(bridge, "_fetch_crafter_known", return_value=[]),
            mock.patch.object(
                bridge,
                "_fetch_recipehunt_facts",
                return_value={
                    "Oz": {
                        "race": HORDE_RACE,
                        "map_id": KALIMDOR,
                        "free_slots": 4,
                        "held": (),
                        "item_counts": (),
                        "rewarded": frozenset(),
                    }
                },
            ),
            mock.patch.object(bridge, "_fetch_standing", return_value={}),
            mock.patch.object(bridge, "_fetch_quest_log", return_value=set()),
            mock.patch.object(bridge, "_fetch_positions", return_value={}),
            mock.patch.object(bridge, "_fetch_recipehunt_npc_spawns", return_value={}),
            mock.patch.object(
                bridge, "_fetch_town", return_value=mock.Mock(stocks={16221})
            ),
            mock.patch.object(bridge, "_recipehunt_rows_blocked", return_value=None),
            mock.patch.object(
                bridge,
                "_insert_recipehunt_errand",
                side_effect=lambda e: written.append(e) or 1,
            ),
        ):
            queued = await br._recipe_hunt_once(["Oz"])
        self.assertEqual(0, queued)
        self.assertEqual([], written)

    async def test_family_recipe_hunt_queues_buy_with_own_gold_and_floor(self):
        br = self._bridge()
        written = []
        with (
            mock.patch.object(
                bridge, "_fetch_purses", return_value={"Oz": (60, 100_000)}
            ),
            mock.patch.object(
                bridge, "_fetch_recipehunt_skills", return_value={"Oz": {333: 275}}
            ),
            mock.patch.object(bridge, "_fetch_crafter_known", return_value=[]),
            mock.patch.object(
                bridge,
                "_fetch_recipehunt_facts",
                return_value={
                    "Oz": {
                        "race": HORDE_RACE,
                        "map_id": KALIMDOR,
                        "free_slots": 4,
                        "held": (),
                        "item_counts": (),
                        "rewarded": frozenset(),
                    }
                },
            ),
            mock.patch.object(bridge, "_fetch_standing", return_value={}),
            mock.patch.object(bridge, "_fetch_quest_log", return_value=set()),
            mock.patch.object(bridge, "_fetch_positions", return_value={}),
            mock.patch.object(bridge, "_fetch_recipehunt_npc_spawns", return_value={}),
            mock.patch.object(
                bridge, "_fetch_town", return_value=mock.Mock(stocks={16221})
            ),
            mock.patch.object(bridge, "_recipehunt_rows_blocked", return_value=set()),
            mock.patch.object(
                bridge,
                "_insert_recipehunt_errand",
                side_effect=lambda e: written.append(e) or 1,
            ),
        ):
            queued = await br._recipe_hunt_once(["Oz"])
        self.assertEqual(1, queued)
        self.assertEqual("buy", written[0].kind)
        self.assertEqual("entry:16221 count:1 max:16000", written[0].command)

    async def test_guild_recipe_hunt_starts_step_and_respects_purse_floor(self):
        br = self._bridge()
        started = []

        async def run_step(step, _cap):
            started.append(step)

        br._run_corps_step = run_step
        poor = guildcorps.Member(
            name="EnchPoor",
            guild="AllyCorp",
            class_id=8,
            level=60,
            online=True,
            map_id=KALIMDOR,
            maintenance=True,
            skills={333: (275, 300)},
            race=ALLIANCE_RACE,
            money=guildjobs.recipe_purse_floor(60) + 16000 - 1,
        )
        rich = guildcorps.Member(
            name="EnchRich",
            guild="HordeCorp",
            class_id=8,
            level=60,
            online=True,
            map_id=KALIMDOR,
            maintenance=True,
            skills={333: (275, 300)},
            race=HORDE_RACE,
            money=guildjobs.recipe_purse_floor(60) + 16000,
        )
        facts = {"members": [poor, rich], "vendors": {KALIMDOR: frozenset({16221})}}
        extra = {
            "facts": {
                "EnchPoor": {
                    "free_slots": 4,
                    "item_counts": (),
                    "rewarded": frozenset(),
                },
                "EnchRich": {
                    "free_slots": 4,
                    "item_counts": (),
                    "rewarded": frozenset(),
                },
            },
            "known": {},
            "in_log": {},
            "tm": {},
            "cc": {},
            "recent": set(),
            "spawns": {},
        }
        with mock.patch.object(
            bridge, "_fetch_guild_recipehunt_facts", return_value=extra
        ):
            count = await br._guild_recipe_hunt_once(facts, set(), 600.0)
            await asyncio.sleep(0)
        self.assertEqual(1, count)
        self.assertEqual(["EnchRich"], [s.holder for s in started])
        self.assertEqual("entry:16221 count:1 max:16000", started[0].rows[0].command)
