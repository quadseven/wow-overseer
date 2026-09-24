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
import travel

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


def _box(d2=100.0 * 100.0, map_id=1):
    # A mailbox spawn row as _nearest_mailbox returns it, d2 from the holder.
    return {"map_id": map_id, "x": -1500.0, "y": 2400.0, "z": 90.0, "d2": d2}


def _walker(name="Avenah", **over):
    base = dict(
        state={"map_id": 1, "in_combat": 0},
        leader_of={"Avenah": "Bonkers"},
        roster={"Avenah"},
        spawn=_box(),
        row_walks=True,
    )
    base.update(over)
    return guildroute.walker_from(
        name,
        base["state"],
        base["leader_of"],
        base["roster"],
        base["spawn"],
        row_walks=base["row_walks"],
    )


class HoldersWalkToAMailbox(unittest.TestCase):
    """#185: a waiting route walks its holder to the nearest mailbox."""

    def setUp(self):
        self.route = gear.route_plan(
            [destiny(has_effect=False)], cands(avenah(), grog())
        ).grants[0]

    def plan(self, walker=None, running=(), spent=0, routes=None, **kw):
        walkers = {"Avenah": walker or _walker()}
        return guildroute.plan_mail_runs(
            routes or [self.route], walkers, set(running), spent, **kw
        )

    def test_a_roster_leader_holder_walks_to_the_nearest_mailbox(self):
        plan = self.plan()
        self.assertEqual(len(plan.runs), 1)
        run = plan.runs[0]
        self.assertEqual((run.holder, run.taker, run.guid), ("Avenah", "Grog", 4909901))
        self.assertEqual(run.cohort, "Bonkers")
        self.assertEqual(run.aim, travel.mailbox_aim(_box(), 1).aim)
        self.assertEqual(
            run.said,
            "Avenah walks 100 yards to the mailbox at %s to post Destiny "
            "(item 4909901) to Grog, +%d item levels" % (run.aim, self.route.gain),
        )

    def test_a_guild_bot_off_the_roster_walks_by_the_module_row(self):
        """#185 with mod-overseer#570: the bot walks by its own walk row."""
        plan = self.plan(_walker(leader_of={}, roster=set()))
        self.assertEqual(len(plan.runs), 1)
        run = plan.runs[0]
        self.assertTrue(run.by_row)
        self.assertEqual(run.cohort, "")
        self.assertEqual(run.walk_command, "walk-to-mailbox max:600")
        self.assertEqual(run.verb, gear.MAIL)
        self.assertEqual(run.command, "send item:4909901 subject:Destiny")

    def test_a_holder_in_outland_or_northrend_is_not_walked(self):
        # The classic ruleset: a guild bot standing on 530 or 571 is not
        # walked to that map's mailbox, however near it is.
        for map_id, land in ((530, "Outland"), (571, "Northrend")):
            walker = _walker(
                leader_of={},
                roster=set(),
                state={"map_id": map_id, "in_combat": 0},
                spawn=_box(map_id=map_id),
            )
            self.assertEqual(self.plan(walker).runs, (), map_id)
            self.assertEqual(
                guildroute.cannot_walk(walker, "Avenah"),
                "Avenah stands in %s, outside the classic world" % land,
            )

    def test_a_roster_leader_is_not_walked_by_row(self):
        self.assertFalse(self.plan().runs[0].by_row)

    def test_off_the_roster_waits_while_the_world_cannot_walk_one(self):
        walker = _walker(leader_of={}, roster=set(), row_walks=False)
        plan = self.plan(walker)
        self.assertEqual(plan.runs, ())
        self.assertEqual(
            plan.notes,
            (
                "Destiny stays with Avenah: Avenah is a guild bot off the roster, "
                "and this worldserver cannot walk one to a mailbox yet "
                "(quadseven/mod-overseer#570)",
            ),
        )

    def test_a_roster_follower_is_not_walked(self):
        plan = self.plan(_walker(leader_of={}))
        self.assertEqual(plan.runs, ())
        self.assertIn(guildroute.NOT_LEADING, plan.notes[0])

    def test_one_run_per_holder_at_a_time(self):
        plan = self.plan(running={"Avenah"})
        self.assertEqual(plan.runs, ())
        self.assertIn("already walking to a mailbox", plan.notes[0])
        second = replace(self.route, guid=77, name="Second")
        plan = self.plan(routes=[self.route, second])
        self.assertEqual([r.guid for r in plan.runs], [4909901])

    def test_the_nearest_mailbox_must_be_within_the_cap(self):
        far = _walker(spawn=_box(d2=700.0 * 700.0))
        plan = self.plan(far)
        self.assertEqual(plan.runs, ())
        self.assertIn("700 yards away, past the 600", plan.notes[0])
        self.assertEqual(len(self.plan(far, max_yards=800).runs), 1)

    def test_no_mailbox_on_the_map_waits(self):
        plan = self.plan(_walker(spawn=None))
        self.assertEqual(plan.runs, ())
        self.assertIn("no mailbox is spawned on map 1", plan.notes[0])

    def test_the_daily_cap(self):
        plan = self.plan(spent=guildroute.MAIL_RUNS_PER_DAY)
        self.assertEqual(plan.runs, ())
        self.assertIn("mail runs a day is the limit", plan.notes[0])
        self.assertEqual(len(self.plan(spent=guildroute.MAIL_RUNS_PER_DAY - 1).runs), 1)

    def test_never_in_combat(self):
        plan = self.plan(_walker(state={"map_id": 1, "in_combat": 1}))
        self.assertEqual(plan.runs, ())
        self.assertIn("is in combat", plan.notes[0])

    def test_never_inside_an_instance(self):
        plan = self.plan(
            _walker(state={"map_id": 36, "in_combat": 0}, spawn=_box(map_id=36))
        )
        self.assertEqual(plan.runs, ())
        self.assertIn("inside an instance", plan.notes[0])

    def test_not_in_the_world_waits(self):
        plan = self.plan(_walker(state=None))
        self.assertEqual(plan.runs, ())
        self.assertIn("not in the world", plan.notes[0])

    def test_only_a_family_receiver_is_walked_for(self):
        plan = self.plan(routes=[replace(self.route, family=False)])
        self.assertEqual(plan.runs, ())

    def test_a_family_runner_up_is_walked_for(self):
        guildmate = replace(self.route, family=False, taker="Someone")
        route = replace(guildmate, alternates=(self.route,))
        self.assertEqual([r.taker for r in self.plan(routes=[route]).runs], ["Grog"])

    def test_a_run_ends_after_its_time(self):
        running = {"Avenah": 0.0, "Other": 1000.0}
        self.assertEqual(
            guildroute.live_runs(running, guildroute.MAIL_RUN_SECONDS + 1.0),
            {"Other": 1000.0},
        )

    def test_the_day_counts_memory_or_the_log_whichever_is_more(self):
        now = guildroute.DAY_SECONDS + 10.0
        self.assertEqual(guildroute.runs_today([0.0, 20.0, 30.0], now), 2)
        self.assertEqual(guildroute.runs_today([20.0], now, posted=4), 4)


class TheBridgeWalksAndNeverGives(unittest.TestCase):
    def body(self, name):
        bridge = (HERE / "bridge.py").read_text(encoding="utf-8")
        body = bridge[bridge.index(name) :]
        return body[: body.index("\n    async def ")]

    def test_the_walk_goes_through_the_town_slot_or_the_walk_row(self):
        body = self.body("async def _walk_route_holders(")
        self.assertIn("guildroute.plan_mail_runs(", body)
        self.assertIn("self._claim_town_slot(", body)
        self.assertIn("cohort=run.cohort", body)
        self.assertIn("if run.by_row:", body)
        self.assertIn("await self._start_mail_walk(run, now)", body)
        self.assertNotIn("INSERT", body)
        self.assertNotIn("_insert_", body)
        self.assertNotIn("'give'", body)

    def test_the_route_pass_hands_its_waiting_routes_to_the_walk(self):
        body = self.body("async def _guild_route_once(")
        self.assertIn("await self._walk_route_holders(waiting, family_names)", body)
        writer = self.body("async def _write_routes(")
        self.assertIn("self._guild_mail_runs.pop(route.holder, None)", writer)

    def test_a_run_is_reserved_before_its_claim_is_awaited(self):
        body = self.body("async def _walk_route_holders(")
        reserve = body.index("self._guild_mail_runs[run.holder] = now")
        self.assertLess(reserve, body.index("await self._claim_town_slot("))

    def test_the_walker_read_carries_combat(self):
        bridge = (HERE / "bridge.py").read_text(encoding="utf-8")
        sql = bridge[bridge.index("_ROUTE_WALKER_SQL = (") :]
        sql = sql[: sql.index("\n)\n")]
        self.assertIn("in_combat", sql)
        self.assertIn("map_id", sql)


if __name__ == "__main__":
    unittest.main()
