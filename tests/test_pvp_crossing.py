"""An honor buyer crosses to the vendor's continent (#603, slice 1, outbound).

Both Warsong Gulch supply officers stand only on Kalimdor. Decided on
2026-10-26: a buyer that holds the honor for its next PvP upgrade takes the
boat or zeppelin to the vendor's continent, but only while its family is idle
in town, and only when the dock and the vendor can be reached, so the far-walk
budget is never spent on a trip that cannot succeed. These pin the pure gate
in pvpgear.py, the guild job step it becomes, and the bridge wiring as source.
"""

import pathlib
import re
import unittest

import guildjobs
import guildsocial
import pvpgear
from source_utils import function_source

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

EASTERN_KINGDOMS, KALIMDOR, OUTLAND = 0, 1, 530
SILVERWING = 14753
ROGUE, HUMAN = 4, 1
LIST_RING = 18500
WSG_RING = 19325


def open_gate():
    return pvpgear.Crossing(True, True, True)


def ring(entry, agility, name="Ring", required=0):
    return {
        "Item": entry,
        "item_name": name,
        "item_level": 60,
        "required_level": required,
        "allowable_class": -1,
        "class": 4,
        "subclass": 0,
        "inventory_type": 11,
        "stat_type1": 3,
        "stat_value1": agility,
    }


def wsg_offer(maps=(KALIMDOR,), honor=300):
    return pvpgear.Offer(
        WSG_RING,
        SILVERWING,
        honor,
        ring(WSG_RING, 15, "Sentinel's Band", 18),
        frozenset(maps),
        "Illiyana Moonblaze",
    )


def member_row(map_id=EASTERN_KINGDOMS, honor=300, name="Auren"):
    return {
        "name": name,
        "guild_name": "Cave",
        "level": 20,
        "class_id": ROGUE,
        "race": HUMAN,
        "honor": honor,
        "talent_spells": None,
        "snapshot_map": map_id,
    }


def worn_rings(name):
    return [
        dict(ring(1000 + slot, 5, "Worn ring"), name=name, slot=slot, entry=1000 + slot)
        for slot in (10, 11)
    ]


def seekers(rows, offers, crossings=None):
    worn = [w for r in rows for w in worn_rings(r["name"])]
    gear = guildsocial.gear_by_name(rows, worn, [])
    lists = {LIST_RING: ring(LIST_RING, 8, "Listed ring")}
    return pvpgear.seekers_from_rows(
        rows, gear, lists, offers, crossings=crossings or {}
    )


def buyer_aim(held=300, maps=(KALIMDOR,)):
    (s,) = seekers(
        [member_row(KALIMDOR, held)], [wsg_offer(maps)], {"Auren": open_gate()}
    )
    return pvpgear.plan_aims([s])["Auren"]


def job_member(map_id=EASTERN_KINGDOMS, **kw):
    base = dict(
        name="Auren", guild="Cave", role=guildjobs.RAIDER, level=20, class_id=ROGUE,
        online=True, map_id=map_id, x=0.0, y=0.0, money=50000, eligible=True,
    )  # fmt: skip
    base.update(kw)
    return guildjobs.Member(**base)


def cross_row(age, refusal="", retryable=False, action="pvp-cross"):
    return guildjobs.Recent(
        "Auren",
        action,
        age,
        "error" if refusal else "applied",
        refusal=refusal,
        retryable=retryable,
        dest=KALIMDOR,
        command="cross-to-map map:%d" % KALIMDOR,
    )


def pvp_walk(age, status="error"):
    return guildjobs.Recent("Auren", pvpgear.ACTION, age, status, walk=True)


def plan_for(crossing, recent=(), map_id=EASTERN_KINGDOMS):
    """The guild job plan for one buyer on `map_id` holding 300 honor."""
    (s,) = seekers([member_row(map_id)], [wsg_offer()], {"Auren": crossing})
    aims = pvpgear.plan_aims([s])
    pvp = {
        n: (a, pvpgear.next_move(a, map_id, False, recent, crossing))
        for n, a in aims.items()
    }
    return aims, guildjobs.plan([job_member(map_id)], pvp=pvp, recent=recent)


def cross_steps(plan):
    return [
        s
        for s in plan.steps
        if any(r.command.startswith("cross-to-map") for r in s.rows)
    ]


class TheCrossingMove(unittest.TestCase):
    """crossing_move: the trip only for an idle buyer with the honor, a vendor
    across the sea, and a reachable dock and vendor."""

    def test_an_idle_buyer_with_the_honor_crosses_to_the_vendor(self):
        move = pvpgear.crossing_move(buyer_aim(), EASTERN_KINGDOMS, True, True, True)
        self.assertEqual(pvpgear.CROSS, move.kind)
        self.assertEqual(KALIMDOR, move.to_map)
        self.assertIn("Kalimdor", move.said)
        self.assertIn("Illiyana Moonblaze", move.said)

    def test_a_busy_family_gets_no_crossing(self):
        self.assertIsNone(
            pvpgear.crossing_move(buyer_aim(), EASTERN_KINGDOMS, False, True, True)
        )

    def test_an_unreachable_dock_or_vendor_gets_no_crossing(self):
        a = buyer_aim()
        self.assertIsNone(pvpgear.crossing_move(a, EASTERN_KINGDOMS, True, False, True))
        self.assertIsNone(pvpgear.crossing_move(a, EASTERN_KINGDOMS, True, True, False))

    def test_short_of_the_honor_or_already_there_it_does_not_cross(self):
        self.assertIsNone(
            pvpgear.crossing_move(
                buyer_aim(held=299), EASTERN_KINGDOMS, True, True, True
            )
        )
        self.assertIsNone(
            pvpgear.crossing_move(buyer_aim(), KALIMDOR, True, True, True)
        )
        both = buyer_aim(maps=(EASTERN_KINGDOMS, KALIMDOR))
        self.assertIsNone(
            pvpgear.crossing_move(both, EASTERN_KINGDOMS, True, True, True)
        )

    def test_off_the_two_classic_continents_it_does_not_cross(self):
        self.assertIsNone(pvpgear.crossing_move(buyer_aim(), OUTLAND, True, True, True))
        self.assertIsNone(pvpgear.crossing_move(buyer_aim(), None, True, True, True))


class TheGate(unittest.TestCase):
    """The facts the bridge reads into each buyer's Crossing."""

    def test_a_family_idle_in_town(self):
        rows = [
            {"name": "Lead", "job": "town run", "snapshot_map": EASTERN_KINGDOMS},
            {"name": "Mend", "job": "craft", "snapshot_map": KALIMDOR},
        ]
        self.assertTrue(pvpgear.family_idle_in_town(rows))

    def test_a_family_in_a_run_questing_or_away_is_not_idle(self):
        cases = {
            "in a run": [{"name": "Lead", "job": "dungeon:deadmines"}],
            "questing": [{"name": "Lead", "job": "quest", "snapshot_map": 0}],
            "inside an instance": [
                {"name": "Lead", "job": "town run", "snapshot_map": 36}
            ],
            "no family read": [],
            # #1921: a member whose snapshot is unread may be anywhere.
            "an unread snapshot": [
                {"name": "Lead", "job": "town run", "snapshot_map": EASTERN_KINGDOMS},
                {"name": "Mend", "job": "craft", "snapshot_map": None},
            ],
        }
        for situation, rows in cases.items():
            with self.subTest(situation=situation):
                self.assertFalse(pvpgear.family_idle_in_town(rows))

    def test_the_gate_reads_the_buyers_family_not_its_whole_guild(self):
        # #1921: two families share the guild Cave. The buyer's own family is
        # idle in town; the other one is in a run, and does not shut its gate.
        rows = [
            {"name": "Auren", "family": "Lead", "guild_name": "Cave",
             "job": "town run", "snapshot_map": EASTERN_KINGDOMS},
            {"name": "Lead", "family": "Lead", "guild_name": "Cave",
             "job": "craft", "snapshot_map": EASTERN_KINGDOMS},
            {"name": "Mend", "family": "Lead", "guild_name": "Elsewhere",
             "job": "town run", "snapshot_map": KALIMDOR},
            {"name": "Zug", "family": "Zug", "guild_name": "Cave",
             "job": "dungeon:deadmines", "snapshot_map": 36},
            {"name": "Lone", "family": "", "guild_name": "Cave",
             "job": "dungeon:deadmines", "snapshot_map": 36},
        ]  # fmt: skip
        mine = pvpgear.family_rows_for("Auren", "Cave", rows)
        self.assertEqual(["Auren", "Lead", "Mend"], [r["name"] for r in mine])
        self.assertTrue(pvpgear.family_idle_in_town(mine))
        theirs = pvpgear.family_rows_for("Zug", "Cave", rows)
        self.assertEqual(["Zug"], [r["name"] for r in theirs])
        # A buyer off the roster reads the family with the most members in
        # its guild (families.guilds), and none where no family plays.
        stray = pvpgear.family_rows_for("Stray", "Cave", rows)
        self.assertEqual(["Auren", "Lead", "Mend"], [r["name"] for r in stray])
        self.assertEqual([], pvpgear.family_rows_for("Stray", "Nowhere", rows))

    def test_the_dock_is_shut_by_a_wall_or_a_cooling_refusal(self):
        wall = "no transport the module knows sails from this map to that map for this faction"
        self.assertTrue(pvpgear.dock_reachable(KALIMDOR, {}, ()))
        self.assertFalse(pvpgear.dock_reachable(KALIMDOR, {KALIMDOR: wall}, ()))
        self.assertFalse(pvpgear.dock_reachable(None, {}, ()))
        refused = cross_row(5, "a fight", retryable=True)
        self.assertFalse(pvpgear.dock_reachable(KALIMDOR, {}, (refused,)))
        self.assertTrue(
            pvpgear.dock_reachable(KALIMDOR, {}, (cross_row(11, "a fight", True),))
        )
        ground = cross_row(60, "the walk to the berth gave up on the ground", True)
        self.assertFalse(pvpgear.dock_reachable(KALIMDOR, {}, (ground,)))

    def test_a_crossing_under_way_keeps_its_buyer_going(self):
        self.assertTrue(pvpgear.crossing_under_way((cross_row(10),)))
        self.assertFalse(pvpgear.crossing_under_way((cross_row(10, "a fight"),)))
        self.assertFalse(pvpgear.crossing_under_way((cross_row(40),)))
        other = cross_row(10, action="classquest-cross")
        self.assertFalse(pvpgear.crossing_under_way((other,)))


class ThePlan(unittest.TestCase):
    """From the seekers to the guild job step."""

    def test_an_idle_buyer_gets_one_crossing_row_and_no_walk(self):
        aims, plan = plan_for(open_gate())
        self.assertIn("Auren", aims)
        (step,) = plan.steps
        self.assertEqual("pvp", step.action)
        self.assertIsNone(step.walk)
        self.assertEqual("Kalimdor", step.goal)
        self.assertEqual(
            [("job", "cross-to-map map:1", "guildjobs:pvp-cross:Auren")],
            [(r.kind, r.command, r.source) for r in step.rows],
        )

    def test_the_same_buyer_with_a_busy_family_gets_none(self):
        aims, plan = plan_for(pvpgear.Crossing(False, True, True))
        self.assertEqual({}, aims)
        self.assertEqual([], cross_steps(plan))

    def test_an_unreachable_dock_or_vendor_starts_no_trip(self):
        for crossing in (
            pvpgear.Crossing(True, False, True),
            pvpgear.Crossing(True, True, False),
        ):
            with self.subTest(crossing=crossing):
                aims, plan = plan_for(crossing)
                self.assertEqual({}, aims)
                # No row at all: no walk is asked, so no far walk is spent.
                self.assertEqual((), tuple(r for s in plan.steps for r in s.rows))

    def test_a_crossing_under_way_is_not_asked_again_and_holds(self):
        young = cross_row(5)
        aims, plan = plan_for(open_gate(), recent=(young,))
        self.assertIn("Auren", aims)
        self.assertEqual([], cross_steps(plan))
        self.assertEqual((), plan.steps)

    def test_a_dock_another_crossing_holds_waits_and_holds_nothing(self):
        # #1921: a class quest's crossing 5 minutes old keeps the clock
        # (guildjobs.crossing_cooling), so no crossing row is written this
        # pass and the buyer is not held from mail, levelling or crafting.
        cooling = pvpgear.Crossing(True, True, True, cooling=True)
        move = pvpgear.next_move(buyer_aim(), EASTERN_KINGDOMS, False, (), cooling)
        self.assertEqual(pvpgear.ACROSS, move.kind)
        self.assertFalse(move.keeps)
        other = cross_row(5, action="classquest-cross")
        aims, plan = plan_for(cooling, recent=(other,))
        self.assertIn("Auren", aims)
        self.assertEqual([], cross_steps(plan))
        step, _doing, held = guildjobs._pvp_first(
            job_member(), (aims["Auren"], move), (other,), 0.0
        )
        self.assertIsNone(step)
        self.assertFalse(held)

    def test_the_crossing_shares_every_crossings_clock(self):
        self.assertIn(pvpgear.CROSS_ACTION, guildjobs.CROSS_ACTIONS)

    def test_on_the_vendors_continent_it_buys_as_before(self):
        a = buyer_aim()
        move = pvpgear.next_move(a, KALIMDOR, False, (), open_gate())
        self.assertEqual(pvpgear.BUY, move.kind)

    def test_a_shut_gate_after_aiming_waits_and_holds_nothing(self):
        move = pvpgear.next_move(buyer_aim(), EASTERN_KINGDOMS, False, ())
        self.assertEqual(pvpgear.ACROSS, move.kind)
        self.assertFalse(move.keeps)


class NaturalOnly(unittest.TestCase):
    """No teleport, summon or GM command anywhere in the crossing's path."""

    FORBIDDEN = re.compile(r"teleport|summon|\.tele\b|\.gm\b|\.go\b|\bport\b", re.I)

    def test_the_rows_are_the_modules_boat_crossing_only(self):
        _, plan = plan_for(open_gate())
        for step in plan.steps:
            for row in (step.walk, *step.rows):
                if row is None:
                    continue
                with self.subTest(command=row.command):
                    self.assertTrue(row.command.startswith("cross-to-map map:"))
                    self.assertIsNone(self.FORBIDDEN.search(row.command))

    def test_the_code_names_no_teleport_summon_or_gm_verb(self):
        sources = [
            function_source(f)
            for f in (
                pvpgear.crossing_move,
                pvpgear._buy_move,
                pvpgear.dock_reachable,
                pvpgear.crossing_under_way,
                guildjobs._pvp_cross_step,
            )
        ]
        body = BRIDGE[BRIDGE.index("def _pvp_crossings") :]
        sources.append(body[: body.index("def _fetch_pvp_facts")])
        for source in sources:
            code = "\n".join(
                line for line in source.splitlines() if not line.strip().startswith("#")
            )
            self.assertIsNone(self.FORBIDDEN.search(code.split('"""')[-1]))


class TheWiring(unittest.TestCase):
    def test_the_bridge_reads_the_gate_and_passes_it_on(self):
        self.assertIn(
            "_fetch_pvp_facts, [m.name for m in wanted], set(busy or ()), recent)",
            BRIDGE,
        )
        self.assertIn('facts["crossings"].get(name))', BRIDGE)
        self.assertIn("cur.execute(_PVP_FAMILY_SQL)", BRIDGE)
        self.assertIn(
            "crossings = _pvp_crossings(rows, family_rows, set(busy or ()), recent)",
            BRIDGE,
        )

    def test_the_gate_reads_the_walls_the_clock_and_the_vendor_walks(self):
        body = BRIDGE[BRIDGE.index("def _pvp_crossings") :]
        body = body[: body.index("def _fetch_pvp_facts")]
        for fact in (
            "name not in busy",
            "pvpgear.family_idle_in_town(",
            "pvpgear.crossing_under_way(",
            "guildjobs.class_walls(name, recent)",
            "guildjobs.CROSS_ACTIONS",
            "guildjobs.pvp_walk_cooldown(name, recent) == 0",
            "pvpgear.family_rows_for(",
            "cooling=guildjobs.crossing_cooling(name, recent) and not under_way",
        ):
            with self.subTest(fact=fact):
                self.assertIn(fact, body)

    def test_the_family_read_carries_the_rosters_family(self):
        start = BRIDGE.index("_PVP_FAMILY_SQL = (")
        sql = BRIDGE[start : BRIDGE.index(")\n", start)]
        self.assertIn("r.family", sql)


if __name__ == "__main__":
    unittest.main()
