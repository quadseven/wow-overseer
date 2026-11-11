"""A split family's banker trip is deferred; a member's own bank moves are not.

The split rule (`bank.errand_step`) governs the family's WALK to a banker and
nothing else. A member that already stands within reach of a banker runs its
own planned moves, whatever the split state of its family, and a deferral says
how many planned moves are waiting. These drive the real `_bank_once` with the
reads stubbed, the way test_bank_sitting_out does.
"""

import asyncio
import time
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import bank
    import bankbags
    import vendor_stall


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    return fresh_import("bridge", discord=stub, pymysql=PYMYSQL)


bridge = _import_bridge()

NAMES = ["Bork", "Grug", "Og", "Ugga"]
HERE = {"map_id": 0, "pos_x": 0.0, "pos_y": 0.0}
FAR = {"map_id": 0, "pos_x": 2804.0, "pos_y": 0.0}
SPLIT_FOR = bank.BANK_SPLIT_RECOVERY_SECONDS + 300.0


def deposit(who="Ugga", guid=501, item="Rough Stone"):
    return bank.Move(who, "deposit", guid, item, 5, "kept in the bank")


class _Run:
    """One `_bank_once` with every read stubbed; what it decided, recorded."""

    def __init__(self, *, counter=(), split=True, moves=(), bag_facts=None, plan=None):
        self.counter = set(counter)
        self.split = split
        self.moves = list(moves)
        self.plan = plan
        self.positions = (
            {"Bork": FAR, "Grug": HERE, "Og": HERE, "Ugga": HERE}
            if split
            else {n: HERE for n in NAMES}
        )
        self.bag_facts = (
            bag_facts
            if bag_facts is not None
            else [bankbags.Facts(name=n, worn=(10, 10, 10, 10)) for n in NAMES]
        )
        self.steps, self.inserted, self.warnings, self.infos = [], [], [], []

    def run(self):
        this = bridge.Bridge.__new__(bridge.Bridge)
        this._bank_family_movement = {}
        if self.split:
            now = time.monotonic()
            this._bank_family_movement["Grug"] = vendor_stall.FamilyMovement(
                positions=tuple((n, 0, self.positions[n]["pos_x"], 0.0) for n in NAMES),
                steady_since=now - SPLIT_FOR,
                split_since=now - SPLIT_FOR,
            )

        async def mid_run(names):
            return False

        async def exit_route(*args):
            return False

        async def claim(claimant, character, aim, **kwargs):
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
            info=lambda msg, *a, **k: self.infos.append(msg % a),
            warning=lambda msg, *a, **k: self.warnings.append(msg % a),
            debug=lambda *a, **k: None,
        )
        planner = self.plan or (lambda names: bank.Plan(moves=tuple(self.moves)))
        with (
            mock.patch.object(bridge, "_STANDIN_OUT", frozenset()),
            mock.patch.multiple(
                bridge,
                log=log,
                _pass_completed=lambda name: True,
                _family_of=lambda cohort=None: (list(NAMES), "Grug"),
                _plan_bank=planner,
                _log_changed=lambda *a, **k: None,
                _recent_bank_keys=lambda minutes: set(),
                _fetch_positions=lambda names: {
                    n: self.positions[n] for n in names if n in self.positions
                },
                _fetch_bank_bag_facts=lambda names: list(self.bag_facts),
                _fetch_town=lambda name: types.SimpleNamespace(
                    banker=name in self.counter
                ),
                _outstanding_bank_moves=lambda names: 0,
                _current_travel_npc=lambda name: "",
                _nearest_banker_yards=lambda name: 80.0,
                _release_trade_errand=lambda name, aim: True,
                _insert_bank=lambda move, command: (
                    self.inserted.append((move.character, command)) or 1
                ),
            ),
        ):
            asyncio.run(this._bank_once())
        return self


class AMemberAtABankerRunsItsOwnMovesWhileTheFamilyIsSplit(unittest.TestCase):
    def test_a_split_family_with_one_member_in_reach_queues_that_members_moves(self):
        run = _Run(counter=("Ugga",), moves=[deposit("Ugga")]).run()
        self.assertEqual(run.steps, [bank.BANK_ERRAND_DEFER], "the walk is deferred")
        self.assertEqual(run.inserted, [("Ugga", "deposit guid:501")])

    def test_a_member_out_of_reach_queues_nothing_while_one_in_reach_does(self):
        run = _Run(
            counter=("Ugga",), moves=[deposit("Ugga"), deposit("Og", 502, "Linen")]
        ).run()
        self.assertEqual(run.inserted, [("Ugga", "deposit guid:501")])


class AMemberWithEveryKindOfMoveQueuesThemInOrder(unittest.TestCase):
    def facts(self):
        facts = [bankbags.Facts(name=n, worn=(10, 10, 10, 10)) for n in NAMES]
        facts[2] = bankbags.Facts(
            name="Og",
            money=5000,
            worn=(10, 10, 10, 10),
            spare=(bankbags.Bag(guid=77, entry=4245, slots=6),),
        )
        return facts

    def test_buy_then_place_then_deposits_in_one_pass_on_a_split_family(self):
        run = _Run(
            counter=("Og",),
            moves=[deposit("Og", 502, "Linen")],
            bag_facts=self.facts(),
        ).run()
        self.assertEqual(
            run.inserted,
            [
                ("Og", "buy slot"),
                ("Og", "place-bag guid:77"),
                ("Og", "deposit guid:502"),
            ],
        )

    def test_the_same_order_when_the_family_is_not_split(self):
        run = _Run(
            counter=("Og",),
            split=False,
            moves=[deposit("Og", 502, "Linen")],
            bag_facts=self.facts(),
        ).run()
        self.assertEqual(
            run.inserted,
            [
                ("Og", "buy slot"),
                ("Og", "place-bag guid:77"),
                ("Og", "deposit guid:502"),
            ],
        )

    def test_the_plan_is_asked_with_the_room_the_placed_bag_adds(self):
        src = open(bridge.__file__, encoding="utf-8").read()
        block = src[src.index("def _plan_bank(") :]
        block = block[: block.index("\n\n\n")]
        self.assertIn("room_gain=bankbags.room_gain(", block)


class ANonSplitFamilyBehavesAsBefore(unittest.TestCase):
    def test_a_family_together_aims_the_trip_and_defers_nothing(self):
        run = _Run(split=False, moves=[deposit("Og", 502, "Linen")]).run()
        self.assertEqual(run.steps, [bank.BANK_ERRAND_AIM])
        self.assertEqual(run.warnings, [])
        self.assertEqual(run.inserted, [])

    def test_a_family_together_with_a_member_at_a_banker_queues_its_moves(self):
        run = _Run(
            split=False,
            counter=("Og", "Ugga"),
            moves=[deposit("Og", 502, "Linen"), deposit("Ugga")],
        ).run()
        self.assertEqual(
            run.inserted, [("Og", "deposit guid:502"), ("Ugga", "deposit guid:501")]
        )


class ADeferralSaysHowManyMovesWait(unittest.TestCase):
    def test_the_deferral_line_carries_the_count_of_waiting_moves(self):
        moves = [
            deposit("Og", 502, "Linen"),
            deposit("Og", 503, "Cloth"),
            deposit("Ugga"),
        ]
        run = _Run(moves=moves).run()
        self.assertEqual(run.steps, [bank.BANK_ERRAND_DEFER])
        (line,) = [w for w in run.warnings if "remained split" in w]
        self.assertIn("3 planned move(s) waiting", line)
        self.assertEqual(run.inserted, [])

    def test_only_moves_out_of_reach_are_counted_as_waiting(self):
        moves = [deposit("Og", 502, "Linen"), deposit("Ugga")]
        run = _Run(counter=("Ugga",), moves=moves).run()
        (line,) = [w for w in run.warnings if "remained split" in w]
        self.assertIn("1 planned move(s) waiting", line)

    def test_a_bank_bag_step_out_of_reach_is_counted_too(self):
        facts = [bankbags.Facts(name=n, worn=(10, 10, 10, 10)) for n in NAMES]
        facts[2] = bankbags.Facts(name="Og", money=5000, worn=(10, 10, 10, 10))
        run = _Run(moves=[deposit("Ugga")], bag_facts=facts).run()
        (line,) = [w for w in run.warnings if "remained split" in w]
        self.assertIn("2 planned move(s) waiting", line)


if __name__ == "__main__":
    unittest.main()
