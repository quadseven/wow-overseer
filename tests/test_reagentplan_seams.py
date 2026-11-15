"""The reagent plan reaches the passes that can feed a craft (#774, #769).

The planner (test_reagentplan.py) names a source; these tests hold the seams
that act on it. The craft pass logs the one plain line for an unfed craft,
the bank pass fetches a banked reagent the crafter's errand eats and never
banks it again, and the guild bank pass takes a vault stack for the crafter
under a source the house's withdrawal reader does not count as stock to sell.
"""

from __future__ import annotations

import ast
import dataclasses
import asyncio
import pathlib
import types
import unittest

import bank
import craft
import craft_rhythm
import reagentplan

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
EMPTY_VIAL, PEACEBLOOM, SILVERLEAF, ROUGH_STONE = 3371, 2447, 765, 2835


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _body(name):
    return ast.get_source_segment(BRIDGE, _function(name))


def _load(names, namespace):
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = debug = info


def _thread(fn, *a, **k):
    async def run():
        return fn(*a, **k)

    return run()


def row(**kw):
    base = dict(
        holder="Uzza",
        level=60,
        item_guid=1,
        count=34,
        name="Empty Vial",
        quality=1,
        sell_price=1,
        required_level=0,
        bonding=0,
        item_class=7,
        container_slots=0,
        bag=0,
        slot=39,
        entry=EMPTY_VIAL,
    )
    base.update(kw)
    return base


FAMILY = bank.family_from_skills({"Uzza": {"alchemy": 52, "herbalism": 70}})


class TheBankFetchesWhatTheCraftEats(unittest.TestCase):
    def _plan(self, rows, wants):
        members = bank.members_from_rows(rows, ["Uzza"])
        storage = bank.storage_from(
            {"Uzza": {"alchemy": 52, "herbalism": 70}}, craft_wants=wants
        )
        # A full bag of room, so only the reason decides.
        members = [dataclasses.replace(m, bag_free=10) for m in members]
        return bank.plan(members, FAMILY, storage=storage)

    def test_a_banked_vial_her_errand_eats_is_withdrawn(self):
        plan = self._plan([row()], {"Uzza": frozenset({EMPTY_VIAL})})
        withdrawn = [m for m in plan.moves if m.verb == bank.WITHDRAW]
        self.assertEqual([1], [m.guid for m in withdrawn])
        self.assertIn("craft", withdrawn[0].why)

    def test_without_the_want_the_vial_stays_banked(self):
        plan = self._plan([row()], {})
        self.assertEqual([], [m for m in plan.moves if m.verb == bank.WITHDRAW])

    def test_a_carried_reagent_the_craft_eats_is_never_banked(self):
        rows = [row(item_guid=2, slot=23, count=200)]
        storage = bank.storage_from(
            {"Uzza": {"alchemy": 52}}, craft_wants={"Uzza": frozenset({EMPTY_VIAL})}
        )
        holding = bank.members_from_rows(rows, ["Uzza"])[0].carried[0]
        self.assertEqual("", bank.storage_reason(holding, storage, frozenset({2})))


class TheCraftPassSaysWhatIsMissing(unittest.TestCase):
    def test_an_unfed_errand_logs_its_plan_line(self):
        log = _Log()
        written = []
        plan = reagentplan.plan(
            "Uzza",
            2330,
            {
                PEACEBLOOM: reagentplan.Stock(bags=20),
                SILVERLEAF: reagentplan.Stock(bags=20),
                EMPTY_VIAL: reagentplan.Stock(bank=34),
            },
            {},
            {},
        )
        asked = []

        def planner(names, spells, skills):
            asked.append(dict(spells))
            return {"Uzza": plan}

        ns = _load(
            ["_craft_once", "_primaries_for"],
            {
                "asyncio": types.SimpleNamespace(to_thread=_thread),
                "craft": craft,
                "reagentplan": reagentplan,
                # The chosen recipe is craft_rhythm's (tested there); pinned here.
                "craft_rhythm": types.SimpleNamespace(
                    reagents_to_count=lambda *a, **k: set(),
                    errand=lambda name, *a, **k: craft_rhythm.Errand(
                        name, 2330, why="w"
                    ),
                ),
                "log": log,
                "_crafting_roster": lambda family=None: ["Uzza"],
                "_fetch_trade_skills": lambda names: {"Uzza": {"alchemy": 52}},
                "_bags_wanted_for": lambda cohort=None: 0,
                "_guild_bag_floor_for": lambda cohort=None: None,
                "_fetch_item_counts": lambda pairs: {},
                "_fetch_crafters_known": lambda names: {},
                "_plan_craft_reagents": planner,
                "_write_craft_errand": lambda name, spell: written.append(
                    (name, spell)
                ),
            },
        )
        asyncio.run(ns["_craft_once"](types.SimpleNamespace(), None))
        self.assertEqual([{"Uzza": written[0][1]}], asked)
        self.assertIn("craft: " + reagentplan.line(plan), log.lines)
        self.assertFalse(any("aimed at" in ln for ln in log.lines), log.lines)


class TheWiringIsInPlace(unittest.TestCase):
    def test_the_bank_plan_is_given_the_crafters_wants(self):
        self.assertIn("craft_wants=", _body("_plan_bank"))
        self.assertIn("reagentplan.bank_wants(", _body("_plan_bank"))

    def test_the_guild_withdrawals_carry_the_crafters_vault_stacks(self):
        body = _body("_plan_guild_withdrawals")
        self.assertIn("reagentplan.vault_withdrawals(", body)

    def test_each_withdrawal_row_is_written_under_its_own_source(self):
        body = _body("_queue_guild_withdrawals")
        self.assertIn('getattr(withdrawal, "source", "guildbank-withdraw")', body)

    def test_the_planner_reads_bags_bank_mail_and_the_vault(self):
        body = _body("_fetch_reagent_stock")
        for table in ("character_inventory", "mail_items"):
            self.assertIn(table, body)
        self.assertIn("guild_bank_item", _body("_fetch_vault_stacks"))


if __name__ == "__main__":
    unittest.main()
