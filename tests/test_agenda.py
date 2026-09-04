"""The current-goal banner's decision table (infra#3205).

Every case here is a state the live realm has actually been in, or one the
schema plainly allows and nothing prevents. The point of the suite is that
`agenda` is a PURE module - rows in, one sentence out - so each of these is a
dict literal rather than a database, and the ones that matter most (a split
party, a stall, a schema that predates half the columns) are the ones that are
hardest to arrange in a live world on purpose.
"""
import unittest
from datetime import datetime, timedelta

import agenda
import jobs

NOW = datetime(2026, 9, 3, 2, 0, 0)
FAMILY = ("Og", "Bork", "Grog", "Grug", "Ugga")


def roster(overrides=None) -> list:
    """The five, all enabled, Og leading, everybody questing.

    `overrides` is a {name: {column: value}} map merged onto the default row,
    so a test says only the thing it is about.
    """
    overrides = overrides or {}
    rows = []
    for name in FAMILY:
        row = {
            "name": name,
            "enabled": 1,
            "lead": 1 if name == "Og" else 0,
            "job": "quest",
            "drive_quest": 101,
            "travel_npc": "",
            "learn_skill": 0,
            "dungeon_runs_wanted": 30,
            "dungeon_runs_done": 0,
        }
        row.update(overrides.get(name, {}))
        rows.append(row)
    return rows


def build(roster_rows=None, run_rows=(), instance_rows=(), goal_rows=(),
          trade_rows=(), event_rows=None, quest_titles=None, now=NOW):
    """build_agenda with the boring arguments already filled in."""
    if roster_rows is None:
        roster_rows = roster()
    if event_rows is None:
        # Something happened a minute ago, so nothing is stalled by default.
        event_rows = [{"kind": "quest_accept",
                       "last_seen": now - timedelta(minutes=1)}]
    if quest_titles is None:
        quest_titles = {101: "The Totem of Infliction", 246: "Assessing the Threat"}
    return agenda.build_agenda(
        list(roster_rows), list(run_rows), list(instance_rows),
        list(goal_rows), list(trade_rows), list(event_rows), quest_titles,
        now=now,
    )


def run_row(**overrides) -> dict:
    row = {
        "id": 1, "leader_name": "Og", "map_id": 36, "state": "active",
        "started_at": NOW - timedelta(minutes=20), "ended_at": None,
        "ended_reason": "", "campaign_id": 1, "run_number": 2,
        "outcome": "", "members": "Bork,Grog,Grug,Og,Ugga",
    }
    row.update(overrides)
    return row


class TheOrdinaryCase(unittest.TestCase):
    def test_a_family_all_on_one_quest_is_named_by_that_quest(self):
        out = build()
        self.assertEqual(out["activity"], agenda.QUEST)
        self.assertEqual(out["headline"], "Questing: The Totem of Infliction")

    def test_an_unnamed_quest_falls_back_to_its_id(self):
        """A quest whose title acore_world did not hand back is still a real
        aim; printing nothing would look like no aim at all."""
        out = build(quest_titles={})
        self.assertEqual(out["headline"], "Questing: quest 101")

    def test_nobody_aimed_says_so_rather_than_inventing_a_quest(self):
        out = build(roster({n: {"drive_quest": 0} for n in FAMILY}))
        self.assertIn("picking their own quests", out["headline"])

    def test_an_empty_roster_is_idle_not_an_exception(self):
        out = build([])
        self.assertEqual(out["activity"], agenda.IDLE)

    def test_a_disabled_character_is_not_part_of_the_family(self):
        """A row nothing drives must not invent a disagreement."""
        out = build(roster({"Ugga": {"enabled": 0, "job": "farm"}}))
        self.assertIsNone(out["job_split"])
        self.assertNotIn("Ugga", out["roster"])


class ASplitPartyIsNeverAveraged(unittest.TestCase):
    """The failure Evan keeps catching by eye, and the one rule this page must
    not break: four against one is reported as four against one."""

    def test_a_job_split_takes_the_headline(self):
        out = build(roster({"Ugga": {"job": "dungeon"}}))
        self.assertEqual(out["activity"], agenda.SPLIT)
        self.assertIn("split", out["headline"])
        self.assertIn("4 on quest", out["headline"])
        self.assertIn("1 on dungeon", out["headline"])

    def test_a_split_names_who_is_where(self):
        out = build(roster({"Ugga": {"job": "dungeon"}}))
        self.assertIn("Ugga", " ".join(out["detail"]))

    def test_the_majority_never_silently_wins(self):
        out = build(roster({"Ugga": {"job": "dungeon"}}))
        self.assertNotEqual(out["headline"], "Questing: The Totem of Infliction")

    def test_a_blank_job_reads_as_the_column_default_not_as_a_split(self):
        """mod_overseer.cpp's LoadJobs treats '' and 'quest' identically, so
        a roster carrying both is NOT a disagreement."""
        out = build(roster({"Ugga": {"job": ""}}))
        self.assertIsNone(out["job_split"])
        self.assertEqual(out["activity"], agenda.QUEST)

    def test_differing_quest_aims_are_reported_under_a_shared_job(self):
        out = build(roster({"Ugga": {"drive_quest": 246}}))
        self.assertIsNotNone(out["quest_split"])
        self.assertIn("Assessing the Threat", " ".join(out["detail"]))

    def test_no_aim_at_all_is_a_side_of_a_quest_split(self):
        """Four aimed and one aimed at nothing is a real disagreement; a
        version of this that skipped blanks called that family unanimous."""
        out = build(roster({"Ugga": {"drive_quest": 0}}))
        self.assertIsNotNone(out["quest_split"])
        self.assertIn("no aim", " ".join(out["detail"]))


class ARunInProgress(unittest.TestCase):
    def test_the_headline_carries_the_run_and_the_bosses(self):
        out = build(run_rows=[run_row()],
                    instance_rows=[{"id": 3, "map": 36,
                                    "completedEncounters": 15,
                                    "resettime": 1788654119}])
        self.assertEqual(out["activity"], agenda.DUNGEON)
        self.assertEqual(
            out["headline"],
            "Running The Deadmines, run 2 of 30, 4 of 7 bosses down")

    def test_a_cleared_lockout_is_called_what_it_is(self):
        """127 is every Deadmines bit. A run into an instance that is already
        empty is `outcome = 'emptied'`, and dressing it up as a finished
        dungeon is the one thing this line must not do."""
        out = build(run_rows=[run_row()],
                    instance_rows=[{"id": 3, "map": 36,
                                    "completedEncounters": 127,
                                    "resettime": 1}])
        self.assertIn("7 of 7 bosses down", out["headline"])
        self.assertIn("already cleared", " ".join(out["detail"]))

    def test_an_unknown_map_gets_no_denominator_rather_than_a_wrong_one(self):
        out = build(run_rows=[run_row(map_id=43)],
                    instance_rows=[{"id": 9, "map": 43,
                                    "completedEncounters": 3, "resettime": 1}])
        self.assertIn("2 bosses down", out["headline"])
        self.assertNotIn(" of ", out["headline"].split("bosses")[0]
                         .split("run 2 of 30")[-1])

    def test_an_unstamped_run_falls_back_to_the_campaign_counter(self):
        """run_number is stamped at the Clearing transition, so a run that has
        not got that far has 0 - and `done + 1` is what the module prints."""
        out = build(roster({"Og": {"dungeon_runs_done": 4}}),
                    run_rows=[run_row(run_number=0)])
        self.assertIn("run 5 of 30", out["headline"])

    def test_a_run_outranks_a_job_split_but_still_reports_it(self):
        """A run actually under way is what is happening whatever the rows
        say - but the disagreement does not get to disappear."""
        out = build(roster({"Ugga": {"job": "quest"}, "Og": {"job": "dungeon"}}),
                    run_rows=[run_row()])
        self.assertEqual(out["activity"], agenda.DUNGEON)
        self.assertIn("does not agree on the job", " ".join(out["detail"]))

    def test_an_ended_run_is_not_a_run_in_progress(self):
        out = build(run_rows=[run_row(state="ended", ended_at=NOW)])
        self.assertNotEqual(out["activity"], agenda.DUNGEON)

    def test_members_not_inside_are_named(self):
        out = build(run_rows=[run_row(members="Og,Grug")])
        self.assertIn("Not inside", " ".join(out["detail"]))
        self.assertIn("Bork", " ".join(out["detail"]))

    def test_a_run_with_no_members_yet_says_less_rather_than_lying(self):
        out = build(run_rows=[run_row(members="")])
        self.assertIn("not stamped into the run yet", " ".join(out["detail"]))


class TheCampaignCounter(unittest.TestCase):
    def test_the_counter_is_read_off_the_leader(self):
        """mod_overseer.cpp's LoadCampaignCap reads the leader's row and no
        other, and prints `done + 1` as the run number."""
        out = build(roster({"Og": {"dungeon_runs_done": 7}}))
        self.assertEqual(out["campaign"]["done"], 7)
        self.assertEqual(out["campaign"]["recorded_by"], "Og")

    def test_a_higher_count_elsewhere_is_reported_not_maximised_away(self):
        """Observed live on 2026-09-03: Grug carried 2 from campaign 1 while Og
        wore the crown with 0. Taking the max would have hidden the fact that
        the crown moved and the counter did not."""
        rows = {n: {"job": "dungeon"} for n in FAMILY}
        rows["Grug"] = {"job": "dungeon", "dungeon_runs_done": 2}
        out = build(roster(rows))
        self.assertEqual(out["campaign"]["done"], 0)
        self.assertEqual(out["campaign"]["disagrees"], ["Grug"])
        self.assertIn("crown moved", " ".join(out["detail"]))

    def test_a_finished_campaign_says_finished(self):
        rows = {n: {"job": "dungeon"} for n in FAMILY}
        rows["Og"] = {"job": "dungeon", "dungeon_runs_done": 30}
        out = build(roster(rows))
        self.assertEqual(out["activity"], agenda.DUNGEON)
        self.assertIn("finished", out["headline"])
        self.assertTrue(out["campaign"]["over"])

    def test_a_wanted_of_zero_stops_the_campaign_outright(self):
        """The coordinator asks `done >= wanted` BEFORE starting a run, so a
        wanted of 0 means no run ever begins."""
        rows = {n: {"job": "dungeon"} for n in FAMILY}
        rows["Og"] = {"job": "dungeon", "dungeon_runs_wanted": 0}
        out = build(roster(rows))
        self.assertTrue(out["campaign"]["over"])

    def test_between_runs_names_why_the_last_one_ended(self):
        rows = {n: {"job": "dungeon"} for n in FAMILY}
        out = build(roster(rows),
                    run_rows=[run_row(state="ended", outcome="wipe",
                                      ended_at=NOW - timedelta(minutes=5))])
        self.assertEqual(out["activity"], agenda.DUNGEON)
        self.assertIn("Between dungeon runs", out["headline"])
        self.assertIn("the party wiped", " ".join(out["detail"]))

    def test_every_writable_outcome_has_a_sentence(self):
        """'left', 'wipe', 'emptied' and 'reset_failed' are the four
        mod_overseer.cpp can write, plus '' from the cold-heartbeat sweep.
        'complete' and 'stalled' are named in the migration as deliberately
        never written, so they are not here."""
        for outcome in ("left", "wipe", "emptied", "reset_failed", ""):
            self.assertIn(outcome, agenda.OUTCOMES)
        self.assertNotIn("complete", agenda.OUTCOMES)
        self.assertNotIn("stalled", agenda.OUTCOMES)


class Errands(unittest.TestCase):
    TRADE = [{"character_name": "Og", "verb": "learn", "skill_name": "tailoring",
              "reason": "Og is assigned tailoring because the mage wears cloth.",
              "status": "planned",
              "decided_at": datetime(2026, 9, 3, 1, 32, 55)}]

    def test_the_leader_walking_is_the_familys_goal(self):
        out = build(roster({"Og": {"travel_npc": "profession trainer",
                                   "learn_skill": 197}}),
                    trade_rows=self.TRADE)
        self.assertEqual(out["activity"], agenda.TRAVEL)
        self.assertEqual(
            out["headline"],
            "Walking Og to the nearest profession trainer to learn Tailoring")

    def test_a_non_leader_walking_is_a_side_trip_not_the_headline(self):
        """mod-overseer gates the RPG drive to the traveller, so the other
        four follow the LEADER. One of them wandering off does not change what
        the family is doing."""
        out = build(roster({"Grug": {"travel_npc": "profession trainer",
                                     "learn_skill": 164}}))
        self.assertEqual(out["activity"], agenda.QUEST)
        self.assertIn("Meanwhile Grug is walking", " ".join(out["detail"]))

    def test_the_councils_reason_is_quoted(self):
        out = build(roster({"Og": {"travel_npc": "profession trainer",
                                   "learn_skill": 197}}),
                    trade_rows=self.TRADE)
        self.assertIn("the mage wears cloth", " ".join(out["detail"]))
        self.assertEqual(out["orders"]["kind"], "errand")

    def test_a_long_reason_is_cut_on_a_word(self):
        long = "word " * 200
        out = build(roster({"Og": {"travel_npc": "profession trainer",
                                   "learn_skill": 197}}),
                    trade_rows=[dict(self.TRADE[0], reason=long)])
        quoted = out["detail"][0]
        self.assertLessEqual(len(quoted), agenda.REASON_CHARS + 3)
        self.assertTrue(quoted.endswith("..."))

    def test_a_leading_errand_outranks_a_standing_discord_order(self):
        """The live state on 2026-09-03: Grug under a Discord quest order
        while Og walks to a tailoring trainer. Crediting the trainer headline
        to the Discord order would put the badge on the wrong sentence."""
        out = build(roster({"Og": {"travel_npc": "profession trainer",
                                   "learn_skill": 197}}),
                    goal_rows=DiscordOrders.GOAL, trade_rows=self.TRADE)
        self.assertEqual(out["activity"], agenda.TRAVEL)
        self.assertEqual(out["orders"]["kind"], "errand")
        self.assertIsNone(out["orders"]["channel_id"])

    def test_a_side_errand_leaves_the_discord_order_credited(self):
        """The headline really is about the quest there, so the order that
        produced it is the one to name."""
        out = build(roster({"Grug": {"travel_npc": "profession trainer",
                                     "learn_skill": 164}}),
                    goal_rows=DiscordOrders.GOAL,
                    trade_rows=[dict(self.TRADE[0], character_name="Grug",
                                     skill_name="blacksmithing")])
        self.assertEqual(out["activity"], agenda.QUEST)
        self.assertEqual(out["orders"]["kind"], "discord")

    def test_a_run_outranks_an_errand(self):
        """The coordinator parks escorted members with a travel aim and they
        deliberately keep it while standing still. Reading those as errands
        would report five people running errands mid-clear."""
        out = build(roster({"Og": {"travel_npc": "trigger:4247"}}),
                    run_rows=[run_row()])
        self.assertEqual(out["activity"], agenda.DUNGEON)


class TravelTargetsTheModuleAccepts(unittest.TestCase):
    """ResolveTravelTarget takes four forms. travel.describe knows two of
    them and answers 'nowhere' for the others, which would put that word on
    the banner for a character who is very definitely walking somewhere."""

    def test_a_coordinate_aim_is_a_place_not_nowhere(self):
        said = agenda.describe_aim("at:0:-10414.6,1047.07,44.5459")
        self.assertNotIn("nowhere", said)
        self.assertIn("spot", said)

    def test_a_doorway_aim_is_a_doorway_not_nowhere(self):
        said = agenda.describe_aim("trigger:4247")
        self.assertNotIn("nowhere", said)

    def test_a_role_keyword_still_goes_through_travel(self):
        self.assertEqual(agenda.describe_aim("profession trainer"),
                         "the nearest profession trainer")

    def test_a_bare_creature_entry_still_goes_through_travel(self):
        self.assertEqual(agenda.describe_aim("5511"), "creature 5511")

    def test_an_empty_aim_is_nowhere(self):
        self.assertEqual(agenda.describe_aim(""), "nowhere")


class Staleness(unittest.TestCase):
    def test_a_quiet_family_is_called_stalled(self):
        out = build(event_rows=[{"kind": "quest_accept",
                                 "last_seen": NOW - timedelta(minutes=45)}])
        self.assertTrue(out["stalled"])
        self.assertEqual(out["moved_seconds"], 45 * 60)

    def test_a_busy_family_is_not(self):
        out = build(event_rows=[{"kind": "level_up",
                                 "last_seen": NOW - timedelta(minutes=3)}])
        self.assertFalse(out["stalled"])

    def test_dying_on_a_loop_is_not_progress(self):
        """A party wiping every few minutes writes a death row every few
        minutes. Counting those would make this agree that a stuck family was
        busy, which is the whole failure it exists to catch."""
        out = build(event_rows=[
            {"kind": "quest_accept", "last_seen": NOW - timedelta(hours=2)},
            {"kind": "death", "last_seen": NOW - timedelta(seconds=30)},
        ])
        self.assertTrue(out["stalled"])

    def test_a_stalled_run_says_the_heartbeat_proves_nothing(self):
        """quadseven/mod-overseer#171 from outside: the run still reads active
        because last_progress_at is touched for everyone standing inside."""
        out = build(run_rows=[run_row()],
                    event_rows=[{"kind": "item_equip",
                                 "last_seen": NOW - timedelta(hours=1)}])
        self.assertTrue(out["stalled"])
        self.assertIn("mod-overseer#171", " ".join(out["detail"]))

    def test_no_events_at_all_is_unknown_and_not_stalled(self):
        """A realm predating overseer_event hands in nothing. Shouting
        'stalled' at that is crying wolf about a missing table."""
        out = build(event_rows=[])
        self.assertFalse(out["stalled"])
        self.assertIsNone(out["moved_seconds"])

    def test_clock_skew_never_prints_a_negative_age(self):
        out = build(event_rows=[{"kind": "level_up",
                                 "last_seen": NOW + timedelta(seconds=3)}])
        self.assertEqual(out["moved_seconds"], 0)


class TheRunProgressColumnIsNotAProgressSignal(unittest.TestCase):
    """The single most important thing this module gets right.

    mod_overseer.cpp touches overseer_dungeon_run.last_progress_at for EVERY
    roster character seen alive on the instance map, every engagement poll,
    before any other decision - its own comment says it "answers 'when was
    somebody last seen in here'". A party standing still keeps it warm
    forever. Feeding it to a stall detector reproduces #171 inside the page
    built to reveal it.
    """

    def test_last_movement_ignores_the_run_table_entirely(self):
        import inspect
        source = inspect.getsource(agenda.last_movement)
        body = source.split('"""')[2]
        self.assertNotIn("last_progress_at", body)

    def test_a_warm_heartbeat_does_not_clear_a_stall(self):
        out = build(run_rows=[run_row(last_progress_at=NOW)],
                    event_rows=[{"kind": "quest_complete",
                                 "last_seen": NOW - timedelta(hours=3)}])
        self.assertTrue(out["stalled"])


class ASchemaThatPredatesTheColumns(unittest.TestCase):
    """infra#2846 and infra#3172, from the reading end. The adapter's 1146 and
    1054 guards turn a missing table or column into an empty list or an absent
    key; this is the half of that contract that has to say less rather than
    raise."""

    def test_a_roster_with_only_its_oldest_columns_still_answers(self):
        rows = [{"name": n, "enabled": 1, "lead": 1 if n == "Og" else 0}
                for n in FAMILY]
        out = build(rows)
        self.assertEqual(out["activity"], agenda.QUEST)
        self.assertEqual(out["campaign"]["done"], 0)

    def test_every_input_empty_is_a_sentence_not_an_exception(self):
        out = agenda.build_agenda([], [], [], [], [], [], {}, now=NOW)
        self.assertEqual(out["activity"], agenda.IDLE)
        self.assertTrue(out["headline"])

    def test_a_run_row_without_the_accounting_columns_still_reads(self):
        thin = {"id": 1, "leader_name": "Og", "map_id": 36, "state": "active",
                "started_at": NOW - timedelta(minutes=5), "ended_at": None,
                "ended_reason": ""}
        out = build(run_rows=[thin])
        self.assertEqual(out["activity"], agenda.DUNGEON)
        self.assertIn("The Deadmines", out["headline"])


class DiscordOrders(unittest.TestCase):
    GOAL = [{"character_name": "Grug", "kind": "quest", "skill_name": None,
             "target": 0, "status": "active", "channel_id": "154305710",
             "last_report": "-15/4", "quest_id": 101,
             "created_at": datetime(2026, 9, 2, 22, 8, 44)}]

    def test_an_active_order_is_credited_to_discord(self):
        out = build(goal_rows=self.GOAL)
        self.assertEqual(out["orders"]["kind"], "discord")
        self.assertEqual(out["orders"]["who"], "Grug")
        self.assertEqual(out["orders"]["channel_id"], "154305710")

    def test_the_objective_count_is_un_negated_for_a_person(self):
        """goals.py stores a quest goal's progress as -objectives_left so
        every kind moves the same direction. A banner printing -15 would be
        showing the reader an implementation detail."""
        out = build(goal_rows=self.GOAL)
        self.assertEqual(out["orders"]["objectives_left"], 15)
        self.assertIn("15 objectives left", " ".join(out["detail"]))

    def test_a_cancelled_order_is_not_an_order(self):
        out = build(goal_rows=[dict(self.GOAL[0], status="cancelled")])
        self.assertIsNone(out["orders"])

    def test_the_private_timestamp_never_reaches_the_page(self):
        out = build(goal_rows=self.GOAL)
        self.assertNotIn("_at", out["orders"])


class OtherJobs(unittest.TestCase):
    def test_an_unbuilt_mode_says_it_is_unbuilt(self):
        out = build(roster({n: {"job": "farm"} for n in FAMILY}))
        self.assertEqual(out["activity"], agenda.JOB)
        self.assertIn("farm", out["headline"])
        self.assertIn("Nothing is wired behind that mode yet",
                      " ".join(out["detail"]))

    def test_dungeon_is_never_described_as_unbuilt(self):
        """It is the sole trigger for the whole run coordinator. Saying it is
        not built would be the page contradicting the thing it is watching."""
        out = build(roster({n: {"job": "dungeon"} for n in FAMILY}))
        self.assertNotIn("Nothing is wired behind", " ".join(out["detail"]))
        self.assertIn("dungeon", jobs.IMPLEMENTED)

    def test_every_mode_the_roster_accepts_produces_a_headline(self):
        for mode in jobs.MODES:
            out = build(roster({n: {"job": mode} for n in FAMILY}))
            self.assertTrue(out["headline"], mode)


class TheEncounterDenominator(unittest.TestCase):
    def test_deadmines_is_seven_and_not_the_boss_list_length(self):
        """acore_world.instance_encounters holds seven rows for the Deadmines
        credit creatures (161-167), which is why a cleared instance reads 127.
        achievements.DUNGEONS lists EIGHT creatures because Sneed's Shredder
        shares Sneed's encounter and holds no bit of its own - deriving the
        denominator from that list would print 'of 8' for a dungeon that can
        only reach 7."""
        import achievements
        self.assertEqual(agenda.ENCOUNTERS[36], 7)
        self.assertEqual(len(achievements.DUNGEONS[36]["bosses"]), 8)

    def test_a_full_mask_matches_the_denominator(self):
        self.assertEqual(agenda.bosses_down(127), agenda.ENCOUNTERS[36])

    def test_an_empty_mask_is_zero_not_an_error(self):
        self.assertEqual(agenda.bosses_down(None), 0)
        self.assertEqual(agenda.bosses_down(0), 0)


class WhatTheColumnsSayIsSet(unittest.TestCase):
    """`standing_orders` answers a different question from the banner's.

    The banner answers "what are they doing", which is a race between five
    tables. This answers "what is SET", which is four columns and the three
    judgements that read them - and a surface offering to change those columns
    needs the second question. It must not become a second opinion: the leader,
    the enabled filter and the blank-job default are all reused from the
    functions the banner already uses.
    """

    def test_the_job_reported_is_the_leaders(self):
        """mod_overseer.cpp looks the LEADER's name up in LoadJobs() and every
        branch that starts, stands down or repeats a run compares that one
        string. A family-wide job is family-wide by construction."""
        rows = roster({"Og": {"job": "dungeon"}, "Grug": {"job": "farm"}})
        self.assertEqual(agenda.standing_orders(rows)["job"], "dungeon")
        self.assertEqual(agenda.standing_orders(rows)["leader"], "Og")

    def test_a_blank_job_reads_as_the_column_default(self):
        """LoadJobs selects `job <> '' AND job <> 'quest'` and treats absence
        from the result as questing, so an empty string means the same thing
        the module means by it."""
        rows = roster({"Og": {"job": ""}})
        self.assertEqual(agenda.standing_orders(rows)["job"], jobs.DEFAULT)

    def test_a_disagreement_is_reported_and_never_averaged(self):
        rows = roster({"Grug": {"job": "farm"}})
        state = agenda.standing_orders(rows)
        self.assertEqual(state["job"], "quest")
        self.assertIsNotNone(state["job_split"])

    def test_a_disabled_row_is_nobody(self):
        """Nothing aims it, so counting its columns would invent a
        disagreement out of a character nobody is playing."""
        rows = roster({"Bork": {"enabled": 0, "job": "farm"}})
        state = agenda.standing_orders(rows)
        self.assertNotIn("Bork", state["roster"])
        self.assertIsNone(state["job_split"])

    def test_the_counter_is_the_one_campaign_already_decided(self):
        rows = roster({"Og": {"dungeon_runs_done": 1},
                       "Grug": {"dungeon_runs_done": 5}})
        self.assertEqual(agenda.standing_orders(rows)["campaign"],
                         agenda.campaign(agenda._enabled(rows)))

    def test_the_travel_column_comes_back_per_character(self):
        rows = roster({"Grug": {"travel_npc": "profession trainer"}})
        aimed = {t["name"]: t["target"] for t in agenda.standing_orders(rows)["travel"]}
        self.assertEqual(aimed["Grug"], "profession trainer")
        self.assertEqual(aimed["Og"], "")

    def test_an_empty_roster_answers_rather_than_raising(self):
        """A realm whose worldserver predates the table hands in []."""
        state = agenda.standing_orders([])
        self.assertIsNone(state["leader"])
        self.assertEqual(state["job"], jobs.DEFAULT)
        self.assertEqual(state["roster"], [])

    def test_a_schema_without_the_job_column_still_answers(self):
        """The adapter drops to a narrower SELECT on a degraded schema, so
        these dicts genuinely arrive without the column."""
        rows = [{"name": n, "enabled": 1, "lead": 1 if n == "Og" else 0}
                for n in FAMILY]
        state = agenda.standing_orders(rows)
        self.assertEqual(state["job"], jobs.DEFAULT)
        self.assertEqual(state["campaign"]["done"], 0)


if __name__ == "__main__":
    unittest.main()
