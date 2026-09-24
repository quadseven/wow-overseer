"""The movement picture any Jev kind can carry (situation.py) and the head's
screen read by a vision model (vision.py).

The families and places here are the dev realm's as read on 2026-09-23: the
Alliance five in Tanaris with one member far below in Un'Goro Crater, and the
Horde five in Orgrimmar on their way to Ragefire Chasm. Every test runs on
fake rows, a fake clock and fake transports; none touches a database, the
model gateway or the Jev API.
"""

import asyncio
import json
import pathlib
import unittest

from test_campaign_queue import _load  # noqa: F401 - sets up the pymysql stub
from test_jev_items import FakeJev

import campaignplan  # noqa: E402
import jev  # noqa: E402
import jev_activity as ja  # noqa: E402
import jev_choices  # noqa: E402
import situation as sit  # noqa: E402
import townslot  # noqa: E402
import vision  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

TANARIS, UNGORO, ORGRIMMAR = 440, 490, 1637
ALLIANCE = ("Grug", "Ugga", "Grog", "Bork", "Og")


def snap(name, x, y, z, zone=TANARIS, map_id=1, health=100, max_health=100, **kw):
    return dict(
        name=name,
        map_id=map_id,
        zone_id=zone,
        pos_x=x,
        pos_y=y,
        pos_z=z,
        health=health,
        max_health=max_health,
        in_combat=kw.get("in_combat", 0),
        age=2,
    )


def together(bork=(-6912.0, -2874.0, 9.7, TANARIS)):
    bx, by, bz, bzone = bork
    return [
        snap("Grug", -6911.6, -2873.7, 9.7),
        snap("Ugga", -6911.1, -2874.7, 9.6),
        snap("Grog", -6909.5, -2874.0, 9.8),
        snap("Bork", bx, by, bz, zone=bzone),
        snap("Og", -6915.3, -2874.0, 9.5),
    ]


def trail_of(points, start=0.0, step=30.0, map_id=1):
    """Tracker samples, `step` seconds apart."""
    return [
        sit.Sample(start + i * step, sit.Point(map_id, x, y, z))
        for i, (x, y, z) in enumerate(points)
    ]


class Progress(unittest.TestCase):
    def test_too_short_a_trail_is_unknown_not_still(self):
        self.assertEqual(sit.UNKNOWN, sit.progress([]).verdict)
        short = trail_of([(0, 0, 0), (0, 0, 0)], step=10)
        self.assertEqual(sit.UNKNOWN, sit.progress(short).verdict)

    def test_standing_with_nowhere_to_be_is_still(self):
        t = trail_of([(0, 0, 0)] * 6)
        self.assertEqual(sit.STILL, sit.progress(t).verdict)

    def test_standing_with_a_goal_not_reached_is_stuck(self):
        t = trail_of([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 0), (1, 1, 0)])
        goal = sit.Point(1, 800, 0, 0)
        p = sit.progress(t, goal)
        self.assertEqual(sit.STUCK, p.verdict)
        self.assertLessEqual(abs(p.closing_yards), 2)

    def test_standing_at_the_goal_is_still_not_stuck(self):
        t = trail_of([(0, 0, 0)] * 5)
        self.assertEqual(sit.STILL, sit.progress(t, sit.Point(1, 5, 0, 0)).verdict)

    def test_walking_toward_the_goal_is_moving_and_closing(self):
        t = trail_of([(i * 100.0, 0, 0) for i in range(5)])
        p = sit.progress(t, sit.Point(1, 1000, 0, 0))
        self.assertEqual(sit.MOVING, p.verdict)
        self.assertEqual(400, p.closing_yards)
        self.assertEqual(400, p.moved_yards)

    def test_walking_back_and_forth_is_circling(self):
        t = trail_of([(0, 0, 0), (60, 0, 0), (0, 0, 0), (60, 0, 0), (0, 0, 0)])
        self.assertEqual(sit.CIRCLING, sit.progress(t).verdict)

    def test_a_taxi_is_flying_and_a_jump_is_a_teleport(self):
        flying = trail_of([(i * 900.0, 0, 0) for i in range(4)])
        self.assertEqual(sit.FLYING, sit.progress(flying).verdict)
        jump = trail_of([(0, 0, 0), (0, 0, 0), (5000, 0, 0)])
        self.assertEqual(sit.TELEPORTED, sit.progress(jump).verdict)
        zoned = trail_of([(0, 0, 0), (0, 0, 0)]) + [
            sit.Sample(90.0, sit.Point(389, 0, 0, 0))
        ]
        self.assertEqual(sit.TELEPORTED, sit.progress(zoned).verdict)


class TheTracker(unittest.TestCase):
    def test_it_keeps_a_bounded_window_and_ignores_unseen_members(self):
        tr = sit.Tracker(keep=120, cap=4)
        for t in range(0, 300, 30):
            tr.record("Grug", sit.Point(1, float(t), 0, 0), float(t))
        tr.record("Bork", None, 0.0)
        kept = tr.trail("Grug", 270.0, window=1e9)
        self.assertEqual(4, len(kept))
        self.assertGreaterEqual(kept[0].t, 150.0)
        self.assertEqual([], tr.trail("Bork", 270.0))


class TheGoal(unittest.TestCase):
    def test_an_at_aim_is_a_point_with_height(self):
        g = sit.goal_of("at:1:-6912.47,-2881.2,9.27", "quest")
        self.assertEqual(sit.Point(1, -6912.47, -2881.2, 9.27), g.at)

    def test_a_role_aim_has_no_point_and_says_so(self):
        g = sit.goal_of("vendor", "quest")
        self.assertIsNone(g.at)
        s = sit.Situation(leader="Grug", bodies=(), goal=g)
        self.assertIn("role", s.goal_state()["yards"])

    def test_a_dungeon_job_aims_at_its_door_and_the_column_wins(self):
        g = sit.goal_of("", "dungeon:ragefire")
        self.assertEqual(1, g.at.map)
        self.assertIsNone(g.at.z)
        self.assertEqual("vendor", sit.goal_of("vendor", "dungeon:ragefire").aim)

    def test_inside_the_dungeon_the_goal_is_reached_and_named(self):
        rows = [snap("Zug", -34.0, -24.9, -21.6, map_id=389, zone=2437)]
        s = sit.build(["Zug"], "Zug", rows, None, 0.0, leader_job="dungeon:ragefire")
        self.assertEqual(
            {"aim": "dungeon:ragefire", "inside_the_dungeon": True}, s.goal_state()
        )
        self.assertEqual("Ragefire Chasm", s.zone_name)
        self.assertIn("inside", s.line())

    def test_no_aim_and_no_dungeon_is_no_goal(self):
        self.assertIsNone(sit.goal_of("", "quest"))


class Cohesion(unittest.TestCase):
    def test_a_member_in_the_crater_is_far_and_below(self):
        bodies = sit.bodies_from_rows(
            ALLIANCE, together(bork=(-8182.8, -2090.9, -114.3, UNGORO))
        )
        c = sit.cohesion(bodies, "Grug")
        self.assertGreater(c["spread_yards"], 1400)
        self.assertEqual(1, len(c["far_from_leader"]))
        self.assertTrue(c["far_from_leader"][0].startswith("Bork "))
        self.assertIn("below", c["far_from_leader"][0])

    def test_a_close_family_names_nobody_far(self):
        c = sit.cohesion(sit.bodies_from_rows(ALLIANCE, together()), "Grug")
        self.assertNotIn("far_from_leader", c)
        self.assertLess(c["spread_yards"], 10)

    def test_a_member_with_no_snapshot_is_not_seen_not_at_the_origin(self):
        rows = [r for r in together() if r["name"] != "Og"]
        bodies = sit.bodies_from_rows(ALLIANCE, rows)
        self.assertIsNone(bodies[-1].at)
        self.assertEqual(["Og"], sit.cohesion(bodies, "Grug")["not_seen"])

    def test_another_map_is_far_without_a_distance(self):
        rows = together()
        rows[3] = snap("Bork", 0, 0, 0, map_id=389, zone=2437)
        far = sit.cohesion(sit.bodies_from_rows(ALLIANCE, rows), "Grug")
        self.assertIn("Bork on another map", far["far_from_leader"])


class Danger(unittest.TestCase):
    HERE = sit.Point(1, 0, 0, 0)

    def spawn(self, name, x, level, rank=0, enemy_group=1):
        return dict(
            name=name,
            minlevel=level,
            maxlevel=level + 1,
            rank=rank,
            enemy_group=enemy_group,
            x=x,
            y=0.0,
            z=0.0,
        )

    def test_hostile_elites_in_reach_are_counted_and_named_first(self):
        spawns = [
            self.spawn("Scorpid Dunestalker", 20, 46),
            self.spawn("Gorishi Hive Guard", 30, 52, rank=1),
            self.spawn("Far Devilsaur", 300, 54, rank=1),
        ]
        d = sit.danger(spawns, self.HERE, weakest_level=48, side=sit.ALLIANCE_MASK)
        self.assertEqual(2, d["hostile_spawns"])
        self.assertEqual(1, d["elites"])
        self.assertEqual(53, d["highest_level"])
        self.assertEqual(5, d["levels_above_weakest_member"])
        self.assertTrue(d["worst"][0].startswith("Gorishi Hive Guard (elite"))

    def test_a_friendly_or_other_side_only_spawn_is_not_danger(self):
        horde_guard = self.spawn("Orgrimmar Grunt", 10, 55, enemy_group=2)
        neutral = self.spawn("Tanaris Turtle", 10, 45, enemy_group=0)
        d = sit.danger([horde_guard, neutral], self.HERE, 20, sit.HORDE_MASK)
        self.assertEqual({"hostile_spawns": 0}, d)
        d = sit.danger([horde_guard], self.HERE, 20, sit.ALLIANCE_MASK)
        self.assertEqual(1, d["hostile_spawns"])

    def test_an_unread_template_is_not_counted_and_no_position_is_none(self):
        unread = self.spawn("Mystery", 10, 40, enemy_group=None)
        self.assertEqual({"hostile_spawns": 0}, sit.danger([unread], self.HERE, 40, 0))
        self.assertIsNone(sit.danger([unread], None, 40, 0))

    def test_side_mask_is_read_off_the_races(self):
        self.assertEqual(sit.ALLIANCE_MASK, sit.side_mask([1, 3, 7]))
        self.assertEqual(sit.HORDE_MASK, sit.side_mask([2, 8]))
        self.assertEqual(0, sit.side_mask([1, 2]))
        self.assertEqual(0, sit.side_mask([]))


class Deaths(unittest.TestCase):
    def test_killers_are_counted_and_the_latest_is_timed(self):
        rows = [
            dict(
                character_name="Bork",
                killer_type="creature",
                killer_name="Devilsaur",
                age=300,
            ),
            dict(
                character_name="Og",
                killer_type="creature",
                killer_name="Devilsaur",
                age=900,
            ),
            dict(
                character_name="Bork",
                killer_type="environment",
                killer_name="",
                age=1500,
            ),
        ]
        d = sit.deaths(rows)
        self.assertEqual(3, d["count"])
        self.assertEqual("Devilsaur x2", d["killers"][0])
        self.assertIn("environment", d["killers"])
        self.assertEqual(5, d["minutes_since_last"])
        self.assertEqual(["Bork", "Og"], d["who"])

    def test_unread_is_not_none_found(self):
        self.assertIsNone(sit.deaths(None))
        self.assertEqual({"count": 0}, sit.deaths([]))


class Route(unittest.TestCase):
    def test_a_node_across_a_cliff_is_not_reachable(self):
        # mod-overseer, on the dev realm: "cannot walk to survey node 3487
        # from where it stands (442 yards across, 193 up or down)".
        nodes = [dict(id=3487, name="Tanaris rim", x=442.0, y=0.0, z=193.0)]
        n = sit.nearest_node(nodes, sit.Point(1, 0, 0, 0))
        self.assertEqual(
            {"node": "Tanaris rim", "yards": 442, "height": 193, "reachable": False}, n
        )

    def test_a_near_level_node_is_reachable(self):
        nodes = [
            dict(id=1, name="Gadgetzan", x=40.0, y=30.0, z=5.0),
            dict(id=2, name="Far", x=500.0, y=0.0, z=0.0),
        ]
        n = sit.nearest_node(nodes, sit.Point(1, 0, 0, 0))
        self.assertEqual("Gadgetzan", n["node"])
        self.assertTrue(n["reachable"])

    def test_no_nodes_in_the_search_says_so(self):
        r = sit.route([], None, sit.Point(1, 0, 0, 0), None, None)
        self.assertIn("none", r["nearest_survey_node"])


class Travel(unittest.TestCase):
    def test_the_holder_campaign_and_columns_are_said(self):
        h = townslot.Holder("vendor pass", "Grug", "vendor", 0.0)
        t = sit.travel(h, "the campaign is staging", {"Grug": "vendor", "Og": ""})
        self.assertEqual("vendor pass", t["held_by"])
        self.assertEqual("the campaign is staging", t["campaign_owns_it"])
        self.assertEqual({"Grug": "vendor"}, t["columns"])

    def test_an_orphan_aim_and_an_empty_column(self):
        h = townslot.Holder("", "Grug", "at:1:0,0,0", 0.0)
        self.assertIn("did not write", sit.travel(h, "", {})["held_by"])
        self.assertEqual({"held_by": "nobody"}, sit.travel(None, "", {}))


def the_alliance_stuck(vision_state=None):
    """Grug aimed at a vendor point 800 yards off and not moving, Bork in the
    crater, two deaths to a Devilsaur."""
    tr = sit.Tracker()
    for i in range(8):
        for name, x in (("Grug", -6911.6), ("Bork", -8182.8)):
            tr.record(name, sit.Point(1, x + (i % 2), -2873.7, 9.7), i * 30.0)
    return sit.build(
        ALLIANCE,
        "Grug",
        together(bork=(-8182.8, -2090.9, -114.3, UNGORO)),
        tr,
        210.0,
        leader_travel="at:1:-7700.0,-2873.7,9.7",
        leader_job="quest",
        spawn_rows=[],
        death_rows=[
            dict(
                character_name="Bork",
                killer_type="creature",
                killer_name="Devilsaur",
                age=120,
            ),
            dict(
                character_name="Bork",
                killer_type="creature",
                killer_name="Devilsaur",
                age=700,
            ),
        ],
        leader_nodes=[
            dict(id=3066, name="Tanaris Sandsorrow Watch", x=-7145.7, y=-2948.9, z=10.3)
        ],
        goal_nodes=[],
        races=[1, 3, 4, 7, 11],
        weakest_level=60,
        holder=townslot.Holder("vendor pass", "Grug", "at:1:-7700.0,-2873.7,9.7", 0.0),
        columns={"Grug": "at:1:-7700.0,-2873.7,9.7"},
        vision=vision_state,
    )


class TheWholePicture(unittest.TestCase):
    def test_the_state_says_stuck_far_and_dying(self):
        s = the_alliance_stuck().state()
        self.assertEqual("Tanaris", s["zone"])
        self.assertEqual(788, s["goal"]["yards"])
        self.assertFalse(s["goal"]["arrived"])
        grug = next(m for m in s["members"] if m["name"] == "Grug")
        self.assertEqual(sit.STUCK, grug["movement"])
        bork = next(m for m in s["members"] if m["name"] == "Bork")
        self.assertEqual(sit.STILL, bork["movement"])
        self.assertTrue(s["cohesion"]["far_from_leader"][0].startswith("Bork"))
        self.assertEqual(2, s["deaths_last_30_min"]["count"])
        self.assertEqual({"hostile_spawns": 0}, s["danger_near_leader"])
        self.assertEqual("vendor pass", s["travel_column"]["held_by"])
        self.assertFalse(s["route"]["nearest_survey_node"]["reachable"])
        self.assertNotIn("leader_screen", s)

    def test_the_state_is_json_and_small(self):
        text = json.dumps(the_alliance_stuck().state())
        self.assertLess(len(text), 2000)

    def test_the_line_fits_its_column(self):
        line = the_alliance_stuck().line(120)
        self.assertLessEqual(len(line), 120)
        self.assertIn("leader stuck", the_alliance_stuck().line())

    def test_a_vision_reading_rides_along_when_there_is_one(self):
        seen = {"screen": "in_world", "dead": False, "seconds_old": 30}
        s = the_alliance_stuck(seen).state()
        self.assertEqual(seen, s["leader_screen"])

    def test_door_distance_from_the_leader(self):
        s = the_alliance_stuck()
        self.assertEqual(
            round(((-6911.6 + 6773.49) ** 2 + (-2873.7 + 2889.77) ** 2) ** 0.5),
            s.yards_to_door("zulfarrak"),
        )
        self.assertEqual("another continent", s.yards_to_door("deadmines"))
        self.assertEqual(sit.UNKNOWN, s.yards_to_door("nowhere"))

    def test_nothing_read_is_unknown_everywhere(self):
        s = sit.build(ALLIANCE, "Grug", [], None, 0.0).state()
        self.assertEqual(sit.UNKNOWN, s["danger_near_leader"])
        self.assertEqual(sit.UNKNOWN, s["deaths_last_30_min"])
        self.assertEqual(sit.UNKNOWN, s["cohesion"]["spread_yards"])
        self.assertEqual(False, s["leader_seen"])

    def test_the_switch(self):
        self.assertTrue(sit.enabled({}))
        self.assertFalse(sit.enabled({"SITUATION_MODE": "off"}))


class JevReadsIt(unittest.TestCase):
    """The activity and dungeon questions carry the picture when there is
    one, and are exactly as they were when there is not."""

    def activity_facts(self, where=None):
        members = tuple(ja.Member(name=n, level=60, free_slots=20) for n in ALLIANCE)
        return ja.Facts(
            family="Grug",
            members=members,
            job="dungeon:zulfarrak",
            queue="Zul'Farrak 2 of 10",
            situation=where,
        )

    def test_the_activity_state_carries_the_situation(self):
        fake = FakeJev()
        client = jev.Client("k", transport=fake)
        asyncio.run(
            ja.ask(client, self.activity_facts(the_alliance_stuck()), ja.policy({}))
        )
        req = fake.requests[0]
        self.assertEqual("Tanaris", req["state"]["situation"]["zone"])
        self.assertIn("`situation`", req["questions"]["activity"]["instructions"])

    def test_without_it_the_activity_question_is_unchanged(self):
        f = self.activity_facts()
        state, questions = ja.question(f, ja.options(f))
        self.assertNotIn("situation", state)
        self.assertNotIn("`situation`", questions["activity"]["instructions"])
        self.assertNotIn("situation", ja.facts_line(f))

    def test_the_activity_record_keeps_a_short_situation(self):
        line = ja.facts_line(self.activity_facts(the_alliance_stuck()))
        self.assertIn("| situation: zone Tanaris", line)
        self.assertLessEqual(len(line), 1000)

    def dungeon(self, where=None):
        f = campaignplan.Facts(
            family="Grug",
            level_rows=tuple(
                {"name": n, "level": 60, "race": 1, "map_id": 1, "lead": int(i == 0)}
                for i, n in enumerate(ALLIANCE)
            ),
            done={},
            failed={},
            quests=None,
        )
        opts = campaignplan.options(f)
        return f, opts

    def test_the_dungeon_state_says_how_far_each_door_is(self):
        f, opts = self.dungeon()
        self.assertGreaterEqual(len(opts), 2)
        state, q = jev_choices.dungeon_question(f, opts, the_alliance_stuck())
        for run in state["dungeons"]:
            self.assertIn("yards_from_the_leader_to_its_door", run)
        self.assertIn("situation", state)
        self.assertIn("another continent", q["dungeon"]["instructions"])

    def test_without_it_the_dungeon_question_is_unchanged(self):
        f, opts = self.dungeon()
        state, q = jev_choices.dungeon_question(f, opts)
        self.assertNotIn("situation", state)
        for run in state["dungeons"]:
            self.assertNotIn("yards_from_the_leader_to_its_door", run)

    def test_dungeon_ask_passes_it_through_to_the_record(self):
        f, opts = self.dungeon()
        fake = FakeJev()
        client = jev.Client("k", transport=fake)
        rule = jev_choices.policy(jev_choices.KIND_DUNGEON, {})
        j = asyncio.run(
            jev_choices.dungeon_ask(
                client,
                f,
                opts,
                opts[0],
                rule,
                "queue ran out",
                where=the_alliance_stuck(),
            )
        )
        self.assertIn("situation", fake.requests[0]["state"])
        self.assertIn("| situation:", j.facts)


class TheBridgeWiring(unittest.TestCase):
    """Source shape: the sampler runs in both loop lists, both kinds ask for
    the picture, and the rank column is quoted (a MySQL 8 reserved word)."""

    def test_the_sampler_is_a_loop_in_both_lists(self):
        self.assertEqual(2, BRIDGE.count("self._situation_loop,"))

    def test_both_kinds_carry_it(self):
        self.assertIn("situation=where)", BRIDGE)
        self.assertIn("due.reason, where=where)", BRIDGE)

    def test_run_recovery_reads_it_as_perception(self):
        self.assertIn("context.perception = where.state()", BRIDGE)

    def test_rank_is_quoted(self):
        self.assertIn("ct.`rank`", BRIDGE)
        self.assertNotIn("ct.rank,", BRIDGE)


# ---------------------------------------------------------------------------
# VISION


JPEG = b"\xff\xd8\xff" + b"0" * 64
GOOD = {
    "seen": "Four characters stand by a campfire at night.",
    "screen": "in_world",
    "dead": False,
    "fighting": False,
    "swimming": False,
    "window_open": False,
    "facing_obstacle": False,
}


class FakeWorld:
    """The map server's /api/frame and the gateway's /api/chat."""

    def __init__(self, age=5, has_frame=True, reply=None, where="thinking"):
        self.age = age
        self.has_frame = has_frame
        self.reply = GOOD if reply is None else reply
        self.where = where
        self.calls = []

    def __call__(self, url, body, timeout):
        self.calls.append(url)
        if "meta=1" in url:
            if self.age is None:
                return 404, b'{"error": "no frame yet"}'
            return 200, json.dumps(
                {"has_frame": self.has_frame, "captured_seconds_ago": self.age}
            ).encode()
        if "/api/frame" in url:
            return 200, JPEG
        request = json.loads(body)
        assert request["format"] == vision.SCHEMA
        assert request["messages"][0]["images"]
        text = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return 200, json.dumps(
            {"message": {"role": "assistant", "content": "", self.where: text}}
        ).encode()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def seer(world, clock=None, **kw):
    return vision.Seer(
        frame_url="http://map.example/api/frame",
        vision_url="http://gateway.example/api/chat",
        transport=world,
        clock=clock or Clock(),
        **kw,
    )


class Vision(unittest.TestCase):
    def test_a_fresh_frame_is_read_into_typed_fields(self):
        look = asyncio.run(seer(FakeWorld()).look("Grug"))
        self.assertEqual(vision.SEEN, look.status)
        state = look.state(1000.0)
        self.assertEqual("in_world", state["screen"])
        self.assertEqual(5, state["seconds_old"])
        self.assertIn("can be wrong", state["source"])

    def test_the_answer_is_read_from_content_as_well_as_thinking(self):
        look = asyncio.run(seer(FakeWorld(where="content")).look("Grug"))
        self.assertEqual(vision.SEEN, look.status)

    def test_no_frame_or_a_stale_one_is_a_status_and_no_fields(self):
        for world, status in (
            (FakeWorld(age=None), vision.NO_FRAME),
            (FakeWorld(has_frame=False), vision.NO_FRAME),
            (FakeWorld(age=600), vision.STALE),
        ):
            look = asyncio.run(seer(world).look("Grug"))
            self.assertEqual(status, look.status)
            self.assertIsNone(look.state(1000.0))
            self.assertFalse(any("api/chat" in c for c in world.calls))

    def test_a_malformed_answer_is_invalid(self):
        for reply in (
            dict(GOOD, screen="underwater_castle"),
            dict(GOOD, dead="no"),
            {k: v for k, v in GOOD.items() if k != "fighting"},
            "not json",
        ):
            look = asyncio.run(seer(FakeWorld(reply=reply)).look("Grug"))
            self.assertEqual(vision.INVALID, look.status, reply)

    def test_one_look_per_minute_per_head(self):
        world, clock = FakeWorld(), Clock()
        s = seer(world, clock)
        asyncio.run(s.look("Grug"))
        clock.now += 30
        asyncio.run(s.look("Grug"))
        chats = [c for c in world.calls if "api/chat" in c]
        self.assertEqual(1, len(chats))
        clock.now += 31
        asyncio.run(s.look("Grug"))
        self.assertEqual(2, len([c for c in world.calls if "api/chat" in c]))

    def test_off_asks_nothing(self):
        world = FakeWorld()
        look = asyncio.run(seer(world, on=False).look("Grug"))
        self.assertEqual(vision.OFF, look.status)
        self.assertEqual([], world.calls)

    def test_the_sentence_is_ascii_and_short(self):
        fields = vision.parse(dict(GOOD, seen="Grug stands 在 camp " + "x" * 400))
        self.assertTrue(fields["seen"].isascii())
        self.assertLessEqual(len(fields["seen"]), vision.SEEN_CHARS)

    def test_the_gateway_is_named_once(self):
        llm = "http://gw.example:8080/v1/chat/completions"
        self.assertEqual(
            "http://gw.example:8080/api/chat", vision.vision_url({"LLM_URL": llm})
        )
        self.assertEqual("http://v", vision.vision_url({"VISION_URL": "http://v"}))
        self.assertEqual("", vision.vision_url({}))
        self.assertFalse(vision.Seer.from_env({}).on)

    def test_only_http_urls_and_no_redirects(self):
        self.assertFalse(
            vision.Seer(
                frame_url="file:///etc/passwd", vision_url="http://v/api/chat"
            ).on
        )
        self.assertFalse(vision.Seer(vision_url="gopher://v/api/chat").on)
        self.assertTrue(vision.Seer(vision_url="http://v/api/chat").on)
        with self.assertRaises(ValueError):
            vision._http("file:///etc/passwd", None, 1.0)
        self.assertIsNone(
            vision._NoRedirect().redirect_request(None, None, 302, "", {}, "http://x")
        )

    def test_heads_are_the_streamed_characters_and_unset_is_nobody(self):
        self.assertEqual(frozenset(), vision.heads({}))
        self.assertEqual(
            frozenset({"Grug", "Zug"}),
            vision.heads({"WOW_STREAMED_CHARACTERS": "Grug, Zug"}),
        )


if __name__ == "__main__":
    unittest.main()
