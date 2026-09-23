"""Gems and spare recipes get a route out of full bags (#148, #145).

Measured on wow-dev 2026-09-22: one member at 0 free slots carried eight gem
stacks, three engineering schematics above his skill of 1 and a
jewelcrafting design; another at 0 carried eight gem stacks and six recipes
above her skills. The guild held 26 jewelcrafters and 20 engineers at 260 or
more. Pinned here: the order KEEP, FAMILY, GUILD, WAIT, AUCTION, VENDOR in
`clearance.route`, the one-stack-per-receiver budget, and the bridge wiring,
read as text because bridge.py imports discord.
"""

import pathlib
import re
import unittest

import clearance
import disposition

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
DOCKERFILE = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"


def _source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature: str) -> str:
    src = _source()
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


def _sql(name: str) -> str:
    src = _source()
    start = src.index(name + " = (")
    return src[start : src.index("\n)\n", start)]


def gem(guid, holder="Grog", entry=7910, name="Star Ruby", price=5000, bound=False):
    return clearance.Stack(
        holder=holder,
        guid=guid,
        entry=entry,
        name=name,
        item_class=clearance.GEM_CLASS,
        count=6,
        quality=2,
        sell_price=price,
        bound=bound,
    )


def schematic(guid, holder="Grog", rank=265, price=4000):
    return clearance.Stack(
        holder=holder,
        guid=guid,
        entry=16044,
        name="Schematic: Lifelike Mechanical Toad",
        item_class=clearance.RECIPE_CLASS,
        quality=2,
        sell_price=price,
        required_skill=202,
        required_rank=rank,
    )


GROG = clearance.Person("Grog", {186: 1, 202: 1}, family=True, online=True)
UGGA = clearance.Person("Ugga", {171: 14}, family=True, online=True)
CUTTER = clearance.Person("Cutter", {755: 300}, online=True)
TINKER = clearance.Person("Tinker", {202: 300}, online=True)
AWAY = clearance.Person("Away", {755: 300, 202: 300}, online=False)


def route(stack, people, **kw):
    by_name = {p.name: p for p in people}
    return clearance.route(stack, by_name.get(stack.holder), people, **kw)


class TheOrder(unittest.TestCase):
    def test_a_recipe_its_holder_can_learn_now_is_kept(self):
        got = route(schematic(1, rank=1), [GROG, TINKER])
        self.assertEqual(got.route, clearance.KEEP)

    def test_a_recipe_above_the_holder_goes_to_a_guildmate_who_can_learn_it(self):
        got = route(schematic(1), [GROG, TINKER])
        self.assertEqual((got.route, got.taker), (clearance.GUILD, "Tinker"))

    def test_a_gem_goes_to_a_jewelcrafter(self):
        got = route(gem(1), [GROG, CUTTER])
        self.assertEqual((got.route, got.taker), (clearance.GUILD, "Cutter"))

    def test_a_family_member_who_can_use_it_comes_first(self):
        cutter = clearance.Person("Og", {755: 5}, family=True, online=True)
        got = route(gem(1), [GROG, cutter, CUTTER])
        self.assertEqual((got.route, got.taker), (clearance.FAMILY, "Og"))

    def test_a_guildmate_who_can_use_it_but_is_offline_means_wait(self):
        got = route(gem(1), [GROG, AWAY])
        self.assertEqual((got.route, got.taker), (clearance.WAIT, "Away"))

    def test_nobody_can_use_it_and_the_market_pays_lists_it(self):
        got = route(gem(1, price=100), [GROG], market={7910: 490}, auction_open=True)
        self.assertEqual(got.route, clearance.AUCTION)

    def test_a_market_below_the_multiple_is_a_vendor_sale(self):
        got = route(gem(1), [GROG], market={7910: 6000}, auction_open=True)
        self.assertEqual(got.route, clearance.VENDOR)

    def test_no_auction_pass_for_the_family_means_the_vendor(self):
        got = route(gem(1, price=100), [GROG], market={7910: 9000})
        self.assertEqual(got.route, clearance.VENDOR)

    def test_a_guid_another_pass_owns_is_kept(self):
        got = route(gem(1), [GROG, CUTTER], kept=frozenset({1}))
        self.assertEqual(got.route, clearance.KEEP)

    def test_a_bound_stack_nobody_can_take_is_sold(self):
        got = route(gem(1, bound=True), [GROG, CUTTER])
        self.assertEqual(got.route, clearance.VENDOR)

    def test_no_vendor_price_is_kept(self):
        got = route(gem(1, price=0), [GROG])
        self.assertEqual(got.route, clearance.KEEP)

    def test_the_rule_for_learnable_lives_in_disposition(self):
        self.assertTrue(disposition.learnable_now(14, 14))
        self.assertFalse(disposition.learnable_now(14, 50))
        self.assertFalse(disposition.learnable_now(0, 0))


class OneStackPerReceiver(unittest.TestCase):
    def test_a_busy_receiver_makes_the_next_stack_wait_not_sell(self):
        got = clearance.plan([gem(1), gem(2)], [GROG, CUTTER])
        self.assertEqual([r.route for r in got], [clearance.GUILD, clearance.WAIT])

    def test_two_receivers_take_two_stacks(self):
        other = clearance.Person("Setter", {755: 50}, online=True)
        got = clearance.plan([gem(1), gem(2)], [GROG, CUTTER, other])
        self.assertEqual({r.taker for r in got}, {"Cutter", "Setter"})

    def test_counts_name_every_route(self):
        got = clearance.plan([gem(1), schematic(2)], [GROG, CUTTER])
        self.assertEqual(clearance.counts(got), {"guild": 1, "vendor": 1})


class RowsBecomeStacks(unittest.TestCase):
    def test_gems_and_skill_gated_recipes_only(self):
        rows = [
            dict(
                holder="Grog",
                item_guid=1,
                entry=7910,
                name="Star Ruby",
                item_class=3,
                count=6,
                sell_price=5000,
            ),
            dict(
                holder="Ugga",
                item_guid=2,
                entry=11734,
                name="Libram",
                item_class=9,
                required_skill=0,
            ),
            dict(
                holder="Ugga",
                item_guid=3,
                entry=6663,
                name="Recipe",
                item_class=9,
                required_skill=171,
                required_rank=90,
                instance_flags=1,
            ),
        ]
        got = clearance.stacks_from_rows(rows)
        self.assertEqual([s.guid for s in got], [1, 3])
        self.assertTrue(got[1].bound)


class TheBridgeWiresIt(unittest.TestCase):
    def test_the_vendor_pass_plans_sells_and_hands_over(self):
        body = _block("    async def _vendor_once(")
        self.assertIn("await self._clearance_plan(names, leader,", body)
        self.assertIn("auction_open=cohort is None", body)
        self.assertIn("clear_sales = _clearance_sales(clear)", body)
        self.assertIn(") + lock_sales + clear_sales", body)
        self.assertLess(
            body.index("await self._route_clearance("),
            body.index("if not bag_pressure.family_town_run_needed("),
        )

    def test_the_sales_count_toward_the_trip(self):
        body = _block("    async def _vendor_once(")
        self.assertIn("for sale in lock_sales + clear_sales:", body)

    def test_hand_overs_ride_the_guild_gift_writer(self):
        body = _block("    async def _route_clearance(")
        self.assertIn("await self._write_guild_gifts(gifts)", body)
        self.assertIn(
            'self._claim_town_slot("clearance", leader, post.aim',
            _block("    async def _walk_to_post("),
        )
        self.assertIn("await self._walk_to_post(pressed, leader, cohort)", body)

    def test_the_auction_lists_what_nobody_can_use_and_is_urgent_under_pressure(self):
        body = _block("    async def _auction_sales_once(")
        self.assertIn("candidates = _clearance_listings(", body)
        self.assertIn("urgent=pressure", body)

    def test_a_recipe_is_kept_only_for_this_family(self):
        body = _block("def _clearance_kept(")
        self.assertIn("if who in family", body)
        self.assertIn("disposition.profession_keeps(", body)

    def test_the_sql_reads_what_the_planner_needs(self):
        sql = _sql("_CLEARANCE_SQL")
        for column in (
            "AS required_skill",
            "AS required_rank",
            "AS bonding",
            "AS instance_flags",
            "AS bag_family",
            "it.class = 3 OR (it.class = 9 AND it.RequiredSkill > 0)",
        ):
            self.assertIn(column, sql)

    def test_clearance_is_in_the_image(self):
        self.assertIn("clearance.py", DOCKERFILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
