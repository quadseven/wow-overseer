"""Raid seats pick up the nodes they pass (guildgather.py, ticket 2586 slice 1).

Pure rows in, command rows out. The bridge is read as text only.
"""

import pathlib
import unittest

import goals
import guildgather as gg
import raidteams

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def seat(name="Durg", level=40, herb=0, mining=0, **kw):
    base = dict(
        online=True,
        alive=True,
        grouped=False,
        in_instance=False,
        in_combat=False,
    )
    base.update(kw)
    return gg.Seat(name=name, level=level, skills={182: herb, 186: mining}, **base)


class Who(unittest.TestCase):
    def test_a_sub_60_seat_with_herbalism_is_granted(self):
        self.assertEqual("", gg.refusal(seat(herb=1)))

    def test_mining_alone_is_enough(self):
        self.assertEqual("", gg.refusal(seat(mining=30)))

    def test_no_gathering_trade_means_nothing_to_pick(self):
        self.assertIn("no gathering trade", gg.refusal(seat()))

    def test_skinning_alone_does_not_count(self):
        s = gg.Seat("Durg", 40, {393: 50}, True, True, False, False, False)
        self.assertIn("no gathering trade", gg.refusal(s))

    def test_level_60_seats_are_left_to_their_own_jobs(self):
        self.assertIn("level", gg.refusal(seat(level=60, herb=5)))

    def test_a_grouped_seat_stays_in_formation(self):
        self.assertIn("group", gg.refusal(seat(herb=5, grouped=True)))

    def test_an_instance_combat_or_a_corpse_is_left_alone(self):
        for kw in ({"in_instance": True}, {"in_combat": True}, {"alive": False}):
            self.assertNotEqual("", gg.refusal(seat(herb=5, **kw)), kw)

    def test_an_offline_seat_is_skipped(self):
        self.assertNotEqual("", gg.refusal(seat(herb=5, online=False)))

    def test_a_trade_at_its_top_rank_has_no_skill_left_to_gain(self):
        self.assertNotEqual("", gg.refusal(seat(herb=300)))


class Rows(unittest.TestCase):
    def test_the_pair_goes_in_the_order_the_family_gets_it(self):
        rows = gg.plan([seat(herb=3)], {}, now=1000.0)
        self.assertEqual(
            [("Durg", c, gg.SOURCE) for c in goals.GATHER_STRATEGIES], rows
        )

    def test_a_seat_granted_recently_is_not_told_again(self):
        again = gg.plan([seat(herb=3)], {"Durg": 1000.0}, now=1000.0 + 60)
        self.assertEqual([], again)

    def test_it_is_told_again_once_the_window_passes(self):
        later = gg.plan(
            [seat(herb=3)], {"Durg": 1000.0}, now=1000.0 + gg.REASSERT_SECONDS + 1
        )
        self.assertEqual(2, len(later))

    def test_a_pass_is_capped(self):
        seats = [seat(name="S%d" % i, herb=3) for i in range(gg.PER_PASS + 5)]
        names = {r[0] for r in gg.plan(seats, {}, now=0.0)}
        self.assertEqual(gg.PER_PASS, len(names))

    def test_the_grant_is_recorded_for_the_next_pass(self):
        seen = {}
        gg.plan([seat(herb=3)], seen, now=500.0)
        self.assertEqual({"Durg": 500.0}, seen)


class Seats(unittest.TestCase):
    def test_the_seats_are_the_approved_raid_seats_without_the_families(self):
        names = gg.seat_names()
        self.assertEqual(70, len(names))
        for guild, groups in raidteams.GROUPS.items():
            for s in groups[0]:
                self.assertNotIn(s.name, names)
            for group in groups[1:]:
                for s in group:
                    self.assertIn(s.name, names)

    def test_a_rename_is_followed_by_the_current_name(self):
        self.assertIn("Aalall", gg.seat_names(include_old=True))


class Switch(unittest.TestCase):
    def test_on_unless_turned_off(self):
        self.assertTrue(gg.enabled({}))
        self.assertFalse(gg.enabled({gg.ENV_SWITCH: "off"}))


class Wiring(unittest.TestCase):
    def test_the_bridge_runs_the_pass_and_the_image_ships_the_module(self):
        self.assertIn("import guildgather", BRIDGE)
        self.assertIn('_Pass("_guild_gather_loop")', BRIDGE)
        self.assertIn("guildgather.py", DOCKERFILE)

    def test_the_pass_never_writes_game_state(self):
        src = (ROOT / "guildgather.py").read_text(encoding="utf-8")
        for word in (".additem", ".setskill", ".learn", ".modify"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
