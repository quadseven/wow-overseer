"""One GitHub issue per broken quest (#926), through the real filing path."""

import importlib
import pathlib
import sys
import types
import unittest
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

    def retire(self, ticket, quest):
        for r in self.rows:
            if r["quest"] == quest and r.get("ticket") == ticket:
                r["ticket"] = None
                break


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


class QuesterBoundRefusalTest(unittest.TestCase):
    """A quest another quester completed is not filed for one quester's refusal."""

    def refused(self, quest, reason, guid=8):
        r = row(quest, guid=guid, name="Pindle")
        r["reason"] = reason
        return r

    def completed_row(self, quest, guid=9):
        r = row(quest, guid=guid, name="Otherer")
        r["reason"] = ql.FAILED_REASON
        r["state"] = ql.COMPLETED
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


class RetireTest(unittest.TestCase):
    """Tickets are retired for completed quests with only quester-bound broken rows."""

    def refused(self, quest, reason, guid=8):
        r = row(quest, guid=guid, name="Pindle")
        r["reason"] = reason
        return r

    def completed_row(self, quest, guid=9):
        r = row(quest, guid=guid, name="Otherer")
        r["reason"] = ql.FAILED_REASON
        r["state"] = ql.COMPLETED
        return r

    def test_plan_returns_completed_quests_with_only_quester_bound_tickets(self):
        rows = [
            self.refused(221, "the quest giver would not give it: not eligible", 7),
            self.refused(221, "the turn-in NPC would not take it: no object", 8),
            self.completed_row(221, 9),
            self.refused(222, "the quest giver would not give it: not eligible", 7),
            self.refused(222, "the turn-in NPC would not take it: no object", 8),
            self.completed_row(222, 9),
        ]
        
        def ticket_lookup(quest):
            if quest == 221:
                return 1001
            if quest == 222:
                return 1002
            return None
        
        store = Store(rows)
        store.completed = lambda: [221, 222]
        out = qt.run(store, qt.Client(FakeGitHub()), [])
        self.assertEqual(out["retired"], 2)
        self.assertEqual(out["filed"], 0)
        
    def test_run_closes_tickets_with_comment(self):
        rows = [
            self.refused(221, "the quest giver would not give it: not eligible", 7),
            self.refused(221, "the turn-in NPC would not take it: no object", 8),
            self.completed_row(221, 9),
        ]
        
        def ticket_lookup(quest):
            if quest == 221:
                return 1001
            return None
        
        store = Store(rows)
        store.completed = lambda: [221]
        
        github = FakeGitHub()
        out = qt.run(store, qt.Client(github), [])
        
        self.assertEqual(out["retired"], 1)
        self.assertEqual(out["filed"], 0)
        
        comment_calls = [c for c in github.calls if "/issues/1001/comments" in c[1]]
        self.assertEqual(len(comment_calls), 1)
        
        patch_calls = [c for c in github.calls if c[1] == "/issues/1001" and c[0] == "PATCH"]
        self.assertEqual(len(patch_calls), 1)
        self.assertEqual(patch_calls[0][2]["state"], "closed")
        
    def test_retire_limited_to_max_per_pass(self):
        rows = []
        for i in range(1, 16):
            rows.extend([
                self.refused(i, "the quest giver would not give it: not eligible", 7),
                self.refused(i, "the turn-in NPC would not take it: no object", 8),
                self.completed_row(i, 9),
            ])
        
        def ticket_lookup(quest):
            return 1000 + quest
        
        store = Store(rows)
        store.completed = lambda: list(range(1, 16))
        
        github = FakeGitHub()
        out = qt.run(store, qt.Client(github), [])
        
        self.assertEqual(out["retired"], 10)
        self.assertEqual(out["filed"], 0)


if __name__ == "__main__":
    unittest.main()