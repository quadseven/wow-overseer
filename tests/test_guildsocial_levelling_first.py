"""Levelling seats ask first: a guild has three open asks and, on the dev
realm, a day of them went mostly to members who cannot level in a dungeon.

Measured over 24 hours on the dev realm: 883 dungeon asks, the guilds' open
asks averaging 3.0 and 3.3 against a cap of 3, so every freed slot was taken at
once. Asks by a member at level 50 or more were 337 (38 percent) and formed 7
runs (2.1 percent); asks by a raid seat under 50 were 297 and formed 75 runs
(25.3 percent). The slot went to whoever had the strongest gear need, so a
level 55 member's best-in-slot ask took a slot a seat that still has levels to
gain could have used.

These pin the order the social layer picks askers in: a raid seat under the
order's level gate first, any other member under it next, everyone else last,
the gear need ranking within each tier. They use the public seam, plan_pass.
"""

import unittest

import guildsocial as gs
from test_guildsocial import ROGUE, MAGE, WARLOCK, mate, plan

BLOOD = "Combat"


def need(name, keyword, gain, preraid=False):
    return gs.Need(
        name,
        keyword,
        "Item of " + name,
        entry=1,
        gain=gain,
        preraid=preraid,
        slot="chest",
    )


def askers(out):
    return [p.asker for p in out.posts]


class TheAskerOrder(unittest.TestCase):
    def setUp(self):
        # A level 55 member whose pre-raid pick outranks any gear need by rank,
        # a level 20 raid seat with a weak need, a level 20 member with no seat
        # and a strong need.
        self.old = mate("Cole", 55, MAGE, target_tree="Fire")
        self.seat = mate("Bree", 20, ROGUE, target_tree=BLOOD)
        self.plain = mate("Dane", 20, WARLOCK)
        self.needs = {
            "Cole": [need("Cole", "maraudon-orange", 9.0, preraid=True)],
            "Bree": [need("Bree", "deadmines", 1.0)],
            "Dane": [need("Dane", "wailing", 8.0)],
        }

    def test_a_raid_seat_under_the_gate_asks_before_a_stronger_need_at_level_55(self):
        out = plan([self.old, self.seat, self.plain], needs=self.needs)
        # Two new asks a guild a pass: the seat, then the other member under the
        # gate. The level 55 pre-raid ask waits for a free slot.
        self.assertEqual(askers(out), ["Bree", "Dane"])

    def test_without_a_seat_under_the_gate_the_level_55_member_still_asks(self):
        out = plan([self.old], needs={"Cole": self.needs["Cole"]})
        self.assertEqual(askers(out), ["Cole"])

    def test_a_member_under_the_gate_without_a_seat_asks_before_level_55(self):
        out = plan([self.old, self.plain], needs=self.needs)
        self.assertEqual(askers(out), ["Dane", "Cole"])

    def test_within_a_tier_the_stronger_need_still_goes_first(self):
        other = mate("Ewan", 21, ROGUE, target_tree=BLOOD)
        needs = dict(self.needs)
        needs["Ewan"] = [need("Ewan", "deadmines", 6.0)]
        out = plan([self.seat, other, self.old], needs=needs)
        self.assertEqual(askers(out), ["Ewan", "Bree"])

    def test_the_switch_off_restores_the_old_order(self):
        with unittest_env(gs.SEATS_LEVEL_FIRST_ENV, "off"):
            out = plan([self.old, self.seat, self.plain], needs=self.needs)
        self.assertEqual(askers(out), ["Cole", "Dane"])

    def test_the_gate_is_the_orders_level_50(self):
        self.assertEqual(gs.ORDER_LEVEL_GATE, 50)
        at_gate = mate("Fynn", 50, MAGE, target_tree="Fire")
        out = plan(
            [at_gate, self.plain],
            needs={
                "Fynn": [need("Fynn", "maraudon-orange", 9.0, preraid=True)],
                "Dane": self.needs["Dane"],
            },
        )
        self.assertEqual(askers(out), ["Dane", "Fynn"])


class unittest_env:
    """Set one environment variable for a block and restore it after."""

    def __init__(self, key, value):
        self.key, self.value = key, value

    def __enter__(self):
        import os

        self.old = os.environ.get(self.key)
        os.environ[self.key] = self.value

    def __exit__(self, *exc):
        import os

        if self.old is None:
            os.environ.pop(self.key, None)
        else:
            os.environ[self.key] = self.old


if __name__ == "__main__":
    unittest.main()
