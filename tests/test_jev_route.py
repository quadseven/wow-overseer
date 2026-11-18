"""Jev asks TypeSafe first and OpenAI Decisions next, then the heuristic (#2899).

JEV_ROUTE names the backends in order. A call goes on to the next one when a
backend asked nothing (no key, paused, capped, busy) or refused it with 401,
402 or 429; that backend is backed off, the paid side holds a daily cap in its
spend ledger, and each backend's calls and tokens are counted per UTC day.
Every test drives the real `jev.Client` through fake transports.
"""

import asyncio
import calendar
import json
import unittest

import jev
import jev_openai as jo
from test_jev import ROUTE, Transport, good_choice, reply

NOV = calendar.timegm((2026, 11, 17, 12, 0, 0))


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def decision(pick="keep"):
    body = {
        "model": "gpt-6-luna",
        "answers": [
            {
                "type": "choice",
                "name": "route",
                "choice": pick,
                "probabilities": [
                    {"value": "keep", "probability": 0.8},
                    {"value": "vendor", "probability": 0.1},
                    {"value": "equip", "probability": 0.1},
                ],
                "confidence": 0.8,
            }
        ],
        "usage": {"input_tokens": 600, "output_tokens": 0},
    }
    return 200, json.dumps(body).encode()


def routed(jev_result, openai_result=None, env=None, clock=None, **kw):
    """A TypeSafe client that falls back to an OpenAI one, each on its own
    transport; the OpenAI side has a spend ledger in memory."""
    clock = clock or Clock()
    first = Transport(result=jev_result)
    second = Transport(result=openai_result or decision())
    store = jo.MemoryStore()
    openai = jev.Client(
        "k-openai",
        backend=jev.OpenAIBackend(),
        url="https://example.com/v1/decisions",
        model="gpt-6-luna",
        transport=second,
        clock=clock,
        spend=jo.Spend(store, env or {}, lambda: NOV),
    )
    client = jev.Client("k-jev", transport=first, clock=clock, fallbacks=[openai], **kw)
    return client, first, second, store


def ask(client, state="a sword"):
    return asyncio.run(client.ask("item_disposition", state, {"route": ROUTE}))


class Configuration(unittest.TestCase):
    def test_jev_route_names_the_backends_in_order_and_leads(self):
        env = {"JEV_ROUTE": "jev, openai", "JEV_PROVIDER": "openai"}
        self.assertEqual(jev.route_names(env), ["jev", "openai"])
        self.assertEqual(jev.backend_name(env), "jev")

    def test_one_backend_or_unknown_names_route_nothing(self):
        for raw in ("", "jev", "jev,jev", "jev,nope"):
            with self.subTest(raw=raw):
                self.assertEqual(jev.route_names({"JEV_ROUTE": raw}), [])
        self.assertEqual(jev.backend_name({"JEV_ROUTE": "jev"}), "jev")

    def test_from_env_builds_the_fallback_with_its_own_key_and_ledger(self):
        env = {
            "JEV_ROUTE": "jev,openai",
            "TYPESAFE_API_KEY": "k-jev",
            "OPENAI_API_KEY": "k-openai",
            "JEV_BACKOFF_429_SECONDS": "30",
        }
        with self.assertLogs("wow-overseer.jev", "INFO") as logs:
            client = jev.Client.from_env(env)
        self.assertEqual(client.backend.name, "jev")
        self.assertIsNone(client.spend)
        [openai] = client.fallbacks
        self.assertEqual(openai.backend.name, "openai")
        self.assertEqual(openai.model, "gpt-6-luna")
        self.assertIsNotNone(openai.spend)
        self.assertIsNone(openai.shadow)
        self.assertEqual(openai.fallbacks, [])
        self.assertEqual(client.backoff_429_seconds, 30.0)
        self.assertIn("jev then openai then the heuristic", logs.output[0])

    def test_without_jev_route_there_is_no_fallback(self):
        client = jev.Client.from_env({"TYPESAFE_API_KEY": "k"})
        self.assertEqual(client.fallbacks, [])

    def test_answered_by_reads_the_backend_from_the_model(self):
        self.assertEqual(jev.answered_by("jev-1.14.0"), "jev")
        self.assertEqual(jev.answered_by("gpt-6-luna"), "openai")
        self.assertEqual(jev.answered_by("@cf/cloudflare/clef-flash"), "clef")
        self.assertEqual(jev.answered_by(""), "")


class Routing(unittest.TestCase):
    def test_typesafe_answers_and_openai_is_not_asked(self):
        client, first, second, store = routed(reply(good_choice()))
        out = ask(client)
        self.assertEqual((out.status, out.backend), (jev.ANSWERED, "jev"))
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(second.calls, [])
        self.assertEqual(store.rows, [])

    def test_a_402_sends_the_call_on_and_backs_typesafe_off(self):
        client, first, second, _ = routed((402, b'{"error":"payment required"}'))
        with self.assertLogs("wow-overseer.jev", "WARNING") as logs:
            out = ask(client)
        self.assertEqual((out.status, out.backend), (jev.ANSWERED, "openai"))
        self.assertEqual(out.answers["route"].choice, "keep")
        self.assertTrue(any("openai or the heuristic" in s for s in logs.output))
        # While TypeSafe is backed off it is not asked at all.
        again = ask(client, state="another sword")
        self.assertEqual(again.backend, "openai")
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(len(second.calls), 2)

    def test_a_429_backs_off_for_its_own_shorter_window(self):
        clock = Clock()
        client, first, second, _ = routed(
            (429, b"{}"), clock=clock, backoff_429_seconds=60
        )
        self.assertEqual(ask(client).backend, "openai")
        clock.now += 30
        self.assertEqual(ask(client, state="b").backend, "openai")
        self.assertEqual(len(first.calls), 1)
        clock.now += 31
        first.result = reply(good_choice())
        self.assertEqual(ask(client, state="c").backend, "jev")
        self.assertEqual(len(first.calls), 2)

    def test_no_typesafe_key_goes_straight_to_openai(self):
        client, first, second, _ = routed(reply(good_choice()))
        client._key = ""
        self.assertEqual(ask(client).backend, "openai")
        self.assertEqual(first.calls, [])

    def test_a_server_error_does_not_route(self):
        for result in ((500, b"{}"), (503, b"{}")):
            with self.subTest(result=result):
                client, _, second, _ = routed(result)
                out = ask(client)
                self.assertEqual((out.status, out.backend), (jev.ERROR, "jev"))
                self.assertEqual(second.calls, [])

    def test_both_refusing_leaves_the_heuristic_to_act(self):
        client, _, second, _ = routed((402, b"{}"), openai_result=(429, b"{}"))
        out = ask(client)
        self.assertIsNone(out.answers)
        self.assertEqual((out.backend, out.http), ("openai", 429))
        self.assertEqual(len(second.calls), 1)

    def test_the_paid_side_stops_at_its_daily_cap(self):
        env = {"JEV_OPENAI_DAILY_CAP_USD": "0.00005"}
        client, _, second, store = routed((402, b"{}"), env=env)
        first = ask(client)
        self.assertEqual(first.backend, "openai")
        self.assertEqual(len(store.rows), 1)
        out = ask(client, state="another sword")
        self.assertEqual((out.status, out.answers), (jev.CAPPED, None))
        self.assertEqual(out.detail, "daily_cap")
        self.assertEqual(len(second.calls), 1)

    def test_compare_names_the_backend_that_answered(self):
        rows = []

        async def sink(batch):
            rows.extend(batch)

        shadow = jev.Client(
            "k-shadow", transport=Transport(result=reply(good_choice()))
        )
        shadow.backend = jev.CLEF
        client, _, _, _ = routed((402, b"{}"), shadow=shadow, compare_sink=sink)

        async def run():
            await client.ask("item_disposition", "s", {"route": ROUTE})
            await client.drain_compare()

        asyncio.run(run())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["active_backend"], "openai")
        self.assertEqual(rows[0]["backend"], "clef")


class DailyCounters(unittest.TestCase):
    def setUp(self):
        self.saved = jev.DAILY
        self.clock = Clock(NOV)
        jev.DAILY = jev.Daily(self.clock)

    def tearDown(self):
        jev.DAILY = self.saved

    def test_calls_and_tokens_are_counted_per_backend_and_day(self):
        client, _, _, _ = routed((402, b"{}"))
        ask(client)
        ask(client, state="b")
        self.assertEqual(
            jev.DAILY.snapshot(),
            {"jev": {"calls": 1, "tokens": 0}, "openai": {"calls": 2, "tokens": 1200}},
        )
        self.assertIn(
            "jev: today backend=openai day=2026-11-17 calls=2 tokens=1200",
            jev.DAILY.lines(),
        )
        self.clock.now += 86400
        self.assertEqual(jev.DAILY.snapshot(), {})


class DailyCap(unittest.TestCase):
    def test_the_default_and_its_ceiling(self):
        self.assertEqual(jo.daily_cap_usd({}), jo.DAILY_CAP_USD)
        self.assertEqual(jo.daily_cap_usd({"JEV_OPENAI_DAILY_CAP_USD": "0.5"}), 0.5)
        self.assertEqual(
            jo.daily_cap_usd(
                {"JEV_OPENAI_DAILY_CAP_USD": "500", "JEV_OPENAI_CAP_USD": "20"}
            ),
            20.0,
        )
        with self.assertRaises(ValueError):
            jo.daily_cap_usd({"JEV_OPENAI_DAILY_CAP_USD": "lots"})

    def test_the_day_resets_at_utc_midnight_and_survives_a_restart(self):
        clock = Clock(NOV)
        store = jo.MemoryStore()
        flat = {"m": jo.Price(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)}
        s = jo.Spend(store, {}, clock, flat)
        s.record("k", "m", "answered", 1, jo.Usage(1_000_000, 0, 0))
        self.assertEqual(s.refusal("m").code, "daily_cap")
        # A new process on the same store sees the day's spend.
        fresh = jo.Spend(store, {}, clock, flat)
        self.assertEqual(fresh.day_usd(), 1.0)
        self.assertEqual(fresh.refusal("m").code, "daily_cap")
        clock.now += 86400
        self.assertIsNone(fresh.refusal("m"))
        self.assertEqual(fresh.day_usd(), 0.0)

    def test_calls_in_flight_hold_a_small_share_of_the_day(self):
        # Four holds of UNKNOWN_CALL_USD are a dollar, so the day counts each
        # call in flight at DAILY_HOLD_USD instead.
        s = jo.Spend(jo.MemoryStore(), {}, lambda: NOV)
        passed = [s.refusal("gpt-6-luna", hold=True) is None for _ in range(8)]
        self.assertEqual(passed, [True] * 8)

    def test_concurrent_asks_cannot_all_pass_just_under_the_day(self):
        # 0.97 spent of a 1.00 day leaves room for three holds of 0.01.
        clock = Clock(NOV)
        flat = {"m": jo.Price(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)}
        s = jo.Spend(jo.MemoryStore(), {}, clock, flat)
        s.record("k", "m", "answered", 1, jo.Usage(970_000, 0, 0))
        passed = [s.refusal("m", hold=True) is None for _ in range(10)]
        self.assertEqual(passed, [True] * 3 + [False] * 7)
        s.release()
        self.assertIsNone(s.refusal("m", hold=True))

    def test_the_sql_store_reads_the_day_from_its_month(self):
        seen = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, args):
                seen.append((sql, args))

            def fetchone(self):
                return {"usd": 0.42, "n": 7}

        class Conn(Cursor):
            def cursor(self):
                return Cursor()

        store = jo.SqlStore(Conn)
        self.assertEqual(store.load_day("2026-11-17"), (0.42, 7))
        self.assertEqual(seen, [(jo.DAY_SQL, ("2026-11",))])
        self.assertIn("UTC_DATE()", jo.DAY_SQL)


class BridgeWiring(unittest.TestCase):
    """bridge.py cannot be imported; its source is read and the judgment insert
    run over a fake connection, as tests/test_jev_items.py does."""

    @classmethod
    def setUpClass(cls):
        with open("bridge.py", encoding="utf-8") as handle:
            cls.BRIDGE = handle.read()

    def test_the_fallbacks_share_the_spend_table(self):
        self.assertIn(
            "for _client in (self._jev, self._jev.shadow, *self._jev.fallbacks):",
            self.BRIDGE,
        )
        self.assertIn("JEV_ROUTED = tuple(jev.route_names())", self.BRIDGE)
        self.assertIn('"openai" not in JEV_ROUTED', self.BRIDGE)

    def test_a_routed_judgment_row_names_the_backend_that_answered(self):
        import tradechoice

        insert = self.BRIDGE[self.BRIDGE.index("def _insert_jev_judgment(") :]
        insert = insert[: insert.index("\n\n\n")]
        executed = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, args):
                executed.append(args)

        class Conn(Cursor):
            def cursor(self):
                return Cursor()

        for routed_names, model, backend in (
            (("jev", "openai"), "gpt-6-luna", "openai"),
            (("jev", "openai"), "jev-1.14.0", "jev"),
            (("jev", "openai"), "", "jev"),
            ((), "gpt-6-luna", "jev"),
        ):
            with self.subTest(routed=routed_names, model=model):
                scope = {
                    "_connect": Conn,
                    "jev": jev,
                    "JEV_ACTIVE_BACKEND": "jev",
                    "JEV_ROUTED": routed_names,
                    "_jev_report_tick": lambda: None,
                }
                exec(insert, scope)  # noqa: S102 - bridge.py's own source
                executed.clear()
                scope["_insert_jev_judgment"](
                    tradechoice.Judgment(
                        subject="Grog",
                        heuristic="a",
                        heuristic_why="w",
                        mode="shadow",
                        status="answered",
                        jev="b",
                        confidence=0.5,
                        model=model,
                    )
                )
                self.assertEqual(executed[0][-1], backend)


if __name__ == "__main__":
    unittest.main()
