"""Who casts to a hearthstone hub, who walks, and who drops it (#2333).

The pre-ship review of #2329 found the kept hub rested on an inference: the
head's bind and the bridge's own hearth rows. A head with no stone, a stone
on a cooldown the bridge did not start, or a dead head still "cast", and a
member bound elsewhere was not looked at. Pinned here: each member's decision
and its reason, and the family's answer.
"""

import unittest

import hearthcast as hc
import hearthcast_data
import situation
import townerrand as te

# The reported hub: the head's hearthstone point in the south of the map.
HUB = {
    "map_id": 0,
    "x": -6673.9,
    "y": -2174.3,
    "z": 244.2,
    "bind": True,
    "place": "the head's hearthstone point",
}
AT_HUB = situation.Point(0, HUB["x"], HUB["y"], HUB["z"])
ELSEWHERE = situation.Point(0, 2150.0, -5260.0, 80.0)
# 9,000 yards north of the hub, on its map.
FAR = {"map_id": 0, "pos_x": 2151.7, "pos_y": -5264.5}
NEAR = {"map_id": 0, "pos_x": -6600.0, "pos_y": -2100.0}
OTHER_MAP = {"map_id": 1, "pos_x": -956.0, "pos_y": -3745.0}
DUNGEON = {"map_id": 230, "pos_x": 458.0, "pos_y": 26.0}


def able(name, at=FAR, bind=AT_HUB, **facts):
    """A member that can cast to HUB unless a fact says otherwise."""
    facts = {"stone": True, "cooldown": 0.0, "alive": True, **facts}
    return hc.Member(name=name, at=at, bind=bind, **facts)


class OneMember(unittest.TestCase):
    def test_a_far_member_with_a_ready_stone_bound_by_the_hub_casts(self):
        d = hc.decide(HUB, able("Grug"))
        self.assertEqual((hc.CAST, hc.STONE_LANDS), (d.act, d.reason))
        self.assertGreater(d.yards, 9000)
        self.assertFalse(d.blocks)

    def test_a_member_without_a_stone_does_not_cast(self):
        d = hc.decide(HUB, able("Grug", stone=False))
        self.assertEqual((hc.HOLD, hc.NO_STONE), (d.act, d.reason))
        self.assertTrue(d.blocks)

    def test_a_stone_on_cooldown_does_not_cast(self):
        d = hc.decide(HUB, able("Grug", cooldown=1800.0))
        self.assertEqual((hc.HOLD, hc.ON_COOLDOWN), (d.act, d.reason))

    def test_a_dead_member_does_not_cast(self):
        d = hc.decide(HUB, able("Grug", alive=False))
        self.assertEqual((hc.HOLD, hc.DEAD), (d.act, d.reason))

    def test_dead_is_said_before_any_other_reason(self):
        d = hc.decide(HUB, able("Grug", alive=False, stone=False, bind=ELSEWHERE))
        self.assertEqual(hc.DEAD, d.reason)

    def test_a_fact_that_was_not_read_is_never_a_cast(self):
        for fact, reason in (
            ("stone", hc.STONE_UNREAD),
            ("cooldown", hc.COOLDOWN_UNREAD),
            ("alive", hc.PULSE_UNREAD),
        ):
            with self.subTest(fact):
                d = hc.decide(HUB, able("Grug", **{fact: None}))
                self.assertEqual((hc.HOLD, reason), (d.act, d.reason))

    def test_a_member_bound_elsewhere_far_on_the_hubs_map_holds(self):
        d = hc.decide(HUB, able("Bork", bind=ELSEWHERE))
        self.assertEqual((hc.HOLD, hc.BOUND_ELSEWHERE), (d.act, d.reason))
        self.assertTrue(d.blocks)

    def test_a_member_with_no_bind_read_is_bound_elsewhere(self):
        d = hc.decide(HUB, able("Bork", bind=None))
        self.assertEqual(hc.BOUND_ELSEWHERE, d.reason)

    def test_a_member_bound_elsewhere_on_another_map_holds_with_no_yards(self):
        d = hc.decide(HUB, able("Bork", at=OTHER_MAP, bind=ELSEWHERE))
        self.assertEqual((hc.HOLD, hc.BOUND_ELSEWHERE), (d.act, d.reason))
        self.assertIsNone(d.yards)

    def test_a_member_within_a_walk_walks_whatever_its_stone(self):
        for member in (
            able("Bork", at=NEAR),
            able("Bork", at=NEAR, bind=ELSEWHERE, stone=False, alive=None),
        ):
            d = hc.decide(HUB, member)
            self.assertEqual((hc.WALK, hc.WITHIN_A_WALK), (d.act, d.reason))
            self.assertLessEqual(d.yards, te.WALK_YARDS)

    def test_a_member_with_no_fresh_reading_holds_and_does_not_block(self):
        d = hc.decide(HUB, able("Bork", at=None))
        self.assertEqual((hc.HOLD, hc.NOT_IN_WORLD), (d.act, d.reason))
        self.assertFalse(d.blocks)

    def test_a_hub_that_is_not_a_hearthstone_point_has_no_cast(self):
        capital = dict(HUB, bind=False)
        self.assertEqual(hc.NO_BIND_HUB, hc.decide(capital, able("Grug")).reason)
        self.assertEqual(hc.NO_BIND_HUB, hc.decide({}, able("Grug")).reason)

    def test_a_head_inside_an_instance_casts(self):
        d = hc.decide(HUB, able("Grug", at=DUNGEON))
        self.assertEqual(hc.CAST, d.act)

    def test_every_reason_has_its_sentence(self):
        reasons = {
            v for k, v in vars(hc).items() if k.isupper() and isinstance(v, str)
        } - {hc.CAST, hc.WALK, hc.HOLD}
        self.assertEqual(reasons, set(hc.SAID))


class TheFamily(unittest.TestCase):
    def keeps(self, *members, leader="Grug"):
        return hc.keeps_hub(HUB, leader, members)

    def test_a_family_that_all_casts_keeps_the_hub(self):
        verdict = self.keeps(able("Grug"), able("Bork"))
        self.assertTrue(verdict.keep)
        self.assertEqual("", verdict.said)
        self.assertEqual(["Bork", "Grug"], [d.name for d in verdict.decisions])

    def test_a_head_without_a_stone_drops_the_hub(self):
        verdict = self.keeps(able("Grug", stone=False), able("Bork"))
        self.assertFalse(verdict.keep)
        self.assertEqual(("Grug", hc.NO_STONE), (verdict.who, verdict.reason))
        self.assertEqual("Grug carries no hearthstone", verdict.said)

    def test_a_head_with_the_stone_on_cooldown_drops_the_hub(self):
        verdict = self.keeps(able("Grug", cooldown=600.0), able("Bork"))
        self.assertFalse(verdict.keep)
        self.assertEqual("Grug has its hearthstone on cooldown", verdict.said)

    def test_a_dead_head_drops_the_hub(self):
        verdict = self.keeps(able("Grug", alive=False), able("Bork"))
        self.assertFalse(verdict.keep)
        self.assertEqual("Grug is dead", verdict.said)

    def test_a_member_bound_elsewhere_on_the_same_map_drops_the_hub(self):
        # The second gap: the head and Og cast, and Bork, bound elsewhere,
        # would be left 9,000 yards from the hub to walk it.
        verdict = self.keeps(able("Grug"), able("Og"), able("Bork", bind=ELSEWHERE))
        self.assertFalse(verdict.keep)
        self.assertEqual(("Bork", hc.BOUND_ELSEWHERE), (verdict.who, verdict.reason))
        acts = {d.name: d.act for d in verdict.decisions}
        self.assertEqual({"Grug": hc.CAST, "Og": hc.CAST, "Bork": hc.HOLD}, acts)

    def test_a_member_bound_elsewhere_beside_the_hub_walks_and_the_hub_stays(self):
        verdict = self.keeps(able("Grug"), able("Bork", at=NEAR, bind=ELSEWHERE))
        self.assertTrue(verdict.keep)
        acts = {d.name: d.act for d in verdict.decisions}
        self.assertEqual({"Grug": hc.CAST, "Bork": hc.WALK}, acts)

    def test_a_member_on_another_map_bound_elsewhere_drops_the_hub(self):
        verdict = self.keeps(able("Grug"), able("Bork", at=OTHER_MAP, bind=ELSEWHERE))
        self.assertFalse(verdict.keep)
        self.assertEqual("Bork is bound somewhere else", verdict.said)

    def test_a_member_that_cannot_cast_its_own_stone_drops_the_hub(self):
        verdict = self.keeps(able("Grug"), able("Bork", stone=False))
        self.assertFalse(verdict.keep)
        self.assertEqual(("Bork", hc.NO_STONE), (verdict.who, verdict.reason))

    def test_a_verdict_on_an_unread_fact_is_data_and_adds_no_line(self):
        # The failed read is logged once where it fails; a line per errand
        # start on top of it would say the same thing every cooldown.
        for fact, reason in (
            ("stone", hc.STONE_UNREAD),
            ("cooldown", hc.COOLDOWN_UNREAD),
            ("alive", hc.PULSE_UNREAD),
        ):
            with self.subTest(fact):
                verdict = self.keeps(able("Grug", **{fact: None}), able("Bork"))
                self.assertEqual(
                    (False, "Grug", reason),
                    (verdict.keep, verdict.who, verdict.reason),
                )
                self.assertEqual("", verdict.said)

    def test_the_heads_own_reason_is_named_first(self):
        verdict = self.keeps(able("Grug", alive=False), able("Bork", stone=False))
        self.assertEqual("Grug", verdict.who)

    def test_an_offline_member_does_not_drop_the_hub(self):
        self.assertTrue(self.keeps(able("Grug"), able("Bork", at=None)).keep)

    def test_a_head_already_by_the_hub_keeps_nothing_and_says_nothing(self):
        verdict = self.keeps(able("Grug", at=NEAR), able("Bork"))
        self.assertFalse(verdict.keep)
        self.assertEqual("", verdict.said)

    def test_an_absent_head_or_a_walked_hub_says_nothing(self):
        self.assertEqual("", self.keeps(able("Bork")).said)
        self.assertEqual("", self.keeps(able("Grug", at=None)).said)
        capital = hc.keeps_hub(dict(HUB, bind=False), "Grug", [able("Grug")])
        self.assertEqual((False, ""), (capital.keep, capital.said))

    def test_a_kept_hub_casts_exactly_who_the_errand_sends_home(self):
        # townerrand.to_hearth writes the hearth rows; a kept hub must never
        # count on a cast that list does not hold.
        family = [able("Grug"), able("Og"), able("Bork", at=NEAR, bind=ELSEWHERE)]
        verdict = hc.keeps_hub(HUB, "Grug", family)
        self.assertTrue(verdict.keep)
        positions = {m.name: m.at for m in family}
        binds = {m.name: m.bind for m in family}
        self.assertEqual(
            te.to_hearth(HUB, positions, list(positions), frozenset(), binds),
            [d.name for d in verdict.decisions if d.act == hc.CAST],
        )


class TheMembersFromTheReads(unittest.TestCase):
    NAMES = ["Grug", "Bork"]
    POSITIONS = {"Grug": FAR, "Bork": FAR}
    BINDS = {"Grug": AT_HUB, "Bork": ELSEWHERE}

    def build(self, facts, hearthed=frozenset()):
        made = hc.members(self.NAMES, self.POSITIONS, self.BINDS, hearthed, facts)
        return {m.name: m for m in made}

    def test_the_reads_become_facts_per_member(self):
        facts = hearthcast_data.Facts(
            stones=frozenset({"Grug"}),
            cooldowns={"Bork": 120.0},
            alive={"Grug": True, "Bork": False},
        )
        made = self.build(facts)
        self.assertEqual(hc.Member("Grug", FAR, AT_HUB, True, 0.0, True), made["Grug"])
        self.assertEqual(
            hc.Member("Bork", FAR, ELSEWHERE, False, 120.0, False), made["Bork"]
        )

    def test_a_member_with_no_fresh_snapshot_has_no_pulse(self):
        facts = hearthcast_data.Facts(frozenset({"Grug"}), {}, {})
        self.assertIsNone(self.build(facts)["Grug"].alive)

    def test_a_read_that_failed_leaves_its_fact_unread(self):
        made = self.build(hearthcast_data.Facts())
        self.assertEqual(
            (None, None, None),
            (made["Grug"].stone, made["Grug"].cooldown, made["Grug"].alive),
        )
        self.assertFalse(hc.keeps_hub(HUB, "Grug", made.values()).keep)

    def test_no_facts_at_all_is_every_fact_unread(self):
        made = self.build(None)
        self.assertEqual(hc.STONE_UNREAD, hc.decide(HUB, made["Grug"]).reason)

    def test_a_hearth_the_bridge_wrote_is_a_cooldown_the_table_may_not_show(self):
        facts = hearthcast_data.Facts(frozenset({"Grug"}), {}, {"Grug": True})
        made = self.build(facts, hearthed=frozenset({"Grug"}))
        self.assertEqual(hc.ON_COOLDOWN, hc.decide(HUB, made["Grug"]).reason)
        unread = self.build(hearthcast_data.Facts(), hearthed=frozenset({"Grug"}))
        self.assertGreater(unread["Grug"].cooldown, 0)

    def test_the_longer_cooldown_is_kept(self):
        facts = hearthcast_data.Facts(frozenset(), {"Grug": 900.0}, {})
        made = self.build(facts, hearthed=frozenset({"Grug"}))
        self.assertEqual(900.0, made["Grug"].cooldown)


if __name__ == "__main__":
    unittest.main()
