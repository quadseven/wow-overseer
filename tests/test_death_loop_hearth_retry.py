"""A death loop's hearth that a fight or a step stopped is asked again (#2152).

WHY THIS EXISTS. Read on the dev realm on 2026-11-17 over the 55 hearth rows
the guild jobs pass wrote from 12:00: 26 went through, and 19 came back with an
answer the next moment changes (the character in combat 7, moving 7, already
casting 4, the cast never started 1). A member in a death loop is in a fight
most of the time, so the hearth failed for exactly the members that needed it.
Two things then kept it from being asked again:

  * the row was asked once; only the stranded knight's recall was asked again
    inside its step, and
  * the failed row started the same hour of hearth cooldown as a hearth that
    landed, so the next pass named the member "hearth cooling" and issued
    nothing: Workwork's hearth came back "in combat" at 13:52 and the 14:48
    pass logged "hearth cooling" for it.

Of the members whose hearth failed that way, 47 percent died in the zone they
were being sent out of within the hour, against 12 percent of the hearths that
landed.
"""

import asyncio
import unittest

import deathloop
import guildjobs
from test_classquest_follow_up import _Loop
from test_guildlevel_open_quests import (
    HILLSBRAD,
    member,
)

NAME = "Looper"
EASTERN_KINGDOMS = 0
GOLDSHIRE_INN = (-9459.0, 43.0)
ELWYNN = 12
IN_COMBAT = "character is in combat"


def hearth_row(age, status="error", reason=IN_COMBAT, name=NAME):
    return {
        "id": 1,
        "target_name": name,
        "command": "use",
        "source": guildjobs.source_for("hearth", name),
        "status": status,
        "age": age,
        "result": '{"outcome":"refused","reason":"%s","retry":"later"}' % reason
        if reason
        else "",
    }


def recent(*rows):
    return guildjobs.recent_from_rows(list(rows))


def looper():
    return member(
        NAME,
        rewarded=frozenset(),
        home_map=EASTERN_KINGDOMS,
        home_x=GOLDSHIRE_INN[0],
        home_y=GOLDSHIRE_INN[1],
        home_zone=ELWYNN,
    )


def loop_of():
    return deathloop.Loop(
        name=NAME,
        zone=HILLSBRAD,
        map_id=EASTERN_KINGDOMS,
        deaths=7,
        killer="Hillsbrad Farmer",
        level=26,
        first_age=3000,
        last_age=120,
    )


class AHearthTheFightStoppedDoesNotCoolForAnHour(unittest.TestCase):
    def test_each_passing_answer_waits_only_the_short_retry(self):
        for reason in (
            IN_COMBAT,
            "character is moving",
            "character is already casting",
            "the cast never started and the character never left",
        ):
            rows = recent(
                hearth_row(guildjobs.LEVEL_TRANSIENT_RETRY_MINUTES, reason=reason)
            )
            self.assertFalse(guildjobs._cooling(looper(), "hearth", rows), reason)

    def test_it_still_waits_inside_the_short_retry(self):
        rows = recent(hearth_row(guildjobs.LEVEL_TRANSIENT_RETRY_MINUTES - 1))
        self.assertTrue(guildjobs._cooling(looper(), "hearth", rows))

    def test_a_hearth_that_landed_still_cools_for_the_hour(self):
        rows = recent(hearth_row(30, status="applied", reason=""))
        self.assertTrue(guildjobs._cooling(looper(), "hearth", rows))

    def test_an_answer_that_will_not_change_still_cools_for_the_hour(self):
        reason = "a recall casts the hearthstone without the stone"
        rows = recent(hearth_row(30, reason=reason))
        self.assertTrue(guildjobs._cooling(looper(), "hearth", rows))

    def test_another_action_in_a_fight_keeps_its_own_wait(self):
        row = hearth_row(30)
        row["source"] = guildjobs.source_for("gear", NAME)
        row["command"] = "walk-to-vendor any"
        self.assertTrue(guildjobs._cooling(looper(), "gear", recent(row)))

    def test_the_escape_is_issued_again_once_the_short_retry_has_passed(self):
        failed = recent(hearth_row(guildjobs.LEVEL_TRANSIENT_RETRY_MINUTES))
        step = guildjobs.death_loop_hearth(looper(), loop_of(), failed)
        self.assertIsNotNone(step)
        self.assertEqual(step.rows[0].kind, "hearth")

    def test_the_escape_waits_the_hour_after_a_hearth_that_landed(self):
        landed = recent(hearth_row(30, status="applied", reason=""))
        self.assertIsNone(guildjobs.death_loop_hearth(looper(), loop_of(), landed))

    def test_the_refusal_line_no_longer_says_cooling_for_a_stopped_hearth(self):
        failed = recent(hearth_row(guildjobs.LEVEL_TRANSIENT_RETRY_MINUTES + 1))
        word = guildjobs._death_loop_reason(looper(), loop_of(), None, failed)
        self.assertNotEqual(word, "hearth cooling")


class TheHearthIsAskedAgainInsideItsStep(unittest.TestCase):
    def test_a_use_row_is_asked_again_like_a_recall(self):
        self.assertTrue(guildjobs.hearth_asks_again("use"))
        self.assertTrue(guildjobs.hearth_asks_again("recall"))
        self.assertFalse(guildjobs.hearth_asks_again("walk-to-vendor any"))

    def drive(self, command):
        loop = _Loop()
        asked = []

        async def again(step, row):
            asked.append(row.command)
            return True

        loop._recall_row = again
        row = guildjobs.guildcorps.Row("hearth", command, "", "guildjobs:hearth:Looper")
        step = guildjobs.guildcorps.Step(NAME, "hearth", 0, "goes home", rows=(row,))
        went = asyncio.run(loop._run_step_row(step, row, 5000.0))
        return went, asked, loop

    def test_the_death_loop_hearth_goes_through_the_asking_loop(self):
        went, asked, loop = self.drive("use")
        self.assertTrue(went)
        self.assertEqual(asked, ["use"])

    def test_only_the_recall_wakes_the_next_pass(self):
        _, _, used = self.drive("use")
        _, _, recalled = self.drive("recall")
        self.assertFalse(used._follow_up_event().is_set())
        self.assertTrue(recalled._follow_up_event().is_set())


if __name__ == "__main__":
    unittest.main()
