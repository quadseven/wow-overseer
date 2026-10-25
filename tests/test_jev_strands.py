"""The strands backend behind jev.Client.ask (#822).

The Strands Decider 2B runs behind a localhost wrapper that speaks the Jev
request and response body. These drive the real client: a fake HTTP server on
127.0.0.1 for the wire, a fake transport for the request shape. Nothing here
leaves the machine.
"""

import asyncio
import http.server
import json
import socket
import threading
import unittest

import campaignplan
import jev
import jev_choices
import jevview
from test_jev import Transport, ROUTE, good_choice, reply
import test_jev_choices


def run(coro):
    return asyncio.run(coro)


class FakeService:
    """A localhost HTTP server answering like the Strands wrapper."""

    def __init__(self, answers=None, service_ms=None, status=200):
        self.requests = []
        outer = self
        body = {"model": "strands-decider-2b", "answers": answers or good_choice()}
        if service_ms is not None:
            body["latency_ms"] = service_ms

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                outer.requests.append(
                    (self.path, dict(self.headers), json.loads(self.rfile.read(length)))
                )
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/" % self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def dead_url():
    """A loopback URL nothing is listening on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return "http://127.0.0.1:%d/" % sock.getsockname()[1]


class Selection(unittest.TestCase):
    def test_strands_is_registered_for_both_variables(self):
        self.assertIn("strands", jev.BACKENDS)
        self.assertEqual(jev.backend_name({"JEV_BACKEND": "strands"}), "strands")
        self.assertEqual(
            jev.backend_name({"JEV_COMPARE_BACKEND": "strands"}, "JEV_COMPARE_BACKEND"),
            "strands",
        )
        client = jev.Client.from_env({"JEV_COMPARE_BACKEND": "strands"})
        self.assertEqual(client.shadow.backend.name, "strands")

    def test_the_defaults_are_the_local_service(self):
        client = jev.Client.from_env({"JEV_BACKEND": "strands"})
        self.assertEqual(client.url, "http://127.0.0.1:8790/")
        self.assertEqual(client.model, "strands-decider-2b")
        self.assertTrue(client.configured)

    def test_the_url_and_model_come_from_the_environment(self):
        client = jev.Client.from_env(
            {
                "JEV_BACKEND": "strands",
                "STRANDS_URL": "http://127.0.0.1:9000/ask",
                "STRANDS_MODEL": "strands-x",
            }
        )
        self.assertEqual(
            (client.url, client.model), ("http://127.0.0.1:9000/ask", "strands-x")
        )

    def test_plain_http_is_only_for_a_local_backend_on_loopback(self):
        with self.assertRaises(ValueError):
            jev.Client.from_env(
                {"JEV_BACKEND": "strands", "STRANDS_URL": "http://example.com/"}
            )
        with self.assertRaises(ValueError):
            jev.Client.from_env(
                {"JEV_BACKEND": "strands", "STRANDS_URL": "file:///etc/passwd"}
            )
        with self.assertRaises(ValueError):
            jev.Client("k", url="http://127.0.0.1:8790/")


DEV = {
    "TYPESAFE_API_KEY": "k",
    "JEV_COMPARE_BACKEND": "strands",
    "STRANDS_URL": "http://strands-decider:8080",
}


class ClusterServiceHttp(unittest.TestCase):
    """Plain http to an in-cluster Service in its own pod, by opt-in (#1469)."""

    def test_an_opted_in_bare_service_host_is_accepted(self):
        client = jev.Client.from_env(
            {
                "JEV_BACKEND": "strands",
                "STRANDS_URL": "http://strands-decider:8080",
                "STRANDS_ALLOW_HTTP_HOST": "strands-decider",
            }
        )
        self.assertEqual(client.url, "http://strands-decider:8080")
        self.assertTrue(client.configured)

    def test_an_opted_in_svc_name_is_accepted(self):
        for host in ("strands-decider.wow-dev.svc", "strands-decider.wow-dev.svc.cluster.local"):
            client = jev.Client.from_env(
                {
                    "JEV_BACKEND": "strands",
                    "STRANDS_URL": "http://%s:8080/" % host,
                    "STRANDS_ALLOW_HTTP_HOST": " Other , %s" % host.upper(),
                }
            )
            self.assertEqual(client.url, "http://%s:8080/" % host)

    def test_the_service_host_without_the_opt_in_is_rejected(self):
        with self.assertRaises(ValueError):
            jev.Client.from_env(
                {"JEV_BACKEND": "strands", "STRANDS_URL": "http://strands-decider:8080"}
            )

    def test_a_look_alike_host_is_rejected(self):
        for url in (
            "http://strands-decider.example.com:8080/",
            "http://strands-decider.svc.example.com/",
            "http://strands-deciders:8080/",
            "http://10.0.0.5:8080/",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                jev.Client.from_env(
                    {
                        "JEV_BACKEND": "strands",
                        "STRANDS_URL": url,
                        "STRANDS_ALLOW_HTTP_HOST": "strands-decider",
                    }
                )

    def test_a_public_name_cannot_be_opted_in(self):
        with self.assertLogs("wow-overseer.jev", "WARNING") as logs:
            hosts = jev.allow_http_hosts("example.com,strands-decider,10.0.0.5")
        self.assertEqual(hosts, ("strands-decider",))
        self.assertIn("example.com", "\n".join(logs.output))
        with self.assertRaises(ValueError):
            jev.Client.from_env(
                {
                    "JEV_BACKEND": "strands",
                    "STRANDS_URL": "http://example.com/",
                    "STRANDS_ALLOW_HTTP_HOST": "example.com",
                }
            )

    def test_a_non_local_backend_never_takes_plain_http(self):
        with self.assertRaises(ValueError):
            jev.Client(
                "k",
                url="http://strands-decider:8080/",
                allow_http_hosts=("strands-decider",),
            )

    def test_the_cluster_host_shapes(self):
        yes = ("strands-decider", "a.b.svc", "a.svc.cluster.local", "x1")
        no = ("", "example.com", "a.svc.evil", "-bad", "10.0.0.5", "a..svc", ".svc")
        for host in yes:
            self.assertTrue(jev.cluster_service_host(host), host)
        for host in no:
            self.assertFalse(jev.cluster_service_host(host), host)


class CompareNeverStopsTheActive(unittest.TestCase):
    """A compare backend that cannot be built is off, loudly (#1469)."""

    def test_a_refused_compare_url_leaves_the_active_backend_working(self):
        transport = Transport()
        with self.assertLogs("wow-overseer.jev", "ERROR") as logs:
            client = jev.Client.from_env(DEV, transport=transport)
        self.assertIsNone(client.shadow)
        self.assertEqual(client.backend.name, "jev")
        self.assertEqual(len(logs.output), 1)
        self.assertIn("compare is off", logs.output[0])
        out = run(client.ask("item_keep", {"item": "Destiny"}, {"route": ROUTE}))
        self.assertEqual(out.status, jev.ANSWERED)

    def test_the_dev_config_with_the_opt_in_builds_the_compare_client(self):
        client = jev.Client.from_env(dict(DEV, STRANDS_ALLOW_HTTP_HOST="strands-decider"))
        self.assertEqual(client.shadow.backend.name, "strands")
        self.assertEqual(client.shadow.url, "http://strands-decider:8080")

    def test_the_bridge_builds_its_client_through_the_guarded_from_env(self):
        """bridge.py cannot be imported here (it needs discord), so pin that its
        constructor builds the client with the bare from_env, whose compare
        failure is caught above, and nothing else that could raise first."""
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("self._jev = jev.Client.from_env()\n", src)
        self.assertEqual(src.count("jev.Client("), 0)


class RequestShape(unittest.TestCase):
    def test_the_body_is_the_jev_body_and_no_authorization_is_sent(self):
        transport = Transport()
        client = jev.Client.from_env({"JEV_BACKEND": "strands"}, transport=transport)
        out = run(client.ask("item_keep", {"item": "Destiny"}, {"route": ROUTE}))
        self.assertEqual(out.status, jev.ANSWERED)
        url, body, headers, _timeout = transport.calls[0]
        self.assertEqual(url, "http://127.0.0.1:8790/")
        self.assertEqual(set(body), {"state", "model", "questions"})
        self.assertEqual(body["model"], "strands-decider-2b")
        self.assertEqual(body["state"], {"item": "Destiny"})
        self.assertEqual(body["questions"], {"route": ROUTE})
        self.assertEqual(headers, {"Content-Type": "application/json"})


class OverHttp(unittest.TestCase):
    def test_a_choice_arrives_typed_with_probabilities_and_confidence(self):
        service = FakeService(service_ms=118)
        self.addCleanup(service.close)
        client = jev.Client.from_env(
            {"JEV_BACKEND": "strands", "STRANDS_URL": service.url}
        )
        out = run(client.ask("item_keep", {"a": 1}, {"route": ROUTE}))
        self.assertEqual(out.status, jev.ANSWERED)
        answer = out.answers["route"]
        self.assertEqual(answer.choice, "equip")
        self.assertEqual(answer.probabilities["equip"], 0.8)
        self.assertEqual(answer.confidence, 0.7)
        self.assertEqual((out.model, out.service_ms), ("strands-decider-2b", 118))
        [(_path, headers, body)] = service.requests
        self.assertNotIn("Authorization", headers)
        self.assertEqual(body["questions"], {"route": ROUTE})

    def test_an_option_nobody_offered_is_none(self):
        service = FakeService(answers=good_choice("bank"))
        self.addCleanup(service.close)
        client = jev.Client.from_env(
            {"JEV_BACKEND": "strands", "STRANDS_URL": service.url}
        )
        out = run(client.ask("item_keep", {"a": 1}, {"route": ROUTE}))
        self.assertIsNone(out.answers)
        self.assertEqual(out.status, jev.INVALID)

    def test_a_service_error_is_none_with_the_reason(self):
        service = FakeService(status=503)
        self.addCleanup(service.close)
        client = jev.Client.from_env(
            {"JEV_BACKEND": "strands", "STRANDS_URL": service.url}
        )
        out = run(client.ask("item_keep", {"a": 1}, {"route": ROUTE}))
        self.assertEqual((out.status, out.detail), (jev.ERROR, "http 503"))
        self.assertIsNone(out.answers)


class NoService(unittest.TestCase):
    def test_an_empty_url_asks_nothing_and_answers_no_key(self):
        transport = Transport()
        client = jev.Client.from_env(
            {"JEV_BACKEND": "strands", "STRANDS_URL": ""}, transport=transport
        )
        self.assertFalse(client.configured)
        with self.assertLogs("wow-overseer.jev", "WARNING") as logs:
            out = run(client.ask("item_keep", {"a": 1}, {"route": ROUTE}))
            run(client.ask("item_keep", {"a": 2}, {"route": ROUTE}))
        self.assertEqual(out.status, jev.NO_KEY)
        self.assertIsNone(out.answers)
        self.assertEqual(transport.calls, [])
        self.assertEqual(len(logs.output), 1)

    def test_an_unreachable_service_is_none_and_counted(self):
        self.addCleanup(setattr, jev, "TALLY", jev.TALLY)
        jev.TALLY = jev.Tally()
        client = jev.Client.from_env(
            {"JEV_BACKEND": "strands", "STRANDS_URL": dead_url()}
        )

        async def go():
            return [
                await client.ask("item_keep", {"i": i}, {"route": ROUTE})
                for i in range(3)
            ]

        with self.assertLogs("wow-overseer.jev", "INFO") as logs:
            outs = run(go())
        for out in outs:
            self.assertEqual(out.status, jev.ERROR)
            self.assertIsNone(out.answers)
        # Said once an hour, counted every time.
        self.assertEqual(len([x for x in logs.output if "backend=strands" in x]), 1)
        self.assertEqual(jev.TALLY._counts[("strands", "item_keep")]["errors"], 3)

    def test_the_heuristic_acts_when_the_service_is_down(self):
        case = test_jev_choices.DungeonChoiceTest()
        facts = case.facts()
        opts = campaignplan.options(facts)
        pick = campaignplan.heuristic(opts)
        rule = jev_choices.policy(jev_choices.KIND_DUNGEON, {})
        client = jev.Client.from_env(
            {"JEV_BACKEND": "strands", "STRANDS_URL": dead_url()}
        )
        judgment = run(jev_choices.dungeon_ask(client, facts, opts, pick, rule))
        self.assertEqual((judgment.status, judgment.jev), (jev.ERROR, ""))
        self.assertIs(jev_choices.dungeon_carried(opts, pick, judgment), pick)


class Compare(unittest.TestCase):
    def pair(self, strands_url, active_choice="equip"):
        rows = []

        async def sink(batch):
            rows.extend(batch)

        # The environment builds the comparison client (checked in Selection);
        # here the active side gets a fake transport and strands the wire.
        shadow = jev.Client.from_env(
            {"JEV_BACKEND": "strands", "STRANDS_URL": strands_url}
        )
        active = jev.Client(
            "k",
            url="https://example.com/a",
            transport=Transport(result=reply(good_choice(active_choice))),
            shadow=shadow,
            compare_sink=sink,
        )
        return active, rows

    def settle(self, client):
        async def go():
            out = await client.ask("item_keep", {"x": 1}, {"route": ROUTE})
            await client.drain_compare()
            return out

        return run(go())

    def test_strands_is_recorded_beside_the_active_answer_and_never_changes_it(self):
        service = FakeService(answers=good_choice("keep"), service_ms=120)
        self.addCleanup(service.close)
        active, rows = self.pair(service.url, "equip")
        out = self.settle(active)
        self.assertEqual((out.backend, out.answers["route"].choice), ("jev", "equip"))
        [row] = rows
        self.assertEqual(
            (
                row["backend"],
                row["active_backend"],
                row["answer"],
                row["active_answer"],
            ),
            ("strands", "jev", "keep", "equip"),
        )
        self.assertIs(row["agree"], False)
        self.assertEqual(row["service_ms"], 120)
        self.assertEqual(len(service.requests), 1)
        self.assertNotIn("Authorization", service.requests[0][1])

    def test_a_down_service_is_a_compare_row_with_an_error_status(self):
        active, rows = self.pair(dead_url(), "equip")
        out = self.settle(active)
        self.assertEqual(out.status, jev.ANSWERED)
        self.assertEqual(out.answers["route"].choice, "equip")
        [row] = rows
        self.assertEqual(
            (row["backend"], row["status"], row["answer"]), ("strands", jev.ERROR, "")
        )
        self.assertIsNone(row["agree"])


class Visible(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, jev, "TALLY", jev.TALLY)
        jev.TALLY = jev.Tally()

    def test_latency_is_in_the_hourly_line(self):
        now = [0.0]
        tally = jev.Tally(clock=lambda: now[0])
        for ms in (10, 20, 30, 40, 100):
            tally.status("strands", "item_keep", jev.ANSWERED, ms, ms // 2)
        tally.status("strands", "item_keep", jev.ERROR)
        tally.agreement("item_keep", False, "strands")
        tally.status("jev", "item_keep", jev.ANSWERED, 400)
        now[0] = 3601.0
        lines = tally.lines()
        self.assertEqual(len(lines), 2)
        strands = [x for x in lines if "backend=strands" in x][0]
        for part in (
            "kind=item_keep",
            "answered=5",
            "disagreed=1",
            "errors=1",
            "p50_ms=30",
            "p95_ms=100",
            "service_p50_ms=15",
            "service_p95_ms=50",
        ):
            self.assertIn(part, strands)
        other = [x for x in lines if "backend=jev" in x][0]
        self.assertIn("p50_ms=400", other)
        self.assertNotIn("service_p50_ms", other)

    def test_the_comparison_backend_has_its_own_tally_lines(self):
        service = FakeService(answers=good_choice("keep"), service_ms=90)
        self.addCleanup(service.close)
        active, _rows = Compare().pair(service.url, "equip")
        Compare().settle(active)
        counts = jev.TALLY._counts
        self.assertEqual(counts[("jev", "item_keep")]["answered"], 1)
        self.assertEqual(counts[("strands", "item_keep")]["answered"], 1)
        self.assertEqual(counts[("strands", "item_keep")]["disagreed"], 1)
        self.assertEqual(counts[("jev", "item_keep")]["disagreed"], 0)
        self.assertEqual(len(counts[("strands", "item_keep")]["service"]), 1)

    def test_the_card_and_the_log_line_count_the_same_percentile(self):
        for n in range(1, 40):
            values = [(i * 37) % 101 for i in range(n)]
            for pct in (50, 95):
                self.assertEqual(
                    jevview._percentile(values, pct), jev._percentile(values, pct)
                )

    def test_the_decree_card_shows_latency_and_agreement_per_kind(self):
        def compare_row(kind, jev_answer, agree, ms):
            return {
                "kind": kind,
                "mode": "compare",
                "backend": "strands",
                "subject": "",
                "item_name": "route",
                "heuristic": "equip",
                "jev": jev_answer,
                "confidence": 0.7,
                "agree": agree,
                "status": "answered" if jev_answer else "error",
                "latency_ms": ms,
                "acted": "",
            }

        rows = [
            compare_row("item_keep", "keep", 0, 100),
            compare_row("item_keep", "equip", 1, 200),
            compare_row("item_keep", "equip", 1, 300),
            compare_row("item_keep", "", None, 3000),
            compare_row("movement", "walk", 1, 50),
        ]
        out = jevview.view(rows)
        self.assertIn("p50 100 ms, p95 300 ms", out["backends"][0])
        by_kind = {line.split(":")[0]: line for line in out["backend_kinds"]}
        keep = by_kind["strands, What to do with a protected non-gear item"]
        for part in (
            "3 answered",
            "agreed on 2 of 3 (67%)",
            "p50 200 ms",
            "p95 300 ms",
            "1 error",
        ):
            self.assertIn(part, keep)
        move = by_kind["strands, How a family gets moving again"]
        self.assertIn("agreed on 1 of 1 (100%)", move)
        self.assertEqual(jevview.view([])["backend_kinds"], [])


if __name__ == "__main__":
    unittest.main()
