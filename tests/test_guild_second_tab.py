"""A guild's second vault tab is used, and set up in one trip.

Measured on the dev realm on 2026-11-15: both guilds kept tab 0 at 98 of 98
stacks while tab 1 stood bought and empty. One guild's tab 1 was also closed to
every rank but the master, because the setup pass issued one rights command per
arrival at the vault and the arrivals were days apart. Two faults:

  1. A keeper that could not go to its wanted tab or to Materials had nowhere
     to go, though another purchased tab had room.
  2. The master finished a bought tab's rights and name one command per trip.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bank  # noqa: E402
import guildbank  # noqa: E402
from test_bank import row  # noqa: E402

NAMES = ["Ugga", "Zug", "Bork"]
HELD = {"Ugga": {"herbalism": 10}}


def guild(tabs, items):
    return {
        "purchased_tabs": tabs,
        "deposit_rank_ids": [0],
        "member_ranks": {"Ugga": 0, "Zug": 0, "Bork": 0},
        "tab_items": items,
    }


def stacks():
    return [
        row(
            holder="Ugga",
            item_guid=2,
            name="Moss Agate",
            entry=1206,
            item_class=3,
            quality=2,
            count=50,
            slot=23,
        ),
    ]


def plan(vault):
    storage = bank.storage_from(HELD, guild=vault, named={})
    return bank.plan(
        bank.members_from_rows(stacks(), NAMES),
        bank.family_from_skills(HELD),
        storage=storage,
    )


class AFullMaterialsTabOverflowsIntoTheNextOpenTab(unittest.TestCase):
    def test_a_keeper_goes_to_tab_one_when_tab_zero_is_full(self):
        result = plan(guild(2, {0: 98, 1: 0}))
        self.assertEqual([1], [m.tab for m in result.guild])

    def test_tab_zero_still_comes_first_while_it_has_room(self):
        result = plan(guild(2, {0: 40, 1: 0}))
        self.assertEqual([0], [m.tab for m in result.guild])

    def test_the_raid_supplies_tab_is_never_an_overflow(self):
        result = plan(guild(3, {0: 98, 1: 98, 2: 0}))
        self.assertEqual([], list(result.guild))

    def test_every_tab_full_sends_nothing(self):
        result = plan(guild(2, {0: 98, 1: 98}))
        self.assertEqual([], list(result.guild))


class ASetupArrivalFinishesTheBoughtTab(unittest.TestCase):
    def actions(self):
        return guildbank.plan_setup(
            leader="Zug",
            purchased_tabs=2,
            rank_ids=(0, 1, 2, 3, 4),
            deposit_rank_ids=(0,),
            tab_names={0: "Materials", 1: ""},
            wanted_tabs=2,
        )

    def test_one_arrival_carries_every_missing_command(self):
        chosen = guildbank.setup_for_arrival(self.actions(), seen=set())
        self.assertEqual(
            [
                "bank grant-deposit rank:1",
                "bank grant-deposit rank:2",
                "bank grant-deposit rank:3",
                "bank grant-deposit rank:4",
                "bank name-tab tab:1 icon:INV_Chest_Chain_05 Gear for Later",
            ],
            [a.command for a in chosen],
        )

    def test_a_command_asked_inside_the_retry_window_is_not_asked_again(self):
        seen = {("Zug", "bank grant-deposit rank:1")}
        chosen = guildbank.setup_for_arrival(self.actions(), seen=seen)
        self.assertNotIn("bank grant-deposit rank:1", [a.command for a in chosen])
        self.assertEqual(4, len(chosen))

    def test_a_purchase_rides_alone(self):
        actions = guildbank.plan_setup(
            leader="Zug",
            purchased_tabs=1,
            rank_ids=(0, 1),
            deposit_rank_ids=(0,),
            tab_names={0: "Materials"},
        )
        chosen = guildbank.setup_for_arrival(actions, seen=set())
        self.assertEqual(["bank buy-tab tab:1"], [a.command for a in chosen])


if __name__ == "__main__":
    unittest.main()
