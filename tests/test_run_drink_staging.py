"""`_run_drink_once` hands a dry healer a drink while a run stages (#2060).

Driven for real with the reads stubbed, not read as source: the question is
which planner the pass asks when `_mid_run` is false, and whether a give the
town trip already wrote stays the only one.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

import towntrip
from test_guildsocial_bridge import bridge


class _Drive(unittest.TestCase):
    def drive(self, *, mid_run, staging, seen=frozenset()):
        """Run the pass once; return (inserted errands, planners asked)."""
        asked, inserted = [], []
        errand = towntrip.Errand(
            "Og", towntrip.GIVE_KIND, "guid:31", "spare water", taker="Grog"
        )

        def planner(name):
            def plan(members, apart):
                asked.append(name)
                return [errand]

            return plan

        async def mid(_names):
            return mid_run

        this = SimpleNamespace(_mid_run=mid)
        patches = {
            "_family_of": lambda cohort=None: (["Og", "Grog"], "Og"),
            "_staging_phase": lambda leader: staging,
            "_fetch_town_worn": lambda names: [],
            "_fetch_town_carried": lambda names: [],
            "_fetch_town_spells": lambda names: [],
            "_fetch_free_slots": lambda names: {},
            "_fetch_positions": lambda names: {},
            "_standin_out": lambda: frozenset(),
            "_recent_town_keys": lambda minutes: set(seen),
            "_insert_town_errand": lambda e: inserted.append(e) or 1,
        }
        with (
            mock.patch.multiple(bridge, **patches),
            mock.patch.object(bridge.towntrip, "members_from_rows", lambda *a: []),
            mock.patch.object(bridge.towntrip, "in_run_drink", planner("in_run")),
            mock.patch.object(bridge.towntrip, "entry_drink", planner("entry")),
        ):
            asyncio.run(bridge.Bridge._run_drink_once(this))
        return inserted, asked


class TheStagingBranch(_Drive):
    def test_staging_and_not_mid_run_asks_the_entry_planner(self):
        inserted, asked = self.drive(mid_run=False, staging="gather")
        self.assertEqual(asked, ["entry"])
        self.assertEqual([e.command for e in inserted], ["guid:31"])

    def test_mid_run_still_asks_the_in_run_planner(self):
        _, asked = self.drive(mid_run=True, staging="")
        self.assertEqual(asked, ["in_run"])

    def test_neither_mid_run_nor_staging_asks_nobody(self):
        inserted, asked = self.drive(mid_run=False, staging="")
        self.assertEqual((asked, inserted), ([], []))

    def test_a_give_the_town_trip_already_wrote_is_not_written_twice(self):
        """Both passes key a give by (giver, guid:N) in source='towntrip'."""
        inserted, asked = self.drive(
            mid_run=False, staging="gather", seen={("Og", "guid:31")}
        )
        self.assertEqual(asked, ["entry"])
        self.assertEqual(inserted, [])


class ADryHealerIsActuallyHandedTheStack(unittest.TestCase):
    """No planner is stubbed: real members in, the queued row is the proof."""

    def _water(self, guid, count):
        return towntrip.Stack(
            guid=guid,
            entry=8077,
            name="Conjured Mineral Water",
            count=count,
            what="drink",
            conjured=True,
        )

    def _members(self):
        mage = towntrip.Member(
            "Og",
            "mage",
            51,
            10**6,
            9,
            (),
            food_carried=20,
            drink_carried=55,
            spells=frozenset({990, 5506}),
            stacks=(self._water(31, 20), self._water(32, 20), self._water(33, 15)),
        )
        healer = towntrip.Member(
            "Grog", "paladin", 53, 10**6, 8, (), food_carried=20, drink_carried=0
        )
        return [mage, healer]

    def _drive(self, *, mid_run, staging):
        inserted = []

        async def mid(_names):
            return mid_run

        beside = {
            "Og": {"map_id": 230, "pos_x": 1.0, "pos_y": 1.0, "instance_id": 7},
            "Grog": {"map_id": 230, "pos_x": 2.0, "pos_y": 1.0, "instance_id": 7},
        }
        patches = {
            "_family_of": lambda cohort=None: (["Og", "Grog"], "Og"),
            "_staging_phase": lambda leader: staging,
            "_fetch_town_worn": lambda names: [],
            "_fetch_town_carried": lambda names: [],
            "_fetch_town_spells": lambda names: [],
            "_fetch_free_slots": lambda names: {},
            "_fetch_positions": lambda names: beside,
            "_standin_out": lambda: frozenset(),
            "_recent_town_keys": lambda minutes: set(),
            "_insert_town_errand": lambda e: inserted.append(e) or 1,
        }
        with (
            mock.patch.multiple(bridge, **patches),
            mock.patch.object(
                bridge.towntrip, "members_from_rows", lambda *a: self._members()
            ),
        ):
            asyncio.run(bridge.Bridge._run_drink_once(SimpleNamespace(_mid_run=mid)))
        return inserted

    def test_staging_hands_the_dry_healer_the_mages_spare_stack(self):
        inserted = self._drive(mid_run=False, staging="gather")
        self.assertEqual(
            [(e.kind, e.member, e.taker, e.command) for e in inserted],
            [(towntrip.GIVE_KIND, "Og", "Grog", "guid:31")],
        )

    def test_without_staging_the_dry_healer_waits_for_the_run(self):
        self.assertEqual(self._drive(mid_run=False, staging=""), [])


if __name__ == "__main__":
    unittest.main()
