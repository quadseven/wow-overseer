"""Test Quest 106 "Young Lovers" eligibility for Durga and Pindle."""

import unittest
import questers
from tests.test_questers import ended, giver, started

ELWYNN = 12
ALLIANCE = 1101
DWARF, GNOME = 3, 7
WARRIOR = 1


def quest_row(qid, title, sort, level, min_level, races=0, **extra):
    """A QUESTS_SQL row."""
    out = {
        "id": qid,
        "title": title,
        "sort": sort,
        "zone": sort,
        "level": level,
        "info": 0,
        "min_level": min_level,
        "races": races,
        "classes": 0,
        "prev_signed": extra.pop("prev", 0),
        "prev": 0,
        "exclusive": extra.pop("exclusive", 0),
        "reward": 0,
        "display": 0,
        "grp": 0,
        "npc1": extra.pop("kill", 0),
        "npc_count1": extra.pop("count", 1),
    }
    out.update(extra)
    out["prev"] = out["prev_signed"]
    return out


def build_catalogue(rows, links=(), drop=()):
    """The quester catalogue of these rows."""
    givers, starts, ends = [], [], []
    for n, r in enumerate(rows):
        guid, entry = 5000 + n, 900 + n
        for role in ("start", "end"):
            givers.append(giver(r["id"], role, guid, entry, 10.0 * n, 0.0, map_id=0))
    # Build starts/ends from ALL givers (named givers, spawned or not)
    named = {g["quest"]: g["entry"] for g in givers if g["role"] == "start"}
    starts = [started(q, e) for q, e in sorted(named.items())]
    enders = {g["quest"]: g["entry"] for g in givers if g["role"] == "end"}
    ends = [ended(q, e) for q, e in sorted(enders.items())]
    # Drop spawns to simulate giver missing from world data
    givers = [g for g in givers if g["guid"] not in drop]
    return questers.catalogue(rows, givers, [], [], starts, ends, links)


def make_member(name, race, level, zone, **kw):
    return questers.Member(
        name=name,
        level=level,
        race=race,
        class_id=WARRIOR,
        map_id=0,
        x=0.0,
        y=0.0,
        zone_id=zone,
        online=True,
        **kw,
    )


class TestQuest106YoungLovers(unittest.TestCase):
    """Quest 106 "Young Lovers" in Elwynn Forest."""

    def test_quest_106_exists_in_catalogue(self):
        """Quest 106 should be loadable and in the catalogue."""
        cat = build_catalogue([
            quest_row(106, "Young Lovers", ELWYNN, 6, 4, ALLIANCE),
        ])
        self.assertIn(106, cat.book.quests)
        self.assertEqual(cat.book.quests[106].title, "Young Lovers")

    def test_durga_level_3_cannot_take_quest_106_min_level_4(self):
        """Durga (level 3 Dwarf) cannot take quest 106 (min level 4)."""
        cat = build_catalogue([
            quest_row(106, "Young Lovers", ELWYNN, 6, 4, ALLIANCE),
        ])
        durga = make_member("Durga", DWARF, 3, ELWYNN)
        self.assertNotIn(106, questers.in_reach(cat, durga, ELWYNN))

    def test_pindle_level_8_can_take_quest_106(self):
        """Pindle (level 8 Gnome) can take quest 106."""
        cat = build_catalogue([
            quest_row(106, "Young Lovers", ELWYNN, 6, 4, ALLIANCE),
        ])
        pindle = make_member("Pindle", GNOME, 8, ELWYNN)
        self.assertIn(106, questers.in_reach(cat, pindle, ELWYNN))

    def test_quest_106_giver_missing_from_world_data(self):
        """Quest 106's giver (Maybell Maclure) has no spawn in world data - GIVER_MISSING.
        
        Need another quest in Elwynn with a giver to keep zone 12 in classic_zones.
        """
        cat = build_catalogue([
            quest_row(106, "Young Lovers", ELWYNN, 6, 4, ALLIANCE),
            quest_row(999, "Anchor Quest", ELWYNN, 5, 1, ALLIANCE),
        ], drop={5000})
        pindle = make_member("Pindle", GNOME, 8, ELWYNN)
        p = questers.plan(cat, pindle, questers.Clock(), 0.0)
        self.assertIn(
            (106, questers.GIVER_MISSING, False),
            [(b.quest, b.reason, b.held) for b in p.broken],
        )
        self.assertNotEqual(p.move.quest, 106)


if __name__ == "__main__":
    unittest.main()