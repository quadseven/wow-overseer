"""Class quests the book named as blockers no member could pass (2026-10-10).

Read on the dev realm on 2026-10-10 (quadseven/wow-overseer#781): `classquest.build`
over the live world named these reward chains blocked, and nobody was sent:

  paladin  The Tome of Divinity (1644, 1648) needs 10 Linen Cloth (2589), which
           10,501 creature spawns drop. 875 of them are elite or rare (Morgaine
           the Sly, 99, rank 4), and `any` elite named the quest GROUP.
  shaman   Call of Water: 1535, 1536 and 1534 hand over an Empty Waterskin
           (7766, 7768, 7767) whose spell (9586, 9583, 9584) fills it only at a
           water spell focus (224 Quilboar Watering Hole, 226 Spring Well, 223
           Ruins of Stardust Fountain). 220 and 96, and Call of Fire 1524 and
           1527, require back only the item the take hands over: a delivery,
           complete on the take. All six read SOURCE.
  warrior  The Affray (1719) asks for Big Will (6238), whom Twiggy Flathead's
           script summons once a warrior holding the quest steps on the grate
           beside him (zone_the_barrens.cpp: x -1684 to -1674, y -4334 to
           -4324). No spawn row holds him: SOURCE. Spawn 13575, a Muck Frenzy,
           lies on the grate's center.
  warlock  The Binding (1795) for the felhunter: the Barrens Summoning Circle
           (gameobject 92388, focus 103) has no spawn row because Acolyte Magaz
           (6252) summons it at (-770.5, -3720.4) when the quest is taken from
           Strahad Farsan (smart_scripts 6251 and 625200; upstream
           2021_06_11_01.sql deleted the static spawn). Magaz's spawn 14370
           stands 4.7 yards from it, inside the circle's 10 yard focus.
"""

import unittest

import classquest
import guildjobs
from test_classquest_use import carried, giver, qrow, spawn

PALADIN, SHAMAN, WARRIOR, WARLOCK = 2, 7, 1, 9
HUMAN, ORC = 1, 2
EASTERN, KALIMDOR = 0, 1
LINEN = 2589


def member(**over):
    base = dict(
        name="Zug",
        guild="Bonkers",
        role=guildjobs.RAIDER,
        level=30,
        class_id=WARRIOR,
        race=ORC,
        online=True,
        map_id=KALIMDOR,
        x=-1600.0,
        y=-4300.0,
        zone_id=17,
        eligible=True,
    )
    base.update(over)
    return guildjobs.Member(**base)


# ------------------------------------------------------------------ paladin --

MURLOCS = [
    spawn(79619, 285, -9473.71, -431.412, "Murloc", EASTERN),
    spawn(79620, 285, -9479.72, -430.688, "Murloc", EASTERN),
]
MORGAINE = spawn(80001, 99, -9480.0, -425.0, "Morgaine the Sly", EASTERN, rank=4)
DUTHORIAN = dict(spawn(1000, 6171, -8573.0, 879.0, "Duthorian Rall", EASTERN))


def tome_book(spawns, loot):
    row = qrow(
        1644,
        "The Tome of Divinity",
        sort=-141,
        classes=2,
        races=1,
        min_level=12,
        reward=7328,
        item1=LINEN,
        item_count1=10,
    )
    return classquest.build(
        quest_rows=[row],
        giver_rows=[giver(1644, "start", DUTHORIAN), giver(1644, "end", DUTHORIAN)],
        spawn_rows=spawns,
        loot_rows=loot,
    )


def paladin(**over):
    return member(
        name="Hokk",
        class_id=PALADIN,
        race=HUMAN,
        level=12,
        map_id=EASTERN,
        x=-9470.0,
        y=-420.0,
        zone_id=12,
        quest_log={1644: 3},
        **over,
    )


LINEN_LOOT = [{"item": LINEN, "entry": 285}, {"item": LINEN, "entry": 99}]


class TheLinen(unittest.TestCase):
    def test_an_elite_among_the_droppers_is_no_group(self):
        quest = tome_book(MURLOCS + [MORGAINE], LINEN_LOOT).quests[1644]
        self.assertEqual(classquest.blocker_of(quest, paladin()), ("", ""))

    def test_the_hunt_goes_to_the_droppers_it_can_kill_alone(self):
        book = tome_book(MURLOCS + [MORGAINE], LINEN_LOOT)
        move, blocked = classquest.next_move(book, paladin())
        self.assertEqual(blocked, [])
        self.assertEqual(move.kind, classquest.HUNT)
        self.assertEqual(move.spot.entry, 285)

    def test_linen_only_an_elite_drops_is_still_a_group(self):
        quest = tome_book([MORGAINE], [{"item": LINEN, "entry": 99}]).quests[1644]
        self.assertEqual(classquest.blocker_of(quest, paladin())[0], classquest.GROUP)

    def test_an_elite_kill_is_still_a_group(self):
        row = qrow(9, "Kill the boss", npc1=99, npc_count1=1)
        book = classquest.build(
            quest_rows=[row], giver_rows=[], spawn_rows=[MORGAINE], loot_rows=[]
        )
        self.assertEqual(
            classquest.blocker_of(book.quests[9], paladin())[0], classquest.GROUP
        )


# ------------------------------------------------------------------- shaman --

WATERING_HOLE = spawn(99864, 107046, -3573.24, -1864.45, "Quilboar Watering Hole")
SPRING_WELL = spawn(99863, 107045, -43.44, -923.2, "Spring Well", EASTERN)
STARDUST = spawn(99862, 107047, 2079.39, -234.62, "Ruins of Stardust Fountain")
ISLEN = dict(spawn(2000, 5901, -3500.0, -1800.0, "Islen Waterseer"))


def water_book(qid, empty, filled, focus, obj):
    row = qrow(
        qid,
        "Call of Water",
        sort=-82,
        classes=64,
        races=690,
        min_level=20,
        reward=5396,
        display=5394,
        item1=filled,
        item_count1=1,
        provided0=empty,
    )
    return classquest.build(
        quest_rows=[row],
        giver_rows=[giver(qid, "start", ISLEN), giver(qid, "end", ISLEN)],
        spawn_rows=[],
        loot_rows=[],
        object_rows=[obj],
        focus_rows=[{"focus": focus, "entry": obj["entry"]}],
    )


def shaman(**over):
    base = dict(
        name="Gorrk",
        class_id=SHAMAN,
        race=ORC,
        level=20,
        map_id=KALIMDOR,
        x=-3560.0,
        y=-1850.0,
        zone_id=17,
    )
    base.update(over)
    return member(**base)


class TheWaterskins(unittest.TestCase):
    def test_each_skin_names_its_water(self):
        # Spell.dbc's RequiresSpellFocus of 9586, 9583 and 9584.
        self.assertEqual(
            {i: classquest.FOCUS_ITEMS.get(i) for i in (7766, 7768, 7767)},
            {7766: 224, 7768: 226, 7767: 223},
        )

    def test_the_brown_skin_is_filled_at_the_watering_hole(self):
        book = water_book(1535, 7766, 7769, 224, WATERING_HOLE)
        m = shaman(quest_log={1535: 3}, carried=carried((7766, 1)))
        move, blocked = classquest.next_move(book, m)
        self.assertEqual(blocked, [])
        self.assertEqual(
            (move.kind, move.use.verb), (classquest.USE, classquest.USE_HERE)
        )
        self.assertEqual(move.spot.guid, 99864)
        self.assertEqual(
            classquest.use_command(move.use, move.spot), "use-item-here item:7766"
        )

    def test_a_filled_skin_is_handed_in(self):
        book = water_book(1535, 7766, 7769, 224, WATERING_HOLE)
        m = shaman(quest_log={1535: 1}, carried=carried((7766, 1), (7769, 1)))
        move, _ = classquest.next_move(book, m)
        self.assertEqual(move.kind, classquest.TURN_IN)

    def test_the_red_skin_at_the_spring_well_crosses_to_it(self):
        book = water_book(1536, 7768, 7771, 226, SPRING_WELL)
        m = shaman(quest_log={1536: 3}, carried=carried((7768, 1)))
        move, _ = classquest.next_move(book, m)
        self.assertEqual((move.kind, move.to_map), (classquest.CROSS, EASTERN))


def delivery_book(qid, title, item, sort=-82):
    row = qrow(
        qid,
        title,
        sort=sort,
        classes=64,
        races=690,
        min_level=10,
        reward=2075,
        item1=item,
        item_count1=1,
        provided0=item,
    )
    return classquest.build(
        quest_rows=[row],
        giver_rows=[giver(qid, "start", ISLEN), giver(qid, "end", ISLEN)],
        spawn_rows=[],
        loot_rows=[],
    )


class TheDeliveries(unittest.TestCase):
    def test_a_quest_that_asks_back_only_its_own_start_item_is_taken(self):
        for qid, title, item in (
            (220, "Call of Water", 7810),
            (96, "Call of Water", 7813),
            (1524, "Call of Fire", 6653),
            (1527, "Call of Fire", 6654),
        ):
            book = delivery_book(qid, title, item)
            self.assertEqual(
                classquest.blocker_of(book.quests[qid], shaman()), ("", ""), qid
            )
            move, blocked = classquest.next_move(book, shaman())
            self.assertEqual((move.kind, blocked), (classquest.TAKE, []), qid)

    def test_an_item_nothing_supplies_is_still_named(self):
        row = qrow(
            5, "Lost", sort=-82, classes=64, races=690, item1=1234, item_count1=1
        )
        book = classquest.build(
            quest_rows=[row],
            giver_rows=[giver(5, "start", ISLEN)],
            spawn_rows=[],
            loot_rows=[],
        )
        self.assertEqual(
            classquest.blocker_of(book.quests[5], shaman())[0], classquest.SOURCE
        )


# ------------------------------------------------------------------ warrior --

GRATE = spawn(13575, 8236, -1678.81, -4328.9, "Muck Frenzy")
KLANNOC = dict(spawn(14137, 6236, -1709.14, -4330.07, "Klannoc Macleod"))


def affray_book(spawns):
    row = qrow(
        1719,
        "The Affray",
        sort=-81,
        classes=1,
        races=0,
        min_level=30,
        reward=8616,
        display=0,
        npc1=6238,
        npc_count1=1,
    )
    return classquest.build(
        quest_rows=[row],
        giver_rows=[giver(1719, "start", KLANNOC), giver(1719, "end", KLANNOC)],
        spawn_rows=spawns,
        loot_rows=[],
    )


class TheAffray(unittest.TestCase):
    def test_big_will_is_summoned_on_the_grate(self):
        self.assertEqual(classquest.SCRIPTED_KILLS[6238], (8236, 13575))
        self.assertIn(8236, classquest.scripted_entries())

    def test_the_warrior_is_sent_onto_the_grate(self):
        book = affray_book([GRATE])
        move, blocked = classquest.next_move(book, member(quest_log={1719: 3}))
        self.assertEqual(blocked, [])
        self.assertEqual(move.kind, classquest.HUNT)
        self.assertEqual((move.spot.guid, move.spot.entry), (13575, 6238))
        spot = guildjobs._class_spot(move)
        self.assertEqual(
            spot.command,
            "walk-to-spawn creature:13575 near:%d" % classquest.SCRIPTED_NEAR,
        )

    def test_without_the_grate_read_it_is_named(self):
        quest = affray_book([]).quests[1719]
        self.assertEqual(classquest.blocker_of(quest, member())[0], classquest.SOURCE)


# ------------------------------------------------------------------ warlock --

MAGAZ = spawn(14370, 6252, -767.662, -3716.64, "Acolyte Magaz")
STRAHAD = dict(spawn(14366, 6251, -785.912, -3723.26, "Strahad Farsan"))
TOME, FELHUNTER = 6999, 6268


def felhunter_book(spawns):
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
        spawn_rows=spawns,
        loot_rows=[],
        object_rows=[],
        focus_rows=[{"focus": 103, "entry": 92388}],
    )


def warlock(**over):
    base = dict(
        name="Mok",
        class_id=WARLOCK,
        race=ORC,
        level=30,
        map_id=KALIMDOR,
        x=-786.0,
        y=-3722.0,
        zone_id=17,
        quest_log={1795: 3},
        carried=carried((TOME, 1)),
    )
    base.update(over)
    return member(**base)


class TheFelhunter(unittest.TestCase):
    def test_the_circle_is_summoned_beside_acolyte_magaz(self):
        self.assertEqual(classquest.SCRIPTED_FOCI[103], (6252, 14370))
        self.assertIn(6252, classquest.scripted_entries())

    def test_the_tome_is_used_at_magaz_once_the_quest_is_taken(self):
        move, blocked = classquest.next_move(felhunter_book([MAGAZ]), warlock())
        self.assertEqual(blocked, [])
        self.assertEqual(
            (move.kind, move.use.verb), (classquest.USE, classquest.USE_HERE)
        )
        spot = guildjobs._class_spot(move)
        self.assertEqual(
            spot.command,
            "walk-to-spawn creature:14370 near:%d" % classquest.SCRIPTED_NEAR,
        )
        self.assertEqual(
            classquest.use_command(move.use, move.spot), "use-item-here item:6999"
        )

    def test_without_magaz_read_the_circle_is_still_named(self):
        move, blocked = classquest.next_move(felhunter_book([]), warlock())
        self.assertIsNone(move)
        self.assertIn("92388", blocked[0])

    def test_the_bridge_reads_the_scripted_ground(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        self.assertTrue("classquest.scripted_entries()" in source)


if __name__ == "__main__":
    unittest.main()
