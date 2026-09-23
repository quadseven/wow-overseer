"""Jev asked about protected non-gear items, in shadow (#232).

THE FIXTURE is the priest measured on 2026-09-23: level 60, 30 bag slots, 0
free, carrying 48 uncut gems, 8 recipes for trades she does not have, 3
lockboxes, 25 Empty Vial, 20 Silverleaf and quest items no open quest needs.
The counts are the measured ones; the entries, prices and stack split are
representative. The tests run the real client over a fake transport and
never call the API.
"""

import asyncio
import pathlib
import unittest

import clearance
import jev
import jev_keep
import jevview
import lockbox
from test_jev_items import FakeJev

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")

PRIEST, ROGUE, WARRIOR, PALADIN, MAGE = 5, 4, 1, 2, 8
HERBALISM, ALCHEMY, TAILORING, ENCHANTING = 182, 171, 197, 333
ENGINEERING, BLACKSMITHING, LEATHERWORKING, JEWELCRAFTING = 202, 164, 165, 755
SKINNING, MINING, LOCKPICKING = 393, 186, 633
EMPTY_VIAL = 3371


def row(guid, entry, name, item_class, count=1, quality=1, sell_price=0, **kw):
    """One of Ugga's carried stacks, flagged as _fetch_vendor_items flags it."""
    base = dict(
        holder="Ugga",
        item_guid=guid,
        entry=entry,
        name=name,
        item_class=item_class,
        count=count,
        quality=quality,
        sell_price=sell_price,
        bag_family=0,
        quest_item=False,
        reagent=False,
        profession_needed=False,
    )
    base.update(kw)
    return base


GEMS = [
    row(101, 774, "Malachite", 3, 12, 2, 25),
    row(102, 818, "Tigerseye", 3, 10, 2, 50),
    row(103, 1210, "Shadowgem", 3, 8, 2, 100),
    row(104, 1206, "Moss Agate", 3, 6, 2, 100),
    row(105, 1705, "Lesser Moonstone", 3, 5, 2, 150),
    row(106, 1529, "Jade", 3, 4, 2, 200),
    row(107, 3864, "Citrine", 3, 2, 2, 400),
    row(108, 7909, "Aquamarine", 3, 1, 2, 800),
]
RECIPES = [
    row(201, 2881, "Plans: Runed Copper Breastplate", 9, 1, 2, 250),
    row(202, 7560, "Schematic: Gnomish Universal Remote", 9, 1, 2, 300),
    row(203, 5786, "Pattern: Murloc Scale Belt", 9, 1, 2, 125),
    row(204, 4355, "Pattern: Icy Cloak", 9, 1, 2, 375),
    row(205, 10424, "Plans: Silvered Bronze Leggings", 9, 1, 2, 450),
    row(206, 20970, "Design: Pendant of the Agate Shield", 9, 1, 2, 300),
    row(207, 4410, "Schematic: Shadow Goggles", 9, 1, 2, 150),
    row(208, 5772, "Pattern: Red Woolen Bag", 9, 1, 2, 125),
]
BOXES = [
    row(301, 4633, "Heavy Bronze Lockbox", 15, 1, 2, 125),
    row(302, 4634, "Iron Lockbox", 15, 1, 2, 200),
    row(303, 4636, "Strong Iron Lockbox", 15, 1, 2, 300),
]
STOCK = [
    row(
        401, EMPTY_VIAL, "Empty Vial", 7, 25, 1, 1, reagent=True, profession_needed=True
    ),
    row(402, 765, "Silverleaf", 7, 20, 1, 5, reagent=True, profession_needed=True),
]
STALE_QUEST = [
    row(501, 3080, "Candle of Beckoning", 12, 1, 1, 0),
    row(502, 5382, "Anaya's Pendant", 12, 1, 1, 0),
    row(503, 6912, "Heartswood", 12, 3, 1, 0),
    row(504, 5810, "Fresh Carcass", 12, 1, 1, 0),
    row(505, 12236, "Pristine Enchanted South Seas Kelp", 12, 1, 1, 0),
]
OPEN_QUEST = [row(601, 20310, "Flayed Demon Skin", 12, 1, 1, 0, quest_item=True)]
# Not asked: sellable junk the vendor pass takes, and gear.
NOT_ASKED = [
    row(701, 4867, "Broken Scorpid Leg", 15, 3, 0, 22),
    row(702, 7527, "Cabalist Chestpiece", 4, 1, 2, 3000),
]
UGGA = GEMS + RECIPES + BOXES + STOCK + STALE_QUEST + OPEN_QUEST
ROWS = UGGA + NOT_ASKED

TEMPLATES = {
    **{r["entry"]: dict(bonding=0, stackable=20) for r in GEMS},
    2881: dict(bonding=0, stackable=1, required_skill=BLACKSMITHING, required_rank=35),
    7560: dict(bonding=0, stackable=1, required_skill=ENGINEERING, required_rank=125),
    5786: dict(bonding=0, stackable=1, required_skill=LEATHERWORKING, required_rank=90),
    4355: dict(bonding=0, stackable=1, required_skill=TAILORING, required_rank=200),
    10424: dict(
        bonding=0, stackable=1, required_skill=BLACKSMITHING, required_rank=130
    ),
    20970: dict(
        bonding=0, stackable=1, required_skill=JEWELCRAFTING, required_rank=120
    ),
    4410: dict(bonding=0, stackable=1, required_skill=ENGINEERING, required_rank=135),
    5772: dict(bonding=0, stackable=1, required_skill=TAILORING, required_rank=115),
    4633: dict(bonding=0, stackable=1, lock_id=60),
    4634: dict(bonding=0, stackable=1, lock_id=61),
    4636: dict(bonding=0, stackable=1, lock_id=62),
    EMPTY_VIAL: dict(bonding=0, stackable=20),
    765: dict(bonding=0, stackable=20),
    **{r["entry"]: dict(bonding=4, stackable=1) for r in STALE_QUEST + OPEN_QUEST},
}

SKILLS = {
    "Ugga": {HERBALISM: 210, ALCHEMY: 195},
    "Og": {TAILORING: 150, ENCHANTING: 140},
    "Bork": {SKINNING: 200, LEATHERWORKING: 60, LOCKPICKING: 250},
    "Grug": {MINING: 175, BLACKSMITHING: 20},
    "Grog": {MINING: 120, ENGINEERING: 1},
}
CLASSES = {
    "Ugga": (PRIEST, 60),
    "Og": (MAGE, 58),
    "Bork": (ROGUE, 58),
    "Grug": (WARRIOR, 60),
    "Grog": (PALADIN, 59),
}
NAMES = sorted(SKILLS)
FREE = {"Ugga": 0, "Og": 4, "Bork": 11, "Grug": 2, "Grog": 6}
# Empty Vial belongs to Alchemy through the craft tables (bridge.REAGENT_TRADES).
REAGENT_TRADES = {EMPTY_VIAL: ("alchemy",)}


def people():
    return [
        clearance.Person(name=n, skills=dict(SKILLS[n]), family=True, online=True)
        for n in NAMES
    ]


def holders():
    return {
        n: jev_keep.Holder(
            name=n,
            class_id=CLASSES[n][0],
            level=CLASSES[n][1],
            free_slots=FREE[n],
            skills=dict(SKILLS[n]),
        )
        for n in NAMES
    }


def routes():
    """What the shipped clearance and lockbox plans do with Ugga's stacks."""
    clear_rows = [
        dict(r, **TEMPLATES[r["entry"]]) for r in ROWS if r["item_class"] in (3, 9)
    ]
    clear = clearance.plan(clearance.stacks_from_rows(clear_rows), people())
    boxes = lockbox.boxes_from_rows(
        [dict(r, lock_id=TEMPLATES[r["entry"]]["lock_id"]) for r in BOXES]
    )
    pickers = [
        lockbox.Picker(n, CLASSES[n][0], SKILLS[n].get(LOCKPICKING, 0), FREE[n])
        for n in NAMES
    ]
    return jev_keep.routes_from_plans(clear, lockbox.plan(boxes, pickers, 3))


def asks(rows=None, market=None, mode=jev.SHADOW):
    return jev_keep.asks(
        jev_keep.protected(ROWS if rows is None else rows),
        templates=TEMPLATES,
        holders=holders(),
        people=people(),
        routes=routes(),
        market=market or {},
        reagent_trades=REAGENT_TRADES,
        mode=mode,
    )


def by_name(pending):
    return {j.item_name: (j, state, q) for j, state, q in pending}


def run(fake, key="k", environ=None, rows=None):
    client = jev.Client(key, transport=fake)
    rule = jev_keep.policy(environ or {})
    return asyncio.run(jev_keep.shadow_pass(client, asks(rows, mode=rule.mode), rule))


class WhichStacksTest(unittest.TestCase):
    def test_every_protected_non_gear_stack_is_asked_and_nothing_else(self):
        kept = jev_keep.protected(ROWS)
        self.assertEqual(
            sorted(r["item_guid"] for r in kept),
            sorted(r["item_guid"] for r in UGGA),
        )
        self.assertEqual(len(kept), 27)

    def test_the_counts_are_the_measured_ones(self):
        self.assertEqual(sum(r["count"] for r in GEMS), 48)
        self.assertEqual((len(RECIPES), len(BOXES)), (8, 3))
        self.assertEqual([r["count"] for r in STOCK], [25, 20])

    def test_protection_says_why_in_words(self):
        self.assertEqual(
            jev_keep.protection(STOCK[0]),
            ("it is a reagent", "a family trade uses it"),
        )
        self.assertEqual(
            jev_keep.protection(STALE_QUEST[0]), ("no vendor pays for it",)
        )
        self.assertIn("an open quest needs it", jev_keep.protection(OPEN_QUEST[0]))
        self.assertEqual(jev_keep.protection(GEMS[0]), ("it is uncommon quality",))
        self.assertEqual(jev_keep.protection(NOT_ASKED[0]), ())


class HeuristicTest(unittest.TestCase):
    def test_the_heuristic_is_what_the_shipped_passes_do(self):
        pending = by_name(asks())
        answers = {name: j.heuristic for name, (j, _s, _q) in pending.items()}
        # No jewelcrafter anywhere and no auction open: the vendor.
        self.assertEqual(answers["Malachite"], jev_keep.SELL)
        # Og tails at 150 and can learn the 115 bag pattern now.
        self.assertEqual(answers["Pattern: Red Woolen Bag"], "give:Og")
        # Bork picks every box at Lockpicking 250.
        for box in BOXES:
            self.assertEqual(answers[box["name"]], "give:Bork")
        # Her own alchemy stock, and quest leftovers, stay.
        self.assertEqual(answers["Empty Vial"], jev_keep.KEEP)
        self.assertEqual(answers["Silverleaf"], jev_keep.KEEP)
        self.assertEqual(answers["Candle of Beckoning"], jev_keep.KEEP)
        self.assertIn(
            "no vendor pays for it", pending["Candle of Beckoning"][0].heuristic_why
        )

    def test_a_stack_no_plan_routes_is_kept_with_its_protection(self):
        answer, why = jev_keep.heuristic(STOCK[1], {})
        self.assertEqual(answer, jev_keep.KEEP)
        self.assertEqual(why, "protected: it is a reagent; a family trade uses it")


class OptionsTest(unittest.TestCase):
    def offered(self, name):
        _j, _s, questions = by_name(asks())[name]
        return list(questions["route"]["criteria"])

    def test_a_bound_quest_leftover_can_only_be_kept_or_destroyed(self):
        self.assertEqual(
            self.offered("Candle of Beckoning"), [jev_keep.KEEP, jev_keep.DESTROY]
        )

    def test_trade_stock_can_be_kept_banked_sold_or_destroyed(self):
        self.assertEqual(
            self.offered("Empty Vial"),
            [jev_keep.KEEP, jev_keep.BANK, jev_keep.SELL, jev_keep.DESTROY],
        )

    def test_a_lockbox_may_go_to_the_rogue(self):
        self.assertIn("give:Bork", self.offered("Iron Lockbox"))

    def test_a_recipe_may_go_to_whoever_can_learn_it(self):
        self.assertIn("give:Og", self.offered("Pattern: Red Woolen Bag"))
        self.assertNotIn("give:Og", self.offered("Pattern: Icy Cloak"))

    def test_the_heuristics_answer_is_always_offered(self):
        for j, _s, questions in asks():
            self.assertIn(j.heuristic, questions["route"]["criteria"], j.item_name)


class FactsTest(unittest.TestCase):
    def test_jev_sees_the_holder_the_stack_and_who_can_use_it(self):
        _j, state, _q = by_name(asks(market={EMPTY_VIAL: 12}))["Empty Vial"]
        self.assertEqual(
            state["holder"],
            {
                "name": "Ugga",
                "class": "Priest",
                "level": 60,
                "free_bag_slots": 0,
                "trades": {"alchemy": 195, "herbalism": 210},
            },
        )
        item = state["item"]
        self.assertEqual((item["stack_size"], item["max_stack"]), (25, 20))
        self.assertEqual(item["vendor_price_each"], "1c")
        self.assertEqual(item["auction_price_each"], "12c")
        self.assertFalse(item["an_open_quest_needs_it"])
        self.assertEqual(item["used_by_trades"], ["alchemy"])
        self.assertTrue(item["holder_works_one_of_them"])
        self.assertEqual(state["who_else_can_use_it"], "nobody in the family or guild")

    def test_a_recipe_says_its_trade_and_that_the_holder_lacks_it(self):
        _j, state, _q = by_name(asks())["Pattern: Icy Cloak"]
        self.assertEqual(
            state["item"]["teaches"],
            {"trade": "tailoring", "skill_needed": 200, "holder_skill": 0},
        )
        self.assertEqual(state["item"]["auction_price_each"], "not known")

    def test_a_lockbox_names_the_rogue_who_can_pick_it(self):
        _j, state, _q = by_name(asks())["Strong Iron Lockbox"]
        [bork] = state["who_else_can_use_it"]
        self.assertEqual(bork["name"], "Bork")
        self.assertIn("Lockpicking 250", bork["why"])

    def test_an_open_quest_item_says_so(self):
        _j, state, _q = by_name(asks())["Flayed Demon Skin"]
        self.assertTrue(state["item"]["an_open_quest_needs_it"])

    def test_the_facts_are_recorded_within_the_column(self):
        for j, _s, _q in asks():
            self.assertTrue(j.facts.startswith("{"), j.item_name)
            self.assertLessEqual(len(j.facts), 1000)
            self.assertIn('"free_bag_slots":0', j.facts)


class ShadowTest(unittest.TestCase):
    def test_every_stack_gets_a_shadow_judgment_and_the_heuristic_acts(self):
        fake = FakeJev(picks={"route": jev_keep.DESTROY}, confidence=0.99)
        judgments = run(fake)
        self.assertEqual(len(judgments), len(UGGA))
        self.assertEqual(len(fake.requests), len(UGGA))
        for j in judgments:
            self.assertEqual(j.kind, "item_keep")
            self.assertEqual(j.mode, jev.SHADOW)
            self.assertEqual(j.jev, jev_keep.DESTROY)
            self.assertEqual(j.acted, jev.HEURISTIC)
            self.assertFalse(j.agree)
            self.assertIn("kind=item_keep", j.line())

    def test_act_is_refused_until_a_route_can_act(self):
        environ = {"JEV_MODE_ITEM_KEEP": "act", "JEV_THRESHOLD_ITEM_KEEP": "0.5"}
        with self.assertLogs("wow-overseer.jev", "WARNING") as said:
            rule = jev_keep.policy(environ)
        self.assertEqual(rule.mode, jev.SHADOW)
        self.assertEqual(rule.threshold, 0.5)
        self.assertIn("no act path is built for item_keep", said.output[0])
        judgments = run(FakeJev(confidence=0.99), environ=environ)
        self.assertTrue(all(j.acted == jev.HEURISTIC for j in judgments))

    def test_the_default_is_shadow_at_the_default_threshold(self):
        rule = jev_keep.policy({})
        self.assertEqual((rule.mode, rule.threshold), (jev.SHADOW, 0.85))

    def test_off_asks_nothing(self):
        fake = FakeJev()
        self.assertEqual(run(fake, environ={"JEV_MODE_ITEM_KEEP": "off"}), [])
        self.assertEqual(fake.requests, [])

    def test_no_key_asks_nothing_and_records_why(self):
        fake = FakeJev()
        judgments = run(fake, key="")
        self.assertEqual(fake.requests, [])
        self.assertTrue(all(j.status == jev.NO_KEY and not j.jev for j in judgments))

    def test_the_summary_line_is_the_kinds_own(self):
        judgments = run(FakeJev(picks={"route": jev_keep.KEEP}), rows=STOCK)
        line = jev_keep.summary(judgments, 27, 8, 180 * 60)
        self.assertEqual(
            line,
            "jev-keep: asked 2 of 27 protected non-gear stack(s), 2 answered, "
            "2 agree, 0 differ (limit 8, every 180 min)",
        )


class RateLimitTest(unittest.TestCase):
    def test_a_full_bag_is_asked_a_few_stacks_a_pass_each_once_per_interval(self):
        kept = jev_keep.protected(ROWS)
        asked: dict = {}
        seen = []
        for n in range(4):
            now = 90.0 * n
            batch = jev_keep.due(kept, asked, now, 3600, 8)
            for r in batch:
                asked[(r["holder"], r["item_guid"])] = now
            seen.append([r["item_guid"] for r in batch])
        self.assertEqual([len(b) for b in seen], [8, 8, 8, 3])
        flat = [g for b in seen for g in b]
        self.assertEqual(len(flat), len(set(flat)))
        self.assertEqual(jev_keep.due(kept, asked, 360.0, 3600, 8), [])
        again = jev_keep.due(kept, asked, 3600.0, 3600, 8)
        self.assertEqual([r["item_guid"] for r in again], seen[0])

    def test_the_knobs_default_and_refuse_nonsense(self):
        self.assertEqual(jev_keep.knobs({}), (8, 180 * 60))
        self.assertEqual(
            jev_keep.knobs(
                {"JEV_ITEM_KEEP_LIMIT": "3", "JEV_ITEM_KEEP_INTERVAL_MINUTES": "10"}
            ),
            (3, 600),
        )
        self.assertEqual(
            jev_keep.knobs(
                {"JEV_ITEM_KEEP_LIMIT": "x", "JEV_ITEM_KEEP_INTERVAL_MINUTES": "-5"}
            ),
            (8, 180 * 60),
        )


class ViewTest(unittest.TestCase):
    def rows(self):
        base = dict(
            kind="item_keep",
            subject="Ugga",
            status="answered",
            mode="shadow",
            acted="heuristic",
        )
        return [
            dict(base, item_name="Malachite", heuristic="sell", jev="bank", agree=0,
                 confidence=0.61),
            dict(base, item_name="Empty Vial", heuristic="keep", jev="keep", agree=1,
                 confidence=0.9),
            dict(base, item_name="Jade", heuristic="sell", jev="", agree=None,
                 confidence=None, status="timeout"),
            dict(kind="weapon_choice", subject="Grog", item_name="Destiny",
                 heuristic="worn", jev="carried", agree=0, confidence=0.9,
                 status="answered", mode="act", acted="jev"),
        ]  # fmt: skip

    def test_only_disagreements_are_listed_and_the_card_keeps_its_other_kinds(self):
        out = jevview.view(self.rows())
        self.assertEqual(
            out["keep_differ"],
            ["Ugga, Malachite: heuristic sell, Jev bank at 0.61 (shadow)."],
        )
        self.assertEqual(len(out["recent"]), 1)
        self.assertIn("Weapon choice", out["recent"][0])
        self.assertIn("protected non-gear item, shadow", " ".join(out["kinds"]))

    def test_nothing_to_list_is_said(self):
        out = jevview.view([])
        self.assertEqual(out["keep_differ"], [])
        self.assertTrue(out["keep_empty"])

    def test_the_page_draws_the_list_as_text(self):
        fn = PAGE[PAGE.index("function dcrRenderJev(j) {") :]
        fn = fn[: fn.index("\n}\n")]
        for key in ("j.keep_title", "j.keep_differ", "j.keep_empty"):
            self.assertIn(key, fn)
        self.assertIn('id="dcrjevkeep"', PAGE)


class BridgeTest(unittest.TestCase):
    def body(self, name):
        fn = BRIDGE[BRIDGE.index("    def %s(" % name) :]
        return fn[: fn.index("\n    def ", 10)]

    def test_the_protection_pass_asks_after_its_plans_and_before_the_hand_offs(self):
        at = BRIDGE.index("self._jev_keep_shadow(names, leader, rows, clear, locks")
        self.assertLess(BRIDGE.index("clear_sales = _clearance_sales(clear)"), at)
        self.assertLess(at, BRIDGE.index("await self._hand_recipes(names, free_slots)"))

    def test_nothing_waits_on_the_answer_and_the_limits_are_read(self):
        body = self.body("_jev_keep_shadow")
        self.assertNotIn("asyncio.wait", body)
        self.assertNotIn("await ", body.split("async def run()")[0])
        self.assertIn("jev_keep.knobs(os.environ)", body)
        self.assertIn("jev_keep.due(", body)
        self.assertIn("self._jev_record(judgments", body)

    def test_the_judgments_carry_their_facts_to_the_record(self):
        insert = BRIDGE[BRIDGE.index("def _insert_jev_judgment(") :]
        insert = insert[: insert.index("\n\n\n")]
        self.assertIn('getattr(judgment, "facts", "")', insert)
        j, _s, _q = asks(rows=STOCK)[0]
        self.assertTrue(j.facts)


if __name__ == "__main__":
    unittest.main()
