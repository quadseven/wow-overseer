"""The death knight's The Emblazoned Runeblade: a chest, then an item used beside a forge.

The quest (12619) is taken at Instructor Razuvious and hands over nothing: its
StartItem is 0. The Battle-worn Sword (38607) is its ItemDrop4, a source item
the core never gives on accept (Player::AddQuest -> GiveQuestSourceItem gives
the StartItem only). The sword is looted from a Battle-worn Sword chest
(gameobject 190584, type 3, loot 24611, 18 spawns on Acherus, map 609). Its
spell works only beside a Runeforge (spell focus 1552, gameobject 190557 and its
twins), and the Runebladed Sword (38631) it makes is the item the quest asks
for. The rows are the dev realm's, read on 2026-10-09.

Brug, Cave's level 60 death knight, was planned as if the take had handed him
the sword: he was sent to use a sword he never had, and dropped and took the
quest again and again for it. These tests hold the real path: take, open the
nearest sword chest (`use-gameobject 190584`), use the sword at a forge
(`use-item-here`), turn in.
"""

import unittest

import classquest
import guildjobs
from test_classquest_use import carried, giver, qrow, spawn

DK, ORC, EBON_HOLD = 6, 2, 609
SWORD, RUNEBLADE = 38607, 38631
FOCUS = 1552
FORGE = 190557
CHEST = 190584

RAZUVIOUS = dict(
    spawn(129307, 28357, 2498.07, -5593.25, "Instructor Razuvious", EBON_HOLD)
)
FORGE_SPAWN = spawn(129401, FORGE, 2418.0, -5583.0, "Runeforge", EBON_HOLD)
# Three of the eighteen Battle-worn Sword spawns (gameobject guids).
CHEST_SPAWNS = [
    spawn(65941, CHEST, 2385.21, -5571.25, "Battle-worn Sword", EBON_HOLD),
    spawn(65942, CHEST, 2452.44, -5523.57, "Battle-worn Sword", EBON_HOLD),
    spawn(65943, CHEST, 2381.37, -5586.32, "Battle-worn Sword", EBON_HOLD),
]
# The spawn nearest a knight standing at (2480, -5590).
NEAREST_CHEST = 65942


def runeblade(**over):
    # The quest_template row as the realm has it: StartItem 0, ItemDrop4 the
    # sword, RequiredItemId1 the runeblade.
    rows = [
        qrow(
            12619,
            "The Emblazoned Runeblade",
            sort=-372,
            classes=32,
            races=0,
            min_level=55,
            prev=0,
            reward=53431,
            display=53431,
            item1=RUNEBLADE,
            item_count1=1,
            source4=SWORD,
        )
    ]
    args = dict(
        quest_rows=rows,
        giver_rows=[giver(12619, "start", RAZUVIOUS), giver(12619, "end", RAZUVIOUS)],
        spawn_rows=[],
        loot_rows=[],
        chest_rows=[{"item": SWORD, "entry": CHEST}],
        object_rows=[FORGE_SPAWN, *CHEST_SPAWNS],
        focus_rows=[{"focus": FOCUS, "entry": FORGE}],
    )
    args.update(over)
    return classquest.build(**args)


def knight(**over):
    base = dict(
        name="Brug",
        guild="Cave",
        role=guildjobs.RAIDER,
        level=60,
        class_id=DK,
        race=ORC,
        online=True,
        map_id=EBON_HOLD,
        x=2480.0,
        y=-5590.0,
        zone_id=4298,
        eligible=True,
        quest_log={12619: 3},
    )
    base.update(over)
    return guildjobs.Member(**base)


def take_row(age=10):
    return guildjobs.recent_from_rows(
        [
            {
                "target_name": "Brug",
                "command": "take quest:12619",
                "source": guildjobs.source_for(classquest.ACTION, "Brug"),
                "status": "delivered",
                "age": age,
                "result": "",
            }
        ]
    )


class TheBook(unittest.TestCase):
    def test_the_take_hands_the_sword_over_not(self):
        quest = runeblade().quests[12619]
        self.assertEqual(quest.provided, ())
        self.assertEqual(quest.sources, (SWORD,))

    def test_the_sword_is_a_use_beside_the_forge_fetched_from_its_chest(self):
        quest = runeblade().quests[12619]
        self.assertEqual([u.verb for u in quest.uses], [classquest.USE_HERE])
        use = quest.uses[0]
        self.assertEqual(
            (use.item, use.targets, use.provided), (SWORD, (FORGE,), False)
        )
        self.assertEqual([s.guid for s in use.spots], [129401])
        fetch = use.fetch
        self.assertEqual(
            (fetch.verb, fetch.item, fetch.count, fetch.targets),
            (classquest.USE_OBJECT, SWORD, 1, (CHEST,)),
        )
        self.assertEqual({s.guid for s in fetch.spots}, {65941, 65942, 65943})

    def test_the_chest_is_one_of_the_gameobjects_the_book_reads(self):
        self.assertIn(CHEST, runeblade().use_entries()[1])

    def test_without_a_forge_spawn_the_quest_is_not_made_a_use(self):
        quest = runeblade(focus_rows=[]).quests[12619]
        self.assertEqual(quest.uses, ())

    def test_the_commands_are_the_modules_gameobject_and_here_verbs(self):
        use = runeblade().quests[12619].uses[0]
        self.assertEqual(
            classquest.use_command(use, use.spots[0]), "use-item-here item:%d" % SWORD
        )
        self.assertEqual(
            classquest.use_command(use.fetch, use.fetch.spots[0]),
            "use-gameobject %d" % CHEST,
        )


class TheMove(unittest.TestCase):
    def move(self, member, book=None):
        return classquest.next_move(book or runeblade(), member)

    def test_a_knight_without_the_quest_takes_it_first(self):
        move, _ = self.move(knight(quest_log={}))
        self.assertEqual((move.kind, move.quest), (classquest.TAKE, 12619))

    def test_a_knight_without_the_sword_opens_the_nearest_sword_chest(self):
        move, blocked = self.move(knight())
        self.assertEqual(blocked, [])
        self.assertEqual(
            (move.kind, move.use.verb), (classquest.USE, classquest.USE_OBJECT)
        )
        self.assertEqual(move.spot.guid, NEAREST_CHEST)
        self.assertEqual(
            classquest.use_command(move.use, move.spot), "use-gameobject %d" % CHEST
        )

    def test_a_knight_without_the_sword_never_drops_the_quest(self):
        # Dropping 12619 and taking it again does not bring the sword.
        for member in (knight(), knight(recently_taken=frozenset({12619}))):
            move, _ = self.move(member)
            self.assertNotEqual(move.kind, classquest.ABANDON)

    def test_with_no_chest_a_missing_sword_is_named_and_not_dropped_for(self):
        move, blocked = self.move(knight(), runeblade(chest_rows=[]))
        self.assertIsNone(move)
        self.assertIn("item (", blocked[0])
        self.assertIn("does not hand it over", blocked[0])

    def test_a_knight_with_the_sword_uses_it_at_the_forge(self):
        move, blocked = self.move(knight(carried=carried((SWORD, 1))))
        self.assertEqual(blocked, [])
        self.assertEqual(
            (move.kind, move.use.verb), (classquest.USE, classquest.USE_HERE)
        )
        self.assertEqual(move.spot.guid, 129401)

    def test_a_knight_with_the_runeblade_is_not_sent_back_to_the_chest(self):
        # The sword is spent making the runeblade; the log has not caught up.
        move, blocked = self.move(knight(carried=carried((RUNEBLADE, 1))))
        self.assertIsNone(move)
        self.assertIn("log has not caught up", blocked[0])

    def test_a_knight_with_the_runeblade_turns_the_quest_in(self):
        move, _ = self.move(
            knight(carried=carried((RUNEBLADE, 1)), quest_log={12619: 1})
        )
        self.assertEqual(move.kind, classquest.TURN_IN)

    def test_the_quest_is_not_unmet_for_want_of_a_source(self):
        quest = runeblade().quests[12619]
        self.assertFalse(classquest._unmet(quest))

    def test_a_chest_on_another_map_is_named(self):
        far = [dict(s, map_id=0) for s in CHEST_SPAWNS]
        move, blocked = self.move(knight(), runeblade(object_rows=[FORGE_SPAWN, *far]))
        self.assertIsNone(move)
        self.assertIn("another map", blocked[0])


class TheStep(unittest.TestCase):
    def test_the_step_walks_to_the_sword_chest_as_a_gameobject_then_opens_it(self):
        m = knight()
        move, _ = classquest.next_move(runeblade(), m)
        step = guildjobs._use_step(m, move, guildjobs._class_spot(move), 5000)
        self.assertEqual(step.rows[0].command, "use-gameobject %d" % CHEST)
        self.assertIn("gameobject:%d" % NEAREST_CHEST, step.walk.command)

    def test_the_step_walks_to_the_forge_as_a_gameobject_then_uses(self):
        m = knight(carried=carried((SWORD, 1)))
        move, _ = classquest.next_move(runeblade(), m)
        step = guildjobs._use_step(m, move, guildjobs._class_spot(move), 5000)
        self.assertEqual(step.rows[0].command, "use-item-here item:%d" % SWORD)
        self.assertIn("gameobject:129401", step.walk.command)

    def test_a_use_here_row_is_followed_as_a_use_row(self):
        import classuse

        self.assertTrue(classuse.is_use_row("use-item-here item:38607"))
        self.assertTrue(classuse.is_use_row("use-gameobject %d" % CHEST))


class TheLatelyTakenQuest(unittest.TestCase):
    """A take lately is trusted for a StartItem only: 12619 hands over nothing,
    so a knight that took it lately goes for the sword chest (2026-10-09)."""

    def test_a_lately_taken_quest_is_not_trusted_to_have_handed_the_sword_over(self):
        move, blocked = classquest.next_move(
            runeblade(), knight(recently_taken=frozenset({12619}))
        )
        self.assertEqual(blocked, [])
        self.assertEqual(
            (move.kind, move.use.verb), (classquest.USE, classquest.USE_OBJECT)
        )
        self.assertEqual(move.spot.guid, NEAREST_CHEST)

    def test_class_step_goes_from_a_take_row_to_the_sword_chest(self):
        # The wire end to end: a take row inside the settle window, no sword in
        # the saved bags, and class_step walks to the chest and opens it.
        step, _doing, _note = guildjobs.class_step(
            knight(), runeblade(), take_row(), 5000
        )
        self.assertEqual(step.rows[0].command, "use-gameobject %d" % CHEST)
        self.assertIn("gameobject:%d" % NEAREST_CHEST, step.walk.command)

    def test_class_step_marks_a_member_from_its_recent_take(self):
        self.assertEqual(
            guildjobs.with_recent_takes(knight(), take_row()).recently_taken, {12619}
        )
        self.assertEqual(
            guildjobs.with_recent_takes(knight(), ()).recently_taken, frozenset()
        )


if __name__ == "__main__":
    unittest.main()
