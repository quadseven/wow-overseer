"""Guild dungeon seats filled in the last hour, and the members waiting (#784).

The measure of more tanks and healers is seats: members who went in with
their guild in the last hour, the ones a pug or a lent family member filled
counted apart, and the free members whose level fits a door still waiting.
"""

import asyncio
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import seatmeter as sm  # noqa: E402
from test_guildsocial import (  # noqa: E402
    DOORS, HOLY, MAGE, PRIEST, PROTECTION, ROGUE, WARRIOR, mate,
)
import guildrun  # noqa: E402
import json  # noqa: E402
from test_guildsocial_bridge import _Self, bridge, facts  # noqa: E402


def run(guild, names, pugs="", outcome=""):
    members = ",".join("%s:dps:4:20" % n for n in names)
    return {"guild": guild, "members": members, "pugs": pugs, "outcome": outcome}


class TheSeats(unittest.TestCase):
    def test_every_seat_of_a_run_that_went_to_the_finder(self):
        rows = [
            run("Cave", ["A", "B", "C", "D", "Mercy"], pugs="Mercy"),
            run("Cave", ["E", "F", "G", "H", "Ugga"], outcome="cleared"),
            run("Bonkers", ["K", "L", "M", "N", "O"], outcome="wiped"),
        ]
        self.assertEqual(
            sm.seats(rows, {"Ugga"}), {"Cave": (10, 2, 1, 1), "Bonkers": (5, 1, 0, 0)}
        )

    def test_a_run_the_finder_turned_away_filled_nothing(self):
        rows = [
            run("Cave", ["A", "B", "C", "D", "E"], outcome="refused"),
            run("Cave", ["A", "B", "C", "D", "E"], outcome="not entered"),
        ]
        self.assertEqual(sm.seats(rows, set()), {})


class TheWaiting(unittest.TestCase):
    def test_free_members_whose_level_fits_a_door(self):
        mates = [
            mate("Auren", 20, ROGUE),
            mate("Zappy", 19, MAGE),
            mate("Tiny", 5, MAGE),
            mate("Busy", 20, ROGUE),
        ]
        held = {"Busy": "in a guild run"}
        self.assertEqual(
            sm.waiting(mates, held, DOORS, {"Cave": "Alliance"}), {"Cave": 2}
        )


class TheLine(unittest.TestCase):
    def test_it_names_each_guild(self):
        found = sm.meters(
            ["Cave", "Bonkers"],
            [run("Cave", ["A", "B", "C", "D", "Mercy"], pugs="Mercy")],
            set(),
            [mate("Auren", 20, ROGUE)],
            {},
            DOORS,
            {"Cave": "Alliance"},
        )
        self.assertEqual(
            sm.line(found),
            "Cave 5 seat(s) in 1 run(s) (1 pug, 0 family), 1 waiting"
            " | Bonkers 0 seat(s) in 0 run(s) (0 pug, 0 family), 0 waiting",
        )


class TheBench(unittest.TestCase):
    """Carry-ready tanks and healers per door (#784 box 1)."""

    DEADMINES_AT_20 = guildrun.doors({}, {36: 20})

    def _row(self, found, guild="Cave"):
        return next(r for r in found[guild] if r["keyword"] == "deadmines")

    def test_counts_the_tanks_and_healers_standing_at_the_carry_floor(self):
        mates = [
            mate("Tanky", 21, WARRIOR, talent_spells=PROTECTION, has_shield=1),
            mate("LowTank", 19, WARRIOR, talent_spells=PROTECTION, has_shield=1),
            mate("Healy", 20, PRIEST, talent_spells=HOLY),
            mate("Auren", 25, ROGUE),
            mate("Bonk", 30, WARRIOR, talent_spells=PROTECTION, has_shield=1, guild="Bonkers"),
        ]
        found = sm.bench(["Cave", "Bonkers"], mates, self.DEADMINES_AT_20,
                         {"Cave": "Alliance", "Bonkers": "Alliance"})
        row = self._row(found)
        self.assertEqual((row["tanks"], row["healers"], row["carry_floor"]), (1, 1, 20))
        self.assertEqual((self._row(found, "Bonkers")["tanks"],
                          self._row(found, "Bonkers")["healers"]), (1, 0))

    def test_a_tank_with_no_shield_is_not_ready(self):
        mates = [mate("Bare", 25, WARRIOR, talent_spells=PROTECTION, has_shield=0)]
        found = sm.bench(["Cave"], mates, self.DEADMINES_AT_20, {"Cave": "Alliance"})
        self.assertEqual(self._row(found)["tanks"], 0)

    def test_a_door_with_no_bosses_level_is_left_out(self):
        found = sm.bench(["Cave"], [], guildrun.doors({}, {}), {"Cave": "Alliance"})
        self.assertEqual(found, {"Cave": []})

    def test_the_page_reads_the_memo_rows(self):
        rows = [{"subject": "Cave", "value": json.dumps([{"keyword": "deadmines"}]),
                 "since": 5.0},
                {"subject": "Bonkers", "value": "not json", "since": 5.0}]
        self.assertEqual(
            sm.page(rows),
            {"guilds": [{"guild": "Cave", "doors": [{"keyword": "deadmines"}], "at": 5.0}]},
        )

    def test_the_bridge_leaves_the_bench_in_the_memo_store(self):
        this = _Self()
        this._log_seat_meter = lambda *a: bridge.Bridge._log_seat_meter(this, *a)
        saved = []
        bounds = mock.Mock(guilds=("Cave",))
        mates = [mate("Tanky", 21, WARRIOR, talent_spells=PROTECTION, has_shield=1)]
        with (
            mock.patch.object(bridge, "_fetch_seat_meter_runs", lambda: []),
            mock.patch.object(bridge, "_memo_upsert", lambda *a: saved.append(a)),
            self.assertLogs("wow-overseer", level="INFO"),
        ):
            asyncio.run(bridge.Bridge._log_seat_meter(
                this, bounds, {"family": set()}, mates, {}, self.DEADMINES_AT_20, []))
        self.assertEqual([(a[0], a[1]) for a in saved], [("seatbench", "Cave")])
        row = next(r for r in saved[0][2] if r["keyword"] == "deadmines")
        self.assertEqual((row["tanks"], row["healers"]), (1, 0))


class TheBridgeSaysIt(unittest.TestCase):
    def test_the_social_pass_logs_the_meter_at_most_every_ten_minutes(self):
        this = _Self()
        this._log_seat_meter = lambda *a: bridge.Bridge._log_seat_meter(this, *a)
        stubs = {
            "_guild_run_gate": lambda: {"uptime": 99999, "latest": []},
            "_guild_runs_in_flight": lambda: 0,
            "_fetch_guild_social_facts": lambda bounds: facts(),
            "_write_guild_social": lambda social: 0,
            "_guild_social_names": lambda: set(),
            "_fetch_seat_meter_runs": lambda: [run("Cave", ["A", "B", "C", "D", "E"])],
            "_memo_upsert": lambda *a: None,
        }
        with (
            mock.patch.multiple(bridge, **stubs),
            mock.patch.dict(bridge.os.environ, {"GUILD_PUGS": "off"}),
            self.assertLogs("wow-overseer", level="INFO") as said,
        ):
            asyncio.run(bridge.Bridge._guild_social_once(this))
            asyncio.run(bridge.Bridge._guild_social_once(this))
        lines = [m for m in said.output if "guild seats: last hour:" in m]
        self.assertEqual(len(lines), 1)
        self.assertIn("Cave 5 seat(s) in 1 run(s)", lines[0])


if __name__ == "__main__":
    unittest.main()
