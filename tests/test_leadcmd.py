"""A family leader's movement is not toggled from the bridge (leadcmd.py).

Measured on the dev realm over the week to 2026-09-26: the Alliance leader
was queued `stay` 18 times, `follow` 21 times and `reset ai` 31 times by the
in-game ear, off lines his own family's bots said, and `nc +/-new rpg` every
ten minutes by the life rule. mod-overseer#722 refuses these for a leader;
this is the bridge not writing them at all. Same rules as the module's
LeaderCommandRefusal.
"""

import pathlib
import unittest

import goals
import leadcmd

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


class MovesTheLeader(unittest.TestCase):
    def test_the_measured_commands_move_him(self):
        for command in (
            "follow",
            "stay",
            "reset ai",
            "nc +new rpg",
            "nc -new rpg",
            "nc +follow",
            "nc +grind,+stay",
            "  Follow ",
        ):
            self.assertTrue(leadcmd.moves_the_leader(command), command)

    def test_survival_and_levelling_do_not(self):
        for command in (
            "co +flee",
            "nc +grind",
            "nc +loot",
            "nc +gather",
            "e Hitem:8271:0",
            "attack",
            "",
        ):
            self.assertFalse(leadcmd.moves_the_leader(command), command)

    def test_a_follower_keeps_everything(self):
        cmds = ["nc -new rpg", "nc +follow", "co +flee"]
        self.assertEqual(cmds, leadcmd.for_character(cmds, is_leader=False))

    def test_the_leader_keeps_flee_and_his_level_strategy(self):
        cmds = goals.life_strategies(leads=True, travelling=True)
        kept = leadcmd.for_character(cmds, is_leader=True)
        self.assertFalse(any(leadcmd.moves_the_leader(c) for c in kept))
        self.assertIn(goals.FLEE_STRATEGY, kept)
        town = leadcmd.for_character(
            goals.life_strategies(leads=True, in_town=True), True
        )
        self.assertEqual([goals.FLEE_STRATEGY], town)


class TheBridgeUsesIt(unittest.TestCase):
    def test_the_life_rule_filters_the_roster_lead(self):
        self.assertIn("leadcmd.for_character(", BRIDGE)
        self.assertIn("leads = _roster_leads()", BRIDGE)

    def test_overheard_orders_and_the_muster_skip_him(self):
        self.assertEqual(2, BRIDGE.count("leadcmd.moves_the_leader("))


if __name__ == "__main__":
    unittest.main()
