"""The profession errand covers the guild maintenance characters too, and waits
where a trade must be given up first.

Pure unit tests against guildjobs.plan with the mix of guildtrades.
"""

import os
import unittest

import guildjobs
import raidteams

BONKERS = "Bonkers"
FOCUS = {BONKERS: guildjobs.DUNGEON_FOCUS}
H, M, S = guildjobs.HERBALISM, guildjobs.MINING, guildjobs.SKINNING


def setUpModule():
    old = os.environ.get("SEATS_LEVEL_FIRST")
    os.environ["SEATS_LEVEL_FIRST"] = "off"

    def restore():
        if old is None:
            os.environ.pop("SEATS_LEVEL_FIRST", None)
        else:
            os.environ["SEATS_LEVEL_FIRST"] = old

    unittest.addModuleCleanup(restore)


def member(name, role, **over):
    base = dict(
        name=name,
        guild=BONKERS,
        role=role,
        level=60,
        class_id=1,
        race=2,
        online=True,
        map_id=1,
        zone_id=17,
        x=0.0,
        y=0.0,
        money=5000,
        eligible=True,
        skills={},
        skills_read=True,
    )
    base.update(over)
    return guildjobs.Member(**base)


def errands(result, name=None):
    return [
        s
        for s in result.steps
        if guildjobs.is_profession_errand(s) and (name is None or s.holder == name)
    ]


MAINT = [new for _old, new in raidteams.MAINTENANCE[BONKERS]]
SEATS = [s.name for s in raidteams.seats(BONKERS)][5:]


class AMaintenanceCharacterIsPlanned(unittest.TestCase):
    def test_it_is_sent_to_a_trainer_for_a_craft(self):
        m = member(MAINT[0], guildjobs.MAINTENANCE)
        result = guildjobs.plan([m], focus=FOCUS)
        self.assertIn(m.name, result.assigned)
        self.assertEqual(1, len(errands(result, m.name)), result.notes)

    def test_the_line_names_maintenance_apart_from_the_seats(self):
        members = [
            member(MAINT[0], guildjobs.MAINTENANCE),
            member(SEATS[0], guildjobs.RAIDER),
        ]
        result = guildjobs.plan(members, focus=FOCUS)
        lines = guildjobs.profession_lines(members, result)
        self.assertEqual(2, len(lines), lines)
        self.assertTrue(any("1 maintenance" in x for x in lines), lines)
        self.assertTrue(any("1 raid seat(s)" in x for x in lines), lines)

    def test_a_summoner_is_never_planned(self):
        name = raidteams.SUMMONERS[BONKERS][0][1]
        m = member(name, guildjobs.SUMMONER)
        result = guildjobs.plan([m], focus=FOCUS)
        self.assertNotIn(name, result.assigned)
        self.assertEqual([], errands(result))

    def test_a_quester_is_never_planned(self):
        name = raidteams.QUESTERS[BONKERS][0].name
        m = member(name, guildjobs.MAINTENANCE)
        result = guildjobs.plan([m], focus=FOCUS)
        self.assertNotIn(name, result.assigned)
        self.assertEqual([], errands(result))


class ACharacterThatMustGiveUpATradeWaits(unittest.TestCase):
    def crowded(self, name, role):
        # Two gathering trades that fit no pair: both slots are full.
        return member(name, role, skills={S: (30, 75), M: (30, 75)}, level=60)

    def test_it_is_not_sent_to_learn_a_third_trade(self):
        for name, role in (
            (SEATS[1], guildjobs.RAIDER),
            (MAINT[1], guildjobs.MAINTENANCE),
        ):
            with self.subTest(name=name):
                result = guildjobs.plan([self.crowded(name, role)], focus=FOCUS)
                self.assertEqual([], errands(result))

    def test_its_planned_trades_do_not_start_with_the_pair_it_would_drop_for(self):
        m = self.crowded(SEATS[2], guildjobs.RAIDER)
        result = guildjobs.plan([m], focus=FOCUS)
        want = set(result.assigned[m.name])
        self.assertFalse({S, M} <= want)
        self.assertNotEqual(want, set(result.trades.get(m.name, ())[:2]))


if __name__ == "__main__":
    unittest.main()
