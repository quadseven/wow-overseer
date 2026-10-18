"""GET /api/v2/evidence answers fixed, named read-only queries, and refuses a
request it cannot check before any SQL runs."""

import datetime
import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
import guildjobs  # noqa: E402
import holdings  # noqa: E402
import realmread  # noqa: E402
from apiv2 import evidence  # noqa: E402

STARTED = datetime.datetime(2026, 10, 12, 9, 30)
RUNS = [
    {
        "id": 12,
        "leader_name": "Grug",
        "map_id": 36,
        "state": "ended",
        "outcome": "cleared",
        "ended_reason": "final boss down",
        "started_at": STARTED,
        "ended_at": STARTED + datetime.timedelta(hours=1),
    },
    {
        "id": 11,
        "leader_name": "Grug",
        "map_id": 36,
        "state": "ended",
        "outcome": "wiped",
        "ended_reason": "party wiped twice",
        "started_at": STARTED - datetime.timedelta(days=1),
        "ended_at": None,
    },
]
LETTERS = [
    {"recipient": "Og", "letters": 7, "delivered": 6},
    {"recipient": "Ugga", "letters": 2, "delivered": 2},
]


def q(**kw):
    return {k: [v] for k, v in kw.items()}


class EvidenceTests(unittest.TestCase):
    def get(self, query, answers=None):
        reader = realmread.Memory(
            answers
            if answers is not None
            else {
                evidence.DUNGEON_RUNS_SQL: RUNS,
                evidence.GUILD_MATERIALS_SQL: LETTERS,
            }
        )
        ctx = types.SimpleNamespace(read=reader)
        code, body = apiv2.handle("/api/v2/evidence", query, ctx)
        return code, body, reader.asked

    def test_route_is_served(self):
        self.assertIs(apiv2.ROUTES["/api/v2/evidence"], evidence.evidence)

    def test_dungeon_runs_binds_checked_values_and_default_limit(self):
        code, body, asked = self.get(
            q(name="dungeon_runs", map_id="36", since="2026-10-01")
        )
        self.assertEqual(code, 200)
        self.assertEqual(
            asked,
            [
                (
                    evidence.DUNGEON_RUNS_SQL,
                    (36, "2026-10-01 00:00:00", evidence.DEFAULT_ROWS + 1),
                )
            ],
        )
        self.assertEqual([r["id"] for r in body["rows"]], [12, 11])
        self.assertEqual(body["rows"][0]["outcome"], "cleared")
        self.assertEqual(body["rows"][0]["started_at"], "2026-10-12 09:30:00")
        self.assertIsNone(body["rows"][1]["ended_at"])
        self.assertEqual(body["params"]["since"], "2026-10-01 00:00:00")
        self.assertEqual((body["count"], body["capped"]), (2, False))

    def test_dungeon_runs_accepts_a_date_and_time(self):
        code, _, asked = self.get(
            q(name="dungeon_runs", map_id="36", since="2026-10-01T06:15", limit="5")
        )
        self.assertEqual(code, 200)
        self.assertEqual(asked[0][1], (36, "2026-10-01 06:15:00", 6))

    def test_limit_caps_rows_and_says_so(self):
        code, body, _ = self.get(
            q(name="dungeon_runs", map_id="36", since="2026-10-01", limit="1")
        )
        self.assertEqual(code, 200)
        self.assertEqual([r["id"] for r in body["rows"]], [12])
        self.assertTrue(body["capped"])

    def test_a_realm_without_outcome_answers_through_the_thin_read(self):
        thin = [{k: v for k, v in r.items() if k != "outcome"} for r in RUNS]
        code, body, asked = self.get(
            q(name="dungeon_runs", map_id="36", since="2026-10-01"),
            {
                evidence.DUNGEON_RUNS_SQL: realmread.MISSING_COLUMN,
                evidence.DUNGEON_RUNS_THIN_SQL: thin,
            },
        )
        self.assertEqual(code, 200)
        self.assertEqual(
            [a[0] for a in asked],
            [evidence.DUNGEON_RUNS_SQL, evidence.DUNGEON_RUNS_THIN_SQL],
        )
        self.assertNotIn("outcome", body["rows"][0])

    def test_a_realm_without_the_table_is_409_not_an_empty_answer(self):
        code, body, _ = self.get(
            q(name="dungeon_runs", map_id="36", since="2026-10-01"),
            {
                evidence.DUNGEON_RUNS_SQL: realmread.MISSING_TABLE,
                evidence.DUNGEON_RUNS_THIN_SQL: realmread.MISSING_TABLE,
            },
        )
        self.assertEqual(code, 409)
        self.assertIn("overseer_dungeon_run", body["error"])

    def test_guild_materials_counts_unread_letters_per_recipient(self):
        code, body, asked = self.get(q(name="guild_materials_unopened"))
        self.assertEqual(code, 200)
        self.assertEqual(
            asked,
            [
                (
                    evidence.GUILD_MATERIALS_SQL,
                    ("Guild materials", 1, evidence.MAX_ROWS + 1),
                )
            ],
        )
        self.assertEqual(body["rows"], LETTERS)

    def test_the_fixed_subject_and_read_bit_match_their_owners(self):
        self.assertEqual(evidence.GUILD_MATERIALS_SUBJECT, guildjobs.POST_SUBJECT)
        self.assertEqual(evidence.MAIL_READ, holdings.MAIL_READ)

    def test_unknown_name_is_404_with_the_names(self):
        code, body, asked = self.get(q(name="drop_table"))
        self.assertEqual(code, 404)
        self.assertEqual(body["names"], sorted(evidence.QUERIES))
        self.assertEqual(asked, [])

    def test_refusals_run_no_sql(self):
        bad = [
            {},
            {"name": ["dungeon_runs", "guild_materials_unopened"]},
            q(name="dungeon_runs", since="2026-10-01"),
            q(name="dungeon_runs", map_id="36"),
            q(name="dungeon_runs", map_id="-1", since="2026-10-01"),
            q(name="dungeon_runs", map_id="65536", since="2026-10-01"),
            q(name="dungeon_runs", map_id="36 OR 1=1", since="2026-10-01"),
            q(name="dungeon_runs", map_id="36", since="2026-13-01"),
            q(name="dungeon_runs", map_id="36", since="2026-10-01'; DROP"),
            q(name="dungeon_runs", map_id="36", since="yesterday"),
            q(name="dungeon_runs", map_id="36", since="2026-10-01", limit="0"),
            q(name="dungeon_runs", map_id="36", since="2026-10-01", limit="201"),
            q(name="dungeon_runs", map_id="36", since="2026-10-01", sql="SELECT 1"),
            q(name="guild_materials_unopened", subject="Anything"),
            {"name": ["dungeon_runs"], "map_id": ["36", "37"], "since": ["2026-10-01"]},
        ]
        for query in bad:
            with self.subTest(query=query):
                code, body, asked = self.get(query)
                self.assertEqual(code, 400)
                self.assertIn("error", body)
                self.assertEqual(asked, [])

    def test_every_query_selects_and_is_capped(self):
        for name, entry in evidence.QUERIES.items():
            for sql in filter(None, (entry.sql, entry.fallback)):
                with self.subTest(name=name):
                    self.assertTrue(sql.startswith("SELECT "))
                    self.assertNotIn(";", sql)
                    self.assertTrue(sql.endswith("LIMIT %s"))
                    self.assertEqual(sql.count("%s"), len(entry.params))
            self.assertEqual(entry.params[-1], "limit")


if __name__ == "__main__":
    unittest.main()
