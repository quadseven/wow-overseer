"""The quest ledger (#923): taken, completed, broken and abandoned off the
questers' quest status, and the bridge pass that writes it."""

import datetime
import pathlib
import sys
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
if not hasattr(sys.modules["pymysql"], "err"):
    # CI keeps this suite stdlib-only; provide the driver's caught base type.
    class _MySQLError(Exception):
        pass

    sys.modules["pymysql"].err = types.SimpleNamespace(MySQLError=_MySQLError)

import questledger as ql  # noqa: E402

NOW = datetime.datetime(2026, 10, 13, 12, 0, 0)
EARLIER = datetime.datetime(2026, 10, 13, 9, 0, 0)
CHARS = {7: "Tharn", 8: "Mirra"}


def ledger(quest, guid, state, first=EARLIER, finished=None, reason="", name=None):
    return {
        "quest": quest,
        "guid": guid,
        "character_name": name or CHARS[guid],
        "state": state,
        "first_taken": first,
        "finished": finished,
        "reason": reason,
    }


def log(quest, guid, status=3):
    return {"guid": guid, "quest": quest, "status": status}


def rewarded(quest, guid):
    return {"guid": guid, "quest": quest}


def moved(ledger_rows=(), log_rows=(), rewarded_rows=()):
    return {
        (e.quest, e.guid): e
        for e in ql.changes(CHARS, ledger_rows, log_rows, rewarded_rows, NOW)
    }


class TheLedgerMoves(unittest.TestCase):
    def test_a_quest_in_the_log_is_taken_from_now(self):
        e = moved(log_rows=[log(10, 7), log(11, 7, status=1)])
        self.assertEqual(e[(10, 7)].args(), (10, 7, "Tharn", "taken", NOW, None, ""))
        self.assertEqual(e[(11, 7)].state, "taken")

    def test_a_taken_quest_still_in_the_log_writes_nothing(self):
        self.assertEqual(moved([ledger(10, 7, "taken")], [log(10, 7)]), {})

    def test_a_rewarded_quest_the_ledger_watched_is_completed_now(self):
        e = moved([ledger(10, 7, "taken")], rewarded_rows=[rewarded(10, 7)])
        self.assertEqual(
            e[(10, 7)].args(), (10, 7, "Tharn", "completed", EARLIER, NOW, "")
        )

    def test_a_quest_rewarded_before_the_ledger_looked_has_no_times(self):
        e = moved(rewarded_rows=[rewarded(10, 8)])
        self.assertEqual(
            e[(10, 8)].args(), (10, 8, "Mirra", "completed", None, None, "")
        )
        self.assertEqual(
            moved([ledger(10, 8, "completed", None)], (), [rewarded(10, 8)]), {}
        )

    def test_a_failed_quest_is_broken_with_its_reason(self):
        e = moved([ledger(10, 7, "taken")], [log(10, 7, status=5)])
        self.assertEqual(
            e[(10, 7)].args(),
            (10, 7, "Tharn", "broken", EARLIER, NOW, ql.FAILED_REASON),
        )
        # Seen failed the first time it is seen at all.
        self.assertEqual(
            moved(log_rows=[log(11, 7, status=5)])[(11, 7)].first_taken, NOW
        )

    def test_a_broken_quest_dropped_from_the_log_stays_broken(self):
        old = ledger(10, 7, "broken", finished=EARLIER, reason=ql.FAILED_REASON)
        self.assertEqual(moved([old]), {})

    def test_a_taken_quest_gone_from_the_log_unrewarded_is_abandoned(self):
        e = moved([ledger(10, 7, "taken")])
        self.assertEqual(
            e[(10, 7)].args(), (10, 7, "Tharn", "abandoned", EARLIER, NOW, "")
        )

    def test_an_abandoned_quest_taken_again_keeps_its_first_time(self):
        old = ledger(10, 7, "abandoned", finished=EARLIER)
        e = moved([old], [log(10, 7)])
        self.assertEqual(
            e[(10, 7)].args(), (10, 7, "Tharn", "taken", EARLIER, None, "")
        )

    def test_a_completed_quest_back_in_the_log_stays_completed(self):
        self.assertEqual(moved([ledger(10, 7, "completed")], [log(10, 7)]), {})

    def test_a_renamed_quester_keeps_its_rows_under_the_new_name(self):
        old = ledger(10, 7, "taken", name="Tharnn")
        self.assertEqual(moved([old], [log(10, 7)])[(10, 7)].character_name, "Tharn")

    def test_characters_that_are_not_questers_are_ignored(self):
        self.assertEqual(moved((), [log(10, 99)], [rewarded(11, 99)]), {})

    def test_a_ledger_row_for_a_character_gone_from_the_realm_is_left(self):
        # Its guid is not among the questers, so no name is looked up for it.
        self.assertEqual(moved([ledger(10, 7, "taken") | {"guid": 99}]), {})


class TheStatusOfAQuest(unittest.TestCase):
    def test_the_best_news_wins(self):
        self.assertEqual(ql.quest_status([]), "not_reached")
        self.assertEqual(ql.quest_status(["abandoned"]), "abandoned")
        self.assertEqual(ql.quest_status(["abandoned", "taken"]), "taken")
        self.assertEqual(ql.quest_status(["taken", "broken"]), "broken")
        self.assertEqual(ql.quest_status(["broken", "completed"]), "completed")


class TheQuesters(unittest.TestCase):
    def test_ten_questers_five_per_guild(self):
        names = ql.quester_names()
        self.assertEqual(len(names), 10)
        self.assertEqual(len(set(names)), 10)
        self.assertEqual({len(v) for v in ql.QUESTERS.values()}, {5})
        self.assertEqual(ql.guild_of("Tharn"), "Cave")
        self.assertEqual(ql.guild_of("Zinja"), "Bonkers")
        self.assertEqual(ql.guild_of("Grug"), "")


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


class _Cursor:
    """Answers the ledger pass's reads in order and records every write."""

    def __init__(self, answers, written):
        self.answers = answers
        self.written = written
        self.last = None

    def execute(self, sql, args=()):
        self.last = sql

    def fetchall(self):
        for key, rows in self.answers.items():
            if self.last.startswith(key):
                return rows
        raise AssertionError("no answer for " + self.last)

    def fetchone(self):
        return self.fetchall()[0]

    def executemany(self, sql, rows):
        self.written.append((sql, list(rows)))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TheBridgePass(unittest.TestCase):
    def setUp(self):
        self.bridge = _import_bridge()

    def run_pass(self, answers):
        written = []
        cursor = _Cursor(answers, written)
        with mock.patch.object(self.bridge, "_connect", lambda: _Conn(cursor)):
            count = self.bridge._record_quests()
        return count, written

    def test_writes_taken_completed_and_broken_off_the_questers_status(self):
        answers = {
            "SELECT guid, name": [{"guid": 7, "name": "Tharn"}],
            "SELECT quest, guid, character_name": [ledger(12, 7, "taken")],
            "SELECT guid, quest, status": [log(10, 7), log(11, 7, status=5)],
            "SELECT guid, quest FROM character_queststatus_rewarded": [rewarded(12, 7)],
            "SELECT NOW()": [{"now": NOW}],
        }
        count, written = self.run_pass(answers)
        self.assertEqual(count, 3)
        ((sql, rows),) = written
        self.assertEqual(sql, ql.WRITE_SQL)
        self.assertEqual(
            rows,
            [
                (10, 7, "Tharn", "taken", NOW, None, ""),
                (11, 7, "Tharn", "broken", NOW, NOW, ql.FAILED_REASON),
                (12, 7, "Tharn", "completed", EARLIER, NOW, ""),
            ],
        )

    def test_no_quester_on_the_realm_writes_nothing(self):
        count, written = self.run_pass({"SELECT guid, name": []})
        self.assertEqual((count, written), (0, []))

    def test_a_table_missing_at_start_up_is_created_by_the_next_pass(self):
        # Match PyMySQL's exception hierarchy for missing tables and sockets.
        MySQLError = self.bridge.pymysql.err.MySQLError

        class ProgrammingError(MySQLError):
            pass

        class OperationalError(MySQLError):
            pass

        err = types.SimpleNamespace(
            MySQLError=MySQLError,
            ProgrammingError=ProgrammingError,
            OperationalError=OperationalError,
        )
        failures = (
            ProgrammingError(1146, "missing table"),
            OperationalError("down"),
        )
        self.assertTrue(all(isinstance(failure, MySQLError) for failure in failures))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.bridge._quest_ledger_ready = False

                def broken(failure=failure):
                    raise failure

                with (
                    mock.patch.object(self.bridge, "_connect", broken),
                    mock.patch.object(self.bridge.pymysql, "err", err, create=True),
                    self.assertLogs(self.bridge.log, "ERROR"),
                ):
                    self.bridge._ensure_quest_ledger_store()
                self.assertFalse(self.bridge._quest_ledger_ready)
                executed = []
                cursor = _Cursor({"SELECT guid, name": []}, [])
                cursor.execute = lambda sql, args=(), cursor=cursor, executed=executed: (
                    executed.append(sql),
                    setattr(cursor, "last", sql),
                )
                with mock.patch.object(
                    self.bridge, "_connect", lambda cursor=cursor: _Conn(cursor)
                ):
                    self.bridge._record_quests()
                self.assertEqual(executed[0], ql.TABLE_SQL)
                self.assertTrue(self.bridge._quest_ledger_ready)

    def test_a_pass_that_cannot_create_the_table_fails_loudly(self):
        class Refuses(_Cursor):
            def execute(self, sql, args=()):
                raise RuntimeError("no table")

        cursor = Refuses({}, [])
        with mock.patch.object(self.bridge, "_connect", lambda: _Conn(cursor)):
            with self.assertRaises(RuntimeError):
                self.bridge._record_quests()

    def test_the_table_is_ensured_and_the_pass_runs(self):
        import inspect

        src = inspect.getsource(self.bridge.Bridge._ensure_stores)
        self.assertIn("_ensure_quest_ledger_store", src)
        self.assertIn("_quest_ledger_loop", [p.name for p in self.bridge.PASSES])


if __name__ == "__main__":
    unittest.main()
