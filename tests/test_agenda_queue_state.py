"""The family banner does not call a campaign finished while the next waits (#2796).

The banner said "The dungeon campaign is finished: 20 of 20 runs done." and
told the reader to queue more dungeons, while the queue line printed right
under it read "Queue: Dire Maul 10 (starting)". The leader's counter counts
the active queue head only, so while a queued entry waits for its start it
still holds the campaign before, at its full count, and the banner was handed
no queue rows to know better.

`agenda.build_agenda` now takes the pending queue rows and reads the
campaign's state from `campaignqueue.campaign_state`, the function the console
sections read (#2249). Pure: dict rows in, the banner's JSON out; the last
class reads map_server.py as text for the one read that feeds it.
"""

import pathlib
import unittest
from datetime import datetime, timedelta

import agenda
import campaignqueue

HERE = pathlib.Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 16, 2, 0, 0)
FAMILY = ("Bork", "Grog", "Grug", "Og", "Ugga")
OTHERS = ("Oz", "Uzza", "Zork", "Zrog", "Zug")


def roster(done: int, wanted: int, names=FAMILY, head="Grug") -> list:
    """One family on a dungeon job, its head leading, every row at one count."""
    return [
        {
            "name": name,
            "family": head,
            "enabled": 1,
            "lead": 1 if name == head else 0,
            "job": "dungeon:blackrock-depths",
            "drive_quest": 0,
            "travel_npc": "",
            "learn_skill": 0,
            "dungeon_runs_wanted": wanted,
            "dungeon_runs_done": done,
        }
        for name in names
    ]


def entry(row_id, keyword, runs, status, position=0, family="Grug") -> dict:
    return {
        "id": row_id,
        "family": family,
        "position": position,
        "keyword": keyword,
        "runs_wanted": runs,
        "status": status,
        "source": "",
        "goal_item": 0,
    }


def build(roster_rows, queue_rows=None, members=None) -> dict:
    """build_agenda with the quiet arguments filled in. The queue rows are
    handed in only when a test has some, so the tests of the unchanged
    sentences run against a banner that never took any."""
    moved = [{"kind": "quest_accept", "last_seen": NOW - timedelta(minutes=1)}]
    queue = {} if queue_rows is None else {"queue_rows": queue_rows}
    return agenda.build_agenda(
        list(roster_rows), [], [], [], [], moved, {}, now=NOW, members=members, **queue
    )


def said(out: dict) -> str:
    return " ".join([out["headline"], *out["detail"]])


class AQueuedEntryIsNotAFinishedCampaign(unittest.TestCase):
    """The live shape: the counter at its cap, the next entry queued and its
    start withheld."""

    def setUp(self):
        self.out = build(
            roster(20, 20), [entry(7, "dire-maul-east-east", 10, "queued")]
        )

    def test_the_banner_does_not_say_finished_or_to_queue_more(self):
        self.assertEqual(agenda.DUNGEON, self.out["activity"])
        self.assertNotIn("finished", said(self.out))
        self.assertNotIn("queue more dungeons", said(self.out))

    def test_the_headline_names_the_entry_that_starts_next(self):
        self.assertIn("Dire Maul", self.out["headline"])
        self.assertIn("10 runs", self.out["headline"])
        self.assertIn("starts next", self.out["headline"])

    def test_the_old_count_is_said_as_the_campaign_before(self):
        self.assertIn("20 of 20", said(self.out))
        self.assertIn("the campaign before", said(self.out))

    def test_another_familys_queue_is_not_this_familys(self):
        """The queue table holds every family. A queued entry of the other
        family must not turn this family's finished campaign into a start."""
        out = build(
            roster(20, 20),
            [entry(7, "dire-maul-east-east", 10, "queued", family="Zug")],
        )
        self.assertIn("finished", out["headline"])
        self.assertEqual(campaignqueue.OVER, out["campaign_state"])

    def test_a_family_narrowed_by_members_reads_its_own_queue(self):
        both = roster(20, 20) + roster(3, 20, OTHERS, "Zug")
        queue = [
            entry(7, "dire-maul-east-east", 10, "queued"),
            entry(8, "scholomance", 20, "active", family="Zug"),
        ]
        ours = build(both, queue, members=list(FAMILY))
        theirs = build(both, queue, members=list(OTHERS))
        self.assertEqual(campaignqueue.STARTING, ours["campaign_state"])
        self.assertEqual(campaignqueue.RUNNING, theirs["campaign_state"])
        self.assertIn("Between dungeon runs: 3 of 20 done.", theirs["headline"])


class AnOverCampaignWithAnEntryBehindIt(unittest.TestCase):
    def test_the_banner_names_what_the_queue_moves_on_to(self):
        out = build(
            roster(20, 20),
            [
                entry(7, "blackrock-depths", 20, "active", 0),
                entry(8, "scholomance", 5, "queued", 1),
            ],
        )
        self.assertIn("finished", out["headline"])
        self.assertIn("The queue moves on to Scholomance, 5 runs.", out["detail"])
        self.assertNotIn("queue more dungeons", said(out))


class TheBannerAndTheQueueViewAgree(unittest.TestCase):
    """One function behind both: the banner's state is the queue view's."""

    def cases(self) -> tuple:
        return (
            (campaignqueue.STARTING, 20, [entry(7, "scholomance", 5, "queued")]),
            (campaignqueue.RUNNING, 3, [entry(7, "blackrock-depths", 20, "active")]),
            (campaignqueue.OVER, 20, [entry(7, "blackrock-depths", 20, "active")]),
        )

    def test_they_carry_one_state(self):
        for want, done, queue in self.cases():
            with self.subTest(want):
                out = build(roster(done, 20), queue)
                view = campaignqueue.view(queue, done, "Grug")
                self.assertEqual(want, out["campaign_state"])
                self.assertEqual(want, view["state"])

    def test_finished_is_never_said_over_a_queue_that_is_starting(self):
        for want, done, queue in self.cases():
            with self.subTest(want):
                out = build(roster(done, 20), queue)
                line = campaignqueue.view(queue, done, "Grug")["line"]
                self.assertFalse(
                    "finished" in out["headline"] and "(starting)" in line,
                    "%s / %s" % (out["headline"], line),
                )


class WithNothingQueuedTheBannerIsUnchanged(unittest.TestCase):
    FINISHED = "The dungeon campaign is finished: 20 of 20 runs done."
    ADVICE = (
        "Start the count again on the Decree tab, or queue more dungeons "
        "there, to go again."
    )

    def test_a_finished_campaign_with_an_empty_queue_reads_as_before(self):
        out = build(roster(20, 20), [])
        self.assertEqual(self.FINISHED, out["headline"])
        self.assertIn(self.ADVICE, out["detail"])

    def test_no_queue_rows_handed_in_reads_as_before(self):
        out = build(roster(20, 20))
        self.assertEqual(self.FINISHED, out["headline"])
        self.assertIn(self.ADVICE, out["detail"])

    def test_the_counter_alone_still_gives_the_state(self):
        self.assertEqual(campaignqueue.OVER, build(roster(20, 20))["campaign_state"])
        self.assertEqual(campaignqueue.RUNNING, build(roster(3, 20))["campaign_state"])

    def test_a_cancelled_entry_is_not_a_start(self):
        out = build(roster(20, 20), [entry(7, "scholomance", 5, "cancelled")])
        self.assertEqual(self.FINISHED, out["headline"])

    def test_between_runs_reads_as_before(self):
        out = build(roster(3, 20), [entry(7, "blackrock-depths", 20, "active")])
        self.assertEqual("Between dungeon runs: 3 of 20 done.", out["headline"])


class TheAgendaReadHandsTheQueueIn(unittest.TestCase):
    """map_server._fetch_agenda reads the pending queue rows in the banner's
    own connection, through the guard that turns a missing table into []."""

    @classmethod
    def setUpClass(cls):
        server = (HERE / "map_server.py").read_text(encoding="utf-8")
        start = server.index("def _fetch_agenda")
        cls.fetch = server[start : server.index("def _fetch_streams", start)]

    def test_the_queue_is_read_through_the_guard(self):
        self.assertIn("rd.rows(campaignqueue.SELECT_PENDING_SQL, (),", self.fetch)
        self.assertIn("what=campaignqueue.TABLE)", self.fetch)

    def test_the_rows_reach_the_banner_by_name(self):
        self.assertIn('"queue_rows": queue_rows', self.fetch)


if __name__ == "__main__":
    unittest.main()
