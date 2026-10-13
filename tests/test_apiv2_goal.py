"""Tests for GET /api/v2/goal.

The handler is run against the in-memory realm reader with fake rows, so the
read statements and the shaped payload are both checked without a database.
"""

import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
import families  # noqa: E402
import guildrun  # noqa: E402
import raidteams  # noqa: E402
import realmread  # noqa: E402
from apiv2 import goal, members as roster, presence, series  # noqa: E402

NOW = 1_800_000_000
HOUR = 3600
DAY = 86400

FAMILIES = families.Families(
    families.MemoryStore({"Grug": ["Grug"]}, {"Cave": ["Grug"], "Bonkers": []}),
    fallback=lambda: [],
)


def _xp_table():
    return [{"level": lvl, "xp": 1000} for lvl in range(1, 60)]


def _seat_names(guild):
    return [seat.name for seat in raidteams.seats(guild)]


def _char_rows(guild):
    rows = []
    for i, name in enumerate(_seat_names(guild)):
        level = 15 + (i // 10) * 10
        rows.append({"guid": i + 1, "name": name, "level": level, "xp": 0})
    return rows


def _events(rows):
    """Level-change events that give every seat a 24h XP rate."""
    out = []
    for row in rows:
        if row["level"] <= 1:
            continue
        out.append(
            {
                "guid": row["guid"],
                "old_level": row["level"] - 2,
                "new_level": row["level"] - 1,
                "at": NOW - 10 * HOUR,
            }
        )
        out.append(
            {
                "guid": row["guid"],
                "old_level": row["level"] - 1,
                "new_level": row["level"],
                "at": NOW - 5 * HOUR,
            }
        )
    return out


class Ctx:
    """A context with the in-memory reader and the family guilds."""

    def __init__(self, answers):
        self.read = realmread.Memory(answers)
        self.server = types.SimpleNamespace(FAMILIES=FAMILIES)


def _base_answers(guild="Cave"):
    chars = _char_rows(guild)
    events = _events(chars)
    return {
        goal.NOW_SQL: [{"now": NOW}],
        series._XP_TABLE_SQL: _xp_table(),
        goal.CHARS_SQL: chars,
        series._EVENTS_SQL: events,
        roster.ASKS_SQL: [],
        goal.QUEST_ASKS_SQL: [],
        goal.DEATHS_SQL: [],
        presence._SNAP_SQL: [],
        presence._FLAGS_SQL: [],
        guildrun._RUN_SQL: [],
    }


class TheRoute(unittest.TestCase):
    def test_goal_is_registered(self):
        self.assertIn("/api/v2/goal", apiv2.ROUTES)


class TheGoal(unittest.TestCase):
    def setUp(self):
        goal._CACHE.clear()

    def test_level_median_lowest_and_histogram(self):
        body = goal.build(Ctx(_base_answers("Cave")).read, "Cave")
        self.assertEqual(body["level"]["lowest"], 15)
        self.assertEqual(body["level"]["median"], 30)
        self.assertEqual(
            body["level"]["histogram"],
            {
                "1-10": 0,
                "11-20": 10,
                "21-30": 10,
                "31-40": 10,
                "41-50": 10,
                "51-60": 0,
            },
        )

    def test_gaining_xp_lists_seats_with_a_rate(self):
        body = goal.build(Ctx(_base_answers("Cave")).read, "Cave")
        gaining = body["gaining_xp"]
        self.assertEqual(len(gaining), 40)
        self.assertIn("Grug", gaining)
        # A seat with no measured hour has no rate.
        no_rate = Ctx(_base_answers("Cave"))
        no_rate.read.answers[series._EVENTS_SQL] = []
        body = goal.build(no_rate.read, "Cave")
        self.assertEqual(body["gaining_xp"], [])

    def test_projected_60_is_the_30th_seat(self):
        body = goal.build(Ctx(_base_answers("Cave")).read, "Cave")
        self.assertIsNotNone(body["projected_60"])
        self.assertRegex(body["projected_60"], r"^\d{4}-\d{2}-\d{2}$")

    def test_projected_60_is_null_when_not_measurable(self):
        answers = _base_answers("Cave")
        answers[series._XP_TABLE_SQL] = []
        body = goal.build(Ctx(answers).read, "Cave")
        self.assertIsNone(body["projected_60"])

    def test_runs_counts_and_clears_per_attempt(self):
        answers = _base_answers("Cave")
        answers[guildrun._RUN_SQL] = [
            {
                "id": 1,
                "guild": "Cave",
                "state": "ended",
                "outcome": "cleared",
                "created_at": "2026-10-12 00:00:00",
                "created_unix": NOW - HOUR,
                "ended_at": "2026-10-12 00:30:00",
                "ended_unix": NOW - HOUR + 1800,
            },
            {
                "id": 2,
                "guild": "Cave",
                "state": "ended",
                "outcome": "cleared",
                "created_at": "2026-10-12 01:00:00",
                "created_unix": NOW - 2 * HOUR,
                "ended_at": "2026-10-12 01:30:00",
                "ended_unix": NOW - 2 * HOUR + 1800,
            },
            {
                "id": 3,
                "guild": "Cave",
                "state": "ended",
                "outcome": "wiped",
                "created_at": "2026-10-12 02:00:00",
                "created_unix": NOW - 3 * HOUR,
                "ended_at": "2026-10-12 02:20:00",
                "ended_unix": NOW - 3 * HOUR + 1200,
            },
            {
                "id": 4,
                "guild": "Cave",
                "state": "ended",
                "outcome": "not entered",
                "created_at": "2026-10-12 03:00:00",
                "created_unix": NOW - 4 * HOUR,
                "ended_at": "2026-10-12 03:05:00",
                "ended_unix": NOW - 4 * HOUR + 300,
            },
        ]
        body = goal.build(Ctx(answers).read, "Cave")
        self.assertEqual(body["runs"]["formed"], 4)
        self.assertEqual(body["runs"]["refused"], 0)
        self.assertEqual(body["runs"]["not_entered"], 1)
        self.assertEqual(body["runs"]["in_flight"], 0)
        self.assertEqual(body["runs"]["entered"], 3)
        self.assertEqual(body["runs"]["cleared"], 2)
        self.assertEqual(body["runs"]["wiped"], 1)
        self.assertEqual(body["runs"]["abandoned"], 0)
        self.assertEqual(body["runs"]["timed_out"], 0)
        self.assertEqual(body["runs"]["clears_per_attempt"], 0.67)

    def test_runs_counts_every_end_state_and_clears_per_attempt_over_entered(self):
        answers = _base_answers("Cave")
        base = NOW - HOUR
        answers[guildrun._RUN_SQL] = [
            {
                "id": 1,
                "guild": "Cave",
                "state": "queued",
                "outcome": "",
                "created_at": "2026-10-12 00:00:00",
                "created_unix": base,
                "ended_at": None,
                "ended_unix": None,
            },
            {
                "id": 2,
                "guild": "Cave",
                "state": "ended",
                "outcome": "refused",
                "created_at": "2026-10-12 01:00:00",
                "created_unix": base - HOUR,
                "ended_at": "2026-10-12 01:01:00",
                "ended_unix": base - HOUR + 60,
            },
            {
                "id": 3,
                "guild": "Cave",
                "state": "ended",
                "outcome": "not entered",
                "created_at": "2026-10-12 02:00:00",
                "created_unix": base - 2 * HOUR,
                "ended_at": "2026-10-12 02:05:00",
                "ended_unix": base - 2 * HOUR + 300,
            },
            {
                "id": 4,
                "guild": "Cave",
                "state": "ended",
                "outcome": "cleared",
                "created_at": "2026-10-12 03:00:00",
                "created_unix": base - 3 * HOUR,
                "ended_at": "2026-10-12 03:30:00",
                "ended_unix": base - 3 * HOUR + 1800,
            },
            {
                "id": 5,
                "guild": "Cave",
                "state": "ended",
                "outcome": "wiped",
                "created_at": "2026-10-12 04:00:00",
                "created_unix": base - 4 * HOUR,
                "ended_at": "2026-10-12 04:20:00",
                "ended_unix": base - 4 * HOUR + 1200,
            },
            {
                "id": 6,
                "guild": "Cave",
                "state": "ended",
                "outcome": "abandoned",
                "created_at": "2026-10-12 05:00:00",
                "created_unix": base - 5 * HOUR,
                "ended_at": "2026-10-12 05:10:00",
                "ended_unix": base - 5 * HOUR + 600,
            },
            {
                "id": 7,
                "guild": "Cave",
                "state": "ended",
                "outcome": "timed out",
                "created_at": "2026-10-12 06:00:00",
                "created_unix": base - 6 * HOUR,
                "ended_at": "2026-10-12 08:00:00",
                "ended_unix": base - 6 * HOUR + 2 * HOUR,
            },
        ]
        body = goal.build(Ctx(answers).read, "Cave")
        self.assertEqual(body["runs"]["formed"], 7)
        self.assertEqual(body["runs"]["refused"], 1)
        self.assertEqual(body["runs"]["not_entered"], 1)
        self.assertEqual(body["runs"]["in_flight"], 1)
        self.assertEqual(body["runs"]["entered"], 4)
        self.assertEqual(body["runs"]["cleared"], 1)
        self.assertEqual(body["runs"]["wiped"], 1)
        self.assertEqual(body["runs"]["abandoned"], 1)
        self.assertEqual(body["runs"]["timed_out"], 1)
        self.assertEqual(body["runs"]["clears_per_attempt"], 0.25)

    def test_repeated_deaths_are_grouped_by_member_spot_and_killer(self):
        answers = _base_answers("Cave")
        answers[goal.DEATHS_SQL] = [
            {"name": "Grug", "map": 0, "zone": 40, "killer": "Defias Pillager", "n": 3},
            {"name": "Bonk", "map": 0, "zone": 40, "killer": "Defias Pillager", "n": 2},
            {"name": "Grug", "map": 36, "zone": 1581, "killer": "Rhahk'Zor", "n": 1},
        ]
        body = goal.build(Ctx(answers).read, "Cave")
        self.assertEqual(body["deaths_24h"]["total"], 6)
        repeated = body["deaths_24h"]["repeated"]
        self.assertEqual(len(repeated), 3)
        self.assertEqual(
            (repeated[0]["member"], repeated[0]["killer"], repeated[0]["n"]),
            ("Grug", "Defias Pillager", 3),
        )
        self.assertEqual(repeated[1]["member"], "Bonk")
        self.assertIn("Westfall", repeated[0]["spot"])

    def test_a_missing_table_answers_zeros_with_a_note(self):
        answers = _base_answers("Cave")
        answers[goal.DEATHS_SQL] = realmread.MISSING_TABLE
        body = goal.build(Ctx(answers).read, "Cave")
        self.assertEqual(body["deaths_24h"]["total"], 0)
        self.assertEqual(body["deaths_24h"]["repeated"], [])
        self.assertIn("overseer_death", body["missing"])

    def test_class_quests_done_and_blocked(self):
        answers = _base_answers("Cave")
        answers[goal.QUEST_ASKS_SQL] = [
            {"asker": "Grug", "state": "ran"},
            {"asker": "Bonk", "state": "ran"},
            {"asker": "Og", "state": "open"},
        ]
        body = goal.build(Ctx(answers).read, "Cave")
        self.assertEqual(body["class_quests"]["done"], 2)
        self.assertEqual(body["class_quests"]["blocked"], 1)

    def test_handler_refuses_bad_guilds(self):
        ctx = Ctx(_base_answers("Cave"))
        self.assertEqual(goal.goal({}, ctx)[0], 400)
        self.assertEqual(goal.goal({"guild": ["nowhere"]}, ctx)[0], 404)

    def test_handler_answers_through_apiv2(self):
        ctx = Ctx(_base_answers("Cave"))
        code, body = apiv2.handle("/api/v2/goal", {"guild": ["cave"]}, ctx)
        self.assertEqual(code, 200)
        self.assertEqual(body["guild"], "Cave")
        self.assertEqual(len(body["seats"]), 40)


if __name__ == "__main__":
    unittest.main()
