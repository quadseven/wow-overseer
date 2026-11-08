"""An outgrown Draenei bot on the isle takes the boat before the errands that
held it there (#2047).

Three steps planned ahead of the level step kept an outgrown islander from
its crossing, even once the crossing had an allowance of its own (#2039):

  * A full-bagged member's sale walk came first every pass and was refused on
    the guild job allowance. A grouped follower's vendor walk is also held by
    the bridge (followhold.py), while its crossing row is not.
  * A class step refused on the class quest allowance left the member with no
    step at all.
  * A class step that keeps failing yields to the level step
    (stalled_level_first), but only while the guild had a level WALK left, and
    the guild's higher members' walks used both every pass.
"""

import dataclasses
import unittest
from unittest import mock

import classquest
import followhold
import guildcorps
import guildjobs
import guildlevel
from test_guildlevel_cross_allowance import WALKERS, islander
from test_guildlevel_outleveled import level_steps, plan

JUNK = 0


def junk(guid):
    return guildjobs.Carried(
        guid=guid, entry=3000 + guid, quality=JUNK, sell_price=25, name="grey"
    )


def full_bags(member):
    """`member` with every bag slot taken, grey items among them."""
    return dataclasses.replace(
        member,
        free_slots=0,
        bag_slots=16,
        carried=tuple(junk(g) for g in range(1, 7)),
    )


def class_step_for(name):
    """A class step (a gameobject use) planned first for `name`."""

    def step(m, *_args, **_kw):
        if m.name != name:
            return None, "", ""
        said = "%s uses an effigy for its class quest" % m.name
        return (
            guildcorps.Step(
                m.name,
                classquest.ACTION,
                9467,
                said,
                rows=(
                    guildcorps.Row(
                        "quest",
                        "use-gameobject 181672",
                        "",
                        guildjobs.source_for(classquest.ACTION, m.name),
                    ),
                ),
            ),
            said,
            "",
        )

    return step


def commands_of(result, name):
    return [s.rows[0].command for s in result.steps if s.holder == name]


class TheBoatComesBeforeTheSale(unittest.TestCase):
    def test_a_full_bagged_islander_crosses_before_it_sells(self):
        result = plan([full_bags(islander("Brakk", 28))])
        self.assertEqual(commands_of(result, "Brakk"), ["cross-to-map map:1"])

    def test_a_sale_waiting_on_the_job_allowance_does_not_hold_the_crossing(self):
        result = plan([full_bags(islander("Eggrok", 29))], per_guild=0)
        self.assertEqual(commands_of(result, "Eggrok"), ["cross-to-map map:1"])

    def test_a_member_on_a_continent_still_sells_first(self):
        walker = full_bags(WALKERS[0])
        result = plan([walker])
        steps = [s for s in result.steps if s.holder == walker.name]
        self.assertEqual([s.action for s in steps], ["sell"])

    def test_a_used_up_crossing_allowance_leaves_the_sale(self):
        isle = [full_bags(islander(n, 28)) for n in ("Brakk", "Dakk", "Eggrok")]
        result = plan(isle)
        crossings = [s for s in level_steps(result) if s.rows]
        self.assertEqual(len(crossings), guildjobs.CROSS_STEPS_PER_GUILD)
        third = ({"Brakk", "Dakk", "Eggrok"} - {s.holder for s in crossings}).pop()
        self.assertEqual(
            [s.action for s in result.steps if s.holder == third], ["sell"]
        )

    def test_a_follower_s_crossing_is_not_held_as_a_follower_walk(self):
        """A grouped follower's crossing row is no walk the follower gate
        stands in front of, so the boat goes where the sale walk was held."""
        command = classquest.cross_command(1)
        self.assertFalse(followhold.is_walk(command))
        group = followhold.Group(guid=1184, leader_guid=2844, leader="Leader")
        self.assertEqual(followhold.Holds().held("Eggrok", command, group, 0.0), "")


class TheClassStepDoesNotHoldTheBoat(unittest.TestCase):
    def test_a_class_step_refused_on_its_allowance_takes_the_crossing(self):
        with (
            mock.patch.object(guildjobs, "class_step", class_step_for("Dakk")),
            mock.patch.object(guildjobs, "CLASSQUEST_STEPS_PER_GUILD", 0),
        ):
            result = plan([islander("Dakk", 27)])
        self.assertEqual(commands_of(result, "Dakk"), ["cross-to-map map:1"])
        self.assertTrue(any(n.startswith("Dakk waits") for n in result.notes))

    def test_a_class_step_with_its_allowance_still_goes_first(self):
        with mock.patch.object(guildjobs, "class_step", class_step_for("Dakk")):
            result = plan([islander("Dakk", 27)])
        self.assertEqual(commands_of(result, "Dakk"), ["use-gameobject 181672"])

    def test_a_failing_class_step_yields_to_the_crossing_while_walks_are_used(self):
        with (
            mock.patch.object(guildjobs, "class_step", class_step_for("Brakk")),
            mock.patch.object(
                guildjobs,
                "class_stall_hold",
                lambda name, recent: (30, 3) if name == "Brakk" else (0, 0),
            ),
        ):
            result = plan([*WALKERS, islander("Brakk", 28)])
        self.assertEqual(commands_of(result, "Brakk"), ["cross-to-map map:1"])
        walks = [s for s in level_steps(result) if s.holder != "Brakk"]
        self.assertEqual(len(walks), guildlevel.STEPS_PER_GUILD)


if __name__ == "__main__":
    unittest.main()
