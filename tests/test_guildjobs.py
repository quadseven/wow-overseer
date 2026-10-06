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
    # A member that already holds First Aid, so the older tests read the
    # gathering, post and sale steps they were written for; the cloth trades
    # have their own tests (TheClothTrades).
    skills = dict(base.get("skills") or {})
    skills.setdefault(guildjobs.FIRST_AID, (40, 75))
    base["skills"] = skills
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


LINEN = 2589
FA, TAILOR = guildjobs.FIRST_AID, guildjobs.TAILORING


def bare(name, **over):
    """A maintenance member with no First Aid, as a natural restart leaves it."""
    over.setdefault("skills", {})
    m = member(name, **over)
    return guildjobs.Member(
        **{
            **{f: getattr(m, f) for f in m.__dataclass_fields__},
            "skills": dict(over["skills"]),
        }
    )


class TheClothTrades(unittest.TestCase):
    """Cloth the maintenance crew loots has a consumer that is not the family
    (the operator, 2026-09-29): First Aid for all, Tailoring for a third."""

    def test_every_maintenance_member_is_sent_to_learn_first_aid(self):
        m = bare("Keeper", level=12, money=100, skills={H: (40, 75), 171: (10, 75)})
        step = only_step(plan([m]), "Keeper")
        self.assertEqual(step.action, "train")
        self.assertEqual(step.rows[0].command, "walk-to-trainer skill:129")
        self.assertIn("learn First Aid (up to 75, 100c)", step.said)

    def test_first_aid_takes_no_primary_slot(self):
        crew = [bare("M%02d" % i) for i in range(10)]
        trades = plan(crew).trades
        for held in trades.values():
            self.assertIn(FA, held)
            self.assertLessEqual(
                len([s for s in held if s in guildjobs.PRIMARY_SKILLS]), 2
            )

    def test_a_third_of_a_crew_takes_tailoring_and_one_gathering_trade(self):
        crew = [bare("M%02d" % i) for i in range(10)]
        trades = plan(crew).trades
        tailors = [n for n, t in trades.items() if TAILOR in t]
        self.assertEqual(len(tailors), 3)
        for name in tailors:
            gathering = [s for s in trades[name] if s in guildjobs.GATHERING]
            self.assertEqual(len(gathering), 1)
        for name in set(trades) - set(tailors):
            self.assertEqual(
                len([s for s in trades[name] if s in guildjobs.GATHERING]), 2
            )

    def test_a_small_crew_has_no_tailor(self):
        self.assertEqual(guildjobs.choose_tailors([bare("A"), bare("B")]), frozenset())

    def test_a_member_with_both_primaries_taken_is_no_tailor(self):
        crew = [bare("F%d" % i, skills={H: (5, 75), M: (5, 75)}) for i in range(3)]
        self.assertEqual(guildjobs.choose_tailors(crew), frozenset())

    def test_a_held_tailor_is_kept_a_tailor(self):
        crew = [bare("A"), bare("B"), bare("C", skills={TAILOR: (20, 75)})]
        self.assertEqual(guildjobs.choose_tailors(crew), frozenset({"C"}))

    def test_raiders_and_summoners_learn_no_cloth_trade(self):
        crew = [member("R", role=guildjobs.RAIDER)]
        self.assertEqual(plan(crew).trades, {})

    def test_tailoring_is_bought_at_level_5_for_ten_copper(self):
        crew = [
            bare("T%d" % i, level=5, money=10, skills={FA: (40, 75), H: (40, 75)})
            for i in range(3)
        ]
        result = plan(crew)
        tailor = next(n for n, t in result.trades.items() if TAILOR in t)
        step = only_step(result, tailor)
        self.assertEqual(step.rows[0].command, "walk-to-trainer skill:%d" % TAILOR)
        self.assertIn("learn Tailoring (up to 75, 10c)", step.said)

    def test_a_first_aider_with_linen_casts_bandages(self):
        m = member(
            "Medic",
            skills={FA: (10, 75), H: (40, 75), 171: (10, 75)},
            carried=(stack(1, LINEN, 14, subclass=5),),
        )
        step = only_step(plan([m]), "Medic")
        self.assertEqual(step.action, "craft")
        (row,) = step.rows
        self.assertEqual((row.kind, row.command), ("cast", "3275"))
        self.assertEqual(row.source, "guildjobs:craft:Medic")
        self.assertEqual(step.repeat, 10)
        self.assertIn("crafts 10 Linen Bandage to raise its First Aid", step.said)

    def test_a_batch_is_what_the_cloth_allows(self):
        m = member(
            "Medic",
            skills={FA: (10, 75), H: (40, 75), 171: (10, 75)},
            carried=(stack(1, LINEN, 3, subclass=5),),
        )
        self.assertEqual(only_step(plan([m]), "Medic").repeat, 3)

    def test_no_cloth_no_craft(self):
        m = member("Medic", skills={FA: (10, 75), H: (40, 75), 171: (10, 75)})
        self.assertIsNone(only_step(plan([m]), "Medic"))

    def test_bandages_stop_at_the_grey_skill(self):
        m = member(
            "Medic",
            skills={FA: (60, 75), H: (40, 75), 171: (10, 75)},
            carried=(stack(1, LINEN, 14, subclass=5),),
        )
        step = only_step(plan([m]), "Medic")
        self.assertTrue(step is None or step.action != "craft")

    def test_a_tailor_with_linen_casts_bolts_once_first_aid_is_grey(self):
        # First Aid's own rung (Silk Bandage, bought) has no silk to eat.
        m = member(
            "Sew",
            skills={FA: (150, 225), TAILOR: (5, 75), H: (40, 75)},
            known=frozenset({7928}),
            carried=(stack(1, LINEN, 7, subclass=5),),
        )
        step = only_step(plan([m]), "Sew")
        self.assertEqual(step.rows[0].command, "2963")
        self.assertEqual(step.repeat, 3)

    def test_a_craft_waits_out_its_cooldown(self):
        m = member(
            "Medic",
            skills={FA: (10, 75), H: (40, 75), 171: (10, 75)},
            carried=(stack(1, LINEN, 14, subclass=5),),
        )
        recent = (guildjobs.Recent("Medic", "craft", 5),)
        self.assertIsNone(only_step(plan([m], recent=recent), "Medic"))

    def test_a_recipe_the_member_does_not_know_is_not_cast(self):
        # Bolt of Woolen Cloth is a trainer purchase, not part of Apprentice.
        m = member(
            "Sew",
            skills={FA: (150, 225), TAILOR: (70, 75), H: (40, 75)},
            known=frozenset({7928}),
            carried=(stack(1, 2592, 9, subclass=5),),
        )
        step = only_step(plan([m]), "Sew")
        self.assertTrue(step is None or step.action != "craft")
        known = guildjobs.Member(
            **{
                **{f: getattr(m, f) for f in m.__dataclass_fields__},
                "known": frozenset({2964, 7928}),
            }
        )
        step = only_step(plan([known]), "Sew")
        self.assertEqual(step.rows[0].command, "2964")

    def test_the_bridge_reads_the_craft_spells_and_repeats_the_cast(self):
        self.assertIn("guildjobs.CRAFT_SPELLS", BRIDGE)
        tree = ast.parse(BRIDGE)
        run = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_job_step"
        )
        self.assertIn("step.repeat", ast.unparse(run))
        # A batch that stops early says how many casts landed.
        self.assertIn("stopped after %d of %d casts", ast.unparse(run))


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


WOOL = 2592


class TheBandageLadder(unittest.TestCase):
    """Past Linen Bandage's grey every bandage is a trainer purchase, so a crew
    member buys the rung its First Aid has reached, then casts it (operator,
    2026-10-05: "craft and get all recipes")."""

    def medic(self, value, cap, known=frozenset(), carried=()):
        return member(
            "Medic",
            skills={FA: (value, cap), H: (40, 75), 171: (10, 75)},
            known=known,
            carried=carried,
        )

    def test_it_walks_to_a_trainer_for_the_rung_it_has_reached(self):
        step = only_step(plan([self.medic(80, 150)]), "Medic")
        self.assertEqual(step.action, "train")
        self.assertEqual(step.rows[0].command, "walk-to-trainer skill:129 learn:3277")
        self.assertIn("learn Wool Bandage", step.said)

    def test_once_known_it_casts_the_rung_from_its_wool(self):
        m = self.medic(
            80,
            150,
            known=frozenset({3277}),
            carried=(stack(1, WOOL, 6, subclass=5),),
        )
        step = only_step(plan([m]), "Medic")
        self.assertEqual(step.action, "craft")
        self.assertEqual(step.rows[0].command, "3277")
        self.assertEqual(step.repeat, 6)

    def test_linen_bandage_needs_no_trainer(self):
        self.assertIsNone(guildjobs.bandage_to_learn(self.medic(40, 75)))

    def test_a_failed_learn_walk_cools_down_on_the_skill(self):
        failed = (guildjobs.Recent("Medic", "train", 30, "error", FA),)
        step = only_step(plan([self.medic(80, 150)], recent=failed), "Medic")
        self.assertTrue(step is None or step.action != "train")


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


class ATrainerWalkThatKeepsFailing(unittest.TestCase):
    """#766: a level 1 hunter was sent to a skinning trainer every hour for a
    day, and every walk died on the way or found the ground did not hold."""

    def failed(self, *ages, status="error"):
        return tuple(guildjobs.Recent("Keeper", "train", a, status) for a in ages)

    def test_a_level_1_skinner_is_not_walked_to_a_trainer(self):
        # The second of two takes skinning, whose apprentice asks no level.
        crew = [member("A"), member("Keeper", level=1, money=500)]
        self.assertIn(S, guildjobs.split_trades(crew)["Keeper"])
        result = plan(crew)
        step = only_step(result, "Keeper")
        self.assertTrue(step is None or step.action != "train")
        self.assertIn("Keeper learns a trade from level 5", result.notes)

    def test_at_level_5_it_is(self):
        m = member("Keeper", level=5, money=500)
        step = only_step(plan([m]), "Keeper")
        self.assertEqual(step.action, "train")

    def test_one_failed_walk_waits_two_hours(self):
        self.assertEqual(guildjobs.train_cooldown("Keeper", self.failed(61)), 120)
        m = member("Keeper", level=10, money=500)
        self.assertIsNone(only_step(plan([m], recent=self.failed(61)), "Keeper"))
        self.assertEqual(
            only_step(plan([m], recent=self.failed(121)), "Keeper").action, "train"
        )

    def test_each_failure_in_a_row_doubles_the_wait_up_to_the_cap(self):
        self.assertEqual(guildjobs.train_cooldown("Keeper", ()), 60)
        self.assertEqual(
            guildjobs.train_cooldown("Keeper", self.failed(60, 120, 180)), 480
        )
        hourly = self.failed(*range(5, 24 * 60, 60), status="unchanged")
        self.assertEqual(guildjobs.train_cooldown("Keeper", hourly), 720)
        m = member("Keeper", level=10, money=500)
        self.assertIsNone(
            only_step(plan([m], recent=self.failed(*range(65, 600, 60))), "Keeper")
        )

    def test_a_walk_that_taught_resets_the_wait(self):
        recent = (
            guildjobs.Recent("Keeper", "train", 70, "applied"),
            guildjobs.Recent("Keeper", "train", 130, "error"),
            guildjobs.Recent("Keeper", "train", 190, "error"),
        )
        self.assertEqual(guildjobs.train_cooldown("Keeper", recent), 60)

    def test_another_members_failures_do_not_count(self):
        other = (guildjobs.Recent("Other", "train", 61, "error"),)
        self.assertEqual(guildjobs.train_cooldown("Keeper", other), 60)

    def test_a_failed_walk_cools_only_its_skill(self):
        recent = (guildjobs.Recent("Keeper", "train", 5, "error", S),)
        self.assertEqual(guildjobs.train_cooldown("Keeper", recent, S), 120)
        self.assertEqual(guildjobs.train_cooldown("Keeper", recent, TAILOR), 60)

    def test_failed_skinning_walk_does_not_block_assigned_tailoring(self):
        crew = [
            bare("A", skills={H: (75, 75), M: (75, 75)}),
            bare("B", skills={H: (75, 75), M: (75, 75)}),
            bare("Keeper", level=10, money=500),
        ]
        initial = plan(crew)
        self.assertIn(TAILOR, initial.trades["Keeper"])
        self.assertIn(S, initial.trades["Keeper"])
        recent = guildjobs.recent_from_rows(
            (
                {
                    "target_name": "Keeper",
                    "command": "walk-to-trainer skill:%d max:20000" % S,
                    "source": "guildjobs:train:Keeper",
                    "status": "unchanged",
                    "age": 5,
                },
            )
        )

        step = only_step(plan(crew, recent=recent), "Keeper")

        self.assertIsNotNone(step)
        self.assertEqual(step.action, "train")
        self.assertEqual(step.rows[0].command, "walk-to-trainer skill:%d" % TAILOR)

    def test_failed_herbalism_walk_does_not_block_first_aid(self):
        medic = bare(
            "Medic",
            level=10,
            money=500,
            skills={H: (75, 75), M: (75, 75)},
        )
        recent = guildjobs.recent_from_rows(
            (
                {
                    "target_name": "Medic",
                    "command": "walk-to-trainer skill:%d max:20000" % H,
                    "source": "guildjobs:train:Medic",
                    "status": "error",
                    "age": 5,
                },
            )
        )

        step = only_step(plan([medic], recent=recent), "Medic")

        self.assertEqual(step.action, "train")
        self.assertEqual(step.rows[0].command, "walk-to-trainer skill:%d" % FA)

    def test_recent_rows_read_the_training_skill_token(self):
        (recent,) = guildjobs.recent_from_rows(
            (
                {
                    "target_name": "Keeper",
                    "command": "walk-to-trainer skill:197 max:20000",
                    "source": "guildjobs:train:Keeper",
                    "status": "error",
                    "age": 5,
                },
            )
        )
        self.assertEqual(recent.skill_id, TAILOR)

        (malformed,) = guildjobs.recent_from_rows(
            (
                {
                    "target_name": "Keeper",
                    "command": "walk-to-trainer skill:bad",
                    "source": "guildjobs:train:Keeper",
                    "status": "error",
                    "age": 5,
                },
            )
        )
        self.assertIsNone(malformed.skill_id)
        self.assertIn('"SELECT target_name, command, source, status, "', BRIDGE)


class ASkinnersField(unittest.TestCase):
    def beast(self, spawn, x, y, level=10, name="Mottled Boar"):
        return (guildjobs.Spot("creature", spawn, 1, x, y, name), level)

    def test_the_cores_skinning_rule(self):
        self.assertEqual(guildjobs.skinnable_level(0), 0)
        self.assertEqual(guildjobs.skinnable_level(1), 10)
        self.assertEqual(guildjobs.skinnable_level(50), 15)
        self.assertEqual(guildjobs.skinnable_level(100), 20)
        self.assertEqual(guildjobs.skinnable_level(300), 60)

    def test_the_band_is_its_level_and_what_its_skill_can_skin(self):
        self.assertEqual(guildjobs.skin_band(12, 30), (6, 13))
        self.assertEqual(guildjobs.skin_band(20, 50), (14, 15))

    def test_the_nearest_dense_pack_in_band_wins(self):
        near = [self.beast(i, 100 + i, 100 + i) for i in range(4)]
        dense_far = [self.beast(10 + i, 2100 + i, 100) for i in range(9)]
        thin = [self.beast(30, 10, 10), self.beast(31, 20, 20)]
        red = [self.beast(40 + i, 50 + i, 50, level=20) for i in range(8)]
        spot = guildjobs.skinning_field(
            near + dense_far + thin + red, (0.0, 0.0), 12, 30
        )
        self.assertEqual(spot.kind, "creature")
        self.assertIn(spot.spawn, {0, 1, 2, 3})
        self.assertIn("6 skinnable beasts of levels 6 to 13", spot.why)

    def test_nothing_in_band_is_no_field(self):
        red = [self.beast(i, 10 + i, 10, level=30) for i in range(8)]
        self.assertIsNone(guildjobs.skinning_field(red, (0.0, 0.0), 12, 30))
        self.assertIsNone(guildjobs.skinning_field([], (0.0, 0.0), 12, 0))

    def test_a_skinner_is_walked_to_its_beasts(self):
        field = guildjobs.Spot("creature", 77, 0, -8000.0, 900.0, "Mottled Boar")
        m = member(
            "Skinner",
            skills={S: (30, 75), 197: (10, 75)},
            carried=(stack(1, 7005, 1, item_class=2),),
        )
        step = only_step(plan([m], fields={"Skinner": field}), "Skinner")
        self.assertEqual(step.rows[0].command, "walk-to-spawn creature:77")


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

    def test_meat_with_every_cook_at_one_goes_to_the_bank(self):
        # #373: ten family members at Cooking 1 made the pick a name
        # tiebreak, and Bork was posted 1,190 items he never opened.
        meat = stack(21, 769, 20, subclass=8, name="Chunk of Boar Meat")
        cooks = {185: [(n, 1) for n in ("Og", "Bork", "Grug", "Ugga", "Grog")]}
        self.assertEqual(
            guildjobs.recipient_for(meat, cooks, "Grug"),
            ("Grug", "the guild bank's Materials tab"),
        )

    def test_cloth_goes_only_to_a_tailor_who_can_work_it(self):
        linen = stack(22, 2589, 20, subclass=5, name="Linen Cloth")
        # Tailoring 1 is under the floor; Tailoring 30 can cast Bolt of Linen.
        self.assertEqual(
            guildjobs.recipient_for(linen, {197: [("Bork", 1)]}, "Grug")[0], "Grug"
        )
        self.assertEqual(
            guildjobs.recipient_for(linen, {197: [("Bork", 1), ("Og", 30)]}, "Grug"),
            ("Og", "its crafter"),
        )

    def test_a_crafter_with_posts_unopened_is_sent_nothing_new(self):
        m = member(
            "Keeper",
            skills={H: (40, 75), M: (40, 75)},
            carried=(
                stack(11, 2447, 12, subclass=9, name="Peacebloom"),
                stack(13, 2901, 1, item_class=2),
            ),
        )
        crafters = {"Cave": {171: [("Ugga", 60), ("Og", 90)]}}

        def rows(result):
            return [(x.command, x.target_arg) for x in only_step(result, "Keeper").rows]

        self.assertEqual(
            rows(plan([m], crafters=crafters, unclaimed={"Og"})),
            [("send item:11 subject:Guild materials", "Ugga")],
        )
        self.assertEqual(
            rows(plan([m], crafters=crafters, unclaimed={"Og", "Ugga"})),
            [("send item:11 subject:Guild materials", "Grug")],
        )

    def test_a_guild_with_no_bank_tab_posts_nothing_to_its_master(self):
        """#395: Bonkers owned no bank tab on 2026-09-28, and every pass posted
        meat, eggs and linen to Zug 'for the Materials tab'."""
        m = member(
            "Keeper",
            guild="Bonkers",
            skills={H: (40, 75), M: (40, 75)},
            carried=(
                stack(21, 769, 20, subclass=8, name="Chunk of Boar Meat"),
                stack(13, 2901, 1, item_class=2),
            ),
        )
        step = only_step(plan([m], banks={"Cave"}), "Keeper")
        self.assertTrue(step is None or step.action != "post", step)
        step = only_step(plan([m], banks={"Cave", "Bonkers"}), "Keeper")
        self.assertEqual([r.target_arg for r in step.rows], ["Zug"])

    def test_a_master_with_a_post_unopened_is_sent_nothing_new(self):
        m = member(
            "Keeper",
            skills={H: (40, 75), M: (40, 75)},
            carried=(
                stack(21, 769, 20, subclass=8, name="Chunk of Boar Meat"),
                stack(13, 2901, 1, item_class=2),
            ),
        )
        step = only_step(plan([m], banks={"Cave"}, unclaimed={"Grug"}), "Keeper")
        self.assertTrue(step is None or step.action != "post", step)
        self.assertEqual(
            guildjobs.bank_masters({"Cave": "Grug"}, None, ()), {"Cave": "Grug"}
        )

    def test_the_pass_reads_the_guild_bank_tabs(self):
        self.assertIn(
            "guild_bank_tab", BRIDGE[BRIDGE.index("_JOB_BANK_TABS_SQL = (") :]
        )
        self.assertIn('banks=facts.get("banks")', BRIDGE)

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

    def test_a_skinner_with_no_node_trade_hunts_surveyed_beasts(self):
        body = self.body("_job_fields")
        self.assertIn("_survey_job_beasts", body)
        self.assertIn("guildjobs.skinning_field(", body)
        self.assertIn("c.guid", BRIDGE[BRIDGE.index("_JOB_BEAST_SQL = (") :])

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
