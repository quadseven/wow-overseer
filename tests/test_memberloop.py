"""A guild member's own profession loop and the ride for a rare node (memberloop.py).

Synthetic rows: lock ids from gatherband, doors from guildrun, members from the
social layer's own test helper. Nothing here starts a run.
"""

import pathlib
import unittest

import guildrun
import guildsocial as gs
import memberloop as ml
import profloop
import strayfollow
from test_guildsocial import mate

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")
DOORS = guildrun.doors()
DIRE_MAUL = next(d for d in DOORS if d.keyword == "dire-maul-north")
DEADMINES = next(d for d in DOORS if d.keyword == "deadmines")
# Lock 380 is a mining lock (band 205) and 49 a herbalism lock (band 185).
ORE_LOCK, HERB_LOCK = 380, 49


class Switch(unittest.TestCase):
    def test_unset_names_no_guild(self):
        self.assertFalse(ml.enabled_for("Cave", {}))

    def test_a_named_guild_is_matched_without_case(self):
        env = {ml.ENV_SWITCH: "cave, Bonkers"}
        self.assertTrue(ml.enabled_for("Cave", env))
        self.assertTrue(ml.enabled_for("BONKERS", env))
        self.assertFalse(ml.enabled_for("Other", env))

    def test_extra_locks_ignore_junk(self):
        self.assertEqual(
            frozenset({380, 49}), ml.extra_locks({ml.ENV_EXTRA_LOCKS: "380, x, 49,"})
        )


class PickTrade(unittest.TestCase):
    def test_the_trade_furthest_behind_wins(self):
        trade, _why = ml.pick_trade({"mining": 150, "herbalism": 90, "skinning": 200})
        self.assertEqual("herbalism", trade)

    def test_a_tie_goes_mining_first(self):
        self.assertEqual("mining", ml.pick_trade({"mining": 5, "herbalism": 5})[0])

    def test_no_gathering_trade_picks_none(self):
        trade, why = ml.pick_trade({"tailoring": 300})
        self.assertEqual("", trade)
        self.assertTrue(why)


class RareNodes(unittest.TestCase):
    def rows(self):
        return [
            {"map_id": 429, "lock_id": ORE_LOCK, "name": "Truesilver Deposit"},
            {"map_id": 429, "lock_id": 38, "name": "Copper Vein"},
            {"map_id": 429, "lock_id": 999999, "name": "A chest"},
        ]

    def test_a_lock_the_open_world_has_is_not_rare(self):
        self.assertEqual((), ml.rare_nodes(self.rows(), {ORE_LOCK, 38}))

    def test_an_instance_only_lock_is_rare_and_unknown_locks_drop(self):
        nodes = ml.rare_nodes(self.rows(), {38})
        self.assertEqual([(429, ORE_LOCK)], [(n.map_id, n.lock_id) for n in nodes])

    def test_the_operator_can_name_a_lock_rare(self):
        nodes = ml.rare_nodes(self.rows(), {ORE_LOCK, 38}, frozenset({ORE_LOCK}))
        self.assertEqual([ORE_LOCK], [n.lock_id for n in nodes])


class RareNeeds(unittest.TestCase):
    NODES = (ml.Node(429, ORE_LOCK, "Truesilver Deposit"),)

    def need(self, skills, free=20, nodes=None):
        return ml.rare_needs(
            "Chop", skills, free, self.NODES if nodes is None else nodes, DOORS
        )

    def test_a_miner_who_opens_the_node_needs_each_door_on_its_map(self):
        needs = self.need({"mining": 220})
        self.assertEqual(3, len(needs))
        self.assertTrue(all(n.node for n in needs))
        self.assertIn("dire-maul-north", {n.keyword for n in needs})

    def test_a_skill_below_the_band_needs_nothing(self):
        self.assertEqual((), self.need({"mining": 150}))

    def test_a_grey_node_needs_nothing(self):
        self.assertEqual((), self.need({"mining": 205 + 100}))

    def test_the_wrong_trade_needs_nothing(self):
        self.assertEqual((), self.need({"herbalism": 220}))

    def test_full_bags_send_it_to_town_not_to_a_door(self):
        self.assertEqual(
            (), self.need({"mining": 220}, free=profloop.TOWN_FREE_SLOTS - 1)
        )

    def test_an_unread_bag_does_not_stop_it(self):
        self.assertTrue(self.need({"mining": 220}, free=None))


class AnswerWorth(unittest.TestCase):
    def test_a_node_need_is_worth_more_than_xp_and_less_than_an_upgrade(self):
        self.assertGreater(ml.NEED_NODE, gs.XP_BAND)
        self.assertLess(ml.NEED_NODE, gs.NEED_UPGRADE)
        self.assertEqual(ml.NEED_NODE, gs.NEED_NODE)

    def test_the_social_layer_gives_a_node_need_its_value(self):
        m = mate("Chop", 58, 4, at=(0.0, 0.0))
        need = ml.rare_needs(
            "Chop", {"mining": 220}, 20, (ml.Node(429, ORE_LOCK, "Ore"),), DOORS
        )
        stance, value, got = gs.stance_of(m, DIRE_MAUL, 58, "Alliance", list(need))
        self.assertEqual((gs.NEED, gs.NEED_NODE), (stance, value))
        self.assertTrue(got.node)

    def test_an_ask_for_a_node_says_so(self):
        need = gs.Need("Chop", "dire-maul-north", "Truesilver Deposit", node=True)
        self.assertIn("Truesilver Deposit", gs.ask_reason(need))
        self.assertIn(
            "Truesilver Deposit", gs.ask_line("Chop", DIRE_MAUL, ("tank",), need)
        )

    def test_needs_merge_best_first(self):
        up = gs.Need("Chop", "deadmines", "Cape", gain=5.0)
        node = gs.Need("Chop", "deadmines", "Ore", node=True)
        self.assertEqual([up, node], ml.merge_needs([node], [up]))


class Leaving(unittest.TestCase):
    def rider(self, **kw):
        base = dict(
            name="Chop", keyword="dire-maul-north", grouped=True,
            in_instance=False, in_combat=False, run_live=False,
        )  # fmt: skip
        base.update(kw)
        return ml.Rider(**base)

    def test_a_rider_outside_after_the_run_leaves(self):
        rows, lines = ml.plan_leaves([self.rider()], {})
        self.assertEqual(
            [("Chop", strayfollow.VERB)], [(r.name, r.command) for r in rows]
        )
        self.assertEqual(1, len(lines))

    def test_nobody_leaves_inside_a_fight_a_run_or_an_instance(self):
        for kw in ({"in_instance": True}, {"in_combat": True}, {"run_live": True}):
            with self.subTest(kw=kw):
                self.assertEqual((), ml.plan_leaves([self.rider(**kw)], {})[0])

    def test_an_ungrouped_rider_has_nothing_to_leave(self):
        self.assertEqual((), ml.plan_leaves([self.rider(grouped=False)], {})[0])

    def test_a_recent_row_holds_it_back_and_a_pass_is_capped(self):
        self.assertEqual((), ml.plan_leaves([self.rider()], {"Chop": 5})[0])
        many = [self.rider(name="R%d" % i) for i in range(9)]
        self.assertEqual(ml.LEAVES_PER_PASS, len(ml.plan_leaves(many, {})[0]))

    def test_forget_drops_the_ungrouped_and_the_stale(self):
        riders = {"A": ("x", 0.0), "B": ("x", 0.0), "C": ("x", 99999.0)}
        kept = ml.forget(riders, 99999.0 + 10, {"A", "C"})
        self.assertEqual({"C"}, set(kept))


class BridgeWiring(unittest.TestCase):
    def test_the_social_pass_asks_for_rare_needs(self):
        self.assertIn("memberloop.rare_needs", BRIDGE)

    def test_the_leave_pass_is_a_declared_loop_and_writes_the_verb(self):
        self.assertIn('_Pass("_member_ride_loop")', BRIDGE)
        self.assertIn("memberloop.plan_leaves", BRIDGE)

    def test_the_verb_is_one_the_module_handles(self):
        import guildcorps

        self.assertIn(ml.VERB, guildcorps.MODULE_GUILD_VERBS)


if __name__ == "__main__":
    unittest.main()
