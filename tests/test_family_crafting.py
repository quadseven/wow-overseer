"""Every roster family gathers and crafts, with its own leader and slot (#215).

The craft errand, craft supply, craft rhythm and materials passes served only
this bridge's own family. Another family's members now count the trades they
hold, its tailor works toward the family's bags first, its job is written for
its own rows only, and a campaign queue that owns its job is never stomped.
Every test here runs on fakes; none touches a database.
"""

import ast
import asyncio
import pathlib
import types
import unittest

from test_decree_order import FakeConn, FakeCursor  # noqa: F401 - sets up the pymysql stub

import craft  # noqa: E402
import craft_rhythm  # noqa: E402
import craft_supply  # noqa: E402
import jobs  # noqa: E402
import materials  # noqa: E402
import townslot  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

HORDE = townslot.Cohort(
    key="Zug", leader="Zug", names=("Oz", "Uzza", "Zork", "Zrog", "Zug")
)
BOLT, LINEN, THREAD = 2996, 2589, 2320


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
    code = compile(module, "bridge.py", "exec")
    exec(code, namespace)  # noqa: S102 - bridge.py's own source
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


FAKE_ASYNCIO = types.SimpleNamespace(to_thread=_thread)


# --- the pure half ------------------------------------------------------------


class AnotherFamilyCountsTheTradesItHolds(unittest.TestCase):
    def test_a_tailor_nobody_assigned_crafts_with_its_held_trades(self):
        skills = {"tailoring": 1}
        self.assertEqual(0, craft.craft_errand("Oz", skills))
        primaries = craft.held_primaries(skills)
        self.assertEqual(("tailoring",), primaries)
        self.assertEqual(2963, craft.craft_errand("Oz", skills, primaries))

    def test_a_miner_nobody_assigned_can_smelt(self):
        skills = {"mining": 1, "blacksmithing": 1}
        primaries = craft.held_primaries(skills)
        self.assertEqual(2657, craft.smelt_errand("Zug", skills, primaries))

    def test_a_trade_not_learned_is_not_held(self):
        self.assertEqual((), craft.held_primaries({"tailoring": 0, "first aid": 5}))


class TheTailorMakesTheFamilysBagsFirst(unittest.TestCase):
    PRIMARIES = ("enchanting", "tailoring")

    def errand(self, value, held, wanted):
        return craft_rhythm.errand(
            "Oz", {"tailoring": value}, held, self.PRIMARIES, wanted
        )

    def test_with_a_bags_worth_of_bolts_it_sews_the_bag(self):
        got = self.errand(50, {BOLT: 3}, 4)
        self.assertEqual(craft.LINEN_BAG.spell_id, got.spell)
        self.assertIn("Linen Bag", got.why)

    def test_short_of_bolts_it_weaves_them_toward_a_bag(self):
        self.assertEqual(2963, self.errand(50, {BOLT: 1, LINEN: 6}, 4).spell)
        self.assertEqual(2963, self.errand(50, {}, 4).spell)

    def test_with_no_bag_wanted_it_climbs_its_ladder(self):
        self.assertEqual(8776, self.errand(50, {BOLT: 3}, 0).spell)

    def test_below_the_bags_skill_it_climbs_its_ladder(self):
        self.assertEqual(2963, self.errand(30, {BOLT: 9}, 4).spell)

    def test_a_character_with_no_tailoring_makes_no_bag(self):
        got = craft_rhythm.errand("Zug", {"mining": 5}, {BOLT: 9}, ("mining",), 4)
        self.assertNotEqual(craft.LINEN_BAG.spell_id, got.spell)

    def test_the_bolts_and_linen_are_counted_for_the_tailor(self):
        wanted = craft_rhythm.reagents_to_count(
            "Oz", {"tailoring": 50}, self.PRIMARIES, 4
        )
        self.assertLessEqual({BOLT, LINEN}, wanted)

    def test_a_bag_in_hand_reads_stocked_and_none_reads_short(self):
        spell = craft.LINEN_BAG.spell_id
        self.assertEqual(
            craft_rhythm.STOCKED, craft_rhythm.stand("Oz", spell, {BOLT: 3}).verdict
        )
        self.assertEqual(
            craft_rhythm.SHORT, craft_rhythm.stand("Oz", spell, {BOLT: 2}).verdict
        )
        self.assertEqual((BOLT,), tuple(r.entry for r in craft_rhythm.feeds(spell)))

    def test_the_bags_thread_is_bought(self):
        self.assertEqual(
            ((THREAD, "Coarse Thread", 10, 3),), craft_supply.REAGENTS[3755]
        )
        self.assertEqual(0, craft.focus_for(3755))


class AnotherFamilysReagentsReachItsOwnCrafter(unittest.TestCase):
    SKILLS = {
        "Oz": {"tailoring": 40, "enchanting": 1},
        "Uzza": {"herbalism": 30, "alchemy": 12},
        "Zug": {"mining": 20, "blacksmithing": 15},
    }

    def test_each_crafting_trade_goes_to_whoever_holds_it(self):
        self.assertEqual(
            {
                "tailoring": "Oz",
                "enchanting": "Oz",
                "alchemy": "Uzza",
                "blacksmithing": "Zug",
            },
            materials.family_crafters(self.SKILLS),
        )

    def test_linen_from_the_leader_goes_to_the_tailor(self):
        plan = materials.plan(
            [materials.Holding("Zug", "Linen Cloth", 7, 101)],
            crafters=materials.family_crafters(self.SKILLS),
        )
        self.assertEqual([("Zug", "Oz")], [(g.holder, g.taker) for g in plan.grants])


class ANodeShortageWalksAndAClothShortageRoams(unittest.TestCase):
    def stand(self, name, verdict):
        return craft_rhythm.Stand(name=name, craft_spell=1, verdict=verdict)

    def test_an_alchemist_short_of_herbs_walks(self):
        stands = [self.stand("Uzza", craft_rhythm.SHORT)]
        self.assertTrue(
            craft_rhythm.short_of_nodes(stands, {"Uzza": ("alchemy", "herbalism")})
        )

    def test_a_tailor_short_of_linen_roams(self):
        stands = [self.stand("Oz", craft_rhythm.SHORT)]
        self.assertFalse(
            craft_rhythm.short_of_nodes(stands, {"Oz": ("enchanting", "tailoring")})
        )


# --- the bridge wiring --------------------------------------------------------


class FakeFamily:
    """The Horde family's rows as the bridge's adapters see them."""

    def __init__(self, *, queued=False, linen=30, job="quest"):
        self.queued = queued
        self.linen = linen
        self.job = job
        self.jobs = []
        self.errands = []
        self.crafted_for = []
        self.set_job_calls = []
        self.idled = []

    def queue_owns_job(self, family=None):
        return self.queued and family == "Zug"

    def standing_jobs(self, family=None):
        assert family == "Zug", family
        return {name: self.job for name in HORDE.names}

    def skills(self, names):
        return {"Oz": {"tailoring": 30, "enchanting": 1}}

    def counts(self, pairs):
        return {(name, entry): self.linen for name, entry in pairs if name == "Oz"}

    def insert_job(self, name, mode, source):
        self.jobs.append((name, mode, source))
        return 1


def _rhythm_self(world, log):
    ns = _load(
        [
            "_craft_rhythm_once",
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
            "_standing_jobs": world.standing_jobs,
            "_fetch_trade_skills": world.skills,
            "_bags_wanted_for": lambda cohort=None: 0,
            "_fetch_item_counts": world.counts,
            "_insert_job": world.insert_job,
        },
    )
    me = types.SimpleNamespace()

    async def craft_once(cohort=None):
        world.crafted_for.append(cohort)

    async def set_job(*a, **k):
        world.set_job_calls.append(a)

    async def mid_run(names):
        return False

    async def idle(claimant, cohort=None):
        world.idled.append((claimant, cohort))

    me._craft_once = craft_once
    me._set_job = set_job
    me._mid_run = mid_run
    me._idle_town_slot = idle
    for name in ("_family_rhythm_moves", "_set_family_job"):
        fn = ns[name]
        setattr(me, name, lambda *a, _fn=fn, **k: _fn(me, *a, **k))
    return me, ns["_craft_rhythm_once"]


class TheRhythmRunsForAnotherFamily(unittest.TestCase):
    def run_rhythm(self, world):
        log = _Log()
        me, once = _rhythm_self(world, log)
        asyncio.run(once(me, HORDE))
        return log.lines

    def test_a_stocked_tailor_sits_its_own_family_down_to_craft(self):
        world = FakeFamily(linen=30)
        self.run_rhythm(world)
        self.assertEqual(
            [(n, "craft", "overseer:craft_rhythm") for n in HORDE.names], world.jobs
        )
        self.assertEqual([HORDE], world.crafted_for)
        self.assertEqual([], world.set_job_calls, "this bridge's own writer was used")

    def test_a_queue_that_owns_the_job_is_never_stomped(self):
        world = FakeFamily(queued=True, linen=30)
        lines = self.run_rhythm(world)
        self.assertEqual([], world.jobs)
        self.assertEqual([], world.idled)
        self.assertTrue(any("campaign queue owns its job" in ln for ln in lines), lines)

    def test_a_tailor_out_of_linen_sends_the_family_roaming(self):
        world = FakeFamily(linen=0, job="craft")
        self.run_rhythm(world)
        self.assertEqual({"quest"}, {mode for _, mode, _ in world.jobs})
        self.assertEqual([("craft_rhythm", HORDE)], world.idled)

    def test_no_write_when_the_mode_already_stands(self):
        world = FakeFamily(linen=30, job="craft")
        self.run_rhythm(world)
        self.assertEqual([], world.jobs)


class TheCraftErrandIsWrittenForAnotherFamily(unittest.TestCase):
    def test_the_tailor_is_aimed_at_the_familys_bag(self):
        written = []
        ns = _load(
            ["_craft_once", "_primaries_for"],
            {
                "asyncio": FAKE_ASYNCIO,
                "craft": craft,
                "craft_rhythm": craft_rhythm,
                "log": _Log(),
                "_crafting_roster": lambda family=None: (
                    ["Oz"] if family == "Zug" else ["Og"]
                ),
                "_fetch_trade_skills": lambda names: {"Oz": {"tailoring": 55}},
                "_bags_wanted_for": lambda cohort=None: 5 if cohort is HORDE else 0,
                "_fetch_item_counts": lambda pairs: {("Oz", BOLT): 3},
                "_write_craft_errand": lambda name, spell: written.append(
                    (name, spell)
                ),
            },
        )
        asyncio.run(ns["_craft_once"](types.SimpleNamespace(), HORDE))
        self.assertEqual([("Oz", craft.LINEN_BAG.spell_id)], written)


class EveryOtherFamilyGetsItsTurn(unittest.TestCase):
    def test_each_other_family_runs_and_one_failure_costs_only_its_turn(self):
        alliance = townslot.Cohort(key="Grug", leader="Grug", names=("Grug",))
        other = townslot.Cohort(key="Kor", leader="Kor", names=("Kor",))
        log = _Log()
        ns = _load(
            ["_for_other_families"],
            {
                "asyncio": FAKE_ASYNCIO,
                "log": log,
                "_protected_guids": lambda: {1: "Grug"},
                "_other_cohorts": lambda own: (
                    (other, HORDE) if own == ["Grug"] else (alliance,)
                ),
            },
        )
        ran = []

        async def step(cohort):
            ran.append(cohort.key)
            if cohort.key == "Kor":
                raise RuntimeError("boom")

        asyncio.run(ns["_for_other_families"](types.SimpleNamespace(), "craft", step))
        self.assertEqual(["Kor", "Zug"], ran)
        self.assertTrue(any("family Kor" in ln for ln in log.lines), log.lines)

    def test_every_crafting_loop_runs_its_pass_for_every_other_family(self):
        for loop, what, once in (
            ("_assign_crafts", "craft", "_craft_once"),
            ("_craft_supply_loop", "craft_supply", "_craft_supply_once"),
            ("_craft_rhythm_loop", "craft_rhythm", "_craft_rhythm_once"),
            ("_move_materials_loop", "materials", "_move_materials_once"),
        ):
            body = ast.get_source_segment(BRIDGE, _function(loop))
            with self.subTest(loop=loop):
                self.assertIn(
                    'await self._for_other_families("%s", self.%s)' % (what, once), body
                )


class AnotherFamilysMaterialsReachItsCrafter(unittest.TestCase):
    def test_the_leaders_linen_is_given_to_the_tailor(self):
        given = []
        ns = _load(
            ["_move_family_materials"],
            {
                "asyncio": FAKE_ASYNCIO,
                "materials": materials,
                "log": _Log(),
                "GIVE_GIVE_UP_HOURS": 6,
                "GIVE_RETRY_MINUTES": 10,
                "_fetch_trade_skills": lambda names: {"Oz": {"tailoring": 20}},
                "_fetch_holdings": lambda names: [
                    materials.Holding("Zug", "Linen Cloth", 9, 7)
                ],
                "_give_attempts": lambda hours: [],
                "_fetch_free_slots": lambda names: {n: 5 for n in names},
                "_recent_give_keys": lambda minutes: set(),
                "_fetch_positions": lambda names: {},
                "handover": types.SimpleNamespace(
                    spots=lambda rows: {},
                    verdict=lambda giver, taker, where: types.SimpleNamespace(
                        verb="give", why=""
                    ),
                    GIVE="give",
                    waiting=lambda *a: "",
                ),
                "_insert_give": lambda grant: (
                    given.append((grant.holder, grant.taker)) or 1
                ),
                "_log_capped": lambda what, lines: None,
            },
        )

        async def not_mid_run(names):
            return False

        me = types.SimpleNamespace(_mid_run=not_mid_run)
        asyncio.run(ns["_move_family_materials"](me, HORDE))
        self.assertEqual([("Zug", "Oz")], given)


class TheWalksUseTheFamilysOwnLeaderAndSlot(unittest.TestCase):
    def test_the_supply_walk_asks_the_familys_slot_and_waits_for_its_queue(self):
        supply = ast.get_source_segment(BRIDGE, _function("_walk_for_reagents"))
        self.assertIn("_queue_owns_job, cohort.key", supply)
        aim = ast.get_source_segment(BRIDGE, _function("_aim_at_reagent_vendor"))
        self.assertIn("_cohort_leader, cohort.key", aim)
        self.assertIn('cohort=getattr(cohort, "key", None)', aim)

    def test_the_family_job_writer_asks_what_set_job_asks(self):
        """`_set_job` asks `jobs.why_not` and stands down for a queue; the
        other family's writer asks both, before any row is written."""
        body = ast.get_source_segment(BRIDGE, _function("_set_family_job"))
        self.assertLess(body.index("jobs.why_not(mode)"), body.index("_insert_job"))
        self.assertLess(
            body.index("_queue_owns_job, cohort.key"), body.index("_insert_job")
        )

    def test_the_gather_walk_asks_the_familys_slot(self):
        walk = ast.get_source_segment(BRIDGE, _function("_walk_to_gather_field"))
        self.assertIn("_family_leader, cohort", walk)
        self.assertIn('cohort=getattr(cohort, "key", None)', walk)
        yielded = ast.get_source_segment(BRIDGE, _function("_yield_gather_aim"))
        self.assertIn("self._cohort_town_slot(cohort).holder", yielded)


if __name__ == "__main__":
    unittest.main()
