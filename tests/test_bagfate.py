"""bagfate: each carried stack in one pile, and what stops the piles (#88)."""

import unittest

import bagfate
import bonds
import gear
import wealth


def row(guid, cls, quality=1, price=10, **kw):
    r = {
        "item_guid": guid,
        "entry": guid,
        "item_name": "Item %d" % guid,
        "class": cls,
        "quality": quality,
        "sell_price": price,
    }
    r.update(kw)
    return r


class ThePilesTest(unittest.TestCase):
    def test_a_quest_item_an_open_quest_needs_is_kept(self):
        self.assertEqual(
            bagfate.pile_of(row(1, bagfate.QUEST, quest_needed=1), None, "A")[0],
            bagfate.QUESTS,
        )
        # No answer at all is read as needed, the vendor's fail-closed way.
        self.assertEqual(
            bagfate.pile_of(row(1, bagfate.QUEST), None, "A")[0], bagfate.QUESTS
        )

    def test_a_quest_leftover_with_a_price_is_junk(self):
        self.assertEqual(
            bagfate.pile_of(row(1, bagfate.QUEST, quest_needed=0), None, "A")[0],
            bagfate.JUNK,
        )

    def test_a_priceless_quest_leftover_says_nothing_destroys_it(self):
        key = bagfate.pile_of(
            row(1, bagfate.QUEST, price=0, quest_needed=0), None, "A"
        )[0]
        self.assertEqual(key, bagfate.LEFTOVERS)
        self.assertEqual(bagfate.PILES[key][3], 144)

    def test_grey_trash_is_junk_and_a_priceless_one_is_not(self):
        self.assertEqual(
            bagfate.pile_of(row(1, 15, quality=0), None, "A")[0], bagfate.JUNK
        )
        self.assertNotEqual(
            bagfate.pile_of(row(1, 15, quality=0, price=0), None, "A")[0], bagfate.JUNK
        )

    def test_a_gem_is_never_junk_even_when_it_is_plain(self):
        self.assertEqual(
            bagfate.pile_of(row(1, bagfate.GEM, quality=1), None, "A")[0], bagfate.GEMS
        )

    def test_trade_goods_are_kept_for_the_trade_not_sold(self):
        self.assertEqual(
            bagfate.pile_of(row(1, bagfate.TRADE_GOODS, quality=1), None, "A")[0],
            bagfate.TRADE,
        )

    def test_gear_follows_the_gear_check(self):
        g = row(1, bagfate.ARMOR, quality=2)
        self.assertEqual(bagfate.pile_of(g, "A", "A"), (bagfate.FOR_HOLDER, "A"))
        self.assertEqual(bagfate.pile_of(g, "B", "A"), (bagfate.FOR_RELATIVE, "B"))
        self.assertEqual(bagfate.pile_of(g, gear.UNJUDGEABLE, "A")[0], bagfate.UNJUDGED)
        self.assertEqual(bagfate.pile_of(g, None, "A")[0], bagfate.UNJUDGED)

    def test_a_trade_tool_is_a_tool_whatever_the_gear_check_says(self):
        pick = row(1, bagfate.WEAPON, quality=1, bag_family=1024)
        self.assertEqual(bagfate.pile_of(pick, "B", "A")[0], bagfate.TOOLS)

    def test_nobodys_gear_goes_to_auction_only_while_it_is_still_tradable(self):
        boe = row(1, bagfate.WEAPON, quality=2, bonding=2, instance_flags=0)
        worn_once = dict(boe, instance_flags=1)
        self.assertEqual(bagfate.pile_of(boe, gear.NOBODY, "A")[0], bagfate.AUCTION)
        self.assertEqual(bagfate.pile_of(worn_once, gear.NOBODY, "A")[0], bagfate.DUST)
        white = row(2, bagfate.ARMOR, quality=1)
        self.assertEqual(
            bagfate.pile_of(white, gear.NOBODY, "A")[0], bagfate.VENDOR_GEAR
        )


class TheTablesAgreeTest(unittest.TestCase):
    def test_every_pile_has_words_and_a_place_in_the_order(self):
        """build_fates sorts by ORDER.index; a pile in one table and not the
        other would fail the whole card, so the two are pinned equal."""
        self.assertEqual(set(bagfate.PILES), set(bagfate.ORDER))
        self.assertEqual(len(bagfate.ORDER), len(set(bagfate.ORDER)))


class TheCardTest(unittest.TestCase):
    def test_piles_are_counted_ordered_and_carry_their_ticket(self):
        rows = [
            row(1, bagfate.QUEST, price=0, quest_needed=0),
            row(2, bagfate.QUEST, price=0, quest_needed=0),
            row(3, 15, quality=0),
            row(4, bagfate.GEM, quality=2),
        ]
        f = bagfate.build_fates("A", rows, {}, free_slots=1, managed=True)
        keys = [p["key"] for p in f["piles"]]
        self.assertEqual(keys, [bagfate.JUNK, bagfate.GEMS, bagfate.LEFTOVERS])
        leftovers = f["piles"][2]
        self.assertEqual(leftovers["count"], "2 stacks")
        self.assertEqual(leftovers["ticket"]["label"], "#144")
        self.assertIn("/issues/144", leftovers["ticket"]["url"])
        self.assertEqual(f["piles"][1]["tone"], bagfate.ALARM)

    def test_junk_waits_for_the_trip_while_there_is_still_room(self):
        f = bagfate.build_fates(
            "A", [row(3, 15, quality=0)], {}, free_slots=20, managed=True
        )
        self.assertEqual(f["piles"][0]["blocker"], bagfate.TRIP_WAIT)
        self.assertEqual(f["piles"][0]["tone"], bagfate.CAUTION)
        tight = bagfate.build_fates(
            "A", [row(3, 15, quality=0)], {}, free_slots=2, managed=True
        )
        self.assertIsNone(tight["piles"][0]["blocker"])

    def test_a_character_no_pass_manages_says_so_instead_of_piles(self):
        f = bagfate.build_fates("Z", [row(1, bagfate.QUEST)], {}, 5, managed=False)
        self.assertEqual(f["piles"], [])
        self.assertEqual(f["unmanaged"]["ticket"]["label"], "#150")

    def test_the_relative_is_named_in_the_label_and_the_route(self):
        g = row(9, bagfate.ARMOR, quality=2)
        f = bagfate.build_fates("A", [g], {9: "B"}, 1, True)
        self.assertEqual(f["piles"][0]["label"], "gear for B")
        self.assertIn("once B is close by", f["piles"][0]["route"])


class TheFamilyClaimsTest(unittest.TestCase):
    def test_an_upgrade_is_claimed_by_the_one_it_suits(self):
        # A priest wearing a level 10 chest; a level 30 cloth chest in the
        # warrior's bag is the priest's upgrade.
        carried = {
            "W": [
                row(
                    5,
                    bagfate.ARMOR,
                    quality=2,
                    item_level=30,
                    required_level=25,
                    allowable_class=-1,
                    inventory_type=5,
                    subclass=1,
                    instance_flags=0,
                )
            ]
        }
        worn = {
            "W": [{"inventory_type": 5, "item_level": 40}],
            "P": [{"inventory_type": 5, "item_level": 10}],
        }
        claims = bagfate.family_claims(carried, worn, {"W": (1, 30), "P": (5, 30)})
        self.assertEqual(claims.get(5), "P")


class TheBagsPayloadTest(unittest.TestCase):
    def test_both_families_are_drawn_and_only_the_managed_one_gets_piles(self):
        managed = next(iter(bonds.FAMILY))
        chars = [
            {"name": managed, "level": 60, "class": 1, "race": 1, "money": 0},
            {"name": "Zed", "level": 10, "class": 1, "race": 2, "money": 0},
        ]
        p = wealth.build_wealth(
            chars, [], [], [], {}, families=[("Zed", ["Zed"]), ("A", [managed])]
        )
        self.assertEqual([s["faction"] for s in p["sides"]], ["alliance", "horde"])
        by = {m["name"]: m for m in p["members"]}
        self.assertIsNone(by[managed]["fates"]["unmanaged"])
        self.assertEqual(by["Zed"]["fates"]["unmanaged"]["ticket"]["label"], "#150")
        self.assertEqual(by["Zed"]["who"], "10 Warrior")

    def test_a_roster_name_with_no_saved_character_still_gets_a_card(self):
        """Every roster name gets a member (an absent one when there is no
        `characters` row), so the side lists never reach for a missing key."""
        managed = next(iter(bonds.FAMILY))
        chars = [{"name": managed, "level": 60, "class": 1, "race": 1, "money": 0}]
        p = wealth.build_wealth(
            chars, [], [], [], {}, families=[("A", [managed, "Gone"])]
        )
        self.assertEqual(p["sides"][0]["names"], [managed, "Gone"])
        gone = next(m for m in p["members"] if m["name"] == "Gone")
        self.assertFalse(gone["present"])


if __name__ == "__main__":
    unittest.main()
