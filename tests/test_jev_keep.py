"""Jev asked about protected non-gear items (#232), acting on bank and give (#267).

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

import bag_pressure
import bank
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
    return jev_keep.routes_from_plans(
        clear,
        lockbox.plan(boxes, pickers, 3),
        destroys=bag_pressure.destroy_candidates(ROWS),
    )


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


# Two stacks the protection keeps that Jev may act on (#267). Linen Cloth is
# tailoring stock Ugga does not work and Og does; Star Wood is jewelcrafting
# stock nobody in the family works.
STAR_WOOD = 9901
LINEN = row(
    801, 2589, "Linen Cloth", 7, 20, 1, 13, reagent=True, profession_needed=True
)
STAR = row(802, STAR_WOOD, "Star Wood", 7, 5, 1, 25, reagent=True)
TEMPLATES[2589] = dict(bonding=0, stackable=20)
TEMPLATES[STAR_WOOD] = dict(bonding=0, stackable=20)
REAGENT_TRADES[STAR_WOOD] = ("jewelcrafting",)


def by_name(pending):
    return {j.item_name: (j, state, q) for j, state, q in pending}


def run(fake, key="k", environ=None, rows=None):
    client = jev.Client(key, transport=fake)
    rule = jev_keep.policy(environ or {})
    return asyncio.run(
        jev_keep.shadow_pass(client, asks(rows, mode=rule.mode), rule, environ or {})
    )


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
        # Her own alchemy stock, and the quest item an open quest needs, stay.
        self.assertEqual(answers["Empty Vial"], jev_keep.KEEP)
        self.assertEqual(answers["Silverleaf"], jev_keep.KEEP)
        self.assertEqual(answers["Flayed Demon Skin"], jev_keep.KEEP)
        self.assertIn(
            "an open quest needs it", pending["Flayed Demon Skin"][0].heuristic_why
        )

    def test_the_destroy_pass_takes_the_released_quest_leftovers(self):
        """#267: the destroy pass (#243) queues these, so the heuristic's
        answer is destroy, not keep. Recorded as keep, every confident destroy
        Jev gave on the dev realm read as a disagreement."""
        pending = by_name(asks())
        for stale in STALE_QUEST:
            j = pending[stale["name"]][0]
            self.assertEqual(j.heuristic, jev_keep.DESTROY, stale["name"])
            self.assertIn("destroy pass", j.heuristic_why)

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


SHADOW = {"JEV_MODE_ITEM_KEEP": "shadow"}


class ShadowTest(unittest.TestCase):
    def test_in_shadow_every_stack_is_judged_and_the_heuristic_acts(self):
        fake = FakeJev(picks={"route": jev_keep.DESTROY}, confidence=0.99)
        judgments = run(fake, environ=SHADOW)
        self.assertEqual(len(judgments), len(UGGA))
        self.assertEqual(len(fake.requests), len(UGGA))
        for j in judgments:
            self.assertEqual(j.kind, "item_keep")
            self.assertEqual(j.mode, jev.SHADOW)
            self.assertEqual(j.jev, jev_keep.DESTROY)
            self.assertEqual(j.acted, jev.HEURISTIC)
            self.assertIn("kind=item_keep", j.line())

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
            "2 agree, 0 differ, 0 carried out as Jev's (limit 8, every 180 min)",
        )


def judged(rows, pick, confidence, environ=None):
    """Each stack in `rows` judged with Jev answering `pick`."""
    return {
        j.item_name: j
        for j in run(
            FakeJev(picks={"route": pick}, confidence=confidence),
            environ=environ,
            rows=rows,
        )
    }


class ActTest(unittest.TestCase):
    """#267: bank and give act; sell and destroy never do."""

    def test_the_default_is_act_with_a_floor_per_route(self):
        rule = jev_keep.policy({})
        self.assertEqual(rule.mode, jev.ACT)
        self.assertEqual(jev_keep.route_rule(rule, jev_keep.BANK).threshold, 0.6)
        self.assertEqual(jev_keep.route_rule(rule, "give:Og").threshold, 0.6)
        self.assertEqual(jev_keep.route_rule(rule, jev_keep.SELL).threshold, 0.85)

    def test_each_route_floor_is_its_own_switch(self):
        env = {"JEV_THRESHOLD_ITEM_KEEP_BANK": "0.9"}
        rule = jev_keep.policy(env)
        self.assertEqual(jev_keep.route_rule(rule, "bank", env).threshold, 0.9)
        self.assertEqual(jev_keep.route_rule(rule, "give:Og", env).threshold, 0.6)
        [j] = judged([STAR], jev_keep.BANK, 0.7, env).values()
        self.assertEqual(j.acted, jev.HEURISTIC)

    def test_stock_nobody_in_the_family_works_is_banked(self):
        [j] = judged([STAR], jev_keep.BANK, 0.62).values()
        self.assertEqual((j.heuristic, j.jev, j.acted), ("keep", "bank", jev.JEV))

    def test_below_the_floor_the_protection_keeps_it(self):
        [j] = judged([STAR], jev_keep.BANK, 0.59).values()
        self.assertEqual(j.acted, jev.HEURISTIC)

    def test_stock_a_family_member_works_is_never_banked_but_may_be_given(self):
        [bank_j] = judged([LINEN], jev_keep.BANK, 0.95).values()
        self.assertEqual(bank_j.acted, jev.HEURISTIC)
        [give_j] = judged([LINEN], "give:Og", 0.7).values()
        self.assertEqual((give_j.jev, give_j.acted), ("give:Og", jev.JEV))

    def test_the_holders_own_trade_stock_is_never_banked(self):
        """Ugga works alchemy, so her vials stay whatever Jev says."""
        for j in judged(STOCK, jev_keep.BANK, 0.99).values():
            self.assertEqual(j.acted, jev.HEURISTIC, j.item_name)

    def test_ugga_loses_nothing_irreversible_and_no_plan_is_overridden(self):
        """The fixture the issue named: at 0.99, Jev's destroy and sell never
        act, an open quest's item stays, and the lockboxes' and recipes' own
        plans are never replaced by a bank."""
        for pick in (jev_keep.DESTROY, jev_keep.SELL, jev_keep.BANK):
            for j in judged(None, pick, 0.99).values():
                self.assertNotEqual(j.acted, jev.JEV, (pick, j.item_name))

    def test_an_act_becomes_an_order_and_nothing_else_does(self):
        judgments = list(judged([STAR, LINEN], jev_keep.BANK, 0.7).values())
        [order] = jev_keep.orders_from(judgments, now=5.0)
        self.assertEqual(
            (order.holder, order.guid, order.route, order.count, order.at),
            ("Ugga", 802, jev_keep.BANK, 5, 5.0),
        )
        self.assertEqual(
            order.said(),
            "jev-keep: acting on Ugga's 5 Star Wood: bank to the guild bank "
            "(conf 0.70)",
        )


def order(guid=802, route=jev_keep.BANK, taker="", count=5, at=0.0, holder="Ugga"):
    return jev_keep.Order(
        holder=holder,
        guid=guid,
        entry=STAR_WOOD,
        name="Star Wood",
        count=count,
        route=route,
        taker=taker,
        confidence=0.7,
        at=at,
    )


class OrderTest(unittest.TestCase):
    def test_an_order_lives_only_while_its_stack_is_carried_unchanged(self):
        orders = {
            ("Ugga", 802): order(),
            ("Ugga", 803): order(guid=803),
            ("Ugga", 804): order(guid=804),
            ("Ugga", 805): order(guid=805, at=-4000.0),
            ("Og", 806): order(guid=806, holder="Og"),
        }
        rows = [
            dict(holder="Ugga", item_guid=802, count=5),
            dict(holder="Ugga", item_guid=804, count=2),
            dict(holder="Ugga", item_guid=805, count=5),
            dict(holder="Og", item_guid=806, count=5),
        ]
        live, dropped = jev_keep.live_orders(orders, rows, 60.0, names={"Ugga"})
        self.assertEqual([o.guid for o in live], [802])
        self.assertEqual(
            sorted((o.guid, why) for o, why in dropped),
            [
                (803, "no longer carried (done, or moved on)"),
                (804, "the stack changed size"),
                (805, "older than 60 minutes"),
            ],
        )

    def test_a_give_order_is_a_guild_gift(self):
        [gift] = jev_keep.gifts([order(route=jev_keep.GIVE, taker="Og"), order()])
        self.assertEqual((gift.holder, gift.taker, gift.guid), ("Ugga", "Og", 802))
        self.assertEqual(gift.count, 5)

    def test_a_bank_order_is_a_guild_deposit_within_the_bank_passs_gates(self):
        planned = (bank.Move("Ugga", bank.DEPOSIT, 803, "x", 1, "keeper", bank.GUILD),)
        orders = [
            order(),
            order(guid=803),
            order(guid=804),
            order(guid=805, holder="Og"),
        ]
        moves, notes = jev_keep.deposits(orders, {"Ugga"}, 1, planned)
        [move] = moves
        self.assertEqual((move.character, move.guid, move.to), ("Ugga", 802, "guild"))
        self.assertEqual(bank.command(move), "bank deposit-item guid:802")
        self.assertEqual(
            notes,
            [
                "the guild bank's tab is full; Star Wood stays",
                "Og's rank cannot deposit Star Wood",
            ],
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
        at = BRIDGE.find("    def %s(" % name)
        if at < 0:
            at = BRIDGE.index("    async def %s(" % name)
        fn = BRIDGE[at:]
        ends = [fn.find(m, 10) for m in ("\n    def ", "\n    async def ")]
        return fn[: min(e for e in ends if e > 0)]

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

    def test_the_destroy_pass_is_read_as_the_heuristics_answer(self):
        body = self.body("_jev_keep_shadow")
        self.assertIn("destroys=bag_pressure.destroy_candidates(rows", body)

    def test_an_act_is_kept_as_an_order_and_said(self):
        body = self.body("_jev_keep_shadow")
        self.assertIn("jev_keep.orders_from(judgments", body)
        self.assertIn("self._jev_keep_orders[order.key] = order", body)

    def test_gives_ride_the_guild_gift_writer_after_the_clearance(self):
        at = BRIDGE.index("await self._jev_keep_give(names, rows)")
        self.assertLess(BRIDGE.index("await self._route_clearance(names, leader"), at)
        self.assertIn("self._write_guild_gifts(gifts)", self.body("_jev_keep_give"))

    def test_banks_ride_the_guild_bank_items_before_its_walk_is_decided(self):
        body = self.body("_guild_bank_once")
        at = body.index("self._jev_keep_deposits(names, setup, items)")
        self.assertLess(body.index("_plan_bank, names)).guild"), at)
        self.assertLess(at, body.index("if not actions and not deposits and not items"))
        self.assertLess(at, body.index("_fetch_positions, sorted({leader}"))

    def test_the_judgments_carry_their_facts_to_the_record(self):
        insert = BRIDGE[BRIDGE.index("def _insert_jev_judgment(") :]
        insert = insert[: insert.index("\n\n\n")]
        self.assertIn('getattr(judgment, "facts", "")', insert)
        j, _s, _q = asks(rows=STOCK)[0]
        self.assertTrue(j.facts)


if __name__ == "__main__":
    unittest.main()
