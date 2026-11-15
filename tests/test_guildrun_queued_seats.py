"""A seat that sits in a battleground queue is not proposed for a run (#2654).

The module refuses a run over one named member waiting in a battleground
queue, and no verb leaves a queue (the module has no `bg-leave`, and the
playerbots `bg leave` action reads a value only its own join sets). A queue
the pvp rung opened before levelling came first therefore stays until the
worldserver restarts, and each such seat cost one refused run a minute long.
These pin the pure read of the module's own queue answers that benches those
seats before a run is proposed, the proposal seam that honours it, and the
wiring in the bridge as source.
"""

import pathlib
import unittest

import guildrun
import pvpgear

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def answer(name, level, age, verb="bg-queue", said="queued"):
    return {
        "name": name,
        "level": level,
        "verb": verb,
        "answer": said,
        "age_minutes": age,
    }


def member(name, level=45):
    return guildrun.Member(name=name, guild="Bonkers", level=level, class_id=1)


class QueuedSeats(unittest.TestCase):
    def test_a_seat_below_the_cap_queued_since_the_start_is_held(self):
        # Worldserver up 175 minutes; queued 168 minutes ago, after the start.
        held = guildrun.queued_seats([answer("Gnarlytusk", 51, 168)], 175)
        self.assertEqual({"Gnarlytusk"}, held)

    def test_a_queue_from_before_the_restart_is_gone(self):
        held = guildrun.queued_seats([answer("Cooltusk", 50, 300)], 175)
        self.assertEqual(set(), held)

    def test_already_in_the_queue_is_held_like_queued(self):
        held = guildrun.queued_seats([answer("Cooltusk", 50, 30, said="already")], 175)
        self.assertEqual({"Cooltusk"}, held)

    def test_a_seat_at_the_cap_is_held_only_while_its_row_is_fresh(self):
        fresh = guildrun.queued_seats([answer("Bongo", 60, 30)], 600)
        stale = guildrun.queued_seats([answer("Bongo", 60, 90)], 600)
        self.assertEqual({"Bongo"}, fresh)
        self.assertEqual(set(), stale)

    def test_an_accepted_leave_newer_than_the_queue_frees_the_seat(self):
        rows = [
            answer("Dunga", 46, 10, verb="bg-leave", said="left"),
            answer("Dunga", 46, 120),
        ]
        self.assertEqual(set(), guildrun.queued_seats(rows, 175))

    def test_a_refused_or_failed_row_says_nothing_about_the_queue(self):
        rows = [
            answer("Dunga", 46, 5, said="refused"),
            answer("Dunga", 46, 4, verb="bg-leave", said="refused"),
            answer("Dunga", 46, 120),
        ]
        self.assertEqual({"Dunga"}, guildrun.queued_seats(rows, 175))

    def test_the_newest_answer_decides_when_the_rows_are_not_in_order(self):
        rows = [
            answer("Dunga", 46, 120),
            answer("Dunga", 46, 10, verb="bg-leave", said="left"),
        ]
        self.assertEqual(set(), guildrun.queued_seats(rows, 175))

    def test_an_unread_uptime_holds_for_the_lookback_and_no_longer(self):
        within = guildrun.queued_seats([answer("Ghoulia", 58, 600)], None)
        beyond = guildrun.queued_seats(
            [answer("Ghoulia", 58, guildrun.QUEUED_LOOKBACK_HOURS * 60 + 1)], None
        )
        self.assertEqual({"Ghoulia"}, within)
        self.assertEqual(set(), beyond)

    def test_an_unread_level_reads_as_fresh_rows_only(self):
        held = guildrun.queued_seats([answer("Bongo", None, 90)], 600)
        self.assertEqual(set(), held)

    def test_no_rows_hold_nobody(self):
        self.assertEqual(set(), guildrun.queued_seats([], 175))
        self.assertEqual(set(), guildrun.queued_seats(None, None))

    def test_the_fresh_window_is_the_pvp_rungs_waiting_bound(self):
        self.assertEqual(pvpgear.WAITING_MINUTES, guildrun.QUEUED_FRESH_MINUTES)
        self.assertEqual(pvpgear.LEVEL_CAP, guildrun.QUEUED_LEVEL_CAP)


class TheProposalSeam(unittest.TestCase):
    def test_a_queued_seat_is_named_as_refused_and_never_picked(self):
        held = guildrun.queued_seats([answer("Gnarlytusk", 51, 168)], 175)
        why = guildrun.why_not(
            member("Gnarlytusk", 51), set(), set(), set(), benched=frozenset(held)
        )
        self.assertEqual("refused a run just now", why)
        self.assertEqual(
            "", guildrun.why_not(member("Auren"), set(), set(), set(), frozenset(held))
        )


class TheWiring(unittest.TestCase):
    def test_the_formation_facts_bench_the_queued_seats(self):
        start = BRIDGE.index("def _fetch_guild_run_facts")
        body = BRIDGE[start : BRIDGE.index("\ndef ", start + 10)]
        self.assertIn("guildrun.read_queued_seats(cur)", body)
        self.assertIn("benched = guildrun.benched(", body)
        self.assertRegex(body, r"benched\s*=\s*benched\s*\|\s*queued")

    def test_the_operator_order_facts_bench_them_too(self):
        source = (HERE / "guildrun.py").read_text(encoding="utf-8")
        start = source.index("def order_facts")
        body = source[start : source.index("\ndef ", start + 10)]
        self.assertIn("read_queued_seats(cur)", body)

    def test_the_query_reads_the_modules_answers_not_a_guess(self):
        sql = guildrun.QUEUED_SEATS_SQL
        self.assertIn("overseer_command", sql)
        self.assertIn("bg-queue", sql)
        self.assertIn("bg-leave", sql)
        self.assertIn('"outcome":"queued"', sql)


if __name__ == "__main__":
    unittest.main()
