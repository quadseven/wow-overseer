"""GET /api/v2/evidence answers fixed, named read-only queries, and refuses a
request it cannot check before any SQL runs."""

import datetime
import decimal
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
import restsupply  # noqa: E402
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

DIED = datetime.datetime(2026, 11, 1, 6, 5)
DEATHS = [
    {
        "id": 902,
        "died_at": DIED,
        "name": "Zug",
        "class_id": 9,
        "class_name": "Warlock",
        "level": 24,
        "map": 0,
        "zone": 44,
        "killer_type": "creature",
        "killer": "Great Goretusk",
        "killer_entry": 547,
        "killer_min_level": 20,
        "killer_max_level": 21,
        "shards_now": 0,
        "pet_now": None,
        "pet_entry_now": None,
        "free_slots_now": 3,
        "food_now": 0,
        "drink_now": 4,
    },
    {
        "id": 901,
        "died_at": DIED - datetime.timedelta(minutes=9),
        "name": "Zug",
        "class_id": 9,
        "class_name": "Warlock",
        "level": 24,
        "map": 0,
        "zone": 44,
        "killer_type": "environment",
        "killer": "",
        "killer_entry": 0,
        "killer_min_level": None,
        "killer_max_level": None,
        "shards_now": 0,
        "pet_now": None,
        "pet_entry_now": None,
        "free_slots_now": 3,
        "food_now": 0,
        "drink_now": 4,
    },
]
SUMMARY = [
    {
        "class_id": 9,
        "class_name": "Warlock",
        "deaths": 40,
        "members": 4,
        "deaths_per_member": decimal.Decimal("10.00"),
        "deaths_no_pet_no_shard_now": decimal.Decimal("30"),
        "share_no_pet_no_shard_now": decimal.Decimal("0.750"),
    },
    {
        "class_id": 8,
        "class_name": "Mage",
        "deaths": 3,
        "members": 3,
        "deaths_per_member": decimal.Decimal("1.00"),
        "deaths_no_pet_no_shard_now": decimal.Decimal("3"),
        "share_no_pet_no_shard_now": decimal.Decimal("1.000"),
    },
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
                evidence.DEATHS_BY_MEMBER_SQL: DEATHS,
                evidence.DEATH_LOOP_SUMMARY_SQL: SUMMARY,
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

    def test_deaths_by_member_binds_fixed_and_checked_values(self):
        code, body, asked = self.get(q(name="deaths_by_member", since="2026-11-01"))
        self.assertEqual(code, 200)
        self.assertEqual(
            asked,
            [
                (
                    evidence.DEATHS_BY_MEMBER_SQL,
                    (6265, 0, 0, 11, 59, "2026-11-01 00:00:00", "", "", 0, 0, 51),
                )
            ],
        )
        self.assertEqual([r["id"] for r in body["rows"]], [902, 901])
        first = body["rows"][0]
        self.assertEqual(first["died_at"], "2026-11-01 06:05:00")
        self.assertEqual((first["name"], first["class_name"]), ("Zug", "Warlock"))
        self.assertEqual(
            (first["killer"], first["killer_min_level"]), ("Great Goretusk", 20)
        )
        self.assertIsNone(body["rows"][1]["killer_min_level"])
        self.assertEqual(
            {
                k: first[k]
                for k in (
                    "shards_now",
                    "pet_now",
                    "free_slots_now",
                    "food_now",
                    "drink_now",
                )
            },
            {
                "shards_now": 0,
                "pet_now": None,
                "free_slots_now": 3,
                "food_now": 0,
                "drink_now": 4,
            },
        )
        self.assertEqual(
            body["params"],
            {"since": "2026-11-01 00:00:00", "member": "", "class": 0, "limit": 50},
        )
        self.assertEqual((body["count"], body["capped"]), (2, False))

    def test_deaths_by_member_filters_one_member_and_class(self):
        for given, cls in (("warlock", 9), ("9", 9), ("Death Knight", 6)):
            with self.subTest(given=given):
                code, _, asked = self.get(
                    q(
                        name="deaths_by_member",
                        since="2026-11-01T06:00",
                        limit="5",
                        **{"member": "Zug", "class": given},
                    )
                )
                self.assertEqual(code, 200)
                self.assertEqual(
                    asked[0][1],
                    (
                        6265,
                        0,
                        0,
                        11,
                        59,
                        "2026-11-01 06:00:00",
                        "Zug",
                        "Zug",
                        cls,
                        cls,
                        6,
                    ),
                )

    def test_deaths_by_member_cap_holds(self):
        code, body, asked = self.get(
            q(name="deaths_by_member", since="2026-11-01", limit="1")
        )
        self.assertEqual(code, 200)
        self.assertEqual(asked[0][1][-1], 2)
        self.assertEqual([r["id"] for r in body["rows"]], [902])
        self.assertTrue(body["capped"])

    def test_deaths_by_member_rows_never_pass_max_rows(self):
        many = [dict(DEATHS[0], id=i) for i in range(evidence.MAX_ROWS + 5)]
        code, body, _ = self.get(
            q(
                name="deaths_by_member",
                since="2026-11-01",
                limit=str(evidence.MAX_ROWS),
            ),
            {evidence.DEATHS_BY_MEMBER_SQL: many},
        )
        self.assertEqual(code, 200)
        self.assertEqual(body["count"], evidence.MAX_ROWS)
        self.assertTrue(body["capped"])

    def test_death_loop_summary_reads_per_class(self):
        code, body, asked = self.get(q(name="death_loop_summary", since="2026-11-01"))
        self.assertEqual(code, 200)
        self.assertEqual(
            asked,
            [
                (
                    evidence.DEATH_LOOP_SUMMARY_SQL,
                    ("2026-11-01 00:00:00", 0, 6265, evidence.MAX_ROWS + 1),
                )
            ],
        )
        warlock = body["rows"][0]
        self.assertEqual(
            (warlock["class_name"], warlock["deaths"], warlock["members"]),
            ("Warlock", 40, 4),
        )
        self.assertEqual(warlock["share_no_pet_no_shard_now"], "0.750")
        self.assertEqual(body["rows"][1]["class_name"], "Mage")
        self.assertFalse(body["capped"])

    def test_the_death_reads_without_their_tables_are_409(self):
        for name in ("deaths_by_member", "death_loop_summary"):
            with self.subTest(name=name):
                code, body, _ = self.get(
                    q(name=name, since="2026-11-01"),
                    {
                        evidence.DEATHS_BY_MEMBER_SQL: realmread.MISSING_TABLE,
                        evidence.DEATH_LOOP_SUMMARY_SQL: realmread.MISSING_TABLE,
                    },
                )
                self.assertEqual(code, 409)
                self.assertIn("overseer_death", body["error"])

    def test_state_not_recorded_at_death_is_named_now(self):
        for sql in (evidence.DEATHS_BY_MEMBER_SQL, evidence.DEATH_LOOP_SUMMARY_SQL):
            self.assertNotIn("at_death", sql)
        for field in (
            "shards_now",
            "pet_now",
            "free_slots_now",
            "food_now",
            "drink_now",
        ):
            self.assertIn(f"AS {field}", evidence.DEATHS_BY_MEMBER_SQL)
        self.assertIn("AS share_no_pet_no_shard_now", evidence.DEATH_LOOP_SUMMARY_SQL)

    def test_the_death_constants_match_their_owners(self):
        self.assertEqual(evidence.SOUL_SHARD, guildjobs.SOUL_SHARD)
        self.assertEqual(evidence.FOOD_CATEGORY, restsupply.FOOD_CATEGORY)
        self.assertEqual(evidence.DRINK_CATEGORY, restsupply.DRINK_CATEGORY)

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
            q(name="deaths_by_member"),
            q(name="deaths_by_member", since="2026-11-01", zone="44"),
            q(name="deaths_by_member", since="2026-11-01", killer="Goretusk"),
            q(name="deaths_by_member", since="2026-11-01", member="Zug1"),
            q(name="deaths_by_member", since="2026-11-01", member="Zug' OR '1"),
            q(name="deaths_by_member", since="2026-11-01", **{"class": "12"}),
            q(name="deaths_by_member", since="2026-11-01", **{"class": "10"}),
            q(name="deaths_by_member", since="2026-11-01", **{"class": "necromancer"}),
            q(name="deaths_by_member", since="2026-11-01", **{"class": "9 OR 1=1"}),
            q(name="deaths_by_member", since="2026-11-01", limit="201"),
            q(name="death_loop_summary"),
            q(name="death_loop_summary", since="2026-11-01", limit="5"),
            q(name="death_loop_summary", since="2026-11-01", **{"class": "9"}),
            {
                "name": ["deaths_by_member"],
                "since": ["2026-11-01"],
                "class": ["9", "8"],
            },
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
