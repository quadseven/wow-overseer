"""teamsync: the rows that bring an approved guild to its approved teams."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import raidteams  # noqa: E402
import teamsync  # noqa: E402


def _bonkers_now():
    """Bonkers as the guild holds it today: current names, no recruits."""
    out = []
    for s in raidteams.seats("Bonkers"):
        if s.was or s.name in ("Zug", "Uzza", "Zrog", "Zork", "Oz"):
            out.append(
                {
                    "name": s.was or s.name,
                    "class_id": s.class_id,
                    "race": teamsync.RACE_IDS[s.race],
                    "level": 20,
                }
            )
    for old, _new in raidteams.SUMMONERS["Bonkers"] + raidteams.MAINTENANCE["Bonkers"]:
        out.append({"name": old, "class_id": 9, "race": 5, "level": 20})
    for name in raidteams.LEAVING["Bonkers"]:
        out.append({"name": name, "class_id": 4, "race": 5, "level": 16})
    return out


ORC_SHAMAN = {"name": "Randomorc", "class_id": 7, "race": 2, "level": 3}
TROLL_SHAMAN = {"name": "Randomtroll", "class_id": 7, "race": 8, "level": 2}
HIGH_ORC_SHAMAN = {"name": "Oldorc", "class_id": 7, "race": 2, "level": 55}


class Order(unittest.TestCase):
    def test_leavers_go_first_a_few_at_a_time(self):
        acts = teamsync.plan("Bonkers", _bonkers_now(), [], set(), False)
        removes = [a for a in acts if a.kind == "remove"]
        self.assertEqual(len(removes), teamsync.REMOVES_PER_PASS)
        self.assertTrue(all(a.target in raidteams.LEAVING["Bonkers"] for a in removes))

    def test_no_invite_while_the_guild_is_full(self):
        acts = teamsync.plan("Bonkers", _bonkers_now(), [ORC_SHAMAN], set(), False)
        # 71 members, 2 leaving this pass: room for 0 until they are gone.
        self.assertEqual([a for a in acts if a.kind == "invite"], [])

    def test_with_room_a_recruit_of_the_seat_class_and_race_is_invited(self):
        members = [
            m for m in _bonkers_now() if m["name"] not in raidteams.LEAVING["Bonkers"]
        ]
        acts = teamsync.plan(
            "Bonkers",
            members,
            [HIGH_ORC_SHAMAN, ORC_SHAMAN, TROLL_SHAMAN],
            set(),
            False,
        )
        invites = [a.target for a in acts if a.kind == "invite"]
        self.assertIn("Randomorc", invites)
        self.assertNotIn("Oldorc", invites)

    def test_a_row_in_flight_is_not_asked_twice(self):
        leaving = set(raidteams.LEAVING["Bonkers"])
        acts = teamsync.plan("Bonkers", _bonkers_now(), [], leaving, False)
        self.assertEqual([a for a in acts if a.kind == "remove"], [])


class Renames(unittest.TestCase):
    def test_no_rename_until_the_verb_is_live(self):
        acts = teamsync.plan("Bonkers", _bonkers_now(), [], set(), False)
        self.assertEqual([a for a in acts if a.kind == "rename"], [])

    def test_approved_names_are_asked_for_a_few_at_a_time(self):
        acts = teamsync.plan("Bonkers", _bonkers_now(), [], set(), True)
        renames = [a for a in acts if a.kind == "rename"]
        self.assertEqual(len(renames), teamsync.RENAMES_PER_PASS)
        self.assertTrue(
            all((a.target, a.new_name) in raidteams.renames("Bonkers") for a in renames)
        )

    def test_a_recruit_takes_its_seat_name(self):
        members = [
            m for m in _bonkers_now() if m["name"] not in raidteams.LEAVING["Bonkers"]
        ]
        members.append(dict(ORC_SHAMAN))
        seated = teamsync.recruits_in_guild("Bonkers", members)
        orc_shaman_seats = [
            s.name
            for s in raidteams.seats("Bonkers")
            if s.class_id == 7 and s.race == "Orc" and not s.was and s.name != "Zrog"
        ]
        self.assertEqual(seated[orc_shaman_seats[0]]["name"], "Randomorc")
        acts = teamsync.plan("Bonkers", members, [], set(), True)
        renamed = {a.target: a.new_name for a in acts if a.kind == "rename"}
        # Renames go in raidteams order; the recruit's is among the wanted ones.
        wanted = [(o, n) for o, n in raidteams.renames("Bonkers")] + [
            ("Randomorc", orc_shaman_seats[0])
        ]
        self.assertTrue(set(renamed.items()) <= set(wanted))

    def test_a_name_already_taken_in_the_guild_is_not_asked_for(self):
        members = _bonkers_now()
        old, new = raidteams.renames("Bonkers")[0]
        members.append({"name": new, "class_id": 1, "race": 2, "level": 20})
        acts = teamsync.plan("Bonkers", members, [], set(), True)
        self.assertNotIn(
            (old, new), [(a.target, a.new_name) for a in acts if a.kind == "rename"]
        )


if __name__ == "__main__":
    unittest.main()
