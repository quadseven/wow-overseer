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
import dungeonstall  # noqa: E402
import families as families_module  # noqa: E402
import guildfund  # noqa: E402
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
        self.assertEqual("stuck:Class quest: Call of Fire", f["key"])
        self.assertEqual("Grassfed is stuck: Class quest: Call of Fire", f["title"])
        self.assertEqual(
            ("quests", 1, 27.8, 27.8),
            (f["area"], f["affected"], f["hours"], f["impact"]),
        )
        self.assertEqual("asked the guild for help 16 times", f["evidence"])
        self.assertTrue(f["since"].endswith("Z"))

    def test_members_stuck_on_one_step_are_one_finding(self):
        # 2026-10-15: five members held "Carrying things to sell" filed five
        # tickets for one bug.
        def m(name, hours, step="Carrying things to sell"):
            return {
                "name": name,
                "step": step,
                "blocker": "waiting for a vendor",
                "since": NOW - int(hours * HOUR),
                "kind": "hold",
            }

        stuck = {
            "members": [
                m("Og", 5.1),
                m("Ugga", 5.0),
                m("Bork", 3.2),
                m("Grog", 2.5, "Following Zug (0 yards behind)"),
                m("Oz", 2.2, "Following Zug (4 yards behind)"),
            ]
        }
        found = {f["key"]: f for f in health.stuck_findings(stuck, NOW)}
        self.assertEqual(
            sorted(found), ["stuck:Carrying things to sell", "stuck:Following Zug"]
        )
        sell = found["stuck:Carrying things to sell"]
        self.assertEqual("3 members are stuck: Carrying things to sell", sell["title"])
        self.assertEqual(
            (3, 5.1, 13.3), (sell["affected"], sell["hours"], sell["impact"])
        )
        self.assertTrue(
            sell["evidence"].startswith("Og, Ugga, Bork; waiting for a vendor")
        )
        self.assertEqual(2, found["stuck:Following Zug"]["affected"])

    def test_a_follower_held_by_its_leader_is_on_the_leaders_finding(self):
        # #1059: Grog waits on Grug, who waits on a vendor. One hold, one
        # finding that counts both, said in the leader's own words.
        def m(name, step, blocker, follows=""):
            return {
                "name": name,
                "step": step,
                "blocker": blocker,
                "since": NOW - 3 * HOUR,
                "kind": "hold",
                "follows": follows,
            }

        stuck = {
            "members": [
                m(
                    "Grog",
                    "Following Grug (0 yards behind)",
                    "Waiting for Grug to move on. Grug's own hold: Waiting "
                    "for a vendor within reach.",
                    follows="Grug",
                ),
                m(
                    "Grug",
                    "Carrying things to sell",
                    "Waiting for a vendor within reach.",
                ),
            ]
        }
        (f,) = health.stuck_findings(stuck, NOW)
        self.assertEqual("stuck:Carrying things to sell", f["key"])
        self.assertEqual((2, 6.0), (f["affected"], f["impact"]))
        self.assertEqual(
            "Grug, Grog; Waiting for a vendor within reach.", f["evidence"]
        )


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


def family_run(rid, map_id=33, outcome="stalled", leader="Zug", ago=HOUR):
    return {
        "id": rid,
        "leader_name": leader,
        "map_id": map_id,
        "state": "ended",
        "outcome": outcome,
        "ended_reason": "dungeon module switched itself off",
        "started_unix": NOW - ago,
        "ended_unix": NOW - ago + 1800,
    }


def boss(rid, mask):
    return {"run_id": rid, "kind": "boss", "detail": "x (mask 0 -> %d)" % mask}


ZUG = {"Zug": ["Zug", "Ugga"]}


class FamilyLoops(unittest.TestCase):
    def test_eleven_stalled_shadowfang_runs_are_one_finding(self):
        """2026-10-15: one family ran map 33 eleven times, stalling each time."""
        runs = [family_run(i, ago=(12 - i) * HOUR) for i in range(1, 12)]
        streaks = health.family_streaks(runs, ZUG)
        events = [boss(1, 15), boss(2, 63), boss(2, 63), boss(3, 15)]
        (f,) = health.family_loop_findings(streaks, events, NOW)
        self.assertEqual("family-run-loop:Zug:33", f["key"])
        self.assertEqual(
            "Zug's family ran Shadowfang Keep 11 times without a clear", f["title"]
        )
        # 11 failed runs, the first 11 hours ago, 11 x half an hour lost.
        self.assertEqual((11, 11.0, 60.5), (f["affected"], f["hours"], f["impact"]))
        self.assertIn("11 stalled", f["evidence"])
        self.assertIn('"dungeon module switched itself off"', f["evidence"])
        self.assertIn("encounter mask 63 (6 encounters)", f["evidence"])
        self.assertEqual("dungeons", f["area"])

    def test_every_ending_but_a_clear_counts(self):
        runs = [
            family_run(1, outcome="split_failed"),
            family_run(2, outcome="client_lost"),
            family_run(3, outcome="stalled"),
        ]
        (f,) = health.family_loop_findings(health.family_streaks(runs, ZUG), [], NOW)
        self.assertIn("1 client_lost, 1 split_failed, 1 stalled", f["evidence"])
        self.assertIn("no encounter credited", f["evidence"])

    def test_a_member_leading_counts_for_the_family(self):
        runs = [family_run(i, leader="Ugga") for i in (1, 2, 3)]
        self.assertEqual([(("Zug", 33))], list(health.family_streaks(runs, ZUG)))

    def test_a_clear_of_the_map_ends_the_loop(self):
        runs = [family_run(i) for i in (1, 2, 3, 4)] + [
            family_run(5, outcome="complete")
        ]
        self.assertEqual({}, health.family_streaks(runs, ZUG))

    def test_moving_to_another_map_ends_the_loop(self):
        runs = [family_run(i) for i in (1, 2, 3, 4)] + [family_run(5, map_id=48)]
        self.assertEqual({}, health.family_streaks(runs, ZUG))

    def test_two_failed_runs_are_not_a_loop(self):
        runs = [family_run(1, outcome="complete"), family_run(2), family_run(3)]
        self.assertEqual({}, health.family_streaks(runs, ZUG))

    def test_a_run_still_open_on_the_map_does_not_break_the_loop(self):
        runs = [family_run(i) for i in (1, 2, 3)] + [
            dict(family_run(4), state="active", outcome="")
        ]
        (rows,) = health.family_streaks(runs, ZUG).values()
        self.assertEqual([1, 2, 3], [r["id"] for r in rows])

    def test_a_stranger_leading_is_no_familys_loop(self):
        runs = [family_run(i, leader="Nobody") for i in (1, 2, 3)]
        self.assertEqual({}, health.family_streaks(runs, ZUG))


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

    def test_gold_the_master_withdrew_for_letters_is_not_an_empty_bank(self):
        """The fund withdraws the whole bank to post it: 0 copper in the vault
        with the gold in the master's purse is gold in transit, not absent."""
        rows = [
            {
                "target_name": "Zug",
                "source": guildfund.WITHDRAW_SOURCE,
                "command": "bank withdraw 990000",
                "status": "applied",
                "result": None,
                "age": 3,
            },
            {
                "target_name": "Zug",
                "source": "guildfund:refund:7",
                "command": "send money:250000 subject:Dues refund",
                "status": "delivered",
                "result": None,
                "age": 1,
            },
        ]
        banks = [
            {
                "guild": "Bonkers",
                "bank": 0,
                "broke": 65,
                "members": 76,
                "master": "Zug",
                "purse": 1_000_000,
            }
        ]
        carried = health.with_carried(banks, rows)
        self.assertEqual(740_000, carried[0]["carried"])
        self.assertEqual([], health.bank_findings(carried, {}, NOW))

    def test_carried_gold_is_capped_by_the_masters_purse(self):
        rows = [
            {
                "target_name": "Zug",
                "source": guildfund.WITHDRAW_SOURCE,
                "command": "bank withdraw 990000",
                "status": "applied",
                "result": None,
                "age": 3,
            }
        ]
        banks = [{"guild": "B", "bank": 0, "broke": 1, "master": "Zug", "purse": 5}]
        self.assertEqual(5, health.with_carried(banks, rows)[0]["carried"])

    def test_a_drained_bank_with_nothing_carried_is_still_a_finding(self):
        banks = [{"guild": "B", "bank": 0, "broke": 1, "master": "Zug", "purse": 9}]
        (f,) = health.bank_findings(health.with_carried(banks, []), {}, NOW)
        self.assertEqual("guild-bank-empty:B", f["key"])


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
            health.FUND_SQL: [],
            health.INVITES_SQL: [],
            health.FAMILY_RUNS_SQL: [family_run(i, leader="Grug") for i in (7, 6, 5)],
            dungeonstall.EVENTS_SQL: [boss(6, 3)],
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
                "family-run-loop:Grug:33",
                "stuck:s",
            ],
            keys,
        )
        self.assertIn(
            "encounter mask 3 (2 encounters)", payload["findings"][2]["evidence"]
        )
        self.assertEqual(
            "Blackfathom Deeps runs clear 0 of 10 in a day",
            payload["findings"][1]["title"],
        )
        self.assertTrue(payload["checked_at"].endswith("Z"))
        # The guild list is bound, never formatted into the statement.
        runs_params = [p for sql, p in asked if "overseer_guild_run" in sql][0]
        self.assertEqual(("Bonkers", "Cave", 1, 500), runs_params)
        # The family names are bound too, and only the loop's runs' timeline is read.
        family_params = [p for sql, p in asked if "FROM overseer_dungeon_run " in sql]
        self.assertEqual([("Grug", "Ugga", 24, 500)], family_params)
        event_params = [p for sql, p in asked if "overseer_dungeon_run_event" in sql]
        self.assertEqual([(5, 6, 7)], event_params)

    def test_a_realm_without_the_tables_reads_as_no_findings(self):
        gap = realmread.MISSING_TABLE
        answers = {
            health.NOW_SQL: [{"now_at": NOW}],
            guildrun._RUN_SQL: gap,
            guildrun._RUN_SQL_THIN: gap,
            health.BANK_SQL: gap,
            health.BANK_MOVED_SQL: gap,
            health.FUND_SQL: gap,
            health.INVITES_SQL: gap,
            health.FAMILY_RUNS_SQL: gap,
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
