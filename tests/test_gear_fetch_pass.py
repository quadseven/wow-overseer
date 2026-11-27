"""The bridge's gear fetch pass walks two guild bots to one mailbox (#2503).

gearfetch.plan (tests/test_gearfetch.py) decides which waiting routes become
meetings. These tests drive the bridge's side: the waiting routes it hands the
planner, the snapshot and spawn rows it turns into the planner's inputs, the
two walk rows a meeting writes, and the one routing pass it runs once both
members stand at the mailbox. The reads and writes are stubbed; no travel aim
or town slot is ever touched.
"""

import asyncio
import inspect
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import deathcells
    import gearfetch as gf
    import gearrouting as gr
    import gearroutingexec as gx
    import guildroute
    import keep
    from test_guildsocial_bridge import bridge


def route(holder="Cowpoke", wearer="Bigmon", guid=501, gain=0.4):
    return gr.Route(
        wearer=wearer,
        holder=holder,
        guid=guid,
        entry=7001,
        item="Fez",
        slot="head",
        worn="Rags",
        worn_entry=1,
        gain=gain,
        reason="beats worn",
    )


APART = "Fez stays with Cowpoke: beside none of Bigmon" + gx.APART_NO_MAILBOX


def waiting(r, why=APART, status=gx.WAITING):
    return gx.Step(r, status, why)


def snapshot(name, x, y=0.0, **kw):
    row = {
        "name": name,
        "map_id": 0,
        "instance_id": 0,
        "pos_x": x,
        "pos_y": y,
        "in_combat": 0,
    }
    row.update(kw)
    return row


CMD = "walk-to-spawn gameobject:77 max:%d stay:%d" % (
    int(gf.MEET_YARDS),
    gf.MEET_STAY_SECONDS,
)


class TheRoutesHandedToThePlanner(unittest.TestCase):
    def test_only_routes_waiting_apart_with_no_mailbox_best_gain_first(self):
        low, high = route(guid=1, gain=0.1), route(guid=2, gain=0.9)
        steps = (
            waiting(low),
            waiting(
                route(guid=3), why="Fez stays with Cowpoke: Bigmon's bags are full"
            ),
            waiting(route(holder=gr.BANK_HOLDER, guid=4)),
            gx.Step(route(guid=5), gx.WRITTEN),
            waiting(high),
        )
        got = gf.candidates(gx.Result(steps=steps))
        self.assertEqual([r.guid for r in got], [2, 1])

    def test_no_result_is_no_route(self):
        self.assertEqual(gf.candidates(gx.Result()), [])


class TheRowsTurnedIntoPlannerInputs(unittest.TestCase):
    def test_a_snapshot_row_is_a_member(self):
        got = gf.members_from(
            [
                snapshot("Cowpoke", 200.0, in_combat=1),
                snapshot("Grug", 5.0, instance_id=9),
            ],
            roster={"Grug"},
            family_of={"Grug": "grug"},
        )
        self.assertEqual(
            got["Cowpoke"], gf.Member("Cowpoke", 0, 200.0, 0.0, in_combat=True)
        )
        self.assertEqual(
            got["Grug"],
            gf.Member(
                "Grug", 0, 5.0, 0.0, in_instance=True, roster=True, family="grug"
            ),
        )

    def test_a_character_with_no_row_is_not_a_member(self):
        self.assertEqual(gf.members_from([{"name": ""}, {}]), {})

    def test_mailbox_rows_name_each_spawn_once(self):
        rows = [
            {"spawn": 77, "map_id": 0, "x": 100.0, "y": 0.0},
            {"spawn": 77, "map_id": 0, "x": 100.0, "y": 0.0},
            {"spawn": None, "map_id": 0, "x": 1.0, "y": 1.0},
        ]
        self.assertEqual(gf.mailboxes_from(rows), [gf.Mailbox(0, 77, 100.0, 0.0)])

    def test_a_death_disc_is_the_planners_tuple(self):
        disc = deathcells.Disc(0, 100.0, 0.0, 30.0, "fall", 3)
        self.assertEqual(gf.disc_tuples([disc]), [(0, 100.0, 0.0, 30.0)])


class _Fetcher:
    """The Bridge's gear fetch methods, with the walks and reruns recorded."""

    _gear_fetch_pass = bridge.Bridge._gear_fetch_pass
    _start_gear_fetch = bridge.Bridge._start_gear_fetch
    _gear_fetch_meet = bridge.Bridge._gear_fetch_meet
    _gear_fetch_walk = bridge.Bridge._gear_fetch_walk

    def __init__(self, answers=None, busy=(), held=()):
        self._gear_fetch_walks = {}
        self._gear_fetch_tasks = set()
        self._gear_fetch_starts = []
        self.answers = dict(answers or {})
        self.busy = set(busy)
        self.held = set(held)
        self.reruns = []
        self.walking_while_rerun = []
        self.followed = []

    def _guild_walkers_busy(self, now):
        return set(self.busy)

    async def _operator_held(self, keys, writer):
        return {k for k in keys if k in self.held}

    async def _follow_guild_walk(self, label, holder, row_id, cap, insert, goal):
        self.followed.append((label, holder, cap, goal))
        await asyncio.sleep(0)
        state = self.answers.get(holder, guildroute.ARRIVED)
        return guildroute.WalkAnswer(state, "%s: %s" % (holder, state)), row_id

    async def _gear_routing_once(self, fetch=True):
        self.reruns.append(fetch)
        self.walking_while_rerun.append(set(self._gear_fetch_walks))

    async def _claim_town_slot(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("a gear fetch never takes the town slot")


def run_pass(this, steps, snapshots, mailboxes, roster=(), discs=(), today=0):
    rows = []

    def insert(holder, row):
        rows.append((holder, row.kind, row.command, row.source))
        return 100 + len(rows)

    stubs = dict(
        _roster_cohort_rows=lambda: [{"name": n, "family": f} for n, f in roster],
        _gear_fetch_member_rows=lambda names: [
            r for r in snapshots if r["name"] in names
        ],
        _gear_fetch_mailbox_rows=lambda wearers: list(mailboxes),
        _fetch_death_discs=lambda: list(discs),
        _gear_fetch_rows_today=lambda: today,
        _insert_corps_row=insert,
        _KEEP=mock.Mock(now=lambda: keep.Reservations()),
    )

    async def go():
        await this._gear_fetch_pass(gx.Result(steps=tuple(steps)))
        if this._gear_fetch_tasks:
            await asyncio.gather(*list(this._gear_fetch_tasks))

    with mock.patch.multiple(bridge, **stubs):
        asyncio.run(go())
    return rows


BOX_ROW = {"spawn": 77, "map_id": 0, "x": 100.0, "y": 0.0}
PAIR = [snapshot("Cowpoke", 200.0), snapshot("Bigmon", 120.0)]


class TheMeeting(unittest.TestCase):
    def test_both_bots_walk_to_the_mailbox_and_the_routing_pass_runs_once(self):
        this = _Fetcher()
        with self.assertLogs(bridge.log, "INFO") as said:
            rows = run_pass(this, [waiting(route())], PAIR, [BOX_ROW])
        self.assertEqual(
            rows,
            [
                ("Cowpoke", "job", CMD, bridge.GEAR_FETCH_SOURCE),
                ("Bigmon", "job", CMD, bridge.GEAR_FETCH_SOURCE),
            ],
        )
        self.assertEqual(
            [(h, cap, goal) for _l, h, cap, goal in this.followed],
            [
                ("Cowpoke", gf.MEET_YARDS, "mailbox 77"),
                ("Bigmon", gf.MEET_YARDS, "mailbox 77"),
            ],
        )
        # The re-run plans no fetch of its own, and both are still held busy
        # while it writes the trade.
        self.assertEqual(this.reruns, [False])
        self.assertEqual(this.walking_while_rerun, [{"Cowpoke", "Bigmon"}])
        self.assertEqual(this._gear_fetch_walks, {})
        self.assertEqual(len(this._gear_fetch_starts), 1)
        self.assertTrue(any("meet at mailbox 77" in line for line in said.output))
        self.assertTrue(any("stand at mailbox 77" in line for line in said.output))

    def test_a_member_that_does_not_arrive_runs_no_routing_pass(self):
        this = _Fetcher(answers={"Bigmon": guildroute.ENDED})
        with self.assertLogs(bridge.log, "INFO") as said:
            rows = run_pass(this, [waiting(route())], PAIR, [BOX_ROW])
        self.assertEqual(len(rows), 2)
        self.assertEqual(this.reruns, [])
        self.assertEqual(this._gear_fetch_walks, {})
        self.assertTrue(
            any("did not both reach mailbox 77" in line for line in said.output)
        )

    def test_a_busy_member_is_not_walked_and_the_refusal_is_logged(self):
        this = _Fetcher(busy={"Bigmon"})
        with self.assertLogs(bridge.log, "INFO") as said:
            rows = run_pass(this, [waiting(route())], PAIR, [BOX_ROW])
        self.assertEqual(rows, [])
        self.assertEqual(this.reruns, [])
        self.assertTrue(any("another walk" in line for line in said.output))

    def test_a_family_wearer_is_left_to_the_mail_run(self):
        this = _Fetcher()
        rows = run_pass(
            this, [waiting(route())], PAIR, [BOX_ROW], roster=[("Bigmon", "bigmon")]
        )
        self.assertEqual(rows, [])
        self.assertEqual(this.reruns, [])

    def test_a_mailbox_in_a_death_disc_is_refused(self):
        this = _Fetcher()
        disc = deathcells.Disc(0, 100.0, 0.0, 30.0, "fall", 3)
        rows = run_pass(this, [waiting(route())], PAIR, [BOX_ROW], discs=[disc])
        self.assertEqual(rows, [])

    def test_the_days_rows_bound_the_fetches(self):
        this = _Fetcher()
        rows = run_pass(this, [waiting(route())], PAIR, [BOX_ROW], today=2 * gf.PER_DAY)
        self.assertEqual(rows, [])

    def test_a_route_waiting_on_anything_else_reads_nothing(self):
        this = _Fetcher()
        with mock.patch.object(bridge, "_gear_fetch_member_rows") as read:
            rows = run_pass(
                this, [waiting(route(), why="bags are full")], PAIR, [BOX_ROW]
            )
        self.assertEqual(rows, [])
        read.assert_not_called()


class TheRoutingPassCallsIt(unittest.TestCase):
    def test_the_pass_runs_after_the_walks_and_not_from_its_own_rerun(self):
        body = inspect.getsource(bridge.Bridge._gear_routing_once)
        walks = body.index("await self._gear_routing_walks(result, world)")
        fetch = body.index("await self._gear_fetch_pass(result)")
        self.assertLess(walks, fetch)
        self.assertIn("if GEAR_FETCH and fetch:", body)

    def test_the_pass_writes_no_travel_aim(self):
        for method in (
            bridge.Bridge._gear_fetch_pass,
            bridge.Bridge._gear_fetch_meet,
            bridge.Bridge._gear_fetch_walk,
        ):
            body = inspect.getsource(method)
            for word in ("_claim_town_slot", "travel_aim", "_write_travel"):
                with self.subTest(method=method.__name__, word=word):
                    self.assertNotIn(word, body)


if __name__ == "__main__":
    unittest.main()
