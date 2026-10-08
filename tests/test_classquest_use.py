"""Class quests that need an item or a gameobject used (classquest.py, classuse.py).

Until mod-overseer#865 the module had no verb that uses anything, so every
class quest below was only NAMED as blocked: "Taming the Beast needs an item no
creature spawn or drop supplies". The ids, creatures and spawns are rows read
from acore_world on the dev realm on 2026-10-06:

  hunter  Taming the Beast (6062, 6083, 6082): each hands over a Taming Rod
          (15917, 15919, 15920) whose spell conditions bind it to one creature
          (3099 Dire Mottled Boar, 3107 Surf Crawler, 3126 Armored Scorpid);
  druid   Curing the Sick (6124): Curative Animal Salve (15826), bound to
          12296 Sickly Gazelle and 12298 Sickly Deer, credits 12299, which has
          no spawn;
  warlock The Stolen Tome (1598): Powers of the Void (6785) lies in the chest
          83763 (Stolen Books), a type 3 gameobject with one spawn;
          The Binding (1471): Runes of Summoning (6284) has no creature
          condition (it is cast at a Summoning Circle), so it stays blocked.
"""

import json
import pathlib
import unittest

import classask
import classquest
import classuse
import guildjobs
import guildroute

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

HUNTER, DRUID, WARLOCK = 3, 11, 9
ORC, HUMAN = 2, 1
KALIMDOR, EASTERN = 1, 0
ORC_TROLL_MASK = 130

ROD, SALVE, TOME = 15917, 15826, 6785


def qrow(qid, title, **over):
    row = {
        "id": qid,
        "title": title,
        "sort": -261,
        "min_level": 10,
        "races": ORC_TROLL_MASK,
        "classes": 4,
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
    for i in range(5):
        row["provided%d" % i] = 0
    row.update(over)
    return row


def spawn(guid, entry, x, y, name, map_id=KALIMDOR, rank=0):
    return {
        "guid": guid,
        "entry": entry,
        "map_id": map_id,
        "x": x,
        "y": y,
        "name": name,
        "rank": rank,
    }


THOTAR = dict(spawn(7293, 3171, 275.341, -4704.0, "Thotar"))
ORMAK = dict(spawn(7449, 3352, 2100.58, -4606.96, "Ormak Grimshot"))
BOARS = [
    spawn(3432, 3099, 47.2036, -4713.72, "Dire Mottled Boar"),
    spawn(3433, 3099, 728.011, -4828.39, "Dire Mottled Boar"),
    spawn(3435, 3099, -438.139, -4686.37, "Dire Mottled Boar"),
]
CRAWLERS = [spawn(4749, 3107, -990.279, -5455.54, "Surf Crawler")]
GAZELLE = spawn(13101, 3, 4.2843, -2322.3, "Sickly Gazelle")
GAZELLE["entry"] = 12296
DEER = spawn(36566, 12298, 7269.77, 27.9562, "Sickly Deer")
ALANNDARIAN = dict(spawn(37312, 3702, 6557.88, 472.97, "Alanndarian Nightsong"))
BOOKS = spawn(26767, 83763, -8957.04, -432.748, "Stolen Books", EASTERN)


def giver(quest, role, sp):
    return dict(sp, quest=quest, role=role)


def taming_rows():
    return [
        qrow(6062, "Taming the Beast", item1=ROD, item_count1=1, provided0=ROD),
        qrow(
            6083,
            "Taming the Beast",
            prev=6062,
            item1=15919,
            item_count1=1,
            provided0=15919,
        ),
        qrow(
            6082,
            "Taming the Beast",
            prev=6083,
            reward=1579,
            display=23356,
            item1=15920,
            item_count1=1,
            provided0=15920,
        ),
    ]


def taming_givers():
    out = []
    for quest in (6062, 6083, 6082):
        out += [giver(quest, "start", THOTAR), giver(quest, "end", THOTAR)]
    return out


# Item -> the creatures its spell is bound to (USE_ITEMS_SQL's rows).
TAMING_USES = [
    {"item": ROD, "target": 3099},
    {"item": 15919, "target": 3107},
    {"item": 15920, "target": 3126},
]


def taming(**over):
    args = dict(
        quest_rows=taming_rows(),
        giver_rows=taming_givers(),
        spawn_rows=BOARS
        + CRAWLERS
        + [spawn(4718, 3126, 665.0, -4255.0, "Armored Scorpid")],
        loot_rows=[],
        use_rows=TAMING_USES,
    )
    args.update(over)
    return classquest.build(**args)


def carried(*stacks):
    return tuple(
        guildjobs.Carried(guid=900 + i, entry=entry, count=count)
        for i, (entry, count) in enumerate(stacks)
    )


def who(name="Pokka", **over):
    base = dict(
        name=name,
        guild="Cave",
        role=guildjobs.RAIDER,
        level=13,
        class_id=HUNTER,
        race=ORC,
        online=True,
        map_id=KALIMDOR,
        x=300.0,
        y=-4700.0,
        zone_id=14,
        eligible=True,
    )
    base.update(over)
    return guildjobs.Member(**base)


# --- the chest and the salve ----------------------------------------------------


def tome_book(**over):
    args = dict(
        quest_rows=[
            qrow(
                1598,
                "The Stolen Tome",
                sort=-61,
                classes=256,
                races=HUMAN,
                min_level=1,
                reward=7763,
                display=688,
                item1=TOME,
                item_count1=1,
            )
        ],
        giver_rows=[],
        spawn_rows=[],
        loot_rows=[],
        chest_rows=[{"item": TOME, "entry": 83763}],
        object_rows=[BOOKS],
    )
    args.update(over)
    return classquest.build(**args)


def salve_book(**over):
    rows = [
        qrow(
            6124,
            "Curing the Sick",
            sort=-263,
            classes=1024,
            races=1101,
            min_level=14,
            prev=0,
            reward=8947,
            npc1=12299,
            npc_count1=1,
            provided0=SALVE,
        )
    ]
    args = dict(
        quest_rows=rows,
        giver_rows=[giver(6124, "start", ALANNDARIAN), giver(6124, "end", ALANNDARIAN)],
        spawn_rows=[GAZELLE, DEER],
        loot_rows=[],
        use_rows=[{"item": SALVE, "target": 12296}, {"item": SALVE, "target": 12298}],
    )
    args.update(over)
    return classquest.build(**args)


class TheUsesAreReadFromTheWorld(unittest.TestCase):
    def test_a_taming_rod_is_an_item_used_on_the_creature_its_spell_names(self):
        use = taming().quests[6062].uses[0]
        self.assertEqual(
            (use.verb, use.item, use.targets, use.provided),
            (classquest.USE_ITEM, ROD, (3099,), True),
        )
        self.assertEqual({s.guid for s in use.spots}, {3432, 3433, 3435})

    def test_each_rod_of_the_chain_names_its_own_creature(self):
        quests = taming().quests
        self.assertEqual(quests[6083].uses[0].targets, (3107,))
        self.assertEqual(quests[6082].uses[0].targets, (3126,))

    def test_a_credit_only_kill_with_a_salve_is_a_use_not_a_hunt(self):
        use = salve_book().quests[6124].uses[0]
        self.assertEqual(use.targets, (12296, 12298))
        self.assertEqual({s.entry for s in use.spots}, {12296, 12298})

    def test_a_required_item_only_a_chest_holds_is_a_gameobject_use(self):
        use = tome_book().quests[1598].uses[0]
        self.assertEqual(
            (use.verb, use.item, use.count, use.targets, use.provided),
            (classquest.USE_OBJECT, TOME, 1, (83763,), False),
        )
        self.assertEqual([s.guid for s in use.spots], [26767])

    def test_a_gameobject_objective_is_a_use_of_that_gameobject(self):
        b = classquest.build(
            quest_rows=[
                qrow(2002, "Altar Job", reward=8121, npc1=-83763, npc_count1=1)
            ],
            giver_rows=[],
            spawn_rows=[],
            loot_rows=[],
            object_rows=[BOOKS],
        )
        use = b.quests[2002].uses[0]
        self.assertEqual(
            (use.verb, use.item, use.targets), (classquest.USE_OBJECT, 0, (83763,))
        )
        self.assertEqual(len(use.spots), 1)

    def test_an_item_a_creature_drops_is_hunted_not_chested(self):
        b = tome_book(
            spawn_rows=[spawn(1, 5000, 0.0, 0.0, "Thief")],
            loot_rows=[{"item": TOME, "entry": 5000}],
        )
        self.assertEqual(b.quests[1598].uses, ())

    def test_with_no_use_rows_no_quest_has_a_use(self):
        b = taming(use_rows=[])
        self.assertTrue(all(q.uses == () for q in b.quests.values()))

    def test_the_item_a_quest_hands_over_is_read_from_the_quest_row(self):
        self.assertEqual(taming().quests[6062].provided, (ROD,))
        self.assertEqual(classquest.QUESTS_SQL.count("StartItem"), 1)
        self.assertIn("ItemDrop4", classquest.QUESTS_SQL)

    def test_the_new_reads_name_the_world_database_and_the_spell_condition(self):
        for sql in (
            classquest.USE_ITEMS_SQL,
            classquest.CHEST_SQL,
            classquest.OBJECT_SPAWNS_SQL,
        ):
            self.assertIn("acore_world.", sql)
        self.assertIn("SourceTypeOrReferenceId = 17", classquest.USE_ITEMS_SQL)
        self.assertIn("ConditionTypeOrReference = 31", classquest.USE_ITEMS_SQL)
        self.assertIn("spelltrigger_1 = 0", classquest.USE_ITEMS_SQL)
        self.assertIn("g.type = 3", classquest.CHEST_SQL)

    def test_the_book_names_the_items_to_read_from_a_bag_and_the_targets(self):
        b = taming()
        self.assertEqual(b.watch_items(), [ROD, 15919, 15920])
        self.assertEqual(b.use_entries(), ([3099, 3107, 3126], []))
        self.assertEqual(tome_book().use_entries(), ([], [83763]))
        self.assertEqual(tome_book().watch_items(), [TOME])


class TheUseMove(unittest.TestCase):
    def move(self, m, b=None):
        return classquest.next_move(b or taming(), m)

    def test_a_held_taming_quest_walks_to_the_nearest_boar_and_uses_the_rod(self):
        m = who(quest_log={6062: 3}, carried=carried((ROD, 1)))
        move, blocked = self.move(m)
        self.assertEqual((move.kind, move.quest), (classquest.USE, 6062))
        self.assertEqual(move.spot.guid, 3432)
        self.assertEqual(blocked, [])
        self.assertEqual(
            classquest.use_command(move.use, move.spot),
            "use-item-on creature:3099 item:15917",
        )

    def test_the_quest_is_taken_first_and_the_rod_comes_with_it(self):
        move, _ = self.move(who())
        self.assertEqual((move.kind, move.quest), (classquest.TAKE, 6062))

    def test_a_member_that_lost_its_rod_drops_the_quest_to_be_handed_it_again(self):
        # The quest hands the rod over when it is taken (2026-10-08), so a member
        # that lost it is not left waiting: it drops the quest and takes it anew.
        m = who(quest_log={6062: 3}, carried=())
        move, blocked = self.move(m)
        self.assertEqual((move.kind, move.quest), (classquest.ABANDON, 6062))
        self.assertEqual(blocked, [])

    def test_the_rod_is_used_again_for_the_next_quest_of_the_chain(self):
        m = who(
            quest_log={6083: 3},
            quests_done=frozenset({6062}),
            carried=carried((15919, 1)),
        )
        move, _ = self.move(m)
        self.assertEqual((move.kind, move.spot.entry), (classquest.USE, 3107))

    def test_a_complete_quest_is_handed_in_not_used_again(self):
        m = who(quest_log={6062: 1}, carried=carried((ROD, 1)))
        move, _ = self.move(m)
        self.assertEqual((move.kind, move.quest), (classquest.TURN_IN, 6062))

    def test_the_salve_is_used_on_the_nearest_sickly_beast(self):
        m = who(
            class_id=DRUID,
            race=HUMAN,
            level=14,
            map_id=KALIMDOR,
            x=7000.0,
            y=100.0,
            quest_log={6124: 3},
            quests_done=frozenset(),
            carried=carried((SALVE, 1)),
        )
        b = salve_book()
        # Its chain starts at 6124 here: nothing before it in this book.
        move, _ = self.move(m, b)
        self.assertEqual((move.kind, move.spot.entry), (classquest.USE, 12298))
        self.assertEqual(
            classquest.use_command(move.use, move.spot),
            "use-item-on creature:12298 item:15826",
        )

    def test_a_chest_is_clicked_until_the_item_is_in_the_bag(self):
        m = who(
            class_id=WARLOCK,
            race=HUMAN,
            level=5,
            map_id=EASTERN,
            x=-8900.0,
            y=-400.0,
            quest_log={1598: 3},
        )
        move, _ = self.move(m, tome_book())
        self.assertEqual((move.kind, move.spot.guid), (classquest.USE, 26767))
        self.assertEqual(
            classquest.use_command(move.use, move.spot), "use-gameobject 83763"
        )

    def test_a_chest_item_already_carried_is_not_clicked_again(self):
        m = who(
            class_id=WARLOCK,
            race=HUMAN,
            level=5,
            map_id=EASTERN,
            quest_log={1598: 3},
            carried=carried((TOME, 1)),
        )
        move, blocked = self.move(m, tome_book())
        self.assertIsNone(move)
        self.assertIn("log has not caught up", blocked[0])
        # Not a help the member asks guild chat for.
        self.assertEqual(classquest.helps(tome_book(), m), [])


class TheBlockersThatStay(unittest.TestCase):
    def test_a_world_before_the_verbs_names_the_use_quests_as_it_did(self):
        plain = taming().plain()
        self.assertTrue(all(q.uses == () for q in plain.quests.values()))
        m = who(quest_log={6062: 3}, carried=carried((ROD, 1)))
        move, blocked = classquest.next_move(plain, m)
        self.assertIsNone(move)
        self.assertIn("no verb", blocked[0])
        self.assertIn("Taming the Beast", blocked[0])

    def test_a_plain_book_is_the_same_book_when_nothing_in_it_has_a_use(self):
        b = taming(use_rows=[])
        self.assertIs(b.plain(), b)

    def test_the_voidwalker_runes_are_cast_at_a_circle_and_stay_blocked(self):
        # Runes of Summoning (6284) has no creature condition, and the creature
        # it summons (5676) has no spawn: no verb here reaches it.
        b = classquest.build(
            quest_rows=[
                qrow(
                    1471,
                    "The Binding",
                    sort=-61,
                    classes=256,
                    races=HUMAN,
                    reward=11520,
                    display=697,
                    npc1=5676,
                    npc_count1=1,
                    item1=6284,
                    item_count1=1,
                    provided0=6284,
                )
            ],
            giver_rows=[],
            spawn_rows=[],
            loot_rows=[],
            use_rows=[],
        )
        m = who(class_id=WARLOCK, race=HUMAN, level=12, quest_log={1471: 3})
        move, blocked = classquest.next_move(b, m)
        self.assertIsNone(move)
        self.assertIn("no verb", blocked[0])

    def test_an_elite_target_is_a_group_kill_not_a_use(self):
        elite = dict(BOARS[0], rank=1)
        b = taming(spawn_rows=[elite])
        m = who(quest_log={6062: 3}, carried=carried((ROD, 1)))
        move, blocked = classquest.next_move(b, m)
        self.assertIsNone(move)
        self.assertIn("elite", blocked[0])

    def test_a_target_on_another_map_is_named(self):
        m = who(quest_log={6062: 3}, carried=carried((ROD, 1)), map_id=EASTERN)
        move, blocked = classquest.next_move(taming(), m)
        self.assertIsNone(move)
        self.assertIn("another map", blocked[0])

    def test_a_target_with_no_spawn_row_is_named(self):
        b = taming(spawn_rows=[])
        m = who(quest_log={6062: 3}, carried=carried((ROD, 1)))
        move, blocked = classquest.next_move(b, m)
        self.assertIsNone(move)
        self.assertIn("no spawn row", blocked[0])

    def test_a_gameobject_objective_with_no_spawn_still_names_the_gameobject(self):
        b = classquest.build(
            quest_rows=[
                qrow(
                    2002,
                    "Altar Job",
                    sort=-81,
                    classes=0,
                    reward=8121,
                    npc1=-4000,
                    npc_count1=1,
                )
            ],
            giver_rows=[],
            spawn_rows=[],
            loot_rows=[],
        )
        m = who(class_id=1, quest_log={2002: 3})
        move, blocked = classquest.next_move(b, m)
        self.assertIsNone(move)
        self.assertIn("gameobject", blocked[0])

    def test_an_item_nothing_supplies_is_still_a_source_blocker(self):
        b = tome_book(chest_rows=[], object_rows=[])
        m = who(class_id=WARLOCK, race=HUMAN, level=5, quest_log={1598: 3})
        move, blocked = classquest.next_move(b, m)
        self.assertIsNone(move)
        self.assertIn("no creature spawn or drop", blocked[0])


class TheUseGivesUpAndAsks(unittest.TestCase):
    def test_a_use_given_up_is_a_help_the_member_asks_guild_chat_for(self):
        b = taming()
        hunts = classquest.Hunts()
        hunts.give_up("Pokka", 6062, 1000.0)
        avoid, off = hunts.state("Pokka", 1001.0)
        m = who(quest_log={6062: 3}, carried=carried((ROD, 1)))
        helps = classquest.helps(b, m, avoid, off)
        self.assertEqual([h.blocker for h in helps], [classquest.USE_STALLED])
        self.assertEqual(helps[0].want, 1)
        line = classask.ask_line(classquest.Help("Pokka", "Cave", 13, 1, helps[0]))
        self.assertIn("Taming the Beast", line)
        self.assertNotIn("hunt", line)

    def test_the_give_up_ends_after_its_hold(self):
        hunts = classquest.Hunts()
        hunts.give_up("Pokka", 6062, 1000.0)
        later = 1000.0 + classquest.GIVE_UP_MINUTES * 60 + 1
        self.assertEqual(hunts.state("Pokka", later), ({}, frozenset()))

    def test_a_target_tried_without_result_sends_the_member_to_another(self):
        b = taming()
        m = who(quest_log={6062: 3}, carried=carried((ROD, 1)))
        tried = {6062: ((KALIMDOR, 47.2036, -4713.72),)}
        move, _ = classquest.next_move(b, m, tried)
        self.assertEqual(move.kind, classquest.USE)
        self.assertNotEqual(move.spot.guid, 3432)

    def test_every_target_tried_is_asked_for_not_waited_on(self):
        b = taming()
        m = who(quest_log={6062: 3}, carried=carried((ROD, 1)))
        tried = {6062: tuple((KALIMDOR, s["x"], s["y"]) for s in BOARS)}
        move, blocked = classquest.next_move(b, m, tried)
        self.assertIsNone(move)
        self.assertEqual(
            [h.blocker for h in classquest.helps(b, m, tried)], [classquest.USE_STALLED]
        )


# --- the step -------------------------------------------------------------------


def class_plan(members, b, **kw):
    kw.setdefault("masters", {"Cave": "Grug"})
    kw.setdefault("classes", b)
    kw.setdefault("cap", guildroute.FAR_WALK_YARDS)
    return guildjobs.plan(members, **kw)


def class_steps(result):
    return [s for s in result.steps if s.action == classquest.ACTION]


class TheStep(unittest.TestCase):
    def member(self, **over):
        over.setdefault("quest_log", {6062: 3})
        over.setdefault("carried", carried((ROD, 1)))
        return who(**over)

    def test_the_use_is_a_walk_to_the_boar_and_a_quest_row(self):
        (step,) = class_steps(class_plan([self.member()], taming()))
        self.assertEqual(
            step.walk.command.split(" ")[0:2], ["walk-to-spawn", "creature:3432"]
        )
        (row,) = step.rows
        self.assertEqual(
            (row.kind, row.command),
            ("quest", "use-item-on creature:3099 item:15917"),
        )
        self.assertTrue(row.source.endswith("classquest:Pokka"))

    def test_a_chest_is_walked_to_as_a_gameobject(self):
        m = who(
            class_id=WARLOCK,
            race=HUMAN,
            level=5,
            map_id=EASTERN,
            x=-8900.0,
            y=-400.0,
            quest_log={1598: 3},
        )
        (step,) = class_steps(class_plan([m], tome_book()))
        self.assertIn("walk-to-spawn gameobject:26767", step.walk.command)
        self.assertEqual(step.rows[0].command, "use-gameobject 83763")

    def test_a_member_beside_its_target_writes_the_row_with_no_walk(self):
        m = self.member(x=BOARS[0]["x"] + 1.0, y=BOARS[0]["y"] + 1.0)
        (step,) = class_steps(class_plan([m], taming()))
        self.assertIsNone(step.walk)
        self.assertEqual(step.rows[0].kind, "quest")

    def test_a_world_before_the_verbs_gets_no_use_step_only_the_named_blocker(self):
        result = class_plan([self.member()], taming().plain())
        self.assertEqual(class_steps(result), [])
        self.assertTrue(any("Taming the Beast" in n for n in result.notes))

    def test_a_use_with_no_result_moves_to_another_target_after_the_stall(self):
        b = taming()
        hunts = classquest.Hunts()
        m = self.member(quest_progress={6062: 1})
        first = class_steps(class_plan([m], b, hunts=hunts, now=0.0))
        self.assertEqual(len(first), 1)
        stalled = classquest.HUNT_STALL_MINUTES * 60 + 1
        later = class_steps(class_plan([m], b, hunts=hunts, now=float(stalled)))
        self.assertEqual(len(later), 1)
        self.assertNotIn("creature:3432", later[0].walk.command)

    def test_a_use_given_up_is_a_help_in_the_plan(self):
        b = taming()
        hunts = classquest.Hunts()
        hunts.give_up("Pokka", 6062, 10.0)
        result = class_plan([self.member()], b, hunts=hunts, now=20.0)
        self.assertEqual(class_steps(result), [])
        self.assertEqual(
            [h.move.blocker for h in result.helps], [classquest.USE_STALLED]
        )


# --- what the world answered ------------------------------------------------------


def answer(status, detail="", **body):
    return classuse.judge("Pokka", status, detail, json.dumps(body) if body else "")


class TheAnswer(unittest.TestCase):
    def test_the_use_rows_are_told_from_every_other_quest_row(self):
        for command in (
            "use-item-on creature:3099 item:15917",
            "use-gameobject 83763",
        ):
            self.assertTrue(classuse.is_use_row(command))
        for command in ("take quest:6062", "turnin quest:6062", ""):
            self.assertFalse(classuse.is_use_row(command))

    def test_a_progressed_or_spent_use_is_done(self):
        self.assertEqual(
            answer("applied", outcome="progressed").state, classuse.PROGRESSED
        )
        self.assertEqual(answer("applied", outcome="spent").state, classuse.SPENT)
        self.assertTrue({classuse.PROGRESSED, classuse.SPENT} <= classuse.DONE)

    def test_a_use_that_changed_nothing_is_not_done(self):
        v = answer(
            "unchanged",
            "the use changed nothing the character could be read for",
            outcome="nothing",
        )
        self.assertEqual(v.state, classuse.NOTHING)
        self.assertNotIn(v.state, classuse.DONE)

    def test_an_applied_row_with_no_reading_is_not_trusted(self):
        self.assertEqual(answer("applied").state, classuse.UNREADABLE)
        self.assertEqual(
            answer("applied", outcome="refused").state, classuse.UNREADABLE
        )

    def test_a_character_that_left_the_world_is_unreadable(self):
        v = answer(
            "error",
            "left the world before the use could be read back",
            outcome="unreadable",
        )
        self.assertEqual(v.state, classuse.UNREADABLE)

    def test_never_gives_the_quest_up(self):
        v = answer(
            "error",
            "that item has no spell that takes a creature target",
            outcome="refused",
            retry="never",
        )
        self.assertEqual(v.state, classuse.NEVER)

    def test_elsewhere_walks_again(self):
        v = answer(
            "error",
            "character is inside an instance or battleground",
            outcome="refused",
            retry="elsewhere",
        )
        self.assertEqual((v.state, v.rewalk), (classuse.ELSEWHERE, True))

    def test_later_waits_and_a_target_out_of_reach_walks_again(self):
        busy = answer(
            "error", "character is in combat", outcome="refused", retry="later"
        )
        self.assertEqual((busy.state, busy.rewalk), (classuse.RETRY, False))
        self.assertEqual(busy.wait, classuse.LATER_WAIT_SECONDS)
        far = answer(
            "error",
            "the target is too far to use the item or object",
            outcome="refused",
            retry="later",
        )
        self.assertEqual((far.state, far.rewalk), (classuse.RETRY, True))
        dead = answer("error", "the creature is dead", outcome="refused", retry="later")
        self.assertEqual(dead.wait, classuse.DEAD_WAIT_SECONDS)

    def test_a_refusal_with_no_result_is_read_from_its_words(self):
        never = classuse.judge(
            "Pokka", "error", "the character does not carry that item", ""
        )
        self.assertEqual(never.state, classuse.NEVER)
        later = classuse.judge("Pokka", "error", "character is moving", "")
        self.assertEqual(later.state, classuse.RETRY)
        elsewhere = classuse.judge(
            "Pokka", "error", "character is inside an instance or battleground", ""
        )
        self.assertEqual(elsewhere.state, classuse.ELSEWHERE)

    def test_a_row_not_yet_answered_is_waited_on(self):
        for status in ("pending", "claimed", "verifying", ""):
            self.assertEqual(
                classuse.judge("Pokka", status, "", "").state, classuse.WAITING
            )

    def test_a_worldserver_before_the_verbs_is_unsupported(self):
        old = "malformed request: want take quest:<id> or turnin quest:<id>"
        self.assertEqual(answer("error", old).state, classuse.UNSUPPORTED)
        self.assertTrue(classuse.unsupported("error", old))
        # The new module's own malformed answer is a refusal, never unsupported.
        mine = "malformed use-item-on command"
        self.assertEqual(answer("error", mine, retry="never").state, classuse.NEVER)
        self.assertFalse(classuse.unsupported("error", mine))

    def test_a_result_that_is_not_json_is_read_as_none(self):
        v = classuse.judge("Pokka", "error", "character is moving", "not json")
        self.assertEqual(v.state, classuse.RETRY)


# --- the bridge -------------------------------------------------------------------


class TheBridgeFollowsTheAnswer(unittest.TestCase):
    def test_a_use_row_is_followed_by_its_answer_not_by_its_status_alone(self):
        self.assertIn("classuse.is_use_row(row.command)", BRIDGE)
        self.assertIn("async def _class_use_row(self, step, row, cap: float)", BRIDGE)
        self.assertIn("classuse.judge(", BRIDGE)

    def test_an_old_worldserver_is_not_asked_again_for_the_unsupported_window(self):
        body = BRIDGE[BRIDGE.index("async def _class_use_row") :]
        body = body[: body.index("async def _class_rewalk")]
        self.assertIn("classuse.UNSUPPORTED", body)
        self.assertIn("self._class_use_unsupported_until", body)
        self.assertIn("guildroute.WALK_UNSUPPORTED_SECONDS", body)

    def test_the_plan_works_from_the_plain_book_while_unsupported(self):
        body = BRIDGE[BRIDGE.index("def _class_book_for_plan") :]
        body = body[: body.index("async def _job_pvp_moves")]
        self.assertIn("self._class_use_unsupported_until", body)
        self.assertIn("book.plain()", body)
        self.assertIn("self._class_book_for_plan(facts)", BRIDGE)

    def test_never_gives_up_and_later_waits_a_bounded_number_of_times(self):
        body = BRIDGE[BRIDGE.index("async def _class_use_row") :]
        body = body[: body.index("async def _class_rewalk")]
        self.assertIn("self._class_hunts.give_up(step.holder, step.key", body)
        self.assertIn("classuse.MAX_ATTEMPTS", body)
        self.assertIn("classuse.REWALKS", body)
        self.assertIn("await asyncio.sleep(verdict.wait)", body)

    def test_the_book_reads_the_uses_and_the_bags_carry_their_items(self):
        for needle in (
            "classquest.USE_ITEMS_SQL",
            "classquest.CHEST_SQL",
            "classquest.OBJECT_SPAWNS_SQL",
            "book.watch_items()",
        ):
            self.assertIn(needle, BRIDGE)
        self.assertIn("return quests, givers, spawns, loot, trained, use_rows,", BRIDGE)

    def test_the_use_row_is_written_as_a_quest_row_of_the_class_step(self):
        body = BRIDGE[BRIDGE.index("def _insert_corps_row") :]
        body = body[: body.index("_JOB_")]
        self.assertIn("INSERT INTO overseer_command", body)


if __name__ == "__main__":
    unittest.main()
