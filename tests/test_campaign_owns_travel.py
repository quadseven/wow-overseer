"""A staging campaign owns its leader's travel column (#227).

Measured on wow-dev 2026-09-23. The Horde family's Ragefire Chasm order was
active and the leader carried `job='dungeon:ragefire'`, and run 1 never
staged:

    05:13:19 town slot: clearance takes the traveller Zug from bags ...
    05:13:19 clearance: Zug hold letters for the guild; leader=Zug aimed at
             a mailbox (taken=True)
    ~05:17   overseer: dungeon run 1 defers staging because leader 'Zug' has
             outstanding travel errand 'at:1:-443.7,-2649.1,95.8'
    05:30:47 overseer: 'Zug' was sent to 'at:1:-443.7,-2649.1,95.8' and made
             no progress in 18 attempts - releasing the errand before
             upstream can teleport it
    05:30:47 overseer: travel release for 'Zug' skipped the column write -
             a profession errand (skill 186) and errand '...' are outstanding
             and this book never claimed the aim it would have erased

Pinned here against fakes:

  * While the campaign owns the leader, every town pass waits, whatever its
    lease, reservation or urgency.
  * The bridge hands back the aim a bridge pass left on the leader, and a
    trainer walk, and nothing it cannot name as its own.
  * An owner that asks for a walk which has stopped closing gives it up and
    does not ask for it again; clearance then picks another mailbox.
  * A withheld campaign, or one that is done, gets the town errands back.
"""

import ast
import asyncio
import dataclasses
import pathlib
import types
import unittest

import bag_pressure
import campaignqueue
import jev_activity
import jobs
import learnaim
import townslot
import travel

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

MAILBOX = "at:1:-443.7,-2649.1,95.8"
# The free slots after the 05:08 bag purchase: nobody is withheld.
FREE = {"Oz": 30, "Uzza": 17, "Zork": 16, "Zrog": 18, "Zug": 9}
# The free slots at 04:31, when the campaign was withheld for bag space.
FULL = {"Oz": 23, "Uzza": 10, "Zork": 6, "Zrog": 6, "Zug": 2}
NAMES = ["Oz", "Uzza", "Zork", "Zrog", "Zug"]


def economy(aim):
    return aim in ("vendor", "repair", "auctioneer") or (
        aim.startswith("at:") or aim.isdigit()
    )


def retaskable(aim):
    if aim.isdigit():
        return ("", aim, "vendor")
    return ("", aim)


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _load(names, namespace):
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102
    return namespace


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = debug = info


def _thread(fn, *a, **k):
    async def run():
        return fn(*a, **k)

    return run()


class Clock:
    def __init__(self, now=0.0):
        self.now = now

    def monotonic(self):
        return self.now


# --- the pure halves ---------------------------------------------------------


class TheRule(unittest.TestCase):
    def test_the_live_state_owns_the_leader(self):
        self.assertTrue(
            townslot.campaign_owns_traveller(
                "dungeon:ragefire", "dungeon:ragefire", False
            )
        )

    def test_a_withheld_campaign_does_not(self):
        self.assertFalse(
            townslot.campaign_owns_traveller(
                "dungeon:ragefire", "dungeon:ragefire", True
            )
        )

    def test_a_jev_interlude_does_not(self):
        """The sell interlude writes job=quest for its lease."""
        self.assertFalse(
            townslot.campaign_owns_traveller("dungeon:ragefire", "quest", False)
        )

    def test_no_active_entry_does_not(self):
        self.assertFalse(
            townslot.campaign_owns_traveller("", "dungeon:ragefire", False)
        )


def _held_by_clearance(now=0.0):
    slot = townslot.Slot(releasable=economy)
    taken = slot.want(
        claimant="clearance",
        character="Zug",
        aim=MAILBOX,
        leader="Zug",
        column="",
        retaskable=retaskable(MAILBOX),
        now=now,
    )
    slot.settle(taken, True, now)
    return slot


class EveryPassWaits(unittest.TestCase):
    def ask(self, slot, claimant, aim, column, now, urgent=False):
        return slot.want(
            claimant=claimant,
            character="Zug",
            aim=aim,
            leader="Zug",
            column=column,
            retaskable=retaskable(aim),
            now=now,
            urgent=urgent,
        )

    def test_no_pass_takes_a_free_column(self):
        slot = townslot.Slot(releasable=economy)
        slot.yield_to_campaign("dungeon:ragefire on Zug")
        for claimant, aim in (
            ("clearance", MAILBOX),
            ("bags", "3481"),
            ("economy", "vendor"),
            ("gather", "at:1:1,2,3"),
        ):
            d = self.ask(slot, claimant, aim, "", 0.0)
            self.assertEqual(townslot.SLOT_WAIT, d.verdict, claimant)
            self.assertIn("campaign owns the traveller Zug", d.reason)

    def test_urgency_and_a_reservation_do_not_cut_in(self):
        slot = townslot.Slot(releasable=economy)
        slot.reserve("bags", 0.0, "withheld")
        slot.yield_to_campaign("dungeon:ragefire on Zug")
        d = self.ask(slot, "bags", "3481", "", 10.0, urgent=True)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_the_holder_does_not_refine_or_hold_either(self):
        slot = _held_by_clearance()
        slot.yield_to_campaign("dungeon:ragefire on Zug")
        d = self.ask(slot, "clearance", MAILBOX, MAILBOX, 60.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_errands_resume_when_the_campaign_lets_go(self):
        slot = townslot.Slot(releasable=economy)
        slot.yield_to_campaign("dungeon:ragefire on Zug")
        slot.campaign_over()
        d = self.ask(slot, "clearance", MAILBOX, "", 0.0)
        self.assertEqual(townslot.SLOT_TAKE, d.verdict)


class WhatTheBridgeHandsBack(unittest.TestCase):
    def test_a_named_passes_aim(self):
        slot = _held_by_clearance()
        got = slot.campaign_release(
            leader="Zug", column=MAILBOX, now=1.0, ground=travel.is_ground_aim
        )
        self.assertEqual("clearance", got.claimant)

    def test_a_keyword_orphan_is_left_to_its_writer(self):
        """mod-overseer's town trip writes `vendor` too (wow-overseer#265):
        handed back every minute on wow-dev, the Horde head's trip restarted
        and the coordinator held the run behind each restart."""
        slot = townslot.Slot(releasable=economy)
        for now in (0.0, townslot.LEASE_SECONDS, 5000.0):
            got = slot.campaign_release(
                leader="Zug", column="vendor", now=now, ground=travel.is_ground_aim
            )
            self.assertIsNone(got, now)

    def test_a_keyword_aim_a_bridge_pass_wrote_is_still_handed_back(self):
        slot = townslot.Slot(releasable=economy)
        taken = slot.want(
            claimant="economy",
            character="Zug",
            aim="vendor",
            leader="Zug",
            column="",
            retaskable=retaskable("vendor"),
            now=0.0,
        )
        slot.settle(taken, True, 0.0)
        got = slot.campaign_release(
            leader="Zug", column="vendor", now=1.0, ground=travel.is_ground_aim
        )
        self.assertEqual("economy", got.claimant)

    def test_a_ground_orphan_only_after_a_lease_and_only_once(self):
        """After a restart the mailbox aim is an orphan; the coordinator's
        staging aims are ground aims too, so one is given the lease first."""
        slot = townslot.Slot(releasable=economy)
        ask = dict(leader="Zug", column=MAILBOX, ground=travel.is_ground_aim)
        self.assertIsNone(slot.campaign_release(now=0.0, **ask))
        got = slot.campaign_release(now=townslot.LEASE_SECONDS, **ask)
        self.assertEqual(MAILBOX, got.aim)
        slot.released_for_campaign(got, True)
        # Re-armed by whoever owned it: never handed back a second time.
        self.assertIsNone(slot.campaign_release(now=5000.0, **ask))
        self.assertIsNone(slot.campaign_release(now=9000.0, **ask))

    def test_never_an_aim_the_economy_cannot_release(self):
        slot = townslot.Slot(releasable=economy)
        got = slot.campaign_release(
            leader="Zug",
            column=learnaim.TRAINER_ROLE,
            now=5000.0,
            ground=travel.is_ground_aim,
        )
        self.assertIsNone(got)


class AWalkThatCannotLand(unittest.TestCase):
    def ask(self, slot, now, distance):
        return slot.want(
            claimant="clearance",
            character="Zug",
            aim=MAILBOX,
            leader="Zug",
            column=MAILBOX,
            retaskable=retaskable(MAILBOX),
            now=now,
            distance=distance,
        )

    def test_the_live_walk_is_given_up_and_not_asked_for_again(self):
        """726 yards out at 05:13 and at 05:18: no ground was gained."""
        slot = _held_by_clearance()
        self.assertEqual(townslot.SLOT_HOLD, self.ask(slot, 0.0, 726.0).verdict)
        d = self.ask(slot, 300.0, 726.0)
        self.assertEqual(townslot.SLOT_GIVE_UP, d.verdict)
        self.assertFalse(d.granted)
        self.assertEqual(MAILBOX, d.release.aim)
        slot.gave_up(d, True, 300.0)
        self.assertIsNone(slot.holder)
        again = self.ask(slot, 600.0, 726.0)
        self.assertEqual(townslot.SLOT_WAIT, again.verdict)
        self.assertIn("gave up", again.reason)
        self.assertTrue(slot.spent("clearance", MAILBOX, 600.0))
        self.assertFalse(
            slot.spent("clearance", MAILBOX, 300.0 + townslot.SPENT_SECONDS)
        )

    def test_a_walk_that_closes_is_kept(self):
        slot = _held_by_clearance()
        for now, yards in ((0.0, 726.0), (300.0, 500.0), (600.0, 250.0)):
            self.assertEqual(townslot.SLOT_HOLD, self.ask(slot, now, yards).verdict)

    def test_an_arrived_leader_is_kept(self):
        slot = _held_by_clearance()
        for now in (0.0, 300.0, 900.0):
            self.assertEqual(townslot.SLOT_HOLD, self.ask(slot, now, 6.0).verdict)

    def test_a_pass_that_names_no_distance_holds_as_before(self):
        slot = _held_by_clearance()
        for now in (0.0, 300.0, 900.0):
            self.assertEqual(townslot.SLOT_HOLD, self.ask(slot, now, None).verdict)


# --- the bridge, with a fake world -------------------------------------------


class FakeWorld:
    """The Horde family at 05:32: run 1 active, the mailbox aim on Zug."""

    def __init__(self, *, column=MAILBOX, free=None, job="dungeon:ragefire"):
        self.column = {"Zug": column}
        self.free = dict(FREE if free is None else free)
        self.job = job
        self.releases = []
        self.learn_releases = []
        # `bridge._TOWN_FIRST_SINCE`: when the queue first held this family.
        self.town_first_since = {}
        self.writes = []

    def pending(self):
        return {
            "Zug": [
                dict(keyword="ragefire", runs_wanted=50, status="active", id=1),
                dict(keyword="wailing", runs_wanted=50, status="queued", id=2),
            ]
        }

    def fams(self):
        return {
            "Zug": {
                "leader": dict(name="Zug", job=self.job, dungeon_runs_done=0),
                "names": list(NAMES),
            }
        }

    def current(self, name):
        return self.column.get(name, "")

    def write(self, errand):
        self.writes.append((errand.character, errand.travel_npc))
        if self.column.get(errand.character, "") not in retaskable(errand.travel_npc):
            return False
        self.column[errand.character] = errand.travel_npc
        return True

    def release(self, name, aim):
        self.releases.append((name, aim))
        if not economy(aim) or self.column.get(name) != aim:
            return False
        self.column[name] = ""
        return True

    def town_first_hold(self, names):
        """`_town_first_hold`: a campaign waits and nobody carries its job."""
        return bool(self.pending()) and not self.job.startswith("dungeon")

    def release_learn(self, name):
        self.learn_releases.append(name)
        if self.column.get(name) != learnaim.TRAINER_ROLE:
            return False
        self.column[name] = ""
        return True


def _bridge_self(world, clock, log):
    ns = _load(
        [
            "_campaign_owns_travel",
            "_staging_campaign",
            "_held_in_town",
            "_hand_back_for_campaign",
            "_claim_town_slot",
            "_cohort_town_slot",
        ],
        {
            "bag_pressure": bag_pressure,
            "_town_first_hold": world.town_first_hold,
            "_TOWN_FIRST_SINCE": world.town_first_since,
            "asyncio": types.SimpleNamespace(to_thread=_thread),
            "time": clock,
            "log": log,
            "townslot": townslot,
            "travel": travel,
            "jobs": jobs,
            "learnaim": learnaim,
            "jev_activity": jev_activity,
            "campaignqueue": campaignqueue,
            "bonds": types.SimpleNamespace(head_of_family=lambda: "Grug"),
            "professions": types.SimpleNamespace(
                Errand=lambda character, travel_npc: types.SimpleNamespace(
                    character=character, travel_npc=travel_npc
                )
            ),
            "TOWN_SLOT_LEASE_SECONDS": townslot.LEASE_SECONDS,
            "GATHER_CLAIMANT": "gather",
            "FLIGHT_CLAIMANT": "flight",
            "LEVEL_CLAIMANT": "level",
            "TOWN_SLOT_GATHER_LEASE_SECONDS": townslot.GATHER_LEASE_SECONDS,
            "TOWN_SLOT_FLIGHT_LEASE_SECONDS": townslot.GATHER_LEASE_SECONDS,
            "_is_economy_aim": economy,
            "_retaskable_from": retaskable,
            "_cohort_of": lambda name: "Grug",
            "_cohort_leader": lambda key: "Zug",
            "_head_now": lambda: "Grug",
            "_current_travel_npc": world.current,
            "_write_trade_errand": world.write,
            "_release_trade_errand": world.release,
            "_release_learn_aim": world.release_learn,
            "_fetch_free_slots": lambda names: dict(world.free),
        },
    )
    me = types.SimpleNamespace(
        _town_slot=townslot.Slot(releasable=economy), _cohort_town_slots={}
    )
    for name in (
        "_campaign_owns_travel",
        "_staging_campaign",
        "_held_in_town",
        "_hand_back_for_campaign",
        "_claim_town_slot",
        "_cohort_town_slot",
    ):
        fn = ns[name]
        setattr(me, name, lambda *a, _fn=fn, **k: _fn(me, *a, **k))
    return me


def _queue_pass(me, world):
    asyncio.run(me._campaign_owns_travel(world.pending(), world.fams()))


class TheLiveSequence(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld(column="")
        self.clock, self.log = Clock(), _Log()
        self.me = _bridge_self(self.world, self.clock, self.log)

    def clearance(self, distance=726.0):
        return asyncio.run(
            self.me._claim_town_slot(
                "clearance", "Zug", MAILBOX, cohort="Zug", distance=distance
            )
        )

    def test_the_mailbox_aim_is_handed_back_and_not_taken_again(self):
        # 05:13:19 - clearance takes Zug for the mailbox.
        self.assertTrue(self.clearance())
        self.assertEqual(MAILBOX, self.world.column["Zug"])
        # The queue pass: run 1 is active on Zug and nobody is withheld.
        self.clock.now = 60.0
        _queue_pass(self.me, self.world)
        self.assertEqual("", self.world.column["Zug"], self.log.lines)
        self.assertIn(("Zug", MAILBOX), self.world.releases)
        # 05:18 - clearance asks again and waits for the campaign.
        self.clock.now = 300.0
        self.assertFalse(self.clearance())
        self.assertEqual("", self.world.column["Zug"])
        self.assertEqual([("Zug", MAILBOX)], self.world.writes)

    def test_other_passes_wait_too(self):
        _queue_pass(self.me, self.world)
        for claimant, aim in (("bags", "3481"), ("economy", "vendor")):
            took = asyncio.run(
                self.me._claim_town_slot(claimant, "Zug", aim, cohort="Zug")
            )
            self.assertFalse(took, claimant)
        self.assertEqual([], self.world.writes)

    def test_a_trainer_walk_is_handed_back_and_the_learn_stays(self):
        self.world.column["Zug"] = learnaim.TRAINER_ROLE
        _queue_pass(self.me, self.world)
        self.assertEqual(["Zug"], self.world.learn_releases)
        self.assertEqual("", self.world.column["Zug"])

    def test_a_withheld_campaign_keeps_its_town_errands(self):
        self.world.free = dict(FULL)
        self.assertTrue(self.clearance())
        _queue_pass(self.me, self.world)
        self.assertEqual(MAILBOX, self.world.column["Zug"])
        self.assertEqual("", self.me._cohort_town_slot("Zug").campaign)

    def test_the_errands_resume_when_the_campaign_lets_go(self):
        _queue_pass(self.me, self.world)
        self.assertTrue(self.me._cohort_town_slot("Zug").campaign)
        self.world.job = "quest"
        self.clock.now = 60.0
        _queue_pass(self.me, self.world)
        self.assertEqual("", self.me._cohort_town_slot("Zug").campaign)
        self.assertTrue(self.clearance())

    def test_an_emptied_queue_lets_go_too(self):
        _queue_pass(self.me, self.world)
        asyncio.run(self.me._campaign_owns_travel({}, self.world.fams()))
        self.assertEqual("", self.me._cohort_town_slot("Zug").campaign)

    def test_after_a_restart_the_orphan_goes_once_its_lease_is_up(self):
        self.world.column["Zug"] = MAILBOX
        _queue_pass(self.me, self.world)
        self.assertEqual(MAILBOX, self.world.column["Zug"])
        self.clock.now = townslot.LEASE_SECONDS
        _queue_pass(self.me, self.world)
        self.assertEqual("", self.world.column["Zug"])

    def test_without_the_campaign_the_unreachable_mailbox_is_given_up(self):
        self.world.job = "quest"
        self.assertTrue(self.clearance(726.0))
        self.clock.now = 300.0
        self.assertTrue(self.clearance(726.0))
        self.clock.now = 600.0
        self.assertFalse(self.clearance(726.0))
        self.assertEqual("", self.world.column["Zug"])
        self.clock.now = 900.0
        self.assertFalse(self.clearance(726.0))
        self.assertEqual("", self.world.column["Zug"])


# The Horde family on 2026-09-24 at 03:55 UTC: Ragefire held "town first", the
# Jev sell interlude on (job=quest), and a trainer walk on the leader.
TOWN_FIRST = {"Oz": 4, "Uzza": 6, "Zork": 4, "Zrog": 6, "Zug": 4}


class ACampaignHeldInTownSells(unittest.TestCase):
    """#297: the trainer walk yields to the town trip the hold asks for."""

    def setUp(self):
        self.world = FakeWorld(
            column=learnaim.TRAINER_ROLE, free=TOWN_FIRST, job="quest"
        )
        self.clock, self.log = Clock(), _Log()
        self.me = _bridge_self(self.world, self.clock, self.log)

    def economy(self):
        return asyncio.run(
            self.me._claim_town_slot(
                "economy", "Zug", "vendor", urgent=True, cohort="Zug"
            )
        )

    def test_the_trainer_walk_is_handed_back_and_the_vendor_trip_taken(self):
        # Before the queue pass the economy waits behind the trainer walk,
        # exactly as the live log said it did every cycle.
        self.assertFalse(self.economy())
        self.assertIn(
            "not an errand the economy may hand back", "\n".join(self.log.lines)
        )
        _queue_pass(self.me, self.world)
        self.assertEqual(["Zug"], self.world.learn_releases)
        self.assertTrue(self.me._cohort_town_slot("Zug").town_first)
        self.assertEqual("", self.me._cohort_town_slot("Zug").campaign)
        self.assertTrue(self.economy())
        self.assertEqual("vendor", self.world.column["Zug"])

    def test_the_learn_trips_wait_while_the_hold_lasts(self):
        _queue_pass(self.me, self.world)
        self.assertTrue(self.me._cohort_town_slot("Zug").learn_waits)

    def test_room_enough_lets_the_learn_trips_go_again(self):
        _queue_pass(self.me, self.world)
        self.world.free = dict(FREE)
        self.clock.now = 60.0
        _queue_pass(self.me, self.world)
        slot = self.me._cohort_town_slot("Zug")
        self.assertEqual("", slot.town_first)
        self.assertEqual("", slot.learn_waits)

    def test_the_hold_ends_at_the_campaigns_resume_ceiling(self):
        """Past the ceiling the queue sends the run in whoever is short, so
        the learn trips must not wait on after it."""
        self.world.town_first_since[tuple(sorted(NAMES))] = 0.0
        self.clock.now = bag_pressure.CAMPAIGN_RESUME_CEILING_SECONDS - 60.0
        _queue_pass(self.me, self.world)
        self.assertTrue(self.me._cohort_town_slot("Zug").town_first)
        self.clock.now = bag_pressure.CAMPAIGN_RESUME_CEILING_SECONDS
        _queue_pass(self.me, self.world)
        self.assertEqual("", self.me._cohort_town_slot("Zug").town_first)

    def test_a_family_with_room_keeps_its_trainer_walk(self):
        self.world.free = dict(FREE)
        _queue_pass(self.me, self.world)
        self.assertEqual([], self.world.learn_releases)
        self.assertEqual(learnaim.TRAINER_ROLE, self.world.column["Zug"])

    def test_a_staging_campaign_is_not_a_town_hold(self):
        self.world.job = "dungeon:ragefire"
        self.world.free = dict(FREE)
        _queue_pass(self.me, self.world)
        slot = self.me._cohort_town_slot("Zug")
        self.assertEqual("", slot.town_first)
        self.assertTrue(slot.campaign)


class ClearancePicksAnotherMailbox(unittest.TestCase):
    def test_a_spent_mailbox_is_skipped(self):
        crossroads = dict(map_id=1, x=-443.7, y=-2649.1, z=95.8, d2=726.0**2)
        other = dict(map_id=1, x=-400.0, y=-2600.0, z=92.0, d2=800.0**2)
        slot = townslot.Slot(releasable=economy)
        slot._spent[("clearance", MAILBOX)] = 0.0
        claims = []
        me = types.SimpleNamespace(_cohort_town_slot=lambda cohort=None: slot)

        async def claim(claimant, leader, aim, **kw):
            claims.append((aim, kw.get("distance")))
            return True

        me._claim_town_slot = claim

        def nearest(name, skip=None):
            return next((r for r in (crossroads, other) if not skip(r)), None)

        ns = _load(
            ["_walk_to_post", "_spawn_yards"],
            {
                "asyncio": types.SimpleNamespace(to_thread=_thread),
                "time": Clock(10.0),
                "log": _Log(),
                "travel": travel,
                "_fetch_positions": lambda names: {"Zug": dict(map_id=1)},
                "_holders_at_mailbox": lambda names, positions: set(),
                "_nearest_mailbox": nearest,
            },
        )
        asyncio.run(ns["_walk_to_post"](me, {"Zork"}, "Zug", "Zug"))
        self.assertEqual(1, len(claims))
        aim, yards = claims[0]
        self.assertNotEqual(MAILBOX, aim)
        self.assertAlmostEqual(800.0, yards)


class TheLearnTripsWait(unittest.TestCase):
    def run_pass(self, campaign, town_first=False):
        slot = townslot.Slot(releasable=economy)
        if campaign:
            slot.yield_to_campaign("dungeon:ragefire on Zug")
        if town_first:
            slot.hold_for_town("bag room for Oz, Zork, Zug")
        ran, marked = [], []
        rows = [
            learnaim.Row(character="Zug", learn_skill=186, leads=True),
            learnaim.Row(character="Oz", learn_skill=171, wanted=(164,)),
        ]
        me = types.SimpleNamespace(
            _cohort_town_slot=lambda key=None: slot, _family_lead_since={}
        )
        tradechoice = types.SimpleNamespace(
            learn_rows=lambda roster, trades, declared: rows,
            next_lead=lambda rows, **kw: "Zug",
            borrow_clock=lambda since, rows, lead, key, now: {},
            expired=lambda since, now, limit: set(),
            led_by=lambda rows, lead: rows,
        )
        ns = _load(
            ["_family_learn_aims"],
            {
                "asyncio": types.SimpleNamespace(to_thread=_thread),
                "time": Clock(0.0),
                "log": _Log(),
                "dataclasses": dataclasses,
                "learnaim": learnaim,
                "tradechoice": tradechoice,
                "ERRAND_LEAD_HOURS": 1,
                "_mark_party_leader": marked.append,
                "_run_learn_aim_plan": lambda stmts: ran.extend(stmts) or len(stmts),
            },
        )
        cohort = townslot.Cohort(key="Zug", leader="Zug", names=tuple(NAMES))
        asyncio.run(
            ns["_family_learn_aims"](me, cohort, {"roster": [], "trades": []}, {})
        )
        return ran, marked

    def test_no_trainer_walk_while_the_campaign_stages(self):
        ran, marked = self.run_pass(campaign=True)
        self.assertEqual([], marked)
        self.assertFalse(any("travel_npc" in sql for sql, _ in ran), ran)
        # The finished learn is still cleared.
        self.assertTrue(any("learn_skill = 0" in sql for sql, _ in ran), ran)

    def test_no_trainer_walk_while_the_campaign_waits_in_town(self):
        ran, marked = self.run_pass(campaign=False, town_first=True)
        self.assertEqual([], marked)
        self.assertFalse(any("travel_npc" in sql for sql, _ in ran), ran)

    def test_the_trainer_walk_is_aimed_once_it_lets_go(self):
        ran, _ = self.run_pass(campaign=False)
        self.assertTrue(any("travel_npc" in sql for sql, _ in ran), ran)


class TheWiring(unittest.TestCase):
    def test_the_queue_pass_runs_it_before_any_early_return(self):
        body = ast.get_source_segment(BRIDGE, _function("_campaign_queue_once"))
        self.assertLess(
            body.index("self._campaign_owns_travel(pending, fams)"),
            body.index("if not pending:"),
        )

    def test_the_sell_rows_follow_the_vendor_aim(self):
        body = ast.get_source_segment(BRIDGE, _function("_vendor_once"))
        self.assertIn("leader_walking=aimed", body)

    def test_the_own_familys_learn_writers_are_gated(self):
        for name in ("_reconcile_learn_aims", "_send_trade_errand"):
            body = ast.get_source_segment(BRIDGE, _function(name))
            self.assertIn("self._town_slot.learn_waits", body, name)


class _Cursor:
    def __init__(self, rows=(), rowcount=0):
        self.rows = list(rows)
        self.rowcount = rowcount
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _constants(*names):
    out = {}
    for node in ast.parse(BRIDGE).body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in names
        ):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "b", "exec"), out)  # noqa: S102
    return out


class TheReads(unittest.TestCase):
    def mailbox(self, cursor, skip):
        ns = _constants("_MAILBOX_SQL", "_MAILBOXES_SQL")
        ns.update(
            travel=travel,
            pymysql=types.SimpleNamespace(
                err=types.SimpleNamespace(MySQLError=RuntimeError)
            ),
            log=_Log(),
            _connect=lambda: _Conn(cursor),
        )
        _load(["_nearest_mailbox"], ns)
        return ns["_nearest_mailbox"]("Zug", skip)

    def test_without_a_skip_the_nearest_is_read_as_before(self):
        cursor = _Cursor([dict(x=1.0)])
        self.assertEqual(dict(x=1.0), self.mailbox(cursor, None))
        self.assertIn("LIMIT 1", cursor.calls[0][0])

    def test_a_skip_reads_further_and_passes_over(self):
        cursor = _Cursor([dict(x=1.0), dict(x=2.0)])
        got = self.mailbox(cursor, lambda row: row["x"] == 1.0)
        self.assertEqual(dict(x=2.0), got)
        self.assertIn("LIMIT 8", cursor.calls[0][0])

    def test_every_mailbox_skipped_is_none(self):
        self.assertIsNone(self.mailbox(_Cursor([dict(x=1.0)]), lambda row: True))

    def test_the_trainer_hand_back_leaves_the_learn(self):
        cursor = _Cursor(rowcount=1)
        ns = {"learnaim": learnaim, "_connect": lambda: _Conn(cursor)}
        _load(["_release_learn_aim"], ns)
        self.assertTrue(ns["_release_learn_aim"]("Zug"))
        sql, params = cursor.calls[0]
        self.assertIn("SET travel_npc = ''", sql)
        self.assertNotIn("learn_skill", sql)
        self.assertEqual(("Zug", learnaim.TRAINER_ROLE), params)


if __name__ == "__main__":
    unittest.main()
