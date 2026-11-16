"""The guild training pass's trainee rows: roster members stay out,
except a roster member holding a raid tank seat (#2361).

The pass walks guild members off the roster to their class trainer; the
families' own passes are supposed to train the roster, but no family
pass walks a roster member to a class trainer, so a seated tank on the
roster had no route at all. classtrain.trainee_rows is the pure filter
bridge._fetch_trainees applies to the guild rows it read: a row is kept
when its member is off the roster, or holds a tank seat under either
name the seat may be found by.
"""

import unittest

import classtrain

ROWS = [
    {"name": "Offroster"},
    {"name": "Familytank"},
    {"name": "Familymage"},
    {"name": "Offtank"},
]


class TraineeRows(unittest.TestCase):
    def test_off_roster_rows_are_kept(self):
        out = classtrain.trainee_rows(
            ROWS, {"Familytank", "Familymage"}, {"Familytank"}
        )
        self.assertEqual(
            [r["name"] for r in out], ["Offroster", "Familytank", "Offtank"]
        )

    def test_a_roster_member_without_a_tank_seat_stays_out(self):
        out = classtrain.trainee_rows(ROWS, {"Familytank", "Familymage"}, set())
        self.assertEqual([r["name"] for r in out], ["Offroster", "Offtank"])

    def test_no_roster_keeps_every_row(self):
        out = classtrain.trainee_rows(ROWS, set(), set())
        self.assertEqual([r["name"] for r in out], [r["name"] for r in ROWS])


if __name__ == "__main__":
    unittest.main()
