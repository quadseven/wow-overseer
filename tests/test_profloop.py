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
import individual
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

    def test_a_leatherworker_short_of_light_leather_farms_it(self):
        short = reagentplan.Short(
            reagentplan.Reagent(2318, "Light Leather", 3),
            reagentplan.Stock(),
            reagentplan.GATHER,
            "Bork",
            "Bork holds Skinning, which gathers Light Leather",
        )
        plan = reagentplan.Plan("Bork", 3756, True, 0, (short,))
        job, why = profloop.gather_job(self.SKILLS, {"Bork": plan})
        self.assertEqual("farm:2318", job)
        self.assertIn("Light Leather", why)

    def test_a_thin_kill_drop_reagent_chooses_farm_item(self):
        # Og: 11 Silk Cloth against 4 per cast is two casts, under SHORT_CASTS.
        have = reagentplan.Stock(bags=11)
        thin = reagentplan.Short(
            reagentplan.Reagent(4306, "Silk Cloth", 12),
            have,
            reagentplan.GATHER,
            "Og",
            "roams",
        )
        plan = reagentplan.Plan("Og", 3839, True, 2, (), (thin,))
        job, why = profloop.gather_job(self.SKILLS, {"Og": plan})
        self.assertEqual("farm:4306", job)
        self.assertIn("Silk Cloth", why)
        self.assertIn("need 12, bags 11", why)

    def test_a_thin_reagent_the_bank_covers_does_not_farm(self):
        thin = reagentplan.Short(
            reagentplan.Reagent(4306, "Silk Cloth", 12),
            reagentplan.Stock(bags=11, bank=5),
            reagentplan.BANK,
            "Og",
            "bank",
        )
        plan = reagentplan.Plan("Og", 3839, True, 2, (), (thin,))
        self.assertEqual(
            "farm:mining", profloop.gather_job(self.SKILLS, {"Og": plan})[0]
        )

    def test_the_bigger_gap_is_farmed_first_across_short_and_thin(self):
        thin = reagentplan.Short(
            reagentplan.Reagent(4306, "Silk Cloth", 12),
            reagentplan.Stock(bags=11),
            reagentplan.GATHER,
            "Og",
            "roams",
        )
        short = reagentplan.Short(
            reagentplan.Reagent(4338, "Mageweave Cloth", 8),
            reagentplan.Stock(),
            reagentplan.AUCTION,
            "Oz",
            "short",
        )
        plans = {
            "Og": reagentplan.Plan("Og", 3839, True, 2, (), (thin,)),
            "Oz": reagentplan.Plan("Oz", 12053, True, 0, (short,)),
        }
        self.assertEqual("farm:4338", profloop.gather_job(self.SKILLS, plans)[0])

    def test_each_crafter_gets_its_own_kill_drop_order(self):
        og = reagentplan.Short(
            reagentplan.Reagent(4306, "Silk Cloth", 12),
            reagentplan.Stock(bags=11),
            reagentplan.GATHER,
            "Og",
            "roams",
        )
        oz = reagentplan.Short(
            reagentplan.Reagent(4338, "Mageweave Cloth", 8),
            reagentplan.Stock(),
            reagentplan.AUCTION,
            "Oz",
            "short",
        )
        vault = reagentplan.Short(
            reagentplan.Reagent(4306, "Silk Cloth", 12),
            reagentplan.Stock(bags=2, guild_bank=40),
            reagentplan.GUILD_BANK,
            "Zug",
            "vault",
        )
        plans = {
            "Og": reagentplan.Plan("Og", 3839, True, 2, (), (og,)),
            "Oz": reagentplan.Plan("Oz", 12053, True, 0, (oz,)),
            "Zug": reagentplan.Plan("Zug", 3839, True, 0, (vault,)),
            "Bork": reagentplan.Plan("Bork", 3756, False),
        }
        got = profloop.member_kill_drops(plans)
        self.assertEqual({"Og", "Oz"}, set(got))
        self.assertEqual("farm:4306", got["Og"][0])
        self.assertEqual("farm:4338", got["Oz"][0])
        self.assertIn("Og is short of Silk Cloth", got["Og"][1])

    def test_member_kill_drops_agrees_with_the_family_wide_choice(self):
        thin = reagentplan.Short(
            reagentplan.Reagent(4306, "Silk Cloth", 12),
            reagentplan.Stock(bags=11),
            reagentplan.GATHER,
            "Og",
            "roams",
        )
        plans = {"Og": reagentplan.Plan("Og", 3839, True, 2, (), (thin,))}
        self.assertEqual(
            profloop.gather_job(self.SKILLS, plans),
            profloop.member_kill_drops(plans)["Og"],
        )

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

    def test_town_end_waits_one_refresh_before_judging_fetched_reagents(self):
        # The saved bags trail the world: vials bought and a bank withdrawal
        # made in town are not in the database yet. No craft phase starts on
        # that guess; the loop stays in town for one refresh of the bags.
        step = profloop.decide(
            at(profloop.TOWN, since=100, town_seen=True),
            facts(1500, errand_ended=1400, casts={"Uzza": 0}, fetch=("Uzza",)),
        )
        self.assertFalse(step.moved)
        self.assertEqual(step.state.phase, profloop.TOWN)

    def test_no_craft_phase_starts_on_bags_that_still_show_no_cast(self):
        late = 1400 + profloop.BAGS_REFRESH_SECONDS
        step = profloop.decide(
            at(profloop.TOWN, since=100, town_seen=True),
            facts(late, errand_ended=1400, casts={"Uzza": 0}, fetch=("Uzza",)),
        )
        self.assertEqual(step.state.phase, profloop.GATHER)

    def test_a_refreshed_bag_with_a_cast_starts_the_craft_phase(self):
        step = profloop.decide(
            at(profloop.TOWN, since=100, town_seen=True),
            facts(1500, errand_ended=1400, casts={"Uzza": 3}, fetch=("Uzza",)),
        )
        self.assertEqual(step.state.phase, profloop.CRAFT)

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
            "individual": individual,
            "log": logging.getLogger("test_profloop_bridge"),
            "profloop": profloop,
            "time": time,
            "townerrand": townerrand,
            "_PROF_LOOPS": {},
            "_PROF_LOOP_SAID": {},
            "_PROF_LOOP_YIELD": set(),
            "_queued_run_door": lambda key: (False, None),
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
            "_standin_out": frozenset,
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

    def _gather_writes(self, family_setting, key="grug"):
        import os

        writes = []
        bridge_obj, ns = self._make_bridge(set(), writes)
        ns["_plan_craft_reagents"] = lambda names, spells, skills: {}
        ns["_fetch_trade_skills"] = lambda names: {
            "Grug": {"mining": 150},
            "Og": {"herbalism": 200},
        }
        with mock.patch.dict(os.environ, {individual.ENV: family_setting}):
            asyncio.run(bridge_obj._prof_loop_for(key, ["Grug", "Og"]))
        return dict((n, m) for n, m, _ in writes)

    def test_an_individual_family_gathers_per_member_under_the_loop(self):
        got = self._gather_writes("grug")
        self.assertEqual(got, {"Grug": "farm:mining", "Og": "farm:herbalism"})

    def test_a_family_not_individual_stays_family_wide_under_the_loop(self):
        got = self._gather_writes("")
        self.assertEqual(got, {"Grug": "farm:mining", "Og": "farm:mining"})

    def test_a_queued_run_keeps_the_family_off_far_farm_jobs(self):
        import os

        writes = []
        bridge_obj, ns = self._make_bridge(set(), writes)
        ns["_plan_craft_reagents"] = lambda names, spells, skills: {}
        ns["_fetch_trade_skills"] = lambda names: {
            "Grug": {"mining": 150},
            "Og": {"herbalism": 200},
        }
        ns["_queued_run_door"] = lambda key: (True, (0, 1.0, 2.0))
        ns["_farm_job_near_door"] = lambda job, door, skills: job == "farm:mining"
        with mock.patch.dict(os.environ, {individual.ENV: "grug"}):
            asyncio.run(bridge_obj._prof_loop_for("grug", ["Grug", "Og"]))
        self.assertEqual(
            dict((n, m) for n, m, _ in writes),
            {"Grug": "farm:mining", "Og": profloop.QUEUED_FALLBACK},
        )

    def test_the_yield_marks_the_family_for_the_queue(self):
        writes = []
        bridge_obj, ns = self._make_bridge(set(), writes)
        ns["_queued_run_door"] = lambda key: (True, None)
        # The bridge reads time.monotonic(), which on a freshly booted runner
        # is smaller than the slice: anchor the clocks to it instead of to a
        # literal, so the slice is spent however long the host has been up.
        spent = time.monotonic() - profloop.QUEUED_SLICE_SECONDS - 1.0
        ns["_PROF_LOOPS"]["grug"] = profloop.State(
            phase=profloop.GATHER, since=spent, queued_since=spent
        )
        asyncio.run(bridge_obj._prof_loop_for("grug", ["Grug", "Og"]))
        self.assertEqual(writes, [])
        self.assertIn("grug", ns["_PROF_LOOP_YIELD"])


class TheQueuedRunSlice(unittest.TestCase):
    """While a run is queued the loop holds a family for a bounded slice."""

    def test_holds_inside_the_slice_and_keeps_its_clock(self):
        state = at(profloop.GATHER, since=0.0)
        first = profloop.decide(state, facts(100.0, run_queued=True))
        self.assertFalse(first.yielded)
        self.assertEqual(first.state.queued_since, 100.0)
        later = profloop.decide(
            first.state,
            facts(100.0 + profloop.QUEUED_SLICE_SECONDS - 1, run_queued=True),
        )
        self.assertFalse(later.yielded)
        self.assertEqual(later.state.queued_since, 100.0)

    def test_yields_at_the_bound_and_the_dungeon_job_stands(self):
        state = at(profloop.GATHER, since=0.0, queued_since=100.0)
        step = profloop.decide(
            state, facts(100.0 + profloop.QUEUED_SLICE_SECONDS, run_queued=True)
        )
        self.assertTrue(step.yielded)
        self.assertEqual(step.job, "")
        self.assertIn("a campaign run is queued", step.line)
        again = profloop.decide(
            step.state,
            facts(100.0 + 2 * profloop.QUEUED_SLICE_SECONDS, run_queued=True),
        )
        self.assertEqual((again.job, again.line, again.yielded), ("", "", False))
        self.assertTrue(again.state.yielded)

    def test_the_yield_is_logged_once(self):
        state = at(profloop.GATHER, since=0.0, queued_since=1.0)
        step = profloop.decide(state, facts(1.0 + H, run_queued=True))
        lines = [profloop.line("Grug", step)]
        for n in range(1, 4):
            step = profloop.decide(
                step.state, facts(1.0 + H + n * 600, run_queued=True)
            )
            lines.append(profloop.line("Grug", step))
        self.assertEqual([x for x in lines if x].__len__(), 1)

    def test_no_run_queued_behaves_as_before(self):
        state = at(profloop.GATHER, since=0.0)
        step = profloop.decide(state, facts(5 * H))
        self.assertFalse(step.yielded)
        self.assertEqual(step.state.queued_since, 0.0)
        # a long stretch with nothing queued is never cut by the slice
        self.assertEqual(step.state.phase, profloop.GATHER)

    def test_a_run_opening_starts_a_fresh_slice(self):
        state = at(profloop.GATHER, since=0.0, queued_since=1.0, yielded=True)
        step = profloop.decide(state, facts(9000.0, run_queued=True, in_run=True))
        self.assertFalse(step.state.yielded)
        self.assertEqual(step.state.queued_since, 0.0)

    def test_a_far_farm_job_is_not_issued_while_a_run_is_queued(self):
        targets = {
            "Bork": "farm:mining",
            "Grog": "farm:herbalism",
            "Grug": "farm:13463",
            "Og": "quest",
        }
        near = {"farm:mining"}
        out = profloop.queued_targets(targets, lambda job: job in near)
        self.assertEqual(out["Bork"], "farm:mining")
        self.assertEqual(out["Grog"], profloop.QUEUED_FALLBACK)
        self.assertEqual(out["Grug"], profloop.QUEUED_FALLBACK)
        self.assertEqual(out["Og"], "quest")

    def test_no_run_queued_still_splits_members(self):
        skills = {
            "Bork": {"mining": 100},
            "Grog": {"herbalism": 100},
        }
        got = individual.gather_targets(
            {n: "farm:mining" for n in skills},
            skills,
            "bork",
            "farm:mining",
            environ={individual.ENV: "bork"},
        )
        self.assertEqual(got, {"Bork": "farm:mining", "Grog": "farm:herbalism"})


if __name__ == "__main__":
    unittest.main()
