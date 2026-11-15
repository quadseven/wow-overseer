"""How fast a raid seat is sent to learn its assigned professions.

Measured on the dev realm on 2026-11-15, the first hour after the profession
plan shipped: Bonkers had 31 of 35 raid seats short of an assigned trade, and
passes sent 3, 3, 0 and 1 of them. Seats below the cap level first, so they
were asked only inside an hour of a town stop they had already made, and only
a handful of seats made one in a given hour; the six-hour dedicated errand
that was meant as the backstop never reached a seat that levels first; a
refusal for a passing reason (in combat, on a flight path, held by another
verb) waited a full hour before the same walk was asked again; and the
allowance was shared with every other trainer walk.

These tests pin the faster order while keeping the rule that an errand never
displaces levelling: it rides a stop the seat already made or stands in a
city, and the backstop never interrupts a walk in flight.

Pure unit tests against guildjobs.plan, with seats levelling first (the live
setting).
"""

import os
import unittest

import classquest
import guildjobs
import raidteams

BONKERS = "Bonkers"
SEATS = [s for s in raidteams.seats(BONKERS)][5:]
FOCUS = {BONKERS: guildjobs.DUNGEON_FOCUS}
ORGRIMMAR = 1637
# A zone with no town in it: the Barrens.
BARRENS = 17


def setUpModule():
    old = os.environ.pop("SEATS_LEVEL_FIRST", None)

    def restore():
        if old is not None:
            os.environ["SEATS_LEVEL_FIRST"] = old

    unittest.addModuleCleanup(restore)


def member(seat, **over):
    base = dict(
        name=seat.name,
        guild=BONKERS,
        role=guildjobs.RAIDER,
        level=30,
        class_id=seat.class_id,
        race=2,
        online=True,
        map_id=1,
        zone_id=BARRENS,
        x=0.0,
        y=0.0,
        money=5000,
        eligible=True,
        skills={},
        skills_read=True,
    )
    base.update(over)
    return guildjobs.Member(**base)


def errands(result, name=None):
    return [
        s
        for s in result.steps
        if guildjobs.is_profession_errand(s) and (name is None or s.holder == name)
    ]


def skill_of(step):
    return int(step.rows[0].command.split("skill:")[1].split()[0])


def recent(name, action, age, status="delivered", skill=None, **over):
    return guildjobs.Recent(name, action, age, status, skill, **over)


def plan(members, rows=()):
    return guildjobs.plan(members, recent=tuple(rows), focus=FOCUS)


class ASeatThatLevelsFirstTakesTheErrandWhereItStands(unittest.TestCase):
    def test_it_is_levelling_in_this_module(self):
        self.assertTrue(guildjobs.levelling_first(member(SEATS[0])))

    def test_a_hearth_home_is_a_stop(self):
        seat = SEATS[0]
        rows = [recent(seat.name, "hearth", 20, "applied")]
        self.assertEqual(1, len(errands(plan([member(seat)], rows))))

    def test_a_hearth_that_failed_is_not(self):
        seat = SEATS[0]
        rows = [
            recent(seat.name, "hearth", 20, "error"),
            recent(seat.name, "gear", 120),
        ]
        self.assertEqual([], errands(plan([member(seat)], rows)))

    def test_standing_in_a_capital_is_a_stop(self):
        seat = SEATS[1]
        result = plan([member(seat, zone_id=ORGRIMMAR)])
        self.assertEqual(1, len(errands(result)), result.notes)

    def test_standing_in_the_field_is_not(self):
        seat = SEATS[1]
        rows = [recent(seat.name, "gear", 120)]
        self.assertEqual([], errands(plan([member(seat)], rows)))

    def test_a_trade_just_learned_carries_the_other_trade_in_the_same_trip(self):
        seat = SEATS[2]
        pair = plan([member(seat)]).trades[seat.name][:2]
        first, second = pair
        rows = [recent(seat.name, "train", 5, "applied", first)]
        (step,) = errands(plan([member(seat)], rows))
        self.assertEqual(second, skill_of(step))

    def test_a_walk_still_under_way_is_not_a_stop(self):
        seat = SEATS[2]
        pair = plan([member(seat)]).trades[seat.name][:2]
        rows = [recent(seat.name, "train", 5, "verifying", pair[0])]
        self.assertEqual([], errands(plan([member(seat)], rows)))


class TheSixHourErrandIsTheBackstopForASeatThatLevelsFirst(unittest.TestCase):
    def test_a_seat_with_no_stop_for_six_hours_is_sent(self):
        seat = SEATS[3]
        age = guildjobs.DEDICATED_AFTER_MINUTES + 30
        rows = [recent(seat.name, "gear", age)]
        self.assertEqual(1, len(errands(plan([member(seat)], rows))))

    def test_a_seat_with_no_rows_at_all_is_sent(self):
        seat = SEATS[3]
        self.assertEqual(1, len(errands(plan([member(seat)]))))

    def test_a_seat_between_the_two_waits_for_a_stop(self):
        seat = SEATS[4]
        age = (guildjobs.TOWN_STOP_MINUTES + guildjobs.DEDICATED_AFTER_MINUTES) // 2
        rows = [recent(seat.name, "gear", age)]
        result = plan([member(seat)], rows)
        self.assertEqual([], errands(result))

    def test_it_never_cuts_across_a_walk_in_flight(self):
        seat = SEATS[5]
        age = guildjobs.DEDICATED_AFTER_MINUTES + 30
        rows = [
            recent(seat.name, "gear", age),
            recent(seat.name, "level", 4, "verifying", walk=True),
        ]
        self.assertEqual([], errands(plan([member(seat)], rows)))

    def test_it_never_walks_a_seat_in_a_group_or_an_instance(self):
        seat = SEATS[6]
        self.assertEqual([], errands(plan([member(seat, follows=True)])))
        self.assertEqual([], errands(plan([member(seat, map_id=189)])))


class ASeatAtTheCapDoesNotWait(unittest.TestCase):
    def test_it_goes_between_stops_too(self):
        seat = SEATS[7]
        age = (guildjobs.TOWN_STOP_MINUTES + guildjobs.DEDICATED_AFTER_MINUTES) // 2
        rows = [recent(seat.name, "gear", age)]
        result = plan([member(seat, level=60)], rows)
        self.assertEqual(1, len(errands(result)), result.notes)


class APassingRefusalIsAskedAgainOnTheNextPass(unittest.TestCase):
    def refused(self, seat, reason, age, skill):
        return recent(
            seat.name,
            "train",
            age,
            "error",
            skill,
            refusal=reason,
            reason=reason,
            retryable=True,
        )

    def lacks(self, seat):
        return plan([member(seat, level=60)]).trades[seat.name][:2]

    def test_a_fight_is_asked_again_after_the_short_wait(self):
        seat = SEATS[8]
        pair = self.lacks(seat)
        rows = [
            self.refused(seat, "character is in combat", 6, skill) for skill in pair
        ]
        asked = [skill_of(s) for s in errands(plan([member(seat, level=60)], rows))]
        self.assertEqual(1, len(asked))
        self.assertIn(asked[0], pair)

    def test_it_is_not_asked_before_the_short_wait_is_up(self):
        seat = SEATS[8]
        pair = self.lacks(seat)
        rows = [
            self.refused(seat, "character is in combat", 1, skill) for skill in pair
        ]
        self.assertEqual([], errands(plan([member(seat, level=60)], rows)))

    def test_the_flight_the_hold_and_the_far_walk_budget_all_pass(self):
        for i, reason in enumerate(
            (
                "character is on a flight path",
                "character is held by another verb",
                classquest.REALM_FULL_REASON,
            )
        ):
            seat = SEATS[9 + i]
            pair = self.lacks(seat)
            rows = [self.refused(seat, reason, 6, skill) for skill in pair]
            with self.subTest(reason=reason):
                self.assertEqual(
                    1, len(errands(plan([member(seat, level=60)], rows))), reason
                )

    def test_a_death_on_the_road_keeps_the_long_wait(self):
        seat = SEATS[12]
        pair = self.lacks(seat)
        rows = [
            self.refused(seat, "died on the way to the trainer", 6, skill)
            for skill in pair
        ]
        self.assertEqual([], errands(plan([member(seat, level=60)], rows)))


class TheProfessionErrandHasAllowanceOfItsOwn(unittest.TestCase):
    def test_it_is_larger_than_the_old_shared_one(self):
        self.assertGreater(
            guildjobs.PROFESSION_STEPS_PER_GUILD, guildjobs.TRAIN_STEPS_PER_GUILD
        )

    def test_a_guild_starts_up_to_its_errand_allowance_in_a_pass(self):
        members = [member(s, level=60) for s in SEATS]
        result = plan(members)
        self.assertEqual(
            guildjobs.PROFESSION_STEPS_PER_GUILD, len(errands(result)), result.notes
        )

    def test_rank_walks_do_not_take_the_errand_slots(self):
        # Six seats with a trade at its tier ceiling take every rank-walk slot;
        # the seats with no trade still get their full errand allowance.
        capped = [
            member(
                s,
                level=60,
                money=10**6,
                skills={guildjobs.MINING: (75, 75), guildjobs.HERBALISM: (75, 75)},
            )
            for s in SEATS[: guildjobs.TRAIN_STEPS_PER_GUILD]
        ]
        bare = [member(s, level=60) for s in SEATS[guildjobs.TRAIN_STEPS_PER_GUILD :]]
        result = plan(capped + bare)
        trains = [s for s in result.steps if s.action == "train"]
        self.assertGreater(len(trains), guildjobs.TRAIN_STEPS_PER_GUILD)
        self.assertEqual(
            guildjobs.PROFESSION_STEPS_PER_GUILD, len(errands(result)), result.notes
        )


if __name__ == "__main__":
    unittest.main()
