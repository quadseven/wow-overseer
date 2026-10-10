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
import guildroute

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
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
    # The crew is the whole guild, family included, as the bridge reads it.
    return gc.tailor_step(t, [t, *members, *fam], fam, trainable, vendors)


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

    def test_the_family_tailor_is_the_master_ahead_of_a_better_crew_tailor(self):
        crew = [
            member(
                "Og", maintenance=False, family=True, skills={gc.TAILORING: (50, 150)}
            ),
            member("Derred", skills={gc.TAILORING: (300, 300)}),
        ]
        posts = gc.plan_corps(crew)["Cave"]
        self.assertEqual([p.name for p in posts], ["Og", "Derred"])
        self.assertTrue(posts[0].master)
        self.assertEqual(posts[0].said, "master tailor Tailoring 50/150")

    def test_a_family_member_holds_no_gathering_post(self):
        crew = [
            member(
                "Ugga",
                maintenance=False,
                family=True,
                skills={gc.HERBALISM: (153, 225)},
            ),
            member("Baldam", skills={gc.HERBALISM: (52, 75)}),
        ]
        self.assertEqual([p.name for p in gc.plan_corps(crew)["Cave"]], ["Baldam"])

    def test_a_guild_member_off_the_family_is_never_a_master(self):
        crew = [member("Bob", maintenance=False, skills={gc.TAILORING: (300, 300)})]
        self.assertEqual(gc.plan_corps(crew), {})

    def test_the_post_reads_as_a_sentence(self):
        post = gc.Post("Derred", "tailor", gc.TAILORING, 300, 300)
        self.assertEqual(post.said, "tailor Tailoring 300/300")


class ATailorsNextStep(unittest.TestCase):
    def test_at_its_ceiling_below_artisan_it_walks_to_a_trainer_for_the_next_rank(self):
        t = tailor("Xohjaz", 225, 225, guild="Bonkers")
        step, _ = step_of(t)
        self.assertEqual(step.action, "train")
        self.assertIsNone(step.walk)
        self.assertEqual(step.rows[0].kind, "cast")
        self.assertEqual(step.rows[0].command, "walk-to-trainer skill:197")
        self.assertEqual(step.rows[0].source, "guildcorps:train:12181")

    def test_at_artisan_no_trainer_sells_it_master(self):
        # The classic ruleset stops at 300. A trainer that sells Master (26791)
        # is not a reason to walk, wherever it stands.
        t = tailor("Xohjaz", guild="Bonkers", carried=(held(21877, 15),))
        step, _ = step_of(t, trainable=TRAINABLE[OUTLAND] | TRAINABLE[EVERLOOK])
        self.assertNotEqual(getattr(step, "action", None), "train")

    def test_a_trainer_recipe_its_skill_allows_is_named(self):
        t = tailor("Baldam", 250, 300, known=KNOWN_300 - {18401})
        crew = [member("Baleron", carried=(held(14047, 20),))]
        step, _ = step_of(t, crew)
        self.assertEqual(step.rows[0].command, "walk-to-trainer skill:197 learn:18401")

    def test_no_netherweave_recipe_is_named_even_where_a_trainer_sells_it(self):
        t = tailor("Baldam", 305, 375, known=KNOWN_300 - {26745})
        crew = [member("Baleron", carried=(held(21877, 20),))]
        step, _ = step_of(t, crew, trainable=TRAINABLE[OUTLAND])
        commands = [row.command for row in getattr(step, "rows", ())]
        self.assertFalse([c for c in commands if "26745" in c or "26746" in c])

    def test_a_rank_whose_spell_it_knows_is_not_bought_again(self):
        """Measured: a bot knew the rank's skill spell with the old ceiling, and
        its trainer walk ended "no trainer on this map will teach this
        character that skill"."""
        t = tailor("Baldam", 225, 225, known=KNOWN_300 | {12180})
        step, _ = step_of(t)
        self.assertNotEqual(getattr(step, "action", None), "train")

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
        step, _ = step_of(ready, fam=[family("Ugga", (6, 8, 8, 8))])
        self.assertEqual((step.action, step.key, step.repeat), ("craft", 18405, 1))

    def test_thread_is_not_bought_before_the_cloth_is_in_hand(self):
        crew = [member("Alylienne", carried=(held(14047, 20),))]
        crew.append(member("Beerix", carried=(held(8170, 20),)))
        t = tailor(known=KNOWN_300 | {18405})
        step, why = step_of(t, crew)
        self.assertIsNone(step)
        self.assertIn("Runecloth Bag", why)

    def test_below_its_ceiling_it_crafts_skill_ups(self):
        t = tailor("Baldam", 255, 300, carried=(held(14047, 20), held(14047, 20)))
        step, _ = step_of(t)
        self.assertEqual((step.action, step.key, step.repeat), ("craft", 18401, 10))
        self.assertIn("skill-up", step.said)

    def test_netherweave_cloth_is_no_skill_up(self):
        t = tailor("Baldam", 305, 375, carried=(held(21877, 20), held(21877, 20)))
        step, _ = step_of(t, trainable=TRAINABLE[OUTLAND])
        self.assertNotEqual(getattr(step, "key", None), 26745)

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


class TheFarWalk(unittest.TestCase):
    """quadseven/mod-overseer#633: the walks may go past the near cap now, and
    the nearest member is asked first."""

    def crew(self):
        return [
            tailor(known=KNOWN_300 | {18405}),
            member("Alylienne", maintenance=False, carried=(held(14047, 20, 4001),)),
            member("Fugotik", maintenance=False, carried=(held(14047, 12, 4002),)),
            member("Beerix", maintenance=False, carried=(held(8170, 20, 4003),)),
        ]

    def test_the_far_cap_is_asked_for_on_every_walk(self):
        far = guildroute.FAR_WALK_YARDS
        plan = gc.plan(self.crew(), {}, TRAINABLE, VENDORS, {}, set(), walk_yards=far)
        supply = [s for s in plan.steps if s.action == "supply"]
        self.assertEqual(supply[0].walk.command, "walk-to-mailbox max:20000")
        step, _ = gc.tailor_step(
            tailor(), self.crew()[1:], (), TRAINABLE[EVERLOOK], VENDORS[EVERLOOK], far
        )
        self.assertEqual(step.walk.command, "walk-to-vendor item:14468 max:20000")
        step, _ = gc.tailor_step(
            tailor("Xohjaz", 225, 225), [], (), TRAINABLE[EVERLOOK], frozenset(), far
        )
        self.assertEqual(step.rows[0].command, "walk-to-trainer skill:197 max:20000")

    def test_the_near_cap_writes_the_rows_it_always_wrote(self):
        step, _ = gc.tailor_step(
            tailor(), self.crew()[1:], (), TRAINABLE[EVERLOOK], VENDORS[EVERLOOK]
        )
        self.assertEqual(step.walk.command, "walk-to-vendor item:14468")

    def test_the_nearest_sender_is_asked_first(self):
        yards = {"Alylienne": 1953.0, "Fugotik": 120.0, "Beerix": 300.0}
        plan = gc.plan(
            self.crew(), {}, TRAINABLE, VENDORS, {}, set(), mailbox_yards=yards
        )
        supply = [s for s in plan.steps if s.action == "supply"]
        self.assertEqual([s.holder for s in supply], ["Fugotik", "Alylienne"])


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


class TheBridgePass(unittest.TestCase):
    def body(self, name):
        start = BRIDGE.index("def %s(" % name)
        end = BRIDGE.find("\n    async def ", start + 1)
        end2 = BRIDGE.find("\ndef ", start + 1)
        ends = [e for e in (end, end2) if e > 0]
        return BRIDGE[start : min(ends)]

    def test_the_loop_runs_in_both_bridges(self):
        self.assertEqual(BRIDGE.count('\n    _Pass("_guild_corps_loop"),\n'), 1)

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

    def test_the_pass_asks_the_far_cap_and_the_nearest_sender(self):
        """quadseven/mod-overseer#633."""
        once = self.body("_guild_corps_once")
        self.assertIn("walk_yards=cap, mailbox_yards=near", once)
        self.assertIn("self._run_corps_step(step, cap)", once)
        self.assertIn("guildroute.GUILD_STEP_SECONDS", once)
        near = self.body("_corps_mailbox_yards")
        self.assertIn("classic.is_expansion_map(m.map_id)", near)
        self.assertIn("CORPS_NEAR_READS", near)

    def test_a_walk_a_fight_ended_is_walked_again_once(self):
        step = self.body("_run_corps_step")
        self.assertIn("self._follow_guild_walk(", step)
        follow = self.body("_follow_guild_walk")
        self.assertIn("self._await_mail_walk(holder, row_id, cap, goal)", follow)
        self.assertIn("range(1, guildroute.WALK_COMBAT_RETRIES + 1)", follow)
        self.assertNotIn("while True", follow)
        row = self.body("_corps_row")
        self.assertIn("self._corps_row_again(", row)
        self.assertIn("guildroute.follow_seconds(cap)", row)
        self.assertIn("guildroute.COMBAT_ENDING", self.body("_corps_row_again"))
        self.assertIn(
            '"guild corps: %s row %d for %s ended in a fight; walking it "', BRIDGE
        )
        self.assertIn(
            '"%s: walk row %d for %s ended in a fight; walking it again in %d "', BRIDGE
        )

    def test_log_lines_are_unique_to_the_pass(self):
        self.assertIn('log.info("guild corps: started %d step(s)%s"', BRIDGE)
        self.assertIn('"guild corps pass failed; retrying next cycle"', BRIDGE)


class TheClassicRuleset(unittest.TestCase):
    """Level 60, skill 300, and never Outland or Northrend (classic.py)."""

    def test_no_bag_or_bolt_outside_the_ruleset_is_ever_a_target(self):
        # Every trainer recipe and every material in hand: the Netherweave Bag
        # is still not the target, and the Runecloth Bag's pattern is.
        t = tailor(
            "Derred",
            320,
            375,
            known=KNOWN_300 | {26746},
            carried=(held(21840, 8), held(14341, 2), held(14047, 20)),
        )
        crew = [member("Beerix", carried=(held(8170, 20),))]
        bag, _ = gc.target_bag(
            t, [t, *crew], TRAINABLE[OUTLAND] | TRAINABLE[EVERLOOK], VENDORS[EVERLOOK]
        )
        self.assertEqual(bag.name, "Runecloth Bag")

    def test_a_tailor_in_outland_is_left_out_with_a_reason(self):
        t = tailor("Xohjaz", guild="Bonkers", map_id=OUTLAND)
        plan = gc.plan([t], {}, TRAINABLE, VENDORS, {}, set())
        self.assertFalse([s for s in plan.steps if s.holder == "Xohjaz"])
        self.assertIn("Xohjaz stands in Outland, outside the classic world", plan.notes)

    def test_a_guildmate_in_outland_posts_nothing(self):
        t = tailor("Derred", 255, 300)
        away = member("Baleron", map_id=OUTLAND, carried=(held(14047, 20),))
        steps = gc.supply_steps(t, None, gc.BOLT_OF[14048], [t, away], set())
        self.assertEqual(steps, [])
        home = member("Baleron", carried=(held(14047, 20),))
        steps = gc.supply_steps(t, None, gc.BOLT_OF[14048], [t, home], set())
        self.assertEqual([s.holder for s in steps], ["Baleron"])

    def test_outland_and_northrend_trainers_and_vendors_are_not_read(self):
        rows = [
            {"map_id": 1, "spell": 18401},
            {"map_id": 530, "spell": 26791},
            {"map_id": 571, "spell": 51308},
        ]
        self.assertEqual(gc.places_from_rows(rows, "spell"), {1: frozenset({18401})})


EASTERN_KINGDOMS = 0
# Map 0 as measured 2026-09-24: its trainers teach up to Artisan and its
# vendors sell every thread, but nobody there sells the Runecloth Bag pattern.
EK_TRAINABLE = TRAINABLE[EVERLOOK]
EK_VENDORS = frozenset({14341, 2320, 2321, 4291, 8343})
TRAINABLE_EK = {**TRAINABLE, EASTERN_KINGDOMS: EK_TRAINABLE}
VENDORS_EK = {**VENDORS, EASTERN_KINGDOMS: EK_VENDORS}


class ABagIsPostedTheMomentItIsMade(unittest.TestCase):
    """Measured on dev 2026-09-24: a Runecloth Bag crafted at 08:09 waited for a
    post walk that ended in a fight and off the map, and by 09:54 the bag was
    gone from the realm. A random bot wearing four 24-slot bags reads a 14-slot
    one as a vendor item and sells it."""

    READY = (held(14048, 5), held(8170, 2), held(14341, 1))

    def test_the_bag_is_crafted_at_a_mailbox_and_posted_by_entry(self):
        t = tailor(known=KNOWN_300 | {18405}, carried=self.READY)
        fam = [family("Grug", (14, 14, 16, 16)), family("Ugga", (6, 8, 8, 8))]
        step, _ = step_of(t, fam=fam)
        self.assertEqual((step.action, step.key), ("craft", 18405))
        self.assertEqual(step.walk.command, "walk-to-mailbox max:600")
        self.assertEqual(step.walk.source, "guildcorps:craft-walk:18405")
        cast, letter = step.rows
        self.assertEqual((cast.kind, cast.command), ("cast", "18405"))
        self.assertEqual(cast.source, "guildcorps:craft:18405")
        self.assertEqual(letter.kind, "mail")
        self.assertEqual(letter.command, "send entry:14046 subject:Runecloth Bag")
        self.assertEqual(letter.target_arg, "Ugga")
        self.assertEqual(letter.source, "guildcorps:post:14046")

    def test_no_bag_is_crafted_that_nobody_in_the_guild_would_wear(self):
        t = tailor(known=KNOWN_300 | {18405}, carried=self.READY)
        step, why = step_of(t, fam=[family("Grug", (16, 16, 16, 16))])
        self.assertIsNone(step)
        self.assertIn("nobody in the guild would wear", why)

    def test_a_bag_already_on_its_way_counts_as_worn(self):
        t = tailor(known=KNOWN_300 | {18405}, carried=self.READY)
        ugga = gc.Member(
            name="Ugga",
            guild="Cave",
            family=True,
            worn_bags=(6, 8, 8, 8),
            mail=(gc.Letter(9, 99, 14046, 1, False),),
        )
        grog = family("Grog", (8, 8, 10, 8))
        step, _ = step_of(t, fam=[ugga, grog])
        self.assertEqual(step.rows[1].target_arg, "Grog")

    def test_a_bag_craft_waits_longer_than_a_bolt(self):
        t = tailor(known=KNOWN_300 | {18405}, carried=self.READY)
        fam = {"Cave": (family("Ugga", (6, 8, 8, 8)),)}
        crew = [t, *fam["Cave"]]
        recent = {("Derred", "craft", 18405): 10}
        plan = gc.plan(crew, fam, TRAINABLE, VENDORS, recent, set())
        self.assertNotIn("craft", [s.action for s in plan.steps])
        recent = {("Derred", "craft", 18405): gc.BAG_CRAFT_MINUTES}
        plan = gc.plan(crew, fam, TRAINABLE, VENDORS, recent, set())
        self.assertEqual([s.action for s in plan.steps], ["craft"])


class TheGuildGetsTheBags(unittest.TestCase):
    """Operator, 2026-10-05: bags go to whoever in the guild needs the slots,
    and the family are the master crafters."""

    BAG = (held(14046, 1, 4242),)

    def test_a_crew_tailor_posts_to_the_guildmate_with_the_smallest_bag(self):
        t = tailor(carried=self.BAG)
        raider = member("Bodo", maintenance=False, worn_bags=(6, 6, 6, 6))
        fam = [family("Ugga", (8, 8, 8, 8))]
        step, _ = step_of(t, members=[raider], fam=fam)
        self.assertEqual(step.action, "post")
        self.assertEqual(step.rows[0].target_arg, "Bodo")

    def test_a_guildmate_whose_bags_were_not_read_gets_nothing(self):
        t = tailor(carried=self.BAG)
        step, _ = step_of(t, members=[member("Bodo", maintenance=False)])
        self.assertIsNone(step)

    def test_a_master_posts_only_from_a_mailbox_and_never_walks(self):
        og = member(
            "Og",
            maintenance=False,
            family=True,
            online=True,
            carried=self.BAG,
            skills={gc.TAILORING: (50, 150)},
        )
        raider = member("Bodo", maintenance=False, worn_bags=(6, 8, 8, 8))
        crew = [og, raider, family("Ugga", (6, 6, 6, 6))]
        away, why = gc.tailor_step(og, crew, (), frozenset(), frozenset())
        self.assertIsNone(away)
        self.assertIn("next mailbox", why)
        step, _ = gc.tailor_step(
            og, crew, (), frozenset(), frozenset(), at_mailbox=frozenset({"Og"})
        )
        self.assertIsNone(step.walk)
        self.assertEqual(
            step.rows[0].target_arg,
            "Bodo",
            "Ugga is family: the family hand-over trades it",
        )


class TheCrewShopsForTheMasters(unittest.TestCase):
    """Operator, 2026-10-05: getting thread for crafting is the maintenance
    members' work, shopping and farming; the family master only sews."""

    FINE_THREAD = 2321

    def og(self, **over):
        base = dict(maintenance=False, family=True, skills={gc.TAILORING: (90, 150)})
        base.update(over)
        return member("Og", **base)

    def test_a_crew_member_on_a_vendor_map_buys_the_thread_and_posts_it(self):
        og = self.og()
        crew = [og, member("Arran"), member("Baldam", map_id=999)]
        vendors = {EVERLOOK: frozenset({self.FINE_THREAD})}
        (step,) = gc.shop_steps(og, crew, vendors, set())
        self.assertEqual((step.holder, step.action, step.key), ("Arran", "shop", 2321))
        self.assertTrue(step.walk.command.startswith("walk-to-vendor item:2321"))
        buy, walk, letter = step.rows
        self.assertEqual(buy.command.split(" max:")[0], "entry:2321 count:5")
        self.assertTrue(walk.command.startswith("walk-to-mailbox"))
        self.assertEqual(
            letter.command, "send entry:2321 subject:Thread for the guild tailor"
        )
        self.assertEqual(letter.target_arg, "Og")

    def test_nothing_is_bought_while_the_master_has_thread_or_it_is_on_its_way(self):
        crew = [member("Arran")]
        vendors = {EVERLOOK: frozenset({self.FINE_THREAD})}
        carried = self.og(carried=(held(self.FINE_THREAD, 1),))
        self.assertEqual(gc.shop_steps(carried, crew, vendors, set()), [])
        posted = self.og(mail=(gc.Letter(1, 2, self.FINE_THREAD, 5),))
        self.assertEqual(gc.shop_steps(posted, crew, vendors, set()), [])

    def test_a_purchase_is_not_repeated_inside_its_cooldown(self):
        og = self.og()
        vendors = {EVERLOOK: frozenset({self.FINE_THREAD})}
        recent = {("to:Og", "shop", self.FINE_THREAD): 10}
        self.assertEqual(
            gc.shop_steps(og, [member("Arran")], vendors, set(), recent), []
        )
        rows = [
            {
                "source": "guildcorps:shop:2321",
                "target_name": "Arran",
                "target_arg": "Og",
                "age": 7,
            }
        ]
        self.assertEqual(gc.recent_from_rows(rows)[("to:Og", "shop", 2321)], 7)

    def test_the_family_never_shops_and_a_busy_member_is_not_asked(self):
        og = self.og()
        vendors = {EVERLOOK: frozenset({self.FINE_THREAD})}
        crew = [og, member("Ugga", maintenance=False, family=True), member("Arran")]
        self.assertEqual(gc.shop_steps(og, crew, vendors, {"Arran"}), [])

    def test_a_master_below_the_first_bag_needs_nothing(self):
        og = self.og(skills={gc.TAILORING: (20, 75)})
        vendors = {EVERLOOK: frozenset({2320})}
        self.assertEqual(gc.shop_steps(og, [member("Arran")], vendors, set()), [])


class TheCrewShopsForTheGarmentRungs(unittest.TestCase):
    """Operator, 2026-10-05: the family are master crafters and the crew shops
    for them. The thread and dye of the master's next garment rungs
    (craft_supply.REAGENTS) are bought and posted like a bag's thread."""

    COARSE, FINE, BLUE = 2320, 2321, 6260
    EVERYWHERE = frozenset({2320, 2321, 6260, 4291, 2604})

    def og(self, value, **over):
        base = dict(maintenance=False, family=True, skills={gc.TAILORING: (value, 150)})
        base.update(over)
        return member("Og", **base)

    def vendors(self):
        return {EVERLOOK: self.EVERYWHERE}

    def test_the_belt_rung_gets_its_thread_with_the_bags(self):
        # Tailoring 50: the Linen Bag's 15 Coarse Thread (5 bags), plus the
        # Linen Belt's 1 a cast, 5 casts deep.
        steps = gc.shop_steps(self.og(50), [member("Arran")], self.vendors(), set())
        (step,) = steps
        self.assertEqual((step.holder, step.key), ("Arran", self.COARSE))
        self.assertEqual(step.rows[0].command.split(" max:")[0], "entry:2320 count:20")
        self.assertIn("Linen Belt", step.said)
        self.assertEqual(step.rows[2].target_arg, "Og")

    def test_a_dye_is_bought_and_posted_by_its_own_shopper(self):
        # Tailoring 140: Azure Silk Hood (145) is a bracket ahead; it takes 1
        # Fine Thread and 2 Blue Dye a cast.
        crew = [member("Arran"), member("Baldam")]
        steps = gc.shop_steps(self.og(140), crew, self.vendors(), set())
        by_item = {s.key: s for s in steps}
        self.assertEqual(set(by_item), {self.FINE, self.BLUE})
        self.assertNotEqual(by_item[self.FINE].holder, by_item[self.BLUE].holder)
        dye = by_item[self.BLUE]
        self.assertEqual(dye.rows[0].command.split(" max:")[0], "entry:6260 count:10")
        self.assertEqual(
            dye.rows[2].command, "send entry:6260 subject:Dye for the guild tailor"
        )

    def test_the_stock_is_topped_up_not_bought_twice(self):
        og = self.og(140, carried=(held(self.BLUE, 4),))
        steps = gc.shop_steps(
            og, [member("Arran"), member("Baldam")], self.vendors(), set()
        )
        (dye,) = [s for s in steps if s.key == self.BLUE]
        self.assertEqual(dye.rows[0].command.split(" max:")[0], "entry:6260 count:6")
        full = self.og(140, mail=(gc.Letter(1, 2, self.BLUE, 10),))
        steps = gc.shop_steps(
            full, [member("Arran"), member("Baldam")], self.vendors(), set()
        )
        self.assertNotIn(self.BLUE, {s.key for s in steps})

    def test_a_rung_further_ahead_is_not_stocked_yet(self):
        # Silken Thread is Crimson Silk Pantaloons' (205): far above Tailoring 90.
        steps = gc.shop_steps(self.og(90), [member("Arran")], self.vendors(), set())
        self.assertNotIn(4291, {s.key for s in steps})

    def test_a_bag_and_a_rung_sharing_a_thread_are_bought_together(self):
        # Woolen Bag (Fine Thread) and Azure Silk Hood (Fine Thread) at 130.
        crew = [member("Arran"), member("Baldam")]
        (step,) = [
            s
            for s in gc.shop_steps(self.og(130), crew, self.vendors(), set())
            if s.key == self.FINE
        ]
        self.assertEqual(
            step.rows[0].command.split(" max:")[0], "entry:2321 count:%d" % (5 + 5)
        )

    def test_every_price_the_crew_pays_is_the_ladders_own(self):
        import craft_supply

        for spell in gc.CREW_RUNGS:
            for entry, name, price, _q in craft_supply.REAGENTS[spell]:
                self.assertEqual(gc.VENDOR_PRICE[entry], price, name)
        for entry in gc.THREAD_PRICE:
            self.assertIn(entry, gc.LADDER_ROWS)
            self.assertEqual(gc.LADDER_ROWS[entry][1], gc.THREAD_PRICE[entry])

    def test_the_corps_reads_the_dyes_so_it_can_count_them_and_find_a_vendor(self):
        self.assertLessEqual({6260, 2604}, gc.PATH_ENTRIES)

    def test_the_family_stops_walking_to_a_vendor_for_these_rungs(self):
        self.assertTrue({8776, 8760, 8791, 18417} <= gc.CREW_RUNGS)
        self.assertNotIn(2167, gc.CREW_RUNGS)  # leatherworking stays the family's
        self.assertIn("spell_id not in guildcorps.CREW_RUNGS", BRIDGE)


class APatternFromAnotherMap(unittest.TestCase):
    """Measured on dev 2026-09-24: both guilds' tailors stood on the Eastern
    Kingdoms, where no vendor sells the Runecloth Bag pattern, and every pass
    ended "no bag its skill allows can be learned and supplied on its map"
    while guildmates stood in Winterspring beside Qia."""

    def crew(self, **buyer):
        buyer.setdefault("map_id", EVERLOOK)
        return [
            tailor(map_id=EASTERN_KINGDOMS),
            member(
                "Alylienne",
                maintenance=False,
                map_id=EASTERN_KINGDOMS,
                carried=(held(14047, 40, 4001),),
            ),
            member(
                "Beerix",
                maintenance=False,
                map_id=EASTERN_KINGDOMS,
                carried=(held(8170, 20, 4003),),
            ),
            member("Hebus", maintenance=False, **buyer),
        ]

    def test_a_guildmate_by_the_vendor_buys_it_and_posts_it_at_once(self):
        plan = gc.plan(self.crew(), {}, TRAINABLE_EK, VENDORS_EK, {}, set())
        fetch = [s for s in plan.steps if s.action == "fetch"]
        self.assertEqual([s.holder for s in fetch], ["Hebus"])
        step = fetch[0]
        self.assertEqual(step.walk.command, "walk-to-vendor item:14468")
        self.assertEqual(step.walk.source, "guildcorps:fetch-walk:14468")
        buy, walk, letter = step.rows
        self.assertEqual(
            (buy.kind, buy.command), ("buy", "entry:14468 count:1 max:15000")
        )
        self.assertEqual(walk.command, "walk-to-mailbox max:600")
        self.assertEqual(
            letter.command, "send entry:14468 subject:For the guild tailor"
        )
        self.assertEqual(letter.target_arg, "Derred")
        self.assertEqual(letter.source, "guildcorps:supply:14468")

    def test_the_tailor_is_aimed_at_the_runecloth_bag_meanwhile(self):
        crew = self.crew()
        by_post = gc.patterns_by_post(crew[0], crew, VENDORS_EK)
        bag, reach = gc.target_bag(crew[0], crew, EK_TRAINABLE, EK_VENDORS, by_post)
        self.assertEqual((bag.name, reach), ("Runecloth Bag", "post"))
        bag, why = gc.target_bag(crew[0], crew, EK_TRAINABLE, EK_VENDORS)
        self.assertIsNone(bag, "without the post the old dead end stands")

    def test_one_fetch_at_a_time_per_guild(self):
        recent = {("Hebus", "fetch", 14468): 10}
        crew = self.crew() + [member("Bytkiz", maintenance=False)]
        plan = gc.plan(crew, {}, TRAINABLE_EK, VENDORS_EK, recent, set())
        self.assertFalse([s for s in plan.steps if s.action == "fetch"])

    def test_a_buyer_whose_fetch_failed_is_not_sent_again_soon(self):
        recent = {("Hebus", "fetch", 14468): gc.FETCH_GUILD_MINUTES + 5}
        crew = self.crew() + [member("Bytkiz", maintenance=False, level=58)]
        plan = gc.plan(crew, {}, TRAINABLE_EK, VENDORS_EK, recent, set())
        self.assertEqual(
            [s.holder for s in plan.steps if s.action == "fetch"], ["Bytkiz"]
        )

    def test_no_low_level_or_family_buyer(self):
        low = self.crew(level=30)
        plan = gc.plan(low, {}, TRAINABLE_EK, VENDORS_EK, {}, set())
        self.assertFalse([s for s in plan.steps if s.action == "fetch"])
        fam = self.crew()
        fam[3] = member("Og", maintenance=False, family=True)
        plan = gc.plan(fam, {}, TRAINABLE_EK, VENDORS_EK, {}, set())
        self.assertFalse([s for s in plan.steps if s.action == "fetch"])

    def test_a_carried_pattern_is_posted_instead_of_bought(self):
        crew = self.crew(carried=(gc.Held(5150, 14468, 1),))
        plan = gc.plan(crew, {}, TRAINABLE_EK, VENDORS_EK, {}, set())
        self.assertFalse([s for s in plan.steps if s.action == "fetch"])
        letters = [s for s in plan.steps if s.action == "supply" and s.key == 14468]
        self.assertEqual(
            letters[0].rows[0].command, "send item:5150 subject:For the guild tailor"
        )

    def test_a_pattern_in_a_letter_is_collected_then_learned(self):
        t = tailor(map_id=EASTERN_KINGDOMS, mail=(gc.Letter(70, 5150, 14468, 1),))
        step, _ = gc.tailor_step(
            t, [t], (), frozenset(), frozenset(), gc.NEAR, frozenset()
        )
        self.assertEqual(step.action, "collect")
        self.assertEqual(step.rows[0].command, "take-item mail:70 item:5150")


class TheTailorWhoKnowsTheBag(unittest.TestCase):
    def test_the_post_goes_to_the_tailor_who_learned_the_bigger_bag(self):
        crew = [
            member("Derred", skills={gc.TAILORING: (300, 375)}, known=KNOWN_300),
            member("Behodiir", skills={gc.TAILORING: (300, 375)}, known=KNOWN_300),
            member(
                "Baldam", skills={gc.TAILORING: (300, 300)}, known=KNOWN_300 | {18405}
            ),
        ]
        posts = gc.plan_corps(crew)["Cave"]
        self.assertEqual([p.name for p in posts if p.role == "tailor"][0], "Baldam")


class EveryFamilysGuild(unittest.TestCase):
    """Measured on dev 2026-09-24: the pass read only this bridge's family, so
    Bonkers' corps never planned a step for the Horde family's pouches."""

    def body(self, name):
        start = BRIDGE.index("def %s(" % name)
        end = BRIDGE.find("\n    async def ", start + 1)
        return BRIDGE[start:end]

    def test_the_loop_runs_the_other_families(self):
        loop = self.body("_guild_corps_loop")
        self.assertIn(
            'self._for_other_families("guild corps", self._guild_corps_once)', loop
        )
        once = self.body("_guild_corps_once")
        self.assertIn("_names_of, cohort", once)
        self.assertLess(
            once.index("if cohort is not None:"), once.index("self._raid_supply_once(")
        )

    def test_every_guildmates_letters_and_bags_are_read(self):
        fetch = BRIDGE[BRIDGE.index("def _fetch_corps_facts(") :]
        fetch = fetch[: fetch.index("\ndef ")]
        self.assertIn("_CORPS_LETTERS_SQL.format(\n            guids=everyone", fetch)
        self.assertIn("_CORPS_BAGS_SQL.format(guids=everyone)", fetch)
        self.assertIn("maintenance | family", fetch)

    def test_the_masters_at_a_mailbox_reach_the_plan(self):
        once = BRIDGE[BRIDGE.index("async def _guild_corps_once(") :]
        once = once[: once.index("\n    async def ")]
        self.assertIn("at_mailbox=masters", once)


class TheGuildPostsClothToItsOwnMaster(unittest.TestCase):
    """2026-10-06: the guild's bag maker stood at no cloth for hours."""

    def og(self, **over):
        base = dict(
            maintenance=False,
            family=True,
            level=30,
            skills={gc.TAILORING: (52, 150)},
            known=frozenset({2963, 3755}),
        )
        base.update(over)
        return member("Og", **base)

    def run_plan(self, crew):
        og = next(m for m in crew if m.name == "Og")
        return gc.plan(crew, {"Cave": [og]}, TRAINABLE, {}, {}, set())

    def test_a_master_away_from_a_thread_vendor_is_still_posted_cloth(self):
        crew = [self.og(), member("Gugga", carried=(held(2589, 20),))]
        plan = self.run_plan(crew)
        (step,) = [s for s in plan.steps if s.action == "supply"]
        self.assertEqual((step.holder, step.key), ("Gugga", 2589))
        self.assertEqual(step.rows[0].target_arg, "Og")

    def test_a_crew_tailor_still_needs_a_vendor_for_its_own_thread(self):
        pokka = member(
            "Pokka", known=frozenset({2963, 3755}), skills={gc.TAILORING: (52, 150)}
        )
        bag, why = gc.target_bag(pokka, [pokka], TRAINABLE[EVERLOOK], frozenset())
        self.assertIsNone(bag)
        self.assertIn("no bag", why)

    def test_the_ask_is_a_stack_so_two_guildmates_can_answer(self):
        og = self.og()
        crew = [og, member("Gugga", carried=(held(2589, 20),))]
        bag, _ = gc.target_bag(og, crew, TRAINABLE[EVERLOOK], frozenset())
        self.assertEqual(gc._shortfall(og, bag, None), [(2589, gc.STACK)])

    def test_cloth_never_crosses_to_the_other_guilds_master(self):
        horde = member("Glob", guild="Bonkers", carried=(held(2589, 20),))
        plan = self.run_plan([self.og(), horde])
        self.assertEqual([s for s in plan.steps if s.action == "supply"], [])

    def test_a_master_with_cloth_on_its_way_is_not_asked_again(self):
        og = self.og(mail=(gc.Letter(1, 2, 2589, 20),))
        crew = [og, member("Gugga", carried=(held(2589, 20),))]
        plan = self.run_plan(crew)
        self.assertEqual([s for s in plan.steps if s.action == "supply"], [])


if __name__ == "__main__":
    unittest.main()
