"""A seated death party is walked, formed and ended, and its ask released (#2277).

WHY THIS EXISTS. The death-party planner (deathparty.py) seats a filled
deathloop ask on the bridge's StartBook, and nothing acted on a seated
start: no party ever formed, so the looper died again alone. This is the
runner at that seam: one task per seated start walks the helper to the
leader's meeting place (the loop place), sees both stand there, forms
the two-member party with the party-up row, keeps it formed while the
leader stays in its loop place, then disbands it. Before each act the
start is re-checked with deathparty.start_still_valid against the
newest reads, and however the party ends the ask is released from the
book and both members are free again. The bridge's writes and reads are
stubbed here the way the class party runner's tests stub them
(test_classparty.py); no level, gear or skill is granted anywhere.
"""

import asyncio
import json
import logging
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import deathparty
    import guildroute
    from test_deathask import loop_of
    from test_guildsocial_bridge import bridge


def start():
    return deathparty.PartyStart(
        ask_id=9,
        leader="Looper",
        helpers=("Helper",),
        place=loop_of().place,
        answers={"Helper": 31},
    )


FORMED = {
    "status": "applied",
    "detail": "",
    "result": json.dumps({"phase": "formed"}),
}
ENDED = {"status": "applied", "detail": "", "result": "{}"}
THERE = (0, 100.0, 200.0)
BESIDE = (0, 110.0, 200.0)


class _Bridge:
    """The Bridge death-party methods, with the writes and reads stubbed."""

    def __init__(self, answers=(), reads=(), stands=None, walk=None):
        self._death_book = deathparty.StartBook()
        self._death_party_tasks = set()
        self._guild_run_names = set()
        self.rows = []
        self.commands = {}
        self.queue = list(answers)
        # (loops, free) reads, in the order the runner asks for them; the
        # last one repeats.
        self.reads = list(reads) or [({"Looper": loop_of()}, {"Looper", "Helper"})]
        self.stands = stands or {"Looper": THERE, "Helper": BESIDE}
        self.walk_answer = walk or guildroute.WalkAnswer(guildroute.ARRIVED, "arrived")
        self.slept = []

    def _guild_walk_cap(self):
        return 20000.0

    async def _await_corps_answer(self, row_id, seconds):
        return self.queue.pop(0) if self.queue else None

    async def _follow_guild_walk(self, label, holder, row_id, cap, insert, goal):
        return self.walk_answer, row_id


for _name in (
    "_begin_death_parties",
    "_start_death_party",
    "_run_death_party",
    "_death_party_still_valid",
    "_death_party_meet",
    "_death_party_meet_walk",
    "_death_party_form",
    "_death_party_watch",
    "_death_party_disband_row",
    "_death_party_close",
):
    setattr(_Bridge, _name, getattr(bridge.Bridge, _name))


def drive(this, seated):
    ids = iter(range(100, 200))

    def insert(holder, row):
        this.rows.append((holder, row.kind, row.command, row.source))
        row_id = next(ids)
        this.commands[row_id] = row.command
        return row_id

    def reads(names):
        if len(this.reads) > 1:
            return this.reads.pop(0)
        return this.reads[0]

    async def nap(seconds):
        this.slept.append(seconds)

    this._death_book.seat(seated)
    this._guild_run_names |= set(seated.names())
    with (
        mock.patch.multiple(
            bridge,
            _insert_corps_row=insert,
            _class_party_stands=lambda names: dict(this.stands),
            _death_party_reads=reads,
        ),
        mock.patch.object(bridge.asyncio, "sleep", nap),
    ):
        with _Logs() as logs:
            asyncio.run(this._run_death_party(seated))
    return logs


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    def __enter__(self):
        self.old = bridge.log.level
        bridge.log.addHandler(self)
        bridge.log.setLevel(logging.INFO)
        return self

    def __exit__(self, *exc):
        bridge.log.removeHandler(self)
        bridge.log.setLevel(self.old)
        return False


class TheDeathPartyRunner(unittest.TestCase):
    def test_a_seated_start_is_walked_formed_ended_and_released(self):
        this = _Bridge(
            answers=[FORMED, ENDED],
            reads=[
                ({"Looper": loop_of()}, {"Looper", "Helper"}),
                ({"Looper": loop_of()}, {"Looper", "Helper"}),
                ({}, {"Looper", "Helper"}),
            ],
        )
        logs = drive(this, start())
        self.assertEqual(
            this.rows,
            [
                ("Helper", "job", "walk-to-member Looper", "deathparty"),
                ("Looper", "guild", "party-up Helper", "classask"),
                ("Looper", "guild", "party-disband", "classask"),
            ],
        )
        self.assertIn(
            "death party: ask 9 formed: Looper leads, Helper helps at %s"
            % loop_of().place,
            logs.lines,
        )
        ended = [line for line in logs.lines if "ask 9 ended:" in line]
        self.assertEqual(len(ended), 1)
        self.assertEqual(this._death_book.seated(), ())
        self.assertEqual(this._guild_run_names, set())

    def test_a_helper_that_never_arrives_forms_no_party_and_releases(self):
        this = _Bridge(
            walk=guildroute.WalkAnswer(guildroute.ENDED, "the walk ended"),
        )
        logs = drive(this, start())
        self.assertEqual([r for r in this.rows if r[2].startswith("party-up")], [])
        ended = [line for line in logs.lines if "ask 9 ended:" in line]
        self.assertEqual(len(ended), 1)
        self.assertIn("the meeting failed", ended[0])
        self.assertEqual(this._death_book.seated(), ())
        self.assertEqual(this._guild_run_names, set())

    def test_a_start_that_no_longer_holds_is_not_acted_on(self):
        this = _Bridge(reads=[({}, {"Looper", "Helper"})])
        logs = drive(this, start())
        self.assertEqual(this.rows, [])
        ended = [line for line in logs.lines if "ask 9 ended:" in line]
        self.assertEqual(len(ended), 1)
        self.assertIn("no longer holds", ended[0])
        self.assertEqual(this._death_book.seated(), ())
        self.assertEqual(this._guild_run_names, set())


if __name__ == "__main__":
    unittest.main()
