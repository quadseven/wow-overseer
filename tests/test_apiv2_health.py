"""GET /api/v2/health: the realm's open problems as rankable findings.

The kinds are pure functions over rows, tested with plain data; the handler
runs against the in-memory realm reader and a fake map server, so the reads
it makes are pinned with no database. It only ever reads.
"""

import json
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import apiv2  # noqa: E402
import families as families_module  # noqa: E402
import guildrun  # noqa: E402
import realmread  # noqa: E402
from apiv2 import health  # noqa: E402
from apiv2._context import Context  # noqa: E402

NOW = 1_792_072_229
HOUR = 3600


def seats(n):
    return ",".join("M%d:dps:mage:20" % i for i in range(n))


def run(keyword, outcome, inside=2700, n=5, ago=HOUR):
    return {
        "keyword": keyword,
        "outcome": outcome,
        "members": seats(n),
        "seconds_inside": inside,
        "created_unix": NOW - ago,
    }


class Stuck(unittest.TestCase):
    def test_a_member_stuck_two_hours_or_more_is_a_finding(self):
        stuck = {
            "members": [
                {
                    "name": "Grassfed",
                    "step": "Class quest: Call of Fire",
                    "blocker": "asked the guild for help 16 times",
                    "since": NOW - int(27.8 * HOUR),
                    "kind": "class quest",
                },
                {"name": "Cronk", "step": "wear", "blocker": "", "since": NOW - 600},
                {"name": "Ghosty", "step": "x", "blocker": "", "since": None},
            ]
        }
        (f,) = health.stuck_findings(stuck, NOW)
        self.assertEqual("stuck:Grassfed:Class quest: Call of Fire", f["key"])
        self.assertEqual(
            ("quests", 1, 27.8, 27.8),
            (f["area"], f["affected"], f["hours"], f["impact"]),
        )
        self.assertEqual("asked the guild for help 16 times", f["evidence"])
        self.assertTrue(f["since"].endswith("Z"))


class Dungeons(unittest.TestCase):
    def test_a_dungeon_clearing_under_thirty_percent_of_eight_runs_is_a_finding(self):
        runs = [run("bfd", "cleared")] + [run("bfd", "timed out", ago=20 * HOUR)] * 9
        runs += [run("bfd", "not entered")] * 5  # never went in: says nothing
        (f,) = health.dungeon_findings(runs, NOW, place=lambda k: "Blackfathom Deeps")
        self.assertEqual("dungeon-clear-rate:bfd", f["key"])
        self.assertEqual("Blackfathom Deeps runs clear 1 of 10 in a day", f["title"])
        # 9 failed runs x 45 minutes x 5 seats, in member-hours.
        self.assertEqual((9, 20.0, 33.8), (f["affected"], f["hours"], f["impact"]))
        self.assertIn("9 timed out", f["evidence"])

    def test_few_runs_or_a_fair_clear_rate_are_not_findings(self):
        runs = [run("rfc", "wiped")] * 7
        runs += [run("wc", "cleared")] * 3 + [run("wc", "wiped")] * 5
        self.assertEqual([], health.dungeon_findings(runs, NOW))


class Questers(unittest.TestCase):
    QUESTERS = {
        "questers": [
            {"name": "Camnae", "guild": "Cave", "present": False},
            {"name": "Paruk", "guild": "Cave", "present": False},
            {"name": "Dorn", "guild": "Bonkers", "present": True},
        ]
    }

    def test_missing_questers_carry_the_modules_refusal_reason(self):
        why = {"outcome": "refused", "reason": "too far above the guild"}
        invites = [
            {
                "target_arg": "Camnae",
                "status": "error",
                "detail": "",
                "result": json.dumps(why),
                "at": NOW - 30 * HOUR,
            },
            {
                "target_arg": "Paruk",
                "status": "unchanged",
                "detail": "",
                "result": json.dumps(why).encode(),
                "at": NOW - HOUR,
            },
        ]
        (f,) = health.quester_findings(self.QUESTERS, invites, NOW)
        self.assertEqual("questers-missing:Cave", f["key"])
        self.assertEqual((2, 30.0, 60.0), (f["affected"], f["hours"], f["impact"]))
        self.assertIn("Camnae, Paruk", f["evidence"])
        self.assertIn(
            '2 of 2 team sync invites in 48 hours were refused, the latest because "too far above the guild"',
            f["evidence"],
        )

    def test_with_no_invites_the_start_is_not_on_record(self):
        (f,) = health.quester_findings(self.QUESTERS, [], NOW)
        self.assertEqual((0.0, 0.0, None), (f["hours"], f["impact"], f["since"]))
        self.assertIn("No team sync invite in 48 hours", f["evidence"])

    def test_detail_is_read_when_result_has_no_reason(self):
        self.assertEqual(
            "no seat", health.refusal_reason({"result": None, "detail": "no seat"})
        )

    def test_an_unchanged_answer_without_a_refusal_is_not_one(self):
        row = {"status": "unchanged", "result": '{"outcome": "invited"}'}
        self.assertFalse(health.refused_invite(row))

    def test_every_quester_present_is_no_finding(self):
        here = {"questers": [{"name": "Dorn", "guild": "Bonkers", "present": True}]}
        self.assertEqual([], health.quester_findings(here, [], NOW))


class Bank(unittest.TestCase):
    def test_an_empty_bank_with_broke_members_is_a_finding(self):
        banks = [
            {"guild": "Bonkers", "bank": 0, "broke": 63, "members": 71},
            {"guild": "Cave", "bank": 410_000, "broke": 65, "members": 71},
        ]
        (f,) = health.bank_findings(banks, {"Bonkers": NOW - 10 * HOUR}, NOW)
        self.assertEqual("guild-bank-empty:Bonkers", f["key"])
        self.assertEqual((63, 10.0, 630.0), (f["affected"], f["hours"], f["impact"]))
        self.assertIn("63 of 71 members", f["evidence"])

    def test_no_broke_members_is_no_finding(self):
        self.assertEqual(
            [],
            health.bank_findings([{"guild": "Cave", "bank": 0, "broke": 0}], {}, NOW),
        )


class Text(unittest.TestCase):
    def test_strings_are_one_line_of_ascii_within_their_limits(self):
        f = health.finding(
            "k",
            "Odo\u2019s Ley Staff \u2014 " + "x" * 200,
            "gear",
            1,
            1.0,
            "a\nb \u00e9",
            None,
        )
        self.assertTrue(f["title"].isascii() and f["evidence"].isascii())
        self.assertTrue(f["title"].startswith("Odo's Ley Staff - "))
        self.assertLessEqual(len(f["title"]), health.TITLE_MAX)
        self.assertEqual("a b ?", f["evidence"])


def ctx_for(answers):
    store = families_module.MemoryStore(
        {"Grug": ["Grug"], "Ugga": ["Ugga"]}, {"Cave": ["Grug"], "Bonkers": ["Ugga"]}
    )
    fams = families_module.Families(store, fallback=lambda: [])
    rd = realmread.Memory(answers)
    return Context(read=rd, server=types.SimpleNamespace(FAMILIES=fams)), rd.asked


class Handler(unittest.TestCase):
    def test_the_route_is_registered(self):
        self.assertIs(health.health, apiv2.ROUTES["/api/v2/health"])

    def test_the_handler_reads_and_ranks_highest_impact_first(self):
        answers = {
            health.NOW_SQL: [{"now_at": NOW}],
            guildrun._RUN_SQL: [run("blackfathom", "timed out", ago=5 * HOUR)] * 10,
            health.BANK_SQL: [
                {"guild": "Bonkers", "bank": 0, "broke": 63, "members": 71}
            ],
            health.BANK_MOVED_SQL: [{"guild": "Bonkers", "at": NOW - 100 * HOUR}],
            health.INVITES_SQL: [],
        }
        ctx, asked = ctx_for(answers)
        stuck = {
            "members": [
                {
                    "name": "Grug",
                    "step": "s",
                    "blocker": "b",
                    "since": NOW - 3 * HOUR,
                    "kind": "hold",
                }
            ]
        }
        with (
            mock.patch.object(health.members, "stuck", return_value=(200, stuck)),
            mock.patch.object(
                health.quests, "questers", return_value=(200, {"questers": []})
            ),
        ):
            status, payload = health.health({}, ctx)
        self.assertEqual(200, status)
        keys = [f["key"] for f in payload["findings"]]
        self.assertEqual(
            [
                "guild-bank-empty:Bonkers",
                "dungeon-clear-rate:blackfathom",
                "stuck:Grug:s",
            ],
            keys,
        )
        self.assertEqual(
            "Blackfathom Deeps runs clear 0 of 10 in a day",
            payload["findings"][1]["title"],
        )
        self.assertTrue(payload["checked_at"].endswith("Z"))
        # The guild list is bound, never formatted into the statement.
        runs_params = [p for sql, p in asked if "overseer_guild_run" in sql][0]
        self.assertEqual(("Bonkers", "Cave", 1, 500), runs_params)

    def test_a_realm_without_the_tables_reads_as_no_findings(self):
        gap = realmread.MISSING_TABLE
        answers = {
            health.NOW_SQL: [{"now_at": NOW}],
            guildrun._RUN_SQL: gap,
            guildrun._RUN_SQL_THIN: gap,
            health.BANK_SQL: gap,
            health.BANK_MOVED_SQL: gap,
            health.INVITES_SQL: gap,
        }
        ctx, _ = ctx_for(answers)
        with (
            mock.patch.object(
                health.members, "stuck", return_value=(200, {"members": []})
            ),
            mock.patch.object(
                health.quests, "questers", return_value=(200, {"questers": []})
            ),
        ):
            self.assertEqual(
                (200, []),
                (health.health({}, ctx)[0], health.health({}, ctx)[1]["findings"]),
            )


if __name__ == "__main__":
    unittest.main()
