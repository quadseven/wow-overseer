"""A member at the bag floor with nothing to sell banks what it does not use.

#1000. Measured 2026-10-15: one family was held 0.93 hours at the bag floor
with the reason the bridge names: "Grog carries nothing a vendor will buy".
The town pass sells only vendor trash, so a member whose bags fill with kept
items stays at the floor and holds the family. Banks are free and every
capital has one, so the next town pass walks to the bank: profession stock
the member's own professions do not need goes first, then uncommon or better
gear it cannot wear, until it is above the floor or the bank is full.

Pinned here:

  * bank.BAG_FLOOR_FREE_SLOTS is bag_pressure.TOWN_RUN_FREE_SLOTS.
  * floor_bank={"Grog"} deposits the unneeded profession stock first, then
    the unwearable gear, and the deposit count brings Grog above the floor.
  * Without the flag the same rows plan nothing new: the unwearable green
    stays in the bags.
  * A full bank is named in the plan's notes ("Grog's bank is full"), which is
    what the hold reason names next.
"""

import unittest

import bag_pressure
import bank


def row(**kw):
    """One joined character_inventory row, as the bridge's SQL names it."""
    base = dict(
        holder="Grog",
        level=40,
        item_guid=1,
        count=1,
        name="Linen Cloth",
        quality=1,
        sell_price=10,
        required_level=0,
        bonding=0,
        item_class=7,
        container_slots=0,
        bag=0,
        slot=23,
    )
    base.update(kw)
    return base


# Grog works tailoring, so his cloth is his own stock.
TAILOR = {"Grog": {"tailoring": 150}}
# Five stacks of 20 against the keeper cap of 40: the first two are what his
# trade keeps, the last three are what his professions do not need.
STOCK = [
    row(item_guid=100 + i, name="Linen Cloth", count=20, slot=23 + i) for i in range(5)
]
# An uncommon chest he cannot wear yet: required level 50, Grog is 40.
GREEN = row(
    item_guid=200,
    name="Green Chest",
    quality=2,
    item_class=4,
    required_level=50,
    bonding=1,
    slot=28,
)
NEUTRAL = [
    row(item_guid=201, name="Tome of Valor", item_class=12, sell_price=0, slot=29),
    row(item_guid=202, name="Conjured Bread", item_class=0, sell_price=0, slot=30),
    row(
        item_guid=203,
        name="Hearthstone",
        item_class=15,
        sell_price=0,
        bonding=1,
        slot=31,
    ),
    # A worn-out sword he CAN wear: common, never a floor-bank candidate.
    row(item_guid=204, name="Rusty Sword", item_class=2, bonding=1, slot=32),
]
# Six quest items fill the last slots: 5 + 1 + 4 + 6 = 16, the backpack full.
FILLER = [
    row(
        item_guid=300 + i,
        name="Tome of Valor",
        item_class=12,
        sell_price=0,
        slot=33 + i,
    )
    for i in range(6)
]


def _grog_floor():
    return STOCK + [GREEN] + NEUTRAL + FILLER


def _plan(rows, **kw):
    storage = bank.storage_from(TAILOR)
    return bank.plan(
        bank.members_from_rows(rows, ["Grog"]),
        bank.family_from_skills(TAILOR),
        storage=storage,
        **kw,
    )


class TheFloorIsTheTownRunFloor(unittest.TestCase):
    def test_the_floor_matches_bag_pressure(self):
        self.assertEqual(bag_pressure.TOWN_RUN_FREE_SLOTS, bank.BAG_FLOOR_FREE_SLOTS)


class AFloorMemberWithNothingSoldBanksWhatItDoesNotUse(unittest.TestCase):
    def test_grog_is_measured_at_the_floor(self):
        members = bank.members_from_rows(_grog_floor(), ["Grog"])
        self.assertEqual(0, members[0].bag_free)

    def test_stock_first_then_unwearable_gear_ends_above_the_floor(self):
        plan = _plan(_grog_floor(), floor_bank={"Grog"})
        moves = [m for m in plan.moves if m.verb == bank.DEPOSIT]
        # Three unneeded stock stacks, then the green chest: four slots, and
        # 0 + 4 is above the floor of 3.
        self.assertEqual([102, 103, 104, 200], [m.guid for m in moves])
        self.assertTrue(all(m.to == bank.PERSONAL for m in moves))
        self.assertGreater(0 + len(moves), bank.BAG_FLOOR_FREE_SLOTS)

    def test_without_the_flag_the_green_stays_in_the_bags(self):
        plan = _plan(_grog_floor())
        guids = {m.guid for m in plan.moves}
        self.assertIn(102, guids)  # the keeper rule still banks surplus
        self.assertNotIn(200, guids)

    def test_a_member_above_the_floor_banks_nothing_for_it(self):
        rows = _grog_floor()[:12]  # four stacks fewer: 4 free
        members = bank.members_from_rows(rows, ["Grog"])
        self.assertEqual(4, members[0].bag_free)
        plan = _plan(rows, floor_bank={"Grog"})
        self.assertNotIn(200, {m.guid for m in plan.moves})


class AFullBankIsNamed(unittest.TestCase):
    def _grog_floor_bank_full(self):
        rows = _grog_floor()
        banked = [
            row(
                item_guid=400 + i,
                name="Linen Cloth",
                count=20,
                bag=0,
                slot=39 + i,
            )
            for i in range(bank.BANK_SIZE)
        ]
        return rows + banked

    def test_the_bank_reads_full(self):
        members = bank.members_from_rows(self._grog_floor_bank_full(), ["Grog"])
        self.assertEqual(0, members[0].bank_free)

    def test_the_note_names_the_full_bank(self):
        plan = _plan(self._grog_floor_bank_full(), floor_bank={"Grog"})
        self.assertEqual((), plan.moves)
        self.assertTrue(
            any("Grog's bank is full" in note for note in plan.notes),
            plan.notes,
        )


if __name__ == "__main__":
    unittest.main()
