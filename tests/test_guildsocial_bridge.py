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
