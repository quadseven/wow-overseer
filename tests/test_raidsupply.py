"""The Molten Core supply (#275): targets, the corps' steps, the budget, Jev.

Pure unit tests against raidsupply.py, plus source checks on the bridge pass,
the Raid tab and the page. The fixtures are the dev realm as measured on
2026-09-23: alchemists at 300 who know Major Healing Potion and nothing
pattern-taught, herbs scattered across the guild, no Greater Fire Protection
Potion anywhere, and a guild bank of about 804 gold that only the guild master
may draw on.
"""

import asyncio
import pathlib
import unittest

import auction
import guildcorps as gc
import jev
import raidready
import raidsupply as rs

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

KALIMDOR = 1
VIAL = 8925
HEALING_SPELL = 17556
MANA_SPELL = 17580
MANA_RECIPE = 13501
FIRE_RECIPE = 13494


def member(name, guild="Cave", **over):
    base = dict(
        name=name,
        guild=guild,
        class_id=8,
        level=60,
        online=True,
        map_id=KALIMDOR,
        maintenance=True,
    )
    base.update(over)
    return gc.Member(**base)


def held(guid, entry, count):
    return gc.Held(guid, entry, count)


def raider(name, role, class_id, **over):
    return rs.Raider(name=name, role=role, class_id=class_id, **over)


# A small raid: the main tank, a second tank, a priest healer, a rogue, a
# hunter and a mage.
RAIDERS = (
    raider("Grug", rs.TANK, rs.WARRIOR, main_tank=True, family=True, fire=10),
    raider("Anneve", rs.TANK, rs.WARRIOR),
    raider("Aylysae", rs.HEALER, rs.PRIEST),
    raider("Atherene", rs.PHYSICAL, rs.ROGUE),
    raider("Arran", rs.PHYSICAL, rs.HUNTER),
    raider("Alindy", rs.CASTER, rs.MAGE),
)
ALCHEMIST = gc.Post("Oden", "alchemist", gc.ALCHEMY, 300, 375)


def facts(members, raiders=RAIDERS, posts=(ALCHEMIST,), vendors=None):
    return rs.GuildFacts(
        "Cave", tuple(members), tuple(raiders), tuple(posts), vendors or {}
    )


def alchemist(**over):
    over.setdefault("known", frozenset({HEALING_SPELL}))
    over.setdefault("skills", {gc.ALCHEMY: (300, 375)})
    return member("Oden", **over)


def raider_members():
    return [
        member(r.name, maintenance=False, family=r.family, class_id=r.class_id)
        for r in RAIDERS
    ]


class TheNightsTargets(unittest.TestCase):
    def test_each_role_wants_its_own_potions(self):
        wants = rs.night_wants(RAIDERS)
        fire = wants[rs.GREATER_FIRE_PROTECTION]
        self.assertEqual(fire["Grug"], 4)
        self.assertEqual(fire["Aylysae"], 2)
        mana = wants[rs.MAJOR_MANA]
        self.assertEqual(mana["Aylysae"], 5)
        self.assertEqual(mana["Alindy"], 3)
        # A hunter spends mana; a rogue and a warrior do not.
        self.assertEqual(mana["Arran"], rs.MANA_FOR_PHYSICAL)
        self.assertNotIn("Atherene", mana)
        self.assertNotIn("Grug", mana)
        self.assertEqual(wants[13510], {"Grug": 1, "Anneve": 1})  # Flask of the Titans
        self.assertEqual(wants[13512], {"Alindy": 1})  # Flask of Supreme Power
        self.assertIn("Atherene", wants[13452])  # Elixir of the Mongoose
        self.assertNotIn("Alindy", wants[13452])

    def test_fire_resistance_targets_put_the_ragnaros_tank_first(self):
        lines = rs.fire_lines(RAIDERS)
        self.assertEqual([f.raider.name for f in lines], ["Grug", "Anneve", "Aylysae"])
        self.assertEqual([f.target for f in lines], [200, 120, 60])
        self.assertEqual(lines[0].short, 190)

    def test_the_first_tank_the_lineup_placed_is_the_main_tank(self):
        lineup = {
            "groups": [
                {
                    "members": [
                        {"name": "Grug", "role": "tank"},
                        {"name": "Aylysae", "role": "healer"},
                    ]
                },
                {
                    "members": [
                        {"name": "Anneve", "role": "tank"},
                        {"name": "Alindy", "role": "dps"},
                    ]
                },
            ]
        }
        worn = [
            {"name": "Grug", "slot": 6, "fire_res": 7},
            {"name": "Grug", "slot": 14, "fire_res": 3},
        ]
        out = rs.raiders_from_lineup(
            lineup, {"Grug": 1, "Aylysae": 5, "Anneve": 1, "Alindy": 8}, worn, ["Grug"]
        )
        by = {r.name: r for r in out}
        self.assertTrue(by["Grug"].main_tank)
        self.assertFalse(by["Anneve"].main_tank)
        self.assertEqual(by["Grug"].fire, 10)
        self.assertEqual(by["Grug"].slot_fire(6), 7)
        self.assertEqual(by["Alindy"].role, rs.CASTER)
        self.assertTrue(by["Grug"].family)


class HowEachSupplyCloses(unittest.TestCase):
    def test_a_recipe_nobody_knows_and_no_vendor_sells_is_bought(self):
        lines = {line.entry: line for line in rs.supply_lines(RAIDERS, {}, {})}
        self.assertEqual(lines[rs.GREATER_FIRE_PROTECTION].route, rs.BUY)
        self.assertIn("Lower Blackrock Spire", lines[rs.GREATER_FIRE_PROTECTION].said)
        self.assertEqual(lines[12451].route, rs.BUY)  # Juju Power: nothing makes it

    def test_a_known_recipe_is_made_and_a_vendor_recipe_is_bought_first(self):
        lines = {
            line.entry: line
            for line in rs.supply_lines(
                RAIDERS, {}, {HEALING_SPELL: ["Oden"]}, vendor_recipes={MANA_RECIPE}
            )
        }
        self.assertEqual(lines[rs.MAJOR_HEALING].route, rs.MAKE)
        self.assertEqual(lines[rs.MAJOR_MANA].route, rs.VENDOR_RECIPE)

    def test_stock_counts_against_the_want(self):
        want = sum(rs.night_wants(RAIDERS)[rs.MAJOR_HEALING].values())
        lines = {
            line.entry: line
            for line in rs.supply_lines(RAIDERS, {rs.MAJOR_HEALING: want}, {})
        }
        self.assertEqual(lines[rs.MAJOR_HEALING].short, 0)
        self.assertEqual(lines[rs.MAJOR_HEALING].said, "stocked for the night")


class TheCorpsSteps(unittest.TestCase):
    def plan(self, members, busy=None, recent=None, focus="", **over):
        busy = set() if busy is None else busy
        return rs.plan_guild(facts(members, **over), recent or {}, busy, focus=focus)

    def test_an_alchemist_with_the_herbs_and_vials_crafts_major_healing(self):
        oden = alchemist(
            carried=(held(1, 13464, 6), held(2, 13465, 3), held(3, VIAL, 3))
        )
        plan = self.plan([oden, *raider_members()])
        step = next(s for s in plan.steps if s.holder == "Oden")
        self.assertEqual(step.action, "craft")
        self.assertEqual(step.rows[0].command, str(HEALING_SPELL))
        self.assertEqual(step.rows[0].source, "raidsupply:craft:17556")
        self.assertEqual(step.repeat, 3)

    def test_a_finished_stack_goes_to_the_main_tank_first(self):
        oden = alchemist(carried=(held(9, rs.MAJOR_HEALING, 4),))
        plan = self.plan([oden, *raider_members()])
        step = next(s for s in plan.steps if s.holder == "Oden")
        self.assertEqual(step.action, "post")
        self.assertEqual(step.rows[0].target_arg, "Grug")
        self.assertTrue(step.rows[0].command.startswith("send item:9 "))
        self.assertTrue(step.walk.command.startswith("walk-to-mailbox"))

    def test_herbs_come_by_post_from_guildmates_off_the_family(self):
        oden = alchemist()
        herbalist = member("Hebus", carried=(held(20, 13464, 9),))
        family_herbs = member(
            "Ugga", family=True, maintenance=False, carried=(held(21, 13464, 20),)
        )
        plan = self.plan([oden, herbalist, family_herbs, *raider_members()])
        letters = [s for s in plan.steps if s.action == "supply"]
        self.assertEqual([s.holder for s in letters], ["Hebus"])
        self.assertEqual(letters[0].rows[0].target_arg, "Oden")
        self.assertEqual(letters[0].rows[0].source, "raidsupply:supply:13464")

    def test_with_the_herbs_in_hand_it_buys_vials_at_a_vendor(self):
        oden = alchemist(carried=(held(1, 13464, 4), held(2, 13465, 2)))
        plan = self.plan(
            [oden, *raider_members()], vendors={KALIMDOR: frozenset({VIAL})}
        )
        step = next(s for s in plan.steps if s.holder == "Oden")
        self.assertEqual(step.action, "buy")
        self.assertTrue(step.rows[0].command.startswith("entry:8925 count:2 "))
        self.assertTrue(step.walk.command.startswith("walk-to-vendor item:8925"))

    def test_a_carried_recipe_is_learned_before_anything_is_bought(self):
        oden = alchemist(known=frozenset(), carried=(held(5, FIRE_RECIPE, 1),))
        plan = self.plan([oden, *raider_members()])
        step = next(s for s in plan.steps if s.holder == "Oden")
        self.assertEqual(step.action, "learn")
        self.assertEqual(step.rows[0].command, "use guid:5")

    def test_a_vendor_sold_recipe_is_bought(self):
        oden = alchemist(known=frozenset())
        plan = self.plan(
            [oden, *raider_members()], vendors={KALIMDOR: frozenset({MANA_RECIPE})}
        )
        step = next(s for s in plan.steps if s.holder == "Oden")
        self.assertEqual(step.action, "buy")
        self.assertTrue(
            step.rows[0].command.startswith("entry:13501 count:1 max:37500")
        )

    def test_a_busy_or_cooling_alchemist_takes_no_step(self):
        oden = alchemist(
            carried=(held(1, 13464, 6), held(2, 13465, 3), held(3, VIAL, 3))
        )
        busy = {"Oden"}
        plan = self.plan([oden, *raider_members()], busy=busy)
        self.assertFalse([s for s in plan.steps if s.holder == "Oden"])
        recent = {("Oden", "craft", HEALING_SPELL): 1}
        plan = self.plan([oden, *raider_members()], recent=recent)
        self.assertFalse([s for s in plan.steps if s.holder == "Oden"])

    def test_the_plan_marks_whoever_it_sends_as_busy(self):
        oden = alchemist(
            carried=(held(1, 13464, 6), held(2, 13465, 3), held(3, VIAL, 3))
        )
        busy = set()
        self.plan([oden, *raider_members()], busy=busy)
        self.assertIn("Oden", busy)

    def test_only_the_corps_alchemist_crafts(self):
        stranger = member(
            "Hebus",
            known=frozenset({HEALING_SPELL}),
            carried=(held(1, 13464, 6), held(2, 13465, 3), held(3, VIAL, 3)),
        )
        plan = self.plan([stranger, *raider_members()])
        self.assertFalse(
            [s for s in plan.steps if s.holder == "Hebus" and s.action == "craft"]
        )

    def test_the_focus_goes_first(self):
        oden = alchemist(
            known=frozenset({HEALING_SPELL, MANA_SPELL}),
            carried=(
                held(1, 13464, 6),
                held(2, 13465, 3),
                held(3, VIAL, 6),
                held(4, 13463, 9),
                held(5, 13467, 6),
            ),
        )
        plan = self.plan([oden, *raider_members()], focus="make:%d" % rs.MAJOR_MANA)
        step = next(s for s in plan.steps if s.holder == "Oden")
        self.assertEqual(step.rows[0].command, str(MANA_SPELL))


class StockIsRoutedBeforeMoreIsMade(unittest.TestCase):
    def test_a_member_off_the_raid_posts_the_potions_it_carries(self):
        keeper = member("Behodiir", carried=(held(55, rs.MAJOR_HEALING, 2),))
        plan = rs.plan_guild(facts([keeper, *raider_members()]), {}, set())
        step = next(s for s in plan.steps if s.holder == "Behodiir")
        self.assertEqual(step.action, "post")
        self.assertEqual(step.rows[0].target_arg, "Grug")

    def test_a_family_member_or_a_raider_keeps_what_it_carries(self):
        people = raider_members()
        people[1] = member(
            "Anneve",
            maintenance=False,
            class_id=rs.WARRIOR,
            carried=(held(56, rs.MAJOR_HEALING, 9),),
        )
        ugga = member(
            "Ugga",
            family=True,
            maintenance=False,
            carried=(held(57, rs.MAJOR_HEALING, 9),),
        )
        plan = rs.plan_guild(facts([*people, ugga]), {}, set())
        self.assertFalse([s for s in plan.steps if s.action == "post"])

    def test_the_note_names_the_missing_reagent(self):
        tailor = member("Baldam", known=frozenset({18421}))
        post = gc.Post("Baldam", "tailor", gc.TAILORING, 300, 300)
        plan = rs.plan_guild(
            facts([tailor, *raider_members()], posts=(post,)), {}, set()
        )
        self.assertIn(
            "Baldam knows Wizardweave Leggings, but nobody in the guild holds Bolt of Runecloth or Dream Dust",
            plan.notes,
        )


class TheRaidersSteps(unittest.TestCase):
    def test_a_raider_off_the_family_collects_the_corps_letters(self):
        letter = gc.Letter(77, 88, rs.MAJOR_HEALING, 4, True)
        people = [
            member("Anneve", maintenance=False, class_id=rs.WARRIOR, mail=(letter,))
        ]
        plan = rs.plan_guild(facts(people), {}, set())
        step = plan.steps[0]
        self.assertEqual(step.action, "collect")
        self.assertEqual(step.rows[0].command, "take-item mail:77 item:88")

    def test_a_family_raider_is_left_to_the_family_mail_pass(self):
        letter = gc.Letter(77, 88, rs.MAJOR_HEALING, 4, True)
        people = [
            member(
                "Grug",
                family=True,
                maintenance=False,
                class_id=rs.WARRIOR,
                mail=(letter,),
            )
        ]
        plan = rs.plan_guild(facts(people), {}, set())
        self.assertFalse(plan.steps)

    def test_a_cloth_healer_puts_on_the_fire_leggings_it_carries(self):
        people = [
            member(
                "Aylysae",
                maintenance=False,
                class_id=rs.PRIEST,
                carried=(held(40, 14132, 1),),
            )
        ]
        plan = rs.plan_guild(facts(people), {}, set())
        step = plan.steps[0]
        self.assertEqual(step.action, "equip")
        self.assertEqual(step.rows[0].kind, "bot")
        self.assertEqual(step.rows[0].command, "e Hitem:14132:0")

    def test_a_warrior_is_not_put_in_cloth(self):
        people = [
            member(
                "Anneve",
                maintenance=False,
                class_id=rs.WARRIOR,
                carried=(held(40, 14132, 1),),
            )
        ]
        plan = rs.plan_guild(facts(people), {}, set())
        self.assertFalse([s for s in plan.steps if s.action == "equip"])


class TheBudget(unittest.TestCase):
    def test_a_tenth_of_the_bank_capped_at_a_hundred_gold(self):
        self.assertEqual(rs.daily_budget(8_046_728), 804_672)
        self.assertEqual(rs.daily_budget(50_000_000), rs.BUDGET_CAP_COPPER)
        self.assertEqual(rs.daily_budget(0), 0)

    def test_the_ledger_reads_only_the_masters_rows(self):
        rows = [
            {
                "target_name": "Grug",
                "command": "bank withdraw 50000",
                "source": rs.WITHDRAW_SOURCE,
                "status": "applied",
            },
            {
                "target_name": "Grug",
                "command": "bank withdraw 50000",
                "source": rs.WITHDRAW_SOURCE,
                "status": "error",
            },
            {
                "target_name": "Ugga",
                "command": "bank withdraw 90000",
                "source": rs.WITHDRAW_SOURCE,
                "status": "applied",
            },
            {
                "target_name": "Grug",
                "command": "buy 5",
                "source": rs.ah_source(13457, 12000),
                "status": "pending",
            },
            {
                "target_name": "Grug",
                "command": "buy 6",
                "source": rs.ah_source(13457, 30000),
                "status": "error",
            },
        ]
        self.assertEqual(rs.ledger(rows, "Grug"), (50_000, 12_000))
        self.assertEqual(rs.reserve(50_000, 12_000), 38_000)

    def test_a_withdrawal_is_what_the_listings_cost_within_the_budget(self):
        copper, why = rs.withdrawal(8_046_728, 0, 0, 120_000)
        self.assertEqual(copper, 120_000)
        copper, _ = rs.withdrawal(8_046_728, 800_000, 0, 120_000)
        self.assertEqual(copper, 0)  # only 4,672 of today's budget is left
        copper, why = rs.withdrawal(8_046_728, 0, 0, 0)
        self.assertEqual(copper, 0)
        self.assertIn("nothing the raid needs is listed", why)
        copper, why = rs.withdrawal(8_046_728, 200_000, 50_000, 120_000)
        self.assertEqual(copper, 0)
        self.assertIn("still carries", why)
        copper, _ = rs.withdrawal(0, 0, 0, 120_000)
        self.assertEqual(copper, 0)  # Bonkers' bank is empty

    def test_the_guild_bank_pass_leaves_the_raid_gold_in_the_masters_purse(self):
        rows = [
            {
                "target_name": "Grug",
                "command": "bank withdraw 50000",
                "source": rs.WITHDRAW_SOURCE,
                "status": "applied",
            }
        ]
        out = rs.hold_back(
            [{"name": "Grug", "money": 80_000}, {"name": "Ugga", "money": 80_000}], rows
        )
        self.assertEqual([r["money"] for r in out], [30_000, 80_000])

    def test_the_master_buys_cheapest_first_and_never_past_the_reserve(self):
        plan = rs.plan_guild(facts([*raider_members()]), {}, set())
        needs = rs.market_needs(plan, "Grug")
        entries = [n.entry for n in needs]
        self.assertEqual(entries[:2], [rs.GREATER_FIRE_PROTECTION, FIRE_RECIPE])
        self.assertTrue(all(n.shopper == "Grug" for n in needs))
        listings = [
            auction.Listing(1, rs.GREATER_FIRE_PROTECTION, "GFPP", 5, 25_000, 2),
            auction.Listing(2, rs.GREATER_FIRE_PROTECTION, "GFPP", 5, 20_000, 2),
            auction.Listing(3, 12451, "Juju Power", 1, 90_000, 2),
        ]
        self.assertEqual(rs.market_cost(needs, listings, 2), 135_000)
        buys, _ = rs.plan_market(needs, listings, 2, "Grug", 500_000, 30_000, 0, 10)
        self.assertEqual([b.auction_id for b in buys], [2])
        buys, notes = rs.plan_market(needs, listings, 2, "Grug", 500_000, 0, 0, 10)
        self.assertFalse(buys)
        self.assertIn("no unspent raid budget", notes[0])

    def test_nothing_the_corps_can_make_goes_to_the_auction_house(self):
        oden = alchemist()
        plan = rs.plan_guild(facts([oden, *raider_members()]), {}, set())
        self.assertNotIn(
            rs.MAJOR_HEALING, [n.entry for n in rs.market_needs(plan, "Grug")]
        )


class FakeClient:
    def __init__(self, choice, confidence):
        self.choice, self.confidence = choice, confidence
        self.asked = []

    async def ask(self, kind, state, questions):
        self.asked.append((kind, state, questions))
        if self.choice is None:
            return jev.Outcome(jev.TIMEOUT, 3000)
        options = list(questions["next"]["criteria"])
        probs = {o: (self.confidence if o == self.choice else 0.0) for o in options}
        answer = jev.Choice(self.choice, probs, self.confidence)
        return jev.Outcome(jev.ANSWERED, 40, answers={"next": answer}, model="jev-test")


class JevPicksWhatComesNext(unittest.TestCase):
    def setUp(self):
        self.plan = rs.plan_guild(facts([alchemist(), *raider_members()]), {}, set())
        self.opts = rs.options(self.plan.lines, self.plan.fire, rs.FIRE_GEAR)

    def run_ask(self, client, environ=None):
        rule = rs.policy(environ or {})
        return asyncio.run(
            rs.ask(client, "Cave", self.plan.lines, self.plan.fire, self.opts, 0, rule)
        )

    def test_the_heuristic_puts_the_fire_potion_first(self):
        self.assertEqual(
            rs.heuristic_focus(self.opts), "buy:%d" % rs.GREATER_FIRE_PROTECTION
        )
        self.assertIn("fire:14132", [o for o, _ in self.opts])

    def test_act_is_the_default_and_a_sure_answer_acts(self):
        self.assertEqual(rs.policy({}).mode, jev.ACT)
        client = FakeClient("make:%d" % rs.MAJOR_HEALING, 0.8)
        judgment = self.run_ask(client)
        self.assertEqual(client.asked[0][0], "raid_supply")
        self.assertEqual(judgment.acted, jev.JEV)
        self.assertEqual(rs.focus_of(judgment, self.opts), "make:%d" % rs.MAJOR_HEALING)
        self.assertIn("raid supply: guild=Cave", judgment.line())

    def test_an_unsure_answer_or_none_keeps_the_heuristic(self):
        judgment = self.run_ask(FakeClient("make:%d" % rs.MAJOR_HEALING, 0.3))
        self.assertEqual(
            rs.focus_of(judgment, self.opts), rs.heuristic_focus(self.opts)
        )
        judgment = self.run_ask(FakeClient(None, 0))
        self.assertEqual(judgment.status, jev.TIMEOUT)
        self.assertEqual(
            rs.focus_of(judgment, self.opts), rs.heuristic_focus(self.opts)
        )
        self.assertEqual(rs.focus_of(None, self.opts), rs.heuristic_focus(self.opts))

    def test_off_asks_nothing(self):
        client = FakeClient("make:%d" % rs.MAJOR_HEALING, 0.9)
        self.assertIsNone(self.run_ask(client, {"JEV_MODE_RAID_SUPPLY": "off"}))
        self.assertFalse(client.asked)


class TheCorpsHasAlchemistsAndACook(unittest.TestCase):
    def test_alchemists_and_a_cook_are_posted_after_the_tailors(self):
        crew = [
            member("Derred", skills={gc.TAILORING: (300, 300), gc.ALCHEMY: (300, 300)}),
            member("Oden", skills={gc.ALCHEMY: (300, 375)}),
            member("Fitozz", skills={gc.ALCHEMY: (300, 300), gc.COOKING: (300, 300)}),
            member("Beerix", skills={gc.COOKING: (300, 300)}),
        ]
        roles = {p.name: p.role for p in gc.plan_corps(crew)["Cave"]}
        self.assertEqual(roles["Derred"], "tailor")
        self.assertEqual(roles["Oden"], "alchemist")
        self.assertEqual(roles["Fitozz"], "alchemist")
        self.assertEqual(roles["Beerix"], "cook")

    def test_the_cooldowns_read_the_raid_supplys_own_rows(self):
        rows = [
            {"source": "raidsupply:craft:17556", "target_name": "Oden", "age": 3},
            {"source": "guildcorps:craft:18405", "target_name": "Derred", "age": 3},
            {
                "source": "raidsupply:supply:13464",
                "target_name": "Hebus",
                "target_arg": "Oden",
                "age": 9,
            },
        ]
        recent = gc.recent_from_rows(rows, prefix=rs.SOURCE)
        self.assertEqual(recent[("Oden", "craft", 17556)], 3)
        self.assertEqual(recent[("to:Oden", "supply", 13464)], 9)
        self.assertNotIn(("Derred", "craft", 18405), recent)


class TheRaidTab(unittest.TestCase):
    def test_the_card_counts_the_night_against_the_guilds_stock(self):
        card = rs.card(
            RAIDERS, {rs.MAJOR_HEALING: 25}, {HEALING_SPELL: ["Oden"]}, None, 8_046_728
        )
        rows = {row["entry"]: row for row in card["supplies"]}
        self.assertEqual(rows[rs.MAJOR_HEALING]["cells"][2], "25")
        self.assertEqual(rows[rs.MAJOR_HEALING]["route"], rs.MAKE)
        self.assertEqual(rows[rs.GREATER_FIRE_PROTECTION]["route"], rs.BUY)
        self.assertEqual(card["fire"][0]["cells"][:3], ["Grug", "main tank", "200"])
        self.assertIn("804 gold", card["budget_line"])
        self.assertIn("80 gold a day", card["budget_line"])

    def test_the_readiness_card_carries_the_supply_section(self):
        group = {
            "guild": "Cave",
            "family": "Grug",
            "family_names": ["Grug"],
            "rows": [
                {"name": "Grug", "level": 60, "class_id": 1},
                {"name": "Aylysae", "level": 60, "class_id": 5},
            ],
        }
        chars = [
            {"name": "Grug", "level": 60, "class": 1},
            {"name": "Aylysae", "level": 60, "class": 5},
        ]
        card = raidready.build_guild(
            group,
            chars,
            [{"name": "Grug", "slot": 6, "fire_res": 10}],
            [],
            55,
            {},
            supply={"have": {}, "knowers": {}, "bank": 0},
        )
        self.assertIn("supply", card)
        fire = {row["cells"][0]: row["cells"] for row in card["supply"]["fire"]}
        self.assertEqual(fire["Grug"][3], "10")

    def test_the_page_draws_the_cells_and_decides_nothing(self):
        self.assertIn("rrSupply(card, g.supply)", PAGE)
        self.assertIn("s.supplies", PAGE)
        self.assertIn("s.fire_columns", PAGE)
        self.assertIn('supply=supply.get(group["guildid"])', SERVER)

    def test_the_module_ships_in_the_image(self):
        self.assertIn("raidsupply.py", DOCKERFILE)


class TheBridgePass(unittest.TestCase):
    def body(self, name):
        start = BRIDGE.index("    async def %s(" % name)
        end = BRIDGE.index("\n    async def ", start + 10)
        return BRIDGE[start:end]

    def test_the_withdrawal_is_the_masters_only_and_only_at_a_vault(self):
        market = self.body("_raid_supply_market")
        self.assertIn('"bank withdraw %d" % copper', market)
        self.assertIn("raidsupply.WITHDRAW_SOURCE", market)
        self.assertLess(
            market.index("travel.spawn_in_reach"), market.index('"bank withdraw %d"')
        )
        self.assertEqual(BRIDGE.count('"bank withdraw'), 1)
        # The master is the guild's leader, read from the guild row itself.
        self.assertIn(
            "c.guid = g.leaderguid", BRIDGE[BRIDGE.index("_RAID_SUPPLY_BANK_SQL = (") :]
        )

    def test_purchases_carry_their_copper_in_the_source(self):
        market = self.body("_raid_supply_market")
        self.assertIn("raidsupply.ah_source(buy.entry, buy.spend)", market)
        self.assertIn("_fetch_auctioneer, master", market)

    def test_the_corps_pass_runs_the_raid_supply_with_its_busy_members(self):
        corps = self.body("_guild_corps_once")
        self.assertIn("busy |= {step.holder for step in plan.steps}", corps)
        self.assertIn("self._raid_supply_once(facts, plan.corps, busy, cap)", corps)
        supply = self.body("_raid_supply_once")
        self.assertIn("raidsupply.ask(", supply)
        self.assertIn("self._run_corps_step(step, cap)", supply)
        self.assertIn('log.info("raid supply: started %d step(s)", started)', supply)

    def test_the_guild_bank_pass_holds_the_raid_gold_back(self):
        start = BRIDGE.index("def _fetch_guild_money(")
        self.assertIn(
            "raidsupply.hold_back(rows, ledger)", BRIDGE[start : start + 3000]
        )


if __name__ == "__main__":
    unittest.main()
