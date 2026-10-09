"""The death knight's The Emblazoned Runeblade: an item used beside a forge.

The quest (12619) hands over a Battle-worn Sword (38607) at Instructor
Razuvious; its spell works only beside a Runeforge (spell focus 1552, gameobject
190557 and its twins), and the Runebladed Sword (38631) it makes is the item the
quest asks for. Brug, Cave's level 60 death knight, stood in the starting zone
with this quest in his log and "the module has no verb for it" as his blocker
(2026-10-08). `use-item-here` is that verb (mod-overseer); these tests hold the
bridge's half: the walk to a forge, the one use row, and the turn in.
"""

import unittest

import classquest
import guildjobs
from test_classquest_use import carried, giver, qrow, spawn

DK, ORC, EBON_HOLD = 6, 2, 609
SWORD, RUNEBLADE = 38607, 38631
FOCUS = 1552
FORGE = 190557

RAZUVIOUS = dict(
    spawn(129307, 28357, 2498.07, -5593.25, "Instructor Razuvious", EBON_HOLD)
)
FORGE_SPAWN = spawn(129401, FORGE, 2418.0, -5583.0, "Runeforge", EBON_HOLD)


def runeblade(**over):
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
            provided0=SWORD,
        )
    ]
    args = dict(
        quest_rows=rows,
        giver_rows=[giver(12619, "start", RAZUVIOUS), giver(12619, "end", RAZUVIOUS)],
        spawn_rows=[],
        loot_rows=[],
        object_rows=[FORGE_SPAWN],
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


class TheBook(unittest.TestCase):
    def test_the_sword_is_a_use_beside_the_forge(self):
        quest = runeblade().quests[12619]
        self.assertEqual([u.verb for u in quest.uses], [classquest.USE_HERE])
        use = quest.uses[0]
        self.assertEqual((use.item, use.targets, use.provided), (SWORD, (FORGE,), True))
        self.assertEqual([s.guid for s in use.spots], [129401])

    def test_without_a_forge_spawn_the_quest_is_not_made_a_use(self):
        quest = runeblade(focus_rows=[]).quests[12619]
        self.assertEqual(quest.uses, ())

    def test_the_command_is_the_modules_here_verb(self):
        use = runeblade().quests[12619].uses[0]
        self.assertEqual(
            classquest.use_command(use, use.spots[0]), "use-item-here item:%d" % SWORD
        )


class TheMove(unittest.TestCase):
    def move(self, member):
        move, blocked = classquest.next_move(runeblade(), member)
        return move, blocked

    def test_a_knight_with_the_sword_uses_it_at_the_forge(self):
        move, blocked = self.move(knight(carried=carried((SWORD, 1))))
        self.assertEqual(blocked, [])
        self.assertEqual(
            (move.kind, move.use.verb), (classquest.USE, classquest.USE_HERE)
        )
        self.assertEqual(move.spot.guid, 129401)

    def test_a_knight_who_lost_the_sword_drops_the_quest_to_take_it_again(self):
        move, blocked = self.move(knight())
        self.assertEqual(blocked, [])
        self.assertEqual((move.kind, move.quest), (classquest.ABANDON, 12619))
        self.assertIsNone(move.spot)

    def test_a_knight_with_the_runeblade_turns_the_quest_in(self):
        move, _ = self.move(
            knight(carried=carried((RUNEBLADE, 1)), quest_log={12619: 1})
        )
        self.assertEqual(move.kind, classquest.TURN_IN)

    def test_the_quest_is_not_unmet_for_want_of_a_source(self):
        quest = runeblade().quests[12619]
        self.assertFalse(classquest._unmet(quest))


class TheAbandon(unittest.TestCase):
    def recent(self, age, quest=12619, name="Brug"):
        return guildjobs.recent_from_rows(
            [
                {
                    "target_name": name,
                    "command": "abandon quest:%d" % quest,
                    "source": guildjobs.source_for(classquest.ACTION, name),
                    "status": "delivered",
                    "age": age,
                    "result": "",
                }
            ]
        )

    def step(self, recent=()):
        m = knight()
        move, _ = classquest.next_move(runeblade(), m)
        return guildjobs._abandon_step(m, move, recent, "")

    def test_the_step_is_one_abandon_row_and_no_walk(self):
        step, said, _note = self.step()
        self.assertEqual(step.rows[0].kind, "quest")
        self.assertEqual(step.rows[0].command, "abandon quest:12619")
        self.assertIsNone(step.walk)
        self.assertIn("drops", said)

    def test_a_quest_dropped_lately_is_not_dropped_again(self):
        step, _said, note = self.step(self.recent(30))
        self.assertIsNone(step)
        self.assertIn("dropped lately", note)

    def test_the_hold_ends_at_its_edge(self):
        # Held while the drop is younger than the hold; free from the minute it
        # reaches it, and long after.
        edge = classquest.ABANDON_HOLD_MINUTES
        self.assertIsNone(self.step(self.recent(edge - 1))[0])
        self.assertIsNotNone(self.step(self.recent(edge))[0])
        self.assertIsNotNone(self.step(self.recent(edge * 2))[0])

    def taken(self, age, status="delivered"):
        return guildjobs.recent_from_rows(
            [
                {
                    "target_name": "Brug",
                    "command": "take quest:12619",
                    "source": guildjobs.source_for(classquest.ACTION, "Brug"),
                    "status": status,
                    "age": age,
                    "result": "",
                }
            ]
        )

    def test_a_quest_taken_lately_is_not_dropped_for_a_missing_item(self):
        # The saved bags trail the live game (2026-10-08).
        step, _said, note = self.step(self.taken(15))
        self.assertIsNone(step)
        self.assertIn("taken lately", note)

    def test_a_take_long_ago_no_longer_holds_it(self):
        step, _said, _note = self.step(self.taken(classquest.TAKE_SETTLE_MINUTES))
        self.assertIsNotNone(step)

    def test_a_take_that_failed_does_not_hold_it(self):
        step, _said, _note = self.step(self.taken(5, status="error"))
        self.assertIsNotNone(step)

    def test_the_take_row_reads_back_as_a_take(self):
        self.assertEqual(self.taken(5)[0].taken, 12619)

    def test_another_members_drop_does_not_hold_it(self):
        step, _said, _note = self.step(self.recent(5, name="Other"))
        self.assertIsNotNone(step)

    def test_the_row_reads_back_as_an_abandon(self):
        self.assertEqual(self.recent(5)[0].abandoned, 12619)


class TheStep(unittest.TestCase):
    def test_the_step_walks_to_the_forge_as_a_gameobject_then_uses(self):
        m = knight(carried=carried((SWORD, 1)))
        move, _ = classquest.next_move(runeblade(), m)
        step = guildjobs._use_step(m, move, guildjobs._class_spot(move), 5000)
        self.assertEqual(step.rows[0].command, "use-item-here item:%d" % SWORD)
        self.assertIn("gameobject:129401", step.walk.command)

    def test_a_use_here_row_is_followed_as_a_use_row(self):
        import classuse

        self.assertTrue(classuse.is_use_row("use-item-here item:38607"))


if __name__ == "__main__":
    unittest.main()
