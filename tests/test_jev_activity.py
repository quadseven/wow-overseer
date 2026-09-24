"""A family's next activity, chosen by Jev the way a player group would (#216).

The operator: "They should play naturally! Make Jev make them play like real
human gamers in WoW." Jev is offered only what the family can carry out now,
acts at a 0.6 floor, and never touches the operator's queue: a choice other
than the campaign is an interlude that delays the next run and nothing else.
Every test runs on fake rows and a fake Jev transport; none touches a
database or the API.
"""

import ast
import asyncio
import pathlib
import types
import unittest

from test_campaign_queue import FakeWorld, _q, _queue_pass  # sets up the pymysql stub

import campaignqueue  # noqa: E402
import core  # noqa: E402
import jev  # noqa: E402
import jev_activity as ja  # noqa: E402
import jevview  # noqa: E402
import jobs  # noqa: E402
import townslot  # noqa: E402
from test_jev_items import FakeJev  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")

ROOMY = {"Zug": 20, "Oz": 20, "Uzza": 20, "Zork": 20, "Zrog": 20}
# Room to loot, and too little to go fishing with (jev_activity.can_fish).
SNUG = {"Zug": 7, "Oz": 8, "Uzza": 9, "Zork": 7, "Zrog": 8}
HORDE = (
    ("Zug", 20, 0),
    ("Oz", 19, 5),
    ("Uzza", 17, 9),
    ("Zork", 16, 7),
    ("Zrog", 17, 8),
)


def members(free=None, recipe=()):
    free = free or {}
    return tuple(
        ja.Member(
            name=n,
            level=lvl,
            class_name="Warrior",
            free_slots=free.get(n, slots),
            empty_gear_slots=1,
            trade_goods=2,
            recipe=n in recipe,
        )
        for n, lvl, slots in HORDE
    )


def facts(**kw):
    kw.setdefault("members", members())
    kw.setdefault("job", "dungeon:ragefire")
    kw.setdefault("queue", "Ragefire Chasm 12 of 50, then Wailing Caverns 50")
    return ja.Facts(family="Zug", **kw)


def ask(f, fake=None, key="k", environ=None):
    client = jev.Client(key, transport=fake or FakeJev())
    return asyncio.run(ja.ask(client, f, ja.policy(environ or {})))


class Slow:
    """A transport that never answers inside the deadline."""

    def __call__(self, url, body, headers, timeout):
        import time

        time.sleep(0.3)
        return 200, b"{}"


class HumanTouches(unittest.TestCase):
    """#267: a player unwinds by fishing, the realm's families do not all
    turn on the same minute, and a leader says what the family does next."""

    def test_fishing_is_offered_with_room_in_every_bag(self):
        roomy = ja.options(facts(queue="", job="quest", members=members(free=ROOMY)))
        self.assertEqual([ja.QUEST, ja.FISH], list(roomy))
        self.assertEqual("fish", ja.JOB[ja.FISH])
        self.assertIn("fish", jobs.IMPLEMENTED)

    def test_fishing_is_never_offered_to_a_full_bag_or_a_withheld_run(self):
        snug = ja.options(facts(queue="", job="quest", members=members(free=SNUG)))
        self.assertNotIn(ja.FISH, snug)
        held = ja.options(facts(withheld=True, members=members(free=ROOMY)))
        self.assertNotIn(ja.FISH, held)
        unknown = members(free=ROOMY)[:4] + (
            ja.Member(name="Zrog", level=17, free_slots=None),
        )
        self.assertNotIn(ja.FISH, ja.options(facts(members=unknown)))

    def test_jev_can_choose_fishing_and_the_family_goes(self):
        fake = FakeJev(picks={"activity": ja.FISH}, confidence=0.8)
        j = ask(facts(queue="", job="quest", members=members(free=ROOMY)), fake)
        self.assertEqual(ja.FISH, j.carried_out)
        state = fake.requests[0]["state"]
        self.assertEqual(
            "not this session", state["minutes_since_the_family_last_fished"]
        )

    def test_only_fishing_is_put_back_on_the_default_job(self):
        self.assertEqual({ja.FISH: jobs.DEFAULT}, ja.RESTORE)

    def test_each_family_has_its_own_cadence_within_the_spread(self):
        keys = ["alliance", "horde", "Zug", "Grug", "Og", "Ugga"]
        cadences = {k: ja.cadence_seconds(k) for k in keys}
        low = 60 * ja.CADENCE_MINUTES * (1 - ja.SPREAD)
        high = 60 * ja.CADENCE_MINUTES * (1 + ja.SPREAD)
        for k, c in cadences.items():
            self.assertTrue(low <= c <= high, (k, c))
            self.assertEqual(c, ja.cadence_seconds(k))
        self.assertGreater(len({round(c) for c in cadences.values()}), 3)

    def test_interludes_vary_in_length(self):
        lengths = {
            round(ja.lease_minutes(ja.QUEST, "Zug", 60.0 * n), 2) for n in range(12)
        }
        self.assertGreater(len(lengths), 3)

    def test_every_activity_but_the_campaign_has_an_emote(self):
        self.assertEqual("", ja.emote(ja.CAMPAIGN, "Zug", 0.0))
        for activity in ja.ACTIVITIES:
            if activity == ja.CAMPAIGN:
                continue
            said = {ja.emote(activity, "Zug", 60.0 * n) for n in range(20)}
            self.assertEqual(set(ja.EMOTES[activity]), said, activity)
            for line in said:
                self.assertTrue(line.isascii() and line.endswith("."), line)
                self.assertNotIn("\u2014", line)

    def test_the_bridge_uses_the_family_cadence_and_speaks_the_emote(self):
        due = BRIDGE[BRIDGE.index("    def _activity_due(") :]
        due = due[: due.index("\n    async def ")]
        self.assertIn("jev_activity.cadence_seconds(key)", due)
        self.assertNotIn("jev_activity.CADENCE_MINUTES)", due)
        carry = BRIDGE[BRIDGE.index("    async def _carry_out_activity(") :]
        carry = carry[: carry.index("\n    async def ", 10)]
        self.assertIn("jev_activity.interlude(activity, time.monotonic(), key)", carry)
        self.assertIn("await self._activity_emote(key, fam, activity)", carry)
        emote = BRIDGE[BRIDGE.index("    async def _activity_emote(") :]
        emote = emote[: emote.index("\n    async def ", 10)]
        self.assertIn("jev_activity.emote(", emote)
        self.assertIn('"emote"', emote)

    def test_the_bridge_ends_a_fishing_break(self):
        body = BRIDGE[BRIDGE.index("    async def _activity_restore_job(") :]
        body = body[: body.index("\n    async def ", 10)]
        self.assertIn("jev_activity.RESTORE", body)
        self.assertIn("_insert_job", body)
        self.assertIn("activity: %s's %s break is over", body)


class TheChoiceSet(unittest.TestCase):
    def test_a_withheld_run_offers_selling_and_never_the_campaign(self):
        offered = ja.options(facts(withheld=True))
        self.assertIn(ja.SELL, offered)
        self.assertNotIn(ja.CAMPAIGN, offered)

    def test_a_run_that_can_start_is_offered(self):
        offered = ja.options(facts())
        self.assertIn(ja.CAMPAIGN, offered)
        self.assertIn("Ragefire Chasm 12 of 50", offered[ja.CAMPAIGN])

    def test_each_option_needs_its_executor(self):
        plain = ja.options(facts(queue="", job="quest", members=members(free=SNUG)))
        self.assertEqual([ja.QUEST], list(plain))
        rich = ja.options(
            facts(
                members=members(free={"Oz": 2}, recipe=("Oz",)),
                can_gather=True,
                can_train=True,
            )
        )
        self.assertEqual(
            {ja.CAMPAIGN, ja.QUEST, ja.GATHER, ja.CRAFT, ja.SELL, ja.TRAIN}, set(rich)
        )

    def test_rest_and_every_queue_edit_are_never_offered(self):
        """Rest has no drive (jobs.IMPLEMENTED); a queue edit is not a choice."""
        self.assertNotIn("rest", jobs.IMPLEMENTED)
        self.assertEqual(
            (ja.CAMPAIGN, ja.QUEST, ja.GATHER, ja.CRAFT, ja.SELL, ja.TRAIN, ja.FISH),
            ja.ACTIVITIES,
        )
        for activity, job in ja.JOB.items():
            self.assertTrue(job == "" or jobs.can_set(job), activity)

    def test_the_heuristic_is_what_todays_rules_do(self):
        self.assertEqual(ja.CAMPAIGN, ja.heuristic(facts())[0])
        answer, why = ja.heuristic(facts(withheld=True))
        self.assertEqual(ja.CAMPAIGN, answer)
        self.assertIn("withheld for bag space", why)
        self.assertEqual(ja.CRAFT, ja.heuristic(facts(queue="", job="craft"))[0])
        self.assertEqual(ja.QUEST, ja.heuristic(facts(queue="", job="quest"))[0])

    def test_the_withhold_is_the_dungeon_writers_own_predicate(self):
        self.assertTrue(ja.withheld(True, {"Zug": 0, "Oz": 9}))
        self.assertFalse(ja.withheld(True, {"Zug": 9, "Oz": 9}))
        self.assertFalse(ja.withheld(False, {"Zug": 0}))
        body = BRIDGE[BRIDGE.index("def _drive_dungeon(") :]
        self.assertIn("bag_pressure.family_town_run_needed(free_slots)", body)


class WhenItIsAsked(unittest.TestCase):
    def marks(self, **kw):
        base = dict(
            runs_done=3,
            levels=(("Zug", 20), ("Oz", 19)),
            deaths=1,
            withheld=False,
            at_town=False,
        )
        base.update(kw)
        return ja.Marks(**base)

    def test_every_breakpoint(self):
        before = self.marks()
        self.assertEqual("", ja.stopped_at(before, self.marks()))
        self.assertEqual(ja.AFTER_RUN, ja.stopped_at(before, self.marks(runs_done=4)))
        self.assertEqual(
            ja.AFTER_LEVEL,
            ja.stopped_at(before, self.marks(levels=(("Zug", 21), ("Oz", 19)))),
        )
        self.assertEqual(ja.AFTER_DEATH, ja.stopped_at(before, self.marks(deaths=2)))
        self.assertEqual(ja.BAGS_FULL, ja.stopped_at(before, self.marks(withheld=True)))
        self.assertEqual(ja.TOWN, ja.stopped_at(before, self.marks(at_town=True)))
        self.assertEqual("", ja.stopped_at(None, self.marks()))

    def test_a_new_queue_entry_resetting_the_count_is_not_a_run(self):
        self.assertEqual(
            "", ja.stopped_at(self.marks(runs_done=50), self.marks(runs_done=0))
        )

    def test_the_cadence(self):
        self.assertEqual(ja.CADENCE, ja.due("", None, 100.0, 1200))
        self.assertEqual("", ja.due("", 100.0, 1000.0, 1200))
        self.assertEqual(ja.CADENCE, ja.due("", 100.0, 1300.0, 1200))
        self.assertEqual(ja.AFTER_RUN, ja.due(ja.AFTER_RUN, 100.0, 101.0, 1200))


class JevChooses(unittest.TestCase):
    def test_a_withheld_family_sells_and_the_log_says_jev_chose_it(self):
        """The first acceptance criterion."""
        fake = FakeJev(picks={"activity": ja.SELL}, confidence=0.78)
        j = ask(facts(withheld=True, reason=ja.BAGS_FULL), fake)
        self.assertEqual((j.heuristic, j.jev, j.acted), (ja.CAMPAIGN, ja.SELL, jev.JEV))
        self.assertEqual(ja.SELL, j.carried_out)
        self.assertIn("Jev chose sell", j.line())
        self.assertIn("run withheld for bag space", j.facts)
        self.assertEqual(ja.BAGS_FULL, j.item_name)

    def test_the_question_carries_the_facts(self):
        fake = FakeJev(picks={"activity": ja.QUEST})
        ask(facts(members=members(recipe=("Oz",)), minutes_on_activity=95), fake)
        [request] = fake.requests
        state = request["state"]
        self.assertEqual(4, state["level_spread"])
        self.assertEqual(95, state["minutes_on_current_activity"])
        self.assertIn("Ragefire Chasm 12 of 50", state["dungeon_queue"])
        zug = state["family"][0]
        self.assertEqual(
            (0, 1, 2),
            (
                zug["free_bag_slots"],
                zug["empty_gear_slots"],
                zug["trade_goods_carried"],
            ),
        )
        self.assertTrue(zug["persona"], "the persona (#212) is in the question")
        self.assertTrue(state["family"][1]["has_a_recipe_to_craft"])
        self.assertEqual(request["model"], jev.MODEL)
        self.assertEqual(list(request["questions"]), ["activity"])
        self.assertEqual("choice", request["questions"]["activity"]["type"])

    def test_below_the_floor_todays_rules_stand(self):
        fake = FakeJev(picks={"activity": ja.SELL}, confidence=0.55)
        j = ask(facts(withheld=True), fake)
        self.assertEqual((j.jev, j.acted, j.carried_out), (ja.SELL, jev.HEURISTIC, ""))
        self.assertIn("today's rules stand", j.line())

    def test_the_floor_and_the_mode_are_the_operators(self):
        rule = ja.policy({})
        self.assertEqual((rule.mode, rule.threshold), (jev.ACT, 0.6))
        rule = ja.policy({"JEV_THRESHOLD_ACTIVITY_CHOICE": "0.9"})
        self.assertEqual(0.9, rule.threshold)
        shadow = {"JEV_MODE_ACTIVITY_CHOICE": "shadow"}
        j = ask(
            facts(withheld=True),
            FakeJev(picks={"activity": ja.SELL}, confidence=0.99),
            environ=shadow,
        )
        self.assertEqual((j.acted, j.carried_out), (jev.HEURISTIC, ""))
        off = {"JEV_MODE_ACTIVITY_CHOICE": "off"}
        fake = FakeJev()
        self.assertIsNone(ask(facts(), fake, environ=off))
        self.assertEqual([], fake.requests)

    def test_no_key_slow_or_broken_leaves_todays_rules(self):
        fake = FakeJev()
        j = ask(facts(withheld=True), fake, key="")
        self.assertEqual((j.status, j.carried_out), (jev.NO_KEY, ""))
        self.assertEqual([], fake.requests)

        client = jev.Client("k", transport=Slow(), timeout=0.1)
        j = asyncio.run(ja.ask(client, facts(withheld=True), ja.policy({})))
        self.assertEqual((j.status, j.carried_out), (jev.TIMEOUT, ""))

        client = jev.Client("k", transport=lambda *a: (500, b"down"))
        j = asyncio.run(ja.ask(client, facts(withheld=True), ja.policy({})))
        self.assertEqual((j.status, j.carried_out), (jev.ERROR, ""))

    def test_nothing_to_choose_asks_nothing(self):
        fake = FakeJev()
        self.assertIsNone(
            ask(facts(queue="", job="quest", members=members(free=SNUG)), fake)
        )
        self.assertEqual([], fake.requests)

    def test_between_runs_every_choice_is_recorded_with_its_facts(self):
        """The second acceptance criterion: confidence and facts on the row."""
        fake = FakeJev(picks={"activity": ja.CRAFT}, confidence=0.71)
        f = facts(members=members(recipe=("Oz",)), reason=ja.AFTER_RUN)
        j = ask(f, fake)
        self.assertEqual((j.kind, j.subject, j.confidence), (ja.KIND, "Zug", 0.71))
        self.assertEqual(ja.CRAFT, j.carried_out)
        self.assertTrue(j.probabilities_json())
        self.assertLessEqual(len(j.facts), 1000)
        for bit in (
            "levels 16-20 (spread 4)",
            "free bag slots Zug 0",
            "recipes Oz",
            "Ragefire Chasm 12 of 50",
        ):
            self.assertIn(bit, j.facts)

    def test_the_lease_is_bounded_and_the_campaign_has_none(self):
        self.assertIsNone(ja.interlude(ja.CAMPAIGN, 0.0))
        lease = ja.interlude(ja.SELL, 100.0, "Zug")
        minutes = ja.lease_minutes(ja.SELL, "Zug", 100.0)
        self.assertTrue(lease.live(100.0 + 60 * minutes - 1))
        self.assertFalse(lease.live(100.0 + 60 * minutes))
        low, high = 1 - ja.SPREAD, 1 + ja.SPREAD
        self.assertTrue(
            low * ja.LEASE_MINUTES[ja.SELL]
            <= minutes
            <= high * ja.LEASE_MINUTES[ja.SELL]
        )
        for activity in ja.ACTIVITIES:
            if activity != ja.CAMPAIGN:
                self.assertLessEqual(ja.LEASE_MINUTES[activity], 30, activity)

    def test_members_come_from_the_bridges_rows(self):
        got = ja.members_from_rows(
            ["Zug", "Oz"],
            [{"name": "Zug", "level": 20, "class_name": "Warrior"}],
            {"Zug": 3},
            [{"name": "Zug", "worn": 14}],
            [{"name": "Oz", "stacks": 4}],
            ["Oz"],
        )
        self.assertEqual(
            (20, 3, 3, 0, False),
            (
                got[0].level,
                got[0].free_slots,
                got[0].empty_gear_slots,
                got[0].trade_goods,
                got[0].recipe,
            ),
        )
        self.assertEqual(
            (0, None, 17, 4, True),
            (
                got[1].level,
                got[1].free_slots,
                got[1].empty_gear_slots,
                got[1].trade_goods,
                got[1].recipe,
            ),
        )
        unread = ja.members_from_rows(["Zug"], [], {}, None, [], [])
        self.assertIsNone(unread[0].empty_gear_slots)


# ---------------------------------------------------------------------------
# THE BRIDGE: its own source, run over fakes.


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


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *args, **k):
        self.lines.append(msg % args if args else msg)

    warning = exception = error = info


class FakeFamily:
    """One family's world as the activity pass reads and writes it."""

    def __init__(self, free, job="dungeon:ragefire"):
        self.free = dict(free)
        self.job = job
        self.jobs = []
        self.records = []
        self.calls = []
        self.speak = []
        self.runs = []  # what successive _mid_run calls answer; empty is False

    def reads(self, names, leader):
        return {
            "free": dict(self.free),
            "members": [
                {"name": n, "level": lvl, "class_name": "Warrior"}
                for n, lvl, _ in HORDE
            ],
            "recipes": [],
            "deaths": 0,
            "worn": [{"name": n, "worn": 16} for n, _, _ in HORDE],
            "goods": [],
            "at_town": False,
        }

    def insert_job(self, name, mode, source):
        self.jobs.append((name, mode, source))


def _bridge(world, fake_jev, holds=None):
    """The activity methods, bound to a fake bridge over `world`."""
    log = _Log()
    ns = {
        "asyncio": asyncio,
        "time": __import__("time"),
        "jev": jev,
        "jev_activity": ja,
        "campaignqueue": campaignqueue,
        "townslot": townslot,
        "gatheraim": types.SimpleNamespace(),
        "trainjob": types.SimpleNamespace(),
        "log": log,
        "_activity_reads": world.reads,
        "_insert_job": world.insert_job,
        "_insert_jev_judgment": world.records.append,
        "_insert_speak": world.speak.append,
        "relay": __import__("relay"),
    }
    names = [
        "_activity_holds",
        "_activity_for",
        "_activity_can",
        "_activity_due",
        "_carry_out_activity",
        "_drive_activity",
        "_activity_emote",
        "_activity_restore_job",
        "_activity_minutes_since_fishing",
    ]
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source

    async def mid_run(_names):
        return bool(world.runs and world.runs.pop(0))

    def recorder(name):
        async def call(*args):
            world.calls.append((name, args))

        return call

    me = type("Me", (), {n: ns[n] for n in names})()
    me._jev = jev.Client("k", transport=fake_jev)
    me._activity_seen = {}
    me._activity_interludes = {}
    me._activity_restore = {}
    me._activity_fished = {}
    me._activity_own_key = None
    me._mid_run = mid_run
    for name in (
        "_vendor_once",
        "_bag_purchase_and_trip",
        "_campaign_queue_once",
        "_craft_once",
        "_drive_train",
    ):
        setattr(me, name, recorder(name))
    return me, log


def _family():
    names = [n for n, _, _ in HORDE]
    leader = {"name": "Zug", "job": "dungeon:ragefire", "dungeon_runs_done": 12}
    return {"leader": leader, "names": names}


def _rows():
    return [_q(1, "ragefire", 50, "active", 0), _q(2, "wailing", 50, "queued", 1)]


class TheBridgeCarriesItOut(unittest.TestCase):
    def run_pass(self, world, fake, rows=None):
        me, log = _bridge(world, fake)
        asyncio.run(
            me._activity_for(
                "Zug",
                _family(),
                _rows() if rows is None else rows,
                False,
                ja.policy({}),
            )
        )
        return me, log

    def test_a_withheld_run_goes_to_town_not_idle(self):
        world = FakeFamily({"Zug": 0, "Oz": 9, "Uzza": 9, "Zork": 9, "Zrog": 9})
        me, log = self.run_pass(
            world, FakeJev(picks={"activity": ja.SELL}, confidence=0.8)
        )
        [record] = world.records
        self.assertEqual((record.jev, record.acted), (ja.SELL, jev.JEV))
        self.assertIn("run withheld for bag space", record.facts)
        called = [name for name, _ in world.calls]
        self.assertEqual(["_vendor_once", "_bag_purchase_and_trip"], called)
        cohort = world.calls[0][1][0]
        self.assertEqual(("Zug", "Zug"), (cohort.key, cohort.leader))
        self.assertEqual(
            {(n, "quest", ja.SOURCE) for n, _, _ in HORDE}, set(world.jobs)
        )
        self.assertEqual(ja.SELL, me._activity_holds("Zug"))
        self.assertTrue(any("Jev chose sell" in line for line in log.lines), log.lines)

    def test_a_carried_out_choice_is_announced_by_the_leader(self):
        world = FakeFamily({"Zug": 0, "Oz": 9, "Uzza": 9, "Zork": 9, "Zrog": 9})
        _me, log = self.run_pass(
            world, FakeJev(picks={"activity": ja.SELL}, confidence=0.8)
        )
        [said] = world.speak
        self.assertEqual((said.target_name, said.channel), ("Zug", "emote"))
        self.assertIn(said.text, ja.EMOTES[ja.SELL])
        self.assertEqual(ja.SOURCE, said.source)
        self.assertTrue(
            any(line.startswith("activity: Zug emotes: ") for line in log.lines),
            log.lines,
        )

    def test_a_fishing_break_ends_on_the_default_job(self):
        world = FakeFamily({n: 20 for n, _, _ in HORDE}, job="quest")
        me, log = _bridge(world, FakeJev(picks={"activity": ja.FISH}, confidence=0.8))
        fam = _family()
        fam["leader"]["job"] = "quest"
        asyncio.run(me._activity_for("Zug", fam, [], False, ja.policy({})))
        self.assertEqual({(n, "fish", ja.SOURCE) for n, _, _ in HORDE}, set(world.jobs))
        self.assertIn("Zug", me._activity_fished)
        # The break runs out while the leader is still fishing.
        held = me._activity_restore["Zug"]
        self.assertEqual(ja.FISH, held[1])
        me._activity_restore["Zug"] = (0.0,) + tuple(held[1:])
        world.jobs.clear()
        fam["leader"]["job"] = "fish"
        asyncio.run(me._activity_for("Zug", fam, [], False, ja.policy({})))
        self.assertEqual(
            {(n, "quest", ja.SOURCE) for n, _, _ in HORDE}, set(world.jobs)
        )
        self.assertNotIn("Zug", me._activity_restore)
        self.assertTrue(
            any("fish break is over; job=quest again" in line for line in log.lines),
            log.lines,
        )

    def test_a_family_moved_on_since_is_not_put_back(self):
        world = FakeFamily({n: 20 for n, _, _ in HORDE})
        me, _log = _bridge(world, FakeJev(picks={"activity": ja.CAMPAIGN}))
        me._activity_restore["Zug"] = (0.0, ja.FISH, ["Zug"])
        asyncio.run(me._activity_for("Zug", _family(), _rows(), False, ja.policy({})))
        self.assertEqual([], world.jobs)
        self.assertEqual({}, me._activity_restore)

    def test_no_answer_writes_nothing_and_still_records(self):
        world = FakeFamily({"Zug": 0, "Oz": 9, "Uzza": 9, "Zork": 9, "Zrog": 9})
        me, _log = self.run_pass(world, lambda *a: (503, b""))
        [record] = world.records
        self.assertEqual((record.status, record.acted), (jev.ERROR, jev.HEURISTIC))
        self.assertEqual(([], []), (world.jobs, world.calls))
        self.assertEqual("", me._activity_holds("Zug"))

    def test_a_run_that_started_while_jev_was_asked_is_not_interrupted(self):
        world = FakeFamily({"Zug": 0, "Oz": 9, "Uzza": 9, "Zork": 9, "Zrog": 9})
        world.runs = [False, True]
        me, _log = self.run_pass(
            world, FakeJev(picks={"activity": ja.SELL}, confidence=0.8)
        )
        self.assertEqual(1, len(world.records))
        self.assertEqual(([], []), (world.jobs, world.calls))
        self.assertEqual("", me._activity_holds("Zug"))

    def test_the_own_family_is_read_once_per_pass(self):
        seen = []
        ns = {
            "asyncio": asyncio,
            "jev": jev,
            "jev_activity": ja,
            "campaignqueue": campaignqueue,
            "log": _Log(),
            "bonds": types.SimpleNamespace(head_of_family=lambda: "Grug"),
            "_cohort_of": lambda name: "Grug",
            "_fetch_queue_roster": lambda: [
                {"name": n, "enabled": 1, "lead": 1, "family": n, "job": "quest"}
                for n in ("Grug", "Zug")
            ],
            "_fetch_queue_rows": lambda: [],
        }
        module = ast.Module(body=[_function("_activity_once")], type_ignores=[])
        exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source

        async def activity_for(key, fam, rows, own, rule):
            seen.append((key, own))

        me = types.SimpleNamespace(
            _jev=jev.Client("k", transport=FakeJev()),
            _activity_own_key=None,
            _activity_for=activity_for,
        )
        asyncio.run(ns["_activity_once"](me))
        self.assertEqual([("Grug", True), ("Zug", False)], seen)
        self.assertEqual("Grug", me._activity_own_key)

    def test_choosing_the_campaign_ends_the_interlude_and_asks_the_queue(self):
        world = FakeFamily({n: 20 for n, _, _ in HORDE})
        me, _log = _bridge(
            world, FakeJev(picks={"activity": ja.CAMPAIGN}, confidence=0.9)
        )
        me._activity_interludes["Zug"] = ja.interlude(
            ja.QUEST, __import__("time").monotonic()
        )
        asyncio.run(
            me._carry_out_activity("Zug", _family(), ja.CAMPAIGN, False, "quest")
        )
        self.assertEqual({}, me._activity_interludes)
        self.assertEqual(["_campaign_queue_once"], [n for n, _ in world.calls])
        self.assertEqual([], world.jobs)

    def test_it_is_not_asked_again_inside_the_cadence(self):
        world = FakeFamily({n: 20 for n, _, _ in HORDE})
        fake = FakeJev(picks={"activity": ja.CAMPAIGN}, confidence=0.9)
        me, _log = _bridge(world, fake)
        for _ in range(3):
            asyncio.run(
                me._activity_for("Zug", _family(), _rows(), False, ja.policy({}))
            )
        self.assertEqual(1, len(fake.requests))

    def test_the_carry_out_never_writes_the_queue(self):
        """The third acceptance criterion: no path from a choice to a queue edit."""
        for name in ("_activity_once", "_activity_for", "_carry_out_activity"):
            body = _body(name)
            for forbidden in (
                "_mark_queue",
                "_write_queue",
                "CANCEL_SQL",
                "INSERT_SQL",
                "START_SQL",
                "FINISH_SQL",
                "_reset_campaign_done",
                "_drive_dungeon",
            ):
                self.assertNotIn(forbidden, body, (name, forbidden))


class TheQueueHoldsForAnInterlude(unittest.TestCase):
    def test_an_interlude_delays_the_run_and_the_order_stands(self):
        world = FakeWorld(
            [_q(1, "ragefire", 50, "queued", 0), _q(2, "wailing", 50, "queued", 1)]
        )
        _queue_pass(world)
        zug = world.row("Zug")
        zug["dungeon_runs_done"] = 12
        for r in world.family("Zug"):
            r["job"] = "quest"  # Jev chose selling between runs
        before = (len(world.jobs), [dict(r) for r in world.queue])
        _queue_pass(world, holds={"Zug": ja.SELL})
        self.assertEqual(before, (len(world.jobs), [dict(r) for r in world.queue]))
        self.assertEqual("quest", zug["job"])
        # The interlude ends: the same entry is re-asserted, the count kept.
        _queue_pass(world)
        self.assertEqual("dungeon:ragefire", zug["job"])
        self.assertEqual(12, zug["dungeon_runs_done"])
        self.assertEqual(["active", "queued"], [r["status"] for r in world.queue])

    def test_the_automatic_passes_and_the_council_lease_stand_down(self):
        ns = {
            "core": core,
            "asyncio": asyncio,
            "log": _Log(),
            "_queue_owns_job": lambda: False,
        }
        module = ast.Module(body=[_function("_queue_holds_job")], type_ignores=[])
        exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
        me = types.SimpleNamespace(_activity_holds=lambda key=None: ja.CRAFT)

        def holds(source):
            d = core.JobDirective(mode="quest", source=source)
            return asyncio.run(ns["_queue_holds_job"](me, d))

        self.assertTrue(holds("overseer:craft_rhythm"))
        self.assertFalse(holds("discord:7"), "a person's order always goes through")
        lease = _body("_goal_drive_dungeon")
        self.assertLess(
            lease.index("self._activity_holds()"), lease.index("_drive_dungeon,")
        )

    def test_the_loop_runs_in_both_starts(self):
        self.assertEqual(2, BRIDGE.count("self._activity_loop,"))


class TheRecordAndTheCard(unittest.TestCase):
    def test_the_record_gains_facts_the_bridge_owned_way(self):
        store = BRIDGE[BRIDGE.index("def _create_jev_store(") :]
        store = store[: store.index("\n\n\n")]
        self.assertIn(" facts VARCHAR(1000) NOT NULL DEFAULT '',", store)
        self.assertIn(
            "ADD COLUMN facts VARCHAR(1000) NOT NULL DEFAULT '' AFTER mode", store
        )

    def test_the_insert_writes_the_facts(self):
        insert = BRIDGE[BRIDGE.index("def _insert_jev_judgment(") :]
        insert = insert[: insert.index("\n\n\n")]
        executed = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, args):
                executed.append((sql, args))

        class Conn(Cursor):
            def cursor(self):
                return Cursor()

        scope = {"_connect": Conn}
        exec(insert, scope)  # noqa: S102 - bridge.py's own source
        j = ask(
            facts(withheld=True), FakeJev(picks={"activity": ja.SELL}, confidence=0.8)
        )
        scope["_insert_jev_judgment"](j)
        sql, args = executed[0]
        self.assertEqual(sql.count("%s"), len(args))
        self.assertEqual((args[-2], args[-1]), (j.facts, jev.JEV))
        self.assertEqual(ja.KIND, args[0])

    def test_the_card_names_the_kind_and_shows_the_facts(self):
        row = {
            "kind": ja.KIND,
            "subject": "Zug",
            "item_name": ja.BAGS_FULL,
            "heuristic": ja.CAMPAIGN,
            "jev": ja.SELL,
            "confidence": 0.8,
            "agree": 0,
            "status": "answered",
            "mode": "act",
            "acted": "jev",
            "facts": "levels 16-20 (spread 4); run withheld for bag space",
        }
        line = jevview.recent_line(row)
        self.assertTrue(
            line.startswith("A family's next activity: Zug, bags too full"), line
        )
        self.assertIn("Jev's answer was carried out", line)
        self.assertIn(
            "Given: levels 16-20 (spread 4); run withheld for bag space.", line
        )
        self.assertNotIn("Given", jevview.recent_line(dict(row, facts="")))

    def test_the_card_reads_the_facts_and_survives_an_older_record(self):
        fetch = SERVER[SERVER.index("def _fetch_jev_view()") :]
        fetch = fetch[: fetch.index("\n\n\n")]
        self.assertIn('for columns in ("acted, facts", "acted"):', fetch)
        self.assertIn("exc.args[0] == 1054", fetch)


if __name__ == "__main__":
    unittest.main()
