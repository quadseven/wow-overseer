"""The fire resistance plan for the raid's tanks and healers (#759).

What was missing: raidsupply set fire resistance targets for every tank and
healer, but nothing named a piece that would meet them, and the tank fire
resistance sets in data/bis/situational.json were read by nothing. These
tests hold the plan to the committed data: each tank and healer seat gets a
target, a worn total and a next piece with its source; the Raid tab and the
raid supply log line name it; and the dungeon planner counts a planned piece
that drops for a family tank. Every test runs on fake rows; none touches a
database.
"""

import contextlib
import pathlib
import unittest

import campaignplan
import fireplan
import gearscore
import preraid
import raidsupply as rs
from test_campaign_queue import _load  # sets up the pymysql stub
from test_preraid import ANCHORS, TEXTS, drop, item_row

HERE = pathlib.Path(__file__).resolve().parent.parent
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")
RAID_JS = (HERE / "app" / "views" / "raid.js").read_text(encoding="utf-8")

WILDFIRE_CAPE = 12905  # 20 fire resistance, Blackrock Spire
EMBERPLATE_ARMGUARDS = 11767  # 10, Blackrock Depths, the warrior set's wrist
CINDERHIDE_ARMSPLINTS = 11764  # 10, Blackrock Depths, the druid set's wrist
BACK, WRIST = 14, 8


def raider(name, role, class_id, worn=(), **over):
    return rs.Raider(
        name=name,
        role=role,
        class_id=class_id,
        fire=sum(f for _s, f in worn),
        worn_fire=tuple(worn),
        **over,
    )


class TheSetsAreRead(unittest.TestCase):
    def test_a_warrior_tank_plans_from_the_warrior_set(self):
        entries = fireplan.planned_entries(fireplan.TANK, fireplan.WARRIOR)
        sets = gearscore.load_situational()["tank_fire_resistance"]["sets"]
        self.assertIn(WILDFIRE_CAPE, sets["warrior_pre-raid"]["back"])
        self.assertIn(WILDFIRE_CAPE, entries)
        self.assertIn(EMBERPLATE_ARMGUARDS, entries)
        self.assertNotIn(CINDERHIDE_ARMSPLINTS, entries)

    def test_a_paladin_and_a_death_knight_tank_wear_the_plate_set(self):
        warrior = fireplan.planned_entries(fireplan.TANK, fireplan.WARRIOR)
        for cls in (fireplan.PALADIN, fireplan.DEATH_KNIGHT):
            self.assertEqual(fireplan.planned_entries(fireplan.TANK, cls), warrior)

    def test_a_druid_tank_plans_from_the_druid_set(self):
        entries = fireplan.planned_entries(fireplan.TANK, fireplan.DRUID)
        self.assertIn(CINDERHIDE_ARMSPLINTS, entries)
        self.assertNotIn(EMBERPLATE_ARMGUARDS, entries)

    def test_a_piece_with_no_fire_resistance_is_not_planned(self):
        # Gyth's Skull is in the warrior set for its stamina, not its fire.
        for piece in fireplan.tank_pieces(fireplan.WARRIOR):
            self.assertGreater(piece.fire, 0, piece.name)
        self.assertNotIn(
            12952, fireplan.planned_entries(fireplan.TANK, fireplan.WARRIOR)
        )

    def test_a_healer_plans_only_what_its_armour_allows(self):
        rows = gearscore.load_situational()["fire_resistance_by_slot"]["slots"]
        by_id = {r["id"]: r for slot in rows.values() for r in slot}
        priest = fireplan.slot_pieces(fireplan.PRIEST)
        self.assertTrue(priest)
        for piece in priest:
            row = by_id[piece.entry]
            self.assertEqual(row["item_class"], fireplan.ARMOUR)
            self.assertIn(row["item_subclass"], (fireplan.MISC, fireplan.CLOTH))
        shaman = {p.entry for p in fireplan.slot_pieces(fireplan.SHAMAN)}
        plate = {i for i, r in by_id.items() if r["item_subclass"] == fireplan.PLATE}
        self.assertFalse(shaman & plate)


class EverySeatHasAPlan(unittest.TestCase):
    def test_a_bare_tank_is_sent_for_the_cape_first(self):
        plan = fireplan.plan("Grug", fireplan.MAIN_TANK, fireplan.WARRIOR, ())
        self.assertEqual((plan.target, plan.worn, plan.short), (200, 0, 200))
        self.assertEqual(plan.next.piece.entry, WILDFIRE_CAPE)
        self.assertEqual(plan.next.slot, BACK)
        self.assertEqual(plan.next.gain, 20)
        self.assertIn("Blackrock Spire", plan.next.piece.source)
        self.assertIn("Wildfire Cape", plan.line)

    def test_a_slot_already_covered_moves_the_plan_on(self):
        plan = fireplan.plan("Grug", fireplan.TANK, fireplan.WARRIOR, ((BACK, 20),))
        self.assertEqual(plan.worn, 20)
        self.assertNotEqual(plan.next.slot, BACK)
        self.assertGreater(plan.next.gain, 0)

    def test_the_pre_raid_set_comes_before_the_post_raid_set(self):
        plan = fireplan.plan("Grug", fireplan.TANK, fireplan.WARRIOR, ())
        self.assertEqual(plan.next.piece.phase, "pre-raid")

    def test_a_seat_at_its_target_needs_no_piece(self):
        plan = fireplan.plan("Aylysae", fireplan.HEALER, fireplan.PRIEST, ((6, 60),))
        self.assertEqual(plan.short, 0)
        self.assertIsNone(plan.next)
        self.assertIn("at target", plan.line)

    def test_a_crafted_piece_names_its_trade(self):
        # A druid tank wearing every dungeon piece of its set is next sent to
        # the Volcanic set, which leatherworking makes.
        drops = [
            p
            for p in fireplan.tank_pieces(fireplan.DRUID)
            if p.phase == "pre-raid" and "drops in" in p.source
        ]
        worn = []
        for p in drops:
            worn.append((fireplan.SLOTS[p.slot][0], p.fire))
        plan = fireplan.plan("Brug", fireplan.TANK, fireplan.DRUID, worn)
        self.assertIsNotNone(plan.next)
        self.assertIn("leatherworking", plan.next.piece.source)

    def test_every_tank_and_healer_line_carries_a_plan(self):
        raiders = (
            raider("Grug", rs.TANK, rs.WARRIOR, main_tank=True),
            raider("Brug", rs.TANK, rs.DRUID, worn=((WRIST, 10),)),
            raider("Crag", rs.TANK, rs.PALADIN),
            raider("Aylysae", rs.HEALER, rs.PRIEST),
            raider("Zug", rs.HEALER, rs.SHAMAN),
            raider("Atherene", rs.PHYSICAL, rs.ROGUE),
        )
        lines = rs.fire_lines(raiders)
        self.assertEqual(
            [f.raider.name for f in lines], ["Grug", "Crag", "Brug", "Aylysae", "Zug"]
        )
        for line in lines:
            self.assertEqual(line.plan.target, line.target)
            self.assertEqual(line.plan.worn, line.raider.fire)
            self.assertIsNotNone(line.plan.next, line.raider.name)
            self.assertNotEqual(line.plan.next.piece.source, fireplan.NO_SOURCE)
            self.assertTrue(line.next_said)
        self.assertEqual(lines[0].plan.seat, fireplan.MAIN_TANK)
        self.assertEqual(lines[2].plan.worn, 10)


class ThePlanIsSaid(unittest.TestCase):
    RAIDERS = (
        raider("Grug", rs.TANK, rs.WARRIOR, main_tank=True),
        raider("Aylysae", rs.HEALER, rs.PRIEST),
    )

    def test_the_raid_supply_log_line_names_the_next_piece(self):
        plan = rs.SupplyPlan("Cave", (), tuple(rs.fire_lines(self.RAIDERS)))
        line = rs.summary(plan)
        self.assertIn("fire resistance short Grug 0/200 (next Wildfire Cape", line)
        self.assertIn("Blackrock Spire", line)

    def test_the_raid_tab_has_a_next_piece_column(self):
        card = rs.card(self.RAIDERS, {}, {}, None, 0)
        self.assertEqual(card["fire_columns"][-1], "next piece")
        grug = card["fire"][0]["cells"]
        self.assertEqual(grug[:5], ["Grug", "main tank", "200", "0", "200"])
        self.assertTrue(grug[5].startswith("Wildfire Cape"))
        self.assertIn("by-slot list", card["fire_line"])

    def test_the_page_finds_the_short_column_by_name(self):
        self.assertIn('cols.indexOf("short")', RAID_JS)

    def test_jev_is_told_the_next_piece(self):
        state, _questions = rs.question("Cave", [], rs.fire_lines(self.RAIDERS), [], 0)
        self.assertTrue(
            state["fire_resistance"][0]["next_piece"].startswith("Wildfire")
        )

    def test_the_module_ships_in_the_image(self):
        self.assertIn("fireplan.py", DOCKERFILE)


# The planner half: a protection warrior tank and a holy priest, level 60 in
# the Eastern Kingdoms, with a fire piece of the warrior set dropping in
# Blackrock Depths and a priest robe dropping in Scholomance, so neither run
# crosses to another continent.
EASTERN_KINGDOMS = 0
CLASSES = {"Grug": (1, 2), "Ugga": (5, 1)}
ITEMS = [
    item_row(
        EMBERPLATE_ARMGUARDS,
        "Emberplate Armguards",
        57,
        9,
        fire_res=10,
        required_level=52,
    ),
    item_row(102, "Robe of Everlasting Night", 62, 20, sub=1, spells=(18056,)),
    # Fire resistance, but in no plan.
    item_row(99050, "Fireproof Bracer", 57, 9, fire_res=15, required_level=52),
]
DROPS = [
    drop(EMBERPLATE_ARMGUARDS, 9017, 230, 80, name="Lord Incendius"),
    drop(102, 10508, 289, 20, name="Ras Frostwhisper"),
    drop(99050, 9018, 230, 80, name="High Interrogator Gerstahn"),
]


def family():
    rows = [
        {
            "name": n,
            "class_id": c,
            "level": 60,
            "race": 1,
            "map_id": EASTERN_KINGDOMS,
            "lead": int(n == "Grug"),
            "spec_tab": t,
        }
        for n, (c, t) in CLASSES.items()
    ]
    worn = [
        dict(item_row(3, "Mystic's Robe", 23, 20, sub=1), member="Ugga", slot=4),
    ]
    return preraid.members(rows, worn, TEXTS)


def catalog():
    return preraid.catalog(DROPS, ANCHORS, [], ITEMS, TEXTS)


def facts(upgrades):
    return campaignplan.Facts(
        family="Grug",
        level_rows=tuple(
            {
                "name": n,
                "level": 60,
                "race": 1,
                "map_id": EASTERN_KINGDOMS,
                "lead": int(i == 0),
            }
            for i, n in enumerate(CLASSES)
        ),
        done={},
        failed={},
        upgrades=upgrades,
        keys=frozenset(e for e, _n, _w in campaignplan.DOOR_KEYS.values()),
    )


class ThePlannerAimsAtAFirePiece(unittest.TestCase):
    def setUp(self):
        self.found = catalog()
        self.plans = [preraid.plan(m, self.found) for m in family()]
        self.gains = preraid.run_gains(self.plans)

    def test_the_item_read_carries_fire_resistance(self):
        self.assertIn("it.fire_res", preraid.ITEMS_SQL)
        self.assertEqual(self.found[EMBERPLATE_ARMGUARDS].fire, 10)

    def test_only_a_tank_plans_fire_pieces(self):
        by = {p.member.name: p for p in self.plans}
        self.assertEqual(
            [u.item.entry for u in by["Grug"].fire], [EMBERPLATE_ARMGUARDS]
        )
        self.assertEqual(by["Ugga"].fire, ())

    def test_a_run_that_drops_a_planned_piece_is_worth_it(self):
        grug = next(g for g in self.gains["blackrock-depths"] if g.name == "Grug")
        self.assertAlmostEqual(grug.fire, 0.8 * 10)
        self.assertAlmostEqual(grug.levels, 0.8 * 10 * preraid.FIRE_LEVELS_PER_POINT)
        self.assertIn("Emberplate Armguards for wrists", grug.fire_best)
        self.assertIn("fire resistance Emberplate Armguards", grug.line)

    def test_a_tank_at_the_target_plans_no_fire(self):
        tank = next(m for m in family() if m.name == "Grug")
        cape = preraid.Item(
            1, "Fire Wall", 60, 3, 16, 4, 1, -1, 50, (), fire=preraid.FIRE_TARGET
        )
        dressed = preraid.Member(
            tank.name, tank.class_id, tank.level, tank.tree, {14: cape}, tank.race
        )
        self.assertEqual(preraid.fire_upgrades(dressed, self.found), ())

    def test_without_the_fire_piece_the_robe_wins(self):
        # The control: the same family and loot, the tank's fire plan unread.
        plans = [preraid.replace(p, fire=()) for p in self.plans]
        pick = campaignplan.heuristic(
            campaignplan.options(facts(preraid.run_gains(plans)))
        )
        self.assertEqual(pick.keyword, "scholomance")

    def test_the_planner_prefers_the_dungeon_with_the_fire_piece(self):
        opts = campaignplan.options(facts(self.gains))
        pick = campaignplan.heuristic(opts)
        self.assertEqual(pick.keyword, "blackrock-depths")
        said = campaignplan.planned_line(pick, "the queue ran dry", "the heuristic")
        self.assertIn("fire resistance: Emberplate Armguards for wrists", said)
        self.assertIn("for Grug", said)
        self.assertIn("Emberplate Armguards", campaignplan.heuristic_why(pick))


# THE LEVELLING HALF (#759 box 2). Blackrock Depths' band starts at 52, eight
# levels before the cap, and its fire pieces want level 52 to 58. A family
# levelling through that band runs the dungeon it outgrows soonest; at 54 that
# is the Sunken Temple. A planned fire piece for a family tank now pulls the
# run to the dungeon that drops it, and the queued line names the piece.
LEVELLING = 54


def levelling_family(level=LEVELLING):
    return [preraid.replace(m, level=level) for m in family()]


def levelling_facts(upgrades, level=LEVELLING):
    return preraid.replace(
        facts(upgrades),
        level_rows=tuple(dict(r, level=level) for r in facts(None).level_rows),
    )


class TheLevellingPlannerAimsAtAFirePiece(unittest.TestCase):
    def setUp(self):
        self.found = catalog()
        self.plans = [preraid.fire_plan(m, self.found) for m in levelling_family()]
        self.gains = preraid.run_gains(self.plans)

    def test_a_fire_plan_counts_only_the_tanks_fire_pieces(self):
        by = {p.member.name: p for p in self.plans}
        self.assertEqual(by["Grug"].upgrades, ())
        self.assertEqual(
            [u.item.entry for u in by["Grug"].fire], [EMBERPLATE_ARMGUARDS]
        )
        self.assertEqual(by["Ugga"].fire, ())
        self.assertEqual(by["Ugga"].upgrades, ())

    def test_a_piece_above_the_tanks_level_is_not_planned_yet(self):
        plans = [preraid.fire_plan(m, self.found) for m in levelling_family(51)]
        self.assertEqual([p.fire for p in plans], [(), ()])

    def test_without_the_fire_piece_the_soonest_outgrown_wins(self):
        # The control: the same family, the fire plan unread.
        pick = campaignplan.heuristic(campaignplan.options(levelling_facts(None)))
        self.assertEqual(pick.keyword, "sunken-temple")

    def test_the_levelling_planner_prefers_the_dungeon_with_the_fire_piece(self):
        pick = campaignplan.heuristic(campaignplan.options(levelling_facts(self.gains)))
        self.assertEqual(pick.keyword, "blackrock-depths")
        said = campaignplan.planned_line(pick, "the queue ran dry", "the heuristic")
        self.assertIn("fire resistance: Emberplate Armguards for wrists", said)
        self.assertIn("for Grug", said)
        self.assertIn("Emberplate Armguards", campaignplan.heuristic_why(pick))

    def test_a_levelling_run_claims_no_expected_item_levels(self):
        # Below the cap the spec gear is not read, so a run's worth in item
        # levels is unknown; only the fire piece is said.
        opts = campaignplan.options(levelling_facts(self.gains))
        depths = next(o for o in opts if o.keyword == "blackrock-depths")
        self.assertIsNone(depths.expected)
        said = campaignplan.planned_line(depths, "the queue ran dry", "the heuristic")
        self.assertNotIn("expected item levels", said)


class _Rows:
    """preraid's member and worn reads, by the label _planner_rows is given."""

    def __init__(self, level):
        self.level = level

    def __call__(self, cur, sql, args, label):
        if sql.startswith(preraid.MEMBERS_SQL.split("{")[0]):
            return [
                {
                    "name": n,
                    "class_id": c,
                    "level": self.level,
                    "race": 1,
                    "map_id": EASTERN_KINGDOMS,
                    "lead": int(n == "Grug"),
                    "spec_tab": t,
                }
                for n, (c, t) in CLASSES.items()
            ]
        if sql.startswith(preraid.WORN_SQL.split("{")[0]):
            return []
        return []


class TheBridgeReadsFireBelowTheCap(unittest.TestCase):
    def preraid_for(self, level):
        connects = []

        @contextlib.contextmanager
        def connect():
            connects.append(1)
            yield _Conn()

        ns = _load(
            ["_planner_preraid"],
            {
                "campaignplan": campaignplan,
                "preraid": preraid,
                "_connect": connect,
                "_planner_catalog": lambda cur: catalog(),
                "_planner_rows": _Rows(level),
            },
        )
        rows = [{"name": n, "level": level} for n in CLASSES]
        return ns["_planner_preraid"](list(CLASSES), rows), connects

    def test_a_family_in_the_depths_band_reads_its_tanks_fire_pieces(self):
        (upgrades, progress), _c = self.preraid_for(LEVELLING)
        self.assertIsNotNone(upgrades)
        grug = next(g for g in upgrades["blackrock-depths"] if g.name == "Grug")
        self.assertIn("Emberplate Armguards for wrists", grug.fire_best)
        self.assertEqual(grug.upgrades, 0)
        self.assertIsNone(progress)

    def test_below_the_band_nothing_is_read(self):
        result, connects = self.preraid_for(preraid.FIRE_FLOOR - 1)
        self.assertEqual(result, (None, None))
        self.assertEqual(connects, [])


class _Conn:
    def cursor(self):
        return contextlib.nullcontext(None)


if __name__ == "__main__":
    unittest.main()
