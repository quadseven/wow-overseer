"""What followed Jev's overrides is recorded, scored and fed back (#584).

#583: the kinds that override the heuristic most (activity_choice,
family_intent) recorded no outcome, so nobody could tell whether those
overrides helped, and Jev never saw what its earlier answers led to. These pin
the jev_recovery pattern copied to them: a row per override, scored at the
family's next question, and the kind's recent outcomes in the question.
"""

import asyncio
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import jev  # noqa: E402
import jev_activity as ja  # noqa: E402
import jev_family_intent as jfi  # noqa: E402
import jev_outcomes as jo  # noqa: E402
from test_jev_items import FakeJev  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def activity_facts(free=3, **kw):
    members = tuple(
        ja.Member(name=n, level=20, class_name="Warrior", free_slots=free)
        for n in ("Zug", "Oz")
    )
    kw.setdefault("queue", "Ragefire Chasm 12 of 50")
    return ja.Facts(family="Zug", members=members, job="dungeon:ragefire", **kw)


def intent_facts(current="quest", target="", table="quest|drive|\neconomy|bags|3156"):
    row = jfi.row_from_db(
        {
            "leader_name": "Zug",
            "current_kind": current,
            "current_target": target,
            "on_the_table": table,
            "module_age": 5,
        }
    )
    return jfi.Facts(family="Zug", row=row, deaths=1)


SCORED = [
    {
        "subject": "Zug",
        "chose": "sell",
        "instead_of": "campaign",
        "confidence": 0.917,
        "outcome": "after 12 min: free bag slots 6 -> 30; the queue did not move",
    },
    {
        "subject": "Ugg",
        "chose": "quest",
        "instead_of": "campaign",
        "confidence": 0.7,
        "outcome": "after 30 min: +1 levels; queue now empty",
    },
]


class TheRecord(unittest.TestCase):
    def test_only_an_override_is_recorded(self):
        base = ja.Judgment(
            subject="Zug",
            heuristic=ja.CAMPAIGN,
            heuristic_why="",
            mode=jev.ACT,
            status="answered",
            jev=ja.SELL,
            confidence=0.97,
        )
        before = ja.snapshot(activity_facts())
        args = jo.record_args(
            ja.Judgment(**{**base.__dict__, "acted": jev.JEV}), before
        )
        self.assertEqual(args[:5], (ja.KIND, "Zug", ja.SELL, ja.CAMPAIGN, 0.97))
        self.assertEqual(jo.before_of({"before_state": args[5]}), before)
        for acted in (jev.BOTH, jev.HEURISTIC):
            judged = ja.Judgment(**{**base.__dict__, "acted": acted})
            self.assertIsNone(jo.record_args(judged, before))

    def test_history_is_oldest_first_and_compact(self):
        out = jo.history(SCORED)
        self.assertEqual([h["family"] for h in out], ["Ugg", "Zug"])
        self.assertEqual(out[1]["confidence"], 0.92)
        self.assertEqual(
            set(out[0]), {"family", "jev_chose", "instead_of", "confidence", "then"}
        )

    def test_an_unreadable_snapshot_is_empty(self):
        self.assertEqual(jo.before_of({"before_state": "not json"}), {})
        self.assertEqual(jo.before_of({}), {})


class TheActivityChoiceLearns(unittest.TestCase):
    def test_what_followed_is_one_line(self):
        before = ja.snapshot(activity_facts(free=3))
        line = ja.outcome_words(before, activity_facts(free=15), 14)
        self.assertIn("after 14 min", line)
        self.assertIn("free bag slots 6 -> 30", line)
        self.assertIn("the queue did not move", line)
        moved = ja.outcome_words(
            before, activity_facts(queue="Ragefire Chasm 13 of 50"), 20
        )
        self.assertIn("queue now Ragefire Chasm 13 of 50", moved)

    def test_the_question_carries_the_history(self):
        fake = FakeJev()
        f = activity_facts(history=tuple(jo.history(SCORED)))
        client = jev.Client("k", transport=fake)
        asyncio.run(ja.ask(client, f, ja.policy({}), {}))
        request = fake.requests[0]
        self.assertEqual(
            request["state"]["recent_jev_overrides_and_what_followed"][1]["then"],
            SCORED[0]["outcome"],
        )
        self.assertIn(
            "recent_jev_overrides_and_what_followed",
            request["questions"]["activity"]["instructions"],
        )

    def test_no_history_leaves_the_question_as_it_was(self):
        state, questions = ja.question(activity_facts(), ja.options(activity_facts()))
        self.assertNotIn("recent_jev_overrides_and_what_followed", state)


class TheFamilyIntentLearns(unittest.TestCase):
    def test_what_followed_a_pick(self):
        before = jfi.snapshot(intent_facts(), "economy:3156")
        self.assertEqual(
            before, {"pick": "economy:3156", "doing": "quest", "deaths": 1}
        )
        on_it = jfi.outcome_words(before, intent_facts("economy", "3156"), 10)
        self.assertIn("the leader is still on it", on_it)
        asked = jfi.outcome_words(before, intent_facts(), 10)
        self.assertIn("still requested", asked)
        gone = jfi.outcome_words(before, intent_facts(table="quest|drive|"), 10)
        self.assertIn("no longer requested", gone)
        self.assertIn("recent deaths 1 -> 1", gone)

    def test_the_question_carries_the_history(self):
        f = jfi.Facts(
            family="Zug", row=intent_facts().row, history=tuple(jo.history(SCORED))
        )
        state, questions = jfi.question(f, jfi.options(f))
        self.assertEqual(len(state["recent_jev_picks_and_what_followed"]), 2)
        self.assertIn(
            "recent_jev_picks_and_what_followed", questions["intent"]["instructions"]
        )
        bare, _q = jfi.question(intent_facts(), jfi.options(intent_facts()))
        self.assertNotIn("recent_jev_picks_and_what_followed", bare)


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
    def __init__(self, log, results):
        self.log = log
        self.results = results
        self.rows = []

    def execute(self, sql, args=()):
        self.log.append((sql, tuple(args)))
        self.rows = list(self.results.get(sql, []))

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, log, results):
        self.log, self.results = log, results

    def cursor(self):
        return _Cursor(self.log, self.results)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _DbError(Exception):
    pass


_PYMYSQL = types.SimpleNamespace(err=types.SimpleNamespace(MySQLError=_DbError))


def _db_down(*_a):
    raise _DbError("gone")


def _bug(*_a):
    raise KeyError("bug")


class TheBridgeScoresAndRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = _import_bridge()

    def setUp(self):
        patcher = mock.patch.object(self.bridge, "pymysql", _PYMYSQL)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_open_rows_past_their_wait_are_scored_then_history_read(self):
        sql = []
        results = {
            jo.OPEN_SQL: [
                {"id": 5, "before_state": '{"free":6}', "minutes": 12},
                {"id": 6, "before_state": '{"free":9}', "minutes": 2},
            ],
            jo.HISTORY_SQL: SCORED,
        }
        seen = []

        def score(before, minutes):
            seen.append((before, minutes))
            return "after %d min" % minutes

        with mock.patch.object(self.bridge, "_connect", lambda: _Conn(sql, results)):
            out = self.bridge._jev_outcome_history(ja.KIND, "Zug", score, 5)
        self.assertEqual(seen, [({"free": 6}, 12)])
        scored = [a for s, a in sql if s == jo.SCORE_SQL]
        self.assertEqual(scored, [("after 12 min", 5)])
        self.assertEqual([h["family"] for h in out], ["Ugg", "Zug"])

    def test_an_override_is_inserted_and_nothing_else(self):
        sql = []
        judgment = ja.Judgment(
            subject="Zug",
            heuristic=ja.CAMPAIGN,
            heuristic_why="",
            mode=jev.ACT,
            status="answered",
            jev=ja.SELL,
            confidence=0.97,
            acted=jev.JEV,
        )
        with mock.patch.object(self.bridge, "_connect", lambda: _Conn(sql, {})):
            self.bridge._record_jev_override(judgment, {"free": 6})
            self.bridge._record_jev_override(
                ja.Judgment(**{**judgment.__dict__, "acted": jev.BOTH}), {}
            )
        self.assertEqual([s for s, _a in sql], [jo.INSERT_SQL])

    def test_history_goes_into_the_facts_and_a_failure_leaves_them(self):
        f = activity_facts()
        with mock.patch.object(
            self.bridge, "_jev_outcome_history", lambda *a: jo.history(SCORED)
        ):
            out = asyncio.run(
                self.bridge._with_jev_history(f, ja.KIND, ja.outcome_words, 5)
            )
        self.assertEqual(len(out.history), 2)
        with mock.patch.object(self.bridge, "_jev_outcome_history", _db_down):
            with self.assertLogs(self.bridge.log, "ERROR"):
                same = asyncio.run(
                    self.bridge._with_jev_history(f, ja.KIND, ja.outcome_words, 5)
                )
        self.assertIs(same, f)
        # A bug is not a database failure: it rises to the pass's handler.
        with mock.patch.object(self.bridge, "_jev_outcome_history", _bug):
            with self.assertRaises(KeyError):
                asyncio.run(
                    self.bridge._with_jev_history(f, ja.KIND, ja.outcome_words, 5)
                )

    def test_a_database_failure_is_logged_and_a_bug_rises(self):
        judgment = ja.Judgment(
            subject="Zug",
            heuristic=ja.CAMPAIGN,
            heuristic_why="",
            mode=jev.ACT,
            status="answered",
            jev=ja.SELL,
            acted=jev.JEV,
        )
        with mock.patch.object(self.bridge, "_record_jev_override", _db_down):
            with self.assertLogs(self.bridge.log, "ERROR"):
                asyncio.run(self.bridge._jev_override_recorded(judgment, {}))
        with mock.patch.object(self.bridge, "_record_jev_override", _bug):
            with self.assertRaises(KeyError):
                asyncio.run(self.bridge._jev_override_recorded(judgment, {}))

    def test_both_kinds_are_wired(self):
        for start, end in (
            ("async def _activity_for", "async def _activity_can"),
            ("async def _family_intent_for", "async def _situation_loop"),
        ):
            body = BRIDGE[BRIDGE.index(start) :]
            body = body[: body.index(end)]
            self.assertLess(
                body.index("_with_jev_history("), body.index(".ask(self._jev")
            )
            self.assertIn("_jev_override_recorded(", body)
        store = BRIDGE[BRIDGE.index("def _create_jev_store") :]
        store = store[: store.index("\ndef ")]
        self.assertIn("jev_outcomes.TABLE_SQL", store)


if __name__ == "__main__":
    unittest.main()
