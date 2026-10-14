"""Statuses name the creature, item or quest a member walks to, never a bare id.

The operator read the Now page on a phone and saw "Doing: Walking to
creature 8122 on a town errand": a numeric aim read out as a number. Every
member-facing string that carries a creature, item or quest id names it from
the world database when it holds one, and says "an unnamed ..." with the
number when it does not - never a bare "<kind> <digits>".
"""

import re
import unittest

import agenda
import bag_pressure
import commandwords
import craft_supply
import nowstatus
import places
import travel
from apiv2 import guild

KORGELD = {"name": "Kor'geld", "subname": "Alchemy Supplies", "place": "Orgrimmar"}
CREATURES = {8122: KORGELD, 5594: "Alchemist Pestlezugg"}

# A bare id: "<kind> <digits>" with no "unnamed" and no parens saying so.
BARE = re.compile(r"(?<!unnamed )(?<!\()\b(creature|item|quest|spell|faction) \d+")


def _named_row(kind="errand", target="8122"):
    return {
        "leader_name": "Zug",
        "current_kind": kind,
        "current_owner": "town trip",
        "current_target": target,
        "current_for": 20,
    }


class TheCreatureAimIsNamed(unittest.TestCase):
    def test_a_numbered_aim_reads_as_name_role_and_town(self):
        self.assertEqual(
            places.aim_place("8122", CREATURES),
            "Kor'geld, the alchemy supplies in Orgrimmar",
        )
        self.assertEqual(
            places.walk_words("8122", CREATURES),
            "to Kor'geld, the alchemy supplies in Orgrimmar",
        )

    def test_a_bare_name_is_still_a_name(self):
        self.assertEqual(places.aim_place("8122", {8122: "Kor'geld"}), "Kor'geld")
        self.assertEqual(
            travel.describe("8122", CREATURES),
            "Kor'geld, the alchemy supplies in Orgrimmar",
        )

    def test_what_is_missing_is_left_out_rather_than_guessed(self):
        self.assertEqual(places.creature_words(8122, {"name": "Kor'geld"}), "Kor'geld")
        self.assertEqual(
            places.creature_words(8122, {"name": "Kor'geld", "place": "Orgrimmar"}),
            "Kor'geld in Orgrimmar",
        )
        self.assertEqual(
            places.creature_words(
                8122, {"name": "Kor'geld", "subname": "Alchemy Supplies"}
            ),
            "Kor'geld, the alchemy supplies",
        )

    def test_an_unnamed_entry_says_so_with_its_number(self):
        self.assertEqual(places.aim_place("8122"), "an unnamed creature (8122)")
        self.assertEqual(places.walk_words("8122"), "to an unnamed creature (8122)")
        self.assertEqual(travel.describe("8122"), "an unnamed creature (8122)")
        self.assertEqual(agenda.describe_aim("8122"), "an unnamed creature (8122)")

    def test_a_numeric_aim_with_what_the_walk_is_for(self):
        got = nowstatus.compose(
            {"present": 1},
            {"intent": _named_row(), "creatures": CREATURES},
        )
        self.assertEqual(
            got["doing"],
            "Walking to Kor'geld, the alchemy supplies in Orgrimmar on a town errand",
        )
        self.assertNotRegex(got["line"], BARE)

    def test_a_numeric_aim_without_a_name_says_so(self):
        got = nowstatus.compose({"present": 1}, {"intent": _named_row()})
        self.assertEqual(
            got["doing"],
            "Walking to an unnamed creature (8122) on a town errand",
        )
        self.assertNotRegex(got["line"], BARE)


class OldLinesReadHonestly(unittest.TestCase):
    def test_a_stored_bare_creature_id_is_said_as_unnamed(self):
        self.assertEqual(
            nowstatus.reword(
                "town trip took over: walking to creature 8122 on a town errand"
            ),
            "The town trip took over: walking to an unnamed creature (8122) on a "
            "town errand",
        )

    def test_a_line_already_said_right_is_untouched(self):
        self.assertEqual(
            nowstatus.reword("walking to an unnamed creature (8122)"),
            "walking to an unnamed creature (8122)",
        )

    def test_a_town_errand_step_with_a_numeric_aim_has_no_bare_id(self):
        step = nowstatus.classify(
            "town slot: town errand takes the traveller Grug for '8122'; "
            "the column was free"
        )[0]
        self.assertNotRegex(step.doing, BARE)

    def test_an_unheld_creature_says_so(self):
        self.assertIn(
            "does not hold",
            guild.walk_target("walk-to-spawn creature:39536", {}),
        )
        self.assertNotRegex(guild.walk_target("walk-to-spawn creature:39536", {}), BARE)
        self.assertEqual(
            guild.walk_target("walk-to-spawn creature:39536", {39536: "Bodley"}),
            "walking to Bodley",
        )


class TheErrandReportsNameTheirVendor(unittest.TestCase):
    def test_the_bag_trip_is_aimed_at_its_vendor_by_name(self):
        vendor = bag_pressure.BagVendor(
            entry=3498,
            name="Jazzik",
            map_id=1,
            yards=39.0,
            faction=69,
            offers=(
                bag_pressure.BagOffer(
                    entry=4496, name="Small Brown Pouch", slots=6, price=100
                ),
            ),
        )
        trip = bag_pressure.BagTrip(target="3498", vendor=vendor, buyers=("Uzza",))
        said = bag_pressure.bag_trip_report(trip, "Zug")
        self.assertIn("Zug is aimed at Jazzik", said)
        self.assertIn("Small Brown Pouch", said)
        self.assertNotRegex(said, BARE)

    def test_the_craft_trip_is_aimed_at_its_vendor_by_name(self):
        vendor = craft_supply.VendorSpawn(
            entry=5594,
            name="Alchemist Pestlezugg",
            faction=474,
            map_id=1,
            yards=83.0,
        )
        trip = craft_supply.SupplyTrip(
            traveller="Grog",
            target="5594",
            shopper="Ugga",
            entry=3371,
            label="Empty Vial",
            vendor=vendor,
        )
        said = craft_supply.report(trip)
        self.assertIn("Grog is aimed at Alchemist Pestlezugg", said)
        self.assertIn("Empty Vial", said)
        self.assertNotRegex(said, BARE)


class TheErrandBannerNamesItsWalk(unittest.TestCase):
    def test_a_numeric_travel_aim_is_the_creature(self):
        rows = [
            {
                "name": "Zug",
                "lead": 1,
                "enabled": 1,
                "travel_npc": "8122",
                "learn_skill": 0,
            }
        ]
        bare = agenda.errand(rows, [])
        self.assertEqual(bare["target_text"], "an unnamed creature (8122)")
        named = agenda.errand(rows, [], CREATURES)
        self.assertEqual(
            named["target_text"],
            "Kor'geld, the alchemy supplies in Orgrimmar",
        )
        self.assertNotRegex(named["target_text"], BARE)


class TheLiveReadNamesNumericAims(unittest.TestCase):
    def test_names_and_spawns_are_read_once_per_process(self):
        import map_server

        saved = dict(map_server._CREATURE_NAMES)
        map_server._CREATURE_NAMES.clear()
        calls = []

        def fetch(sql, params):
            calls.append((sql, tuple(params)))
            if "creature_template" in sql:
                return [
                    {
                        "id": 8122,
                        "name": "Kor'geld",
                        "subname": "Alchemy Supplies",
                    }
                ]
            return [{"entry": 8122, "map_id": 1, "x": 100.0, "y": 100.0}]

        try:
            got = map_server._creature_names(fetch, ["8122", "trigger:194", ""])
            self.assertEqual(got[8122]["name"], "Kor'geld")
            self.assertIn("place", got[8122])
            # Only the numeric aim is read, and only its two statements.
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][1], (8122,))
            # The second render reads nothing: template rows do not change
            # while a realm runs.
            again = map_server._creature_names(fetch, ["8122"])
            self.assertEqual(again, got)
            self.assertEqual(len(calls), 2)
            self.assertNotRegex(places.creature_words(8122, got[8122]), BARE)
        finally:
            map_server._CREATURE_NAMES.clear()
            map_server._CREATURE_NAMES.update(saved)


class NoMemberFacingStringPrintsABareId(unittest.TestCase):
    def test_the_now_and_member_status_strings(self):
        said = []
        for kind in sorted(nowstatus._KIND_WORDS):
            for target, creatures in (("8122", CREATURES), ("8122", None)):
                got = nowstatus.compose(
                    {"present": 1},
                    {"intent": _named_row(kind, target), "creatures": creatures},
                )
                said.append(got["line"])
                for step in got["steps"]:
                    said.append(step["text"])
        for target, creatures in (("8122", CREATURES), ("8122", None)):
            said.append(nowstatus.aim_words(target, creatures))
            said.append(places.walk_words(target, creatures))
            said.append(travel.describe(target, creatures))
            said.append(agenda.describe_aim(target, creatures))
            said.append(
                guild.walk_target("walk-to-spawn creature:%s" % target, CREATURES)
            )
        said.append(nowstatus.reword("walking to creature 8122 on a town errand"))
        said.append(
            nowstatus.classify(
                "town slot: town errand takes the traveller Grug for '8122'; "
                "the column was free"
            )[0].doing
        )
        for words in said:
            self.assertNotRegex(words, BARE, words)

    def test_the_command_log_names_or_says_unnamed(self):
        def say(kind, command, arg=""):
            return commandwords.say(
                {"kind": kind, "command": command, "target_arg": arg}, {}
            )

        for words in (
            say("job", "walk-to-spawn creature:10076 near:3"),
            say("buy", "entry:3771 count:4 max:4000"),
            say("share", "quest:710", "Bork"),
        ):
            self.assertNotRegex(words, BARE, words)

    def test_no_bare_creature_format_string_in_the_naming_modules(self):
        import pathlib

        here = pathlib.Path(__file__).resolve().parent.parent
        paths = [
            here / name
            for name in (
                "places.py",
                "travel.py",
                "nowstatus.py",
                "bag_pressure.py",
                "craft_supply.py",
                "agenda.py",
                "commandwords.py",
            )
        ] + [here / "apiv2" / "guild.py"]
        found = []
        for path in paths:
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"creature %[sdr]", line):
                    found.append("%s:%d: %s" % (path.name, i, line.strip()))
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
