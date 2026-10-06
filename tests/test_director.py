"""The Watcher's director: target choice, the follow/re-appear decision, and
the command allow-list that holds ONLY observer commands."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core
import director as d
import relay

W = d.WATCHER_NAME


def spot(name, map_id=0, inst=0, x=0.0, y=0.0, z=0.0, combat=False, grp=0):
    return d.Spot(name, map_id, inst, x, y, z, combat, grp)


def run(
    rid,
    guild="Bonkers",
    kw="ragefire",
    tank="Tanky",
    members=("Tanky", "Heal"),
    state="inside",
    created=1.0,
):
    return d.Run(rid, guild, kw, tank, tuple(members), state, created)


class AllowList(unittest.TestCase):
    def test_boot_and_move_lines_pass(self):
        for c in (
            *d.BOOT_COMMANDS,
            ".appear Grug",
            "appear grug",
            ".instance unbind all",
            d.HOP_COMMAND,
            ".modify speed all 4",
        ):
            self.assertTrue(d.observer_allows(c), c)

    def test_nothing_else_passes(self):
        bad = [
            ".group invite Grug",
            ".summon Grug",
            ".gm visible on",
            ".gm off",
            ".gm fly off",
            ".cheat god off",
            ".appear",
            ".appear Grug now",
            ".appear Gr ug",
            ".appear Grug1",
            ".instance unbind",
            ".instance unbind 389",
            ".modify speed all 7",
            ".modify speed all 0",
            ".modify speed 2",
            ".modify hp 1",
            ".die",
            ".additem 25",
            ".tele orgrimmar",
            ".tele del x",
            ".go xyz 1 2 3",
            ".revive",
            ".account set gmlevel x 3",
            ".server shutdown",
            ".gm on; .die",
            ".gm on\n.die",
            "say hi",
            "",
            ".",
            ".cast 1",
            ".appear Grug\n.die",
            ".npc add 1",
            ".learn all",
            ".aura 1",
            ".damage 99",
        ]
        for c in bad:
            self.assertFalse(d.observer_allows(c), repr(c))

    def test_every_command_the_director_emits_passes(self):
        w = spot(W, 0, 0)
        for t in (spot("Grug", 389, 3), spot("Zug", 489, 5), spot("Og", 1, 0, x=900.0)):
            dec = d.decide(w, t, now=100.0, booted_at=0.0, new_target=True)
            self.assertTrue(d.commands_ok(dec.commands), dec)
        self.assertTrue(d.commands_ok(d.BOOT_COMMANDS))

    def test_general_gm_surface_is_wider_than_the_observer_surface(self):
        # relay admits `group`; the observer list must not.
        self.assertTrue(relay.gm_is_allowed(".group invite Grug"))
        self.assertFalse(d.observer_allows(".group invite Grug"))

    def test_discord_line_for_the_watcher_is_held_to_the_list(self):
        allowed = frozenset({"1"})
        ok = core.parse_directive(f"@{W} .appear Grug", "1", allowed)
        self.assertIsInstance(ok[0], relay.GmCommand)
        for line in (
            f"@{W} .group invite Grug",
            f"@{W} /say hi",
            f"@{W} follow me",
            f"@{W} .gm visible on",
        ):
            got = core.parse_directive(line, "1", allowed)
            self.assertEqual(len(got), 1, line)
            self.assertIsInstance(got[0], core.Reply, line)


class Grammar(unittest.TestCase):
    def test_orders(self):
        cases = {
            "watch Grug": d.Spec("character", "Grug"),
            "Grug": d.Spec("character", "Grug"),
            "watch character Zug": d.Spec("character", "Zug"),
            "watch family": d.Spec("family", ""),
            "watch family Cave": d.Spec("family", "cave"),
            "watch guild Bonkers": d.Spec("guild", "Bonkers"),
            "watch run 285": d.Spec("run", "285"),
            "watch dungeon Ragefire": d.Spec("dungeon", "ragefire"),
            "watch bg": d.Spec("bg"),
            "watch raid": d.Spec("raid"),
            "watch off": d.Spec("off"),
        }
        for text, want in cases.items():
            self.assertEqual(d.parse_watch(text), want, text)

    def test_bad_orders(self):
        for text in (
            "watch",
            "watch run abc",
            "watch dungeon",
            "watch guild",
            "watch x",
            "watch family a;b",
            "watch Grug Zug",
            "watch run 99999999999",
        ):
            self.assertIsInstance(d.parse_watch(text), d.SpecError, text)

    def test_message_prefix(self):
        self.assertIsNotNone(d.parse_watch_message("watch Grug"))
        self.assertIsNone(d.parse_watch_message("watcher status"))
        self.assertIsNone(d.parse_watch_message("who is online"))


class Targets(unittest.TestCase):
    def test_named_character_ignores_case_and_the_watcher_itself(self):
        spots = [spot("Grug"), spot(W)]
        self.assertEqual(d.pick_target(d.Spec("character", "grug"), spots).name, "Grug")
        self.assertIsInstance(d.pick_target(d.Spec("character", W), spots), d.Refused)
        self.assertEqual(
            d.pick_target(d.Spec("character", "Nobody"), spots).code, d.R_TARGET_OFFLINE
        )

    def test_family_head(self):
        heads = {"cave": "Grug", "alt": "Thak"}
        spots = [spot("Grug"), spot("Thak")]
        self.assertEqual(
            d.pick_target(d.Spec("family"), spots, heads=heads).name, "Grug"
        )
        self.assertEqual(
            d.pick_target(d.Spec("family", "alt"), spots, heads=heads).name, "Thak"
        )
        self.assertEqual(
            d.pick_target(d.Spec("family", "zz"), spots, heads=heads).code,
            d.R_NO_TARGET,
        )
        self.assertEqual(
            d.pick_target(d.Spec("family"), [spot("Thak")], heads=heads).code,
            d.R_TARGET_OFFLINE,
        )

    def test_dungeon_and_run_pick_the_tank(self):
        spots = [spot("Tanky", 389, 3), spot("Heal", 389, 3)]
        r = [run(1)]
        for spec in (
            d.Spec("dungeon", "rage"),
            d.Spec("run", "1"),
            d.Spec("guild", "bonkers"),
        ):
            self.assertEqual(d.pick_target(spec, spots, runs=r).name, "Tanky", spec)

    def test_dead_tank_falls_to_a_member_and_sticks(self):
        spots = [spot("Heal", 389, 3), spot("Zed", 389, 3)]
        r = [run(1, members=("Tanky", "Heal", "Zed"))]
        self.assertEqual(d.pick_target(d.Spec("run", "1"), spots, runs=r).name, "Heal")
        self.assertEqual(
            d.pick_target(d.Spec("run", "1"), spots, runs=r, current="Zed").name, "Zed"
        )

    def test_guild_chooses_its_busiest_run_then_newest(self):
        spots = [spot("A", 389, 3), spot("B", 389, 3), spot("C", 43, 7)]
        r = [
            run(1, tank="A", members=("A", "B"), created=1),
            run(2, tank="C", members=("C",), created=9),
        ]
        self.assertEqual(
            d.pick_target(d.Spec("guild", "Bonkers"), spots, runs=r).name, "A"
        )

    def test_runs_not_inside_are_refused(self):
        spots = [spot("Tanky", 389, 3)]
        r = [run(1, state="ended")]
        self.assertEqual(
            d.pick_target(d.Spec("run", "1"), spots, runs=r).code, d.R_NO_TARGET
        )
        self.assertEqual(
            d.pick_target(d.Spec("dungeon", "rage"), spots, runs=r).code, d.R_NO_TARGET
        )
        self.assertEqual(
            d.pick_target(d.Spec("run", "9"), spots, runs=r).code, d.R_NO_TARGET
        )

    def test_bg_picks_the_fullest_battleground_and_its_fight(self):
        spots = [
            spot("A", 489, 1, 0, 0),
            spot("B", 489, 1, 5, 0, combat=True),
            spot("C", 489, 1, 6, 0, combat=True),
            spot("D", 489, 2),
            spot("Far", 0),
        ]
        got = d.pick_target(d.Spec("bg"), spots)
        self.assertIn(got.name, ("B", "C"))
        self.assertEqual(d.pick_target(d.Spec("bg"), spots, current="A").name, "A")
        self.assertEqual(
            d.pick_target(d.Spec("bg"), [spot("Far", 0)]).code, d.R_NO_TARGET
        )

    def test_raid_prefers_a_seated_tank(self):
        spots = [spot("T", 409, 4), spot("H", 409, 4), spot("X", 409, 4, combat=True)]
        got = d.pick_target(
            d.Spec("raid"), spots, seats=[("T", "tank"), ("H", "healer")]
        )
        self.assertEqual(got.name, "T")
        self.assertEqual(
            d.pick_target(d.Spec("raid"), [spot("Z", 0)]).code, d.R_NO_TARGET
        )


class Decisions(unittest.TestCase):
    def go(self, w, t, **kw):
        kw.setdefault("now", 100.0)
        kw.setdefault("booted_at", 0.0)
        return d.decide(w, t, **kw)

    def test_refusals_come_first_and_are_named(self):
        t = spot("Grug", 389, 3)
        self.assertEqual(self.go(None, t).code, d.R_WATCHER_OFFLINE)
        self.assertEqual(self.go(spot(W), None).code, d.R_TARGET_OFFLINE)
        self.assertEqual(self.go(spot(W), spot(W)).code, d.R_SELF)
        self.assertEqual(self.go(spot(W), spot("Grug", 559, 2)).code, d.R_ARENA)
        self.assertEqual(self.go(spot(W, grp=77), t).code, d.R_GROUPED)
        self.assertEqual(self.go(spot(W), spot("Grug", 389, 0)).code, d.R_UNRESOLVED)

    def test_a_grouped_watcher_never_acts_even_for_an_overworld_target(self):
        self.assertEqual(self.go(spot(W, grp=5), spot("Grug", 0)).action, d.REFUSE)

    def test_first_tick_boots_then_settles(self):
        w, t = spot(W), spot("Grug", 1, 0, 500.0)
        first = d.decide(w, t, now=100.0, booted_at=None)
        self.assertEqual((first.action, first.commands), (d.BOOT, d.BOOT_COMMANDS))
        self.assertEqual(d.decide(w, t, now=104.0, booted_at=100.0).action, d.HOLD)
        self.assertEqual(
            d.decide(w, t, now=110.0, booted_at=100.0, new_target=True).action, d.APPEAR
        )

    def test_in_range_follows_and_does_not_teleport(self):
        got = self.go(spot(W, 1, 0, 0, 0), spot("Grug", 1, 0, 20, 0))
        self.assertEqual((got.action, got.commands), (d.FOLLOW, ()))
        self.assertEqual(got.client_hint, "/follow Grug")

    def test_target_moves_away_reappears_when_the_gap_allows(self):
        w, t = spot(W, 1, 0, 0, 0), spot("Grug", 1, 0, 200, 0)
        got = self.go(w, t, moves=[50.0])
        self.assertEqual((got.action, got.commands), (d.APPEAR, (".appear Grug",)))
        self.assertEqual(self.go(w, t, moves=[95.0]).code, d.R_RATE)

    def test_new_target_skips_the_gap_but_not_the_budget(self):
        w, t = spot(W, 1), spot("Grug", 0, 0, 900)
        self.assertEqual(self.go(w, t, moves=[99.0], new_target=True).action, d.APPEAR)
        spent = [10.0 + i for i in range(d.APPEAR_BUDGET[0])]
        self.assertEqual(self.go(w, t, moves=spent, new_target=True).code, d.R_RATE)

    def test_budget_window_expires(self):
        w, t = spot(W, 1), spot("Grug", 0, 0, 900)
        old = [1.0 + i for i in range(d.APPEAR_BUDGET[0])]
        self.assertEqual(self.go(w, t, now=2000.0, moves=old).action, d.APPEAR)

    def test_into_an_instance_unbinds_first(self):
        got = self.go(spot(W, 1), spot("Tanky", 389, 3), new_target=True)
        self.assertEqual(got.commands, (".instance unbind all", ".appear Tanky"))

    def test_same_instance_far_away_just_appears(self):
        got = self.go(spot(W, 389, 3, 0), spot("Tanky", 389, 3, 300), new_target=True)
        self.assertEqual(got.commands, (".appear Tanky",))

    def test_a_different_instance_of_the_same_map_hops_out_first(self):
        for m in (389, 489):
            got = self.go(spot(W, m, 2), spot("T", m, 3), new_target=True)
            self.assertEqual((got.action, got.commands), (d.HOP, (d.HOP_COMMAND,)), m)

    def test_battleground_target_appears_without_unbind(self):
        got = self.go(spot(W, 0), spot("Flag", 489, 5), new_target=True)
        self.assertEqual(got.commands, (".appear Flag",))


class Memory(unittest.TestCase):
    def test_login_resets_the_boot(self):
        m = d.Memory(booted_at=5.0, was_present=False)
        m.on_presence(True)
        self.assertIsNone(m.booted_at)
        m.booted_at = 9.0
        m.on_presence(True)
        self.assertEqual(m.booted_at, 9.0)
        m.on_presence(False)
        m.on_presence(True)
        self.assertIsNone(m.booted_at)

    def test_order_change_resets_the_target_and_moves_are_pruned(self):
        m = d.Memory()
        self.assertTrue(m.on_order("guild Bonkers"))
        m.target = "Tanky"
        self.assertFalse(m.on_order("guild Bonkers"))
        self.assertTrue(m.on_order("raid"))
        self.assertEqual(m.target, "")
        m.record_move(0.0)
        m.record_move(10000.0)
        self.assertEqual(m.moves, [10000.0])

    def test_mandate_expiry(self):
        self.assertFalse(d.mandate_active(None))
        self.assertFalse(d.mandate_active({"ttl": 0}))
        self.assertTrue(d.mandate_active({"ttl": 5}))


if __name__ == "__main__":
    unittest.main()


class Surfaces(unittest.TestCase):
    def test_observer_card_needs_an_explicit_streamed_listing(self):
        import family
        import watchwall

        row = {
            "name": W,
            "level": 80,
            "race": 1,
            "class": 1,
            "health": 10,
            "max_health": 10,
            "in_combat": 0,
            "is_bot": 0,
            "group_leader": 0,
            "map_id": 0,
            "zone_id": 1,
            "pos_x": 0,
            "pos_y": 0,
            "age_seconds": 1,
        }

        class Geo:
            def place(self, *a):
                return None

            def zone_name(self, *a):
                return "somewhere"

            def zone_by_id(self, *a):
                return "somewhere"

        saved = family._STREAMED
        try:
            family._STREAMED = frozenset()
            self.assertEqual(family.build_observers([row], Geo(), (W,)), [])
            family._STREAMED = frozenset({"Grug", W})
            cards = family.build_observers([row], Geo(), (W,))
            self.assertEqual(len(cards), 1)
            self.assertTrue(cards[0]["broadcast_url"])
            self.assertTrue(cards[0]["present"])
            self.assertEqual(cards[0]["role"], "observer")
            # the host watchdog's reader: any named entry with both keys
            gone = family.build_observers([], Geo(), (W,))[0]
            self.assertTrue(gone["broadcast_url"])
            self.assertFalse(gone["present"])
            wall = watchwall.build_heads([], cards)
            self.assertEqual([m["name"] for m in wall["members"]], [W])
        finally:
            family._STREAMED = saved

    def test_http_door_is_closed_without_a_token_and_compares_in_constant_time(self):
        src = open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "map_server.py",
            )
        ).read()
        body = src[src.index("def _director_post") : src.index("def _read_json_body")]
        self.assertIn("if not _DIRECTOR_TOKEN", body)
        self.assertIn("hmac.compare_digest", body)
        self.assertLess(
            body.index("hmac.compare_digest"), body.index("_read_json_body")
        )
        self.assertIn("director.parse_watch", body)
