"""The guild bank keeps what the guild will eat, and lets the rest go.

Measured on the dev realm 2026-10-10 (read-only): Cave's one tab held 98 of
98 slots, 14 of them Linen Cloth (280). The crew ate 201 Linen Cloth in Linen
Bandage casts in seven days, and the members held 1,114 more in their bags,
banks and post. The numbers in these cases are those.
"""

import pathlib
import re
import unittest

import bank
import bankforecast as bf
import clearance
import disposition

LINEN = 2589
WOOL = 2592
PEACEBLOOM = 2447
FIRST_AID = 129
TAILORING = 197
LEATHERWORKING = 165
JEWELCRAFTING = 755
ELEMENTAL_FIRE = 7068  # Greater Fire Protection Potion's reagent

LINEN_ITEM = bf.Item(LINEN, "Linen Cloth", 7, 5, 1, 20, 13)
WOOL_ITEM = bf.Item(WOOL, "Wool Cloth", 7, 5, 1, 20, 33)
TIGERSEYE = bf.Item(818, "Tigerseye", 3, 7, 2, 20, 100)
STAR_RUBY = bf.Item(7910, "Star Ruby", 3, 7, 2, 20, 5000)
FIRE = bf.Item(ELEMENTAL_FIRE, "Elemental Fire", 7, 10, 1, 10, 400)
SCORPID = bf.Item(8401, "Pattern: Tough Scorpid Leggings", 9, 1, 2, 1, 1375, 165, 245)
FANG = bf.Item(5637, "Large Fang", 7, 11, 1, 5, 75)
GREY = bf.Item(3300, "Rabbit's Foot", 15, 0, 0, 20, 50)
LOCKBOX = bf.Item(5758, "Mithril Lockbox", 15, 0, 2, 1, 250)

# The family, 2026-10-10: First Aid between 1 and 12, Og's Tailoring past linen.
FAMILY = (
    bf.Member("Grug", 43, {FIRST_AID: 12}, family=True),
    bf.Member("Bork", 39, {FIRST_AID: 2, LEATHERWORKING: 12}, family=True),
    bf.Member("Og", 38, {FIRST_AID: 1, TAILORING: 81}, family=True),
)
# Two of the crew, climbing First Aid on Linen Bandage from their own bags.
CREW = (
    bf.Member("Totta", 23, {FIRST_AID: 56}),
    bf.Member("Glob", 16, {FIRST_AID: 31}),
)


def linen_stacks(n, first_guid=100):
    return tuple(bf.Stack(first_guid + i, LINEN, 20) for i in range(n))


def asks(entry, per_unit, n, count=5, outcome="expired", house=2):
    return tuple(
        {
            "house": house,
            "item_entry": entry,
            "item_count": count,
            "bid": per_unit * count * 4 // 5,
            "buyout": per_unit * count,
            "price_paid": per_unit * count if outcome == "sold" else 0,
            "outcome": outcome,
        }
        for _ in range(n)
    )


class WhatAMemberEats(unittest.TestCase):
    def test_first_aid_at_12_eats_linen_on_its_rung_and_its_ladder(self):
        rung, ladder = bf.climb(FIRST_AID, 12, 300)
        # Linen Bandage 12..59: 48 points, five casts for four points.
        self.assertEqual(60, rung[LINEN])
        # Heavy Linen Bandage 60..79 eats two a cast on top.
        self.assertEqual(60 + 25 * 2, ladder[LINEN])
        self.assertIn(WOOL, ladder)
        self.assertNotIn(WOOL, rung)

    def test_a_trade_past_linen_eats_none(self):
        rung, ladder = bf.climb(TAILORING, 81, 300)
        self.assertNotIn(LINEN, ladder)
        self.assertNotIn(LINEN, rung)

    def test_the_level_caps_the_climb(self):
        # Tailoring's Expert rank asks level 20: a level 15 tailor stops at 150.
        self.assertEqual(150, bf.skill_ceiling(TAILORING, 15))
        self.assertEqual(300, bf.skill_ceiling(TAILORING, 35))
        _, ladder = bf.climb(TAILORING, 140, 150)
        self.assertNotIn(4338, ladder)  # Mageweave is past 150

    def test_the_crews_pace_is_measured_from_its_casts(self):
        need = bf.needs(CREW, casts=(("Totta", 3275, 120), ("Glob", 3275, 81)))[LINEN]
        self.assertAlmostEqual(201 / 7.0, need.pace)
        self.assertEqual(201, need.casts)
        # The crew's rungs are not counted twice: their pace is their eating.
        self.assertEqual(0, need.rungs)

    def test_the_familys_rungs_count_whole(self):
        need = bf.needs(FAMILY)[LINEN]
        # Five casts for four points, rounded up: 48, 58 and 59 points.
        self.assertEqual(60 + 73 + 74, need.rungs)
        self.assertEqual({"Grug": 60, "Bork": 73, "Og": 74}, need.by_member)


class AFairPriceFromTheHousesOwnHistory(unittest.TestCase):
    def test_what_sold_is_the_price(self):
        rows = asks(LINEN, 300, 3, outcome="sold") + asks(LINEN, 900, 5)
        price, why = bf.fair_price(rows, LINEN, 2)
        self.assertEqual(300, price)
        self.assertIn("sold 3", why)

    def test_asks_that_expired_were_too_high(self):
        # Measured: 8 Linen Cloth asks at house 2, median 7s 29c, none sold.
        price, why = bf.fair_price(asks(LINEN, 729, 8), LINEN, 2)
        self.assertEqual(729 * 3 // 4, price)
        self.assertIn("expired unsold", why)

    def test_the_familys_house_first(self):
        rows = asks(LINEN, 400, 2, house=6) + asks(LINEN, 800, 2, house=2)
        self.assertEqual(600, bf.fair_price(rows, LINEN, 2)[0])
        self.assertEqual(300, bf.fair_price(rows, LINEN, 6)[0])

    def test_no_history_is_no_price(self):
        self.assertEqual(0, bf.fair_price((), LINEN, 2)[0])


class TheVaultKeepsWhatTheGuildWillEat(unittest.TestCase):
    def cave(self, **kw):
        args = dict(
            stacks=linen_stacks(14),
            items={LINEN: LINEN_ITEM},
            members=FAMILY + CREW,
            held={LINEN: 1114},
            casts=(("Totta", 3275, 120), ("Glob", 3275, 81)),
            history=asks(LINEN, 729, 8),
            house=2,
        )
        args.update(kw)
        stacks = args.pop("stacks")
        items = args.pop("items")
        members = args.pop("members")
        held = args.pop("held")
        return bf.plan(stacks, items, members, held, **args)

    def test_the_vaults_linen_is_past_what_the_guild_eats_in_a_fortnight(self):
        forecast = self.cave()
        (line,) = forecast.lines
        self.assertEqual(14, line.count(bf.SELL))
        self.assertEqual(0, line.count(bf.KEEP))
        self.assertTrue(
            line.summary.startswith(
                "Linen Cloth: 14 stack(s) (280) in the vault, 1394 guild-wide, need "
            ),
            line.summary,
        )
        self.assertIn("list 14 at 5s 46c each", line.summary)
        self.assertIn(LINEN, forecast.over_target)
        self.assertEqual(546, forecast.fair[LINEN])

    def test_the_members_stock_is_eaten_first_and_the_vault_keeps_the_rest(self):
        forecast = self.cave(held={LINEN: 400})
        (line,) = forecast.lines
        kept = sum(
            d.stack.count for d in line.decisions if d.action in (bf.KEEP, bf.GIVE)
        )
        # Whole stacks, just enough to reach the target with what members hold.
        self.assertEqual(-(-(line.target - 400) // 20) * 20, kept)
        self.assertEqual(14 - kept // 20, line.count(bf.SELL))

    def test_a_kept_stack_goes_to_the_member_whose_rung_is_short(self):
        forecast = self.cave(held={LINEN: 400}, carried={"Og": {}, "Bork": {LINEN: 10}})
        gives = [d for d in forecast.decisions() if d.action == bf.GIVE]
        self.assertTrue(gives)
        self.assertEqual("Og", gives[0].taker)
        self.assertIn(
            "Og's current rung eats 74 Linen Cloth and it carries 0", gives[0].line
        )

    def test_the_members_short_of_their_rung_are_named(self):
        forecast = self.cave(carried={"Og": {LINEN: 200}, "Bork": {LINEN: 10}})
        self.assertIn("Bork", forecast.short[LINEN])
        self.assertNotIn("Og", forecast.short[LINEN])

    def test_once_every_member_has_climbed_past_linen_nothing_is_kept(self):
        past = (
            bf.Member("Og", 38, {FIRST_AID: 80, TAILORING: 81}, family=True),
            bf.Member("Totta", 23, {FIRST_AID: 90}),
        )
        forecast = self.cave(members=past, held={}, casts=())
        (line,) = forecast.lines
        self.assertEqual(bf.SURPLUS, line.kind)
        self.assertEqual(0, line.target)
        self.assertEqual(14, line.count(bf.SELL))

    def test_a_raid_reagent_is_never_sold(self):
        forecast = self.cave(
            stacks=(bf.Stack(1, ELEMENTAL_FIRE, 1),),
            items={ELEMENTAL_FIRE: FIRE},
            members=(),
            held={},
        )
        (line,) = forecast.lines
        self.assertEqual(bf.RAID, line.kind)
        self.assertEqual([bf.KEEP], [d.action for d in line.decisions])
        self.assertNotIn(ELEMENTAL_FIRE, forecast.over_target)

    def test_a_gem_nobody_cuts_is_listed_when_the_house_beats_the_vendor(self):
        forecast = self.cave(
            stacks=(bf.Stack(1, 818, 13), bf.Stack(2, 7910, 20)),
            items={818: TIGERSEYE, 7910: STAR_RUBY},
            history=asks(818, 582, 11),
        )
        actions = {d.item: d.action for d in forecast.decisions()}
        self.assertEqual(bf.SELL, actions["Tigerseye"])
        # No history for Star Ruby, and a vendor pays 50s each.
        self.assertEqual(bf.VENDOR, actions["Star Ruby"])

    def test_a_gem_is_kept_while_somebody_cuts_gems(self):
        cutter = bf.Member("Mok", 40, {JEWELCRAFTING: 50})
        forecast = self.cave(
            stacks=(bf.Stack(1, 818, 13),),
            items={818: TIGERSEYE},
            members=FAMILY + (cutter,),
        )
        self.assertEqual([bf.KEEP], [d.action for d in forecast.decisions()])

    def test_one_copy_of_a_recipe_per_member_whose_trade_reaches_it(self):
        forecast = self.cave(
            stacks=tuple(bf.Stack(i, 8401, 1) for i in (1, 2, 3)),
            items={8401: SCORPID},
            held={},
        )
        (line,) = forecast.lines
        self.assertEqual(bf.LATER, line.kind)
        self.assertEqual(1, line.count(bf.KEEP))
        self.assertEqual(2, line.count(bf.VENDOR))
        self.assertIn("Bork", line.why)

    def test_a_trade_good_nobody_uses_is_surplus_and_a_grey_one_is_junk(self):
        forecast = self.cave(
            stacks=(bf.Stack(1, 5637, 5), bf.Stack(2, 3300, 20)),
            items={5637: FANG, 3300: GREY},
            history=(),
        )
        kinds = {line.item: line.kind for line in forecast.lines}
        self.assertEqual(bf.SURPLUS, kinds["Large Fang"])
        self.assertEqual(bf.JUNK, kinds["Rabbit's Foot"])
        self.assertEqual({bf.VENDOR}, {d.action for d in forecast.decisions()})

    def test_what_the_model_does_not_judge_is_kept(self):
        forecast = self.cave(stacks=(bf.Stack(1, 5758, 1),), items={5758: LOCKBOX})
        (line,) = forecast.lines
        self.assertEqual(bf.UNJUDGED, line.kind)
        self.assertEqual([bf.KEEP], [d.action for d in line.decisions])

    def test_a_material_the_guild_will_climb_to_is_kept_whole(self):
        forecast = self.cave(
            stacks=(bf.Stack(1, WOOL, 20),),
            items={WOOL: WOOL_ITEM},
            members=CREW,
            held={WOOL: 400},
            casts=(),
        )
        (line,) = forecast.lines
        self.assertEqual(bf.LATER, line.kind)
        self.assertEqual([bf.KEEP], [d.action for d in line.decisions])
        self.assertNotIn(WOOL, forecast.over_target)

    def test_a_guild_with_no_vault_still_gets_its_targets(self):
        forecast = self.cave(stacks=(), held={LINEN: 5589}, entries=(LINEN,))
        (line,) = forecast.lines
        self.assertIn("none in the vault, 5589 guild-wide", line.summary)
        self.assertIn(LINEN, forecast.over_target)

    def test_the_headline_counts_the_vault(self):
        line = self.cave().headline("Cave")
        self.assertEqual("Cave's vault holds 14 stack(s): 14 surplus; list 14", line)


class TheFactsAreReadOnly(unittest.TestCase):
    def test_every_statement_is_a_select_and_survives_formatting(self):
        class Cursor:
            def __init__(self):
                self.seen = []

            def execute(self, sql, args=()):
                rendered = sql % tuple(repr(a) for a in args)
                self.seen.append(rendered)

            def fetchall(self):
                return []

            def fetchone(self):
                return {"guildid": 23, "guild": "Cave"}

        cur = Cursor()
        facts = bf.read(cur, ["Grug", "Og"])
        self.assertEqual("Cave", facts.guild)
        self.assertGreaterEqual(len(cur.seen), 6)
        for sql in cur.seen:
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
            self.assertNotIn("%s", sql)


class TheVaultTakesNothingPastTheTarget(unittest.TestCase):
    """Og's linen went to the vault because a trade claimed it, without a ceiling."""

    GUILD = {
        "purchased_tabs": 1,
        "deposit_rank_ids": (0, 1),
        "member_ranks": {"Og": 1},
        "tab_items": {0: 10},
    }

    def linen(self, guid, count=20):
        return bank.Holding(
            holder="Og",
            guid=guid,
            place=bank.BAGS,
            count=count,
            container_slots=0,
            item=disposition.Item(
                name="Linen Cloth",
                known=True,
                quality=1,
                item_class=bank.ITEM_CLASS_TRADE_GOODS,
                quest_item=False,
                equipment=False,
                reagent_for="first aid",
            ),
            template_id=LINEN,
            bound=False,
        )

    def plan(self, over=None):
        storage = bank.storage_from(
            {"Og": {"first aid": 1}},
            named={LINEN: ("first aid",)},
            guild=self.GUILD,
            over_target=over,
        )
        member = bank.Member(
            "Og",
            38,
            bag_free=0,
            bank_free=10,
            carried=(self.linen(1), self.linen(2), self.linen(3)),
        )
        return bank.plan([member], disposition.Family(), storage=storage)

    def test_without_a_forecast_the_stack_past_the_cap_goes_to_the_vault(self):
        result = self.plan()
        self.assertEqual(
            ["bank deposit-item guid:3"], [bank.command(m) for m in result.guild]
        )
        self.assertIn(
            "Linen Cloth is past the 40 Og keeps for first aid", result.guild[0].why
        )

    def test_past_the_guilds_target_it_goes_to_the_holders_own_bank(self):
        result = self.plan({LINEN: "the guild holds 1394 against a target of 777"})
        self.assertEqual([], list(result.guild))
        self.assertEqual(["deposit guid:3"], [bank.command(m) for m in result.moves])
        self.assertIn(
            "Linen Cloth stays out of the guild bank: the guild holds 1394 against a "
            "target of 777",
            result.notes,
        )


class ClearanceSellsWhatThePastTargetLeaves(unittest.TestCase):
    def stack(self):
        return clearance.Stack(
            holder="Og",
            guid=7,
            entry=LINEN,
            name="Linen Cloth",
            item_class=7,
            count=20,
            quality=1,
            sell_price=13,
            subclass=5,
            material=True,
        )

    def people(self):
        return (
            clearance.Person("Og", {FIRST_AID: 1}, family=True, online=True),
            clearance.Person("Totta", {FIRST_AID: 56}, online=True),
        )

    def test_today_a_vault_with_room_takes_it(self):
        (route,) = clearance.plan(
            [self.stack()], self.people()[:1], vault=frozenset({"Og"}), vault_room=5
        )
        self.assertEqual(clearance.BANK, route.route)

    def test_past_the_target_it_skips_the_vault_and_lists_at_the_fair_price(self):
        (route,) = clearance.plan(
            [self.stack()],
            self.people()[:1],
            vault=frozenset({"Og"}),
            vault_room=5,
            auction_open=True,
            over_target={LINEN: "the guild holds 1394 against 777"},
            fair={LINEN: 546},
        )
        self.assertEqual(clearance.AUCTION, route.route)
        self.assertIn("546", route.why)
        self.assertIn("1394 against 777", route.why)

    def test_past_the_target_a_guildmate_takes_it_only_when_short(self):
        over = {LINEN: "past"}
        (route,) = clearance.plan(
            [self.stack()],
            self.people(),
            auction_open=True,
            over_target=over,
            fair={LINEN: 546},
            short={LINEN: frozenset()},
        )
        self.assertEqual(clearance.AUCTION, route.route)
        (route,) = clearance.plan(
            [self.stack()],
            self.people(),
            auction_open=True,
            over_target=over,
            fair={LINEN: 546},
            short={LINEN: frozenset({"Totta"})},
        )
        self.assertEqual((clearance.GUILD, "Totta"), (route.route, route.taker))


class TheBridgeAsksTheForecast(unittest.TestCase):
    SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
        encoding="utf-8"
    )

    def block(self, signature):
        start = self.SOURCE.index(signature)
        rest = self.SOURCE[start:]
        match = re.search(r"\n(    )?(async def |def )", rest[1:])
        return rest[: match.start() + 1]

    def test_the_guild_bank_pass_logs_the_forecast(self):
        self.assertIn(
            "_say_bank_forecast(", self.block("    async def _guild_bank_once(")
        )

    def test_the_keeper_rule_reads_it(self):
        self.assertIn("over_target=", self.block("def _plan_bank("))

    def test_clearance_reads_it(self):
        body = self.block("    async def _clearance_plan(")
        self.assertIn("over_target=", body)
        self.assertIn("fair=", body)
        self.assertIn("short=", body)

    def test_the_module_ships(self):
        dockerfile = (
            pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"
        ).read_text()
        self.assertIn("bankforecast.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
