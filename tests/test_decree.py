"""What the decree console is allowed to claim (infra#2597).

The console is the only WRITE surface in the redesign, and the two things it
gets wrong are not cosmetic. Both have a history in this repo:

  * A JOB MODE THAT IS NOT WIRED does not do nothing. It stands the quest
    drive DOWN and puts nothing in its place, so the family stops questing and
    starts standing still. A person who sets FARM without being told that
    watches an empty stream and goes looking for a broken encoder.

  * `delivered` IS NOT SUCCESS. It is written the instant the module accepts
    the row and says nothing whatsoever about the character. Two engineers
    read it as "applied", in writing, all night, while the same command
    changed nothing on the same character twice (rows 4049 and 4184; the whole
    story is in tests/test_command_outcome.py).

Every test here is a dict literal against a pure module: no database, no
browser. The page contract is tests/test_decree_tab.py.
"""
import pathlib
import unittest
from datetime import datetime
from unittest import mock

import agenda
import bonds
import chat
import core
import decree
import jobs
import professions
import travel

HERE = pathlib.Path(__file__).resolve().parent.parent
FAMILY = ("Og", "Bork", "Grog", "Grug", "Ugga")


def roster(overrides=None) -> list:
    """The five, all enabled, Og leading, everybody questing."""
    overrides = overrides or {}
    rows = []
    for name in FAMILY:
        row = {
            "name": name,
            "enabled": 1,
            "lead": 1 if name == "Og" else 0,
            "job": "quest",
            "drive_quest": 0,
            "travel_npc": "",
            "learn_skill": 0,
            "dungeon_runs_wanted": 30,
            "dungeon_runs_done": 0,
        }
        row.update(overrides.get(name, {}))
        rows.append(row)
    return rows


def command(**overrides) -> dict:
    row = {
        "id": 4184,
        "target_name": "Ugga",
        "command": "nc -new rpg",
        "kind": "bot",
        "status": "delivered",
        "detail": "",
        "created_at": None,
    }
    row.update(overrides)
    return row


class AnUnwiredJobStandsTheQuestDriveDown(unittest.TestCase):
    """The first of the two honesty mechanisms, and the one that decides
    whether a person can trust anything else on the console."""

    def test_every_mode_the_roster_accepts_is_offered(self):
        self.assertEqual([c["mode"] for c in decree.job_chips()], list(jobs.MODES))

    def test_which_modes_are_wired_is_read_and_never_restated(self):
        """The list of what works lives in jobs.IMPLEMENTED. If this module
        kept its own copy, wiring a mode in mod-overseer would light up the
        game and leave the console lying about it."""
        wired = {c["mode"] for c in decree.job_chips() if c["wired"]}
        self.assertEqual(wired, set(jobs.IMPLEMENTED))

    def test_wiring_a_mode_moves_the_console_with_no_edit_here(self):
        """The guard that proves the line above. Widening IMPLEMENTED must
        flip the chip, the dot and the sentence together."""
        widened = frozenset(jobs.IMPLEMENTED | {"farm"})
        with mock.patch.object(jobs, "IMPLEMENTED", widened):
            farm = next(c for c in decree.job_chips() if c["mode"] == "farm")
            self.assertTrue(farm["wired"])
            self.assertEqual(farm["state"], decree.WIRED)
            self.assertNotIn("NOT BUILT YET", farm["says"])
            self.assertFalse(decree.job_choice("farm")["stands_down"])

    def test_an_unwired_mode_says_it_stands_the_drive_down(self):
        choice = decree.job_choice("farm")
        self.assertTrue(choice["stands_down"])
        self.assertIn("stands the quest drive down", choice["says"])
        self.assertIn("nothing positive replaces it", choice["says"])

    def test_the_sentence_is_the_modules_own_and_not_a_second_copy(self):
        """The bridge answers a job order in the overseer's channel with
        jobs.describe. A console that phrased the warning in its own words
        would be a copy free to soften on its own."""
        for mode in jobs.MODES:
            self.assertEqual(decree.job_choice(mode)["says"], jobs.describe(mode))

    def test_a_wired_mode_does_not_carry_the_warning(self):
        for mode in sorted(jobs.IMPLEMENTED):
            choice = decree.job_choice(mode)
            self.assertFalse(choice["stands_down"])
            self.assertNotIn("NOT BUILT YET", choice["says"])

    def test_the_dot_is_a_state_and_not_a_colour(self):
        """Which pigment says "this works" is the stylesheet's decision. A
        module handing the page a hex would be deciding it twice."""
        states = {c["state"] for c in decree.job_chips()}
        self.assertEqual(states, {decree.WIRED, decree.UNWIRED})
        for chip in decree.job_chips():
            self.assertNotIn("#", chip["state"])

    def test_something_that_is_not_a_mode_is_an_ordinary_answer(self):
        """None rather than an exception, the same contract jobs.resolve
        keeps: this is fed by a surface people type at."""
        self.assertIsNone(decree.job_choice("nonsense"))
        self.assertIsNone(decree.job_choice(""))

    def test_an_alias_resolves_the_way_the_channel_resolves_it(self):
        self.assertEqual(decree.job_choice("farming time")["mode"], "farm")

    def test_the_unwired_list_is_counted_and_not_typed(self):
        self.assertEqual(
            set(decree.unwired_modes()), set(jobs.MODES) - set(jobs.IMPLEMENTED)
        )


class DeliveredIsNotSuccess(unittest.TestCase):
    """The second honesty mechanism. `delivered` fooled two engineers in
    writing; on a console it must not look like a tick."""

    def test_the_console_is_stricter_than_the_bridge_on_purpose(self):
        """core is right to bucket `delivered` as not-an-error. A console is
        not a bucket, and this asserts the DIFFERENCE rather than the
        agreement, so nobody can quietly align them."""
        self.assertIn("delivered", core.COMMAND_SUCCESS_STATUSES)
        self.assertNotIn("delivered", decree.SUCCESS_STATUSES)
        self.assertEqual(decree.SUCCESS_STATUSES, ("applied",))

    def test_delivered_is_not_a_success(self):
        self.assertFalse(decree.is_success("delivered"))
        self.assertFalse(decree.outcome(command(status="delivered"))["success"])

    def test_applied_is_the_only_success(self):
        for status in decree.OUTCOMES:
            self.assertEqual(decree.is_success(status), status == "applied", status)

    def test_delivered_and_applied_never_read_the_same(self):
        handed = decree.outcome_of("delivered")
        held = decree.outcome_of("applied")
        self.assertNotEqual(handed.tone, held.tone)
        self.assertNotEqual(handed.word, held.word)

    def test_delivered_is_not_drawn_in_the_verified_tone(self):
        self.assertNotEqual(decree.outcome_of("delivered").tone, decree.VERIFIED)
        self.assertEqual(decree.outcome_of("delivered").tone, decree.UNVERIFIED)

    def test_delivered_says_that_nothing_was_read_back(self):
        read = decree.outcome_of("delivered")
        self.assertIn("NOTHING WAS READ BACK", read.means)
        self.assertIn("nothing", read.evidence.lower())

    def test_applied_says_the_read_back_agreed(self):
        self.assertIn("Read back", decree.outcome_of("applied").means)


class TheCanonicalUnchangedRow(unittest.TestCase):
    """overseer_command row 4184: `nc -new rpg` to Ugga, accepted, and her
    strategy list did not move. It read `delivered` at the time, which is the
    whole reason the status exists."""

    def test_it_is_reported_and_is_not_an_error(self):
        line = decree.outcome(command(id=4184, status="unchanged"))
        self.assertEqual(line["tone"], decree.INERT)
        self.assertNotEqual(line["tone"], decree.FAILED)
        self.assertFalse(line["success"])

    def test_it_says_nothing_happened_rather_than_nothing_worked(self):
        line = decree.outcome(command(status="unchanged"))
        self.assertIn("Nothing failed and nothing happened", line["means"])

    def test_it_names_the_row_and_the_evidence_on_it(self):
        """The row id is the whole handle on the diagnosis; `result` carries
        the live lists the verdict was made against."""
        line = decree.outcome(command(id=4184, status="unchanged"))
        self.assertEqual(line["id"], 4184)
        self.assertIn("`result`", line["evidence"])

    def test_every_line_carries_its_row_id_not_only_the_interesting_ones(self):
        for status in decree.OUTCOMES:
            self.assertEqual(decree.outcome(command(id=7, status=status))["id"], 7)


class EveryStatusTheQueueCanHold(unittest.TestCase):

    def test_every_terminal_status_the_bridge_knows_can_be_drawn(self):
        for status in core.COMMAND_TERMINAL_STATUSES:
            self.assertIn(status, decree.OUTCOMES, status)

    def test_the_in_flight_states_are_drawn_too(self):
        """A console shows a row the moment it is written, which is before any
        worldserver has touched it. A queued row that fell through to the
        unknown branch would read as a fault on every send."""
        for status in ("pending", "claimed", "verifying"):
            self.assertIn(status, decree.OUTCOMES, status)
            self.assertEqual(decree.outcome_of(status).tone, decree.WAITING)

    def test_an_unknown_future_status_is_named_rather_than_swallowed(self):
        """The worldserver image and this one deploy separately, so a status
        from a newer module is an ordinary deploy window. Same rule
        core.report_outcomes keeps at the other end of the same table."""
        read = decree.outcome_of("something-new")
        self.assertIn("something-new", read.word)
        self.assertEqual(read.tone, decree.UNSEEN)
        self.assertFalse(decree.is_success("something-new"))

    def test_an_error_carries_the_detail_the_row_wrote(self):
        line = decree.outcome(command(status="error", detail="target has no bot AI"))
        self.assertEqual(line["tone"], decree.FAILED)
        self.assertEqual(line["detail"], "target has no bot AI")

    def test_the_newest_row_is_first(self):
        rows = [command(id=1), command(id=9), command(id=5)]
        self.assertEqual([o["id"] for o in decree.outcomes(rows)], [9, 5, 1])


class TheCampaignCounter(unittest.TestCase):
    """agenda.campaign already decides who is authoritative and whether the
    roster disagrees. This adds the sentences and must not add a second
    opinion."""

    def test_the_leaders_row_is_the_one_reported(self):
        rows = roster({"Og": {"dungeon_runs_done": 1},
                       "Grug": {"dungeon_runs_done": 7}})
        view = decree.campaign_view(agenda.standing_orders(rows)["campaign"])
        self.assertEqual(view["done"], 1)
        self.assertEqual(view["recorded_by"], "Og")
        self.assertIn("Og", view["line"])

    def test_a_higher_count_elsewhere_is_said_out_loud(self):
        """The crown moves and the counter does not travel with it. Silently
        taking the maximum would hide a campaign that restarts every time
        leadership changes, behind a number that merely looks right."""
        rows = roster({"Og": {"dungeon_runs_done": 0},
                       "Grug": {"dungeon_runs_done": 2}})
        view = decree.campaign_view(agenda.standing_orders(rows)["campaign"])
        self.assertEqual(view["disagrees"], ["Grug"])
        self.assertIn("Grug", view["warning"])
        self.assertIn("crown", view["warning"])
        self.assertIn("governs", view["warning"])

    def test_an_agreeing_roster_raises_no_warning(self):
        view = decree.campaign_view(agenda.standing_orders(roster())["campaign"])
        self.assertEqual(view["warning"], "")
        self.assertEqual(view["disagrees"], [])

    def test_zero_stops_the_campaign_outright(self):
        """Not "0 runs left". The coordinator asks whether done is at least
        wanted BEFORE it starts a run, so a wanted of 0 means no run ever
        begins - which is a different thing from a campaign that finished."""
        rows = roster({n: {"dungeon_runs_wanted": 0} for n in FAMILY})
        view = decree.campaign_view(agenda.standing_orders(rows)["campaign"])
        self.assertTrue(view["stopped"])
        self.assertEqual(view["wanted"], decree.CAMPAIGN_STOP)
        self.assertIn("stops the campaign outright", view["means"])

    def test_a_finished_campaign_says_it_is_over_rather_than_stopped(self):
        rows = roster({n: {"dungeon_runs_done": 30} for n in FAMILY})
        view = decree.campaign_view(agenda.standing_orders(rows)["campaign"])
        self.assertTrue(view["over"])
        self.assertFalse(view["stopped"])
        self.assertIn("over", view["means"])

    def test_runs_left_is_counted_and_reads_as_english(self):
        rows = roster({n: {"dungeon_runs_done": 29} for n in FAMILY})
        view = decree.campaign_view(agenda.standing_orders(rows)["campaign"])
        self.assertIn("1 run left", view["means"])

    def test_an_empty_roster_says_so_rather_than_reporting_zeroes(self):
        view = decree.campaign_view(agenda.standing_orders([])["campaign"])
        self.assertIsNone(view["recorded_by"])
        self.assertIn("no campaign", view["line"])


class TravelIsNotTransaction(unittest.TestCase):

    def test_every_role_the_module_knows_is_offered_and_no_others(self):
        """The keywords are already duplicated in C++ and checked line for
        line by test_travel_npc. A third copy in a web page is the one nobody
        would think to check."""
        self.assertEqual([c["role"] for c in decree.travel_chips()],
                         list(travel.ROLES))

    def test_the_caveat_is_the_one_the_module_states(self):
        self.assertIn("Travel, not transaction", decree.TRAVEL_CAVEAT)
        self.assertIn("stands in front of it", decree.TRAVEL_CAVEAT)

    def test_the_modules_own_docstring_still_says_it(self):
        """The caveat is a claim about travel.py. If that module ever starts
        transacting, this test fails and the sentence gets revisited rather
        than quietly becoming false."""
        source = (HERE / "travel.py").read_text(encoding="utf-8")
        self.assertIn("TRAVEL, NOT TRANSACTION", source)

    def test_picking_a_role_repeats_the_caveat_where_it_is_read(self):
        for chip in decree.travel_chips():
            self.assertIn("does not make them use it", chip["says"])

    def test_the_unbuilt_list_is_not_empty(self):
        """An empty list would say "everything works", which is the failure
        shape this whole epic is about. professions.BLOCKERS keeps the same
        rule for the same reason."""
        self.assertTrue(decree.TRAVEL_UNBUILT)

    def test_only_characters_actually_aimed_somewhere_are_listed(self):
        rows = [{"name": "Og", "target": "profession trainer"},
                {"name": "Grug", "target": ""}]
        aimed = decree.travel_now(rows)
        self.assertEqual([a["name"] for a in aimed], ["Og"])
        self.assertIn("profession trainer", aimed[0]["says"])

    def test_nobody_aimed_anywhere_is_said_rather_than_left_blank(self):
        """An empty list under a heading reads as a panel that failed."""
        self.assertIn("Nobody is aimed anywhere", decree.travel_line(()))

    def test_a_target_the_module_would_not_accept_is_not_reported(self):
        self.assertEqual(decree.travel_now([{"name": "Og", "target": "pub"}]), ())


class WhatThisConsoleMayWrite(unittest.TestCase):
    """All four cards reach the world now (infra#3345), and every one of them
    says which road it takes and what it writes. A control that silently does
    nothing is the failure this epic is named after; so is one that writes
    without saying where."""

    def test_every_card_can_be_sent_and_names_its_road(self):
        """`writes` is the road, and can_send is derived from it - so a card
        cannot become sendable on screen without naming what it writes."""
        roads = {s.key: s.writes for s in decree.SECTIONS}
        self.assertEqual(roads, {
            decree.JOB: decree.COMMAND,
            decree.CAMPAIGN: decree.ROSTER,
            decree.TRAVEL: decree.ROSTER,
            decree.WILL: decree.CHAT,
        })
        for section in decree.SECTIONS:
            self.assertTrue(decree.can_send(section.key), section.key)

    def test_the_will_still_goes_through_the_chat_path(self):
        """Not a new endpoint for it. The page already had a chat POST and the
        decree travels it, one character at a time - and plan_order refuses
        the will rather than growing a second grammar for it."""
        will = next(s for s in decree.SECTIONS if s.key == decree.WILL)
        self.assertEqual(will.writes, decree.CHAT)
        order = decree.plan_order({"section": decree.WILL}, roster())
        self.assertEqual(order.refusal, decree.ORDER_REFUSALS["will"])

    def test_every_card_names_the_table_or_column_it_writes(self):
        """The candour the refusals used to carry, now that the buttons work.
        An operator who has to press one to find out what it writes is being
        asked to experiment on a live realm."""
        named = {decree.JOB: "overseer_command",
                 decree.CAMPAIGN: "overseer_roster.dungeon_runs_wanted",
                 decree.TRAVEL: "overseer_roster.travel_npc"}
        for section in decree.SECTIONS:
            self.assertTrue(section.does, section.key)
            if section.key in named:
                self.assertIn(named[section.key], section.does, section.key)

    def test_a_card_that_could_not_send_would_still_say_how_it_is_done(self):
        """The refusal machinery is kept, not deleted: a control that loses
        its write path must go back to a reason and a way forward rather than
        to a dead button."""
        for section in decree.SECTIONS:
            if not decree.can_send(section.key):
                self.assertTrue(section.why_not, section.key)
                self.assertTrue(section.instead, section.key)

    def test_the_console_does_not_aim_through_aim_statements(self):
        """The travel order deliberately does not aim through
        travel.aim_statements: its second statement clears everybody who was
        not named, which is right for a council deciding where the whole
        family stands and wrong for a console aiming one person. Standing the
        others down is its own order here.

        This docstring used to claim aim_statements "is STILL called by
        nothing". That stopped being true when `trainjob.statements` landed,
        and the stale claim is part of why its roster-wide clear went
        unaudited (infra#4195). The ASSERTION below is unchanged and still
        correct - these four files are not callers - it is only the reason
        that needed correcting."""
        for name in ("bridge.py", "map_server.py", "council.py", "decree.py"):
            source = (HERE / name).read_text(encoding="utf-8")
            self.assertNotIn("travel.aim_statements(", source, name)

    def test_the_train_drive_is_the_bridge_side_aimer(self):
        """infra#3338 gave the `train` job drive its own statements on the
        bridge side. That is a different symbol from travel.aim_statements,
        which the test above pins as still having no callers, so both claims
        are true at once and this keeps the train drive's coverage rather
        than losing it to the merge.
        """
        bridge = (HERE / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("trainjob.statements", bridge)


class TheWill(unittest.TestCase):

    def test_the_family_answers_oldest_first(self):
        """bonds.speaking_order is the family table's own answer to who comes
        first. mod-overseer delivers in row order, so the order these are
        written in is the order they are read in."""
        rows = ["Bork", "Grug", "Ugga", "Og", "Grog"]
        self.assertEqual(list(decree.will_audience(decree.WILL_FAMILY, rows)),
                         bonds.speaking_order(rows))

    def test_one_of_them_is_exactly_one_and_only_from_the_roster(self):
        rows = ["Grug", "Ugga"]
        self.assertEqual(decree.will_audience(decree.WILL_ONE, rows, "Ugga"), ("Ugga",))
        self.assertEqual(decree.will_audience(decree.WILL_ONE, rows, "Thrall"), ())

    def test_the_two_targets_that_cannot_be_reached_say_why(self):
        for target in decree.WILL_TARGETS:
            if target["reachable"]:
                self.assertEqual(target["why_not"], "")
            else:
                self.assertTrue(target["why_not"], target["id"])

    def test_the_wide_targets_are_the_unreachable_ones(self):
        """The chat path takes ONE character name. Widening an order is
        fanout.py's job and it runs on the bridge."""
        unreachable = {t["id"] for t in decree.WILL_TARGETS if not t["reachable"]}
        self.assertEqual(unreachable, {decree.WILL_GUILD, decree.WILL_FACTION})

    def test_one_target_and_only_one_needs_a_character_named(self):
        needs = [t["id"] for t in decree.WILL_TARGETS if t["needs_name"]]
        self.assertEqual(needs, [decree.WILL_ONE])

    def test_the_limit_comes_from_the_module_that_enforces_it(self):
        """A number typed into an HTML attribute is a second limit free to
        drift from the one the server actually applies."""
        self.assertEqual(decree.WILL_MAX_CHARS, chat.MAX_MESSAGE)

    def test_the_submit_says_what_it_does(self):
        self.assertEqual(decree.WILL_SUBMIT, "Let the family overhear it")

    def test_there_is_a_refusal_for_every_way_it_can_be_wrong(self):
        for key in ("unchosen", "empty", "unnamed", "nobody"):
            self.assertTrue(decree.WILL_REFUSALS[key], key)

    def test_no_preset_pretends_to_be_a_command(self):
        """What the words become is the inner voice's decision. A preset
        shaped like a command line would be pretending otherwise."""
        from voice import is_raw_command
        for preset in decree.PRESETS:
            self.assertFalse(is_raw_command(preset), preset)


class WhatIsStoppingThem(unittest.TestCase):

    def test_the_job_count_is_counted_and_not_typed(self):
        entry = decree.backlog()[-1]
        self.assertIn("%d of %d" % (len(decree.unwired_modes()), len(jobs.MODES)),
                      entry["what"])

    def test_wiring_a_mode_moves_the_count(self):
        """The guard for the line above: the sentence must be derived, so a
        mode wired in mod-overseer changes the backlog without anybody
        remembering to edit prose."""
        before = decree.backlog()[-1]["what"]
        widened = frozenset(jobs.IMPLEMENTED | {"farm"})
        with mock.patch.object(jobs, "IMPLEMENTED", widened):
            after = decree.backlog()[-1]["what"]
        self.assertNotEqual(before, after)
        # Derived, not typed: wiring a real mode changes how many are left,
        # and this test must not need an edit each time one is (it did, once,
        # when `train` was wired).
        self.assertIn("%d of %d" % (len(jobs.MODES) - len(widened), len(jobs.MODES)),
                      after)

    def test_the_crafter_is_read_off_the_family_plan(self):
        """Who is owed the family's first trade is a fact professions.py
        holds. Typing a name here would be a second answer."""
        first = professions.OPEN_ORDER[0]
        owed = next(n for n in professions.ROSTER if first in professions.assigned(n))
        entry = next(b for b in decree.backlog() if first in b["what"])
        self.assertIn(owed, entry["what"])

    def test_it_says_nothing_crafts(self):
        self.assertTrue(any("crafts" in b["what"] for b in decree.backlog()))

    def test_every_entry_carries_a_reason(self):
        for entry in decree.backlog():
            self.assertTrue(entry["what"])
            self.assertTrue(entry["why"])


class TheWholePayload(unittest.TestCase):

    def test_an_empty_world_builds_a_thinner_console_and_never_raises(self):
        """A realm whose worldserver predates a table hands in [] for it. The
        same contract every other endpoint on this page keeps."""
        payload = decree.build_console([], [])
        self.assertEqual(payload["outcomes"], [])
        self.assertIn("Nobody is on the roster", payload["job"]["line"])
        self.assertEqual(payload["will"]["audience"], [])

    def test_the_standing_job_is_the_leaders(self):
        rows = roster({"Og": {"job": "dungeon"}, "Grug": {"job": "farm"}})
        payload = decree.build_console(rows, [])
        self.assertEqual(payload["job"]["standing"], "dungeon")
        self.assertEqual(payload["job"]["leader"], "Og")

    def test_a_family_that_disagrees_about_the_job_is_reported(self):
        rows = roster({"Grug": {"job": "farm"}})
        payload = decree.build_console(rows, [])
        self.assertIsNotNone(payload["job"]["split"])
        self.assertIn("farm", payload["job"]["split_line"])

    def test_a_split_free_family_reports_no_split(self):
        payload = decree.build_console(roster(), [])
        self.assertIsNone(payload["job"]["split"])
        self.assertEqual(payload["job"]["split_line"], "")

    def test_the_verdict_travels_on_the_row_and_not_as_a_word_to_match(self):
        """The page never compares a status string. Whether a row may be
        drawn as a success arrives already decided, on the row."""
        payload = decree.build_console([], [command(status="applied"),
                                            command(id=2, status="delivered")])
        verdicts = {o["status"]: o["success"] for o in payload["outcomes"]}
        self.assertEqual(verdicts, {"applied": True, "delivered": False})

    def test_every_card_names_its_own_section(self):
        payload = decree.build_console([], [])
        keys = {s["key"] for s in payload["sections"]}
        for card in ("job", "campaign", "travel", "will"):
            self.assertIn(payload[card]["section"], keys, card)

    def test_the_payload_is_json(self):
        import json
        json.dumps(decree.build_console(roster(), [command()]))


def two_families() -> list:
    """Grug's five and Zug's two, each with its own leader and counter."""
    rows = roster({"Og": {"lead": 0}, "Grug": {"lead": 1}})
    for row in rows:
        row["family"] = "Grug"
    for name, lead in (("Zug", 1), ("Oz", 0)):
        rows.append(dict(rows[0], name=name, lead=lead, family="Zug",
                         dungeon_runs_wanted=5))
    return rows


SENT = datetime(2026, 9, 11, 21, 29, 18)
NOW = datetime(2026, 9, 22, 17, 0, 0)


def job_row(row_id, name, status="delivered", detail="", command_="quest"):
    return command(id=row_id, target_name=name, command=command_, kind="job",
                   status=status, detail=detail, created_at=SENT,
                   source="web:overseer")


class AJobOrderIsReadBack(unittest.TestCase):
    """DoJob only ever reports `delivered`, so every job order read "NOTHING
    WAS READ BACK" forever. The column it writes is in the roster this
    console already reads, so the console checks it."""

    def test_a_job_the_column_now_carries_is_in_effect(self):
        line = decree.outcome(job_row(5, "Ugga"), {"Ugga": "quest"}, {}, NOW)
        self.assertEqual(line["word"], "in effect")
        self.assertEqual(line["tone"], decree.VERIFIED)
        self.assertTrue(line["success"])
        self.assertIn("Ugga's job reads quest now", line["verdict"])

    def test_a_later_order_is_named_as_the_reason(self):
        line = decree.outcome(job_row(5, "Ugga"), {"Ugga": "farm"},
                              {"Ugga": 9}, NOW)
        self.assertEqual(line["word"], "replaced")
        self.assertFalse(line["success"])
        self.assertIn("row 9", line["means"])

    def test_the_newest_order_that_the_column_disagrees_with_did_not_take(self):
        line = decree.outcome(job_row(5, "Ugga"), {"Ugga": "farm"},
                              {"Ugga": 5}, NOW)
        self.assertEqual(line["word"], "did not take")
        self.assertEqual(line["tone"], decree.FAILED)

    def test_a_name_with_no_roster_row_changed_nothing(self):
        line = decree.outcome(job_row(5, "Nobody"), {"Ugga": "quest"}, {}, NOW)
        self.assertEqual(line["word"], "changed nothing")
        self.assertFalse(line["success"])

    def test_no_roster_read_is_not_evidence(self):
        """A thin roster read hands in no jobs. That is "not read", so the
        row says handed over exactly as before."""
        line = decree.outcome(job_row(5, "Ugga"), {}, {}, NOW)
        self.assertEqual(line["word"], "handed over")
        self.assertFalse(line["success"])

    def test_a_bot_row_is_never_judged_against_the_job_column(self):
        line = decree.outcome(command(), {"Ugga": "nc -new rpg"}, {}, NOW)
        self.assertEqual(line["word"], "handed over")

    def test_not_online_is_said_in_plain_words(self):
        line = decree.outcome(job_row(4, "Grug", "error", "target not online"),
                              {"Grug": "quest"}, {}, NOW)
        self.assertIn("was not logged in", line["verdict"])

    def test_every_line_says_when_it_was_sent(self):
        line = decree.outcome(job_row(5, "Ugga"), {}, {}, NOW)
        self.assertEqual(line["ago"], "10 days ago")
        self.assertEqual(decree.ago(None, NOW), "at an unknown time")


class OneOrderIsOneLine(unittest.TestCase):

    def test_a_family_order_is_one_batch_with_the_exception_named(self):
        rows = [job_row(3, "Grug", "error", "target not online"),
                job_row(4, "Ugga"), job_row(5, "Og")]
        payload = decree.build_console(two_families(), rows, NOW,
                                       [{"target_name": "Ugga", "id": 4}])
        self.assertEqual(len(payload["orders"]), 1)
        batch = payload["orders"][0]
        self.assertEqual(batch["who"], "Grug's family")
        self.assertIn("in effect for 2 of 3", batch["verdict"])
        self.assertIn("Grug was not logged in", batch["verdict"])
        self.assertEqual(batch["tone"], decree.FAILED)
        self.assertEqual(batch["ago"], "10 days ago")

    def test_orders_sent_at_different_times_are_different_lines(self):
        rows = [job_row(4, "Ugga"),
                dict(job_row(5, "Og"), created_at=datetime(2026, 9, 12))]
        payload = decree.build_console(two_families(), rows, NOW)
        self.assertEqual(len(payload["orders"]), 2)


class BothFamilies(unittest.TestCase):
    """Two families, two leaders, two counters. Reading them as one printed
    "read off Grug's row" over ten characters and set the Horde's job from a
    card that described the Alliance's."""

    def test_each_family_gets_its_own_job_and_campaign(self):
        payload = decree.build_console(two_families(), [], NOW)
        fams = {f["key"]: f for f in payload["families"]}
        self.assertEqual(set(fams), {"Grug", "Zug"})
        self.assertEqual(fams["Zug"]["leader"], "Zug")
        self.assertIn("Zug's row", fams["Zug"]["job"]["line"])
        self.assertEqual(fams["Zug"]["campaign"]["wanted"], 5)
        self.assertEqual(fams["Grug"]["campaign"]["wanted"], 30)

    def test_a_job_order_without_a_family_is_refused_when_there_are_two(self):
        order = decree.plan_order({"section": decree.JOB, "mode": "quest"},
                                  two_families())
        self.assertEqual(order.refusal, decree.ORDER_REFUSALS["family"])

    def test_a_job_order_reaches_only_the_named_family(self):
        order = decree.plan_order(
            {"section": decree.JOB, "mode": "quest", "family": "Zug"},
            two_families())
        self.assertEqual({r.target_name for r in order.rows}, {"Zug", "Oz"})

    def test_a_campaign_order_reaches_only_the_named_family(self):
        order = decree.plan_order(
            {"section": decree.CAMPAIGN, "wanted": 3, "family": "Grug"},
            two_families())
        self.assertEqual({u.name for u in order.updates}, set(FAMILY))

    def test_an_unknown_family_is_refused(self):
        order = decree.plan_order(
            {"section": decree.JOB, "mode": "quest", "family": "Nope"},
            two_families())
        self.assertTrue(order.refusal)

    def test_one_family_needs_no_name(self):
        order = decree.plan_order({"section": decree.JOB, "mode": "quest"},
                                  roster())
        self.assertEqual(order.refusal, "")

    def test_travel_is_by_name_and_needs_no_family(self):
        order = decree.plan_order(
            {"section": decree.TRAVEL, "name": "Oz", "role": "vendor"},
            two_families())
        self.assertEqual(order.refusal, "")


class TheHouseRules(unittest.TestCase):

    def test_no_em_dashes(self):
        for name in ("decree.py", "tests/test_decree.py"):
            self.assertNotIn(chr(0x2014),
                             (HERE / name).read_text(encoding="utf-8"), name)

    def test_the_module_is_ascii(self):
        (HERE / "decree.py").read_text(encoding="utf-8").encode("ascii")

    def test_it_ships_in_the_image(self):
        """A new top-level module the map server imports is one forgotten
        COPY line away from a pod that crashes at start."""
        dockerfile = (HERE / "Dockerfile").resolve()
        self.assertIn("decree.py",
                      dockerfile.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
