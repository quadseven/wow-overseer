"""A crossing the module cannot route is a wall (#678).

On the dev realm three Night Elf members were refused `cross-to-map map:0` 27 to
30 times a day each (every 35 to 45 minutes), because the module's refusal text
in the result is a per-ship diagnostic list, not the literal CROSS_WALLS holds,
so no wall ever stood. Two death knights on map 609 were asked the same way.
"""

import unittest

import classquest

SHIPS = (
    "'Ship, Night Elf (Moonspray)' no berth at boarding stop 1 on map 1; "
    "'Zeppelin (The Thundercaller)' boarding and landing both select stop 1 on map 1"
)


class TheWall(unittest.TestCase):
    def test_a_ship_by_ship_refusal_is_a_wall(self):
        self.assertTrue(classquest.is_cross_wall(SHIPS))

    def test_a_path_names_both_maps_refusal_is_a_wall(self):
        self.assertTrue(classquest.is_cross_wall("no transport's path names both maps"))

    def test_a_routeless_faction_refusal_is_a_wall(self):
        self.assertTrue(
            classquest.is_cross_wall(
                "no transport its faction may ride joins map 1 and map 0"
            )
        )

    def test_a_busy_refusal_is_not_a_wall(self):
        self.assertFalse(classquest.is_cross_wall("the character is in combat"))
        self.assertFalse(classquest.is_cross_wall(""))


if __name__ == "__main__":
    unittest.main()
