"""A guildmate's loot goes to the guild member who gains most (#174).

Pure unit tests against the decision (gear.rank_receivers, gear.route_plan,
gear.route_deliverable) and its adapters, plus source checks on the bridge
and the page. The fixtures are the dev realm as measured on 2026-09-22: a
level 60 warlock guildmate carrying Destiny (item 647, a bind-on-equip epic
two-hand sword, item level 57, with a chance-on-hit effect) she can never
swing; the family's Retribution paladin with a one-hand axe at item level 52
and a shield; the family's Protection warrior with an item level 30 dagger
and a shield.
"""

import pathlib
import unittest
from dataclasses import replace

import armory
import bag_pressure
import gear
import guildroute
import raidlineup

HERE = pathlib.Path(__file__).resolve().parents[1]

WARRIOR, PALADIN, WARLOCK, PRIEST = 1, 2, 9, 5


def destiny(**over):
    base = dict(
        holder="Avenah",
        guid=4909901,
        entry=647,
        name="Destiny",
        quality=4,
        item_level=57,
        required_level=52,
        allowable_class=-1,
        inventory_type=17,
        item_class=gear.ITEM_CLASS_WEAPON,
        item_subclass=gear.WEAPON_SWORD2,
        has_effect=True,
    )
    base.update(over)
    return gear.Holding(**base)


def avenah():
    # Worn: The Staff of Twin Worlds (two-hand, item level 81).
    return gear.CharacterState(
        name="Avenah", class_id=WARLOCK, level=60, equipped={"two_hand": 81}
    )


def grog(role=gear.ROLE_DAMAGE):
    # Moon Cleaver (one hand, 52) and Templar Shield (58), as measured.
    return gear.CharacterState(
        name="Grog",
        class_id=PALADIN,
        level=60,
        equipped={"main_hand": 52, "off_hand": 58, "head": 31, "chest": 41},
        role=role,
    )


def grug(role=gear.ROLE_TANK):
    # Honed Stiletto (dagger, 30), Bloodforged Shield (51), Banded Cloak (29).
    return gear.CharacterState(
        name="Grug",
        class_id=WARRIOR,
        level=60,
        equipped={
            "head": 45,
            "shoulder": 42,
            "chest": 42,
            "waist": 42,
            "legs": 56,
            "feet": 55,
            "wrist": 49,
            "hands": 33,
            "back": 29,
            "main_hand": 30,
            "off_hand": 51,
            "ranged": 32,
        },
        role=role,
    )


def cands(*states, family=("Grog", "Grug")):
    return [gear.Candidate(character=s, family=s.name in family) for s in states]


class TheDestinyCase(unittest.TestCase):
    def test_the_paladin_ranks_first_and_the_tank_not_at_all(self):
        ranked = gear.rank_receivers(destiny(), cands(avenah(), grog(), grug()))
        self.assertEqual([r.name for r in ranked], ["Grog"])
        self.assertEqual(ranked[0].gain, 5)
        self.assertTrue(ranked[0].family)

    def test_an_effect_makes_the_ranking_unsure_and_nothing_moves(self):
        ranked = gear.rank_receivers(destiny(), cands(avenah(), grog(), grug()))
        self.assertFalse(ranked[0].sure)
        decided = gear.route_plan([destiny()], cands(avenah(), grog(), grug()))
        self.assertEqual(decided.grants, ())
        self.assertEqual(len(decided.notes), 1)
        self.assertIn("effect", decided.notes[0])

    def test_without_the_effect_it_is_routed_to_the_paladin(self):
        decided = gear.route_plan(
            [destiny(has_effect=False)], cands(avenah(), grog(), grug())
        )
        self.assertEqual(len(decided.grants), 1)
        route = decided.grants[0]
        self.assertEqual((route.holder, route.taker, route.gain), ("Avenah", "Grog", 5))
        self.assertEqual(route.alternates, ())

    def test_a_warlock_cannot_wield_a_two_hand_sword(self):
        bare = gear.CharacterState(name="Avenah", class_id=WARLOCK, level=60)
        wears, reason = gear.would_wear(destiny(), bare)
        self.assertFalse(wears)
        self.assertIn("cannot wield", reason)

    def test_a_tank_never_gets_a_two_hander_over_a_shield(self):
        gain, reason = gear.upgrade_gain(destiny(has_effect=False), grug())
        self.assertEqual(gain, 0)
        self.assertIn("off-hand", reason)

    def test_an_unknown_role_keeps_the_old_guard(self):
        gain, _ = gear.upgrade_gain(destiny(has_effect=False), grog(gear.ROLE_UNKNOWN))
        self.assertEqual(gain, 0)

    def test_a_two_hander_must_beat_the_main_hand_it_replaces(self):
        weak = destiny(item_level=40, has_effect=False)
        self.assertEqual(gear.upgrade_gain(weak, grog())[0], 0)
        no_shield = replace(grog(), equipped={"main_hand": 52})
        self.assertEqual(gear.upgrade_gain(weak, no_shield)[0], 0)


class NothingBoundAndNothingFromAWearer(unittest.TestCase):
    def test_a_soulbound_item_ranks_nobody(self):
        self.assertEqual(
            gear.rank_receivers(destiny(soulbound=True), cands(grog())), ()
        )

    def test_bound_rows_never_become_holdings(self):
        row = {
            "holder": "Avenah",
            "item_guid": 1,
            "entry": 647,
            "name": "Destiny",
            "quality": 4,
            "item_level": 57,
            "required_level": 52,
            "allowable_class": -1,
            "inventory_type": 17,
            "item_class": 2,
            "item_subclass": 8,
            "bonding": 2,
            "instance_flags": 0,
        }
        pickup = dict(row, item_guid=2, bonding=1)
        worn_once = dict(row, item_guid=3, instance_flags=1)
        quest = dict(row, item_guid=4, bonding=4)
        held = bag_pressure.guild_route_holdings([row, pickup, worn_once, quest])
        self.assertEqual([h.guid for h in held], [1])

    def test_a_holder_who_would_wear_it_keeps_it(self):
        paladin_holder = gear.CharacterState(
            name="Avenah", class_id=PALADIN, level=60, equipped={"two_hand": 40}
        )
        decided = gear.route_plan(
            [destiny(has_effect=False)], cands(paladin_holder, grog())
        )
        self.assertEqual(decided.grants, ())

    def test_a_holder_nobody_described_is_left_alone(self):
        decided = gear.route_plan([destiny(has_effect=False)], cands(grog()))
        self.assertEqual(decided.grants, ())

    def test_a_family_holder_is_not_this_passes(self):
        mine = destiny(holder="Grug", has_effect=False)
        decided = gear.route_plan([mine], cands(grug(), grog()))
        self.assertEqual(decided.grants, ())


class TheRankingOrder(unittest.TestCase):
    def test_family_first_among_equal_gains(self):
        stranger = gear.CharacterState(
            name="Zelra",
            class_id=PALADIN,
            level=60,
            equipped={"main_hand": 52, "off_hand": 58},
            role=gear.ROLE_DAMAGE,
        )
        ranked = gear.rank_receivers(
            destiny(has_effect=False), cands(stranger, grog(), family=("Grog",))
        )
        self.assertEqual([r.name for r in ranked], ["Grog", "Zelra"])

    def test_filling_the_weakest_slot_breaks_a_tie(self):
        dagger = destiny(
            name="Keen Dagger",
            inventory_type=13,
            item_subclass=gear.WEAPON_DAGGER,
            item_level=45,
            has_effect=False,
        )
        other = gear.CharacterState(
            name="Zub",
            class_id=WARRIOR,
            level=60,
            equipped={"main_hand": 30, "off_hand": 51, "back": 1, "head": 60},
            role=gear.ROLE_TANK,
        )
        ranked = gear.rank_receivers(
            dagger, cands(other, grug(), family=("Grug", "Zub"))
        )
        self.assertEqual([r.name for r in ranked], ["Grug", "Zub"])
        self.assertTrue(ranked[0].fills_weakest)
        self.assertFalse(ranked[1].fills_weakest)

    def test_a_small_gain_is_noted_not_moved(self):
        slight = destiny(item_level=54, has_effect=False)
        decided = gear.route_plan([slight], cands(avenah(), grog()))
        self.assertEqual(decided.grants, ())
        self.assertIn("under the 3", decided.notes[0])


def _pos(map_id, x, y):
    return {"map_id": map_id, "pos_x": x, "pos_y": y}


class HandOversHappenInTheWorld(unittest.TestCase):
    def setUp(self):
        self.route = gear.route_plan(
            [destiny(has_effect=False)], cands(avenah(), grog())
        ).grants[0]

    def test_together_is_a_trade(self):
        ready = gear.route_deliverable(
            [self.route],
            {"Avenah": _pos(1, 0, 0), "Grog": _pos(1, 5, 5)},
            set(),
            {"Grog": 3},
        )
        self.assertEqual([r.verb for r in ready.grants], [gear.TRADE])
        self.assertEqual(ready.grants[0].command, "guid:4909901")

    def test_apart_with_the_holder_at_a_mailbox_is_a_letter(self):
        ready = gear.route_deliverable(
            [self.route],
            {"Avenah": _pos(1, 0, 0), "Grog": _pos(0, 5, 5)},
            {"Avenah"},
            {"Grog": 0},
        )
        self.assertEqual([r.verb for r in ready.grants], [gear.MAIL])
        self.assertEqual(ready.grants[0].command, "send item:4909901 subject:Destiny")

    def test_apart_and_no_mailbox_waits_and_says_why(self):
        ready = gear.route_deliverable(
            [self.route],
            {"Avenah": _pos(1, 0, 0), "Grog": _pos(1, 900, 900)},
            set(),
            {"Grog": 5},
        )
        self.assertEqual(ready.grants, ())
        self.assertEqual(
            ready.notes[0],
            "Destiny stays with Avenah: Avenah is beside none of Grog, and at no mailbox",
        )

    def test_never_a_give(self):
        for positions, mailbox in (
            ({"Avenah": _pos(1, 0, 0), "Grog": _pos(1, 5, 5)}, set()),
            ({"Avenah": _pos(1, 0, 0), "Grog": _pos(0, 5, 5)}, {"Avenah"}),
        ):
            ready = gear.route_deliverable(
                [self.route], positions, mailbox, {"Grog": 1}
            )
            self.assertNotIn(gear.GIVE, [r.verb for r in ready.grants])

    def test_a_guildmate_receiver_is_not_posted_to(self):
        route = replace(self.route, family=False)
        ready = gear.route_deliverable(
            [route],
            {"Avenah": _pos(1, 0, 0), "Grog": _pos(0, 5, 5)},
            {"Avenah"},
            {"Grog": 5},
        )
        self.assertEqual(ready.grants, ())

    def test_the_pass_is_rate_limited(self):
        routes = [replace(self.route, guid=g, taker="T%d" % g) for g in (1, 2, 3)]
        positions = {"Avenah": _pos(1, 0, 0)}
        positions.update({"T%d" % g: _pos(1, 1, 1) for g in (1, 2, 3)})
        ready = gear.route_deliverable(
            routes, positions, set(), {"T1": 1, "T2": 1, "T3": 1}, per_pass=2
        )
        self.assertEqual(len(ready.grants), 2)
        self.assertIn("limit per pass", ready.notes[0])

    def test_one_item_per_receiver_per_pass(self):
        second = replace(self.route, guid=7)
        ready = gear.route_deliverable(
            [self.route, second],
            {"Avenah": _pos(1, 0, 0), "Grog": _pos(1, 1, 1)},
            set(),
            {"Grog": 5},
        )
        self.assertEqual(len(ready.grants), 1)


class TheWeakestSlot(unittest.TestCase):
    def test_the_tanks_dagger_is_his_weakest_slot(self):
        weakest = gear.weakest_slot(grug())
        self.assertEqual(weakest.slot, "weapon")
        self.assertEqual(weakest.label, "main hand")
        self.assertEqual(weakest.said, "main hand, item level 30 at level 60")

    def test_nothing_behind_is_none(self):
        at_level = gear.CharacterState(
            name="X",
            class_id=WARRIOR,
            level=10,
            equipped={
                b: 10
                for b in (
                    "head",
                    "shoulder",
                    "chest",
                    "waist",
                    "legs",
                    "feet",
                    "wrist",
                    "hands",
                    "back",
                    "main_hand",
                )
            },
        )
        self.assertIsNone(gear.weakest_slot(at_level))

    def test_the_armory_flags_every_slot_badly_behind_and_only_those(self):
        def member(name, weakest):
            return {"name": name, "weakest": weakest, "gear": {"chips": []}}

        grug_m = member(
            "Grug", {"shortfall": 60, "said": "main hand, item level 30 at level 60"}
        )
        bork_m = member(
            "Bork", {"shortfall": 72, "said": "main hand, item level 24 at level 60"}
        )
        fine = member("Og", {"shortfall": 4, "said": "head, item level 58 at level 60"})
        flagged = armory.flag_weakest([grug_m, fine, bork_m])
        self.assertEqual(flagged, ["Bork", "Grug"])
        self.assertEqual(
            grug_m["gear"]["chips"],
            [
                {
                    "key": armory.WEAKEST_KEY,
                    "value": "main hand, item level 30 at level 60",
                    "tone": armory.TONE_CAUTION,
                }
            ],
        )
        self.assertEqual(fine["gear"]["chips"], [])

    def test_the_armory_reads_the_paper_doll_through_gear(self):
        slots = [
            {"slot": "main hand", "empty": False, "item_level": 30},
            {"slot": "back", "empty": False, "item_level": 29},
            {"slot": "finger 1", "empty": False, "item_level": 1},
        ] + [
            {"slot": s, "empty": False, "item_level": 50}
            for s in (
                "head",
                "shoulders",
                "chest",
                "waist",
                "legs",
                "feet",
                "wrists",
                "hands",
            )
        ]
        w = armory.weakest_payload("Grug", WARRIOR, 60, slots)
        self.assertEqual(w["slot"], "main hand")


class TheRolesComeFromTheLineupPacking(unittest.TestCase):
    ROWS = [
        {
            "name": "Grug",
            "class_id": WARRIOR,
            "level": 60,
            "inventory_type": 13,
            "item_level": 30,
        },
        {
            "name": "Grug",
            "class_id": WARRIOR,
            "level": 60,
            "inventory_type": 14,
            "item_level": 51,
        },
        {
            "name": "Ugga",
            "class_id": PRIEST,
            "level": 60,
            "inventory_type": 20,
            "item_level": 50,
        },
        {
            "name": "Grog",
            "class_id": PALADIN,
            "level": 60,
            "inventory_type": 13,
            "item_level": 52,
        },
        {
            "name": "Grog",
            "class_id": PALADIN,
            "level": 60,
            "inventory_type": 14,
            "item_level": 58,
        },
    ]

    def test_party_roles(self):
        roles = raidlineup.party_roles(
            [
                {"name": "Grog", "class_id": PALADIN},
                {"name": "Grug", "class_id": WARRIOR},
                {"name": "Ugga", "class_id": PRIEST},
            ]
        )
        self.assertEqual(roles, {"Grug": "tank", "Ugga": "healer", "Grog": "damage"})

    def test_the_family_carries_its_roles(self):
        chars = bag_pressure.family_characters(self.ROWS, ["Grog", "Grug", "Ugga"])
        self.assertEqual(
            {c.name: c.role for c in chars},
            {"Grog": "damage", "Grug": "tank", "Ugga": "healer"},
        )

    def test_the_family_claim_keeps_a_routed_two_hander_with_the_paladin(self):
        """Handed over and then sold would be worse than never moved: the
        sell path's claim must agree that Grog would wear it."""
        carried = {
            "holder": "Grog",
            "item_guid": 4909901,
            "entry": 647,
            "name": "Destiny",
            "quality": 4,
            "item_level": 57,
            "required_level": 52,
            "allowable_class": -1,
            "inventory_type": 17,
            "item_class": 2,
            "item_subclass": 8,
            "instance_flags": 0,
        }
        claims = bag_pressure.family_claimants(
            [carried], self.ROWS, ["Grog", "Grug", "Ugga"]
        )
        self.assertEqual(claims[4909901], "Grog")


class TheRowsAndThePage(unittest.TestCase):
    def test_source_carries_the_gain(self):
        self.assertEqual(guildroute.source_for(5), "guildroute:5")
        self.assertEqual(guildroute.gain_of("guildroute:5"), 5)
        self.assertEqual(guildroute.gain_of("guildshare"), 0)

    def test_the_view_says_holder_receiver_item_and_gain(self):
        rows = [
            {
                "target_name": "Avenah",
                "target_arg": "Grog",
                "kind": "trade",
                "command": "guid:4909901",
                "status": "delivered",
                "detail": "",
                "source": "guildroute:5",
            },
            {
                "target_name": "Avenah",
                "target_arg": "Grog",
                "kind": "mail",
                "command": "send item:12 subject:Doombringer",
                "status": "delivered",
                "detail": "",
                "source": "guildroute:4",
            },
        ]
        view = guildroute.view(rows, {4909901: "Destiny"})
        self.assertEqual(
            view["lines"][0], "Avenah to Grog: Destiny by trade, +5 item levels - done"
        )
        self.assertIn("item 12 by post, +4 item levels - posted", view["lines"][1])
        self.assertEqual(guildroute.view([])["lines"], [])

    def test_the_bridge_never_writes_a_give_for_a_route(self):
        bridge = (HERE / "bridge.py").read_text(encoding="utf-8")
        body = bridge[bridge.index("def _insert_route(") :]
        body = body[: body.index("\ndef ")]
        self.assertIn("if route.verb not in guildroute.VERBS:", body)
        self.assertNotIn("give", body)
        self.assertEqual(guildroute.VERBS, (gear.TRADE, gear.MAIL))

    def test_the_held_gear_read_excludes_bound_items(self):
        bridge = (HERE / "bridge.py").read_text(encoding="utf-8")
        sql = bridge[bridge.index("_GUILD_HELD_GEAR_SQL = (") :]
        sql = sql[: sql.index("\n)\n")]
        self.assertIn("(ii.flags & 1) = 0", sql)
        self.assertIn("it.bonding IN (0, 2, 3)", sql)
        self.assertIn("AS has_effect", sql)

    def test_the_bags_page_draws_the_routes(self):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        self.assertIn('<div id="wroute"></div>', page)
        self.assertIn("renderRoutes(p.guild_routes);", page)
        server = (HERE / "map_server.py").read_text(encoding="utf-8")
        self.assertIn('payload["guild_routes"] = _fetch_guild_routes()', server)


if __name__ == "__main__":
    unittest.main()
