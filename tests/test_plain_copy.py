"""The site speaks a player's language, and says where an order came from truly (#567).

The operator, reading the home banner on a phone: "this page looks weird
saying it came from discord, can we make the website way more coherent
everywhere". The banner for a family on a town run read "This drives: ... the
leader carries `new rpg` ... (mod_overseer.cpp, LeaderCarriesNewRpg and
CutOffFollowerRoams, mod-overseer#659)", and under it "from a Discord order",
which was false: the goal row it came from was written by the family council,
which stamps the overseer's reporting channel on its own decisions.

Each test below builds a payload the page prints verbatim and checks it for
code references: file names, function names, table and column names, issue
numbers and backticked identifiers. They stay in comments and logs.
"""

import re
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import agenda  # noqa: E402
import campaignqueue  # noqa: E402
import council  # noqa: E402
import decree  # noqa: E402
import dungeonpath  # noqa: E402
import jobs  # noqa: E402
import runtimeline  # noqa: E402
import standing  # noqa: E402
import tradespec  # noqa: E402

NOW = datetime(2026, 10, 4, 20, 30, 0)
FAMILY = ("Grug", "Bork", "Grog", "Og", "Ugga")

# What a reader must never be shown. Kept narrow on purpose: every pattern is
# a thing that only code says, so a plain sentence cannot trip it.
CODE = re.compile(
    r"\.cpp\b"
    r"|\.py\b"
    r"|mod-overseer"
    r"|infra#"
    r"|#\d{2,}"
    r"|`"
    r"|overseer_[a-z]"
    r"|LeaderCarriesNewRpg|CutOffFollowerRoams|DriveQuests|DoJob|ResolveTravelTarget"
    r"|\bnew rpg\b"
    r"|\b[a-z]+_[a-z]+_?[a-z]*\b"  # snake_case: a column or a function
    r"|\b[A-Z]{3,}_[A-Z_]+\b"  # an enum: STAGED_INSIDE
)


def code_in(text: str) -> list:
    return CODE.findall(str(text or ""))


def strings(payload) -> list:
    """Every string in a payload, however deep."""
    out = []
    if isinstance(payload, dict):
        for value in payload.values():
            out.extend(strings(value))
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            out.extend(strings(value))
    elif isinstance(payload, str):
        out.append(payload)
    return out


def roster(job: str) -> list:
    return [
        {
            "name": name,
            "enabled": 1,
            "lead": 1 if name == "Grug" else 0,
            "job": job,
            "drive_quest": 0,
            "travel_npc": "",
            "learn_skill": 0,
            "dungeon_runs_wanted": 11,
            "dungeon_runs_done": 9,
        }
        for name in FAMILY
    ]


# The live state on 2026-10-04: the council set Bork on Scarlet Cathedral at
# 20:33, its row carrying the reporting channel, while the family waited in
# town for its Gnomeregan runs.
COUNCIL_GOAL = {
    "character_name": "Bork",
    "kind": "dungeon",
    "skill_name": "scarlet-cathedral",
    "target": 25,
    "status": "active",
    "channel_id": "154305710",
    "last_report": "0",
    "quest_id": 0,
    "created_at": datetime(2026, 10, 4, 20, 33, 12),
}


def town_run_agenda() -> dict:
    return agenda.build_agenda(
        roster("town run"),
        [],
        [],
        [COUNCIL_GOAL],
        [],
        [{"kind": "quest_accept", "last_seen": NOW - timedelta(seconds=7)}],
        {},
        now=NOW,
    )


class TheTownRunBannerReadsLikeAPlayerWroteIt(unittest.TestCase):
    """The operator's screenshot, rebuilt from the rows that drew it."""

    def test_no_code_reference_reaches_the_banner(self):
        out = town_run_agenda()
        for line in [out["headline"], *out["detail"]]:
            self.assertEqual(code_in(line), [], line)
            for word in (".cpp", "mod-overseer#", "LeaderCarriesNewRpg", "This drives"):
                self.assertNotIn(word, line)

    def test_the_headline_says_what_they_are_doing(self):
        out = town_run_agenda()
        self.assertIn("in town", out["headline"])
        self.assertIn("repairing", out["headline"])

    def test_a_council_goal_for_one_member_is_not_credited_to_the_town_run(self):
        """The headline is the town run, which the council's Scarlet
        Cathedral goal did not produce, so no source label is drawn."""
        out = town_run_agenda()
        self.assertEqual(out["orders"]["kind"], "council")
        self.assertEqual(out["source"], "")


class TheSourceLabelIsTrue(unittest.TestCase):
    def test_the_label_comes_from_a_known_set(self):
        self.assertEqual(
            set(agenda.SOURCE_LABELS.values()), {"set by the family council"}
        )
        for label in agenda.SOURCE_LABELS.values():
            self.assertNotIn("Discord", label)

    def test_a_goal_with_a_channel_is_the_councils_not_discords(self):
        """A channel on the row is where the council announced it."""
        quest_goal = dict(
            COUNCIL_GOAL,
            kind="quest",
            skill_name=None,
            target=0,
            quest_id=101,
            last_report="-3",
        )
        rows = roster("quest")
        for row in rows:
            row["drive_quest"] = 101
        out = agenda.build_agenda(
            rows,
            [],
            [],
            [quest_goal],
            [],
            [{"kind": "quest_accept", "last_seen": NOW}],
            {101: "The Totem of Infliction"},
            now=NOW,
        )
        self.assertEqual(out["source"], "set by the family council")
        self.assertIn(out["source"], agenda.SOURCE_LABELS.values())
        for line in [out["headline"], *out["detail"], out["orders"]["text"]]:
            self.assertNotIn("Discord", line)

    def test_the_page_prints_the_payloads_label_and_no_discord_badge(self):
        page = (HERE / "classic.html").read_text(encoding="utf-8")
        self.assertNotIn("from a Discord order", page)
        start = page.index("function renderAgenda(p)")
        body = page[start : page.index("\n}\n", start)]
        self.assertIn("o.textContent = p.source", body)
        self.assertNotIn("channel_id", body)


class EveryJobSaysWhatItDoesPlainly(unittest.TestCase):
    def test_every_mode_and_every_door_form(self):
        modes = list(jobs.MODES) + ["dungeon:gnomeregan", "raid:moltencore"]
        for mode in modes:
            said = jobs.say(mode)
            self.assertTrue(said, mode)
            self.assertEqual(code_in(said), [], (mode, said))

    def test_every_wired_mode_has_a_sentence_of_its_own(self):
        self.assertEqual(set(jobs.SAYS), set(jobs.IMPLEMENTED))

    def test_a_door_is_named_as_a_place(self):
        self.assertEqual(
            campaignqueue.job_words("dungeon:scarlet-cathedral"),
            "Scarlet Monastery (the Cathedral) runs",
        )
        self.assertEqual(
            campaignqueue.job_words("raid:moltencore"), "the Molten Core raid"
        )
        self.assertEqual(campaignqueue.job_words("town run"), "town run")


class TheDecreeConsoleIsPlain(unittest.TestCase):
    def test_every_string_the_console_prints(self):
        out = decree.build_console(roster("dungeon:shadowfang"), [], now=NOW)
        # The Jev panel compares answers by their stored option names
        # ("give:Og"), which is its subject; everything else is checked.
        out.pop("jev", None)
        # A travel chip's `flag` is the NPC flag the page matches on and never
        # prints.
        for chip in out.get("travel", {}).get("chips", []):
            chip.pop("flag", None)
        for text in strings(out):
            self.assertEqual(code_in(text), [], text)

    def test_every_refusal(self):
        for mode in decree.unwired_modes():
            refusal = decree.unwired_refusal(mode)
            self.assertEqual(code_in(refusal), [], refusal)
        for text in decree.ORDER_NOTHING.values():
            self.assertEqual(code_in(text), [], text)


class TheOtherViewsArePlain(unittest.TestCase):
    def test_the_dungeon_path_lines(self):
        portals = {
            36: ["deadmines"],
            189: ["scarlet", "scarlet-library"],
            43: ["wailing"],
        }
        line = dungeonpath.runnable_line(portals, {36: "The Deadmines"})
        self.assertEqual(code_in(line), [], line)
        self.assertEqual(code_in(dungeonpath.BASIS), [], dungeonpath.BASIS)
        for caveat in dungeonpath.PORTAL_CAVEATS.values():
            self.assertEqual(code_in(caveat), [], caveat)

    def test_the_run_timeline(self):
        rows = [
            {
                "id": 1,
                "family": "Grug",
                "kind": "phase",
                "phase": "RESET",
                "detail": "IDLE -> RESET (gnomeregan, run 9 of campaign 78)",
                "campaign_id": 78,
                "run_number": 9,
                "portal": "gnomeregan",
                "age_seconds": 600,
            },
            {
                "id": 2,
                "family": "Grug",
                "kind": "phase",
                "phase": "STAGED_INSIDE",
                "detail": "RECOVERING -> STAGED_INSIDE",
                "campaign_id": 78,
                "run_number": 9,
                "run_id": 433157,
                "age_seconds": 500,
            },
            {
                "id": 3,
                "family": "Grug",
                "kind": "ended",
                "detail": "split_failed: the family is split at the berth",
                "campaign_id": 78,
                "run_number": 9,
                "age_seconds": 400,
            },
        ]
        out = runtimeline.build_run_timeline(rows, {"Grug": list(FAMILY)})
        run = out["families"][0]["runs"][0]
        self.assertEqual(run["title"], "Gnomeregan, run 9")
        for text in [run["title"], run["line"], *(e["line"] for e in run["events"])]:
            self.assertEqual(code_in(text), [], text)

    def test_the_council_card_says_the_job_as_a_place(self):
        line = council._job_said("dungeon:blackrock-depths")
        self.assertEqual(line, "Blackrock Depths runs")

    def test_the_trade_and_standing_notes(self):
        for text in (
            tradespec.STEERING_LIMIT,
            tradespec.GRANT_REFUSAL,
            standing.ENCHANTING_WHY,
        ):
            self.assertEqual(code_in(text), [], text)
        for spec in tradespec.SPECS:
            if spec.unreachable:
                self.assertEqual(code_in(spec.unreachable), [], spec.key)


class TheLightThemeKeepsClassNamesReadable(unittest.TestCase):
    """#563: Rogue yellow and Priest white on a white Lineup card measured
    1.13:1 and 1:1. The Lineup paints names through classInk, which mixes the
    class colour toward black by --class-mix: 50% on light (Priest white
    then reads at about 6:1), whole on dark."""

    PAGE = (HERE / "classic.html").read_text(encoding="utf-8")

    def test_the_lineup_names_go_through_class_ink(self):
        for fn in ("function lnCard(", "function lgRender("):
            start = self.PAGE.index(fn)
            body = self.PAGE[start : self.PAGE.index("\n}\n", start)]
            self.assertIn("classInk(m.class_colour)", body, fn)
            self.assertNotIn("style.color = m.class_colour", body, fn)

    def test_the_mix_is_set_for_every_theme_state(self):
        self.assertIn("--class-mix:50%;", self.PAGE)
        # Once under the OS dark preference, once under the explicit choice.
        self.assertEqual(self.PAGE.count("--class-mix:100%;"), 2)


if __name__ == "__main__":
    unittest.main()
