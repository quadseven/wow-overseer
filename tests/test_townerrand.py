"""The town errand: one bounded trip to the capital, every step while parked.

The dev realm, 2026-09-27: three rounds of fixes to the separate mail and
vendor passes moved slots worn by almost nothing, because the family was
always walking when a row was written. `townerrand` parks the family first.
Pinned here: the states and their exits, and the bridge adapter driven
tick by tick against fakes, including that no mail take is written for a
member who is not standing at the mailbox.
"""

import ast
import asyncio
import pathlib
import types
import unittest

import mailrun
import townerrand as te

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
HUB = {"map_id": 0, "x": 100.0, "y": 100.0, "z": 10.0, "auctioneer": "Auctioneer"}
FACTS = {
    "Bork": {"equipped": {"finger1": 21}, "purse": 800},
    "Grug": {"equipped": {"head": 45}, "purse": 500000},
}


def _at(x, y, map_id=0):
    return {"map_id": map_id, "pos_x": x, "pos_y": y}


class TheStates(unittest.TestCase):
    def test_gear_in_the_post_starts_it(self):
        why = te.should_start(
            te.State(), now=0, in_run=False, mail_gear={"Bork": 3}, facts={}
        )
        self.assertIn("Bork", why)

    def test_a_short_member_with_its_own_gold_starts_it(self):
        why = te.should_start(
            te.State(), now=0, in_run=False, mail_gear={}, facts=FACTS
        )
        self.assertIn("Grug", why)
        self.assertNotIn("Bork", why)  # 8 silver is not enough to shop with

    def test_not_in_a_run_not_twice_and_not_inside_the_cooldown(self):
        args = dict(now=100.0, mail_gear={"Bork": 1}, facts={})
        self.assertEqual("", te.should_start(te.State(), in_run=True, **args))
        self.assertEqual(
            "", te.should_start(te.start(0, HUB, "x"), in_run=False, **args)
        )
        ended = te.State(phase=te.DONE, ended=50.0)
        self.assertEqual("", te.should_start(ended, in_run=False, **args))
        later = dict(args, now=50.0 + te.COOLDOWN_SECONDS)
        self.assertTrue(te.should_start(ended, in_run=False, **later))

    def test_go_waits_for_the_leader_at_the_mailbox(self):
        s = te.start(0.0, HUB, "why")
        s2, line = te.advance(s, 10.0, gathered=True)
        self.assertEqual(te.GO, s2.phase)
        s3, line = te.advance(s, 20.0, leader_at_hub=True)
        self.assertEqual(te.GATHER, s3.phase)
        self.assertIn("gathers", line)

    def test_a_walk_that_never_lands_releases_the_family(self):
        s, line = te.advance(te.start(0.0, HUB, "w"), te.GO_SECONDS)
        self.assertEqual(te.DONE, s.phase)
        self.assertIn("did not land", line)

    def test_gather_then_every_step_in_order_then_release(self):
        s = te.start(0.0, HUB, "w")
        s, _ = te.advance(s, 1.0, leader_at_hub=True)
        s, _ = te.advance(s, 2.0, gathered=True)
        seen = []
        t = 3.0
        while s.phase == te.STEPS:
            seen.append(s.current_step)
            s, line = te.advance(s, t, step_done=True)
            t += 1.0
        self.assertEqual(list(te.STEP_ORDER), seen)
        self.assertEqual(te.DONE, s.phase)
        self.assertIn("every step ran", line)

    def test_a_step_that_never_finishes_is_cut_at_its_window(self):
        s = te.State(phase=te.STEPS, started=0.0, phase_since=0.0, step=0, hub=HUB)
        s2, _ = te.advance(s, te.STEP_SECONDS[te.MAIL] - 1)
        self.assertEqual(te.MAIL, s2.current_step)
        s3, line = te.advance(s, te.STEP_SECONDS[te.MAIL])
        self.assertEqual(te.EQUIP, s3.current_step)
        self.assertIn("ran out of time", line)

    def test_the_ceiling_and_a_dungeon_run_both_release(self):
        s = te.start(0.0, HUB, "w")
        self.assertEqual(te.DONE, te.advance(s, te.TOTAL_SECONDS)[0].phase)
        self.assertEqual(te.DONE, te.advance(s, 5.0, in_run=True)[0].phase)

    def test_in_range_is_planar_and_same_map(self):
        self.assertTrue(te.in_range(HUB, _at(105, 105), 10))
        self.assertFalse(te.in_range(HUB, _at(120, 100), 10))
        self.assertFalse(te.in_range(HUB, _at(100, 100, 1), 10))
        self.assertFalse(te.in_range(HUB, None, 10))


def _functions(*names):
    out = []
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names
        ):
            out.append(node)
    assert len(out) == len(names), [n.name for n in out]
    return out


class Slot:
    def __init__(self):
        self.reserved = []

    def reserve(self, claimant, now, why):
        self.reserved.append(claimant)

    def unreserve(self, claimant):
        self.reserved.append("-" + claimant)


class Family:
    """The bridge as the errand sees it, and the world it reads."""

    def __init__(self, test):
        self.t = test
        self.slot = Slot()
        self.aims = []
        self.vendor_passes = 0

    async def _mid_run(self, names):
        return False

    def _cohort_town_slot(self, key=None):
        return self.slot

    async def _settled_positions(self, names):
        return dict(self.t.positions)

    async def _claim_town_slot(self, claimant, leader, aim, urgent=False, cohort=None):
        self.aims.append((claimant, leader, aim))
        return True

    async def _vendor_once(self, cohort=None):
        self.vendor_passes += 1


class TheAdapter(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.positions = {"Grug": _at(400, 400), "Bork": _at(401, 400)}
        self.written = []
        self.jobs = []
        letters = [
            {
                "holder": "Bork",
                "mail_id": 9,
                "money": 0,
                "cod": 0,
                "delivered": 1,
                "expire_time": 5,
                "item_guid": 77,
                "inventory_type": 5,
                "required_level": 30,
                "holder_level": 35,
            },
        ]
        ns = {
            "asyncio": asyncio,
            "log": types.SimpleNamespace(info=lambda *a, **k: None),
            "time": types.SimpleNamespace(monotonic=lambda: self.now),
            "townerrand": te,
            "mailrun": mailrun,
            "TOWN_COUNTER_YARDS": 8,
            "GIVE_RETRY_MINUTES": 10,
            "TOWN_ERRAND_CLAIMANT": "town errand",
            "_TOWN_ERRANDS": {},
            "_TOWN_ERRAND_MARKS": {},
            "_family_of": lambda cohort: (["Bork", "Grug"], "Grug"),
            "_cohort_key": lambda cohort: None,
            "_family_label": lambda cohort: "",
            "_fetch_gearup_facts": lambda names: FACTS,
            "_mail_gear_holders": lambda names: {"Bork": 1},
            "_fetch_teams": lambda names: {"Grug": "alliance"},
            # The capital is read on the leader's own fresh snapshot, so an
            # absent leader finds none, as _ERRAND_AUCTIONEERS_SQL does.
            "_fetch_capital_hub": lambda leader, team: (
                dict(HUB) if leader in self.positions else {}
            ),
            "_fetch_positions": lambda names: {
                n: self.positions[n] for n in names if n in self.positions
            },
            "_TOWN_ERRAND_HEAD_AWAY": set(),
            "_town_errand_jobs": lambda names: self.jobs.append("town run") or 2,
            "_hub_aim": lambda hub: "at:0:100,100,10",
            "_fetch_mail": lambda names: letters,
            "_recent_mail_keys": lambda minutes: set(),
            "_fetch_free_slots": lambda names: {"Bork": 5, "Grug": 5},
            "_insert_mail": lambda take, command: (
                self.written.append((take.character, command)) or 1
            ),
        }
        module = ast.Module(
            body=_functions(
                "_town_errand_once",
                "_town_errand_start",
                "_town_errand_aim",
                "_town_errand_step",
                "_town_errand_mail",
            ),
            type_ignores=[],
        )
        exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
        self.ns = ns
        self.fam = Family(self)
        self.fam._town_errand_start = lambda *a: ns["_town_errand_start"](self.fam, *a)
        self.fam._town_errand_aim = lambda *a: ns["_town_errand_aim"](self.fam, *a)
        self.fam._town_errand_step = lambda *a: ns["_town_errand_step"](self.fam, *a)
        self.fam._town_errand_mail = lambda *a: ns["_town_errand_mail"](self.fam, *a)

    def tick(self, seconds=30.0):
        self.now += seconds
        asyncio.run(self.ns["_town_errand_once"](self.fam))
        return self.ns["_TOWN_ERRANDS"][("Bork", "Grug")]

    def test_the_family_is_sent_to_the_capital_and_held_in_town(self):
        state = self.tick()
        self.assertEqual(te.GO, state.phase)
        self.assertEqual(["town run"], self.jobs)
        self.assertIn("town errand", self.fam.slot.reserved)
        self.assertEqual(("town errand", "Grug", "at:0:100,100,10"), self.fam.aims[-1])

    def test_no_take_is_written_until_the_member_stands_at_the_mailbox(self):
        self.tick()
        self.positions = {"Grug": _at(101, 100), "Bork": _at(160, 100)}
        self.assertEqual(te.GATHER, self.tick().phase)
        self.assertEqual(te.GATHER, self.tick().phase)  # Bork is not there yet
        self.assertEqual([], self.written)
        self.positions["Bork"] = _at(103, 101)
        self.assertEqual(te.STEPS, self.tick().phase)
        state = self.tick()
        self.assertEqual([("Bork", "take-item mail:9 item:77")], self.written)
        self.assertEqual(te.MAIL, state.current_step)

    def test_an_absent_head_defers_the_errand_without_a_cooldown(self):
        # wow-dev 2026-09-27 21:15: the pod came up while the roster head was
        # out of the world, the capital read on his snapshot found nothing,
        # and "not going" started the two-hour cooldown. He was back at 21:17.
        # mod-overseer holds the family while its head is away and lets no
        # member lead in his place (mod-overseer#736), so the errand waits.
        del self.positions["Grug"]
        state = self.tick()
        self.assertFalse(state.active)
        self.assertEqual(0.0, state.ended)
        self.assertEqual([], self.fam.aims)
        self.assertEqual([], self.jobs)
        self.positions["Grug"] = _at(400, 400)
        self.assertEqual(te.GO, self.tick().phase)
        self.assertEqual(("town errand", "Grug", "at:0:100,100,10"), self.fam.aims[-1])


if __name__ == "__main__":
    unittest.main()
