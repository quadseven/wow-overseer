"""The warlock's The Binding: the take's item used at a summoning circle, then the demon killed.

Every Binding quest (voidwalker 1471, 1504, 1689 and 9619; succubus 1474,
1513 and 1739; felhunter 1795) hands its item over on the take (StartItem) and
requires it back with one kill of a Summoned Voidwalker (5676), Succubus (5677)
or Felhunter (6268). No creature row spawns those three: the item's spell
(Bloodstone Choker 6928, spell 7728) requires the Stormwind Summoning Circle
(spell focus 83, gameobject 92015) and sends event 1131, whose event_scripts row
summons a Summoned Voidwalker beside the circle. The rows are the dev realm's,
read on 2026-10-10; the foci are Spell.dbc's RequiresSpellFocus.

Measured that day: none of the two guilds' 50 warlocks knew Summon Voidwalker
(697) and none of the 39 at level 20 or above knew Summon Succubus (712), while
17 held a Binding quest at status 3. The book named every Binding SOURCE ("an
objective no creature spawn or drop supplies"), a permanent blocker, so nobody
was ever sent to the circle.
"""

import unittest

import classquest
import guildjobs
from test_classquest_use import carried, giver, qrow, spawn

WARLOCK, HUMAN = 9, 1
EASTERN, KALIMDOR = 0, 1
HUMAN_GNOME_MASK = 1 | 64
CHOKER = 6928
VOIDWALKER = 5676
STORMWIND_FOCUS = 83
CIRCLE = 92015
CIRCLE_SPAWN = spawn(42881, CIRCLE, -8973.05, 1043.72, "Summoning Circle", EASTERN)
GAKIN = dict(spawn(90471, 6122, -8983.0, 1041.52, "Gakin the Darkbinder", EASTERN))

# The Tome of the Cabal (6999) works only at the Barrens Summoning Circle
# (focus 103, gameobject 92388), which has no spawn row on this realm.
TOME, FELHUNTER, BARRENS_FOCUS, BARRENS_CIRCLE = 6999, 6268, 103, 92388
STRAHAD = dict(spawn(14366, 6251, -785.91, -3723.26, "Strahad Farsan", KALIMDOR))


def binding_row(**over):
    row = qrow(
        1689,
        "The Binding",
        sort=-61,
        classes=256,
        races=HUMAN_GNOME_MASK,
        min_level=10,
        reward=11520,
        display=697,
        npc1=VOIDWALKER,
        npc_count1=1,
        item1=CHOKER,
        item_count1=1,
        provided0=CHOKER,
    )
    row.update(over)
    return row


def book(**over):
    args = dict(
        quest_rows=[binding_row()],
        giver_rows=[giver(1689, "start", GAKIN), giver(1689, "end", GAKIN)],
        spawn_rows=[],
        loot_rows=[],
        object_rows=[CIRCLE_SPAWN],
        focus_rows=[{"focus": STORMWIND_FOCUS, "entry": CIRCLE}],
    )
    args.update(over)
    return classquest.build(**args)


def felhunter_book():
    row = qrow(
        1795,
        "The Binding",
        sort=-61,
        classes=256,
        races=0,
        min_level=30,
        reward=1373,
        display=691,
        npc1=FELHUNTER,
        npc_count1=1,
        item1=TOME,
        item_count1=1,
        provided0=TOME,
    )
    return classquest.build(
        quest_rows=[row],
        giver_rows=[giver(1795, "start", STRAHAD), giver(1795, "end", STRAHAD)],
        spawn_rows=[],
        loot_rows=[],
        object_rows=[],
        focus_rows=[{"focus": BARRENS_FOCUS, "entry": BARRENS_CIRCLE}],
    )


def warlock(**over):
    base = dict(
        name="Mukk",
        guild="Cave",
        role=guildjobs.RAIDER,
        level=22,
        class_id=WARLOCK,
        race=HUMAN,
        online=True,
        map_id=EASTERN,
        x=-8960.0,
        y=1030.0,
        zone_id=1519,
        eligible=True,
        quest_log={1689: 3},
        carried=carried((CHOKER, 1)),
    )
    base.update(over)
    return guildjobs.Member(**base)


class TheFoci(unittest.TestCase):
    def test_every_binding_item_names_its_circle(self):
        # Spell.dbc's RequiresSpellFocus of each item's on-use spell.
        self.assertEqual(
            {
                item: classquest.FOCUS_ITEMS.get(item)
                for item in (6284, 7464, 6928, 23732, 6286, 6626, 6913, 6999)
            },
            {
                6284: 43,
                7464: 203,
                6928: 83,
                23732: 1375,
                6286: 43,
                6626: 203,
                6913: 83,
                6999: 103,
            },
        )

    def test_the_death_knights_sword_keeps_its_forge(self):
        self.assertEqual(classquest.FOCUS_ITEMS[38607], 1552)


class TheBook(unittest.TestCase):
    def test_the_choker_is_used_beside_the_circle(self):
        quest = book().quests[1689]
        self.assertEqual([u.verb for u in quest.uses], [classquest.USE_HERE])
        use = quest.uses[0]
        self.assertEqual(
            (use.item, use.targets, use.provided), (CHOKER, (CIRCLE,), True)
        )
        self.assertEqual([s.guid for s in use.spots], [42881])

    def test_the_summoned_demon_is_no_unmet_kill(self):
        self.assertFalse(classquest._unmet(book().quests[1689]))

    def test_without_a_circle_the_summoned_kill_stays_unmet(self):
        quest = book(focus_rows=[], object_rows=[]).quests[1689]
        self.assertTrue(classquest._unmet(quest))


class TheMove(unittest.TestCase):
    def test_a_warlock_with_the_choker_uses_it_at_the_circle(self):
        move, blocked = classquest.next_move(book(), warlock())
        self.assertEqual(blocked, [])
        self.assertEqual(
            (move.kind, move.use.verb), (classquest.USE, classquest.USE_HERE)
        )
        self.assertEqual(move.spot.guid, 42881)
        self.assertEqual(
            classquest.use_command(move.use, move.spot),
            "use-item-here item:%d" % CHOKER,
        )

    def test_carrying_the_choker_is_not_the_quest_done(self):
        # The choker is the item the quest requires back, not a product of the
        # use: holding it says nothing about the voidwalker being dead.
        move, blocked = classquest.next_move(book(), warlock())
        self.assertNotIn("log has not caught up", " ".join(blocked))
        self.assertEqual(move.kind, classquest.USE)

    def test_the_binding_is_owed_not_permanently_blocked(self):
        owed = classquest.owed(book(), warlock())
        self.assertIsNotNone(owed)
        self.assertEqual((owed.quest, owed.blocker), (1689, ""))

    def test_a_warlock_on_the_other_continent_crosses(self):
        move, _ = classquest.next_move(
            book(), warlock(map_id=KALIMDOR, x=1800.0, y=-4400.0, zone_id=1637)
        )
        self.assertEqual((move.kind, move.to_map), (classquest.CROSS, EASTERN))

    def test_the_killed_demon_turns_the_quest_in(self):
        move, _ = classquest.next_move(book(), warlock(quest_log={1689: 1}))
        self.assertEqual(move.kind, classquest.TURN_IN)

    def test_a_lost_choker_is_named_not_used(self):
        move, blocked = classquest.next_move(book(), warlock(carried=()))
        self.assertNotEqual(getattr(move, "kind", None), classquest.USE)


class TheStep(unittest.TestCase):
    def test_the_step_walks_to_the_circle_then_uses_the_choker(self):
        m = warlock()
        move, _ = classquest.next_move(book(), m)
        step = guildjobs._use_step(m, move, guildjobs.class_spot(move), 5000)
        self.assertEqual(step.rows[0].command, "use-item-here item:%d" % CHOKER)
        self.assertIn("gameobject:42881", step.walk.command)


class TheFelhunter(unittest.TestCase):
    def test_a_circle_with_no_spawn_is_named_an_object_blocker(self):
        m = warlock(
            level=30,
            quest_log={1795: 3},
            carried=carried((TOME, 1)),
            map_id=KALIMDOR,
            x=-780.0,
            y=-3720.0,
            zone_id=17,
        )
        move, blocked = classquest.next_move(felhunter_book(), m)
        self.assertIsNone(move)
        self.assertIn(str(BARRENS_CIRCLE), blocked[0])
        self.assertIn("no spawn row", blocked[0])


if __name__ == "__main__":
    unittest.main()
