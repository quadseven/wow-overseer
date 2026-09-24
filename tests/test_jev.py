"""The Jev client never makes a caller wait, and never hands back an untyped answer (#95).

Every test drives the real `jev.Client` through a fake transport, so the
request it builds, the deadline, the in-flight limit, the cache and the typed
parsing are the shipped code. Nothing here reaches the network.
"""

import asyncio
import io
import json
import threading
import time
import unittest
import urllib.error
from unittest import mock

import jev

ROUTE = jev.choice(
    "What should happen to it?",
    {"keep": "keep it", "vendor": "sell it", "equip": "wear it"},
)


def reply(answers, model="jev-1.13.0", status=200):
    body = json.dumps({"model": model, "answers": answers, "usage": {}}).encode()
    return status, body


def good_choice(pick="equip"):
    probabilities = {"keep": 0.1, "vendor": 0.1, "equip": 0.8}
    return {
        "route": {
            "type": "choice",
            "choice": pick,
            "probabilities": probabilities,
            "confidence": 0.7,
        }
    }


class Transport:
    """Records every request and answers with a canned (status, body)."""

    def __init__(self, result=None, delay=0.0, error=None):
        self.result = result or reply(good_choice())
        self.delay = delay
        self.error = error
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, url, body, headers, timeout):
        with self.lock:
            self.calls.append((url, json.loads(body), dict(headers), timeout))
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


def ask(client, questions=None, state="a sword"):
    return asyncio.run(
        client.ask("item_disposition", state, questions or {"route": ROUTE})
    )


class RequestShapeTest(unittest.TestCase):
    def test_the_request_is_the_documented_shape(self):
        transport = Transport()
        client = jev.Client("k-test", transport=transport, timeout=2.5)
        ask(client, state={"item": "Destiny"})
        url, body, headers, timeout = transport.calls[0]
        self.assertEqual(url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(headers["Authorization"], "Bearer k-test")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["state"], {"item": "Destiny"})
        self.assertEqual(body["questions"], {"route": ROUTE})
        self.assertEqual(timeout, 2.5)

    def test_the_default_transport_posts_through_urllib(self):
        seen = {}

        class Response(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def urlopen(request, timeout):
            seen["method"] = request.get_method()
            seen["auth"] = request.get_header("Authorization")
            seen["timeout"] = timeout
            return Response(b"{}")

        with mock.patch.object(jev.urllib.request, "urlopen", urlopen):
            status, body = jev._urllib_post(
                "https://example.invalid", b"{}", {"Authorization": "Bearer x"}, 3.0
            )
        self.assertEqual((status, body), (200, b"{}"))
        self.assertEqual(seen, {"method": "POST", "auth": "Bearer x", "timeout": 3.0})

    def test_the_default_transport_returns_an_http_error_status(self):
        def urlopen(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 529, "Overloaded", {}, io.BytesIO(b"busy")
            )

        with mock.patch.object(jev.urllib.request, "urlopen", urlopen):
            status, _ = jev._urllib_post("https://example.invalid", b"{}", {}, 3.0)
        self.assertEqual(status, 529)


class FallbackTest(unittest.TestCase):
    """Every failure is answers=None, so the caller keeps its heuristic."""

    def test_no_key_asks_nothing_and_says_so_once(self):
        transport = Transport()
        client = jev.Client("", transport=transport)
        with self.assertLogs("wow-overseer.jev", "WARNING") as logs:
            first = ask(client)
            second = ask(client)
        self.assertEqual((first.status, first.answers), (jev.NO_KEY, None))
        self.assertEqual(second.status, jev.NO_KEY)
        self.assertEqual(transport.calls, [])
        self.assertEqual(len(logs.records), 1)

    def test_a_slow_api_is_abandoned_at_the_deadline(self):
        client = jev.Client("k", transport=Transport(delay=1.0), timeout=0.2)

        async def timed():
            started = time.monotonic()
            outcome = await client.ask("x", "s", {"route": ROUTE})
            return outcome, time.monotonic() - started

        outcome, waited = asyncio.run(timed())
        self.assertLess(waited, 0.6)
        self.assertEqual((outcome.status, outcome.answers), (jev.TIMEOUT, None))

    def test_an_abandoned_request_keeps_its_slot_until_its_thread_ends(self):
        transport = Transport(delay=0.6)
        client = jev.Client("k", transport=transport, timeout=0.1, concurrency=1)

        async def both():
            first = await client.ask("x", "s1", {"route": ROUTE})
            second = await client.ask("x", "s2", {"route": ROUTE})
            await asyncio.sleep(0.8)
            third = await client.ask("x", "s3", {"route": ROUTE})
            return first, second, third

        first, second, third = asyncio.run(both())
        self.assertEqual(first.status, jev.TIMEOUT)
        self.assertEqual(second.status, jev.BUSY)
        self.assertEqual(third.status, jev.TIMEOUT)
        self.assertEqual(len(transport.calls), 2)

    def test_a_queued_ask_takes_the_slot_when_it_frees(self):
        """#267: a background pass waits for a slot rather than meeting busy."""
        transport = Transport(delay=0.2)
        client = jev.Client("k", transport=transport, timeout=3.0, concurrency=1)

        async def both():
            first = asyncio.ensure_future(client.ask("x", "s1", {"route": ROUTE}))
            await asyncio.sleep(0.01)
            second = await client.ask("x", "s2", {"route": ROUTE}, wait=3.0)
            return await first, second

        first, second = asyncio.run(both())
        self.assertEqual((first.status, second.status), (jev.ANSWERED, jev.ANSWERED))
        self.assertEqual(len(transport.calls), 2)

    def test_a_queued_ask_still_answers_busy_past_its_wait(self):
        transport = Transport(delay=0.5)
        client = jev.Client("k", transport=transport, timeout=1.0, concurrency=1)

        async def both():
            first = asyncio.ensure_future(client.ask("x", "s1", {"route": ROUTE}))
            await asyncio.sleep(0.01)
            second = await client.ask("x", "s2", {"route": ROUTE}, wait=0.1)
            await first
            return second

        self.assertEqual(asyncio.run(both()).status, jev.BUSY)
        self.assertEqual(len(transport.calls), 1)

    def test_an_http_error_is_an_error(self):
        client = jev.Client("k", transport=Transport(result=(529, b"overloaded")))
        outcome = ask(client)
        self.assertEqual((outcome.status, outcome.answers), (jev.ERROR, None))
        self.assertIn("529", outcome.detail)

    def test_a_transport_exception_is_an_error(self):
        client = jev.Client("k", transport=Transport(error=OSError("refused")))
        self.assertEqual(ask(client).status, jev.ERROR)

    def test_a_body_that_is_not_json_is_invalid(self):
        client = jev.Client("k", transport=Transport(result=(200, b"<html>")))
        self.assertEqual(ask(client).status, jev.INVALID)

    def test_an_option_nobody_offered_is_invalid(self):
        answers = good_choice()
        answers["route"]["choice"] = "disenchant"
        client = jev.Client("k", transport=Transport(result=reply(answers)))
        self.assertEqual(ask(client).answers, None)

    def test_a_distribution_missing_an_option_is_invalid(self):
        answers = good_choice()
        del answers["route"]["probabilities"]["vendor"]
        client = jev.Client("k", transport=Transport(result=reply(answers)))
        self.assertEqual(ask(client).status, jev.INVALID)

    def test_a_missing_answer_voids_the_whole_request(self):
        questions = {"route": ROUTE, "sure": jev.noul("Is it an upgrade?")}
        client = jev.Client("k", transport=Transport())
        self.assertEqual(ask(client, questions).status, jev.INVALID)


class AnswerTest(unittest.TestCase):
    def test_a_good_choice_is_typed_and_logged_with_its_latency(self):
        client = jev.Client("k", transport=Transport())
        with self.assertLogs("wow-overseer.jev", "INFO") as logs:
            outcome = ask(client)
        self.assertEqual(outcome.status, jev.ANSWERED)
        self.assertEqual(outcome.model, "jev-1.13.0")
        self.assertEqual(outcome.answers["route"].choice, "equip")
        self.assertAlmostEqual(outcome.answers["route"].confidence, 0.7)
        self.assertRegex(logs.output[-1], r"status=answered latency_ms=\d+")

    def test_an_identical_question_is_answered_from_the_cache(self):
        transport = Transport()
        client = jev.Client("k", transport=transport)
        first = ask(client)
        second = ask(client)
        third = ask(client, state="another sword")
        self.assertEqual(first.status, jev.ANSWERED)
        self.assertEqual(second.status, jev.CACHED)
        self.assertEqual(second.answers, first.answers)
        self.assertEqual(third.status, jev.ANSWERED)
        self.assertEqual(len(transport.calls), 2)

    def test_the_cache_is_bounded(self):
        transport = Transport()
        client = jev.Client("k", transport=transport, cache_size=1)
        ask(client, state="a")
        ask(client, state="b")
        ask(client, state="a")
        self.assertEqual(len(transport.calls), 3)

    def test_a_failure_is_not_cached(self):
        transport = Transport(result=(529, b""))
        client = jev.Client("k", transport=transport)
        ask(client)
        ask(client)
        self.assertEqual(len(transport.calls), 2)

    def test_score_and_noul_are_parsed_and_bounded(self):
        levels = jev.score("How much?", ["none", "some", "a lot"])
        good = {
            "type": "score",
            "score": 1.2,
            "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3},
            "confidence": 0.5,
        }
        self.assertEqual(jev.parse(levels, good).score, 1.2)
        self.assertIsNone(jev.parse(levels, dict(good, score=3.5)))
        yes = jev.noul("Is it?")
        self.assertEqual(jev.parse(yes, {"type": "noul", "noul": 0.9}).noul, 0.9)
        self.assertIsNone(jev.parse(yes, {"type": "noul", "noul": 1.5}))
        self.assertIsNone(jev.parse(yes, {"type": "noul", "noul": "yes"}))
        self.assertIsNone(jev.parse(yes, {"type": "choice", "noul": 0.9}))


class ModeTest(unittest.TestCase):
    def test_the_default_is_shadow(self):
        self.assertEqual(jev.mode("item_disposition", {}), jev.SHADOW)

    def test_each_kind_has_its_own_switch(self):
        env = {"JEV_MODE_ITEM_DISPOSITION": "off", "JEV_MODE_WEAPON_CHOICE": "Act"}
        self.assertEqual(jev.mode("item_disposition", env), jev.OFF)
        self.assertEqual(jev.mode("weapon_choice", env), jev.ACT)

    def test_an_unreadable_value_is_shadow_and_says_so(self):
        with self.assertLogs("wow-overseer.jev", "WARNING"):
            self.assertEqual(
                jev.mode("item_disposition", {"JEV_MODE_ITEM_DISPOSITION": "yes"}),
                jev.SHADOW,
            )

    def test_act_without_an_act_path_runs_shadow_and_says_so(self):
        env = {"JEV_MODE_ITEM_DISPOSITION": "act"}
        with self.assertLogs("wow-overseer.jev", "WARNING") as logs:
            chosen = jev.effective_mode("item_disposition", False, env)
        self.assertEqual(chosen, jev.SHADOW)
        self.assertIn("no act path", logs.output[0])
        self.assertEqual(jev.effective_mode("item_disposition", True, env), jev.ACT)

    def test_only_an_https_url_is_accepted(self):
        for url in ("file:///etc/passwd", "http://api.typesafe.ai/v1/systemone"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                jev.Client("k", url=url)

    def test_from_env_reads_the_key_and_the_knobs(self):
        client = jev.Client.from_env(
            {
                "TYPESAFE_API_KEY": "k",
                "JEV_TIMEOUT_SECONDS": "1.5",
                "JEV_CONCURRENCY": "2",
                "JEV_MODEL": "jev-1.13.0",
            }
        )
        self.assertTrue(client.configured)
        self.assertEqual((client.timeout, client.concurrency), (1.5, 2))
        self.assertEqual(client.model, "jev-1.13.0")
        self.assertFalse(jev.Client.from_env({}).configured)


if __name__ == "__main__":
    unittest.main()
