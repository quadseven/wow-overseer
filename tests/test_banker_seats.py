"""The guild bankers hold seats the way the questers do: named, recruited at a
rotating bot, reset to level 1, and never placed in the raid or on the kick list.

Two per guild, in the race whose start lies nearest its faction's own vault
city. They never raid, level, quest or join a group, so the lineup, the
summoner and maintenance lists and the kick list must all leave them out.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import raidlineup  # noqa: E402
import raidteams  # noqa: E402
import teamsync  # noqa: E402

RNDBOT = 1
GUILDS = ("Cave", "Bonkers")


def _row(b, level=1, name=""):
    return {
        "name": name or b.name,
        "class_id": b.class_id,
        "race": teamsync.RACE_IDS[b.race],
        "level": level,
    }


def _full_guild(guild):
    out = []
    for s in raidteams.seats(guild):
        out.append(
            {
                "name": s.name,
                "class_id": s.class_id,
                "level": 60,
                "race": teamsync.RACE_IDS[s.race],
            }
        )
    for _old, new in raidteams.SUMMONERS[guild] + raidteams.MAINTENANCE[guild]:
        out.append({"name": new, "class_id": 9, "race": 5, "level": 60})
    for q in raidteams.QUESTERS[guild]:
        out.append(
            {
                "name": q.name,
                "class_id": q.class_id,
                "level": 1,
                "race": teamsync.RACE_IDS[q.race],
            }
        )
    return out


class TheBankersAreApproved(unittest.TestCase):
    def test_two_per_guild(self):
        for guild in GUILDS:
            self.assertEqual(2, len(raidteams.BANKERS[guild]))

    def test_names_are_unique_across_every_table(self):
        everything = []
        for guild in GUILDS:
            everything += sorted(raidteams.banker_names(guild))
            everything += sorted(raidteams.quester_names(guild))
            everything += [s.name for s in raidteams.seats(guild)]
        self.assertEqual(len(everything), len(set(everything)))

    def test_a_guild_names_its_bankers(self):
        for guild in GUILDS:
            self.assertLessEqual(
                raidteams.banker_names(guild), raidteams.names_of(guild)
            )

    def test_both_bankers_of_a_guild_start_in_one_zone(self):
        for guild in GUILDS:
            self.assertEqual(1, len({b.zone for b in raidteams.BANKERS[guild]}))

    def test_a_banker_race_is_one_the_teams_can_match(self):
        for guild in GUILDS:
            for b in raidteams.BANKERS[guild]:
                self.assertIn(b.race, teamsync.RACE_IDS)


class TheLineupLeavesThemAlone(unittest.TestCase):
    def test_a_banker_is_not_on_the_kick_list(self):
        for guild in GUILDS:
            members = _full_guild(guild) + [_row(b) for b in raidteams.BANKERS[guild]]
            lineup = raidlineup.build_lineup(members, guaranteed=[])
            kicked = {m["name"] for m in lineup["surplus"]}
            self.assertFalse(kicked & raidteams.banker_names(guild))
            self.assertEqual(
                sorted(raidteams.banker_names(guild)),
                sorted(m["name"] for m in lineup["bankers"]),
            )
            self.assertEqual(2, lineup["counts"]["bankers"])

    def test_a_banker_holds_no_raid_seat(self):
        guild = "Cave"
        members = _full_guild(guild) + [_row(b) for b in raidteams.BANKERS[guild]]
        lineup = raidlineup.build_lineup(members, guaranteed=[])
        seated = {m["name"] for g in lineup["groups"] for m in g["members"]}
        self.assertFalse(seated & raidteams.banker_names(guild))


class TheTeamSyncSeatsThem(unittest.TestCase):
    def test_a_banker_seat_is_open_until_a_member_holds_the_name(self):
        guild = "Cave"
        opens = teamsync.open_seats(guild, [m["name"] for m in _full_guild(guild)])
        self.assertEqual(
            sorted(raidteams.banker_names(guild)), sorted(s.name for s in opens)
        )

    def test_a_rotating_bot_of_the_seat_race_and_class_is_invited(self):
        guild = "Bonkers"
        b = raidteams.BANKERS[guild][0]
        candidate = dict(_row(b, level=34, name="Randomtauren"), account_type=RNDBOT)
        acts = teamsync.plan(guild, _full_guild(guild), [candidate], set(), True)
        self.assertEqual(
            [("invite", "Randomtauren")], [(a.kind, a.target) for a in acts]
        )

    def test_a_banker_in_the_guild_is_renamed_then_reset_to_level_one(self):
        guild = "Cave"
        b = raidteams.BANKERS[guild][0]
        held = _full_guild(guild) + [_row(b, level=40, name="Randomdwarf")]
        acts = teamsync.plan(guild, held, [], set(), True, reset_done=set())
        self.assertIn(
            ("rename", "Randomdwarf", b.name),
            [(a.kind, a.target, a.new_name) for a in acts],
        )
        named = _full_guild(guild) + [_row(b, level=40)]
        done = raidteams.quester_names(guild)
        acts = teamsync.plan(guild, named, [], set(), True, reset_done=done)
        self.assertIn(
            ("reset", b.name, "reset-level-1"),
            [(a.kind, a.target, a.command) for a in acts],
        )

    def test_the_guild_has_room_for_the_bankers(self):
        self.assertEqual(83, teamsync.GUILD_SIZE)
        for guild in GUILDS:
            self.assertEqual(83, len(_full_guild(guild)) + 2)


if __name__ == "__main__":
    unittest.main()
