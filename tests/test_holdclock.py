"""Hold and loop clocks survive a bridge restart (#3226)."""

from __future__ import annotations

import unittest

import holdclock
import profloop


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


if __name__ == "__main__":
    unittest.main()
