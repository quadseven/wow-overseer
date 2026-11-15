"""Tests for guild rank promotion and MOTD policy (#2616)."""

from __future__ import annotations

import pathlib
import re
import types
import unittest

import apiv2.guild as guild_api
import apiv2.presence as presence
import guildranks
import guildrun
import raidteams
import realmread

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOW = 1_760_000_000


def _member(name, level, rank, *, online=False):
    return {
        "name": name,
        "level": level,
        "rank": rank,
        "online": online,
    }


class RankRuleTests(unittest.TestCase):
    def test_rank_constants_match_mod_overseer_header(self):
        header = (ROOT / "mod-overseer/src/overseer_decisions.h").read_text(
            encoding="utf-8"
        )
        expected = {}
        for name in ("MASTER", "OFFICER", "VETERAN", "MEMBER", "INITIATE"):
            match = re.search(rf"constexpr unsigned GUILD_RANK_{name} = (\d+);", header)
            self.assertIsNotNone(match, name)
            expected[name] = int(match.group(1))
        self.assertEqual(
            expected,
            {
                "MASTER": guildranks.RANK_MASTER,
                "OFFICER": guildranks.RANK_OFFICER,
                "VETERAN": guildranks.RANK_VETERAN,
                "MEMBER": guildranks.RANK_MEMBER,
                "INITIATE": guildranks.RANK_INITIATE,
            },
        )

    def test_target_rank_maps_level_and_raid_seat(self):
        self.assertEqual(guildranks.RANK_INITIATE, guildranks.target_rank(1, False))
        self.assertEqual(guildranks.RANK_INITIATE, guildranks.target_rank(19, False))
        self.assertEqual(guildranks.RANK_MEMBER, guildranks.target_rank(20, False))
        self.assertEqual(guildranks.RANK_MEMBER, guildranks.target_rank(60, False))
        self.assertEqual(guildranks.RANK_VETERAN, guildranks.target_rank(60, True))
        self.assertEqual(guildranks.RANK_VETERAN, guildranks.target_rank(15, True))

    def test_promotion_rank_never_demotes_or_touches_officers(self):
        self.assertIsNone(guildranks.promotion_rank(guildranks.RANK_MASTER, 1, False))
        self.assertIsNone(guildranks.promotion_rank(guildranks.RANK_OFFICER, 1, False))
        self.assertIsNone(guildranks.promotion_rank(guildranks.RANK_VETERAN, 60, False))
        self.assertIsNone(guildranks.promotion_rank(guildranks.RANK_MEMBER, 25, False))
        self.assertIsNone(
            guildranks.promotion_rank(guildranks.RANK_INITIATE, 19, False)
        )
        self.assertEqual(
            guildranks.RANK_MEMBER,
            guildranks.promotion_rank(guildranks.RANK_INITIATE, 20, False),
        )
        self.assertEqual(
            guildranks.RANK_VETERAN,
            guildranks.promotion_rank(guildranks.RANK_INITIATE, 60, True),
        )
        self.assertEqual(
            guildranks.RANK_VETERAN,
            guildranks.promotion_rank(guildranks.RANK_MEMBER, 60, True),
        )


class MotdAndPlanTests(unittest.TestCase):
    def test_motd_names_active_goal_or_raid_lineup_within_cap(self):
        self.assertEqual("", guildranks.motd_for_goal("Cave"))
        line = guildranks.motd_for_goal(
            "Cave",
            active_goal={"kind": "dungeon", "target": 10, "instance": "deadmines"},
        )
        self.assertIn("deadmines", line.lower())
        self.assertLessEqual(len(line), guildranks.MAX_MOTD_BYTES)
        raid_line = guildranks.motd_for_goal("Cave", raid_keyword="mc")
        self.assertIn("mc", raid_line.lower())
        self.assertTrue(raid_line.isascii())

    def test_plan_actions_promotes_and_sets_motd_when_master_online(self):
        seats = frozenset(s.name for s in raidteams.seats("Cave"))
        raider = sorted(seats)[0]
        members = [
            _member("Grug", 60, guildranks.RANK_MASTER, online=True),
            _member("Ugga", 60, guildranks.RANK_OFFICER, online=True),
            _member(raider, 60, guildranks.RANK_INITIATE),
            _member("Ltwenty", 20, guildranks.RANK_INITIATE),
            _member("Lnineteen", 19, guildranks.RANK_INITIATE),
        ]
        actions = guildranks.plan_actions(
            "Cave",
            master="Grug",
            members=members,
            current_motd="No message set.",
            raid_keyword="mc",
            raid_seats=seats,
        )
        promotes = {a.target: a.command for a in actions if a.verb == "promote"}
        self.assertEqual(
            {
                raider: "promote rank:2",
                "Ltwenty": "promote rank:3",
            },
            promotes,
        )
        motds = [a.command for a in actions if a.verb == "motd"]
        self.assertEqual(1, len(motds))
        self.assertIn("mc", motds[0].lower())

    def test_plan_actions_waits_without_online_master_and_skips_pending(self):
        members = [
            _member("Grug", 60, guildranks.RANK_MASTER, online=False),
            _member("Beta", 25, guildranks.RANK_INITIATE),
        ]
        self.assertEqual(
            (),
            guildranks.plan_actions(
                "Cave",
                master="Grug",
                members=members,
                current_motd="No message set.",
                raid_keyword="mc",
            ),
        )
        members[0]["online"] = True
        pending = frozenset({"Beta", "motd"})
        self.assertEqual(
            (),
            guildranks.plan_actions(
                "Cave",
                master="Grug",
                members=members,
                current_motd="No message set.",
                raid_keyword="mc",
                pending=pending,
            ),
        )


class GuildApiAndDocTests(unittest.TestCase):
    def test_apiv2_guild_exposes_rank_counts_and_pending_promotions(self):
        class Server:
            recap = types.SimpleNamespace(zone_names=lambda c: {40: "Westfall"})
            GEO = types.SimpleNamespace(continents={})
            achievements = types.SimpleNamespace(MAP_NAMES={})

        class Ctx:
            read = realmread.Memory(
                {
                    guild_api._GUILD_SQL: [{"guildid": 23, "name": "Cave"}],
                    guild_api._NOW_SQL: [{"now": NOW}],
                    presence._SNAP_SQL: [],
                    presence._FLAGS_SQL: [],
                    guild_api._MEMBERS_SQL: [
                        {
                            "guid": 1,
                            "name": "Grug",
                            "level": 60,
                            "class": 1,
                            "race": 1,
                            "zone": 40,
                            "rank": 0,
                        },
                        {
                            "guid": 2,
                            "name": "Mid",
                            "level": 20,
                            "class": 9,
                            "race": 3,
                            "zone": 40,
                            "rank": 4,
                        },
                    ],
                    guild_api._DINGS_SQL: [],
                    guild_api._KILLERS_SQL: [],
                    guild_api._DEATH_TOTAL_SQL: [{"n": 0, "who": 0}],
                    guild_api._LAST_DEATH_SQL: [],
                    guild_api._CQ_DONE_SQL: [{"n": 0, "who": 0}],
                    guild_api._CQ_OPEN_SQL: [],
                    guild_api._CQ_STEPS_SQL: [],
                    guildrun._RUN_SQL: [],
                }
            )
            server = Server
            families = types.SimpleNamespace(
                guilds=lambda: [{"name": "Cave", "family": "grug"}]
            )

        code, body = guild_api.guild({"guild": ["cave"]}, Ctx)
        self.assertEqual(200, code)
        self.assertIn("ranks", body)
        self.assertEqual({0: 1, 4: 1}, body["ranks"]["counts"])
        self.assertEqual(1, body["ranks"]["pending_promotions"])

    def test_design_doc_names_pinned_playerbots_and_module_sources(self):
        pins = (ROOT / "UPSTREAM-PINS.env").read_text(encoding="utf-8")
        sha = re.search(r"^AC_MODULE_SHA=(\S+)", pins, re.M)
        self.assertIsNotNone(sha)
        doc = (ROOT / "docs/design/guild-rank-motd.md").read_text(encoding="utf-8")
        for needle in (
            sha.group(1),
            "GuildManagementActions.cpp",
            "GuildPromoteAction",
            "GuildVerb",
            "ChangeMemberRank",
            "HandleSetMOTD",
        ):
            self.assertIn(needle, doc)


if __name__ == "__main__":
    unittest.main()
