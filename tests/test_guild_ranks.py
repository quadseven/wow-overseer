"""Tests for guild rank promotion and MOTD policy (#2616)."""

from __future__ import annotations

import re
import types
import unittest

import apiv2.guild as guild_api
import apiv2.presence as presence
import guildranks
import guildrun
import modsource
import raidteams
import realmread

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
        header = modsource.read(modsource.DECISIONS_H)
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

    def test_sanitize_motd_preserves_ordinary_text_and_caps_bytes(self):
        ordinary = "Clear Deadmines | cff00ff00 tonight (2x)!"
        self.assertEqual(ordinary, guildranks._sanitize_motd(ordinary))
        self.assertEqual(
            f"motd {ordinary}",
            guildranks.motd_command(f"  {ordinary}  "),
        )
        truncated = guildranks._sanitize_motd("a" * (guildranks.MAX_MOTD_BYTES + 20))
        self.assertEqual(guildranks.MAX_MOTD_BYTES, len(truncated))
        self.assertTrue(truncated.endswith("..."))

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


class GuildApiAndPolicyTests(unittest.TestCase):
    def _ctx(self, motd: str, active_goal_rows: list):
        class Server:
            recap = types.SimpleNamespace(zone_names=lambda c: {40: "Westfall"})
            GEO = types.SimpleNamespace(continents={})
            achievements = types.SimpleNamespace(MAP_NAMES={})

        class Ctx:
            read = realmread.Memory(
                {
                    guild_api._GUILD_SQL: [
                        {"guildid": 23, "name": "Cave", "motd": motd}
                    ],
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
                    guild_api._ACTIVE_GOAL_SQL: active_goal_rows,
                    guildrun._RUN_SQL: [],
                }
            )
            server = Server
            families = types.SimpleNamespace(
                guilds=lambda: [{"name": "Cave", "family": "grug"}]
            )

        return Ctx

    def test_apiv2_guild_exposes_rank_counts_and_desired_motd(self):
        ctx = self._ctx(
            "No message set.",
            [
                {
                    "kind": "guild_count",
                    "skill_name": "deadmines",
                    "target": 5,
                    "guild": "Cave",
                }
            ],
        )
        code, body = guild_api.guild({"guild": ["cave"]}, ctx)
        self.assertEqual(200, code)
        self.assertEqual({0: 1, 4: 1}, body["ranks"]["counts"])
        self.assertEqual(1, body["ranks"]["pending_promotions"])
        self.assertEqual("No message set.", body["ranks"]["current_motd"])
        self.assertEqual(
            "Cave goal: clear deadmines (5x)", body["ranks"]["desired_motd"]
        )

        # Without an active goal row, raid guilds still carry their raid keyword MOTD.
        fallback_ctx = self._ctx("", [])
        code, body = guild_api.guild({"guild": ["cave"]}, fallback_ctx)
        self.assertEqual(200, code)
        self.assertEqual("", body["ranks"]["current_motd"])
        self.assertEqual("Cave goal: raid mc", body["ranks"]["desired_motd"])

    def test_banker_seats_are_excluded_from_promotion_plans_and_summary(self):
        banker = sorted(raidteams.banker_names("Cave"))[0]
        members = [
            _member("Grug", 60, guildranks.RANK_MASTER, online=True),
            _member(banker, 60, guildranks.RANK_INITIATE),
            _member("Eligible", 25, guildranks.RANK_INITIATE),
        ]
        actions = guildranks.plan_actions(
            "Cave",
            master="Grug",
            members=members,
            raid_seats=frozenset(),
        )
        self.assertEqual(
            [("promote", "Eligible")], [(a.verb, a.target) for a in actions]
        )
        summary = guildranks.summarize_ranks("Cave", members, raid_seats=frozenset())
        self.assertEqual(1, summary["pending_promotions"])

    def test_plan_actions_caps_per_pass_and_skips_matching_motd(self):
        members = [_member("Grug", 60, guildranks.RANK_MASTER, online=True)]
        members.extend(
            _member(f"Alt{i:02d}", 25, guildranks.RANK_INITIATE) for i in range(8)
        )
        actions = guildranks.plan_actions(
            "Cave",
            master="Grug",
            members=members,
            current_motd="Cave goal: raid mc",
            raid_keyword="mc",
            raid_seats=frozenset(),
        )
        promotes = [a for a in actions if a.verb == "promote"]
        self.assertEqual(guildranks.PROMOTES_PER_PASS, len(promotes))
        self.assertEqual([], [a for a in actions if a.verb == "motd"])


if __name__ == "__main__":
    unittest.main()
