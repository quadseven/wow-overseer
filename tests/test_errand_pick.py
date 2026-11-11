"""A bag-room town errand outranks a regroup, a fetch and a training stop.

A bag-room town errand's walk failed to land because the family leader stood
still: the module's static order ranks regroup, fetch, hearth and training
above an errand, and the intent choice is paused where no model key is set, so
nothing ever lifted the errand over them. These tests run on fake rows; none touches a database.
"""

import asyncio
import pathlib
import types
import unittest

from test_campaign_queue import _load

import jev_family_intent as jfi  # noqa: E402
import townerrand  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

AIM = "at:1:1630.5,-4420.1,9.7"


def row(table, **kw):
    raw = dict(
        leader_name="Zug",
        family="Zug",
        current_kind="regroup",
        current_owner="regroup",
        current_target="Uzza",
        current_for=40,
        on_the_table=table,
        goal_yards=403,
        members_state="Uzza|walking back to the leader|1030",
        module_age=10,
        chosen_kind="",
        chosen_target="",
        chosen_by="",
        changes=1,
    )
    raw.update(kw)
    return jfi.row_from_db(raw)


ERRAND = "errand|town trip|" + AIM


class ThePolicy(unittest.TestCase):
    def test_each_outranking_kind_loses_to_the_errand(self):
        for outranker in (
            "regroup|regroup|Uzza",
            "fetch|fetch|Oz",
            "training|training stop|Hukk",
        ):
            with self.subTest(outranker):
                pick = jfi.errand_pick(row(outranker + "\n" + ERRAND), True)
                self.assertIsNotNone(pick)
                self.assertEqual("errand:" + AIM, pick.ask.option)
                self.assertEqual(outranker.split("|")[0], pick.outranked.kind)

    def test_the_vendor_walk_is_the_errand_too(self):
        pick = jfi.errand_pick(
            row("regroup|regroup|Uzza\neconomy|travel column|vendor"), True
        )
        self.assertEqual("economy:vendor", pick.ask.option)

    def test_the_errand_ask_ranks_highest_among_errand_kinds(self):
        pick = jfi.errand_pick(
            row("regroup|regroup|Uzza\neconomy|travel column|vendor\n" + ERRAND), True
        )
        self.assertEqual("errand", pick.ask.kind)

    def test_no_active_bag_room_errand_picks_nothing(self):
        self.assertIsNone(
            jfi.errand_pick(row("regroup|regroup|Uzza\n" + ERRAND), False)
        )

    def test_an_errand_not_on_the_table_picks_nothing(self):
        self.assertIsNone(jfi.errand_pick(row("regroup|regroup|Uzza"), True))

    def test_nothing_outranks_it_picks_nothing(self):
        self.assertIsNone(jfi.errand_pick(row(ERRAND + "\nquest|quest drive|"), True))

    def test_a_dungeon_run_or_an_operator_order_still_comes_first(self):
        for kind in ("dungeon", "operator"):
            with self.subTest(kind):
                self.assertIsNone(
                    jfi.errand_pick(
                        row("regroup|regroup|Uzza\n" + ERRAND, current_kind=kind), True
                    )
                )

    def test_a_row_the_module_has_not_refreshed_is_not_acted_on(self):
        self.assertIsNone(
            jfi.errand_pick(
                row(
                    "regroup|regroup|Uzza\n" + ERRAND, module_age=jfi.FRESH_SECONDS + 1
                ),
                True,
            )
        )

    def test_the_cap_gives_the_regroup_its_turn_back(self):
        table = "regroup|regroup|Uzza\n" + ERRAND
        self.assertIsNotNone(jfi.errand_pick(row(table), True, held_for=60))
        self.assertIsNone(
            jfi.errand_pick(row(table), True, held_for=jfi.ERRAND_PICK_CAP_SECONDS)
        )

    def test_the_cap_is_the_walks_own_window(self):
        self.assertEqual(townerrand.GO_SECONDS, jfi.ERRAND_PICK_CAP_SECONDS)

    def test_a_long_target_is_written_as_any_errand(self):
        long_aim = "at:1:" + "9" * 120
        pick = jfi.errand_pick(
            row("regroup|regroup|Uzza\nerrand|town trip|" + long_aim), True
        )
        self.assertEqual(("errand", ""), jfi.errand_pick_columns(pick))


class TheStep(unittest.TestCase):
    TABLE = "regroup|regroup|Uzza\n" + ERRAND

    def test_it_writes_once_then_renews_halfway_through_the_pick(self):
        s = jfi.errand_step(row(self.TABLE), 100.0, None, 1000.0)
        self.assertEqual("write", s.action)
        self.assertTrue(s.first)
        s2 = jfi.errand_step(row(self.TABLE), 100.0, s.memory, 1030.0)
        self.assertEqual("", s2.action)
        s3 = jfi.errand_step(
            row(self.TABLE), 100.0, s2.memory, 1000.0 + jfi.PICK_SECONDS / 2
        )
        self.assertEqual("write", s3.action)
        self.assertFalse(s3.first)

    def test_a_changed_errand_is_written_at_once(self):
        s = jfi.errand_step(row(self.TABLE), 100.0, None, 1000.0)
        vendor = row("regroup|regroup|Uzza\neconomy|travel column|vendor")
        s2 = jfi.errand_step(vendor, 100.0, s.memory, 1030.0)
        self.assertEqual("write", s2.action)
        self.assertEqual("economy:vendor", s2.pick.ask.option)

    def test_the_pick_is_cleared_when_the_errand_ends(self):
        s = jfi.errand_step(row(self.TABLE), 100.0, None, 1000.0)
        s2 = jfi.errand_step(row(self.TABLE), None, s.memory, 1060.0)
        self.assertEqual("clear", s2.action)
        self.assertIsNone(s2.memory)

    def test_an_errand_that_never_picked_has_nothing_to_clear(self):
        s = jfi.errand_step(row(ERRAND), None, None, 1000.0)
        self.assertEqual("", s.action)
        self.assertIsNone(s.memory)

    def test_past_the_cap_it_clears_once_and_stays_out_of_the_way(self):
        s = jfi.errand_step(row(self.TABLE), 100.0, None, 1000.0)
        late = 1000.0 + jfi.ERRAND_PICK_CAP_SECONDS
        s2 = jfi.errand_step(row(self.TABLE), 100.0, s.memory, late)
        self.assertEqual("clear", s2.action)
        self.assertFalse(jfi.errand_pick_standing(s2.memory))
        s3 = jfi.errand_step(row(self.TABLE), 100.0, s2.memory, late + 30)
        self.assertEqual("", s3.action)
        # The clock is the errand's: a new errand gets its own window.
        s4 = jfi.errand_step(row(self.TABLE), 900.0, s3.memory, late + 60)
        self.assertEqual("write", s4.action)

    def test_a_standing_pick_blocks_the_model_answer(self):
        s = jfi.errand_step(row(self.TABLE), 100.0, None, 1000.0)
        self.assertTrue(jfi.errand_pick_standing(s.memory))
        self.assertFalse(jfi.errand_pick_standing(None))


class TheBridge(unittest.TestCase):
    def load(self, errands, rows):
        calls = {"write": [], "clear": [], "log": []}

        async def to_thread(fn, *a):
            return fn(*a)

        ns = _load(
            ["_errand_pick_once", "_bag_errand_started"],
            {
                "asyncio": types.SimpleNamespace(to_thread=to_thread),
                "time": types.SimpleNamespace(monotonic=lambda: 1000.0),
                "jev_family_intent": jfi,
                "townerrand": townerrand,
                "_TOWN_ERRANDS": errands,
                "_ERRAND_PICKS": {},
                "_fetch_family_intents": lambda: rows,
                "_write_family_pick": lambda *a: calls["write"].append(a) or 1,
                "_clear_family_pick": calls["clear"].append,
                "log": types.SimpleNamespace(
                    info=lambda *a: calls["log"].append(a[0] % a[1:]),
                    exception=lambda *a: None,
                ),
            },
        )
        return ns, calls

    def bag_errand(self, names=("Zug", "Uzza"), why=townerrand.BAG_PRESSURE_WHY):
        return {
            tuple(sorted(names)): townerrand.State(
                phase=townerrand.GO, started=100.0, why=why
            )
        }

    def table_row(self):
        return {
            "Zug": dict(
                leader_name="Zug",
                family="Zug",
                current_kind="regroup",
                current_owner="regroup",
                current_target="Uzza",
                current_for=5,
                on_the_table="regroup|regroup|Uzza\n" + ERRAND,
                goal_yards=403,
                members_state="",
                module_age=5,
                chosen_kind="",
                chosen_target="",
                chosen_by="",
                changes=1,
            )
        }

    def test_the_bridge_writes_the_errand_pick_without_a_model(self):
        ns, calls = self.load(self.bag_errand(), self.table_row())
        asyncio.run(ns["_errand_pick_once"](object()))
        self.assertEqual([("Zug", "errand", AIM, None)], calls["write"])
        self.assertEqual(1, len(calls["log"]))
        self.assertIn("Zug", calls["log"][0])
        self.assertIn("regroup", calls["log"][0])

    def test_it_logs_once_per_errand_not_per_renewal(self):
        ns, calls = self.load(self.bag_errand(), self.table_row())
        asyncio.run(ns["_errand_pick_once"](object()))
        asyncio.run(ns["_errand_pick_once"](object()))
        self.assertEqual(1, len(calls["write"]))
        self.assertEqual(1, len(calls["log"]))

    def test_a_family_in_a_trade_turn_gets_the_pick_over_a_training_stop(self):
        # #2271: the pick reads the errand and the module's row only, so a
        # live trade turn changes nothing about it. The pick is written, and
        # the training stop is what it is written over.
        rows = self.table_row()
        rows["Zug"].update(
            current_kind="training",
            current_owner="training stop",
            current_target="trainer:4567",
            on_the_table="training|training stop|trainer:4567\n" + ERRAND,
        )
        ns, calls = self.load(self.bag_errand(), rows)
        ns["_TRADE_TURN"] = {"Zug"}
        asyncio.run(ns["_errand_pick_once"](object()))
        self.assertEqual([("Zug", "errand", AIM, None)], calls["write"])
        self.assertIn("training", calls["log"][0])

    def test_a_supplies_errand_in_a_trade_turn_is_still_left_alone(self):
        rows = self.table_row()
        ns, calls = self.load(
            self.bag_errand(why="family short of usable supplies: drink"), rows
        )
        ns["_TRADE_TURN"] = {"Zug"}
        asyncio.run(ns["_errand_pick_once"](object()))
        self.assertEqual([], calls["write"])

    def test_a_town_errand_for_anything_but_bag_room_is_left_alone(self):
        ns, calls = self.load(self.bag_errand(why="gear in the post"), self.table_row())
        asyncio.run(ns["_errand_pick_once"](object()))
        self.assertEqual([], calls["write"])

    def test_the_pick_is_cleared_when_the_errand_ends(self):
        errands = self.bag_errand()
        ns, calls = self.load(errands, self.table_row())
        asyncio.run(ns["_errand_pick_once"](object()))
        errands.clear()
        asyncio.run(ns["_errand_pick_once"](object()))
        self.assertEqual(["Zug"], calls["clear"])

    def test_the_wiring(self):
        self.assertIn("await self._errand_pick_once()", BRIDGE)
        self.assertIn("_errand_pick_standing", BRIDGE)
