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
import guildgear  # noqa: E402
import guildjobs  # noqa: E402
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


def server(families=None, guildmates=(), **extra):
    fams = families if families is not None else {"Grug": ["Grug", "Ugga"]}
    ns = types.SimpleNamespace(
        _NAME_RE=__import__("re").compile(r"^[A-Za-z]{2,12}$"),
        _fetch_families=lambda: fams,
        _fetch_family_groups=lambda: list(fams.items()),
        _is_family_guildmate=lambda name, names: name in guildmates,
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
        self.assertIn("nobody has come", found["blocker"])

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
                    "blocker": "Cannot finish Taming the Beast alone: asked the guild for help 2 times, and nobody has come.",
                    "since": NOW - 7200,
                    "kind": "class quest",
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

    def test_no_roster_reads_nothing(self):
        ctx, log = ctx_for([], server(families={}))
        code, payload = members.roster({}, ctx)
        self.assertEqual((code, payload["members"]), (200, []))
        self.assertEqual(log, [])


# ---- upgrades now --------------------------------------------------------------------


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
        with tempfile.TemporaryDirectory() as tmp:
            dst = pathlib.Path(tmp) / "badges.mjs"
            dst.write_text(
                (HERE / "app" / "badges.js").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
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


if __name__ == "__main__":
    unittest.main()
