"""A raid seat learns the two professions it was assigned (slice 2).

Measured on the dev realm on 2026-11-15: 33 of the 80 approved raid seats held
no primary profession, 32 of them in Bonkers, whose guild runs under
GUILD_FOCUS dungeon. That focus keeps every member's ordinary job, and a
raider's ordinary job is the post and the sale, so no Bonkers seat was ever
sent to a trainer. These tests pin the narrow exception: a seat missing an
assigned profession gets one trainer errand per missing trade, between runs,
under either focus, and never walks anybody it should not.

Pure unit tests against guildjobs.plan.
"""

import unittest

import guildjobs
import legacy_ladder
import guildtrades
import raidteams

H, M = guildjobs.HERBALISM, guildjobs.MINING
BONKERS = "Bonkers"
SEATS = [s for s in raidteams.seats(BONKERS)][5:]
FOCUS_DUNGEON = {BONKERS: guildjobs.DUNGEON_FOCUS}
FOCUS_CRAFT = {BONKERS: guildjobs.CRAFT_FOCUS}


def setUpModule():
    legacy_ladder.switch_off()


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


def recent(name, action, age, status="delivered"):
    return guildjobs.Recent(name, action, age, status)


class ASeatWithNoProfession(unittest.TestCase):
    def test_it_walks_to_a_trainer_for_one_of_its_assigned_trades_under_dungeon_focus(
        self,
    ):
        seat = SEATS[0]
        result = guildjobs.plan([member(seat)], focus=FOCUS_DUNGEON)
        (step,) = errands(result)
        pair = result.trades[seat.name]
        self.assertIn(skill_of(step), pair)
        self.assertEqual("train", step.action)
        self.assertIn("walk-to-trainer skill:%d" % skill_of(step), step.rows[0].command)

    def test_the_same_seat_walks_under_craft_focus_and_with_no_focus(self):
        seat = SEATS[1]
        for focus in (FOCUS_CRAFT, None):
            with self.subTest(focus=focus):
                result = guildjobs.plan([member(seat)], focus=focus)
                self.assertEqual(1, len(errands(result)), result.notes)

    def test_the_plan_names_the_pair_it_assigned(self):
        seat = SEATS[2]
        result = guildjobs.plan([member(seat)], focus=FOCUS_DUNGEON)
        self.assertEqual(2, len(result.assigned[seat.name]))
        self.assertTrue(set(result.assigned[seat.name]) <= guildtrades.PRIMARIES)

    def test_the_errand_only_writes_a_trainer_walk_never_an_aim_or_a_grant(self):
        seat = SEATS[3]
        (step,) = errands(guildjobs.plan([member(seat)], focus=FOCUS_DUNGEON))
        self.assertIsNone(step.walk)
        self.assertEqual(1, len(step.rows))
        self.assertEqual("cast", step.rows[0].kind)
        self.assertTrue(step.rows[0].command.startswith("walk-to-trainer skill:"))

    def test_it_holds_nothing_back_for_a_level_it_has_not_reached(self):
        seat = SEATS[4]
        result = guildjobs.plan([member(seat, level=4)], focus=FOCUS_DUNGEON)
        self.assertEqual([], errands(result))

    def test_it_saves_for_the_fee_and_says_so(self):
        seat = SEATS[5]
        result = guildjobs.plan([member(seat, money=9)], focus=FOCUS_DUNGEON)
        self.assertEqual([], errands(result))
        self.assertTrue(any("saves for" in n for n in result.notes), result.notes)

    def test_a_seat_not_yet_natural_is_left_alone(self):
        seat = SEATS[6]
        result = guildjobs.plan([member(seat, eligible=False)], focus=FOCUS_DUNGEON)
        self.assertEqual([], errands(result))


class ASeatThatHoldsSome(unittest.TestCase):
    def pair_of(self, seat, **over):
        return guildjobs.plan([member(seat, **over)]).trades[seat.name]

    def test_it_is_sent_for_the_trade_it_lacks_only(self):
        seat = SEATS[7]
        pair = self.pair_of(seat)
        have, lack = pair[0], pair[1]
        m = member(seat, skills={have: (20, 75)})
        result = guildjobs.plan([m], focus=FOCUS_DUNGEON)
        (step,) = errands(result)
        self.assertEqual(lack, skill_of(step))

    def test_it_is_not_sent_when_it_holds_its_whole_pair(self):
        seat = SEATS[8]
        pair = self.pair_of(seat)
        m = member(seat, skills={s: (20, 75) for s in pair})
        self.assertEqual([], errands(guildjobs.plan([m], focus=FOCUS_DUNGEON)))

    def test_it_keeps_two_trades_that_are_no_pair_and_is_not_sent(self):
        seat = SEATS[9]
        m = member(seat, skills={H: (20, 75), guildjobs.SKINNING: (20, 75)})
        result = guildjobs.plan([m], focus=FOCUS_DUNGEON)
        self.assertEqual([], errands(result))
        self.assertEqual(
            guildtrades_key((H, guildjobs.SKINNING)),
            guildtrades_key(result.assigned[seat.name]),
        )


def guildtrades_key(pair):
    return tuple(sorted(pair))


class WhenTheErrandIsTaken(unittest.TestCase):
    def test_a_seat_with_no_town_stop_for_a_long_time_gets_a_dedicated_errand(self):
        seat = SEATS[10]
        rows = (recent(seat.name, "gear", guildjobs.DEDICATED_AFTER_MINUTES + 30),)
        result = guildjobs.plan([member(seat)], recent=rows, focus=FOCUS_DUNGEON)
        self.assertEqual(1, len(errands(result)), result.notes)

    def test_a_seat_that_has_just_made_a_town_stop_takes_it_there(self):
        seat = SEATS[10]
        rows = (recent(seat.name, "sell", 20),)
        result = guildjobs.plan([member(seat)], recent=rows, focus=FOCUS_DUNGEON)
        self.assertEqual(1, len(errands(result)), result.notes)

    def test_a_seat_between_the_two_waits_for_its_next_stop(self):
        seat = SEATS[10]
        age = (guildjobs.TOWN_STOP_MINUTES + guildjobs.DEDICATED_AFTER_MINUTES) // 2
        rows = (recent(seat.name, "gear", age),)
        result = guildjobs.plan([member(seat)], recent=rows, focus=FOCUS_DUNGEON)
        self.assertEqual([], errands(result))
        self.assertTrue(any("town stop" in n for n in result.notes), result.notes)

    def test_a_failed_walk_cools_down_before_the_next_one(self):
        seat = SEATS[11]
        pair = guildjobs.plan([member(seat)]).trades[seat.name]
        rows = tuple(
            guildjobs.Recent(seat.name, "train", 5, "error", skill) for skill in pair
        )
        result = guildjobs.plan([member(seat)], recent=rows, focus=FOCUS_DUNGEON)
        self.assertEqual([], errands(result))

    def test_a_walk_just_made_is_not_asked_again_inside_the_hour(self):
        seat = SEATS[11]
        pair = guildjobs.plan([member(seat)]).trades[seat.name]
        rows = tuple(
            guildjobs.Recent(seat.name, "train", 10, "delivered", skill)
            for skill in pair
        )
        result = guildjobs.plan([member(seat)], recent=rows, focus=FOCUS_DUNGEON)
        self.assertEqual([], errands(result))


class WhoIsLeftAlone(unittest.TestCase):
    def check_none(self, seat_index, **over):
        seat = SEATS[seat_index]
        return errands(guildjobs.plan([member(seat, **over)], focus=FOCUS_DUNGEON))

    def test_a_seat_in_a_group_following_its_leader(self):
        self.assertEqual([], self.check_none(12, follows=True))

    def test_a_seat_in_combat(self):
        self.assertEqual([], self.check_none(13, in_combat=True))

    def test_a_seat_that_is_offline_or_dead(self):
        self.assertEqual([], self.check_none(14, online=False))
        self.assertEqual([], self.check_none(15, alive=False))

    def test_a_seat_inside_an_instance(self):
        self.assertEqual([], self.check_none(16, map_id=389))

    def test_a_seat_in_a_guild_run_is_busy_and_is_not_walked(self):
        seat = SEATS[17]
        result = guildjobs.plan([member(seat)], busy=(seat.name,), focus=FOCUS_DUNGEON)
        self.assertEqual([], errands(result))

    def test_a_seat_a_summon_waits_on(self):
        seat = SEATS[18]
        result = guildjobs.plan(
            [member(seat)], pending=(seat.name,), focus=FOCUS_DUNGEON
        )
        self.assertEqual([], errands(result))

    def test_a_maintenance_member_and_a_seat_off_the_approved_list(self):
        seat = SEATS[19]
        other = member(seat, name="Notaseatname")
        self.assertEqual([], errands(guildjobs.plan([other], focus=FOCUS_DUNGEON)))

    def test_a_family_seat_is_left_to_its_own_loop(self):
        seat = raidteams.seats(BONKERS)[0]
        m = member(seat, role=guildjobs.FAMILY)
        self.assertEqual([], errands(guildjobs.plan([m], focus=FOCUS_DUNGEON)))


class HowManyAtOnce(unittest.TestCase):
    def test_a_guild_starts_no_more_than_its_trainer_allowance_in_a_pass(self):
        members = [member(s) for s in SEATS]
        result = guildjobs.plan(members, focus=FOCUS_DUNGEON)
        self.assertEqual(guildjobs.PROFESSION_STEPS_PER_GUILD, len(errands(result)))

    def test_the_planned_trades_are_the_assigned_pairs(self):
        members = [member(s) for s in SEATS]
        result = guildjobs.plan(members, focus=FOCUS_DUNGEON)
        for m in members:
            self.assertEqual(result.assigned[m.name], result.trades[m.name][:2])


class TheFirstRanksAreTheWorldsOwn(unittest.TestCase):
    # acore_world.trainer_spell on the dev world, 2026-11-15: the least
    # MoneyCost and ReqLevel across the trainers that teach each first rank.
    MEASURED = {
        2372: (10, 5),  # Herbalism
        2581: (10, 5),  # Mining
        8615: (10, 0),  # Skinning
        2275: (10, 5),  # Alchemy
        4039: (10, 5),  # Engineering
        2020: (10, 5),  # Blacksmithing
        2155: (10, 5),  # Leatherworking
        3911: (10, 5),  # Tailoring
        7414: (10, 5),  # Enchanting
    }

    def test_each_first_rank_costs_and_asks_what_the_trainer_table_says(self):
        for skill in guildtrades.PRIMARIES:
            first = guildjobs.RANKS[skill][0]
            self.assertEqual(
                self.MEASURED[first.spell], (first.cost, first.level), skill
            )


class TheBridgeChecksTheDeathDiscs(unittest.TestCase):
    def test_the_job_step_runner_asks_the_discs_before_a_profession_errand_walks(self):
        import pathlib

        text = pathlib.Path("bridge.py").read_text(encoding="utf-8")
        start = text.index("async def _run_job_step")
        body = text[start : start + 5000]
        self.assertIn("is_profession_errand", body)
        self.assertIn("_death_disc_refusal", body)
        self.assertLess(body.index("_death_disc_refusal"), body.index("step.rows"))


class TheLogLine(unittest.TestCase):
    def test_a_guild_says_how_many_hold_their_trades_and_how_many_walk(self):
        members = [member(s) for s in SEATS]
        result = guildjobs.plan(members, focus=FOCUS_DUNGEON)
        (line,) = guildjobs.profession_lines(members, result)
        self.assertIn("Bonkers: profession plan: %d raid seat(s)" % len(SEATS), line)
        self.assertIn(
            "%d sent to a trainer" % guildjobs.PROFESSION_STEPS_PER_GUILD, line
        )


if __name__ == "__main__":
    unittest.main()
