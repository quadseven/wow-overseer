"""A grouped follower's own walk is held, not written for the world to refuse (#995).

mod-overseer's walk gate refuses a guild bot whose group somebody else leads:
"character is grouped as a follower". Before this, every guild pass wrote the
walk anyway and the module refused it, 174 rows in six hours. These drive the
bridge's real writers with the database stubbed: the snapshot says who leads
the member's group, and the writer either inserts or says why it held.
"""

import pathlib
import re
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import


HERE = pathlib.Path(__file__).resolve().parent.parent

FOLLOWER = {"guid": 7, "group_leader": 3, "leader_name": "Tanky", "age": 4}
LEADER = {"guid": 3, "group_leader": 3, "leader_name": "Tanky", "age": 4}
UNGROUPED = {"guid": 7, "group_leader": 0, "leader_name": None, "age": 4}


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    bridge = fresh_import("bridge", discord=stub, pymysql=PYMYSQL)
    return bridge


bridge = _import_bridge()


class _Cursor:
    """Answers the snapshot read with `group`, an answer read with `answer`,
    and records every statement."""

    def __init__(self, log, group, answer):
        self.log = log
        self.group = group
        self.answer = answer
        self.lastrowid = 0
        self._last = ""

    def execute(self, sql, args=()):
        self._last = sql
        self.log.append((sql, tuple(args)))
        if sql.startswith("INSERT"):
            self.lastrowid = 41

    def fetchone(self):
        if "FROM overseer_snapshot" in self._last:
            return self.group
        if "FROM overseer_command WHERE id" in self._last:
            return self.answer
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, log, group, answer=None):
        self.log, self.group, self.answer = log, group, answer

    def cursor(self):
        return _Cursor(self.log, self.group, self.answer)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run(holder="Blingz"):
    return types.SimpleNamespace(
        holder=holder,
        walk_command="walk-to-mailbox max:600",
        taker="Grug",
        gain=5,
    )


def _inserts(log):
    return [args for sql, args in log if sql.startswith("INSERT INTO overseer_command")]


class FollowerTest(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(bridge, "_FOLLOWERS", bridge.followhold.Holds())
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self, fn, *args, group=None):
        log = []
        with mock.patch.object(bridge, "_connect", lambda: _Conn(log, group)):
            row_id = fn(*args)
        return row_id, _inserts(log)


class AMailErrand(FollowerTest):
    def test_a_follower_s_mailbox_walk_is_not_written_as_its_own_row(self):
        with self.assertLogs(bridge.log, "INFO") as said:
            row_id, inserts = self.write(
                bridge._insert_mail_walk, _run(), group=FOLLOWER
            )
        self.assertEqual(row_id, 0)
        self.assertEqual(inserts, [])
        line = "\n".join(said.output)
        self.assertIn("Blingz", line)
        self.assertIn("follower of Tanky", line)
        self.assertIn("held until it is ungrouped", line)

    def test_a_dues_walk_for_a_follower_is_held_and_its_letter_is_not(self):
        held, inserts = self.write(
            bridge._insert_dues_row,
            "Blingz",
            "walk-to-mailbox max:600",
            "Grug",
            "guildwork:dues",
            group=FOLLOWER,
        )
        self.assertEqual((held, inserts), (0, []))
        written, inserts = self.write(
            bridge._insert_dues_row,
            "Blingz",
            "send money:500",
            "Grug",
            "guildwork:dues",
            group=FOLLOWER,
        )
        self.assertEqual(written, 41)
        self.assertEqual([a[1] for a in inserts], ["send money:500"])

    def test_the_leader_and_an_ungrouped_member_are_walked_as_before(self):
        for group in (LEADER, UNGROUPED, None):
            with self.subTest(group=group):
                row_id, inserts = self.write(
                    bridge._insert_mail_walk, _run(), group=group
                )
                self.assertEqual(row_id, 41)
                self.assertEqual([a[1] for a in inserts], ["walk-to-mailbox max:600"])


class TheOtherWalks(FollowerTest):
    """The same gate refuses all four walks, on four kinds."""

    def test_a_vendor_trainer_or_spawn_walk_for_a_follower_is_held(self):
        for kind, command in (
            ("buy", "walk-to-vendor item:2901"),
            ("cast", "walk-to-trainer skill:197"),
            ("job", "walk-to-spawn creature:10076 near:3"),
        ):
            with self.subTest(kind=kind):
                row = bridge.guildcorps.Row(kind, command, "", "guildcorps")
                row_id, inserts = self.write(
                    bridge._insert_corps_row, "Blingz", row, group=FOLLOWER
                )
                self.assertEqual((row_id, inserts), (0, []))
                row_id, inserts = self.write(
                    bridge._insert_crafter_row,
                    "Blingz",
                    command,
                    kind,
                    "crafter",
                    group=FOLLOWER,
                )
                self.assertEqual((row_id, inserts), (0, []))

    def test_a_follower_s_buy_at_the_vendor_is_still_written(self):
        row = bridge.guildcorps.Row("buy", "2901 1", "", "guildcorps")
        row_id, inserts = self.write(
            bridge._insert_corps_row, "Blingz", row, group=FOLLOWER
        )
        self.assertEqual(row_id, 41)
        self.assertEqual([a[1] for a in inserts], ["2901 1"])


class ARefusal(FollowerTest):
    """The world's own answer holds the member when the snapshot cannot say."""

    def test_a_refused_walk_is_not_written_again_on_the_next_pass(self):
        answer = {
            "target_name": "Blingz",
            "status": "error",
            "detail": "character is grouped as a follower",
            "result": "",
        }
        log = []
        with mock.patch.object(bridge, "_connect", lambda: _Conn(log, None, answer)):
            bridge._command_answer(41)
        with self.assertLogs(bridge.log, "INFO") as said:
            row_id, inserts = self.write(bridge._insert_mail_walk, _run(), group=None)
        self.assertEqual((row_id, inserts), (0, []))
        self.assertIn("held until it is ungrouped", "\n".join(said.output))

    def test_a_fresh_snapshot_after_the_refusal_lifts_the_hold(self):
        answer = {
            "target_name": "Blingz",
            "status": "error",
            "detail": "character is grouped as a follower",
            "result": "",
        }
        clock = [100.0]
        with mock.patch.object(bridge.time, "monotonic", lambda: clock[0]):
            with mock.patch.object(bridge, "_connect", lambda: _Conn([], None, answer)):
                bridge._command_answer(41)
            clock[0] = 130.0
            fresh = dict(UNGROUPED, age=0)
            row_id, inserts = self.write(bridge._insert_mail_walk, _run(), group=fresh)
        self.assertEqual(row_id, 41)
        self.assertEqual(len(inserts), 1)


class AQuesterSale(FollowerTest):
    """A grouped quester with full bags takes its sale walk (#1962, #1813).

    The quester sale (questers.sell_step) is built only for a quester at
    SELL_FLOOR free slots or fewer; the module lets that walk through its
    follower wall when it reads the same (mod-overseer#1395)."""

    SALE_SOURCE = bridge.guildjobs.source_for(
        bridge.questers.SELL_WALK_ACTION, "Blingz"
    )

    def sale_row(self, command="walk-to-vendor any max:600", source=None):
        return bridge.guildcorps.Row("buy", command, "", source or self.SALE_SOURCE)

    def test_a_follower_s_quester_sale_walk_is_written(self):
        with self.assertLogs(bridge.log, "INFO") as said:
            row_id, inserts = self.write(
                bridge._insert_corps_row, "Blingz", self.sale_row(), group=FOLLOWER
            )
        self.assertEqual(row_id, 41)
        self.assertEqual([a[1] for a in inserts], ["walk-to-vendor any max:600"])
        self.assertIn(
            "questers: Blingz is grouped as a follower and sells with full bags",
            "\n".join(said.output),
        )

    def test_every_other_follower_walk_is_still_held(self):
        for row in (
            # an item vendor walk from the quester sale's own source
            self.sale_row(command="walk-to-vendor item:2901"),
            # the same sale walk from any other pass
            self.sale_row(source="guildcorps"),
            self.sale_row(
                source=bridge.guildjobs.source_for(
                    bridge.questers.WALK_ACTION, "Blingz"
                )
            ),
            # the quester sale's other walks
            self.sale_row(command="walk-to-mailbox max:600"),
            self.sale_row(command="walk-to-spawn creature:10076 near:3"),
        ):
            with self.subTest(row=row):
                row_id, inserts = self.write(
                    bridge._insert_corps_row, "Blingz", row, group=FOLLOWER
                )
                self.assertEqual((row_id, inserts), (0, []))

    def test_a_follower_refusal_of_the_sale_walk_holds_it_again(self):
        """The module read 2 or more free slots and refused it as a follower:
        the sale walk is held for REFUSAL_HOLD_SECONDS, even though fresh
        snapshot rows keep saying the quester follows."""
        answer = {
            "target_name": "Blingz",
            "status": "error",
            "detail": "character is grouped as a follower",
            "result": "",
        }
        clock = [100.0]
        with mock.patch.object(bridge.time, "monotonic", lambda: clock[0]):
            with mock.patch.object(bridge, "_connect", lambda: _Conn([], None, answer)):
                bridge._command_answer(41)
            clock[0] = 400.0
            fresh = dict(FOLLOWER, age=0)
            with self.assertLogs(bridge.log, "INFO") as said:
                row_id, inserts = self.write(
                    bridge._insert_corps_row, "Blingz", self.sale_row(), group=fresh
                )
            self.assertEqual((row_id, inserts), (0, []))
            self.assertIn("held until it is ungrouped", "\n".join(said.output))
            clock[0] = 100.0 + bridge.followhold.REFUSAL_HOLD_SECONDS
            row_id, inserts = self.write(
                bridge._insert_corps_row, "Blingz", self.sale_row(), group=fresh
            )
        self.assertEqual(row_id, 41)
        self.assertEqual(len(inserts), 1)


class EveryWalkWriter(unittest.TestCase):
    """Every writer a guild walk row goes through asks before it inserts."""

    WRITERS = (
        "_insert_mail_walk",
        "_insert_dues_row",
        "_insert_crafter_row",
        "_insert_corps_row",
    )

    def test_each_walk_writer_asks_before_it_writes(self):
        source = (HERE / "bridge.py").read_text()
        for name in self.WRITERS:
            with self.subTest(writer=name):
                match = re.search(
                    r"^def %s\(.*?(?=^def |\Z)" % name, source, re.S | re.M
                )
                self.assertIsNotNone(match, name)
                body = match.group(0)
                ask = body.find("_held_as_follower(")
                write = body.find("INSERT INTO overseer_command")
                self.assertGreater(ask, 0, name)
                self.assertLess(ask, write, name)


if __name__ == "__main__":
    unittest.main()
