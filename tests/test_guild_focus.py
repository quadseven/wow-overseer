"""The guild focus (GUILD_FOCUS): one guild crafts and farms, the other runs
dungeons (the operator, 2026-10-05).

A craft-focus guild gives every free member the trade work a maintenance
member has: farm the fields its gathering trades open and cast what its
crafting trades allow, natural or not for those two, since neither is a
contribution. A dungeon-focus guild, and any guild not named, keeps its jobs.
"""

import ast
import pathlib
import unittest

import craft
import guildjobs

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

H, M, S = guildjobs.HERBALISM, guildjobs.MINING, guildjobs.SKINNING
FA, TAILOR = guildjobs.FIRST_AID, guildjobs.TAILORING
LEATHERWORKING, ALCHEMY = 165, 171
LINEN, SCRAPS, PEACEBLOOM, SILVERLEAF, VIAL = 2589, 2934, 2447, 765, 3371
CRAFT = {"Cave": "craft", "Bonkers": "dungeon"}


def member(name, role=guildjobs.RAIDER, **over):
    base = dict(
        name=name,
        guild="Cave",
        role=role,
        level=12,
        class_id=1,
        race=1,
        online=True,
        map_id=0,
        x=-9000.0,
        y=100.0,
        money=5000,
        eligible=True,
        skills={FA: (10, 75), H: (40, 75), ALCHEMY: (10, 75)},
    )
    base.update(over)
    return guildjobs.Member(**base)


def stack(guid, entry, count, subclass=5, item_class=7, quality=1):
    return guildjobs.Carried(
        guid=guid,
        entry=entry,
        count=count,
        item_class=item_class,
        subclass=subclass,
        quality=quality,
        sell_price=5,
        name="item %d" % entry,
    )


def field_spot(x=-8000.0):
    return guildjobs.Spot("gameobject", 4242, 0, x, 100.0, "Copper veins", "in band")


def plan(members, **kw):
    kw.setdefault("masters", {"Cave": "Grug", "Bonkers": "Zug"})
    return guildjobs.plan(members, **kw)


def step_of(result, name):
    steps = [s for s in result.steps if s.holder == name]
    return steps[0] if steps else None


class TheSetting(unittest.TestCase):
    def test_it_parses_guild_focus_pairs(self):
        self.assertEqual(
            guildjobs.parse_focus("Cave:craft,Bonkers:dungeon"),
            {"Cave": "craft", "Bonkers": "dungeon"},
        )

    def test_junk_pairs_are_dropped(self):
        self.assertEqual(
            guildjobs.parse_focus(" Cave : CRAFT ,Bonkers,:craft,Zed:raid,"),
            {"Cave": "craft"},
        )

    def test_unset_is_off(self):
        self.assertEqual(guildjobs.focus_from_env({}), {})
        self.assertEqual(
            guildjobs.focus_from_env({"GUILD_FOCUS": "Cave:craft"}), {"Cave": "craft"}
        )

    def test_guild_names_match_without_case(self):
        self.assertEqual(guildjobs.focus_of("cave", {"Cave": "craft"}), "craft")
        self.assertEqual(guildjobs.focus_of("Bonkers", {"Cave": "craft"}), "")


class ACraftGuild(unittest.TestCase):
    def test_a_raider_with_linen_crafts_only_under_craft_focus(self):
        m = member("Rok", carried=(stack(1, LINEN, 6),))
        self.assertIsNone(step_of(plan([m]), "Rok"))
        step = step_of(plan([m], focus=CRAFT), "Rok")
        self.assertEqual(step.action, "craft")
        self.assertEqual(step.rows[0].command, "3275")
        self.assertEqual(step.repeat, 6)

    def test_a_raider_far_from_its_field_walks_there_only_under_craft_focus(self):
        m = member("Rok")
        fields = {"Rok": field_spot()}
        self.assertIsNone(step_of(plan([m], fields=fields), "Rok"))
        step = step_of(plan([m], fields=fields, focus=CRAFT), "Rok")
        self.assertEqual(step.action, "farm")
        self.assertEqual(step.rows[0].command, "walk-to-spawn gameobject:4242")

    def test_a_member_short_of_its_natural_restart_still_crafts_and_farms(self):
        m = member("Rok", eligible=False, carried=(stack(1, LINEN, 4),))
        result = plan([m], focus=CRAFT)
        self.assertEqual(step_of(result, "Rok").action, "craft")
        result = plan(
            [m],
            focus={"Cave": "craft"},
            recent=(guildjobs.Recent("Rok", "craft", 1),),
            fields={"Rok": field_spot()},
        )
        self.assertEqual(step_of(result, "Rok").action, "farm")
        # Without the focus it waits, as before.
        self.assertIsNone(step_of(plan([m]), "Rok"))

    def test_a_member_short_of_its_restart_contributes_nothing(self):
        herbs = stack(2, PEACEBLOOM, 40, subclass=9)
        m = member(
            "Rok",
            role=guildjobs.MAINTENANCE,
            eligible=False,
            money=0,
            carried=(herbs,),
            skills={H: (5, 75)},
        )
        result = plan([m], focus=CRAFT)
        self.assertIsNone(step_of(result, "Rok"))
        self.assertIn("gives nothing", result.lines["Rok"])

    def test_a_natural_raider_trains_a_gathering_trade_of_its_own(self):
        m = member("Rok", skills={FA: (10, 75)})
        result = plan([m], focus=CRAFT)
        self.assertEqual(result.trades["Rok"], (H, M, FA))
        step = step_of(result, "Rok")
        self.assertEqual(step.action, "train")
        self.assertIn("walk-to-trainer skill:", step.rows[0].command)
        self.assertNotIn("Rok", plan([m]).trades)

    def test_a_raider_keeps_the_cloth_its_casts_eat(self):
        m = member("Rok", carried=(stack(1, LINEN, 25),))
        self.assertEqual(guildjobs.postable(m, None), [m.carried[0]])
        self.assertEqual(guildjobs.postable(m, None, crafting=True), [])

    def test_a_member_in_a_guild_run_is_left_alone(self):
        m = member("Rok", carried=(stack(1, LINEN, 6),))
        result = plan([m], focus=CRAFT, busy={"Rok"})
        self.assertIsNone(step_of(result, "Rok"))
        self.assertIn("Rok is already on another guild walk", result.notes)

    def test_the_family_is_never_given_trade_work(self):
        m = member("Grug", role=guildjobs.FAMILY, carried=(stack(1, LINEN, 6),))
        result = plan([m], focus=CRAFT)
        self.assertEqual(result.steps, ())
        self.assertNotIn("Grug", result.lines)

    def test_a_summoner_with_a_door_keeps_its_door(self):
        stone = guildjobs.Spot("gameobject", 77, 0, 0.0, 0.0, "a meeting stone")
        door = guildjobs.Door("rfc", "Ragefire Chasm", 13, 18, stone)
        m = member(
            "Lok",
            role=guildjobs.SUMMONER,
            level=22,
            known=frozenset({guildjobs.RITUAL_OF_SUMMONING}),
        )
        step = step_of(plan([m], focus=CRAFT, doors={"Lok": door}), "Lok")
        self.assertEqual(step.action, "door")

    def test_a_summoner_without_a_door_works_its_trades(self):
        m = member("Lok", role=guildjobs.SUMMONER, carried=(stack(1, LINEN, 3),))
        step = step_of(plan([m], focus=CRAFT), "Lok")
        self.assertEqual(step.action, "craft")


class TheOtherGuilds(unittest.TestCase):
    def test_a_dungeon_guild_and_an_unnamed_guild_are_unchanged(self):
        crew = [
            member("Zed", guild="Bonkers", carried=(stack(1, LINEN, 6),)),
            member("Ned", guild="Other", eligible=False, carried=(stack(2, LINEN, 6),)),
            member("Mo", guild="Bonkers", role=guildjobs.MAINTENANCE),
        ]
        fields = {"Zed": field_spot(), "Ned": field_spot()}
        before = plan(crew, fields=fields)
        after = plan(crew, fields=fields, focus=CRAFT)
        self.assertEqual(before.steps, after.steps)
        self.assertEqual(before.lines, after.lines)
        self.assertEqual(before.trades, after.trades)


class TheLog(unittest.TestCase):
    def test_each_pass_says_each_guilds_focus_and_its_counts(self):
        crew = [
            member("Rok", carried=(stack(1, LINEN, 6),)),
            member("Tak", carried=(stack(2, LINEN, 6),), eligible=False),
            member("Fen"),
            member("Sat", x=-8000.0),
            member("Zed", guild="Bonkers"),
        ]
        fields = {"Fen": field_spot(), "Sat": field_spot()}
        result = plan(crew, fields=fields, focus=CRAFT)
        self.assertEqual(
            result.focus["Cave"],
            {"focus": "craft", "members": 4, "craft": 2, "farm": 1, "gathering": 1},
        )
        self.assertEqual(
            guildjobs.focus_lines(result),
            [
                "Bonkers: focus dungeon: 1 member(s) keep their jobs; the guild "
                "social pass's dungeon asks and runs are unchanged",
                "Cave: focus craft: 4 member(s); 2 took a craft step, 1 a farm "
                "step, 1 gather in their field",
            ],
        )

    def test_unset_says_nothing(self):
        self.assertEqual(guildjobs.focus_lines(plan([member("Rok")])), [])


class EveryCraftingTrade(unittest.TestCase):
    """_craft_step covers every crafting trade craft.RECIPES carries."""

    def test_a_leatherworker_cures_its_scraps(self):
        m = member(
            "Hide",
            role=guildjobs.MAINTENANCE,
            skills={FA: (60, 75), LEATHERWORKING: (1, 75), H: (40, 75)},
            carried=(stack(1, SCRAPS, 9, subclass=6),),
        )
        step = step_of(plan([m]), "Hide")
        self.assertEqual(step.action, "craft")
        self.assertEqual(step.rows[0].command, "2881")
        self.assertEqual(step.repeat, 3)
        self.assertIn("to raise its Leatherworking", step.said)

    def test_a_bought_reagent_must_be_carried_too(self):
        herbs = (
            stack(1, PEACEBLOOM, 5, subclass=9),
            stack(2, SILVERLEAF, 5, subclass=9),
        )
        m = member(
            "Brew",
            role=guildjobs.MAINTENANCE,
            skills={FA: (60, 75), ALCHEMY: (1, 75), H: (40, 75)},
            carried=herbs,
        )
        step = step_of(plan([m]), "Brew")
        self.assertTrue(step is None or step.action != "craft")
        vials = guildjobs.Member(
            **{
                **m.__dict__,
                "carried": herbs + (stack(3, VIAL, 2, item_class=0, subclass=0),),
            }
        )
        step = step_of(plan([vials]), "Brew")
        self.assertEqual(step.rows[0].command, "2330")
        self.assertEqual(step.repeat, 2)

    def test_a_recipe_that_needs_a_forge_is_never_cast_in_place(self):
        m = member(
            "Ore",
            role=guildjobs.MAINTENANCE,
            skills={FA: (60, 75), M: (1, 75), H: (40, 75)},
            carried=(
                stack(1, 2770, 20, subclass=7),
                stack(2, guildjobs.MINING_PICK, 1, item_class=2, subclass=20),
            ),
        )
        # Mining is a crafting trade here (Smelt Copper), but its cast needs
        # a forge, so nothing is cast where the member stands.
        self.assertIn(M, guildjobs.CRAFT_SKILLS)
        self.assertIsNone(guildjobs._craft_step(m))
        self.assertEqual(step_of(plan([m]), "Ore").action, "post")

    def test_every_auto_learned_recipe_is_a_real_recipe(self):
        # craft.py's list of nine auto-learned first rungs.
        nine = {3275, 2963, 3918, 2657, 2330, 2660, 2881, 2152, 9058}
        self.assertEqual(guildjobs.AUTO_LEARNED, nine)
        self.assertLessEqual(guildjobs.AUTO_LEARNED, guildjobs.CRAFT_SPELLS)
        named = {r.spell_id for recipes in craft.RECIPES.values() for r in recipes}
        self.assertLessEqual(guildjobs.AUTO_LEARNED, named)


class TheField(unittest.TestCase):
    def test_a_craft_guilds_online_members_want_a_field_natural_or_not(self):
        m = member("Rok", eligible=False)
        self.assertFalse(guildjobs.wants_field(m, {}))
        self.assertTrue(guildjobs.wants_field(m, CRAFT))
        self.assertFalse(guildjobs.wants_field(member("Rok", online=False), CRAFT))
        self.assertFalse(guildjobs.wants_field(member("Zed", guild="Bonkers"), CRAFT))

    def test_a_natural_maintenance_member_wants_one_as_before(self):
        m = member("Mo", role=guildjobs.MAINTENANCE)
        self.assertTrue(guildjobs.wants_field(m))


class TheBridge(unittest.TestCase):
    tree = ast.parse(BRIDGE)

    def body(self, name):
        fn = next(
            n
            for n in ast.walk(self.tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name
        )
        return ast.get_source_segment(BRIDGE, fn)

    def test_the_pass_reads_the_focus_and_hands_it_to_the_plan(self):
        body = self.body("_plan_guild_jobs")
        self.assertIn("guildjobs.focus_from_env()", body)
        self.assertIn("focus=focus", body)
        self.assertIn("self._job_fields(members, focus, busy)", body)

    def test_fields_follow_the_focus(self):
        self.assertIn("guildjobs.wants_field(m, focus)", self.body("_job_fields"))

    def test_the_pass_logs_each_guilds_focus(self):
        self.assertIn("guildjobs.focus_lines(plan)", self.body("_log_guild_job_plan"))


if __name__ == "__main__":
    unittest.main()
