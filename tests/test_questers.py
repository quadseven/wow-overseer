"""The questers' play (questers.py, #924): every quest in reach, zone by zone,
and a quest that stops progressing is broken with its reason."""

import unittest

import classquest
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
        giver(20, "start", 1020, 120, 3000, 0),
        giver(20, "end", 1020, 120, 3000, 0),
        giver(21, "start", 1020, 120, 3000, 0),
        giver(21, "end", 1020, 120, 3000, 0),
        giver(30, "start", 1030, 130, 2000, 0),
        giver(30, "end", 1030, 130, 2000, 0),
        giver(31, "start", 1030, 130, 2000, 0),
        giver(31, "end", 1030, 130, 2000, 0),
    ] + list(extra_givers)
    spawns = [spawn(2001, 200, 150, 0), spawn(2002, 201, 250, 0, level=3)]
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
            if p.move.quest in {20, 21, 30, 31}:
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
        p = questers.plan(cat, mirra(quest_log={3: 1}), questers.Clock(), 0.0)
        self.assertEqual(
            [(b.quest, b.reason) for b in p.broken], [(3, questers.ENDER_MISSING)]
        )
        self.assertEqual(p.move.kind, classquest.ABANDON)

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
        # quest goes to turn-in at once and is never abandoned again.
        tried = [
            questers.Attempt(
                "Mirra",
                "turnin quest:1",
                "error",
                reason="not ready",
                age_minutes=m,
            )
            for m in (30, 20, 10)
        ] + [
            questers.Attempt(
                "Mirra",
                "abandon quest:1",
                "error",
                reason="it is complete; hand it in",
                age_minutes=5,
            )
        ]
        p = questers.plan(
            world(), mirra(quest_log={1: 1}), questers.Clock(), 0.0, tried=tried
        )
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 1))

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
