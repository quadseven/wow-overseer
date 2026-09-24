"""The pre-raid plan, and the planner and Jev choosing dungeons by it (#280).

What the operator asked for: the level 60 family gears for Molten Core the way
a raid guild does, with the next dungeon chosen by the upgrades it holds for
each member, the attunement and the key picked up on the way, and the plan
shown on the Raid tab as next upgrades and where they drop. The family here is
the dev realm's as read on 2026-09-23: five at level 60 on Kalimdor, a
protection warrior, a retribution paladin, a combat rogue, a frost mage and a
holy priest. Every test runs on fake rows; none touches a database.
"""

import asyncio
import pathlib
import unittest
from dataclasses import replace

import campaignplan
import jev
import jev_choices
import preraid
import raidready
from test_jev_items import FakeJev

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")

KALIMDOR = 1
TEXTS = {
    7598: "Increases your critical strike rating by 28.",
    15465: "Increases your hit rating by 20.",
    18056: "Increases spell power by 40.",
    99001: "Increases frost spell power by 30.",
}


def item_row(entry, name, level, inv, cls=4, sub=4, **kw):
    row = {
        "entry": entry,
        "name": name,
        "item_level": level,
        "quality": 3,
        "inventory_type": inv,
        "item_class": cls,
        "subclass": sub,
        "allowable_class": -1,
        "required_level": min(level - 5, 60),
        "armor": 0,
        "block": 0,
        "dmg_min1": 0,
        "dmg_max1": 0,
        "delay": 0,
    }
    for i in range(1, 11):
        row["stat_type%d" % i] = 0
        row["stat_value%d" % i] = 0
    for i in range(1, 6):
        row["spellid_%d" % i] = 0
        row["spelltrigger_%d" % i] = 0
    for i, (kind, value) in enumerate(kw.pop("stats", ()), start=1):
        row["stat_type%d" % i] = kind
        row["stat_value%d" % i] = value
    for i, spell in enumerate(kw.pop("spells", ()), start=1):
        row["spellid_%d" % i] = spell
        row["spelltrigger_%d" % i] = 1
    row.update(kw)
    return row


STA, STR, AGI, INT, SPI, DEF = 7, 4, 3, 5, 6, 12

# What the family wears, one slot each where it matters here.
WORN = {
    "Grug": [item_row(1, "Jouster's Chestplate", 42, 5, stats=((STA, 8), (STR, 6)))],
    "Ugga": [item_row(2, "Resilient Tunic", 33, 5, sub=2, stats=((INT, 5),))],
    "Og": [item_row(3, "Mystic's Robe", 23, 20, sub=1, stats=((INT, 4),))],
}

CLASSES = {"Grug": (1, 2, 1), "Ugga": (5, 1, 1), "Og": (8, 2, 1)}


def member_rows(level=60, map_id=KALIMDOR):
    return [
        {
            "name": n,
            "class_id": c,
            "level": level,
            "race": r,
            "map_id": map_id,
            "lead": int(n == "Grug"),
            "spec_tab": t,
        }
        for n, (c, t, r) in CLASSES.items()
    ]


def worn_rows():
    out = []
    for name, pieces in WORN.items():
        for piece in pieces:
            out.append(dict(piece, member=name, slot=4))
    return out


def drop(item, source, map_id, chance=20, grp=0, **kw):
    row = {
        "kind": preraid.DROP,
        "source": source,
        "map_id": map_id,
        "name": kw.pop("name", "Boss %d" % source),
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "item": item,
        "chance": chance,
        "grp": grp,
        "rolls": 1,
        "outer_chance": 100,
        "group_zero": 0,
        "group_explicit": 0,
    }
    row.update(kw)
    return row


# Kromcrush's Chestplate in Dire Maul North (Captain Kromcrush, 14325), a
# priest's robe in Dire Maul West (Immol'thar, 11496), a plate chest in the
# Upper Spire (General Drakkisath, 10363), a mail chest nobody here wears.
ITEMS = [
    item_row(101, "Kromcrush's Chestplate", 62, 5, stats=((STA, 20), (DEF, 10))),
    item_row(102, "Robe of Everlasting Night", 62, 20, sub=1, spells=(18056,)),
    item_row(103, "Breastplate of Valor", 63, 5, stats=((STA, 25), (DEF, 14))),
    item_row(104, "Battleforge Chain", 60, 5, sub=3, stats=((STA, 40),)),
    item_row(105, "Horde Trinket", 63, 12, sub=0, stats=((STA, 30),)),
]
DROPS = [
    drop(101, 14325, 429, 25, name="Captain Kromcrush"),
    drop(102, 11496, 429, 20, name="Immol'thar"),
    drop(103, 10363, 229, 11, name="General Drakkisath"),
    drop(104, 14325, 429, 25, name="Captain Kromcrush"),
]
ANCHORS = [
    {"entry": 14325, "map_id": 429, "x": 0.0, "y": 0.0, "z": 0.0},
    {"entry": 11496, "map_id": 429, "x": 500.0, "y": 0.0, "z": 0.0},
    {"entry": 10363, "map_id": 229, "x": 0.0, "y": 0.0, "z": 100.0},
    {"entry": 9196, "map_id": 229, "x": 0.0, "y": 0.0, "z": -100.0},
]
# A Horde-only quest (race mask 2, orc) rewarding the trinket.
REWARDS = [
    dict(
        {c: 0 for c in preraid.REWARD_COLUMNS},
        quest=4974,
        title="For The Horde!",
        zone=1583,
        races=2,
        classes=0,
        RewardItem1=105,
    )
]


def catalog():
    return preraid.catalog(DROPS, ANCHORS, REWARDS, ITEMS, TEXTS)


def family():
    return preraid.members(member_rows(), worn_rows(), TEXTS)


class HowOftenItDrops(unittest.TestCase):
    def test_an_ungrouped_row_is_its_own_chance(self):
        self.assertEqual(preraid.chance({"chance": 20, "outer_chance": 100}), 20)

    def test_a_grouped_row_with_no_chance_shares_what_is_left(self):
        row = {
            "chance": 0,
            "grp": 1,
            "group_zero": 4,
            "group_explicit": 20,
            "outer_chance": 100,
        }
        self.assertEqual(preraid.chance(row), 20.0)

    def test_a_reference_multiplies_by_its_chance_and_rolls(self):
        # Emperor Thaurissan: reference 35014 at 100%, two rolls, one of
        # eleven items with one explicit 1%.
        row = {
            "chance": 0,
            "grp": 1,
            "group_zero": 10,
            "group_explicit": 1,
            "outer_chance": 100,
            "rolls": 2,
        }
        self.assertAlmostEqual(preraid.chance(row), 19.8)

    def test_a_world_drop_under_the_floor_is_no_source(self):
        rare = [drop(101, 14325, 429, 0.5)]
        self.assertEqual(preraid.sources(rare, ANCHORS, []), {})


class WhereItDrops(unittest.TestCase):
    def test_a_wing_boss_is_its_wing(self):
        place = preraid.placer(ANCHORS)
        self.assertEqual(place(429, 14325, 0, 0, 0), "dire-maul-north")
        self.assertEqual(place(229, 10363, 0, 0, 0), preraid.UPPER_SPIRE)

    def test_anything_else_on_a_wing_map_is_the_nearest_boss_wing(self):
        place = preraid.placer(ANCHORS)
        self.assertEqual(place(429, 1, 480, 10, 0), "dire-maul-west-north")
        self.assertEqual(place(229, 1, 0, 0, -90), "lower-blackrock-spire")

    def test_a_one_wing_map_is_its_door(self):
        place = preraid.placer([])
        self.assertEqual(place(230, 9019, 0, 0, 0), "blackrock-depths")

    def test_a_quest_reward_is_credited_to_its_dungeon_and_its_faction(self):
        found = catalog()
        [source] = found[105].sources
        self.assertEqual(source.place, "blackrock-spire-quests")
        self.assertFalse(source.allows(1, 1))  # a human warrior
        self.assertTrue(source.allows(2, 1))  # an orc warrior


class WhatAPieceIsWorth(unittest.TestCase):
    def test_equip_spells_count_as_stats(self):
        piece = preraid.item(
            item_row(9, "Lionheart", 61, 1, spells=(7598, 15465)), TEXTS
        )
        self.assertEqual(dict(piece.stats), {"crit": 28, "hit": 20})

    def test_a_school_counts_only_for_the_spec_that_casts_it(self):
        robe = preraid.item(
            item_row(9, "Frost robe", 60, 20, sub=1, spells=(99001,)), TEXTS
        )
        by = {m.name: m for m in family()}
        og, ugga = by["Og"], by["Ugga"]
        self.assertGreater(preraid.score(robe, og), 0)
        self.assertEqual(preraid.score(robe, ugga), 0)

    def test_the_specs_are_the_roster_trees(self):
        by = {m.name: m for m in family()}
        self.assertEqual(by["Grug"].spec_name, "Protection Warrior")
        self.assertEqual(by["Grug"].role, preraid.TANK)
        self.assertEqual(by["Ugga"].role, preraid.HEALER)
        self.assertEqual(by["Og"].spec_name, "Frost Mage")


class WhoCanWearIt(unittest.TestCase):
    def setUp(self):
        self.by = {m.name: m for m in family()}
        self.found = catalog()

    def test_a_priest_never_gets_mail_or_plate(self):
        self.assertEqual(preraid.slots_for(self.found[104], self.by["Ugga"]), ())
        self.assertEqual(preraid.slots_for(self.found[101], self.by["Ugga"]), ())

    def test_a_warrior_at_60_takes_plate_and_not_mail(self):
        self.assertEqual(preraid.slots_for(self.found[101], self.by["Grug"]), (4,))
        self.assertEqual(preraid.slots_for(self.found[104], self.by["Grug"]), ())

    def test_a_tank_keeps_the_shield_and_a_caster_takes_a_wand(self):
        two_hander = preraid.item(item_row(9, "Axe", 60, 17, cls=2, sub=1))
        shield = preraid.item(item_row(10, "Shield", 60, 14, sub=6))
        wand = preraid.item(item_row(11, "Wand", 60, 26, cls=2, sub=19))
        self.assertEqual(preraid.slots_for(two_hander, self.by["Grug"]), ())
        self.assertEqual(preraid.slots_for(shield, self.by["Grug"]), (16,))
        self.assertEqual(preraid.slots_for(wand, self.by["Og"]), (17,))
        self.assertEqual(preraid.slots_for(wand, self.by["Grug"]), ())


class ThePlan(unittest.TestCase):
    def setUp(self):
        self.by = {m.name: m for m in family()}
        self.found = catalog()

    def test_the_target_is_the_best_anywhere_and_next_the_best_reachable(self):
        plan = preraid.plan(self.by["Grug"], self.found, {"dire-maul-north"})
        chest = next(s for s in plan.slots if s.slot == 4)
        self.assertEqual(chest.worn.name, "Jouster's Chestplate")
        self.assertEqual(chest.target.item.name, "Breastplate of Valor")
        self.assertEqual(chest.next.item.name, "Kromcrush's Chestplate")
        self.assertEqual(chest.next.levels, 20)

    def test_the_other_factions_quest_reward_is_not_a_target(self):
        plan = preraid.plan(self.by["Grug"], self.found, set(preraid.PLACES))
        self.assertNotIn(105, {u.item.entry for u in plan.upgrades})

    def test_a_run_is_worth_its_chance_times_the_item_levels(self):
        plans = [preraid.plan(m, self.found) for m in family()]
        gains = preraid.run_gains(plans)
        grug = next(g for g in gains["dire-maul-north"] if g.name == "Grug")
        self.assertEqual(grug.upgrades, 1)
        self.assertAlmostEqual(grug.levels, 0.25 * 20)
        ugga = next(g for g in gains["dire-maul-west-north"] if g.name == "Ugga")
        self.assertAlmostEqual(ugga.levels, 0.2 * (62 - 33))
        self.assertIn("Robe of Everlasting Night", ugga.best)

    def test_a_quest_reward_is_not_counted_every_run(self):
        horde = [replace(m, race=2) for m in family()]
        gains = preraid.run_gains([preraid.plan(m, self.found) for m in horde])
        self.assertTrue(all(g.upgrades == 0 for g in gains["lower-blackrock-spire"]))


class TheAttunementAndTheKey(unittest.TestCase):
    NAMES = ["Grug", "Ugga", "Og"]

    def test_nobody_holding_the_quest_is_needed_but_not_advanced(self):
        moved = preraid.progress(self.NAMES, [], [], [])["blackrock-depths"]
        self.assertTrue(moved.needed)
        self.assertEqual(moved.rank, 0)
        self.assertIn("Lothos Riftwaker", moved.line)

    def test_a_holder_without_a_fragment_makes_depths_the_attunement_run(self):
        held = [{"name": "Ugga", "quest": 7848, "status": 3}]
        moved = preraid.progress(self.NAMES, [], held, [])["blackrock-depths"]
        self.assertEqual(moved.rank, 2)
        self.assertIn("Ugga holds the quest", moved.line)

    def test_everyone_attuned_is_nothing_to_do(self):
        done = [{"name": n, "quest": 7848} for n in self.NAMES]
        self.assertFalse(
            preraid.progress(self.NAMES, done, [], [])["blackrock-depths"].needed
        )

    def test_the_key_pieces_drop_for_anybody_so_the_lower_spire_advances_it(self):
        items = [{"name": "Grug", "entry": 12336, "count": 1}]
        moved = preraid.progress(self.NAMES, [], [], items)["lower-blackrock-spire"]
        self.assertEqual(moved.rank, 1)
        self.assertIn("Grug holds 1 of the 4 pieces", moved.line)

    def test_a_seal_held_is_the_key_done(self):
        items = [{"name": "Og", "entry": preraid.SEAL_OF_ASCENSION, "count": 1}]
        moved = preraid.progress(self.NAMES, [], [], items)["lower-blackrock-spire"]
        self.assertFalse(moved.needed)


# The Crescent Key in a member's bags, which opens Dire Maul West and North.
CRESCENT = frozenset({18249})


def facts(upgrades=None, progress=None, done=None, keys=CRESCENT):
    return campaignplan.Facts(
        family="Grug",
        level_rows=tuple(
            {"name": n, "level": 60, "race": 1, "map_id": KALIMDOR, "lead": int(i == 0)}
            for i, n in enumerate(("Grug", "Ugga", "Grog", "Bork", "Og"))
        ),
        done=dict(done or {}),
        failed={},
        upgrades=upgrades,
        progress=progress,
        keys=keys,
    )


def gains(**levels):
    return {
        place: (preraid.Gain("Grug", 1, 0.2, value, "a chest"),)
        for place, value in levels.items()
    }


class ThePlannerGearsForTheRaid(unittest.TestCase):
    def test_at_the_cap_the_most_expected_upgrades_goes_first(self):
        opts = campaignplan.options(
            facts(gains(**{"dire-maul-north": 9.0, "dire-maul-east-east": 2.0}))
        )
        pick = campaignplan.heuristic(opts)
        self.assertEqual(pick.keyword, "dire-maul-north")
        self.assertEqual(pick.expected, 9.0)
        self.assertIn("most expected upgrades", campaignplan.heuristic_why(pick))

    def test_unread_gear_still_plans_by_the_round(self):
        pick = campaignplan.heuristic(campaignplan.options(facts()))
        self.assertEqual(pick.keyword, "dire-maul-east-east")
        self.assertIsNone(pick.expected)

    def test_a_run_done_to_its_round_makes_way(self):
        ups = gains(**{"dire-maul-north": 9.0, "dire-maul-east-east": 2.0})
        opts = campaignplan.options(facts(ups, done={"dire-maul-north": 10}))
        self.assertNotIn("dire-maul-north", [o.keyword for o in opts])
        self.assertEqual(campaignplan.heuristic(opts).keyword, "dire-maul-east-east")

    def test_raid_progress_beats_upgrades(self):
        ups = gains(**{"dire-maul-north": 9.0, "dire-maul-east-east": 2.0})
        moved = {
            "dire-maul-east-east": preraid.Progress(
                "dire-maul-east-east", preraid.KEY, True, True, "the key"
            )
        }
        pick = campaignplan.heuristic(campaignplan.options(facts(ups, moved)))
        self.assertEqual(pick.keyword, "dire-maul-east-east")
        self.assertEqual(pick.progress_rank, 1)
        self.assertIn("raid's progression", campaignplan.heuristic_why(pick))

    def test_a_crossing_halves_what_a_run_is_worth(self):
        opts = campaignplan.options(facts(gains(**{"dire-maul-north": 9.0})))
        self.assertEqual(len(opts), 3)  # the three Dire Maul wings
        self.assertEqual({o.continent for o in opts}, {"Kalimdor"})
        self.assertFalse(any(o.crossing for o in opts))
        north = next(o for o in opts if o.keyword == "dire-maul-north")
        self.assertEqual(north.value, 9.0)
        crossed = replace(north, crossing=True)
        self.assertEqual(crossed.value, 4.5)

    def test_the_log_line_says_what_the_run_is_worth(self):
        opts = campaignplan.options(facts(gains(**{"dire-maul-north": 9.0})))
        pick = campaignplan.heuristic(opts)
        self.assertIn(
            "9.0 expected item levels a run",
            campaignplan.planned_line(pick, "the queue is empty", "Jev"),
        )

    def test_an_operators_order_is_never_replaced(self):
        head = {
            "id": 3,
            "status": "active",
            "keyword": "zulfarrak",
            "runs_wanted": 50,
            "source": "web:overseer",
        }
        due = campaignplan.due(
            [head], {"dungeon_runs_done": 12}, list(facts().level_rows)
        )
        self.assertEqual(due.reason, "")


class JevIsToldTheUpgrades(unittest.TestCase):
    def test_the_question_carries_upgrades_progress_and_the_continent(self):
        ups = gains(**{"dire-maul-north": 9.0, "dire-maul-east-east": 2.0})
        f = facts(ups)
        opts = campaignplan.options(f)
        pick = campaignplan.heuristic(opts)
        fake = FakeJev(picks={"dungeon": "dire-maul-north"}, confidence=0.9)
        rule = jev_choices.policy(jev_choices.KIND_DUNGEON, {})
        judgment = asyncio.run(
            jev_choices.dungeon_ask(
                jev.Client("k", transport=fake),
                f,
                opts,
                pick,
                rule,
                "the queue is empty",
            )
        )
        [request] = fake.requests
        north = next(
            d for d in request["state"]["dungeons"] if d["door"] == "dire-maul-north"
        )
        self.assertEqual(north["expected_item_levels_gained_per_run"], 9.0)
        self.assertEqual(
            north["upgrades_per_member"], ["Grug: 1 upgrade, 0.20 a run, best a chest"]
        )
        self.assertEqual(north["raid_progress"], "none")
        self.assertEqual(north["continent"], "Kalimdor")
        self.assertFalse(north["needs_a_continent_crossing"])
        self.assertIn("raid guild", request["questions"]["dungeon"]["instructions"])
        self.assertIn("exp 9.0", judgment.facts)
        self.assertEqual(judgment.chosen, "dire-maul-north")


class TheRaidTab(unittest.TestCase):
    def test_a_capped_family_on_kalimdor_sees_dire_maul_and_why_the_rest_is_closed(
        self,
    ):
        crescent = [{"name": "Og", "entry": 18249, "count": 1}]
        view = preraid.family_view(
            ["Grug", "Ugga", "Og"],
            member_rows(),
            worn_rows(),
            catalog(),
            [],
            [],
            crescent,
        )
        self.assertIn("Dire Maul (the North wing)", view["line"])
        grug = next(m for m in view["members"] if m["name"] == "Grug")
        self.assertIn("Kromcrush's Chestplate", grug["line"])
        chest = next(r["cells"] for r in grug["rows"] if r["cells"][0] == "chest")
        self.assertEqual(chest[1], "Jouster's Chestplate (42)")
        self.assertIn("Captain", chest[3])
        self.assertIn("Breastplate of Valor", chest[4])
        closed = " ".join(view["closed"])
        self.assertIn("Stratholme (the main gate): withheld", closed)
        self.assertIn(
            "Upper Blackrock Spire: it starts behind the Dragonspine Door", closed
        )
        self.assertIn("Blackrock Depths: on the Eastern Kingdoms", closed)
        self.assertTrue(view["runs"][0].startswith("Dire Maul"))
        self.assertEqual(len(view["progress"]), 2)

    def test_below_the_cap_there_is_no_plan(self):
        view = preraid.family_view(
            ["Grug"], member_rows(level=25), worn_rows(), catalog(), [], [], []
        )
        self.assertEqual(view["members"], [])
        self.assertIn("weakest is 25", view["line"])

    def test_the_card_carries_the_plan_and_the_page_draws_it(self):
        group = {
            "guildid": None,
            "guild": "",
            "family": "Grug",
            "family_names": ["Grug"],
            "rows": [],
        }
        card = raidready.build_guild(
            group, [], [], [], 50, {"goals": []}, preraid={"line": "x"}
        )
        self.assertEqual(card["preraid"], {"line": "x"})
        self.assertIn('"next upgrades and where they drop"', PAGE)
        self.assertIn("for (const m of pre.members)", PAGE)
        self.assertIn("preraid=preraid.family_view(", SERVER)

    def test_the_bridge_planner_reads_the_upgrades_at_the_cap(self):
        self.assertIn("upgrades=upgrades, progress=progress", BRIDGE)
        self.assertIn("preraid.run_gains(plans)", BRIDGE)
        self.assertIn("min(levels) < campaignplan.LEVEL_CAP", BRIDGE)


if __name__ == "__main__":
    unittest.main()
