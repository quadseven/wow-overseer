"""Tests for fair crossing order and cap-refusal retry spread (#2184)."""

import unittest

from test_classquest import KALIMDOR, book, who

import classquest
import guildjobs

AT_ONCE = "the realm already has as many crossings as it allows (Overseer.Cross.AtOnce)"
BERTH = "the walk to the berth gave up on the ground"
NO_ROUTE = (
    "no transport the module knows sails from this map to that map for this faction"
)


def _cap_row(name, age, action=classquest.CROSS_ACTION):
    return guildjobs.Recent(
        name,
        action,
        age,
        status="error",
        dest=KALIMDOR,
        refusal=AT_ONCE,
        retryable=True,
    )


def _ok_row(name, age, action=classquest.CROSS_ACTION):
    return guildjobs.Recent(
        name,
        action,
        age,
        status="applied",
        dest=KALIMDOR,
    )


class CapRefusalOrder(unittest.TestCase):
    def test_cap_refused_seat_is_planned_ahead_of_crossed_and_unrefused(self):
        # Zz has lower priority (DPS, lower level) and was refused at the cap;
        # Aa has higher priority (healer, higher level) and just crossed;
        # Bb was not refused. Zz must be ordered first.
        aa = who("Aa", class_id=5, tree="Holy", level=50)
        bb = who("Bb", class_id=5, tree="Holy", level=45)
        zz = who("Zz", class_id=1, tree="Arms", level=20)
        recent = (
            _ok_row("Aa", 15),
            _cap_row("Zz", 12),
        )

        ordered = guildjobs._class_ordered([aa, bb, zz], book(), recent)

        self.assertEqual([m.name for m in ordered], ["Zz", "Bb", "Aa"])

    def test_every_seat_crosses_within_bounded_passes_without_starvation(self):
        # 5 seats compete for 1 crossing slot per pass; class priority and
        # level alone would starve lower-priority seats if refusals did not
        # promote them.
        seats = [
            who("Seat0", class_id=5, tree="Holy", level=60),
            who("Seat1", class_id=1, tree="Protection", level=55),
            who("Seat2", class_id=1, tree="Arms", level=40),
            who("Seat3", class_id=1, tree="Arms", level=30),
            who("Seat4", class_id=1, tree="Arms", level=20),
        ]
        recent = ()
        crossed = set()
        for _pass in range(8):
            ordered = guildjobs._class_ordered(seats, book(), recent)
            # 1 slot succeeds, the next 2 hit the cap, rest wait.
            winner = ordered[0].name
            crossed.add(winner)
            next_rows = [_ok_row(winner, 0)]
            for loser in ordered[1:3]:
                next_rows.append(_cap_row(loser.name, 0))
            recent = tuple(
                guildjobs.Recent(
                    r.name,
                    r.action,
                    r.age_minutes + 15,
                    r.status,
                    dest=r.dest,
                    refusal=r.refusal,
                    retryable=r.retryable,
                )
                for r in recent
            ) + tuple(next_rows)
            if len(crossed) == len(seats):
                break

        self.assertEqual(crossed, {s.name for s in seats})


class CapRefusalRetryClock(unittest.TestCase):
    def test_cap_refusal_differs_from_fault_retry_and_spreads_seats(self):
        names = [f"Seat{i}" for i in range(12)]
        # Fault refusal always cools at age CROSS_RETRY_MINUTES - 1.
        fault_row = guildjobs.Recent(
            "Seat0",
            classquest.CROSS_ACTION,
            classquest.CROSS_RETRY_MINUTES - 1,
            status="error",
            dest=KALIMDOR,
            refusal="the character is in combat",
            retryable=True,
        )
        self.assertTrue(guildjobs.crossing_cooling("Seat0", (fault_row,)))

        # Cap refusals spread across the retry interval so not all seats
        # return together at CROSS_RETRY_MINUTES.
        cooling_at_mid = {
            name: guildjobs.crossing_cooling(name, (_cap_row(name, 6),))
            for name in names
        }
        self.assertTrue(any(cooling_at_mid.values()))
        self.assertFalse(all(cooling_at_mid.values()))

    def test_berth_give_up_hold_and_walls_keep_meaning(self):
        berth_rows = (
            guildjobs.Recent(
                "Mirra",
                classquest.CROSS_ACTION,
                classquest.CROSS_RETRY_MINUTES,
                status="error",
                dest=KALIMDOR,
                refusal=BERTH,
                retryable=True,
            ),
            guildjobs.Recent(
                "Mirra",
                classquest.CROSS_ACTION,
                classquest.CROSS_RETRY_MINUTES + 10,
                status="error",
                dest=KALIMDOR,
                refusal=BERTH,
                retryable=True,
            ),
        )
        self.assertTrue(guildjobs.crossing_cooling("Mirra", berth_rows))
        wall_row = guildjobs.Recent(
            "Mirra",
            classquest.CROSS_ACTION,
            20,
            status="error",
            dest=KALIMDOR,
            refusal=NO_ROUTE,
            retryable=False,
        )
        self.assertEqual(
            guildjobs.class_walls("Mirra", (wall_row,)), {KALIMDOR: NO_ROUTE}
        )


if __name__ == "__main__":
    unittest.main()
