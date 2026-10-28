"""The Dark Iron road: plans, reputation, the Black Forge and the Black Anvil.

#480. `fireplan` names a tank's Dark Iron pieces as upgrades and `raidsupply`
called them plans nobody holds. This suite pins the road (it lives in fireplan) between those two
sentences: the reputation gate Lokhtos sells each plan behind, the plan
purchase, the smelt learned from The Spectral Chalice, the bars made at the
Black Forge, and the piece made at the Black Anvil.

WHAT THIS PINS THAT A LIVE RUN CANNOT. None of these gates fails loudly in the
world. A plan bought at the wrong rank is simply absent from the vendor's list;
a smelt cast at an ordinary forge returns a numeric `SpellCastResult` and no
bar; a craft at the wrong anvil does the same. The order is the whole
pipeline, so the order is what is tested.

THE ITEM BOOK'S SKILL NUMBERS ARE NOT CLASSIC. It gives these plans 315 and
320, and the classic cap is 300. The module says so rather than trusting the
number; the realm's own item_template is the authority.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fireplan  # noqa: E402
import towntrip  # noqa: E402


def item_book() -> dict:
    with (ROOT / "data" / "bis" / "items.json").open() as fh:
        return json.load(fh)["items"]


class PlanTableTests(unittest.TestCase):
    def test_every_plan_makes_a_piece_the_item_book_knows(self):
        book = item_book()
        for plan in fireplan.PLANS:
            with self.subTest(plan=plan.name):
                row = book.get(str(plan.piece))
                self.assertIsNotNone(row, plan.piece_name)
                self.assertEqual(row["name"], plan.piece_name)
                self.assertEqual(row["fire_res"], plan.fire)
                self.assertLessEqual(row["req"], 60)

    def test_every_plan_teaches_the_spell_the_item_book_gives_the_piece(self):
        book = item_book()
        for plan in fireplan.PLANS:
            with self.subTest(plan=plan.name):
                crafts = [
                    s
                    for s in book[str(plan.piece)]["sources"]
                    if s.get("type") == "craft"
                ]
                self.assertEqual([s["spell"] for s in crafts], [plan.teaches])

    def test_the_plans_are_in_reputation_order(self):
        ranks = [fireplan.rank_index(p.rank) for p in fireplan.PLANS]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(ranks[0], fireplan.rank_index(fireplan.FRIENDLY))
        self.assertEqual(ranks[-1], fireplan.rank_index(fireplan.EXALTED))

    def test_every_plan_is_sold_at_a_rank_on_the_ladder(self):
        for plan in fireplan.PLANS:
            with self.subTest(plan=plan.name):
                self.assertIn(plan.rank, fireplan.RANK_VALUE)
                self.assertGreater(plan.bars, 0)
                self.assertTrue(plan.reagents)

    def test_the_turn_ins_are_ore_cores_leather_and_blood(self):
        self.assertEqual(
            [q for q, _needs in fireplan.TURNINS],
            [6642, 6643, 6644, 6645, 6646],
        )
        entries = {entry for _q, needs in fireplan.TURNINS for entry, _count in needs}
        self.assertEqual(
            entries,
            {
                fireplan.DARK_IRON_ORE,
                fireplan.FIERY_CORE,
                fireplan.LAVA_CORE,
                fireplan.CORE_LEATHER,
                fireplan.BLOOD_OF_THE_MOUNTAIN,
            },
        )
        for _q, needs in fireplan.TURNINS:
            for entry, count in needs:
                with self.subTest(entry=entry):
                    self.assertIn(entry, fireplan.ITEM_NAMES)
                    self.assertGreater(count, 0)

    def test_the_skill_note_quotes_the_item_book_and_the_classic_cap(self):
        """The note must stay true to the data it warns about.

        Nothing here claims the realm's skill gate: the realm's item_template
        is the authority and the plan never reads the item book's number. What
        is pinned is that `skill_note` quotes whatever skill the item book
        gives each craft, so a changed book makes the note fail here instead
        of going stale, and that it names the classic cap.
        """
        book = item_book()
        note = fireplan.skill_note()
        for plan in fireplan.PLANS:
            with self.subTest(plan=plan.name):
                crafts = [
                    s
                    for s in book[str(plan.piece)]["sources"]
                    if s.get("type") == "craft"
                ]
                self.assertIn(str(crafts[0]["skill"]), note)
        self.assertIn("classic cap is 300", note)


class PipelineTests(unittest.TestCase):
    def test_a_neutral_guild_is_sent_to_friendly_first(self):
        pipe = fireplan.iron_plan()
        self.assertEqual(pipe.step.kind, fireplan.GRIND)
        self.assertEqual(pipe.plan.rank, fireplan.FRIENDLY)
        self.assertIn("Friendly", pipe.step.said)
        self.assertIn("Master Smith Burninate", pipe.step.said)
        self.assertNotIn("Lokhtos", pipe.step.said)
        self.assertIn("Plans: Dark Iron Bracers", pipe.step.said)

    def test_the_grind_names_the_furthest_rank_the_first_plan_needs(self):
        pipe = fireplan.iron_plan(known=(17051,), made=(17014,))
        self.assertEqual(pipe.step.kind, fireplan.GRIND)
        self.assertEqual(pipe.plan.rank, fireplan.HONORED)
        self.assertIn("Honored", pipe.step.said)

    def test_friendly_buys_the_bracers_plan(self):
        pipe = fireplan.iron_plan(rank=fireplan.FRIENDLY)
        self.assertEqual(pipe.step.kind, fireplan.BUY)
        self.assertEqual(pipe.plan.entry, 17051)
        self.assertIn("Lokhtos", pipe.step.said)
        self.assertIn("Friendly", pipe.step.said)

    def test_a_known_plan_still_has_to_learn_the_smelt(self):
        pipe = fireplan.iron_plan(known=(17051,), rank=fireplan.FRIENDLY)
        self.assertEqual(pipe.step.kind, fireplan.LEARN)
        self.assertEqual(pipe.step.plan.piece, 17014)
        self.assertIn("Spectral Chalice", pipe.step.said)
        self.assertIn("Mining 230", pipe.step.said)
        self.assertIn("Star Ruby", pipe.step.said)

    def test_the_smelt_asks_for_the_ore_the_bars_need(self):
        pipe = fireplan.iron_plan(
            known=(17051,), rank=fireplan.FRIENDLY, smelt_known=True
        )
        self.assertEqual(pipe.step.kind, fireplan.SMELT)
        self.assertIn("4 Dark Iron Bars", pipe.step.said)
        self.assertIn("32 Dark Iron Ore", pipe.step.said)
        self.assertIn("Black Forge", pipe.step.said)

    def test_held_bars_skip_the_smelt(self):
        pipe = fireplan.iron_plan(
            known=(17051,),
            rank=fireplan.FRIENDLY,
            smelt_known=True,
            held={fireplan.DARK_IRON_BAR: 4},
        )
        self.assertEqual(pipe.step.kind, fireplan.GATHER)
        self.assertIn("2 Fiery Core", pipe.step.said)
        self.assertIn("2 Lava Core", pipe.step.said)

    def test_all_the_reagents_make_the_piece_at_the_black_anvil(self):
        pipe = fireplan.iron_plan(
            known=(17051,),
            rank=fireplan.FRIENDLY,
            smelt_known=True,
            held={
                fireplan.DARK_IRON_BAR: 4,
                fireplan.FIERY_CORE: 2,
                fireplan.LAVA_CORE: 2,
            },
        )
        self.assertEqual(pipe.step.kind, fireplan.CRAFT)
        self.assertIn("Dark Iron Bracers", pipe.step.said)
        self.assertIn("Black Anvil", pipe.step.said)

    def test_a_made_piece_moves_the_pipeline_on(self):
        pipe = fireplan.iron_plan(
            known=(17051,),
            rank=fireplan.HONORED,
            made=(17014,),
        )
        self.assertEqual(pipe.plan.entry, 19206)
        self.assertEqual(pipe.step.kind, fireplan.BUY)

    def test_every_plan_made_is_done(self):
        pipe = fireplan.iron_plan(
            known=[p.entry for p in fireplan.PLANS],
            rank=fireplan.EXALTED,
            made=[p.piece for p in fireplan.PLANS],
        )
        self.assertTrue(pipe.done)
        self.assertIn("every piece is made", pipe.line)


class SaidTests(unittest.TestCase):
    def test_a_piece_names_its_plan_and_rank_for_the_fire_plan(self):
        said = fireplan.iron_source(19148)
        self.assertIn("Plans: Dark Iron Helm", said)
        self.assertIn("Honored", said)
        self.assertIn("Black Anvil", said)

    def test_a_piece_this_module_does_not_know_has_no_road(self):
        self.assertEqual(fireplan.iron_source(12345), "")

    def test_the_road_names_the_place_the_rank_and_the_anvil(self):
        for word in ("Lokhtos", "Thorium Brotherhood", "Black Forge", "Black Anvil"):
            self.assertIn(word, fireplan.IRON_ROAD)

    def test_the_road_says_the_first_step_and_the_skill_note(self):
        self.assertIn(fireplan.iron_plan().line, fireplan.IRON_ROAD)
        self.assertIn(fireplan.skill_note(), fireplan.IRON_ROAD)

    def test_the_module_ships_in_the_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("fireplan.py", dockerfile)


LOKHTOS_STOCK = frozenset(p.entry for p in fireplan.PLANS)


def smith(**kw):
    base = dict(name="Smith", money=10**7, free_slots=4, stocks=LOKHTOS_STOCK)
    base.update(kw)
    if isinstance(base.get("held"), dict):
        base["held"] = tuple(base["held"].items())
    return fireplan.Smith(**base)


class RealmDataTests(unittest.TestCase):
    """Pinned to what acore_world says (read 2026-10-26, SELECT only)."""

    def test_plan_entries_ranks_and_prices_match_the_realm(self):
        realm = {
            # entry: (rank from the vendor condition mask, BuyPrice, skill)
            17051: (fireplan.FRIENDLY, 70000, 295),
            19206: (fireplan.HONORED, 60000, 300),
            19207: (fireplan.REVERED, 80000, 300),
            17052: (fireplan.REVERED, 180000, 300),
            20040: (fireplan.EXALTED, 80000, 300),
        }
        self.assertEqual({p.entry for p in fireplan.PLANS}, set(realm))
        for plan in fireplan.PLANS:
            with self.subTest(plan=plan.name):
                self.assertEqual((plan.rank, plan.price, plan.skill), realm[plan.entry])

    def test_17060_is_the_destroyer_not_the_leggings(self):
        legs = next(p for p in fireplan.PLANS if p.piece == 17013)
        self.assertEqual(legs.entry, 17052)
        self.assertNotIn(17060, {p.entry for p in fireplan.PLANS})

    def test_the_skill_note_quotes_the_realm_numbers(self):
        self.assertIn("295 and 300", fireplan.skill_note())


class TurnInRankTests(unittest.TestCase):
    def test_below_honored_lokhtos_takes_no_turn_in(self):
        # Friendly with the Bracers made: the Helm is Honored, and below Honored
        # Lokhtos's Favor quests are refused, however much is spare.
        turn = fireplan.iron_member(
            smith(standing=3000, held={fireplan.BLOOD_OF_THE_MOUNTAIN: 5}),
            made={17014},
        )
        self.assertEqual(turn.pipe.step.kind, fireplan.GRIND)
        self.assertIsNone(turn.errand)
        self.assertIn("below Honored", turn.note)

    def test_every_lokhtos_turn_in_needs_honored(self):
        self.assertEqual(fireplan.TURNIN_MIN_STANDING, 9000)

    def test_at_honored_spare_blood_is_handed_in(self):
        learned = {fireplan.PLANS[0].teaches, fireplan.PLANS[1].teaches}
        turn = fireplan.iron_member(
            smith(
                standing=9000,
                learned=frozenset(learned),
                held={fireplan.BLOOD_OF_THE_MOUNTAIN: 1},
                in_log=frozenset({6646}),
            ),
            made={17014, 19148},
        )
        self.assertEqual(turn.errand.kind, "quest")
        self.assertEqual(turn.errand.command, "turnin quest:6646")

    def test_a_quest_not_in_the_log_is_taken_first(self):
        turn = fireplan.iron_member(
            smith(standing=9000, held={fireplan.BLOOD_OF_THE_MOUNTAIN: 1}),
            made={17014, 19148},
        )
        self.assertEqual(turn.errand.command, "take quest:6646")


class KeptReagentTests(unittest.TestCase):
    def test_cores_and_leather_are_never_handed_in(self):
        held = {
            fireplan.FIERY_CORE: 40,
            fireplan.LAVA_CORE: 40,
            fireplan.CORE_LEATHER: 40,
        }
        turn = fireplan.iron_member(
            smith(standing=9000, held=held), made={17014, 19148}
        )
        self.assertIsNone(turn.errand)
        self.assertIn("nothing spare", turn.note)

    def test_ore_the_bars_still_need_is_kept(self):
        # Bars still owed: every piece but the first two, 6+8+6 = 20 bars.
        made = {17014, 19148}
        owed = sum(p.bars for p in fireplan.PLANS if p.piece not in made)
        ore = owed * fireplan.ORE_PER_BAR
        turn = fireplan.iron_member(
            smith(standing=9000, held={fireplan.DARK_IRON_ORE: ore + 9}), made=made
        )
        self.assertIsNone(turn.errand)
        turn = fireplan.iron_member(
            smith(standing=9000, held={fireplan.DARK_IRON_ORE: ore + 10}), made=made
        )
        self.assertEqual(turn.errand.command, "take quest:6642")

    def test_spare_never_offers_a_kept_item(self):
        held = {i: 100 for i in fireplan.ITEM_NAMES}
        free = fireplan.spare(held)
        for item in fireplan.KEPT_FOR_CRAFTS:
            self.assertNotIn(item, free)


class CounterGateTests(unittest.TestCase):
    def test_a_member_away_from_lokhtos_is_walked_not_queued(self):
        turn = fireplan.iron_member(smith(standing=3000, stocks=frozenset()))
        self.assertEqual(turn.pipe.step.kind, fireplan.BUY)
        self.assertIsNone(turn.errand)
        self.assertEqual(turn.walk_to, 17051)

    def test_a_buy_needs_the_price(self):
        turn = fireplan.iron_member(smith(standing=3000, money=69999))
        self.assertIsNone(turn.errand)
        self.assertIn("cannot afford", turn.note)

    def test_a_buy_needs_a_free_bag_slot(self):
        turn = fireplan.iron_member(smith(standing=3000, free_slots=0))
        self.assertIsNone(turn.errand)
        self.assertIn("free bag slot", turn.note)

    def test_a_buy_at_the_counter_carries_the_realm_price(self):
        turn = fireplan.iron_member(smith(standing=3000))
        self.assertEqual(turn.errand.kind, "buy")
        self.assertEqual(turn.errand.command, "entry:17051 count:1 max:70000")
        self.assertEqual(turn.errand.spend, 70000)

    def test_a_refused_or_pending_row_is_not_written_again(self):
        blocked = {("Smith", "entry:17051 count:1 max:70000")}
        turn = fireplan.iron_member(smith(standing=3000), blocked=blocked)
        self.assertIsNone(turn.errand)
        self.assertIn("not written again", turn.note)

    def test_a_step_with_no_command_kind_queues_nothing(self):
        turn = fireplan.iron_member(
            smith(standing=3000, learned=frozenset({fireplan.PLANS[0].teaches}))
        )
        self.assertEqual(turn.pipe.step.kind, fireplan.LEARN)
        self.assertIsNone(turn.errand)


class ProgressRecordTests(unittest.TestCase):
    def test_holding_a_piece_is_not_having_made_it(self):
        learned = frozenset({fireplan.PLANS[0].teaches, fireplan.SMELT_SPELL})
        turn = fireplan.iron_member(
            smith(standing=3000, learned=learned, held={17014: 1})
        )
        self.assertEqual(turn.pipe.plan.piece, 17014)

    def test_a_crafted_record_moves_the_road_on(self):
        learned = frozenset({fireplan.PLANS[0].teaches, fireplan.SMELT_SPELL})
        turn = fireplan.iron_member(smith(standing=3000, learned=learned), made={17014})
        self.assertEqual(turn.pipe.plan.piece, 19148)


class FlagTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(fireplan.dark_iron_enabled({}))

    def test_on_only_for_1(self):
        self.assertTrue(fireplan.dark_iron_enabled({"DARK_IRON_ENABLED": "1"}))
        with self.assertRaises(ValueError):
            fireplan.dark_iron_enabled({"DARK_IRON_ENABLED": "yes"})


class LogTests(unittest.TestCase):
    def test_the_log_line_names_the_member_and_the_step(self):
        turn = fireplan.iron_member(smith())
        self.assertEqual(
            fireplan.iron_log("Smith", turn.pipe),
            "dark iron: Smith step grind: " + turn.pipe.step.said,
        )


# --- the bridge side, exec'd from bridge.py against fakes -------------------

BRIDGE = ROOT / "bridge.py"
_TREE = ast.parse(BRIDGE.read_text(encoding="utf-8"))


def _module_fn(name):
    return next(
        n for n in _TREE.body if isinstance(n, ast.FunctionDef) and n.name == name
    )


def _method(name):
    return next(
        n
        for c in _TREE.body
        if isinstance(c, ast.ClassDef)
        for n in c.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == name
    )


class _Log:
    def __init__(self):
        self.lines, self.exceptions = [], []

    def info(self, fmt, *args):
        self.lines.append(fmt % args if args else fmt)

    warning = info

    def exception(self, fmt, *args):
        self.exceptions.append(fmt % args if args else fmt)


class _Cursor:
    def __init__(self, error=None, rows=()):
        self.error, self.rows, self.lastrowid = error, list(rows), 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a):
        if self.error:
            raise self.error

    def fetchall(self):
        return self.rows


class _Conn(_Cursor):
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur


def _exec(nodes, **ns):
    base = {
        "pymysql": _PYMYSQL,
        "fireplan": fireplan,
        "log": _Log(),
        "attunestep": types.SimpleNamespace(LOG_SQL="{holes}{quests}"),
    }
    base.update(ns)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "bridge.py", "exec"), base)  # noqa: S102
    return base


class _MySQLError(Exception):
    """Stands in for pymysql.err.MySQLError: (code, message) args. Another
    module in the same test batch may replace pymysql in sys.modules, so the
    exec'd bridge functions get this rather than whatever is imported."""


_PYMYSQL = types.SimpleNamespace(err=types.SimpleNamespace(MySQLError=_MySQLError))


class BridgeGuardTests(unittest.TestCase):
    """_fetch_standing and the pending/refused read degrade like siblings."""

    def _ns(self, code):
        err = _MySQLError(code, "x")
        names = [
            "_fetch_standing",
            "_iron_rows_blocked",
            "_fetch_crafted",
            "_fetch_quest_log",
            "_insert_iron_errand",
        ]
        return _exec(
            [_module_fn(n) for n in names], _connect=lambda: _Conn(_Cursor(error=err))
        )

    def test_every_dark_iron_read_survives_1054_1146_1265(self):
        for code in (1054, 1146, 1265):
            with self.subTest(code=code):
                ns = self._ns(code)
                self.assertEqual(ns["_fetch_standing"](["A"], 59), {})
                self.assertIsNone(ns["_iron_rows_blocked"](60))
                self.assertEqual(ns["_fetch_crafted"](["A"], [1]), set())
                self.assertEqual(ns["_fetch_quest_log"](["A"], [1]), set())
                errand = towntrip.Errand("A", "buy", "entry:1 count:1 max:1", "")
                self.assertEqual(ns["_insert_iron_errand"](errand), 0)

    def test_another_error_still_raises(self):
        ns = self._ns(2013)
        with self.assertRaises(_MySQLError):
            ns["_fetch_standing"](["A"], 59)


async def _to_thread(fn, *a, **k):
    return fn(*a, **k)


def _bridge_pass(
    enabled="1",
    blocked=frozenset(),
    standing=3000,
    stocks=LOKHTOS_STOCK,
    boom=False,
    runs=1,
):
    inserted, walks = [], []

    def skill_cap(name, skill):
        if boom:
            raise RuntimeError("boom")
        return 300

    ns = _exec(
        [_method("_dark_iron_once"), _method("_dark_iron_pass")],
        asyncio=types.SimpleNamespace(to_thread=_to_thread),
        craft_supply=types.SimpleNamespace(Need=lambda *a: a),
        BLACKSMITHING_SKILL=164,
        THORIUM_FACTION=59,
        _fetch_skill_cap=skill_cap,
        _fetch_crafter_known=lambda names, spells: [],
        _fetch_standing=lambda names, f: {n: standing for n in names},
        _fetch_crafted=lambda names, entries: set(),
        _fetch_quest_log=lambda names, quests: set(),
        _fetch_item_counts=lambda pairs: {},
        _fetch_purses=lambda names: {n: (60, 10**7) for n in names},
        _fetch_free_slots=lambda names: {n: 4 for n in names},
        _iron_rows_blocked=lambda minutes: blocked,
        _fetch_town=lambda name: towntrip.Town(stocks=stocks),
        _insert_iron_errand=lambda e: inserted.append(e) or 1,
    )
    me = types.SimpleNamespace()
    me._dark_iron_pass = lambda names, cohort=None: ns["_dark_iron_pass"](
        me, names, cohort
    )

    async def walk(needs, cohort=None):
        walks.append(list(needs))

    me._walk_for_reagents = walk
    old = fireplan.os.environ.get("DARK_IRON_ENABLED")
    fireplan.os.environ["DARK_IRON_ENABLED"] = enabled
    try:
        for _ in range(runs):
            queued = asyncio.run(ns["_dark_iron_once"](me, ["Smith"]))
    finally:
        if old is None:
            fireplan.os.environ.pop("DARK_IRON_ENABLED", None)
        else:
            fireplan.os.environ["DARK_IRON_ENABLED"] = old
    return queued, inserted, walks, ns["log"]


class BridgePassTests(unittest.TestCase):
    def test_off_by_default_queues_nothing(self):
        queued, inserted, _w, _l = _bridge_pass(enabled="0")
        self.assertEqual((queued, inserted), (0, []))

    def test_an_invalid_flag_is_logged_once_and_treated_as_off(self):
        # #1510: the flag read sat outside the pass guard, so DARK_IRON_ENABLED
        # set to anything but 0 or 1 raised ValueError into the craft supply
        # pass. It now reads as off, with one warning per bridge.
        queued, inserted, _w, log = _bridge_pass(enabled="yes", runs=3)
        self.assertEqual((queued, inserted), (0, []))
        warned = [line for line in log.lines if "DARK_IRON_ENABLED" in line]
        self.assertEqual(len(warned), 1, log.lines)
        self.assertIn("'yes'", warned[0])

    def test_a_failing_pass_is_logged_and_does_not_raise(self):
        queued, _i, _w, log = _bridge_pass(boom=True)
        self.assertEqual(queued, 0)
        self.assertTrue(log.exceptions)

    def test_a_member_at_the_counter_gets_the_buy(self):
        queued, inserted, walks, _l = _bridge_pass()
        self.assertEqual(queued, 1)
        self.assertEqual(inserted[0].command, "entry:17051 count:1 max:70000")
        self.assertEqual(walks, [])

    def test_a_member_away_from_lokhtos_is_walked(self):
        queued, inserted, walks, _l = _bridge_pass(stocks=frozenset())
        self.assertEqual((queued, inserted), (0, []))
        self.assertEqual(walks, [[("Smith", 17051, fireplan.VENDOR)]])

    def test_an_unreadable_queue_writes_nothing(self):
        queued, inserted, _w, _l = _bridge_pass(blocked=None)
        self.assertEqual((queued, inserted), (0, []))

    def test_a_refused_row_is_not_written_again(self):
        blocked = {("Smith", "entry:17051 count:1 max:70000")}
        queued, inserted, _w, _l = _bridge_pass(blocked=blocked)
        self.assertEqual((queued, inserted), (0, []))

    def test_the_bridge_plans_it_from_the_craft_supply_pass(self):
        src = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("await self._dark_iron_once(names, cohort)", src)


if __name__ == "__main__":
    unittest.main()
