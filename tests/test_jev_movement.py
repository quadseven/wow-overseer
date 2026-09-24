"""How a family gets moving again, chosen by Jev (jev_movement.py).

The operator: "Please use Jev for movement decisions like a human." The dev
realm's Alliance family, as read on 2026-09-23, had one member standing still
at the bottom of Un'Goro Crater 1,400 yards from the leader in Tanaris. Every
test runs on fake rows and a fake Jev transport; none touches a database or
the API.
"""

import asyncio
import pathlib
import types
import unittest

from test_campaign_queue import _load  # sets up the pymysql stub
from test_jev_items import FakeJev

import jev  # noqa: E402
import jev_movement as jm  # noqa: E402
import jevview  # noqa: E402
import situation as sit  # noqa: E402
import townslot  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

NAMES = ("Grug", "Ugga", "Grog", "Bork", "Og")
TANARIS_INN = sit.Point(1, -7159.0, -3841.0, 8.7)
IRONFORGE_INN = sit.Point(0, -4840.0, -860.0, 502.0)


def snap(name, x, y, z, **kw):
    return dict(
        name=name,
        map_id=kw.get("map_id", 1),
        zone_id=kw.get("zone", 440),
        pos_x=x,
        pos_y=y,
        pos_z=z,
        health=kw.get("health", 100),
        max_health=100,
        in_combat=kw.get("in_combat", 0),
        age=2,
    )


def where(bork=(-8182.8, -2090.9, -114.3), moving=(), deaths=None, **kw):
    """The family in Tanaris with Bork where `bork` says; everybody still
    unless named in `moving`."""
    rows = [
        snap("Grug", -6911.6, -2873.7, 9.7),
        snap("Ugga", -6911.1, -2874.7, 9.6),
        snap("Grog", -6909.5, -2874.0, 9.8),
        snap("Bork", *bork, **kw),
        snap("Og", -6915.3, -2874.0, 9.5),
    ]
    tr = sit.Tracker()
    for i in range(8):
        for r in rows:
            dx = i * 20.0 if r["name"] in moving else 0.0
            tr.record(
                r["name"],
                sit.Point(r["map_id"], r["pos_x"] + dx, r["pos_y"], r["pos_z"]),
                i * 30.0,
            )
    return sit.build(
        NAMES,
        "Grug",
        rows,
        tr,
        210.0,
        leader_travel=kw.get("travel", ""),
        death_rows=deaths if deaths is not None else [],
    )


def facts(w=None, binds=None, hearthed=(), errand="", claimant=""):
    return jm.Facts(
        family="Grug",
        where=w or where(),
        binds=dict(binds if binds is not None else {n: TANARIS_INN for n in NAMES}),
        hearthed=frozenset(hearthed),
        errand=errand,
        claimant=claimant,
    )


def ask(f, fake=None, environ=None):
    client = jev.Client("k", transport=fake or FakeJev())
    return asyncio.run(jm.ask(client, f, jm.policy(environ or {})))


DYING = [
    dict(character_name="Og", killer_type="creature", killer_name="Sandfury", age=60),
    dict(character_name="Ugga", killer_type="creature", killer_name="Sandfury", age=90),
]


class WhatIsOffered(unittest.TestCase):
    def test_a_member_stranded_in_the_crater_may_hearth(self):
        f = facts()
        self.assertEqual("Bork", jm.stranded(f))
        self.assertIn(jm.HEARTH_STRAGGLER, jm.options(f))
        self.assertIn("Bork", jm.options(f)[jm.HEARTH_STRAGGLER])

    def test_a_member_walking_back_is_not_stranded(self):
        self.assertEqual("", jm.stranded(facts(where(moving=("Bork",)))))

    def test_a_member_near_the_leader_is_not_stranded(self):
        self.assertEqual("", jm.stranded(facts(where(bork=(-6950.0, -2880.0, 9.0)))))

    def test_an_inn_farther_than_the_member_is_no_way_back(self):
        far_inn = {n: IRONFORGE_INN for n in NAMES}
        self.assertEqual("", jm.stranded(facts(binds=far_inn)))

    def test_a_hearth_used_this_hour_or_no_bind_read_is_not_offered(self):
        self.assertEqual("", jm.stranded(facts(hearthed=("Bork",))))
        self.assertEqual("", jm.stranded(facts(binds={"Grug": TANARIS_INN})))

    def test_a_dead_or_fighting_member_does_not_hearth(self):
        self.assertEqual("", jm.stranded(facts(where(health=0))))
        self.assertEqual("", jm.stranded(facts(where(in_combat=1))))

    def test_the_family_meets_at_the_inn_only_when_all_are_bound_there(self):
        self.assertTrue(jm.one_inn(facts()))
        split = {n: TANARIS_INN for n in NAMES}
        split["Og"] = IRONFORGE_INN
        self.assertFalse(jm.one_inn(facts(binds=split)))
        self.assertFalse(jm.one_inn(facts(where(moving=("Og",)))))

    def test_dropping_the_walk_needs_an_errand_this_process_wrote(self):
        self.assertNotIn(jm.DROP_ERRAND, jm.options(facts()))
        f = facts(errand="at:1:-7203.1,-3821.1,8.6", claimant="guild bank")
        self.assertIn(jm.DROP_ERRAND, jm.options(f))

    def test_carry_on_is_always_offered_and_is_the_heuristic(self):
        self.assertIn(jm.CARRY_ON, jm.options(facts()))
        self.assertEqual(jm.CARRY_ON, jm.heuristic(facts())[0])


class WhenItIsAsked(unittest.TestCase):
    def test_a_quiet_family_is_not_asked(self):
        fake = FakeJev()
        f = facts(where(bork=(-6912.0, -2874.0, 9.7)))
        self.assertEqual("", jm.trouble(f))
        self.assertIsNone(ask(f, fake))
        self.assertEqual([], fake.requests)

    def test_trouble_names_the_straggler_the_lost_leader_and_the_deaths(self):
        self.assertIn("far from the leader", jm.trouble(facts()))
        dying = facts(where(bork=(-6912.0, -2874.0, 9.7), deaths=DYING))
        self.assertIn("2 deaths", jm.trouble(dying))
        stuck = facts(
            where(bork=(-6912.0, -2874.0, 9.7), travel="at:1:-7700.0,-2873.7,9.7")
        )
        self.assertIn("the leader is stuck", jm.trouble(stuck))

    def test_off_asks_nothing(self):
        fake = FakeJev()
        self.assertIsNone(ask(facts(), fake, {"JEV_MODE_MOVEMENT": "off"}))
        self.assertEqual([], fake.requests)


class JevActs(unittest.TestCase):
    def test_a_confident_hearth_is_carried_out(self):
        fake = FakeJev(picks={"movement": jm.HEARTH_STRAGGLER}, confidence=0.8)
        j = ask(facts(), fake)
        self.assertEqual(jev.JEV, j.acted)
        self.assertEqual(jm.HEARTH_STRAGGLER, j.carried_out)
        self.assertEqual("Bork", j.straggler)
        state = fake.requests[0]["state"]
        self.assertIn("situation", state)
        self.assertIn("far from the leader", state["why_now"])

    def test_below_the_threshold_nothing_changes(self):
        fake = FakeJev(picks={"movement": jm.HEARTH_STRAGGLER}, confidence=0.7)
        j = ask(facts(), fake)
        self.assertEqual(jev.HEURISTIC, j.acted)
        self.assertEqual("", j.carried_out)

    def test_carry_on_carries_out_nothing_even_when_confident(self):
        j = ask(facts(), FakeJev(picks={"movement": jm.CARRY_ON}, confidence=0.95))
        self.assertEqual("", j.carried_out)

    def test_the_threshold_is_the_operators_to_move(self):
        fake = FakeJev(picks={"movement": jm.HEARTH_STRAGGLER}, confidence=0.7)
        j = ask(facts(), fake, {"JEV_THRESHOLD_MOVEMENT": "0.6"})
        self.assertEqual(jm.HEARTH_STRAGGLER, j.carried_out)

    def test_the_record_line_and_view_name_the_kind(self):
        j = ask(facts(), FakeJev(picks={"movement": jm.HEARTH_STRAGGLER}))
        self.assertTrue(j.line().startswith("movement: family=Grug"))
        self.assertEqual("How a family gets moving again", jevview.KINDS[jm.KIND])


class TheSlotRemembersAWalkGivenUp(unittest.TestCase):
    def test_an_abandoned_aim_is_refused_to_its_claimant(self):
        aim = "at:1:-7203.1,-3821.1,8.6"
        slot = townslot.Slot()
        slot.holder = townslot.Holder("guild bank", "Grug", aim, 0.0)
        slot.abandon("guild bank", aim, True, 100.0)
        self.assertIsNone(slot.holder)
        self.assertTrue(slot.spent("guild bank", aim, 200.0))
        again = slot.want(
            claimant="guild bank",
            character="Grug",
            aim=aim,
            leader="Grug",
            column="",
            retaskable=(),
            now=200.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, again.verdict)
        self.assertFalse(slot.spent("guild bank", aim, 100.0 + townslot.SPENT_SECONDS))


class TheBridge(unittest.TestCase):
    """_movement_due and _carry_out_movement, run on fakes."""

    def load(self):
        written = {"hearth": [], "release": []}
        ns = _load(
            ["_movement_due", "_carry_out_movement"],
            {
                "asyncio": asyncio,
                "time": __import__("time"),
                "jobs": __import__("jobs"),
                "jev_movement": jm,
                "campaignqueue": __import__("campaignqueue"),
                "log": types.SimpleNamespace(info=lambda *a: None),
                "_insert_hearth": written["hearth"].append,
                "_release_trade_errand": lambda c, a: (
                    written["release"].append((c, a)) or True
                ),
            },
        )
        me = types.SimpleNamespace(_movement_seen={})
        return ns, me, written

    def test_not_during_a_dungeon_job_or_inside_its_clocks(self):
        ns, me, _ = self.load()
        due = ns["_movement_due"]
        self.assertTrue(due(me, "Grug", "quest", 1000.0))
        self.assertFalse(due(me, "Grug", "dungeon:ragefire", 1000.0))
        me._movement_seen["Grug"] = {"asked": 900.0}
        self.assertFalse(due(me, "Grug", "quest", 1000.0))
        me._movement_seen["Grug"] = {"asked": 0.0, "acted": 900.0}
        self.assertFalse(due(me, "Grug", "quest", 1000.0))

    def test_a_hearth_is_one_row_per_member(self):
        ns, me, written = self.load()
        f = facts()
        j = ask(f, FakeJev(picks={"movement": jm.HEARTH_STRAGGLER}, confidence=0.9))
        asyncio.run(ns["_carry_out_movement"](me, "Grug", f, j, None))
        self.assertEqual(["Bork"], written["hearth"])
        j = ask(f, FakeJev(picks={"movement": jm.HEARTH_FAMILY}, confidence=0.9))
        written["hearth"].clear()
        asyncio.run(ns["_carry_out_movement"](me, "Grug", f, j, None))
        self.assertEqual(list(NAMES), written["hearth"])

    def test_dropping_the_walk_releases_the_aim_and_spends_it(self):
        ns, me, written = self.load()
        aim = "at:1:-7203.1,-3821.1,8.6"
        f = facts(errand=aim, claimant="guild bank")
        slot = townslot.Slot()
        slot.holder = townslot.Holder("guild bank", "Grug", aim, 0.0)
        j = ask(f, FakeJev(picks={"movement": jm.DROP_ERRAND}, confidence=0.9))
        asyncio.run(ns["_carry_out_movement"](me, "Grug", f, j, slot))
        self.assertEqual([("Grug", aim)], written["release"])
        self.assertIsNone(slot.holder)

    def test_the_loop_runs_in_both_lists(self):
        self.assertEqual(2, BRIDGE.count("self._movement_loop,"))
        self.assertIn("AND status <> 'error' AND created_at", BRIDGE)


if __name__ == "__main__":
    unittest.main()
