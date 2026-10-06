"""A guild member does its class quests first, as a player does (classquest.py).

Measured on the dev realm on 2026-10-06: every Bonkers warrior at level 14 and
above, and three of Cave's, lacked Defensive Stance, Taunt and Sunder Armor, the
reward of the level-10 class quest chain they held (1498, 1819, 1678 at status 3)
and never finished. The ids, creatures and spawns below are rows read from
acore_world on that day: Path of Defense (1498) after Veteran Uzzek (1505), five
Thunder Lizard or Lightning Hide hides (item 6486) for the quest, handed in to
Uzzek (creature 5810); Ulag the Cleaver (1819), whose creature 6390 has no spawn
row because a script summons it.
"""

import pathlib
import unittest

import classquest
import guildcorps
import guildjobs
import guildlevel
import guildroute

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

WARRIOR, PRIEST = 1, 5
ORC, UNDEAD, TROLL = 2, 5, 8
KALIMDOR, EASTERN = 1, 0
ORC_MASK = 690


def qrow(qid, title, **over):
    row = {
        "id": qid,
        "title": title,
        "sort": -81,
        "min_level": 10,
        "races": ORC_MASK,
        "classes": 0,
        "prev": 0,
        "reward": 0,
        "display": 0,
        "grp": 0,
    }
    for i in range(1, 5):
        row["npc%d" % i] = 0
        row["npc_count%d" % i] = 0
    for i in range(1, 7):
        row["item%d" % i] = 0
        row["item_count%d" % i] = 0
    row.update(over)
    return row


UZZEK = {
    "guid": 19732,
    "entry": 5810,
    "map_id": 1,
    "x": 186.0,
    "y": -3597.0,
    "name": "Uzzek",
}
TARSHAW = {
    "guid": 7291,
    "entry": 3169,
    "map_id": 1,
    "x": 311.0,
    "y": -4828.0,
    "name": "Tarshaw",
}
SOREK = {
    "guid": 7443,
    "entry": 3354,
    "map_id": 1,
    "x": 1971.0,
    "y": -4808.0,
    "name": "Sorek",
}
LIZARD = {
    "guid": 4788,
    "entry": 3130,
    "map_id": 1,
    "x": 705.0,
    "y": -4112.0,
    "name": "Thunder Lizard",
    "rank": 0,
}
HIDE = {
    "guid": 12197,
    "entry": 3131,
    "map_id": 1,
    "x": 918.0,
    "y": -4269.0,
    "name": "Lightning Hide",
    "rank": 0,
}
DILLINGER = {
    "guid": 29796,
    "entry": 1496,
    "map_id": 0,
    "x": 2288.0,
    "y": 403.0,
    "name": "Deathguard Dillinger",
}


def givers():
    out = []
    for quest, role, spawn in (
        (1505, "start", TARSHAW),
        (1505, "start", SOREK),
        (1505, "end", UZZEK),
        (1498, "start", UZZEK),
        (1498, "end", UZZEK),
        (1818, "start", DILLINGER),
        (1818, "end", DILLINGER),
        (1819, "end", DILLINGER),
    ):
        out.append(dict(spawn, quest=quest, role=role))
    return out


def warrior_rows():
    return [
        qrow(1505, "Veteran Uzzek"),
        qrow(
            1498, "Path of Defense", prev=1505, reward=8121, item1=6486, item_count1=5
        ),
        qrow(1818, "Speak with Dillinger"),
        qrow(1819, "Ulag the Cleaver", prev=1818, reward=8121, npc1=6390, npc_count1=1),
    ]


def book(**over):
    args = dict(
        quest_rows=warrior_rows(),
        giver_rows=givers(),
        spawn_rows=[LIZARD, HIDE],
        loot_rows=[{"item": 6486, "entry": 3130}, {"item": 6486, "entry": 3131}],
    )
    args.update(over)
    return classquest.build(**args)


def who(name="Bigzug", **over):
    base = dict(
        name=name,
        guild="Bonkers",
        role=guildjobs.RAIDER,
        level=20,
        class_id=WARRIOR,
        race=ORC,
        online=True,
        map_id=KALIMDOR,
        x=-282.0,
        y=-4164.0,
        zone_id=14,
        eligible=True,
    )
    base.update(over)
    return guildjobs.Member(**base)


class TheBook(unittest.TestCase):
    def test_a_chain_runs_from_its_first_quest_to_the_reward(self):
        b = book()
        self.assertEqual(classquest.chain(b, 1498), [1505, 1498])
        self.assertEqual(classquest.chain(b, 1819), [1818, 1819])

    def test_the_reward_group_is_the_class_and_the_spell(self):
        b = book()
        self.assertEqual(b.groups, {(WARRIOR, (8121,)): [1498, 1819]})

    def test_the_objective_is_the_creatures_that_drop_the_item(self):
        quest = book().quests[1498]
        self.assertEqual({s.entry for s in quest.fields}, {3130, 3131})

    def test_a_class_comes_from_the_class_mask_or_the_class_sort(self):
        self.assertEqual(classquest.klass_of({"classes": 16, "sort": 0}), 5)
        self.assertEqual(classquest.klass_of({"classes": 0, "sort": -81}), WARRIOR)
        self.assertEqual(classquest.klass_of({"classes": 0, "sort": 14}), 0)
        self.assertEqual(classquest.klass_of({"classes": 1024, "sort": 0}), 11)

    def test_the_statements_name_the_world_database(self):
        for sql in (classquest.QUESTS_SQL, classquest.GIVERS_SQL, classquest.LOOT_SQL):
            self.assertIn("acore_world.", sql)
        self.assertIn("AllowableClasses", classquest.QUESTS_SQL)


class TheNextMove(unittest.TestCase):
    def move(self, m, b=None):
        return classquest.next_move(b or book(), m)

    def test_a_quest_held_incomplete_sends_the_member_to_the_objective(self):
        m = who(quest_log={1498: 3}, quests_done=frozenset({1505}))
        move, blocked = self.move(m)
        self.assertEqual((move.kind, move.quest), (classquest.HUNT, 1498))
        self.assertEqual(move.spot.guid, 4788)
        self.assertEqual(blocked, [])

    def test_a_complete_quest_is_handed_in_at_its_ender(self):
        m = who(quest_log={1498: 1}, quests_done=frozenset({1505}))
        move, _ = self.move(m)
        self.assertEqual(
            (move.kind, move.quest, move.spot.entry), (classquest.TURN_IN, 1498, 5810)
        )

    def test_the_first_quest_of_the_chain_is_taken_at_the_nearest_giver(self):
        move, _ = self.move(who(x=1900.0, y=-4800.0))
        self.assertEqual(
            (move.kind, move.quest, move.spot.entry), (classquest.TAKE, 1505, 3354)
        )

    def test_the_next_quest_is_taken_once_the_one_before_is_rewarded(self):
        move, _ = self.move(who(quests_done=frozenset({1505})))
        self.assertEqual(
            (move.kind, move.quest, move.spot.entry), (classquest.TAKE, 1498, 5810)
        )

    def test_a_rewarded_quest_or_a_known_spell_is_done(self):
        self.assertEqual(self.move(who(quests_done=frozenset({1505, 1498})))[0], None)
        self.assertEqual(self.move(who(known=frozenset({8121})))[0], None)

    def test_the_variant_in_the_log_wins_over_a_nearer_giver(self):
        # Held 1819 on Eastern Kingdoms, standing beside Dillinger or not.
        m = who(
            race=UNDEAD, map_id=EASTERN, x=2300.0, y=400.0, quest_log={1819: 3, 1818: 0}
        )
        m = who(
            race=UNDEAD,
            map_id=EASTERN,
            x=2300.0,
            y=400.0,
            quest_log={1819: 3},
            quests_done=frozenset({1818}),
        )
        move, blocked = self.move(m)
        self.assertIsNone(move)
        self.assertIn("Ulag the Cleaver", blocked[0])

    def test_a_class_quest_is_not_offered_below_its_level(self):
        self.assertIsNone(self.move(who(level=9))[0])

    def test_another_class_has_nothing_to_do_here(self):
        self.assertIsNone(self.move(who(class_id=PRIEST))[0])

    def test_a_giver_on_another_map_is_a_named_blocker(self):
        m = who(map_id=EASTERN, x=-9000.0, y=100.0, race=ORC)
        move, blocked = self.move(m)
        self.assertEqual(move.quest, 1818)  # Dillinger stands on its map
        move, blocked = self.move(who(map_id=530, x=0.0, y=0.0))
        self.assertIsNone(move)
        self.assertTrue(blocked)
        self.assertIn("map", blocked[0])


class TheBlockers(unittest.TestCase):
    def blocked(self, rows, spawns=(), loot=(), **who_over):
        b = classquest.build(
            quest_rows=rows,
            giver_rows=givers(),
            spawn_rows=list(spawns),
            loot_rows=list(loot),
        )
        m = who(**who_over)
        return classquest.next_move(b, m)

    def test_ulag_has_no_spawn_row_and_is_named_not_waited_on(self):
        move, blocked = self.blocked(
            [qrow(1819, "Ulag the Cleaver", reward=8121, npc1=6390, npc_count1=1)],
            quest_log={1819: 3},
        )
        self.assertIsNone(move)
        self.assertIn("no verb", blocked[0])

    def test_a_suggested_group_is_left_for_the_ask(self):
        move, blocked = self.blocked(
            [qrow(2000, "Group Job", reward=8121, grp=3, npc1=3130, npc_count1=1)],
            spawns=[LIZARD],
            quest_log={2000: 3},
        )
        self.assertIsNone(move)
        self.assertIn("group of 3", blocked[0])

    def test_an_elite_objective_is_a_group_kill(self):
        elite = dict(LIZARD, rank=1)
        move, blocked = self.blocked(
            [qrow(2001, "Elite Job", reward=8121, npc1=3130, npc_count1=1)],
            spawns=[elite],
            quest_log={2001: 3},
        )
        self.assertIsNone(move)
        self.assertIn("elite", blocked[0])

    def test_a_gameobject_objective_names_the_missing_verb(self):
        move, blocked = self.blocked(
            [qrow(2002, "Altar Job", reward=8121, npc1=-4000, npc_count1=1)],
            quest_log={2002: 3},
        )
        self.assertIsNone(move)
        self.assertIn("gameobject", blocked[0])

    def test_a_reward_a_trainer_teaches_is_the_trainers(self):
        b = classquest.build(
            quest_rows=warrior_rows(),
            giver_rows=givers(),
            spawn_rows=[LIZARD],
            loot_rows=[{"item": 6486, "entry": 3130}],
            trained_rows=[{"spell": 8121}],
        )
        self.assertIsNone(classquest.next_move(b, who())[0])

    def test_a_prerequisite_the_book_does_not_hold_keeps_the_quest_shut(self):
        rows = [qrow(10379, "Touch of Weakness", prev=10638, reward=19318)]
        move, blocked = self.blocked(rows, class_id=WARRIOR)
        self.assertIsNone(move)


def class_plan(members, b=None, **kw):
    kw.setdefault("masters", {"Cave": "Grug", "Bonkers": "Zug"})
    kw.setdefault("classes", b or book())
    kw.setdefault("cap", guildroute.FAR_WALK_YARDS)
    return guildjobs.plan(members, **kw)


def class_steps(result):
    return [s for s in result.steps if s.action == classquest.ACTION]


class TheStep(unittest.TestCase):
    def test_a_hunt_is_a_spawn_walk_to_the_objective(self):
        m = who(quest_log={1498: 3}, quests_done=frozenset({1505}))
        steps = class_steps(class_plan([m]))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].rows[0].kind, "job")
        self.assertTrue(
            steps[0].rows[0].command.startswith("walk-to-spawn creature:4788")
        )

    def test_a_take_walks_to_the_giver_then_takes_the_quest(self):
        m = who(quests_done=frozenset({1505}))
        step = class_steps(class_plan([m]))[0]
        self.assertTrue(step.walk.command.startswith("walk-to-spawn creature:19732"))
        self.assertEqual(
            step.rows,
            (
                guildcorps.Row(
                    "quest",
                    "take quest:1498",
                    "",
                    guildjobs.source_for("classquest", "Bigzug"),
                ),
            ),
        )

    def test_a_hand_in_walks_to_the_ender_then_turns_in(self):
        m = who(quest_log={1498: 1}, quests_done=frozenset({1505}))
        step = class_steps(class_plan([m]))[0]
        self.assertTrue(step.walk.command.startswith("walk-to-spawn creature:19732"))
        self.assertEqual(step.rows[0].command, "turnin quest:1498")

    def test_a_member_at_its_field_hunts_and_is_asked_nothing_else(self):
        m = who(quest_log={1498: 3}, quests_done=frozenset({1505}), x=720.0, y=-4100.0)
        result = class_plan([m])
        self.assertEqual(result.steps, ())
        self.assertIn(classquest.MARK, result.lines["Bigzug"])
        self.assertEqual(guildjobs.class_held(result.lines), {"Bigzug"})

    def test_a_recent_class_row_is_not_asked_again_at_once(self):
        m = who(quests_done=frozenset({1505}))
        recent = (guildjobs.Recent("Bigzug", classquest.ACTION, 3),)
        self.assertEqual(class_steps(class_plan([m], recent=recent)), [])

    def test_no_book_takes_no_class_step(self):
        m = who(quests_done=frozenset({1505}))
        self.assertEqual(
            class_steps(guildjobs.plan([m], masters={"Bonkers": "Zug"})), []
        )


class ThePriority(unittest.TestCase):
    """The class quest is the first rung: nothing else pre-empts it."""

    def test_it_comes_before_the_level_walk(self):
        # A level 20 warrior standing in a zone it has outgrown would be walked
        # to a hub; with a class quest to take it goes to the giver instead.
        m = who(quests_done=frozenset({1505}), zone_id=14)
        step = only(class_plan([m]), "Bigzug")
        self.assertEqual(step.action, classquest.ACTION)
        self.assertNotEqual(step.action, guildlevel.ACTION)

    def test_it_comes_before_gear_the_post_and_the_farm(self):
        source = guildjobs._member_step.__code__.co_names
        order = [
            n
            for n in source
            if n
            in (
                "class_step",
                "_gear_first",
                "_pvp_first",
                "_collect_first",
                "level_step",
                "_plan_member",
            )
        ]
        self.assertEqual(order[0], "class_step")
        self.assertEqual(order.index("class_step"), 0)

    def test_a_member_held_on_a_hunt_gets_no_ordinary_job(self):
        m = who(
            role=guildjobs.MAINTENANCE,
            quest_log={1498: 3},
            quests_done=frozenset({1505}),
            x=720.0,
            y=-4100.0,
        )
        result = class_plan([m])
        self.assertEqual(result.steps, ())
        self.assertNotIn("gathers", result.lines["Bigzug"])

    def test_its_allowance_is_its_own_and_larger_than_the_ordinary_jobs(self):
        self.assertGreater(
            guildjobs.CLASSQUEST_STEPS_PER_GUILD, guildjobs.STEPS_PER_GUILD
        )
        members = [
            who("W%d" % i, quests_done=frozenset({1505}), x=-282.0 + i)
            for i in range(8)
        ]
        steps = class_steps(class_plan(members))
        self.assertEqual(len(steps), guildjobs.CLASSQUEST_STEPS_PER_GUILD)

    def test_a_blocked_quest_is_named_and_the_ordinary_job_goes_on(self):
        m = who(
            race=UNDEAD,
            map_id=EASTERN,
            x=2300.0,
            y=400.0,
            quest_log={1819: 3},
            quests_done=frozenset({1818}),
        )
        result = class_plan([m])
        self.assertTrue(any("Ulag the Cleaver" in n for n in result.notes))

    def test_the_family_social_pass_does_not_ask_a_member_on_a_class_quest(self):
        self.assertIn("_classquest_held", BRIDGE)
        self.assertIn("guildjobs.class_held(plan.lines)", BRIDGE)


def only(result, name):
    steps = [s for s in result.steps if s.holder == name]
    assert len(steps) == 1, steps
    return steps[0]


class TheWiring(unittest.TestCase):
    def test_the_bridge_reads_the_book_the_log_and_the_rewards(self):
        for needle in (
            "classquest.QUESTS_SQL",
            "classquest.LOG_SQL",
            "classquest.REWARDED_SQL",
            "classquest.TRAINED_SQL",
            'classes=facts.get("class_book")',
        ):
            self.assertIn(needle, BRIDGE)

    def test_the_image_carries_the_module(self):
        self.assertIn("classquest.py", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
