"""A level crossing off the Draenei isle is not starved by the guild's level
walks.

Measured on the dev realm on 2026-11-08: four of Cave's Draenei at 27 to 32
(Brakk, Dakk, Drogg, Eggrok) stood on Azuremyst Isle and in the Exodar with no
crossing row since 2026-10-15. Their level step was planned every pass ("takes
the boat off map 530 to level ... Astranaar in Ashenvale") and then refused by
the guild's allowance: "Brakk waits: 2 guild job steps per guild per pass". The
two level steps a guild may start each pass (guildlevel.STEPS_PER_GUILD) went
to the guild's higher members' walks on the continents, planned first, which
were due again by the time their two hour cooldown ran out: 128 of Cave's
level walks in that day, none of them a crossing.

That allowance is there for the realm's far walks. A `cross-to-map` or
`ride-to-stop` row is no far walk of the pass's: the module paces crossings
with its own cap (Overseer.Cross.AtOnce, asked again on its retry flag) and the
bridge with the shared crossing clock. So a level crossing counts against
guildjobs.CROSS_STEPS_PER_GUILD, not against the level walks.
"""

import unittest

import classquest
import guildjobs
import guildlevel
from test_guildlevel_outleveled import (
    AZUREMYST,
    EASTERN_KINGDOMS,
    HUMAN,
    WESTFALL,
    level_steps,
    member,
    plan,
)


def walker(name):
    """A Cave member past Westfall, planned ahead of the Draenei by name."""
    return member(
        name,
        race=HUMAN,
        level=30,
        map_id=EASTERN_KINGDOMS,
        x=-10500.0,
        y=1000.0,
        zone_id=WESTFALL,
    )


def islander(name="Brakk", level=28):
    return member(name, level=level, x=-3961.0, y=-13931.0, zone_id=AZUREMYST)


WALKERS = [walker("Agg"), walker("Akk"), walker("Arr")]


def crosses(step) -> bool:
    return classquest.is_cross_row(step.rows[0].command)


class TheIsleCrossingHasItsOwnAllowance(unittest.TestCase):
    def test_the_walkers_use_the_level_walk_allowance(self):
        steps = level_steps(plan(WALKERS))
        self.assertEqual(len(steps), guildlevel.STEPS_PER_GUILD)
        self.assertFalse(any(crosses(s) for s in steps))

    def test_a_draenei_on_the_isle_crosses_while_the_walks_are_used_up(self):
        result = plan([*WALKERS, islander()])
        crossing = [s for s in level_steps(result) if s.holder == "Brakk"]
        self.assertEqual([s.rows[0].command for s in crossing], ["cross-to-map map:1"])
        self.assertFalse(any("Brakk waits" in n for n in result.notes))
        walks = [s for s in level_steps(result) if not crosses(s)]
        self.assertEqual(len(walks), guildlevel.STEPS_PER_GUILD)

    def test_crossings_keep_a_cap_of_their_own(self):
        isle = [
            islander(name, level)
            for name, level in (
                ("Brakk", 28),
                ("Dakk", 27),
                ("Drogg", 30),
                ("Eggrok", 29),
            )
        ]
        result = plan([*WALKERS, *isle])
        crossings = [s for s in level_steps(result) if crosses(s)]
        self.assertEqual(len(crossings), guildjobs.CROSS_STEPS_PER_GUILD)
        # The rest wait for the next pass, named.
        crossed = {s.holder for s in crossings}
        for name in {"Brakk", "Dakk", "Drogg", "Eggrok"} - crossed:
            self.assertTrue(any(n.startswith(name + " waits") for n in result.notes))


if __name__ == "__main__":
    unittest.main()
