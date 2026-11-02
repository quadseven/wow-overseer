"""The scorecard's heuristic arm while the active backend gives no answer (#820).

Jev answers HTTP 402 on every call, so every comparison row had no active
answer and `agree` was always None, and no outcome row was ever written: the
scorecard had nothing to read. The decision on #820: callers pass the
heuristic's answer into jev.ask, a comparison is then set against the
heuristic, each disagreement is recorded as an overseer_jev_outcome row (the
heuristic arm) and scored, guild_recipient gains an outcome scorer, and the
scorecard queries ship in jev_outcomes. These drive the real client over a
fake transport and run the stored queries on SQLite.
"""

import asyncio
import json
import pathlib
import sqlite3
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import jev  # noqa: E402
import jev_activity as ja  # noqa: E402
import jev_family_intent as jfi  # noqa: E402
import jev_items  # noqa: E402
import jev_outcomes as jo  # noqa: E402
from test_jev import ROUTE, Transport, good_choice, reply  # noqa: E402
from test_jev_act import DESTINY, FakePick, ranked, route  # noqa: E402
from test_jev_items import FakeJev  # noqa: E402
from test_jev_outcomes import _import_bridge, activity_facts, intent_facts  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


def pair(shadow_transport, active_result=(402, b"{}")):
    """An active Jev answering 402 and a strands comparison backend."""
    rows = []

    async def sink(batch):
        rows.extend(batch)

    shadow = jev.Client(
        "",
        backend=jev.STRANDS,
        url="http://127.0.0.1:8790/",
        transport=shadow_transport,
    )
    active = jev.Client(
        "a",
        url="https://example.com/a",
        transport=Transport(result=active_result),
        shadow=shadow,
        compare_sink=sink,
    )
    return active, rows


class TheComparisonFallsBackToTheHeuristic(unittest.TestCase):
    def ask(self, active, **kw):
        async def go():
            out = await active.ask("item_keep", {"x": 1}, {"route": ROUTE}, **kw)
            await active.drain_compare()
            return out

        return run(go())

    def test_no_active_answer_is_compared_with_the_heuristic(self):
        active, rows = pair(Transport(result=reply(good_choice("keep"))))
        out = self.ask(active, heuristic={"route": "equip"})
        self.assertIsNone(out.answers)
        [row] = rows
        self.assertEqual(
            (row["against"], row["active_answer"], row["answer"], row["agree"]),
            (jev.AGAINST_HEURISTIC, "equip", "keep", False),
        )
        self.assertNotIn("before", row)

    def test_an_active_answer_is_still_what_is_compared(self):
        active, rows = pair(
            Transport(result=reply(good_choice("keep"))),
            active_result=reply(good_choice("equip")),
        )
        self.ask(active, heuristic={"route": "vendor"}, before=lambda a: {"a": a})
        [row] = rows
        self.assertEqual((row["against"], row["active_answer"]), ("jev", "equip"))
        self.assertNotIn("before", row)

    def test_a_disagreement_with_the_heuristic_carries_the_snapshot(self):
        active, rows = pair(Transport(result=reply(good_choice("keep"))))
        self.ask(
            active,
            heuristic={"route": "equip"},
            subject="Zug",
            before=lambda answer: {"chose": answer},
        )
        [row] = rows
        self.assertEqual((row["subject"], row["before"]), ("Zug", {"chose": "keep"}))
        args = jo.compare_record_args(row)
        self.assertEqual(
            args,
            (
                "item_keep",
                "Zug",
                "keep",
                "equip",
                0.7,
                '{"chose":"keep"}',
                "heuristic",
                "strands",
            ),
        )

    def test_an_agreement_carries_no_snapshot_and_records_no_outcome(self):
        active, rows = pair(Transport(result=reply(good_choice("equip"))))
        self.ask(
            active,
            heuristic={"route": "equip"},
            subject="Zug",
            before=lambda answer: {"chose": answer},
        )
        [row] = rows
        self.assertTrue(row["agree"])
        self.assertNotIn("before", row)
        self.assertIsNone(jo.compare_record_args(row))

    def test_without_the_heuristic_nothing_changes(self):
        active, rows = pair(Transport(result=reply(good_choice("keep"))))
        self.ask(active)
        self.assertEqual((rows[0]["against"], rows[0]["agree"]), ("jev", None))


class TheCallersPassTheHeuristic(unittest.TestCase):
    def test_activity_choice(self):
        f = activity_facts(free=0, withheld=True)
        current, _why = ja.heuristic(f)
        other = next(o for o in ja.options(f) if o != current)
        active, rows = pair(FakeJev(picks={"activity": other}))

        async def go():
            await ja.ask(active, f, ja.policy({}), {})
            await active.drain_compare()

        run(go())
        [row] = rows
        self.assertEqual((row["active_answer"], row["answer"]), (current, other))
        self.assertEqual(row["subject"], "Zug")
        self.assertEqual(row["before"], ja.snapshot(f))

    def test_family_intent(self):
        f = intent_facts(table="quest|drive|\neconomy|bags|3156\ntrain|drive|")
        current, _why = jfi.heuristic(f)
        other = next(o for o in jfi.options(f) if o != current)
        active, rows = pair(FakeJev(picks={"intent": other}))

        async def go():
            await jfi.ask(active, f, jfi.policy({}))
            await active.drain_compare()

        run(go())
        [row] = rows
        self.assertEqual((row["active_answer"], row["answer"]), (current, other))
        self.assertEqual(row["before"], jfi.snapshot(f, other))

    def test_guild_recipient(self):
        grants = (route("Grug", 27, alternates=(route("Grog", 5),)),)
        ranking = (ranked("Grug", 27, True), ranked("Grog", 5, True))
        asks = jev_items.recipient_asks([DESTINY], [], grants, lambda h, c: ranking)
        active, rows = pair(FakePick("Grog", 0.9))

        async def go():
            await jev_items.recipient_pass(active, asks, lambda e: None, {}, jev.ACT)
            await active.drain_compare()

        run(go())
        [row] = rows
        self.assertEqual((row["active_answer"], row["answer"]), ("Grug", "Grog"))
        self.assertEqual(row["subject"], "Avenah")
        self.assertEqual(
            row["before"],
            {"guid": 4909901, "holder": "Avenah", "heuristic": "Grug", "chose": "Grog"},
        )


class TheRecipientOutcome(unittest.TestCase):
    BEFORE = {"guid": 7, "holder": "Avenah", "heuristic": "Grug", "chose": "Grog"}

    def test_words(self):
        words = jev_items.recipient_outcome_words
        self.assertEqual(
            words(self.BEFORE, {"name": "Grug", "worn": 1}, 70),
            "after 70 min: worn by Grug (the heuristic pick)",
        )
        self.assertEqual(
            words(self.BEFORE, {"name": "Grog", "worn": 1}, 70),
            "after 70 min: worn by Grog (the other pick)",
        )
        self.assertIn(
            "held by Avenah, not worn (still the holder)",
            words(self.BEFORE, {"name": "Avenah", "worn": 0}, 70),
        )
        self.assertIn("on no character", words(self.BEFORE, None, 70))


class _Cursor:
    def __init__(self, log, results):
        self.log, self.results, self.rows = log, results, []

    def execute(self, sql, args=()):
        self.log.append((sql, tuple(args)))
        self.rows = list(self.results.get(sql, []))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn(_Cursor):
    def cursor(self):
        return _Cursor(self.log, self.results)


class _DbError(Exception):
    pass


class TheBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = _import_bridge()

    def setUp(self):
        patcher = mock.patch.object(
            self.bridge,
            "pymysql",
            types.SimpleNamespace(err=types.SimpleNamespace(MySQLError=_DbError)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_marked_comparison_is_also_an_outcome_row(self):
        sql = []
        row = {
            "kind": "activity_choice",
            "question": "activity",
            "backend": "strands",
            "active_backend": "jev",
            "against": jev.AGAINST_HEURISTIC,
            "active_answer": "campaign",
            "answer": "sell",
            "confidence": 0.6,
            "probabilities": None,
            "status": "answered",
            "latency_ms": 900,
            "model": "strands-decider-2b",
            "agree": False,
            "subject": "Zug",
            "before": {"free": 3},
        }
        with mock.patch.object(self.bridge, "_connect", lambda: _Conn(sql, {})):
            self.bridge._insert_jev_comparisons([row, dict(row, before=None)])
        judgment_args = sql[0][1]
        self.assertIn("heuristic; active backend jev gave no answer", judgment_args)
        outcomes = [a for s, a in sql if s == jo.INSERT_SQL]
        self.assertEqual(
            outcomes,
            [
                (
                    "activity_choice",
                    "Zug",
                    "sell",
                    "campaign",
                    0.6,
                    '{"free":3}',
                    "heuristic",
                    "strands",
                )
            ],
        )

    def test_recipient_rows_are_scored_by_where_the_item_is(self):
        sql = []
        results = {
            jo.OPEN_KIND_SQL: [
                {
                    "id": 4,
                    "before_state": json.dumps(TheRecipientOutcome.BEFORE),
                    "minutes": 75,
                },
            ],
            jev_items.RECIPIENT_WHERE_SQL: [{"name": "Grug", "worn": 1}],
        }
        with mock.patch.object(self.bridge, "_connect", lambda: _Conn(sql, results)):
            self.assertEqual(self.bridge._score_recipient_outcomes(), 1)
        self.assertEqual(
            sql[0][1],
            (
                jev_items.KIND_GUILD,
                jev_items.RECIPIENT_OUTCOME_MINUTES,
                jev_items.RECIPIENT_OUTCOME_LIMIT,
            ),
        )
        self.assertEqual(sql[1], (jev_items.RECIPIENT_WHERE_SQL, (7,)))
        self.assertEqual(
            sql[2],
            (jo.SCORE_SQL, ("after 75 min: worn by Grug (the heuristic pick)", 4)),
        )

    def test_the_store_gains_the_outcome_backend_column(self):
        bridge = (HERE / "bridge.py").read_text(encoding="utf-8")
        store = bridge[bridge.index("def _create_jev_store(") :]
        store = store[: store.index("\n\n\n")]
        self.assertIn("jev_outcomes.ADD_BACKEND_SQL", store)
        self.assertIn("backend VARCHAR(12)", jo.TABLE_SQL)
        self.assertIn("_score_recipient_outcomes", bridge)


def _sqlite(sql: str) -> str:
    """The driver's format (`%s` arguments, `%%` a literal percent) in
    SQLite's: `%` formatting with `?` for each argument does exactly that."""
    return sql % tuple("?" for _ in range(sql.count("%s") - sql.count("%%s")))


class TheStoredScorecard(unittest.TestCase):
    """Both queries run on SQLite against the columns the bridge writes, and
    return non-zero scored counts for the three kinds the ticket names."""

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE overseer_jev_judgment (kind TEXT, status TEXT, "
            "agree INTEGER, latency_ms INTEGER, mode TEXT, backend TEXT, "
            "created_at TEXT)"
        )
        self.db.execute(
            "CREATE TABLE overseer_jev_outcome (kind TEXT, subject TEXT, chose TEXT, "
            "instead_of TEXT, confidence REAL, acted TEXT, backend TEXT, "
            "before_state TEXT, outcome TEXT, created_at TEXT, scored_at TEXT)"
        )

    def judge(self, kind, status, agree, ms, mode="compare", backend="strands"):
        self.db.execute(
            "INSERT INTO overseer_jev_judgment VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, status, agree, ms, mode, backend, "2026-11-01 00:00:00"),
        )

    def outcome(self, kind, outcome, acted="heuristic", backend="strands"):
        self.db.execute(
            "INSERT INTO overseer_jev_outcome VALUES "
            "(?, 'Zug', 'a', 'b', 0.5, ?, ?, '{}', ?, '2026-11-01 00:00:00', ?)",
            (kind, acted, backend, outcome, None if outcome is None else "x"),
        )

    def test_per_kind_judgments(self):
        self.judge("family_intent", "answered", 1, 800)
        self.judge("family_intent", "answered", 0, 1200)
        self.judge("family_intent", "timeout", None, 0)
        self.judge("family_intent", "answered", 1, 50, backend="clef")
        self.judge("family_intent", "answered", 1, 50, mode="act")
        [row] = self.db.execute(
            _sqlite(jo.JUDGMENT_SQL), ("strands", "2026-10-28")
        ).fetchall()
        self.assertEqual(
            (
                row["kind"],
                row["questions"],
                row["answered"],
                row["timeouts"],
                row["errors"],
                row["agreed"],
                row["disagreed"],
                row["max_ms"],
            ),
            ("family_intent", 3, 2, 1, 1, 1, 1, 1200),
        )
        self.assertEqual(row["mean_ms"], 1000)

    def test_scored_disagreements_and_which_side_they_favoured(self):
        self.outcome("activity_choice", "after 9 min: queue now RFC 13 of 50")
        self.outcome("activity_choice", "after 9 min: the queue did not move")
        self.outcome("activity_choice", None)
        self.outcome("family_intent", "after 20 min: no longer requested, x")
        self.outcome("family_intent", "after 20 min: still requested, x")
        self.outcome(
            "guild_recipient", "after 70 min: worn by Grug (the heuristic pick)"
        )
        self.outcome("guild_recipient", "after 70 min: worn by Grog (the other pick)")
        self.outcome("guild_recipient", "after 70 min: the item is on no character")
        self.outcome(
            "activity_choice",
            "after 9 min: the queue did not move",
            acted="jev",
            backend="jev",
        )
        got = {
            (r["kind"], r["acted"]): (
                r["disagreements"],
                r["scored"],
                r["favoured_heuristic"],
                r["favoured_backend"],
                r["unclear"],
            )
            for r in self.db.execute(_sqlite(jo.OUTCOME_SQL), ("2026-10-28",))
        }
        self.assertEqual(
            got,
            {
                ("activity_choice", "heuristic"): (3, 2, 1, 1, 0),
                ("activity_choice", "jev"): (1, 1, 1, 0, 0),
                ("family_intent", "heuristic"): (2, 2, 1, 1, 0),
                ("guild_recipient", "heuristic"): (3, 3, 1, 1, 1),
            },
        )

    def test_the_readings_match_the_lines_the_kinds_write(self):
        before = ja.snapshot(activity_facts())
        moved = ja.outcome_words(before, activity_facts(queue="RFC 13 of 50"), 9)
        stuck = ja.outcome_words(before, activity_facts(), 9)
        gone = jfi.outcome_words(
            jfi.snapshot(intent_facts(), "economy:3156"),
            intent_facts(table="quest|drive|"),
            20,
        )
        self.outcome("activity_choice", moved)
        self.outcome("activity_choice", stuck)
        self.outcome("family_intent", gone)
        rows = list(self.db.execute(_sqlite(jo.OUTCOME_SQL), ("2026-10-28",)))
        self.assertEqual(sum(r["unclear"] for r in rows), 0)
        self.assertEqual(sum(r["favoured_heuristic"] for r in rows), 2)


if __name__ == "__main__":
    unittest.main()
