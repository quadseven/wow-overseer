"""A member left in the starting lands of map 530, past its zone, gets its
level step or a named reason in the same pass (#2400).

Such a member could be given no step pass after pass, and no line of the log
said why. The boat rung (guildjobs.isle_crossing_first) reads
level_step and returns nothing for every branch that issues no crossing, and
four of level_step's branches return `None, "", ""`: blocked (fighting, a
roster family member, the level cap), already at the flight master, the walk's
cooldown, and not outgrown.

The plan now carries `isle_lines`: one line per online member in the starting
lands that has outgrown where it stands and got no level step, with the branch
that issued nothing. The bridge logs them uncapped, when new or changed.
"""

import dataclasses
import pathlib
import unittest

import classic
import guildjobs
import guildlevel
from test_guildlevel_cross_allowance import WALKERS, islander
from test_guildlevel_isle_held import full_bags
from test_guildlevel_outleveled import (
    ALL_HUBS,
    BLOODMYST,
    QUESTS,
    crossing,
    level_steps,
    master_rows,
    member,
    plan,
    world,
)

HERE = pathlib.Path(__file__).resolve().parent.parent


def line_of(result, name):
    """The one isle line naming `name`, or "" when it has none."""
    lines = [n for n in result.isle_lines if n.startswith(name + " ")]
    assert len(lines) <= 1, lines
    return lines[0] if lines else ""


def in_the_exodar(name="Dakk", level=14, **over):
    """A Draenei in the Exodar, which has no quest band, whose level hub
    (Blood Watch) stands on map 530: its level step is a walk, not the boat."""
    return member(name, level=level, zone_id=classic.THE_EXODAR, **over)


def blood_watch_master():
    """Where the fixture world puts the Blood Watch flight master."""
    hub = next(h for h in ALL_HUBS if h.zone_id == BLOODMYST)
    return hub.point[1] + 5.0, hub.point[2]


def level_walk(name, age):
    return guildjobs.Recent(name, guildlevel.ACTION, age, "ok")


class TheStepNamesItself(unittest.TestCase):
    def test_a_member_that_takes_the_boat_has_no_line(self):
        result = plan([islander("Brakk", 28)])
        self.assertEqual(
            [s.rows[0].command for s in level_steps(result)], ["cross-to-map map:1"]
        )
        self.assertEqual(result.isle_lines, ())

    def test_a_member_walked_to_a_hub_on_the_isle_has_no_line(self):
        result = plan([in_the_exodar()])
        self.assertEqual([s.holder for s in level_steps(result)], ["Dakk"])
        self.assertEqual(result.isle_lines, ())


class EveryQuietBranchIsNamed(unittest.TestCase):
    """One test per branch that left such a member with no step and no word."""

    def assert_named(self, result, name, reason):
        self.assertEqual([s for s in level_steps(result) if s.holder == name], [])
        line = line_of(result, name)
        self.assertTrue(line, result.isle_lines)
        self.assertIn("gets no level step off map 530", line)
        self.assertIn(reason, line)

    def test_a_member_that_is_fighting(self):
        fighter = dataclasses.replace(islander("Brakk", 28), in_combat=True)
        self.assertEqual(
            guildjobs.level_step(fighter, world(), (), None), (None, "", "")
        )
        self.assert_named(plan([fighter]), "Brakk", "it is fighting")

    def test_a_roster_family_member(self):
        leveling = guildlevel.world(QUESTS, master_rows(), roster=("Brakk",))
        brakk = islander("Brakk", 28)
        self.assertEqual(
            guildjobs.level_step(brakk, leveling, (), None), (None, "", "")
        )
        self.assert_named(
            plan([brakk], leveling=leveling), "Brakk", "roster family member"
        )

    def test_a_member_already_at_the_flight_master_of_its_hub(self):
        x, y = blood_watch_master()
        dakk = in_the_exodar(x=x, y=y)
        self.assertEqual(guildjobs.level_step(dakk, world(), (), None), (None, "", ""))
        self.assert_named(
            plan([dakk]), "Dakk", "it already stands at the flight master at"
        )

    def test_a_member_whose_level_walk_is_cooling_down(self):
        recent = (level_walk("Dakk", 5),)
        dakk = in_the_exodar()
        self.assertEqual(
            guildjobs.level_step(dakk, world(), recent, None), (None, "", "")
        )
        self.assert_named(plan([dakk], recent=recent), "Dakk", "is still cooling down")

    def test_a_crossing_refused_on_the_guilds_allowance(self):
        isle = [islander(n, 28) for n in ("Brakk", "Dakk", "Eggrok")]
        result = plan(isle)
        crossed = {s.holder for s in level_steps(result)}
        self.assertEqual(len(crossed), guildjobs.CROSS_STEPS_PER_GUILD)
        third = ({"Brakk", "Dakk", "Eggrok"} - crossed).pop()
        self.assert_named(result, third, "the step was refused: %s waits" % third)

    def test_a_crossing_behind_another_step_when_the_allowance_is_used(self):
        isle = [full_bags(islander(n, 28)) for n in ("Brakk", "Dakk", "Eggrok")]
        result = plan(isle)
        crossed = {s.holder for s in level_steps(result)}
        third = ({"Brakk", "Dakk", "Eggrok"} - crossed).pop()
        self.assertEqual(
            [s.action for s in result.steps if s.holder == third], ["sell"]
        )
        self.assert_named(result, third, "another step came first this pass")

    def test_a_crossing_still_in_flight(self):
        recent = (crossing("Brakk", 1, status="pending"),)
        result = plan([islander("Brakk", 28)], recent=recent)
        self.assert_named(result, "Brakk", "it is held on the way it has started")
        # The held crossing's line says why the zone is outgrown, once.
        self.assertEqual(line_of(result, "Brakk").count("no quest band"), 1)

    def test_a_dead_member(self):
        ghost = dataclasses.replace(islander("Brakk", 28), alive=False)
        self.assert_named(plan([ghost]), "Brakk", "Brakk is dead")

    def test_a_seat_outside_the_lineup(self):
        seat = dataclasses.replace(islander("Brakk", 28), role=guildjobs.UNASSIGNED)
        self.assert_named(plan([seat]), "Brakk", "it holds no seat in the lineup")

    def test_every_line_names_the_member_its_level_and_why_it_has_outgrown(self):
        fighter = dataclasses.replace(islander("Brakk", 28), in_combat=True)
        line = line_of(plan([fighter]), "Brakk")
        self.assertTrue(line.startswith("Brakk at level 28 gets no level step"), line)
        self.assertIn("where its side has no quest band in", line)


class OnlyAMemberThatWaitsOnItsWayOutIsListed(unittest.TestCase):
    def test_an_offline_member_is_not_listed(self):
        away = dataclasses.replace(islander("Brakk", 28), online=False)
        self.assertEqual(plan([away]).isle_lines, ())

    def test_a_member_still_inside_its_zones_band_is_not_listed(self):
        young = dataclasses.replace(member("Bonk", level=15), in_combat=True)
        self.assertEqual(plan([young]).isle_lines, ())

    def test_a_member_on_a_continent_is_not_listed(self):
        fighters = [dataclasses.replace(w, in_combat=True) for w in WALKERS]
        self.assertEqual(plan(fighters).isle_lines, ())

    def test_nothing_is_listed_while_the_level_world_is_unread(self):
        self.assertEqual(plan([islander("Brakk", 28)], leveling=None).isle_lines, ())


class TheBridgeLogsEveryIsleLine(unittest.TestCase):
    def test_the_pass_logs_them_uncapped_when_new_or_changed(self):
        src = (HERE / "bridge.py").read_text(encoding="utf-8")
        at = src.index('_log_changed("guild jobs", plan.isle_lines,')
        call = src[at : src.index(")\n", at)]
        self.assertIn("capped=False", call)
        # Per cohort: one family's pass does not count another's lines gone.
        self.assertIn("_cohort_key(cohort)", call)


if __name__ == "__main__":
    unittest.main()
