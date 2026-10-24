"""The dungeon quest pass says it walks the family only when the walk is taken.

On wow-dev (2026-09-28) "dungeon quests: Zug's family: walk the family to
dungeon quest giver 3665 to turn in" was logged every minute for an hour
while the town slot answered "gave up '3665' ... does not ask for it again
for 1800s". The family was not walking anywhere.
"""

import asyncio
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import campaignqueue  # noqa: E402
import dungeonquests  # noqa: E402


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()
WALK = dungeonquests.Step(
    dungeonquests.GO,
    "walk the family to dungeon quest giver 3665 to turn in",
    hold_planner=True,
    aim=3665,
    giver=3665,
)


class _Pass:
    def __init__(self, granted):
        self.granted = granted

    async def _mid_run(self, names):
        return False

    async def _claim_town_slot(self, claimant, leader, aim, cohort=None):
        return self.granted


FREE = {"Zug": 30, "Oz": 30}
# Members out in a guild run (familyseat.present).
OUT = set()


def run_pass(granted, sellable=None, names=("Zug", "Oz")):
    fam = {"leader": {"name": "Zug"}, "names": list(names)}
    rows = [{"status": campaignqueue.QUEUED, "keyword": "ragefire"}]
    with (
        mock.patch.object(
            bridge, "_fetch_free_slots", lambda names: {n: FREE[n] for n in names}
        ),
        mock.patch.object(bridge, "_guild_run_members_out", lambda: set(OUT)),
        mock.patch.dict(bridge._VENDOR_SELLABLE, sellable or {}, clear=True),
        mock.patch.object(bridge, "_dungeonquest_facts", lambda *a: None),
        mock.patch.object(bridge.dungeonquests, "step", lambda facts: WALK),
        mock.patch.object(bridge.log, "info") as info,
    ):
        held = asyncio.run(
            bridge.Bridge._dungeonquest_for_family(
                _Pass(granted), "Zug", fam, rows, "Zug"
            )
        )
    said = [c.args[0] % c.args[1:] for c in info.call_args_list]
    return held, said


class RefusedWalkTest(unittest.TestCase):
    def test_a_refused_walk_is_not_said(self):
        held, said = run_pass(False)
        self.assertFalse(held)
        self.assertFalse([s for s in said if "walk the family" in s], said)

    def test_a_taken_walk_is_said(self):
        held, said = run_pass(True)
        self.assertTrue(held)
        self.assertTrue([s for s in said if "walk the family" in s], said)


class WithheldForBagRoomTest(unittest.TestCase):
    """A family at three free slots or fewer walks nowhere for a quest."""

    def setUp(self):
        global FREE
        self._saved = dict(FREE)
        FREE["Oz"] = 0
        self.addCleanup(lambda: (FREE.clear(), FREE.update(self._saved)))

    def test_the_walk_waits_and_the_queue_is_not_held(self):
        held, said = run_pass(True)
        self.assertFalse(held)
        self.assertFalse([s for s in said if "walk the family" in s], said)
        self.assertTrue([s for s in said if "waits for bag room" in s], said)

    def test_the_walk_waits_while_a_vendor_trip_can_lift_the_floor(self):
        held, said = run_pass(True, {"Zug": 0, "Oz": 4})
        self.assertFalse(held)
        self.assertTrue([s for s in said if "waits for bag room" in s], said)


class NoVendorTripCanMakeTheRoomTest(unittest.TestCase):
    """#1243: the hold waits on a vendor trip only when one can make room.

    On the dev realm 2026-10-20 Zug's family (Oz, Uzza, Zork, Zrog, Zug) read
    "waits for bag room; the vendor trip keeps the travel column" for 70
    minutes, four minutes after #1204's finding cleared. A member at the floor
    whose stacks no vendor will buy is not lifted by any sale, so no trip the
    vendor pass takes for bag room ever ends that wait: the walk to the quest
    giver is the family's way forward, and turning a quest in frees its items.
    """

    def setUp(self):
        global FREE
        self._saved = dict(FREE)
        FREE["Oz"] = 0
        self.addCleanup(lambda: (FREE.clear(), FREE.update(self._saved)))

    def test_the_walk_is_taken_when_no_sale_lifts_the_floor(self):
        held, said = run_pass(True, {"Zug": 5, "Oz": 0})
        self.assertTrue(held)
        self.assertFalse([s for s in said if "waits for bag room" in s], said)
        self.assertTrue([s for s in said if "walk the family" in s], said)


class TheVendorPassReadingTest(unittest.TestCase):
    """What the vendor pass records is what the hold asks of."""

    def setUp(self):
        patcher = mock.patch.dict(bridge._VENDOR_SELLABLE, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_floor_the_vendor_pass_has_not_read_keeps_the_hold(self):
        self.assertTrue(
            bridge._vendor_trip_makes_room(["Zug", "Oz"], {"Zug": 30, "Oz": 0})
        )

    def test_a_recorded_floor_no_sale_lifts_lets_the_walk_go(self):
        bridge._note_vendor_sellable(["Zug", "Oz"], {"Zug": 5, "Oz": 0})
        self.assertFalse(
            bridge._vendor_trip_makes_room(["Zug", "Oz"], {"Zug": 30, "Oz": 0})
        )

    def test_a_recorded_floor_a_sale_lifts_keeps_the_hold(self):
        bridge._note_vendor_sellable(["Zug", "Oz"], {"Zug": 0, "Oz": 4})
        self.assertTrue(
            bridge._vendor_trip_makes_room(["Zug", "Oz"], {"Zug": 30, "Oz": 0})
        )


class ALentMemberIsNotWaitedForTest(unittest.TestCase):
    """#1375: a member out in a guild run holds no family walk for bag room.

    On the dev realm 2026-10-24 Uzza was lent to a guild run in Razorfen Kraul
    at one free slot with nine stacks a vendor buys. Zug's family read "waits
    for bag room; the vendor trip keeps the travel column" for an hour: the
    leader stood at a vendor that could sell nothing of Uzza's, and the family
    walked nowhere.
    """

    def setUp(self):
        FREE["Uzza"] = 1
        OUT.add("Uzza")
        self.addCleanup(lambda: (FREE.pop("Uzza", None), OUT.clear()))

    def test_the_walk_goes_while_the_floor_is_out_in_a_guild_run(self):
        held, said = run_pass(
            True, {"Zug": 0, "Oz": 0, "Uzza": 9}, names=("Zug", "Oz", "Uzza")
        )
        self.assertTrue(held)
        self.assertFalse([s for s in said if "waits for bag room" in s], said)

    def test_the_same_member_at_home_still_holds_the_walk(self):
        OUT.clear()
        held, said = run_pass(
            True, {"Zug": 0, "Oz": 0, "Uzza": 9}, names=("Zug", "Oz", "Uzza")
        )
        self.assertFalse(held)
        self.assertTrue([s for s in said if "waits for bag room" in s], said)


class TheVendorPassJudgesThePresentMembersTest(unittest.TestCase):
    """#1375: the vendor pass sells for, and holds the leader for, only the
    members standing with the family."""

    def test_present_leaves_out_the_lent_member_and_keeps_the_leader(self):
        import familyseat

        self.assertEqual(
            ["Oz", "Zug"],
            familyseat.present(["Oz", "Uzza", "Zug"], {"Uzza", "Zug"}, "Zug"),
        )

    def test_the_vendor_pass_filters_before_it_settles_the_errand(self):
        import inspect

        body = inspect.getsource(bridge.Bridge._vendor_once)
        self.assertLess(
            body.index("_present_members"),
            body.index("_settle_vendor_errand_and_should_yield"),
        )

    def test_an_unreadable_guild_run_judges_the_whole_family(self):
        class Down(Exception):
            pass

        def broken():
            raise Down("down")

        db = types.SimpleNamespace(err=types.SimpleNamespace(MySQLError=Down))
        with (
            mock.patch.object(bridge, "pymysql", db),
            mock.patch.object(bridge, "_guild_run_members_out", broken),
            mock.patch.object(bridge.log, "exception"),
        ):
            self.assertEqual(
                ["Uzza", "Zug"], bridge._present_members(["Uzza", "Zug"], "Zug")
            )


if __name__ == "__main__":
    unittest.main()
