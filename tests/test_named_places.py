"""Nothing ambiguous: every place, event and reason is named.

The run page said "Durg: Durg crossed into an unknown place." for a seat
walking into The Deadmines, "dungeon: a member asked for it" when the row
named the asker, "(spec-tank/spec-healer)" for the seats, and the Now strip
said "Walking to trigger 194" and "a spot on the map". Each fact was on a
row; these pin that the name is said.
"""

import ast
import pathlib
import re
import shutil
import unittest

import achievements
import agenda
import commandwords
import events
import guildrun
import nowstatus
import places
import raidready
from apiv2 import activity, guild
from apiv2 import run as run_api
from events import Event
from transform import Geometry

HERE = pathlib.Path(__file__).resolve().parent.parent
GEO = Geometry.load(str(HERE))
WESTFALL = (-10600.0, 1000.0)


class AnInstanceMapIsNamed(unittest.TestCase):
    def test_an_instance_map_id_resolves_to_its_name(self):
        self.assertEqual(places.map_name(36), "The Deadmines")
        self.assertEqual(places.map_name(33), "Shadowfang Keep")
        self.assertEqual(places.map_name(409), "Molten Core")

    def test_battlegrounds_arenas_and_continents_are_named_too(self):
        self.assertEqual(places.map_name(489), "Warsong Gulch")
        self.assertEqual(places.map_kind(489), places.BATTLEGROUND)
        self.assertEqual(places.map_name(559), "Nagrand Arena")
        self.assertEqual(places.map_name(0), "Eastern Kingdoms")
        self.assertTrue(places.is_instance(36))
        self.assertFalse(places.is_instance(0))

    def test_the_zone_lookup_names_the_instance_it_holds_no_rectangle_for(self):
        self.assertEqual(GEO.zone_name(36, 0.0, 0.0), "The Deadmines")
        self.assertEqual(GEO.zone_name(489, 0.0, 0.0), "Warsong Gulch")

    def test_where_a_raider_stands_names_the_instance(self):
        self.assertEqual(
            raidready._where({"map": 36, "online": 1}), "inside The Deadmines"
        )
        self.assertEqual(raidready._where({"map": None}), "position not read")

    def test_the_site_dungeon_names_agree_with_the_map_list(self):
        for map_id, name in achievements.MAP_NAMES.items():
            self.assertEqual(places.map_name(map_id), name, map_id)


class NoBuilderSaysUnknownPlace(unittest.TestCase):
    def test_no_payload_builder_emits_unknown_place(self):
        """Every string a builder can return (docstrings and comments aside)
        and every line of the app's code."""
        found = []
        for path in sorted(HERE.glob("*.py")) + sorted((HERE / "apiv2").glob("*.py")):
            for text in _strings(path):
                if "unknown place" in text:
                    found.append("%s: %s" % (path.name, text))
        for path in sorted((HERE / "app").rglob("*.js")):
            for line in path.read_text(encoding="utf-8").splitlines():
                # A quoted string the page could print; the run page's regex
                # that renames old lines is a match, not an emission.
                quoted = re.search(r"[\"'`][^\"'`]*unknown place", line)
                if quoted and not line.strip().startswith("//"):
                    found.append("%s: %s" % (path.name, line.strip()))
        self.assertEqual(found, [])

    def test_no_map_a_character_can_stand_on_reads_as_unknown(self):
        for map_id in places.MAP_NAMES:
            said = GEO.zone_name(map_id, 0.0, 0.0)
            self.assertNotIn("unknown", said, map_id)

    def test_walking_into_the_deadmines_is_narrated_by_name(self):
        prev = {"Durg": _snap("Durg", 0, 40, WESTFALL)}
        curr = {"Durg": _snap("Durg", 36, 1581, (-16.4, -383.1))}
        got = events.detect_events(prev, curr, GEO)
        self.assertEqual(len(got), 1)
        self.assertEqual(events.template_line(got[0]), "Durg entered The Deadmines.")

    def test_walking_out_names_both_ends(self):
        prev = {"Durg": _snap("Durg", 36, 1581, (-16.4, -383.1))}
        curr = {"Durg": _snap("Durg", 0, 40, WESTFALL)}
        got = events.detect_events(prev, curr, GEO)
        self.assertEqual(
            events.template_line(got[0]), "Durg left The Deadmines for Westfall."
        )
        self.assertIn("left The Deadmines for Westfall", events.describe(got[0]))

    def test_an_event_written_before_maps_still_reads(self):
        old = Event("zone_change", "Grug", {"from_zone": "A", "to_zone": "Durotar"})
        self.assertEqual(events.template_line(old), "Grug crossed into Durotar.")


def _strings(path):
    """The string constants of a module that are not docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr):
                docs.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docs
    ]


def _snap(name, map_id, zone_id, pos):
    return {
        "name": name,
        "level": 23,
        "map_id": map_id,
        "zone_id": zone_id,
        "pos_x": pos[0],
        "pos_y": pos[1],
        "health": 100,
        "in_combat": 0,
    }


class TheTravelAimIsAPlace(unittest.TestCase):
    def test_a_trigger_id_is_the_doorway_it_is(self):
        self.assertEqual(
            nowstatus.aim_words("trigger:194"), "the way out of Shadowfang Keep"
        )
        self.assertEqual(
            nowstatus.aim_words("trigger:145"), "the door of Shadowfang Keep"
        )
        self.assertEqual(places.walk_words("trigger:194"), "out of Shadowfang Keep")

    def test_coordinates_are_the_place_they_stand_in(self):
        self.assertEqual(
            nowstatus.aim_words("at:0:-3898,-597,5.4"),
            "the Menethil Harbor docks (Wetlands)",
        )
        self.assertEqual(
            nowstatus.aim_words("at:1:-443.7,-2649.1,95.8"), "Crossroads (The Barrens)"
        )
        self.assertEqual(
            nowstatus.aim_words("at:0:-11208.5,1685.34,25.76"),
            "the door of The Deadmines (Westfall)",
        )

    def test_the_walk_sentences_name_the_place(self):
        row = {
            "leader_name": "Zug",
            "current_kind": "dungeon",
            "current_owner": "dungeon run",
            "current_target": "trigger:194",
            "current_for": 20,
        }
        got = nowstatus.compose({"present": 1}, {"intent": row, "now_at": 100})
        self.assertTrue(
            got["line"].startswith(
                "Doing: Walking out of Shadowfang Keep for the dungeon run."
            ),
            got["line"],
        )
        step = nowstatus.classify(
            "town slot: town errand takes the traveller Grug for "
            "'at:0:-3898,-597,5.4'; the column was free"
        )[0]
        self.assertEqual(
            step.doing,
            "Walking to the Menethil Harbor docks (Wetlands) on a town errand",
        )
        self.assertEqual(
            agenda.describe_aim("trigger:194"), "the way out of Shadowfang Keep"
        )

    def test_a_stored_step_with_a_trigger_id_is_named_as_it_is_read(self):
        self.assertEqual(
            nowstatus.reword(
                "dungeon run took over: walking to trigger 194 for the dungeon run"
            ),
            "The dungeon run took over: walking out of Shadowfang Keep for the "
            "dungeon run",
        )

    def test_a_pace_hold_keeps_its_record_and_its_note_apart(self):
        got = nowstatus.classify(
            "pace: Zug's family: Shadowfang Keep holds (5 fought, 0 wiped (0%), "
            "0 cleared, 0 wipes in a row) (six or more empty slots: Zork 6)"
        )[0]
        self.assertEqual(
            got.waiting,
            "5 fought, 0 wiped (0%), 0 cleared, 0 wipes in a row; six or more "
            "empty slots: Zork 6",
        )


def _asked(**over):
    row = {
        "id": 507,
        "guild": "Cave",
        "band": "20-24",
        "composition": "spec-tank/spec-healer",
        "keyword": "deadmines",
        "proposer": "Durg",
        "members": "Durg:tank:warrior:23",
        "dungeon_by": "ask",
        "composition_by": "answers",
        "state": "inside",
    }
    row.update(over)
    return guildrun._run_view(row)


class TheRunCardSaysWhoAndWhichSeats(unittest.TestCase):
    def test_the_seats_are_words_not_the_learning_key(self):
        view = _asked()
        self.assertEqual(
            view["lines"][1],
            "group: the guildmates who answered yes; seats: a tank and a healer "
            "chosen by spec",
        )
        self.assertNotIn("spec-", " ".join(view["lines"]))
        self.assertEqual(
            guildrun.composition_words("spec-tank/class-healer+2help+1pug"),
            "seats: a tank chosen by spec and a healer chosen by class (not spec), "
            "plus 2 helpers above the dungeon's levels and 1 pick-up player from "
            "outside the guild",
        )
        self.assertEqual(view["band_line"], "levels 20 to 24")

    def test_the_asker_is_named_and_a_row_without_one_says_so(self):
        self.assertEqual(
            _asked()["lines"][0], "dungeon: Durg asked for it in guild chat"
        )
        bare = _asked(proposer="")["lines"][0]
        self.assertNotIn("a member", bare)
        self.assertIn("does not name who asked", bare)

    def test_both_run_reads_select_the_asker(self):
        self.assertIn("proposer", run_api._RUN_SQL)
        self.assertNotIn("proposer", run_api._RUN_SQL_THIN)
        server = (HERE / "map_server.py").read_text(encoding="utf-8")
        start = server.index("_GUILD_RUNS_SQL = (")
        self.assertIn("proposer", server[start : server.index(")", start)])


class TheActivityLogSaysWhy(unittest.TestCase):
    def test_a_refusal_that_points_at_its_result_gives_the_result_reason(self):
        said = activity.answer_words(
            "error",
            "refused: see result",
            '{"phase":"refused","why":"\'Divalicious\' is in combat"}',
        )
        self.assertEqual(said, "refused: 'Divalicious' is in combat")
        self.assertEqual(activity.answer_words("error", "refused"), "refused")
        cut = '{"outcome":"refused","reason":"character is held by another verb","sp'
        self.assertEqual(
            activity.answer_words("error", "refused: see result", cut),
            "refused: character is held by another verb",
        )

    def test_a_command_is_said_with_its_objects_named(self):
        names = {
            "creature": {10076: "High Priestess of Thaurissan"},
            "item": {3771: "Wild Hog Shank"},
            "quest": {710: "Mudsnout Blossoms"},
        }

        def say(kind, command, arg=""):
            row = {"kind": kind, "command": command, "target_arg": arg}
            return commandwords.say(row, names)

        self.assertEqual(
            say("guild", "finder-run deadmines Dunga Eggrok Bluk Brakk"),
            "Run The Deadmines through the dungeon finder: this member tanks, "
            "Dunga healing, with Eggrok, Bluk and Brakk",
        )
        self.assertEqual(
            say("job", "walk-to-spawn creature:10076 near:3"),
            "Walk to High Priestess of Thaurissan",
        )
        self.assertEqual(
            say("buy", "entry:3771 count:4 max:4000"), "Buy 4 x Wild Hog Shank"
        )
        self.assertEqual(
            say("share", "quest:710", "Bork"), "Share Mudsnout Blossoms with Bork"
        )
        self.assertEqual(
            say("bot", "nc -grind"), "Out of combat: stop grinding nearby mobs"
        )
        self.assertEqual(say("job", "cross-to-map map:0"), "Cross to Eastern Kingdoms")
        self.assertEqual(say("hearth", "use"), "Use the hearthstone")
        self.assertIn("does not hold", say("quest", "turnin quest:1473"))
        self.assertEqual(
            commandwords.wanted([{"command": "walk-to-spawn creature:10076"}]),
            {"creature": [10076]},
        )

    def test_a_blocked_class_quest_walk_names_its_creature(self):
        self.assertEqual(
            guild.walk_target("walk-to-spawn creature:7 max:3", {7: "Bodley"}),
            "walking to Bodley",
        )
        self.assertIn(
            "does not hold", guild.walk_target("walk-to-spawn creature:39536", {})
        )


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheRunTimelineNamesOnce(unittest.TestCase):
    def test_a_seat_is_named_once_and_its_old_unknown_place_is_the_dungeon(self):
        from test_measured_views import render

        got = render(
            "views/run.js",
            """
console.log(JSON.stringify([
  M.seatLine("Durg", "Durg crossed into an unknown place.", "The Deadmines"),
  M.seatLine("Durg", "Durg entered The Deadmines.", "The Deadmines"),
  M.seatLine("Durg", "Ready when you are.", "The Deadmines"),
]));""",
        )
        self.assertEqual(
            got,
            [
                {"lead": True, "text": "entered The Deadmines."},
                {"lead": True, "text": "entered The Deadmines."},
                {"lead": False, "text": "Ready when you are."},
            ],
        )


if __name__ == "__main__":
    unittest.main()
