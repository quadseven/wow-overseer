"""The questers' play (questers.py, #924): every quest in reach, zone by zone,
and a quest that stops progressing is broken with its reason."""

import unittest

import classquest
import guildjobs
import questers

ELWYNN, NORTHSHIRE, WESTFALL, REDRIDGE = 12, 9, 40, 44
HUMAN, ORC = 1, 2
PRIEST, WARRIOR = 5, 1
ALLIANCE_MASK, HORDE_MASK = 1101, 690


def quest(
    qid,
    zone,
    level,
    *,
    min_level=1,
    races=0,
    classes=0,
    prev=0,
    kill=0,
    count=1,
    title="",
):
    return {
        "id": qid,
        "title": title or "Quest %d" % qid,
        "sort": zone,
        "zone": zone,
        "level": level,
        "info": 0,
        "min_level": min_level,
        "races": races,
        "classes": classes,
        "prev_signed": prev,
        "prev": prev,
        "exclusive": 0,
        "reward": 0,
        "display": 0,
        "grp": 0,
        "npc1": kill,
        "npc_count1": count,
    }


def giver(qid, role, guid, entry, x, y, map_id=0, name="Marshal"):
    return {
        "quest": qid,
        "role": role,
        "guid": guid,
        "entry": entry,
        "map_id": map_id,
        "x": x,
        "y": y,
        "name": name,
    }


def spawn(guid, entry, x, y, level=2, map_id=0, name="Wolf"):
    return {
        "guid": guid,
        "entry": entry,
        "map_id": map_id,
        "x": x,
        "y": y,
        "name": name,
        "rank": 0,
        "level": level,
    }


def started(qid, entry):
    return {"quest": qid, "kind": "creature", "entry": entry}


def ended(qid, entry, kind="creature"):
    return {"quest": qid, "kind": kind, "entry": entry}


def world(extra_quests=(), extra_givers=(), extra_starts=(), extra_ends=(), drop=()):
    """Northshire (sorted under its area, 9), Goldshire in Elwynn (12), two
    zones further on, and quests a Human priest may not take."""
    quests = [
        quest(1, NORTHSHIRE, 2, kill=200, count=8, title="Wolves Across the Border"),
        quest(2, NORTHSHIRE, 3, kill=201, title="Kobold Camp Cleanup"),
        quest(3, ELWYNN, 4, title="Report to Goldshire"),
        quest(4, NORTHSHIRE, 2, races=HORDE_MASK, title="A Horde Errand"),
        quest(5, NORTHSHIRE, 2, classes=1 << (WARRIOR - 1), title="Simple Letter"),
        quest(6, NORTHSHIRE, 3, prev=1, title="After the Wolves"),
        quest(7, NORTHSHIRE, 12, min_level=10, title="Too High For Now"),
        quest(18, WESTFALL, 4, title="Brotherhood of Thieves"),
        quest(20, WESTFALL, 4, title="The Westfall Stew"),
        quest(21, WESTFALL, 12, title="The Defias Brotherhood"),
        quest(30, REDRIDGE, 6, title="Redridge Goulash"),
        quest(31, REDRIDGE, 18, title="Blackrock Menace"),
    ] + list(extra_quests)
    givers = [
        giver(1, "start", 1001, 100, 0, 0),
        giver(1, "end", 1001, 100, 0, 0),
        giver(2, "start", 1002, 101, 60, 0),
        giver(2, "end", 1002, 101, 60, 0),
        giver(3, "start", 1003, 102, 400, 0),
        giver(3, "end", 1003, 102, 400, 0),
        giver(4, "start", 1004, 103, 5, 0),
        giver(4, "end", 1004, 103, 5, 0),
        giver(5, "start", 1005, 104, 5, 0),
        giver(5, "end", 1005, 104, 5, 0),
        giver(6, "start", 1001, 100, 0, 0),
        giver(6, "end", 1001, 100, 0, 0),
        giver(7, "start", 1001, 100, 0, 0),
        giver(7, "end", 1001, 100, 0, 0),
        giver(18, "start", 1018, 118, 3500, 0),
        giver(18, "end", 1018, 118, 3500, 0),
        giver(20, "start", 1020, 120, 3000, 0),
        giver(20, "end", 1020, 120, 3000, 0),
        giver(21, "start", 1020, 120, 3000, 0),
        giver(21, "end", 1020, 120, 3000, 0),
        giver(30, "start", 1030, 130, 2000, 0),
        giver(30, "end", 1030, 130, 2000, 0),
        giver(31, "start", 1030, 130, 2000, 0),
        giver(31, "end", 1030, 130, 2000, 0),
    ] + list(extra_givers)
    spawns = [
        spawn(2001, 200, 150, 0),
        spawn(2002, 201, 250, 0, level=3),
        spawn(2018, 218, 1850, 0, level=4),
    ]
    # What is named to give and take each quest, spawned or not.
    named = {g["quest"]: g["entry"] for g in givers if g["role"] == "start"}
    starts = [started(q, e) for q, e in sorted(named.items())] + list(extra_starts)
    enders = {g["quest"]: g["entry"] for g in givers if g["role"] == "end"}
    ends = [ended(q, e) for q, e in sorted(enders.items())] + list(extra_ends)
    # The spawned givers and enders catalogue() reads: `drop` takes the spawn
    # out of these while `starts` and `ends` still name it.
    givers = [g for g in givers if g["guid"] not in drop]
    return questers.catalogue(quests, givers, spawns, [], starts, ends)


def mirra(**kw):
    base = dict(
        name="Mirra",
        level=2,
        race=HUMAN,
        class_id=PRIEST,
        map_id=0,
        x=10.0,
        y=0.0,
        zone_id=ELWYNN,
        online=True,
    )
    base.update(kw)
    return questers.Member(**base)


def walk(member, cat, rounds=20, clock=None):
    """Play the quester forward: each take goes into the log at once, each
    hunt completes the quest, each hand-in rewards it. Returns the moves."""
    clock = clock or questers.Clock()
    moves = []
    for i in range(rounds):
        p = questers.plan(cat, member, clock, now=60.0 * i)
        if p.move is None:
            break
        moves.append((p.move.kind, p.move.quest))
        log, done = dict(member.quest_log), set(member.quests_done)
        if p.move.kind == classquest.TAKE:
            if p.move.quest in {18, 20, 21, 30, 31}:
                break  # the walk to the next zone
            log[p.move.quest] = questers.STATUS_INCOMPLETE
            if not cat.quest(p.move.quest).kills:
                log[p.move.quest] = questers.STATUS_COMPLETE
        elif p.move.kind == classquest.HUNT:
            log[p.move.quest] = questers.STATUS_COMPLETE
        elif p.move.kind == classquest.TURN_IN:
            log.pop(p.move.quest)
            done.add(p.move.quest)
        member = questers.Member(
            **{**member.__dict__, "quest_log": log, "quests_done": frozenset(done)}
        )
    return moves, member


class EveryQuestInReach(unittest.TestCase):
    def test_a_starting_area_quest_is_of_the_zone_the_quester_stands_in(self):
        cat = world()
        self.assertEqual(cat.facts[1].zone, ELWYNN)
        self.assertEqual(questers.in_reach(cat, mirra(), ELWYNN), [1, 2, 3])

    def test_race_class_level_and_the_quest_before_it_are_held_to(self):
        cat = world()
        warrior = mirra(class_id=WARRIOR)
        self.assertIn(5, questers.in_reach(cat, warrior, ELWYNN))
        self.assertNotIn(4, questers.in_reach(cat, mirra(), ELWYNN))
        self.assertIn(4, questers.in_reach(cat, mirra(race=ORC), ELWYNN))
        self.assertNotIn(7, questers.in_reach(cat, mirra(), ELWYNN))
        self.assertNotIn(6, questers.in_reach(cat, mirra(), ELWYNN))
        done = mirra(quests_done=frozenset({1}))
        self.assertIn(6, questers.in_reach(cat, done, ELWYNN))

    def test_it_takes_the_nearest_quest_first(self):
        p = questers.plan(world(), mirra(x=55.0), questers.Clock(), 0.0)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 2))
        p = questers.plan(world(), mirra(x=0.0), questers.Clock(), 0.0)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 1))

    def test_it_takes_every_open_quest_in_its_zone_then_works_and_hands_them_in(self):
        moves, member = walk(mirra(), world())
        taken = [q for k, q in moves if k == classquest.TAKE]
        # Every quest open to it in Elwynn, the one the wolves open too, and only
        # then the walk on to the next zone.
        self.assertEqual(sorted(taken[:-1]), [1, 2, 3, 6])
        self.assertEqual(member.quests_done, frozenset({1, 2, 3, 6}))
        self.assertEqual(moves[-1], (classquest.TAKE, 20))

    def test_it_does_not_move_on_while_a_quest_in_reach_is_left(self):
        cat = world()
        member = mirra(quests_done=frozenset({1, 3, 6}))
        p = questers.plan(cat, member, questers.Clock(), 0.0)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 2))
        held = mirra(quests_done=frozenset({1, 3, 6}), quest_log={2: 3})
        p = questers.plan(cat, held, questers.Clock(), 0.0)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.HUNT, 2))

    def test_the_next_zone_is_the_lowest_band_that_holds_a_quest_in_reach(self):
        cat = world()
        done = mirra(level=5, quests_done=frozenset({1, 2, 3, 6}))
        self.assertEqual(questers.next_zone(cat, done)[0], WESTFALL)
        # Westfall finished, Redridge is next.
        later = mirra(level=5, quests_done=frozenset({1, 2, 3, 6, 20}))
        zone, opens = questers.next_zone(cat, later)
        self.assertEqual((zone, opens), (REDRIDGE, [30]))
        p = questers.plan(cat, later, questers.Clock(), 0.0)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 30))
        self.assertIn("goes on to", p.move.said)

    def test_a_zone_on_the_other_continent_is_crossed_to(self):
        far = [quest(40, 148, 4, title="Darkshore Fish")]
        cat = world(
            extra_quests=far,
            extra_givers=[
                giver(40, "start", 1040, 140, 0, 0, map_id=1),
                giver(40, "end", 1040, 140, 0, 0, map_id=1),
            ],
        )
        member = mirra(level=5, quests_done=frozenset({1, 2, 3, 6, 20, 30}))
        p = questers.plan(cat, member, questers.Clock(), 0.0)
        self.assertEqual((p.move.kind, p.move.to_map), (classquest.CROSS, 1))

    def test_a_full_log_takes_nothing_and_works_what_it_holds(self):
        log = {100 + i: 3 for i in range(questers.LOG_SLOTS - 1)}
        log[1] = 3
        p = questers.plan(world(), mirra(quest_log=log), questers.Clock(), 0.0)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.HUNT, 1))

    def test_a_take_that_went_through_is_not_asked_again_before_the_log_saves(self):
        tried = [questers.Attempt("Mirra", "take quest:1", "applied", age_minutes=2)]
        p = questers.plan(world(), mirra(x=0.0), questers.Clock(), 0.0, tried=tried)
        self.assertNotEqual((p.move.kind, p.move.quest), (classquest.TAKE, 1))


# A zone whose band is lower than Westfall's (2026-10-19 on the dev realm:
# Durotar for questers of 14 to 22, who had done or broken every quest a
# creature there gives, and still held two that an item starts).
DUROTAR = 14


def item_started(qid, entry=4881):
    return {"quest": qid, "kind": "item", "entry": entry}


class NextZoneHasAGiverToGoTo(unittest.TestCase):
    """A zone is gone to only for a quest whose giver the quester can walk to:
    one only an item starts, or one whose givers it leaves for now, made the
    quester pick that zone every pass and then say it 'has no way there'."""

    def done_with_elwynn(self, **kw):
        # Elwynn done, and Durotar's quest a creature gives (52) done too.
        return mirra(level=5, quests_done=frozenset({1, 2, 3, 6, 52}), **kw)

    def durotar(self, extra_quests=(), extra_givers=(), extra_starts=()):
        """The world with a Durotar whose one creature-given quest (52) is
        done, as the realm's quester had done or broken them all."""
        return world(
            extra_quests=[quest(52, DUROTAR, 2, title="Carry Your Weight")]
            + list(extra_quests),
            extra_givers=[
                giver(52, "start", 1052, 152, 500, 0),
                giver(52, "end", 1052, 152, 500, 0),
            ]
            + list(extra_givers),
            extra_starts=list(extra_starts),
        )

    def test_a_zone_whose_open_quests_an_item_starts_is_passed_over(self):
        cat = self.durotar(
            extra_quests=[quest(50, DUROTAR, 2, title="The Admiral's Orders")],
            extra_starts=[item_started(50)],
        )
        # The quest is in reach: race, level and chain allow it.
        self.assertEqual(questers.in_reach(cat, self.done_with_elwynn(), DUROTAR), [50])
        self.assertEqual(questers.next_zone(cat, self.done_with_elwynn())[0], WESTFALL)
        p = questers.plan(cat, self.done_with_elwynn(), questers.Clock(), 0.0)
        self.assertIsNotNone(p.move, p.line)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 20))
        self.assertNotIn("has no way there", p.line)

    def test_an_item_started_zone_on_the_other_continent_is_not_crossed_to(self):
        cat = self.durotar(
            extra_quests=[quest(50, DUROTAR, 2, title="The Admiral's Orders")],
            extra_starts=[item_started(50)],
        )
        member = self.done_with_elwynn(map_id=1)
        zone, _opens = questers.next_zone(cat, member)
        self.assertNotEqual(zone, DUROTAR)

    def test_a_zone_whose_only_giver_it_leaves_for_now_is_passed_over(self):
        cat = world(
            extra_quests=[quest(51, DUROTAR, 2, title="Vanquish the Betrayers")],
            extra_givers=[
                giver(51, "start", 1051, 151, 500, 0),
                giver(51, "end", 1051, 151, 500, 0),
            ],
        )
        member = self.done_with_elwynn()
        self.assertEqual(questers.next_zone(cat, member)[0], DUROTAR)
        other_side = "the way to the spawn crosses the other side's ground"
        self.assertIn(other_side, classquest.SPAWN_REFUSALS)
        tried = [
            questers.Attempt(
                "Mirra",
                "walk-to",
                "error",
                reason=other_side,
                spawn=1051,
                age_minutes=5,
            )
        ]
        p = questers.plan(cat, member, questers.Clock(), 0.0, tried=tried)
        self.assertIsNotNone(p.move, p.line)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 20))
        # Once the hold on that giver lapses, the zone is gone to again.
        later = [
            questers.Attempt(
                **{**tried[0].__dict__, "age_minutes": classquest.SPAWN_REFUSED_MINUTES}
            )
        ]
        p = questers.plan(cat, member, questers.Clock(), 0.0, tried=later)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 51))

    def test_a_zone_with_a_giver_to_go_to_is_still_chosen_first(self):
        cat = world(
            extra_quests=[
                quest(50, DUROTAR, 2, title="The Admiral's Orders"),
                quest(51, DUROTAR, 2, title="Vanquish the Betrayers"),
            ],
            extra_givers=[
                giver(51, "start", 1051, 151, 500, 0),
                giver(51, "end", 1051, 151, 500, 0),
            ],
            extra_starts=[item_started(50)],
        )
        zone, opens = questers.next_zone(cat, self.done_with_elwynn())
        self.assertEqual((zone, opens), (DUROTAR, [51]))


def walk_row(reason, age, spawn=1003, status="error", name="Mirra"):
    """One quester walk row of the command log, ended by the module with
    `reason` (a refusal when the status failed), `age` minutes ago."""
    outcome = "refused" if status == "error" else "arrived"
    return {
        "id": 9,
        "target_name": name,
        "command": "walk-to-spawn creature:%d map:0 x:400 y:0" % spawn,
        "source": guildjobs.source_for(questers.WALK_ACTION, name),
        "status": status,
        "result": '{"outcome":"%s","reason":"%s","retryable":true}' % (outcome, reason),
        "age": age,
    }


# The module's far walk walls, in its own words (FarWalkRefusal, and the hold
# another verb places on a character).
WALLS = (
    "this character has started as many far walks this hour as one may",
    "the realm has as many far walks under way as it allows",
    "character is held by another verb",
)
LETHAL_ROAD = "the road to the spawn crosses ground far above its level"


class FarWalkWallsWait(unittest.TestCase):
    """A quester whose walk the realm refused for a far walk wall waits the
    wall's own time (classquest.BACKOFF_MINUTES) before it walks again
    (2026-10-18 to 2026-10-20 on the dev realm: the twenty questers' walks
    were refused 2,276 times for the bot's far walk budget and 2,453 times as
    held by another verb, because the same walk was asked every pass, about
    every two minutes)."""

    def member(self, **kw):
        # Northshire done but for Report to Goldshire, its giver 390 yards off.
        return mirra(level=5, quests_done=frozenset({1, 2, 6}), **kw)

    def plan(self, *rows, member=None):
        tried = questers.attempts(rows)
        return questers.plan(
            world(), member or self.member(x=-700.0), questers.Clock(), 0.0, tried=tried
        )

    def test_with_no_refused_walk_it_walks(self):
        p = self.plan()
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 3))

    def test_a_walk_refused_for_a_wall_holds_the_quester_the_wall_s_time(self):
        for wall in WALLS:
            with self.subTest(wall=wall):
                self.assertIn(wall, classquest.BACKOFF_MINUTES)
                wait = classquest.BACKOFF_MINUTES[wall]
                p = self.plan(walk_row(wall, 5))
                self.assertIsNone(p.move, p.line)
                self.assertIn("waits", p.line)
                self.assertIn(wall, p.line)
                self.assertIn("%d more minute" % (wait - 5), p.line)
                due = self.plan(walk_row(wall, wait))
                self.assertIsNotNone(due.move, due.line)
                self.assertEqual((due.move.kind, due.move.quest), (classquest.TAKE, 3))

    def test_a_near_hand_in_is_not_held_by_a_far_walk_wall(self):
        member = self.member(quest_log={3: questers.STATUS_COMPLETE})
        p = self.plan(walk_row(WALLS[0], 5), member=member)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 3))

    def test_a_far_hand_in_is_still_held_by_a_far_walk_wall(self):
        member = self.member(x=-700.0, quest_log={3: questers.STATUS_COMPLETE})
        p = self.plan(walk_row(WALLS[0], 5), member=member)
        self.assertIsNone(p.move, p.line)
        self.assertIn("waits", p.line)

    def test_a_near_walk_is_held_by_another_verb_s_hold(self):
        # 2026-10-27/28 on the dev realm: a quester's 170-yard hunt walk was
        # refused as held by another verb every pass, about every two minutes,
        # nine times in a row; the hold is on the character, not the road, so
        # a near walk waits it out as a far one does.
        held = classquest.HELD_REASON
        wait = classquest.BACKOFF_MINUTES[held]
        p = self.plan(walk_row(held, 2), member=self.member())
        self.assertIsNone(p.move, p.line)
        self.assertIn("waits %d more minutes to walk: %s" % (wait - 2, held), p.line)
        due = self.plan(walk_row(held, wait), member=self.member())
        self.assertEqual((due.move.kind, due.move.quest), (classquest.TAKE, 3))

    def test_a_near_walk_is_not_held_by_a_far_walk_budget(self):
        for wall in (classquest.BOT_BUDGET_REASON, classquest.REALM_FULL_REASON):
            with self.subTest(wall=wall):
                p = self.plan(walk_row(wall, 2), member=self.member())
                self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 3))

    def test_only_the_newest_row_decides(self):
        budget = WALLS[0]
        p = self.plan(walk_row(budget, 10), walk_row("", 3, status="done"))
        self.assertIsNotNone(p.move, p.line)
        p = self.plan(walk_row("", 10, status="done"), walk_row(budget, 3))
        self.assertIsNone(p.move, p.line)

    def test_another_quester_s_refusal_does_not_hold_it(self):
        p = self.plan(walk_row(WALLS[0], 5, name="Durga"))
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 3))

    def test_a_drop_needs_no_walk_and_is_not_held(self):
        member = self.member(quest_log={2: questers.STATUS_INCOMPLETE})
        tried = questers.attempts([walk_row(WALLS[0], 5)])
        p = questers.plan(
            world(), member, questers.Clock(), 0.0, frozenset({2}), tried=tried
        )
        self.assertIsNotNone(p.move, p.line)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.ABANDON, 2))


class ALethalRoadPassesTheGiverOver(unittest.TestCase):
    """A walk the module refused because the road to the spawn crosses ground
    far above the quester's level (SpawnWalkRefusal) leaves that spawn for
    classquest.SPAWN_REFUSED_MINUTES, as a drop on the way does: the road will
    be as deadly on the next pass (2026-10-20: Pindle's walk to Deputy Willem
    was refused so five times in a row, one pass after another)."""

    def test_the_lethal_road_is_a_lasting_spawn_refusal(self):
        self.assertIn(LETHAL_ROAD, classquest.SPAWN_REFUSALS)
        self.assertNotIn(LETHAL_ROAD, classquest.SPAWN_SHORT_REFUSALS)

    def test_the_zone_of_a_giver_behind_a_lethal_road_is_passed_over(self):
        cat = world(
            extra_quests=[quest(51, DUROTAR, 2, title="Vanquish the Betrayers")],
            extra_givers=[
                giver(51, "start", 1051, 151, 500, 0),
                giver(51, "end", 1051, 151, 500, 0),
            ],
        )
        member = mirra(level=5, quests_done=frozenset({1, 2, 3, 6, 52}))
        p = questers.plan(cat, member, questers.Clock(), 0.0)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 51))
        tried = questers.attempts([walk_row(LETHAL_ROAD, 5, spawn=1051)])
        self.assertEqual(questers.left_spawns("Mirra", tried), frozenset({1051}))
        p = questers.plan(cat, member, questers.Clock(), 0.0, tried=tried)
        self.assertIsNotNone(p.move, p.line)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 20))
        self.assertNotIn("waits", p.line)
        later = questers.attempts(
            [walk_row(LETHAL_ROAD, classquest.SPAWN_REFUSED_MINUTES, spawn=1051)]
        )
        p = questers.plan(cat, member, questers.Clock(), 0.0, tried=later)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 51))


# The module's answer to a crossing row, as the command log holds it.
NO_TRANSPORT = (
    "no transport the module knows sails from this map to that map for this faction"
)
AT_ONCE = "the realm already has as many crossings as it allows (Overseer.Cross.AtOnce)"


def crossing_row(reason, retry, age, to_map=1, source="guildjobs:quester-cross:Mirra"):
    """One crossing row of the command log, refused by the module with
    `reason` (CrossResultJson's own shape), `age` minutes ago."""
    result = '{"outcome":"refused","reason":"%s","retry":%s,"map":%d,"steps":0}' % (
        reason,
        "true" if retry else "false",
        to_map,
    )
    return {
        "id": 7,
        "target_name": "Mirra",
        "command": "cross-to-map map:%d" % to_map,
        "source": source,
        "status": "error",
        "result": result,
        "age": age,
    }


class OneCrossingAtATime(unittest.TestCase):
    """A quester's crossing shares the guild's one crossing clock and walls
    (guildjobs.CROSS_ACTIONS): asked once, not every pass (2026-10-18)."""

    def setUp(self):
        far = [quest(40, 148, 4, title="Darkshore Fish")]
        self.cat = world(
            extra_quests=far,
            extra_givers=[
                giver(40, "start", 1040, 140, 0, 0, map_id=1),
                giver(40, "end", 1040, 140, 0, 0, map_id=1),
            ],
        )
        self.member = mirra(level=5, quests_done=frozenset({1, 2, 3, 6, 20, 30}))

    def plan(self, *rows):
        crossings = guildjobs.recent_from_rows(rows)
        return questers.plan(
            self.cat, self.member, questers.Clock(), 0.0, crossings=crossings
        )

    def test_the_crossing_row_has_its_own_source_on_the_shared_clock(self):
        p = self.plan()
        step = questers.step_for(self.member, p.move, 0)
        self.assertEqual([r.command for r in step.rows], ["cross-to-map map:1"])
        self.assertEqual(step.rows[0].source, "guildjobs:quester-cross:Mirra")
        self.assertIn(guildjobs.action_of(step.rows[0].source), guildjobs.CROSS_ACTIONS)
        self.assertEqual(questers.CROSS_ACTION, questers.ACTION + "-cross")

    def test_a_crossing_the_world_has_no_transport_for_is_not_asked_again(self):
        p = self.plan(crossing_row(NO_TRANSPORT, False, age=60))
        self.assertIsNone(p.move)
        self.assertIn(NO_TRANSPORT, p.line)

    def test_the_wall_lifts_after_cross_wall_minutes(self):
        p = self.plan(
            crossing_row(NO_TRANSPORT, False, age=classquest.CROSS_WALL_MINUTES)
        )
        self.assertEqual((p.move.kind, p.move.to_map), (classquest.CROSS, 1))

    def test_a_crossing_refused_at_the_cap_waits_the_retry_minutes(self):
        young = self.plan(crossing_row(AT_ONCE, True, age=2))
        self.assertIsNone(young.move)
        self.assertIn("waits on its last crossing", young.line)
        due = self.plan(crossing_row(AT_ONCE, True, age=classquest.CROSS_RETRY_MINUTES))
        self.assertEqual((due.move.kind, due.move.to_map), (classquest.CROSS, 1))

    def test_a_class_quest_crossing_holds_the_questers_too(self):
        row = crossing_row(
            AT_ONCE, True, age=2, source="guildjobs:classquest-cross:Mirra"
        )
        self.assertIsNone(self.plan(row).move)


class WallsOnMapZero(unittest.TestCase):
    def test_a_crossing_to_map_zero_refused_for_good_is_walled(self):
        rows = [crossing_row(NO_TRANSPORT, False, age=5, to_map=0)]
        walls = guildjobs.class_walls("Mirra", guildjobs.recent_from_rows(rows))
        self.assertEqual(walls, {0: NO_TRANSPORT})


# Dun Morogh and Loch Modan, and the module's answer when the walk to the
# berth fails (2026-10-19 on the dev realm: three Alliance questers of 15 and
# 16 in Dun Morogh, sent to Durotar for its one quest in reach every pass).
DUN_MOROGH, LOCH_MODAN = 1, 38
DWARF = 3
BERTH = "the walk to the berth gave up on the ground"


def under_way_row(age, to_map=1):
    """A crossing row the module took and has not answered yet."""
    return {
        "id": 8,
        "target_name": "Mirra",
        "command": "cross-to-map map:%d" % to_map,
        "source": "guildjobs:quester-cross:Mirra",
        "status": "delivered",
        "result": "",
        "age": age,
    }


class AFailedCrossingPassesTheZoneOver(unittest.TestCase):
    """While its last crossing failed and the crossing clock holds it, a
    quester goes to the best zone on its own continent instead of choosing the
    zone across the sea and standing still until the clock lapses."""

    def setUp(self):
        self.cat = world(
            extra_quests=[
                quest(834, DUROTAR, 9, min_level=7, title="Winds in the Desert"),
                quest(60, LOCH_MODAN, 14, min_level=10, title="Stormpike's Order"),
            ],
            extra_givers=[
                giver(834, "start", 3293, 3293, 300, -4700, map_id=1, name="Rezlak"),
                giver(834, "end", 3293, 3293, 300, -4700, map_id=1, name="Rezlak"),
                giver(60, "start", 1060, 160, -5300, -2900, name="Mountaineer"),
                giver(60, "end", 1060, 160, -5300, -2900, name="Mountaineer"),
            ],
        )
        self.member = mirra(
            level=15,
            race=DWARF,
            zone_id=DUN_MOROGH,
            x=-5600.0,
            y=-500.0,
            quests_done=frozenset({1, 2, 3, 6, 7, 20, 21, 30, 31}),
        )

    def plan(self, *rows):
        crossings = guildjobs.recent_from_rows(rows)
        return questers.plan(
            self.cat, self.member, questers.Clock(), 0.0, crossings=crossings
        )

    def test_with_no_failed_crossing_it_still_crosses_for_the_lowest_band(self):
        self.assertEqual(questers.next_zone(self.cat, self.member)[0], DUROTAR)
        p = self.plan()
        self.assertEqual((p.move.kind, p.move.to_map), (classquest.CROSS, 1))

    def test_after_the_berth_walk_fails_it_goes_to_a_zone_on_its_own_map(self):
        p = self.plan(crossing_row(BERTH, True, age=2))
        self.assertIsNotNone(p.move, p.line)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 60))
        self.assertNotIn("waits on its last crossing", p.line)
        self.assertEqual(
            questers.next_zone(self.cat, self.member, unsailed=frozenset({1})),
            (LOCH_MODAN, [60]),
        )

    def test_once_the_crossing_clock_lapses_the_zone_is_chosen_again(self):
        young = self.plan(crossing_row(BERTH, True, age=2))
        self.assertEqual((young.move.kind, young.move.quest), (classquest.TAKE, 60))
        due = self.plan(crossing_row(BERTH, True, age=classquest.CROSS_RETRY_MINUTES))
        self.assertEqual((due.move.kind, due.move.to_map), (classquest.CROSS, 1))

    def test_a_second_berth_walk_that_gives_up_holds_the_crossing_for_hours(self):
        # 2026-10-18 to 2026-10-20 on the dev realm: three Alliance questers
        # of 15 were sent to the Menethil berth for Durotar every ten minutes
        # for 44 hours, one of them 256 times, and every walk gave up on the
        # ground, because the road there crosses ground far above its level.
        twice = (
            crossing_row(BERTH, True, age=classquest.CROSS_RETRY_MINUTES),
            crossing_row(BERTH, True, age=2 * classquest.CROSS_RETRY_MINUTES + 1),
        )
        crossings = guildjobs.recent_from_rows(twice)
        self.assertTrue(guildjobs.crossing_cooling("Mirra", crossings))
        p = self.plan(*twice)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 60))
        late = (
            crossing_row(BERTH, True, age=classquest.CROSS_GROUND_HOLD_MINUTES - 1),
            crossing_row(BERTH, True, age=classquest.CROSS_GROUND_HOLD_MINUTES + 9),
        )
        self.assertTrue(
            guildjobs.crossing_cooling("Mirra", guildjobs.recent_from_rows(late))
        )

    def test_the_berth_hold_lapses_and_counts_only_that_map(self):
        lapsed = (
            crossing_row(BERTH, True, age=classquest.CROSS_GROUND_HOLD_MINUTES),
            crossing_row(BERTH, True, age=classquest.CROSS_GROUND_HOLD_MINUTES + 10),
        )
        due = self.plan(*lapsed)
        self.assertEqual((due.move.kind, due.move.to_map), (classquest.CROSS, 1))
        other_map = (
            crossing_row(BERTH, True, age=classquest.CROSS_RETRY_MINUTES),
            crossing_row(BERTH, True, age=30, to_map=0),
        )
        self.assertFalse(
            guildjobs.crossing_cooling("Mirra", guildjobs.recent_from_rows(other_map))
        )

    def test_a_crossing_still_under_way_is_waited_on(self):
        p = self.plan(under_way_row(age=5))
        self.assertIsNone(p.move)
        self.assertIn("waits on its last crossing", p.line)
        self.assertEqual(
            questers.failed_crossings(
                "Mirra", guildjobs.recent_from_rows([under_way_row(age=5)])
            ),
            frozenset(),
        )

    def test_a_crossing_refused_for_good_passes_the_zone_over_too(self):
        p = self.plan(crossing_row(NO_TRANSPORT, False, age=60))
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 60))


class Steps(unittest.TestCase):
    def test_a_take_is_a_walk_to_the_giver_and_the_take(self):
        p = questers.plan(world(), mirra(x=0.0), questers.Clock(), 0.0)
        step = questers.step_for(mirra(x=0.0), p.move, 0)
        self.assertTrue(step.walk.command.startswith("walk-to-spawn creature:1001"))
        self.assertEqual([r.command for r in step.rows], ["take quest:1"])
        self.assertEqual(step.rows[0].source, "guildjobs:quester:Mirra")

    def test_a_drop_is_the_abandon_row_alone(self):
        clock = questers.Clock()
        member = mirra(quest_log={1: 3})
        for minute in range(0, 125, 5):
            p = questers.plan(world(), member, clock, minute * 60.0)
        step = questers.step_for(member, p.move, 0)
        self.assertIsNone(step.walk)
        self.assertEqual([r.command for r in step.rows], ["abandon quest:1"])

    def test_a_hunt_is_the_walk_and_the_hunt_spawn_row_for_its_creature(self):
        member = mirra(x=-400.0, quest_log={1: 3}, quests_done=frozenset({2, 3}))
        cat = world()
        p = questers.plan(cat, member, questers.Clock(), 0.0)
        step = questers.step_for(member, p.move, 0, cat.quest(1))
        self.assertTrue(step.walk.command.startswith("walk-to-spawn creature:2001"))
        self.assertEqual(
            [r.command for r in step.rows], ["hunt-spawn creature:200 count:8 max:480"]
        )

    def test_with_no_hunt_verb_a_far_hunt_is_the_walk_to_the_spawn_alone(self):
        member = mirra(x=-400.0, quest_log={1: 3}, quests_done=frozenset({2, 3}))
        cat = world()
        p = questers.plan(cat, member, questers.Clock(), 0.0)
        step = questers.step_for(member, p.move, 0, cat.quest(1), hunt=False)
        self.assertTrue(step.walk.command.startswith("walk-to-spawn creature:2001"))
        self.assertEqual(step.walk.source, "guildjobs:quester-walk:Mirra")
        self.assertEqual(step.rows, ())
        self.assertEqual(
            (step.action, step.key, step.spot), (questers.ACTION, 1, p.move.spot)
        )

    def test_a_walk_only_hunt_the_quester_stands_at_writes_nothing(self):
        member = mirra(x=150.0, quest_log={1: 3}, quests_done=frozenset({2, 3}))
        cat = world()
        p = questers.plan(cat, member, questers.Clock(), 0.0)
        self.assertEqual(p.move.kind, classquest.HUNT)
        self.assertIsNone(
            questers.step_for(member, p.move, 0, cat.quest(1), hunt=False)
        )


class Broken(unittest.TestCase):
    def _play(self, member, minutes, clock=None, step=5, progress=None):
        clock = clock or questers.Clock()
        p = None
        for minute in range(0, minutes + 1, step):
            if progress:
                member = questers.Member(
                    **{**member.__dict__, "quest_progress": progress(minute)}
                )
            p = questers.plan(world(), member, clock, minute * 60.0)
        return p, clock

    def test_objectives_still_for_two_hours_of_play_break_the_quest(self):
        p, _ = self._play(mirra(quest_log={1: 3}), 115)
        self.assertEqual(p.broken, ())
        p, _ = self._play(mirra(quest_log={1: 3}), 120)
        self.assertEqual(
            [(b.quest, b.reason, b.held) for b in p.broken],
            [(1, questers.STALLED, True)],
        )
        self.assertEqual((p.move.kind, p.move.quest), (classquest.ABANDON, 1))
        self.assertIn(questers.STALLED, p.move.said)

    def test_objectives_that_move_never_stall(self):
        p, _ = self._play(
            mirra(quest_log={1: 3}), 240, progress=lambda minute: {1: minute // 60}
        )
        self.assertEqual(p.broken, ())

    def test_time_offline_is_not_play(self):
        clock = questers.Clock()
        self._play(mirra(quest_log={1: 3}), 60, clock)
        p = questers.plan(
            world(), mirra(quest_log={1: 3}, online=False), clock, 5 * 3600.0
        )
        self.assertEqual(p.broken, ())
        self.assertLess(clock.played("Mirra", 1), questers.STALL_SECONDS)

    def test_a_quest_of_another_zone_it_is_not_working_does_not_stall(self):
        p, _ = self._play(mirra(quest_log={20: 3}), 240)
        self.assertEqual(p.broken, ())

    def test_the_clock_survives_a_restart(self):
        clock = questers.Clock()
        self._play(mirra(quest_log={1: 3}), 60, clock)
        again = questers.Clock()
        again.load(clock.dump())
        self.assertEqual(again.played("Mirra", 1), clock.played("Mirra", 1))

    def test_a_turn_in_npc_not_in_the_world_breaks_the_quest_at_once(self):
        cat = world(drop={1003})  # Goldshire's marshal is not spawned
        p = questers.plan(cat, mirra(quest_log={3: 3}), questers.Clock(), 0.0)
        self.assertEqual(
            [(b.quest, b.reason) for b in p.broken], [(3, questers.ENDER_MISSING)]
        )
        self.assertEqual(p.move.kind, classquest.ABANDON)

    def test_a_complete_quest_with_no_turn_in_npc_is_recorded_not_abandoned(self):
        # The module refuses to abandon a complete quest ("it is complete;
        # hand it in"), so the bridge never asks (#1085): the quest is
        # recorded broken with its reason and the quester moves on.
        cat = world(drop={1003})
        p = questers.plan(cat, mirra(quest_log={3: 1}), questers.Clock(), 0.0)
        self.assertEqual(
            [(b.quest, b.reason) for b in p.broken], [(3, questers.ENDER_MISSING)]
        )
        self.assertNotEqual(p.move.kind, classquest.ABANDON)

    def test_a_quest_giver_not_in_the_world_is_recorded_and_not_taken(self):
        cat = world(drop={1002})
        p = questers.plan(cat, mirra(x=60.0), questers.Clock(), 0.0)
        self.assertIn(
            (2, questers.GIVER_MISSING, False),
            [(b.quest, b.reason, b.held) for b in p.broken],
        )
        self.assertNotEqual(p.move.quest, 2)

    def test_a_quest_an_item_also_starts_is_not_missing_its_giver(self):
        cat = world(
            drop={1002}, extra_starts=[{"quest": 2, "kind": "item", "entry": 9}]
        )
        p = questers.plan(cat, mirra(x=60.0), questers.Clock(), 0.0)
        self.assertEqual(p.broken, ())

    def test_every_objective_spawn_gone_names_the_creature_never_found(self):
        tried = [
            questers.Attempt(
                "Mirra",
                "walk-to-spawn creature:2001",
                "error",
                reason=questers.GONE,
                spawn=2001,
            )
        ]
        p = questers.plan(
            world(), mirra(quest_log={1: 3}), questers.Clock(), 0.0, tried=tried
        )
        self.assertEqual(
            [(b.quest, b.reason) for b in p.broken], [(1, questers.SOURCE_MISSING)]
        )

    def test_a_way_the_world_refused_is_left_for_now_and_breaks_nothing(self):
        tried = [
            questers.Attempt(
                "Mirra",
                "walk-to-spawn creature:1001",
                "error",
                reason="the first step toward the creature goes over a drop",
                spawn=1001,
                age_minutes=10,
            )
        ]
        p = questers.plan(world(), mirra(x=0.0), questers.Clock(), 0.0, tried=tried)
        self.assertEqual(p.broken, ())
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 2))
        later = [questers.Attempt(**{**tried[0].__dict__, "age_minutes": 200})]
        p = questers.plan(world(), mirra(x=0.0), questers.Clock(), 0.0, tried=later)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TAKE, 1))

    def test_a_hand_in_refused_three_times_is_broken_with_the_worlds_words(self):
        tried = [
            questers.Attempt(
                "Mirra",
                "turnin quest:1",
                "error",
                reason="quest is not complete",
                age_minutes=m,
            )
            for m in (30, 20, 10)
        ]
        p = questers.plan(
            world(), mirra(quest_log={1: 1}), questers.Clock(), 0.0, tried=tried
        )
        self.assertEqual(
            [b.reason for b in p.broken],
            [questers.REFUSED_TURN_IN + ": quest is not complete"],
        )

    def test_a_complete_quest_is_handed_in_not_stalled(self):
        # A complete quest's objectives cannot move; stillness is not a stall
        # (#1085): it is due a turn-in, never an abandon.
        p, _ = self._play(mirra(quest_log={1: 1}), 240)
        self.assertEqual(p.broken, ())
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 1))

    def test_an_abandon_the_world_refused_as_complete_hands_the_quest_in(self):
        # The module refused the drop with its complete words (#1085): the
        # quest goes to turn-in at once, even while its log row still says
        # incomplete, and is never abandoned again.
        tried = [
            questers.Attempt(
                "Mirra",
                "abandon quest:1",
                "error",
                reason="it is complete; hand it in",
                age_minutes=5,
            )
        ]
        p = questers.plan(
            world(),
            mirra(quest_log={1: questers.STATUS_INCOMPLETE}),
            questers.Clock(),
            0.0,
            tried=tried,
        )
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 1))

    def test_a_complete_quest_the_ledger_holds_broken_is_handed_in_not_dropped(self):
        # Live, 2026-10-19 23:29Z: Bromli's Bitter Rivals (310) was in the
        # ledger as broken from before #1085, complete in the log, and the
        # day-old abandon refusal had aged out of the rows the pass reads, so
        # the bridge sent `abandon quest:310` again and the module refused it
        # as complete. A complete quest is never dropped: it is handed in.
        p = questers.plan(
            world(),
            mirra(quest_log={1: questers.STATUS_COMPLETE}),
            questers.Clock(),
            0.0,
            broken=frozenset({1}),
        )
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 1))

    def test_a_complete_quest_whose_hand_in_keeps_failing_is_not_abandoned(self):
        # Live, 2026-10-19 23:22Z: Kellan's The Killing Fields (9) was complete,
        # its hand-in refused three times ("no taker of that quest in reach"),
        # and the bridge sent `abandon quest:9`, which the module refused as
        # complete. The quest is recorded broken with the world's words, it is
        # not dropped, and the quester gets on with the rest of its zone.
        tried = [
            questers.Attempt(
                "Mirra",
                "turnin quest:1",
                "error",
                reason="no taker of that quest in reach",
                age_minutes=m,
            )
            for m in (30, 20, 10)
        ]
        p = questers.plan(
            world(),
            mirra(quest_log={1: questers.STATUS_COMPLETE}),
            questers.Clock(),
            0.0,
            tried=tried,
        )
        self.assertEqual(
            [b.reason for b in p.broken],
            [questers.REFUSED_TURN_IN + ": no taker of that quest in reach"],
        )
        self.assertIsNotNone(p.move)
        self.assertNotEqual(p.move.kind, classquest.ABANDON)
        self.assertNotEqual(p.move.quest, 1)

    @staticmethod
    def _refused_hand_ins(ages, words="no taker of that quest in reach"):
        """Refused `turnin quest:1` rows at these ages, and the abandon the
        module refused as complete five minutes after the first three."""
        rows = [
            questers.Attempt(
                "Mirra", "turnin quest:1", "error", reason=words, age_minutes=m
            )
            for m in ages
        ]
        rows.append(
            questers.Attempt(
                "Mirra",
                "abandon quest:1",
                "error",
                reason=questers.COMPLETE_HAND_IN,
                age_minutes=max(ages[2] - 5, 0),
            )
        )
        return rows

    def _move_with(self, tried):
        p = questers.plan(
            world(),
            mirra(quest_log={1: questers.STATUS_COMPLETE}),
            questers.Clock(),
            0.0,
            tried=tried,
        )
        return (p.move.kind, p.move.quest) if p.move is not None else None

    def test_a_refused_hand_in_the_module_calls_complete_is_held_not_looped(self):
        # Live, 2026-10-18 to 2026-10-20: Kellan's The Killing Fields (9) had
        # its hand-in refused three times ("no taker of that quest in reach"),
        # its abandon refused as complete, and then the quester walked to the
        # ender and handed it in again every two minutes for 42 hours (216
        # refusals; Pindle's Return to Bellowfiz 511). The hand-in the world
        # keeps refusing is held for TURN_IN_RETRY_MINUTES after the last
        # refusal; the quester gets on with the rest of its zone meanwhile.
        hold = questers.TURN_IN_RETRY_MINUTES
        for shift in (0, 60, hold - 11):
            move = self._move_with(
                self._refused_hand_ins((30 + shift, 20 + shift, 10 + shift))
            )
            self.assertIsNotNone(move, shift)
            self.assertIn(
                move[0], (classquest.TAKE, classquest.HUNT, classquest.CROSS), shift
            )
            self.assertNotEqual(move[1], 1, shift)
        # Past the hold it is handed in once more ...
        late = self._refused_hand_ins((hold + 30, hold + 20, hold + 10))
        self.assertEqual(self._move_with(late), (classquest.TURN_IN, 1))
        # ... and that hand-in refused again holds it once more.
        again = late + [
            questers.Attempt(
                "Mirra",
                "turnin quest:1",
                "error",
                reason="no taker of that quest in reach",
                age_minutes=1,
            )
        ]
        self.assertNotEqual(self._move_with(again), (classquest.TURN_IN, 1))
        self.assertNotEqual(self._move_with(again)[0], classquest.ABANDON)

    def test_each_further_refused_hand_in_doubles_the_hold(self):
        hold = questers.TURN_IN_RETRY_MINUTES
        four = (1000, 990, 980)
        held = self._refused_hand_ins(four + (hold + 30,))
        self.assertNotEqual(self._move_with(held), (classquest.TURN_IN, 1))
        due = self._refused_hand_ins(four + (2 * hold + 1,))
        self.assertEqual(self._move_with(due), (classquest.TURN_IN, 1))

    def test_a_hand_in_refused_less_than_three_times_is_tried_again_at_once(self):
        tried = self._refused_hand_ins((30, 20, 10))[1:]
        self.assertEqual(self._move_with(tried), (classquest.TURN_IN, 1))

    # mod-overseer#19: quest 45, Discover Rolf's Fate, has no
    # creature ender; a world that names nothing to hand it in to refuses the
    # hand-in with "retryable":false. That is "could not", not "did not yet".
    NO_HOLDER = "the world names no creature and no object that takes that quest in"

    @staticmethod
    def _turn_in_row(reason, retryable, age=10, name="Mirra"):
        result = '{"outcome":"refused","reason":"%s","holder":"none"' % reason
        if retryable is not None:
            result += ',"retryable":%s' % ("true" if retryable else "false")
        return {
            "id": 1,
            "target_name": name,
            "command": "turnin quest:1",
            "source": guildjobs.source_for(questers.ACTION, name),
            "status": "error",
            "result": result + "}",
            "age": age,
        }

    def _plan_rows(self, *rows):
        return questers.plan(
            world(),
            mirra(quest_log={1: questers.STATUS_COMPLETE}),
            questers.Clock(),
            0.0,
            tried=questers.attempts(rows),
        )

    def test_a_never_retryable_hand_in_is_could_not_on_the_first_refusal(self):
        p = self._plan_rows(self._turn_in_row(self.NO_HOLDER, False))
        self.assertEqual(
            [(b.quest, b.reason) for b in p.broken],
            [(1, questers.CANNOT_TURN_IN + ": " + self.NO_HOLDER)],
        )
        self.assertNotEqual(questers.CANNOT_TURN_IN, questers.REFUSED_TURN_IN)

    def test_a_never_retryable_hand_in_is_not_asked_again(self):
        p = self._plan_rows(self._turn_in_row(self.NO_HOLDER, False))
        self.assertIsNotNone(p.move)
        self.assertNotEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 1))
        self.assertNotEqual(p.move.kind, classquest.ABANDON)

    def test_a_retryable_or_unmarked_refusal_keeps_the_three_strike_rule(self):
        # A world image older than mod-overseer#19 writes no "retryable" on a
        # quest row: absent is not false.
        for retryable in (True, None):
            p = self._plan_rows(self._turn_in_row(self.NO_HOLDER, retryable))
            self.assertEqual(p.broken, (), retryable)
            self.assertEqual(
                (p.move.kind, p.move.quest), (classquest.TURN_IN, 1), retryable
            )

    def test_a_never_retryable_refusal_about_the_log_is_not_could_not(self):
        p = self._plan_rows(self._turn_in_row("already turned in", False))
        self.assertEqual(p.broken, ())

    def test_another_quester_s_never_retryable_refusal_does_not_count(self):
        p = self._plan_rows(self._turn_in_row(self.NO_HOLDER, False, name="Pindle"))
        self.assertEqual(p.broken, ())
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 1))

    def test_no_pass_ever_sends_an_abandon_for_a_complete_quest(self):
        # Every way a held quest can be broken, with the quest complete in the
        # log, over four hours of passes: none of them is a drop (#1085).
        refused = tuple(
            questers.Attempt(
                "Mirra", "turnin quest:1", "error", reason="nope", age_minutes=m
            )
            for m in (30, 20, 10)
        )
        cases = [
            (world(drop={1003}), {3: 1}, frozenset(), ()),
            (world(), {1: 1}, frozenset({1}), ()),
            (world(), {1: 1}, frozenset(), refused),
            (world(), {1: 1, 2: 1}, frozenset({1, 2}), refused),
        ]
        for cat, log, broken, tried in cases:
            clock = questers.Clock()
            for minute in range(0, 241, 5):
                p = questers.plan(
                    cat,
                    mirra(quest_log=log),
                    clock,
                    minute * 60.0,
                    broken=broken,
                    tried=tried,
                )
                kind = p.move.kind if p.move is not None else None
                self.assertNotEqual(kind, classquest.ABANDON, (log, broken, minute))

    def test_a_quest_already_broken_is_dropped_and_never_taken_again(self):
        p = questers.plan(
            world(),
            mirra(quest_log={1: 3}),
            questers.Clock(),
            0.0,
            broken=frozenset({1}),
        )
        self.assertEqual((p.move.kind, p.move.quest), (classquest.ABANDON, 1))
        p = questers.plan(
            world(), mirra(x=0.0), questers.Clock(), 0.0, broken=frozenset({1})
        )
        self.assertNotEqual(p.move.quest, 1)


if __name__ == "__main__":
    unittest.main()


def object_ended(qid, entry, guid=0, x=0.0, y=0.0, map_id=0, name="Wanted Poster"):
    """An ENDERS_SQL gameobject row: the object named to take the quest, with
    one of its spawns (guid 0: the object has no spawn in the world)."""
    return {
        "quest": qid,
        "kind": "gameobject",
        "entry": entry,
        "guid": guid,
        "map_id": map_id,
        "x": x,
        "y": y,
        "name": name if guid else "",
    }


def object_world(*ends):
    """world() with quest 40, of Elwynn, whose only ender is gameobject 270."""
    return world(
        extra_quests=[quest(40, ELWYNN, 4, title="Bitter Rivals")],
        extra_givers=[giver(40, "start", 1003, 102, 400, 0)],
        extra_starts=[started(40, 102)],
        extra_ends=list(ends),
    )


class AGameobjectEnder(unittest.TestCase):
    """A complete quest whose only ender is a gameobject (#1594)."""

    def test_a_complete_quest_is_handed_in_at_the_object_spawn(self):
        cat = object_world(object_ended(40, 270, guid=5001, x=300.0))
        member = mirra(quest_log={40: 1})
        p = questers.plan(cat, member, questers.Clock(), 0.0)
        self.assertEqual(p.broken, ())
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 40))
        self.assertEqual(p.move.spot.guid, 5001)
        self.assertIn("Wanted Poster", p.move.said)
        step = questers.step_for(member, p.move, 0, cat.quest(40))
        self.assertTrue(step.walk.command.startswith("walk-to-spawn gameobject:5001"))
        self.assertEqual([r.command for r in step.rows], ["turnin quest:40"])

    def test_the_nearest_object_spawn_is_walked_to(self):
        cat = object_world(
            object_ended(40, 270, guid=5001, x=900.0),
            object_ended(40, 270, guid=5002, x=200.0),
        )
        p = questers.plan(cat, mirra(quest_log={40: 1}), questers.Clock(), 0.0)
        self.assertEqual(p.move.spot.guid, 5002)

    def test_a_creature_ender_walk_is_still_a_creature_walk(self):
        member = mirra(quest_log={3: 1})
        p = questers.plan(world(), member, questers.Clock(), 0.0)
        self.assertEqual(p.move.kind, classquest.TURN_IN)
        step = questers.step_for(member, p.move, 0, world().quest(3))
        self.assertTrue(step.walk.command.startswith("walk-to-spawn creature:1003"))

    def test_an_object_with_no_spawn_breaks_the_quest_with_its_reason(self):
        cat = object_world(object_ended(40, 270))
        p = questers.plan(cat, mirra(quest_log={40: 1}), questers.Clock(), 0.0)
        self.assertEqual(
            [(b.quest, b.reason) for b in p.broken],
            [(40, questers.OBJECT_ENDER_MISSING)],
        )
        self.assertNotEqual(p.move.kind, classquest.ABANDON)
        self.assertNotEqual(p.move.quest, 40)

    def _object_walk_rows(self, member, reason=questers.GONE):
        """The command log rows the realm writes for the hand-in walk this
        plan sends, ended by the module with `reason`, read as the bridge reads
        them (questers.attempts)."""
        cat = object_world(object_ended(40, 270, guid=5001, x=300.0))
        p = questers.plan(cat, member, questers.Clock(), 0.0)
        step = questers.step_for(member, p.move, 0, cat.quest(40))
        row = {
            "id": 9,
            "target_name": member.name,
            "command": step.walk.command,
            "source": step.walk.source,
            "status": "error",
            "result": '{"outcome":"refused","reason":"%s","retryable":true}' % reason,
            "age": 5,
        }
        return cat, questers.attempts([row])

    def test_every_object_spawn_gone_breaks_the_quest_with_its_reason(self):
        member = mirra(quest_log={40: 1})
        cat, tried = self._object_walk_rows(member)
        self.assertEqual(
            [(a.spawn, a.spawn_kind) for a in tried], [(5001, questers.OBJECT_KIND)]
        )
        p = questers.plan(cat, member, questers.Clock(), 0.0, tried=tried)
        self.assertEqual(
            [(b.quest, b.reason) for b in p.broken],
            [(40, questers.OBJECT_ENDER_MISSING)],
        )
        self.assertNotEqual(p.move.kind, classquest.ABANDON)

    def test_a_gone_object_spawn_never_stands_for_a_creature_spawn(self):
        member = mirra(quest_log={40: 1})
        _cat, tried = self._object_walk_rows(member)
        self.assertEqual(questers.gone_spawns("Mirra", tried), frozenset())
        self.assertEqual(
            questers.gone_spawns("Mirra", tried, questers.OBJECT_KIND),
            frozenset({5001}),
        )

    def test_a_gone_creature_spawn_never_hides_an_object_spawn(self):
        cat = object_world(object_ended(40, 270, guid=1003, x=300.0))
        tried = questers.attempts([walk_row(questers.GONE, 5, spawn=1003)])
        p = questers.plan(
            cat, mirra(quest_log={40: 1}), questers.Clock(), 0.0, tried=tried
        )
        self.assertNotIn(40, [b.quest for b in p.broken])
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 40))

    def test_a_hand_in_the_world_keeps_refusing_is_broken_and_never_dropped(self):
        cat = object_world(object_ended(40, 270, guid=5001, x=300.0))
        tried = [
            questers.Attempt(
                "Mirra",
                "turnin quest:40",
                "error",
                reason="no quest ender in reach",
                age_minutes=10 * i,
            )
            for i in range(questers.FAILS_BEFORE_BROKEN)
        ]
        p = questers.plan(
            cat, mirra(quest_log={40: 1}), questers.Clock(), 0.0, tried=tried
        )
        self.assertEqual([b.quest for b in p.broken], [40])
        self.assertTrue(p.broken[0].reason.startswith(questers.REFUSED_TURN_IN))
        p = questers.plan(
            cat,
            mirra(quest_log={40: 1}),
            questers.Clock(),
            0.0,
            tried=tried,
            broken=frozenset({40}),
        )
        self.assertNotEqual(p.move.kind, classquest.ABANDON)

    def test_a_quest_held_broken_by_the_ledger_is_never_dropped(self):
        cat = object_world(object_ended(40, 270))
        p = questers.plan(
            cat,
            mirra(quest_log={40: 1}),
            questers.Clock(),
            0.0,
            broken=frozenset({40}),
        )
        self.assertNotEqual(p.move.kind, classquest.ABANDON)


class ASummonedObjectEnder(unittest.TestCase):
    """An incomplete quest one of whose enders is a gameobject with no static
    spawn: a script or an event summons it, so the quest is not judged on its
    ender and is never dropped for it (#1606)."""

    def test_an_incomplete_quest_is_not_broken_or_dropped(self):
        cat = object_world(object_ended(40, 270))
        p = questers.plan(cat, mirra(quest_log={40: 3}), questers.Clock(), 0.0)
        self.assertNotIn(40, [b.quest for b in p.broken])
        self.assertFalse(
            p.move is not None
            and (p.move.kind, p.move.quest) == (classquest.ABANDON, 40)
        )

    def test_a_named_creature_not_spawned_does_not_judge_it_either(self):
        cat = object_world(object_ended(40, 270), ended(40, 999))
        p = questers.plan(cat, mirra(quest_log={40: 3}), questers.Clock(), 0.0)
        self.assertNotIn(40, [b.quest for b in p.broken])

    def test_it_still_stalls_after_two_hours_of_play(self):
        cat = object_world(object_ended(40, 270))
        clock = questers.Clock()
        reasons = []
        for minute in range(0, 2 * 60 + 10, 5):
            p = questers.plan(
                cat, mirra(quest_log={40: 3}), clock, minute * 60.0, last_quest=40
            )
            reasons += [b.reason for b in p.broken if b.quest == 40]
        self.assertTrue(reasons and reasons[-1].startswith(questers.STALLED))

    def test_an_incomplete_quest_whose_object_spawns_are_gone_is_still_broken(self):
        member = mirra(quest_log={40: 3})
        cat = object_world(object_ended(40, 270, guid=5001, x=300.0))
        tried = questers.attempts(
            [
                {
                    "id": 9,
                    "target_name": "Mirra",
                    "command": "walk-to-spawn gameobject:5001",
                    "source": "guildjobs:quester-walk:Mirra",
                    "status": "error",
                    "result": '{"outcome":"refused","reason":"%s","retryable":true}'
                    % questers.GONE,
                    "age": 5,
                }
            ]
        )
        p = questers.plan(cat, member, questers.Clock(), 0.0, tried=tried)
        self.assertEqual(
            [(b.quest, b.reason) for b in p.broken],
            [(40, questers.OBJECT_ENDER_MISSING)],
        )

    def test_a_complete_one_is_still_recorded_and_never_dropped(self):
        cat = object_world(object_ended(40, 270))
        p = questers.plan(cat, mirra(quest_log={40: 1}), questers.Clock(), 0.0)
        self.assertEqual([b.quest for b in p.broken], [40])
        self.assertNotEqual(p.move.kind, classquest.ABANDON)
