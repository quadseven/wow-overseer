"""The errand recall cannot loop, and no economy aim is taken inside an
instance, whichever pass asks (#2323).

Pre-ship review of the door recall (#2280) found the recall cooldown and the
instance guard read by one aim writer only. Every test here drives bridge.py's
own functions, loaded from its source, against a small fake world: the door
verdict, the town slot door every economy pass asks, the bag pressure aim and
the vendor pass's release. A helper that is renamed, or a caller that stops
asking it, fails these; nothing here reads the source as text except the scan
at the end, which is what refuses a NEW aim writer that asks nobody.
"""

import ast
import asyncio
import importlib
import inspect
import pathlib
import types
import unittest
import unittest.mock

from test_bag_withheld_stall import _FakeEconomySelf, _run_vendor_once

import bag_pressure
import campaignqueue
import claims
import dungeonstall as stall
import errandgate
import jev_family_intent
import jobs
import professions
import townslot
import weaponskill

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
TREE = ast.parse(BRIDGE)
FUNCTIONS = {
    node.name: node
    for node in ast.walk(TREE)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
ECONOMY_AIMS = ("vendor", "banker", "guild banker", "repair")
HEAD = {"id": 7, "keyword": "maraudon-orange", "status": "active"}
INSTANCE_MAP = 230

# The helpers this change adds. A test that tells the story of the bug loads
# them when the source has them, so it fails on the old source by what the
# passes DID; the wiring tests below require them by name.
GATE = ("_economy_aim_hold", "_errand_clock_start")


def _load(names, namespace, optional=()):
    body = [FUNCTIONS[n] for n in names]
    body += [FUNCTIONS[n] for n in optional if n in FUNCTIONS]
    exec(
        compile(ast.Module(body=body, type_ignores=[]), "bridge.py", "exec"), namespace
    )  # noqa: S102 - bridge.py's own source
    return namespace


class World:
    """One family at a door: Zug leads, Oz is the member with errands."""

    def __init__(self):
        self.clock = [1000.0]
        self.aims = {}
        self.maps = {"Zug": 0, "Oz": 0}
        self.positions = {
            "Zug": {"map_id": 1, "instance_id": 0, "pos_x": 0, "pos_y": 0, "pos_z": 0},
            "Oz": {"map_id": 1, "instance_id": 0, "pos_x": 0, "pos_y": 0, "pos_z": 0},
        }
        self.released = []
        self.writes = []
        self.logs = []
        self.recalled = {}
        self.slot = townslot.Slot(releasable=lambda aim: aim in ECONOMY_AIMS)
        self.claims = claims.Claims()

    def release(self, name, aim):
        if self.aims.get(name) != aim:
            return False
        self.released.append((name, aim))
        del self.aims[name]
        self.positions[name]["pos_x"] = 0
        return True

    def write(self, errand):
        if self.aims.get(errand.character, "") not in ("", errand.travel_npc):
            return False
        self.writes.append((errand.character, errand.travel_npc))
        self.aims[errand.character] = errand.travel_npc
        self.positions[errand.character]["pos_x"] = 2500
        return True

    def members(self, leader, head_id):
        state = stall.ERRAND_STATE if self.aims.get("Oz") else "following"
        return 0, (jev_family_intent.Member("Oz", state, "0"),)

    def namespace(self, strict=False):
        async def to_thread(fn, *args):
            return fn(*args)

        log = types.SimpleNamespace(
            info=lambda *a, **k: self.logs.append(a),
            debug=lambda *a, **k: None,
            warning=lambda *a, **k: self.logs.append(a),
        )
        ns = {
            "asyncio": types.SimpleNamespace(to_thread=to_thread),
            "bag_pressure": bag_pressure,
            "campaignqueue": campaignqueue,
            "dungeonpath": types.SimpleNamespace(PORTAL_MAPS={"brd": INSTANCE_MAP}),
            "dungeonstall": stall,
            "errandgate": errandgate,
            "jobs": jobs,
            "log": log,
            "professions": professions,
            "raidrun": types.SimpleNamespace(MAPS={}, is_raid=lambda keyword: False),
            "time": types.SimpleNamespace(monotonic=lambda: self.clock[0]),
            "townslot": townslot,
            "WEAPON_SKILL_CLAIMANT": "weapon master",
            "_DOOR_HOLD_SINCE": {},
            "DOOR_HOLD_RECOVER_YARDS": 1500,
            "_ERRAND_HOLD_SAID": {},
            "_ERRAND_RECALLED": self.recalled,
            "_ERRAND_SERVED": {},
            "_current_travel_npc": lambda name: self.aims.get(name, ""),
            "_door_run_boss_age": lambda leader: None,
            "_door_wedge_evidence": self.members,
            "_fetch_live_maps": lambda names: {
                n: self.maps[n] for n in names if n in self.maps
            },
            "_fetch_positions": lambda names: {
                n: {
                    **self.positions[n],
                    "pos_x": 2500 if self.aims.get(n) else 0,
                }
                for n in names
                if n in self.positions
            },
            "_head_now": lambda: "Oz",
            "_is_economy_aim": lambda aim: aim in ECONOMY_AIMS,
            "_jobs_of": lambda names: {n: "dungeon:maraudon-orange" for n in names},
            "_release_trade_errand": self.release,
            "_retaskable_from": lambda aim: ("", aim) if aim in ECONOMY_AIMS else (),
            "_write_trade_errand": self.write,
        }
        names = [
            "_claim_town_slot",
            "_door_held_verdict",
            "_door_wedge",
            "_door_wedge_ages",
            "_door_wedge_member_recovered",
            "_members_inside_instance",
            "_recall_door_errands",
            "_release_instance_economy_aims",
        ]
        if strict:
            return _load(names + list(GATE), ns)
        return _load(names, ns, optional=GATE)

    def adapter(self):
        return types.SimpleNamespace(
            _claims=self.claims,
            _cohort_town_slot=lambda cohort: self.slot,
        )

    def ask(self, ns, claimant, aim):
        """The pass `claimant` asks the town slot door for Oz, as it does."""
        return asyncio.run(ns["_claim_town_slot"](self.adapter(), claimant, "Oz", aim))

    def judge(self, ns):
        return ns["_door_wedge"](dict(HEAD), ["Zug", "Oz"], "Zug")


class ARecallCannotLoop(unittest.TestCase):
    """Recall at ten minutes, a new aim, recall at ten minutes again: the 30
    minute stand-down never came due, because every recall restarted the
    member's clock and only the bag pressure aim read the cooldown."""

    def test_the_bank_pass_does_not_aim_a_recalled_member_again(self):
        """Fails before the change: the bank pass asked nobody, and the
        member was walking to the banker again on the next cycle."""
        world = World()
        ns = world.namespace()
        world.aims["Oz"] = "vendor"
        world.judge(ns)
        world.clock[0] += stall.RECALL_SECONDS
        self.assertIsNone(world.judge(ns))
        self.assertEqual([("Oz", "vendor")], world.released)
        world.clock[0] += 30
        self.assertFalse(world.ask(ns, "bank", "banker"))
        self.assertEqual([], world.writes)
        self.assertNotIn("Oz", world.aims)

    def test_the_cooldown_reaches_every_economy_pass_alike(self):
        world = World()
        ns = world.namespace()
        world.recalled["Oz"] = world.clock[0]
        world.clock[0] += 60
        asks = (
            ("economy", "vendor"),
            ("bank", "banker"),
            ("guild bank", "guild banker"),
            ("towntrip", "repair"),
            ("craft_supply", "vendor"),
            ("forge", "vendor"),
        )
        for claimant, aim in asks:
            self.assertFalse(world.ask(ns, claimant, aim), claimant)
        self.assertEqual([], world.writes)

    def test_the_cooldown_ends_and_the_pass_aims_again(self):
        world = World()
        ns = world.namespace()
        world.recalled["Oz"] = world.clock[0]
        world.clock[0] += stall.RECALL_COOLDOWN_SECONDS
        self.assertTrue(world.ask(ns, "bank", "banker"))
        self.assertEqual([("Oz", "banker")], world.writes)

    def test_a_pass_that_is_not_the_economys_is_not_held(self):
        world = World()
        ns = world.namespace()
        world.recalled["Oz"] = world.clock[0]
        world.maps["Oz"] = INSTANCE_MAP
        self.assertTrue(world.ask(ns, "dungeon quests", "vendor"))
        self.assertEqual([("Oz", "vendor")], world.writes)

    def test_a_held_aim_is_said_once_and_names_the_pass(self):
        world = World()
        ns = world.namespace()
        world.recalled["Oz"] = world.clock[0]
        for _ in range(3):
            world.clock[0] += 30
            world.ask(ns, "bank", "banker")
        said = [a for a in world.logs if a and a[0] == "economy: %s"]
        self.assertEqual(1, len(said))
        self.assertIn("Oz", said[0][1])
        self.assertIn("bank", said[0][1])

    def test_two_recalls_with_a_new_aim_between_end_in_the_stand_down(self):
        """Fails before the change: the second recall restarted the clock, so
        the member was recalled every ten minutes and the run never stood
        down. The aim between the recalls is the bank pass's own ask; where
        the door now refuses it, the aim is put on the member anyway, the way
        a writer the cooldown does not cover would, because the clock must
        hold even then."""
        world = World()
        ns = world.namespace()
        world.aims["Oz"] = "vendor"
        world.judge(ns)
        recalls, verdict = 0, None
        for _ in range(2 * stall.HOLD_SECONDS // 60):
            world.clock[0] += 60
            before = len(world.released)
            verdict = world.judge(ns)
            if verdict is not None:
                break
            if len(world.released) > before:
                recalls += 1
                world.judge(ns)  # the member is seen back with the party
                world.ask(ns, "bank", "banker")
                world.aims["Oz"] = "banker"
        self.assertIsNotNone(verdict, "the run was never stood down")
        self.assertGreaterEqual(recalls, 2)
        self.assertIn("Oz", verdict.why)
        self.assertIn("a trip to the bank", verdict.why)
        self.assertLessEqual(world.clock[0] - 1000.0, stall.HOLD_SECONDS + 60)

    def test_a_member_at_the_stand_down_bound_is_not_recalled_again(self):
        world = World()
        ns = world.namespace(strict=True)
        world.aims["Oz"] = "banker"
        ages = {"Oz": (stall.ERRAND_STATE, float(stall.HOLD_SECONDS))}
        self.assertEqual([], ns["_recall_door_errands"]("Zug", ages, 7))
        self.assertEqual([], world.released)

    def test_one_recall_that_takes_does_not_stand_the_run_down(self):
        """The member goes back to the party and stays: no verdict, and the
        errand it takes once the cooldown is over starts a clock of its own."""
        world = World()
        ns = world.namespace(strict=True)
        world.aims["Oz"] = "vendor"
        world.judge(ns)
        world.clock[0] += stall.RECALL_SECONDS
        self.assertIsNone(world.judge(ns))
        world.clock[0] += stall.RECALL_COOLDOWN_SECONDS
        self.assertIsNone(world.judge(ns))
        self.assertTrue(world.ask(ns, "bank", "banker"))
        world.clock[0] += 60
        self.assertIsNone(world.judge(ns))
        world.clock[0] += stall.RECALL_SECONDS - 120
        self.assertIsNone(world.judge(ns))
        self.assertEqual([("Oz", "vendor")], world.released)

    def test_a_new_queue_entry_starts_the_clock_over(self):
        world = World()
        ns = world.namespace(strict=True)
        key = ("Zug", "Oz", stall.ERRAND_STATE)
        ns["_ERRAND_SERVED"][("Zug", "Oz")] = errandgate.Served(7, 600.0, 1000.0)
        self.assertEqual(400.0, ns["_errand_clock_start"](key, 7, 1060.0))
        self.assertEqual(1060.0, ns["_errand_clock_start"](key, 8, 1060.0))
        dead = ("Zug", "Oz", "dead")
        self.assertEqual(1060.0, ns["_errand_clock_start"](dead, 7, 1060.0))


class NoEconomyAimInsideAnInstance(unittest.TestCase):
    """The release ran only while a run row was open, and only the bag
    pressure aim refused a member on an instance map."""

    def test_a_member_inside_with_no_run_row_ends_with_no_economy_aim(self):
        """Fails before the change: the aim taken before the member went
        inside stood, because the vendor pass released only in its in-run
        branch. The whole vendor pass is run here with no run row (its
        `_mid_run` answers False), beside the bridge's own release."""
        released = vendor_pass_release(in_run=False, aim="banker")
        self.assertEqual([("Zug", "banker")], released)

    def test_a_member_inside_with_no_run_row_is_not_aimed_by_the_bank_pass(self):
        """Fails before the change: only the bag pressure aim read the map."""
        world = World()
        ns = world.namespace()
        world.maps["Oz"] = INSTANCE_MAP
        self.assertFalse(world.ask(ns, "bank", "banker"))
        self.assertEqual([], world.writes)
        self.assertEqual({}, world.aims)

    def test_the_vendor_pass_still_releases_during_a_run(self):
        self.assertEqual([("Zug", "vendor")], vendor_pass_release(in_run=True))

    def test_a_member_outside_keeps_its_aim_through_the_vendor_pass(self):
        self.assertEqual([], vendor_pass_release(in_run=False, inside=False))
        self.assertEqual([], vendor_pass_release(in_run=True, inside=False))

    def test_every_economy_pass_refuses_a_member_inside(self):
        world = World()
        ns = world.namespace()
        world.maps["Oz"] = INSTANCE_MAP
        for claimant in sorted(errandgate.ECONOMY_CLAIMANTS - {"bag pressure"}):
            self.assertFalse(world.ask(ns, claimant, "vendor"), claimant)
        self.assertEqual([], world.writes)

    def test_an_unreadable_map_holds_nothing(self):
        world = World()
        ns = world.namespace()
        ns["_fetch_live_maps"] = lambda names: None
        self.assertTrue(world.ask(ns, "bank", "banker"))

    def test_an_aim_the_economy_did_not_write_is_left_inside(self):
        world = World()
        ns = world.namespace(strict=True)
        world.maps["Oz"] = INSTANCE_MAP
        world.aims["Oz"] = "trainer:985"
        self.assertEqual([], ns["_release_instance_economy_aims"](["Oz"]))
        self.assertEqual({"Oz": "trainer:985"}, world.aims)


PRESSED = ["Grug", "Bork", "Grog"]
PRESSED_AT = {
    "Grug": {"map_id": 0, "pos_x": 0.0, "pos_y": 0.0},
    "Bork": {"map_id": 0, "pos_x": 2000.0, "pos_y": 0.0},
    "Grog": {"map_id": 0, "pos_x": 1400.0, "pos_y": 0.0},
}
PRESSED_SLOTS = {"Grug": 13, "Bork": 2, "Grog": 0}


def bag_pressure_pass(maps=None, recalled=None, now=1000.0):
    """Run the bag pressure aim for Grug's family, Bork and Grog cut off and
    short of bag room, with the bridge's own helpers beside it. Returns (the
    count it reports, the members it wrote an aim for)."""
    writes = []
    maps = maps or {}

    async def to_thread(fn, *args):
        return fn(*args)

    ns = {
        "asyncio": types.SimpleNamespace(to_thread=to_thread),
        "bag_pressure": bag_pressure,
        "dungeonpath": types.SimpleNamespace(PORTAL_MAPS={"brd": INSTANCE_MAP}),
        "errandgate": errandgate,
        "log": types.SimpleNamespace(info=lambda *a, **k: None),
        "professions": professions,
        "raidrun": types.SimpleNamespace(MAPS={}),
        "time": types.SimpleNamespace(monotonic=lambda: now),
        "townslot": townslot,
        "_ERRAND_HOLD_SAID": {},
        "_ERRAND_RECALLED": dict(recalled or {}),
        "_current_travel_npc": lambda name: "",
        "_fetch_live_maps": lambda names: {n: maps.get(n, 0) for n in names},
        "_is_economy_aim": lambda aim: aim == "vendor",
        "_write_trade_errand": lambda errand: writes.append(errand.character) or True,
    }
    _load(
        [
            "_aim_stranded_bag_pressure_members",
            "_economy_aim_hold",
            "_economy_aimable",
            "_members_inside_instance",
        ],
        ns,
    )
    adapter = types.SimpleNamespace(_claims=claims.Claims(), _stranded_vendor_slots={})
    aimed = asyncio.run(
        ns["_aim_stranded_bag_pressure_members"](
            adapter, PRESSED, "Grug", PRESSED_AT, PRESSED_SLOTS, False
        )
    )
    return aimed, writes


def vendor_pass_release(in_run, inside=True, aim="vendor"):
    """Run the whole vendor pass for Zug carrying `aim`, with or without a run
    row, beside the bridge's own release. Returns what was handed back."""
    world = World()
    ns = world.namespace()
    world.maps["Zug"] = INSTANCE_MAP if inside else 0
    world.aims["Zug"] = aim

    async def mid_run(self, names):
        return in_run

    with unittest.mock.patch.object(_FakeEconomySelf, "_mid_run", mid_run):
        _run_vendor_once(
            queued=False,
            extra={
                "_release_instance_economy_aims": ns["_release_instance_economy_aims"]
            },
        )
    return world.released


class TheBagPressureAimAsksTheSameHelper(unittest.TestCase):
    """The wiring, driven: the pass itself is run with the bridge's own
    helpers beside it, and what it wrote is read."""

    def test_both_cut_off_members_are_aimed_when_nothing_holds_them(self):
        self.assertEqual((2, ["Bork", "Grog"]), bag_pressure_pass())

    def test_the_pass_reads_who_is_inside_before_it_aims(self):
        got = bag_pressure_pass(maps={"Bork": INSTANCE_MAP})
        self.assertEqual((1, ["Grog"]), got)

    def test_the_pass_skips_a_member_in_its_recall_cooldown(self):
        self.assertEqual((1, ["Bork"]), bag_pressure_pass(recalled={"Grog": 940.0}))

    def test_the_pass_aims_a_member_whose_cooldown_is_over(self):
        recalled = {"Grog": 1000.0 - stall.RECALL_COOLDOWN_SECONDS}
        self.assertEqual((2, ["Bork", "Grog"]), bag_pressure_pass(recalled=recalled))


def _mentions(node) -> set:
    """Every name and string a function mentions: a helper reached through
    `globals().get("name")` is a string, one called directly is a name."""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.add(sub.value)
    return out


def _module_strings(tree) -> dict:
    """The module's NAME = "text" constants."""
    out = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _claimant_of(arg, constants) -> str | None:
    """The claimant a `_claim_town_slot` call names, or None when the scan
    cannot read it."""
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Name):
        return constants.get(arg.id)
    if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
        module = importlib.import_module(arg.value.id)
        return getattr(module, arg.attr, None)
    return None


class NoAimWriterBypassesTheHelper(unittest.TestCase):
    """Parse the town-slot callers so prose cannot count as a claim."""

    MODULES = {
        "bridge.py": TREE,
        "weaponskill.py": ast.parse(inspect.getsource(weaponskill)),
    }
    HELPER = "_economy_aim_hold"
    # The same check over a list of names, for a pass that aims several.
    HELPERS = frozenset({"_economy_aim_hold", "_economy_aimable"})
    DOOR = "_claim_town_slot"
    WRITE = "_write_trade_errand"
    # The functions that write the travel column without asking the helper,
    # and why each is not an economy aim writer.
    NOT_ECONOMY_WRITERS = {
        "_send_trade_errand": "writes a profession plan's trainer errand, "
        "which the economy never hands back",
        "_keep_at_auctioneer": "re-asserts an aim the column already carries; "
        "a new aim goes through the door",
    }

    def claims(self):
        for filename, tree in self.MODULES.items():
            constants = _module_strings(tree)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == self.DOOR
                ):
                    yield (
                        f"{filename}:{node.lineno}",
                        _claimant_of(node.args[0], constants),
                    )

    def test_the_door_asks_the_helper_before_it_reads_the_slot(self):
        self.assertTrue(
            self.HELPER in _mentions(FUNCTIONS[self.DOOR]),
            "%s does not ask %s" % (self.DOOR, self.HELPER),
        )

    def test_every_pass_that_asks_the_door_is_classified(self):
        known = set(errandgate.ECONOMY_CLAIMANTS) | set(errandgate.OTHER_CLAIMANTS)
        seen, unknown = set(), []
        for location, claimant in self.claims():
            seen.add(claimant)
            if claimant not in known:
                unknown.append(f"{location}: {claimant!r}")
        self.assertEqual(
            [],
            unknown,
            "these passes ask the town slot under a claimant errandgate does "
            "not know. Add the name to errandgate.ECONOMY_CLAIMANTS (held by "
            "the recall cooldown and the instance guard) or to "
            "errandgate.OTHER_CLAIMANTS with the reason it is not",
        )
        self.assertGreaterEqual(len(seen), 20)

    def test_no_classified_claimant_is_left_without_a_pass(self):
        seen = {claimant for _line, claimant in self.claims()}
        seen.add("bag pressure")  # the one aim written beside the door
        known = set(errandgate.ECONOMY_CLAIMANTS) | set(errandgate.OTHER_CLAIMANTS)
        self.assertEqual(set(), known - seen)

    def test_every_writer_beside_the_door_asks_the_helper(self):
        offenders = []
        for filename, tree in self.MODULES.items():
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name == self.DOOR or node.name in self.NOT_ECONOMY_WRITERS:
                    continue
                names = _mentions(node)
                if self.WRITE in names and not names & self.HELPERS:
                    offenders.append(f"{node.name} ({filename}:{node.lineno})")
        self.assertEqual(
            [],
            offenders,
            "these write the travel column without asking %s, so a recalled "
            "member or one inside an instance can be aimed by them: route "
            "the write through the town slot door, ask the helper, or name "
            "the function in NOT_ECONOMY_WRITERS with its reason" % self.HELPER,
        )

    def test_the_excused_writers_still_exist_and_still_write(self):
        for name in self.NOT_ECONOMY_WRITERS:
            self.assertIn(name, FUNCTIONS)
            self.assertIn(self.WRITE, _mentions(FUNCTIONS[name]), name)

    def test_the_scan_sees_a_writer_that_asks_nobody(self):
        """The scan is not vacuous: a pass written the old way is caught."""
        rogue = ast.parse(
            "async def _rogue(self, name):\n"
            "    await asyncio.to_thread(_write_trade_errand, name)\n"
        ).body[0]
        names = _mentions(rogue)
        self.assertIn(self.WRITE, names)
        self.assertFalse(names & self.HELPERS)

    def test_the_list_helper_asks_the_one_check(self):
        self.assertIn(self.HELPER, _mentions(FUNCTIONS["_economy_aimable"]))


if __name__ == "__main__":
    unittest.main()
