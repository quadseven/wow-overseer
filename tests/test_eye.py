"""The Eye: eye.py's judgement, and the page's contract.

THE THING THIS VIEW IS FOR IS THE THING IT REFUSES TO DRAW. A server rollup
over a realm with one family on it is five real numbers and a dozen invented
ones, and the invented ones are what a reader remembers. So every rung says
whether it is real, and a rung that is not says what would turn it on rather
than drawing an empty chart of itself.

Most of these assertions are therefore about ABSENCE: no guild ladder, no
population curve, no tier reported ON that was not counted. A view whose
value is its honesty needs its honesty pinned, or the first person to make it
look busier will win.

Tickets: infra#2597.
"""

import pathlib
import unittest
from datetime import datetime

import eye

HERE = pathlib.Path(__file__).resolve().parent.parent
BANNER = "// --- the Eye (infra#2597)"
CSS_BANNER = "/* --- the Eye (infra#2597)"
NEXT = "// --- the Armory tab (infra#3096, infra#3139)"
NEXT_CSS = "/* --- the Armory tab (infra#3096, infra#3139)"

T0 = datetime(2026, 9, 3, 20, 0, 0)

FAMILY = [{"name": n} for n in ("Grug", "Ugga", "Grog", "Bork", "Og")]


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same helper test_chronicle_tab.py and test_council_view.py carry, and
    duplicated for the same reason: these files slice the page apart by
    banner, and a helper imported across them would tie one view's window to
    another's. A guard a COMMENT can trip is a guard that gets weakened until
    it passes, and this file's banner names every word its guards forbid.
    """
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )


def snapshot(name, bot=1, leader=""):
    return {"name": name, "is_bot": bot, "group_leader": leader}


def tiers(payload):
    return {row["tier"]: row for row in payload["tiers"]}


class ATierThatIsNotRealSaysWhatWouldMakeItReal(unittest.TestCase):
    def test_the_guild_tier_is_off_and_names_its_condition(self):
        """THE RUNG THE WHOLE VIEW IS SHAPED AROUND. There is no guild. An
        empty guild roster with an axis on it is a picture of a server that
        does not exist; the number of signatures a charter needs is a fact."""
        rung = eye.guild_tier(0, 5)
        self.assertEqual(eye.OFF, rung["state"])
        self.assertEqual("0", rung["value"])
        self.assertIn(str(eye.CHARTER_SIGNATURES), rung["switch"])

    def test_a_realm_too_small_to_sign_a_charter_says_how_short_it_is(self):
        rung = eye.guild_tier(0, 5)
        self.assertIn("5 short", rung["switch"])

    def test_a_realm_big_enough_says_nobody_has_done_it_instead(self):
        """Two different absences. "Nobody can" and "nobody has" are not the
        same finding and must not read the same."""
        rung = eye.guild_tier(0, eye.CHARTER_SIGNATURES)
        self.assertNotIn("short", rung["switch"])
        self.assertIn("nobody has taken one round", rung["switch"])

    def test_a_guild_that_exists_turns_the_tier_on_by_itself(self):
        """No change to this module or to the page. The count is a real read."""
        rung = eye.guild_tier(2, 40)
        self.assertEqual(eye.ON, rung["state"])
        self.assertEqual("", rung["switch"])

    def test_a_tier_that_is_on_never_carries_a_switch(self):
        """A switch on a working tier reads as a suggestion to change
        something that already works."""
        rung = eye.tier("X", eye.ON, "1", "fine", "do a thing")
        self.assertEqual("", rung["switch"])

    def test_every_off_or_partial_tier_in_a_full_build_has_a_switch(self):
        payload = eye.build_eye(
            [], FAMILY, [{"characters": 5}], [{"guilds": 0}], now=T0
        )
        for rung in payload["tiers"]:
            if rung["state"] != eye.ON:
                self.assertTrue(rung["switch"], rung["tier"])


class TheRealmTierRefusesToCallOneFamilyAPopulation(unittest.TestCase):
    def test_an_empty_world_is_a_real_state_and_not_an_outage(self):
        """The module sweeps logged-out rows, so an empty world drains the
        table. Saying so is honest; crying outage over an empty tavern is
        the bug the map banner already had."""
        rung = eye.realm_tier(0, 0)
        self.assertEqual(eye.OFF, rung["state"])
        self.assertIn("Nobody walks the world", rung["headline"])

    def test_one_family_logged_in_is_partial_and_says_why(self):
        rung = eye.realm_tier(5, 0)
        self.assertEqual(eye.PARTIAL, rung["state"])
        self.assertIn("population IS the family", rung["switch"])

    def test_a_crowd_is_a_population(self):
        rung = eye.realm_tier(eye.CROWD, 1)
        self.assertEqual(eye.ON, rung["state"])
        self.assertEqual("", rung["switch"])

    def test_the_machine_played_characters_are_counted_as_such(self):
        self.assertIn(
            "4 of them played by the machine", eye.realm_tier(5, 1)["headline"]
        )


class ThePartyTierIsReadOffTheLiveWorld(unittest.TestCase):
    def test_one_leader_is_one_party(self):
        rows = [snapshot("Grug", leader="Grug"), snapshot("Bork", leader="Grug")]
        rung = eye.party_tier(rows, {"Grug", "Bork"})
        self.assertEqual(eye.ON, rung["state"])
        self.assertIn("Grug", rung["headline"])

    def test_two_leaders_is_a_split_family_and_not_a_party(self):
        """Five characters behind two leaders are not one party, and calling
        that a party would be the invention this view exists to refuse."""
        rows = [snapshot("Grug", leader="Grug"), snapshot("Bork", leader="Bork")]
        rung = eye.party_tier(rows, {"Grug", "Bork"})
        self.assertEqual(eye.PARTIAL, rung["state"])
        self.assertIn("split", rung["headline"])

    def test_nobody_in_the_world_is_no_party(self):
        rung = eye.party_tier([], {"Grug"})
        self.assertEqual(eye.OFF, rung["state"])

    def test_a_stranger_leading_a_stranger_is_not_the_familys_party(self):
        """The tier reports the FAMILY. Another player's group on the same
        realm is not evidence about this one."""
        rows = [snapshot("Someone", leader="Someone")]
        self.assertEqual(eye.OFF, eye.party_tier(rows, {"Grug"})["state"])


class TheFamilyTierDoesNotBlinkOutAtBedtime(unittest.TestCase):
    def test_the_family_is_read_from_saved_rows_and_not_from_the_snapshot(self):
        """The five exist whether or not they are logged in. A FAMILY tier
        driven by the live snapshot would report "no family is in the world"
        every night, which is a claim about the wrong thing."""
        payload = eye.build_eye(
            [], FAMILY, [{"characters": 5}], [{"guilds": 0}], now=T0
        )
        self.assertEqual(eye.ON, tiers(payload)[eye.FAMILY]["state"])
        self.assertEqual(eye.OFF, tiers(payload)[eye.REALM]["state"])

    def test_the_family_is_named_rather_than_counted(self):
        rung = eye.family_tier(FAMILY)
        for name in ("Grug", "Ugga", "Grog", "Bork", "Og"):
            self.assertIn(name, rung["headline"])

    def test_no_saved_family_is_reported_and_not_hidden(self):
        self.assertEqual(eye.OFF, eye.family_tier([])["state"])
        self.assertEqual(eye.OFF, eye.character_tier([], 0)["state"])

    def test_a_family_that_is_the_whole_realm_says_so(self):
        self.assertIn(
            "they are the whole realm", eye.character_tier(FAMILY, 5)["headline"]
        )

    def test_a_realm_with_other_characters_gives_the_bigger_number(self):
        self.assertIn("of 40", eye.character_tier(FAMILY, 40)["headline"])


class TheRollupAddsUpToOneHonestSentence(unittest.TestCase):
    def test_it_says_how_much_of_the_ladder_is_real(self):
        self.assertIn("2 of 5", eye.honest_line(2, 5))
        self.assertIn("names what would turn it on", eye.honest_line(2, 5))

    def test_it_does_not_congratulate_anybody(self):
        """A rollup that says "3 of 5 systems nominal" over a realm with one
        family on it is the dashboard voice this view refuses."""
        for banned in ("nominal", "healthy", "all good", "%"):
            self.assertNotIn(banned, eye.honest_line(3, 5))

    def test_a_complete_ladder_says_nothing_is_a_placeholder(self):
        self.assertIn("Nothing on this page is a placeholder", eye.honest_line(5, 5))

    def test_the_strip_counts_and_never_estimates(self):
        payload = eye.build_eye(
            [snapshot("Grug", bot=1, leader="Grug")],
            FAMILY,
            [{"characters": 5}],
            [{"guilds": 0}],
            now=T0,
        )
        strip = {t["label"]: t["value"] for t in payload["strip"]}
        self.assertEqual("5", strip["CHARACTERS"])
        self.assertEqual("1", strip["IN WORLD"])
        self.assertEqual("1", strip["FAMILIES"])
        self.assertEqual("0", strip["GUILDS"])
        self.assertEqual("3/5", strip["TIERS ON"])


class ADegradedSchemaThinsTheViewRatherThanBreakingIt(unittest.TestCase):
    def test_every_input_may_be_empty(self):
        """A realm whose schema predates a table hands in [] for it, exactly
        as build_agenda's inputs may."""
        payload = eye.build_eye([], [], [], [], now=T0)
        self.assertEqual(5, len(payload["tiers"]))
        self.assertTrue(payload["honest"])

    def test_a_count_row_with_a_null_in_it_is_zero_and_not_a_crash(self):
        self.assertEqual(0, eye._count([{"guilds": None}], "guilds"))
        self.assertEqual(0, eye._count([], "guilds"))

    def test_a_tier_is_never_reported_on_without_having_been_counted(self):
        """The one failure that would make this view worse than no view."""
        payload = eye.build_eye([], [], [], [], now=T0)
        for rung in payload["tiers"]:
            self.assertNotEqual(eye.ON, rung["state"], rung["tier"])


class ThePageOnlyDraws(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        handler = self.server[self.server.index("def _eye") :]
        handler = handler[: handler.index("def _wealth")]
        self.assertNotIn("query.get", handler)
        self.assertIn("503", handler)

    def test_the_guild_count_is_a_real_read_and_not_a_constant(self):
        """The Eye reports no guild because the table was counted and had
        nothing in it. A hard-coded zero would keep saying so on the day one
        was made."""
        fetch = self.server[self.server.index("def _fetch_eye") :]
        fetch = fetch[: fetch.index("# --- the current-goal banner")]
        self.assertIn("SELECT COUNT(*) AS guilds FROM guild", fetch)
        self.assertIn('"guild")', fetch)

    def test_the_module_ships_in_the_image(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("eye.py", dockerfile)

    def test_no_em_dashes(self):
        for name in ("eye.py", "tests/test_eye.py"):
            self.assertNotIn(
                chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name
            )


if __name__ == "__main__":
    unittest.main()
