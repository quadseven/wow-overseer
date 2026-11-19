"""Jev on a small OpenAI model (#2899): the spend ledger, the bar, the fallbacks.

The ledger tests are the station's spend-ledger tests (its bus/openai_budget.py
suite), ported to this module's store. The client tests drive the real
`jev.Client` through a fake transport; nothing reaches the network.
"""

import asyncio
import calendar
import json
import logging
import unittest

import jev
import jev_openai as jo
import jevview
from test_jev import Transport

NOV = calendar.timegm((2026, 11, 15, 12, 0, 0))
DEC = calendar.timegm((2026, 12, 1, 0, 0, 1))
# One dollar per million tokens of each kind keeps the arithmetic plain.
FLAT = {"flat-model": jo.Price(1.0, 0.5, 1.0, 4.0, 2.0, 8.0)}
ROUTE = jev.choice("What now?", {"keep": "keep it", "vendor": "sell it"})


class Clock:
    def __init__(self, now=NOV):
        self.now = now

    def __call__(self):
        return self.now


def spend(clock=None, env=None, store=None):
    # The daily cap is raised to the monthly one unless a test sets it, so the
    # monthly-cap tests can spend a month in one test day.
    return jo.Spend(
        store, env or {"JEV_OPENAI_DAILY_CAP_USD": "90"}, clock or Clock(), FLAT
    )


def run(coro):
    return asyncio.run(coro)


class Pricing(unittest.TestCase):
    def test_the_table_names_its_source_and_the_day_it_was_read(self):
        self.assertTrue(jo.PRICES_SOURCE.startswith("https://developers.openai.com/"))
        self.assertRegex(jo.PRICES_READ, r"^\d{4}-\d{2}-\d{2}$")
        nano, luna = jo.PRICES["gpt-5-nano"], jo.PRICES["gpt-6-luna"]
        self.assertEqual((nano.input, nano.cached, nano.output), (0.05, 0.005, 0.40))
        self.assertEqual((luna.input, luna.cached, luna.output), (0.10, 0.01, 0.50))
        self.assertEqual(jo.DEFAULT_MODEL, "gpt-6-luna")

    def test_cost_from_uncached_cached_and_output_tokens(self):
        usage = jo.Usage(100_000, 100_000, 500_000)
        self.assertAlmostEqual(jo.cost("flat-model", usage, FLAT), 0.1 + 0.05 + 0.5)

    def test_a_prompt_past_the_long_context_line_pays_the_long_rates(self):
        usage = jo.Usage(jo.LONG_CONTEXT_OVER, 1, 1_000_000)
        expected = (jo.LONG_CONTEXT_OVER * 4.0 + 2.0) / 1e6 + 8.0
        self.assertAlmostEqual(jo.cost("flat-model", usage, FLAT), expected)

    def test_an_unpriced_model_has_no_cost(self):
        with self.assertRaises(jo.Unpriced):
            jo.cost("gpt-6-astra", jo.Usage(1, 0, 1))

    def test_chat_style_usage_counts_cached_prompt_tokens_apart(self):
        usage = jo.Usage.from_openai(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 50,
                "prompt_tokens_details": {"cached_tokens": 400},
            }
        )
        self.assertEqual(usage, jo.Usage(600, 400, 50))

    def test_responses_style_usage_reads_the_same(self):
        usage = jo.Usage.from_openai(
            {
                "input_tokens": 10,
                "output_tokens": 7,
                "input_tokens_details": {"cached_tokens": 3},
            }
        )
        self.assertEqual(usage, jo.Usage(7, 3, 7))

    def test_usage_with_no_token_counts_is_unknown(self):
        for bad in (
            None,
            {},
            {"prompt_tokens": "many"},
            {"prompt_tokens": -1, "completion_tokens": 1},
        ):
            with self.assertRaises(jo.UsageUnknown):
                jo.Usage.from_openai(bad)


class Ledger(unittest.TestCase):
    def test_each_call_is_one_stored_row_with_its_tokens_and_cost(self):
        store = jo.MemoryStore()
        row = spend(store=store).record(
            "loot_council", "flat-model", "answered", 420, jo.Usage(0, 0, 2_000_000)
        )
        self.assertEqual(store.rows, [row])
        self.assertEqual(row["cost_usd"], 2.0)
        self.assertEqual((row["month"], row["output_tokens"]), ("2026-11", 2_000_000))

    def test_the_cap_skips_calls_within_the_margin_with_a_reason(self):
        s = spend()
        s.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 88_000_000))
        self.assertIsNone(s.refusal("flat-model"))
        s.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 1_000_000))
        why = s.refusal("flat-model")
        self.assertEqual(why.code, "cap")
        self.assertIn("89.00", why.text)
        self.assertIn("2026-11", why.text)
        self.assertIn("cap $90.00", why.text)

    def test_concurrent_asks_cannot_all_pass_a_cap_only_some_fit_under(self):
        s = spend()
        # $88.50 spent; cap 90 and margin 1 leave room for exactly two holds
        # of UNKNOWN_CALL_USD (0.25) before usd + holds + margin reaches the cap.
        s.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 88_500_000))
        passed = [s.refusal("flat-model", hold=True) is None for _ in range(10)]
        self.assertEqual(passed.count(True), 2)
        self.assertEqual(passed[:2], [True, True])

    def test_recording_or_releasing_a_call_gives_its_hold_back(self):
        s = spend()
        s.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 88_500_000))
        self.assertIsNone(s.refusal("flat-model", hold=True))
        self.assertIsNone(s.refusal("flat-model", hold=True))
        self.assertIsNotNone(s.refusal("flat-model", hold=True))
        s.release()
        self.assertIsNone(s.refusal("flat-model", hold=True))
        s.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 1))
        self.assertIsNone(s.refusal("flat-model", hold=True))

    def test_a_leaked_hold_expires(self):
        clock = Clock()
        s = spend(clock)
        s.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 88_500_000))
        for _ in range(2):
            self.assertIsNone(s.refusal("flat-model", hold=True))
        self.assertIsNotNone(s.refusal("flat-model"))
        clock.now += jo.HOLD_SECONDS + 1
        self.assertIsNone(s.refusal("flat-model"))

    def test_the_daily_cap_refuses_persists_and_resets_at_midnight_utc(self):
        store, clock = jo.MemoryStore(), Clock()
        env = {"JEV_OPENAI_DAILY_CAP_USD": "1"}
        first = spend(clock, env=env, store=store)
        self.assertIsNone(first.refusal("flat-model"))
        first.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 1_000_000))
        self.assertEqual(first.refusal("flat-model").code, "daily_cap")
        # A new Spend on the same store still sees the day's spend.
        again = spend(clock, env=env, store=store)
        self.assertEqual(again.refusal("flat-model").code, "daily_cap")
        # 00:00 UTC the next day lifts it.
        clock.now = calendar.timegm((2026, 11, 16, 0, 0, 0))
        self.assertIsNone(again.refusal("flat-model"))

    def test_the_month_rolls_over_and_the_cap_lifts(self):
        clock = Clock()
        s = spend(clock)
        s.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 95_000_000))
        self.assertIsNotNone(s.refusal("flat-model"))
        clock.now = DEC
        self.assertIsNone(s.refusal("flat-model"))
        self.assertEqual(s.month_usd(), 0.0)

    def test_a_configured_cap_may_lower_the_ceiling_never_raise_it(self):
        low = spend(env={"JEV_OPENAI_CAP_USD": "40"})
        low.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 50_000_000))
        self.assertIsNotNone(low.refusal("flat-model"))
        high = spend(env={"JEV_OPENAI_CAP_USD": "500"})
        high.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 95_000_000))
        self.assertIsNotNone(high.refusal("flat-model"))
        self.assertEqual(jo.cap_usd({"JEV_OPENAI_CAP_USD": "500"}), jo.CAP_USD)
        self.assertLess(jo.CAP_USD, 90.01)

    def test_a_cap_that_does_not_parse_refuses_every_call(self):
        why = spend(env={"JEV_OPENAI_CAP_USD": "lots"}).refusal("flat-model")
        self.assertEqual(why.code, "cap_unreadable")

    def test_an_unpriced_model_is_refused(self):
        self.assertEqual(spend().refusal("gpt-6-astra").code, "unpriced")

    def test_a_call_of_unknown_usage_is_charged_never_zero(self):
        row = spend().record("k", "flat-model", "answered", 1, None)
        self.assertEqual(row["cost_usd"], jo.UNKNOWN_CALL_USD)
        self.assertEqual(row["estimated"], 1)

    def test_a_call_that_cost_nothing_is_recorded_free(self):
        row = spend().record("k", "flat-model", "timeout", 3000, None, charged=False)
        self.assertEqual(row["cost_usd"], 0.0)

    def test_a_restart_does_not_reset_the_month(self):
        store = jo.MemoryStore()
        first = spend(store=store)
        first.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 89_500_000))
        restarted = spend(store=store)
        self.assertEqual(restarted.refusal("flat-model").code, "cap")
        self.assertAlmostEqual(restarted.month_usd(), 89.5)

    def test_two_clients_on_one_store_see_each_others_spend_after_a_refresh(self):
        store, clock = jo.MemoryStore(), Clock()
        a, b = spend(clock, store=store), spend(clock, store=store)
        self.assertIsNone(b.refusal("flat-model"))
        a.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 95_000_000))
        clock.now += jo.REFRESH_SECONDS + 1
        self.assertEqual(b.refusal("flat-model").code, "cap")

    def test_an_unreadable_store_never_loosens_the_cap(self):
        class Broken(jo.MemoryStore):
            def load(self, month):
                raise OSError("down")

            def append(self, row):
                raise OSError("down")

        s = spend(store=Broken())
        with self.assertLogs("wow-overseer.jev", "ERROR"):
            s.record("k", "flat-model", "answered", 1, jo.Usage(0, 0, 95_000_000))
            self.assertEqual(s.refusal("flat-model").code, "cap")


class ReasonText(unittest.TestCase):
    def test_nothing_that_renders_survives(self):
        hostile = (
            "ok <!-- hidden --> @someone see #123 `code` [link](x) {y} "
            "line\nbreak <script>"
        )
        out = jo.clean_reason(hostile)
        for bad in ("<!--", "-->", "@", "#", "`", "[", "]", "(", ")", "<", ">", "\n"):
            self.assertNotIn(bad, out)
        self.assertRegex(out, r"^[A-Za-z0-9 .,:\-]*$")

    def test_a_comment_marker_cannot_be_rebuilt(self):
        self.assertNotIn("--", jo.clean_reason("<!---- x ---->"))

    def test_ordinary_text_comes_back_unchanged(self):
        for plain in (
            "low confidence: 0.42, try again",
            "rate-limited after 3 retries.",
            "a | b",
        ):
            want = plain.replace("|", "").replace("  ", " ")
            self.assertEqual(jo.clean_reason(plain), want)
        self.assertEqual(jo.clean_reason("keep this sentence"), "keep this sentence")

    def test_it_is_capped(self):
        self.assertEqual(len(jo.clean_reason("a" * 1000)), jo.REASON_LIMIT)
        self.assertEqual(jo.clean_reason(None), "")


class PagedCursor:
    """Serves the spend table a page at a time the way the keyset query does."""

    def __init__(self, total):
        self.rows = [
            {"id": i, "kind": "k", "status": "answered", "latency_ms": 1, "cost_usd": 0}
            for i in range(total, 0, -1)
        ]
        self._out = []

    def execute(self, sql, args):
        _days, before, page = args
        self._out = [r for r in self.rows if r["id"] < before][:page]

    def fetchall(self):
        return self._out


class EveryCallInTheWindowIsRead(unittest.TestCase):
    def test_a_window_larger_than_a_page_is_read_whole(self):
        cur = PagedCursor(2 * jo.CALLS_PAGE + 7)
        self.assertEqual(len(jo.fetch_calls(cur)), 2 * jo.CALLS_PAGE + 7)

    def test_an_exact_page_multiple_ends_cleanly(self):
        self.assertEqual(len(jo.fetch_calls(PagedCursor(jo.CALLS_PAGE))), jo.CALLS_PAGE)

    def test_an_empty_window_is_empty(self):
        self.assertEqual(jo.fetch_calls(PagedCursor(0)), [])


def calls(kind, n, status="answered", ms=400, usd=0.0002):
    return [
        {"kind": kind, "status": status, "latency_ms": ms, "cost_usd": usd}
        for _ in range(n)
    ]


class Report(unittest.TestCase):
    def test_the_report_has_every_measure_per_kind(self):
        rows = calls("loot_council", 190, ms=300) + calls(
            "loot_council", 10, "error", 100
        )
        rep = jo.report(rows, {"loot_council": (90, 100)})["loot_council"]
        self.assertEqual(rep["calls"], 200)
        self.assertAlmostEqual(rep["answer_rate"], 0.95)
        self.assertEqual((rep["p50_ms"], rep["p95_ms"]), (300, 300))
        self.assertAlmostEqual(rep["agreement"], 0.9)
        self.assertAlmostEqual(rep["cost_per_1000"], 0.2)
        self.assertEqual(rep["misses"], [])

    def test_each_measure_can_miss_the_bar_on_its_own(self):
        agree = {"k": (90, 100)}
        cases = {
            "answer_rate": calls("k", 180) + calls("k", 20, "timeout", 100),
            "p95_ms": calls("k", 180, ms=300) + calls("k", 20, ms=3000),
            "p50_ms": calls("k", 200, ms=1600),
            "cost_per_1000": calls("k", 200, usd=0.001),
            "calls": calls("k", 199),
        }
        for measure, rows in cases.items():
            miss = jo.report(rows, agree)["k"]["misses"]
            self.assertTrue(miss and miss[0].startswith(measure), (measure, miss))

    def test_agreement_below_the_bar_misses_unless_a_reviewed_sample_stands(self):
        rows = calls("k", 200)
        low = {"k": (50, 100)}
        self.assertTrue(jo.report(rows, low)["k"]["misses"])
        env = {"JEV_OPENAI_REVIEWED_K": "1"}
        self.assertEqual(jo.report(rows, low, env=env)["k"]["misses"], [])

    def test_too_few_compared_answers_miss(self):
        miss = jo.report(calls("k", 200), {"k": (10, 10)})["k"]["misses"]
        self.assertTrue(miss[0].startswith("compared"))

    def test_only_calls_that_reached_the_provider_count(self):
        rows = calls("k", 5) + calls("k", 50, "capped") + calls("k", 50, "paused")
        self.assertEqual(jo.report(rows, {})["k"]["calls"], 5)

    def test_the_summary_line_reads_all_measures(self):
        rep = jo.report(calls("k", 200), {"k": (90, 100)})["k"]
        line = jo.summary_line("k", rep)
        for part in (
            "kind=k",
            "answer_rate=1.000",
            "p50_ms=400",
            "p95_ms=400",
            "agreement=0.900",
            "cost_per_1000=0.200",
            "bar=clears",
        ):
            self.assertIn(part, line)

    def test_the_bar_numbers_are_the_ticket_numbers(self):
        b = jo.BAR
        self.assertEqual(
            (b.min_calls, b.answer_rate, b.p95_ms, b.p50_ms, b.agreement),
            (200, 0.95, 3000, 1500, 0.80),
        )
        self.assertEqual(b.cost_per_1000, 0.50)


class Gate(unittest.TestCase):
    def tearDown(self):
        jev.set_act_gate(None)

    def test_act_runs_as_compare_until_the_kind_clears_the_bar(self):
        gate = jo.ActGate()
        jev.set_act_gate(gate)
        env = {"JEV_MODE_LOOT_COUNCIL": "act", "JEV_MODE_ITEM_KEEP": "act"}
        with self.assertLogs("wow-overseer.jev", "WARNING"):
            self.assertEqual(jev.mode("loot_council", env), jev.SHADOW)
        rep = jo.report(calls("loot_council", 200), {"loot_council": (90, 100)})
        gate.update(rep)
        self.assertEqual(jev.mode("loot_council", env), jev.ACT)
        self.assertEqual(jev.mode("item_keep", env), jev.SHADOW)

    def test_compare_is_shadow_and_the_default_is_compare(self):
        self.assertEqual(jev.mode("loot_council", {}), jev.SHADOW)
        self.assertEqual(
            jev.mode("loot_council", {"JEV_MODE_LOOT_COUNCIL": "compare"}), jev.SHADOW
        )

    def test_off_stays_off_and_no_gate_leaves_act_alone(self):
        jev.set_act_gate(jo.ActGate())
        self.assertEqual(jev.mode("k", {"JEV_MODE_K": "off"}), jev.OFF)
        jev.set_act_gate(None)
        self.assertEqual(jev.mode("k", {"JEV_MODE_K": "act"}), jev.ACT)

    def test_a_restart_starts_every_kind_gated(self):
        self.assertFalse(jo.ActGate()("loot_council"))


class Reporting(unittest.TestCase):
    def test_the_report_logs_hourly_and_feeds_the_gate(self):
        now = [0.0]
        rep = jo.Reporter(jo.ActGate(), clock=lambda: now[0])
        self.assertTrue(rep.due())
        self.assertFalse(rep.due())
        now[0] += 3601
        self.assertTrue(rep.due())
        report = jo.report(calls("k", 200), {"k": (90, 100)})
        with self.assertLogs("wow-overseer.jev", "INFO") as logs:
            lines = rep.publish(report)
        self.assertEqual(len(lines), 1)
        self.assertIn("openai report kind=k", logs.output[0])
        self.assertTrue(rep.gate("k"))

    def test_the_card_shows_the_report_lines(self):
        lines = ["jev: openai report kind=k calls=1"]
        self.assertEqual(jevview.view([], openai=lines)["openai"], lines)
        self.assertEqual(jevview.view([])["openai"], [])


class Selection(unittest.TestCase):
    def test_the_provider_picks_the_openai_backend_over_jev_backend(self):
        env = {"JEV_PROVIDER": "openai", "JEV_BACKEND": "clef"}
        self.assertEqual(jev.backend_name(env), "openai")
        self.assertEqual(jev.backend_name({"JEV_BACKEND": "clef"}), "clef")
        with self.assertLogs("wow-overseer.jev", "WARNING"):
            self.assertEqual(jev.backend_name({"JEV_PROVIDER": "nope"}), "jev")

    def test_the_key_comes_from_the_environment_and_the_model_has_a_default(self):
        client = jev.Client.from_env(
            {"JEV_PROVIDER": "openai", "OPENAI_API_KEY": "k-test"}
        )
        self.assertEqual(client.backend.name, "openai")
        self.assertTrue(client.configured)
        self.assertEqual(client.model, "gpt-6-luna")
        self.assertIsNotNone(client.spend)
        self.assertEqual(client.backend.effort, "")

    def test_the_defaults_send_only_what_the_decisions_endpoint_accepts(self):
        # POST /v1/decisions answers 404 model_not_found to any model but
        # those in DECISIONS_MODELS, and 400 unknown_parameter to any body
        # key but model, input and questions (live probes, 2026-11-17).
        for env in (
            {"JEV_PROVIDER": "openai", "OPENAI_API_KEY": "k-test"},
            {"JEV_BACKEND": "openai", "OPENAI_API_KEY": "k-test"},
        ):
            transport = Transport(result=decision(usage=USAGE))
            client = jev.Client.from_env(env, transport=transport)
            run(client.ask("loot_council", "s", {"r": ROUTE}))
            [(url, body)] = [(c[0], c[1]) for c in transport.calls]
            self.assertTrue(url.endswith("/v1/decisions"), url)
            self.assertIn(body["model"], jo.DECISIONS_MODELS)
            self.assertEqual(set(body), {"model", "input", "questions"})
        self.assertIn(jo.DEFAULT_MODEL, jo.DECISIONS_MODELS)
        self.assertIn(jo.DEFAULT_MODEL, jo.PRICES)
        self.assertEqual(jo.DEFAULT_REASONING, "")

    def test_the_model_and_effort_and_per_kind_models_are_configurable(self):
        env = {
            "JEV_PROVIDER": "openai",
            "OPENAI_API_KEY": "k",
            "JEV_OPENAI_MODEL": "gpt-6-luna",
            "JEV_OPENAI_MODEL_LOOT_COUNCIL": "gpt-5-nano",
            "JEV_OPENAI_REASONING": "minimal",
        }
        client = jev.Client.from_env(env)
        self.assertEqual(client.model, "gpt-6-luna")
        self.assertEqual(client.models, {"loot_council": "gpt-5-nano"})
        self.assertEqual(client.backend.effort, "minimal")

    def test_with_no_key_the_provider_is_disabled_and_says_so_once(self):
        client = jev.Client.from_env({"JEV_PROVIDER": "openai"})
        self.assertFalse(client.configured)
        transport = Transport()
        client._transport = transport
        with self.assertLogs("wow-overseer.jev", "WARNING") as logs:
            first = run(client.ask("k", "s", {"r": ROUTE}))
            second = run(client.ask("k", "s", {"r": ROUTE}))
        self.assertEqual((first.status, second.status), (jev.NO_KEY, jev.NO_KEY))
        self.assertIsNone(first.answers)
        self.assertEqual(transport.calls, [])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("OPENAI_API_KEY", logs.output[0])
        self.assertNotIn("TYPESAFE", logs.output[0])


def decision(pick="keep", usage=None):
    body = {
        "model": "gpt-5-nano",
        "answers": [
            {
                "type": "choice",
                "name": "r",
                "choice": pick,
                "probabilities": [
                    {"value": "keep", "probability": 0.8},
                    {"value": "vendor", "probability": 0.2},
                ],
                "confidence": 0.8,
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return 200, json.dumps(body).encode()


USAGE = {"input_tokens": 1000, "output_tokens": 100}


def make(transport, **kw):
    store = kw.pop("store", None) or jo.MemoryStore()
    client = jev.Client(
        "k-test",
        backend=jev.OpenAIBackend("low"),
        url="https://example.com/v1/decisions",
        model="gpt-5-nano",
        transport=transport,
        spend=jo.Spend(store, kw.pop("env", {})),
        **kw,
    )
    return client, store


def ask(client, kind="loot_council", state="s"):
    return run(client.ask(kind, state, {"r": ROUTE}))


class Fallbacks(unittest.TestCase):
    def test_an_answer_is_priced_from_the_usage_it_returns(self):
        client, store = make(Transport(result=decision(usage=USAGE)))
        out = ask(client)
        self.assertEqual(out.status, jev.ANSWERED)
        [row] = store.rows
        self.assertEqual((row["input_tokens"], row["output_tokens"]), (1000, 100))
        self.assertAlmostEqual(row["cost_usd"], 1000 * 0.05 / 1e6 + 100 * 0.40 / 1e6)
        self.assertEqual(
            (row["kind"], row["model"], row["status"]),
            ("loot_council", "gpt-5-nano", "answered"),
        )

    def test_the_request_carries_the_model_and_a_low_reasoning_effort(self):
        transport = Transport(result=decision(usage=USAGE))
        client, _ = make(transport)
        ask(client)
        body = transport.calls[0][1]
        self.assertEqual(body["model"], "gpt-5-nano")
        self.assertEqual(body["reasoning"], {"effort": "low"})

    def test_a_response_with_no_usage_is_charged_the_unknown_price(self):
        client, store = make(Transport(result=decision()))
        ask(client)
        self.assertEqual(store.rows[0]["cost_usd"], jo.UNKNOWN_CALL_USD)

    def test_402_429_and_a_server_error_keep_the_heuristic_and_cost_nothing(self):
        for code in (402, 429, 500):
            body = json.dumps(
                {"error": {"message": "slow <!-- down --> @x #9"}}
            ).encode()
            client, store = make(Transport(result=(code, body)))
            with self.assertLogs("wow-overseer.jev", "WARNING") as logs:
                out = ask(client)
            self.assertEqual(out.status, jev.ERROR)
            self.assertIsNone(out.answers)
            self.assertIn("http %d" % code, out.detail)
            for bad in ("<!--", "@", "#"):
                self.assertNotIn(bad, out.detail)
                self.assertNotIn(bad, " ".join(logs.output))
            self.assertEqual(store.rows[0]["cost_usd"], 0.0)

    def test_a_timeout_keeps_the_heuristic(self):
        client, store = make(
            Transport(result=decision(usage=USAGE), delay=0.5), timeout=0.1
        )
        out = ask(client)
        self.assertEqual(out.status, jev.TIMEOUT)
        self.assertIsNone(out.answers)
        self.assertEqual(store.rows[0]["status"], "timeout")

    def test_the_default_deadline_is_three_seconds(self):
        self.assertEqual(jev.TIMEOUT_SECONDS, 3.0)

    def test_an_answer_that_does_not_parse_keeps_the_heuristic_and_is_still_charged(
        self,
    ):
        client, store = make(Transport(result=decision(pick="nobody", usage=USAGE)))
        out = ask(client)
        self.assertEqual(out.status, jev.INVALID)
        self.assertIsNone(out.answers)
        self.assertGreater(store.rows[0]["cost_usd"], 0)

    def test_low_confidence_keeps_the_heuristic(self):
        policy = jev.Policy("loot_council", jev.ACT, 0.9)
        self.assertEqual(policy.acted("vendor", "keep", 0.8), jev.HEURISTIC)
        self.assertEqual(policy.acted("vendor", "keep", 0.95), jev.JEV)


class SpendCap(unittest.TestCase):
    def test_calls_stop_at_the_cap_with_the_reason_logged_once(self):
        store = jo.MemoryStore()
        store.append(
            {"month": jo.month_of(__import__("time").time()), "cost_usd": 89.5}
        )
        transport = Transport(result=decision(usage=USAGE))
        client, _ = make(transport, store=store)
        with self.assertLogs("wow-overseer.jev", "WARNING") as logs:
            first = ask(client, state="a")
            second = ask(client, state="b")
        self.assertEqual((first.status, second.status), (jev.CAPPED, jev.CAPPED))
        self.assertIsNone(first.answers)
        self.assertEqual(transport.calls, [])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("spend cap reached", logs.output[0])

    def test_an_unpriced_model_is_never_asked(self):
        transport = Transport(result=decision(usage=USAGE))
        client, _ = make(transport, models={"loot_council": "gpt-6-astra"})
        with self.assertLogs("wow-overseer.jev", "WARNING"):
            out = ask(client)
        self.assertEqual(out.status, jev.CAPPED)
        self.assertEqual(transport.calls, [])

    def test_a_kind_can_ask_a_dearer_model_than_the_rest(self):
        transport = Transport(result=decision(usage=USAGE))
        client, store = make(transport, models={"loot_council": "gpt-6-luna"})
        ask(client, "loot_council")
        ask(client, "item_keep")
        self.assertEqual(
            [c[1]["model"] for c in transport.calls], ["gpt-6-luna", "gpt-5-nano"]
        )
        self.assertEqual([r["model"] for r in store.rows], ["gpt-6-luna", "gpt-5-nano"])


class Cache(unittest.TestCase):
    def test_a_repeat_is_free_inside_the_ttl_and_asked_again_after_it(self):
        now = [100.0]
        transport = Transport(result=decision(usage=USAGE))
        client, store = make(transport, clock=lambda: now[0], cache_ttl=60)
        self.assertEqual(ask(client).status, jev.ANSWERED)
        self.assertEqual(ask(client).status, jev.CACHED)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(store.rows), 1)
        now[0] += 61
        self.assertEqual(ask(client).status, jev.ANSWERED)
        self.assertEqual(len(transport.calls), 2)

    def test_inputs_that_differ_only_in_spacing_are_one_question(self):
        transport = Transport(result=decision(usage=USAGE))
        client, _ = make(transport)
        ask(client, state={"item": "Sword  of  Truth"})
        self.assertEqual(
            ask(client, state={"item": " Sword of Truth "}).status, jev.CACHED
        )

    def test_another_kind_or_model_is_another_question(self):
        transport = Transport(result=decision(usage=USAGE))
        client, _ = make(transport)
        ask(client, "a")
        self.assertEqual(ask(client, "b").status, jev.ANSWERED)

    def test_a_cache_hit_is_served_even_at_the_cap(self):
        store = jo.MemoryStore()
        client, _ = make(Transport(result=decision(usage=USAGE)), store=store)
        ask(client)
        store.append(
            {"month": jo.month_of(__import__("time").time()), "cost_usd": 95.0}
        )
        client.spend._read_at = float("-inf")
        self.assertEqual(ask(client).status, jev.CACHED)


class SourceShape(unittest.TestCase):
    """The bridge and the Decree call what this module ships (no inert module)."""

    def read(self, name):
        with open(name, encoding="utf-8") as handle:
            return handle.read()

    def test_the_bridge_wires_the_store_the_gate_and_the_report(self):
        text = self.read("bridge.py")
        for needle in (
            "jev_openai.TABLE_SQL",
            "jev_openai.SqlStore(",
            "jev.set_act_gate(",
            "jev_openai.fetch_report(",
            "_jev_report_tick()",
        ):
            self.assertIn(needle, text)

    def test_the_decree_reads_the_report(self):
        text = self.read("map_server.py")
        self.assertIn("jev_openai.fetch_report(", text)
        self.assertIn("openai=", text)


if __name__ == "__main__":
    logging.disable(logging.NOTSET)
    unittest.main()
