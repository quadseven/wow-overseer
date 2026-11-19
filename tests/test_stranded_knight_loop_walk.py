"""A hearthstone-less death knight on the start map keeps a way out.

Its recall is refused for the missing stone and the death loop's hearth and
level walk do not run on map 609, so the class walk (the module's gryphon
click) is its way out; it must be asked again soon, not once in three hours.
"""

import unittest
from types import SimpleNamespace

import classquest
import classtrain
import guildjobs
import guildroute
from test_death_loop_hearth_retry import loop_of, looper


def row(name, age, source=None):
    return {
        "target_name": name,
        "source": source or "%s:%s" % (classtrain.SOURCE, name),
        "age": age,
        "result": "",
    }


def knight_trainee(name="Knight"):
    return classtrain.Trainee(
        name,
        "Guild",
        60,
        0,
        classtrain.Due(),
        True,
        class_id=classquest.DEATH_KNIGHT,
    )


class KnightClassWalkCooldown(unittest.TestCase):
    def test_knight_is_free_to_walk_after_the_short_cooldown(self):
        age = classtrain.KNIGHT_COOLDOWN_MINUTES + 1
        held = classtrain.recent_walkers([row("Knight", age)], knights=["Knight"])
        self.assertEqual(held, set())

    def test_knight_is_held_inside_the_short_cooldown(self):
        age = classtrain.KNIGHT_COOLDOWN_MINUTES - 1
        held = classtrain.recent_walkers([row("Knight", age)], knights=["Knight"])
        self.assertEqual(held, {"Knight"})

    def test_other_members_keep_the_long_cooldown(self):
        age = classtrain.KNIGHT_COOLDOWN_MINUTES + 1
        held = classtrain.recent_walkers([row("Mage", age)], knights=["Knight"])
        self.assertEqual(held, {"Mage"})

    def test_stranded_knight_is_walked_again_after_the_short_cooldown(self):
        walker = guildroute.Walker(
            name="Knight", map_id=609, by_row=True, aim="at:0:1,2,3"
        )
        age = classtrain.KNIGHT_COOLDOWN_MINUTES + 1
        held = classtrain.recent_walkers([row("Knight", age)], knights=["Knight"])
        walks, _ = classtrain.plan([knight_trainee()], {"Knight": walker}, held, set())
        self.assertEqual([w.name for w in walks], ["Knight"])
        self.assertTrue(walks[0].gryphon)


class DeathLoopNamesTheClassWalk(unittest.TestCase):
    def test_reason_names_the_gryphon_walk_for_a_knight_on_the_start_map(self):
        m = SimpleNamespace(
            **{
                **vars(looper()),
                "class_id": classquest.DEATH_KNIGHT,
                "map_id": classquest.DEATH_KNIGHT_START_MAP,
            }
        )
        word = guildjobs._death_loop_reason(
            m, loop_of(), None, guildjobs.recent_from_rows([])
        )
        self.assertIn("gryphon", word)

    def test_reason_is_unchanged_for_another_class(self):
        m = SimpleNamespace(
            **{
                **vars(looper()),
                "class_id": 8,
                "map_id": classquest.DEATH_KNIGHT_START_MAP,
            }
        )
        word = guildjobs._death_loop_reason(
            m, loop_of(), None, guildjobs.recent_from_rows([])
        )
        self.assertEqual(word, "not in the open world")


if __name__ == "__main__":
    unittest.main()
