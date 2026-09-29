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

import gearup
import guildbank
import guildwork
import mailrun
import townerrand as te

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
HUB = {"map_id": 0, "x": 100.0, "y": 100.0, "z": 10.0, "auctioneer": "Auctioneer"}
HOME = {"map_id": 1, "x": -1035.1, "y": -3676.0, "z": 23.1, "bind": True}
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
        facts = {
            "Bork": {"equipped": {"finger1": 21, "mainhand": 30}, "purse": 800},
            "Grug": {"equipped": {"head": 45, "mainhand": 40}, "purse": 50000},
        }
        why = te.should_start(
            te.State(), now=0, in_run=False, mail_gear={}, facts=facts
        )
        self.assertIn("Grug", why)
        self.assertNotIn("Bork", why)  # 8 silver is not enough to shop with

    def test_a_member_with_no_weapon_starts_it_when_a_sibling_can_fund_it(self):
        # wow-dev 2026-09-28: the level 35 mage and priest wore no main hand,
        # and the warrior carried 54 gold. A missing weapon is reason enough,
        # and a broke member goes when the family can pay for it.
        facts = {
            "Og": {
                "equipped": {
                    s: 20
                    for s in (
                        "head",
                        "chest",
                        "legs",
                        "feet",
                        "hands",
                        "wrist",
                        "waist",
                        "back",
                        "neck",
                        "shoulder",
                        "finger1",
                        "finger2",
                        "trinket1",
                        "trinket2",
                        "offhand",
                        "ranged",
                    )
                },
                "purse": 800,
            },
            "Grug": {"equipped": {"mainhand": 40}, "purse": 540000},
        }
        why = te.should_start(
            te.State(), now=0, in_run=False, mail_gear={}, facts=facts
        )
        self.assertIn("Og (no weapon)", why)
        poor = dict(facts, Grug={"equipped": {"mainhand": 40}, "purse": 800})
        self.assertEqual(
            "",
            te.should_start(te.State(), now=0, in_run=False, mail_gear={}, facts=poor),
        )

    def test_the_family_is_funded_before_the_post_is_collected(self):
        self.assertEqual(te.FUND, te.STEP_ORDER[0])
        self.assertLess(te.STEP_ORDER.index(te.FUND), te.STEP_ORDER.index(te.MAIL))
        self.assertLess(te.STEP_ORDER.index(te.MAIL), te.STEP_ORDER.index(te.VENDOR))

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
        at_mail = te.STEP_ORDER.index(te.MAIL)
        s = te.State(
            phase=te.STEPS, started=0.0, phase_since=0.0, step=at_mail, hub=HUB
        )
        s2, _ = te.advance(s, te.STEP_SECONDS[te.MAIL] - 1)
        self.assertEqual(te.MAIL, s2.current_step)
        s3, line = te.advance(s, te.STEP_SECONDS[te.MAIL])
        self.assertEqual(te.EQUIP, s3.current_step)
        self.assertIn("ran out of time", line)

    def test_the_ceiling_and_a_dungeon_run_both_release(self):
        s = te.start(0.0, HUB, "w")
        self.assertEqual(te.DONE, te.advance(s, te.TOTAL_SECONDS)[0].phase)
        self.assertEqual(te.DONE, te.advance(s, 5.0, in_run=True)[0].phase)

    def test_home_unless_the_head_already_stands_by_a_capital(self):
        home = dict(HOME)
        self.assertEqual(home, te.choose_hub(home, HUB, _at(3000, 3000)))
        self.assertEqual(HUB, te.choose_hub(home, HUB, _at(150, 150)))
        self.assertEqual(HUB, te.choose_hub({}, HUB, _at(3000, 3000)))
        self.assertEqual({}, te.choose_hub({}, {}, _at(0, 0)))

    def test_members_beyond_a_walk_from_home_hearth(self):
        positions = {
            "Grug": _at(3000, 3000),
            "Bork": _at(-990, -3700, 1),
            "Og": _at(0, 0),
            "Ugga": _at(-1040, -3670, 0),
        }
        names = ["Bork", "Grug", "Og", "Ugga", "Zed"]
        self.assertEqual(["Grug", "Ugga"], te.to_hearth(HOME, positions, names, {"Og"}))
        self.assertEqual([], te.to_hearth(HUB, positions, names))

    def test_the_leader_is_not_aimed_during_the_cast(self):
        s = te.start(0.0, HOME, "why", hearthed=True)
        self.assertFalse(te.aim_now(s, 10.0))
        self.assertTrue(te.aim_now(s, te.HEARTH_SECONDS))
        self.assertTrue(te.aim_now(te.start(0.0, HOME, "why"), 0.0))

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
        self.home = {}
        self.hearths = []
        self.hearthed = frozenset()
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
            "_TOWN_ERRAND_FUNDED": {},
            "_TOWN_ERRAND_BOUGHT": {},
            "gearup": gearup,
            "guildwork": guildwork,
            "guildbank": guildbank,
            "_fetch_guild_bank_setup": lambda names: self.setup,
            "_natural_contributors": lambda cands, names: frozenset(cands),
            "TOWN_ERRAND_SETTLE_SECONDS": 60.0,
            "_insert_fund_letter": lambda gift, command: (
                self.written.append((gift.donor, gift.taker, command)) or 1
            ),
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
            "TOWN_ERRAND_SOURCE": "overseer:town-errand",
            "_fetch_bind_hub": lambda leader: dict(self.home),
            "_movement_reads": lambda names: {"binds": {}, "hearthed": self.hearthed},
            "_insert_hearth": lambda name, source: self.hearths.append(name) or 1,
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
                "_town_errand_fund",
                "_tab_gifts",
                "_town_errand_regroup",
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
        self.fam._town_errand_fund = lambda *a: ns["_town_errand_fund"](self.fam, *a)
        self.fam._town_errand_regroup = lambda *a: ns["_town_errand_regroup"](
            self.fam, *a
        )

    setup = None

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
        self.assertEqual(te.MAIL, self.tick().current_step)  # nothing to fund
        state = self.tick()
        self.assertEqual([("Bork", "take-item mail:9 item:77")], self.written)
        self.assertEqual(te.MAIL, state.current_step)

    def test_the_richest_member_posts_gold_before_the_post_is_taken(self):
        # wow-dev 2026-09-28: the warrior carried 54 gold, the rogue 2.
        rich = {
            "Grug": {"level": 38, "purse": 540103, "equipped": {"mainhand": 43}},
            "Bork": {"level": 35, "purse": 23904, "equipped": {"head": 38}},
        }
        self.ns["_fetch_gearup_facts"] = lambda names: rich
        self.tick()
        self.positions = {"Grug": _at(101, 100), "Bork": _at(103, 101)}
        self.assertEqual(te.GATHER, self.tick().phase)
        self.assertEqual(te.STEPS, self.tick().phase)
        state = self.tick()
        gift = 35 * gearup.FUND_PER_LEVEL - 23904
        self.assertEqual(
            [("Grug", "Bork", "send money:%d subject:For your gear" % gift)],
            self.written,
        )
        self.assertEqual(te.FUND, state.current_step)
        self.assertEqual(
            {"Bork": gift, "Grug": -gift},
            self.ns["_TOWN_ERRAND_FUNDED"][("Bork", "Grug")],
        )
        self.assertEqual(te.FUND, self.tick().current_step)  # the letter settles
        self.assertEqual(te.MAIL, self.tick(60.0).current_step)

    def test_with_no_gear_to_fund_the_family_funds_the_guilds_first_tab(self):
        # wow-dev 2026-09-29: the Horde guild had no tab, its master held
        # under a gold against the hundred it costs, and no sibling posted.
        rich = {
            "Grug": {"level": 18, "purse": 8467, "equipped": {"mainhand": 43}},
            "Bork": {"level": 16, "purse": 51567, "equipped": {"mainhand": 44}},
        }
        self.ns["_fetch_gearup_facts"] = lambda names: rich
        self.setup = {"master": "Grug", "purchased_tabs": 0, "master_mailed_copper": 0}
        self.tick()
        self.positions = {"Grug": _at(101, 100), "Bork": _at(103, 101)}
        self.assertEqual(te.GATHER, self.tick().phase)
        self.assertEqual(te.STEPS, self.tick().phase)
        state = self.tick()
        spare = 51567 - guildbank.tab_fund_float(16)
        self.assertEqual(
            [
                (
                    "Bork",
                    "Grug",
                    "send money:%d subject:For the guild bank" % (spare // 2),
                )
            ],
            self.written,
        )
        self.assertEqual(te.FUND, state.current_step)

    def test_a_guild_that_owns_its_tab_is_not_asked_for_more(self):
        rich = {
            "Grug": {"level": 18, "purse": 8467, "equipped": {"mainhand": 43}},
            "Bork": {"level": 16, "purse": 51567, "equipped": {"mainhand": 44}},
        }
        self.ns["_fetch_gearup_facts"] = lambda names: rich
        self.setup = {"master": "Grug", "purchased_tabs": 1, "master_mailed_copper": 0}
        self.tick()
        self.positions = {"Grug": _at(101, 100), "Bork": _at(103, 101)}
        self.tick()
        self.tick()
        self.tick()
        self.assertEqual([], self.written)

    def test_the_fund_step_waits_for_the_donor_at_the_mailbox(self):
        # wow-dev 2026-09-28 02:20: the step ran on a tick whose settled
        # reading had nobody at the mailbox, and ended with no letter.
        rich = {
            "Grug": {"level": 38, "purse": 540103, "equipped": {"mainhand": 43}},
            "Bork": {"level": 35, "purse": 23904, "equipped": {"head": 38}},
        }
        self.ns["_fetch_gearup_facts"] = lambda names: rich
        self.tick()
        self.positions = {"Grug": _at(101, 100), "Bork": _at(103, 101)}
        self.assertEqual(te.GATHER, self.tick().phase)
        self.assertEqual(te.STEPS, self.tick().phase)
        self.positions = {"Bork": _at(103, 101)}  # the donor's reading is gone
        self.assertEqual(te.FUND, self.tick().current_step)
        self.assertEqual(te.FUND, self.tick().current_step)
        self.assertEqual([], self.written)
        self.positions["Grug"] = _at(101, 100)
        self.tick()
        self.assertEqual("Grug", self.written[0][0])
        self.assertEqual("Bork", self.written[0][1])

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

    def test_a_scattered_family_hearths_home_and_then_walks_the_last_yards(self):
        # wow-dev 2026-09-27 21:41: sent to Stormwind, the head 3,223 yards off
        # in the Burning Steppes and three members in Tirisfal, bound in
        # Ratchet beside a mailbox, vendors and a banker.
        self.home = dict(HOME)
        self.positions = {"Grug": _at(-7924, -1353), "Bork": _at(2050, -601)}
        state = self.tick()
        self.assertEqual(te.GO, state.phase)
        self.assertEqual(HOME["x"], state.hub["x"])
        self.assertEqual(["Bork", "Grug"], self.hearths)
        self.assertEqual([], self.fam.aims)  # the cast is not walked out of
        self.positions = {"Grug": _at(-1046, -3665, 1), "Bork": _at(-1044, -3663, 1)}
        self.tick(te.HEARTH_SECONDS)
        self.assertEqual("town errand", self.fam.aims[-1][0])
        self.assertEqual(["Bork", "Grug"], self.hearths)  # once, at the start

    def test_a_straggler_hearths_home_while_the_family_gathers(self):
        # wow-dev 2026-09-27 22:26: Og's cast "never started", he was counted
        # as hearthed and left in Tirisfal while the other four stood at the
        # Ratchet mailbox.
        self.home = dict(HOME)
        self.positions = {"Grug": _at(-1034, -3675, 1), "Bork": _at(1572, -422)}
        self.hearthed = frozenset({"Bork"})
        state = self.tick()
        self.assertEqual([], self.hearths)  # counted as hearthed: left alone
        self.hearthed = frozenset()
        state = self.tick()
        self.assertEqual(te.GATHER, state.phase)
        self.assertEqual(["Bork"], self.hearths)
        self.hearthed = frozenset({"Bork"})
        self.tick()
        self.assertEqual(["Bork"], self.hearths)  # its row stands; not twice


class TheMovementChoice(unittest.TestCase):
    """The movement choice is not offered the town errand's walk to drop."""

    def facts(self, claimant):
        import jev_movement

        holder = types.SimpleNamespace(
            claimant=claimant, character="Grug", aim="at:1:1,2,3"
        )
        fam = types.SimpleNamespace(
            _travel_slot_of=lambda key: types.SimpleNamespace(holder=holder),
        )

        async def where(key, names, leader):
            return object()

        fam._situation_for = where
        ns = {
            "asyncio": asyncio,
            "jev_movement": jev_movement,
            "TOWN_ERRAND_CLAIMANT": "town errand",
            "_movement_reads": lambda names: {"binds": {}, "hearthed": frozenset()},
        }
        module = ast.Module(body=_functions("_movement_facts"), type_ignores=[])
        exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
        return asyncio.run(ns["_movement_facts"](fam, "Grug", ["Grug"], "Grug"))

    def test_the_town_errand_walk_is_not_offered(self):
        self.assertEqual("", self.facts("town errand").errand)

    def test_a_cast_that_never_started_is_no_hearth(self):
        start = BRIDGE.index("_MOVEMENT_HEARTHED = (")
        sql = BRIDGE[start : BRIDGE.index(")", BRIDGE.index("SECOND", start))]
        self.assertIn("status NOT IN ('error', 'unchanged')", sql)

    def test_another_pass_walk_still_is(self):
        self.assertEqual("at:1:1,2,3", self.facts("bank").errand)


if __name__ == "__main__":
    unittest.main()
