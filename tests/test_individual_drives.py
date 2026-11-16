"""Individual mode's bridge drives, run on fakes (#2395, #2404).

Each test loads the real function out of bridge.py and runs it against fake
adapters, so the order of the checks and the writes is what is tested, not
whether a word appears in the source. None touches a database.
"""

import asyncio
import os
import types
import unittest
from unittest import mock

from test_family_crafting import FAKE_ASYNCIO, HORDE, FakeFamily, _load, _Log

import craft
import craft_rhythm
import craft_supply
import guildcorps
import individual
import jobs
import trainjob
import travel

ZUG = {individual.ENV: "Zug"}
TAILORING = 197


class TheFamilyIsNamedOnlyWhenTheSettingNamesOne(unittest.TestCase):
    def run_helper(self, cohort=None):
        calls = []

        def cohort_of(name):
            calls.append(name)
            return "Grug"

        ns = _load(
            ["_individual_family"],
            {
                "individual": individual,
                "log": _Log(),
                "_cohort_of": cohort_of,
                "bonds": types.SimpleNamespace(head_of_family=lambda: "Grug"),
            },
        )
        return ns["_individual_family"](cohort), calls

    def test_no_query_while_the_setting_names_no_family(self):
        with mock.patch.dict(os.environ, {individual.ENV: ""}):
            got, calls = self.run_helper()
        self.assertIsNone(got)
        self.assertEqual([], calls, "a query was made with the feature off")

    def test_its_own_family_is_read_when_one_is_named(self):
        with mock.patch.dict(os.environ, ZUG):
            got, calls = self.run_helper()
        self.assertEqual("Grug", got)
        self.assertEqual(["Grug"], calls)

    def test_another_family_is_named_by_its_key(self):
        with mock.patch.dict(os.environ, ZUG):
            got, calls = self.run_helper(HORDE)
        self.assertEqual("Zug", got)
        self.assertEqual([], calls)


class MixedFamily(FakeFamily):
    """The Horde family with each member on its own job."""

    def __init__(self, jobs_by_name, **kw):
        super().__init__(**kw)
        self.jobs_by_name = dict(jobs_by_name)

    def standing_jobs(self, family=None):
        assert family == "Zug", family
        return dict(self.jobs_by_name)


def _individual_rhythm(world, log, *, mid_run=False, sitting=frozenset()):
    ns = _load(
        [
            "_craft_rhythm_once",
            "_individual_rhythm_moves",
            "_family_rhythm_moves",
            "_set_family_job",
            "_primaries_for",
            "_names_of",
        ],
        {
            "asyncio": FAKE_ASYNCIO,
            "craft": craft,
            "craft_rhythm": craft_rhythm,
            "jobs": jobs,
            "log": log,
            "_protected_guids": lambda: {1: "Grug"},
            "_queue_owns_job": world.queue_owns_job,
            "individual": individual,
            "_individual_family": lambda cohort=None: getattr(cohort, "key", None),
            "_standing_jobs": world.standing_jobs,
            "_standin_out": lambda: sitting,
            "_standin_running": list,
            "_fetch_trade_skills": world.skills,
            "_bags_wanted_for": lambda cohort=None: 0,
            "_guild_bag_floor_for": lambda cohort=None: None,
            "_fetch_item_counts": world.counts,
            "_fetch_crafters_known": lambda names: {},
            "_insert_job": world.insert_job,
        },
    )
    me = types.SimpleNamespace()

    async def craft_once(cohort=None):
        world.crafted_for.append(cohort)

    async def run_check(names):
        return mid_run

    async def no_material_requests(names):
        return []

    async def nothing(*a, **k):
        return None

    me._craft_once = craft_once
    me._material_routes = no_material_requests
    me._set_job = nothing
    me._mid_run = run_check
    me._idle_town_slot = nothing
    for name in ("_family_rhythm_moves", "_set_family_job", "_individual_rhythm_moves"):
        fn = ns[name]
        setattr(me, name, lambda *a, _fn=fn, **k: _fn(me, *a, **k))
    return me, ns["_craft_rhythm_once"]


class TheRhythmActsPerMember(unittest.TestCase):
    # Oz is the family's tailor (FakeFamily.skills); the rest hold no trade.
    JOBS = {
        "Oz": "quest",
        "Uzza": "train",
        "Zork": "quest",
        "Zrog": "fish",
        "Zug": "quest",
    }

    def run_once(self, world, **kw):
        log = _Log()
        me, once = _individual_rhythm(world, log, **kw)
        with mock.patch.dict(os.environ, ZUG):
            asyncio.run(once(me, HORDE))
        return log.lines, me

    def test_only_the_stocked_member_is_moved_to_craft(self):
        world = MixedFamily(self.JOBS, linen=30)
        self.run_once(world)
        self.assertEqual([("Oz", "craft", "overseer:craft_rhythm")], world.jobs)
        self.assertEqual([HORDE], world.crafted_for)

    def test_the_family_path_would_have_stood_down(self):
        world = MixedFamily(self.JOBS, linen=30)
        log = _Log()
        me, once = _individual_rhythm(world, log)
        with mock.patch.dict(os.environ, {individual.ENV: ""}):
            asyncio.run(once(me, HORDE))
        self.assertEqual([], world.jobs)

    def test_a_queue_that_owns_the_job_writes_no_job(self):
        world = MixedFamily(self.JOBS, linen=30, queued=True)
        lines, _ = self.run_once(world)
        self.assertEqual([], world.jobs)
        self.assertTrue(any("campaign queue owns its job" in ln for ln in lines), lines)

    def test_a_run_in_progress_writes_no_job(self):
        world = MixedFamily(self.JOBS, linen=30)
        self.run_once(world, mid_run=True)
        self.assertEqual([], world.jobs)

    def test_a_member_sitting_out_is_skipped(self):
        world = MixedFamily(self.JOBS, linen=30)
        self.run_once(world, sitting=frozenset({"Oz"}))
        self.assertEqual([], world.jobs)

    def test_a_dungeon_job_links_the_family(self):
        world = MixedFamily({**self.JOBS, "Zug": "dungeon:wailing"}, linen=30)
        self.run_once(world)
        self.assertEqual([], world.jobs)

    def test_a_move_to_gather_is_held_and_warned_once(self):
        world = MixedFamily({**self.JOBS, "Oz": "craft"}, linen=0)
        log = _Log()
        me, once = _individual_rhythm(world, log)
        with mock.patch.dict(os.environ, ZUG):
            asyncio.run(once(me, HORDE))
            asyncio.run(once(me, HORDE))
        self.assertEqual([], world.jobs, "a move to gather was written")
        warned = [ln for ln in log.lines if "is short of its reagents" in ln]
        self.assertEqual(1, len(warned), log.lines)


def trainee(name, job="train", skill=0):
    wanted = (skill,) if skill else ()
    return trainjob.Member(name=name, job=job, learn_skill=skill, wanted=wanted)


def _train_drive(members, *, queued=False, mid_run=False):
    written = []
    log = _Log()
    ns = _load(
        ["_drive_train"],
        {
            "asyncio": FAKE_ASYNCIO,
            "individual": individual,
            "trainjob": trainjob,
            "log": log,
            "_train_members": lambda: list(members),
            "_individual_family": lambda cohort=None: "Zug",
            "_queue_owns_job": lambda family=None: queued,
            "_aim_train_traveller": written.append,
        },
    )
    me = types.SimpleNamespace()

    async def run_check(names):
        return mid_run

    me._mid_run = run_check
    return me, ns["_drive_train"], written, log


class TheTrainDriveActsPerMember(unittest.TestCase):
    def family(self):
        return [
            trainee("Zug", job="quest"),
            trainee("Oz", skill=TAILORING),
            trainee("Uzza", job="craft"),
        ]

    def run_drive(self, members, times=1, **kw):
        me, drive, written, log = _train_drive(members, **kw)
        with mock.patch.dict(os.environ, ZUG):
            for _ in range(times):
                asyncio.run(drive(me))
        return written, log.lines

    def test_the_member_on_train_is_aimed_and_stale_aims_cleared(self):
        written, _ = self.run_drive(self.family())
        self.assertEqual(1, len(written))
        statements = written[0]
        self.assertEqual(
            travel.aim_only_statements(["Oz"], trainjob.TRAINER_ROLE), statements[:1]
        )
        self.assertEqual(
            trainjob.stale_clear_statements(["Uzza", "Zug"]), statements[1:]
        )

    def test_a_queue_that_owns_the_job_writes_nothing(self):
        written, lines = self.run_drive(self.family(), times=2, queued=True)
        self.assertEqual([], written)
        held = [ln for ln in lines if "no member is aimed" in ln]
        self.assertEqual(1, len(held), "the hold is said once, not every cycle")

    def test_a_run_in_progress_writes_nothing(self):
        written, _ = self.run_drive(self.family(), mid_run=True)
        self.assertEqual([], written)

    def test_with_nobody_on_train_stale_aims_are_still_cleared(self):
        members = [trainee("Zug", job="quest"), trainee("Uzza", job="craft")]
        written, _ = self.run_drive(members)
        self.assertEqual([trainjob.stale_clear_statements(["Uzza", "Zug"])], written)


class StaleTrainerAims(unittest.TestCase):
    def test_the_clear_is_a_compare_and_swap_on_the_trainer_value(self):
        sql, params = trainjob.stale_clear_statements(["Og"])[0]
        self.assertIn("WHERE travel_npc = %s AND learn_skill = 0 AND name IN", sql)
        self.assertEqual(("", travel.resolve(trainjob.TRAINER_ROLE), "Og"), params)

    def test_a_member_with_a_learn_errand_is_never_stale(self):
        plan = trainjob.plan(
            [trainee("Og", job="craft", skill=TAILORING), trainee("Zug", job="quest")],
            individual=True,
        )
        self.assertEqual(("Zug",), plan.stale)

    def test_naming_nobody_clears_nothing(self):
        self.assertEqual([], trainjob.stale_clear_statements([]))


class CraftSupplyBuysForTheFilteredMembersAndWalksNobody(
    unittest.IsolatedAsyncioTestCase
):
    async def test_individual_mode_buys_for_the_crafters_and_does_not_walk(self):
        need = craft_supply.Need("Og", 2901, "Mining Pick")
        ns = _load(
            ["_craft_supply_once", "_individual_walk_waits"],
            dict(
                asyncio=asyncio,
                craft_rhythm=craft_rhythm,
                craft_supply=craft_supply,
                guildcorps=guildcorps,
                individual=individual,
                _names_of=lambda cohort: ["Grug", "Og"],
                _individual_family=lambda cohort=None: "Grug",
                _standing_jobs=lambda family: {"Grug": "train", "Og": "craft"},
                _standin_out=lambda: set(),
                _fetch_standing_crafts=lambda names: {},
                log=mock.Mock(),
            ),
        )
        owner = types.SimpleNamespace(
            _dark_iron_once=mock.AsyncMock(),
            _buy_blacksmith_hammers=mock.AsyncMock(return_value=(0, [])),
            _buy_gather_tools=mock.AsyncMock(return_value=(1, [need])),
            _walk_for_hammers=mock.AsyncMock(),
            _walk_for_reagents=mock.AsyncMock(),
        )
        with mock.patch.dict(os.environ, {individual.ENV: "Grug"}):
            await ns["_craft_supply_once"](owner, None)
        owner._buy_gather_tools.assert_awaited_once_with(["Og"])
        owner._walk_for_hammers.assert_not_awaited()
        owner._walk_for_reagents.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
