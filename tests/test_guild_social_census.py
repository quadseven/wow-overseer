"""The guild social pass says, per guild, how many members are free to answer
an ask and why the rest are held (2026-10-05: asks drew no tank or healer for
hours and nothing said why)."""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import guildsocial  # noqa: E402


def _mate(name, guild):
    return types.SimpleNamespace(name=name, member=types.SimpleNamespace(guild=guild))


class TheCensus(unittest.TestCase):
    def test_free_and_held_by_reason_per_guild(self):
        mates = [
            _mate("A", "Cave"),
            _mate("B", "Cave"),
            _mate("C", "Cave"),
            _mate("D", "Bonkers"),
        ]
        held = {"A": "on a guild job", "B": "on a guild job", "D": "resting"}
        line = guildsocial.census(mates, held)
        self.assertIn("Cave 3 read, 1 free; held: on a guild job 2", line)
        self.assertIn("Bonkers 1 read, 0 free; held: resting 1", line)

    def test_nobody_held(self):
        self.assertEqual(
            guildsocial.census([_mate("A", "Cave")], {}), "Cave 1 read, 1 free"
        )


if __name__ == "__main__":
    unittest.main()
