"""Class quest objectives a gameobject's use summons (#781, 2026-10-19).

The book named these SOURCE, "needs an objective no creature spawn or drop
supplies (... or a summoned spawn)", and nobody was sent: the creature to kill,
or the one whose loot the quest asks for, has no spawn row. Seven draenei
shamans held the draenei Call of Fire (9467) in progress on the dev realm on
2026-10-19 and none got past it. The world data names who summons each one, and
these are its rows (acore_world event_scripts, smart_scripts,
gameobject_template, creature_template, item_loot_template, gameobject):

  9467  Call of Fire (draenei shaman) asks for Hauteur's Ashes (23688), which
        Hauteur (17206) drops. The Wickerman Effigy (181672, goober, Data2
        event 10626, spawn 22150 on map 530) runs event_scripts 10626: command
        10 summons 17206. The take hands over a Fireproof Satchel (24336) that
        holds the Ritual Torch (23682) the quest asks back.
  9508  Call of Water (draenei shaman) asks for the Head of Tel'athion (23997),
        which Tel'athion the Impure (17359) drops. The Barrel of Filth (181699,
        event 10685, spawn 28522) summons him and two Water Spirits (6748).
  1819  Ulag the Cleaver (undead warrior) asks for Ulag (6390) killed. The
        Mausoleum Trigger (104593, spawn 44766 on map 0) calls the action list
        10459300 when it is activated (smart_scripts event 70, loot state 2),
        and the list's first action (12) summons him.

What the data cannot say stays named: Call of Water 63's Corrupt Minor
Manifestation of Water (5894) has no summoner in event_scripts or
smart_scripts, and Big Will (6238) of The Affray (1719) is summoned by a core
script (npc_twiggy_flathead), which the book's SCRIPTED_KILLS ground covers.
"""

import pathlib
import sqlite3
import unittest

from test_classquest_use import carried, giver, qrow, spawn, who

import classquest

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

SHAMAN, WARRIOR = 7, 1
DRAENEI, UNDEAD = 11, 5
EASTERN, OUTLAND = 0, 530

HAUTEUR, TELATHION, ULAG, WATER_SPIRIT = 17206, 17359, 6390, 6748
CORRUPT_WATER, BIG_WILL = 5894, 6238
EFFIGY, BARREL, TRIGGER = 181672, 181699, 104593
ASHES, TORCH, SATCHEL, ORB = 23688, 23682, 24336, 24335
HEAD, PURE_WATER = 23997, 23751

# event_scripts (id, delay, command, datalong): command 10 summons datalong.
EVENT_SCRIPTS = [
    (10626, 2, 10, HAUTEUR),
    (10685, 5, 10, WATER_SPIRIT),
    (10685, 5, 10, WATER_SPIRIT),
    (10685, 2, 10, TELATHION),
]
# gameobject_template (entry, type, name, Data0 lock, Data1 quest, Data2 event).
# The chest is no goober: its Data2 is no event, so it summons nothing.
GAMEOBJECTS = [
    (EFFIGY, 10, "Wickerman Effigy", 1660, 9467, 10626),
    (BARREL, 10, "Barrel of Filth", 1663, 9508, 10685),
    (TRIGGER, 10, "Mausoleum Trigger", 43, 1819, 0),
    (900001, 3, "A chest", 57, 0, 10626),
]
# smart_scripts (entryorguid, source_type, id, event_type, event_param1,
# action_type, action_param1).
SMART_SCRIPTS = [
    (TRIGGER, 1, 0, 70, 2, 80, 10459300),
    (10459300, 9, 0, 0, 0, 12, ULAG),
    (10459300, 9, 1, 0, 0, 9, 0),
    # The barrel's own rows summon more barrels (a gameobject, action 50).
    (BARREL, 1, 3, 60, 0, 50, BARREL),
]
# item_loot_template (Entry, Item): what the satchel holds.
HELD = [(SATCHEL, TORCH), (SATCHEL, ORB)]


def creatures(rank=0):
    return [
        (HAUTEUR, "Hauteur", rank),
        (TELATHION, "Tel'athion the Impure", rank),
        (WATER_SPIRIT, "Water Spirit", 0),
        (ULAG, "Ulag the Cleaver", rank),
        (CORRUPT_WATER, "Corrupt Minor Manifestation of Water", 0),
        (BIG_WILL, "Big Will", 0),
    ]


def _world(rank=0):
    """An in-memory acore_world holding the recorded rows."""
    con = sqlite3.connect(":memory:")
    con.execute("ATTACH DATABASE ':memory:' AS acore_world")
    con.execute(
        "CREATE TABLE acore_world.event_scripts "
        "(id INT, delay INT, command INT, datalong INT)"
    )
    con.execute(
        "CREATE TABLE acore_world.gameobject_template (entry INT, type INT, "
        "name TEXT, Data0 INT, Data1 INT, Data2 INT)"
    )
    con.execute(
        "CREATE TABLE acore_world.creature_template (entry INT, name TEXT, `rank` INT)"
    )
    con.execute(
        "CREATE TABLE acore_world.smart_scripts (entryorguid INT, source_type INT, "
        "id INT, event_type INT, event_param1 INT, action_type INT, "
        "action_param1 INT)"
    )
    con.execute("CREATE TABLE acore_world.item_loot_template (Entry INT, Item INT)")
    con.executemany(
        "INSERT INTO acore_world.event_scripts VALUES (?, ?, ?, ?)", EVENT_SCRIPTS
    )
    con.executemany(
        "INSERT INTO acore_world.gameobject_template VALUES (?, ?, ?, ?, ?, ?)",
        GAMEOBJECTS,
    )
    con.executemany(
        "INSERT INTO acore_world.creature_template VALUES (?, ?, ?)", creatures(rank)
    )
    con.executemany(
        "INSERT INTO acore_world.smart_scripts VALUES (?, ?, ?, ?, ?, ?, ?)",
        SMART_SCRIPTS,
    )
    con.executemany("INSERT INTO acore_world.item_loot_template VALUES (?, ?)", HELD)
    con.row_factory = sqlite3.Row
    return con


def ids(values):
    return ",".join(str(v) for v in values)


def summon_rows(rank=0, entries=(HAUTEUR, TELATHION, ULAG, CORRUPT_WATER, BIG_WILL)):
    sql = classquest.SUMMONERS_SQL.format(entries=ids(entries))
    return [dict(r) for r in _world(rank).execute(sql)]


def held_rows(items=(SATCHEL, PURE_WATER)):
    sql = classquest.HELD_SQL.format(items=ids(items))
    return [dict(r) for r in _world().execute(sql)]


# The summoners' spawns (OBJECT_SPAWNS_SQL rows) and the givers.
EFFIGY_SPAWN = spawn(22150, EFFIGY, -5027.12, -10966.0, "Wickerman Effigy", OUTLAND)
BARREL_SPAWN = spawn(28522, BARREL, -1647.35, -10922.1, "Barrel of Filth", OUTLAND)
TRIGGER_SPAWN = spawn(44766, TRIGGER, 2376.07, 359.997, "Mausoleum Trigger", EASTERN)
TEMPER = dict(spawn(61720, 17205, -3285.64, -12924.1, "Temper", OUTLAND))
AQUEOUS = dict(spawn(62043, 17275, -1110.26, -11128.9, "Aqueous", OUTLAND))
DILLINGER = dict(spawn(29796, 1496, 2287.66, 403.372, "Deathguard Dillinger", EASTERN))
ISLEN = dict(spawn(3000, 5901, -3700.0, -1900.0, "Islen Waterseer"))

# LOOT_SQL rows: who drops each required item.
LOOT = [
    {"item": ASHES, "entry": HAUTEUR},
    {"item": HEAD, "entry": TELATHION},
    {"item": 7812, "entry": CORRUPT_WATER},
]


def quest_rows():
    # The chains' spells, as the Bota Bag's book carries them: one step stands
    # alone.
    return [
        qrow(
            9467,
            "Call of Fire",
            sort=-82,
            classes=64,
            races=1101,
            min_level=10,
            display=3599,
            item1=ASHES,
            item_count1=1,
            item2=TORCH,
            item_count2=1,
            provided0=SATCHEL,
        ),
        qrow(
            9508,
            "Call of Water",
            sort=-82,
            classes=64,
            races=1024,
            min_level=20,
            display=5394,
            item1=HEAD,
            item_count1=1,
            item2=PURE_WATER,
            item_count2=1,
            provided0=PURE_WATER,
        ),
        qrow(
            1819,
            "Ulag the Cleaver",
            sort=-81,
            classes=1,
            races=0,
            min_level=10,
            display=71,
            npc1=ULAG,
            npc_count1=1,
        ),
        qrow(
            63,
            "Call of Water",
            sort=-82,
            classes=64,
            races=690,
            min_level=20,
            display=5396,
            item1=7812,
            item_count1=1,
            item2=7811,
            item_count2=1,
            provided0=7811,
        ),
    ]


def givers():
    out = []
    for quest, sp in ((9467, TEMPER), (9508, AQUEOUS), (1819, DILLINGER), (63, ISLEN)):
        out += [giver(quest, "start", sp), giver(quest, "end", sp)]
    return out


def book(summons=None, held=None, objects=None):
    return classquest.build(
        quest_rows=quest_rows(),
        giver_rows=givers(),
        spawn_rows=[],
        loot_rows=LOOT,
        object_rows=[EFFIGY_SPAWN, BARREL_SPAWN, TRIGGER_SPAWN]
        if objects is None
        else objects,
        summon_rows=summon_rows() if summons is None else summons,
        held_rows=held_rows() if held is None else held,
    )


def draenei(quest, level=12, **over):
    base = dict(
        name="Bluk",
        class_id=SHAMAN,
        race=DRAENEI,
        level=level,
        map_id=OUTLAND,
        x=-4900.0,
        y=-11000.0,
        zone_id=3524,
        quest_log={quest: 3},
    )
    base.update(over)
    return who(**base)


def undead(**over):
    base = dict(
        name="Eyesocket",
        class_id=WARRIOR,
        race=UNDEAD,
        level=12,
        map_id=EASTERN,
        x=2300.0,
        y=380.0,
        zone_id=85,
        quest_log={1819: 3},
    )
    base.update(over)
    return who(**base)


class TheSummonerRead(unittest.TestCase):
    def test_each_summoned_objective_names_its_gameobject(self):
        self.assertEqual(
            sorted((r["creature"], r["entry"], r["rank"]) for r in summon_rows()),
            [(ULAG, TRIGGER, 0), (HAUTEUR, EFFIGY, 0), (TELATHION, BARREL, 0)],
        )

    def test_no_data_names_a_summoner_for_the_corrupt_water_or_big_will(self):
        # 5894 has no event or smart script summon; Big Will's is a core script.
        self.assertEqual(summon_rows(entries=(CORRUPT_WATER, BIG_WILL)), [])

    def test_the_satchel_holds_the_ritual_torch(self):
        self.assertIn(
            (SATCHEL, TORCH), [(r["container"], r["item"]) for r in held_rows()]
        )

    def test_the_bridge_reads_the_summoners_and_what_a_take_hands_over_holds(self):
        body = BRIDGE[BRIDGE.index("def _class_use_reads") :]
        body = body[: body.index("def _class_rows")]
        self.assertIn("classquest.SUMMONERS_SQL", body)
        self.assertIn("classquest.HELD_SQL", body)
        self.assertIn('{int(r["entry"]) for r in summon_rows}', body)
        self.assertIn(
            "classquest.build(*world, summon_rows=summon_rows, held_rows=held_rows)",
            BRIDGE,
        )


class TheWickermanEffigy(unittest.TestCase):
    def test_call_of_fire_is_no_source(self):
        quest = book().quests[9467]
        m = draenei(9467, carried=carried((TORCH, 1)))
        self.assertEqual(classquest.blocker_of(quest, m), ("", ""))

    def test_the_member_walks_to_the_effigy_and_uses_it(self):
        move, blocked = classquest.next_move(
            book(), draenei(9467, carried=carried((TORCH, 1)))
        )
        self.assertEqual(blocked, [])
        self.assertEqual(move.kind, classquest.USE)
        self.assertEqual(move.spot.guid, 22150)
        self.assertEqual(
            classquest.use_command(move.use, move.spot), "use-gameobject 181672"
        )
        self.assertEqual(move.use.summons, (HAUTEUR,))

    def test_with_the_ashes_carried_the_effigy_is_not_used_again(self):
        # Hauteur was looted: the log catches up, then the quest is handed in.
        m = draenei(9467, carried=carried((TORCH, 1), (ASHES, 1)))
        move, blocked = classquest.next_move(book(), m)
        self.assertIsNone(move)
        self.assertIn("the quest log has not caught up", blocked[0])

    def test_the_ashes_and_the_torch_are_handed_in(self):
        m = draenei(9467, quest_log={9467: 1}, carried=carried((TORCH, 1), (ASHES, 1)))
        move, blocked = classquest.next_move(book(), m)
        self.assertEqual((move.kind, blocked), (classquest.TURN_IN, []))

    def test_without_the_satchel_read_the_torch_is_still_named(self):
        quest = book(held=[]).quests[9467]
        m = draenei(9467, carried=carried((TORCH, 1)))
        self.assertEqual(classquest.blocker_of(quest, m)[0], classquest.SOURCE)

    def test_without_the_summoner_read_hauteur_is_still_named(self):
        quest = book(summons=[]).quests[9467]
        m = draenei(9467, carried=carried((TORCH, 1)))
        self.assertEqual(classquest.blocker_of(quest, m)[0], classquest.SOURCE)


class TheBarrelOfFilth(unittest.TestCase):
    def test_the_member_uses_the_barrel_to_bring_telathion_out(self):
        m = draenei(
            9508,
            level=24,
            x=-1700.0,
            y=-10900.0,
            quests_done=frozenset({9467}),
            carried=carried((PURE_WATER, 1)),
        )
        self.assertEqual(classquest.blocker_of(book().quests[9508], m), ("", ""))
        move, blocked = classquest.next_move(book(), m)
        self.assertEqual(blocked, [])
        self.assertEqual((move.kind, move.spot.guid), (classquest.USE, 28522))
        self.assertEqual(
            classquest.use_command(move.use, move.spot), "use-gameobject 181699"
        )

    def test_an_elite_summoned_target_is_a_group(self):
        elite = book(summons=summon_rows(rank=1))
        m = draenei(
            9508,
            level=24,
            quests_done=frozenset({9467}),
            carried=carried((PURE_WATER, 1)),
        )
        self.assertEqual(
            classquest.blocker_of(elite.quests[9508], m)[0], classquest.GROUP
        )
        move, blocked = classquest.next_move(elite, m)
        self.assertIsNone(move)
        self.assertIn("group (Call of Water's objective is an elite)", blocked[0])


class TheMausoleumTrigger(unittest.TestCase):
    def test_ulag_is_summoned_through_the_action_list(self):
        move, blocked = classquest.next_move(book(), undead())
        self.assertEqual(blocked, [])
        self.assertEqual((move.kind, move.spot.guid), (classquest.USE, 44766))
        self.assertEqual(
            classquest.use_command(move.use, move.spot), "use-gameobject 104593"
        )

    def test_a_summoner_with_no_spawn_row_is_named_not_walked_to(self):
        quest = book(objects=[EFFIGY_SPAWN, BARREL_SPAWN]).quests[1819]
        self.assertEqual(classquest.blocker_of(quest, undead())[0], classquest.OBJECT)


class WhatTheDataCannotSay(unittest.TestCase):
    def test_a_creature_with_no_spawn_and_no_summoner_is_still_source(self):
        quest = book().quests[63]
        m = draenei(63, level=22, race=2, map_id=1, x=-3700.0, y=-1900.0)
        self.assertEqual(quest.uses, ())
        self.assertEqual(classquest.blocker_of(quest, m)[0], classquest.SOURCE)


if __name__ == "__main__":
    unittest.main()
