"""The Strands Decider wrapper speaks the Jev body end to end (#822).

Every test starts the real HTTP server (services/strands-decider/
strands_server.py) on 127.0.0.1 with an ephemeral port and drives it over a
socket with urllib, against a fake decider, so the routes, status codes,
validation and answer shaping are the shipped code. The answers are then read
by jev.py's own JevBackend.read and jev.parse: the wrapper is correct when the
bridge's parser accepts what it returns, not when it looks right.

No torch and no model: the package is imported only inside LibraryDecider,
which is tested here against a stub of the package's two entry points.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import threading
import types
import unittest
import urllib.error
import urllib.request

import jev

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PATH = ROOT / "services" / "strands-decider" / "strands_server.py"

_spec = importlib.util.spec_from_file_location("strands_server", SERVER_PATH)
strands_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(strands_server)

ROUTE = jev.choice(
    "What should happen to it?",
    {"keep": "keep it", "vendor": "sell it", "equip": "wear it"},
)
FULL = jev.noul("The bags are nearly full.")
URGENCY = jev.score("How urgent is clearing space?", ["low", "medium", "high"])


class Running:
    """A server on 127.0.0.1:<ephemeral> in a thread, for one test."""

    def __init__(self, service, max_body=strands_server.DEFAULT_MAX_BODY):
        self.service = service
        self.server = strands_server.make_server(service, "127.0.0.1", 0, max_body)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def call(self, method, path, body=None, raw=None):
        data = (
            raw
            if raw is not None
            else (None if body is None else json.dumps(body).encode())
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            finally:
                exc.close()

    def ask(self, questions, path="/", state="12 Linen Cloth, bags 90 percent full"):
        return self.call(
            "POST", path, {"state": state, "model": "anything", "questions": questions}
        )


class WrapperCase(unittest.TestCase):
    def serve(self, decider=None, **kw):
        service = strands_server.Service(decider)
        running = Running(service, **kw)
        self.addCleanup(running.close)
        return running


class ChoiceAnswer(WrapperCase):
    def test_choice_carries_label_probabilities_and_confidence(self):
        running = self.serve(strands_server.FakeDecider(model="strands-test-1"))
        status, body = running.ask({"route": ROUTE})
        self.assertEqual(status, 200)
        self.assertEqual(body["model"], "strands-test-1")
        answer = body["answers"]["route"]
        self.assertEqual(answer["type"], "choice")
        self.assertEqual(answer["choice"], "keep")
        self.assertEqual(set(answer["probabilities"]), {"keep", "vendor", "equip"})
        self.assertAlmostEqual(sum(answer["probabilities"].values()), 1.0)
        self.assertGreater(answer["confidence"], 0.0)

        typed, model = jev.JevBackend().read({"route": ROUTE}, body)
        self.assertEqual(model, "strands-test-1")
        self.assertIsInstance(typed["route"], jev.Choice)
        self.assertEqual(typed["route"].choice, "keep")
        self.assertEqual(typed["route"].probabilities, answer["probabilities"])

    def test_v1_ask_is_the_same_route(self):
        running = self.serve(strands_server.FakeDecider())
        root_status, root = running.ask({"route": ROUTE})
        v1_status, v1 = running.ask({"route": ROUTE}, path="/v1/ask")
        self.assertEqual((root_status, v1_status), (200, 200))
        # Everything but the measured time is the same answer.
        root.pop("latency_ms")
        v1.pop("latency_ms")
        self.assertEqual(root, v1)

    def test_the_decider_sees_the_jev_question_unchanged(self):
        fake = strands_server.FakeDecider()
        running = self.serve(fake)
        running.ask({"route": ROUTE, "full": FULL}, state={"bags": 0.9})
        state, questions = fake.calls[-1]
        self.assertEqual(state, {"bags": 0.9})
        self.assertEqual(questions, {"route": ROUTE, "full": FULL})


class NoulAnswer(WrapperCase):
    def test_noul_is_a_probability_jev_reads(self):
        running = self.serve(strands_server.FakeDecider(noul=0.8))
        status, body = running.ask({"full": FULL, "route": ROUTE})
        self.assertEqual(status, 200)
        self.assertEqual(body["answers"]["full"], {"type": "noul", "noul": 0.8})
        typed, _ = jev.JevBackend().read({"full": FULL, "route": ROUTE}, body)
        self.assertEqual(typed["full"], jev.Noul(0.8))


class ScoreAnswer(WrapperCase):
    def test_unsupported_score_is_omitted_so_jev_returns_none(self):
        fake = strands_server.FakeDecider(kinds=("choice", "noul"))
        running = self.serve(fake)
        questions = {"route": ROUTE, "urgency": URGENCY}
        status, body = running.ask(questions)
        self.assertEqual(status, 200)
        self.assertNotIn("urgency", body["answers"])
        self.assertIn("route", body["answers"])
        # The decider is never asked a kind it cannot answer.
        self.assertEqual(set(fake.calls[-1][1]), {"route"})
        self.assertIsNone(jev.parse(URGENCY, body["answers"].get("urgency")))
        self.assertIsNotNone(jev.parse(ROUTE, body["answers"]["route"]))
        # Read as a whole, a request with an unanswered question is no answer:
        # the heuristic acts.
        typed, _ = jev.JevBackend().read(questions, body)
        self.assertIsNone(typed)

    def test_only_unsupported_questions_answer_empty_without_calling(self):
        fake = strands_server.FakeDecider(kinds=("choice", "noul"))
        running = self.serve(fake)
        status, body = running.ask({"urgency": URGENCY})
        self.assertEqual(status, 200)
        self.assertEqual(body["answers"], {})
        self.assertEqual(fake.calls, [])

    def test_supported_score_is_read_by_jev(self):
        running = self.serve(strands_server.FakeDecider(kinds=strands_server.KINDS))
        status, body = running.ask({"urgency": URGENCY})
        self.assertEqual(status, 200)
        typed, _ = jev.JevBackend().read({"urgency": URGENCY}, body)
        self.assertEqual(typed["urgency"].score, 1.0)


class MalformedRequest(WrapperCase):
    def assert_400(self, running, *, body=None, raw=None):
        status, reply = running.call("POST", "/", body=body, raw=raw)
        self.assertEqual(status, 400, reply)
        self.assertIsInstance(reply.get("error"), str)

    def test_each_malformed_body_is_400(self):
        fake = strands_server.FakeDecider()
        running = self.serve(fake)
        self.assert_400(running, raw=b"{not json")
        self.assert_400(running, raw=b"\xff\xfe")
        self.assert_400(running, body=["a", "list"])
        self.assert_400(running, body={"questions": {"route": ROUTE}})
        self.assert_400(running, body={"state": 3, "questions": {"route": ROUTE}})
        self.assert_400(running, body={"state": "s"})
        self.assert_400(running, body={"state": "s", "questions": {}})
        self.assert_400(running, body={"state": "s", "questions": {"q": "text"}})
        self.assert_400(
            running,
            body={
                "state": "s",
                "questions": {"q": {"type": "essay", "instructions": "x"}},
            },
        )
        self.assert_400(
            running,
            body={
                "state": "s",
                "questions": {"q": {"type": "choice", "criteria": {"a": "", "b": ""}}},
            },
        )
        self.assert_400(
            running,
            body={"state": "s", "questions": {"q": jev.choice("x", {"only": "one"})}},
        )
        self.assert_400(
            running, body={"state": "s", "questions": {"q": jev.score("x", ["one"])}}
        )
        self.assert_400(
            running,
            body={"state": "s", "questions": {"q": jev.noul("x", {"maybe": "y"})}},
        )
        # A malformed request never reaches the model.
        self.assertEqual(fake.calls, [])

    def test_body_over_the_limit_is_413(self):
        running = self.serve(strands_server.FakeDecider(), max_body=64)
        status, reply = running.ask({"route": ROUTE})
        self.assertEqual(status, 413)
        self.assertIn("error", reply)

    def test_unknown_path_is_404(self):
        running = self.serve(strands_server.FakeDecider())
        self.assertEqual(running.call("GET", "/nope")[0], 404)
        self.assertEqual(running.ask({"route": ROUTE}, path="/v1/other")[0], 404)


class ModelNotLoaded(WrapperCase):
    def test_ask_and_health_are_503_until_loaded(self):
        running = self.serve(None)
        status, body = running.ask({"route": ROUTE})
        self.assertEqual(status, 503)
        self.assertIn("error", body)
        self.assertEqual(running.call("GET", "/healthz"), (503, {"status": "loading"}))

        running.service.load(lambda: strands_server.FakeDecider(model="strands-test-2"))
        self.assertEqual(
            running.call("GET", "/healthz"),
            (200, {"status": "ok", "model": "strands-test-2"}),
        )
        self.assertEqual(running.ask({"route": ROUTE})[0], 200)

    def test_a_failed_load_stays_503_with_its_reason(self):
        running = self.serve(None)

        def broken():
            raise OSError("no weights")

        with self.assertLogs("strands-decider", level="ERROR"):
            running.service.load(broken)
        status, body = running.call("GET", "/healthz")
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "error")
        self.assertIn("no weights", body["error"])
        status, body = running.ask({"route": ROUTE})
        self.assertEqual(status, 503)
        self.assertIn("no weights", body["error"])


class Latency(WrapperCase):
    def test_latency_ms_is_present_and_measures_the_decider(self):
        running = self.serve(strands_server.FakeDecider(delay=0.05))
        status, body = running.ask({"route": ROUTE})
        self.assertEqual(status, 200)
        self.assertIsInstance(body["latency_ms"], float)
        self.assertGreaterEqual(body["latency_ms"], 50.0)

    def test_latency_ms_is_present_with_no_supported_question(self):
        running = self.serve(strands_server.FakeDecider(kinds=("choice",)))
        status, body = running.ask({"full": FULL})
        self.assertEqual(status, 200)
        self.assertIn("latency_ms", body)


class DeciderFailures(WrapperCase):
    def test_a_refused_prompt_is_422(self):
        running = self.serve(
            strands_server.FakeDecider(error=ValueError("does not fit"))
        )
        self.assertEqual(
            running.ask({"route": ROUTE}), (422, {"error": "does not fit"})
        )

    def test_a_crash_is_500(self):
        running = self.serve(
            strands_server.FakeDecider(error=RuntimeError("device lost"))
        )
        with self.assertLogs("strands-decider", level="ERROR"):
            status, body = running.ask({"route": ROUTE})
        self.assertEqual(status, 500)
        self.assertIn("device lost", body["error"])

    def test_an_ill_typed_answer_is_left_out_not_passed_on(self):
        class Wrong(strands_server.FakeDecider):
            def decide(self, state, questions):
                return {
                    "route": {
                        "type": "choice",
                        "choice": "burn",
                        "probabilities": {},
                        "confidence": 2,
                    },
                    "full": {"type": "noul", "noul": 1.5},
                }

        running = self.serve(Wrong())
        status, body = running.ask({"route": ROUTE, "full": FULL})
        self.assertEqual(status, 200)
        self.assertEqual(body["answers"], {})


class Shaping(unittest.TestCase):
    """shape_answer passes on only what jev.parse accepts."""

    def test_every_shaped_answer_parses_and_every_rejected_one_does_not(self):
        cases = [
            (
                ROUTE,
                {
                    "choice": "keep",
                    "probabilities": {"keep": 0.5, "vendor": 0.3, "equip": 0.2},
                    "confidence": 0.25,
                },
            ),
            (
                ROUTE,
                {
                    "choice": "keep",
                    "probabilities": {"keep": 0.5, "vendor": 0.5},
                    "confidence": 0.0,
                },
            ),
            (
                ROUTE,
                {
                    "choice": "keep",
                    "probabilities": {"keep": True, "vendor": 0, "equip": 0},
                    "confidence": 1,
                },
            ),
            (FULL, {"noul": 0.2}),
            (FULL, {"noul": float("nan")}),
            (
                URGENCY,
                {
                    "score": 0.9,
                    "legend": {"0": "low"},
                    "probabilities": {"0": 0.4, "1": 0.3, "2": 0.3},
                    "confidence": 0.3,
                },
            ),
            (
                URGENCY,
                {
                    "score": 3.0,
                    "probabilities": {"0": 0.4, "1": 0.3, "2": 0.3},
                    "confidence": 0.3,
                },
            ),
            (
                URGENCY,
                {
                    "score": float("inf"),
                    "probabilities": {"0": 0.4, "1": 0.3, "2": 0.3},
                    "confidence": 0.3,
                },
            ),
            (URGENCY, "0.9"),
        ]
        for question, answer in cases:
            with self.subTest(question=question["type"], answer=answer):
                shaped = strands_server.shape_answer(question, answer)
                if shaped is None:
                    probe = (
                        dict(answer, type=question["type"])
                        if isinstance(answer, dict)
                        else answer
                    )
                    self.assertIsNone(jev.parse(question, probe))
                else:
                    self.assertIsNotNone(jev.parse(question, shaped))
                    self.assertNotIn("legend", shaped)


class LibraryDeciderOverTheStub(unittest.TestCase):
    """LibraryDecider calls the package's load_engine once and dumps its answers."""

    def setUp(self):
        self.loaded = []
        loaded = self.loaded

        class Answer:
            def __init__(self, data):
                self.data = data

            def model_dump(self):
                return dict(self.data)

        class Engine:
            def __init__(self):
                self.cfg = types.SimpleNamespace(model_name="strands-decider-0.0.0")

            def evaluate(self, request):
                self.request = request
                return types.SimpleNamespace(
                    answers={"full": Answer({"type": "noul", "noul": 0.6})}
                )

        def load_engine(checkpoint, *, device):
            engine = Engine()
            loaded.append((checkpoint, device, engine))
            return engine

        def request(**kw):
            return types.SimpleNamespace(**kw)

        package = types.ModuleType("strands_decider")
        infer = types.ModuleType("strands_decider.infer")
        infer.load_engine = load_engine
        schema = types.ModuleType("strands_decider.schema")
        schema.SystemOneRequest = request
        package.infer, package.schema = infer, schema
        patched = {
            "strands_decider": package,
            "strands_decider.infer": infer,
            "strands_decider.schema": schema,
        }
        saved = {name: sys.modules.get(name) for name in patched}
        sys.modules.update(patched)

        def restore():
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.addCleanup(restore)

    def test_loads_once_names_the_model_and_answers(self):
        decider = strands_server.LibraryDecider("Org/strands-decider-2B-x/", "cpu")
        self.assertEqual(decider.model, "strands-decider-2B-x")
        checkpoint, device, engine = self.loaded[0]
        self.assertEqual((checkpoint, device), ("Org/strands-decider-2B-x/", "cpu"))
        self.assertEqual(engine.cfg.model_name, "strands-decider-2B-x")
        self.assertEqual(decider.kinds, frozenset(strands_server.KINDS))

        running = Running(strands_server.Service(decider))
        self.addCleanup(running.close)
        status, body = running.ask({"full": FULL})
        self.assertEqual(status, 200)
        self.assertEqual(body["model"], "strands-decider-2B-x")
        self.assertEqual(body["answers"], {"full": {"type": "noul", "noul": 0.6}})
        self.assertEqual(engine.request.questions, {"full": FULL})
        self.assertEqual(len(self.loaded), 1)

    def test_an_explicit_model_name_wins(self):
        decider = strands_server.LibraryDecider("/models/ckpt", "mps", "strands-2b-v1")
        self.assertEqual(decider.model, "strands-2b-v1")


class Environment(unittest.TestCase):
    def test_defaults_bind_localhost_and_the_reference_checkpoint(self):
        self.assertEqual(strands_server.DEFAULT_BIND, "127.0.0.1")
        self.assertEqual(
            strands_server.DEFAULT_CHECKPOINT,
            "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610",
        )
        self.assertEqual(strands_server.DEFAULT_DEVICE, "cpu")

    def test_fake_decider_from_the_environment(self):
        decider = strands_server.decider_factory({"STRANDS_DECIDER": "fake"})()
        self.assertIsInstance(decider, strands_server.FakeDecider)
        self.assertNotIn("score", decider.kinds)

    def test_an_unknown_decider_refuses_to_start(self):
        with self.assertRaises(SystemExit):
            strands_server.decider_factory({"STRANDS_DECIDER": "gpu-magic"})


if __name__ == "__main__":
    unittest.main()
