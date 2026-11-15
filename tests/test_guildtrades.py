"""The raid seats' profession plan, as data (slice 2 of the raid-seat plan).

Pure tests against guildtrades: the pair table, the rule that fills it from the
approved seats, and what the rule keeps. They read the real approved seat list
(raidteams.GROUPS), as the plan does, and import nothing but pure modules.
"""

import unittest

import guildtrades
import raidteams

H, M, S = guildtrades.HERBALISM, guildtrades.MINING, guildtrades.SKINNING
ALCH, ENG = guildtrades.ALCHEMY, guildtrades.ENGINEERING
SMITH, LW = guildtrades.BLACKSMITHING, guildtrades.LEATHERWORKING
TAIL, ENCH = guildtrades.TAILORING, guildtrades.ENCHANTING

TABLE = {
    (H, ALCH): 8,
    (H, M): 8,
    (M, ENG): 6,
    (M, SMITH): 6,
    (S, LW): 6,
    (TAIL, ENCH): 6,
}


def pair_counts(assigned):
    counts = {}
    for pair in assigned.values():
        key = tuple(sorted(pair))
        counts[key] = counts.get(key, 0) + 1
    return counts


def table_key(pair):
    return tuple(sorted(pair))


class TheTable(unittest.TestCase):
    def test_the_targets_are_the_ones_the_plan_names(self):
        got = {table_key(p.skills): p.seats for p in guildtrades.PAIRS}
        self.assertEqual({table_key(k): v for k, v in TABLE.items()}, got)

    def test_the_targets_fill_a_guilds_forty_seats(self):
        self.assertEqual(40, sum(p.seats for p in guildtrades.PAIRS))
        for guild in raidteams.GROUPS:
            self.assertEqual(40, len(raidteams.seats(guild)))

    def test_every_pair_is_two_distinct_primary_trades(self):
        for p in guildtrades.PAIRS:
            self.assertEqual(2, len(set(p.skills)), p)
            self.assertTrue(set(p.skills) <= guildtrades.PRIMARIES, p)


class TheRuleOnTheApprovedSeats(unittest.TestCase):
    def test_each_guilds_forty_seats_cover_the_table_exactly(self):
        for guild in sorted(raidteams.GROUPS):
            with self.subTest(guild=guild):
                got = guildtrades.assign(guild)
                self.assertEqual({s.name for s in raidteams.seats(guild)}, set(got))
                self.assertEqual(
                    {table_key(k): v for k, v in TABLE.items()}, pair_counts(got)
                )

    def test_a_seat_has_at_most_two_primaries(self):
        for guild in sorted(raidteams.GROUPS):
            for name, pair in guildtrades.assign(guild).items():
                self.assertLessEqual(len(pair), 2, name)
                self.assertEqual(len(set(pair)), len(pair), name)

    def test_a_second_run_gives_the_same_answer(self):
        for guild in sorted(raidteams.GROUPS):
            self.assertEqual(guildtrades.assign(guild), guildtrades.assign(guild))

    def test_every_crafter_has_its_gatherer_in_the_pair(self):
        feeds = {
            ALCH: H,
            ENG: M,
            SMITH: M,
            LW: S,
        }
        for guild in sorted(raidteams.GROUPS):
            for pair in guildtrades.assign(guild).values():
                for craft, gather in feeds.items():
                    if craft in pair:
                        self.assertIn(gather, pair)

    def test_the_alchemy_seats_are_healers_where_the_guild_has_enough(self):
        for guild in sorted(raidteams.GROUPS):
            healers = [
                s
                for s in raidteams.seats(guild)
                if s.class_id in guildtrades.HEALER_CLASSES
            ]
            self.assertGreaterEqual(len(healers), 8, guild)
            by_name = {s.name: s for s in raidteams.seats(guild)}
            for name, pair in guildtrades.assign(guild).items():
                if ALCH in pair:
                    self.assertIn(by_name[name].class_id, guildtrades.HEALER_CLASSES)

    def test_the_smiths_wear_plate_and_the_tailors_wear_cloth(self):
        for guild in sorted(raidteams.GROUPS):
            by_name = {s.name: s for s in raidteams.seats(guild)}
            for name, pair in guildtrades.assign(guild).items():
                if SMITH in pair:
                    self.assertIn(by_name[name].class_id, (1, 2, 6), name)
                if ENCH in pair:
                    self.assertIn(by_name[name].class_id, (5, 8, 9), name)


def live_for(guild, level=30, held=None):
    held = held or {}
    return {
        s.name: guildtrades.Seen(level, frozenset(held.get(s.name, ())))
        for s in raidteams.seats(guild)
    }


class WhatTheRuleKeeps(unittest.TestCase):
    guild = "Bonkers"

    def non_family(self):
        return [s for s in raidteams.seats(self.guild)][5:]

    def test_a_seat_keeps_a_trade_it_already_holds(self):
        seat = self.non_family()[0]
        got = guildtrades.assign(
            self.guild, live_for(self.guild, held={seat.name: {SMITH}})
        )
        self.assertEqual(table_key((M, SMITH)), table_key(got[seat.name]))

    def test_a_held_pair_is_kept_whole(self):
        seat = self.non_family()[1]
        got = guildtrades.assign(
            self.guild, live_for(self.guild, held={seat.name: {H, M}})
        )
        self.assertEqual(table_key((H, M)), table_key(got[seat.name]))

    def test_two_trades_that_are_no_pair_are_kept_as_they_are(self):
        seat = self.non_family()[2]
        got = guildtrades.assign(
            self.guild, live_for(self.guild, held={seat.name: {H, S}})
        )
        self.assertEqual(table_key((H, S)), table_key(got[seat.name]))

    def test_a_seat_that_holds_a_trade_takes_a_slot_of_its_pair(self):
        seats = self.non_family()
        held = {s.name: {ENCH} for s in seats[:3]}
        got = guildtrades.assign(self.guild, live_for(self.guild, held=held))
        for s in seats[:3]:
            self.assertEqual(table_key((TAIL, ENCH)), table_key(got[s.name]))
        # The table's other targets are met around them.
        counts = pair_counts(got)
        self.assertEqual(6, counts[table_key((TAIL, ENCH))])

    def test_a_trade_outside_the_table_is_kept_alone(self):
        seat = self.non_family()[3]
        got = guildtrades.assign(
            self.guild, live_for(self.guild, held={seat.name: {755}})
        )
        self.assertEqual((755,), got[seat.name])

    def test_the_lowest_level_seat_is_filled_first_within_a_preference(self):
        healers = [
            s for s in self.non_family() if s.class_id in guildtrades.HEALER_CLASSES
        ]
        live = live_for(self.guild, level=40)
        low = healers[-1]
        live[low.name] = guildtrades.Seen(12, frozenset())
        got = guildtrades.assign(self.guild, live)
        self.assertIn(ALCH, got[low.name])

    def test_a_renamed_seat_is_found_under_the_name_it_has_now(self):
        renamed = [s for s in raidteams.seats(self.guild) if s.was]
        if not renamed:
            self.skipTest("no approved seat is waiting on a rename")
        seat = renamed[0]
        live = {seat.was: guildtrades.Seen(30, frozenset({M}))}
        got = guildtrades.assign(self.guild, live)
        self.assertIn(seat.was, got)
        self.assertNotIn(seat.name, got)
        self.assertIn(M, got[seat.was])

    def test_a_guild_with_no_approved_seats_is_given_nothing(self):
        self.assertEqual({}, guildtrades.assign("Nobody"))

    def test_guild_names_match_without_regard_to_case(self):
        self.assertEqual(guildtrades.assign("bonkers"), guildtrades.assign("Bonkers"))


if __name__ == "__main__":
    unittest.main()
