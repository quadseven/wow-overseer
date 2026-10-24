"""GET /api/v2/achievements: the announcer's achievements, earned read-only.

Each rule is reached from a fixture row shaped like the table it reads
(overseer_death, overseer_guild_run, overseer_level, overseer_event,
overseer_guild_ask, overseer_command), through the pure build(). The handler
runs against a fake connection and a fake map server, so the gate (a family
guild member or a family guild, or a 404) is exercised with no database.
"""

import pathlib
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import families as families_module  # noqa: E402
import guildrun  # noqa: E402
import realmread  # noqa: E402
from apiv2 import achievements as A  # noqa: E402
from apiv2._context import Context  # noqa: E402

T0 = 1_790_000_000
MAPS = {33: "Shadowfang Keep", 36: "The Deadmines"}
ROSTER = {
    "Grug": "Cave",
    "Ugga": "Cave",
    "Og": "Cave",
    "Zug": "Bonkers",
    "Oz": "Bonkers",
}


def death(n=1, **kw):
    row = {
        "id": n,
        "name": "Grug",
        "level": 30,
        "map": 0,
        "zone": 12,
        "killer_type": "creature",
        "killer_name": "Defias Thug",
        "killer_entry": 38,
        "killer_level": None,
        "yards_fallen": -1.0,
        "fall_guard_standdown": -1,
        "fall_guard_seconds": -1,
        "ghost_recovery": "",
        "at": T0 + n,
    }
    row.update(kw)
    return row


def rows(**kw):
    out = {
        "deaths": [],
        "death_times": [],
        "run_deaths": [],
        "runs": [],
        "levels": [],
        "events": [],
        "asks": [],
        "sales": [],
        "hearths": [],
        "maps": MAPS,
    }
    out.update(kw)
    return out


def earned(r, now=T0 + 10**6):
    return A.build(r, ROSTER, now)


def ids(found):
    return sorted(a["id"] for a in found)


class DeathRules(unittest.TestCase):
    def test_drowning_in_a_dungeon_is_earned_once_with_its_source(self):
        water = {
            "killer_type": "self",
            "killer_name": "Grug",
            "map": 33,
            "fall_guard_standdown": 32,
            "fall_guard_seconds": 1,
            "yards_fallen": 0.0,
        }
        found = earned(rows(deaths=[death(7, **water), death(9, **water)]))
        got = [a for a in found if a["rule"] == "drowned_dungeon"]
        self.assertEqual(len(got), 1)
        a = got[0]
        self.assertEqual(a["member"], "Grug")
        self.assertEqual(a["guild"], "Cave")
        self.assertEqual(a["earned_at"], T0 + 7)
        self.assertEqual(a["source"], {"table": "overseer_death", "id": 7})
        self.assertIn("Shadowfang Keep", a["line"])
        self.assertIn(a["tier"], ("bronze", "silver", "gold", "dubious"))


def times(name, *offsets, start=1000):
    """overseer_death (name, at, id) rows, `offsets` seconds after T0."""
    return [
        {"id": start + i, "name": name, "at": T0 + o} for i, o in enumerate(offsets)
    ]


PARTY = "Grug:tank:warrior:30,Ugga:healer:priest:29,Og:dps:mage:30,Pug:dps:rogue:30"


def run(n=1, **kw):
    """An overseer_guild_run row as the fetch shapes it: times in seconds."""
    row = {
        "id": n,
        "guild": "Cave",
        "keyword": "deadmines",
        "members": PARTY,
        "tank": "Grug",
        "outcome": "wiped",
        "why": "everybody inside is dead",
        "deaths": 4,
        "bosses_done": 0,
        "bosses_total": 7,
        "seconds_inside": 1800,
        "started_at": T0 + n * 10000,
        "at": T0 + n * 10000 + 1800,
    }
    row.update(kw)
    return row


def inside(n, name, offset, start=5000):
    """A death of `name`, `offset` seconds into run `n` (as run() times it)."""
    return {"id": start + n * 100 + offset, "name": name, "at": T0 + n * 10000 + offset}


def event(n=1, **kw):
    row = {
        "id": n,
        "name": "Ugga",
        "kind": "item_loot",
        "subject_id": 0,
        "subject_name": "",
        "quality": 0,
        "detail": "",
        "via": "",
        "occurrences": 1,
        "map": 0,
        "at": T0 + n,
    }
    row.update(kw)
    return row


def level(n, name, new, old=None):
    return {
        "id": n,
        "name": name,
        "old": new - 1 if old is None else old,
        "level": new,
        "at": T0 + n,
    }


def asks(name, label, count, every=900, start=3000, target="quest:1473"):
    return [
        {
            "id": start + i,
            "asker": name,
            "target": target,
            "target_label": label,
            "state": "expired",
            "at": T0 + i * every,
        }
        for i in range(count)
    ]


def sale(n, name, item, count):
    return {"id": n, "name": name, "item": item, "count": count, "at": T0 + n}


BEAST = {"start": 6000, "target": "quest:6001"}

WATER = {
    "killer_type": "self",
    "killer_name": "Grug",
    "fall_guard_standdown": 32,
    "fall_guard_seconds": 1,
    "yards_fallen": 0.0,
}

# rule -> (the rows that earn it, who earns it). Every rule in the catalog has
# one; test_every_rule_has_a_fixture keeps it that way.
CASES = {
    "drowned_dungeon": (rows(deaths=[death(7, map=33, **WATER)]), "Grug"),
    "drowned": (rows(deaths=[death(17, map=0, **WATER)]), "Grug"),
    "punched_down": (
        rows(deaths=[death(3, level=30, killer_level=25)]),
        "Grug",
    ),
    "humbled": (
        rows(deaths=[death(13, level=30, killer_level=4)]),
        "Grug",
    ),
    "death_spiral": (rows(death_times=times("Ugga", 0, 60, 200, 400, 590)), "Ugga"),
    "death_marathon": (
        rows(death_times=times("Ugga", *range(0, 3600, 360))),
        "Ugga",
    ),
    "professional_corpse": (
        rows(death_times=times("Og", *range(0, 100 * 7200, 7200))),
        "Og",
    ),
    "fall_death": (
        rows(deaths=[death(4, killer_type="self", yards_fallen=62.5)]),
        "Grug",
    ),
    "fall_survived": (rows(deaths=[death(14, yards_fallen=48.0)]), "Grug"),
    "corpse_run": (rows(deaths=[death(5, ghost_recovery="corpse_run")]), "Grug"),
    "dungeon_corpse_run": (
        rows(deaths=[death(15, map=36, ghost_recovery="corpse_run")]),
        "Grug",
    ),
    "pvp_death": (
        rows(deaths=[death(6, killer_type="player", killer_name="Stabby")]),
        "Grug",
    ),
    "friendly_fire": (
        rows(deaths=[death(16, killer_type="player", killer_name="Zug")]),
        "Grug",
    ),
    "hearth_after_one": (
        rows(
            death_times=times("Oz", 0),
            hearths=[{"id": 77, "name": "Oz", "at": T0 + 300}],
        ),
        "Oz",
    ),
    "first_boss": (rows(runs=[run(1, bosses_done=1)]), ""),
    "first_clear": (
        rows(runs=[run(1, outcome="cleared", bosses_done=7, deaths=2)]),
        "",
    ),
    "flawless": (
        rows(runs=[run(1, outcome="cleared", bosses_done=7, deaths=0)]),
        ["Grug", "Og", "Ugga"],
    ),
    "speed_clear": (
        rows(runs=[run(1, outcome="cleared", bosses_done=7, seconds_inside=1100)]),
        ["Grug", "Og", "Ugga"],
    ),
    "so_close": (rows(runs=[run(1, bosses_done=6)]), ["Grug", "Og", "Ugga"]),
    "group_nap": (rows(runs=[run(1)]), ["Grug", "Og", "Ugga"]),
    "wipe_connoisseur": (
        rows(runs=[run(i) for i in range(1, 11)]),
        ["Grug", "Og", "Ugga"],
    ),
    "scenic_route": (
        rows(runs=[run(1, outcome="timed out", seconds_inside=7200)]),
        ["Grug", "Og", "Ugga"],
    ),
    "stood_at_door": (
        rows(runs=[run(1, outcome="refused", seconds_inside=0)]),
        ["Grug", "Og", "Ugga"],
    ),
    "healer_first": (
        rows(
            runs=[run(1)],
            run_deaths=[
                inside(1, "Ugga", 100),
                inside(1, "Grug", 130),
                inside(1, "Og", 140),
            ],
        ),
        "Ugga",
    ),
    "tank_alone": (
        rows(
            runs=[run(1), run(2)],
            run_deaths=[
                inside(1, "Grug", 100),
                inside(1, "Og", 900),
                inside(2, "Grug", 300),
                inside(2, "Ugga", 1000),
            ],
        ),
        "Grug",
    ),
    "level_10": (rows(levels=[level(1, "Og", 10)]), "Og"),
    "level_20": (rows(levels=[level(1, "Og", 20)]), "Og"),
    "level_30": (rows(levels=[level(1, "Og", 30)]), "Og"),
    "level_40": (rows(levels=[level(1, "Og", 41, old=39)]), "Og"),
    "level_50": (rows(levels=[level(1, "Og", 50)]), "Og"),
    "level_60": (rows(levels=[level(1, "Og", 60)]), "Og"),
    "first_epic": (
        rows(events=[event(1, subject_name="Ravager", quality=4, subject_id=7717)]),
        "Ugga",
    ),
    "first_rare": (
        rows(events=[event(1, subject_name="Cookie's Tenderizer", quality=3)]),
        "Ugga",
    ),
    "need_roll": (
        rows(
            events=[event(1, subject_name="Cookie's Tenderizer", quality=3, via="need")]
        ),
        "Ugga",
    ),
    "first_mount": (
        rows(events=[event(1, kind="learn", subject_id=762, subject_name="Riding")]),
        "Ugga",
    ),
    "cottage_industry": (
        rows(
            events=[
                event(i, kind="craft", subject_name="Linen Bandage", occurrences=7)
                for i in range(1, 9)
            ]
        ),
        "Ugga",
    ),
    "errand_runner": (
        rows(
            events=[
                event(i, kind="quest_reward", subject_name="Q") for i in range(1, 51)
            ]
        ),
        "Ugga",
    ),
    "window_shopping": (
        rows(
            events=[
                event(i, kind="town_trip", detail="vendor: nothing happened; 0 damaged")
                for i in range(1, 11)
            ]
        ),
        "Ugga",
    ),
    "held_by_spite": (
        rows(
            events=[
                event(
                    1,
                    kind="repair",
                    detail="whole: 3 damaged (2 broken) before, 0 (0) after",
                )
            ]
        ),
        "Ugga",
    ),
    "hand_me_down": (
        rows(events=[event(1, kind="item_given", subject_name="Doomspike", quality=3)]),
        "Ugga",
    ),
    "water_starer": (rows(events=[event(1, kind="fish")]), "Ugga"),
    "cloth_liquidator": (
        rows(
            sales=[sale(1, "Zug", "Linen Cloth", 12), sale(2, "Zug", "Wool Cloth", 9)]
        ),
        "Zug",
    ),
    "cq_ten": (rows(asks=asks("Oz", "Creature of the Void", 10)), "Oz"),
    "cq_fifty": (rows(asks=asks("Oz", "Creature of the Void", 50)), "Oz"),
    "stuck_day": (rows(asks=asks("Oz", "Taming the Beast", 100, **BEAST)), "Oz"),
    "stuck_three_days": (
        rows(asks=asks("Oz", "Taming the Beast", 300, start=9000, target="quest:6002")),
        "Oz",
    ),
}


class EveryRule(unittest.TestCase):
    def test_each_rule_is_earned_from_its_fixture(self):
        for rule, (r, who) in CASES.items():
            with self.subTest(rule=rule):
                got = [a for a in earned(r) if a["rule"] == rule]
                if isinstance(who, list):
                    self.assertEqual(sorted(a["member"] for a in got), who)
                else:
                    self.assertEqual([a["member"] for a in got], [who])

    def test_every_rule_has_a_fixture(self):
        self.assertEqual(sorted(A.RULES), sorted(CASES))


class DeathEdges(unittest.TestCase):
    def rules(self, r):
        return {a["rule"] for a in earned(r)}

    def test_a_creature_four_levels_below_is_no_achievement(self):
        r = rows(deaths=[death(3, level=30, killer_level=26)])
        self.assertNotIn("punched_down", self.rules(r))

    def test_a_creature_whose_level_is_not_read_is_no_achievement(self):
        self.assertNotIn("punched_down", self.rules(rows(deaths=[death(3)])))

    def test_four_deaths_in_ten_minutes_is_not_a_spiral(self):
        r = rows(death_times=times("Ugga", 0, 60, 200, 590, 1300))
        self.assertNotIn("death_spiral", self.rules(r))

    def test_a_stale_water_reading_is_not_a_drowning(self):
        stale = dict(WATER, fall_guard_seconds=40)
        self.assertNotIn("drowned", self.rules(rows(deaths=[death(7, **stale)])))

    def test_a_drop_that_kills_in_water_is_a_fall_not_a_drowning(self):
        wet = dict(WATER, yards_fallen=80.0)
        found = self.rules(rows(deaths=[death(7, **wet)]))
        self.assertNotIn("drowned", found)
        self.assertIn("fall_death", found)

    def test_a_hearth_after_two_deaths_is_not_after_one(self):
        r = rows(
            death_times=times("Oz", 0, 120),
            hearths=[{"id": 77, "name": "Oz", "at": T0 + 300}],
        )
        self.assertNotIn("hearth_after_one", self.rules(r))

    def test_a_player_outside_the_roster_is_not_friendly_fire(self):
        r = rows(deaths=[death(6, killer_type="player", killer_name="Stabby")])
        self.assertNotIn("friendly_fire", self.rules(r))


class RunEdges(unittest.TestCase):
    def of(self, r, rule):
        return [a for a in earned(r) if a["rule"] == rule]

    def test_a_guild_first_is_once_per_guild_and_dungeon(self):
        r = rows(
            runs=[
                run(1, outcome="cleared", bosses_done=7),
                run(2, outcome="cleared", bosses_done=7),
                run(
                    3,
                    outcome="cleared",
                    bosses_done=7,
                    guild="Bonkers",
                    members="Zug:tank:warrior:30",
                ),
                run(4, outcome="cleared", bosses_done=4, keyword="shadowfang"),
            ]
        )
        got = sorted(
            (a["guild"], a["id"], a["earned_at"]) for a in self.of(r, "first_clear")
        )
        self.assertEqual(
            got,
            [
                ("Bonkers", "first_clear:Bonkers:deadmines", T0 + 30000 + 1800),
                ("Cave", "first_clear:Cave:deadmines", T0 + 10000 + 1800),
                ("Cave", "first_clear:Cave:shadowfang", T0 + 40000 + 1800),
            ],
        )
        cave = [
            a
            for a in self.of(r, "first_clear")
            if a["id"] == "first_clear:Cave:deadmines"
        ][0]
        self.assertEqual(cave["who"], ["Grug", "Ugga", "Og"])
        self.assertIn("The Deadmines", cave["title"] + cave["line"])

    def test_a_pug_never_earns_anything(self):
        found = earned(rows(runs=[run(1, outcome="cleared", bosses_done=7, deaths=0)]))
        self.assertNotIn("Pug", {a["member"] for a in found})

    def test_one_lonely_tank_death_is_not_again(self):
        r = rows(
            runs=[run(1)], run_deaths=[inside(1, "Grug", 100), inside(1, "Og", 900)]
        )
        self.assertEqual(self.of(r, "tank_alone"), [])

    def test_the_tank_dying_first_is_not_the_healer_first(self):
        r = rows(
            runs=[run(1)], run_deaths=[inside(1, "Grug", 100), inside(1, "Ugga", 130)]
        )
        self.assertEqual(self.of(r, "healer_first"), [])

    def test_a_death_outside_the_run_window_is_not_the_runs(self):
        r = rows(
            runs=[run(1)], run_deaths=[inside(1, "Ugga", -60), inside(1, "Grug", 100)]
        )
        self.assertEqual(self.of(r, "healer_first"), [])

    def test_nine_wipes_are_not_ten(self):
        r = rows(runs=[run(i) for i in range(1, 10)])
        self.assertEqual(self.of(r, "wipe_connoisseur"), [])


class OtherEdges(unittest.TestCase):
    def rules(self, r):
        return {(a["rule"], a["member"]) for a in earned(r)}

    def test_a_level_past_a_milestone_without_crossing_it_is_not_the_milestone(self):
        self.assertNotIn(
            ("level_10", "Og"), self.rules(rows(levels=[level(1, "Og", 11)]))
        )

    def test_nineteen_cloth_is_not_twenty(self):
        r = rows(
            sales=[sale(1, "Zug", "Linen Cloth", 19), sale(2, "Zug", "Rough Stone", 40)]
        )
        self.assertNotIn(("cloth_liquidator", "Zug"), self.rules(r))

    def test_asks_for_two_quests_do_not_add_up(self):
        r = rows(
            asks=asks("Oz", "A", 5) + asks("Oz", "B", 5, start=4000, target="quest:9")
        )
        self.assertNotIn(("cq_ten", "Oz"), self.rules(r))

    def test_a_silence_over_six_hours_ends_a_stuck_run(self):
        early = asks("Oz", "Taming the Beast", 40, every=900)
        late = [
            dict(a, id=a["id"] + 500, at=a["at"] + 7 * 3600 + 40 * 900) for a in early
        ]
        self.assertNotIn(("stuck_day", "Oz"), self.rules(rows(asks=early + late)))

    def test_nobody_outside_the_roster_earns_anything(self):
        r = rows(deaths=[death(7, name="Stranger", map=33, **WATER)])
        self.assertEqual(earned(r), [])


def everything():
    """Every fixture at once, as one realm's rows."""
    out = rows()
    for r, _ in CASES.values():
        for k, v in r.items():
            if k in ("maps",):
                continue
            if isinstance(v, dict):
                out[k] = {**out[k], **v}
            else:
                out[k] = out[k] + list(v)
    return out


class Idempotent(unittest.TestCase):
    def test_the_same_rows_give_the_same_list(self):
        self.assertEqual(earned(everything()), earned(everything()))

    def test_row_order_does_not_matter(self):
        r = everything()
        flipped = {
            k: (list(reversed(v)) if isinstance(v, list) else v) for k, v in r.items()
        }
        self.assertEqual(earned(r), earned(flipped))

    def test_ids_are_unique(self):
        found = earned(everything())
        self.assertEqual(len({a["id"] for a in found}), len(found))

    def test_a_later_drowning_does_not_move_the_first(self):
        first = earned(rows(deaths=[death(7, map=33, **WATER)]))
        again = earned(
            rows(deaths=[death(7, map=33, **WATER), death(90, map=33, **WATER)])
        )
        self.assertEqual(first, again)


class Copy(unittest.TestCase):
    def test_at_least_thirty_rules_in_the_four_tiers(self):
        self.assertGreaterEqual(len(A.RULES), 30)
        self.assertTrue(all(r.tier in A.TIERS for r in A.RULES.values()))

    def test_every_line_is_ascii_one_line_and_short(self):
        for a in earned(everything()):
            with self.subTest(rule=a["rule"]):
                text = a["title"] + a["line"]
                self.assertTrue(text.isascii(), text)
                self.assertNotIn("\n", text)
                self.assertNotIn("{", text)
                self.assertLessEqual(len(a["line"]), 140, a["line"])


def server():
    store = families_module.MemoryStore(
        {"Grug": ["Grug", "Ugga"], "Zug": ["Zug", "Oz"]},
        {"Cave": ["Grug", "Ugga", "Og"], "Bonkers": ["Zug", "Oz"]},
    )
    return types.SimpleNamespace(
        FAMILIES=families_module.Families(store, fallback=lambda: []),
        achievements=types.SimpleNamespace(MAP_NAMES=MAPS),
    )


def as_guildrun(r):
    """run() as guildrun's own read returns it: unix times under its names."""
    out = {k: v for k, v in r.items() if k not in ("started_at", "at")}
    return dict(out, state="ended", created_unix=r["started_at"], ended_unix=r["at"])


# Every statement the endpoint reads, by the constant it is built from; the
# in-memory reader raises on any other, so a reworded read fails here.
LIVE = {
    A.MEMBERS_SQL: [{"name": n, "guild": g} for n, g in ROSTER.items()],
    A.NOW_SQL: [{"now_at": T0 + 10**6}],
    A.DEATHS_SQL: [
        death(7, map=33, **WATER),
        death(8, name="Zug", killer_type="player", killer_name="Stabby"),
    ],
    A.DEATH_TIMES_SQL: [],
    A.HEARTHS_SQL: [],
    A.RUN_DEATHS_SQL: [],
    guildrun._RUN_SQL: [
        as_guildrun(r)
        for r in (
            run(1, outcome="cleared", bosses_done=7),
            run(3, outcome="cleared", bosses_done=4, keyword="shadowfang"),
            run(2, guild="Bonkers", members="Zug:tank:warrior:30,Oz:healer:priest:29"),
        )
    ],
    A.LEVELS_SQL: [level(1, "Oz", 20), level(2, "Ugga", 30)],
    A.EVENTS_SQL: [],
    A.SALES_SQL: [],
    A.ASKS_SQL: [],
}


def call(query, answers=None):
    rd = realmread.Memory(LIVE if answers is None else answers)
    srv = server()
    ctx = Context(read=rd, server=srv, families=srv.FAMILIES)
    status, payload = A.achievements(query, ctx)
    return status, payload, rd.asked


class Gate(unittest.TestCase):
    def setUp(self):
        A.clear_cache()

    def test_a_name_outside_the_families_is_refused_before_any_read(self):
        status, payload, asked = call({"name": ["Stranger"]})
        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "not a guild member"})
        self.assertEqual(asked, [])

    def test_a_name_of_the_wrong_shape_is_refused(self):
        for bad in ("Grug1", "x" * 13, "Grug Ugga", ""):
            with self.subTest(bad=bad):
                status, _, asked = call({"name": [bad]})
                self.assertEqual(status, 404)
                self.assertEqual(asked, [])

    def test_a_guild_outside_the_families_is_refused_before_any_read(self):
        status, payload, asked = call({"guild": ["Pyreborne"]})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "no such guild")
        self.assertEqual(asked, [])

    def test_a_member_gets_its_own_list_and_the_firsts_it_was_part_of(self):
        status, payload, _ = call({"name": ["Grug"]})
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "Grug")
        self.assertEqual(payload["guild"], "Cave")
        rules = {a["rule"] for a in payload["earned"]}
        self.assertIn("drowned_dungeon", rules)
        self.assertIn("first_clear", rules)
        self.assertTrue(
            all(a["member"] == "Grug" or "Grug" in a["who"] for a in payload["earned"])
        )
        self.assertEqual(payload["of"], len(A.RULES))
        self.assertEqual(payload["count"], len({a["rule"] for a in payload["earned"]}))

    def test_a_guild_feed_holds_only_that_guilds(self):
        status, payload, _ = call({"guild": ["cave"]})
        self.assertEqual(status, 200)
        self.assertEqual(payload["guilds"], ["Cave"])
        self.assertTrue(payload["items"])
        self.assertEqual({a["guild"] for a in payload["items"]}, {"Cave"})

    def test_no_guild_is_both_family_guilds(self):
        status, payload, _ = call({})
        self.assertEqual(status, 200)
        self.assertEqual(sorted(payload["guilds"]), ["Bonkers", "Cave"])
        self.assertEqual({a["guild"] for a in payload["items"]}, {"Bonkers", "Cave"})

    def test_every_statement_reads_and_every_table_read_is_bounded(self):
        for query in ({"name": ["Grug"]}, {"guild": ["bonkers"]}, {}):
            A.clear_cache()
            _, _, log = call(query)
            for sql, _params in log:
                with self.subTest(sql=sql[:60]):
                    self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
                    if "FROM overseer_" in sql:
                        self.assertIn("LIMIT", sql)
                        self.assertTrue("INTERVAL" in sql or "BETWEEN" in sql, sql)


class RunRows(unittest.TestCase):
    def test_a_guildrun_row_reads_in_seconds_and_ends_when_formed_without_an_end(self):
        r = run(4)
        self.assertEqual(A.run_row(as_guildrun(r))["at"], r["at"])
        self.assertEqual(A.run_row(as_guildrun(r))["started_at"], r["started_at"])
        bare = dict(as_guildrun(r), ended_unix=None)
        self.assertEqual(A.run_row(bare)["at"], r["started_at"])


class EndedSince(unittest.TestCase):
    def test_guildrun_reads_every_ended_run_of_the_guilds_in_the_window(self):
        rd = realmread.Memory({guildrun._RUN_SQL: [as_guildrun(run(1))]})
        got = guildrun.ended_since(rd, ["Cave", "Bonkers"], 90, 50)
        self.assertEqual([r["id"] for r in got], [1])
        sql, params = rd.asked[0]
        self.assertIn("state = 'ended'", sql)
        self.assertIn("INTERVAL %s DAY", sql)
        self.assertNotIn("outcome IN", sql)
        self.assertEqual(params, ("Cave", "Bonkers", 90, 50))

    def test_no_guild_reads_nothing(self):
        rd = realmread.Memory({})
        self.assertEqual(guildrun.ended_since(rd, [], 90, 50), [])
        self.assertEqual(rd.asked, [])


class SaleRows(unittest.TestCase):
    def test_a_sold_answer_reads_as_the_item_and_its_count(self):
        row = {
            "id": 5,
            "name": "Zug",
            "at": T0,
            "result": '{"outcome":"sold","item":{"guid":1,"entry":2589,"name":"Linen Cloth","count":20,"stack":20},"gained":80}',
        }
        self.assertEqual(
            A.sale_row(row),
            {"id": 5, "name": "Zug", "at": T0, "item": "Linen Cloth", "count": 20},
        )

    def test_a_refused_or_unreadable_answer_is_no_sale(self):
        for result in (
            '{"outcome":"refused","item":{"name":"Linen Cloth","count":20}}',
            "not json",
            None,
        ):
            with self.subTest(result=result):
                self.assertIsNone(
                    A.sale_row({"id": 5, "name": "Zug", "at": T0, "result": result})
                )


if __name__ == "__main__":
    unittest.main()
