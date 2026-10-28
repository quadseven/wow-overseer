"""The vendor, banker and borrowed-lead clocks survive a bridge restart (#817).

Each bounds a stall, and each was in memory only, so every deploy counted a
stuck trip or a borrowed lead from zero; with deploys closer together than
the bound, the give-up never fired. `bridge._ClockMemo` keeps them in the
bridge memo store. These tests run its real source against a fake store and a
fake clock whose monotonic time starts over at the restart, as a new process's
does, while wall time carries on.
"""

import ast
import json
import logging
import pathlib
import re
import types
import unittest

import bank
import guildroute
import tradechoice
import vendor_stall


SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
TREE = ast.parse(SOURCE)

LEADER = "Leader"
NAMES = ("Leader", "Member")


class Clock:
    """Wall time that carries on, monotonic time that a restart starts over."""

    def __init__(self, wall=1_000_000.0, boot=50.0):
        self.wall, self.base = wall, wall - boot

    def time(self):
        return self.wall

    def monotonic(self):
        return self.wall - self.base

    def tick(self, seconds):
        self.wall += seconds

    def restart(self, down_seconds, boot=3.0):
        self.wall += down_seconds
        self.base = self.wall - boot


class Store:
    """overseer_bridge_memo, as _memo_upsert, _memo_read and _memo_delete see it."""

    def __init__(self):
        self.rows, self.writes, self.deletes = {}, [], []

    def upsert(self, kind, subject, value, since, expires):
        # The real store keeps the value as JSON.
        self.rows[kind, subject] = (json.loads(json.dumps(value)), since)
        self.writes.append((kind, subject, since, expires))

    def read(self, kind):
        return {s: v for (k, s), v in self.rows.items() if k == kind}

    def delete(self, kind, subject):
        self.rows.pop((kind, subject), None)
        self.deletes.append((kind, subject))


def _bridge_nodes(*names):
    return [n for n in TREE.body if getattr(n, "name", None) in names] + [
        n
        for n in TREE.body
        if isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) in names for t in n.targets)
    ]


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *args):
        self.lines.append(msg % args)

    def exception(self, msg, *args):
        self.lines.append("EXC " + msg % args)


def _memo_module(clock, store):
    """The bridge's real _ClockMemo and constants, with the store and clock faked."""
    log = _Log()
    ns = {
        "time": types.SimpleNamespace(time=clock.time, monotonic=clock.monotonic),
        "log": log,
        "_memo_upsert": store.upsert,
        "_memo_read": store.read,
        "_memo_delete": store.delete,
        # One synchronous writer: the order the real single-thread pool keeps.
        "_MEMO_WRITER": types.SimpleNamespace(submit=lambda fn, *a: fn(*a)),
        "vendor_stall": vendor_stall,
        "tradechoice": tradechoice,
    }
    nodes = _bridge_nodes(
        "_memo_job",
        "_ClockMemo",
        "_trip_clock",
        "TRIP_CLOCK_MEMO_SECONDS",
        "LEAD_CLOCK_MEMO_SECONDS",
    )
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
    ns["log_lines"] = log.lines
    return types.SimpleNamespace(**ns)


def _init_call(attribute):
    """The constructor call Bridge.__init__ assigns to `attribute`."""
    bridge = next(
        n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "Bridge"
    )
    init = next(n for n in bridge.body if getattr(n, "name", "") == "__init__")
    for node in ast.walk(init):
        targets = (
            [node.target]
            if isinstance(node, ast.AnnAssign)
            else node.targets
            if isinstance(node, ast.Assign)
            else []
        )
        if any(getattr(t, "attr", None) == attribute for t in targets):
            return node.value
    raise AssertionError(f"Bridge.__init__ never assigns {attribute}")


def _clocks(memo, attribute):
    """A fresh store for `attribute`, built by the very call Bridge.__init__ makes."""
    call = _init_call(attribute)
    ns = dict(vars(memo))
    return eval(compile(ast.Expression(call), "bridge.py", "eval"), ns)  # noqa: S307 - bridge.py's own source


class Process:
    """One bridge process: its own clock stores, restored from the memo store."""

    def __init__(self, clock, store):
        self.memo = _memo_module(clock, store)
        self.clock = clock
        self.vendor = _clocks(self.memo, "_vendor_movement")
        self.vendor_family = _clocks(self.memo, "_vendor_family_movement")
        self.bank_family = _clocks(self.memo, "_bank_family_movement")
        self.lead = _clocks(self.memo, "_family_lead_since")
        for clocks in (self.vendor, self.vendor_family, self.bank_family, self.lead):
            clocks.restore()

    def vendor_poll(self, position):
        """What _settle_vendor_errand does with one vendor observation."""
        stall = vendor_stall.progress(
            self.vendor.get(LEADER), position, self.clock.monotonic()
        )
        if stall.current is not None:
            self.vendor[LEADER] = stall.current
        return stall

    def bank_poll(self, positions):
        """What _bank_family_progress does with one banker observation."""
        progress = vendor_stall.family_progress(
            self.bank_family.get(LEADER), positions, NAMES, self.clock.monotonic()
        )
        if progress.current is not None:
            self.bank_family[LEADER] = progress.current
        return progress


STUCK = (0, 100.0, 50.0, 0.0)
SPLIT = {
    "Leader": {"map_id": 0, "pos_x": 0.0, "pos_y": 0.0},
    "Member": {"map_id": 1, "pos_x": 0.0, "pos_y": 0.0},
}


def _vendor_decision(stall):
    return vendor_stall.decide(
        pressure=True,
        at_counter=False,
        sales_outstanding=0,
        movement_readable=stall.readable,
        movement_progressed=stall.progressed,
        stalled_seconds=stall.stalled_seconds,
    )


class AStuckVendorTripKeepsItsTime(unittest.TestCase):
    def _run(self, restart_at):
        """Poll a stuck leader every minute; the minute the trip is given up."""
        clock, store = Clock(), Store()
        process = Process(clock, store)
        for minute in range(0, 60):
            if minute == restart_at:
                clock.restart(60.0)
                process = Process(clock, store)
            elif minute:
                clock.tick(60.0)
            stall = process.vendor_poll(STUCK)
            if _vendor_decision(stall).action == vendor_stall.RELEASE:
                return minute, stall, process
        self.fail("the stuck vendor trip was never given up")

    def test_the_give_up_fires_at_the_same_minute_with_a_deploy_as_without(self):
        without, _, _ = self._run(restart_at=None)
        self.assertEqual(vendor_stall.STALL_AFTER_SECONDS // 60, without)
        for restart_at in (5, 15, 19, 20):
            with self.subTest(restart_at=restart_at):
                minute, _, _ = self._run(restart_at=restart_at)
                self.assertEqual(without, minute)

    def test_the_restored_clock_is_named_in_the_log(self):
        _, stall, process = self._run(restart_at=15)
        restored = [
            line
            for line in process.memo.log_lines
            if "restored the vendor trip stall" in line
        ]
        self.assertEqual(1, len(restored), process.memo.log_lines)
        self.assertIn(LEADER, restored[0])
        # Fourteen minutes of polls and the minute the bridge was down.
        self.assertIn("900 seconds already spent", restored[0])

    def test_a_trip_that_keeps_moving_is_not_given_up_after_a_deploy(self):
        clock, store = Clock(), Store()
        process = Process(clock, store)
        for minute in range(40):
            if minute == 10:
                clock.restart(60.0)
                process = Process(clock, store)
            else:
                clock.tick(60.0)
            stall = process.vendor_poll((0, 100.0 + 10 * minute, 50.0, 0.0))
            self.assertEqual(vendor_stall.HOLD, _vendor_decision(stall).action)

    def test_a_stopped_trip_writes_nothing_while_it_waits(self):
        clock, store = Clock(), Store()
        process = Process(clock, store)
        for _ in range(10):
            process.vendor_poll(STUCK)
            clock.tick(60.0)
        self.assertEqual(1, len(store.writes), store.writes)

    def test_a_released_trip_leaves_no_memo(self):
        clock, store = Clock(), Store()
        process = Process(clock, store)
        process.vendor_poll(STUCK)
        process.vendor.pop(LEADER, None)
        process.vendor.pop("Nobody", None)
        self.assertEqual({}, store.read("vendor_move"))
        with self.assertRaises(KeyError):
            process.vendor.pop("Nobody")
        clock.restart(60.0)
        self.assertNotIn(LEADER, Process(clock, store).vendor)


class TheFamilySplitClocksKeepTheirTime(unittest.TestCase):
    def test_a_banker_split_reads_the_same_seconds_after_a_deploy(self):
        clock, store = Clock(), Store()
        process = Process(clock, store)
        process.bank_poll(SPLIT)
        clock.tick(600.0)
        before = process.bank_poll(SPLIT).split_seconds
        clock.restart(120.0)
        after = Process(clock, store).bank_poll(SPLIT)
        self.assertEqual(before + 120.0, after.split_seconds)
        self.assertTrue(after.split)
        self.assertFalse(after.progressed)

    def test_the_banker_give_up_fires_when_it_would_have_without_a_deploy(self):
        clock, store = Clock(), Store()
        process = Process(clock, store)
        process.bank_poll(SPLIT)
        clock.tick(bank.BANK_SPLIT_RECOVERY_SECONDS - 300)
        process.bank_poll(SPLIT)
        clock.restart(300.0)
        restored = Process(clock, store).bank_poll(SPLIT)
        self.assertGreaterEqual(
            restored.split_seconds, bank.BANK_SPLIT_RECOVERY_SECONDS
        )

    def test_the_vendor_family_clock_round_trips_with_tuples(self):
        clock, store = Clock(), Store()
        process = Process(clock, store)
        current = vendor_stall.family_progress(
            None, SPLIT, NAMES, clock.monotonic()
        ).current
        process.vendor_family[LEADER] = current
        restored = Process(clock, store).vendor_family[LEADER]
        self.assertEqual(current, restored)
        self.assertIsInstance(restored.positions[0], tuple)

    def test_a_cohesive_family_restores_its_steady_clock(self):
        clock, store = Clock(), Store()
        together = vendor_stall.FamilyMovement(
            (("Leader", 0, 1.0, 2.0), ("Member", 0, 3.0, 4.0)),
            clock.monotonic() - 30.0,
            None,
        )
        Process(clock, store).vendor_family[LEADER] = together
        clock.restart(10.0)
        restored = Process(clock, store).vendor_family[LEADER]
        self.assertIsNone(restored.split_since)
        self.assertEqual(clock.monotonic() - 40.0, restored.steady_since)


class ABorrowedLeadKeepsItsTime(unittest.TestCase):
    def test_the_lead_bound_expires_at_the_same_wall_time_after_a_deploy(self):
        clock, store = Clock(), Store()
        process = Process(clock, store)
        process.lead["Family"] = {"Trainee": clock.monotonic()}
        limit = 6 * 3600
        clock.tick(limit - 600)
        clock.restart(300.0)
        restarted = Process(clock, store)
        since = restarted.lead["Family"]
        self.assertFalse(tradechoice.expired(since, clock.monotonic(), limit))
        clock.tick(301.0)
        self.assertEqual(
            frozenset({"Trainee"}), tradechoice.expired(since, clock.monotonic(), limit)
        )
        lines = [line for line in restarted.memo.log_lines if "borrowed lead" in line]
        self.assertEqual(1, len(lines), restarted.memo.log_lines)
        self.assertIn("Family", lines[0])

    def test_an_emptied_borrow_clock_is_deleted_not_stored(self):
        clock, store = Clock(), Store()
        process = Process(clock, store)
        process.lead["Family"] = {"Trainee": clock.monotonic()}
        process.lead["Family"] = {}
        self.assertEqual({}, store.read("lead_borrow"))
        self.assertNotIn("Family", Process(clock, store).lead)

    def test_the_lead_memo_outlives_the_lead_bound(self):
        clock, store = Clock(), Store()
        Process(clock, store).lead["Family"] = {"Trainee": clock.monotonic()}
        _kind, _subject, since, expires = store.writes[-1]
        self.assertGreater(expires - since, 6 * 3600)


class RestoreIsSafe(unittest.TestCase):
    def test_an_invalid_memo_is_dropped_and_said(self):
        clock, store = Clock(), Store()
        store.rows["vendor_move", LEADER] = ({"map_id": 0}, 1.0)
        process = Process(clock, store)
        self.assertNotIn(LEADER, process.vendor)
        self.assertTrue(any(line.startswith("EXC") for line in process.memo.log_lines))

    def test_a_second_restore_keeps_what_memory_already_observes(self):
        clock, store = Clock(), Store()
        process = Process(clock, store)
        fresh = vendor_stall.Movement(0, 1.0, 2.0, 3.0, clock.monotonic())
        process.vendor[LEADER] = fresh
        store.rows["vendor_move", LEADER] = (
            vendor_stall.movement_memo(fresh, -1e6),
            0.0,
        )
        process.vendor.restore()
        self.assertEqual(fresh, process.vendor[LEADER])


class Wiring(unittest.TestCase):
    def test_bridge_keeps_the_four_clocks_in_the_memo_store(self):
        for attribute in (
            "_vendor_movement",
            "_vendor_family_movement",
            "_bank_family_movement",
            "_family_lead_since",
        ):
            with self.subTest(attribute=attribute):
                call = _init_call(attribute)
                self.assertEqual("_ClockMemo", getattr(call.func, "id", None))

    def test_start_up_restores_them(self):
        bridge = next(
            n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "Bridge"
        )
        ensure = next(
            n for n in bridge.body if getattr(n, "name", "") == "_ensure_stores"
        )
        text = ast.get_source_segment(SOURCE, ensure)
        self.assertIn("asyncio.to_thread(restore)", text)
        for attribute in (
            "_vendor_movement",
            "_vendor_family_movement",
            "_bank_family_movement",
            "_family_lead_since",
            "_material_requests",
        ):
            self.assertIn(f'"{attribute}"', text)

    def test_the_memo_kinds_fit_the_store(self):
        kinds = re.findall(r'_ClockMemo\(\s*"([^"]+)"', SOURCE)
        self.assertEqual(5, len(set(kinds)), kinds)
        self.assertTrue(all(len(kind) <= 32 for kind in kinds))


class TheMailRunCapReadsTheSameDay(unittest.TestCase):
    """`_guild_mail_run_starts` stays in memory (#817): the cap also reads the
    command log, and that read must cover the window the starts are kept for."""

    def test_the_log_reads_and_the_memory_cover_one_day(self):
        self.assertEqual(24 * 3600, guildroute.DAY_SECONDS)
        for name in ("_route_letters_today", "_route_walks_today"):
            node = next(n for n in TREE.body if getattr(n, "name", None) == name)
            self.assertIn(
                "created_at > NOW() - INTERVAL 1 DAY",
                ast.get_source_segment(SOURCE, node),
            )

    def test_a_restart_spends_the_runs_the_log_holds(self):
        self.assertEqual(3, guildroute.runs_today([], 100.0, posted=3))


if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()
