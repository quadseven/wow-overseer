"""Hold and loop clocks survive a bridge restart (#3226)."""

from __future__ import annotations

import unittest

import holdclock
import profloop
import townerrand


class Store:
    """A stand-in for the memo store, shared across 'processes'."""

    def __init__(self):
        self.rows = {}

    def read(self, kind):
        return {s: v for (k, s), v in self.rows.items() if k == kind}

    def upsert(self, kind, subject, value, since, expires):
        self.rows[(kind, subject)] = (value, since)

    def delete(self, kind, subject):
        self.rows.pop((kind, subject), None)


def process(store, mono, wall, kind="gear"):
    """A fresh process: its monotonic clock starts at `mono`."""
    box = {"mono": mono, "wall": wall}
    clocks = holdclock.Clocks(
        kind,
        store.read,
        store.upsert,
        store.delete,
        mono=lambda: box["mono"],
        wall=lambda: box["wall"],
    )
    return clocks, box


class ClocksRestart(unittest.TestCase):
    def test_restart_keeps_each_members_cooldown(self):
        store = Store()
        first, box = process(store, mono=1000.0, wall=5_000_000.0)
        first.setdefault(("Bork", "Grug"), box["mono"])
        box["mono"] += 600.0
        box["wall"] += 600.0
        first.setdefault(("Og",), box["mono"])
        # restart: a new process, monotonic clock near zero, 300s later
        second, box2 = process(store, mono=5.0, wall=5_000_900.0)
        held = box2["mono"] - second[("Bork", "Grug")]
        self.assertAlmostEqual(held, 900.0)
        self.assertAlmostEqual(box2["mono"] - second[("Og",)], 300.0)

    def test_setdefault_keeps_the_stored_start(self):
        store = Store()
        first, box = process(store, 1000.0, 5_000_000.0)
        first.setdefault(("Grug",), box["mono"])
        second, box2 = process(store, 2.0, 5_000_100.0)
        self.assertAlmostEqual(
            second.setdefault(("Grug",), box2["mono"]), box2["mono"] - 100.0
        )

    def test_pop_clears_the_store(self):
        store = Store()
        first, box = process(store, 1000.0, 5_000_000.0)
        first.setdefault(("Grug",), box["mono"])
        self.assertIsNotNone(first.pop(("Grug",), None))
        second, _ = process(store, 2.0, 5_000_100.0)
        self.assertIsNone(second.get(("Grug",)))
        self.assertNotIn(("Grug",), second)

    def test_unreadable_store_is_an_empty_clock(self):
        def broken(kind):
            raise RuntimeError("down")

        clocks = holdclock.Clocks("gear", broken, lambda *a: None, lambda *a: None)
        self.assertIsNone(clocks.get(("Grug",)))

    def test_an_unreadable_store_is_logged(self):
        def broken(kind):
            raise RuntimeError("down")

        clocks = holdclock.Clocks("gear", broken, lambda *a: None, lambda *a: None)
        with self.assertLogs("holdclock", level="WARNING") as logs:
            clocks.load()
        self.assertIn("could not be read", logs.output[0])
        self.assertIn("RuntimeError: down", logs.output[0])

    def test_a_failed_write_is_logged_and_the_clock_still_runs(self):
        def refuse(*a):
            raise RuntimeError("write refused")

        clocks = holdclock.Clocks(
            "gear",
            lambda kind: {},
            refuse,
            refuse,
            mono=lambda: 50.0,
            wall=lambda: 100.0,
        )
        with self.assertLogs("holdclock", level="WARNING") as logs:
            clocks[("Grug",)] = 40.0
        self.assertEqual(clocks[("Grug",)], 40.0)
        self.assertIn("Grug was not stored", logs.output[0])
        self.assertIn("RuntimeError: write refused", logs.output[0])
        with self.assertLogs("holdclock", level="WARNING") as logs:
            self.assertEqual(clocks.pop(("Grug",)), 40.0)
        self.assertIn("Grug was not cleared", logs.output[0])
        self.assertNotIn(("Grug",), clocks)

    def test_never_later_than_now(self):
        # wall clock stepped back: the reading is clamped to now
        self.assertEqual(holdclock.to_mono(200.0, 50.0, 100.0), 50.0)


class LoopState(unittest.TestCase):
    def test_state_round_trips_across_a_restart(self):
        state = profloop.State(
            phase=profloop.TOWN,
            since=900.0,
            asserted=950.0,
            town_seen=True,
            entered=(("Bork", 2),),
            fruitless=("Og",),
            fruitless_stamps=(("Og", 800.0),),
            queued_since=700.0,
            yielded=True,
        )
        data = holdclock.state_to_wall(state, 1000.0, 5_000_000.0)
        back = holdclock.state_from_wall(profloop.State, data, 10.0, 5_000_100.0)
        self.assertEqual(back.phase, profloop.TOWN)
        self.assertAlmostEqual(10.0 - back.since, 200.0)
        self.assertAlmostEqual(10.0 - back.asserted, 150.0)
        self.assertAlmostEqual(10.0 - back.queued_since, 400.0)
        self.assertAlmostEqual(10.0 - back.fruitless_stamps[0][1], 300.0)
        self.assertEqual(back.fruitless, ("Og",))
        self.assertTrue(back.town_seen and back.yielded)

    def test_unset_times_stay_unset(self):
        data = holdclock.state_to_wall(profloop.State(), 1000.0, 5_000_000.0)
        back = holdclock.state_from_wall(profloop.State, data, 3.0, 5_000_010.0)
        self.assertEqual(
            (back.since, back.asserted, back.queued_since), (0.0, 0.0, 0.0)
        )

    def test_garbage_is_none(self):
        self.assertIsNone(holdclock.state_from_wall(profloop.State, {}, 1.0, 2.0))


def errands(store, mono, wall):
    """A fresh process's town errand table; its monotonic clock starts at `mono`."""
    box = {"mono": mono, "wall": wall}
    table = holdclock.ErrandEnds(
        holdclock.TOWN_ERRAND_KIND,
        store.read,
        store.upsert,
        store.delete,
        townerrand.State,
        mono=lambda: box["mono"],
        wall=lambda: box["wall"],
    )
    return table, box


class ErrandCooldownRestart(unittest.TestCase):
    """The town errand's cooldown resumes after a restart instead of lapsing."""

    KEY = ("Bork", "Grug")

    def test_restart_keeps_the_errands_cooldown(self):
        store = Store()
        first, box = errands(store, 1000.0, 5_000_000.0)
        done, _ = townerrand.end(townerrand.start(900.0, {}, "x"), 1000.0, "done")
        first[self.KEY] = done
        # restart 600 seconds later, monotonic clock near zero
        second, box2 = errands(store, 4.0, 5_000_600.0)
        back = second.get(self.KEY, townerrand.State())
        self.assertFalse(back.active)
        self.assertAlmostEqual(box2["mono"] - back.ended, 600.0)
        why = townerrand.should_start(
            back,
            now=box2["mono"],
            in_run=False,
            mail_gear={},
            facts={},
            supply_gaps=("Og drink",),
        )
        self.assertEqual(why, "")

    def test_a_run_since_the_end_and_an_unlanded_walk_are_kept(self):
        store = Store()
        first, _ = errands(store, 1000.0, 5_000_000.0)
        first[self.KEY] = townerrand.State(ended=990.0, ran_since=True, unlanded=True)
        second, _ = errands(store, 4.0, 5_000_010.0)
        back = second[self.KEY]
        self.assertTrue(back.ran_since and back.unlanded)

    def test_a_family_with_no_errand_yet_stores_nothing(self):
        store = Store()
        first, _ = errands(store, 1000.0, 5_000_000.0)
        first[self.KEY] = townerrand.State()
        self.assertEqual(store.rows, {})
        second, _ = errands(store, 4.0, 5_000_010.0)
        self.assertNotIn(self.KEY, second)

    def test_an_unchanged_end_is_written_once(self):
        store = Store()
        writes = []
        first, _ = errands(store, 1000.0, 5_000_000.0)
        first._upsert = lambda *a: writes.append(a)
        for _ in range(3):
            first[self.KEY] = townerrand.State(ended=990.0)
        self.assertEqual(len(writes), 1)

    def test_a_restored_end_is_not_written_back(self):
        store = Store()
        first, _ = errands(store, 1000.0, 5_000_000.0)
        first[self.KEY] = townerrand.State(ended=990.0)
        second, _ = errands(store, 4.0, 5_000_010.0)
        writes = []
        second._upsert = lambda *a: writes.append(a)
        back = second[self.KEY]
        second[self.KEY] = townerrand.State(ended=back.ended)
        self.assertEqual(writes, [])

    def test_a_live_errand_in_this_process_wins_over_the_store(self):
        store = Store()
        first, _ = errands(store, 1000.0, 5_000_000.0)
        first[self.KEY] = townerrand.State(ended=990.0)
        second, _ = errands(store, 4.0, 5_000_010.0)
        live = townerrand.start(3.0, {}, "x")
        second[self.KEY] = live
        self.assertIs(second.get(self.KEY), live)
        self.assertEqual([s for s in second.values() if s.active], [live])

    def test_an_unreadable_store_is_an_empty_table(self):
        def broken(kind):
            raise RuntimeError("down")

        table = holdclock.ErrandEnds(
            holdclock.TOWN_ERRAND_KIND,
            broken,
            lambda *a: None,
            lambda *a: None,
            townerrand.State,
        )
        with self.assertLogs("holdclock", level="WARNING"):
            self.assertIsNone(table.get(self.KEY))
        self.assertEqual(list(table.items()), [])

    def test_the_bridge_keeps_its_errands_in_the_store(self):
        from test_guildsocial_bridge import bridge

        table = bridge._TOWN_ERRANDS
        self.assertIsInstance(table, holdclock.ErrandEnds)
        self.assertEqual(table._kind, holdclock.TOWN_ERRAND_KIND)
        self.assertIs(table._make, townerrand.State)

    def test_an_unreadable_row_is_logged_and_the_rest_restored(self):
        store = Store()
        store.rows[(holdclock.TOWN_ERRAND_KIND, "Og")] = ("junk", 1.0)
        store.rows[(holdclock.TOWN_ERRAND_KIND, "Ugga")] = ({"ended": "x"}, 1.0)
        first, _ = errands(store, 1000.0, 5_000_000.0)
        first[self.KEY] = townerrand.State(ended=990.0)
        second, _ = errands(store, 4.0, 5_000_010.0)
        with self.assertLogs("holdclock", level="WARNING") as logs:
            self.assertIn(self.KEY, second)
        self.assertEqual(len(logs.output), 2)
        self.assertIn("Og", logs.output[0] + logs.output[1])
        self.assertNotIn(("Og",), second)

    def test_the_kind_fits_the_memo_column(self):
        self.assertLessEqual(len(holdclock.TOWN_ERRAND_KIND), 32)


if __name__ == "__main__":
    unittest.main()
