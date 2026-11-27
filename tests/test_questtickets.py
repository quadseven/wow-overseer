"""One GitHub issue per broken quest (#926), through the real filing path."""

import importlib
import pathlib
import sys
import types
import unittest
from datetime import datetime
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import questledger as ql
    import questtickets as qt


def row(quest, guid=7, name="Tharn", ticket=None, state=ql.BROKEN):
    return {
        "quest": quest,
        "guid": guid,
        "character_name": name,
        "state": state,
        "reason": ql.FAILED_REASON,
        "ticket": ticket,
    }


class Store:
    def __init__(self, rows, last_pass=None):
        self.rows = rows
        self._last_pass = last_pass

    def broken(self):
        return [dict(r) for r in self.rows if r.get("state", ql.BROKEN) == ql.BROKEN]

    def ticket(self, quest):
        for r in self.rows:
            if r["quest"] == quest and r.get("ticket") is not None:
                return r["ticket"]
        return None

    def last_pass(self):
        return self._last_pass

    def record_pass(self, when):
        self._last_pass = when

    def objectives(self, quest):
        return [{"guid": 7, "mobcount1": 3, "itemcount2": 1}]

    def take(self, quest, ticket):
        for r in self.rows:
            if r["quest"] == quest and r["ticket"] is None:
                r["ticket"] = ticket

    def filed(self, quest, ticket):
        for r in self.rows:
            if r["quest"] == quest and r["ticket"] == qt.FILING:
                r["ticket"] = ticket

    def release(self, quest):
        for r in self.rows:
            if r["quest"] == quest and r["ticket"] == qt.FILING:
                r["ticket"] = None


class FakeGitHub:
    def __init__(self, refuse=None, timeout=None):
        self.calls, self.refuse, self.timeout, self.next = [], refuse, timeout, 1000

    def call(self, method, path, body=None, ok=(200,)):
        self.calls.append((method, path, body))
        if self.refuse and self.refuse in path:
            raise RuntimeError("refused")
        if self.timeout and (self.timeout is True or self.timeout in path):
            raise TimeoutError("timed out")
        self.next += 1
        return types.SimpleNamespace(
            json=lambda n=self.next: {"id": n * 10, "number": n}
        )

    def issues(self):
        return [c for c in self.calls if c[1] == "/issues"]


class Filing(unittest.TestCase):
    def run_pass(self, store, github=None, now=None):
        self.github = github or FakeGitHub()
        return qt.run(store, qt.Client(self.github), (), "", now=now)

    def test_two_questers_on_one_quest_are_one_issue_under_the_epic(self):
        store = Store([row(1), row(1, 8, "Mirra"), row(2)])
        done = self.run_pass(store)
        self.assertEqual(done["filed"], 2)
        self.assertEqual(len(self.github.issues()), 2)
        self.assertEqual({r["ticket"] for r in store.rows if r["quest"] == 1}, {1001})
        link = [c for c in self.github.calls if "sub_issues" in c[1]][0]
        self.assertEqual(link[1], "/issues/%d/sub_issues" % qt.EPIC)
        self.assertEqual(link[2], {"sub_issue_id": 10010})
        self.assertEqual(self.github.issues()[0][2]["labels"], list(qt.LABELS))

    def test_a_filed_quest_is_never_filed_again(self):
        store = Store([row(1)])
        self.run_pass(store)
        self.assertEqual(self.run_pass(store)["filed"], 0)
        self.assertEqual(self.github.issues(), [])

    def test_a_new_row_of_a_filed_quest_takes_its_number(self):
        store = Store([row(1, ticket=55), row(1, 8, "Mirra")])
        done = self.run_pass(store)
        self.assertEqual((done["filed"], done["copied"]), (0, 1))
        self.assertEqual(store.rows[1]["ticket"], 55)

    def test_a_refused_filing_frees_the_quest_and_stops_the_pass(self):
        store = Store([row(1), row(2)])
        with self.assertRaises(RuntimeError):
            self.run_pass(store, FakeGitHub(refuse="/issues"))
        self.assertIsNone(store.rows[0]["ticket"])

    def test_a_pass_that_fails_partway_still_records_its_pass_time(self):
        # Elder on #1726: a refused POST after earlier filings must not leave
        # the pass unrecorded, or a restart files five more inside the day.
        store = Store([row(1), row(2)])
        github = FakeGitHub()
        real_call = github.call

        def refuse_second_issue(method, path, body=None, ok=(200,)):
            if path == "/issues" and github.issues():
                github.calls.append((method, path, body))
                raise RuntimeError("refused")
            return real_call(method, path, body, ok)

        github.call = refuse_second_issue
        with self.assertRaises(RuntimeError):
            self.run_pass(store, github, now=5000.0)
        self.assertEqual(store.rows[0]["ticket"], 1001)
        self.assertEqual(store.last_pass(), 5000.0)

    def test_a_refused_link_keeps_the_issue_it_filed(self):
        store = Store([row(1)])
        done = self.run_pass(store, FakeGitHub(refuse="sub_issues"))
        self.assertEqual(store.rows[0]["ticket"], 1001)
        self.assertEqual(done["unlinked"], [1001])

    def test_a_linked_issue_is_not_reported_unlinked(self):
        self.assertEqual(self.run_pass(Store([row(1)]))["unlinked"], [])

    def test_a_filing_that_never_finished_is_reported_and_not_retried(self):
        done = self.run_pass(Store([row(1, ticket=qt.FILING)]))
        self.assertEqual((done["filed"], done["stuck"]), (0, [1]))
        self.assertEqual(self.github.issues(), [])

    def test_a_pass_is_bounded(self):
        store = Store([row(q) for q in range(1, qt.MAX_PER_PASS + 4)])
        self.assertEqual(self.run_pass(store)["filed"], qt.MAX_PER_PASS)

    def test_the_body_names_what_a_fixer_needs(self):
        info = types.SimpleNamespace(
            title="The Fargodeep Mine", zone_name="Elwynn", level=7
        )
        text = qt.body(
            62, info, [row(62)], [{"guid": 7, "mobcount1": 3}], "https://site.example/"
        )
        for want in (
            "The Fargodeep Mine",
            "Elwynn",
            "Level: 7",
            "Tharn",
            ql.FAILED_REASON,
            "mobcount1 3",
            "Cave:",
            "https://site.example/#/quests/62",
            "Part of #%d" % qt.EPIC,
        ):
            self.assertIn(want, text)

    def test_the_body_forbids_a_reason_keyed_on_the_quest_id(self):
        text = qt.body(62, None, [row(62)], [], "")
        out_of_scope = text.split("## Out of scope", 1)[1]
        self.assertIn("A reason string keyed on this quest's id", out_of_scope)

    def test_stolen_journal_ticket_explains_the_recorded_take_refusal(self):
        # bridge._record_quest_broken persists the reason from questers._giver_failure.
        reason = "the quest giver would not give it: no giver of that quest in reach"
        rows = [
            dict(row(218, guid=7, name="Fizzik"), reason=reason),
            dict(row(218, guid=8, name="Pindle"), reason=reason),
        ]
        text = qt.body(218, None, rows, [], "")
        self.assertEqual(text.count("Reason: " + reason), 2)
        self.assertEqual(text.count("Last objective counts: not in the log now"), 2)
        self.assertEqual(
            text.count(
                "At that take, the quest command found no live creature giver within "
                "its 20-yard arrival radius. The stored rows explain the refusal "
                "but do not identify why the lookup found no giver."
            ),
            1,
        )
        self.assertNotIn(
            "The take was refused because no living creature",
            qt.body(218, None, [row(218)], [], ""),
        )

    def test_already_in_log_take_refusal_is_explained_as_a_point_in_time_read(self):
        # This stored row shape is selected by questtickets.BROKEN_SQL. The
        # current questers.LOG_STATE_REFUSALS guard no longer counts this reason
        # as evidence of a broken take.
        reason = "the quest giver would not give it: already in the quest log"
        text = qt.body(
            222,
            None,
            [dict(row(222, name="Quester A"), reason=reason)],
            [],
            "",
        )

        self.assertIn("Reason: " + reason, text)
        self.assertIn(
            "The take refusal records that the quest was already in the character's "
            "quest log at the time. It is a log-state observation, not evidence that "
            "the quest's objectives cannot be completed.",
            text,
        )

    def test_tickets_default_to_the_open_quest_epic(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("QUEST_TICKET_EPIC", None)
            with stub_modules(pymysql=PYMYSQL):
                fresh = importlib.reload(qt)
        self.assertEqual(1575, fresh.EPIC)

    def test_with_no_site_the_body_names_the_route_and_no_host(self):
        self.assertIn("Quests page: #/quests/62", qt.body(62, None, [row(62)], [], ""))

    def test_a_restart_does_not_start_a_second_pass_inside_a_day(self):
        now = 1_000_000.0
        cycle = 86400.0
        # Elapsed < cycle yields remainder cycle - elapsed
        self.assertEqual(
            qt.initial_delay(now - 7200.0, cycle, now),
            79200.0,
        )
        self.assertEqual(qt.initial_delay(None, cycle, now), 300.0)
        self.assertEqual(qt.initial_delay(now - 90000.0, cycle, now), 300.0)
        self.assertEqual(qt.initial_delay(now - 86300.0, cycle, now), 300.0)
        self.assertEqual(qt.initial_delay(now + 1000.0, cycle, now), cycle)

        # Drive a restart against a populated pass-time memo in the store
        store = Store([row(1)], last_pass=now - 7200.0)
        # On bridge restart inside a day (2 hours after previous pass), the delay
        # is the remainder of the 24-hour cycle (22 hours), preventing a duplicate pass
        restart_delay = qt.initial_delay(store.last_pass(), cycle, now)
        self.assertEqual(restart_delay, 79200.0)

        # When a day has passed since the recorded pass, restart only waits startup
        later = now - 7200.0 + cycle + 10.0
        self.assertEqual(qt.initial_delay(store.last_pass(), cycle, later), 300.0)

        # Running the pass updates the memo to now
        self.run_pass(store, now=later)
        self.assertEqual(store.last_pass(), later)
        self.assertEqual(
            qt.initial_delay(store.last_pass(), cycle, later + 3600.0),
            cycle - 3600.0,
        )

    def test_plan_with_earlier_row_in_non_broken_state_carrying_ticket(self):
        earlier_completed = row(1, guid=7, ticket=55, state=ql.COMPLETED)
        new_broken = row(1, guid=8, name="Mirra", ticket=None, state=ql.BROKEN)

        all_ledger = [earlier_completed, new_broken]

        def ticket_lookup(quest_id):
            for r in all_ledger:
                if r["quest"] == quest_id and r.get("ticket") is not None:
                    return r["ticket"]
            return None

        # Driving plan with broken rows only and ticket_for from non-broken row
        p = qt.plan([new_broken], ticket_for=ticket_lookup)
        self.assertEqual(p.new, ())
        self.assertEqual(p.copies, ((1, 55),))
        self.assertEqual(p.stuck, ())

        # If earlier row had FILING in flight, it is marked stuck
        p_stuck = qt.plan([new_broken], ticket_for=lambda q: qt.FILING)
        self.assertEqual(p_stuck.new, ())
        self.assertEqual(p_stuck.copies, ())
        self.assertEqual(p_stuck.stuck, (1,))

    def test_a_quest_filed_once_is_never_filed_again_after_its_row_leaves_broken(self):
        store = Store(
            [
                row(1, guid=7, ticket=55, state=ql.COMPLETED),
                row(1, guid=8, name="Mirra", ticket=None, state=ql.BROKEN),
            ]
        )
        done = self.run_pass(store)
        self.assertEqual((done["filed"], done["copied"]), (0, 1))
        self.assertEqual(self.github.issues(), [])
        self.assertEqual(store.rows[1]["ticket"], 55)

    def test_client_file_timeout_propagates_timeout_error(self):
        github = FakeGitHub(timeout="/issues")
        client = qt.Client(github)
        with self.assertRaises(TimeoutError):
            client.file("Quest 1", "Body")

    def test_a_timed_out_post_files_nothing_further(self):
        store = Store([row(1), row(2)])
        github = FakeGitHub(timeout="/issues")
        client = qt.Client(github)
        with self.assertRaises(TimeoutError):
            qt.run(store, client, (), "")
        self.assertEqual(store.rows[0]["ticket"], qt.FILING)
        self.assertIsNone(store.rows[1]["ticket"])

        github2 = FakeGitHub()
        client2 = qt.Client(github2)
        done = qt.run(store, client2, (), "")
        self.assertEqual(done["stuck"], [1])
        self.assertEqual(done["filed"], 1)
        self.assertEqual(len(github2.issues()), 1)
        self.assertIn("Quest 2", github2.issues()[0][2]["title"])
        self.assertEqual(store.rows[0]["ticket"], qt.FILING)

    def test_a_refused_post_releases_the_row(self):
        store = Store([row(1), row(2)])
        github = FakeGitHub(refuse="/issues")
        client = qt.Client(github)
        with self.assertRaises(RuntimeError):
            qt.run(store, client, (), "")
        self.assertIsNone(store.rows[0]["ticket"])

    def test_is_timeout_recognition(self):
        import urllib.error

        class CustomTimeout(Exception):
            pass

        self.assertTrue(qt._is_timeout(TimeoutError("request timed out")))
        self.assertTrue(
            qt._is_timeout(urllib.error.URLError(TimeoutError("connection timed out")))
        )
        self.assertTrue(qt._is_timeout(CustomTimeout("custom timeout")))
        self.assertTrue(
            qt._is_timeout(urllib.error.URLError(CustomTimeout("nested timeout")))
        )
        self.assertFalse(qt._is_timeout(RuntimeError("refused")))
        self.assertFalse(
            qt._is_timeout(urllib.error.URLError(RuntimeError("connection refused")))
        )
        self.assertFalse(qt._is_timeout(ValueError("bad format")))


class Plumbing(unittest.TestCase):
    def test_holes_refuses_an_empty_list(self):
        with self.assertRaises(ValueError):
            ql.holes(0)

    def test_no_credential_means_no_client(self):
        self.assertIsNone(qt.client_from_env(env={"QUEST_TICKET_APP_ID": "1"}))

    def test_the_token_asks_for_issues_only(self):
        env = {
            "QUEST_TICKET_APP_ID": "1",
            "QUEST_TICKET_INSTALLATION_ID": "2",
            "QUEST_TICKET_KEY_PATH": "/k",
        }
        self.assertEqual(
            qt.client_from_env(env=env).github.token.permissions, {"issues": "write"}
        )

    def test_the_column_is_added_once(self):
        for have, adds in ((0, 1), (1, 0)):
            cur = mock.Mock()
            cur.fetchone.return_value = {"n": have}
            qt.ensure_column(cur)
            done = [c.args[0] for c in cur.execute.call_args_list]
            self.assertEqual(done.count(qt.ADD_COLUMN_SQL), adds)

    def test_ticket_of_skips_a_filing_in_flight(self):
        self.assertIsNone(qt.ticket_of([row(1, ticket=qt.FILING)]))
        self.assertEqual(qt.ticket_of([row(1, ticket=9)])["number"], 9)

    def test_sql_store_ticket_reads_from_any_row(self):
        cur = mock.Mock()
        cur.fetchone.return_value = {"ticket": 42}
        store = qt.SqlStore(cur)
        self.assertEqual(store.ticket(10), 42)
        self.assertIn(qt.TICKET_SQL, [c.args[0] for c in cur.execute.call_args_list])

    def test_sql_store_pass_time_round_trips(self):
        cur = mock.Mock()
        cur.fetchone.return_value = {"since": 12345.0}
        store = qt.SqlStore(cur)
        self.assertEqual(store.last_pass(), 12345.0)
        store.record_pass(67890.0)
        self.assertIn(
            qt.RECORD_PASS_SQL, [c.args[0] for c in cur.execute.call_args_list]
        )

    def test_bridge_wires_delay_and_last_pass(self):
        bridge_src = (HERE / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("initial_delay", bridge_src)
        self.assertIn("_read_last_quest_tickets_pass", bridge_src)
        self.assertIn("SqlStore(cur).last_pass()", bridge_src)


class QuesterBoundRefusalTest(unittest.TestCase):
    """A quest another quester completed is not filed for one quester's refusal."""

    def refused(self, quest, reason, guid=8):
        r = row(quest, guid=guid, name="Pindle")
        r["reason"] = reason
        return r

    def test_completed_quest_with_only_refusals_files_nothing(self):
        rows = [
            self.refused(328, "the turn-in NPC would not take it: no object in reach"),
            self.refused(328, "the quest giver would not give it: not eligible", 9),
        ]
        todo = qt.plan(rows, completed={328})
        self.assertEqual(todo.new, ())

    def test_same_rows_file_when_nobody_completed_it(self):
        rows = [self.refused(328, "the turn-in NPC would not take it: no object")]
        self.assertEqual([q for q, _ in qt.plan(rows).new], [328])

    def test_a_stall_on_a_completed_quest_still_files(self):
        rows = [self.refused(348, "its objectives did not move for 2 hours of play")]
        self.assertEqual([q for q, _ in qt.plan(rows, completed={348}).new], [348])

    def test_run_reads_completed_from_the_store(self):
        store = Store([self.refused(353, "the quest giver would not give it: x")])
        store.completed = lambda: [353]
        out = qt.run(store, qt.Client(FakeGitHub()), [])
        self.assertEqual(out["filed"], 0)


class Retirement(unittest.TestCase):
    def test_plan_retires_only_linked_completed_quests_with_refusals(self):
        refusal = "the quest giver would not give it: not eligible"
        rows = [
            dict(row(101, ticket=2001), reason=refusal),
            dict(row(101, guid=8), reason=refusal),
            dict(row(102, ticket=2002), reason=refusal),
            row(102, guid=8, ticket=2002),
            dict(row(103, ticket=2003), reason=refusal),
            dict(row(104), reason=refusal),
            dict(row(105, ticket=qt.FILING), reason=refusal),
            dict(row(106), reason=refusal),
        ]
        todo = qt.plan(
            rows, ticket_for={104: 2004}, completed={101, 102, 104, 105, 106}
        )
        self.assertEqual(todo.retire, ((101, 2001), (104, 2004)))
        self.assertEqual(todo.copies, ((101, 2001), (104, 2004)))
        self.assertEqual(todo.stuck, (105,))
        self.assertEqual(todo.new, ())

    def test_run_closes_at_most_ten_open_tickets_with_completion_evidence(self):
        store = Store(
            [
                dict(
                    row(q, ticket=2000 + q), reason="the turn-in NPC would not take it"
                )
                for q in range(1, 14)
            ]
        )
        store.completed = lambda: range(1, 14)
        store.completion = lambda quest: (2, datetime(2026, 11, 19, 15, 29))
        github, log = mock.Mock(), mock.Mock()

        def call(method, path, body=None, ok=(200,)):
            if method == "GET":
                if path == "/issues/2001":
                    return types.SimpleNamespace(status=404)
                state = "closed" if path == "/issues/2002" else "open"
                return types.SimpleNamespace(status=200, json=lambda: {"state": state})

        github.call.side_effect = call
        github.pages.return_value = []
        done = qt.run(store, qt.Client(github, log), ())

        retired = range(2003, 2013)
        self.assertEqual(done["retired"], 10)
        self.assertEqual(done["filed"], 0)
        self.assertEqual(
            [c for c in github.call.call_args_list if c.args[0] == "PATCH"],
            [
                mock.call(
                    "PATCH",
                    f"/issues/{n}",
                    {"state": "closed", "state_reason": "not_planned"},
                )
                for n in retired
            ],
        )
        self.assertEqual(
            [c.args[0] for c in github.comment.call_args_list], list(retired)
        )
        for number, comment in (c.args for c in github.comment.call_args_list):
            self.assertIn(f"Quest {number - 2000} ", comment)
            self.assertIn("2 questers", comment)
            self.assertIn("2026-11-19 15:29:00", comment)
        self.assertEqual(log.info.call_count, 10)
        for call in log.info.call_args_list:
            self.assertTrue(call.args[0].startswith("questtickets: retired"))
        self.assertEqual([r["ticket"] for r in store.rows], list(range(2001, 2014)))

    def test_retry_after_a_refused_close_does_not_repeat_the_comment(self):
        store = Store(
            [dict(row(101, ticket=2001), reason="the quest giver would not give it")]
        )
        store.completed = lambda: [101]
        store.completion = lambda quest: (1, None)
        github, log = mock.Mock(), mock.Mock()
        github.pages.return_value = []
        open_issue = types.SimpleNamespace(status=200, json=lambda: {"state": "open"})
        github.call.side_effect = [
            open_issue,
            RuntimeError("refused"),
            open_issue,
            None,
        ]
        client = qt.Client(github, log)

        with self.assertRaisesRegex(RuntimeError, "refused"):
            qt.run(store, client, (), now=5000)
        self.assertEqual(store.last_pass(), 5000)
        log.info.assert_not_called()
        self.assertEqual(github.comment.call_count, 1)
        comment = github.comment.call_args.args[1]
        self.assertIn("completed by 1 quester.", comment)
        self.assertIn("completion time is unknown", comment)

        github.pages.return_value = [{"id": 5001, "body": comment}]
        store.completion = lambda quest: (2, datetime(2026, 11, 19, 15, 29))
        github.call.side_effect = [open_issue, None, None]
        self.assertEqual(qt.run(store, client, (), now=91500)["retired"], 1)
        self.assertEqual(github.comment.call_count, 1)
        method, path, update = github.call.call_args_list[-2].args
        self.assertEqual((method, path), ("PATCH", "/issues/comments/5001"))
        self.assertIn("2 questers", update["body"])
        self.assertIn("2026-11-19 15:29:00", update["body"])
        log.info.assert_called_once()


if __name__ == "__main__":
    unittest.main()
