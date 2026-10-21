"""A member sitting out to craft neither holds back nor latches the banker trip (#872).

Measured on wow-dev 2026-10-20: Og (sitting out of Grug's family to craft,
standin.py) logged "bank bags: Og puts a 8-slot bag in its bank bag slot 1;
it waits for a banker" at 16:38Z and again at 22:38Z with no banker trip in
between, and the one bank pass that reached the errand said "leader=Grug is
not taking a banker trip while the family has remained split for 26015
seconds". The split was Og: a member off the campaign stands wherever it
crafts, 2804 yards from its family at the time.

Two defects, one cause. The bank pass counted the sitting-out member in its
family split clock, so the whole family's banker trip was deferred for as
long as the member crafted. And a sitting-out member's own step was a reason
to walk the leader to a banker the member never follows to: with the leader
at the counter and that step never written, `bank.errand_step` held the aim
for good. Every other family-wide gate already leaves the member out
(`bridge._standin_running`); these drive the real `_bank_once` with the reads
stubbed and pin that the bank trip does too.
"""

import asyncio
import sys
import time
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import bank  # noqa: E402
import bankbags  # noqa: E402
import vendor_stall  # noqa: E402


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

NAMES = ["Bork", "Grug", "Og", "Ugga"]
TOGETHER = {"map_id": 0, "pos_x": 0.0, "pos_y": 0.0}
FAR = {"map_id": 0, "pos_x": 2804.0, "pos_y": 0.0}


class _Run:
    """One `_bank_once` with every read stubbed; what it decided, recorded."""

    def __init__(
        self,
        *,
        sitting=("Og",),
        counter=(),
        positions=None,
        item_moves=(),
        previous_split=None,
    ):
        self.sitting = frozenset(sitting)
        self.counter = set(counter)
        self.positions = positions or {n: TOGETHER for n in NAMES}
        self.item_moves = list(item_moves)
        self.previous_split = previous_split
        self.steps, self.aims, self.released, self.inserted = [], [], [], []
        self.notes, self.warnings, self.split_names = [], [], []

    def run(self):
        this = bridge.Bridge.__new__(bridge.Bridge)
        this._bank_family_movement = {}
        if self.previous_split is not None:
            this._bank_family_movement["Grug"] = self.previous_split

        async def mid_run(names):
            return False

        async def exit_route(*args):
            return False

        async def claim(claimant, character, aim, **kwargs):
            self.aims.append((character, aim))
            return True

        settle = this._settle_bank_errand

        async def recording_settle(*args, **kwargs):
            self.steps.append(await settle(*args, **kwargs))
            return self.steps[-1]

        this._mid_run = mid_run
        this._bank_exit_route = exit_route
        this._claim_town_slot = claim
        this._cohort_town_slot = lambda cohort=None: None
        this._settle_bank_errand = recording_settle
        log = types.SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda msg, *a, **k: self.warnings.append(msg % a),
            debug=lambda *a, **k: None,
        )
        # Og has a spare 8-slot bag for its bought slot; nobody else has a step.
        bag_facts = [
            bankbags.Facts(name="Bork", worn=(10, 10, 10, 10)),
            bankbags.Facts(name="Grug", worn=(10, 10, 10, 10)),
            bankbags.Facts(
                name="Og",
                bought=1,
                worn=(10, 10, 10, 10),
                spare=(bankbags.Bag(guid=77, entry=4245, slots=8),),
            ),
            bankbags.Facts(name="Ugga", worn=(10, 10, 10, 10)),
        ]

        def log_changed(prefix, notes, key=(), capped=True):
            if prefix == "bank bags":
                self.notes.extend(notes)

        real_progress = vendor_stall.family_progress

        def family_progress(previous, positions, names, now, **kwargs):
            self.split_names.append(list(names))
            return real_progress(previous, positions, names, now, **kwargs)

        with (
            mock.patch.object(bridge.vendor_stall, "family_progress", family_progress),
            mock.patch.multiple(
                bridge,
                log=log,
                _STANDIN_OUT=self.sitting,
                _pass_completed=lambda name: True,
                _family_of=lambda cohort=None: (list(NAMES), "Grug"),
                _plan_bank=lambda names: bank.Plan(moves=tuple(self.item_moves)),
                _log_changed=log_changed,
                _recent_bank_keys=lambda minutes: set(),
                _fetch_positions=lambda names: {
                    n: self.positions[n] for n in names if n in self.positions
                },
                _fetch_bank_bag_facts=lambda names: list(bag_facts),
                _fetch_town=lambda name: types.SimpleNamespace(
                    banker=name in self.counter
                ),
                _outstanding_bank_moves=lambda names: 0,
                _current_travel_npc=lambda name: (
                    "banker" if "Grug" in self.counter else ""
                ),
                _nearest_banker_yards=lambda name: 80.0,
                _release_trade_errand=lambda name, aim: (
                    self.released.append((name, aim)) or True
                ),
                _insert_bank=lambda move, command: (
                    self.inserted.append((move.character, command)) or 1
                ),
            ),
        ):
            asyncio.run(this._bank_once())
        return self


def _ugga_deposit():
    return bank.Move("Ugga", "deposit", 501, "Rough Stone", 5, "kept in the bank")


class ASittingOutMembersStepIsNotTheFamilysTrip(unittest.TestCase):
    def test_its_bag_step_alone_does_not_walk_the_leader_to_a_banker(self):
        """The leader's trip never reaches a member that does not follow it."""
        run = _Run().run()
        self.assertEqual(run.aims, [], "no banker aim for Og's step alone")
        self.assertEqual(run.steps, [bank.BANK_ERRAND_RELEASE])
        self.assertEqual(run.inserted, [])

    def test_the_leader_at_the_counter_does_not_hold_the_aim_for_it(self):
        """The latch: Og's row is never written while Og is elsewhere, so a
        hold for it would keep the family at the banker for good."""
        run = _Run(counter=("Grug", "Bork", "Ugga")).run()
        self.assertEqual(run.steps, [bank.BANK_ERRAND_RELEASE])
        self.assertEqual(run.released, [("Grug", "banker")])
        self.assertEqual(run.inserted, [], "Og is not at the counter")

    def test_its_step_is_still_written_when_it_stands_at_a_banker(self):
        """Riding along is what is left for it, and it still works."""
        run = _Run(counter=("Og",)).run()
        self.assertIn(("Og", "place-bag guid:77"), run.inserted)

    def test_on_its_family_turn_its_step_walks_the_family_again(self):
        """Not sitting out, the member follows the leader, so the trip is for it."""
        run = _Run(sitting=()).run()
        self.assertEqual(run.steps, [bank.BANK_ERRAND_AIM])
        self.assertEqual(run.aims, [("Grug", "banker")])

    def test_the_note_names_why_no_trip_comes(self):
        run = _Run().run()
        og = [n for n in run.notes if n.startswith("Og ")]
        self.assertEqual(len(og), 1, run.notes)
        self.assertIn("it waits for a banker", og[0])
        self.assertIn("sitting out to craft", og[0])


class ASittingOutMemberIsNotTheFamilySplit(unittest.TestCase):
    def test_the_split_clock_reads_only_the_members_on_the_campaign(self):
        run = _Run(item_moves=[_ugga_deposit()]).run()
        self.assertEqual(run.split_names, [["Bork", "Grug", "Ugga"]])

    def test_a_crafting_member_far_away_does_not_defer_the_familys_trip(self):
        """Live: 'not taking a banker trip while the family has remained split
        for 26015 seconds' with the family together and Og 2804 yards off."""
        positions = {"Bork": TOGETHER, "Grug": TOGETHER, "Og": FAR, "Ugga": TOGETHER}
        now = time.monotonic()
        long_split = vendor_stall.FamilyMovement(
            positions=tuple((n, 0, positions[n]["pos_x"], 0.0) for n in NAMES),
            steady_since=now - 26015.0,
            split_since=now - 26015.0,
        )
        run = _Run(
            positions=positions, item_moves=[_ugga_deposit()], previous_split=long_split
        ).run()
        self.assertEqual(run.steps, [bank.BANK_ERRAND_AIM], run.warnings)
        self.assertEqual(run.aims, [("Grug", "banker")])
        self.assertFalse(
            [w for w in run.warnings if "remained split" in w], run.warnings
        )

    def test_a_running_member_far_away_still_defers_it(self):
        """The bound #872's split rule set is kept for the family itself."""
        positions = {"Bork": FAR, "Grug": TOGETHER, "Og": TOGETHER, "Ugga": TOGETHER}
        now = time.monotonic()
        running = [n for n in NAMES if n != "Og"]
        long_split = vendor_stall.FamilyMovement(
            positions=tuple((n, 0, positions[n]["pos_x"], 0.0) for n in running),
            steady_since=now - 1300.0,
            split_since=now - 1300.0,
        )
        run = _Run(
            positions=positions, item_moves=[_ugga_deposit()], previous_split=long_split
        ).run()
        self.assertEqual(run.steps, [bank.BANK_ERRAND_DEFER])
        self.assertEqual(run.aims, [])


if __name__ == "__main__":
    unittest.main()
