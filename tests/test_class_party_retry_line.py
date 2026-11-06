"""The class party's retry lines are written after the retry has run, and a
retry that succeeds writes its own line (#1332).

A line written before the retry proves only that a retry was due. A live
check reading the bridge log needs the line that says what the retry did.
"""

import logging
import unittest

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import classparty
    import guildroute
    from test_classparty import FORMED, _Bridge, a_run, answer, drive
    from test_guildsocial_bridge import bridge

HELD = guildroute.WalkAnswer(
    guildroute.ENDED,
    "Bigzug cannot walk to the Lizard: character is held by another verb",
)
HERE = guildroute.WalkAnswer(guildroute.ARRIVED, "here")


class _Timeline(logging.Handler):
    """Puts each class party log line on the bridge's shared timeline."""

    def __init__(self, events):
        super().__init__(logging.INFO)
        self.events = events

    def emit(self, record):
        message = record.getMessage()
        if message.startswith("class party:"):
            self.events.append(("log", message))


class _RetryBridge(_Bridge):
    """A bridge whose meeting walks answer from a per-member script, and which
    records each walk and each class party log line on one timeline."""

    def __init__(self, answers, rounds):
        super().__init__(answers)
        self.rounds = {name: list(script) for name, script in rounds.items()}
        self.events = []

    async def _follow_guild_walk(self, label, holder, row_id, cap, insert, goal):
        if not self.commands.get(row_id, "").startswith(classparty.MEET):
            return self.walk_answer, row_id
        script = self.rounds.get(holder) or [HERE]
        got = script.pop(0) if len(script) > 1 else script[0]
        self.events.append(("walk", holder))
        return got, row_id

    async def _await_corps_answer(self, row_id, seconds):
        got = await super()._await_corps_answer(row_id, seconds)
        if self.commands.get(row_id, "").startswith(classparty.UP):
            self.events.append(("invite", row_id))
        return got


def _run(this, run):
    handler = _Timeline(this.events)
    bridge.log.addHandler(handler)
    level = bridge.log.level
    bridge.log.setLevel(logging.INFO)
    try:
        drive(this, run)
    finally:
        bridge.log.removeHandler(handler)
        bridge.log.setLevel(level)


def _lines(this, needle):
    return [
        i
        for i, (kind, what) in enumerate(this.events)
        if kind == "log" and needle in what
    ]


def _walks(this):
    return [i for i, (kind, _) in enumerate(this.events) if kind == "walk"]


class TheHeldMeetingRetryLine(unittest.TestCase):
    def setUp(self):
        self.this = _RetryBridge(
            [FORMED, answer("applied", phase="ended")], {"Bigzug": [HELD, HERE]}
        )
        _run(self.this, a_run(meeting=True))

    def test_the_meeting_is_walked_twice_and_the_party_forms(self):
        self.assertEqual(len(_walks(self.this)), 6)
        self.assertIn(classparty.MEET_HELD_WAIT_SECONDS, self.this.slept)
        self.assertEqual(self.this.settled, [(1, True, False)])

    def test_the_retry_line_follows_the_retried_walks(self):
        (line,) = _lines(self.this, "walked again after waiting out Bigzug")
        self.assertGreater(line, max(_walks(self.this)))
        message = self.this.events[line][1]
        self.assertIn("walk 1 of %d" % classparty.MEET_HELD_RETRIES, message)
        self.assertTrue(message.endswith(": met"), message)

    def test_nothing_about_the_retry_is_logged_before_it_runs(self):
        second_round_start = _walks(self.this)[3]
        before = [
            what
            for kind, what in self.this.events[:second_round_start]
            if kind == "log" and "waits out" in what
        ]
        self.assertEqual(before, [])

    def test_a_met_retry_has_its_own_line_naming_the_party(self):
        (line,) = _lines(self.this, "met on retry")
        self.assertEqual(
            self.this.events[line][1],
            "class party: the meeting for Bigzug's Group Job met on retry 1 of %d"
            % classparty.MEET_HELD_RETRIES,
        )
        self.assertGreater(line, max(_walks(self.this)))

    def test_the_lines_are_written_from_one_format_each(self):
        self.assertIn("%s", bridge.CLASS_PARTY_MEET_RETRY_LINE)
        self.assertIn("met on retry", bridge.CLASS_PARTY_MEET_RETRY_MET_LINE)


class AMeetingWithNoRetry(unittest.TestCase):
    def test_writes_no_retry_lines(self):
        this = _RetryBridge([FORMED, answer("applied", phase="ended")], {})
        _run(this, a_run(meeting=True))
        self.assertEqual(_lines(this, "walked again"), [])
        self.assertEqual(_lines(this, "met on retry"), [])


class TheLeaderBusyRetryLine(unittest.TestCase):
    def test_the_invite_retry_line_follows_the_rewritten_invite(self):
        busy = answer(
            "error", "the leader is in combat", "refused", "refused: see result"
        )
        this = _RetryBridge([busy, FORMED, answer("applied", phase="ended")], {})
        _run(this, a_run())
        invites = [i for i, (kind, _) in enumerate(this.events) if kind == "invite"]
        self.assertEqual(len(invites), 2)
        (line,) = _lines(this, "was written again after Bigzug fought")
        self.assertGreater(line, invites[1])
        self.assertIn(
            "(1 of %d)" % classparty.LEADER_BUSY_RETRIES, this.events[line][1]
        )
        (formed,) = _lines(this, "formed on retry")
        self.assertEqual(
            this.events[formed][1],
            "class party: the invite for Bigzug's Group Job formed on retry 1 of %d"
            % classparty.LEADER_BUSY_RETRIES,
        )
        self.assertGreater(formed, invites[1])


if __name__ == "__main__":
    unittest.main()
