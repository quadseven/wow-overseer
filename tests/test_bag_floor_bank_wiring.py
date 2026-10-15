"""The floor's last resort is wired through the town pass (#1000).

Measured 2026-10-15: a family was held 0.93 hours at the bag floor on "Grog
carries nothing a vendor will buy: 53 stack(s) kept". The vendor cannot help
such a member, so the next bank pass must: bank.py's `floor_bank` plans the
deposits, and this file pins the bridge half - the vendor pass's dry list
reaches the bank plan, and the hold reason names what was banked, or that
the bank is full.

Pinned here:

  * `_note_bag_floor` records a floor member with nothing sold in
    `_BAG_FLOOR_DRY`, and drops it when the member leaves the floor or the
    vendor pass finds something to sell.
  * `_plan_bank` hands exactly the dry members to `bank.plan` as
    `floor_bank`.
  * `_note_banked_why` records what the bank pass banked for a floor member,
    or that the bank is full; a pass that banked nothing with room to spare
    leaves no stale sentence behind.
  * `_bag_hold_why` names the bank's outcome for a held member while it
    stands, instead of the vendor's older news.
  * `_prune_bag_hold_stuck` drops inactive names from both new dicts.
"""

import ast
import pathlib
import unittest

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

NAMES = ["Bork", "Grog"]
KEY = tuple(sorted(NAMES))


def _functions(*names):
    found = {
        node.name: node
        for node in ast.walk(ast.parse(BRIDGE))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    }
    missing = set(names) - set(found)
    if missing:
        raise AssertionError("not found in bridge.py: %s" % sorted(missing))
    return [found[n] for n in names]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


class BagPressure:
    TOWN_RUN_FREE_SLOTS = 3

    @staticmethod
    def floor_reason(name, sellable, rows, keep_names=()):
        return "%s carries nothing a vendor will buy" % name


class Move:
    def __init__(self, character, verb, item, to):
        self.character = character
        self.verb = verb
        self.item = item
        self.to = to


class Plan:
    def __init__(self, moves=(), notes=()):
        self.moves = moves
        self.notes = notes


class Bank:
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"
    PERSONAL = "PERSONAL"
    GUILD = "GUILD"

    def __init__(self):
        self.planned = []

    def storage_from(self, *args, **kwargs):
        return object()

    def members_from_rows(self, rows, names):
        return names

    def family_from_skills(self, held):
        return held

    def plan(self, members, family, **kwargs):
        self.planned.append(kwargs)
        return Plan()


class Forecast:
    def __init__(self):
        self.over_target = {}


class CrafterPlan:
    def __init__(self):
        self.routed = set()


class Hold:
    def __init__(self, since, best):
        self.since = since
        self.best = best


def _bridge():
    clock = Clock()
    bank = Bank()
    ns = {
        "bag_pressure": BagPressure(),
        "townerrand": None,
        "time": clock,
        "OWNER_KEEPS": (),
        "REAGENT_TRADES": frozenset(),
        "_GUILD_BANK_KEEPS": {},
        "_BAG_HOLD": {},
        "_BAG_HOLD_STUCK": {},
        "_BAG_FLOOR_WHY": {},
        "_TOWN_PASS_NOTE": {},
        "_BAG_HOLD_SAID": {},
        "_TOWN_ERRANDS": {},
        "_BAG_FLOOR_DRY": set(),
        "_BAG_BANKED_WHY": {},
        "bank": bank,
        "_fetch_bank_items": lambda names: [],
        "_fetch_trade_skills": lambda names: {},
        "_worked_by": lambda names: {},
        "_fetch_guild_bank_setup": lambda names: None,
        "_crafter_plan": lambda names: CrafterPlan(),
        "_tidy_routes": lambda names: set(),
        "_withdrawn_for_sale_routes": lambda names: set(),
        "_bank_policy": lambda names: {},
        "_bank_spare": lambda names: frozenset(),
        "_bank_forecast": lambda names: Forecast(),
        "_campaign_waiting": lambda names: False,
    }
    exec(  # noqa: S102 - bridge.py's own source
        compile(
            ast.Module(
                body=_functions(
                    "_note_bag_floor",
                    "_note_banked_why",
                    "_bag_hold_why",
                    "_plan_bank",
                    "_prune_bag_hold_stuck",
                ),
                type_ignores=[],
            ),
            "bridge.py",
            "exec",
        ),
        ns,
    )
    return ns, bank


class TheDryList(unittest.TestCase):
    def test_a_floor_member_with_nothing_sold_is_dry(self):
        ns, _ = _bridge()
        ns["_note_bag_floor"](
            NAMES, {"Bork": 15, "Grog": 0}, [], {"Bork": 4, "Grog": 0}
        )
        self.assertEqual({"Grog"}, ns["_BAG_FLOOR_DRY"])
        self.assertIn("Grog", ns["_BAG_FLOOR_WHY"])

    def test_a_floor_member_with_something_to_sell_is_not_dry(self):
        ns, _ = _bridge()
        ns["_note_bag_floor"](
            NAMES, {"Bork": 15, "Grog": 2}, [], {"Bork": 4, "Grog": 1}
        )
        self.assertEqual(set(), ns["_BAG_FLOOR_DRY"])

    def test_leaving_the_floor_clears_the_dry_and_banked_notes(self):
        ns, _ = _bridge()
        ns["_BAG_FLOOR_DRY"].add("Grog")
        ns["_BAG_BANKED_WHY"]["Grog"] = "Grog banked 2 stack(s): Linen Cloth"
        ns["_note_bag_floor"](
            NAMES, {"Bork": 15, "Grog": 9}, [], {"Bork": 4, "Grog": 1}
        )
        self.assertEqual(set(), ns["_BAG_FLOOR_DRY"])
        self.assertNotIn("Grog", ns["_BAG_BANKED_WHY"])
        self.assertNotIn("Grog", ns["_BAG_FLOOR_WHY"])


class ThePlanTakesTheDryList(unittest.TestCase):
    def test_only_dry_members_reach_the_plan(self):
        ns, bank = _bridge()
        ns["_BAG_FLOOR_DRY"].update({"Grog", "Og"})
        ns["_plan_bank"](["Bork", "Grog"])
        self.assertEqual({"Grog"}, bank.planned[0]["floor_bank"])

    def test_an_empty_dry_list_plans_as_before(self):
        ns, bank = _bridge()
        ns["_plan_bank"](NAMES)
        self.assertEqual(set(), bank.planned[0]["floor_bank"])


class TheBankedNote(unittest.TestCase):
    def test_deposits_are_named(self):
        ns, _ = _bridge()
        plan = Plan(
            moves=(
                Move("Grog", Bank.DEPOSIT, "Linen Cloth", Bank.PERSONAL),
                Move("Grog", Bank.DEPOSIT, "Linen Cloth", Bank.PERSONAL),
                Move("Grog", Bank.DEPOSIT, "Green Chest", Bank.PERSONAL),
            )
        )
        ns["_note_banked_why"](NAMES, plan, {"Grog"})
        self.assertEqual(
            "Grog banked 3 stack(s): 2 Linen Cloth, Green Chest",
            ns["_BAG_BANKED_WHY"]["Grog"],
        )

    def test_a_full_bank_is_named(self):
        ns, _ = _bridge()
        plan = Plan(notes=(("Grog's bank is full, so Green Chest stays in the bags"),))
        ns["_note_banked_why"](NAMES, plan, {"Grog"})
        self.assertEqual(
            "Grog's bank is full, so its town pass cannot make room",
            ns["_BAG_BANKED_WHY"]["Grog"],
        )

    def test_a_quiet_pass_leaves_no_stale_sentence(self):
        ns, _ = _bridge()
        ns["_BAG_BANKED_WHY"]["Grog"] = "Grog banked 1 stack(s): Linen Cloth"
        ns["_note_banked_why"](NAMES, Plan(), {"Grog"})
        self.assertNotIn("Grog", ns["_BAG_BANKED_WHY"])

    def test_withdrawals_and_guild_moves_are_not_banked_news(self):
        ns, _ = _bridge()
        plan = Plan(
            moves=(
                Move("Grog", Bank.WITHDRAW, "Linen Cloth", Bank.PERSONAL),
                Move("Grog", Bank.DEPOSIT, "Linen Cloth", Bank.GUILD),
            )
        )
        ns["_note_banked_why"](NAMES, plan, {"Grog"})
        self.assertNotIn("Grog", ns["_BAG_BANKED_WHY"])

    def test_members_off_the_list_are_untouched(self):
        ns, _ = _bridge()
        plan = Plan(moves=(Move("Grog", Bank.DEPOSIT, "Linen Cloth", Bank.PERSONAL),))
        ns["_note_banked_why"](NAMES, plan, set())
        self.assertNotIn("Grog", ns["_BAG_BANKED_WHY"])


class TheHoldNamesTheBank(unittest.TestCase):
    def _held(self, ns, banked=()):
        ns["_BAG_HOLD"][KEY] = Hold(since=1000.0 - 3600.0, best=[("Grog", 0)])
        ns["_BAG_FLOOR_WHY"]["Grog"] = "Grog carries nothing a vendor will buy"
        for name, note in banked:
            ns["_BAG_BANKED_WHY"][name] = note

    def test_what_was_banked_is_the_reason(self):
        ns, _ = _bridge()
        self._held(ns, [("Grog", "Grog banked 3 stack(s): 2 Linen Cloth")])
        why = ns["_bag_hold_why"](NAMES)
        self.assertIn("Grog banked 3 stack(s): 2 Linen Cloth", why)
        self.assertNotIn("carries nothing a vendor will buy", why)

    def test_a_full_bank_is_the_reason(self):
        ns, _ = _bridge()
        self._held(
            ns, [("Grog", ("Grog's bank is full, so its town pass cannot make room"))]
        )
        why = ns["_bag_hold_why"](NAMES)
        self.assertIn("Grog's bank is full", why)

    def test_without_bank_news_the_vendor_part_stands(self):
        ns, _ = _bridge()
        self._held(ns)
        why = ns["_bag_hold_why"](NAMES)
        self.assertIn("Grog carries nothing a vendor will buy", why)


class ThePrune(unittest.TestCase):
    def test_inactive_names_leave_both_dicts(self):
        ns, _ = _bridge()
        ns["_BAG_FLOOR_DRY"].add("Gone")
        ns["_BAG_BANKED_WHY"]["Gone"] = "Gone banked 1 stack(s): Linen Cloth"
        ns["_prune_bag_hold_stuck"]({"f": {"names": list(NAMES)}})
        self.assertEqual(set(), ns["_BAG_FLOOR_DRY"])
        self.assertEqual({}, ns["_BAG_BANKED_WHY"])


if __name__ == "__main__":
    unittest.main()
