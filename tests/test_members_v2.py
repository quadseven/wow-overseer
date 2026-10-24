"""The Members section's /api/v2 reads: roster and stuck, upgrades now,
training (Standing), class chains and activity, and the guild gear strip.

Each read is built from rows by a pure function, tested here with rows; the
handlers are run against a fake connection (through the realm reader's
database adapter) and a fake map server, so the gate (a family guild member,
or a 404) and the reads are exercised with no database.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import apiv2  # noqa: E402
import families as families_module  # noqa: E402
import guildgear  # noqa: E402
import guildjobs  # noqa: E402
import nowstatus  # noqa: E402
import realmread  # noqa: E402
from apiv2 import activity, classchain, members, training, upgrades  # noqa: E402
from apiv2._context import Context  # noqa: E402

NOW = 1_800_000_000


# ---- a fake database and map server -------------------------------------------


class FakeCursor:
    """Answers each execute() with the rows of the first rule whose words are
    all in the SQL."""

    def __init__(self, rules, log):
        self.rules, self.log, self.rows = rules, log, []

    def execute(self, sql, params=()):
        self.log.append((sql, params))
        self.rows = []
        for words, rows in self.rules:
            if all(w in sql for w in words):
                self.rows = rows(params) if callable(rows) else list(rows)
                return

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, rules, log):
        self.rules, self.log = rules, log

    def cursor(self):
        return FakeCursor(self.rules, self.log)

    def close(self):
        pass


def realm_of(fams, guildmates=()):
    """families.Families over plain data: `fams`, all in one guild with
    `guildmates`."""
    everyone = [n for names in fams.values() for n in names]
    store = families_module.MemoryStore(fams, {"Guild": everyone + list(guildmates)})
    return families_module.Families(store, fallback=lambda: [])


def server(families=None, guildmates=(), **extra):
    fams = families if families is not None else {"Grug": ["Grug", "Ugga"]}
    ns = types.SimpleNamespace(
        _NAME_RE=__import__("re").compile(r"^[A-Za-z]{2,12}$"),
        FAMILIES=realm_of(fams, guildmates),
        _LINEUP_GUILD="SELECT lineup guild ({holes})",
        _fetch_now_facts=lambda names: {},
        family=types.SimpleNamespace(roster=lambda: []),
    )
    for k, v in extra.items():
        setattr(ns, k, v)
    return ns


def ctx_for(rules, srv):
    """The handler's context: the realm reader's database adapter over the
    fake connection, so the reads run as the map server runs them."""
    log = []
    rd = realmread.Session(lambda: FakeConn(rules, log))
    return Context(read=rd, server=srv), log


# ---- the routes ------------------------------------------------------------------


class TheRoutes(unittest.TestCase):
    def test_every_members_read_is_a_v2_route(self):
        for path in (
            "/api/v2/roster",
            "/api/v2/stuck",
            "/api/v2/upgrades",
            "/api/v2/training",
            "/api/v2/classchain",
            "/api/v2/activity",
        ):
            self.assertIn(path, apiv2.ROUTES)

    def test_a_name_off_the_family_guilds_is_a_404_everywhere(self):
        ctx, log = ctx_for([], server())
        for handler in (
            upgrades.upgrades,
            training.training,
            classchain.classchain,
            activity.activity,
        ):
            for name in ("Stranger", "", "x'; DROP", "a" * 20):
                code, payload = handler({"name": [name]}, ctx)
                self.assertEqual(code, 404, (handler, name))
                self.assertEqual(payload, {"error": "not a guild member"})
        self.assertEqual(log, [], "a refused name never reaches SQL")


# ---- stuck ---------------------------------------------------------------------------


def ask(
    at, target="quest:9486", label="Taming the Beast", state="expired", asker="Twinkle"
):
    return {
        "asker": asker,
        "target": target,
        "target_label": label,
        "state": state,
        "at": at,
    }


class StuckIsTheBridgesOwnRecord(unittest.TestCase):
    def test_a_live_run_of_asks_is_stuck_since_its_first_ask(self):
        run = [ask(NOW - 3 * 3600), ask(NOW - 2 * 3600), ask(NOW - 600, state="open")]
        found = members.ask_blocker(members.ask_streaks(run)["Twinkle"], NOW)
        self.assertEqual(found["since"], NOW - 3 * 3600)
        self.assertEqual(found["step"], "Class quest: Taming the Beast")
        self.assertIn("3 times", found["blocker"])
        self.assertIn("0 said yes, no party formed", found["blocker"])

    def test_a_long_silence_or_another_quest_starts_a_new_run(self):
        rows = [
            ask(NOW - 30 * 3600),
            ask(NOW - 3 * 3600, target="quest:1", label="Other"),
            ask(NOW - 600, target="quest:1", label="Other"),
        ]
        run = members.ask_streaks(rows)["Twinkle"]
        self.assertEqual([r["target"] for r in run], ["quest:1", "quest:1"])
        gap = [ask(NOW - 20 * 3600), ask(NOW - 600)]
        self.assertEqual(len(members.ask_streaks(gap)["Twinkle"]), 1)

    def test_an_old_ask_is_not_stuck_any_more(self):
        run = [ask(NOW - members.ASK_LIVE_SECONDS - 60)]
        self.assertIsNone(members.ask_blocker(run, NOW))

    def test_a_party_that_went_is_said(self):
        run = [ask(NOW - 900, state="ran"), ask(NOW - 300)]
        self.assertIn("a party went 1 time", members.ask_blocker(run, NOW)["blocker"])

    def test_a_hold_is_stuck_after_thirty_minutes_and_not_before(self):
        now = {
            "doing": "Carrying things to sell",
            "waiting": "a vendor within reach",
            "for_s": 1800,
        }
        found = members.hold_blocker(now, NOW)
        self.assertEqual(found["since"], NOW - 1800)
        self.assertEqual(found["blocker"], "Waiting for a vendor within reach.")
        self.assertIsNone(members.hold_blocker(dict(now, for_s=600), NOW))
        self.assertIsNone(members.hold_blocker(dict(now, waiting="to get there"), NOW))
        self.assertIsNone(members.hold_blocker(dict(now, doing="Idle"), NOW))

    def test_a_hold_with_no_clock_is_stuck_since_not_measured(self):
        found = members.hold_blocker(
            {"doing": "Held", "waiting": "a door", "for_s": None}, NOW
        )
        self.assertIsNone(found["since"])

    def test_walk_restarts_are_stuck_after_thirty_minutes_and_not_before(self):
        now = {
            "doing": "Walking out of Shadowfang Keep for the dungeon run",
            "waiting": "a way there; the walk has ended and restarted 5 times",
            "for_s": 1800,
        }
        found = members.hold_blocker(now, NOW)
        self.assertEqual(found["kind"], "walk restarts")
        self.assertIsNone(members.hold_blocker(dict(now, for_s=600), NOW))

    def test_the_restart_reason_nowstatus_writes_is_read_as_walk_restarts(self):
        now = {"doing": "Walking", "waiting": nowstatus.restart_words(424)}
        self.assertIn("restarted 424 times", now["waiting"])
        self.assertEqual(members.hold_blocker(now, NOW)["kind"], "walk restarts")

    def test_bank_bag_slot_note_is_not_a_stuck_hold(self):
        self.assertIsNone(
            members.hold_blocker(
                {
                    "doing": "Buying a bank bag slot",
                    "waiting": "a banker",
                    "for_s": 7200,
                },
                NOW,
            )
        )


class PlacesInWords(unittest.TestCase):
    # Online and life are apiv2/presence.py's reading (tests/test_presence.py).
    def test_a_zone_key_is_said_in_words(self):
        self.assertEqual(members.place_words("SwampOfSorrows"), "Swamp of Sorrows")
        self.assertEqual(members.place_words("Stormwind"), "Stormwind")


def roster_rules():
    snaps = [
        {
            "name": "Grug",
            "zone_id": 1519,
            "map_id": 0,
            "health": 900,
            "max_health": 900,
            "in_combat": 0,
        },
        {
            "name": "Ugga",
            "zone_id": 1519,
            "map_id": 0,
            "health": 1,
            "max_health": 500,
            "in_combat": 0,
        },
    ]
    chars = [
        {
            "name": n,
            "race": 1,
            "gender": 0,
            "class_id": c,
            "level": lv,
            "zone": 1519,
            "map": 0,
            "flags": 0,
        }
        for n, c, lv in (("Grug", 1, 42), ("Ugga", 5, 39), ("Twinkle", 3, 15))
    ]
    guild = [
        {
            "guildid": 1,
            "guild_name": "Cave",
            "name": n,
            "class_id": 1,
            "level": 1,
            "race": 1,
        }
        for n in ("Grug", "Ugga", "Twinkle")
    ]
    return [
        (("lineup guild",), guild),
        (("FROM characters",), chars),
        (("FROM overseer_snapshot",), snaps),
        (("FROM overseer_guild_ask",), [ask(NOW - 7200), ask(NOW - 300)]),
        (
            ("FROM overseer_command",),
            [
                {
                    "name": "Twinkle",
                    "source": "guildjobs:classquest-walk:Twinkle",
                    "command": "walk",
                    "status": "error",
                    "detail": "refused",
                    "at": NOW - 60,
                }
            ],
        ),
        (("UNIX_TIMESTAMP() AS now_at",), [{"now_at": NOW}]),
    ]


class TheRosterAndStuckReads(unittest.TestCase):
    def test_the_roster_names_everyone_with_family_life_and_step(self):
        ctx, _log = ctx_for(roster_rules(), server())
        code, payload = members.roster({}, ctx)
        self.assertEqual(code, 200)
        by = {m["name"]: m for m in payload["members"]}
        self.assertEqual(list(by), ["Grug", "Ugga", "Twinkle"])
        self.assertEqual(by["Grug"]["family"], "Grug")
        self.assertTrue(by["Grug"]["lead"])
        self.assertEqual(by["Ugga"]["life"], "ghost")
        self.assertFalse(by["Ugga"]["stuck"], "a ghost is a ghost, not stuck")
        self.assertTrue(by["Twinkle"]["stuck"])
        self.assertEqual(by["Twinkle"]["since"], NOW - 7200)
        self.assertEqual(by["Twinkle"]["class"], "Hunter")
        self.assertEqual(by["Grug"]["zone"], "Stormwind")
        self.assertEqual(payload["checked_at"], NOW)

    def test_stuck_is_the_spec_shape_longest_first(self):
        ctx, _log = ctx_for(roster_rules(), server())
        code, payload = members.stuck({}, ctx)
        self.assertEqual(code, 200)
        self.assertEqual(
            payload["members"],
            [
                {
                    "name": "Twinkle",
                    "step": "Class quest: Taming the Beast",
                    "blocker": "Cannot finish Taming the Beast alone: asked the guild for help 2 times, 0 said yes, no party formed.",
                    "since": NOW - 7200,
                    "kind": "class quest",
                    "follows": "",
                }
            ],
        )

    def test_an_idle_member_shows_its_newest_guild_job(self):
        m = {"doing": "Idle", "job": "Guild job: level"}
        self.assertEqual(members._step_of(m, None), "Guild job: level")
        self.assertEqual(
            members.job_step({"source": "guildjobs:classquest-walk:Chopp"}),
            "Guild job: class quest walk",
        )
        self.assertEqual(
            members.job_answer({"status": "error", "detail": "refused"}),
            "refused",
        )

    def test_roster_and_stuck_take_no_name_and_answer_the_same_to_one(self):
        # Neither read has a parameter to gate: who they answer about is the
        # roster's families and their guilds, never the request.
        for handler in (members.roster, members.stuck):
            ctx, log = ctx_for(roster_rules(), server())
            plain = handler({}, ctx)
            asked = handler({"name": ["Stranger"], "guild": ["Other"]}, ctx)
            self.assertEqual(plain, asked)
            self.assertFalse(any("Stranger" in str(p) for _sql, p in log))

    def test_a_null_snapshot_zone_falls_back_to_the_save(self):
        snap = {"zone_id": None, "map_id": None}
        self.assertEqual(members._first(snap, "zone_id", "zone"), None)
        self.assertEqual(
            members._first({"zone_id": None, "zone": 1519}, "zone_id", "zone"), 1519
        )

    def test_a_quester_is_in_the_quester_group(self):
        guild = [
            {
                "name": "Grakk",
                "guild_name": "Bonkers",
                "level": 1,
                "class_id": 9,
                "race": 2,
            },
            {
                "name": "Zug",
                "guild_name": "Bonkers",
                "level": 30,
                "class_id": 1,
                "race": 2,
            },
            {
                "name": "Grakk",
                "guild_name": "Elsewhere",
                "level": 1,
                "class_id": 9,
                "race": 2,
            },
        ]
        out = members.build({"Zug": ["Zug"]}, guild[:2], [], [], [], {}, NOW)
        by = {m["name"]: m for m in out["members"]}
        self.assertEqual((by["Grakk"]["group"], by["Zug"]["group"]), ("quester", ""))
        self.assertEqual(by["Grakk"]["level"], 1)
        other = members.build({}, guild[2:], [], [], [], {}, NOW)
        self.assertEqual(other["members"][0]["group"], "")

    def test_no_roster_reads_nothing(self):
        ctx, log = ctx_for([], server(families={}))
        code, payload = members.roster({}, ctx)
        self.assertEqual((code, payload["members"]), (200, []))
        self.assertEqual(log, [])


# ---- a stalled family is stuck on its leader ------------------------------------------


class AStalledFamilyIsStuck(unittest.TestCase):
    """The operator, 2026-10-20: STALLED on the Now page beside "Top blocker:
    No current blocker recorded". A family with no quest, level or gear change
    for 20 minutes is a stuck record on its leader, named by his reading."""

    def stuck(self, moved):
        view = members.stuck_view(family_roster(moved=moved))
        return {m["name"]: m for m in view["members"]}, view

    def test_a_still_family_puts_its_leader_on_the_stuck_list(self):
        by, _ = self.stuck({"Zug": NOW - 1500, "Oz": NOW - 1320})
        zug = by["Zug"]
        self.assertEqual((zug["kind"], zug["since"]), ("stall", NOW - 1320))
        self.assertEqual(
            zug["blocker"],
            "No quest, level or gear change for the family for 22 minutes. "
            "Nothing the bridge recorded says why: Zug has no errand and no hold.",
        )

    def test_its_followers_are_held_by_the_stall(self):
        by, _ = self.stuck({"Zug": NOW - 1500})
        for name in ("Oz", "Uzza", "Zork"):
            self.assertEqual(("stall", "Zug"), (by[name]["kind"], by[name]["follows"]))
            self.assertIn("No quest, level or gear change", by[name]["blocker"])

    def test_the_digest_names_the_stall_as_a_cause(self):
        _, view = self.stuck({"Zug": NOW - 1500})
        self.assertTrue(
            any(c["cause"].startswith("stall: ") for c in view["digest"]["causes"])
        )

    def test_a_family_that_moved_lately_is_not_stuck(self):
        by, _ = self.stuck({"Zug": NOW - 600})
        self.assertNotIn("Zug", by)

    def test_a_leader_already_held_keeps_his_own_record(self):
        by, _ = self.stuck({"Grug": NOW - 5000})
        self.assertEqual("hold", by["Grug"]["kind"])
        self.assertEqual(NOW - 3 * 3600, by["Grug"]["since"])

    def test_no_movement_record_is_not_a_stall(self):
        by, _ = self.stuck({})
        self.assertNotIn("Zug", by)

    def test_the_read_carries_the_last_movement(self):
        rules = roster_rules() + [
            (("FROM overseer_event",), [{"name": "Grug", "at": NOW - 3600}])
        ]
        ctx, log = ctx_for(rules, server())
        code, payload = members.stuck({}, ctx)
        self.assertEqual(200, code)
        grug = {m["name"]: m for m in payload["members"]}["Grug"]
        self.assertEqual(("stall", NOW - 3600), (grug["kind"], grug["since"]))
        sql = next(q for q, _ in log if "FROM overseer_event" in q)
        self.assertNotIn("death", str([p for q, p in log if q == sql]))


# ---- upgrades now --------------------------------------------------------------------


def family_roster(asks=(), moved=None):
    """Two families as the stuck read of 2026-10-16 02:59Z saw them (#1059):
    Zug's four followers by a leader holding nothing, three at 0 yards and one
    on another map, and Grug held on a vendor with Grog at his side and Og
    left 4585 yards behind, all four read by the module as plain following."""
    fams = {
        "Zug": ["Zug", "Oz", "Uzza", "Zork", "Zrog"],
        "Grug": ["Grug", "Grog", "Og"],
    }
    roster = [
        {"name": n, "family": fam, "lead": i == 0}
        for fam, names in fams.items()
        for i, n in enumerate(names)
    ]
    intents = [
        {
            "leader_name": "Zug",
            "family": "Zug",
            "current_kind": "none",
            "module_age": 10,
            "members_state": "Oz|following|0\nUzza|following|0\n"
            "Zork|following|0\nZrog|following|another map",
        },
        {
            "leader_name": "Grug",
            "family": "Grug",
            "current_kind": "none",
            "module_age": 10,
            "members_state": "Grog|following|0\nOg|following|4585",
        },
    ]
    steps = [
        {
            "subject": "Grug",
            "scope": "character",
            "kind": "no_vendor",
            "doing": "Carrying things to sell",
            "waiting": "a vendor within reach",
            "occurrences": 40,
            "first_at": NOW - 3 * 3600,
            "last_at": NOW - 60,
        }
    ]
    names = [n for group in fams.values() for n in group]
    facts = nowstatus.build_facts(names, roster, intents, steps, NOW)
    chars = [{"name": n, "level": 30, "class_id": 1, "race": 2} for n in names]
    readings = {n: {"online": True, "life": "alive", "fresh_at": NOW} for n in names}
    return members.build(
        fams, [], chars, [], asks, facts, NOW, readings=readings, moved=moved
    )


class AFollowerIsHeldByItsLeader(unittest.TestCase):
    # #1059: a plain follower has no clock and no hold of its own. Read alone it
    # was stuck the moment it was read, beside a leader the list did not name.

    def setUp(self):
        self.stuck = members.stuck_view(family_roster())
        self.by = {m["name"]: m for m in self.stuck["members"]}

    def test_followers_by_a_leader_holding_nothing_are_not_stuck(self):
        for name in ("Zug", "Oz", "Uzza", "Zork"):
            self.assertNotIn(name, self.by, name)

    def test_a_follower_by_a_held_leader_names_his_hold_and_its_age(self):
        grog = self.by["Grog"]
        self.assertEqual(grog["step"], "Following Grug (0 yards behind)")
        self.assertEqual(
            grog["blocker"],
            "Waiting for Grug to move on. "
            "Grug's own hold: Waiting for a vendor within reach.",
        )
        self.assertEqual(
            (grog["since"], grog["kind"], grog["follows"]),
            (self.by["Grug"]["since"], "hold", "Grug"),
        )
        self.assertEqual(grog["since"], NOW - 3 * 3600)

    def test_a_follower_left_behind_is_stuck_on_being_left(self):
        self.assertEqual(
            self.by["Og"]["blocker"],
            "Left 4585 yards behind Grug, read as following, not walking back. "
            "Grug's own hold: Waiting for a vendor within reach.",
        )
        self.assertEqual(
            self.by["Zrog"]["blocker"],
            "On another map than Zug, read as following, not walking back.",
        )
        self.assertIsNone(self.by["Og"]["since"])
        self.assertIsNone(self.by["Zrog"]["since"])

    def test_the_stuck_list_falls_from_seven_to_four(self):
        # Without the follower reading: Grug, Grog, Og, Oz, Uzza, Zork, Zrog.
        self.assertEqual(sorted(self.by), ["Grog", "Grug", "Og", "Zrog"])

    def test_a_followers_own_class_quest_ask_is_still_its_own(self):
        asks = [ask(NOW - 7200, asker="Oz"), ask(NOW - 300, asker="Oz")]
        oz = {m["name"]: m for m in family_roster(asks)["members"]}["Oz"]
        self.assertEqual((oz["stuck"], oz["stuck_kind"]), (True, "class quest"))
        self.assertEqual((oz["since"], oz["follows"]), (NOW - 7200, ""))


def stuck_row(name, since, blocker, kind="hold", follows=""):
    return {
        "name": name,
        "step": "",
        "blocker": blocker,
        "since": since,
        "kind": kind,
        "follows": follows,
    }


BAG_FLOOR = "Waiting for Bork, Grog at the bag floor and no town pass has made room."
VENDOR = "Waiting for a vendor within reach."


class TheStuckDigestRanksTheCauses(unittest.TestCase):
    # #868: each tick journals the stuck count and the longest stuck time and
    # works the biggest cause first. The stuck read of 2026-10-19 held eleven:
    # five at the bag floor for 4.17h, five waiting on a vendor for 0.56h, and
    # one class quest for 0.91h. The list gave no count, no longest and no
    # grouping, so every tick summed them by hand.

    def setUp(self):
        bag = NOW - 15012
        vendor = NOW - 2016
        rows = [stuck_row(n, bag, BAG_FLOOR) for n in ("Bork", "Grog", "Grug")]
        rows += [stuck_row(n, vendor, VENDOR) for n in ("Oz", "Uzza", "Zork")]
        rows.append(
            stuck_row(
                "Ezzo",
                NOW - 3276,
                "Cannot finish Call of Water alone: asked the guild for help 3 "
                "times, 6 said yes.",
                kind="class quest",
            )
        )
        rows.append(stuck_row("Zrog", None, "On another map than Zug."))
        self.digest = members.stuck_digest(rows, NOW)

    def test_the_count_and_the_longest_wait_are_read_off(self):
        d = self.digest
        self.assertEqual(d["count"], 8)
        self.assertEqual(d["longest"], {"name": "Bork", "seconds": 15012})
        self.assertEqual((d["over_bound"], d["bound_s"]), (3, 7200))
        self.assertEqual(d["unmeasured"], 1)

    def test_the_biggest_cause_by_member_hours_comes_first(self):
        got = [
            (c["cause"], c["members"], c["member_hours"]) for c in self.digest["causes"]
        ]
        self.assertEqual(
            got,
            [
                ("hold: " + BAG_FLOOR, ["Bork", "Grog", "Grug"], 12.51),
                ("hold: " + VENDOR, ["Oz", "Uzza", "Zork"], 1.68),
                ("class quest", ["Ezzo"], 0.91),
                ("hold: On another map than Zug.", ["Zrog"], 0.0),
            ],
        )

    def test_a_followers_leader_hold_and_a_retry_time_do_not_split_a_cause(self):
        rows = [
            stuck_row(
                "Cronk", NOW - 600, "Waiting for the game (tries again at 21:50)."
            ),
            stuck_row(
                "Bonk", NOW - 900, "Waiting for the game (tries again at 22:21)."
            ),
            stuck_row(
                "Grog",
                NOW - 900,
                "Waiting for Bonk to move on. "
                "Bonk's own hold: Waiting for the game (tries again at 22:21).",
                follows="Bonk",
            ),
        ]
        causes = members.stuck_digest(rows, NOW)["causes"]
        self.assertEqual(len(causes), 1)
        self.assertEqual(
            causes[0]["cause"], "hold: Waiting for the game (tries again at #:#)."
        )
        self.assertEqual(causes[0]["longest_s"], 900)

    def test_the_stuck_read_carries_its_digest(self):
        stuck = members.stuck_view(family_roster())
        d = stuck["digest"]
        self.assertEqual(d["count"], len(stuck["members"]))
        self.assertEqual(d["longest"], {"name": "Grog", "seconds": 3 * 3600})
        self.assertEqual(d["causes"][0]["members"], ["Grog", "Grug", "Og"])

    def test_an_empty_list_digests_to_nobody(self):
        d = members.stuck_digest([], NOW)
        self.assertEqual((d["count"], d["longest"], d["causes"]), (0, None, []))


def gain(slot, delta, entry, ilvl=30, boss="Boss"):
    return {
        "slot": slot,
        "delta": delta,
        "entry": entry,
        "name": "Item %d" % entry,
        "quality": 3,
        "icon": "inv_x",
        "ilvl": ilvl,
        "boss": boss,
    }


class NowIsTheBestDropOpenAtThisLevel(unittest.TestCase):
    PLAN = {
        "dungeons": [
            {
                "name": "Uldaman",
                "shut": False,
                "members": [{"gains": [gain("hands", 5, 1), gain("back", 8, 2)]}],
            },
            {
                "name": "Zul'Farrak",
                "shut": False,
                "members": [{"gains": [gain("hands", 19, 3)]}],
            },
            {
                "name": "Molten Core",
                "shut": True,
                "members": [{"gains": [gain("hands", 50, 4)]}],
            },
            {
                "name": "Deadmines",
                "shut": False,
                "members": [{"gains": [gain("trinket 1", None, 5, ilvl=22)]}],
            },
        ]
    }

    def test_the_biggest_gain_per_slot_wins_and_a_shut_dungeon_is_skipped(self):
        best = upgrades.best_now(self.PLAN)
        self.assertEqual(best["hands"]["entry"], 3)
        self.assertEqual(best["hands"]["where"], "Zul'Farrak, Boss")
        self.assertEqual(best["back"]["gain"], 8)

    def test_an_empty_slot_gains_the_whole_item_level(self):
        best = upgrades.best_now(self.PLAN)
        self.assertEqual(best["trinket 1"]["gain"], 22)
        self.assertTrue(best["trinket 1"]["empty"])

    def test_extend_adds_now_and_keeps_every_existing_field(self):
        payload = {
            "name": "Grug",
            "level": 42,
            "ready": {"pct": 0.0},
            "slots": [
                {"slot": "hands", "state": "upgrade", "worn": {"entry": 9}},
                {"slot": "head", "state": "bis", "worn": None},
            ],
        }
        out = upgrades.extend(
            payload, upgrades.best_now(self.PLAN), {"9": {"quality": 2}}, 42
        )
        for key, value in payload.items():
            if key != "slots":
                self.assertEqual(out[key], value)
        for old, new in zip(payload["slots"], out["slots"], strict=True):
            self.assertLessEqual(old.items(), new.items())
        self.assertEqual(out["slots"][0]["now"]["gain"], 19)
        self.assertIsNone(out["slots"][1]["now"])
        self.assertEqual(out["now_count"], 1)
        self.assertIn("At level 42, now", out["now_basis"])

    def test_every_named_item_gets_its_quality_and_icon(self):
        payload = {
            "slots": [
                {
                    "worn": {"entry": 9},
                    "next": {"entry": 10},
                    "targets": {"preraid": [{"entry": 11}], "raid": [{"entry": 12}]},
                }
            ]
        }
        self.assertEqual(upgrades.named_entries(payload), {9, 10, 11, 12})
        idx = upgrades.item_index(
            [{"entry": 9, "quality": 3, "displayid": 77, "item_level": 40}],
            {77: "inv_y"},
        )
        self.assertEqual(idx, {"9": {"quality": 3, "icon": "inv_y", "item_level": 40}})

    def test_the_handler_extends_the_v1_payload(self):
        v1 = {
            "name": "Grug",
            "level": 42,
            "slots": [{"slot": "hands", "worn": {"entry": 9}}],
        }
        upgrades._WORLD.clear()
        srv = server(
            _upgrades_payload=lambda name: (200, v1),
            _PLAN_CATALOGUE="SELECT catalogue",
            _PLAN_CATALOGUE_OLD="",
            _PLAN_ENCOUNTERS="SELECT encounters {holes}",
            _PLAN_LOOT="SELECT loot {holes}",
            _PLAN_CHARS="SELECT plan chars {holes}",
            _PLAN_CHARS_OLD="",
            _RECAP_WORN="SELECT worn {holes}",
            _RECAP_SKILLS="SELECT skills {holes}",
            armory=types.SimpleNamespace(EQUIPPED_SLOTS=list(range(19))),
            ITEMS=types.SimpleNamespace(icons={}),
            GEO=types.SimpleNamespace(entrances={}, continents={}),
        )
        rules = [
            (
                ("plan chars",),
                [{"name": "Grug", "level": 42, "class": 1, "map": 0, "race": 1}],
            ),
            (
                ("item_template",),
                [{"entry": 9, "quality": 2, "displayid": None, "item_level": 30}],
            ),
        ]
        ctx, _log = ctx_for(rules, srv)
        code, out = upgrades.upgrades({"name": ["Grug"]}, ctx)
        self.assertEqual(code, 200)
        self.assertEqual(out["slots"][0]["worn"], {"entry": 9})
        self.assertIsNone(out["slots"][0]["now"])
        self.assertEqual(out["items"]["9"]["quality"], 2)


# ---- training (Standing) ---------------------------------------------------------------


class StandingSortsWhatATrainerSells(unittest.TestCase):
    ROWS = [
        {"spell": 1, "level": 10, "cost": 100},
        {"spell": 2, "level": 20, "cost": 200},
        {"spell": 3, "level": 20, "cost": 300, "req1": 99},
        {"spell": 4, "level": 50, "cost": 400},
        {"spell": 5, "level": 70, "cost": 500},
    ]

    def test_learned_trainable_needs_and_above(self):
        out = training.spells(self.ROWS, {1}, 30, 60)
        self.assertEqual([s["spell"] for s in out["learned"]], [1])
        self.assertEqual([s["spell"] for s in out["trainable"]], [2])
        self.assertEqual([s["spell"] for s in out["needs"]], [3])
        self.assertEqual([s["spell"] for s in out["above"]], [4])
        self.assertEqual(out["trainable_cost"], 200)
        self.assertEqual(out["next_level"], 50)

    def test_a_rank_is_judged_by_the_bridges_own_rule(self):
        herb = guildjobs.HERBALISM
        self.assertEqual(training.trade_state(herb, 300, 300, 40)["state"], "learned")
        self.assertEqual(training.trade_state(herb, 75, 75, 10)["state"], "trainable")
        self.assertEqual(training.trade_state(herb, 20, 75, 10)["state"], "skill")
        self.assertEqual(training.trade_state(herb, 225, 225, 20)["state"], "above")

    def test_an_apprentice_trade_reads_the_skill_the_bridge_buys_at(self):
        # Cooking 1/75 and First Aid 58/75: the next rank asks skill 50, but the
        # bridge buys it only within RANK_UP_MARGIN of the 75 ceiling, so the
        # card must say 70 and not 50 (a 58 reads as met when it is not due).
        cook = training.trade_state(guildjobs.COOKING, 1, 75, 46)
        self.assertEqual(cook["state"], "skill")
        self.assertEqual(cook["next"]["needs"], 50)
        self.assertEqual(cook["next"]["buys_at"], 70)
        aid = training.trade_state(guildjobs.FIRST_AID, 58, 75, 46)
        self.assertEqual(aid["state"], "skill")
        self.assertEqual(aid["next"]["buys_at"], 70)
        # A rank whose own ask is higher than the margin keeps its ask.
        self.assertEqual(
            training.trade_state(guildjobs.HERBALISM, 20, 150, 40)["next"]["buys_at"],
            max(guildjobs.RANKS[guildjobs.HERBALISM][2].needs, 145),
        )

    def test_the_line_counts_both(self):
        f = {
            "char": {"level": 30, "class_id": 1, "money": 5},
            "known": [{"spell": 1}],
            "trainer": self.ROWS,
            "skills": [{"skill": guildjobs.HERBALISM, "value": 75, "max": 75}],
        }
        out = training.build("Grug", f)
        self.assertEqual(out["line"], "1 learned, 2 trainable now, 1 above level")
        self.assertEqual(out["class"], "Warrior")


# ---- class chains --------------------------------------------------------------------


def quest(qid, title, prev=0, reward=0, level=10, classes=1, races=0):
    return {
        "id": qid,
        "title": title,
        "sort": 0,
        "min_level": level,
        "races": races,
        "classes": classes,
        "prev": prev,
        "exclusive": 0,
        "reward": reward,
        "display": 0,
        "grp": 0,
    }


class TheClassChain(unittest.TestCase):
    QUESTS = [
        quest(1, "A Warrior's Training"),
        quest(2, "Bartleby the Drunk", prev=1),
        quest(3, "Bartleby's Mug", prev=2, reward=71),
        quest(4, "The Islander", level=30),
        quest(5, "The Affray", prev=4, reward=72, level=30),
        quest(6, "Retired", reward=73),
        quest(7, "Sold At A Trainer", reward=74),
    ]

    def book(self):
        return classchain.book_of(self.QUESTS, {1, 4, 7}, [{"spell": 74}])

    def test_a_quest_nothing_starts_and_a_trained_reward_are_left_out(self):
        char = {"class_id": 1, "race": 1, "level": 20}
        found = classchain.chains(self.book(), char, {}, set(), set(), 0)
        self.assertEqual([c["title"] for c in found], ["Bartleby's Mug", "The Affray"])

    def test_each_step_says_where_it_stands(self):
        char = {"class_id": 1, "race": 1, "level": 20}
        status = {2: 3}
        found = classchain.chains(self.book(), char, status, {1}, set(), 0)
        steps = {s["title"]: s["state"] for c in found for s in c["steps"]}
        self.assertEqual(steps["A Warrior's Training"], "done")
        self.assertEqual(steps["Bartleby the Drunk"], "in progress")
        self.assertEqual(steps["Bartleby's Mug"], "open")
        self.assertEqual(steps["The Islander"], "locked")
        blocked = classchain.chains(self.book(), char, status, {1}, set(), 3)
        self.assertEqual(blocked[0]["steps"][2]["state"], "blocked")

    def test_a_known_reward_spell_is_a_done_chain(self):
        char = {"class_id": 1, "race": 1, "level": 40}
        found = classchain.chains(self.book(), char, {}, set(), {71}, 0)
        self.assertTrue(found[0]["done"])

    def test_the_live_ask_names_the_blocked_quest(self):
        self.assertEqual(
            classchain.blocked_quest([ask(NOW - 60, target="quest:3")], NOW), 3
        )
        self.assertEqual(
            classchain.blocked_quest([ask(NOW - 9 * 3600, target="quest:3")], NOW), 0
        )

    def test_a_chain_that_opens_a_longer_one_is_drawn_once(self):
        a = {"steps": [{"id": 1}, {"id": 2}]}
        b = {"steps": [{"id": 1}, {"id": 2}, {"id": 3}]}
        self.assertEqual(classchain.without_prefixes([a, b]), [b])


# ---- activity ----------------------------------------------------------------------------


class Activity(unittest.TestCase):
    def test_sources_and_answers_in_words(self):
        self.assertEqual(
            activity.source_words("guildjobs:classquest-walk:Chopp"),
            "guild jobs, classquest walk",
        )
        self.assertEqual(activity.source_words("overseer:guildsocial"), "guild chat")
        self.assertEqual(activity.source_words("something:new"), "something:new")
        self.assertEqual(
            activity.answer_words("error", "vendor not in range"),
            "refused: vendor not in range",
        )
        self.assertEqual(activity.answer_words("applied", ""), "done")

    def test_the_handler_reads_commands_without_probes_and_the_level_line(self):
        rules = [
            (
                ("FROM overseer_command",),
                [
                    {
                        "id": 5,
                        "kind": "job",
                        "source": "guildjobs:level:Grug",
                        "command": "walk",
                        "status": "applied",
                        "detail": "",
                        "at": NOW,
                    }
                ],
            ),
            (
                ("FROM overseer_level",),
                [{"old_level": 41, "new_level": 42, "at": NOW - 100}],
            ),
            (("FROM characters",), [{"level": 42, "now_at": NOW}]),
        ]
        ctx, log = ctx_for(rules, server())
        code, out = activity.activity({"name": ["Grug"]}, ctx)
        self.assertEqual(code, 200)
        self.assertEqual(out["commands"][0]["source"], "guild jobs, level")
        self.assertEqual(out["levels"], [[NOW - 100, 42]])
        self.assertEqual(out["start_level"], 41)
        command_sql = next(sql for sql, _p in log if "overseer_command" in sql)
        self.assertIn("kind <> 'probe'", command_sql)
        self.assertIn("api:auras", command_sql)


# ---- the guild gear strip ------------------------------------------------------------------


class TheQualityStrip(unittest.TestCase):
    def test_one_cell_per_stat_slot_with_the_worn_quality(self):
        rows = [
            {
                "guild_name": "Cave",
                "name": "Og",
                "level": 20,
                "class_id": 8,
                "money": 1,
                "online": 1,
                "slot": 0,
                "item_level": 20,
                "item_name": "Cap",
                "item_entry": 1,
                "item_quality": 3,
            },
        ]
        m = guildgear.members_from_rows(rows)[0]
        self.assertEqual(len(m["strip"]), len(guildgear.STAT_SLOTS))
        self.assertEqual(m["strip"][0], {"slot": "head", "quality": 3, "name": "Cap"})
        self.assertIsNone(m["strip"][1]["quality"])


# ---- the nav badge -----------------------------------------------------------------------------


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheMembersBadge(unittest.TestCase):
    def run_badge(self, data):
        # The app is copied whole into a module package: badges.js reads its
        # times through models/time.js.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(HERE / "app", root)
            (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
            dst = root / "badges.js"
            code = (
                "import P from %s;\n"
                "const p = P.find((b) => b.section === 'members');\n"
                "const got = p.compute(() => ({data: %s}), {});\n"
                "console.log(JSON.stringify({reads: p.reads, got}));"
            ) % (json.dumps(dst.as_uri()), json.dumps(data))
            out = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", code],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        return json.loads(out.stdout)

    def test_a_warn_badge_with_the_stuck_count_opens_the_stuck_roster(self):
        out = self.run_badge({"members": [{"name": "A"}, {"name": "B"}]})
        self.assertEqual(out["reads"], ["/api/v2/stuck"])
        self.assertEqual(
            out["got"],
            {"n": 2, "tone": "warn", "label": "2 stuck", "href": "#/members?stuck=1"},
        )

    def test_nobody_stuck_is_no_badge(self):
        self.assertIsNone(self.run_badge({"members": []})["got"])


class AGhostIsOutOfPlay(unittest.TestCase):
    """A released ghost reads as dead to nowstatus, so it shows Ghost, not
    Idle. #1093"""

    def test_a_ghost_reading_is_a_dead_condition_and_keeps_its_life(self):
        got = members._presence({"online": True, "life": "ghost"}, None)
        self.assertEqual("dead", got["condition"])
        self.assertEqual("ghost", got["life"])

    def test_an_online_ghost_composes_as_ghost_not_idle(self):
        presence = members._presence({"online": True, "life": "ghost"}, None)
        got = nowstatus.compose({"name": "Grumbles", **presence}, None)
        self.assertEqual("Ghost", got["doing"])

    def test_a_living_reading_stays_ok(self):
        got = members._presence({"online": True, "life": "alive"}, None)
        self.assertEqual("ok", got["condition"])


if __name__ == "__main__":
    unittest.main()
