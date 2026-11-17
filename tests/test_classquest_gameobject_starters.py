"""A Blood Elf warlock reaches and takes its gameobject-started Voidwalker quest."""

import unittest
from pathlib import Path

import classquest
import guildjobs
from test_classquest import who

WARLOCK = 9
BLOOD_ELF = 10
OUTLAND = 530
RUNE_QUEST = 9619
SUCCUBUS_QUEST = 1474
VOIDWALKER_SPELL = 697
SUCCUBUS_SPELL = 712
ORB_ENTRY = 184503
ORB = {
    "guid": 2001,
    "entry": ORB_ENTRY,
    "map_id": 0,
    "x": 50.0,
    "y": 50.0,
    "name": "Orb of Translocation",
}
RUNE_SPAWN = {
    "guid": 2002,
    "entry": 181698,
    "map_id": OUTLAND,
    "x": 50.0,
    "y": 50.0,
    "name": "Rune of Summoning",
    "creature": 0,
}
SUCCUBUS_GIVER = {
    "guid": 2003,
    "entry": 6268,
    "map_id": 1,
    "x": 50.0,
    "y": 50.0,
    "name": "Succubus quest giver",
}


def qrow(qid, title, **over):
    row = {
        "id": qid,
        "title": title,
        "sort": -61,
        "min_level": 10,
        "races": 1 << (BLOOD_ELF - 1),
        "classes": 1 << (WARLOCK - 1),
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


def book():
    quests = [
        qrow(RUNE_QUEST, "The Rune of Summoning", display=VOIDWALKER_SPELL),
        qrow(
            SUCCUBUS_QUEST,
            "The Succubus Quest",
            min_level=20,
            display=SUCCUBUS_SPELL,
        ),
    ]
    givers = [
        dict(RUNE_SPAWN, quest=RUNE_QUEST, role="start"),
        dict(SUCCUBUS_GIVER, quest=SUCCUBUS_QUEST, role="start"),
    ]
    return classquest.build(
        quest_rows=quests,
        giver_rows=givers,
        spawn_rows=[],
        loot_rows=[],
        start_rows=[
            {"quest": RUNE_QUEST, "kind": "gameobject", "entry": RUNE_SPAWN["entry"]},
            {"quest": SUCCUBUS_QUEST, "kind": "creature", "entry": SUCCUBUS_GIVER["entry"]},
        ],
        condition_rows=[
            {
                "quest": RUNE_QUEST,
                "grp": 0,
                "kind": 8,
                "value1": 9529,
                "value2": 0,
                "negative": 0,
            }
        ],
        isle_orb_rows=[ORB],
    )


def blood_elf_warlock(**over):
    member = dict(
        class_id=WARLOCK,
        race=BLOOD_ELF,
        level=20,
        map_id=0,
        x=0.0,
        y=0.0,
        quest_log={},
        quests_done=frozenset({9529}),
        known=frozenset(),
    )
    member.update(over)
    return who("Test Warlock", **member)


class TheGameobjectStartedRune(unittest.TestCase):
    def test_the_class_giver_read_includes_gameobject_starter_spawns(self):
        self.assertIn("gameobject_queststarter", classquest.GAMEOBJECT_GIVERS_SQL)
        self.assertIn(
            "JOIN acore_world.gameobject g ON g.id = s.id",
            classquest.GAMEOBJECT_GIVERS_SQL,
        )
        self.assertIn("JOIN acore_world.gameobject_template", classquest.GAMEOBJECT_GIVERS_SQL)
        self.assertIn("0 AS creature", classquest.GAMEOBJECT_GIVERS_SQL)
        self.assertIn("WHERE g.id = 184503 AND g.map = 0", classquest.ISLE_ORB_SQL)

    def test_the_bridge_reads_the_orb_spawns_into_the_class_book(self):
        source = (Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        start = source.index("def _class_book_reads(")
        end = source.index("def _class_use_reads(", start)
        book_reader = source[start:end]
        self.assertIn("classquest.GAMEOBJECT_GIVERS_SQL", book_reader)
        self.assertIn("classquest.ISLE_ORB_SQL", book_reader)
        self.assertIn("isle_orb_rows=isle_orb_rows", source)

    def test_a_blood_elf_in_the_eastern_kingdoms_takes_the_orb_route_first(self):
        move, _blocked = classquest.next_move(book(), blood_elf_warlock())
        self.assertEqual(
            (move.kind, move.quest, move.to_map),
            (classquest.ISLE_ORB, RUNE_QUEST, OUTLAND),
        )
        self.assertEqual(move.spot.entry, ORB_ENTRY)

    def test_a_blood_elf_on_kalimdor_crosses_to_the_orb_before_later_rewards(self):
        move, _blocked = classquest.next_move(
            book(), blood_elf_warlock(map_id=1, x=50.0, y=50.0)
        )
        self.assertEqual(
            (move.kind, move.quest, move.to_map),
            (classquest.CROSS, RUNE_QUEST, 0),
        )

    def test_a_blood_elf_on_map_530_takes_the_quest_at_its_gameobject_spawn(self):
        move, blocked = classquest.next_move(
            book(), blood_elf_warlock(map_id=OUTLAND, x=50.0, y=50.0)
        )
        self.assertEqual((move.kind, move.quest), (classquest.TAKE, RUNE_QUEST))
        self.assertEqual(
            (move.spot.guid, move.spot.entry),
            (RUNE_SPAWN["guid"], RUNE_SPAWN["entry"]),
        )
        self.assertEqual(blocked, [])

    def test_the_class_step_walks_to_the_gameobject_quest_giver(self):
        step, _doing, _note = guildjobs.class_step(
            blood_elf_warlock(map_id=OUTLAND, x=0.0, y=0.0), book(), [], 5000
        )
        self.assertIsNotNone(step)
        self.assertEqual(
            step.walk.command, "walk-to-spawn gameobject:2002 max:5000"
        )
        self.assertEqual(step.rows[0].command, "take quest:9619")

    def test_the_class_step_walks_to_and_uses_the_undercity_orb(self):
        step, _doing, _note = guildjobs.class_step(
            blood_elf_warlock(), book(), [], 5000
        )
        self.assertIsNotNone(step)
        self.assertEqual(step.rows[0].command, "use-gameobject 184503")
        self.assertEqual(
            step.walk.command, "walk-to-spawn gameobject:2001 max:5000"
        )


if __name__ == "__main__":
    unittest.main()
