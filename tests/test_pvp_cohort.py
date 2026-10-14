"""A battleground is queued as a full cohort (#959): members who want PvP for
an upgrade queue only when each side reaches the world's minimum per team,
together, in one pass; idle fillers close a small gap; a queue that did not pop
leaves together and cools down."""

import unittest

import guildjobs
import pvpgear

WSG_ALLIANCE_OFFICER = 14753
ALLIANCE, HORDE = "Alliance", "Horde"


def offer():
    return pvpgear.Offer(
        19325,
        WSG_ALLIANCE_OFFICER,
        5000,
        {"item_name": "Don Julio's Band"},
        frozenset({0}),
    )


def wanter(name, level=60, faction=ALLIANCE, idle=True):
    up = pvpgear.Upgrade(19325, "Don Julio's Band", 10.0, 1.0, offer())
    return pvpgear.Seeker(name, "Cave", level, 0, up, faction, idle)


def filler(name, level=60, faction=ALLIANCE, idle=True):
    return pvpgear.Seeker(name, "Cave", level, 0, None, faction, idle)


def rows(prefix, count, make=wanter, **kw):
    return [make("%s%02d" % (prefix, i), **kw) for i in range(count)]


def run(seekers, minimum=10, recent=(), maps=None, minimums=None):
    aims = pvpgear.plan_aims(seekers)
    maps = maps or {}
    moves = {
        n: pvpgear.next_move(a, maps.get(n, 0), False, recent) for n, a in aims.items()
    }
    return pvpgear.gate(
        aims,
        moves,
        seekers,
        {"wsg": minimum} if minimums is None else minimums,
        recent,
        maps,
    )


def queuing(moves):
    return sorted(n for n, m in moves.items() if m.kind == pvpgear.QUEUE)


def recent_row(name, command, age, status="queued"):
    return guildjobs.Recent(name, "pvp", age, status, command=command)


class TheMinimumComesFromTheWorld(unittest.TestCase):
    def test_a_fake_world_row_sets_the_minimum_per_team(self):
        rows_ = [{"id": 2, "minimum": 7}, {"id": 3, "minimum": 5}]
        got = pvpgear.minimums_from_rows(rows_, {})
        self.assertEqual({"wsg": 7, "ab": 5}, got)

    def test_the_server_override_wins_when_set(self):
        got = pvpgear.minimums_from_rows(
            [{"id": 2, "minimum": 10}], {"PVP_BG_MIN_PER_TEAM": "wsg=4, junk=9"}
        )
        self.assertEqual({"wsg": 4}, got)

    def test_the_gate_reads_the_row_not_a_constant(self):
        seekers = rows("A", 7)
        for minimum, queues in ((7, 7), (8, 0)):
            got = pvpgear.minimums_from_rows([{"id": 2, "minimum": minimum}], {})
            _, moves, _ = run(seekers, minimums=got)
            self.assertEqual(queues, len(queuing(moves)))

    def test_an_unread_minimum_queues_nobody(self):
        _, moves, (cohort,) = run(rows("A", 12), minimums={})
        self.assertEqual([], queuing(moves))
        self.assertIn("not known", cohort.line)


class TheCohort(unittest.TestCase):
    def test_six_of_ten_queue_nobody_and_say_the_count(self):
        _, moves, (cohort,) = run(rows("A", 6))
        self.assertEqual([], queuing(moves))
        self.assertEqual({pvpgear.GATHERING}, {m.kind for m in moves.values()})
        self.assertEqual("Warsong Gulch 6/10, waiting for 4 more", cohort.line)
        self.assertIn("6/10, waiting for 4 more", moves["A00"].said)

    def test_ten_of_ten_all_queue_in_one_pass(self):
        seekers = rows("A", 10)
        aims, moves, (cohort,) = run(seekers)
        self.assertEqual(sorted(s.name for s in seekers), queuing(moves))
        self.assertEqual("Warsong Gulch 10/10, queueing together", cohort.line)
        self.assertIn("10/10", aims["A00"].cohort)

    def test_a_busy_member_is_not_counted(self):
        seekers = rows("A", 9) + [wanter("Zed", idle=False)]
        _, moves, _ = run(seekers)
        self.assertEqual([], queuing(moves))

    def test_another_bracket_is_not_counted(self):
        seekers = rows("A", 9) + [wanter("Low", level=25)]
        _, moves, _ = run(seekers)
        self.assertEqual([], queuing(moves))

    def test_the_other_faction_is_a_side_of_its_own(self):
        seekers = rows("A", 10) + rows("H", 3, faction=HORDE)
        _, moves, _ = run(seekers)
        self.assertEqual([], queuing(moves))


class Fillers(unittest.TestCase):
    def test_idle_fillers_close_a_gap_of_two(self):
        seekers = rows("A", 8) + rows("F", 5, filler)
        aims, moves, _ = run(seekers)
        self.assertEqual(10, len(queuing(moves)))
        fills = sorted(n for n, a in aims.items() if a.filler)
        self.assertEqual(["F00", "F01"], fills)
        self.assertEqual({pvpgear.QUEUE}, {moves[n].kind for n in fills})

    def test_fillers_are_not_queued_for_a_gap_of_eight(self):
        seekers = rows("A", 2) + rows("F", 5, filler)
        aims, moves, _ = run(seekers)
        self.assertEqual([], queuing(moves))
        self.assertFalse(any(a.filler for a in aims.values()))

    def test_a_busy_filler_is_never_used(self):
        seekers = rows("A", 9) + rows("F", 1, filler, idle=False)
        _, moves, _ = run(seekers)
        self.assertEqual([], queuing(moves))

    def test_a_filler_never_buys_or_queues_alone(self):
        _, moves, _ = run(rows("F", 12, filler))
        self.assertEqual({}, moves)


class TheWait(unittest.TestCase):
    def queued(self, age, extra=()):
        seekers = rows("A", 10) + list(extra)
        recent = [recent_row(s.name, "bg-queue wsg", age) for s in seekers[:10]]
        return seekers, recent

    def test_a_queue_inside_the_wait_keeps_waiting(self):
        seekers, recent = self.queued(5)
        _, moves, _ = run(seekers, recent=recent)
        self.assertEqual({pvpgear.WAITING}, {m.kind for m in moves.values()})

    def test_a_queue_past_the_wait_stays_held_and_is_not_left(self):
        seekers, recent = self.queued(pvpgear.QUEUE_MINUTES + 5)
        _, moves, _ = run(seekers, recent=recent)
        self.assertEqual({pvpgear.WAITING}, {m.kind for m in moves.values()})

    def test_no_guild_job_writes_a_leave_for_a_queue_that_did_not_pop(self):
        seekers, recent = self.queued(20)
        aims, moves, _ = run(seekers, recent=recent)
        members = [
            guildjobs.Member(
                name=s.name, guild="Cave", role=guildjobs.RAIDER, level=60,
                online=True, map_id=0, x=0.0, y=0.0, eligible=True,
            )  # fmt: skip
            for s in seekers
        ]
        plan = guildjobs.plan(
            members, pvp={n: (aims[n], moves[n]) for n in moves}, recent=recent
        )
        commands = [r.command for step in plan.steps for r in step.rows]
        self.assertFalse([c for c in commands if c.startswith("bg-leave")])

    def test_a_filler_in_the_queue_is_held_with_them(self):
        seekers = rows("A", 8) + rows("F", 2, filler)
        recent = [recent_row(s.name, "bg-queue wsg", 20) for s in seekers]
        _, moves, _ = run(seekers, recent=recent)
        self.assertEqual({pvpgear.WAITING}, {m.kind for m in moves.values()})
        self.assertEqual(10, len(moves))

    def test_a_cohort_that_left_cools_down_then_may_queue_again(self):
        seekers = rows("A", 10)
        left = [recent_row(s.name, "bg-leave wsg", 5, "already") for s in seekers]
        _, moves, _ = run(seekers, recent=left)
        self.assertEqual({pvpgear.COOLING}, {m.kind for m in moves.values()})
        old = [
            recent_row(s.name, "bg-leave wsg", pvpgear.LEAVE_COOLDOWN_MINUTES + 1,
                       "already")
            for s in seekers
        ]  # fmt: skip
        _, moves, _ = run(seekers, recent=old)
        self.assertEqual(10, len(queuing(moves)))

    def test_a_refused_or_undelivered_leave_does_not_cool_a_member_down(self):
        for status in ("error", "unchanged", "delivered", "pending", ""):
            with self.subTest(status=status):
                row = recent_row("A00", "bg-leave wsg", 5, status)
                self.assertFalse(pvpgear.left_lately("A00", [row]))

    def test_an_accepted_leave_counts(self):
        for status in ("queued", "already"):
            with self.subTest(status=status):
                row = recent_row("A00", "bg-leave wsg", 5, status)
                self.assertTrue(pvpgear.left_lately("A00", [row]))

    def test_a_member_that_left_does_not_fill_a_gap(self):
        seekers = rows("A", 9) + rows("F", 1, filler)
        left = [recent_row("F00", "bg-leave wsg", 5, "already")]
        _, moves, _ = run(seekers, recent=left)
        self.assertEqual([], queuing(moves))


class TheChat(unittest.TestCase):
    def test_the_queue_line_carries_the_count(self):
        aims, moves, _ = run(rows("A", 10))
        lines = pvpgear.chat_lines(moves, aims, ())
        self.assertTrue(lines)
        self.assertTrue(all("Warsong Gulch 10/10" in text for _, text in lines[:1]))

    def test_a_short_cohort_says_its_count_once_per_change(self):
        _, _, cohorts = run(rows("A", 6))
        said: dict = {}
        (line,) = pvpgear.gathering_lines(cohorts, said)
        self.assertIn("Warsong Gulch 6/10, waiting for 4 more", line[1])
        self.assertEqual([], pvpgear.gathering_lines(cohorts, said))
        _, _, cohorts = run(rows("A", 7))
        self.assertEqual(1, len(pvpgear.gathering_lines(cohorts, said)))

    def test_a_gathering_member_keeps_its_ordinary_job_and_names_the_count(self):
        aims, moves, _ = run(rows("A", 6))
        member = guildjobs.Member(
            name="A00", guild="Cave", role=guildjobs.RAIDER, level=60,
            online=True, map_id=0, x=0.0, y=0.0, eligible=True,
        )  # fmt: skip
        plan = guildjobs.plan([member], pvp={"A00": (aims["A00"], moves["A00"])})
        self.assertFalse(any(s.action == "pvp" for s in plan.steps))
        self.assertIn("6/10, waiting for 4 more", " ".join(plan.notes))


if __name__ == "__main__":
    unittest.main()
