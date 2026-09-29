"""The guild coordinator: groups, doors, Jev's two choices, the learning loop.

guildrun.py forms a bot guild's own five-man by level band and role, offers
Jev the compositions and the dungeons that fit with each one's record, and
falls back on that record (the prior) when Jev is below its floor or silent.
mod-overseer's `finder-run` verb carries the pick out and writes the outcome
on the row, which the bridge folds into overseer_guild_run. These pin the
decisions with the real Jev client over a fake transport (no API call), and
the wiring in the bridge, the map server and the page as source.
"""

import asyncio
import pathlib
import unittest

import guildrun
import jev
from test_jev_items import FakeJev

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
PAGE = (HERE / "index.html").read_text(encoding="utf-8")

WARRIOR, PALADIN, ROGUE, PRIEST, MAGE, WARLOCK, DRUID = 1, 2, 4, 5, 8, 9, 11
PROTECTION_TALENT = "12301"
HOLY_TALENT = "14913"


def row(name, level, class_id, **kw):
    out = {
        "name": name,
        "level": level,
        "class_id": class_id,
        "map_id": 0,
        # An orc: a band the Horde's own doors (Ragefire Chasm) are open to.
        "race": 2,
        "in_combat": 0,
        "health": 300,
        "group_leader": 0,
        "guild_name": "Cave",
        "talent_spells": None,
        "target_tree": "",
    }
    out.update(kw)
    return out


def member(name, level, class_id, **kw):
    return guildrun.member_from_row(row(name, level, class_id, **kw))


def cave_band():
    """Seven free Cave members at 14 to 17: a Protection warrior, a Fury
    warrior, a Holy priest, a paladin with no talents and the raid plan's
    Holy, and three damage dealers."""
    return [
        member("Tanky", 20, WARRIOR, talent_spells=PROTECTION_TALENT),
        member("Furio", 19, WARRIOR, talent_spells="61216"),
        member("Healy", 19, PRIEST, talent_spells=HOLY_TALENT),
        member("Pally", 19, PALADIN, target_tree="Holy"),
        member("Stabby", 19, ROGUE),
        member("Zappy", 18, MAGE),
        member("Locky", 17, WARLOCK),
    ]


DOORS = guildrun.doors({389: 8, 36: 10, 43: 10, 33: 14})


class TheSwitchAndTheLimits(unittest.TestCase):
    def test_off_unless_it_is_turned_on(self):
        self.assertFalse(guildrun.enabled({}))
        self.assertFalse(guildrun.enabled({"GUILD_RUNS": "off"}))
        self.assertTrue(guildrun.enabled({"GUILD_RUNS": "on"}))

    def test_the_cap_is_two_and_clamped(self):
        self.assertEqual(guildrun.limits({}).max_groups, 2)
        self.assertEqual(
            guildrun.limits({"GUILD_RUNS_MAX": "40"}).max_groups,
            guildrun.HARD_MAX_GROUPS,
        )
        self.assertEqual(guildrun.limits({"GUILD_RUNS_MAX": "x"}).max_groups, 2)
        self.assertEqual(guildrun.limits({}).guilds, ("Cave", "Bonkers"))
        self.assertGreaterEqual(
            guildrun.limits({"GUILD_RUNS_EVERY_SECONDS": "1"}).form_every_seconds, 60
        )


class WhoCanGo(unittest.TestCase):
    def test_the_talent_tree_decides_the_seat(self):
        tank = member("Tanky", 16, WARRIOR, talent_spells=PROTECTION_TALENT)
        fury = member("Furio", 15, WARRIOR, talent_spells="61216")
        self.assertEqual(tank.fit(guildrun.TANK), "spec")
        self.assertEqual(fury.fit(guildrun.TANK), "class")
        self.assertEqual(member("Zappy", 14, MAGE).fit(guildrun.TANK), "")

    def test_the_raid_plan_seat_stands_in_before_any_talent(self):
        self.assertEqual(
            member("Pally", 14, PALADIN, target_tree="Holy").fit(guildrun.HEALER),
            "spec",
        )

    def test_what_keeps_a_member_home(self):
        free = member("A", 15, MAGE)
        self.assertEqual(guildrun.why_not(free, set(), set(), set()), "")
        self.assertEqual(guildrun.why_not(free, set(), set(), {"A"}), "a family member")
        self.assertEqual(guildrun.why_not(free, {"A"}, set(), set()), "in a guild run")
        self.assertEqual(
            guildrun.why_not(free, set(), {"A"}, set()), "resting after a run"
        )
        self.assertEqual(
            guildrun.why_not(
                member("A", 15, MAGE, group_leader=9), set(), set(), set()
            ),
            "already in a group",
        )
        self.assertEqual(
            guildrun.why_not(member("A", 15, MAGE, map_id=36), set(), set(), set()),
            "inside an instance",
        )
        self.assertEqual(
            guildrun.why_not(member("A", 15, MAGE, health=0), set(), set(), set()),
            "dead",
        )


class OnlyAMemberWhoCanGoIsPicked(unittest.TestCase):
    """The first three runs after a restart all failed before entering: five
    members the old process had just logged out, then a ghost twice. A ghost
    reports health 1, so health alone passed it."""

    def test_a_ghost_is_dead_though_it_reports_health(self):
        ghost = member("Eazoth", 16, WARRIOR, health=1, has_corpse=1)
        self.assertFalse(ghost.alive)
        self.assertEqual(guildrun.why_not(ghost, set(), set(), set()), "dead")
        self.assertTrue(member("Hurt", 16, WARRIOR, health=1, has_corpse=0).alive)
        # Resurrected in place, its old corpse row still standing.
        self.assertTrue(member("Grog", 36, WARRIOR, health=1121, has_corpse=1).alive)
        self.assertFalse(member("Fallen", 16, WARRIOR, health=0).alive)

    def test_an_offline_member_is_not_picked(self):
        away = member("Tynneda", 16, MAGE, online=0)
        self.assertEqual(guildrun.why_not(away, set(), set(), set()), "offline")

    def test_a_member_a_refusal_named_sits_out(self):
        free = member("Daidanden", 14, WARRIOR)
        self.assertEqual(
            guildrun.why_not(free, set(), set(), set(), {"Daidanden"}),
            "refused a run just now",
        )

    def test_nobody_is_picked_while_a_restart_settles(self):
        self.assertTrue(guildrun.settling(2))
        self.assertTrue(guildrun.settling(guildrun.SETTLE_SECONDS - 1))
        self.assertFalse(guildrun.settling(guildrun.SETTLE_SECONDS))
        self.assertFalse(guildrun.settling(None))

    def test_the_refused_member_is_read_off_the_why(self):
        self.assertEqual(guildrun.refused_member("'Daidanden' is dead"), "Daidanden")
        self.assertEqual(
            guildrun.refused_member("'Bramitho' is locked out of it (level)"),
            "Bramitho",
        )
        self.assertEqual(guildrun.refused_member("target not online"), "")
        self.assertEqual(
            guildrun.refused_member("the realm already has 2 guild groups out"), ""
        )
        self.assertEqual(
            guildrun.benched(
                [
                    {"outcome": "refused", "why": "'Eazoth' is dead"},
                    {"outcome": "lost", "why": "'Selie' is not in the world"},
                    {"outcome": "refused", "why": "the door has no finder entry"},
                ]
            ),
            {"Eazoth"},
        )

    def test_a_refusal_over_one_member_is_formed_again_at_once(self):
        refused = {"state": "ended", "outcome": "refused", "why": "'Eazoth' is dead"}
        self.assertTrue(guildrun.swap_now([refused]))
        self.assertTrue(guildrun.swap_now([refused, refused]))
        # A run formed since heads the list: no second swap while it is out.
        queued = {"state": "queued", "outcome": "", "why": ""}
        self.assertFalse(guildrun.swap_now([queued, refused]))
        # A refusal no swap can fix, and a streak at the cap, wait the spacing.
        realm = {"state": "ended", "outcome": "refused", "why": "the finder is off"}
        self.assertFalse(guildrun.swap_now([realm]))
        self.assertFalse(guildrun.swap_now([refused] * guildrun.MAX_SWAPS))
        self.assertFalse(guildrun.swap_now([]))

    def test_only_a_run_that_went_in_rests_its_members(self):
        self.assertNotIn("refused", guildrun.WENT_IN)
        self.assertNotIn("lost", guildrun.WENT_IN)
        facts = BRIDGE[BRIDGE.index("def _fetch_guild_run_facts") :]
        facts = facts[: facts.index("\ndef ")]
        resting = facts[
            facts.index("resting = set()") - 400 : facts.index("resting = set()")
        ]
        self.assertIn("guildrun.WENT_IN", resting)

    def test_the_bridge_reads_online_and_the_corpse(self):
        sql = BRIDGE[BRIDGE.index("_GUILD_RUN_MEMBERS_SQL = (") :]
        sql = sql[: sql.index("\n)\n")]
        self.assertNotIn("c.online", sql)
        self.assertIn("(s.updated_at > NOW() - INTERVAL 60 SECOND) AS online", sql)
        self.assertIn("FROM corpse k WHERE k.guid = s.guid) AS has_corpse", sql)

    def test_the_pass_settles_then_swaps_then_passes_the_bench(self):
        once = BRIDGE[BRIDGE.index("async def _guild_run_once") :]
        once = once[: once.index("    async def ", 10)]
        self.assertLess(
            once.index('guildrun.settling(gate["uptime"])'),
            once.index("_fetch_guild_run_facts"),
        )
        self.assertIn("if (not swap and self._guild_run_formed_at is not None", once)
        self.assertIn('facts["benched"])', once)


class EachGuildStaysOnItsOwnSide(unittest.TestCase):
    """60 of 159 guild deaths in 30 minutes on wow-dev were Alliance members
    killed by Razor Hill Grunts after Cave runs into Ragefire Chasm, whose door
    is inside Orgrimmar, left them on the Horde side."""

    HUMAN, ORC = 1, 2

    def test_an_alliance_guild_is_not_sent_into_orgrimmar(self):
        levels = [17, 17, 18, 18, 18]
        alliance = [
            d.keyword for d in guildrun.fitting_doors(levels, DOORS, "Alliance")
        ]
        horde = [d.keyword for d in guildrun.fitting_doors(levels, DOORS, "Horde")]
        self.assertNotIn("ragefire", alliance)
        self.assertIn("ragefire", horde)
        self.assertNotIn(
            "stockades",
            [d.keyword for d in guildrun.fitting_doors([26] * 5, DOORS, "Horde")],
        )

    def test_the_faction_is_read_off_the_members(self):
        cave = [member("A", 12, MAGE, race=self.HUMAN), member("B", 12, MAGE, race=7)]
        self.assertEqual(guildrun.faction_of(cave), "Alliance")
        self.assertEqual(
            guildrun.faction_of([member("C", 12, MAGE, race=self.ORC)]), "Horde"
        )
        self.assertEqual(
            guildrun.faction_of(cave + [member("C", 12, MAGE, race=self.ORC)]), ""
        )

    def test_a_member_on_the_other_side_hearths_home(self):
        in_durotar = member("Bramitho", 14, PRIEST, zone_id=14)
        self.assertTrue(guildrun.stranded(in_durotar, "Alliance"))
        self.assertFalse(guildrun.stranded(in_durotar, "Horde"))
        inside = member("Cesca", 13, WARLOCK, map_id=389)
        self.assertTrue(guildrun.stranded(inside, "Alliance"))
        self.assertFalse(
            guildrun.stranded(
                member("G", 13, MAGE, zone_id=14, health=1, has_corpse=1), "Alliance"
            )
        )
        self.assertFalse(
            guildrun.stranded(
                member("F", 13, MAGE, zone_id=14, in_combat=1), "Alliance"
            )
        )
        self.assertFalse(
            guildrun.stranded(member("W", 13, MAGE, zone_id=40), "Alliance")
        )

    def test_each_member_is_judged_by_its_own_guild_and_runs_are_left_alone(self):
        cave = [
            member("A", 13, MAGE, race=self.HUMAN, zone_id=14),
            member("B", 13, MAGE, race=self.HUMAN, zone_id=14),
        ]
        bonkers = [
            member("C", 13, MAGE, race=self.ORC, zone_id=14, guild_name="Bonkers")
        ]
        self.assertEqual(guildrun.stranded_names(cave + bonkers, {"B"}), ["A"])

    def test_the_bridge_hearths_the_stranded_every_cycle(self):
        loop = BRIDGE[BRIDGE.index("async def _guild_run_loop") :]
        loop = loop[: loop.index("async def _guild_run_once")]
        self.assertLess(
            loop.index("_hearth_stranded_guild_members"),
            loop.index("if guildrun.enabled():"),
        )
        rescue = BRIDGE[BRIDGE.index("def _hearth_stranded_guild_members") :]
        rescue = rescue[: rescue.index("\ndef ")]
        self.assertIn("_MOVEMENT_HEARTHED", rescue)
        self.assertIn("_insert_hearth(name, guildrun.SOURCE)", rescue)


class EachGuildRunsItsOwnDoorsInGear(unittest.TestCase):
    """12 guild runs entered Ragefire Chasm on wow-dev and none cleared: members
    at levels 10 to 16 wore item level 2 to 5 gear."""

    def test_each_side_is_offered_only_its_own_doors(self):
        alliance = {
            d.keyword for d in guildrun.fitting_doors([19] * 5, DOORS, "Alliance")
        }
        horde = {d.keyword for d in guildrun.fitting_doors([17] * 5, DOORS, "Horde")}
        self.assertLessEqual(alliance, guildrun.GUILD_DOORS["Alliance"])
        self.assertIn("deadmines", alliance)
        self.assertLessEqual(horde, guildrun.GUILD_DOORS["Horde"])
        self.assertIn("ragefire", horde)

    def test_an_under_geared_member_is_not_sent(self):
        weak = member("Bramitho", 14, PRIEST, gear_ilvl=4.0)
        self.assertEqual(
            guildrun.why_not(weak, set(), set(), set()), "gear too weak for a dungeon"
        )
        # Exactly GEAR_GAP under is still sent; only more than that is not.
        edge = member("Edge", 16, WARRIOR, gear_ilvl=10.0)
        self.assertEqual(guildrun.why_not(edge, set(), set(), set()), "")
        ready = member("Selie", 14, WARRIOR, gear_ilvl=9.0)
        self.assertEqual(guildrun.why_not(ready, set(), set(), set()), "")
        self.assertEqual(
            guildrun.why_not(member("U", 14, MAGE), set(), set(), set()), ""
        )

    def test_the_gear_gate_can_be_lifted_for_the_fallback(self):
        weak = member("Weak", 14, WARRIOR, gear_ilvl=2.0)
        self.assertEqual(
            guildrun.why_not(weak, set(), set(), set()), "gear too weak for a dungeon"
        )
        self.assertEqual(
            guildrun.why_not(weak, set(), set(), set(), gear_gate=False), ""
        )
        # Lifting the gear gate lifts nothing else.
        dead = member("Dead", 14, WARRIOR, gear_ilvl=2.0, health=0)
        self.assertEqual(
            guildrun.why_not(dead, set(), set(), set(), gear_gate=False), "dead"
        )

    def test_the_bridge_falls_back_when_the_gear_gate_leaves_no_run(self):
        self.assertIn("_free_members(False)", BRIDGE)
        self.assertIn("forming without it", BRIDGE)

    def test_the_bridge_reads_worn_item_level(self):
        sql = BRIDGE[BRIDGE.index("_GUILD_RUN_MEMBERS_SQL = (") :]
        sql = sql[: sql.index("\n)\n")]
        self.assertIn("AVG(it.ItemLevel)", sql)
        self.assertIn("AS gear_ilvl", sql)


class TheHostileCapitalDoorIsNeverOffered(unittest.TestCase):
    """Cave (Alliance) never runs Ragefire Chasm (map 389) and Bonkers (Horde)
    never runs The Stockade (map 34), at any level, and a side whose faction
    cannot be read is held to the doors both sides may use."""

    ALLIANCE_MAP, HORDE_MAP = 34, 389

    def offered(self, level, faction):
        return [
            d.keyword
            for d in guildrun.fitting_doors([level] * 5, guildrun.doors(), faction)
        ]

    def test_alliance_never_gets_ragefire_at_any_level(self):
        for level in range(1, 61):
            self.assertNotIn("ragefire", self.offered(level, "Alliance"), level)

    def test_horde_never_gets_the_stockade_at_any_level(self):
        for level in range(1, 61):
            self.assertNotIn("stockades", self.offered(level, "Horde"), level)

    def test_each_side_climbs_its_own_doors_in_level_order(self):
        """The first door offered never falls back to a lower floor as the
        group grows: the doors a side uses come in the order of their floors."""
        by_keyword = {d.keyword: d for d in guildrun.doors()}
        for faction in ("Alliance", "Horde"):
            floors = []
            for level in range(1, 61):
                offered = self.offered(level, faction)
                for keyword in offered:
                    door = by_keyword[keyword]
                    self.assertIn(keyword, guildrun.GUILD_DOORS[faction])
                    self.assertGreaterEqual(level, door.floor)
                    self.assertLessEqual(level, door.ceiling)
                    self.assertNotIn(
                        door.map_id, guildrun.HOSTILE_CAPITAL_DUNGEONS[faction]
                    )
                if offered:
                    floors.append(by_keyword[offered[0]].floor)
            self.assertEqual(floors, sorted(floors), faction)

    def test_an_unreadable_faction_is_offered_neither_capital_door(self):
        """Race 0 (a snapshot without a race) or a mixed roster reads as no
        faction; that must not lift the filter."""
        for level in range(1, 61):
            offered = self.offered(level, "")
            self.assertNotIn("ragefire", offered, level)
            self.assertNotIn("stockades", offered, level)
        self.assertEqual(self.offered(19, ""), ["wailing", "deadmines"])

    def test_the_hostile_capital_map_ids_are_the_capital_dungeons(self):
        self.assertEqual(guildrun.HOSTILE_CAPITAL_DUNGEONS["Alliance"], {389})
        self.assertEqual(guildrun.HOSTILE_CAPITAL_DUNGEONS["Horde"], {34})

    def test_a_member_inside_the_hostile_dungeon_map_is_stranded(self):
        alliance = member("A", 19, MAGE, race=1, map_id=389)
        horde = member("H", 19, MAGE, race=2, map_id=34, guild_name="Bonkers")
        self.assertEqual(guildrun.stranded_names([alliance, horde], set()), ["A", "H"])
        own = member("O", 19, MAGE, race=1, map_id=34)
        self.assertEqual(guildrun.stranded_names([own], set()), [])


class EachSideHasADoorAtEveryLevelItCanPlay(unittest.TestCase):
    """wow-overseer#414: the per-side door lists stopped short, so the Horde
    was offered no door from level 25 up and the Alliance none from level 33
    up. Every dungeon mod-overseer's finder can queue is on each side's ladder,
    the hostile capital's own dungeon excepted."""

    # Doors the module can queue through the dungeon finder: one finder row on
    # the map, or a wing the door's own landing picks out (Maraudon).
    QUEUEABLE = {
        "wailing", "deadmines", "shadowfang", "blackfathom", "scarlet",
        "gnomeregan", "razorfen-kraul", "razorfen-downs", "uldaman",
        "zulfarrak", "ragefire", "stockades", "maraudon-orange", "maraudon-purple", "sunken-temple",
        "blackrock-depths", "scholomance",
    }  # fmt: skip
    # Doors the finder cannot resolve today (see guildrun.BLOCKED_DOORS).
    BLOCKED = {
        "scarlet-library", "scarlet-armory", "scarlet-cathedral",
        "lower-blackrock-spire", "dire-maul-east-east", "dire-maul-west-north",
        "dire-maul-north",
    }  # fmt: skip
    FIRST_LEVEL = {"Alliance": 17, "Horde": 15}

    def offered(self, level, faction):
        return [
            d.keyword
            for d in guildrun.fitting_doors([level] * 5, guildrun.doors(), faction)
        ]

    def test_each_side_uses_every_queueable_door_but_the_hostile_capital(self):
        self.assertEqual(
            guildrun.GUILD_DOORS["Alliance"], self.QUEUEABLE - {"ragefire"}
        )
        self.assertEqual(guildrun.GUILD_DOORS["Horde"], self.QUEUEABLE - {"stockades"})

    def test_no_blocked_door_is_on_either_ladder(self):
        for faction, keywords in guildrun.GUILD_DOORS.items():
            self.assertFalse(keywords & self.BLOCKED, faction)
        self.assertEqual(set(guildrun.BLOCKED_DOORS), self.BLOCKED)

    def test_every_level_from_the_first_door_to_sixty_has_a_door(self):
        for faction, first in self.FIRST_LEVEL.items():
            for level in range(first, 61):
                self.assertTrue(self.offered(level, faction), (faction, level))

    def test_the_ladder_climbs_through_the_high_dungeons(self):
        self.assertIn("razorfen-kraul", self.offered(32, "Horde"))
        self.assertIn("zulfarrak", self.offered(40, "Alliance"))
        self.assertIn("sunken-temple", self.offered(52, "Horde"))
        self.assertIn("blackrock-depths", self.offered(56, "Alliance"))
        self.assertIn("scholomance", self.offered(60, "Horde"))


class TheDoorsThatFit(unittest.TestCase):
    def test_a_band_of_seventeen_to_nineteen_gets_ragefire_first(self):
        keywords = [
            d.keyword
            for d in guildrun.fitting_doors([17, 17, 18, 18, 19], DOORS, "Horde")
        ]
        self.assertEqual(keywords[0], "ragefire")
        self.assertNotIn("shadowfang", keywords)

    def test_the_guide_minimum_goes_in(self):
        """Wailing Caverns has floor 17: a mean of 17.0 is offered, 16.8 is not."""
        at = [
            d.keyword
            for d in guildrun.fitting_doors([17, 17, 17, 17, 17], DOORS, "Alliance")
        ]
        under = [
            d.keyword
            for d in guildrun.fitting_doors([16, 17, 17, 17, 17], DOORS, "Horde")
        ]
        self.assertIn("wailing", at)
        self.assertIn("deadmines", at)
        self.assertNotIn("wailing", under)
        self.assertIn("ragefire", under)

    def test_a_group_at_the_ragefire_floor_is_sent(self):
        keywords = [
            d.keyword
            for d in guildrun.fitting_doors([15, 15, 15, 15, 16], DOORS, "Horde")
        ]
        self.assertEqual(keywords, ["ragefire"])

    def test_a_group_below_every_floor_stays_home(self):
        self.assertEqual(guildrun.fitting_doors([13, 14, 14, 14, 14], DOORS), [])

    def test_the_finders_own_minimum_keeps_a_low_member_out(self):
        floors = guildrun.doors({389: 15})
        self.assertNotIn(
            "ragefire",
            [d.keyword for d in guildrun.fitting_doors([13, 15, 15, 16, 16], floors)],
        )

    def test_an_outgrown_door_is_not_offered(self):
        keywords = [
            d.keyword for d in guildrun.fitting_doors([20, 21, 22, 22, 22], DOORS)
        ]
        self.assertNotIn("ragefire", keywords)

    def test_the_band_is_the_average_level(self):
        self.assertEqual(guildrun.band_of([13, 14, 15, 15, 16]), "10-14")
        self.assertEqual(guildrun.band_of([15, 15, 16, 16, 16]), "15-19")


class TheCompositions(unittest.TestCase):
    def test_the_best_tank_and_healer_by_tree_lead_the_options(self):
        comps = guildrun.compositions(cave_band())
        self.assertGreaterEqual(len(comps), 2)
        first = comps[0]
        self.assertEqual(first.tank.name, "Tanky")
        self.assertIn(first.healer.name, ("Healy", "Pally"))
        self.assertEqual(first.key, "spec-tank/spec-healer")
        self.assertEqual(len(set(first.names)), 5)

    def test_each_alternative_changes_a_seat(self):
        comps = guildrun.compositions(cave_band())
        self.assertEqual(len({frozenset(c.names) for c in comps}), len(comps))
        self.assertLessEqual(len(comps), guildrun.MAX_OPTIONS)

    def test_no_healer_no_group(self):
        crowd = [m for m in cave_band() if m.class_id not in (PRIEST, PALADIN)]
        self.assertEqual(guildrun.compositions(crowd), [])

    def test_the_module_row_names_the_seats(self):
        comp = guildrun.compositions(cave_band())[0]
        command = comp.command("ragefire")
        self.assertTrue(
            command.startswith("finder-run ragefire " + comp.healer.name + " ")
        )
        self.assertEqual(len(command.split()), 6)
        self.assertNotIn(comp.tank.name, command)

    def test_pools_never_share_a_member(self):
        horde = [
            guildrun.member_from_row(dict(row(n + "h", lvl, c), guild_name="Bonkers"))
            for n, lvl, c in (
                ("W", 19, WARRIOR),
                ("P", 18, PRIEST),
                ("R", 18, ROGUE),
                ("M", 17, MAGE),
                ("L", 17, WARLOCK),
            )
        ]
        pools = guildrun.pools(cave_band() + horde, DOORS)
        self.assertEqual({p.guild for p in pools}, {"Cave", "Bonkers"})
        seen = [m.name for p in pools for m in p.members]
        self.assertEqual(len(seen), len(set(seen)))


def ended(keyword, outcome, band="15-19", comp="spec-tank/spec-healer", deaths=0):
    return {
        "keyword": keyword,
        "band": band,
        "composition": comp,
        "state": "ended",
        "outcome": outcome,
        "deaths": deaths,
    }


class TheRecord(unittest.TestCase):
    def test_a_rolling_smoothed_rate_per_door_band_and_shape(self):
        rows = [
            ended("ragefire", "cleared"),
            ended("ragefire", "wiped", deaths=5),
            ended("ragefire", "cleared"),
        ]
        rate = guildrun.rates(rows)[("ragefire", "15-19", "spec-tank/spec-healer")]
        self.assertEqual((rate.runs, rate.cleared, rate.deaths), (3, 2, 5))
        self.assertAlmostEqual(rate.smoothed, 3 / 5.0)
        self.assertIn("2 cleared of 3 runs", rate.words())

    def test_only_the_last_runs_count(self):
        rows = [ended("ragefire", "cleared")] * 3 + [ended("ragefire", "wiped")] * 30
        rate = guildrun.rates(rows, rolling=3)[
            ("ragefire", "15-19", "spec-tank/spec-healer")
        ]
        self.assertEqual((rate.runs, rate.cleared), (3, 3))

    def test_a_run_that_never_went_in_says_nothing_about_the_dungeon(self):
        rows = [
            ended("ragefire", "not entered"),
            ended("ragefire", "refused"),
            ended("ragefire", "lost"),
        ]
        self.assertEqual(guildrun.rates(rows), {})


def plan(table_rows=()):
    pool = guildrun.Pool("Cave", tuple(cave_band()))
    return guildrun.plan_for(pool, DOORS, guildrun.rates(list(table_rows)))


class TheHeuristicIsThePrior(unittest.TestCase):
    def test_with_no_record_the_closest_level_fit(self):
        p = plan()
        keyword, why = guildrun.heuristic_door(p, p.options[0])
        self.assertEqual(keyword, "ragefire")
        self.assertIn("closest level fit", why)

    def test_a_record_with_enough_runs_moves_it(self):
        rows = [ended("ragefire", "wiped")] * 4 + [ended("wailing", "cleared")] * 4
        p = plan(rows)
        keyword, why = guildrun.heuristic_door(p, p.options[0])
        self.assertEqual(keyword, "wailing")
        self.assertIn("best record", why)

    def test_too_few_runs_do_not(self):
        rows = [ended("ragefire", "wiped")] * 4 + [ended("wailing", "cleared")] * 2
        p = plan(rows)
        self.assertEqual(guildrun.heuristic_door(p, p.options[0])[0], "ragefire")


class JevChoosesWithAConfidence(unittest.TestCase):
    def decide(self, fake, key="k"):
        client = jev.Client(key, transport=fake)
        return asyncio.run(guildrun.decide(client, plan(), environ={}))

    def test_both_questions_go_in_one_request_with_the_records(self):
        fake = FakeJev(picks={"dungeon": "wailing", "composition": "b"}, confidence=0.9)
        self.decide(fake)
        self.assertEqual(len(fake.requests), 1)
        questions = fake.requests[0]["questions"]
        self.assertEqual(set(questions), {"composition", "dungeon"})
        self.assertIn(
            "record for this band", questions["dungeon"]["criteria"]["ragefire"]
        )
        self.assertIn("record at band", questions["composition"]["criteria"]["a"])

    def test_a_confident_answer_acts(self):
        fake = FakeJev(picks={"dungeon": "wailing", "composition": "b"}, confidence=0.9)
        decision = self.decide(fake)
        self.assertEqual(decision.dungeon.chosen, "wailing")
        self.assertEqual(decision.dungeon.acted, jev.JEV)
        self.assertEqual(decision.dungeon.confidence, 0.9)
        self.assertEqual(decision.composition.chosen, "b")
        self.assertEqual(decision.chosen, decision.plan.options[1])

    def test_below_the_floor_the_prior_acts_and_jevs_answer_is_kept(self):
        fake = FakeJev(picks={"dungeon": "wailing", "composition": "b"}, confidence=0.3)
        decision = self.decide(fake)
        self.assertEqual(decision.dungeon.chosen, "ragefire")
        self.assertEqual(decision.dungeon.acted, jev.HEURISTIC)
        self.assertEqual(decision.dungeon.jev, "wailing")
        self.assertEqual(decision.dungeon.confidence, 0.3)
        self.assertEqual(decision.composition.chosen, "a")

    def test_no_answer_is_the_prior(self):
        decision = self.decide(FakeJev(), key="")
        self.assertEqual(decision.dungeon.status, jev.NO_KEY)
        self.assertEqual(decision.dungeon.chosen, "ragefire")
        self.assertEqual(decision.dungeon.chosen_by, jev.HEURISTIC)

    def test_each_judgment_is_shaped_for_the_judgment_table(self):
        decision = self.decide(FakeJev(confidence=0.9))
        for judgment in (decision.composition, decision.dungeon):
            self.assertIn(
                judgment.kind, (guildrun.KIND_COMPOSITION, guildrun.KIND_DUNGEON)
            )
            self.assertTrue(judgment.facts)
            self.assertTrue(judgment.probabilities_json())
            self.assertLessEqual(len(judgment.kind), 32)
            self.assertIsNotNone(judgment.agree)


class TheOutcomeIsReadOffTheRow(unittest.TestCase):
    def test_a_cleared_run(self):
        seen = guildrun.outcome_from_row(
            {
                "status": "applied",
                "detail": "cleared",
                "result": '{"phase":"done","outcome":"cleared","why":"the finder says the '
                'dungeon is finished","deaths":2,"seconds_inside":1500,'
                '"bosses_done":4,"bosses_total":4,"loot_items":17,'
                '"loot_notable":[1,2],"ilvl_start":300,"ilvl_end":312,'
                '"members":[{"name":"A","level_start":15,"level_end":16}]}',
            }
        )
        self.assertEqual(seen["state"], guildrun.ENDED)
        self.assertEqual(seen["outcome"], "cleared")
        self.assertEqual(
            (seen["deaths"], seen["bosses_done"], seen["loot_items"]), (2, 4, 17)
        )
        self.assertEqual((seen["ilvl_gained"], seen["levels_gained"]), (12, 1))
        self.assertEqual(seen["loot_notable"], "1,2")

    def test_a_group_inside_is_still_running(self):
        seen = guildrun.outcome_from_row(
            {
                "status": "verifying",
                "result": '{"phase":"inside","deaths":1,"seconds_inside":300}',
            }
        )
        self.assertEqual(seen["state"], guildrun.INSIDE)
        self.assertIsNone(
            guildrun.outcome_from_row(
                {"status": "verifying", "result": '{"phase":"queued"}'}
            )
        )

    def test_a_refusal_and_a_swept_row(self):
        refused = guildrun.outcome_from_row(
            {
                "status": "error",
                "result": '{"phase":"refused","outcome":"refused","why":"x"}',
            }
        )
        self.assertEqual(refused["outcome"], "refused")
        swept = guildrun.outcome_from_row(
            {"status": "error", "detail": "claim expired", "result": None}
        )
        self.assertEqual(swept["outcome"], "lost")


class TheGuildTab(unittest.TestCase):
    def test_the_page_payload_carries_its_own_sentences(self):
        rows = [
            {
                "id": 2,
                "guild": "Cave",
                "band": "10-14",
                "composition": "spec-tank/spec-healer",
                "keyword": "ragefire",
                "members": "Tanky:tank:warrior:16,Healy:healer:priest:15",
                "state": "inside",
                "dungeon_by": "jev",
                "dungeon_jev": "ragefire",
                "dungeon_confidence": 0.81,
                "composition_by": "heuristic",
                "composition_jev": "b",
                "composition_confidence": 0.4,
                "seconds_inside": 600,
            },
            dict(
                ended("ragefire", "cleared"),
                id=1,
                guild="Cave",
                members="",
                dungeon_by="heuristic",
            ),
        ]
        page = guildrun.page(rows)
        self.assertEqual(page["head"], "1 group(s) out, 1 back")
        card = page["active"][0]
        self.assertEqual(card["title"], "Cave - Ragefire Chasm")
        self.assertIn(
            "Jev chose ragefire at 0.81 confidence, and Jev's answer acted",
            card["lines"][0],
        )
        self.assertIn("the prior acted", card["lines"][1])
        self.assertEqual(
            card["members"][0],
            {"name": "Tanky", "seat": "tank", "class": "warrior", "level": 16},
        )
        self.assertEqual(page["recent"][0]["tone"], "good")
        self.assertIn("1 cleared of 1 run", page["records"][0]["line"])


class TheWiring(unittest.TestCase):
    def test_the_loop_runs_on_both_bridges(self):
        self.assertEqual(BRIDGE.count("                self._guild_run_loop,\n"), 2)
        self.assertEqual(
            BRIDGE.count("await asyncio.to_thread(_ensure_guild_run_store)"), 2
        )

    def test_the_row_is_a_guild_row_on_the_tank(self):
        start = BRIDGE[BRIDGE.index("def _start_guild_run") :]
        start = start[: start.index("\ndef ")]
        self.assertIn("VALUES (%s, %s, 'guild', %s)", start)
        self.assertIn("comp.command(door.keyword)", start)
        self.assertIn("item_guid=run_id", start)

    def test_a_member_in_a_run_is_left_alone_by_the_guild_passes(self):
        self.assertEqual(
            BRIDGE.count('busy = set(getattr(self, "_guild_run_names", ())) | '), 4
        )

    def test_nothing_new_is_formed_while_the_switch_is_off(self):
        loop = BRIDGE[BRIDGE.index("async def _guild_run_loop") :]
        loop = loop[: loop.index("async def _guild_run_once")]
        self.assertIn("if guildrun.enabled():", loop)
        self.assertLess(
            loop.index("_follow_guild_runs"), loop.index("if guildrun.enabled():")
        )

    def test_the_site_serves_and_routes_the_tab(self):
        self.assertIn('"/api/guildruns": _guild_runs,', SERVER)
        listed = PAGE[PAGE.index("const HASH_VIEWS = [") :]
        self.assertIn("GUILD_VIEW", listed[: listed.index("];")])
        layout = PAGE[PAGE.index("function tabLayout()") :]
        self.assertIn("GUILD_VIEW", layout[: layout.index("],")])
        show = PAGE[PAGE.index("function showView") :]
        branch = show[show.index("  if (isGuild) {") :]
        self.assertIn("pollGuild();", branch[: branch.index("  }")])
        self.assertIn('fetch(u("/api/guildruns")', PAGE)


if __name__ == "__main__":
    unittest.main()
