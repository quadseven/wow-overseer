"""A guild run formed by the guild social pass names its seats' upgrades (#760).

Live guild runs form in `_guild_social_once` (GUILD_SOCIAL is on), never in
`_guild_run_once`, so the seated raiders' pre-raid gains were read and named
only on a path the realm never runs: the dev realm logged no "drops upgrades
for" line from 2026-11-03 to 2026-11-07.
"""

import unittest
from unittest import mock

import guildrun
import preraid
import test_guildsocial_bridge as social_bridge
from test_guildsocial_bridge import bridge


class _AnyDoor(dict):
    """Gains that answer the same seats for whichever door the run forms at."""

    def __init__(self, seats):
        super().__init__(any=seats)
        self.seats = seats

    def get(self, _keyword, default=None):
        return self.seats


def gain(name, levels, best):
    return preraid.Gain(name=name, upgrades=1, drops=0.2, levels=levels, best=best)


class TheSocialPassNamesTheSeatsUpgrades(unittest.TestCase):
    def run_pass(self, gains):
        asked = []

        def seat_gains(names, levels):
            asked.append((tuple(names), tuple(levels)))
            return gains

        this = social_bridge._Self()
        with (
            mock.patch.object(guildrun, "UPGRADE_FLOOR", 0),
            mock.patch.object(bridge.log, "info") as info,
        ):
            written = social_bridge.TheBridgePass.run_once(
                social_bridge.TheBridgePass(), this, _guild_seat_gains=seat_gains
            )
        said = [c.args[0] % c.args[1:] for c in info.call_args_list if c.args]
        return written, asked, said

    def test_the_formed_seats_are_read_and_their_upgrades_logged(self):
        gains = _AnyDoor(
            (
                gain("Tanky", 4.5, "Helm of Might for head (+9 item levels, 20%)"),
                gain("Idle", 9.0, "Not Seated for legs (+9 item levels, 20%)"),
            )
        )
        written, asked, said = self.run_pass(gains)
        form = written[0].form
        self.assertEqual([tuple(form.composition.names)], [a[0] for a in asked])
        line = [s for s in said if "drops upgrades for" in s]
        self.assertEqual(1, len(line), said)
        self.assertIn("upgrades for Tanky (Helm of Might for head)", line[0])
        self.assertNotIn("Idle", line[0])
        self.assertIn(form.door.place, line[0])

    def test_no_gains_no_line(self):
        _written, _asked, said = self.run_pass({})
        self.assertFalse([s for s in said if "drops upgrades for" in s], said)


class TheWordsAreTheGuildRunsOwn(unittest.TestCase):
    def test_gain_words_is_what_upgrade_words_says(self):
        from test_guildrun import seated_plan

        gains = {
            "beta": (
                gain("Tanky", 4.5, "Helm of Might for head (+9 item levels, 20%)"),
            )
        }
        plan, comp = seated_plan(55, gains)
        door = plan.doors[1]
        self.assertEqual(
            guildrun.upgrade_words(plan, door, comp),
            guildrun.gain_words(gains, door, comp),
        )
        self.assertEqual("", guildrun.gain_words(gains, plan.doors[0], comp))


if __name__ == "__main__":
    unittest.main()
