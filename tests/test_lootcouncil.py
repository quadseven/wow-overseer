"""The loot council (#194): the question Jev is asked about a dropped item, who
the answer gives it to and why, the facts item_disposition and weapon_choice
now carry, the guild bank's share of a BoE extra, and what the Chronicle and
Bags show."""

import asyncio
import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bag_pressure  # noqa: E402
import bank  # noqa: E402
import disposition  # noqa: E402
import jev  # noqa: E402
import jev_items  # noqa: E402
import lootcouncil  # noqa: E402
import lootstory  # noqa: E402
import statweights  # noqa: E402

WARRIOR, PALADIN, ROGUE, PRIEST, MAGE = 1, 2, 4, 5, 8

# The shape mod-overseer's LootCandidatesJson writes (its #642).
CANDIDATES = [
    {
        "name": "Grug",
        "family": True,
        "wearable": True,
        "comparison": "better",
        "gain": 60.0,
        "score": 150.0,
        "upgrade_percent": 40,
        "item_level_gain": 22,
        "role": "tank",
        "class": "Warrior",
        "spec": "Protection",
        "tank": True,
        "why": "plate, 600 armour",
    },
    {
        "name": "Raider",
        "family": False,
        "wearable": True,
        "comparison": "better",
        "gain": 90.0,
        "score": 150.0,
        "upgrade_percent": 60,
        "item_level_gain": 5,
        "role": "tank",
        "class": "Warrior",
        "spec": "Protection",
        "tank": True,
        "why": "plate",
    },
    {
        "name": "Ugga",
        "family": True,
        "wearable": False,
        "comparison": "not_better",
        "gain": 0.0,
        "score": 0.0,
        "upgrade_percent": 0,
        "item_level_gain": 0,
        "role": "healer",
        "class": "Priest",
        "spec": "Holy",
        "tank": False,
        "why": "no plate proficiency",
    },
    {
        "name": "Og",
        "family": True,
        "wearable": True,
        "comparison": "undecided",
        "gain": 10.0,
        "score": 100.0,
        "upgrade_percent": 10,
        "item_level_gain": 3,
        "role": "melee",
        "class": "Paladin",
        "spec": "Retribution",
        "tank": False,
        "why": "an effect the score cannot price",
    },
]


def row(**kw):
    base = dict(
        council_key="ml:77:1",
        kind="master",
        family="Grug",
        source="Lucifron",
        item_entry=16863,
        item_name="Gauntlets of Might",
        candidates=json.dumps(CANDIDATES),
        heuristic="Grug",
        heuristic_why="the biggest upgrade in the family as a tank",
    )
    base.update(kw)
    return base


def council(**kw):
    return lootcouncil.council_from_row(row(**kw))


def outcome(pick, confidence, status=jev.ANSWERED):
    return jev.Outcome(
        status,
        12,
        {"to": jev.Choice(pick, {pick: confidence}, confidence)},
        "jev-test",
    )


def rule(mode=jev.ACT):
    return lootcouncil.policy({"JEV_MODE_LOOT_COUNCIL": mode})


class FakeClient:
    timeout = 1.0

    def __init__(self, pick, confidence):
        self.pick, self.confidence, self.asked = pick, confidence, []

    async def ask(self, kind, state, questions, wait=0.0):
        self.asked.append((kind, state, questions))
        return outcome(self.pick, self.confidence)


class TheRow(unittest.TestCase):
    def test_candidates_parse_from_the_modules_json(self):
        c = council()
        self.assertEqual(
            [x.name for x in c.candidates], ["Grug", "Raider", "Ugga", "Og"]
        )
        grug = c.candidates[0]
        self.assertTrue(grug.family and grug.tank and grug.upgrades)
        self.assertEqual(grug.upgrade_percent, 40)
        self.assertEqual(grug.spec, "Protection")

    def test_unreadable_candidates_are_none_not_a_crash(self):
        self.assertEqual(lootcouncil.candidates_from_json("not json"), ())
        self.assertEqual(lootcouncil.candidates_from_json(None), ())
        self.assertIsNone(lootcouncil.council_from_row({}))


class TheQuestion(unittest.TestCase):
    def test_only_upgrades_are_offered_family_first(self):
        names = [c.name for c in lootcouncil.offered(council())]
        self.assertEqual(names, ["Grug", "Og", "Raider"])

    def test_the_question_carries_role_weights_and_upgrade_size(self):
        state, questions = lootcouncil.question(council(), {"name": "Gauntlets"})
        options = questions["to"]["criteria"]
        self.assertEqual(set(options), {"Grug", "Og", "Raider", lootcouncil.NOBODY})
        self.assertIn("40% of its worth is new", options["Grug"])
        self.assertIn("+22 item levels", options["Grug"])
        self.assertIn("in the family", options["Grug"])
        self.assertIn("a guild raider", options["Raider"])
        self.assertIn("(a tank)", options["Grug"])
        grug = state["candidates"][0]
        self.assertTrue(grug["tank"])
        self.assertTrue(grug["in_the_family"])
        weights = grug["stat_weights"]
        for stat in ("stamina", "defense", "armor", "block"):
            self.assertGreater(weights[stat], 0)
        self.assertIn(
            "family's own members come first", questions["to"]["instructions"]
        )

    def test_nobody_to_offer_asks_nothing(self):
        only_ugga = json.dumps([CANDIDATES[2]])
        self.assertIsNone(lootcouncil.question(council(candidates=only_ugga), None))

    def test_the_nobody_option_says_what_happens(self):
        self.assertIn("master looter holds it", lootcouncil.nobody_option(council()))
        self.assertIn(
            "everybody greeds", lootcouncil.nobody_option(council(kind="roll"))
        )


# Big Bad Pauldrons, dev realm 2026-09-24 (overseer_loot_council id 12), as
# the module now writes it: the main tank has first call on a tank's piece.
PAULDRONS = [
    dict(
        CANDIDATES[0],
        gain=169.0,
        score=467.0,
        upgrade_percent=36,
        item_level_gain=8,
        main_tank=True,
        role_piece=True,
        priority=0,
    ),
    dict(
        CANDIDATES[3],
        name="Grog",
        comparison="better",
        gain=76.3,
        score=191.8,
        upgrade_percent=40,
        item_level_gain=8,
        main_tank=False,
        role_piece=False,
        priority=3,
    ),
]


def pauldrons(**kw):
    return council(
        kind="roll",
        item_name="Big Bad Pauldrons",
        candidates=json.dumps(PAULDRONS),
        heuristic="Grug",
        heuristic_why="the main tank in the family has first call on a tank's piece",
        **kw,
    )


class FirstCall(unittest.TestCase):
    def test_the_first_call_facts_parse(self):
        grug, grog = pauldrons().candidates
        self.assertTrue(grug.main_tank and grug.role_piece)
        self.assertEqual(grug.priority, lootcouncil.MAIN_TANK_CALL)
        self.assertEqual(grog.priority, lootcouncil.NO_CALL)

    def test_an_older_row_reads_as_no_first_call(self):
        grug = council().candidates[0]
        self.assertFalse(grug.main_tank or grug.role_piece)
        self.assertEqual(grug.priority, lootcouncil.NO_CALL)
        odd = lootcouncil.candidates_from_json(
            json.dumps([dict(PAULDRONS[0], priority=9)])
        )
        self.assertEqual(odd[0].priority, lootcouncil.NO_CALL)

    def test_the_main_tank_is_offered_first_over_a_bigger_share(self):
        names = [c.name for c in lootcouncil.offered(pauldrons())]
        self.assertEqual(names, ["Grug", "Grog"])

    def test_jev_is_told_the_main_tank_and_the_rule(self):
        state, questions = lootcouncil.question(pauldrons(), {"name": "Pauldrons"})
        options = questions["to"]["criteria"]
        self.assertIn("(the main tank)", options["Grug"])
        self.assertIn("first call as the main tank on a tank's piece", options["Grug"])
        self.assertNotIn("first call", options["Grog"])
        grug, grog = state["candidates"]
        self.assertTrue(grug["main_tank"] and grug["a_piece_for_their_role"])
        self.assertEqual(grog["first_call"], "none")
        self.assertIn("gears its main tank first", questions["to"]["instructions"])
        self.assertIn("healer's piece", questions["to"]["instructions"])

    def test_agreeing_with_the_main_tank_says_why(self):
        d = lootcouncil.decide(pauldrons(), outcome("Grug", 0.47), rule())
        self.assertEqual((d.recipient, d.decided_by), ("Grug", jev.BOTH))
        self.assertIn("first call as the main tank", d.reason)
        self.assertLessEqual(len(d.reason.encode("utf-8")), lootcouncil.REASON_BYTES)

    def test_an_unsure_jev_leaves_the_main_tank(self):
        d = lootcouncil.decide(pauldrons(), outcome("Grog", 0.47), rule())
        self.assertEqual((d.recipient, d.decided_by), ("Grug", jev.HEURISTIC))

    def test_a_healer_is_offered_first_on_a_healers_piece(self):
        ugga = dict(
            CANDIDATES[2],
            wearable=True,
            comparison="better",
            upgrade_percent=20,
            role_piece=True,
            priority=2,
        )
        og = dict(CANDIDATES[3], name="Og", comparison="better", upgrade_percent=60)
        c = council(candidates=json.dumps([og, ugga]))
        self.assertEqual([x.name for x in lootcouncil.offered(c)], ["Ugga", "Og"])
        _, questions = lootcouncil.question(c, None)
        self.assertIn(
            "first call as a healer on a healer's piece",
            questions["to"]["criteria"]["Ugga"],
        )


class TheDecision(unittest.TestCase):
    def test_a_confident_different_pick_acts_with_jevs_reason(self):
        d = lootcouncil.decide(council(), outcome("Og", 0.9), rule())
        self.assertEqual(d.recipient, "Og")
        self.assertEqual(d.decided_by, jev.JEV)
        self.assertTrue(d.reason.startswith("Jev (0.90): Og gets it:"), d.reason)
        self.assertEqual(d.judgment.kind, lootcouncil.KIND)
        self.assertEqual(d.judgment.acted, jev.JEV)

    def test_an_unsure_pick_leaves_the_heuristic(self):
        d = lootcouncil.decide(council(), outcome("Og", 0.4), rule())
        self.assertEqual(d.recipient, "Grug")
        self.assertEqual(d.decided_by, jev.HEURISTIC)
        self.assertIn("Heuristic:", d.reason)
        self.assertIn("Jev was unsure: 0.40 for Og", d.reason)

    def test_agreement_counts_at_any_confidence(self):
        d = lootcouncil.decide(council(), outcome("Grug", 0.3), rule())
        self.assertEqual((d.recipient, d.decided_by), ("Grug", jev.BOTH))
        self.assertTrue(d.reason.startswith("Jev agreed (0.30)"))

    def test_a_confident_nobody_names_nobody(self):
        d = lootcouncil.decide(council(), outcome(lootcouncil.NOBODY, 0.95), rule())
        self.assertEqual((d.recipient, d.decided_by), ("", jev.JEV))

    def test_shadow_never_acts(self):
        d = lootcouncil.decide(council(), outcome("Og", 0.99), rule(jev.SHADOW))
        self.assertEqual((d.recipient, d.decided_by), ("Grug", jev.HEURISTIC))

    def test_no_answer_is_the_heuristic(self):
        d = lootcouncil.decide(council(), jev.Outcome(jev.TIMEOUT, 3000), rule())
        self.assertEqual((d.recipient, d.decided_by), ("Grug", jev.HEURISTIC))
        self.assertEqual(d.judgment.status, jev.TIMEOUT)

    def test_the_reason_fits_its_column(self):
        long_why = "x" * 400
        d = lootcouncil.decide(
            council(heuristic_why=long_why), outcome("Og", 0.1), rule()
        )
        self.assertLessEqual(len(d.reason.encode("utf-8")), lootcouncil.REASON_BYTES)

    def test_answer_asks_once_and_decides(self):
        client = FakeClient("Raider", 0.88)
        d = asyncio.run(
            lootcouncil.answer(client, council(), lambda e: {"name": "G"}, rule())
        )
        self.assertEqual(len(client.asked), 1)
        self.assertEqual(client.asked[0][0], lootcouncil.KIND)
        self.assertEqual((d.recipient, d.decided_by), ("Raider", jev.JEV))

    def test_answer_with_nothing_to_ask_is_the_heuristic(self):
        client = FakeClient("Grug", 0.99)
        only_ugga = json.dumps([CANDIDATES[2]])
        d = asyncio.run(
            lootcouncil.answer(
                client,
                council(candidates=only_ugga, heuristic=""),
                lambda e: None,
                rule(),
            )
        )
        self.assertEqual(client.asked, [])
        self.assertEqual((d.recipient, d.decided_by), ("", jev.HEURISTIC))

    def test_the_default_policy_acts_at_three_quarters(self):
        r = lootcouncil.policy({})
        self.assertEqual((r.mode, r.threshold, r.on_agreement), (jev.ACT, 0.75, True))


class StatWeights(unittest.TestCase):
    def test_a_protection_warrior_is_a_tank_valuing_the_tank_stats(self):
        self.assertEqual(statweights.role_for(WARRIOR, "Protection"), statweights.TANK)
        w = statweights.stat_weights(statweights.TANK)
        self.assertGreater(w["defense"], w["strength"])
        self.assertGreater(w["stamina"], w["attack_power"])

    def test_roles_by_class_and_tree(self):
        self.assertEqual(
            statweights.role_for(PALADIN, "Retribution"), statweights.MELEE
        )
        self.assertEqual(statweights.role_for(PRIEST, "Holy"), statweights.HEALER)
        self.assertEqual(statweights.role_for(MAGE, ""), statweights.CASTER)
        self.assertEqual(statweights.role_for(ROGUE, "Combat"), statweights.MELEE)
        self.assertEqual(statweights.role_for(WARRIOR, ""), statweights.UNKNOWN)
        self.assertEqual(statweights.stat_weights(statweights.UNKNOWN), {})


def wardrobe(name, class_id, spec, worn, head=False):
    return jev_items.Wardrobe(name, class_id, 60, spec, worn, head)


def holding(**kw):
    base = dict(
        holder="Og",
        inventory_type=10,
        soulbound=False,
        item_level=66,
        item_class=4,
        name="Gauntlets of Might",
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


class ItemQuestionFacts(unittest.TestCase):
    """item_disposition and weapon_choice carry the upgrade size, the role's
    stat weights and the head's tank flag (#194)."""

    def closet(self):
        return {
            "Grug": wardrobe(
                "Grug",
                WARRIOR,
                "Protection",
                {9: {"name": "Old Gloves", "item_level": 44}, 15: {"item_level": 30}},
                head=True,
            ),
            "Og": wardrobe(
                "Og", MAGE, "Frost", {9: {"name": "Cloth", "item_level": 40}}
            ),
        }

    def test_disposition_facts(self):
        state, _q = jev_items.disposition_question(
            holding(), {"name": "Gauntlets"}, self.closet(), {"keep": "keep"}
        )
        grug = state["family"][0]
        self.assertEqual(grug["name"], "Grug")
        self.assertTrue(grug["tank"])
        self.assertTrue(grug["family_head"])
        self.assertEqual(grug["role"], "tank")
        self.assertEqual(grug["upgrade_item_levels"], 22)
        self.assertGreater(grug["stat_weights"]["block"], 0)
        og = state["holder"]
        self.assertFalse(og["tank"])
        self.assertNotIn("family_head", og)
        self.assertEqual(og["upgrade_item_levels"], 26)

    def test_weapon_facts_measure_the_main_hand(self):
        state, _q = jev_items.weapon_question(
            holding(holder="Grug", inventory_type=13, item_class=2, item_level=60),
            {"name": "Sword"},
            self.closet()["Grug"],
        )
        who = state["character"]
        self.assertTrue(who["tank"] and who["family_head"])
        self.assertEqual(who["upgrade_item_levels"], 30)
        self.assertIn("stamina", who["stat_weights"])
        self.assertNotIn("wearing_in_those_slots", who)

    def test_an_empty_slot_is_all_upgrade(self):
        w = wardrobe("Og", MAGE, "Frost", {})
        self.assertEqual(jev_items.upgrade_item_levels(w, (0,), 50), 50)
        self.assertIsNone(jev_items.upgrade_item_levels(w, (), 50))
        self.assertEqual(jev_items.upgrade_slots(17), (15,))
        self.assertEqual(jev_items.upgrade_slots(14), (16,))


class GuildBankShare(unittest.TestCase):
    """A BoE extra goes to the guildmate it upgrades, or the guild bank for a
    member who will wear it later, or the auction house (#194)."""

    def gear_row(self, **kw):
        base = dict(
            holder="Og",
            item_guid=9001,
            entry=10001,
            name="Knight's Breastplate",
            quality=2,
            item_level=55,
            required_level=50,
            allowable_class=-1,
            inventory_type=5,
            item_class=4,
            item_subclass=4,
            bonding=2,
            instance_flags=0,
        )
        base.update(kw)
        return base

    def equipped(self, name, class_id, level, item_level=60):
        return dict(
            name=name,
            class_id=class_id,
            level=level,
            inventory_type=5,
            item_level=item_level,
        )

    def members(self, *names):
        return [types.SimpleNamespace(name=n, online=True) for n in names]

    def test_a_lower_level_guild_warrior_gets_it_banked(self):
        equipped = [
            self.equipped("Og", MAGE, 60),
            self.equipped("Recruit", WARRIOR, 42, 30),
        ]
        keeps = bag_pressure.guild_bank_keeps(
            [self.gear_row()], equipped, ["Og"], self.members("Og", "Recruit")
        )
        self.assertIn(9001, keeps)
        self.assertIn("Recruit can wear it at level 50", keeps[9001])

    def test_somebody_it_upgrades_now_is_not_the_banks(self):
        equipped = [
            self.equipped("Og", MAGE, 60),
            self.equipped("Tank", WARRIOR, 60, 40),
            self.equipped("Recruit", WARRIOR, 42, 30),
        ]
        keeps = bag_pressure.guild_bank_keeps(
            [self.gear_row()], equipped, ["Og"], self.members("Og", "Tank", "Recruit")
        )
        self.assertEqual(keeps, {})

    def test_nobody_later_either_is_the_auction_houses(self):
        equipped = [self.equipped("Og", MAGE, 60), self.equipped("Caster", PRIEST, 30)]
        keeps = bag_pressure.guild_bank_keeps(
            [self.gear_row()], equipped, ["Og"], self.members("Og", "Caster")
        )
        self.assertEqual(keeps, {})

    def test_the_keeper_rule_stores_it_in_the_guild_bank(self):
        item = disposition.Item(
            name="Knight's Breastplate",
            quality=2,
            item_class=4,
            required_level=50,
            sell_price=100,
            binding=disposition.BIND_ON_EQUIP,
        )
        h = bank.Holding(
            holder="Og",
            guid=9001,
            place=bank.BAGS,
            count=1,
            container_slots=0,
            item=item,
            bound=False,
        )
        storage = bank.Storage(
            guild_depositors=frozenset({"Og"}),
            guild_later={9001: "kept for Recruit"},
        )
        self.assertEqual(bank.storage_reason(h, storage), "kept for Recruit")
        not_depositor = bank.Storage(guild_later={9001: "kept for Recruit"})
        self.assertEqual(bank.storage_reason(h, not_depositor), "")
        bound = bank.Holding(
            holder="Og",
            guid=9001,
            place=bank.BAGS,
            count=1,
            container_slots=0,
            item=item,
            bound=True,
        )
        self.assertEqual(bank.storage_reason(bound, storage), "")


AWARD = dict(
    council_key="ml:77:1",
    kind="master",
    family="Grug",
    source="Lucifron",
    item_entry=16863,
    item_name="Gauntlets of Might",
    item_quality=4,
    status="given",
    recipient="Grug",
    given_to="Grug",
    reason="Jev (0.88): Grug gets it: Protection Warrior, playing tank (a tank), in the family.",
    decided_by="jev",
    item_guid=5550001,
    outcome="handed over by the master looter",
    opened_at=None,
    decided_at=None,
    given_at=None,
)


class WhatThePagesShow(unittest.TestCase):
    def test_the_chronicle_board(self):
        board = lootcouncil.board([AWARD, dict(AWARD, status="open", council_key="x")])
        self.assertEqual(len(board["awards"]), 1)
        a = board["awards"][0]
        self.assertEqual(
            (a["to"], a["source"], a["decided_by"]), ("Grug", "Lucifron", "jev")
        )
        self.assertTrue(a["reason"].startswith("Jev (0.88)"))

    def test_the_bags_strip_and_tooltip(self):
        v = lootcouncil.view([AWARD])
        self.assertEqual((v["index"], v["label"]), ("05", "loot council"))
        self.assertIn("Gauntlets of Might to Grug from Lucifron.", v["lines"][0])
        self.assertIn("Jev (0.88)", v["lines"][0])
        self.assertIn("Loot council: to Grug from Lucifron.", v["by_guid"]["5550001"])

    def test_the_tooltip_of_an_awarded_item_carries_the_reason(self):
        v = lootcouncil.view([AWARD])
        payload = {
            "members": [
                {
                    "bags": [
                        {"items": [{"guid": 5550001, "tip": "Gauntlets (epic)"}]},
                        {"items": [{"guid": 42, "tip": "Linen"}]},
                    ]
                }
            ]
        }
        self.assertEqual(lootcouncil.annotate_tips(payload, v["by_guid"]), 1)
        bags = payload["members"][0]["bags"]
        self.assertIn("Loot council: to Grug", bags[0]["items"][0]["tip"])
        self.assertEqual(bags[1]["items"][0]["tip"], "Linen")
        self.assertEqual(lootcouncil.annotate_tips(payload, v["by_guid"]), 0)

    def test_a_failed_hand_over_says_so(self):
        v = lootcouncil.view(
            [dict(AWARD, status="failed", outcome="bags full", given_to="")]
        )
        self.assertIn("not handed over: bags full", v["lines"][0])

    def test_the_story_ends_with_the_councils_reason(self):
        rows = [
            dict(
                id=1,
                kind=lootstory.ITEM_LOOT,
                character_name="Grug",
                subject_id=16863,
                subject_name="Gauntlets of Might",
                subject_quality=4,
                item_guid=5550001,
                via=lootstory.VIA_COUNCIL,
                source="Lucifron",
            )
        ]
        payload = lootstory.build_loot(
            rows, {}, council=lootcouncil.by_item_guid([AWARD])
        )
        line = payload["stories"][0]["line"]
        self.assertIn("Grug was awarded it by the loot council from Lucifron", line)
        self.assertIn("Loot council: Jev (0.88)", line)


class TheBridgeWiring(unittest.TestCase):
    """The seams in bridge.py and map_server.py, which import discord and
    pymysql and are read as source here."""

    @classmethod
    def setUpClass(cls):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "bridge.py"), encoding="utf-8") as f:
            cls.bridge = f.read()
        with open(os.path.join(root, "map_server.py"), encoding="utf-8") as f:
            cls.site = f.read()

    def test_the_council_loop_runs(self):
        self.assertIn("self._loot_council_loop,", self.bridge)
        self.assertIn("lootcouncil.answer(", self.bridge)

    def test_an_answer_never_overwrites_the_modules_heuristic(self):
        self.assertIn("WHERE council_key = %s AND status = 'open'", self.bridge)

    def test_the_guild_bank_keeps_reach_the_bank_and_the_auction(self):
        self.assertIn("guild_later=dict(_GUILD_BANK_KEEPS)", self.bridge)
        self.assertIn('"the guild bank" if guid in _GUILD_BANK_KEEPS', self.bridge)

    def test_the_pages_are_served_the_council(self):
        self.assertIn('payload["council"] = lootcouncil.board(council)', self.site)
        self.assertIn('payload["loot_council"] = _fetch_loot_council_view()', self.site)


if __name__ == "__main__":
    unittest.main()
