"""A quester is never sent to a quest giver of the other side (#1998).

2026-11-07 on the dev realm: Velo, a level 31 Draenei shaman in Felwood, was
sent on every quester pass to Eitrigg in Orgrimmar for The New Horde (787,
level 1, AllowableRaces 0), and alternated it with a refused crossing to the
Eastern Kingdoms. Tharn, a level 19 Night Elf, was sent there too, and Tahomi,
a level 26 Tauren, to Denalan in Teldrassil."""

import unittest

import classquest
import guildjobs
import questers
from test_questers import crossing_row, giver, quest

DUROTAR, TELDRASSIL, DUN_MOROGH, FELWOOD, ASHENVALE, STV = 14, 141, 1, 361, 331, 33
DRAENEI, TAUREN = 11, 6
SHAMAN = 7
KALIMDOR, EASTERN = 1, 0
# factiontemplate_dbc FactionGroup / EnemyGroup bits: 2 Alliance, 4 Horde,
# 8 monster. Eitrigg (template 29) and Denalan (template 79) as read live.
EITRIGG = {"faction_group": 4, "enemy_group": 2}
DENALAN = {"faction_group": 3, "enemy_group": 12}
SENTINEL = {"faction_group": 3, "enemy_group": 12}


def sided(row, sides):
    return {**row, **sides}


def realm(extra_quests=(), extra_givers=()):
    """Felwood done; The New Horde in Durotar from Eitrigg; Timberling
    Sprouts in Teldrassil from Denalan; a leftover level 5 quest in Dun
    Morogh across the sea; and the extra quests given."""
    quests = [
        quest(787, DUROTAR, 1, title="The New Horde"),
        quest(919, TELDRASSIL, 7, title="Timberling Sprouts"),
        quest(400, DUN_MOROGH, 5, title="Tools for Steelgrip"),
    ] + list(extra_quests)
    givers = [
        sided(
            giver(787, "start", 3144, 3144, 1900, -4200, KALIMDOR, "Eitrigg"), EITRIGG
        ),
        sided(giver(787, "end", 3144, 3144, 1900, -4200, KALIMDOR, "Eitrigg"), EITRIGG),
        sided(giver(919, "start", 919, 2080, 9800, 900, KALIMDOR, "Denalan"), DENALAN),
        sided(giver(919, "end", 919, 2080, 9800, 900, KALIMDOR, "Denalan"), DENALAN),
        sided(
            giver(400, "start", 400, 1400, -5600, -500, EASTERN, "Steelgrip"), SENTINEL
        ),
        sided(
            giver(400, "end", 400, 1400, -5600, -500, EASTERN, "Steelgrip"), SENTINEL
        ),
    ] + list(extra_givers)
    starts = [
        {"quest": g["quest"], "kind": "creature", "entry": g["entry"]}
        for g in givers
        if g["role"] == "start"
    ]
    ends = [
        {"quest": g["quest"], "kind": "creature", "entry": g["entry"]}
        for g in givers
        if g["role"] == "end"
    ]
    return questers.catalogue(quests, givers, [], [], starts, ends)


def velo(**kw):
    base = dict(
        name="Velo",
        level=31,
        race=DRAENEI,
        class_id=SHAMAN,
        map_id=KALIMDOR,
        x=5000.0,
        y=-500.0,
        zone_id=FELWOOD,
        online=True,
    )
    base.update(kw)
    return questers.Member(**base)


class AGiverOfTheOtherSideGivesNothing(unittest.TestCase):
    def test_the_givers_side_is_read_off_its_faction_template(self):
        cat = realm()
        self.assertIn(3144, cat.hostile["alliance"])
        self.assertNotIn(3144, cat.hostile["horde"])
        self.assertIn(919, cat.hostile["horde"])
        self.assertNotIn(919, cat.hostile["alliance"])

    def test_a_giver_with_no_faction_read_is_no_side_s_enemy(self):
        rows = [giver(1, "start", 5, 5, 0, 0)]
        self.assertEqual(
            questers.hostile_givers(rows),
            {"alliance": frozenset(), "horde": frozenset()},
        )

    def test_the_new_horde_is_not_in_reach_for_an_alliance_quester(self):
        cat = realm()
        self.assertEqual(questers.in_reach(cat, velo(), DUROTAR), [])
        self.assertEqual(questers.in_reach(cat, velo(race=TAUREN), DUROTAR), [787])

    def test_an_alliance_quester_with_nothing_left_is_not_sent_to_durotar(self):
        cat = realm()
        p = questers.plan(cat, velo(), questers.Clock(), 0.0)
        self.assertNotEqual(questers.next_zone(cat, velo())[0], DUROTAR)
        moved = p.move is not None and p.move.quest == 787
        self.assertFalse(moved, p.line)
        self.assertNotIn("Durotar", p.move.said if p.move else p.line)
        self.assertNotIn("The New Horde", p.move.said if p.move else p.line)

    def test_a_horde_quester_is_not_sent_to_teldrassil(self):
        cat = realm()
        tahomi = velo(name="Tahomi", race=TAUREN, level=26, quests_done={787})
        self.assertNotEqual(questers.next_zone(cat, tahomi)[0], TELDRASSIL)


class AZoneOfItsLevelComesBeforeGreyLeftovers(unittest.TestCase):
    def cat(self):
        return realm(
            extra_quests=[quest(1018, ASHENVALE, 30, title="The New Frontier")],
            extra_givers=[
                sided(giver(1018, "start", 1018, 1018, 2700, -400, KALIMDOR), SENTINEL),
                sided(giver(1018, "end", 1018, 1018, 2700, -400, KALIMDOR), SENTINEL),
            ],
        )

    def test_a_level_31_quester_goes_to_its_band_not_to_a_level_5_quest(self):
        cat = self.cat()
        self.assertEqual(questers.next_zone(cat, velo()), (ASHENVALE, [1018]))
        p = questers.plan(cat, velo(), questers.Clock(), 0.0)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 1018))

    def test_with_only_grey_leftovers_it_still_goes_to_them(self):
        cat = realm()
        self.assertEqual(questers.next_zone(cat, velo())[0], DUN_MOROGH)


class NoAlternationWithARefusedCrossing(unittest.TestCase):
    """Velo's two moves on consecutive passes were the crossing for Dun
    Morogh and, while that crossing was held, The New Horde on its own
    continent. With the Horde quest gone there is no move on Kalimdor, so
    the held crossing waits on the crossing clock instead."""

    def plan(self, *rows):
        rows = [{**r, "target_name": "Velo"} for r in rows]
        crossings = guildjobs.recent_from_rows(rows)
        return questers.plan(
            realm(), velo(), questers.Clock(), 0.0, crossings=crossings
        )

    def test_the_held_crossing_does_not_fall_back_to_the_horde_quest(self):
        free = self.plan()
        self.assertEqual(
            (free.move.kind, free.move.to_map), (classquest.CROSS, EASTERN)
        )
        held = self.plan(
            crossing_row(
                "the character is in combat",
                True,
                age=2,
                to_map=EASTERN,
                source="guildjobs:quester-cross:Velo",
            )
        )
        self.assertFalse(held.move is not None and held.move.quest == 787, held.line)


if __name__ == "__main__":
    unittest.main()
