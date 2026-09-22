"""Jev is asked about carried items in shadow, beside the heuristic, and acts on nothing (#95).

The Destiny case is the fixture the pilot exists for. Measured on wow-dev on
2026-09-22: a level 60 Retribution paladin wields Moon Cleaver (a one-hand
axe, item level 52) with Templar Shield (58), and Destiny (item 647, a
two-hand sword, item level 57, "Chance on hit: Increases Strength by 200 for
10 sec.") reaches his bags. gear.py refuses any two-hander over a worn
off-hand piece and compares item levels only, so it cannot weigh the proc
against the shield. That is where a Choice fits: the heuristic's answer and
Jev's are recorded side by side, and the heuristic's is the one acted on.

A real call made while building this (one request, from the operator's
machine) answered `carried` at 0.89 in 373 ms. The tests never call the API:
Jev is the real client over a fake transport.
"""

import asyncio
import json
import pathlib
import re
import unittest

import bonds
import gear
import jev
import jev_items

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()

WARRIOR, PALADIN, ROGUE, PRIEST, MAGE = 1, 2, 4, 5, 8
NAMES = ["Bork", "Grog", "Grug", "Og", "Ugga"]

# Equipped rows (_FAMILY_EQUIPPED_SQL) and worn items (_JEV_WORN_SQL).
WORN = [
    dict(name="Grog", class_id=PALADIN, level=60, inventory_type=13, item_level=52),
    dict(name="Grog", class_id=PALADIN, level=60, inventory_type=14, item_level=58),
    dict(name="Grug", class_id=WARRIOR, level=60, inventory_type=13, item_level=30),
    dict(name="Grug", class_id=WARRIOR, level=60, inventory_type=14, item_level=51),
    dict(name="Ugga", class_id=PRIEST, level=60, inventory_type=17, item_level=45),
    dict(name="Bork", class_id=ROGUE, level=60, inventory_type=13, item_level=50),
    dict(name="Bork", class_id=ROGUE, level=60, inventory_type=22, item_level=50),
    dict(name="Og", class_id=MAGE, level=60, inventory_type=17, item_level=40),
    dict(name="Og", class_id=MAGE, level=60, inventory_type=5, item_level=40),
    # Everybody wears a chest, so a chest in the bags is judged against one.
    dict(name="Grog", class_id=PALADIN, level=60, inventory_type=5, item_level=40),
    dict(name="Grug", class_id=WARRIOR, level=60, inventory_type=5, item_level=40),
    dict(name="Ugga", class_id=PRIEST, level=60, inventory_type=5, item_level=40),
    dict(name="Bork", class_id=ROGUE, level=60, inventory_type=5, item_level=40),
]
WORN_ITEMS = [
    dict(name="Grog", slot=15, entry=15236),
    dict(name="Grog", slot=16, entry=10364),
    dict(name="Grug", slot=15, entry=15242),
    dict(name="Grug", slot=16, entry=14954),
]
CARDS = {
    647: {
        "name": "Destiny",
        "item_level": 57,
        "slot": "Two-Hand",
        "kind": "Sword",
        "damage": {"min": 112, "max": 168, "speed": 2.6, "dps": 53.8},
        "effects": ["Chance on hit: Increases Strength by 200 for 10 sec."],
        "quality": "epic",
    },
    15236: {"name": "Moon Cleaver", "item_level": 52, "slot": "One-Hand"},
    10364: {"name": "Templar Shield", "item_level": 58, "slot": "Off Hand"},
    15242: {"name": "Honed Stiletto", "item_level": 30, "slot": "One-Hand"},
    14954: {"name": "Bloodforged Shield", "item_level": 51, "slot": "Off Hand"},
}


def carried(**kw):
    """One _SURPLUS_GEAR_SQL row. Defaults are Destiny in Grog's bags,
    bind on equip and not yet bound."""
    row = dict(
        holder="Grog",
        level=60,
        item_guid=4909901,
        entry=647,
        count=1,
        instance_flags=0,
        name="Destiny",
        quality=4,
        sell_price=70024,
        required_level=52,
        bonding=2,
        item_class=2,
        item_subclass=8,
        bag_family=0,
        item_level=57,
        allowable_class=-1,
        inventory_type=17,
    )
    row.update(kw)
    return row


def chest(**kw):
    """A mail chest, bind on equip, uncommon. Defaults to Grog's bags."""
    base = dict(
        item_guid=8001,
        entry=7527,
        name="Cabalist Chestpiece",
        quality=2,
        sell_price=3000,
        required_level=45,
        item_class=4,
        item_subclass=3,
        item_level=50,
        inventory_type=5,
    )
    base.update(kw)
    return carried(**base)


class FakeJev:
    """A transport answering every Choice with `picks[qid]`, or its first option."""

    def __init__(self, picks=None, confidence=0.78):
        self.picks = picks or {}
        self.confidence = confidence
        self.requests = []

    def __call__(self, url, body, headers, timeout):
        request = json.loads(body)
        self.requests.append(request)
        answers = {}
        for qid, question in request["questions"].items():
            options = list(question["criteria"])
            pick = self.picks.get(qid, options[0])
            rest = (1.0 - 0.89) / max(1, len(options) - 1)
            answers[qid] = {
                "type": "choice",
                "choice": pick,
                "probabilities": {o: (0.89 if o == pick else rest) for o in options},
                "confidence": self.confidence,
            }
        return 200, json.dumps({"model": "jev-1.13.0", "answers": answers}).encode()


def run(gear_rows, fake=None, key="k", **kw):
    client = jev.Client(key, transport=fake or FakeJev())
    kw.setdefault("specs", {"Grog": "Retribution", "Grug": "Protection"})
    return asyncio.run(
        jev_items.shadow_pass(
            client,
            gear_rows=gear_rows,
            worn_rows=WORN,
            worn_items=WORN_ITEMS,
            names=NAMES,
            describe=lambda entry: CARDS.get(int(entry)),
            **kw,
        )
    )


def holding(row):
    return gear.holdings_from_rows([row])[0]


def characters():
    return gear.characters_from_rows(WORN, NAMES)


class DestinyTest(unittest.TestCase):
    def test_the_weapon_question_is_asked_where_the_numbers_cannot_settle_it(self):
        fake = FakeJev(picks={"better": jev_items.WORN, "route": jev_items.EQUIP})
        judgments = run([carried()], fake)
        weapon = [j for j in judgments if j.kind == jev_items.KIND_WEAPON]
        grog = [j for j in weapon if j.subject == "Grog"]
        self.assertEqual(len(grog), 1)
        judgment = grog[0]
        # The heuristic now reads the party role (#174): a damage-role
        # paladin takes the two-hander over a spare shield, by item level,
        # and still says the proc is beyond the numbers ...
        self.assertEqual(judgment.heuristic, jev_items.CARRIED)
        self.assertIn("cannot be settled from the numbers", judgment.heuristic_why)
        # ... and when Jev weighs it the other way, both are recorded.
        self.assertEqual(judgment.jev, jev_items.WORN)
        self.assertFalse(judgment.agree)
        self.assertIn("verdict=differ", judgment.line())
        self.assertIn("heuristic=carried", judgment.line())

    def test_jev_is_shown_the_proc_the_shield_and_the_specialization(self):
        fake = FakeJev()
        run([carried()], fake)
        weapon = [
            r
            for r in fake.requests
            if "better" in r["questions"] and r["state"]["character"]["name"] == "Grog"
        ][0]
        state = weapon["state"]
        self.assertEqual(state["character"]["talent_specialization"], "Retribution")
        self.assertIn("Chance on hit", state["carried"]["effects"][0])
        self.assertEqual(
            [w["name"] for w in state["worn"]], ["Moon Cleaver", "Templar Shield"]
        )
        self.assertEqual(
            set(weapon["questions"]["better"]["criteria"]),
            {jev_items.CARRIED, jev_items.WORN},
        )

    def test_a_class_that_cannot_wield_it_is_never_offered_it(self):
        offered = jev_items.options(carried(), holding(carried()), characters())
        # The paladin can equip it, the warrior can be handed it; the priest,
        # the rogue and the mage cannot wield a two-handed sword at all.
        self.assertEqual(
            set(offered),
            {jev_items.KEEP, jev_items.EQUIP, "give:Grug", jev_items.VENDOR},
        )

    def test_an_epic_is_not_offered_to_the_auction_house(self):
        offered = jev_items.options(carried(), holding(carried()), characters())
        self.assertNotIn(jev_items.AUCTION, offered)


class OptionsTest(unittest.TestCase):
    def test_a_soulbound_copy_cannot_be_handed_on_or_listed(self):
        row = chest(instance_flags=1)
        offered = jev_items.options(row, holding(row), characters())
        self.assertFalse([o for o in offered if o.startswith(jev_items.GIVE_PREFIX)])
        self.assertNotIn(jev_items.AUCTION, offered)

    def test_an_unbound_uncommon_can_be_listed(self):
        row = chest()
        offered = jev_items.options(row, holding(row), characters())
        self.assertIn(jev_items.AUCTION, offered)

    def test_nothing_is_offered_that_has_no_executor(self):
        row = chest()
        offered = jev_items.options(row, holding(row), characters())
        self.assertNotIn("disenchant", offered)

    def test_mail_is_offered_only_to_those_trained_in_it(self):
        row = chest()
        offered = jev_items.options(row, holding(row), characters())
        gives = {o for o in offered if o.startswith(jev_items.GIVE_PREFIX)}
        self.assertEqual(gives, {"give:Grug"})

    def test_no_vendor_price_means_no_vendor_option(self):
        row = chest(sell_price=0)
        self.assertNotIn(
            jev_items.VENDOR, jev_items.options(row, holding(row), characters())
        )


class HeuristicTest(unittest.TestCase):
    """The heuristic's answer is read off the shipped passes, not re-decided."""

    def routes(self, rows, keep_names=()):
        return jev_items.heuristic(rows, WORN, NAMES, keep_names)

    def test_an_upgrade_for_the_holder_is_equip(self):
        route, _ = self.routes([chest()])[8001]
        self.assertEqual(route, jev_items.EQUIP)

    def test_an_upgrade_for_a_sibling_names_them(self):
        # Grog and Grug both wear mail; gear.claimant asks them by name.
        route, _ = self.routes([chest(holder="Og")])[8001]
        self.assertEqual(route, "give:Grog")

    def test_a_ring_cannot_be_settled_from_the_numbers(self):
        ring = chest(
            item_guid=9001, name="Blood Ring", inventory_type=11, item_subclass=0
        )
        route, why = self.routes([ring])[9001]
        self.assertEqual(route, jev_items.KEEP)
        self.assertIn("cannot be settled from the numbers", why)

    def test_bind_on_equip_nobody_wants_is_the_auction_pass(self):
        cloth = chest(holder="Og", item_level=10, required_level=5, item_subclass=1)
        route, _ = self.routes([cloth])[8001]
        self.assertEqual(route, jev_items.AUCTION)

    def test_soulbound_nobody_wants_is_the_vendor_pass(self):
        cloth = chest(
            holder="Og",
            item_level=10,
            required_level=5,
            item_subclass=1,
            instance_flags=1,
        )
        route, _ = self.routes([cloth])[8001]
        self.assertEqual(route, jev_items.VENDOR)

    def test_the_operator_mark_keeps(self):
        route, why = self.routes([chest()], keep_names=("cabalist chestpiece",))[8001]
        self.assertEqual(route, jev_items.KEEP)
        self.assertIn("operator", why)


class ShadowPassTest(unittest.TestCase):
    def test_no_key_keeps_every_heuristic_answer(self):
        judgments = run([chest(), carried()], key="")
        self.assertTrue(judgments)
        for judgment in judgments:
            self.assertEqual(judgment.status, jev.NO_KEY)
            self.assertEqual(judgment.jev, "")
            self.assertIsNone(judgment.agree)
            self.assertTrue(judgment.heuristic)
            self.assertIn("verdict=no-answer", judgment.line())

    def test_agreement_is_recorded_as_agreement(self):
        fake = FakeJev(picks={"route": jev_items.EQUIP})
        [judgment] = [
            j for j in run([chest()], fake) if j.kind == jev_items.KIND_DISPOSITION
        ]
        self.assertTrue(judgment.agree)
        self.assertEqual(judgment.model, "jev-1.13.0")
        self.assertIn('"equip":0.89', judgment.probabilities_json())

    def test_a_kind_switched_off_is_never_asked(self):
        fake = FakeJev()
        judgments = run([carried()], fake, modes={jev_items.KIND_WEAPON: jev.OFF})
        self.assertEqual({j.kind for j in judgments}, {jev_items.KIND_DISPOSITION})
        self.assertFalse([r for r in fake.requests if "better" in r["questions"]])

    def test_a_pass_sends_at_most_its_limit(self):
        rows = [chest(item_guid=8000 + n) for n in range(6)]
        fake = FakeJev()
        judgments = run(rows, fake, limit=3)
        self.assertEqual(len(judgments), 3)
        self.assertEqual(len(fake.requests), 3)

    def test_the_mode_rides_on_the_record(self):
        [judgment] = [
            j
            for j in run([chest()], modes={jev_items.KIND_DISPOSITION: jev.ACT})
            if j.kind == jev_items.KIND_DISPOSITION
        ]
        self.assertEqual(judgment.mode, jev.ACT)

    def test_an_unchanged_answer_has_an_unchanged_signature(self):
        first = run([chest()])
        second = run([chest()])
        self.assertEqual([j.signature for j in first], [j.signature for j in second])


class DescriptionTest(unittest.TestCase):
    def test_the_card_drops_what_the_judgment_does_not_need(self):
        card = jev_items.item_card(
            {
                "name": "Destiny",
                "quality": 4,
                "sell_price": {"gold": 7},
                "flavor": None,
                "durability": "120 / 120",
                "set": None,
                "effects": ["Chance on hit: x"],
                "stats": [],
            }
        )
        self.assertEqual(
            card,
            {"name": "Destiny", "quality": "epic", "effects": ["Chance on hit: x"]},
        )
        self.assertIsNone(jev_items.item_card(None))

    def test_the_specialization_comes_from_the_family_table(self):
        trees = {
            PALADIN: [
                ("382", {"name": "Holy"}),
                ("383", {"name": "Protection"}),
                ("381", {"name": "Retribution"}),
            ],
        }
        specs = jev_items.specs_for(
            ["Grog", "Nobody"], bonds.FAMILY, lambda c: trees.get(c, [])
        )
        self.assertEqual(specs, {"Grog": "Retribution"})


class BridgeWiringTest(unittest.TestCase):
    """bridge.py is read as text: it imports discord and cannot be imported here."""

    def test_the_shadow_pass_starts_after_the_equip_pass_and_is_not_awaited(self):
        equip = BRIDGE.index("await self._equip_upgrades(gear_rows, worn, names)")
        shadow = BRIDGE.index("self._jev_shadow(gear_rows, worn, names)", equip)
        gate = BRIDGE.index("family_town_run_needed(", equip)
        self.assertLess(shadow, gate)
        self.assertNotIn("await self._jev_shadow(", BRIDGE)

    def test_the_shadow_pass_writes_only_its_own_record(self):
        start = BRIDGE.index("    async def _jev_shadow_once(")
        end = BRIDGE.index("\n    async def ", start + 10)
        body = BRIDGE[start:end]
        self.assertNotIn("_insert_", body.replace("_insert_jev_judgment", ""))
        self.assertNotIn("overseer_command", body)
        insert = BRIDGE[BRIDGE.index("def _insert_jev_judgment(") :]
        insert = insert[: insert.index("\n\n\n")]
        self.assertEqual(
            re.findall(r"INSERT INTO (\w+)", insert), ["overseer_jev_judgment"]
        )

    def test_the_record_is_created_at_both_start_ups(self):
        self.assertEqual(BRIDGE.count("await asyncio.to_thread(_ensure_jev_store)"), 2)

    def test_act_is_not_wired_yet(self):
        self.assertIn("jev.effective_mode(kind, act_supported=False)", BRIDGE)


if __name__ == "__main__":
    unittest.main()
