"""partystatus.py: what each family member is doing, beside their name (infra#3334).

Pure module, no MySQL and no game client - same seam as agenda.py, whose rows
this reads through agenda's own public functions.

Three classes here are NOT pure and say so. The precedence between the five
locally observed states has to run inside a WoW client, because the facts only
exist there, so it is written twice: once as partystatus.PRECEDENCE and once as
LOCAL_RULES in PartyStatus.lua. A claim nobody checks is how the two would come
to disagree about which of "away" and "fighting" wins, so the Lua is asserted
against as source text, the way test_jobs.py holds mod_overseer.cpp and
test_frames.py holds map_server.py.
"""
import datetime
import pathlib
import re
import unittest

import partystatus

ROOT = pathlib.Path(__file__).resolve().parents[3]
ADDON = ROOT / "hosts/srv-unraid-gpu/wow-addons/PartyStatus"
HERE = pathlib.Path(__file__).resolve().parent.parent

NOW = datetime.datetime(2026, 9, 5, 12, 0, 0)


def _member(name, **kw):
    row = {"name": name, "enabled": 1, "lead": 0, "job": "quest",
           "travel_npc": "", "drive_quest": 0, "learn_skill": 0}
    row.update(kw)
    return row


def _moved(minutes):
    return [{"kind": "quest_complete",
             "last_seen": NOW - datetime.timedelta(minutes=minutes)}]


class WhatTheClientDecidesForItself(unittest.TestCase):
    """decide() with no pushed state at all - the degraded case, which is the
    only case until something carries the line."""

    def test_a_disconnected_member_is_offline_whatever_else_is_true(self):
        got = partystatus.decide({"connected": False, "dead": True,
                                  "combat": True, "visible": False,
                                  "in_range": False})
        self.assertEqual(got["code"], partystatus.OFFLINE)

    def test_dead_outranks_every_distance_and_combat_fact(self):
        got = partystatus.decide({"dead": True, "visible": False,
                                  "combat": True, "in_range": False})
        self.assertEqual(got["code"], partystatus.DEAD)

    def test_out_of_sight_outranks_combat(self):
        """The one place this disagrees with watchwall, on purpose.

        A member the client cannot see is the drift this addon exists to
        catch, and a drifted member is nearly always fighting something. Combat
        first would hide the alarming state behind the ordinary one.
        """
        got = partystatus.decide({"visible": False, "combat": True})
        self.assertEqual(got["code"], partystatus.AWAY)

    def test_combat_outranks_merely_being_out_of_spell_range(self):
        got = partystatus.decide({"combat": True, "in_range": False})
        self.assertEqual(got["code"], partystatus.FIGHTING)

    def test_out_of_spell_range_is_the_last_local_word(self):
        got = partystatus.decide({"in_range": False})
        self.assertEqual(got["code"], partystatus.APART)

    def test_an_unremarkable_member_with_no_push_says_nothing(self):
        """Silence, not a cheerful default.

        From inside a client, a member working quietly beside the party and a
        member nobody is driving are the same picture. Only one is a problem,
        so neither gets a word until something says which it is.
        """
        got = partystatus.decide({})
        self.assertEqual(got, {"code": "", "label": ""})

    def test_facts_that_were_never_gathered_raise_no_alarms(self):
        """An empty dict is a caller that asked nothing, not five faults."""
        self.assertEqual(partystatus.decide({})["code"], "")

    def test_every_local_code_has_a_word_for_a_viewer(self):
        for code in partystatus.PRECEDENCE:
            self.assertIn(code, partystatus.LOCAL_LABELS, code)


class WhatThePushAddsAndWhatItCannotOverride(unittest.TestCase):

    def test_a_pushed_state_fills_the_silence(self):
        got = partystatus.decide({}, {"code": partystatus.TASK,
                                      "label": "quest"})
        self.assertEqual(got, {"code": partystatus.TASK, "label": "quest"})

    def test_an_observed_death_beats_a_recorded_job(self):
        """The push is a database snapshot seconds old; the corpse is now."""
        got = partystatus.decide({"dead": True}, {"code": partystatus.TASK,
                                                 "label": "quest"})
        self.assertEqual(got["code"], partystatus.DEAD)

    def test_a_local_code_arriving_over_the_wire_is_not_honoured(self):
        """Only the five pushed codes may fill the gap.

        A sender that started claiming "dead" would be reporting a fact the
        client can see better, from a snapshot that is older.
        """
        got = partystatus.decide({}, {"code": partystatus.DEAD,
                                      "label": "dead"})
        self.assertEqual(got["code"], "")

    def test_a_long_pushed_label_is_cut_to_what_fits(self):
        got = partystatus.decide({}, {"code": partystatus.TASK,
                                      "label": "x" * 40})
        self.assertEqual(len(got["label"]), partystatus.MAX_LABEL_CHARS)


class TheWireSurvivesTheColumn(unittest.TestCase):
    """overseer_command.command is VARCHAR(255) and MySQL truncates silently."""

    def test_a_line_round_trips(self):
        members = [{"name": "Grug", "code": partystatus.TASK, "label": "quest"},
                   {"name": "Ugga", "code": partystatus.TRAVEL,
                    "label": "walking"}]
        self.assertEqual(partystatus.parse(partystatus.line(members)), members)

    def test_a_whole_roster_of_five_fits_in_one_command(self):
        members = [{"name": n, "code": partystatus.DUNGEON, "label": "dungeon"}
                   for n in ("Grug", "Ugga", "Grog", "Bork", "Og")]
        self.assertLessEqual(len(partystatus.line(members)),
                             partystatus.MAX_LINE_CHARS)

    def test_a_separator_inside_a_label_cannot_shift_the_line(self):
        """A stray tab would silently move every later name onto the wrong
        state, which is worse than losing the label."""
        line = partystatus.line([
            {"name": "Grug", "code": partystatus.TASK, "label": "a\tb"},
            {"name": "Ugga", "code": partystatus.IDLE, "label": "idle"}])
        got = partystatus.parse(line)
        self.assertEqual([m["name"] for m in got], ["Grug", "Ugga"])
        self.assertEqual(got[0]["label"], "a b")

    def test_members_that_would_overflow_are_dropped_whole(self):
        members = [{"name": "Name%02d" % i, "code": partystatus.TASK,
                    "label": "guild business"} for i in range(40)]
        line = partystatus.line(members)
        self.assertLessEqual(len(line), partystatus.MAX_LINE_CHARS)
        got = partystatus.parse(line)
        self.assertLess(len(got), len(members))
        self.assertEqual(got, [{"name": m["name"], "code": m["code"],
                                "label": m["label"]} for m in members[:len(got)]])

    def test_somebody_elses_addon_traffic_is_not_ours(self):
        self.assertIsNone(partystatus.parse("MBOT\tGET~ROSTER"))

    def test_a_person_talking_is_not_ours(self):
        self.assertIsNone(partystatus.parse("OVSR is a funny word"))

    def test_a_version_this_build_does_not_know_is_refused(self):
        self.assertIsNone(partystatus.parse("OVSR\t9\tGrug\ttask\tquest"))

    def test_an_empty_roster_is_a_different_answer_from_not_ours(self):
        """[] blanks the labels; None leaves whatever is showing alone."""
        self.assertEqual(partystatus.parse(partystatus.line([])), [])

    def test_a_truncated_tail_drops_rather_than_guesses(self):
        line = partystatus.line([
            {"name": "Grug", "code": partystatus.TASK, "label": "quest"}])
        got = partystatus.parse(line + "\tUgga\ttravel")
        self.assertEqual([m["name"] for m in got], ["Grug"])

    def test_a_code_nobody_defined_is_skipped(self):
        got = partystatus.parse("OVSR\t1\tGrug\tinventing\tsomething")
        self.assertEqual(got, [])


class WhatThePushSays(unittest.TestCase):
    """build_push, branch by branch, in the order it decides them."""

    def push(self, roster, runs=(), events=()):
        return partystatus.build_push(list(roster), list(runs), list(events),
                                      now=NOW)

    def codes(self, payload):
        return {m["name"]: m["code"] for m in payload["members"]}

    def test_a_family_nobody_enabled_produces_nobody(self):
        got = self.push([_member("Grug", enabled=0)])
        self.assertEqual(got["members"], [])
        self.assertEqual(got["commands"], [])

    def test_the_ordinary_case_is_on_task_named_by_the_job(self):
        got = self.push([_member("Grug", lead=1, job="farm")])
        self.assertEqual(got["members"],
                         [{"name": "Grug", "code": partystatus.TASK,
                           "label": "farm"}])

    def test_a_blank_job_column_means_the_default_the_module_means(self):
        got = self.push([_member("Grug", lead=1, job="")])
        self.assertEqual(got["members"][0]["label"], "quest")

    def test_a_qualified_dungeon_job_is_said_without_its_keyword(self):
        """mod_overseer.cpp's IsDungeonJob accepts `dungeon:deadmines`, which
        jobs.MODES has never had a vocabulary for. Spending the whole label on
        a keyword would say nothing a viewer needs beside a name."""
        got = self.push([_member("Grug", lead=1, job="dungeon:shadowfang")])
        self.assertEqual(got["members"][0]["label"], "dungeon")

    def test_a_travel_aim_is_said_as_walking(self):
        got = self.push([_member("Grug", lead=1),
                         _member("Ugga", travel_npc="innkeeper")])
        self.assertEqual(self.codes(got),
                         {"Grug": partystatus.TASK, "Ugga": partystatus.TRAVEL})

    def test_an_active_run_outranks_the_errands_it_holds(self):
        """The coordinator parks escorted members with travel aims that stay
        set while they stand still. Reading those as errands would report five
        people running errands in the middle of a clear."""
        got = self.push(
            [_member("Grug", lead=1, travel_npc="trigger:1234"),
             _member("Ugga", travel_npc="at:36:1,2,3")],
            runs=[{"state": "active", "map_id": 36, "members": "",
                   "started_at": NOW}])
        self.assertEqual(set(self.codes(got).values()), {partystatus.DUNGEON})

    def test_a_run_names_only_its_stamped_members_once_it_has_any(self):
        got = self.push(
            [_member("Grug", lead=1), _member("Ugga")],
            runs=[{"state": "active", "map_id": 36, "members": "Grug",
                   "started_at": NOW}])
        self.assertEqual(self.codes(got),
                         {"Grug": partystatus.DUNGEON, "Ugga": partystatus.TASK})

    def test_an_ended_run_is_not_a_run(self):
        got = self.push([_member("Grug", lead=1)],
                        runs=[{"state": "ended", "map_id": 36, "members": "Grug",
                               "started_at": NOW}])
        self.assertEqual(self.codes(got), {"Grug": partystatus.TASK})

    def test_a_stalled_family_is_stalled_even_inside_a_live_run(self):
        """The reason stalled outranks everything: a run whose row still reads
        active and a job that is still set are exactly what a stuck family
        looks like from the tables."""
        got = self.push(
            [_member("Grug", lead=1)],
            runs=[{"state": "active", "map_id": 36, "members": "Grug",
                   "started_at": NOW}],
            events=_moved(90))
        self.assertEqual(self.codes(got), {"Grug": partystatus.STALLED})

    def test_a_family_that_moved_recently_is_not_stalled(self):
        got = self.push([_member("Grug", lead=1)], events=_moved(2))
        self.assertEqual(self.codes(got), {"Grug": partystatus.TASK})

    def test_a_world_with_no_event_feed_at_all_is_not_stalled(self):
        """agenda.stalled's rule, inherited rather than re-decided: unknown is
        not stalled, or a realm predating overseer_event cries wolf forever."""
        got = self.push([_member("Grug", lead=1)], events=[])
        self.assertEqual(self.codes(got), {"Grug": partystatus.TASK})

    def test_deaths_do_not_count_as_the_family_moving(self):
        """MOVEMENT_KINDS excludes death, so a wipe loop still reads stalled."""
        got = self.push(
            [_member("Grug", lead=1)],
            events=[{"kind": "death", "last_seen": NOW},
                    {"kind": "level_up",
                     "last_seen": NOW - datetime.timedelta(minutes=90)}])
        self.assertEqual(self.codes(got), {"Grug": partystatus.STALLED})

    def test_a_disabled_row_is_not_in_the_line_at_all(self):
        got = self.push([_member("Grug", lead=1), _member("Ugga", enabled=0)])
        self.assertEqual([m["name"] for m in got["members"]], ["Grug"])

    def test_every_code_it_emits_is_one_the_addon_can_colour(self):
        got = self.push([_member("Grug", lead=1, travel_npc="trainer"),
                         _member("Ugga")])
        for member in got["members"]:
            self.assertIn(member["code"], partystatus.PUSHED, member)

    def test_the_line_it_emits_parses_back_to_the_members_it_named(self):
        got = self.push([_member("Grug", lead=1), _member("Ugga")])
        self.assertEqual(partystatus.parse(got["line"]), got["members"])


class TheCommandRowsAreOnesDoChatAccepts(unittest.TestCase):

    def test_one_row_spoken_by_the_leader_reaches_all_five(self):
        """DoChat builds the party packet itself and broadcasts it to the
        group, so one row is one delivery to every session in it."""
        rows = partystatus.commands("OVSR\t1\tGrug\ttask\tquest", "Grug")
        self.assertEqual(rows, [{"target_name": "Grug",
                                 "command": "OVSR\t1\tGrug\ttask\tquest",
                                 "kind": "chat", "channel": "party"}])

    def test_no_leader_means_no_rows_rather_than_a_row_that_will_fail(self):
        """DoChat answers "not in a group" and marks the row an error, so
        enqueueing anyway fills the queue with failures."""
        self.assertEqual(partystatus.commands("OVSR\t1", None), [])

    def test_nothing_to_say_sends_nothing(self):
        self.assertEqual(partystatus.commands("", "Grug"), [])

    def test_the_payload_is_tab_separated_so_the_relay_already_skips_it(self):
        """relay.is_addon_traffic treats any C0 byte as machine traffic and
        keeps the row out of Discord and out of the thought store. That is why
        this needs no change there, and it stops being true the moment the
        separator becomes printable."""
        import relay
        rows = partystatus.commands(
            partystatus.line([{"name": "Grug", "code": partystatus.TASK,
                               "label": "quest"}]), "Grug")
        self.assertTrue(relay.is_addon_traffic(rows[0]["command"]))


class TheAddonMirrorsTheModule(unittest.TestCase):
    """PartyStatus.lua runs in a game client, so it is asserted as source text.

    The precedence between the five local facts cannot be moved into Python -
    the facts only exist inside a running client - so the guard is that the two
    lists are compared here and the suite fails when they drift.
    """

    @classmethod
    def setUpClass(cls):
        cls.lua = (ADDON / "PartyStatus.lua").read_text()
        cls.toc = (ADDON / "PartyStatus.toc").read_text()

    def rules(self):
        block = self.lua[self.lua.index("local LOCAL_RULES = {"):]
        block = block[:block.index("\n}")]
        return re.findall(r'\{ code = "(\w+)",\s+label = "([^"]*)"', block)

    def test_the_addon_asks_the_local_facts_in_the_modules_order(self):
        self.assertEqual([code for code, _ in self.rules()],
                         list(partystatus.PRECEDENCE))

    def test_the_addon_says_the_words_the_module_chose(self):
        self.assertEqual({code: label for code, label in self.rules()},
                         partystatus.LOCAL_LABELS)

    def test_every_state_has_a_colour_so_none_renders_black_on_black(self):
        block = self.lua[self.lua.index("local COLOUR = {"):]
        block = block[:block.index("\n}")]
        coloured = set(re.findall(r"^\s+(\w+)\s+= \{", block, re.M))
        self.assertEqual(coloured, set(partystatus.CODES))

    def test_the_addon_and_the_module_agree_about_the_wire(self):
        self.assertIn('local PREFIX = "%s"' % partystatus.PREFIX, self.lua)
        self.assertIn('local VERSION = "%s"' % partystatus.VERSION, self.lua)
        self.assertIn(r'local SEP = "\t"', self.lua)

    def test_the_addon_expires_a_push_on_the_modules_clock(self):
        """A sender that dies must take the labels with it, not leave "on
        task" under a character who stopped an hour ago."""
        self.assertIn("local PUSH_STALE_SECONDS = %d"
                      % partystatus.PUSH_STALE_SECONDS, self.lua)

    def test_the_addon_reads_both_routes(self):
        """CHAT_MSG_ADDON is the route worth having; a party-chat line is the
        one that works with no change to the worldserver at all."""
        self.assertIn('driver:RegisterEvent("CHAT_MSG_ADDON")', self.lua)
        self.assertIn('ChatFrame_AddMessageEventFilter("CHAT_MSG_PARTY"',
                      self.lua)

    def test_the_party_chat_route_hides_its_own_traffic(self):
        """Returning true removes the line from every chat frame. Without it
        the stream shows machine text in party chat all day."""
        block = self.lua[self.lua.index("local function chatFilter"):]
        block = block[:block.index("\nend")]
        self.assertIn("return true", block)

    def test_nothing_is_drawn_inside_the_party_frame(self):
        """The whole 128x53 of a party member frame is spoken for, and so is
        the band under it where the pet frame hangs. The label is anchored to
        the frame's TOPRIGHT and offset clear of it - see the file header for
        the measurements this protects."""
        self.assertIn(
            'frame:SetPoint("LEFT", parent, "TOPRIGHT", CLEAR_X, NAME_Y)',
            self.lua)

    def test_the_clearance_puts_it_past_the_party_background_panel(self):
        """PartyMemberBackground is 134 wide from x=-5, so it ends at x=129
        and the frame's own right edge is x=128. Anything under 1 would sit on
        the panel when the operator turns it on."""
        found = re.search(r"local CLEAR_X = (\d+)", self.lua)
        self.assertIsNotNone(found)
        self.assertGreaterEqual(int(found.group(1)), 1)

    def test_the_label_never_takes_a_click_off_the_world(self):
        self.assertIn("frame:EnableMouse(false)", self.lua)

    def test_an_edit_to_the_lua_alone_still_runs_this_suite(self):
        """Otherwise the mirror guard is decoration on exactly the change it
        exists to catch: the addon lives outside production/scripts, so its
        path has to be named in the workflow that runs this file."""
        flow = (ROOT.parent / ".github" / "workflows"
                / "check.python-units.yml").read_text()
        self.assertEqual(
            flow.count("production/hosts/srv-unraid-gpu/wow-addons/**"), 2,
            "both the push and the pull_request filters must name it")

    def test_the_toc_is_one_a_335a_client_will_load(self):
        self.assertIn("## Interface: 30300", self.toc)
        self.assertIn("PartyStatus.lua", self.toc)


class TheEndpointIsWired(unittest.TestCase):
    """map_server imports pymysql, so it is asserted against its source."""

    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text()

    def test_the_route_reaches_the_handler(self):
        get = self.server[self.server.index("GET_ROUTES = {"):]
        get = get[:get.index("}")]
        self.assertIn('"/api/party-status": _party_status', get)

    def test_it_reads_no_table_the_agenda_banner_does_not_already_read(self):
        """No new fetch and no new SQL: the party frames and the web page must
        not be able to reach different conclusions about the same family."""
        block = self.server[self.server.index("def _party_status"):]
        block = block[:block.index("\n    def ", 10)]
        self.assertIn("_fetch_agenda()", block)
        self.assertNotIn("SELECT", block)

    def test_the_module_ships_in_the_image(self):
        """The bridge image is built from the shared tarball by name, so a
        module left out of this list imports fine in the suite and crashes the
        map server on the next roll."""
        dockerfile = (HERE.parent.parent / "docker" / "wow-overseer"
                      / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("_shared/partystatus.py", dockerfile)



class TheSenderIsAPipeWithASchedule(unittest.TestCase):
    """tools/push_party_status.py carries the line and chooses none of it."""

    @classmethod
    def setUpClass(cls):
        cls.tool = (HERE / "tools" / "push_party_status.py").read_text()

    def test_it_pushes_more_often_than_the_addon_forgets(self):
        """A sender slower than PUSH_STALE_SECONDS blanks every label between
        its own pushes, which reads exactly like a sender that has died."""
        found = re.search(r"DEFAULT_EVERY = (\d+)", self.tool)
        self.assertIsNotNone(found)
        self.assertLess(int(found.group(1)), partystatus.PUSH_STALE_SECONDS)

    def test_it_names_no_state_of_its_own(self):
        """Every word a viewer reads is chosen in this module. A sender that
        composed its own labels would be a second vocabulary nothing tests."""
        for code in partystatus.PUSHED:
            self.assertNotIn('"%s"' % code, self.tool, code)

    def test_it_stamps_a_source_so_its_rows_are_separable(self):
        self.assertIn("source", self.tool)

    def test_a_world_it_cannot_reach_does_not_end_the_loop(self):
        """The endpoint answers 503 while MySQL is rolling. Exiting there would
        need a restart by hand every time, while the addon has already gone
        quiet on its own."""
        self.assertIn("continue", self.tool)


if __name__ == "__main__":
    unittest.main()
