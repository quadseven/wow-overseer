"""The death knight's Runeforging: Preparation For Battle (12842) is a cast, not a hunt.

The quest has no objective rows (SpecialFlags 2): it completes when a rune
spell is cast on the main-hand weapon beside a Runeforge, which credits
Runeforging Credit (54586). The module has a verb for exactly that,
`cast-spell-on-mainhand spell:<id>`; the bridge never sent it, so the knight
read "every pack of its objective was tried" 362 times in five days and never
left the starting zone. These tests hold the table from quest to spell and
focus, and the step that walks to the forge and casts.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import classquest
import classuse
import guildjobs
import guildroute
from test_classquest_use import giver, qrow, spawn
from test_classquest_use_here import EBON_HOLD, FORGE, FORGE_SPAWN, knight

QUEST, RAZORICE, FOCUS = 12842, 53343, 1552
INSTRUCTOR = dict(spawn(129330, 28357, 2498.07, -5593.25, "Instructor", EBON_HOLD))


def runeforging(**over):
    rows = [
        qrow(
            QUEST,
            "Runeforging: Preparation For Battle",
            sort=-372,
            classes=32,
            races=0,
            min_level=55,
            prev=0,
            reward=53431,
            display=53431,
        )
    ]
    args = dict(
        quest_rows=rows,
        giver_rows=[giver(QUEST, "start", INSTRUCTOR), giver(QUEST, "end", INSTRUCTOR)],
        spawn_rows=[],
        loot_rows=[],
        object_rows=[FORGE_SPAWN],
        focus_rows=[{"focus": FOCUS, "entry": FORGE}],
    )
    args.update(over)
    return classquest.build(**args)


def move_of(member, book=None):
    return classquest.next_move(book or runeforging(), member)


class TheTable(unittest.TestCase):
    def test_the_quest_maps_to_razorice_at_the_runeforge_focus(self):
        self.assertEqual(classquest.MAINHAND_CASTS[QUEST], (RAZORICE, FOCUS))

    def test_the_quest_is_one_cast_use_at_the_forge(self):
        uses = runeforging().quests[QUEST].uses
        self.assertEqual([u.verb for u in uses], [classquest.CAST_MAINHAND])
        self.assertEqual((uses[0].spell, uses[0].targets), (RAZORICE, (FORGE,)))
        self.assertEqual([s.guid for s in uses[0].spots], [FORGE_SPAWN["guid"]])

    def test_a_quest_off_the_table_gets_no_cast(self):
        book = runeforging(quest_rows=[qrow(1, "Other", sort=-372, classes=32)])
        self.assertEqual(book.quests[1].uses, ())

    def test_the_quest_is_not_unmet_for_want_of_a_source(self):
        self.assertFalse(classquest._unmet(runeforging().quests[QUEST]))


class TheMove(unittest.TestCase):
    def test_a_knight_holding_the_quest_casts_at_the_forge(self):
        move, blocked = move_of(knight(quest_log={QUEST: 3}))
        self.assertEqual(blocked, [])
        self.assertEqual(
            (move.kind, move.use.verb), (classquest.USE, classquest.CAST_MAINHAND)
        )
        self.assertEqual(move.spot.guid, FORGE_SPAWN["guid"])

    def test_the_command_is_the_modules_main_hand_verb(self):
        move, _ = move_of(knight(quest_log={QUEST: 3}))
        self.assertEqual(
            classquest.use_command(move.use, move.spot),
            "cast-spell-on-mainhand spell:%d" % RAZORICE,
        )

    def test_a_forge_with_no_spawn_is_named_not_hunted(self):
        move, blocked = move_of(
            knight(quest_log={QUEST: 3}), runeforging(object_rows=[])
        )
        self.assertIsNone(move)
        self.assertIn("no spawn row", blocked[0])

    def test_a_forge_on_another_map_is_named(self):
        far = dict(FORGE_SPAWN, map_id=0)
        move, blocked = move_of(
            knight(quest_log={QUEST: 3}), runeforging(object_rows=[far])
        )
        self.assertIsNone(move)
        self.assertIn("another map", blocked[0])

    def test_a_completed_quest_is_handed_in_not_cast_again(self):
        move, _ = move_of(knight(quest_log={QUEST: 1}))
        self.assertEqual(move.kind, classquest.TURN_IN)


class TheStep(unittest.IsolatedAsyncioTestCase):
    WALK = "walk-to-spawn gameobject:%d near:8 max:5000" % FORGE_SPAWN["guid"]

    def test_the_step_walks_inside_the_focus_radius_then_casts(self):
        m = knight(quest_log={QUEST: 3}, x=FORGE_SPAWN["x"] + 13.2, y=FORGE_SPAWN["y"])
        step, _, _ = guildjobs.class_step(m, runeforging(), [], 5000)
        self.assertEqual(step.walk.command, self.WALK)
        self.assertEqual(step.rows[0].command, "cast-spell-on-mainhand spell:53343")

    def test_a_knight_already_beside_the_forge_casts_without_walking(self):
        m = knight(quest_log={QUEST: 3}, x=FORGE_SPAWN["x"] + 3, y=FORGE_SPAWN["y"])
        step, _, _ = guildjobs.class_step(m, runeforging(), [], 5000)
        self.assertIsNone(step.walk)
        self.assertEqual(step.rows[0].command, "cast-spell-on-mainhand spell:53343")

    async def test_a_repeat_walk_keeps_the_focus_radius(self):
        from test_guildsocial_bridge import bridge

        m = knight(quest_log={QUEST: 3})
        step, _, _ = guildjobs.class_step(m, runeforging(), [], 5000)
        follow = mock.AsyncMock(
            return_value=(SimpleNamespace(state=guildroute.ARRIVED), 1)
        )
        with mock.patch.object(bridge, "_insert_corps_row", return_value=1) as insert:
            arrived = await bridge.Bridge._class_rewalk(
                SimpleNamespace(_follow_guild_walk=follow), step, 5000
            )
        self.assertTrue(arrived)
        self.assertEqual(insert.call_args.args[1].command, self.WALK)

    def test_the_cast_row_is_followed_as_a_use_row(self):
        self.assertTrue(classuse.is_use_row("cast-spell-on-mainhand spell:53343"))


if __name__ == "__main__":
    unittest.main()
