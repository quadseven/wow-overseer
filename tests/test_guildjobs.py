"""Every guild member's job, earned in play (#194).

Pure unit tests against guildjobs.py, plus source checks on the bridge pass,
the lineup endpoint and the page. The fixtures follow the operator's order of
2026-09-24: both guilds restart their guild bots at level 1 with nothing, the
ten maintenance members farm and give the most, the warlocks farm near their
doors between summons, and only what a member earned after its natural restart
counts.
"""

import ast
import json
import pathlib
import unittest

import guildjobs
import guildroute
import keep

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

H, M, S = guildjobs.HERBALISM, guildjobs.MINING, guildjobs.SKINNING
WARLOCK = 9
ORC, HUMAN = 2, 1


def member(name, role=guildjobs.MAINTENANCE, **over):
    base = dict(
        name=name,
        guild="Cave",
        role=role,
        level=12,
        class_id=1,
        race=HUMAN,
        online=True,
        map_id=0,
        x=-9000.0,
        y=100.0,
        money=5000,
        eligible=True,
    )
    base.update(over)
    return guildjobs.Member(**base)


def stack(guid, entry, count, subclass=9, item_class=7, quality=1, price=5, name=""):
    return guildjobs.Carried(
        guid=guid,
        entry=entry,
        count=count,
        item_class=item_class,
        subclass=subclass,
        quality=quality,
        sell_price=price,
        name=name or "item %d" % entry,
    )


def plan(members, **kw):
    kw.setdefault("masters", {"Cave": "Grug", "Bonkers": "Zug"})
    return guildjobs.plan(members, **kw)


def only_step(result, name):
    steps = [s for s in result.steps if s.holder == name]
    return steps[0] if steps else None


class TheTradeSplit(unittest.TestCase):
    def test_ten_members_give_seven_seven_and_six(self):
        crew = [member("M%02d" % i) for i in range(10)]
        trades = guildjobs.split_trades(crew)
        counts = {s: sum(s in t for t in trades.values()) for s in (H, M, S)}
        self.assertEqual(counts, {H: 7, M: 7, S: 6})
        self.assertTrue(all(len(t) == 2 for t in trades.values()))

    def test_a_trade_a_member_learned_on_its_own_is_kept(self):
        crew = [member("A", skills={S: (40, 75)}), member("B")]
        trades = guildjobs.split_trades(crew)
        self.assertIn(S, trades["A"])
        self.assertEqual(len(trades["A"]), 2)

    def test_a_full_primary_slot_is_not_given_a_third_trade(self):
        crafter = member("Tailor", skills={197: (30, 75), 171: (10, 75)})
        self.assertEqual(guildjobs.split_trades([crafter])["Tailor"], ())

    def test_raiders_and_summoners_are_not_split(self):
        trades = guildjobs.split_trades(
            [member("R", role=guildjobs.RAIDER), member("W", role=guildjobs.SUMMONER)]
        )
        self.assertEqual(trades, {})

    def test_each_guild_is_split_on_its_own(self):
        crew = [member("A"), member("B", guild="Bonkers")]
        trades = guildjobs.split_trades(crew)
        self.assertEqual(trades["A"], (H, M))
        self.assertEqual(trades["B"], (H, M))


class TheRanks(unittest.TestCase):
    def test_the_first_rank_waits_for_its_level(self):
        self.assertIsNone(guildjobs.next_rank(H, 0, 0, 4))
        self.assertEqual(guildjobs.next_rank(H, 0, 0, 5).spell, 2372)
        # Skinning's apprentice asks no level.
        self.assertEqual(guildjobs.next_rank(S, 0, 0, 1).spell, 8615)

    def test_the_next_rank_waits_for_the_ceiling(self):
        self.assertIsNone(guildjobs.next_rank(M, 60, 75, 12))
        self.assertEqual(guildjobs.next_rank(M, 70, 75, 12).spell, 2582)

    def test_artisan_waits_for_level_25(self):
        self.assertIsNone(guildjobs.next_rank(H, 222, 225, 24))
        self.assertEqual(guildjobs.next_rank(H, 222, 225, 25).spell, 11994)

    def test_nothing_past_the_classic_ceiling(self):
        self.assertIsNone(guildjobs.next_rank(M, 300, 300, 60))


class Maintenance(unittest.TestCase):
    def test_a_new_member_learns_its_first_trade_at_a_trainer_and_pays(self):
        m = member("Keeper", level=5, money=40)
        step = only_step(plan([m]), "Keeper")
        self.assertEqual(step.action, "train")
        (row,) = step.rows
        self.assertEqual((row.kind, row.command), ("cast", "walk-to-trainer skill:182"))
        self.assertEqual(row.source, "guildjobs:train:Keeper")
        self.assertIn("learn Herbalism (up to 75, 10c)", step.said)

    def test_a_member_that_cannot_pay_saves_and_says_so(self):
        m = member("Poor", level=12, money=0)
        result = plan([m])
        self.assertIsNone(only_step(result, "Poor"))
        self.assertIn("Poor saves for Herbalism (10c, it carries 0c)", result.notes)

    def test_a_miner_without_a_pick_buys_one(self):
        m = member("Miner", skills={H: (10, 75), M: (10, 75)}, money=500)
        step = only_step(plan([m]), "Miner")
        self.assertEqual(step.action, "tool")
        self.assertEqual(step.walk.command, "walk-to-vendor item:2901")
        self.assertEqual(step.rows[0].command, "entry:2901 count:1 max:162")

    def test_any_pick_the_bot_ai_accepts_will_do(self):
        m = member(
            "Miner",
            skills={H: (10, 75), M: (10, 75)},
            carried=(stack(9, 1819, 1, item_class=2, subclass=14),),
        )
        step = only_step(plan([m]), "Miner")
        self.assertTrue(step is None or step.action != "tool")

    def test_a_member_at_its_field_is_left_to_gather(self):
        field = guildjobs.Spot("gameobject", 4242, 0, -9010.0, 120.0, "Peacebloom")
        m = member(
            "Keeper",
            skills={H: (40, 75), S: (10, 75)},
            carried=(stack(1, 7005, 1, item_class=2),),
        )
        result = plan([m], fields={"Keeper": field})
        self.assertIsNone(only_step(result, "Keeper"))
        self.assertEqual(
            result.lines["Keeper"], "gathers Herbalism and Skinning at Peacebloom"
        )

    def test_a_member_far_from_its_field_walks_to_the_spawn(self):
        field = guildjobs.Spot(
            "gameobject", 4242, 0, -8000.0, 900.0, "Copper Vein", why="in band"
        )
        m = member(
            "Keeper",
            skills={H: (40, 75), M: (40, 75)},
            carried=(stack(1, 2901, 1, item_class=2),),
        )
        step = only_step(plan([m], fields={"Keeper": field}, cap=20000), "Keeper")
        self.assertEqual(step.action, "farm")
        (row,) = step.rows
        self.assertEqual(
            (row.kind, row.command), ("job", "walk-to-spawn gameobject:4242 max:20000")
        )

    def test_a_cooldown_in_the_log_is_honoured(self):
        field = guildjobs.Spot("gameobject", 4242, 0, -8000.0, 900.0, "Copper Vein")
        m = member(
            "Keeper",
            skills={H: (40, 75), S: (1, 75)},
            carried=(stack(1, 7005, 1, item_class=2),),
        )
        recent = (guildjobs.Recent("Keeper", "farm", 10),)
        result = plan([m], fields={"Keeper": field}, recent=recent)
        self.assertIsNone(only_step(result, "Keeper"))
        recent = (guildjobs.Recent("Keeper", "farm", 50),)
        self.assertIsNotNone(
            only_step(plan([m], fields={"Keeper": field}, recent=recent), "Keeper")
        )


class WhereMaterialsGo(unittest.TestCase):
    def test_herbs_go_to_the_guilds_alchemist_and_ore_to_the_bank(self):
        m = member(
            "Keeper",
            skills={H: (40, 75), M: (40, 75)},
            carried=(
                stack(11, 2447, 12, subclass=9, name="Peacebloom"),
                stack(12, 2770, 8, subclass=7, name="Copper Ore"),
                stack(13, 2901, 1, item_class=2),
            ),
        )
        crafters = {"Cave": {171: [("Ugga", 60), ("Og", 90)]}}
        step = only_step(plan([m], crafters=crafters), "Keeper")
        self.assertEqual(step.action, "post")
        self.assertEqual(step.walk.command, "walk-to-mailbox max:600")
        self.assertEqual(
            [(r.kind, r.command, r.target_arg) for r in step.rows],
            [
                ("mail", "send item:11 subject:Guild materials", "Og"),
                ("mail", "send item:12 subject:Guild materials", "Grug"),
            ],
        )
        self.assertIn("12 Peacebloom to Og (its crafter)", step.said)
        self.assertIn(
            "8 Copper Ore to Grug (the guild bank's Materials tab)", step.said
        )

    def test_a_reserved_stack_is_never_posted(self):
        m = member(
            "Keeper",
            skills={H: (40, 75), S: (1, 75)},
            carried=(stack(11, 2447, 12), stack(1, 7005, 1, item_class=2)),
        )
        kept = keep.from_rows(
            [{"character_name": "keeper", "item_entry": 2447, "item_guid": 0}]
        )
        result = plan([m], kept=kept)
        self.assertIsNone(only_step(result, "Keeper"))
        # Another holder's reservation keeps nothing of this one's.
        other = keep.from_rows(
            [{"character_name": "someone", "item_entry": 2447, "item_guid": 0}]
        )
        self.assertEqual(only_step(plan([m], kept=other), "Keeper").action, "post")
        step = only_step(result, "Keeper")
        self.assertTrue(step is None or step.action != "post")

    def test_a_raider_posts_only_a_real_haul(self):
        small = member(
            "Raider", role=guildjobs.RAIDER, carried=(stack(1, 2589, 12, subclass=5),)
        )
        self.assertIsNone(only_step(plan([small]), "Raider"))
        big = member(
            "Raider", role=guildjobs.RAIDER, carried=(stack(1, 2589, 20, subclass=5),)
        )
        self.assertEqual(only_step(plan([big]), "Raider").action, "post")

    def test_no_postage_no_letter(self):
        m = member(
            "Keeper",
            money=10,
            skills={H: (40, 75), S: (1, 75)},
            carried=(stack(11, 2447, 12), stack(1, 7005, 1, item_class=2)),
        )
        result = plan([m])
        self.assertIsNone(only_step(result, "Keeper"))
        self.assertIn(
            "Keeper cannot pay the postage for its materials yet", result.notes
        )

    def test_grey_loot_is_sold_at_any_vendor(self):
        junk = tuple(stack(20 + i, 100 + i, 1, quality=0, price=40) for i in range(4))
        m = member(
            "Keeper",
            skills={H: (40, 75), S: (1, 75)},
            carried=junk + (stack(1, 7005, 1, item_class=2),),
        )
        step = only_step(plan([m]), "Keeper")
        self.assertEqual(step.action, "sell")
        self.assertEqual(step.walk.command, "walk-to-vendor any")
        self.assertEqual(
            [r.command for r in step.rows], ["guid:20", "guid:21", "guid:22", "guid:23"]
        )
        self.assertEqual({r.kind for r in step.rows}, {"sell"})


class Summoners(unittest.TestCase):
    stones = (
        guildjobs.Spot("gameobject", 6855, 1, 1811.0, -4410.0, "Meeting Stone"),
        guildjobs.Spot("gameobject", 15686, 1, -740.0, -2215.0, "Meeting Stone"),
    )

    def warlock(self, name, **over):
        base = dict(
            role=guildjobs.SUMMONER,
            class_id=WARLOCK,
            race=ORC,
            map_id=1,
            x=1000.0,
            y=-4400.0,
            guild="Bonkers",
            level=20,
            known=frozenset({guildjobs.RITUAL_OF_SUMMONING}),
        )
        base.update(over)
        return member(name, **base)

    def test_below_level_20_a_warlock_levels(self):
        result = plan([self.warlock("W", level=12, known=frozenset())])
        self.assertIsNone(only_step(result, "W"))
        self.assertEqual(result.lines["W"], "levels toward Ritual of Summoning at 20")

    def test_at_20_without_the_ritual_it_says_so(self):
        result = plan([self.warlock("W", known=frozenset())])
        self.assertIn("has not learned it", result.lines["W"])

    def test_doors_fit_the_level_and_are_spread_fewest_first(self):
        crew = [self.warlock("A"), self.warlock("B")]
        doors = guildjobs.assign_doors(crew, guildjobs.entrances(), self.stones)
        self.assertEqual({d.keyword for d in doors.values()}, {"ragefire", "wailing"})
        self.assertEqual(doors["A"].stone.spawn, 6855)

    def test_a_warlock_with_the_ritual_walks_to_its_stone_to_farm(self):
        w = self.warlock("A")
        doors = guildjobs.assign_doors([w], guildjobs.entrances(), self.stones)
        step = only_step(plan([w], doors=doors), "A")
        self.assertEqual(step.action, "door")
        self.assertEqual(step.rows[0].command, "walk-to-spawn gameobject:6855")
        self.assertEqual(step.rows[0].kind, "job")

    def test_a_summon_waiting_keeps_it_where_it_is(self):
        w = self.warlock("A")
        doors = guildjobs.assign_doors([w], guildjobs.entrances(), self.stones)
        result = plan([w], doors=doors, pending={"A"})
        self.assertIsNone(only_step(result, "A"))
        self.assertTrue(result.lines["A"].startswith("answers a summon at"))

    def test_near_its_stone_it_farms_there(self):
        w = self.warlock("A", x=1811.0, y=-4300.0)
        doors = guildjobs.assign_doors([w], guildjobs.entrances(), self.stones)
        result = plan([w], doors=doors)
        self.assertIsNone(only_step(result, "A"))
        self.assertIn("farms near the meeting stone at", result.lines["A"])
        self.assertIn("carries no Soul Shard yet", result.lines["A"])

    def test_without_a_fresh_position_it_is_not_walked(self):
        w = self.warlock("A")
        doors = guildjobs.assign_doors([w], guildjobs.entrances(), self.stones)
        stale = self.warlock("A", x=None, y=None)
        result = plan([stale], doors=doors)
        self.assertIsNone(only_step(result, "A"))
        self.assertIn("where it stands is not read this pass", result.lines["A"])

    def test_wings_that_share_a_stone_share_its_load(self):
        stones = (
            guildjobs.Spot("gameobject", 44791, 0, 2655.95, -678.2, "Meeting Stone"),
        )
        crew = [
            self.warlock(
                n, race=HUMAN, map_id=0, x=2000.0, y=-600.0, level=36, guild="Cave"
            )
            for n in ("A", "B", "C")
        ]
        doors = guildjobs.assign_doors(crew, guildjobs.entrances(), stones)
        self.assertEqual({d.stone.spawn for d in doors.values()}, {44791})
        self.assertEqual(len(doors), 3)

    def test_a_door_that_does_not_fit_is_never_given(self):
        w = self.warlock("Low", level=20)
        self.assertNotIn("zulfarrak", {r.keyword for r in guildjobs.doors_for(w)})
        old = self.warlock("Old", level=60)
        self.assertNotIn("ragefire", {r.keyword for r in guildjobs.doors_for(old)})

    def test_the_stone_is_the_nearest_to_the_entrance(self):
        stone = guildjobs.stone_for("ragefire", guildjobs.entrances(), self.stones)
        self.assertEqual(stone.spawn, 6855)
        far = (guildjobs.Spot("gameobject", 1, 1, 9000.0, 9000.0, "Meeting Stone"),)
        self.assertIsNone(guildjobs.stone_for("ragefire", guildjobs.entrances(), far))


class NaturallyEarnedOnly(unittest.TestCase):
    def test_a_member_not_restarted_does_nothing_and_says_why(self):
        m = member("Factory", eligible=False, carried=(stack(1, 2447, 200),))
        result = plan([m])
        self.assertEqual(result.steps, ())
        self.assertEqual(
            result.lines["Factory"],
            "waits for its natural restart; nothing it holds is counted",
        )

    def test_the_family_is_never_planned(self):
        result = plan([member("Grug", role=guildjobs.FAMILY)])
        self.assertEqual((result.steps, result.lines), ((), {}))


class TheBudget(unittest.TestCase):
    def test_a_guild_starts_at_most_its_steps_per_pass(self):
        crew = [member("M%02d" % i, level=5) for i in range(10)]
        result = plan(crew)
        self.assertEqual(len(result.steps), guildjobs.STEPS_PER_GUILD)
        self.assertEqual(
            sum("guild job steps per guild per pass" in n for n in result.notes), 6
        )

    def test_offline_fighting_and_busy_members_wait(self):
        crew = [
            member("Off", level=5, online=False),
            member("Fight", level=5, in_combat=True),
            member("Busy", level=5),
        ]
        result = plan(crew, busy={"Busy"})
        self.assertEqual(result.steps, ())
        said = " | ".join(result.notes)
        for why in (
            "Off is offline",
            "Fight is in combat",
            "Busy is already on another guild walk",
        ):
            self.assertIn(why, said)


def sent(name, count=12, status="delivered", outcome="sent"):
    return dict(
        target_name=name,
        source="guildjobs:post:%s" % name,
        status=status,
        result=json.dumps(
            {"outcome": outcome, "item": {"entry": 2447, "count": count}}
        ),
    )


class WhatWasGiven(unittest.TestCase):
    def test_only_what_the_world_sent_or_sold_counts(self):
        rows = [
            sent("Keeper"),
            sent("Keeper", count=4),
            sent("Keeper", status="error", outcome="refused"),
            dict(
                target_name="Keeper",
                source="guildjobs:sell:Keeper",
                status="applied",
                result=json.dumps({"outcome": "sold", "gained": 160}),
            ),
            dict(
                target_name="Keeper",
                source="guildjobs:sell:Keeper",
                status="error",
                result=json.dumps({"outcome": "refused", "gained": 0}),
            ),
            dict(
                target_name="Keeper", source="guildjobs:train:Keeper", status="applied"
            ),
        ]
        self.assertEqual(
            guildjobs.contributions(rows)["Keeper"],
            {"letters": 2, "items": 16, "sold": 160},
        )

    def test_every_role_gets_its_job_and_the_guild_its_totals(self):
        lineup = {
            "groups": [{"members": [{"name": "Grug"}, {"name": "Raider"}]}],
            "maintenance": [{"name": "Keeper"}],
            "summoners": [{"name": "Warlock"}],
        }
        guildjobs.attach_jobs(
            lineup,
            {"Keeper": "gathers (Herbalism 40/75)"},
            guildjobs.contributions([sent("Keeper")]),
            {"Keeper": {"copper": 25000}},
            family={"Grug"},
        )
        grug, raider = lineup["groups"][0]["members"]
        self.assertNotIn("work", grug)
        self.assertEqual(raider["job"], guildjobs.RAIDER)
        self.assertEqual(
            lineup["maintenance"][0]["work"],
            "farms and gathers for the guild: gathers (Herbalism 40/75); gave 2g in "
            "dues, 12 item(s) in 1 letter(s)",
        )
        self.assertTrue(lineup["summoners"][0]["work"].endswith("gave nothing yet"))
        self.assertEqual(lineup["given"]["by_role"]["maintenance"]["items"], 12)
        self.assertTrue(
            lineup["given"]["said"].startswith("given: maintenance 2g in dues")
        )

    def test_the_page_reads_each_member_from_what_it_can_see(self):
        self.assertEqual(
            guildjobs.page_doing(guildjobs.MAINTENANCE, 12, {H: (40, 75)}, set(), True),
            "gathers (Herbalism 40/75)",
        )
        self.assertEqual(
            guildjobs.page_doing(guildjobs.SUMMONER, 22, {}, {698}, True),
            "summons at its door, and farms near the meeting stone between summons",
        )
        self.assertIn(
            "natural restart",
            guildjobs.page_doing(guildjobs.RAIDER, 60, {}, set(), False),
        )


class AnOlderWorldserver(unittest.TestCase):
    def test_its_answers_are_recognised(self):
        self.assertEqual(
            guildjobs.unsupported_walk(
                "job", "walk-to-spawn gameobject:1", "unknown job mode"
            ),
            "spawn",
        )
        self.assertEqual(
            guildjobs.unsupported_walk(
                "buy", "walk-to-vendor any", "x malformed walk-to-vendor command"
            ),
            "sale",
        )
        self.assertEqual(
            guildjobs.unsupported_walk(
                "job", "walk-to-spawn gameobject:1", "no such spawn in the world"
            ),
            "",
        )


class TheBridgePass(unittest.TestCase):
    tree = ast.parse(BRIDGE)

    def body(self, name):
        fn = next(
            n
            for n in ast.walk(self.tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name
        )
        return ast.get_source_segment(BRIDGE, fn)

    def test_the_loop_is_registered_in_both_lists(self):
        self.assertEqual(BRIDGE.count("self._guild_jobs_loop,"), 2)

    def test_the_pass_plans_through_the_pure_module(self):
        body = self.body("_guild_jobs_once")
        for word in (
            "_fetch_job_facts",
            "guildjobs.plan",
            "guildjobs.assign_doors",
            "self._job_fields",
            "self._run_job_step",
        ):
            self.assertIn(word, body)

    def test_the_facts_go_through_natural_py_and_keep_py(self):
        """One gate and one reservation list, #331's and #330's, not copies."""
        self.assertIn("_natural_contributors(", self.body("_fetch_job_facts"))
        self.assertIn(
            "kept=await asyncio.to_thread(_KEEP.now)", self.body("_guild_jobs_once")
        )
        reads = BRIDGE[
            BRIDGE.index("_JOB_MEMBERS_SQL = (") : BRIDGE.index("def _job_read(")
        ]
        self.assertNotIn("overseer_keep", reads)
        self.assertNotIn("overseer_naturalized", reads)

    def test_it_never_gives_or_uses_a_gm_command(self):
        for name in ("_guild_jobs_once", "_run_job_step", "_job_row", "_job_fields"):
            body = self.body(name)
            self.assertNotIn("_insert_gm", body)
            self.assertNotIn("_insert_give", body)
            self.assertNotIn("'give'", body)

    def test_a_field_is_a_node_spawn_the_world_surveyed(self):
        body = self.body("_job_fields")
        self.assertIn("gatheraim.choose(", body)
        self.assertIn("_survey_job_nodes", body)
        self.assertIn("spawn=int(spawn.guid)", body)
        self.assertIn("g.guid", BRIDGE[BRIDGE.index("_JOB_NODE_SQL = (") :])

    def test_an_older_worldserver_is_remembered_for_an_hour(self):
        self.assertIn(
            "guildjobs.unsupported_walk", self.body("_note_job_walk_unsupported")
        )
        self.assertIn(
            "guildroute.WALK_UNSUPPORTED_SECONDS",
            self.body("_note_job_walk_unsupported"),
        )


class ThePage(unittest.TestCase):
    def test_the_lineup_endpoint_attaches_every_members_job(self):
        lineup = SERVER[SERVER.index("    def _lineup(") :]
        self.assertIn("guildjobs.attach_jobs(", lineup)
        self.assertIn("guildjobs.contributions(", lineup)
        self.assertIn("guildjobs.page_doing(", SERVER)

    def test_the_page_draws_the_guilds_totals(self):
        self.assertIn("g.given.said", PAGE)
        self.assertIn("farm there between summons", PAGE)

    def test_the_module_ships_in_the_image(self):
        self.assertIn("guildjobs.py", DOCKERFILE)

    def test_walk_caps_are_the_guild_passes_own(self):
        self.assertEqual(guildjobs.FIELD_REACH, 400.0)
        self.assertEqual(guildroute.errand_cap_word(20000), " max:20000")


if __name__ == "__main__":
    unittest.main()
