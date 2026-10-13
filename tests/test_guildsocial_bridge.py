"""The bridge's half of the social layer, driven for real with the reads stubbed.

`Bridge._guild_social_once` turns the facts into a guildsocial.Pass and hands
it to `_write_guild_social`, which closes and records asks and answers, writes
the run an ask formed exactly as the old coordinator wrote one (its finder row
targeted at the tank), and says every line in guild chat from its speaker.
"""

import asyncio
import contextlib
import datetime
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import guildrun  # noqa: E402
import guildsocial as gs  # noqa: E402
import jev  # noqa: E402
from test_guildsocial import NOW, ask, five_yeses  # noqa: E402
from test_guildsocial import two_door_post  # noqa: E402
from test_jev_items import FakeJev  # noqa: E402


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()
bridge._COMPLETED_PASSES.add("guild_jobs")


def row(name, level, class_id, **kw):
    out = {
        "name": name,
        "level": level,
        "class_id": class_id,
        "map_id": 0,
        "race": 1,
        "zone_id": 40,
        "in_combat": 0,
        "health": 300,
        "group_leader": 0,
        "guild_name": "Cave",
        "talent_spells": None,
        "target_tree": "",
        "pos_x": -11100.0,
        "pos_y": 1600.0,
        "worn_slots": 6,
        "has_weapon": 1,
    }
    out.update(kw)
    return out


def facts():
    rows = [
        row("Auren", 20, 4),
        row("Tanky", 21, 1, talent_spells="12301", has_shield=1),
        row("Healy", 20, 5, talent_spells="14913"),
        row("Zappy", 19, 8),
        row("Locky", 20, 9),
        row("Idle", 20, 8, zone_id=1519),
    ]
    return {
        "rows": rows,
        "busy": set(),
        "resting": set(),
        "family": set(),
        "benched": set(),
        "finder_floors": {},
        "history": [],
        "in_flight_by_guild": {},
        "now": NOW,
        "asks": [ask(7, "Auren")],
        "answers": five_yeses(),
        "quests": {},
        "gear": {},
        "campaigns": [],
        "drops": {},
    }


class _Self:
    """The attributes `_guild_social_once` reads off the bridge."""

    def __init__(self):
        self._guild_run_formed_at = None
        self._guild_run_names = set()
        self._guild_social_names = set()
        self._job_steps = {}


class TheBridgePass(unittest.TestCase):
    def run_once(self, this, **patches):
        written = []

        def write(social):
            written.append(social)
            return 41 if social.form else 0

        stubs = {
            "_guild_run_gate": lambda: {"uptime": 99999, "latest": []},
            "_guild_runs_in_flight": lambda: 0,
            "_fetch_guild_social_facts": lambda bounds: facts(),
            "_write_guild_social": write,
            "_guild_social_names": lambda: {"Auren"},
        }
        stubs.update(patches)
        with mock.patch.multiple(bridge, **stubs):
            asyncio.run(bridge.Bridge._guild_social_once(this))
        return written

    def test_an_answered_ask_becomes_the_run_and_nobody_else_is_seated(self):
        this = _Self()
        written = self.run_once(this)
        self.assertEqual(len(written), 1)
        form = written[0].form
        self.assertIsNotNone(form)
        self.assertEqual(form.composition.tank.name, "Tanky")
        self.assertNotIn("Idle", form.composition.names)
        self.assertEqual(
            set(this._guild_run_names), {"Auren", "Tanky", "Healy", "Zappy", "Locky"}
        )
        self.assertIsNotNone(this._guild_run_formed_at)
        self.assertEqual(this._guild_social_names, {"Auren"})

    def test_a_yes_on_a_guild_job_is_not_seated(self):
        this = _Self()
        this._job_steps = {"Zappy": 1.0}
        written = self.run_once(this)
        self.assertIsNone(written[0].form)
        self.assertEqual(written[0].withdraw, (3,))

    def test_the_cap_holds_the_group_as_filled(self):
        this = _Self()
        written = self.run_once(this, _guild_runs_in_flight=lambda: guildrun.MAX_GROUPS)
        self.assertIsNone(written[0].form)
        self.assertEqual(written[0].filled, (7,))
        self.assertIsNone(this._guild_run_formed_at)


class _RecipeCursor:
    """The two reads _guild_raid_recipes makes: the drops, then who knows."""

    def __init__(self, drops, known):
        self.reads = []
        self.drops, self.known = drops, known

    def execute(self, sql, args=()):
        self.reads.append(sql)

    def fetchall(self):
        last = self.reads[-1]
        return self.drops if "creature_loot_template" in last else self.known


class TheRaidRecipes(unittest.TestCase):
    """The bridge reads the raid recipes nobody knows and hands them on (#893)."""

    SPIRE = "Recipe: Greater Fire Protection Potion"

    def setUp(self):
        bridge._RAID_RECIPE_DROPS = None
        self.addCleanup(setattr, bridge, "_RAID_RECIPE_DROPS", None)

    def test_each_guild_gets_the_recipes_its_members_do_not_know(self):
        drops = [{"item": 13494, "item_name": self.SPIRE, "map_id": 229}]
        known = [{"guild": "Den", "spell": 17574}]
        cur = _RecipeCursor(drops, known)
        found = bridge._guild_raid_recipes(cur, ["Cave", "Den"])
        self.assertEqual(found, {"Cave": {229: (self.SPIRE,)}, "Den": {}})
        # The drops are read once; who knows a recipe is read every pass.
        bridge._guild_raid_recipes(cur, ["Cave"])
        self.assertEqual(sum("creature_loot_template" in sql for sql in cur.reads), 1)
        self.assertEqual(sum("character_spell" in sql for sql in cur.reads), 2)

    def test_no_guild_reads_nothing(self):
        cur = _RecipeCursor([], [])
        self.assertEqual(bridge._guild_raid_recipes(cur, []), {})
        self.assertEqual(cur.reads, [])

    def test_the_social_pass_is_handed_the_recipes(self):
        recipes = {"Cave": {229: (self.SPIRE,)}}

        def with_recipes(bounds):
            out = facts()
            out["recipes"] = recipes
            return out

        handed, real = [], gs.plan_pass

        def plan_pass(*args, **kwargs):
            handed.append(kwargs.get("recipes"))
            return real(*args, **kwargs)

        with mock.patch.object(bridge.guildsocial, "plan_pass", plan_pass):
            TheBridgePass().run_once(_Self(), _fetch_guild_social_facts=with_recipes)
        self.assertEqual(handed, [recipes])


class _Cursor:
    def __init__(self, log):
        self.log = log
        self.rowcount = 1
        self.lastrowid = 0

    def execute(self, sql, args=()):
        self.lastrowid += 100
        self.log.append((sql, tuple(args)))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, log):
        self.log = log

    def cursor(self):
        return _Cursor(self.log)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TheBridgeWrites(unittest.TestCase):
    def test_ask_index_is_added_only_when_missing(self):
        for present, expected in ((True, False), (False, True)):
            statements = []

            class Cursor:
                # Defaults bind this iteration's list and flag (ruff B023).
                def execute(self, sql, args=(), statements=statements):
                    statements.append(sql)

                def fetchone(self, statements=statements, present=present):
                    # First lookup is idx_created; second is the proposer column.
                    return (
                        {"n": int(present)}
                        if len(
                            [
                                s
                                for s in statements
                                if "information_schema.STATISTICS" in s
                            ]
                        )
                        == 1
                        else {"n": 1}
                    )

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            class Conn:
                def cursor(self):
                    return Cursor()

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            with (
                mock.patch.multiple(
                    bridge,
                    _connect=lambda: Conn(),
                ),
                mock.patch.object(bridge.guildpug, "enabled", return_value=False),
            ):
                bridge._ensure_guild_run_store()
            alters = [s for s in statements if "ADD KEY idx_created" in s]
            self.assertEqual(bool(alters), expected)

    def test_ask_index_database_error_is_logged_and_swallowed(self):
        class Cursor:
            def execute(self, sql, args=()):
                if "information_schema.STATISTICS" in sql:
                    raise bridge.pymysql.err.MySQLError("db unavailable")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Conn:
            def cursor(self):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with (
            mock.patch.object(
                bridge.pymysql,
                "err",
                types.SimpleNamespace(MySQLError=Exception),
                create=True,
            ),
            mock.patch.multiple(bridge, _connect=lambda: Conn()),
            mock.patch.object(bridge.guildpug, "enabled", return_value=False),
            mock.patch.object(bridge.log, "exception") as logged,
        ):
            bridge._ensure_guild_run_store()
        logged.assert_called_once()

    def test_the_rows_then_the_lines_from_their_speakers(self):
        sql = []
        said = []
        form_pass = None

        def fake_facts(bounds):
            return facts()

        written = []
        with mock.patch.multiple(
            bridge,
            _guild_run_gate=lambda: {"uptime": 99999, "latest": []},
            _guild_runs_in_flight=lambda: 0,
            _fetch_guild_social_facts=fake_facts,
            _write_guild_social=lambda social: written.append(social) or 0,
            _guild_social_names=lambda: set(),
        ):
            asyncio.run(bridge.Bridge._guild_social_once(_Self()))
        form_pass = written[0]
        expired = ask(8, "Bree", expires_at=NOW - datetime.timedelta(minutes=1))
        post = gs.Post(
            guild="Cave",
            asker="Cole",
            kind="dungeon",
            target="wailing",
            target_label="Wailing Caverns",
            roles_needed="tank,healer,dps,dps",
            reason="r",
            said="Anyone up for Wailing Caverns?",
        )
        reply = gs.Reply(
            ask_id=9, member="Dain", role="dps", stance="need", said="I'm in!"
        )
        social = gs.Pass(
            expire=((expired.id, "Bree", "Never mind."),),
            posts=(post,),
            replies=(reply,),
            form=form_pass.form,
        )
        with mock.patch.multiple(
            bridge,
            _connect=lambda: _Conn(sql),
            _wait_out_of_combat=lambda names: [],
            _insert_speak=lambda cmd: said.append(
                (cmd.target_name, cmd.channel, cmd.text)
            ),
        ):
            run_id = bridge._write_guild_social(social)
        self.assertTrue(run_id)
        statements = [s for s, _a in sql]
        run_insert = next(
            s for s in statements if "INSERT INTO overseer_guild_run" in s
        )
        self.assertIn("proposer", run_insert)
        finder = next(a for s, a in sql if "INSERT INTO overseer_command" in s)
        self.assertEqual(finder[0], "Tanky")
        self.assertTrue(finder[1].startswith("finder-run deadmines Healy "))
        ran = next(a for s, a in sql if s == gs.ASK_RAN_SQL)
        self.assertEqual(ran, (run_id, 7))
        seated = [a for s, a in sql if s == gs.ANSWER_STATE_SQL and a[0] == gs.SEATED]
        self.assertEqual(sorted(a[1] for a in seated), [1, 2, 3, 4])
        self.assertEqual(
            [(n, c) for n, c, _t in said],
            [
                ("Bree", "guild"),
                ("Cole", "guild"),
                ("Dain", "guild"),
                ("Tanky", "guild"),
            ],
        )
        self.assertIn("Auren's Deadmines group", said[-1][2])


if __name__ == "__main__":
    unittest.main()


class TheBridgeAsksJevTheDoor(unittest.TestCase):
    """#584: each new ask with two doors goes to Jev once before it is
    written, and the judgment is recorded."""

    def test_the_post_is_rewritten_and_the_judgment_recorded(self):
        post = two_door_post()
        recorded = []
        client = jev.Client(
            "k", transport=FakeJev(picks={"door": "wailing"}, confidence=0.9)
        )
        with mock.patch.object(bridge, "_insert_jev_judgment", recorded.append):
            out = asyncio.run(
                bridge._guild_social_doors(client, gs.Pass(posts=(post,)))
            )
        self.assertEqual(out.posts[0].target, "wailing")
        self.assertEqual([j.kind for j in recorded], [gs.KIND_ASK_DOOR])

    def test_a_failure_keeps_the_heuristics_door(self):
        post = two_door_post()

        def broken(*_a):
            raise RuntimeError("boom")

        client = jev.Client("k", transport=FakeJev())
        with mock.patch.object(gs, "choose_door", side_effect=broken):
            with self.assertLogs(bridge.log, "ERROR"):
                out = asyncio.run(
                    bridge._guild_social_doors(client, gs.Pass(posts=(post,)))
                )
        self.assertEqual(out.posts, (post,))


class AFightDoesNotCostTheGroup(unittest.TestCase):
    """2026-10-05: 5 of Bonkers' last 14 guild runs were refused at the door
    because one member was in a fight. The start waits it out."""

    def test_nobody_is_started_while_a_member_fights(self):
        started = []
        social = gs.Pass(
            form=types.SimpleNamespace(
                composition=types.SimpleNamespace(names=("Tanky", "Healy")),
                ask=types.SimpleNamespace(asker="Cole"),
                speaker="Cole",
                said="Off we go",
            )
        )
        with mock.patch.multiple(
            bridge,
            _connect=lambda: _Conn([]),
            _wait_out_of_combat=lambda names: ["Healy"],
            _start_social_run=lambda form: started.append(form) or 5,
            _insert_speak=lambda cmd: None,
        ):
            self.assertEqual(bridge._write_guild_social(social), 0)
        self.assertEqual(started, [])

    def test_the_wait_reads_until_nobody_fights(self):
        reads = iter([[{"name": "Healy"}], []])

        class Cur:
            def execute(self, sql, args):
                self.rows = next(reads)

            def fetchall(self):
                return self.rows

        class Conn:
            def cursor(self):
                return contextlib.nullcontext(Cur())

        with (
            mock.patch.object(
                bridge, "_connect", lambda: contextlib.nullcontext(Conn())
            ),
            mock.patch.object(bridge.time, "sleep", lambda s: None),
        ):
            self.assertEqual(
                bridge._wait_out_of_combat(["Tanky", "Healy"], wait=60, poll=0), []
            )

    def test_a_fight_benches_nobody(self):
        rows = [
            {"outcome": "refused", "why": "'Amony' is in combat"},
            {"outcome": "refused", "why": "'Daidanden' is dead"},
        ]
        self.assertEqual(guildrun.benched(rows), {"Daidanden"})
