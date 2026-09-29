"""A crafter's surplus materials go to people who can use them before a vendor.

MEASURED ON wow-dev, 2026-09-29. The material keep cap (#418) turned every
stack of a crafting material past six stacks into vendor goods, and a crafter's
fifty-five stacks of Linen Cloth were sold for copper. The operator's rule:
surplus crafting materials feed guild members' professions, the guild bank, and
the auction house, and a vendor is the last resort.

Why nothing else took them, from the code and the live realm:

  guildshare.plan       hands one stack per guildmate per pass, only to an
                        online non-family member who holds a consuming trade.
                        Neither guild had such a member (one first-aid holder
                        in one guild, no other tailor or first-aid holder
                        outside the family), so the note was "nobody online can
                        use it" every cycle.
  bank.py               deposits into a guild vault only when the guild has a
                        tab; one guild has none, and the holder's own bank was
                        full ("bank is full, so ... stays in the bags").
  the vendor pass       took whatever was left, because the keep cap made the
                        surplus sellable.

Pinned here: `clearance.route` sends a surplus material GUILD, then BANK, then
AUCTION, then VENDOR; the vendor read no longer offers the surplus itself; and
an auction listing of a stack asks for the whole stack's price.
"""

import pathlib
import re
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import auction  # noqa: E402
import bank  # noqa: E402
import clearance  # noqa: E402
import disposition  # noqa: E402
import guildshare  # noqa: E402
import materials  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
CLOTH = 5
TAILORING = guildshare.SKILL_LINES["tailoring"]
FIRST_AID = guildshare.SKILL_LINES["first aid"]
MINING = guildshare.SKILL_LINES["mining"]


def cloth(guid, holder="Oz", count=20, price=13):
    return clearance.Stack(
        holder=holder,
        guid=guid,
        entry=2589,
        name="Linen Cloth",
        item_class=7,
        count=count,
        quality=1,
        sell_price=price,
        subclass=CLOTH,
        material=True,
    )


def person(name, skills=(), online=True, family=False):
    return clearance.Person(
        name=name, skills={s: 1 for s in skills}, family=family, online=online
    )


class TheOrderIsGuildBankAuctionVendor(unittest.TestCase):
    def test_a_guildmate_with_a_consuming_trade_takes_it(self):
        got = clearance.route(cloth(1), None, [person("Tess", [TAILORING])])
        self.assertEqual((got.route, got.taker), (clearance.GUILD, "Tess"))
        self.assertIn("tailoring", got.why)

    def test_first_aid_uses_cloth_too(self):
        got = clearance.route(cloth(1), None, [person("Nan", [FIRST_AID])])
        self.assertEqual((got.route, got.taker), (clearance.GUILD, "Nan"))

    def test_a_trade_that_does_not_use_cloth_takes_none(self):
        got = clearance.route(
            cloth(1),
            None,
            [person("Min", [MINING])],
            market={2589: 999},
            auction_open=True,
        )
        self.assertEqual(got.route, clearance.AUCTION)

    def test_a_family_member_is_not_a_taker_for_a_material(self):
        people = [person("Og", [TAILORING], family=True)]
        got = clearance.route(cloth(1), None, people)
        self.assertEqual(got.route, clearance.VENDOR)

    def test_an_offline_taker_does_not_hold_the_stack_for_ever(self):
        got = clearance.route(
            cloth(1), None, [person("Tess", [TAILORING], online=False)]
        )
        self.assertEqual(got.route, clearance.VENDOR)

    def test_the_guild_bank_is_next_when_the_holder_may_deposit(self):
        got = clearance.route(
            cloth(1),
            None,
            [],
            vault=frozenset({"Oz"}),
            market={2589: 999},
            auction_open=True,
        )
        self.assertEqual(got.route, clearance.BANK)

    def test_a_holder_without_the_deposit_right_skips_the_bank(self):
        got = clearance.route(cloth(1), None, [], vault=frozenset({"Zork"}))
        self.assertEqual(got.route, clearance.VENDOR)

    def test_the_auction_house_is_next_when_it_pays_more_than_a_vendor(self):
        got = clearance.route(
            cloth(1),
            None,
            [],
            market={2589: 13 * disposition.AUCTION_BEATS_VENDOR_BY},
            auction_open=True,
        )
        self.assertEqual(got.route, clearance.AUCTION)

    def test_a_house_that_pays_no_more_leaves_it_to_the_vendor(self):
        got = clearance.route(cloth(1), None, [], market={2589: 13}, auction_open=True)
        self.assertEqual(got.route, clearance.VENDOR)

    def test_a_vendor_is_the_last_resort(self):
        got = clearance.route(cloth(1), None, [])
        self.assertEqual(got.route, clearance.VENDOR)
        self.assertIn("13 copper", got.why)

    def test_a_stack_a_vendor_will_not_buy_is_kept(self):
        got = clearance.route(cloth(1, price=0), None, [])
        self.assertEqual(got.route, clearance.KEEP)


class ThePlanSpreadsTheSurplus(unittest.TestCase):
    def test_each_guildmate_takes_one_stack_a_pass_and_the_rest_goes_on(self):
        stacks = [cloth(10 + i) for i in range(4)]
        routes = clearance.plan(stacks, [person("Tess", [TAILORING])])
        self.assertEqual(
            [r.route for r in routes],
            [clearance.GUILD, clearance.VENDOR, clearance.VENDOR, clearance.VENDOR],
        )

    def test_the_vault_takes_only_the_stacks_its_tab_has_room_for(self):
        stacks = [cloth(10 + i) for i in range(4)]
        routes = clearance.plan(stacks, [], vault=frozenset({"Oz"}), vault_room=3)
        self.assertEqual(
            [r.route for r in routes],
            [clearance.BANK] * 3 + [clearance.VENDOR],
        )

    def test_no_room_in_the_vault_means_no_bank_route(self):
        routes = clearance.plan([cloth(1)], [], vault=frozenset({"Oz"}), vault_room=0)
        self.assertEqual(routes[0].route, clearance.VENDOR)

    def test_a_gem_keeps_its_own_route_beside_the_materials(self):
        gem = clearance.Stack(
            holder="Oz",
            guid=99,
            entry=7910,
            name="Star Ruby",
            item_class=clearance.GEM_CLASS,
            quality=2,
            sell_price=5000,
        )
        routes = clearance.plan(
            [gem, cloth(1)],
            [person("Tess", [TAILORING])],
            vault=frozenset({"Oz"}),
            vault_room=5,
        )
        by_name = {r.stack.name: r.route for r in routes}
        self.assertEqual(by_name["Linen Cloth"], clearance.GUILD)
        self.assertEqual(by_name["Star Ruby"], clearance.VENDOR)


class TheSurplusIsTheKeepCapsComplement(unittest.TestCase):
    def rows(self, stacks):
        return [
            {
                "holder": "Oz",
                "item_guid": 100 + i,
                "entry": 2589,
                "count": 20,
                "name": "Linen Cloth",
                "item_class": 7,
                "bag_family": 0,
            }
            for i in range(stacks)
        ]

    def test_a_pile_inside_the_cap_has_no_surplus(self):
        self.assertEqual(
            disposition.material_surplus(self.rows(6), materials.REAGENTS),
            frozenset(),
        )

    def test_a_pile_past_the_cap_leaves_only_what_is_over(self):
        rows = self.rows(61)
        over = disposition.material_surplus(rows, materials.REAGENTS)
        kept = disposition.material_keeps(rows, materials.REAGENTS)
        self.assertEqual(len(kept), 6)
        self.assertEqual(len(over), 55)
        self.assertFalse(over & set(kept))

    def test_a_name_no_family_trade_uses_is_nobodys_surplus(self):
        rows = [dict(r, name="Wool Cloth") for r in self.rows(9)]
        self.assertEqual(
            disposition.material_surplus(rows, materials.REAGENTS), frozenset()
        )


class OnlyFlaggedSurplusBecomesAStack(unittest.TestCase):
    def row(self, guid, flagged):
        return {
            "holder": "Oz",
            "item_guid": guid,
            "entry": 2589,
            "name": "Linen Cloth",
            "item_class": 7,
            "subclass": CLOTH,
            "count": 20,
            "quality": 1,
            "sell_price": 13,
            "material_surplus": flagged,
        }

    def test_a_kept_stack_is_not_read_as_a_clearance_stack(self):
        stacks = clearance.stacks_from_rows([self.row(1, True), self.row(2, False)])
        self.assertEqual([s.guid for s in stacks], [1])
        self.assertTrue(stacks[0].material)
        self.assertEqual(stacks[0].subclass, CLOTH)


class TheVaultFactsComeFromTheBankPassesOwnRule(unittest.TestCase):
    def test_no_tab_means_no_vault(self):
        self.assertEqual(bank.guild_room({"purchased_tabs": 0}), (frozenset(), 0))

    def test_a_tab_with_room_names_the_ranks_that_may_deposit(self):
        depositors, room = bank.guild_room(
            {
                "purchased_tabs": 1,
                "deposit_rank_ids": (1,),
                "member_ranks": {"Oz": 1, "Zork": 3},
                "tab0_items": 90,
            }
        )
        self.assertEqual((depositors, room), (frozenset({"Oz"}), 8))


class AnAuctionListingAsksForTheWholeStack(unittest.TestCase):
    def sale(self, count):
        row = {
            "holder": "Oz",
            "item_guid": 5,
            "entry": 2589,
            "quality": 1,
            "binding": "none",
            "sell_price": 13,
            "market_price": 100,
            "count": count,
        }
        return auction.plan_sales([row])[0]

    def test_the_buyout_scales_with_the_stack(self):
        self.assertEqual(self.sale(1).buyout, 100)
        self.assertEqual(self.sale(20).buyout, 2000)

    def test_a_row_with_no_count_is_one_unit(self):
        row = {
            "holder": "Oz",
            "item_guid": 5,
            "entry": 2589,
            "quality": 2,
            "binding": "boe",
            "sell_price": 13,
            "market_price": 100,
        }
        self.assertEqual(auction.plan_sales([row])[0].buyout, 100)


class TheBridgeWiring(unittest.TestCase):
    def setUp(self):
        self.src = BRIDGE.read_text(encoding="utf-8")

    def block(self, signature):
        start = self.src.index(signature)
        indent = len(signature) - len(signature.lstrip())
        rest = self.src[start:]
        end = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
        return rest[: end.start() + 1] if end else rest

    def test_the_vendor_read_flags_the_surplus_instead_of_offering_it(self):
        body = self.block("def _fetch_vendor_items(")
        self.assertIn("disposition.material_surplus(", body)
        self.assertNotIn("material_kept", body)
        self.assertRegex(
            body, r'profession_material = item\.get\("name"\) in materials\.REAGENTS'
        )

    def test_the_clearance_plan_reads_the_materials_and_the_vault(self):
        body = self.block("    async def _clearance_plan(")
        self.assertIn("_fetch_clearance_materials", body)
        self.assertIn("_fetch_guild_bank_setup", body)
        self.assertIn("bank.guild_room(", body)
        self.assertIn("vault=vault, vault_room=vault_room", body)

    def test_the_materials_query_reads_carried_named_unbound_stacks(self):
        start = self.src.index("_CLEARANCE_MATERIALS_SQL = (")
        sql = self.src[start : self.src.index("\n)\n", start)]
        self.assertIn("it.name IN (%s)", sql)
        self.assertIn("it.subclass AS subclass", sql)
        self.assertIn("it.bonding = 0", sql)

    def test_the_vendor_half_still_sells_what_clearance_sends_it(self):
        self.assertIn("+ lock_sales + clear_sales", self.src)

    def test_the_auction_candidate_carries_the_stack_count(self):
        body = self.block("def _clearance_listings(")
        self.assertIn('"count": r.stack.count', body)


if __name__ == "__main__":
    unittest.main()
