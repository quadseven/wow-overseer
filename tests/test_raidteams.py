"""The approved raid teams (raidteams, 2026-10-05) and how the lineup seats
them: the operator's Molten Core lineup, not the generic five-man shape."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import guildwork  # noqa: E402
import raidlineup  # noqa: E402
import raidroles  # noqa: E402
import raidteams  # noqa: E402


def _guild(team, renamed=False, recruits_joined=False):
    """Members of `team` as the guild holds them: by their current names
    until the rename, and with no recruit until one joins."""
    out = []
    for s in raidteams.seats(team):
        if not s.was and s.name not in _family(team) and not recruits_joined:
            continue
        name = s.name if (renamed or not s.was) else s.was
        out.append({"name": name, "level": 20, "class_id": s.class_id})
    for pairs in (raidteams.SUMMONERS[team], raidteams.MAINTENANCE[team]):
        for old, new in pairs:
            out.append({"name": new if renamed else old, "level": 20, "class_id": 9})
    for name in raidteams.LEAVING[team]:
        out.append({"name": name, "level": 15, "class_id": 4})
    return out


def _family(team):
    return {s.name for s in raidteams.GROUPS[team][0]}


class TheTeams(unittest.TestCase):
    def test_each_raid_is_8_tanks_11_healers_21_damage(self):
        for team in raidteams.GROUPS:
            seats = [s.seat for s in raidteams.seats(team)]
            self.assertEqual(seats.count(raidroles.SEAT_TANK), 8, team)
            self.assertEqual(seats.count(raidroles.SEAT_HEALER), 11, team)
            self.assertEqual(seats.count(raidroles.SEAT_DAMAGE), 21, team)

    def test_every_group_has_a_fire_resistance_source(self):
        for team, groups in raidteams.GROUPS.items():
            for number, group in enumerate(groups, start=1):
                self.assertTrue(
                    any(s.fire_resistance for s in group),
                    "%s group %d" % (team, number),
                )

    def test_groups_two_to_eight_are_named_by_letter(self):
        for team, groups in raidteams.GROUPS.items():
            for number, group in enumerate(groups[1:], start=2):
                letter = "ABCDEFGH"[number - 1]
                for s in group:
                    self.assertTrue(s.name.startswith(letter), (team, number, s.name))

    def test_coom_is_an_orc_enhancement_shaman_in_bonkers(self):
        coom = [s for s in raidteams.seats("Bonkers") if s.name == "Coom"]
        self.assertEqual(len(coom), 1)
        self.assertEqual(
            (coom[0].class_id, coom[0].tree, coom[0].race), (7, "Enhancement", "Orc")
        )

    def test_21_summoners_and_10_maintenance(self):
        for team in raidteams.GROUPS:
            self.assertEqual(len(raidteams.SUMMONERS[team]), 21)
            self.assertEqual(len(raidteams.MAINTENANCE[team]), 10)

    def test_a_guild_is_known_by_its_names(self):
        self.assertEqual(raidteams.guild_of(["Grug", "Bonk", "Crag"]), "Cave")
        self.assertEqual(raidteams.guild_of(["Zug", "Velalenn"]), "Bonkers")
        self.assertEqual(raidteams.guild_of(["Warrior0", "Priest1"]), "")


class TheLineupSeatsTheApprovedTeams(unittest.TestCase):
    def test_before_the_rename_members_are_seated_under_their_names_now(self):
        lineup = raidlineup.build_lineup(_guild("Cave"))
        self.assertEqual(lineup["approved"], "Cave")
        group2 = lineup["groups"][1]["members"]
        aalall = [m for m in group2 if m["name"] == "Aalall"][0]
        self.assertEqual(aalall["approved_name"], "Brug")
        self.assertEqual(aalall["duty"], "off tank")

    def test_after_the_rename_the_same_seats_hold(self):
        before = raidlineup.build_lineup(_guild("Bonkers"))
        after = raidlineup.build_lineup(_guild("Bonkers", renamed=True))
        self.assertEqual(
            [[m["approved_name"] for m in g["members"]] for g in before["groups"]],
            [[m["approved_name"] for m in g["members"]] for g in after["groups"]],
        )

    def test_recruits_not_yet_joined_are_open_seats(self):
        lineup = raidlineup.build_lineup(_guild("Bonkers"))
        self.assertIn("Coom", [r["name"] for r in lineup["recruits"]])
        self.assertEqual(lineup["counts"]["raiders"], 30)
        joined = raidlineup.build_lineup(_guild("Bonkers", recruits_joined=True))
        self.assertEqual(joined["counts"]["raiders"], 40)
        self.assertEqual(joined["recruits"], [])

    def test_the_leavers_are_the_kick_list(self):
        lineup = raidlineup.build_lineup(_guild("Cave"))
        self.assertEqual(
            sorted(m["name"] for m in lineup["surplus"]),
            sorted(raidteams.LEAVING["Cave"]),
        )

    def test_nobody_respecs(self):
        lineup = raidlineup.build_lineup(_guild("Cave", recruits_joined=True))
        self.assertEqual(lineup["counts"]["respec"], 0)

    def test_the_family_is_group_one(self):
        lineup = raidlineup.build_lineup(_guild("Cave"))
        self.assertEqual(
            {m["name"] for m in lineup["groups"][0]["members"]},
            {"Grug", "Ugga", "Grog", "Bork", "Og"},
        )


def _questers(team):
    return [
        {"name": q.name, "level": 1, "class_id": q.class_id}
        for q in raidteams.QUESTERS[team]
    ]


class TheQuestersHoldNoRaidSeat(unittest.TestCase):
    """#927: the questers are guild members, and nothing the raid places."""

    def test_no_quester_name_is_a_raid_summoner_maintenance_or_leaving_name(self):
        for team in raidteams.QUESTERS:
            others = set()
            for s in raidteams.seats(team):
                others.update((s.name, s.was))
            for pairs in (raidteams.SUMMONERS[team], raidteams.MAINTENANCE[team]):
                for old, new in pairs:
                    others.update((old, new))
            others.update(raidteams.LEAVING[team])
            self.assertEqual(raidteams.quester_names(team) & others, set(), team)

    def test_the_guild_is_still_known_with_its_questers(self):
        names = [m["name"] for m in _guild("Cave", True, True) + _questers("Cave")]
        self.assertEqual(raidteams.guild_of(names), "Cave")

    def test_the_lineup_seats_40_and_lists_the_questers_apart(self):
        for team in raidteams.QUESTERS:
            lineup = raidlineup.build_lineup(
                _guild(team, renamed=True, recruits_joined=True) + _questers(team)
            )
            questers = raidteams.quester_names(team)
            placed = {m["name"] for g in lineup["groups"] for m in g["members"]}
            self.assertEqual(lineup["counts"]["raiders"], 40, team)
            self.assertEqual(placed & questers, set(), team)
            self.assertEqual(
                {m["name"] for m in lineup["summoners"] + lineup["maintenance"]}
                & questers,
                set(),
            )
            self.assertEqual({m["name"] for m in lineup["questers"]}, questers)
            self.assertEqual({m["role"] for m in lineup["questers"]}, {"quester"})
            self.assertEqual(lineup["counts"]["questers"], 5)

    def test_a_quester_is_not_on_the_kick_list(self):
        lineup = raidlineup.build_lineup(_guild("Cave") + _questers("Cave"))
        self.assertEqual(
            sorted(m["name"] for m in lineup["surplus"]),
            sorted(raidteams.LEAVING["Cave"]),
        )

    def test_a_quester_warlock_is_no_summoner_in_any_lineup(self):
        # A guild without an approved lineup takes its warlocks as summoners.
        members = [{"name": "Grakk", "level": 1, "class_id": 9}] + [
            {"name": "Lock%s" % c, "level": 20, "class_id": 9} for c in "abc"
        ]
        lineup = raidlineup.build_lineup(members)
        self.assertNotIn("Grakk", [m["name"] for m in lineup["summoners"]])
        self.assertNotIn("Grakk", [m["name"] for m in lineup["surplus"]])
        self.assertEqual([m["name"] for m in lineup["questers"]], ["Grakk"])

    def test_a_quester_gets_no_guild_job(self):
        rows = [
            dict(m, guild_name="Bonkers", money=0, online=0)
            for m in _guild("Bonkers", renamed=True, recruits_joined=True)
            + _questers("Bonkers")
        ]
        members, _masters = guildwork.members_from_rows(rows, ["Zug"])
        roles = {m.name: m.role for m in members}
        self.assertEqual(set(roles) & raidteams.quester_names("Bonkers"), set())
        self.assertIn("Coom", roles)


if __name__ == "__main__":
    unittest.main()
