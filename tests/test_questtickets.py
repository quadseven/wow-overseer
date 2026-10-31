"""One GitHub issue per broken quest (#926), through the real filing path."""

import pathlib
import sys
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import questledger as ql  # noqa: E402
import questtickets as qt  # noqa: E402


def row(quest, guid=7, name="Tharn", ticket=None):
    return {
        "quest": quest,
        "guid": guid,
        "character_name": name,
        "reason": ql.FAILED_REASON,
        "ticket": ticket,
    }


class Store:
    def __init__(self, rows):
        self.rows = rows

    def broken(self):
        return [dict(r) for r in self.rows]

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
    def __init__(self, refuse=None):
        self.calls, self.refuse, self.next = [], refuse, 1000

    def call(self, method, path, body=None, ok=(200,)):
        self.calls.append((method, path, body))
        if self.refuse and self.refuse in path:
            raise RuntimeError("refused")
        self.next += 1
        return types.SimpleNamespace(
            json=lambda n=self.next: {"id": n * 10, "number": n}
        )

    def issues(self):
        return [c for c in self.calls if c[1] == "/issues"]


class Filing(unittest.TestCase):
    def run_pass(self, store, github=None):
        self.github = github or FakeGitHub()
        return qt.run(store, qt.Client(self.github), (), "")

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

    def test_a_refused_link_keeps_the_issue_it_filed(self):
        store = Store([row(1)])
        self.run_pass(store, FakeGitHub(refuse="sub_issues"))
        self.assertEqual(store.rows[0]["ticket"], 1001)

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

    def test_with_no_site_the_body_names_the_route_and_no_host(self):
        self.assertIn("Quests page: #/quests/62", qt.body(62, None, [row(62)], [], ""))


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


if __name__ == "__main__":
    unittest.main()
