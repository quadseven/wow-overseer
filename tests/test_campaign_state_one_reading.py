"""The console's campaign and queue sections say one state (#2249).

The operator console drew a family's campaign from its leader's run counter
and its queue from the queue rows, and each had its own idea of where the
campaign stood. The counter counts the ACTIVE head only, so while a queued
head waited to start, the counter still held the campaign before it: the
campaign line read "The campaign is over: every run wanted is done, and no
other run will start." and the queue line under it read "(starting)". A
person about to send the next order could not tell whether the family was
free.

`campaignqueue.campaign_state` is the one reading; `decree.family_views`
hands it to both sections. Pure: dict rows in, the console's JSON out.
"""

import unittest

import agenda
import campaignqueue
import decree

FAMILY = ("Bork", "Grog", "Grug", "Og", "Ugga")


def roster(done: int, wanted: int, job: str = "dungeon:blackrock-depths") -> list:
    """One family, Grug leading, every row at the same count."""
    return [
        {
            "name": name,
            "family": "Grug",
            "enabled": 1,
            "lead": 1 if name == "Grug" else 0,
            "job": job,
            "drive_quest": 0,
            "travel_npc": "",
            "learn_skill": 0,
            "dungeon_runs_wanted": wanted,
            "dungeon_runs_done": done,
        }
        for name in FAMILY
    ]


def entry(row_id: int, keyword: str, runs: int, status: str, position: int) -> dict:
    return {
        "id": row_id,
        "family": "Grug",
        "position": position,
        "keyword": keyword,
        "runs_wanted": runs,
        "status": status,
        "source": "",
        "goal_item": 0,
    }


def family(roster_rows: list, queue_rows: list) -> dict:
    """The Grug family's block of the console payload (GET /api/decree)."""
    console = decree.build_console(roster_rows, [], queue_rows=queue_rows)
    return next(f for f in console["families"] if f["key"] == "Grug")


def says_starting(queue: dict) -> bool:
    return "(starting)" in queue["line"] or any(
        e["state"] in (campaignqueue.STARTING, campaignqueue.WAITING)
        for e in queue["entries"][:1]
    )


class AQueuedHeadIsNotACampaignThatIsOver(unittest.TestCase):
    """The live shape: the last entry ran to its count, the next one is queued
    and its start is withheld, so the leader's counter still reads the old
    campaign as complete."""

    def setUp(self):
        self.fam = family(
            roster(20, 20), [entry(7, "dire-maul-east-east", 10, "queued", 0)]
        )

    def test_the_campaign_section_does_not_say_over_while_the_queue_says_starting(self):
        self.assertTrue(says_starting(self.fam["queue"]))
        self.assertFalse(self.fam["campaign"]["over"])
        self.assertNotIn("is over", self.fam["campaign"]["means"])
        self.assertNotIn("no other run will start", self.fam["campaign"]["means"])

    def test_it_says_what_starts_next_instead(self):
        means = self.fam["campaign"]["means"]
        self.assertIn("the campaign before", means)
        self.assertIn("Dire Maul", means)
        self.assertIn("10 runs", means)

    def test_both_sections_carry_the_same_state(self):
        self.assertEqual(campaignqueue.STARTING, self.fam["campaign"]["state"])
        self.assertEqual(campaignqueue.STARTING, self.fam["queue"]["state"])

    def test_a_cap_of_zero_does_not_stop_a_queue_that_is_starting(self):
        fam = family(roster(0, 0), [entry(7, "dire-maul-east-east", 10, "queued", 0)])
        self.assertFalse(fam["campaign"]["stopped"])
        self.assertNotIn("no run begins", fam["campaign"]["means"])

    def test_the_console_wide_campaign_section_agrees_too(self):
        console = decree.build_console(
            roster(20, 20),
            [],
            queue_rows=[entry(7, "dire-maul-east-east", 10, "queued", 0)],
        )
        self.assertEqual(campaignqueue.STARTING, console["campaign"]["state"])
        self.assertFalse(console["campaign"]["over"])


class ACampaignThatIsOverIsNotStartingInTheQueue(unittest.TestCase):
    """The other direction: once the campaign is over, no queue entry of it
    reads as starting or queued."""

    def test_an_active_head_at_its_count_is_marked_over_with_the_reason(self):
        fam = family(roster(20, 20), [entry(7, "blackrock-depths", 20, "active", 0)])
        self.assertTrue(fam["campaign"]["over"])
        self.assertFalse(says_starting(fam["queue"]))
        head = fam["queue"]["entries"][0]
        self.assertEqual(campaignqueue.OVER, head["state"])
        self.assertEqual("every run wanted is done (20 of 20)", head["ended"])

    def test_an_over_head_with_an_entry_behind_it_names_what_is_next(self):
        fam = family(
            roster(20, 20),
            [
                entry(7, "blackrock-depths", 20, "active", 0),
                entry(8, "scholomance", 5, "queued", 1),
            ],
        )
        self.assertIn("moves on to Scholomance, 5 runs", fam["campaign"]["means"])
        self.assertNotIn("no other run will start", fam["campaign"]["means"])
        states = [e["state"] for e in fam["queue"]["entries"]]
        self.assertEqual([campaignqueue.OVER, campaignqueue.WAITING], states)

    def test_a_running_head_is_not_marked_ended(self):
        fam = family(roster(3, 20), [entry(7, "blackrock-depths", 20, "active", 0)])
        head = fam["queue"]["entries"][0]
        self.assertEqual(campaignqueue.RUNNING, head["state"])
        self.assertEqual("", head["ended"])


def cases() -> tuple:
    """(name, roster rows, queue rows, the state both sections must carry)."""
    return (
        (
            "running",
            roster(3, 20),
            [entry(7, "blackrock-depths", 20, "active", 0)],
            campaignqueue.RUNNING,
        ),
        (
            "over",
            roster(20, 20),
            [entry(7, "blackrock-depths", 20, "active", 0)],
            campaignqueue.OVER,
        ),
        (
            "over, nothing queued",
            roster(20, 20),
            [],
            campaignqueue.OVER,
        ),
        (
            "cancelled",
            roster(3, 20),
            [entry(7, "blackrock-depths", 20, "cancelled", 0)],
            campaignqueue.RUNNING,
        ),
        (
            "cancelled after its count",
            roster(20, 20),
            [entry(7, "blackrock-depths", 20, "cancelled", 0)],
            campaignqueue.OVER,
        ),
        (
            "never started",
            roster(0, 30, job="quest"),
            [entry(7, "blackrock-depths", 20, "queued", 0)],
            campaignqueue.STARTING,
        ),
        (
            "stopped",
            roster(0, 0, job="quest"),
            [],
            campaignqueue.STOPPED,
        ),
    )


class TheTwoSectionsAgreeInEveryState(unittest.TestCase):
    """Running, over, cancelled and never started: one function, one answer."""

    def test_the_sections_carry_one_state(self):
        for name, roster_rows, queue_rows, want in cases():
            with self.subTest(name):
                fam = family(roster_rows, queue_rows)
                self.assertEqual(want, fam["campaign"]["state"])
                self.assertEqual(want, fam["queue"]["state"])

    def test_over_and_starting_are_never_said_together(self):
        for name, roster_rows, queue_rows, _want in cases():
            with self.subTest(name):
                fam = family(roster_rows, queue_rows)
                self.assertFalse(
                    fam["campaign"]["over"] and says_starting(fam["queue"]),
                    "%s / %s" % (fam["campaign"]["means"], fam["queue"]["line"]),
                )

    def test_a_cancelled_entry_is_not_drawn_in_the_queue(self):
        fam = family(roster(3, 20), [entry(7, "blackrock-depths", 20, "cancelled", 0)])
        self.assertEqual([], fam["queue"]["entries"])
        self.assertIn("nothing is queued", fam["queue"]["line"])


class TheStateItself(unittest.TestCase):
    """campaignqueue.campaign_state, the function both sections read."""

    def counter(self, done: int, wanted: int) -> dict:
        return agenda.campaign(roster(done, wanted))

    def test_pending_rows_decide_before_the_counter(self):
        state = campaignqueue.campaign_state(
            [entry(7, "scholomance", 5, "queued", 0)], self.counter(20, 20)
        )
        self.assertEqual(campaignqueue.STARTING, state["state"])
        self.assertEqual("Scholomance", state["place"])
        self.assertEqual(5, state["runs"])

    def test_an_active_head_runs_until_the_leaders_count_reaches_it(self):
        rows = [entry(7, "scholomance", 5, "active", 0)]
        self.assertEqual(
            campaignqueue.RUNNING,
            campaignqueue.campaign_state(rows, self.counter(4, 5))["state"],
        )
        self.assertEqual(
            campaignqueue.OVER,
            campaignqueue.campaign_state(rows, self.counter(5, 5))["state"],
        )

    def test_an_unread_count_is_running_not_over(self):
        state = campaignqueue.campaign_state(
            [entry(7, "scholomance", 5, "active", 0)], None
        )
        self.assertEqual(campaignqueue.RUNNING, state["state"])

    def test_nobody_on_the_roster_and_nothing_queued_never_started(self):
        state = campaignqueue.campaign_state([], agenda.campaign([]))
        self.assertEqual(campaignqueue.NEVER_STARTED, state["state"])

    def test_the_queue_view_alone_reads_the_same_state(self):
        """The Now page's queue view (campaignqueue.views) takes no counter
        dict, only the leader's count, and still marks an over head."""
        view = campaignqueue.view([entry(7, "scholomance", 5, "active", 0)], 5, "Grug")
        self.assertEqual(campaignqueue.OVER, view["state"])
        self.assertEqual(campaignqueue.OVER, view["entries"][0]["state"])


if __name__ == "__main__":
    unittest.main()
