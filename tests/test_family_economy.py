"""Every family gets the bag and economy passes, and bags get bought (#150).

Measured on wow-dev 2026-09-22: the second family (Zug, Oz, Uzza, Zork,
Zrog; levels 12 to 16) carried only the 16-slot backpack each, Zug at 15 of
16, while every pass took its names from OVERSEER_NOTABLE_NAMES, which is the
first family. `bag_pressure.bag_purchase_allowed` existed and had no caller.

Pinned here: which families a pass is run for and who walks each one, the
pure purchase planner (cheapest stocked bag, a reserve that survives it, a
free slot for it to land in, one per buyer, never while the family already
owns a spare), and that the bridge wires them in the order vendor, hand-over,
purchase, through the existing kind='buy' town-trip row.
"""

import pathlib
import re
import unittest

import bag_pressure
import bag_upgrade
import townslot

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

ALLIANCE = ["Bork", "Grog", "Grug", "Og", "Ugga"]


def roster(*rows):
    return [dict(name=n, family=f, lead=lead) for n, f, lead in rows]


LIVE_ROSTER = roster(
    ("Bork", "Grug", 0),
    ("Grog", "Grug", 0),
    ("Grug", "Grug", 1),
    ("Og", "Grug", 0),
    ("Ugga", "Grug", 0),
    ("Oz", "Zug", 0),
    ("Uzza", "Zug", 0),
    ("Zork", "Zug", 0),
    ("Zrog", "Zug", 0),
    ("Zug", "Zug", 1),
)


class EveryFamilyIsSeen(unittest.TestCase):
    def test_the_other_family_is_found_with_its_own_leader(self):
        got = townslot.other_cohorts(LIVE_ROSTER, ALLIANCE)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].key, "Zug")
        self.assertEqual(got[0].leader, "Zug")
        self.assertEqual(got[0].names, ("Oz", "Uzza", "Zork", "Zrog", "Zug"))

    def test_this_bridges_own_family_is_never_passed_twice(self):
        got = townslot.other_cohorts(LIVE_ROSTER, ALLIANCE)
        for cohort in got:
            self.assertFalse(set(cohort.names) & set(ALLIANCE))

    def test_the_lead_flag_names_the_traveller_over_the_key(self):
        rows = roster(("Oz", "Zug", 1), ("Zug", "Zug", 0))
        self.assertEqual(townslot.other_cohorts(rows, ())[0].leader, "Oz")

    def test_without_a_lead_flag_the_head_named_by_the_key_leads(self):
        rows = roster(("Oz", "Zug", 0), ("Zug", "Zug", 0))
        self.assertEqual(townslot.other_cohorts(rows, ())[0].leader, "Zug")

    def test_a_family_nobody_can_walk_is_left_out(self):
        rows = roster(("Oz", "Zug", 0), ("Uzza", "Zug", 0))
        self.assertEqual(townslot.other_cohorts(rows, ()), ())

    def test_a_world_without_the_column_has_no_other_family(self):
        self.assertEqual(townslot.other_cohorts([], ALLIANCE), ())


POUCH = bag_pressure.BagOffer(entry=4496, name="Small Brown Pouch", slots=6, price=500)
SATCHEL = bag_pressure.BagOffer(
    entry=4498, name="Brown Leather Satchel", slots=8, price=2500
)


def buyer(
    name="Uzza",
    level=13,
    money=1995,
    open_positions=4,
    free_slots=8,
    stocks=(4496, 4498),
):
    return bag_pressure.BagBuyer(
        name=name,
        level=level,
        money=money,
        open_positions=open_positions,
        free_slots=free_slots,
        stocks=frozenset(stocks),
    )


class TheCheapestBagIsBoughtWhenTheReserveSurvives(unittest.TestCase):
    def test_the_cheapest_stocked_bag_is_bought(self):
        got, notes = bag_pressure.bag_purchases([buyer()], [SATCHEL, POUCH])
        self.assertEqual([(p.buyer, p.entry) for p in got], [("Uzza", 4496)])
        self.assertEqual(notes, ())

    def test_the_row_is_the_buy_verb_capped_at_the_list_price(self):
        got, _ = bag_pressure.bag_purchases([buyer()], [POUCH])
        self.assertEqual(got[0].command, "entry:4496 count:1 max:500")
        self.assertEqual(got[0].equip_command, "e Hitem:4496:0")

    def test_the_reserve_is_never_spent(self):
        """Zug at level 16 with 860 copper keeps 1600 back, so a 500 copper
        pouch would take him below the floor and is not bought."""
        got, notes = bag_pressure.bag_purchases(
            [buyer(name="Zug", level=16, money=860)], [POUCH]
        )
        self.assertEqual(got, ())
        self.assertIn("cannot spare", notes[0])

    def test_exactly_at_the_floor_is_allowed(self):
        money = 500 + bag_pressure.bag_reserve(13)
        got, _ = bag_pressure.bag_purchases([buyer(money=money)], [POUCH])
        self.assertEqual(len(got), 1)
        got, _ = bag_pressure.bag_purchases([buyer(money=money - 1)], [POUCH])
        self.assertEqual(got, ())

    def test_only_what_this_buyers_own_vendors_stock(self):
        """DoBuy answers on the buyer's own range."""
        got, notes = bag_pressure.bag_purchases(
            [buyer(stocks=(4498,), money=10000)], [POUCH, SATCHEL]
        )
        self.assertEqual([p.entry for p in got], [4498])
        got, notes = bag_pressure.bag_purchases([buyer(stocks=())], [POUCH])
        self.assertEqual(got, ())
        self.assertIn("no vendor in reach stocks a bag", notes[0])

    def test_no_empty_position_buys_nothing(self):
        got, notes = bag_pressure.bag_purchases([buyer(open_positions=0)], [POUCH])
        self.assertEqual((got, notes), ((), ()))

    def test_no_free_slot_to_land_in_buys_nothing(self):
        got, notes = bag_pressure.bag_purchases([buyer(free_slots=0)], [POUCH])
        self.assertEqual(got, ())
        self.assertIn("no free slot", notes[0])

    def test_one_bag_per_buyer_per_pass(self):
        got, _ = bag_pressure.bag_purchases(
            [buyer(money=100000), buyer(name="Zork", level=12, money=100000)], [POUCH]
        )
        self.assertEqual([p.buyer for p in got], ["Uzza", "Zork"])

    def test_the_reserve_scales_with_level(self):
        self.assertEqual(bag_pressure.bag_reserve(13), 1300)
        self.assertEqual(bag_pressure.bag_reserve(0), 100)


def member(name, worn=0, carried=()):
    return bag_upgrade.Member(
        name,
        4,
        worn=tuple(bag_upgrade.Bag("Pouch", 6, guid=100 + i) for i in range(worn)),
        carried=tuple(carried),
    )


class ASpareTheFamilyOwnsIsNotBoughtAgain(unittest.TestCase):
    def test_every_empty_position_is_open_with_no_spares(self):
        got = bag_pressure.open_bag_positions([member("Zug"), member("Oz", 3)])
        self.assertEqual(got, {"Oz": 1, "Zug": 4})

    def test_a_carried_empty_spare_fills_a_position_first(self):
        spare = bag_upgrade.Bag("Small Brown Pouch", 6, used=0, guid=9)
        got = bag_pressure.open_bag_positions(
            [member("Oz", 3), member("Zug", 4, carried=(spare,))]
        )
        self.assertEqual(got, {"Oz": 0, "Zug": 0})

    def test_a_spare_with_things_in_it_is_not_a_spare(self):
        full = bag_upgrade.Bag("Small Brown Pouch", 6, used=2, guid=9)
        got = bag_pressure.open_bag_positions(
            [member("Oz", 3), member("Zug", 4, carried=(full,))]
        )
        self.assertEqual(got, {"Oz": 1, "Zug": 0})


def _source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature: str) -> str:
    src = _source()
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


def _statements(signature: str) -> str:
    body = _block(signature)
    if body.count('"""') >= 2:
        body = body.split('"""', 2)[2]
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )


class TheBridgeRunsEveryFamily(unittest.TestCase):
    def test_the_vendor_loop_runs_every_family_after_its_own(self):
        loop = _statements("    async def _vendor_loop(")
        self.assertLess(
            loop.index("await self._vendor_once()"),
            loop.index("await self._economy_for_every_family()"),
        )

    def test_other_families_run_vendor_then_hand_over_then_purchase(self):
        body = _statements("    async def _economy_for_every_family(")
        self.assertIn("_other_cohorts, own", body)
        self.assertLess(
            body.index("self._vendor_once(c)"), body.index("self._hand_bags_once(")
        )
        self.assertLess(
            body.index("self._hand_bags_once("),
            body.index("self._bag_purchase_and_trip(list(c.names), c)"),
        )

    def test_this_family_buys_bags_too(self):
        body = _statements("    async def _economy_for_every_family(")
        self.assertIn("await self._bag_purchase_and_trip(own)", body)

    def test_another_family_walks_its_own_leader_on_its_own_slot(self):
        body = _statements("    async def _vendor_once(")
        self.assertIn("names, leader = sorted(cohort.names), cohort.leader", body)
        self.assertIn("slot = self._cohort_town_slot(cohort)", body)
        self.assertIn('cohort=getattr(cohort, "key", None)', body)
        self.assertIn('slot.productive("economy")', body)
        self.assertNotIn("self._town_slot", body)

    def test_the_ground_sweep_never_reaches_another_family(self):
        body = _statements("    async def _release_stranded_ground_errands(")
        self.assertIn("if name in names", body)

    def test_a_purchase_is_a_town_trip_buy_row_then_an_equip(self):
        body = _statements("    async def _buy_bags_once(")
        self.assertIn("towntrip.BUY_KIND", body)
        self.assertIn("_insert_town_errand, errand", body)
        self.assertIn("_recent_town_keys", body)
        self.assertLess(
            body.index("_insert_town_errand, errand"),
            body.index("_insert_bag_equip, purchase"),
        )
        self.assertIn("bag_pressure.bag_purchases(buyers, offers)", body)

    def test_no_gm_command_and_no_travel_write_in_the_purchase(self):
        body = _statements("    async def _buy_bags_once(")
        for forbidden in (
            "'gm'",
            "_insert_gm",
            "_write_trade_errand",
            "_claim_town_slot",
            "additem",
        ):
            self.assertNotIn(forbidden, body)

    def test_only_general_bags_are_offered(self):
        sql = _source()[_source().index("_BAG_OFFERS_SQL = (") :]
        sql = sql[: sql.index("def _fetch_bag_offers(")]
        self.assertIn("class = 1 AND subclass = 0", sql)
        self.assertIn("BuyPrice > 0", sql)


if __name__ == "__main__":
    unittest.main()
