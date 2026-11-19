"""The trip count does not include stacks the loot policy will keep (#1261).

Measured on the dev realm 2026-11-17 06:00Z. The Zug family stood at the bag
floor (one free slot each for two members) for most of an hour, held at the
dungeon door for bag room, and the vendor trip kept the leader's one travel
column. The pass logged "6 carried candidate(s) for Oz", Oz stood 1.5 yards
from the counter, "holder=Oz queued 6/6 vendor sale(s)", and then six lines of
"kept ... no vendor sale": a disenchant, two holds, an upgrade for a
guildmate, another upgrade and a lockbox for the bank. No sell row was
written. The count that said a vendor trip would make room counted the same
six stacks the writer then refused, so the trip, the errand and the quest hold
waited on a sale of nothing.

The count now asks the writer's own question (the loot policy) before it
counts a gear, lockbox, clearance or route sale.
"""

import ast
import pathlib
import types
import unittest

import bag_pressure
import lootpolicy

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)


def _load(names, namespace):
    tree = ast.parse(BRIDGE)
    found = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    module = ast.Module(body=[found[n] for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102
    return namespace


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = info


def _sale(holder, guid):
    return bag_pressure.SellCandidate(
        holder=holder,
        item_guid=guid,
        count=1,
        item=bag_pressure.ItemForSale(quality=2, sell_price=50),
    )


def _wrapped(holder, guid):
    """The item plan route's Sale: the candidate sits one level down."""
    return types.SimpleNamespace(holder=holder, candidate=_sale(holder, guid))


class CountingSkipsRefusedSales(unittest.TestCase):
    def setUp(self):
        self.ns = _load(["_sale_guid", "_count_sales"], {})

    def test_a_refused_stack_is_not_counted(self):
        counts = {"Oz": 0}
        sales = [_sale("Oz", 1), _sale("Oz", 2), _sale("Oz", 3)]
        self.ns["_count_sales"](counts, sales, refused=frozenset({("Oz", 2)}))
        self.assertEqual({"Oz": 2}, counts)

    def test_a_route_sale_is_matched_by_its_candidate(self):
        counts = {"Oz": 0}
        self.ns["_count_sales"](
            counts,
            [_wrapped("Oz", 7), _wrapped("Oz", 8)],
            refused=frozenset({("Oz", 7)}),
        )
        self.assertEqual({"Oz": 1}, counts)

    def test_the_same_guid_on_another_holder_still_counts(self):
        counts = {}
        self.ns["_count_sales"](
            counts, [_sale("Uzza", 2)], refused=frozenset({("Oz", 2)})
        )
        self.assertEqual({"Uzza": 1}, counts)

    def test_without_a_refusal_set_it_counts_as_before(self):
        counts = {}
        self.ns["_count_sales"](counts, [_sale("Oz", 1), _sale("Oz", 2)])
        self.assertEqual({"Oz": 2}, counts)


def _policy_ns(facts, verdicts, fail=False):
    log = _Log()

    def fetch(guids):
        if fail:
            raise OSError("db down")
        return [dict(item_guid=g, **facts[g]) for g in guids if g in facts]

    ns = _load(
        ["_sale_guid", "_policy_refused_pairs"],
        {
            "log": log,
            "lootpolicy": lootpolicy,
            "_fetch_epic_facts": fetch,
            "_guild_classes": lambda: frozenset({1}),
            "_policy_verdict": lambda holder, row, classes: verdicts[row["item_guid"]],
        },
    )
    return ns, log


V = lootpolicy.Verdict


class RefusedPairsAreTheWritersAnswer(unittest.TestCase):
    def test_the_six_stacks_logged_for_oz_are_all_refused(self):
        routes = [
            lootpolicy.DISENCHANT,
            lootpolicy.HOLD,
            lootpolicy.HOLD,
            lootpolicy.UPGRADE,
            lootpolicy.UPGRADE,
            lootpolicy.BANK_OR_AUCTION,
        ]
        verdicts = {100 + i: V(r, "why") for i, r in enumerate(routes)}
        facts = {g: {} for g in verdicts}
        ns, _ = _policy_ns(facts, verdicts)
        sales = [_sale("Oz", g) for g in verdicts]
        refused = ns["_policy_refused_pairs"](sales)
        self.assertEqual({("Oz", g) for g in verdicts}, set(refused))
        counts = {"Oz": 0}
        _load(["_count_sales"], ns)["_count_sales"](counts, sales, refused)
        self.assertEqual({"Oz": 0}, counts)
        # Nothing a vendor would buy, so no trip lifts the member at one slot.
        self.assertFalse(bag_pressure.vendor_trip_makes_room({"Oz": 1}, counts))

    def test_a_vendor_verdict_is_not_refused(self):
        verdicts = {1: V(lootpolicy.VENDOR, "gray or junk")}
        ns, _ = _policy_ns({1: {}}, verdicts)
        self.assertEqual(frozenset(), ns["_policy_refused_pairs"]([_sale("Oz", 1)]))

    def test_a_stack_with_no_facts_is_refused_like_the_writer_holds_it(self):
        ns, _ = _policy_ns({}, {})
        self.assertEqual(
            frozenset({("Oz", 5)}), ns["_policy_refused_pairs"]([_sale("Oz", 5)])
        )

    def test_a_failed_read_refuses_nothing_and_says_so(self):
        ns, log = _policy_ns({}, {}, fail=True)
        self.assertEqual(frozenset(), ns["_policy_refused_pairs"]([_sale("Oz", 5)]))

    def test_route_sales_are_read_through_their_candidate(self):
        verdicts = {9: V(lootpolicy.HOLD, "bound")}
        ns, _ = _policy_ns({9: {}}, verdicts)
        self.assertEqual(
            frozenset({("Oz", 9)}), ns["_policy_refused_pairs"]([_wrapped("Oz", 9)])
        )

    def test_nothing_to_read_is_no_read(self):
        ns, _ = _policy_ns({}, {}, fail=True)
        self.assertEqual(frozenset(), ns["_policy_refused_pairs"]([]))


if __name__ == "__main__":
    unittest.main()
