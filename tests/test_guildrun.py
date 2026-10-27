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
import dataclasses
import datetime
from dataclasses import replace
import pathlib
import unittest
from unittest import mock

import guildrun
import jev
import preraid
from test_jev_items import FakeJev

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")

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
        # Holy Shock (20473) spent: a paladin that heals. #575 seats only a
        # member whose spent talents play the seat.
        member("Pally", 19, PALADIN, talent_spells="20473"),
        member("Stabby", 19, ROGUE),
        member("Zappy", 18, MAGE),
        member("Locky", 17, WARLOCK),
    ]


DOORS = guildrun.doors({389: 8, 36: 10, 43: 10, 33: 14})


class OnlyDamageDealersFillDamageSeats(unittest.TestCase):
    """A bot plays its spent tree whatever seat it is given, so a Protection
    warrior or a Holy priest in a damage seat is a second tank or a second
    healer (runs 247, 256 and 265 took Protection warriors as damage)."""

    def test_a_tank_or_healer_tree_does_not_deal_damage(self):
        self.assertFalse(
            member("Tanky", 20, WARRIOR, talent_spells=PROTECTION_TALENT).deals_damage()
        )
        self.assertFalse(
            member("Healy", 20, PRIEST, talent_spells=HOLY_TALENT).deals_damage()
        )

    def test_a_member_with_no_talents_or_a_damage_tree_does(self):
        self.assertTrue(member("Stabby", 19, ROGUE).deals_damage())
        self.assertTrue(
            member("Furio", 19, WARRIOR, talent_spells="61216").deals_damage()
        )

    def test_a_window_short_of_damage_dealers_seats_no_group(self):
        window = [
            member("Tanky", 20, WARRIOR, talent_spells=PROTECTION_TALENT),
            member("Shieldy", 20, WARRIOR, talent_spells=PROTECTION_TALENT),
            member("Healy", 20, PRIEST, talent_spells=HOLY_TALENT),
            member("Zappy", 19, MAGE),
            member("Locky", 19, WARLOCK),
        ]
        window = [
            replace(m, worn_slots=6, has_weapon=True, has_shield=True) for m in window
        ]
        self.assertEqual(guildrun.compositions(window), [])

    def test_the_damage_seats_go_to_the_damage_dealers(self):
        window = [
            member("Tanky", 20, WARRIOR, talent_spells=PROTECTION_TALENT),
            member("Shieldy", 20, WARRIOR, talent_spells=PROTECTION_TALENT),
            member("Healy", 20, PRIEST, talent_spells=HOLY_TALENT),
            member("Zappy", 19, MAGE),
            member("Locky", 19, WARLOCK),
            member("Stabby", 19, ROGUE),
        ]
        window = [
            replace(m, worn_slots=6, has_weapon=True, has_shield=True) for m in window
        ]
        for comp in guildrun.compositions(window):
            self.assertTrue(all(m.deals_damage() for m in comp.dps), comp.names)


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
        self.assertEqual(
            guildrun.limits({"GUILD_RUNS_EVERY_SECONDS": "-5"}).form_every_seconds, 0
        )

    def test_no_practical_limit_when_the_operator_lifts_it(self):
        # 2026-10-05: "let all groups run stuff at the same time, no limits".
        lifted = guildrun.limits(
            {"GUILD_RUNS_MAX": "30", "GUILD_RUNS_EVERY_SECONDS": "0"}
        )
        self.assertEqual(lifted.max_groups, 30)
        self.assertEqual(lifted.form_every_seconds, 0)


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
            "inside The Deadmines",
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

    def test_queue_refusal_has_longer_bench_but_combat_still_expires(self):
        queue_why = "'Auren' is waiting in a battleground queue"
        combat_why = "'Auren' is in combat"
        self.assertEqual(
            {"Auren"},
            guildrun.benched(
                [
                    {"outcome": "refused", "why": queue_why, "age_minutes": 16},
                    {"outcome": "refused", "why": combat_why, "age_minutes": 1},
                ]
            ),
        )
        self.assertEqual(
            set(),
            guildrun.benched(
                [
                    {"outcome": "refused", "why": queue_why, "age_minutes": 60},
                ]
            ),
        )

    def test_a_refusal_with_no_age_reads_as_fresh(self):
        why = "'Auren' is waiting in a battleground queue"
        self.assertEqual(
            {"Auren"},
            guildrun.benched([{"outcome": "refused", "why": why, "age_minutes": None}]),
        )

    def test_the_bridge_reads_each_refusals_age_over_the_queue_window(self):
        from test_guildsocial_bridge import bridge

        ran = []
        refusals = [
            {
                "outcome": "refused",
                "why": "'Auren' is waiting in a battleground queue",
                "age": 30,
            },
            {"outcome": "refused", "why": "'Bo' is in combat", "age": 30},
        ]

        class Cursor:
            rows = []

            def execute(self, sql, args=()):
                ran.append((sql, tuple(args)))
                self.rows = []
                if sql.startswith("SELECT outcome, why"):
                    # Only a column the SELECT names comes back on the row.
                    self.rows = [
                        {
                            "outcome": r["outcome"],
                            "why": r["why"],
                            **(
                                {"age_minutes": r["age"]}
                                if "AS age_minutes" in sql
                                else {}
                            ),
                        }
                        for r in refusals
                    ]

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return {}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Conn:
            def cursor(self):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with mock.patch.object(bridge, "_connect", Conn):
            facts = bridge._fetch_guild_run_facts(guildrun.limits({}))
        self.assertEqual({"Auren"}, facts["benched"])
        bench_args = [args for sql, args in ran if "AS age_minutes" in sql]
        self.assertEqual([(guildrun.QUEUE_BENCH_MINUTES,)], bench_args)

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

    def test_short_zero_boss_abandon_does_not_rest_but_timeout_does(self):
        short_abandon = {
            "outcome": "abandoned",
            "seconds_inside": 299,
            "bosses_done": 0,
        }
        timeout = {
            "outcome": "timed out",
            "seconds_inside": 299,
            "bosses_done": 0,
        }
        self.assertFalse(guildrun.rests_members(short_abandon))
        self.assertTrue(guildrun.rests_members(timeout))

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

    def test_no_item_level_gate_below_sixty(self):
        """#532: the item-level gate held 117 of 132 members out of the
        dungeons that gear them. Low item level alone never holds a member."""
        weak = member("Bramitho", 14, PRIEST, gear_ilvl=4.0)
        self.assertEqual(guildrun.why_not(weak, set(), set(), set()), "")
        rows = [row("Member%d" % i, 17, WARRIOR, gear_ilvl=3.0) for i in range(5)]
        free, skipped = guildrun.free_members(rows, set(), set(), set(), set())
        self.assertEqual(len(free), 5)
        self.assertEqual(skipped, {})

    def test_a_tank_or_healer_needs_a_weapon_and_four_body_armor_slots(self):
        # Live 2026-10-04: tank- and healer-fit members wore 4 to 7 slots.
        dressed = member("T", 18, WARRIOR, worn_slots=4, has_weapon=1)
        self.assertTrue(guildrun.covered(dressed))
        self.assertFalse(
            guildrun.covered(member("T", 18, WARRIOR, worn_slots=3, has_weapon=1))
        )
        self.assertFalse(
            guildrun.covered(member("T", 18, WARRIOR, worn_slots=8, has_weapon=0))
        )
        # Unread gear is never a reason to hold a member.
        self.assertTrue(guildrun.covered(member("U", 18, WARRIOR)))

    def test_a_warrior_or_paladin_tank_needs_a_shield(self):
        dressed = dict(worn_slots=6, has_weapon=1)
        self.assertFalse(
            guildrun.tank_ready(member("W", 18, WARRIOR, has_shield=0, **dressed))
        )
        self.assertTrue(
            guildrun.tank_ready(member("W", 18, WARRIOR, has_shield=1, **dressed))
        )
        self.assertFalse(
            guildrun.tank_ready(member("P", 18, PALADIN, has_shield=0, **dressed))
        )
        # A druid tanks in bear form; unread gear never holds a member.
        self.assertTrue(
            guildrun.tank_ready(member("D", 18, DRUID, has_shield=0, **dressed))
        )
        self.assertTrue(guildrun.tank_ready(member("U", 18, WARRIOR)))

    def test_a_shieldless_warrior_is_not_seated_as_tank(self):
        band = [
            dataclasses.replace(m, worn_slots=6, has_weapon=True, has_shield=False)
            for m in cave_band()
        ]
        for comp in guildrun.compositions(band):
            self.assertNotIn(comp.tank.class_id, guildrun.SHIELD_TANK_CLASSES)

    def test_a_bare_tank_is_not_seated_but_a_bare_damage_dealer_is(self):
        band = cave_band()
        bare = [dataclasses.replace(m, worn_slots=2, has_weapon=True) for m in band]
        self.assertEqual(guildrun.compositions(bare), [])
        dressed_tanks = [
            dataclasses.replace(m, worn_slots=6, has_weapon=True)
            if m.fit(guildrun.TANK) or m.fit(guildrun.HEALER)
            else m
            for m in bare
        ]
        self.assertTrue(guildrun.compositions(dressed_tanks))

    def test_the_bridge_does_not_retry_without_the_gear_gate(self):
        start = BRIDGE.index("    async def _guild_run_once(self)")
        end = BRIDGE.index("\n    async def ", start + 1)
        coordinator = BRIDGE[start:end]

        self.assertIn("guildrun.free_members(", coordinator)
        self.assertNotIn("_free_members(False)", coordinator)
        self.assertNotIn("forming without it", coordinator)

    def test_the_bridge_reads_worn_item_level(self):
        sql = BRIDGE[BRIDGE.index("_GUILD_RUN_MEMBERS_SQL = (") :]
        sql = sql[: sql.index("\n)\n")]
        self.assertIn("AVG(it.ItemLevel)", sql)
        self.assertIn("AS gear_ilvl", sql)
        self.assertIn("AS worn_slots", sql)
        self.assertIn("ci.slot IN (0, 2, 4, 5, 6, 7, 8, 9)) AS worn_slots", sql)
        self.assertIn("AS has_weapon", sql)
        self.assertIn("AS has_shield", sql)

    def test_the_gate_skips_the_shirt_and_tabard(self):
        """wow-dev 2026-10-04: an item level 1 shirt pulled members under the
        gate; the gear step's own stale test already leaves both slots out."""
        sql = BRIDGE[BRIDGE.index("_GUILD_RUN_MEMBERS_SQL = (") :]
        sql = sql[: sql.index("\n)\n")]
        self.assertIn("ci.slot NOT IN (3, 18)", sql)


class TheHostileCapitalDoorIsNeverOffered(unittest.TestCase):
    """Cave (Alliance) never runs Ragefire Chasm (map 389) and Bonkers (Horde)
    never runs The Stockade (map 34), at any level, and a side whose faction
    cannot be read is held to the doors both sides may use."""

    ALLIANCE_MAP, HORDE_MAP = 34, 389

    def offered(self, level, faction):
        """The doors offered to five members at `level` who carry no door key:
        a keyed wing comes in only with its key (guildrun.opens_for)."""
        five = [
            guildrun.Member(name="M%d" % i, guild="Cave", level=level, class_id=1)
            for i in range(5)
        ]
        return [
            d.keyword
            for d in guildrun.fitting_doors(
                [level] * 5, guildrun.doors(), faction, five
            )
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
        self.assertEqual(guildrun.stranded_names([own], {"O"}), [])


class MembersLeftInsideADungeonHearthOut(unittest.TestCase):
    """50 guild members stood alone in Ragefire Chasm and Wailing Caverns on
    wow-dev (2026-10-04), ungrouped, days after their runs ended."""

    def test_a_member_alone_in_its_own_sides_dungeon_hearths_out(self):
        bonkers = member("R", 15, MAGE, race=2, map_id=389, guild_name="Bonkers")
        cave = member("W", 18, MAGE, race=1, map_id=43)
        self.assertEqual(guildrun.stranded_names([bonkers, cave], set()), ["R", "W"])

    def test_runs_groups_the_dead_and_the_fighting_stay(self):
        self.assertEqual(
            guildrun.stranded_names([member("Q", 15, MAGE, map_id=43)], {"Q"}), []
        )
        for kw in (
            {"group_leader": 7},
            {"in_combat": 1},
            {"health": 1, "has_corpse": 1},
        ):
            self.assertFalse(
                guildrun.stranded(member("Q", 15, MAGE, map_id=43, **kw), "Alliance"),
                kw,
            )

    def test_the_continents_and_acherus_are_home(self):
        for map_id in (0, 1, 530, 609):
            self.assertFalse(
                guildrun.stranded(member("Q", 15, MAGE, map_id=map_id), "Alliance"),
                map_id,
            )

    def test_why_not_names_the_instance_before_the_gear(self):
        weak_inside = member("Q", 15, MAGE, map_id=43, gear_ilvl=2.0)
        self.assertEqual(
            guildrun.why_not(weak_inside, set(), set(), set()),
            "inside Wailing Caverns",
        )

    def test_the_bridge_never_hearths_a_family_member(self):
        rescue = BRIDGE[BRIDGE.index("def _hearth_stranded_guild_members") :]
        rescue = rescue[: rescue.index("\ndef ")]
        self.assertIn("FROM overseer_roster", rescue)
        self.assertLess(
            rescue.index("FROM overseer_roster"), rescue.index("stranded_names(")
        )


class EachSideHasADoorAtEveryLevelItCanPlay(unittest.TestCase):
    """wow-overseer#414: the per-side door lists stopped short, so the Horde
    was offered no door from level 25 up and the Alliance none from level 33
    up. Every dungeon mod-overseer's finder can queue is on each side's ladder,
    the hostile capital's own dungeon excepted."""

    # Doors the module can queue through the dungeon finder: one normal finder
    # row on the map (the Lower Spire), or a wing the door's own landing picks
    # out (Maraudon, the Scarlet Library).
    QUEUEABLE = {
        "wailing", "deadmines", "shadowfang", "blackfathom", "scarlet",
        "gnomeregan", "razorfen-kraul", "razorfen-downs", "uldaman",
        "zulfarrak", "ragefire", "stockades", "maraudon-orange", "maraudon-purple", "sunken-temple",
        "blackrock-depths", "scholomance", "scarlet-library", "lower-blackrock-spire",
        "scarlet-armory", "scarlet-cathedral", "dire-maul-east-east",
        "dire-maul-west-north", "dire-maul-north",
    }  # fmt: skip
    # Keyed wings (campaignplan.DOOR_KEYS): offered to a group that carries the
    # key, never to one that does not (guildrun.opens_for, #785).
    KEYED = {
        "scarlet-armory", "scarlet-cathedral", "dire-maul-west-north",
        "dire-maul-north", "blackrock-depths",
    }  # fmt: skip
    FIRST_LEVEL = {"Alliance": 17, "Horde": 15}

    def offered(self, level, faction, keys=frozenset()):
        """The doors offered to five members at `level` who carry `keys`."""
        five = [
            guildrun.Member(
                name="M%d" % i, guild="Cave", level=level, class_id=1, keys=keys
            )
            for i in range(5)
        ]
        return [
            d.keyword
            for d in guildrun.fitting_doors(
                [level] * 5, guildrun.doors(), faction, five
            )
        ]

    def test_each_side_uses_every_queueable_door_but_the_hostile_capital(self):
        self.assertEqual(
            guildrun.GUILD_DOORS["Alliance"], self.QUEUEABLE - {"ragefire"}
        )
        self.assertEqual(guildrun.GUILD_DOORS["Horde"], self.QUEUEABLE - {"stockades"})

    def test_no_door_is_held_back(self):
        """Dire Maul's East and West doors find their wings' finder rows
        (mod-overseer's FinderWingDoorFor), and a keyed wing is held to its
        key by the seat, not by a list (#783, #785)."""
        self.assertEqual(guildrun.BLOCKED_DOORS, {})

    def test_every_level_from_the_first_door_to_sixty_has_a_door(self):
        for faction, first in self.FIRST_LEVEL.items():
            for level in range(first, 61):
                self.assertTrue(self.offered(level, faction), (faction, level))

    def test_the_library_and_the_lower_spire_are_on_both_ladders(self):
        """The finder resolves both doors on the realm's own data (wow-dev,
        2026-10-10): the Library's landing is lfg_dungeon_template row 165's
        start, and the Spire has one normal finder row, 32. Held out, a side's
        level-35 groups had no Library and its level-58 groups no Spire."""
        for faction in ("Alliance", "Horde"):
            self.assertIn("scarlet-library", self.offered(35, faction), faction)
            self.assertIn("lower-blackrock-spire", self.offered(58, faction), faction)

    def test_a_keyed_wing_is_offered_only_to_a_group_with_its_key(self):
        """The Armory (Herod's Door), the Cathedral (the Chapel Door), Dire
        Maul West and North (the Crescent doors) and Blackrock Depths (the
        Shadowforge gates) need their key: a group that carries none is never
        offered them, and one that carries it is."""
        for faction in ("Alliance", "Horde"):
            for level in range(36, 61):
                offered = set(self.offered(level, faction))
                self.assertFalse(offered & self.KEYED, (faction, level))
            self.assertIn(
                "scarlet-armory", self.offered(38, faction, frozenset({7146}))
            )
            self.assertIn(
                "blackrock-depths", self.offered(56, faction, frozenset({11000}))
            )
            self.assertIn(
                "dire-maul-west-north", self.offered(58, faction, frozenset({18249}))
            )
            self.assertIn("dire-maul-east-east", self.offered(58, faction))

    def test_the_ladder_climbs_through_the_high_dungeons(self):
        self.assertIn("razorfen-kraul", self.offered(32, "Horde"))
        self.assertIn("zulfarrak", self.offered(40, "Alliance"))
        self.assertIn("sunken-temple", self.offered(52, "Horde"))
        self.assertIn(
            "blackrock-depths", self.offered(56, "Alliance", frozenset({11000}))
        )
        self.assertIn("scholomance", self.offered(60, "Horde"))


class NoRunFormsForADoorTheClearCannotFinish(unittest.TestCase):
    """wow-overseer#782: Blackfathom Deeps took 9 guild runs and cleared none.
    Five sat out the two-hour ceiling at 1 to 4 of 7 bosses, about 10
    member-hours each, because mod-dungeon-clear had no data for it: nothing
    lit the Fires of Aku'mai that open the door to its last bosses. The hold
    on Blackfathom lifted once mod-dungeon-clear 19 and 21 rolled onto the
    worldserver (roll 48, 2026-10-10). Gnomeregan was held too, until #807
    found its route needs no new data. A run that cannot finish does not
    form."""

    HELD: set = set()

    def offered(self, levels, faction):
        return {
            d.keyword for d in guildrun.fitting_doors(levels, guildrun.doors(), faction)
        }

    def test_the_held_doors_say_why(self):
        self.assertEqual(set(guildrun.NO_CLEAR_DATA), self.HELD)
        # Each held keyword is a real door, so a typo cannot hold nothing.
        keywords = {d.keyword for d in guildrun.doors()}
        self.assertLessEqual(self.HELD, keywords)
        for keyword, why in guildrun.NO_CLEAR_DATA.items():
            self.assertTrue(why.strip(), keyword)

    def test_a_held_door_is_offered_to_no_band_on_either_side(self):
        for faction in ("Alliance", "Horde"):
            for level in range(15, 61):
                offered = self.offered([level] * 5, faction)
                self.assertFalse(offered & self.HELD, (faction, level))

    def test_blackfathom_is_offered_again_to_the_band_that_fits_it(self):
        """The hold lifted with mod-dungeon-clear 19 and 21: Bonkers' 24 to 26
        band is offered Blackfathom Deeps and still has Shadowfang Keep."""
        offered = self.offered([24, 25, 25, 25, 26], "Horde")
        self.assertIn("blackfathom", offered)
        self.assertIn("shadowfang", offered)

    def test_razorfen_kraul_stays_on_the_ladder(self):
        """Its derived boss order ends at Charlga Razorflank, the finder's
        finish, with no scripted door on the way, so it is not held."""
        self.assertIn("razorfen-kraul", self.offered([32] * 5, "Horde"))
        self.assertIn("razorfen-kraul", self.offered([32] * 5, "Alliance"))

    def test_gnomeregan_is_offered_to_the_band_that_fits_it(self):
        """#807: the route from the front entrance to Thermaplugg never meets
        the Workshop Door, and The Final Chamber opens to a click, so a band
        of 31 to 33 is offered Gnomeregan on both sides."""
        door = next(d for d in guildrun.doors() if d.keyword == "gnomeregan")
        for faction in ("Alliance", "Horde"):
            self.assertIn("gnomeregan", self.offered([31, 32, 32, 32, 33], faction))
            fits = guildrun.fitting_doors([32] * 5, [door], faction)
            self.assertEqual(fits, [door], faction)

    def test_a_single_held_door_does_not_fit_a_member(self):
        """The pug and social paths ask fitting_doors about one door."""
        door = next(d for d in guildrun.doors() if d.keyword == "gnomeregan")
        with mock.patch.dict(guildrun.NO_CLEAR_DATA, {"gnomeregan": "a test hold"}):
            self.assertEqual(guildrun.fitting_doors([32] * 5, [door], "Alliance"), [])
            self.assertEqual(guildrun.fitting_doors([32] * 5, [door], "Horde"), [])


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


SPIRE_RECIPE = "Recipe: Greater Fire Protection Potion"
FLASK_RECIPE = "Recipe: Flask of Supreme Power"
# Blackrock Spire's map and Scholomance's (#893).
SPIRE_MAP, SCHOLOMANCE_MAP = 229, 289


class AGuildGoesForARaidRecipeNobodyKnows(unittest.TestCase):
    """#893: nobody in either guild holds Recipe 13494 (Blackrock Spire) or a
    flask recipe, and the level fit alone never sent a group for one."""

    def first(self, levels, recipes=None):
        doors = guildrun.fitting_doors(levels, DOORS, "Alliance", recipes=recipes)
        return doors[0].keyword

    def test_fitting_doors_prefers_a_door_dropping_a_raid_recipe_nobody_knows(self):
        # A group averaging 56 sits on Blackrock Depths' middle and 1.5 levels
        # from the Spire's.
        self.assertEqual(self.first([56] * 5), "blackrock-depths")
        recipes = {SPIRE_MAP: (SPIRE_RECIPE,)}
        self.assertEqual(self.first([56] * 5, recipes), "lower-blackrock-spire")

    def test_below_fifty_two_the_level_fit_stands(self):
        # Sunken Temple (50 to 60) fits a group of 51; a recipe behind it
        # does not move a group under RAID_RECIPE_LEVEL.
        recipes = {109: (SPIRE_RECIPE,)}
        self.assertEqual(self.first([51] * 5), self.first([51] * 5, recipes))

    def test_a_door_past_the_slack_does_not_win(self):
        # At 53 the Sunken Temple is 2 levels from its middle, Blackrock
        # Depths 3 and Zul'Farrak 8: the Depths is within RECIPE_FIT_SLACK of
        # the best fit and goes first for a recipe, Zul'Farrak is not.
        self.assertEqual(self.first([53] * 5), "sunken-temple")
        self.assertEqual(
            self.first([53] * 5, {230: (SPIRE_RECIPE,)}), "blackrock-depths"
        )
        self.assertEqual(self.first([53] * 5, {209: (SPIRE_RECIPE,)}), "sunken-temple")

    def test_the_recipes_nobody_knows_are_read_off_the_drops(self):
        rows = [
            {"item": 13494, "item_name": SPIRE_RECIPE, "map_id": SPIRE_MAP},
            {"item": 13519, "item_name": "Recipe: Flask of the Titans", "map_id": 229},
            {"item": 13521, "item_name": FLASK_RECIPE, "map_id": SCHOLOMANCE_MAP},
            # A world drop, and a vendor recipe: neither is a door's.
            {"item": 13491, "item_name": "Recipe: Elixir", "map_id": 1},
            {"item": 13501, "item_name": "Recipe: Major Mana", "map_id": 289},
        ]
        found = guildrun.unknown_recipes(rows)
        self.assertEqual(
            found,
            {
                SPIRE_MAP: (SPIRE_RECIPE, "Recipe: Flask of the Titans"),
                SCHOLOMANCE_MAP: (FLASK_RECIPE,),
            },
        )
        # A guild with an alchemist who knows the fire potion is sent for the
        # flask that drops on the same map instead.
        known = guildrun.known_by_guild([{"guild": "Cave", "spell": 17574}])
        self.assertEqual(known, {"Cave": {17574}})
        found = guildrun.unknown_recipes(rows, known["Cave"])
        self.assertEqual(found[SPIRE_MAP], ("Recipe: Flask of the Titans",))

    def test_the_pick_names_the_recipe(self):
        def high(name, class_id, **kw):
            return member(name, 56, class_id, race=1, **kw)

        band = [
            high("Tanky", WARRIOR, talent_spells=PROTECTION_TALENT),
            high("Healy", PRIEST, talent_spells=HOLY_TALENT),
            high("Rogue", ROGUE),
            high("Mage", MAGE),
            high("Lock", WARLOCK),
        ]
        pool = guildrun.Pool("Cave", tuple(band))
        p = guildrun.plan_for(pool, DOORS, {}, {SPIRE_MAP: (SPIRE_RECIPE,)})
        keyword, why = guildrun.heuristic_door(p, p.options[0])
        self.assertEqual(keyword, "lower-blackrock-spire")
        self.assertEqual(why, "for %s (nobody knows it)" % SPIRE_RECIPE)
        criteria = guildrun.questions(p)["dungeon"]
        self.assertIn(SPIRE_RECIPE, str(criteria))

    # The bridge's read of these recipes and its hand-off to the social pass
    # are driven for real in test_guildsocial_bridge.TheRaidRecipes.


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
        talents = {"W": PROTECTION_TALENT, "P": HOLY_TALENT}
        horde = [
            guildrun.member_from_row(
                dict(
                    row(n + "h", lvl, c, talent_spells=talents.get(n)),
                    guild_name="Bonkers",
                )
            )
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

    def test_three_boss_timeout_counts_as_progress_and_boss_time(self):
        rows = [
            dict(ended("ragefire", "timed out"), bosses_done=3, seconds_inside=1800),
            dict(ended("ragefire", "timed out"), bosses_done=2, seconds_inside=900),
            dict(ended("ragefire", "abandoned"), bosses_done=5, seconds_inside=2000),
            dict(ended("ragefire", "timed out"), seconds_inside=500),
        ]
        rate = guildrun.rates(rows)[("ragefire", "15-19", "spec-tank/spec-healer")]
        pooled = guildrun.door_rate(guildrun.rates(rows), "ragefire", "15-19")
        self.assertEqual((rate.runs, rate.progress), (4, 1))
        self.assertEqual(pooled.progress, 1)
        self.assertIn("about 8 minutes a boss", rate.words())
        no_bosses = guildrun.rates([dict(ended("ragefire", "wiped"))])[
            ("ragefire", "15-19", "spec-tank/spec-healer")
        ]
        self.assertNotIn("a boss", no_bosses.words())


class TheRecordByShape(unittest.TestCase):
    """#584: the social layer's record, keyed by (door, band, shape) with the
    runs the finder turned away counted."""

    def test_turned_away_runs_count_and_a_lost_one_does_not(self):
        rows = [
            ended("ragefire", "not entered", band="10-14"),
            ended("ragefire", "refused", band="10-14"),
            ended("ragefire", "lost", band="10-14"),
            ended("ragefire", "wiped", band="10-14", deaths=3),
        ]
        rec = guildrun.shape_records(rows)[
            ("ragefire", "10-14", "spec-tank/spec-healer")
        ]
        self.assertEqual((rec.went_in, rec.turned_away, rec.streak), (1, 2, 2))
        self.assertIn("turned 2 groups away", rec.words())

    def test_a_helper_does_not_change_the_shape(self):
        rows = [ended("ragefire", "cleared", comp="spec-tank/class-healer+1help")]
        self.assertIn(
            ("ragefire", "15-19", "spec-tank/class-healer"),
            guildrun.shape_records(rows),
        )

    def test_failing_by_wipes_or_by_a_turned_away_streak(self):
        wipes = [ended("ragefire", "wiped")] * guildrun.FAILING_RUNS
        away = [ended("ragefire", "not entered")] * guildrun.TURNED_AWAY_RUNS
        broken = [ended("ragefire", "not entered")] * 4 + [ended("ragefire", "wiped")]
        key = ("ragefire", "15-19", "spec-tank/spec-healer")
        self.assertTrue(guildrun.shape_records(wipes)[key].failing)
        self.assertTrue(guildrun.shape_records(away)[key].failing)
        self.assertFalse(guildrun.shape_records(broken)[key].failing)

    def test_progress_timeout_keeps_shape_open(self):
        key = ("ragefire", "15-19", "spec-tank/spec-healer")
        wipes = [ended("ragefire", "wiped")] * guildrun.FAILING_RUNS
        progress = dict(ended("ragefire", "timed out"), bosses_done=3)
        self.assertTrue(guildrun.shape_records(wipes)[key].failing)
        record = guildrun.shape_records([progress] + wipes[:-1])[key]
        self.assertEqual(record.progress, 1)
        self.assertFalse(record.failing)

    def test_an_old_run_ages_out(self):
        now = datetime.datetime(2026, 10, 4, 20, 0, 0)
        old = dict(
            ended("ragefire", "wiped"),
            ended_at=now - datetime.timedelta(days=guildrun.RECORD_DAYS + 1),
        )
        self.assertEqual(guildrun.shape_records([old] * 6, now), {})
        self.assertEqual(guildrun.shape_key(True, False), "spec-tank/class-healer")


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
        # Under MIN_SAMPLES runs a door scores the untried prior, as the level
        # fit does with none: a tie, and the level fit keeps it.
        rows = [ended("wailing", "cleared")] * 2
        p = plan(rows)
        self.assertEqual(guildrun.heuristic_door(p, p.options[0])[0], "ragefire")

    def test_an_untried_door_beats_a_long_losing_record(self):
        # #583: Wailing Caverns went 0 of 48 and still beat the door nobody
        # had tried, because a door under MIN_SAMPLES runs was left out.
        rows = [ended("ragefire", "wiped")] * 4
        p = plan(rows)
        keyword, why = guildrun.heuristic_door(p, p.options[0])
        self.assertNotEqual(keyword, "ragefire")
        self.assertIn("untried", why)

    def test_a_winning_record_still_beats_an_untried_door(self):
        rows = [ended("ragefire", "cleared")] * 3
        p = plan(rows)
        self.assertEqual(guildrun.heuristic_door(p, p.options[0])[0], "ragefire")


class OnlyRealTanksAndHealersAreSeated(unittest.TestCase):
    """#575: Cave seated damage-specced shamans, paladins and druids in the
    tank and healer seats; dungeon clear logged no tank in 7 of 9 runs."""

    def test_a_class_that_could_heal_but_does_not_is_not_a_healer(self):
        ret = member("Ret", 19, PALADIN, talent_spells="20375")
        planned = member("Plan", 19, PALADIN, target_tree="Holy")
        holy = member("Holy", 19, PALADIN, talent_spells="20473")
        self.assertFalse(ret.plays(guildrun.HEALER))
        self.assertFalse(planned.plays(guildrun.HEALER))
        self.assertTrue(holy.plays(guildrun.HEALER))

    def test_no_real_healer_no_group(self):
        crowd = [
            member("Tanky", 20, WARRIOR, talent_spells=PROTECTION_TALENT),
            member("Ret", 19, PALADIN, talent_spells="20375"),
            member("Plan", 19, PALADIN, target_tree="Holy"),
            member("Stabby", 19, ROGUE),
            member("Zappy", 18, MAGE),
        ]
        self.assertEqual(guildrun.compositions(crowd), [])


class AFailingDoorIsRetired(unittest.TestCase):
    def test_six_wipes_and_no_clear_retire_a_door_at_the_band(self):
        rows = [ended("ragefire", "wiped")] * 6
        p = plan(rows)
        self.assertEqual(guildrun.failing_doors(p), {"ragefire"})
        keyword, _why = guildrun.heuristic_door(p, p.options[0])
        self.assertNotEqual(keyword, "ragefire")

    def test_the_only_fitting_door_is_still_chosen(self):
        # A preference, not a ban: the record only moves when the door is run.
        rows = [ended("ragefire", "wiped")] * 6
        p = plan(rows)
        only = replace(p, doors=tuple(d for d in p.doors if d.keyword == "ragefire"))
        self.assertEqual(guildrun.heuristic_door(only, only.options[0])[0], "ragefire")

    def test_one_clear_keeps_it(self):
        rows = [ended("ragefire", "wiped")] * 6 + [ended("ragefire", "cleared")]
        self.assertEqual(guildrun.failing_doors(plan(rows)), set())

    def test_progress_timeout_keeps_door_open(self):
        wipes = [ended("ragefire", "wiped")] * guildrun.FAILING_RUNS
        self.assertEqual(guildrun.failing_doors(plan(wipes)), {"ragefire"})
        progress = dict(ended("ragefire", "timed out"), bosses_done=3)
        self.assertEqual(guildrun.failing_doors(plan([progress] + wipes[:-1])), set())

    def test_door_option_shows_time_per_boss_only_when_bosses_are_down(self):
        p = plan(
            [dict(ended("ragefire", "timed out"), bosses_done=3, seconds_inside=1800)]
        )
        text = guildrun.questions(p)["dungeon"]["criteria"]["ragefire"]
        self.assertIn("about 10 minutes a boss", text)
        empty = guildrun.questions(plan([ended("ragefire", "wiped")]))["dungeon"][
            "criteria"
        ]["ragefire"]
        self.assertNotIn("a boss", empty)


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

    def test_an_agreement_below_the_floor_is_the_heuristics(self):
        # #584: 30 Wailing Caverns runs at 0.02 to 0.64 were credited to Jev.
        fake = FakeJev(
            picks={"dungeon": "ragefire", "composition": "a"}, confidence=0.3
        )
        decision = self.decide(fake)
        self.assertEqual(decision.dungeon.chosen, "ragefire")
        self.assertEqual(decision.dungeon.acted, jev.HEURISTIC)
        self.assertEqual(decision.dungeon.chosen_by, jev.HEURISTIC)
        self.assertTrue(decision.dungeon.agree)
        self.assertEqual(decision.composition.acted, jev.HEURISTIC)

    def test_an_agreement_at_the_floor_is_both(self):
        fake = FakeJev(
            picks={"dungeon": "ragefire", "composition": "a"}, confidence=0.6
        )
        self.assertEqual(self.decide(fake).dungeon.acted, jev.BOTH)

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
    def test_blackfathom_room_uses_the_nearest_encounter_spawn(self):
        position = {"pos_x": 12, "pos_y": 34, "pos_z": -40}
        bosses = [
            {"name": "Gelihast", "x": 500, "y": 500, "z": -40},
            {"name": "Twilight Lord Kelris", "x": 13, "y": 35, "z": -40},
        ]
        self.assertEqual(
            guildrun.blackfathom_room(position, bosses),
            "near Twilight Lord Kelris (x 12, y 34, z -40)",
        )

    def test_blackfathom_timeout_keeps_the_last_room_and_reason(self):
        seen = guildrun.outcome_from_row(
            {
                "status": "applied",
                "keyword": "blackfathom",
                "last_room": "near Twilight Lord Kelris (x 12, y 34, z -40)",
                "detail": "the run ran out of time",
                "result": '{"outcome":"timed out","why":"the run ran out of time",'
                '"bosses_done":4,"bosses_total":7}',
            }
        )
        self.assertEqual(
            seen["why"],
            "Last room: near Twilight Lord Kelris (x 12, y 34, z -40); "
            "the run ran out of time",
        )

    def test_blackfathom_timeout_says_when_the_last_boss_fell(self):
        seen = guildrun.outcome_from_row(
            {
                "status": "applied",
                "keyword": "blackfathom",
                "last_room": "near Twilight Lord Kelris (x 12, y 34, z -40)",
                "seconds_since_boss": 4 * 60,
                "result": '{"outcome":"timed out","why":"inside for 7200s",'
                '"bosses_done":4,"bosses_total":7}',
            }
        )
        self.assertEqual(
            seen["why"],
            "Last room: near Twilight Lord Kelris (x 12, y 34, z -40); "
            "still progressing: the 2-hour limit ended the run at 4 of 7 bosses, "
            "4 minutes after the last boss",
        )

    def test_blackfathom_timeout_names_a_stall(self):
        seen = guildrun.outcome_from_row(
            {
                "status": "applied",
                "keyword": "blackfathom",
                "last_room": "near Ghamoo-ra (x -394, y 296, z -70)",
                "seconds_since_boss": 83 * 60,
                "result": '{"outcome":"timed out","why":"inside for 7200s",'
                '"bosses_done":1,"bosses_total":7}',
            }
        )
        self.assertEqual(
            seen["why"],
            "Last room: near Ghamoo-ra (x -394, y 296, z -70); "
            "stalled: the 2-hour limit ended the run at 1 of 7 bosses, "
            "83 minutes after the last boss",
        )

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
        self.assertEqual(page["head"], "1 group out, 1 back")
        card = page["active"][0]
        self.assertEqual(card["title"], "Cave - Ragefire Chasm")
        self.assertIn(
            "Jev chose Ragefire Chasm, 81% sure",
            card["lines"][0],
        )
        self.assertIn("the usual rule chose", card["lines"][1])
        self.assertIn("lineup ", card["lines"][1])
        self.assertEqual(
            card["members"][0],
            {"name": "Tanky", "seat": "tank", "class": "warrior", "level": 16},
        )
        self.assertEqual(page["recent"][0]["tone"], "good")
        self.assertIn("1 cleared of 1 run", page["records"][0]["line"])


class TheWiring(unittest.TestCase):
    def test_the_loop_runs_on_both_bridges(self):
        self.assertEqual(BRIDGE.count('\n    _Pass("_guild_run_loop"),\n'), 1)
        self.assertEqual(BRIDGE.count("            _ensure_guild_run_store,\n"), 1)

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


# THE SEATS THAT CARRY A GROUP STAND AT ITS BOSSES' LEVEL. Measured on wow-dev
# (2026-10-07 to 10-09): 0 of 57 guild runs cleared the Deadmines, and 60 of
# its 68 runs ever had a tank or a healer under its bosses' level (20).
# Ragefire's runs whose tank and healer stood at its bosses' 16 cleared 21 of
# 38; those under, 10 of 89.
BOSS_LEVELS = {389: 16, 43: 20, 36: 20, 189: 40, 289: 62}


class TheSeatsThatCarryStandAtTheBossesLevel(unittest.TestCase):
    def doors(self):
        return {d.keyword: d for d in guildrun.doors({}, BOSS_LEVELS)}

    def test_each_door_reads_its_bosses_level(self):
        doors = self.doors()
        self.assertEqual(doors["deadmines"].carry_floor, 20)
        self.assertEqual(doors["ragefire"].carry_floor, 16)
        self.assertEqual(doors["wailing"].carry_floor, 20)

    def test_a_shared_map_never_asks_past_the_top_of_the_doors_first_band(self):
        # The Graveyard shares the Monastery's map with the Cathedral's
        # level-40 bosses; Scholomance's skull bosses read 62.
        doors = self.doors()
        scarlet = doors["scarlet"]
        self.assertEqual(scarlet.carry_floor, scarlet.floor + guildrun.BAND_SPREAD)
        self.assertEqual(doors["scholomance"].carry_floor, 60)

    def test_an_unread_level_holds_nobody(self):
        unread = next(d for d in guildrun.doors() if d.keyword == "deadmines")
        self.assertEqual(unread.carry_floor, 0)
        self.assertTrue(guildrun.carries(member("Low", 15, PRIEST), unread))

    def test_under_the_bosses_level_does_not_carry(self):
        deadmines = self.doors()["deadmines"]
        self.assertFalse(guildrun.carries(member("Healy", 19, PRIEST), deadmines))
        self.assertTrue(guildrun.carries(member("Healy", 20, PRIEST), deadmines))

    def test_the_fallback_offers_no_door_its_tank_and_healer_cannot_carry(self):
        # cave_band's best tank is 20 and its best healer 19: Ragefire's
        # bosses are 16, Wailing Caverns' and the Deadmines' 20.
        pool = guildrun.Pool("Cave", tuple(cave_band()))
        doors = guildrun.doors({}, BOSS_LEVELS)
        p = guildrun.plan_for(pool, doors, {})
        keywords = [d.keyword for d in p.doors]
        self.assertIn("ragefire", keywords)
        self.assertNotIn("wailing", keywords)
        self.assertNotIn("deadmines", keywords)

    def test_the_bridge_reads_the_bosses_levels_for_every_guild_pass(self):
        facts = BRIDGE[BRIDGE.index("def _fetch_guild_run_facts") :]
        facts = facts[: facts.index("\ndef ")]
        self.assertIn("boss_levels = _door_boss_levels(cur)", facts)
        self.assertIn('"boss_levels": boss_levels', facts)
        self.assertIn("guildrun.BOSS_LEVELS_SQL", BRIDGE)
        self.assertIn("GROUP BY cr.map", guildrun.BOSS_LEVELS_SQL)
        # The formation pass and the social pass.
        self.assertEqual(BRIDGE.count('guildrun.doors(facts["finder_floors"])'), 0)
        self.assertEqual(
            BRIDGE.count(
                'guildrun.doors(facts["finder_floors"], facts.get("boss_levels"))'
            ),
            2,
        )


def seated_plan(level, gains):
    """A pool of five at `level` choosing between two untried doors that both
    fit, with `gains` as preraid.run_gains would give them (#760)."""
    window = [
        member("Tanky", level, WARRIOR, talent_spells=PROTECTION_TALENT),
        member("Healy", level, PRIEST, talent_spells=HOLY_TALENT),
        member("Stabby", level, ROGUE),
        member("Zappy", level, MAGE),
        member("Locky", level, WARLOCK),
    ]
    comp = guildrun.Composition(window[0], window[1], tuple(window[2:]))
    doors = tuple(
        guildrun.Door(kw, kw.title(), 50, 60, 1, 50) for kw in ("alpha", "beta")
    )
    pool = guildrun.Pool("Cave", tuple(window))
    return guildrun.Plan(
        pool=pool, options=(comp,), doors=doors, band="55-59", gains=gains
    ), comp


def gain(name, levels, best="Helm of Might for head (+9 item levels, 20%)"):
    return preraid.Gain(
        name=name,
        upgrades=1 if levels else 0,
        drops=0.2,
        levels=levels,
        best=best if levels else "",
    )


class SeatedRaidersUpgradesChooseTheDoor(unittest.TestCase):
    """#760: from level 52 a guild run's door is weighed by what it drops for
    the five seated raiders, and the reason names the upgrades."""

    def gains(self):
        return {
            "alpha": (gain("Tanky", 0), gain("Stabby", 0)),
            "beta": (
                gain("Tanky", 4.5),
                gain("Stabby", 2.0, "Edge for hands (+5 item levels, 10%)"),
            ),
        }

    def test_the_door_that_drops_more_for_the_seats_wins_a_tie(self):
        p, comp = seated_plan(55, self.gains())
        keyword, why = guildrun.heuristic_door(p, comp)
        self.assertEqual(keyword, "beta")
        self.assertIn("upgrades for Tanky (Helm of Might for head)", why)
        self.assertIn("Stabby (Edge for hands)", why)

    def test_without_gains_the_first_door_stays_first(self):
        p, comp = seated_plan(55, {})
        keyword, why = guildrun.heuristic_door(p, comp)
        self.assertEqual(keyword, "alpha")
        self.assertEqual(guildrun.upgrade_words(p, p.doors[1], comp), "")

    def test_below_level_52_the_gains_are_not_read(self):
        p, comp = seated_plan(50, self.gains())
        self.assertEqual(guildrun.heuristic_door(p, comp)[0], "alpha")
        self.assertEqual(guildrun.upgrade_levels(p, p.doors[1], comp), 0)

    def test_a_better_record_still_beats_the_gains(self):
        p, comp = seated_plan(55, self.gains())
        rows = [ended("alpha", "cleared", band="55-59", comp=comp.key)] * 3
        p = replace(p, table=guildrun.rates(rows))
        keyword, _why = guildrun.heuristic_door(p, comp)
        self.assertEqual(keyword, "alpha")

    def test_the_bridge_reads_the_seats_and_logs_the_upgrades(self):
        self.assertIn("_guild_seat_gains(", BRIDGE)
        self.assertIn("guildrun.upgrade_words(plan, decision.door", BRIDGE)
        self.assertIn("gains)", BRIDGE)


class AnySeatedRaiderIsReadByPreraid(unittest.TestCase):
    def test_a_guild_member_row_with_no_roster_tab_gets_the_class_default(self):
        rows = [
            {"name": "Stabby", "class_id": 4, "level": 55, "race": 2, "spec_tab": None}
        ]
        (m,) = preraid.members(rows, [])
        self.assertEqual((m.name, m.level, m.tree), ("Stabby", 55, -1))
        self.assertIn("overseer_raid_spec", preraid.GUILD_MEMBERS_SQL)
        self.assertIn("LEFT JOIN overseer_roster", preraid.GUILD_MEMBERS_SQL)


if __name__ == "__main__":
    unittest.main()
