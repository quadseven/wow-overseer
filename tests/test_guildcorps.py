"""The guild crafting corps: posts, a tailor's next step, and the page.

Pure unit tests against guildcorps.py, plus source checks on the bridge pass,
the lineup endpoint and the page. The fixtures are the dev realm as measured
on 2026-09-23: maintenance members are random bots holding four to six trades
at 300, tailors who know every trainer bag up to Mageweave, a Runecloth Bag
pattern sold only in Everlook, and a Horde family on six-slot pouches.
"""

import pathlib
import unittest

import guildcorps as gc

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

# The recipes every 300 tailor on dev knew (character_spell, 2026-09-23).
KNOWN_300 = frozenset({2964, 3755, 3757, 3813, 3839, 3865, 12065, 18401, 26745})
EVERLOOK = 1
OUTLAND = 530
# Map 1 (Kalimdor): Qia sells the Runecloth Bag pattern and Rune Thread; its
# trainers teach up to Artisan. Map 530: the Master rank and the netherweave
# recipes are taught there.
TRAINABLE = {
    EVERLOOK: frozenset(
        {2964, 3755, 3757, 3813, 3839, 3865, 12065, 18401, 3912, 3913, 12181}
    ),
    OUTLAND: frozenset({18401, 26745, 26746, 26791, 12181}),
}
VENDORS = {
    EVERLOOK: frozenset({14468, 14341, 2320, 2321, 4291}),
    OUTLAND: frozenset({14341}),
}


def member(name, guild="Cave", **over):
    base = dict(
        name=name,
        guild=guild,
        class_id=8,
        level=60,
        online=True,
        map_id=EVERLOOK,
        maintenance=True,
    )
    base.update(over)
    return gc.Member(**base)


def tailor(name="Derred", value=300, cap=300, **over):
    over.setdefault("known", KNOWN_300)
    over.setdefault("skills", {gc.TAILORING: (value, cap)})
    return member(name, **over)


def held(entry, count=20, guid=None):
    return gc.Held(guid or entry * 10 + count, entry, count)


def family(name, bags, guild="Cave"):
    return member(
        name, guild=guild, maintenance=False, family=True, worn_bags=tuple(bags)
    )


def step_of(t, members=(), fam=(), trainable=None, vendors=None):
    trainable = TRAINABLE.get(t.map_id, frozenset()) if trainable is None else trainable
    vendors = VENDORS.get(t.map_id, frozenset()) if vendors is None else vendors
    return gc.tailor_step(t, [t, *members], fam, trainable, vendors)


class TheMeasuredRecipes(unittest.TestCase):
    def test_the_bags_read_from_the_worldserver(self):
        bags = {r.name: r for r in gc.BAGS}
        runecloth = bags["Runecloth Bag"]
        self.assertEqual(runecloth.slots, 14)
        self.assertEqual(runecloth.learn_rank, 260)
        self.assertEqual(runecloth.reagents, ((14048, 5), (8170, 2), (14341, 1)))
        self.assertEqual((runecloth.source, runecloth.pattern), ("pattern", 14468))
        nether = bags["Netherweave Bag"]
        self.assertEqual((nether.slots, nether.learn_rank), (16, 315))
        self.assertEqual(nether.reagents, ((21840, 4), (14341, 1)))
        self.assertEqual(bags["Mooncloth Bag"].pattern, 14499)

    def test_every_bolt_is_what_a_bag_asks_for(self):
        for bag in gc.BAGS:
            for entry, _ in bag.reagents:
                if entry in gc.THREAD_PRICE:
                    continue
                if entry in gc.BOLT_OF:
                    self.assertIn(gc.BOLT_OF[entry].spell, gc.PATH_SPELLS)

    def test_no_bag_grants_itself(self):
        """Every bag is made of items, never of nothing."""
        for bag in gc.BAGS:
            self.assertTrue(bag.reagents)


class ThePosts(unittest.TestCase):
    def test_a_guild_officer_fills_the_tailors_first(self):
        crew = [
            member(
                "Derred", skills={gc.TAILORING: (300, 300), gc.HERBALISM: (306, 375)}
            ),
            member("Baldam", skills={gc.TAILORING: (300, 375)}),
            member("Behodiir", online=False, skills={gc.TAILORING: (300, 300)}),
            member("Goraraa", skills={gc.TAILORING: (50, 50), gc.MINING: (300, 375)}),
            member("Beerix", skills={gc.SKINNING: (300, 300), gc.MINING: (301, 375)}),
        ]
        posts = gc.plan_corps(crew)["Cave"]
        roles = {p.name: p.role for p in posts}
        # The higher ceiling first, then the online one of two equals.
        self.assertEqual(
            [p.name for p in posts if p.role == "tailor"], ["Baldam", "Derred"]
        )
        self.assertEqual(roles["Beerix"], "skinner")
        self.assertEqual(roles["Goraraa"], "miner")
        self.assertNotIn("Behodiir", roles)
        self.assertEqual(len(roles), len(posts), "one post per member")

    def test_only_maintenance_members_hold_posts(self):
        crew = [
            member(
                "Og", maintenance=False, family=True, skills={gc.TAILORING: (50, 150)}
            ),
            member("Derred", skills={gc.TAILORING: (300, 300)}),
        ]
        self.assertEqual([p.name for p in gc.plan_corps(crew)["Cave"]], ["Derred"])

    def test_the_post_reads_as_a_sentence(self):
        post = gc.Post("Derred", "tailor", gc.TAILORING, 300, 300)
        self.assertEqual(post.said, "tailor Tailoring 300/300")


class ATailorsNextStep(unittest.TestCase):
    def test_at_its_ceiling_it_walks_to_a_trainer_for_the_next_rank(self):
        t = tailor(
            "Xohjaz", guild="Bonkers", map_id=OUTLAND, carried=(held(21877, 15),)
        )
        step, _ = step_of(t)
        self.assertEqual(step.action, "train")
        self.assertIsNone(step.walk)
        self.assertEqual(step.rows[0].kind, "cast")
        self.assertEqual(step.rows[0].command, "walk-to-trainer skill:197")
        self.assertEqual(step.rows[0].source, "guildcorps:train:26791")

    def test_a_trainer_recipe_its_skill_allows_is_named(self):
        t = tailor("Baldam", 305, 375, map_id=OUTLAND, known=KNOWN_300 - {26745})
        crew = [member("Baleron", carried=(held(21877, 20),))]
        step, _ = step_of(t, crew)
        self.assertEqual(step.rows[0].command, "walk-to-trainer skill:197 learn:26745")

    def test_no_trainer_on_the_map_means_no_walk(self):
        t = tailor("Derred", carried=(held(14047, 5),))
        step, _ = step_of(t, trainable=frozenset({3912}))
        self.assertNotEqual(getattr(step, "action", None), "train")

    def test_the_runecloth_bag_starts_with_its_pattern_at_the_vendor(self):
        crew = [member("Alylienne", carried=(held(14047, 20),)), member("Beerix")]
        crew[1] = member("Beerix", carried=(held(8170, 20),))
        step, _ = step_of(tailor(), crew)
        self.assertEqual(step.action, "buy")
        self.assertEqual(step.walk.kind, "buy")
        self.assertEqual(step.walk.command, "walk-to-vendor item:14468")
        self.assertEqual(step.rows[0].command, "entry:14468 count:1 max:15000")

    def test_a_carried_pattern_is_used(self):
        crew = [member("Alylienne", carried=(held(14047, 20),))]
        crew.append(member("Beerix", carried=(held(8170, 20),)))
        t = tailor(carried=(gc.Held(777, 14468, 1),))
        step, _ = step_of(t, crew)
        self.assertEqual(step.action, "learn")
        self.assertEqual(step.rows[0].command, "use guid:777")

    def test_bolts_first_then_thread_then_the_bag(self):
        known = KNOWN_300 | {18405}
        cloth = tailor(known=known, carried=(held(14047, 20), held(8170, 2)))
        step, _ = step_of(cloth)
        self.assertEqual((step.action, step.key, step.repeat), ("craft", 18401, 5))
        self.assertEqual(step.rows[0].command, "18401")

        bolts = tailor(known=known, carried=(held(14048, 5), held(8170, 2)))
        step, _ = step_of(bolts)
        self.assertEqual((step.action, step.key), ("buy", 14341))
        self.assertEqual(step.walk.command, "walk-to-vendor item:14341")
        self.assertEqual(step.rows[0].command, "entry:14341 count:1 max:6250")

        ready = tailor(
            known=known, carried=(held(14048, 5), held(8170, 2), held(14341, 1))
        )
        step, _ = step_of(ready)
        self.assertEqual((step.action, step.key, step.repeat), ("craft", 18405, 1))

    def test_thread_is_not_bought_before_the_cloth_is_in_hand(self):
        crew = [member("Alylienne", carried=(held(14047, 20),))]
        crew.append(member("Beerix", carried=(held(8170, 20),)))
        t = tailor(known=KNOWN_300 | {18405})
        step, why = step_of(t, crew)
        self.assertIsNone(step)
        self.assertIn("Runecloth Bag", why)

    def test_below_its_ceiling_it_crafts_skill_ups(self):
        t = tailor(
            "Baldam",
            305,
            375,
            map_id=OUTLAND,
            carried=(held(21877, 20), held(21877, 20)),
        )
        step, _ = step_of(t)
        self.assertEqual((step.action, step.key, step.repeat), ("craft", 26745, 8))
        self.assertIn("skill-up", step.said)

    def test_a_finished_bag_goes_to_the_smallest_bag_in_the_family(self):
        t = tailor(carried=(gc.Held(9001, 14046, 1),))
        fam = [family("Grug", (8, 14, 16, 16)), family("Ugga", (6, 8, 8, 8))]
        step, _ = step_of(t, fam=fam)
        self.assertEqual(step.action, "post")
        self.assertEqual(step.walk.command, "walk-to-mailbox max:600")
        self.assertEqual(step.rows[0].target_arg, "Ugga")
        self.assertEqual(step.rows[0].command, "send item:9001 subject:Runecloth Bag")

    def test_a_bag_nobody_would_wear_stays_put(self):
        t = tailor(carried=(gc.Held(9001, 4238, 1),))  # a six slot Linen Bag
        step, _ = step_of(t, fam=[family("Grug", (8, 14, 16, 16))])
        self.assertNotEqual(getattr(step, "action", None), "post")

    def test_delivered_materials_are_collected_before_anything_else(self):
        t = tailor(
            mail=(gc.Letter(55, 5001, 14047, 20), gc.Letter(56, 5002, 14047, 20, False))
        )
        step, _ = step_of(t)
        self.assertEqual(step.action, "collect")
        self.assertEqual(
            [r.command for r in step.rows], ["take-item mail:55 item:5001"]
        )

    def test_an_offline_tailor_does_nothing(self):
        step, why = step_of(tailor(online=False))
        self.assertIsNone(step)
        self.assertIn("offline", why)


class ThePass(unittest.TestCase):
    def crew(self):
        return [
            tailor(skills={gc.TAILORING: (300, 300), gc.HERBALISM: (1, 1)}),
            member("Alylienne", maintenance=False, carried=(held(14047, 20, 4001),)),
            member("Fugotik", maintenance=False, carried=(held(14047, 12, 4002),)),
            member("Beerix", maintenance=False, carried=(held(8170, 20, 4003),)),
            member(
                "Og", maintenance=False, family=True, carried=(held(14047, 20, 4004),)
            ),
        ]

    def test_a_tailor_short_of_cloth_is_supplied_by_post(self):
        crew = self.crew()
        crew[0] = tailor(known=KNOWN_300 | {18405})
        plan = gc.plan(crew, {}, TRAINABLE, VENDORS, {}, set())
        supply = [s for s in plan.steps if s.action == "supply"]
        self.assertEqual([s.holder for s in supply], ["Alylienne", "Beerix"])
        letter = supply[0].rows[0]
        self.assertEqual((letter.kind, letter.target_arg), ("mail", "Derred"))
        self.assertEqual(letter.command, "send item:4001 subject:For the guild tailor")
        self.assertEqual(supply[0].walk.command, "walk-to-mailbox max:600")
        self.assertNotIn(
            "Og", [s.holder for s in plan.steps], "the family is never walked"
        )

    def test_nothing_is_asked_twice_inside_the_cooldown(self):
        crew = self.crew()
        crew[0] = tailor(known=KNOWN_300 | {18405})
        recent = {("to:Derred", "supply", 14047): 10, ("to:Derred", "supply", 8170): 10}
        plan = gc.plan(crew, {}, TRAINABLE, VENDORS, recent, set())
        self.assertEqual([s for s in plan.steps if s.action == "supply"], [])

    def test_a_step_waits_out_its_cooldown(self):
        recent = {("Derred", "buy", 14468): 30}
        plan = gc.plan(self.crew(), {}, TRAINABLE, VENDORS, recent, set())
        self.assertNotIn("buy", [s.action for s in plan.steps if s.holder == "Derred"])
        self.assertTrue(any("cooldown" in n for n in plan.notes))

    def test_a_busy_tailor_is_left_alone(self):
        plan = gc.plan(self.crew(), {}, TRAINABLE, VENDORS, {}, {"Derred"})
        self.assertNotIn("Derred", [s.holder for s in plan.steps])


class TheGuards(unittest.TestCase):
    def test_a_post_whose_member_is_missing_is_noted_not_raised(self):
        posts = (gc.Post("Ghost", "tailor", gc.TAILORING, 300, 300),)
        steps, notes = [], []
        gc._guild_steps(([], (), TRAINABLE, VENDORS), posts, {}, set(), steps, notes)
        self.assertEqual(steps, [])
        self.assertIn("Ghost holds a post and is missing from the crew", notes)

    def test_a_pattern_that_is_gone_is_bought_again(self):
        bag = next(r for r in gc.BAGS if r.spell == 18405)
        step = gc._bag_steps(
            tailor(), bag, "pattern", TRAINABLE[EVERLOOK], VENDORS[EVERLOOK]
        )
        self.assertEqual((step.action, step.key), ("buy", 14468))


class FromRows(unittest.TestCase):
    def test_members_from_rows(self):
        members = gc.members_from_rows(
            [
                {
                    "guild_name": "Cave",
                    "guid": 1184,
                    "name": "Derred",
                    "class_id": 8,
                    "level": 60,
                    "online": 1,
                    "map_id": 1,
                },
                {
                    "guild_name": "Cave",
                    "guid": 7,
                    "name": "Ugga",
                    "class_id": 5,
                    "level": 60,
                    "online": 0,
                    "map_id": None,
                },
            ],
            [{"guid": 1184, "skill": 197, "value": 300, "max": 300}],
            [{"guid": 1184, "spell": 18401}],
            [{"owner": 1184, "item_guid": 9, "entry": 14047, "count": 5}],
            [
                {
                    "receiver": 1184,
                    "mail_id": 3,
                    "item_guid": 10,
                    "entry": 14047,
                    "count": 20,
                    "ready": 0,
                }
            ],
            [{"owner": 7, "slots": 8}, {"owner": 7, "slots": 6}],
            {"Derred"},
            {"Ugga"},
        )
        derred, ugga = members
        self.assertEqual(derred.skill(197), (300, 300))
        self.assertIn(18401, derred.known)
        self.assertEqual((derred.count(14047), derred.incoming(14047)), (5, 20))
        self.assertFalse(derred.mail[0].ready)
        self.assertTrue(derred.maintenance and not derred.family)
        self.assertEqual(ugga.worn_bags, (6, 8))
        self.assertIsNone(ugga.map_id)

    def test_recent_reads_a_walk_as_its_step_and_a_letter_for_its_tailor(self):
        recent = gc.recent_from_rows(
            [
                {
                    "target_name": "Derred",
                    "target_arg": "",
                    "source": "guildcorps:buy-walk:14468",
                    "age": 12,
                },
                {
                    "target_name": "Alylienne",
                    "target_arg": "Derred",
                    "source": "guildcorps:supply:14047",
                    "age": 3,
                },
                {"target_name": "X", "source": "guilddues:100", "age": 1},
            ]
        )
        self.assertEqual(recent[("Derred", "buy", 14468)], 12)
        self.assertEqual(recent[("to:Derred", "supply", 14047)], 3)
        self.assertEqual(len(recent), 3)

    def test_places(self):
        places = gc.places_from_rows(
            [{"map_id": 1, "item": 14468}, {"map_id": 1, "item": 1}], "item"
        )
        self.assertEqual(places, {1: frozenset({1, 14468})})


class ThePage(unittest.TestCase):
    def test_bags_made_counts_only_bags_the_world_made(self):
        rows = [
            {
                "target_name": "Derred",
                "source": "guildcorps:craft:18405",
                "status": "applied",
                "result": '{"outcome":"spent"}',
            },
            {
                "target_name": "Derred",
                "source": "guildcorps:craft:18405",
                "status": "error",
                "result": "{}",
            },
            {
                "target_name": "Derred",
                "source": "guildcorps:craft:18401",
                "status": "applied",
                "result": "{}",
            },
            {
                "target_name": "Derred",
                "source": "guildcorps:craft:18405",
                "status": "applied",
                "result": '{"outcome":"refused"}',
            },
        ]
        self.assertEqual(gc.bags_made(rows), {"Derred": {"Runecloth Bag": 1}})

    def test_attach_corps_writes_the_line_and_the_total(self):
        lineup = {"maintenance": [{"name": "Derred"}, {"name": "Bakurn"}]}
        posts = (gc.Post("Derred", "tailor", gc.TAILORING, 300, 300),)
        gc.attach_corps(lineup, posts, {"Derred": {"Runecloth Bag": 2}})
        derred, bakurn = lineup["maintenance"]
        self.assertEqual(
            derred["corps"], "corps: tailor Tailoring 300/300; made 2 Runecloth Bag"
        )
        self.assertEqual(derred["profession"]["value"], 300)
        self.assertNotIn("corps", bakurn)
        self.assertEqual(lineup["corps"]["said"], "crafting corps: 2 bags made")

    def test_posts_for_lineup_reads_name_keyed_skills(self):
        lineup = {"maintenance": [{"name": "Derred"}]}
        posts = gc.posts_for_lineup(
            lineup, "Cave", [{"name": "Derred", "skill": 197, "value": 300, "max": 300}]
        )
        self.assertEqual([(p.name, p.role) for p in posts], [("Derred", "tailor")])

    def test_the_endpoint_and_page_carry_the_corps(self):
        lineup = SERVER[SERVER.index("    def _lineup(") :]
        lineup = lineup[: lineup.index("    def _raidgoals(")]
        self.assertIn("guildcorps.attach_corps(", lineup)
        self.assertIn("guildcorps.bags_made(", lineup)
        self.assertIn("WHERE kind = 'cast' AND source LIKE %s", SERVER)
        self.assertIn("if (m.corps) {", PAGE)
        self.assertIn("g.corps ? g.corps.said", PAGE)
        self.assertIn("guildcorps.py", DOCKERFILE)


class TheBridgePass(unittest.TestCase):
    def body(self, name):
        start = BRIDGE.index("def %s(" % name)
        end = BRIDGE.find("\n    async def ", start + 1)
        end2 = BRIDGE.find("\ndef ", start + 1)
        ends = [e for e in (end, end2) if e > 0]
        return BRIDGE[start : min(ends)]

    def test_the_loop_runs_in_both_bridges(self):
        self.assertEqual(BRIDGE.count("                self._guild_corps_loop,\n"), 2)

    def test_rows_are_the_players_own_verbs(self):
        for name in ("_guild_corps_once", "_run_corps_step", "_corps_row"):
            body = self.body(name)
            self.assertNotIn("_insert_gm", body)
            self.assertNotIn("_insert_give", body)
            self.assertNotIn("'give'", body)
        insert = self.body("_insert_corps_row")
        self.assertIn("(target_name, command, kind, target_arg, source)", insert)

    def test_the_action_rows_follow_an_arrival(self):
        body = self.body("_run_corps_step")
        self.assertLess(
            body.index("guildroute.ARRIVED"), body.index("for row in step.rows")
        )

    def test_log_lines_are_unique_to_the_pass(self):
        self.assertIn('log.info("guild corps: started %d step(s)"', BRIDGE)
        self.assertIn('"guild corps pass failed; retrying next cycle"', BRIDGE)


if __name__ == "__main__":
    unittest.main()
