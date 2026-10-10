"""A guild member that stands on one spot with nothing moving it hearths home.

Measured on the dev realm on 2026-10-10 (UTC 04:30): Highlights, a level 7
Blood Elf warlock of Bonkers, had stood at one point in Eversong Woods for
10.8 hours played at her level, the bridge writing her nothing since a gear buy
at 15:56 the day before. Her own AI picked a grind spot or an innkeeper every
few minutes and gave each up, "stuck when moving far", 119 times in 3.2 hours,
every time from the same point. Diggo (Cave, 14, Teldrassil, 67.9 hours at his
level), Dug (Cave, 15, Bloodmyst Isle, 54 hours) and Totta (Cave, 23, Elwynn
Forest) stood the same way, and nothing noticed: the pass reads no position
history, and a member with no job and no outgrown zone gets no step.

A player whose character will not move from a spot uses the hearthstone. So a
member that has stood within STILL_YARDS of one point for STILL_MINUTES, alive,
out of combat, below the level cap, with no level gained and no guild job row
written for it in that time, hearths home to its inn (kind='hearth' `use`, the
gear walk's hearth), where its own AI starts again.
"""

import pathlib
import unittest

import guildjobs
import guildlevel
import guildroute
import standstill

OUTLAND, EASTERN_KINGDOMS, KALIMDOR = 530, 0, 1
BLOOD_ELF, WARLOCK = 10, 9
EVERSONG, WAILING_CAVERNS = 3430, 718
MINUTE = 60.0


def member(name="Highlights", **over):
    base = dict(
        name=name,
        guild="Bonkers",
        role=guildjobs.RAIDER,
        level=7,
        class_id=WARLOCK,
        race=BLOOD_ELF,
        online=True,
        map_id=OUTLAND,
        x=9436.78,
        y=-6316.45,
        zone_id=EVERSONG,
        money=0,
        eligible=True,
    )
    base.update(over)
    return guildjobs.Member(**base)


def plan(members, **kw):
    kw.setdefault("masters", {"Cave": "Grug", "Bonkers": "Zug"})
    kw.setdefault("cap", guildroute.FAR_WALK_YARDS)
    return guildjobs.plan(members, **kw)


def hearths(result):
    return [s for s in result.steps if s.action == "hearth"]


def row(name, action, age, status="applied"):
    return guildjobs.Recent(name, action, age, status)


class TheClock(unittest.TestCase):
    def test_a_member_on_one_spot_counts_up(self):
        anchors = standstill.track({}, [member()], 0.0)
        anchors = standstill.track(anchors, [member(x=9440.0)], 30 * MINUTE)
        anchors = standstill.track(anchors, [member(y=-6312.0)], 70 * MINUTE)
        self.assertEqual(standstill.minutes(anchors, "Highlights", 70 * MINUTE), 70)

    def test_a_step_away_starts_it_again(self):
        anchors = standstill.track({}, [member()], 0.0)
        anchors = standstill.track(anchors, [member(x=9436.78 + 20.0)], 50 * MINUTE)
        self.assertEqual(standstill.minutes(anchors, "Highlights", 70 * MINUTE), 20)

    def test_another_map_or_a_level_gained_starts_it_again(self):
        start = standstill.track({}, [member()], 0.0)
        moved = standstill.track(start, [member(map_id=EASTERN_KINGDOMS)], 50 * MINUTE)
        self.assertEqual(standstill.minutes(moved, "Highlights", 70 * MINUTE), 20)
        levelled = standstill.track(start, [member(level=8)], 50 * MINUTE)
        self.assertEqual(standstill.minutes(levelled, "Highlights", 70 * MINUTE), 20)

    def test_offline_dead_or_unread_is_not_standing(self):
        start = standstill.track({}, [member()], 0.0)
        for gone in (member(online=False), member(alive=False), member(x=None)):
            later = standstill.track(start, [gone], 70 * MINUTE)
            self.assertEqual(standstill.minutes(later, "Highlights", 70 * MINUTE), 0)

    def test_another_guilds_pass_keeps_this_ones_clock(self):
        start = standstill.track({}, [member()], 0.0)
        other = standstill.track(start, [member("Diggo", guild="Cave")], 30 * MINUTE)
        self.assertEqual(standstill.minutes(other, "Highlights", 70 * MINUTE), 70)

    def test_a_member_unseen_for_long_is_forgotten(self):
        start = standstill.track({}, [member()], 0.0)
        later = standstill.track(
            start, [member("Diggo")], standstill.FORGET_SECONDS + 1.0
        )
        self.assertNotIn("Highlights", later)


class TheHearth(unittest.TestCase):
    def test_a_member_stood_still_an_hour_with_nothing_asked_hearths_home(self):
        result = plan([member()], still={"Highlights": 70})
        steps = hearths(result)
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual([(r.kind, r.command) for r in step.rows], [("hearth", "use")])
        self.assertEqual(step.rows[0].source, "guildjobs:hearth:Highlights")
        self.assertIn("stood", step.said)
        self.assertIn("70 minutes", step.said)
        self.assertEqual(result.lines["Highlights"], step.said)

    def test_not_before_the_hour(self):
        self.assertEqual(hearths(plan([member()], still={"Highlights": 50})), [])

    def test_not_with_no_clock(self):
        self.assertEqual(hearths(plan([member()])), [])

    def test_not_while_a_guild_job_row_was_written_for_it_in_that_time(self):
        recent = (row("Highlights", "gear", 20),)
        self.assertEqual(
            hearths(plan([member()], still={"Highlights": 70}, recent=recent)), []
        )

    def test_a_row_older_than_the_stand_does_not_hold_it(self):
        recent = (row("Highlights", "gear", 80),)
        got = hearths(plan([member()], still={"Highlights": 70}, recent=recent))
        self.assertEqual(len(got), 1)

    def test_not_within_the_hearthstones_hour(self):
        recent = (row("Highlights", "hearth", 65),)
        # A hearth that went through 65 minutes ago is older than the stand of
        # 70 minutes but inside no cooldown: it may go again.
        self.assertEqual(
            len(hearths(plan([member()], still={"Highlights": 70}, recent=recent))), 1
        )
        recent = (row("Highlights", "hearth", 30),)
        self.assertEqual(
            hearths(plan([member()], still={"Highlights": 90}, recent=recent)), []
        )

    def test_not_fighting_dead_offline_or_at_the_cap(self):
        for m in (
            member(in_combat=True),
            member(alive=False),
            member(online=False),
            member(level=guildlevel.LEVEL_CAP),
        ):
            self.assertEqual(hearths(plan([m], still={"Highlights": 120})), [], m)

    def test_not_inside_a_dungeon(self):
        inside = member(map_id=43, zone_id=WAILING_CAVERNS, x=0.0, y=0.0)
        self.assertEqual(hearths(plan([inside], still={"Highlights": 120})), [])

    def test_not_a_roster_family_member(self):
        world = guildlevel.World(bands={}, masters={}, roster=frozenset({"Highlights"}))
        self.assertEqual(
            hearths(plan([member()], still={"Highlights": 120}, leveling=world)), []
        )


class TheBridgeKeepsTheClock(unittest.TestCase):
    def test_each_pass_reads_the_stands_and_hands_them_to_the_plan(self):
        bridge = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "self._guild_still = standstill.track(self._guild_still, members, now)",
            bridge,
        )
        self.assertIn(
            "still=standstill.all_minutes(self._guild_still, time.monotonic())", bridge
        )


if __name__ == "__main__":
    unittest.main()
