"""The guild-wide profession plan, as data.

Pure tests against guildtrades: the one mix both guilds follow, the rule that
fills it from the approved raid seats and the guild maintenance characters,
and what the rule keeps, never touches and never drops. They read the real
approved lineup (raidteams), as the plan does, and import nothing but pure
modules.
"""

import unittest

import guildtrades
import raidteams

H, M, S = guildtrades.HERBALISM, guildtrades.MINING, guildtrades.SKINNING
ALCH, ENG = guildtrades.ALCHEMY, guildtrades.ENGINEERING
SMITH, LW = guildtrades.BLACKSMITHING, guildtrades.LEATHERWORKING
TAIL, ENCH = guildtrades.TAILORING, guildtrades.ENCHANTING

# Per guild of fifty (forty seats and ten maintenance characters), the same for
# both: see the derivation in guildtrades.py.
MIX = {
    (H, ALCH): 18,
    (S, LW): 8,
    (M, SMITH): 7,
    (TAIL, ENCH): 7,
    (M, ENG): 3,
    (H, M): 7,
}
FEEDS = {ALCH: H, SMITH: M, ENG: M, LW: S}


def key(pair):
    return tuple(sorted(pair))


def mix_key():
    return {key(k): v for k, v in MIX.items()}


def counts(assigned):
    out = {}
    for pair in assigned.values():
        out[key(pair)] = out.get(key(pair), 0) + 1
    return out


def family_of(guild):
    return [s.name for s in raidteams.GROUPS[guild][0]]


def maintenance_of(guild):
    return [new for _old, new in raidteams.MAINTENANCE[guild]]


def planned(guild):
    return [s.name for s in raidteams.seats(guild)] + maintenance_of(guild)


def live_for(guild, level=30, held=None, values=None):
    """Everyone planned holds nothing, but for `held` (name -> trades); the
    family hold a Herbalism and Alchemy pair, so they count against the mix."""
    held = dict(held or {})
    for name in family_of(guild):
        held.setdefault(name, {H, ALCH})
    values = values or {}
    return {
        name: guildtrades.Seen(
            level, frozenset(held.get(name, ())), dict(values.get(name, {}))
        )
        for name in planned(guild)
    }


class TheMix(unittest.TestCase):
    def test_the_counts_are_the_ones_the_derivation_names(self):
        got = {key(p.skills): p.seats for p in guildtrades.PAIRS}
        self.assertEqual(mix_key(), got)

    def test_the_mix_fills_a_guilds_fifty_characters(self):
        self.assertEqual(50, sum(p.seats for p in guildtrades.PAIRS))
        for guild in raidteams.GROUPS:
            self.assertEqual(40, len(raidteams.seats(guild)))
            self.assertEqual(10, len(raidteams.MAINTENANCE[guild]))

    def test_alchemy_has_the_most_seats(self):
        by_size = sorted(guildtrades.PAIRS, key=lambda p: -p.seats)
        self.assertIn(ALCH, by_size[0].skills)
        self.assertGreater(by_size[0].seats, by_size[1].seats)

    def test_every_crafter_is_paired_with_the_trade_that_feeds_it(self):
        for p in guildtrades.PAIRS:
            self.assertEqual(2, len(set(p.skills)), p)
            self.assertTrue(set(p.skills) <= guildtrades.PRIMARIES, p)
            for craft, gather in FEEDS.items():
                if craft in p.skills:
                    self.assertIn(gather, p.skills)
            if ENCH in p.skills:
                self.assertIn(TAIL, p.skills)

    def test_only_the_pure_gatherers_are_two_gathering_trades(self):
        for p in guildtrades.PAIRS:
            if set(p.skills) <= guildtrades.GATHERING:
                self.assertEqual({H, M}, set(p.skills))


class TheComposition(unittest.TestCase):
    def test_a_guild_is_its_forty_seats_and_its_maintenance_characters(self):
        for guild in sorted(raidteams.GROUPS):
            names = {m.name for m in guildtrades.members_of(guild, {})}
            self.assertEqual(set(planned(guild)), names)

    def test_summoners_and_questers_are_never_assigned(self):
        for guild in sorted(raidteams.GROUPS):
            live = live_for(guild)
            left_out = [new for _old, new in raidteams.SUMMONERS[guild]]
            left_out += [q.name for q in raidteams.QUESTERS[guild]]
            for name in left_out:
                live[name] = guildtrades.Seen(30, frozenset())
            got = guildtrades.assign(guild, live)
            self.assertEqual(set(planned(guild)), set(got))
            self.assertFalse(set(left_out) & set(got))

    def test_a_guild_with_no_approved_seats_is_given_nothing(self):
        self.assertEqual({}, guildtrades.assign("Nobody"))

    def test_guild_names_match_without_regard_to_case(self):
        self.assertEqual(guildtrades.assign("bonkers"), guildtrades.assign("Bonkers"))


class TheRule(unittest.TestCase):
    def test_both_guilds_get_exactly_the_mix(self):
        for guild in sorted(raidteams.GROUPS):
            with self.subTest(guild=guild):
                got = guildtrades.assign(guild, live_for(guild))
                self.assertEqual(mix_key(), counts(got))

    def test_both_guilds_get_the_same_mix(self):
        cave = counts(guildtrades.assign("Cave", live_for("Cave")))
        bonkers = counts(guildtrades.assign("Bonkers", live_for("Bonkers")))
        self.assertEqual(cave, bonkers)

    def test_a_second_run_gives_the_same_answer(self):
        for guild in sorted(raidteams.GROUPS):
            live = live_for(guild)
            self.assertEqual(
                guildtrades.assign(guild, live), guildtrades.assign(guild, live)
            )

    def test_a_character_has_at_most_two_primaries(self):
        for guild in sorted(raidteams.GROUPS):
            for name, pair in guildtrades.assign(guild, live_for(guild)).items():
                self.assertLessEqual(len(pair), 2, name)
                self.assertEqual(len(set(pair)), len(pair), name)

    def test_the_maintenance_characters_take_crafts_not_pure_gathering(self):
        for guild in sorted(raidteams.GROUPS):
            got = guildtrades.assign(guild, live_for(guild))
            for name in maintenance_of(guild):
                self.assertNotEqual(key((H, M)), key(got[name]), name)

    def test_the_alchemists_are_healers_and_casters_where_there_are_enough(self):
        for guild in sorted(raidteams.GROUPS):
            by_name = {s.name: s for s in raidteams.seats(guild)}
            got = guildtrades.assign(guild, live_for(guild))
            family = set(family_of(guild))
            for name, pair in got.items():
                if ALCH in pair and name in by_name and name not in family:
                    self.assertIn(
                        by_name[name].class_id,
                        guildtrades.HEALER_CLASSES | guildtrades.CASTER_CLASSES,
                        name,
                    )


class WhatTheRuleKeeps(unittest.TestCase):
    guild = "Bonkers"

    def free_seats(self):
        family = set(family_of(self.guild))
        return [s.name for s in raidteams.seats(self.guild) if s.name not in family]

    def assign(self, held, values=None):
        return guildtrades.assign(
            self.guild, live_for(self.guild, held=held, values=values)
        )

    def test_a_held_pair_is_kept_whole(self):
        name = self.free_seats()[0]
        got = self.assign({name: {M, SMITH}})
        self.assertEqual(key((M, SMITH)), key(got[name]))

    def test_a_seat_that_holds_a_trade_takes_a_pair_that_contains_it(self):
        names = self.free_seats()[:3]
        got = self.assign({n: {ENCH} for n in names})
        for n in names:
            self.assertEqual(key((TAIL, ENCH)), key(got[n]))

    def test_a_gatherer_takes_the_craft_it_feeds_and_drops_nothing(self):
        names = self.free_seats()[:3]
        got = self.assign({names[0]: {H}, names[1]: {S}, names[2]: {M}})
        self.assertIn(ALCH, got[names[0]])
        self.assertIn(LW, got[names[1]])
        self.assertTrue({SMITH, ENG} & set(got[names[2]]))
        for n, trade in zip(names, (H, S, M)):
            self.assertIn(trade, got[n])
        live = live_for(self.guild, held={names[0]: {H}})
        self.assertNotIn(names[0], guildtrades.drops(self.guild, live))

    def test_two_crafts_that_are_no_pair_are_kept_as_they_are(self):
        name = self.free_seats()[1]
        got = self.assign({name: {ALCH, LW}})
        self.assertEqual(key((ALCH, LW)), key(got[name]))

    def test_a_craft_is_never_dropped_to_fit_the_mix(self):
        for guild in sorted(raidteams.GROUPS):
            family = set(family_of(guild))
            seats = [n for n in planned(guild) if n not in family]
            # Everybody holds one craft and one gatherer that is not its feeder.
            held = {}
            for i, n in enumerate(seats):
                craft = (ALCH, SMITH, LW, ENCH)[i % 4]
                gather = {ALCH: S, SMITH: H, LW: M, ENCH: H}[craft]
                held[n] = {craft, gather}
            live = live_for(guild, held=held)
            got = guildtrades.assign(guild, live)
            for n, trades in held.items():
                for craft in trades & guildtrades.CRAFTS:
                    self.assertIn(craft, got[n], n)

    def test_the_family_keeps_exactly_what_it_holds(self):
        for guild in sorted(raidteams.GROUPS):
            names = family_of(guild)
            held = {names[0]: {S, M}, names[1]: {H}, names[2]: set()}
            live = live_for(guild, held=held)
            got = guildtrades.assign(guild, live)
            for n in names[:3]:
                self.assertEqual(key(held[n]), key(got[n]), n)
            gone = guildtrades.drops(guild, live)
            self.assertFalse(set(names) & set(gone))

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


class WhatTheRuleGivesUp(unittest.TestCase):
    """Two gathering trades that fit no pair: one is given up, the cheaper."""

    guild = "Cave"

    def crowd(self, skills):
        """Every non-family seat holds Skinning and Mining (no pair): the mix
        cannot hold them all, so some must give one up."""
        family = set(family_of(self.guild))
        names = [n for n in planned(self.guild) if n not in family]
        held = {n: {S, M} for n in names}
        values = {n: {S: skills.get(n, 10), M: 40} for n in names}
        return names, live_for(self.guild, held=held, values=values)

    def test_the_trade_with_the_higher_skill_is_kept_where_a_choice_exists(self):
        names, live = self.crowd({})
        name = names[0]
        live[name] = guildtrades.Seen(30, frozenset({S, M}), {S: 200, M: 5})
        got = guildtrades.assign(self.guild, live)
        self.assertIn(S, got[name])

    def test_a_gathering_trade_above_the_guard_is_never_dropped(self):
        names, live = self.crowd({})
        for n in names:
            live[n] = guildtrades.Seen(30, frozenset({S, M}), {S: 120, M: 130})
        got = guildtrades.assign(self.guild, live)
        for n in names:
            self.assertEqual(key((S, M)), key(got[n]), n)
        self.assertEqual({}, guildtrades.drops(self.guild, live, got))
        self.assertEqual({}, guildtrades.guarded(self.guild, live, got))

    def test_the_mix_adds_up_around_the_characters_that_keep_both_trades(self):
        names, live = self.crowd({})
        high = names[:5]
        for n in high:
            live[n] = guildtrades.Seen(30, frozenset({H, S}), {H: 107, S: 20})
        got = guildtrades.assign(self.guild, live)
        for n in high:
            self.assertEqual(key((H, S)), key(got[n]), n)
        others = {n: p for n, p in got.items() if n not in high}
        self.assertEqual(45, len(others))
        self.assertEqual(
            guildtrades.PAIRS[-1].seats - 5, counts(others).get(key((H, M)), 0)
        )
        self.assertEqual(18, counts(others).get(key((H, ALCH)), 0))

    def test_a_craft_and_a_high_gatherer_are_kept_whole(self):
        names, live = self.crowd({})
        n = names[0]
        live[n] = guildtrades.Seen(30, frozenset({ALCH, S}), {ALCH: 40, S: 90})
        got = guildtrades.assign(self.guild, live)
        self.assertEqual(key((ALCH, S)), key(got[n]))

    def test_a_trade_below_the_guard_is_not_listed(self):
        names, live = self.crowd({})
        got = guildtrades.assign(self.guild, live)
        self.assertEqual({}, guildtrades.guarded(self.guild, live, got))

    def test_only_gathering_trades_are_ever_dropped(self):
        names, live = self.crowd({})
        for gone in guildtrades.drops(self.guild, live).values():
            for skill, _value in gone:
                self.assertIn(skill, guildtrades.GATHERING)

    def test_a_character_with_a_free_slot_drops_nothing(self):
        names, live = self.crowd({})
        name = names[0]
        live[name] = guildtrades.Seen(30, frozenset({H}), {H: 60})
        self.assertNotIn(name, guildtrades.drops(self.guild, live))


if __name__ == "__main__":
    unittest.main()
