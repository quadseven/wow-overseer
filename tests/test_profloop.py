"""The profession loop (#2419): gather, town, craft, train, and back."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import logging
import pathlib
import time
import unittest
from unittest import mock

import craft_rhythm
import jobs
import profloop
import reagentplan
import townerrand

H = 3600.0
FAMILY = ("Bork", "Grog", "Grug", "Og", "Ugga")


def facts(now, **kw):
    kw.setdefault("jobs", {n: "quest" for n in FAMILY})
    kw.setdefault("free_slots", {n: 15 for n in FAMILY})
    return profloop.Facts(now=now, **kw)


def at(phase, since=0.0, **kw):
    return profloop.State(phase=phase, since=since, **kw)


class TheSwitch(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(profloop.families({}), frozenset())
        self.assertFalse(profloop.enabled_for("Grug", {}))

    def test_names_families(self):
        env = {"PROFESSION_LOOP": " Grug, Zug ,"}
        self.assertEqual(profloop.families(env), frozenset({"Grug", "Zug"}))
        self.assertTrue(profloop.enabled_for("Zug", env))
        self.assertFalse(profloop.enabled_for("Other", env))
        self.assertFalse(profloop.enabled_for(None, env))


class GatherToTown(unittest.TestCase):
    def test_low_bags_go_to_town_with_a_reason_for_the_errand(self):
        slots = {n: 15 for n in FAMILY}
        slots["Og"] = profloop.TOWN_FREE_SLOTS - 1
        step = profloop.decide(at(profloop.GATHER), facts(600, free_slots=slots))
        self.assertTrue(step.moved)
        self.assertEqual(step.state.phase, profloop.TOWN)
        self.assertEqual(step.job, "")
        self.assertTrue(step.ask_town.startswith(townerrand.LOOP_WHY))
        self.assertIn("Og (7)", step.line)
        self.assertIn("gather -> town", profloop.line("Grug", step))
        self.assertIn("Grug", profloop.line("Grug", step))

    def test_enough_room_keeps_gathering(self):
        step = profloop.decide(at(profloop.GATHER), facts(600))
        self.assertFalse(step.moved)
        self.assertEqual((step.job, step.ask_town, step.line), ("", "", ""))

    def test_time_box_goes_to_town(self):
        step = profloop.decide(at(profloop.GATHER), facts(6 * H))
        self.assertEqual(step.state.phase, profloop.TOWN)
        self.assertIn("6 hours", step.line)

    def test_stocked_crafters_sit_down_after_the_minimum(self):
        casts = {"Ugga": profloop.READY_CASTS, "Bork": profloop.READY_CASTS + 4}
        early = profloop.decide(at(profloop.GATHER), facts(60, casts=casts))
        self.assertFalse(early.moved)
        step = profloop.decide(
            at(profloop.GATHER), facts(profloop.GATHER_MIN_SECONDS, casts=casts)
        )
        self.assertEqual(step.state.phase, profloop.CRAFT)
        self.assertEqual(step.job, "craft")

    def test_stocked_with_mail_waiting_goes_to_town_first(self):
        casts = {"Ugga": profloop.READY_CASTS}
        step = profloop.decide(
            at(profloop.GATHER),
            facts(profloop.GATHER_MIN_SECONDS, casts=casts, mail_waiting=("Og",)),
        )
        self.assertEqual(step.state.phase, profloop.TOWN)
        self.assertIn("Og", step.line)

    def test_a_town_errand_started_by_another_reason_is_the_town_phase(self):
        step = profloop.decide(
            at(profloop.GATHER),
            facts(600, errand_active=True, errand_why="bought gear waits"),
        )
        self.assertEqual(step.state.phase, profloop.TOWN)
        self.assertTrue(step.state.town_seen)
        self.assertEqual(step.job, "")


class TownAndBack(unittest.TestCase):
    def test_asks_the_errand_until_it_starts(self):
        step = profloop.decide(at(profloop.TOWN, since=100), facts(200))
        self.assertTrue(step.ask_town.startswith(townerrand.LOOP_WHY))
        self.assertFalse(step.moved)

    def test_errand_end_goes_back_to_gathering(self):
        seen = profloop.decide(
            at(profloop.TOWN, since=100),
            facts(200, errand_active=True, jobs={n: "town run" for n in FAMILY}),
        )
        self.assertTrue(seen.state.town_seen)
        step = profloop.decide(seen.state, facts(1500, errand_ended=1400))
        self.assertEqual(step.state.phase, profloop.GATHER)
        self.assertEqual(step.job, "quest")
        self.assertIn("town -> gather: the town errand ended", step.line)

    def test_errand_end_with_reagents_goes_to_craft(self):
        step = profloop.decide(
            at(profloop.TOWN, since=100, town_seen=True),
            facts(1500, errand_ended=1400, casts={"Ugga": 4}),
        )
        self.assertEqual(step.state.phase, profloop.CRAFT)

    def test_errand_end_with_a_rank_due_goes_to_train(self):
        step = profloop.decide(
            at(profloop.TOWN, since=100, town_seen=True),
            facts(1500, errand_ended=1400, train_due={"Og": (197,)}),
        )
        self.assertEqual(step.state.phase, profloop.TRAIN)
        self.assertEqual(step.job, "train")

    def test_an_errand_that_never_starts_is_not_waited_on(self):
        step = profloop.decide(
            at(profloop.TOWN, since=100), facts(100 + profloop.TOWN_START_SECONDS)
        )
        self.assertEqual(step.state.phase, profloop.GATHER)
        self.assertIn("did not start", step.line)

    def test_an_errand_ended_before_the_phase_does_not_count(self):
        step = profloop.decide(
            at(profloop.TOWN, since=100), facts(200, errand_ended=50)
        )
        self.assertFalse(step.moved)


class CraftAndTrain(unittest.TestCase):
    def test_craft_holds_while_a_cast_is_in_the_bags(self):
        step = profloop.decide(
            at(profloop.CRAFT),
            facts(600, casts={"Ugga": 3}, jobs={n: "craft" for n in FAMILY}),
        )
        self.assertFalse(step.moved)
        self.assertEqual(step.job, "")

    def test_spent_reagents_go_to_train_when_due(self):
        step = profloop.decide(
            at(profloop.CRAFT),
            facts(600, casts={"Ugga": 0}, train_due={"Ugga": (171,)}),
        )
        self.assertEqual(step.state.phase, profloop.TRAIN)

    def test_spent_reagents_go_gathering_when_nothing_is_due(self):
        step = profloop.decide(at(profloop.CRAFT), facts(600, casts={"Ugga": 0}))
        self.assertEqual(step.state.phase, profloop.GATHER)
        self.assertIn("spent", step.line)

    def test_craft_time_box(self):
        step = profloop.decide(
            at(profloop.CRAFT), facts(profloop.CRAFT_SECONDS, casts={"Ugga": 9})
        )
        self.assertEqual(step.state.phase, profloop.GATHER)

    def test_train_ends_when_nothing_is_due(self):
        step = profloop.decide(at(profloop.TRAIN), facts(60, train_due={"Og": ()}))
        self.assertEqual(step.state.phase, profloop.GATHER)
        self.assertIn("nothing left to buy", step.line)

    def test_train_time_box(self):
        step = profloop.decide(
            at(profloop.TRAIN), facts(profloop.TRAIN_SECONDS, train_due={"Og": (197,)})
        )
        self.assertEqual(step.state.phase, profloop.GATHER)
        self.assertIn("Og", step.line)


class OneOwner(unittest.TestCase):
    def test_another_writers_job_is_set_back_once_per_window(self):
        found = {n: "quest" for n in FAMILY}
        found["Og"] = "dungeon:scholomance"
        step = profloop.decide(
            at(profloop.CRAFT),
            facts(
                600,
                jobs=dict(found, **{n: "craft" for n in FAMILY if n != "Og"}),
                casts={"Ugga": 5},
            ),
        )
        self.assertEqual(step.job, "craft")
        self.assertIn("Og=dungeon:scholomance", step.line)
        again = profloop.decide(
            step.state, facts(700, jobs={"Og": "quest"}, casts={"Ugga": 5})
        )
        self.assertEqual(again.job, "")

    def test_a_farm_job_is_gathering(self):
        step = profloop.decide(
            at(profloop.GATHER), facts(600, jobs={n: "farm:mining" for n in FAMILY})
        )
        self.assertEqual(step.job, "")

    def test_a_run_or_a_queue_comes_first(self):
        for kw in ({"in_run": True}, {"queue_owns": True}):
            step = profloop.decide(
                at(profloop.GATHER), facts(9 * H, free_slots={"Og": 0}, **kw)
            )
            self.assertFalse(step.moved)
            self.assertEqual((step.job, step.ask_town), ("", ""))
            self.assertIn("waits", step.line)

    def test_joining_on_craft_writes_nothing(self):
        step = profloop.decide(
            profloop.State(), facts(10, jobs={n: "craft" for n in FAMILY})
        )
        self.assertEqual(step.state.phase, profloop.CRAFT)
        self.assertEqual(step.job, "")
        self.assertIn("joined -> craft", step.line)

    def test_joining_on_quest_writes_the_farm_job(self):
        step = profloop.decide(profloop.State(), facts(10, gather_job="farm:mining"))
        self.assertEqual(step.state.phase, profloop.GATHER)
        self.assertEqual(step.job, "farm:mining")
        self.assertGreater(step.state.asserted, 0)

    def test_a_family_on_quest_is_set_to_the_farm_job_while_gathering(self):
        state = at(profloop.GATHER, since=0.0)
        step = profloop.decide(state, facts(11 * 60, gather_job="farm:mining"))
        self.assertEqual(step.job, "farm:mining")
        self.assertIn("quest", step.line)

    def test_a_family_already_on_the_farm_job_is_left_alone(self):
        step = profloop.decide(
            at(profloop.GATHER),
            facts(
                11 * 60,
                gather_job="farm:mining",
                jobs={n: "farm:mining" for n in FAMILY},
            ),
        )
        self.assertEqual(step.job, "")

    def test_joining_on_another_job_gathers(self):
        step = profloop.decide(
            profloop.State(), facts(10, jobs={n: "raid prep" for n in FAMILY})
        )
        self.assertEqual(step.state.phase, profloop.GATHER)
        self.assertEqual(step.job, "quest")


class GatherTarget(unittest.TestCase):
    SKILLS = {
        "Grug": {"mining": 28, "blacksmithing": 22},
        "Ugga": {"herbalism": 199},
        "Bork": {"skinning": 14},
    }

    def test_quest_until_the_farm_job_is_wired(self):
        with mock.patch("jobs.can_set", side_effect=lambda m: m == "quest"):
            job, why = profloop.gather_job(self.SKILLS)
        self.assertEqual(job, "quest")
        self.assertIn("mining", why)

    def test_the_trade_furthest_behind_once_farm_is_wired(self):
        with mock.patch("jobs.can_set", return_value=True):
            self.assertEqual(profloop.gather_job(self.SKILLS)[0], "farm:mining")
            herbs = {"Uzza": {"herbalism": 124}, "Zug": {"mining": 160}}
            self.assertEqual(profloop.gather_job(herbs)[0], "farm:herbalism")

    def test_no_node_trade_roams(self):
        self.assertEqual(profloop.gather_job({"Bork": {"skinning": 14}})[0], "quest")

    def test_kill_drop_shortage_chooses_farm_item(self):
        short = reagentplan.Short(
            reagentplan.Reagent(4338, "Mageweave Cloth", 8),
            reagentplan.Stock(),
            reagentplan.AUCTION,
            "Mizu",
            "short",
        )
        plan = reagentplan.Plan("Mizu", 12053, True, 0, (short,))
        job, why = profloop.gather_job(self.SKILLS, {"Mizu": plan})
        self.assertEqual("farm:4338", job)
        self.assertIn("Mageweave Cloth", why)

    def test_sandworm_meat_entry_comes_from_gathered(self):
        self.assertIn(20424, profloop.KILL_DROP_ENTRIES)
        self.assertNotIn(20401, profloop.KILL_DROP_ENTRIES)
        short = reagentplan.Short(
            reagentplan.Reagent(20424, "Sandworm Meat", 1),
            reagentplan.Stock(),
            reagentplan.GATHER,
            "Bork",
            "short",
        )
        plan = reagentplan.Plan("Bork", 24801, True, 0, (short,))
        job, why = profloop.gather_job(self.SKILLS, {"Bork": plan})
        self.assertEqual("farm:20424", job)
        self.assertIn("Sandworm Meat", why)

    def test_kill_drop_entries_match_craft_rhythm_gathered(self):
        gathered_entries = {
            r.entry for reagents in craft_rhythm.GATHERED.values() for r in reagents
        }
        self.assertTrue(profloop.KILL_DROP_ENTRIES)
        self.assertTrue(profloop.KILL_DROP_ENTRIES.issubset(gathered_entries))
        for entry in profloop.KILL_DROP_ENTRIES:
            self.assertTrue(jobs.can_set("farm:%d" % entry), entry)

    def test_town_answered_cloth_shortage_does_not_farm(self):
        short = reagentplan.Short(
            reagentplan.Reagent(4338, "Mageweave Cloth", 8),
            reagentplan.Stock(guild_bank=8),
            reagentplan.GUILD_BANK,
            "Mizu",
            "in vault",
        )
        plan = reagentplan.Plan("Mizu", 12053, True, 0, (short,))
        job, _ = profloop.gather_job(self.SKILLS, {"Mizu": plan})
        self.assertEqual("farm:mining", job)

    def test_node_reagent_shortage_falls_back_to_node_trade(self):
        short = reagentplan.Short(
            reagentplan.Reagent(2447, "Peacebloom", 1),
            reagentplan.Stock(),
            reagentplan.GATHER,
            "Ugga",
            "gather",
        )
        plan = reagentplan.Plan("Uzza", 2330, True, 0, (short,))
        job, _ = profloop.gather_job(self.SKILLS, {"Uzza": plan})
        self.assertEqual("farm:mining", job)


class TheTownErrandTakesTheLoopsReason(unittest.TestCase):
    def test_same_prefix(self):
        self.assertEqual(townerrand.LOOP_WHY, profloop.LOOP_WHY)

    def test_the_loop_bypasses_the_cooldown(self):
        state = townerrand.State(ended=1000.0)
        kw = dict(now=1100.0, in_run=False, mail_gear={}, facts={})
        self.assertEqual(townerrand.should_start(state, **kw), "")
        why = profloop.LOOP_WHY + "Og (2) below 8 free bag slots"
        self.assertEqual(townerrand.should_start(state, loop_why=why, **kw), why)
        self.assertEqual(
            townerrand.should_start(state, loop_why=why, **dict(kw, in_run=True)), ""
        )

    def test_bag_room_steps_first(self):
        self.assertEqual(
            townerrand.steps_for(profloop.LOOP_WHY + "x"), townerrand.ROOM_STEP_ORDER
        )
        self.assertEqual(townerrand.steps_for("bought gear"), townerrand.STEP_ORDER)


class TheBridgeWiresIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = pathlib.Path("bridge.py").read_text(encoding="utf-8")

    def body(self, name):
        start = self.source.index(name)
        end = self.source.index("\n    async def ", start + len(name))
        return self.source[start:end]

    def test_the_pass_runs(self):
        self.assertEqual(self.source.count('_Pass("_prof_loop_loop"),'), 1)
        body = self.body("async def _prof_loop_for(")
        self.assertIn("profloop.decide(", body)
        self.assertIn("_PROF_LOOP_TOWN[town_key] = step.ask_town", body)
        reads = self.body("async def _prof_loop_facts(")
        self.assertIn("_queue_owns_job, key", reads)
        self.assertIn("self._mid_run(names)", reads)
        write = self.body("async def _prof_loop_write(")
        self.assertIn("jobs.why_not(mode)", write)
        self.assertIn("profloop.SOURCE", write)

    def test_the_errand_starts_on_the_loops_reason(self):
        body = self.body("async def _town_errand_start(")
        self.assertIn('globals().get("_PROF_LOOP_TOWN"', body)
        self.assertIn("loop_why=loop_why", body)

    def test_every_other_job_writer_stands_down(self):
        for name, guard in (
            ("async def _activity_for(", "looped_by(key)"),
            ("async def _attunement_for(", "looped_by(key)"),
            ("async def _level_route_for(", "looped_by(key)"),
            ("async def _drive_skill(", "looped_by, None"),
            ("async def _craft_rhythm_once(", "if loop_key:"),
        ):
            with self.subTest(name):
                self.assertIn(guard, self.body(name))

    def test_the_rhythm_records_its_recipes(self):
        self.assertIn(
            '"_RHYTHM_SPELLS", {}).update(spells)',
            self.body("async def _craft_rhythm_once("),
        )


class CraftAndTrainReach(unittest.TestCase):
    """#2501: the loop reached neither craft nor train on the dev realm."""

    def test_one_unfed_crafter_does_not_hold_the_family_in_gather(self):
        casts = {"Ugga": profloop.READY_CASTS, "Bork": 0, "Og": 0}
        step = profloop.decide(
            at(profloop.GATHER), facts(profloop.GATHER_MIN_SECONDS, casts=casts)
        )
        self.assertEqual(step.state.phase, profloop.CRAFT)
        self.assertIn("Ugga", step.line)

    def test_nobody_stocked_still_gathers(self):
        casts = {"Ugga": 1, "Bork": 0}
        step = profloop.decide(
            at(profloop.GATHER), facts(profloop.GATHER_MIN_SECONDS, casts=casts)
        )
        self.assertFalse(step.moved)

    def test_a_due_rank_pulls_gather_to_train_without_a_town_visit(self):
        due = {"Uzza": (2280,)}
        early = profloop.decide(
            at(profloop.GATHER), facts(profloop.GATHER_TRAIN_SECONDS - 1, train_due=due)
        )
        self.assertFalse(early.moved)
        step = profloop.decide(
            at(profloop.GATHER), facts(profloop.GATHER_TRAIN_SECONDS, train_due=due)
        )
        self.assertEqual(step.state.phase, profloop.TRAIN)
        self.assertEqual(step.job, "train")
        self.assertIn("Uzza", step.line)

    def test_a_full_bag_still_goes_to_town_before_a_due_rank(self):
        slots = {n: 15 for n in FAMILY}
        slots["Og"] = 2
        step = profloop.decide(
            at(profloop.GATHER),
            facts(
                profloop.GATHER_TRAIN_SECONDS,
                free_slots=slots,
                train_due={"Uzza": (2280,)},
            ),
        )
        self.assertEqual(step.state.phase, profloop.TOWN)

    def test_town_end_crafts_when_the_errand_just_fetched_a_crafters_reagents(self):
        # The saved bags trail the world: vials bought and a bank withdrawal
        # made in town are not in the database yet, so casts reads 0 for a
        # crafter whose every short reagent is one the errand fetches.
        step = profloop.decide(
            at(profloop.TOWN, since=100, town_seen=True),
            facts(1500, errand_ended=1400, casts={"Uzza": 0}, fetch=("Uzza",)),
        )
        self.assertEqual(step.state.phase, profloop.CRAFT)
        self.assertIn("Uzza", step.line)

    def test_town_end_without_casts_or_fetch_still_gathers(self):
        step = profloop.decide(
            at(profloop.TOWN, since=100, town_seen=True),
            facts(1500, errand_ended=1400, casts={"Uzza": 0}),
        )
        self.assertEqual(step.state.phase, profloop.GATHER)

    def test_town_end_says_why_each_crafter_was_not_counted(self):
        plans = {
            "Uzza": profloop.CrafterPlan(spell=2330, judged=True, casts=0),
            "Og": profloop.CrafterPlan(spell=0, judged=False, casts=0),
        }
        step = profloop.decide(
            at(profloop.TOWN, since=100, town_seen=True),
            facts(1500, errand_ended=1400, plans=plans),
        )
        self.assertIn("Uzza spell 2330 judged 0 cast(s)", step.line)
        self.assertIn("Og has no recipe chosen", step.line)

    def test_a_missing_rhythm_recipe_falls_back_to_the_standing_craft(self):
        chosen = profloop.choose_spells(
            ["Uzza", "Og", "Bork"],
            {"Uzza": 0, "Og": 2964},
            {"Uzza": 2330, "Bork": 3275},
        )
        self.assertEqual(chosen, {"Uzza": 2330, "Og": 2964, "Bork": 3275})


class ProfLoopBridgeWiring(unittest.TestCase):
    @staticmethod
    def _load_prof_loop_methods(ns):
        src = pathlib.Path("bridge.py").read_text(encoding="utf-8")
        tree = ast.parse(src, filename="bridge.py")
        wanted = {
            "_prof_loop_for",
            "_prof_loop_facts",
            "_prof_loop_say",
            "_prof_loop_write",
        }
        bridge_cls = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Bridge"
        )
        methods = [
            node
            for node in bridge_cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in wanted
        ]
        mod = ast.Module(
            body=[
                ast.ClassDef(
                    name="Bridge",
                    bases=[],
                    keywords=[],
                    body=methods,
                    decorator_list=[],
                )
            ],
            type_ignores=[],
        )
        ast.fix_missing_locations(mod)
        exec(compile(mod, "bridge.py", "exec"), ns)
        return ns["Bridge"]

    def _make_bridge(self, held_keys, writes):
        short = reagentplan.Short(
            reagentplan.Reagent(4338, "Mageweave Cloth", 8),
            reagentplan.Stock(),
            reagentplan.AUCTION,
            "Og",
            "short",
        )
        plan = reagentplan.Plan("Og", 12053, True, 0, (short,))
        ns = {
            "asyncio": asyncio,
            "dataclasses": dataclasses,
            "jobs": jobs,
            "log": logging.getLogger("test_profloop_bridge"),
            "profloop": profloop,
            "time": time,
            "townerrand": townerrand,
            "_PROF_LOOPS": {},
            "_PROF_LOOP_SAID": {},
            "_PROF_LOOP_TOWN": {},
            "_PROF_LOOP_TOWN_SOURCES": (
                reagentplan.BANK,
                reagentplan.MAIL,
                reagentplan.GUILD_BANK,
                reagentplan.VENDOR,
            ),
            "_RHYTHM_SPELLS": {"Og": 12053},
            "_TOWN_ERRANDS": {},
            "_standin_running": lambda names: list(names),
            "_jobs_of": lambda names: {n: "quest" for n in names},
            "_fetch_trade_skills": lambda names: {"Grug": {"mining": 150}},
            "_fetch_standing_crafts": lambda names: {"Og": (12053, 1)},
            "_plan_craft_reagents": lambda names, spells, skills: {"Og": plan},
            "_mail_gear_holders": lambda names: {},
            "_fetch_free_slots": lambda names: {n: 15 for n in names},
            "_prof_loop_train_due": lambda names: {},
            "_queue_owns_job": lambda key: False,
            "_prof_loop_quiet": lambda *a, **kw: None,
            "_last_job_source": lambda name: "",
            "_record_production": lambda names, skills: None,
            "_insert_job": lambda name, mode, source: writes.append(
                (name, mode, source)
            ),
        }
        bridge_cls = self._load_prof_loop_methods(ns)

        class FakeBridge(bridge_cls):
            async def _mid_run(self, names):
                return False

            async def _operator_held(self, keys, writer):
                return set(keys) & held_keys

        return FakeBridge(), ns

    def test_unheld_family_writes_kill_drop_farm_order_through_real_jobs(self):
        writes = []
        bridge_obj, _ = self._make_bridge(set(), writes)
        asyncio.run(bridge_obj._prof_loop_for("grug", ["Grug", "Og"]))
        self.assertEqual(
            writes,
            [
                ("Grug", "farm:4338", profloop.SOURCE),
                ("Og", "farm:4338", profloop.SOURCE),
            ],
        )

    def test_held_family_still_writes_farm_order(self):
        writes = []
        bridge_obj, _ = self._make_bridge({"grug"}, writes)
        asyncio.run(bridge_obj._prof_loop_for("grug", ["Grug", "Og"]))
        self.assertEqual(
            writes,
            [
                ("Grug", "farm:4338", profloop.SOURCE),
                ("Og", "farm:4338", profloop.SOURCE),
            ],
        )

    def test_held_family_still_writes_non_farm_job(self):
        writes = []
        bridge_obj, _ = self._make_bridge({"grug"}, writes)
        count = asyncio.run(
            bridge_obj._prof_loop_write("grug", ["Grug", "Og"], "craft")
        )
        self.assertEqual(count, 2)
        self.assertEqual(
            writes,
            [
                ("Grug", "craft", profloop.SOURCE),
                ("Og", "craft", profloop.SOURCE),
            ],
        )


if __name__ == "__main__":
    unittest.main()
