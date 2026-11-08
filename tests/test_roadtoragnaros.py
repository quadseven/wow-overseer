"""The road to Ragnaros: the pure module and its /api/v2 route."""

import os
import sys
import types
import unittest

from _stub_modules import PYMYSQL, stub_modules

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
with stub_modules(pymysql=PYMYSQL):
    import apiv2
    import raidteams
    import roadtoragnaros as road


def _teams(
    level=60,
    open_names=(),
    attuned=True,
    fire=500,
    carried=None,
    unread=(),
    quests=True,
):
    """A raidteams payload for Cave: every seat filled unless named open."""
    seats, members = [], {}
    for group in raidteams.GROUPS["Cave"]:
        row = []
        for s in group:
            opened = s.name in open_names
            row.append(
                {
                    "name": None if opened else s.name,
                    "approved": s.name,
                    "seat": s.seat,
                    "class_id": s.class_id,
                }
            )
            if not opened:
                members[s.name] = {
                    "level": None if s.name in unread else level,
                    "attuned": attuned,
                    "fire_resistance": fire,
                    "consumables": {} if carried is None else carried,
                    "class_quests": quests,
                }
        seats.append(row)
    return {"seats": seats, "members": members}


def _by_key(payload):
    return {m["key"]: m for m in payload["milestones"]}


def _dungeon_runs(*keywords):
    """Cleared runs that covered every boss, one per keyword."""
    return [
        {"keyword": k, "outcome": "cleared", "bosses_done": 3, "bosses_total": 3}
        for k in keywords
    ]


def _coverage():
    """Every Cave summoner with the ritual and every repair hand with engineering."""
    rows = [
        {"name": n, "role": "summoner", "level": 60, "summon": True, "engineering": 0}
        for n, _old in raidteams.SUMMONERS["Cave"]
    ]
    rows += [
        {
            "name": n,
            "role": "maintenance",
            "level": 60,
            "summon": False,
            "engineering": 150,
        }
        for n, _old in raidteams.MAINTENANCE["Cave"]
    ]
    return rows


class TheMilestones(unittest.TestCase):
    def test_eight_milestones_in_order(self):
        out = road.build("Cave", _teams(), None, [])
        self.assertEqual([m["key"] for m in out["milestones"]], list("ABCDEFGH"))

    def test_a_dungeon_and_repair_milestone_are_not_measured_with_a_reason(self):
        out = _by_key(road.build("Cave", _teams(), None, []))
        for key in "DG":
            self.assertFalse(out[key]["measured"])
            self.assertIsNone(out[key]["percent"])
            self.assertTrue(out[key]["reason"])

    def test_d_reads_cleared_dungeons_from_the_run_table_and_the_ladder(self):
        runs = _dungeon_runs("ragefire", "wailing", "deadmines")
        out = _by_key(road.build("Cave", _teams(), None, [], dungeons=runs))
        # Cave is Alliance: its ladder has no Ragefire Chasm door, so
        # only the two Alliance doors among these count.
        self.assertTrue(out["D"]["measured"])
        self.assertEqual(out["D"]["unit"], "dungeons")
        self.assertEqual(out["D"]["have"], 2)
        names = [n for b in out["D"]["blockers"] for n in b["names"]]
        self.assertNotIn("Wailing Caverns", names)
        self.assertNotIn("The Deadmines", names)

    def test_d_counts_only_a_clear_that_felled_every_boss(self):
        runs = [
            {
                "keyword": "wailing",
                "outcome": "cleared",
                "bosses_done": 1,
                "bosses_total": 3,
            },
            {
                "keyword": "deadmines",
                "outcome": "wiped",
                "bosses_done": 3,
                "bosses_total": 3,
            },
        ]
        out = _by_key(road.build("Cave", _teams(), None, [], dungeons=runs))
        self.assertEqual(out["D"]["have"], 0)

    def test_g_reads_summoner_and_maintenance_coverage_and_names_the_missing(self):
        cov = _coverage()
        cov[0]["summon"] = False
        cov[-1]["engineering"] = 0
        before = raidteams.SUMMONERS["Cave"][0][0]
        out = _by_key(road.build("Cave", _teams(), None, [], coverage=cov))
        self.assertTrue(out["G"]["measured"])
        self.assertEqual(out["G"]["want"], 31)
        self.assertEqual(out["G"]["have"], 29)
        names = [n for b in out["G"]["blockers"] for n in b["names"]]
        self.assertIn(before, names)
        keys = {b["key"] for b in out["G"]["blockers"]}
        self.assertIn("no-summon", keys)
        self.assertIn("no-repair", keys)

    def test_b_counts_a_seat_only_when_its_class_quests_are_rewarded(self):
        out = _by_key(road.build("Cave", _teams(level=45, quests=True), None, []))
        self.assertEqual(out["B"]["have"], 40)
        out = _by_key(road.build("Cave", _teams(level=45, quests=False), None, []))
        self.assertEqual(out["B"]["have"], 0)
        keys = {b["key"]: b for b in out["B"]["blockers"]}
        self.assertIn("class-quest", keys)
        self.assertEqual(keys["class-quest"]["seats_short"], 40)

    def test_b_an_unread_class_quest_is_neither_passed_nor_short(self):
        out = _by_key(road.build("Cave", _teams(level=45, quests=None), None, []))
        self.assertEqual(out["B"]["unread"], 40)
        self.assertEqual(out["B"]["have"], 0)
        self.assertEqual(out["B"]["seats_short"], 0)

    def test_an_open_seat_stays_open_and_fails_every_seat_milestone(self):
        opened = raidteams.seats("Cave")[3].name
        out = _by_key(road.build("Cave", _teams(open_names=(opened,)), None, []))
        for key in "ABCE":
            self.assertEqual(out[key]["have"], 39)
            self.assertEqual(out[key]["seats_short"], 1 if key in "ABCE" else 0)
        names = [n for b in out["A"]["blockers"] for n in b["names"]]
        self.assertIn(opened, names)

    def test_levels_are_counted_per_checkpoint(self):
        out = _by_key(road.build("Cave", _teams(level=45), None, []))
        self.assertEqual(out["A"]["have"], 40)
        self.assertEqual(out["B"]["have"], 40)
        self.assertEqual(out["C"]["have"], 0)
        self.assertEqual(out["C"]["blockers"][0]["seats_short"], 40)

    def test_an_unread_level_is_neither_passed_nor_short(self):
        unread = tuple(s.name for s in raidteams.seats("Cave")[:4])
        out = _by_key(road.build("Cave", _teams(level=30, unread=unread), None, []))
        self.assertEqual(out["A"]["unread"], 4)
        self.assertEqual(out["A"]["have"], 36)
        self.assertEqual(out["A"]["seats_short"], 0)
        self.assertEqual(out["A"]["percent"], 100)
        self.assertEqual(out["C"]["seats_short"], 36)

    def test_no_seat_read_leaves_every_milestone_unmeasured(self):
        out = road.build("Cave", None, None, None)
        self.assertTrue(all(not m["measured"] for m in out["milestones"]))
        self.assertIsNone(out["total"]["percent"])

    def test_fire_resistance_and_supplies_are_blockers_with_seat_counts(self):
        out = _by_key(road.build("Cave", _teams(fire=0, carried={}), None, []))
        keys = {b["key"]: b for b in out["F"]["blockers"]}
        self.assertIn("fire-resistance", keys)
        self.assertIn("supplies", keys)
        self.assertGreater(keys["supplies"]["seats_short"], 0)


class TheTotal(unittest.TestCase):
    def test_the_total_is_the_mean_of_measured_seat_milestones_only(self):
        out = road.build(
            "Cave",
            _teams(level=45, attuned=False),
            None,
            [],
            dungeons=_dungeon_runs(),
            coverage=_coverage(),
        )
        # A 100, B 100, C 0, E 0, F is read as short on supplies (0).
        # D and G are measured in dungeons and people, not seats, so
        # they stay out of the seat mean without being left out.
        self.assertEqual(out["total"]["counted"], list("ABCEF"))
        self.assertEqual(out["total"]["left_out"], [])
        self.assertEqual(out["total"]["percent"], 40)
        self.assertNotIn("D, G", out["total"]["how"])

    def test_a_guild_with_no_runs_has_a_measured_zero_attempt_count(self):
        out = road.build("Cave", _teams(), None, [])
        self.assertEqual(out["attempts"]["entered"], 0)
        self.assertTrue(out["attempts"]["measured"])
        self.assertIsNone(out["attempts"]["best"])
        self.assertEqual(_by_key(out)["H"]["have"], 0)

    def test_an_unreadable_run_table_is_not_a_zero(self):
        out = road.build("Cave", _teams(), None, None)
        self.assertFalse(out["attempts"]["measured"])
        self.assertIsNone(_by_key(out)["H"]["have"])

    def test_attempts_count_wipes_and_the_best_boss_count(self):
        runs = [
            {"outcome": "wiped", "bosses_done": 2, "bosses_total": 10},
            {"outcome": "wiped", "bosses_done": 4, "bosses_total": 10},
            {"outcome": "refused", "bosses_done": 0, "bosses_total": 10},
        ]
        out = road.build("Cave", _teams(), None, runs)["attempts"]
        self.assertEqual(out["formed"], 3)
        self.assertEqual(out["entered"], 2)
        self.assertEqual(out["wiped"], 2)
        self.assertEqual(out["best"], {"bosses_done": 4, "bosses_total": 10})
        self.assertFalse(out["killed"])

    def test_blockers_are_sorted_by_seats_short(self):
        out = road.build("Cave", _teams(level=10), None, [])
        shorts = [b["seats_short"] for b in out["blockers"]]
        self.assertEqual(shorts, sorted(shorts, reverse=True))


class TheRoute(unittest.TestCase):
    def test_the_route_is_registered_under_v2(self):
        self.assertIn("/api/v2/ragnaros", apiv2.ROUTES)

    def test_a_missing_guild_is_a_400(self):
        code, body = apiv2.ROUTES["/api/v2/ragnaros"]({}, types.SimpleNamespace())
        self.assertEqual(code, 400)


class TheRaidView(unittest.TestCase):
    HERE = os.path.join(os.path.dirname(__file__), "..")

    def _read(self, rel):
        with open(os.path.join(self.HERE, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_the_raid_view_reads_the_road_and_draws_it_first(self):
        js = self._read("app/views/raid.js")
        self.assertIn("/api/v2/ragnaros?guild=", js)
        self.assertLess(js.index("${roadCard("), js.index("${headCard(card)}"))

    def test_an_unmeasured_milestone_is_drawn_not_measured_never_zero(self):
        js = self._read("app/views/raid.js")
        body = js[js.index("function roadRow") : js.index("function roadBlocker")]
        self.assertIn("if (!m.measured)", body)
        self.assertIn("notMeasured()", body)

    def test_the_dockerfile_ships_the_module(self):
        self.assertIn("roadtoragnaros.py", self._read("Dockerfile"))


if __name__ == "__main__":
    unittest.main()
