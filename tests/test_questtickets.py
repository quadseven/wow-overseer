"""Each broken quest becomes a ticket under the questers epic (#926):
questtickets.run against an in-memory realm and a fake GitHub tracker."""

import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import questcatalogue as qc  # noqa: E402
import questledger as ql  # noqa: E402
import questtickets as qt  # noqa: E402

EPIC = 922
SITE = "https://example.com/overseer/"
ALLIANCE_ONLY = 1 | 4 | 8 | 64 | 1024


def quest(qid, title, level, sort=12):
    return {
        "quest": qid,
        "title": title,
        "level": level,
        "min_level": max(1, level - 2),
        "sort": sort,
        "races": ALLIANCE_ONLY,
        "classes": 0,
        "follows": 0,
    }


QUEST_ROWS = [
    quest(11, "Wolves Across the Border", 6),
    quest(12, "Kobold Candles", 7),
    quest(13, "Brotherhood of Thieves", 8),
]
GIVER_ROWS = [
    {"quest": q["quest"], "role": role, "map_id": 0}
    for q in QUEST_ROWS
    for role in ("start", "end")
]


def attempt(quest_id, guid, name, state, reason=""):
    return {
        "quest": quest_id,
        "guid": guid,
        "character_name": name,
        "state": state,
        "reason": reason,
    }


def counts(quest_id, guid, mobs=(), items=()):
    row = {"quest": quest_id, "guid": guid}
    for i in range(1, 5):
        have, need = mobs[i - 1] if i <= len(mobs) else (0, 0)
        row["mobcount%d" % i], row["need_mob%d" % i] = have, need
    for i in range(1, 7):
        have, need = items[i - 1] if i <= len(items) else (0, 0)
        row["itemcount%d" % i], row["need_item%d" % i] = have, need
    return row


class Realm:
    """The statements questtickets.run sends, answered from lists."""

    def __init__(self, ledger, tickets=(), objectives=(), fail_record=False):
        self.ledger = list(ledger)
        self.tickets = [dict(t) for t in tickets]
        self.objectives = list(objectives)
        self.fail_record = fail_record
        self.created = False

    def rows(self, sql, params=()):
        if sql == ql.TICKETS_SQL:
            return list(self.tickets)
        if sql == qt.LEDGER_SQL:
            broken = {r["quest"] for r in self.ledger if r["state"] == ql.BROKEN}
            return [r for r in self.ledger if r["quest"] in broken]
        if sql == qc.QUESTS_SQL:
            return QUEST_ROWS
        if sql == qc.GIVERS_SQL:
            return GIVER_ROWS
        if sql.startswith(qt.OBJECTIVES_SQL.split("{")[0]):
            return [
                r
                for r in self.objectives
                if r["quest"] in params and r["guid"] in params
            ]
        raise AssertionError("unexpected statement: %s" % sql)

    def write(self, sql, params=()):
        if sql == ql.TICKET_TABLE_SQL:
            self.created = True
            return
        if sql == ql.TICKET_WRITE_SQL:
            if self.fail_record:
                raise OSError("the realm went away")
            quest_id, issue, url = params
            if not any(t["quest"] == quest_id for t in self.tickets):
                self.tickets.append({"quest": quest_id, "issue": issue, "url": url})
            return
        raise AssertionError("unexpected write: %s" % sql)

    def ticket(self, quest_id):
        return next((t["issue"] for t in self.tickets if t["quest"] == quest_id), None)


class Tracker:
    """A repository's issues and the epic's sub-issues, in memory."""

    def __init__(self, issues=()):
        self.issues = [dict(i) for i in issues]
        self.children_of = {EPIC: [i["id"] for i in self.issues]}
        self.calls = []

    def children(self, epic):
        self.calls.append(("children", epic))
        ids = self.children_of.get(epic, [])
        return [i for i in self.issues if i["id"] in ids]

    def open(self, title, body, labels):
        self.calls.append(("open", title))
        number = 1000 + len(self.issues)
        issue = {
            "id": 50000 + number,
            "number": number,
            "html_url": "https://example.com/issues/%d" % number,
            "title": title,
            "body": body,
            "labels": list(labels),
        }
        self.issues.append(issue)
        return issue

    def attach(self, epic, issue_id):
        self.calls.append(("attach", epic, issue_id))
        self.children_of.setdefault(epic, []).append(issue_id)

    def under_epic(self):
        return self.children(EPIC)


class Base(unittest.TestCase):
    def setUp(self):
        qc.forget()
        self.addCleanup(qc.forget)

    def run_pass(self, realm, tracker, limit=qt.LIMIT):
        return qt.run(realm, tracker, SITE, EPIC, limit)


class EachNewBrokenQuest(Base):
    def test_gets_exactly_one_issue_under_the_epic_and_the_ledger_keeps_its_number(
        self,
    ):
        realm = Realm(
            [
                attempt(11, 7, "Tharn", ql.BROKEN, ql.FAILED_REASON),
                attempt(12, 8, "Mirra", ql.BROKEN, "the candles never drop"),
                attempt(13, 8, "Mirra", ql.TAKEN),
            ]
        )
        tracker = Tracker()
        notes = self.run_pass(realm, tracker)
        self.assertTrue(realm.created)
        filed = tracker.under_epic()
        self.assertEqual(len(filed), 2)
        self.assertEqual(
            [i["title"] for i in filed],
            [
                'Quest 11 "Wolves Across the Border" cannot be finished '
                "(Elwynn Forest, level 6)",
                'Quest 12 "Kobold Candles" cannot be finished (Elwynn Forest, level 7)',
            ],
        )
        for issue in filed:
            self.assertEqual(issue["labels"], ["loom:ticket", "loom:queued"])
        self.assertEqual(realm.ticket(11), filed[0]["number"])
        self.assertEqual(realm.ticket(12), filed[1]["number"])
        self.assertIsNone(realm.ticket(13))
        self.assertEqual(
            notes,
            [
                "quest 11: filed #%d" % filed[0]["number"],
                "quest 12: filed #%d" % filed[1]["number"],
            ],
        )

    def test_the_body_says_what_broke_who_broke_it_and_where_to_look(self):
        realm = Realm(
            [
                attempt(12, 8, "Mirra", ql.BROKEN, "the candles never drop"),
                attempt(12, 7, "Tharn", ql.BROKEN, ql.FAILED_REASON),
            ],
            objectives=[counts(12, 8, mobs=[(3, 10)], items=[(0, 8)])],
        )
        tracker = Tracker()
        self.run_pass(realm, tracker)
        (issue,) = tracker.under_epic()
        body = issue["body"]
        self.assertIn("- Quest: 12, Kobold Candles", body)
        self.assertIn("(https://example.com/overseer/#/quests/12)", body)
        self.assertIn("- Zone: Elwynn Forest", body)
        self.assertIn("- Level: level 7, taken from level 5", body)
        self.assertIn(
            "- **Mirra**, of the Cave questers (Tharn, Mirra, Velo, Durga, Fizzik). "
            "Reason: the candles never drop. Objectives when last seen: "
            "kills or uses 3/10; items 0/8.",
            body,
        )
        # Tharn's quest is no longer in the log: no counts to show.
        self.assertIn(
            "Reason: %s. Objectives when last seen: not in the log any more"
            % ql.FAILED_REASON,
            body,
        )
        self.assertLess(body.index("**Mirra**"), body.index("**Tharn**"))
        self.assertIn("Part of #922", body)
        self.assertEqual(qt.marked(body), 12)
        for section in (
            "## Why",
            "## What",
            "## Acceptance criteria",
            "## Size",
            "## Out of scope",
        ):
            self.assertIn(section, body)

    def test_realm_text_never_mentions_anyone(self):
        realm = Realm([attempt(11, 7, "Tharn", ql.BROKEN, "ask @someone about it")])
        tracker = Tracker()
        self.run_pass(realm, tracker)
        (issue,) = tracker.under_epic()
        self.assertNotIn("@someone", issue["body"])

    def test_a_quest_broken_by_two_questers_is_one_issue(self):
        realm = Realm(
            [
                attempt(11, 7, "Tharn", ql.BROKEN, ql.FAILED_REASON),
                attempt(11, 30, "Saelis", ql.BROKEN, ql.FAILED_REASON),
            ]
        )
        tracker = Tracker()
        self.run_pass(realm, tracker)
        (issue,) = tracker.under_epic()
        self.assertIn("**Saelis**, of the Bonkers questers", issue["body"])
        self.assertIn("**Tharn**, of the Cave questers", issue["body"])

    def test_a_quest_another_quester_completed_is_not_broken(self):
        realm = Realm(
            [
                attempt(11, 7, "Tharn", ql.BROKEN, ql.FAILED_REASON),
                attempt(11, 8, "Mirra", ql.COMPLETED),
            ]
        )
        tracker = Tracker()
        self.assertEqual(
            self.run_pass(realm, tracker), ["no broken quest is waiting for a ticket"]
        )
        self.assertEqual(tracker.issues, [])


class AnAlreadyFiledQuest(Base):
    def test_is_never_filed_again(self):
        realm = Realm(
            [attempt(11, 7, "Tharn", ql.BROKEN, ql.FAILED_REASON)],
            tickets=[
                {"quest": 11, "issue": 940, "url": "https://example.com/issues/940"}
            ],
        )
        tracker = Tracker()
        self.run_pass(realm, tracker)
        self.assertEqual(tracker.issues, [])
        # Nothing due: GitHub is not even asked.
        self.assertEqual(tracker.calls, [])

    def test_a_second_run_files_nothing(self):
        realm = Realm([attempt(11, 7, "Tharn", ql.BROKEN, ql.FAILED_REASON)])
        tracker = Tracker()
        self.run_pass(realm, tracker)
        self.run_pass(realm, tracker)
        self.assertEqual(len(tracker.issues), 1)

    def test_a_second_quester_breaking_it_later_files_nothing(self):
        realm = Realm([attempt(11, 7, "Tharn", ql.BROKEN, ql.FAILED_REASON)])
        tracker = Tracker()
        self.run_pass(realm, tracker)
        realm.ledger.append(attempt(11, 8, "Mirra", ql.BROKEN, ql.FAILED_REASON))
        self.run_pass(realm, tracker)
        self.assertEqual(len(tracker.issues), 1)

    def test_an_issue_under_the_epic_is_recorded_not_filed_again(self):
        realm = Realm([attempt(11, 7, "Tharn", ql.BROKEN, ql.FAILED_REASON)])
        tracker = Tracker(
            [
                {
                    "id": 7001,
                    "number": 941,
                    "html_url": "https://example.com/issues/941",
                    "body": "an earlier run's ticket\n\n" + qt.marker(11) + "\n",
                }
            ]
        )
        notes = self.run_pass(realm, tracker)
        self.assertEqual(len(tracker.issues), 1)
        self.assertEqual(realm.ticket(11), 941)
        self.assertEqual(notes, ["quest 11: already filed as #941"])

    def test_a_failed_record_still_attaches_so_the_next_run_does_not_refile(self):
        realm = Realm(
            [attempt(11, 7, "Tharn", ql.BROKEN, ql.FAILED_REASON)], fail_record=True
        )
        tracker = Tracker()
        with self.assertRaises(OSError):
            self.run_pass(realm, tracker)
        self.assertEqual(len(tracker.under_epic()), 1)
        realm.fail_record = False
        self.run_pass(realm, tracker)
        self.assertEqual(len(tracker.issues), 1)
        self.assertEqual(realm.ticket(11), tracker.issues[0]["number"])


class TheLimit(Base):
    def test_files_at_most_the_limit_and_the_rest_wait(self):
        realm = Realm(
            [attempt(q, 7, "Tharn", ql.BROKEN, ql.FAILED_REASON) for q in (11, 12, 13)]
        )
        tracker = Tracker()
        notes = self.run_pass(realm, tracker, limit=2)
        self.assertEqual(
            [realm.ticket(q) is not None for q in (11, 12, 13)], [True, True, False]
        )
        self.assertIn("1 broken quest(s) wait for tomorrow", notes)
        self.run_pass(realm, tracker, limit=2)
        self.assertIsNotNone(realm.ticket(13))
        self.assertEqual(len(tracker.issues), 3)


class TheTrackerAdapter(unittest.TestCase):
    """Tracker speaks the REST paths GitHub's issues and sub-issues use."""

    class GitHub:
        def __init__(self):
            self.calls = []

        def pages(self, path, key=None):
            self.calls.append(("GET", path))
            return [{"number": 1}]

        def call(self, method, path, body=None, ok=(200,), url=None):
            self.calls.append((method, path, body, ok))
            return types.SimpleNamespace(json=lambda: {"id": 9, "number": 2})

    def test_paths(self):
        gh = self.GitHub()
        tracker = qt.Tracker(gh)
        self.assertEqual(tracker.children(922), [{"number": 1}])
        self.assertEqual(tracker.open("t", "b", ["loom:ticket"])["number"], 2)
        tracker.attach(922, 9)
        self.assertEqual(
            gh.calls,
            [
                ("GET", "/issues/922/sub_issues"),
                (
                    "POST",
                    "/issues",
                    {"title": "t", "body": "b", "labels": ["loom:ticket"]},
                    (201,),
                ),
                ("POST", "/issues/922/sub_issues", {"sub_issue_id": 9}, (201,)),
            ],
        )


if __name__ == "__main__":
    unittest.main()
