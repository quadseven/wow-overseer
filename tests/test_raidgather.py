"""A raid night's gathering: how each seated raider reaches Blackrock Mountain.

What these pin (#762):

  1. THE ORDER NAMES EVERY RAIDER'S WAY. Each seated raider not already at the
     mountain is said as walking in behind the head or summoned at the
     Blackrock Mountain meeting stone, in one bridge log line.
  2. THE RAID SUMMONS ITSELF. The core summons only within the summoner's
     raid, so the summoner and the second clicker are seated raiders standing
     at the stone, and the raider brought is in the head's group.
  3. THE STONE IS A RAID NIGHT'S DOOR. The family's on-call summoner holds the
     Blackrock Mountain stone when the campaign door is Molten Core.
  4. THE NIGHT IS TIMED. Each change in who is inside is logged with the
     minutes since the order.
"""

import ast
import contextlib
import pathlib
import types
import unittest

import guildjobs
import raidrun

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

DOOR = guildjobs.entrances()[str(raidrun.MOLTEN_CORE_MAP)]
STONE = guildjobs.Spot(
    "gameobject", 4001, 0, DOOR["x"] + 30.0, DOOR["y"] - 20.0, "Meeting Stone"
)
WARLOCK, ORC = 9, 2


def at(map_id, x, y):
    return {"map_id": map_id, "pos_x": x, "pos_y": y}


def by_the_stone(dx=0.0):
    return at(0, STONE.x + dx, STONE.y)


def in_the_mountain(dy=0.0):
    return at(0, DOOR["x"] - 100.0, DOOR["y"] + dy)


class EachRaiderHasAWay(unittest.TestCase):
    def test_inside_the_mountain_it_is_already_there(self):
        self.assertEqual(raidrun.AT_MOUNTAIN, raidrun.arrival(in_the_mountain(), DOOR))

    def test_near_the_mountain_on_its_continent_it_walks(self):
        near = at(0, DOOR["x"] + 900.0, DOOR["y"])
        self.assertEqual(raidrun.WALK, raidrun.arrival(near, DOOR))

    def test_across_the_sea_it_is_summoned(self):
        kalimdor = at(1, DOOR["x"], DOOR["y"])
        self.assertEqual(raidrun.SUMMON, raidrun.arrival(kalimdor, DOOR))
        self.assertEqual(
            raidrun.SUMMON, raidrun.arrival(at(530, 9000.0, -7000.0), DOOR)
        )

    def test_far_off_on_its_own_continent_it_is_summoned(self):
        far = at(0, -9000.0, 100.0)
        self.assertEqual(raidrun.SUMMON, raidrun.arrival(far, DOOR))

    def test_a_raider_the_snapshot_does_not_show_is_said_so(self):
        self.assertEqual(raidrun.UNSEEN, raidrun.arrival(None, DOOR))

    def test_the_order_line_names_how_each_raider_not_there_arrives(self):
        positions = {
            "Head": in_the_mountain(),
            "Walker": at(0, DOOR["x"] + 900.0, DOOR["y"]),
            "Sailor": at(1, 100.0, 100.0),
            "Elf": at(530, 9000.0, -7000.0),
        }
        names = ["Head", "Walker", "Sailor", "Elf", "Gone"]
        line = raidrun.order_line(
            "Cave", "moltencore", raidrun.arrivals(names, positions, DOOR)
        )
        self.assertTrue(line.startswith("raid order: Cave into Molten Core, 5 seated"))
        self.assertIn("1 at Blackrock Mountain", line)
        self.assertIn("walk in behind the head 1: Walker", line)
        self.assertIn(
            "summoned at the Blackrock Mountain meeting stone 2: Elf, Sailor", line
        )
        self.assertIn("not in the world 1: Gone", line)
        self.assertNotIn("Head", line)


class TheRaidSummonsItself(unittest.TestCase):
    def gather(self, positions, in_raid=None, **kw):
        names = sorted(positions)
        ways = raidrun.arrivals(names, positions, DOOR)
        in_raid = set(names) if in_raid is None else in_raid
        return raidrun.gather(ways, positions, in_raid, DOOR, STONE, **kw)

    def test_two_raiders_at_the_stone_summon_one_from_across_the_sea(self):
        step = self.gather(
            {"Ann": by_the_stone(), "Bea": by_the_stone(2.0), "Kal": at(1, 0.0, 0.0)}
        )
        self.assertEqual(raidrun.Summon("Ann", "Kal", "Bea"), step.summon)
        self.assertEqual("use Kal", step.summon.command)
        self.assertEqual((), step.walks)

    def test_without_clickers_two_raiders_at_the_mountain_walk_to_the_stone(self):
        step = self.gather(
            {
                "Head": in_the_mountain(),
                "Near": in_the_mountain(5.0),
                "Far": in_the_mountain(150.0),
                "Kal": at(1, 0.0, 0.0),
            },
            keep={"Head"},
        )
        self.assertIsNone(step.summon)
        self.assertEqual(("Near", "Far"), step.walks)

    def test_a_raider_already_walking_there_is_not_walked_again(self):
        open_rows = [{"kind": "job", "target_name": "Near", "status": "claimed"}]
        step = self.gather(
            {
                "Near": in_the_mountain(5.0),
                "Far": in_the_mountain(150.0),
                "Kal": at(1, 0.0, 0.0),
            },
            open_rows=open_rows,
        )
        self.assertEqual(("Far",), step.walks)

    def test_one_summon_at_a_time(self):
        open_rows = [
            {
                "kind": "summon",
                "target_name": "Ann",
                "command": "use Kal",
                "target_arg": "Bea",
            }
        ]
        step = self.gather(
            {
                "Ann": by_the_stone(),
                "Bea": by_the_stone(2.0),
                "Kal": at(1, 0.0, 0.0),
                "Elf": at(530, 0.0, 0.0),
            },
            open_rows=open_rows,
        )
        self.assertIsNone(step.summon)
        self.assertEqual("a summon is under way", step.why)

    def test_a_raider_outside_the_heads_group_is_not_summoned(self):
        step = self.gather(
            {"Ann": by_the_stone(), "Bea": by_the_stone(2.0), "Kal": at(1, 0.0, 0.0)},
            in_raid={"Ann", "Bea"},
        )
        self.assertIsNone(step.summon)
        self.assertEqual("nobody in the raid waits on a summon", step.why)

    def test_a_summon_that_did_not_bring_its_raider_moves_to_the_next(self):
        rows = [
            {"kind": "summon", "command": "use Elf", "status": "unchanged"},
            {"kind": "summon", "command": "use Old", "status": "applied"},
        ]
        self.assertEqual({"Elf"}, raidrun.tried(rows))
        step = self.gather(
            {
                "Ann": by_the_stone(),
                "Bea": by_the_stone(2.0),
                "Elf": at(530, 0.0, 0.0),
                "Kal": at(1, 0.0, 0.0),
            },
            tried=raidrun.tried(rows),
        )
        self.assertEqual("Kal", step.summon.target)

    def test_a_clicker_beyond_the_modules_walk_is_not_at_the_stone(self):
        self.assertTrue(raidrun.at_stone(by_the_stone(raidrun.STONE_REACH - 1), STONE))
        self.assertFalse(raidrun.at_stone(by_the_stone(raidrun.STONE_REACH + 1), STONE))
        self.assertFalse(raidrun.at_stone(at(1, STONE.x, STONE.y), STONE))

    def test_without_a_stone_nothing_is_written(self):
        positions = {"Ann": by_the_stone(), "Kal": at(1, 0.0, 0.0)}
        ways = raidrun.arrivals(sorted(positions), positions, DOOR)
        step = raidrun.gather(ways, positions, set(positions), DOOR, None)
        self.assertEqual(
            raidrun.Gathering(why="no meeting stone stands near the door"), step
        )


class TheNightIsTimed(unittest.TestCase):
    def test_all_inside_says_the_minutes_since_the_order(self):
        positions = {"A": at(409, 0.0, 0.0), "B": at(409, 1.0, 1.0)}
        count = raidrun.inside(["A", "B"], positions)
        self.assertEqual(
            "raid gather: Cave: all 2 inside Molten Core, 37 minute(s) after the order",
            raidrun.gathered_line("Cave", "moltencore", count, 2, 37 * 60 + 5),
        )

    def test_part_inside_says_how_many(self):
        line = raidrun.gathered_line("Cave", "moltencore", 31, 40, 600)
        self.assertIn("31 of 40 inside Molten Core, 10 minute(s)", line)


class TheStoneIsARaidNightsDoor(unittest.TestCase):
    def warlock(self, name, level):
        return guildjobs.Member(
            name=name,
            guild="Cave",
            role=guildjobs.SUMMONER,
            level=level,
            class_id=WARLOCK,
            race=ORC,
            online=True,
            map_id=0,
            x=-7000.0,
            y=-900.0,
            money=0,
            eligible=True,
            known=frozenset({guildjobs.RITUAL_OF_SUMMONING}),
        )

    def test_the_on_call_summoner_holds_the_blackrock_mountain_stone(self):
        crew = [self.warlock("Lock", 55), self.warlock("Low", 30)]
        doors = guildjobs.assign_doors(
            crew, guildjobs.entrances(), (STONE,), "moltencore"
        )
        self.assertEqual("moltencore", doors["Lock"].keyword)
        self.assertTrue(doors["Lock"].on_call)
        self.assertEqual(STONE, doors["Lock"].stone)
        self.assertEqual("Blackrock Mountain", doors["Lock"].place)
        self.assertNotIn("Low", {n for n, d in doors.items() if d.on_call})

    def test_a_raid_is_still_no_dungeon_band(self):
        lock = self.warlock("Lock", 55)
        self.assertNotIn("moltencore", {r.keyword for r in guildjobs.doors_for(lock)})
        self.assertEqual(
            ["moltencore"],
            [d.keyword for d in guildjobs.campaign_doors_for(lock, "moltencore")],
        )


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(BRIDGE, node)
    raise AssertionError("no %s in bridge.py" % name)


def _load_gather_pass(answers, writes):
    """bridge._raid_gather_pass, run for real against a cursor that answers
    each read in turn and records each write."""
    source = "\n\n".join(
        _function(n)
        for n in (
            "_raid_positions",
            "_raid_door",
            "_raid_gather_reads",
            "_raid_gather_write",
            "_raid_gather_pass",
        )
    )
    queue = list(answers)

    class Cursor:
        def execute(self, sql, args=()):
            if sql.startswith("INSERT"):
                writes.append((sql, args))

        def fetchall(self):
            return queue.pop(0)

        def fetchone(self):
            return queue.pop(0)

    class Conn:
        def cursor(self):
            return contextlib.nullcontext(Cursor())

    namespace = {"__name__": "bridge_slice"}
    for name in (
        "_RAID_SEATED_SQL",
        "_RAID_POSITIONS_SQL",
        "_RAID_GROUP_SQL",
        "_RAID_GATHER_ROWS_SQL",
        "_RAID_ORDERED_SQL",
        "RAID_GATHER_WINDOW_MINUTES",
    ):
        namespace[name] = name
    namespace["_RAID_POSITIONS_SQL"] = "{holes}"
    namespace.update(
        raidrun=raidrun,
        guildjobs=guildjobs,
        campaignqueue=types.SimpleNamespace(_family=lambda f: f),
        v2_presence=types.SimpleNamespace(FRESH_SECONDS=60),
        _connect=lambda: contextlib.nullcontext(Conn()),
        _JOB_STONES=[
            {
                "guid": STONE.spawn,
                "map_id": 0,
                "x": STONE.x,
                "y": STONE.y,
                "name": "Meeting Stone",
            }
        ],
        _job_read=lambda *a: [],
        _JOB_STONES_SQL="",
        MEETING_STONE_GO_TYPE=23,
    )
    exec(compile(source, str(BRIDGE), "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace["_raid_gather_pass"]


class TheBridgeWritesTheSummon(unittest.TestCase):
    def test_a_summon_row_is_the_modules_stone_verb(self):
        seated = [{"name": n} for n in ("Ann", "Bea", "Kal")]
        snapshot = [
            dict(by_the_stone(), name="Ann"),
            dict(by_the_stone(2.0), name="Bea"),
            dict(at(1, 0.0, 0.0), name="Kal"),
        ]
        answers = [seated, seated, [], {"seconds": 1200}, snapshot]
        writes = []
        run = _load_gather_pass(answers, writes)
        written, why, count, line = run("Cave", "moltencore", 7, "Ann", ["Ann"])
        self.assertEqual(1, len(writes))
        sql, args = writes[0]
        self.assertIn("'summon'", sql)
        self.assertEqual(("Ann", "use Kal", "Bea", "raidgather:summon:Kal"), args)
        self.assertEqual(
            ["Ann summons Kal at the Blackrock Mountain meeting stone, Bea clicking"],
            written,
        )
        self.assertEqual(0, count)
        self.assertIn("0 of 3 inside Molten Core, 20 minute(s) after the order", line)

    def test_a_raid_order_logs_its_arrivals_after_the_seats(self):
        body = _function("_drive_raid")
        self.assertIn("_log_raid_order(family, keyword, [s[2] for s in seats])", body)
        self.assertLess(body.index("_insert_job("), body.index("_log_raid_order("))

    def test_an_active_raid_gathers_on_each_queue_pass(self):
        body = BRIDGE.split("async def _campaign_queue_family_once", 1)[1]
        body = body.split("\n    async def ", 1)[0]
        self.assertIn('getattr(self, "_raid_gather", None)', body)

    def test_the_campaign_door_of_a_raid_night_is_the_raid(self):
        body = _function("_guild_campaign_door")
        self.assertIn("jobs.is_raid_job(job)", body)


if __name__ == "__main__":
    unittest.main()
