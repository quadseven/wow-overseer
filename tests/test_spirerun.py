"""The Upper Spire run: ten seats from one guild, ordered and ended by itself.

What these pin:

  1. ONLY EARNED LEVELS SIT. A seat is at the floor by its own play: a Death
     Knight starts at 55 and is never seated, and a family under the floor
     holds the whole run, because its head leads and its members cannot be
     left out of his group.
  2. A RUNNING CAMPAIGN IS NEVER REPLACED. The order goes behind an active
     entry and in front of a queued one, once.
  3. IT ENDS ITSELF. A raid order otherwise stands until a person clears it,
     and nobody is there to clear this one.
"""

import pathlib
import unittest

import campaignplan
import campaignqueue
import guildjobs
import jobs
import preraid
import raidrun
import spirerun

WARRIOR, PALADIN, HUNTER, ROGUE, PRIEST, DK, SHAMAN, MAGE, WARLOCK, DRUID = (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 11,
)  # fmt: skip
HERE = pathlib.Path(__file__).resolve().parent.parent
FAMILY = ["Head", "Heal", "Mage", "Rogue", "Shaman"]


def member(name, class_id, level=56, spec=""):
    return {"name": name, "class_id": class_id, "level": level, "spec": spec}


def guild(**changes):
    rows = [
        member("Head", WARRIOR, spec="Protection"),
        member("Heal", PRIEST, spec="Holy"),
        member("Mage", MAGE),
        member("Rogue", ROGUE),
        member("Shaman", SHAMAN, spec="Restoration"),
        member("Aa", MAGE, 60),
        member("Bb", WARLOCK, 58),
        member("Cc", HUNTER, 57),
        member("Dd", ROGUE, 56),
        member("Ee", MAGE, 56),
        member("Low", MAGE, 55),
    ]
    return [dict(r, **changes.get(r["name"], {})) for r in rows]


def seated(lineup):
    return [m["name"] for g in lineup.groups for m in g["members"]]


class TheSeats(unittest.TestCase):
    def test_ten_natural_seats_in_two_groups_with_the_family_together(self):
        lineup = spirerun.lineup(guild(), FAMILY)
        self.assertEqual(lineup.short, "")
        self.assertEqual(len(seated(lineup)), 10)
        self.assertEqual([len(g["members"]) for g in lineup.groups], [5, 5])
        self.assertEqual(
            sorted(m["name"] for m in lineup.groups[0]["members"]), sorted(FAMILY)
        )
        self.assertNotIn("Low", seated(lineup))

    def test_a_death_knight_never_sits_whatever_its_level(self):
        rows = guild() + [member("Knight", DK, 60)]
        self.assertNotIn("Knight", seated(spirerun.lineup(rows, FAMILY)))

    def test_a_family_member_under_the_floor_holds_the_run_and_says_who(self):
        lineup = spirerun.lineup(guild(Shaman={"level": 55}), FAMILY)
        self.assertEqual(lineup.groups, ())
        self.assertIn("Shaman", lineup.short)
        self.assertIn("56", lineup.short)

    def test_nine_seats_is_not_a_run(self):
        rows = [r for r in guild() if r["name"] != "Ee"]
        lineup = spirerun.lineup(rows, FAMILY)
        self.assertEqual(lineup.groups, ())
        self.assertIn("9 of 10", lineup.short)

    def test_two_healers_are_required(self):
        rows = guild(Shaman={"class_id": HUNTER, "spec": ""})
        lineup = spirerun.lineup(rows, FAMILY)
        self.assertEqual(lineup.groups, ())
        self.assertIn("healer", lineup.short)

    def test_a_guild_healer_fills_the_second_healing_seat_first(self):
        rows = guild(Shaman={"class_id": HUNTER, "spec": ""})
        rows.append(member("Zz", PRIEST, 56, "Holy"))
        lineup = spirerun.lineup(rows, FAMILY)
        self.assertEqual(lineup.short, "")
        self.assertIn("Zz", seated(lineup))

    def test_the_seat_rows_are_what_the_raid_table_takes(self):
        rows = raidrun.seat_rows("Head", raidrun.UPPER_SPIRE, spirerun.lineup(guild(), FAMILY).as_dict())
        self.assertEqual(len(rows), 10)
        self.assertEqual({r[3] for r in rows}, {0, 1})
        self.assertEqual({r[1] for r in rows}, {raidrun.UPPER_SPIRE})
        head = [r for r in rows if r[2] == "Head"][0]
        self.assertEqual(head[4], "tank")


def row(id_, keyword, status="queued", position=1, source="overseer:planner"):
    return {
        "id": id_,
        "keyword": keyword,
        "status": status,
        "position": position,
        "source": source,
    }


NOW = 1_800_000_000.0


class TheOrder(unittest.TestCase):
    def test_an_active_campaign_stays_and_the_run_goes_behind_it(self):
        rows = [row(1, "uldaman", "active", 2), row(2, "maraudon", "queued", 3)]
        slot = spirerun.order_slot(rows, None, NOW)
        self.assertEqual(slot.position, 3)
        self.assertEqual(slot.shift, (2,))

    def test_with_nothing_active_it_goes_first(self):
        slot = spirerun.order_slot([row(2, "uldaman", "queued", 1)], None, NOW)
        self.assertEqual(slot.position, 1)
        self.assertEqual(slot.shift, (2,))

    def test_an_empty_queue_takes_it(self):
        self.assertEqual(spirerun.order_slot([], None, NOW).position, 0)

    def test_once_queued_it_is_not_written_again(self):
        rows = [row(5, raidrun.UPPER_SPIRE, "active", 0, spirerun.SOURCE)]
        self.assertIsNone(spirerun.order_slot(rows, None, NOW))

    def test_a_clear_waits_a_week_and_a_failed_night_a_day(self):
        cleared = spirerun.Last(finished_at=NOW - 86400, cleared=True)
        failed = spirerun.Last(finished_at=NOW - 86400 + 60, cleared=False)
        self.assertIsNone(spirerun.order_slot([], cleared, NOW))
        self.assertIsNone(spirerun.order_slot([], failed, NOW))
        later = spirerun.Last(finished_at=NOW - 86401, cleared=False)
        self.assertIsNotNone(spirerun.order_slot([], later, NOW))


class ReviewFindings(unittest.TestCase):
    def test_a_death_knight_in_the_family_holds_the_run(self):
        lineup = spirerun.lineup(guild(Mage={"class_id": DK, "level": 60}), FAMILY)
        self.assertEqual(lineup.groups, ())
        self.assertIn("Death Knight", lineup.short)

    def test_every_shortfall_is_said(self):
        rows = [r for r in guild(Shaman={"class_id": HUNTER, "spec": ""}) if r["name"] != "Ee"]
        lineup = spirerun.lineup(rows, FAMILY)
        self.assertIn("healer", lineup.short)
        self.assertIn("9 of 10", lineup.short)

    def test_the_event_join_names_its_collation(self):
        for sql in (spirerun.LAST_SQL, spirerun.STANDING_SQL):
            self.assertIn("q.family COLLATE utf8mb4_unicode_ci", sql)

    def test_the_insert_itself_refuses_a_second_pending_entry(self):
        self.assertIn("NOT EXISTS", spirerun.ORDER_SQL)
        self.assertIn("'queued', 'active'", spirerun.ORDER_SQL)

    def test_a_step_down_keeps_the_door_row_behind_it(self):
        rows = [
            row(1, "zulfarrak", "active", 0, campaignplan.SOURCE_STEPDOWN),
            row(2, "maraudon", "queued", 1, campaignplan.SOURCE),
            row(3, "uldaman", "queued", 2, campaignplan.SOURCE),
        ]
        slot = spirerun.order_slot(rows, None, NOW)
        self.assertEqual(slot.position, 2)
        self.assertEqual(slot.shift, (3,))

    def test_the_stone_lookup_uses_the_raids_own_map(self):
        self.assertEqual(guildjobs._door_map("ubrs"), 229)
        self.assertEqual(guildjobs._door_map("moltencore"), 409)

    def test_the_image_carries_the_module(self):
        self.assertIn("spirerun.py", (HERE / "Dockerfile").read_text(encoding="utf-8"))


class AStopSticks(unittest.TestCase):
    def test_a_cancelled_entry_stops_the_order_for_its_whole_wait(self):
        stopped = spirerun.Last(finished_at=NOW - 86400 * 6, cleared=False, cancelled=True)
        self.assertIsNone(spirerun.order_slot([], stopped, NOW))

    def test_a_cancel_stops_it_longer_than_a_failed_night(self):
        self.assertGreater(spirerun.AFTER_CANCEL_SECONDS, spirerun.AFTER_FAILURE_SECONDS)
        over = spirerun.Last(
            finished_at=NOW - spirerun.AFTER_CANCEL_SECONDS - 1,
            cleared=False,
            cancelled=True,
        )
        self.assertIsNotNone(spirerun.order_slot([], over, NOW))

    def test_the_read_counts_a_cancel_and_not_its_own_withdrawal(self):
        self.assertIn("'cancelled'", spirerun.LAST_SQL)
        self.assertNotEqual(spirerun.SOURCE, spirerun.SOURCE_WITHDRAWN)

    def test_an_operators_queued_entry_stays_in_front(self):
        rows = [
            row(1, "uldaman", "queued", 0, "discord:someone"),
            row(2, "maraudon", "queued", 1, campaignplan.SOURCE),
        ]
        slot = spirerun.order_slot(rows, None, NOW)
        self.assertEqual(slot.position, 1)
        self.assertEqual(slot.shift, (2,))

    def test_behind_an_active_entry_and_the_operators_after_it(self):
        rows = [
            row(1, "uldaman", "active", 0, campaignplan.SOURCE),
            row(2, "maraudon", "queued", 1, "discord:someone"),
            row(3, "zulfarrak", "queued", 2, campaignplan.SOURCE_JEV),
        ]
        slot = spirerun.order_slot(rows, None, NOW)
        self.assertEqual(slot.position, 2)
        self.assertEqual(slot.shift, (3,))


class AnEntryThatNeverStarted(unittest.TestCase):
    def waiting(self):
        return row(9, raidrun.UPPER_SPIRE, "queued", 3, spirerun.SOURCE)

    def test_a_short_lineup_withdraws_it(self):
        self.assertEqual(spirerun.withdrawal([self.waiting()], "9 of 10 seats", 60), 9)

    def test_the_age_ceiling_withdraws_it(self):
        self.assertEqual(
            spirerun.withdrawal([self.waiting()], "", spirerun.QUEUED_CEILING_SECONDS), 9
        )

    def test_a_full_lineup_inside_the_ceiling_keeps_it(self):
        self.assertIsNone(spirerun.withdrawal([self.waiting()], "", 60))

    def test_a_running_entry_is_never_withdrawn(self):
        active = row(9, raidrun.UPPER_SPIRE, "active", 0, spirerun.SOURCE)
        self.assertIsNone(spirerun.withdrawal([active], "short", 99999999))

    def test_an_operators_entry_is_never_withdrawn(self):
        mine = row(9, raidrun.UPPER_SPIRE, "queued", 0, "discord:someone")
        self.assertIsNone(spirerun.withdrawal([mine], "short", 99999999))

    def test_the_statement_can_only_touch_a_queued_row(self):
        self.assertIn("status = 'queued'", spirerun.WITHDRAW_SQL)

    def test_the_bridge_reads_it_behind_a_campaign_too(self):
        source = (HERE / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("spirerun.withdrawal(rows,", source)


class TheEnd(unittest.TestCase):
    def active(self):
        return row(9, raidrun.UPPER_SPIRE, "active", 0, spirerun.SOURCE)

    def test_a_clear_ends_it_and_the_family_goes_back_to_its_queue(self):
        move = spirerun.ending([self.active()], True, 60)
        self.assertEqual(move.finish, 9)
        self.assertTrue(move.quest)

    def test_the_ceiling_ends_it(self):
        move = spirerun.ending([self.active()], False, spirerun.CEILING_SECONDS)
        self.assertEqual(move.finish, 9)

    def test_under_the_ceiling_it_stands(self):
        self.assertIsNone(
            spirerun.ending([self.active()], False, spirerun.CEILING_SECONDS - 1)
        )

    def test_an_operators_order_is_left_for_the_operator(self):
        mine = row(9, raidrun.UPPER_SPIRE, "active", 0, "discord:someone")
        self.assertIsNone(spirerun.ending([mine], True, 99999))

    def test_a_queued_entry_is_not_ended(self):
        waiting = row(9, raidrun.UPPER_SPIRE, "queued", 0, spirerun.SOURCE)
        self.assertIsNone(spirerun.ending([waiting], True, 99999))


class TheVocabulary(unittest.TestCase):
    def test_the_keyword_is_the_modules_and_fits_the_seat_table(self):
        self.assertEqual(jobs.raid_job("ubrs"), "raid:ubrs")
        self.assertLessEqual(len(raidrun.UPPER_SPIRE), 20)

    def test_a_person_can_say_it(self):
        for said in ("ubrs", "UBRS", "Upper Blackrock Spire", "upper spire"):
            self.assertEqual(campaignqueue.keyword_for(said), raidrun.UPPER_SPIRE)

    def test_the_floor_is_the_upper_spires_own(self):
        rows = [{"name": "Head", "level": 55}]
        self.assertIn("below level 56", raidrun.refusal("ubrs", 1, rows))

    def test_the_planner_can_never_choose_it(self):
        self.assertNotIn(raidrun.UPPER_SPIRE, jobs.PORTAL_KEYWORDS)

    def test_the_raid_page_stops_saying_a_key_opens_the_door(self):
        self.assertNotIn("Seal", preraid.CLOSED[preraid.UPPER_SPIRE])


class TheBridgeWiring(unittest.TestCase):
    def test_the_pass_runs_after_the_planner_and_before_the_step(self):
        source = (HERE / "bridge.py").read_text(encoding="utf-8")
        planner = source.index("await self._plan_campaigns(pending, fams)")
        spire = source.index('getattr(self, "_spire_pass", None)')
        step = source.index("await self._campaign_queue_family_once(key, rows")
        self.assertLess(planner, spire)
        self.assertLess(spire, step)

    def test_the_raid_writer_seats_the_ten_and_not_forty(self):
        source = (HERE / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("spirerun.lineup(members, list(names))", source)

    def test_the_family_at_the_floor_is_written_once_with_the_modules_source(self):
        source = (HERE / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("cur.execute(spirerun.ORDER_SQL,", source)


class OppositeFactions(unittest.TestCase):
    def test_a_combined_run_across_factions_is_refused(self):
        human = [{"name": "A", "level": 60, "race": 1, "map_id": 0}]
        orc = [{"name": "B", "level": 60, "race": 2, "map_id": 1}]
        plan = campaignqueue.combined_plan(
            "A", "B", (campaignqueue.Entry("ubrs", 1),), human, orc
        )
        self.assertIn("opposite factions", plan.refusal)
        self.assertEqual(plan.entries, ())


if __name__ == "__main__":
    unittest.main()
