"""The strands localhost wrapper answers POST /ask with a Jev-shaped body.

No network is needed: the server binds 127.0.0.1:0 in-process. These tests skip
in the lane check sandbox, which denies localhost connections (CI runs them).
"""

import json
import threading
import unittest
from http.client import HTTPConnection

from tests import sandbox_caps

import strands_server


class FakeModel:
    """Returns a canned Jev-typed answer for choice questions, None otherwise."""

    def __init__(self):
        self.calls = []

    def __call__(self, question):
        self.calls.append(question)
        if question.get("type") == "choice":
            return {
                "type": "choice",
                "choice": "equip",
                "probabilities": {"keep": 0.1, "vendor": 0.1, "equip": 0.8},
                "confidence": 0.7,
            }
        return None


class StrandsServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sandbox_caps.LOCALHOST:
            return
        cls.model = FakeModel()
        cls.server = strands_server.serve(cls.model, "127.0.0.1", 0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        if not sandbox_caps.LOCALHOST:
            return
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, questions):
        if not sandbox_caps.LOCALHOST:
            self.skipTest(sandbox_caps.NO_LOCALHOST)
        body = json.dumps(
            {"state": "a sword", "model": "strands-decider-2b", "questions": questions}
        ).encode("utf-8")
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(
            "POST", "/ask", body=body, headers={"Content-Type": "application/json"}
        )
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, json.loads(data)

    @unittest.skipUnless(sandbox_caps.LOCALHOST, sandbox_caps.NO_LOCALHOST)
    def test_a_choice_answer_has_label_probabilities_and_confidence(self):
        status, data = self._post(
            {
                "route": {
                    "type": "choice",
                    "instructions": "what happens to it?",
                    "criteria": {
                        "keep": "keep it",
                        "vendor": "sell it",
                        "equip": "wear it",
                    },
                }
            }
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["model"], "strands-decider-2b")
        answer = data["answers"]["route"]
        self.assertEqual(answer["type"], "choice")
        self.assertEqual(answer["choice"], "equip")
        self.assertEqual(
            answer["probabilities"], {"keep": 0.1, "vendor": 0.1, "equip": 0.8}
        )
        self.assertEqual(answer["confidence"], 0.7)

    @unittest.skipUnless(sandbox_caps.LOCALHOST, sandbox_caps.NO_LOCALHOST)
    def test_an_unhandled_question_is_a_missing_answer(self):
        status, data = self._post({"sure": {"type": "noul", "instructions": "is it?"}})
        self.assertEqual(status, 200)
        self.assertIsNone(data["answers"]["sure"])

    @unittest.skipUnless(sandbox_caps.LOCALHOST, sandbox_caps.NO_LOCALHOST)
    def test_the_model_receives_each_question(self):
        self._post(
            {"route": {"type": "choice", "instructions": "x", "criteria": {"a": "1"}}}
        )
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(self.model.calls[0]["type"], "choice")
