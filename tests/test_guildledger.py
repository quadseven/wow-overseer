"""The guild ledger: one picture of what the vault, the members and the
bankers hold, folded from the reads the bank pass and the item plan make."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import bank  # noqa: E402
import guildledger  # noqa: E402
from test_bank import row  # noqa: E402


def members(rows, names):
    return bank.members_from_rows(rows, names)


class WhatEveryoneHolds(unittest.TestCase):
    def setUp(self):
        rows = [
            row(holder="Ugga", item_guid=1, entry=2589, name="Linen Cloth", count=20),
            row(holder="Hoarg", item_guid=2, entry=2589, name="Linen Cloth", count=40),
        ]
        self.ledger = guildledger.build(
            members(rows, ["Ugga"]),
            bankers=members(rows, ["Hoarg"]),
            vault=[{"tab": 0, "entry": 2589, "count": 100}],
        )

    def test_held_names_each_holder_by_kind(self):
        self.assertEqual(
            {"Ugga": 20, "Hoarg": 40, "vault": 100},
            dict(self.ledger.held[2589]),
        )

    def test_an_entry_nobody_holds_is_absent(self):
        self.assertNotIn(9, self.ledger.held)


class WhatTheBankersCanTake(unittest.TestCase):
    def test_room_is_bag_and_bank_free_less_the_reserves(self):
        banker = members([], ["Hoarg"])
        ledger = guildledger.build([], bankers=banker, vault=[])
        free = banker[0].bag_free + banker[0].bank_free
        want = (banker[0].bag_free - guildledger.BAG_RESERVE) + (
            banker[0].bank_free - bank.BANK_FREE_RESERVE
        )
        self.assertEqual(max(0, want), ledger.banker_room())
        self.assertLess(ledger.banker_room(), free)

    def test_no_bankers_means_no_room(self):
        self.assertEqual(0, guildledger.build([], bankers=[], vault=[]).banker_room())

    def test_a_full_banker_has_none(self):
        rows = [
            row(holder="Hoarg", item_guid=i, entry=1000 + i, slot=slot)
            for i, slot in enumerate(list(range(23, 39)) + list(range(39, 67)), 1)
        ]
        banker = members(rows, ["Hoarg"])
        self.assertEqual(
            0, guildledger.build([], bankers=banker, vault=[]).banker_room()
        )


class TheSummaryLine(unittest.TestCase):
    def test_it_says_what_the_bankers_hold_and_can_take(self):
        ledger = guildledger.build(
            [],
            bankers=members([], ["Hoarg"]),
            vault=[{"tab": 0, "entry": 1, "count": 1}],
        )
        line = ledger.line("Cave")
        self.assertIn("Cave", line)
        self.assertIn("1 banker", line)


class TheShadowReadOfBankerRoom(unittest.TestCase):
    NAMES = ["Grug", "Ugga", "Grog", "Bork", "Og"]

    class Seat:
        def __init__(self, name):
            self.name = name

    def test_room_is_read_only_for_bankers_in_the_guild_roster(self):
        import itemplan_reads

        asked = []

        def bank_rows(names):
            asked.append(list(names))
            return []

        got = itemplan_reads._banker_room(
            self.NAMES, "Grug", bank_rows, lambda names: [self.Seat("Hoarg")]
        )
        self.assertEqual([["Hoarg"]], asked)
        self.assertEqual({"Grug"}, set(got))
        self.assertGreater(got["Grug"], 0)

    def test_no_banker_in_the_roster_is_no_room_not_phantom_room(self):
        import itemplan_reads

        got = itemplan_reads._banker_room(
            self.NAMES, "Grug", lambda n: [], lambda names: [self.Seat("Pokka")]
        )
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
