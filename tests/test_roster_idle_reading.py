"""The roster stops calling a seat Idle when it is not (#2178).

A member with no step, no intent and no guild job used to read "Idle: no errand
and no hold found", whatever it was doing. The roster now reads three truer
things off records the bridge already keeps: an active guild run, a level
gained lately, and a long stretch with no level below the raid tracker's next
level milestone. Run against the roster handler with a fake database.
"""

import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules
from test_members_v2 import NOW, ctx_for, server

with stub_modules(pymysql=PYMYSQL):
    from apiv2 import health, members

HOUR = 3600
NAMES = ("Moss", "Fern", "Reed", "Oak", "Pip", "Sedge")
LEVELS = {"Moss": 31, "Fern": 33, "Reed": 29, "Oak": 47, "Pip": 30, "Sedge": 35}


def rules(runs=(), levelled=(), jobs=()):
    chars = [
        {
            "name": n,
            "race": 1,
            "gender": 0,
            "class_id": 1,
            "level": LEVELS[n],
            "zone": 12,
            "map": 0,
            "flags": 0,
        }
        for n in NAMES
    ]
    guild = [
        {
            "guildid": 1,
            "guild_name": "Hall",
            "name": n,
            "class_id": 1,
            "level": LEVELS[n],
            "race": 1,
        }
        for n in NAMES
    ]
    snaps = [
        {
            "name": n,
            "zone_id": 12,
            "map_id": 0,
            "health": 900,
            "max_health": 900,
            "in_combat": 0,
        }
        for n in NAMES
    ]
    return [
        (("lineup guild",), guild),
        (("FROM characters",), chars),
        (("FROM overseer_snapshot",), snaps),
        (("FROM overseer_guild_run",), [{"members": m} for m in runs]),
        (("FROM overseer_level",), [{"name": n, "at": at} for n, at in levelled]),
        (("FROM overseer_command",), list(jobs)),
        (("UNIX_TIMESTAMP() AS now_at",), [{"now_at": NOW}]),
    ]


def roster(**kw):
    ctx, _log = ctx_for(rules(**kw), server(guildmates=NAMES))
    _code, payload = members.roster({}, ctx)
    return {m["name"]: m for m in payload["members"]}, ctx


class TheIdleLineIsEarned(unittest.TestCase):
    def test_a_member_inside_an_active_guild_run_reads_as_in_that_run(self):
        by, _ = roster(runs=["Moss:tank:warrior:31,Pip:dps:mage:30"])
        self.assertEqual(by["Moss"]["doing"], "In a guild run")
        self.assertNotIn("Idle", by["Moss"]["line"])
        self.assertEqual(by["Pip"]["doing"], "In a guild run")

    def test_a_member_who_levelled_lately_reads_as_playing_on_its_own(self):
        by, _ = roster(levelled=[("Fern", NOW - 2 * HOUR)])
        self.assertEqual(by["Fern"]["doing"], "Playing on its own")
        self.assertIn("last level 2 h 0 min ago", by["Fern"]["line"])
        self.assertEqual(by["Fern"]["for_s"], 2 * HOUR)

    def test_a_member_below_the_milestone_with_no_level_for_a_day_is_stalled(self):
        by, _ = roster(levelled=[("Reed", NOW - 30 * HOUR), ("Fern", NOW - HOUR)])
        self.assertEqual(by["Reed"]["doing"], "Stalled")
        self.assertEqual(by["Reed"]["stalled_s"], 30 * HOUR)
        self.assertIn("30 h 0 min", by["Reed"]["line"])
        self.assertIsNone(by["Fern"]["stalled_s"])

    def test_a_member_with_no_level_on_record_is_stalled_for_at_least_a_day(self):
        by, _ = roster()
        self.assertEqual(by["Reed"]["stalled_s"], 24 * HOUR)

    def test_a_member_that_fits_none_keeps_the_idle_line(self):
        by, _ = roster()
        self.assertEqual(by["Oak"]["doing"], "Idle")
        self.assertEqual(by["Oak"]["line"], "Idle: no errand and no hold found.")
        self.assertIsNone(by["Oak"]["stalled_s"])

    def test_a_member_holding_a_guild_job_is_not_re_read(self):
        job = {
            "name": "Sedge",
            "source": "guildjobs:pvp:Sedge",
            "command": "x",
            "status": "delivered",
            "detail": "",
            "at": NOW - 60,
        }
        by, _ = roster(jobs=[job])
        self.assertEqual(by["Sedge"]["doing"], "Idle")
        self.assertIsNone(by["Sedge"]["stalled_s"])

    def test_a_stall_is_not_a_stuck_record_and_files_no_health_finding(self):
        by, ctx = roster(levelled=[("Reed", NOW - 30 * HOUR)])
        self.assertFalse(by["Reed"]["stuck"])
        self.assertEqual(by["Reed"]["stuck_kind"], "")
        _code, payload = members.stuck({}, ctx)
        self.assertEqual(payload["members"], [])
        self.assertEqual(health.stuck_findings(payload, NOW), [])


if __name__ == "__main__":
    sys.exit(unittest.main())
