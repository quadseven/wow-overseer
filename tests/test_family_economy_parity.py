"""Every roster family gets the town economy passes, not only the first (#246).

Measured on the dev realm 2026-09-23: the mail, auction, bank, guild bank,
guild dues, recipebook, town trip and forge passes took their names from
OVERSEER_NOTABLE_NAMES, which is the first family. The second family never
collected a letter, never listed or bought at the auction house, and its
guild's maintenance members never posted dues (Cave: 969 gold in four
letters; Bonkers: none). Bonkers has no bank tab, and the guild master's
purse is what buys one.

Pinned here, on a two-family fixture: each loop runs its pass for every other
family; each pass reads that family's names, walks that family's leader and
claims that family's town slot; the dues pass reads the other family's guild;
the guild bank pass asks the guild master to buy tab 0 only once its purse
holds the price; and this bridge's own family still runs exactly as before.
Every test runs on fakes; none touches a database.
"""

import ast
import asyncio
import pathlib
import types
import unittest

from test_decree_order import FakeConn, FakeCursor  # noqa: F401 - sets up the pymysql stub

import guildbank  # noqa: E402
import guildroute  # noqa: E402
import guildwork  # noqa: E402
import natural  # noqa: E402
import townslot  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

ALLIANCE = ["Bork", "Grog", "Grug", "Og", "Ugga"]
HORDE = townslot.Cohort(
    key="Zug", leader="Zug", names=("Oz", "Uzza", "Zork", "Zrog", "Zug")
)


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _load(names, namespace):
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace


def _source(name):
    return ast.get_source_segment(BRIDGE, _function(name))


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


class _Task:
    def add_done_callback(self, cb):
        return None


def _task(coro):
    coro.close()
    return _Task()


FAKE_ASYNCIO = types.SimpleNamespace(to_thread=_thread, create_task=_task)
HELPERS = ["_family_of", "_names_of", "_cohort_key", "_family_label"]


def _base(world):
    """The namespace every loaded pass shares: who each family is."""
    return {
        "asyncio": FAKE_ASYNCIO,
        "_protected_guids": lambda: {i: n for i, n in enumerate(ALLIANCE)},
        "_head_now": lambda: world.setdefault("head_now_asked", "Grug") or "Grug",
    }


class TheSelf:
    """The bridge object as a pass sees it: a slot claim and a run check."""

    def __init__(self, world):
        self.world = world
        self.claims = []
        self._dues_walks = {}
        self._guild_mail_runs = {}
        self._mail_walk_unsupported_until = 0.0
        self._far_walk_unsupported_until = 0.0
        self._mail_walk_tasks = set()

    def _guild_walk_cap(self):
        # The near cap, which is what these fixtures' mailboxes are inside.
        return 600.0

    async def _mid_run(self, names):
        self.world.setdefault("mid_run_names", []).append(list(names))
        return False

    async def _claim_town_slot(
        self, claimant, character, aim, urgent=False, cohort=None, distance=None
    ):
        self.claims.append((claimant, character, aim, cohort))
        if urgent:
            self.world.setdefault("urgent_claims", []).append(claimant)
        return True

    def _mail_urgency_spent(self, cohort, urgent, aimed, fresh):
        self.world.setdefault("mail_urgency", []).append(
            (urgent and aimed, bool(fresh))
        )

    async def _follow_dues_walk(self, run, row_id):
        return None

    def _jev_keep_deposits(self, names, setup, planned):
        """What Jev chose to bank (#267): nothing, in this world."""
        return []

    def _mail_walk_task_done(self, task):
        return None


# --- which family, which leader ---------------------------------------------


class AFamilyIsItsNamesAndItsLeader(unittest.TestCase):
    def ns(self):
        world = {}
        return world, _load(HELPERS, _base(world))

    def test_this_bridges_family_walks_behind_head_now(self):
        world, ns = self.ns()
        self.assertEqual((ALLIANCE, "Grug"), ns["_family_of"](None))
        self.assertIn("head_now_asked", world)

    def test_another_family_walks_behind_its_roster_leader(self):
        world, ns = self.ns()
        self.assertEqual((list(HORDE.names), "Zug"), ns["_family_of"](HORDE))
        self.assertNotIn("head_now_asked", world)

    def test_the_slot_key_and_label_are_empty_for_this_bridges_family(self):
        _, ns = self.ns()
        self.assertIsNone(ns["_cohort_key"](None))
        self.assertEqual("", ns["_family_label"](None))
        self.assertEqual("Zug", ns["_cohort_key"](HORDE))
        self.assertEqual(" for family Zug", ns["_family_label"](HORDE))


# --- every loop runs its pass for every other family -------------------------


ECONOMY_LOOPS = (
    ("_mail_loop", "mail", "_mail_once"),
    ("_bank_loop", "bank", "_bank_once"),
    ("_guild_bank_loop", "guild bank", "_guild_bank_once"),
    ("_guild_dues_loop", "guild dues", "_guild_dues_once"),
    ("_auction_loop", "auction", "_auction_once"),
    ("_recipebook_loop", "recipebook", "_recipebook_once"),
    ("_towntrip_loop", "towntrip", "_towntrip_once"),
    ("_forge_loop", "forge", "_forge_once"),
)


class EveryEconomyLoopServesEveryFamily(unittest.TestCase):
    def test_each_loop_runs_its_pass_for_every_other_family(self):
        for loop, what, once in ECONOMY_LOOPS:
            with self.subTest(loop=loop):
                body = _source(loop)
                self.assertIn("await self.%s()" % once, body)
                self.assertIn(
                    'await self._for_other_families("%s", self.%s)' % (what, once),
                    body,
                )

    def test_each_pass_takes_a_family(self):
        for _, _, once in ECONOMY_LOOPS:
            with self.subTest(once=once):
                args = [a.arg for a in _function(once).args.args]
                self.assertEqual(["self", "cohort"], args)

    def test_every_walk_a_pass_claims_goes_through_that_familys_slot(self):
        """A claim with no `cohort=` is a claim on this bridge's own slot and
        its own `_head_now()`: the other family's leader would never walk."""
        for name in (
            "_mail_once",
            "_guild_bank_once",
            "_auction_once",
            "_auction_sales_once",
            "_auction_bag_upgrades",
            "_settle_bank_errand",
            "_settle_town_errand",
            "_forge_once",
        ):
            for node in ast.walk(_function(name)):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_claim_town_slot"
                ):
                    with self.subTest(name=name, line=node.lineno):
                        self.assertIn("cohort", [k.arg for k in node.keywords])

    def test_the_auction_hold_is_recorded_in_that_familys_slot(self):
        body = _source("_keep_at_auctioneer")
        self.assertIn("self._cohort_town_slot(cohort).adopt(", body)
        self.assertNotIn("self._town_slot.adopt(", body)

    def test_the_vendor_pass_lets_every_family_list_at_the_house(self):
        body = _source("_vendor_once")
        self.assertNotIn("auction_open=cohort is None", body)
        self.assertEqual(2, body.count("auction_open=True"))

    def test_a_roster_that_cannot_be_read_costs_one_cycle_not_the_loop(self):
        log = _Log()

        def broken(own):
            raise RuntimeError("roster unreadable")

        ns = _load(
            ["_for_other_families"],
            {
                "asyncio": FAKE_ASYNCIO,
                "log": log,
                "_protected_guids": lambda: {1: "Grug"},
                "_other_cohorts": broken,
            },
        )

        async def step(cohort):
            raise AssertionError("no family can be run without the roster")

        asyncio.run(ns["_for_other_families"](types.SimpleNamespace(), "mail", step))
        self.assertTrue(any("could not be read" in ln for ln in log.lines), log.lines)


# --- mail: the other family collects its own letters -------------------------


class _Take:
    def __init__(self, character):
        self.character = character


def _mail_ns(world, log):
    ns = _base(world)
    ns.update(
        {
            "log": log,
            "GIVE_RETRY_MINUTES": 10,
            "TOWN_COUNTER_YARDS": 10,
            "_fetch_mail": lambda names: world.setdefault("mail_read", list(names)),
            "_recent_mail_keys": lambda minutes: set(),
            "_dues_fund_tab": lambda names: world.get("dues_fund_tab", False),
            "_fetch_free_slots": lambda names: {n: 10 for n in names},
            "_fetch_positions": lambda names: {n: {"map_id": 1} for n in names},
            "_nearest_mailbox": lambda leader: world.setdefault("mailbox_for", leader),
            "_spawn_yards": lambda spawn: None,
            "_mail_takes_in_reach": lambda takes, spawn, positions, yards, aim: takes,
            "_insert_mail": lambda take, command: (
                world.setdefault("taken", []).append(take.character) or 1
            ),
            "mailrun": types.SimpleNamespace(
                letters_from_rows=lambda rows, names: [("letter", n) for n in names],
                attachments_asked=lambda seen: {},
                plan=lambda letters, slots, asked: types.SimpleNamespace(
                    notes=(), takes=[_Take(n) for _, n in letters]
                ),
                command=lambda take: "take all",
                lines=lambda fresh: [],
            ),
            "travel": types.SimpleNamespace(
                mailbox_aim=lambda spawn, map_id: types.SimpleNamespace(
                    aim="at:1:1,1,1", refused=""
                ),
                spawn_in_reach=lambda spawn, where, yards: True,
            ),
        }
    )
    return _load(["_mail_once", "_mail_urgent", *HELPERS], ns)


class TheMailPassServesTheFamilyItIsGiven(unittest.TestCase):
    def run_mail(self, cohort):
        world, log = {}, _Log()
        me = TheSelf(world)
        ns = _mail_ns(world, log)
        me._mail_urgent = lambda *a: ns["_mail_urgent"](me, *a)
        asyncio.run(ns["_mail_once"](me, cohort))
        return world, me, log

    def test_the_other_family_reads_its_own_mail_and_its_leader_walks(self):
        world, me, log = self.run_mail(HORDE)
        self.assertEqual(list(HORDE.names), world["mail_read"])
        self.assertEqual("Zug", world["mailbox_for"])
        self.assertEqual([("mail", "Zug", "at:1:1,1,1", "Zug")], me.claims)
        self.assertEqual(sorted(HORDE.names), sorted(world["taken"]))
        self.assertTrue(
            any(ln.endswith("for family Zug") for ln in log.lines), log.lines
        )

    def test_this_bridges_family_is_served_exactly_as_before(self):
        world, me, _ = self.run_mail(None)
        self.assertEqual(ALLIANCE, world["mail_read"])
        self.assertEqual("Grug", world["mailbox_for"])
        self.assertEqual([("mail", "Grug", "at:1:1,1,1", None)], me.claims)
        self.assertNotIn("urgent_claims", world)

    def test_dues_that_pay_for_the_next_tab_make_the_walk_urgent(self):
        """#319: the Horde master held 5 silver with 2,400 gold of dues in its
        mailbox while the mail pass lost the column every cycle."""
        world, log = {"dues_fund_tab": True}, _Log()
        me = TheSelf(world)
        ns = _mail_ns(world, log)
        me._mail_urgent = lambda *a: ns["_mail_urgent"](me, *a)
        asyncio.run(ns["_mail_once"](me, HORDE))
        self.assertEqual(["mail"], world["urgent_claims"])
        self.assertEqual([(True, True)], world["mail_urgency"])
        self.assertTrue(
            any("pay for the guild's next bank tab" in ln for ln in log.lines),
            log.lines,
        )


# --- guild dues: the other family's guild posts to its own master ------------


def _guild_rows(guild, master, family, bots):
    rows = [
        {
            "guild_name": guild,
            "name": n,
            "class_id": 1,
            "level": 25,
            "money": 20_000,
            "online": 1,
            "master": master,
        }
        for n in family
    ]
    rows += [
        {
            "guild_name": guild,
            "name": "%s%02d" % (guild, i),
            "class_id": 1 + i % 9,
            "level": 60,
            "money": 5_000_000,
            "online": 1,
            "master": master,
        }
        for i in range(bots)
    ]
    return rows


class AnUrgentMailWalkIsBounded(unittest.TestCase):
    """#319: the urgent dues walk backs off when a grant queues no take."""

    def spend(self, urgent, aimed, fresh):
        calls = []

        class Slot:
            def productive(self, claimant):
                calls.append(("productive", claimant))

            def fruitless(self, claimant, now):
                calls.append(("fruitless", claimant))
                return now

        ns = _base({})
        ns.update({"log": _Log(), "time": types.SimpleNamespace(monotonic=lambda: 0.0)})
        ns = _load(["_mail_urgency_spent", *HELPERS], ns)
        me = types.SimpleNamespace(_cohort_town_slot=lambda key: Slot())
        ns["_mail_urgency_spent"](me, None, urgent, aimed, fresh)
        return calls

    def test_a_take_queued_is_productive(self):
        self.assertEqual([("productive", "mail")], self.spend(True, True, [1]))

    def test_no_take_yet_backs_off(self):
        self.assertEqual([("fruitless", "mail")], self.spend(True, True, []))

    def test_an_ordinary_or_ungranted_walk_costs_nothing(self):
        self.assertEqual([], self.spend(False, True, []))
        self.assertEqual([], self.spend(True, False, []))


class TheOtherGuildPaysItsDues(unittest.TestCase):
    def run_dues(self, cohort, natural_names=None):
        world, log = {}, _Log()
        guilds = {
            tuple(ALLIANCE): _guild_rows("Cave", "Grug", ALLIANCE, 60),
            tuple(sorted(HORDE.names)): _guild_rows("Bonkers", "Zug", HORDE.names, 60),
        }

        def walkers(holders, names, row_walks):
            return {
                h: guildroute.Walker(
                    name=h, map_id=1, aim="at:1:2,2,2", yards=30.0, by_row=True
                )
                for h in holders
            }

        ns = _base(world)
        ns.update(
            {
                "log": log,
                "time": types.SimpleNamespace(monotonic=lambda: 1000.0),
                "guildwork": guildwork,
                "guildroute": guildroute,
                "_fetch_dues_rows": lambda names: (
                    world.setdefault("read", list(names)),
                    guilds[tuple(names)],
                )[1],
                "_dues_recent_holders": lambda: set(),
                "_route_walkers": walkers,
                "_log_capped": lambda what, lines: None,
                # Everyone reset unless the test names who (natural.py).
                "_natural_contributors": lambda candidates, family: frozenset(
                    candidates if natural_names is None else natural_names
                ),
                "_insert_dues_row": lambda holder, command, taker, source: (
                    world.setdefault("rows", []).append((holder, taker)) or 7
                ),
            }
        )
        ns = _load(["_guild_dues_once", *HELPERS], ns)
        asyncio.run(ns["_guild_dues_once"](TheSelf(world), cohort))
        return world, log

    def test_bonkers_maintenance_members_post_to_zug(self):
        world, log = self.run_dues(HORDE)
        self.assertEqual(sorted(HORDE.names), world["read"])
        self.assertTrue(world["rows"])
        for holder, taker in world["rows"]:
            self.assertTrue(holder.startswith("Bonkers"), holder)
            self.assertEqual("Zug", taker)
        self.assertTrue(any("for family Zug" in ln for ln in log.lines), log.lines)

    def test_a_guild_that_nobody_has_reset_posts_no_dues(self):
        # Naturally earned only (the operator, 2026-09-24): a maintenance
        # member that was not reset to level 1 posts nothing.
        world, _ = self.run_dues(HORDE, natural_names=())
        self.assertNotIn("rows", world)

    def test_cave_still_posts_to_grug(self):
        world, _ = self.run_dues(None)
        self.assertEqual(ALLIANCE, world["read"])
        self.assertTrue(world["rows"])
        self.assertEqual({"Grug"}, {taker for _, taker in world["rows"]})


# --- guild bank: the master buys tab 0 once its purse can ---------------------


class TheMasterBuysTheTabWithTheGold(unittest.TestCase):
    def run_bank(self, cohort, purse, master="Zug", tabs=0, natural_names=None):
        world, log = {}, _Log()
        me = TheSelf(world)
        names = sorted(HORDE.names) if cohort else ALLIANCE
        ns = _base(world)
        ns.update(
            {
                "log": log,
                "guildbank": guildbank,
                "GIVE_RETRY_MINUTES": 10,
                "TOWN_COUNTER_YARDS": 10,
                "_fetch_guild_bank_setup": lambda n: {
                    "purchased_tabs": tabs,
                    "rank_ids": (0, 1),
                    "deposit_rank_ids": (0, 1),
                    "member_ranks": {},
                    "tab0_items": 0,
                    "master": master,
                },
                "_fetch_guild_money": lambda n: [
                    {
                        "name": x,
                        "money": purse if x == master else 20_000,
                        "in_guild": 1,
                    }
                    for x in n
                ],
                "_plan_bank": lambda n: types.SimpleNamespace(guild=[]),
                "natural": natural,
                "_natural_contributors": lambda candidates, family: frozenset(
                    candidates if natural_names is None else natural_names
                ),
                "_not_kept_at_home": lambda moves, names: tuple(moves),
                "_fetch_positions": lambda n: {x: {"map_id": 1} for x in n},
                "_nearest_vault": lambda leader: world.setdefault("vault_for", leader),
                "_spawn_yards": lambda spawn: None,
                "_recent_guild_setup_keys": lambda minutes: set(),
                "_insert_guild": lambda who, command, source: world.setdefault(
                    "guild_rows", []
                ).append((who, command)),
                "_recent_guild_bank_keys": lambda minutes: set(),
                "travel": types.SimpleNamespace(
                    vault_aim=lambda spawn, map_id: types.SimpleNamespace(
                        aim="at:1:3,3,3", refused=""
                    ),
                    spawn_in_reach=lambda spawn, where, yards: True,
                ),
            }
        )
        ns = _load(
            ["_guild_bank_once", "_plan_guild_setup", "_setup_buyer", *HELPERS], ns
        )
        asyncio.run(ns["_guild_bank_once"](me, cohort))
        self.assertEqual([names], world.get("mid_run_names"))
        return world, me, log

    def test_a_master_short_of_the_price_is_not_sent_to_buy(self):
        world, me, log = self.run_bank(HORDE, purse=37_910)
        self.assertNotIn("guild_rows", world)
        self.assertEqual([], me.claims)
        self.assertTrue(
            any("tab 0 waits - Zug holds 3g of the 100g" in ln for ln in log.lines),
            log.lines,
        )

    def test_a_master_holding_the_factory_members_dues_buys_no_tab(self):
        # Naturally earned only (the operator, 2026-09-24): the master still
        # holds dues the factory-made members posted, so neither the tab nor
        # a deposit is paid from its purse.
        world, _me, log = self.run_bank(HORDE, purse=1_200_000, natural_names=())
        rows = world.get("guild_rows", [])
        self.assertFalse(any("buy-tab" in c for _, c in rows), rows)
        self.assertFalse(any("deposit" in c for _, c in rows), rows)
        self.assertTrue(any("buys no tab" in ln for ln in log.lines), log.lines)

    def test_a_master_holding_the_price_walks_and_buys_it(self):
        world, me, _ = self.run_bank(HORDE, purse=1_200_000)
        self.assertEqual([("guild bank", "Zug", "at:1:3,3,3", "Zug")], me.claims)
        # The tab first, named so a stale count can never buy tab 1 (#496);
        # then only what sits above the float and the price, which is the
        # reserve `plan_deposits` keeps while there is no tab.
        self.assertEqual(
            [("Zug", "bank buy-tab tab:0"), ("Zug", "bank deposit 100000")],
            world["guild_rows"],
        )

    def test_the_alliance_guild_buys_its_next_tab_and_keeps_its_price(self):
        """#319: a guild with tab 0 buys tab 1 next, and the master's gold
        deposit leaves the 250 gold that tab costs in its purse."""
        world, me, log = self.run_bank(None, purse=5_000_000, master="Grug", tabs=1)
        self.assertEqual("Grug", world["vault_for"])
        self.assertEqual([("guild bank", "Grug", "at:1:3,3,3", None)], me.claims)
        self.assertEqual(
            [("Grug", "bank buy-tab tab:1"), ("Grug", "bank deposit 2400000")],
            world["guild_rows"],
        )
        self.assertFalse(any("tab 0 waits" in ln for ln in log.lines))

    def test_a_master_short_of_the_next_tab_says_so_with_its_dues(self):
        world, _me, log = self.run_bank(None, purse=1_000_000, master="Grug", tabs=1)
        self.assertNotIn(("Grug", "bank buy-tab tab:1"), world.get("guild_rows", []))
        self.assertTrue(
            any("tab 1 waits - Grug holds 100g of the 250g" in ln for ln in log.lines),
            log.lines,
        )


class TheBuyerIsTheGuildMaster(unittest.TestCase):
    def setUp(self):
        self.buyer = _load(["_setup_buyer"], {})["_setup_buyer"]

    def test_the_master_in_the_family_buys(self):
        self.assertEqual("Zug", self.buyer({"master": "Zug"}, ["Oz", "Zug"], "Oz"))

    def test_a_master_outside_the_family_leaves_the_traveller(self):
        self.assertEqual("Grug", self.buyer({"master": "Ezra"}, ["Grug"], "Grug"))
        self.assertEqual("Grug", self.buyer(None, ["Grug"], "Grug"))


class ThePlanAsksOnlyAPurseThatPays(unittest.TestCase):
    def plan(self, purse):
        return guildbank.plan_setup(leader="Zug", purchased_tabs=0, purse=purse)

    def test_short_of_the_price_asks_nothing(self):
        self.assertEqual((), self.plan(guildbank.TAB0_COST_COPPER - 1))
        self.assertEqual((), self.plan("unreadable"))

    def test_the_price_in_hand_asks_for_the_tab(self):
        self.assertEqual(
            (guildbank.SetupAction("Zug", "bank buy-tab tab:0"),),
            self.plan(guildbank.TAB0_COST_COPPER),
        )

    def test_an_unread_purse_keeps_the_old_answer(self):
        self.assertEqual(
            (guildbank.SetupAction("Zug", "bank buy-tab tab:0"),), self.plan(None)
        )

    def test_the_purse_never_gates_the_rank_grants(self):
        got = guildbank.plan_setup(
            leader="Zug",
            purchased_tabs=1,
            rank_ids=(0, 1),
            deposit_rank_ids=(0,),
            purse=0,
        )
        self.assertEqual(
            (guildbank.SetupAction("Zug", "bank grant-deposit rank:1"),), got
        )


if __name__ == "__main__":
    unittest.main()
