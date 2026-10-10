"""Decision backends behind jev.Client.ask (#820).

The contract is unchanged for every caller: None answers keep the heuristic,
one hard deadline, no retry, bounded slots and cache. These drive the real
client through a fake transport, one adapter at a time.
"""

import asyncio
import json
import os
import tempfile
import unittest

import jev
from test_jev import Transport, reply, good_choice, ROUTE

SCORE = jev.score("How bad?", ["low", "mid", "high"])
NOUL = jev.noul("Is it so?")


def run(coro):
    return asyncio.run(coro)


def token_file(text="not-a-real-token\n"):
    handle = tempfile.NamedTemporaryFile("w", suffix=".tok", delete=False)
    handle.write(text)
    handle.close()
    return handle.name


class Selection(unittest.TestCase):
    def test_default_is_jev(self):
        self.assertEqual(jev.backend_name({}), "jev")
        self.assertEqual(jev.Client.from_env({}).backend.name, "jev")

    def test_unknown_backend_falls_back_to_jev(self):
        self.assertEqual(jev.backend_name({"JEV_BACKEND": "nope"}), "jev")

    def test_clef_without_token_or_account_is_unconfigured(self):
        client = jev.Client.from_env({"JEV_BACKEND": "clef"})
        self.assertFalse(client.configured)
        out = run(client.ask("k", {"a": 1}, {"route": ROUTE}))
        self.assertEqual(out.status, jev.NO_KEY)
        self.assertIsNone(out.answers)

    def test_clef_token_comes_from_a_file_and_is_never_logged(self):
        path = token_file()
        self.addCleanup(os.unlink, path)
        env = {
            "JEV_BACKEND": "clef",
            "CLEF_ACCOUNT_ID": "acct123",
            "CLEF_TOKEN_FILE": path,
        }
        transport = Transport()
        client = jev.Client.from_env(env, transport=transport)
        self.assertTrue(client.configured)
        with self.assertLogs("wow-overseer.jev", "INFO") as logs:
            out = run(client.ask("k", {"a": 1}, {"route": ROUTE}))
        self.assertEqual(out.status, jev.ANSWERED)
        url, body, headers, _t = transport.calls[0]
        self.assertEqual(
            url,
            "https://api.cloudflare.com/client/v4/accounts/acct123/ai/run/@cf/cloudflare/clef",
        )
        self.assertEqual(headers["Authorization"], "Bearer not-a-real-token")
        self.assertEqual(body["model"], "clef")
        self.assertEqual(set(body), {"state", "model", "questions"})
        self.assertNotIn("not-a-real-token", "\n".join(logs.output))

    def test_unreadable_token_file_is_unconfigured(self):
        client = jev.Client.from_env(
            {
                "JEV_BACKEND": "clef",
                "CLEF_ACCOUNT_ID": "a",
                "CLEF_TOKEN_FILE": "/nope/x",
            }
        )
        self.assertFalse(client.configured)

    def test_clef_unwraps_the_workers_ai_envelope(self):
        wrapped = json.dumps(
            {"success": True, "result": {"model": "clef", "answers": good_choice()}}
        ).encode()
        transport = Transport(result=(200, wrapped))
        client = jev.Client(
            "k", backend=jev.CLEF, url="https://example.com/x", transport=transport
        )
        out = run(client.ask("k", {}, {"route": ROUTE}))
        self.assertEqual(out.status, jev.ANSWERED)
        self.assertEqual(out.answers["route"].choice, "equip")

    def test_clef_flash_model_id_names_the_body_model(self):
        path = token_file()
        self.addCleanup(os.unlink, path)
        transport = Transport()
        client = jev.Client.from_env(
            {
                "JEV_BACKEND": "clef",
                "CLEF_ACCOUNT_ID": "a",
                "CLEF_TOKEN_FILE": path,
                "CLEF_MODEL": "@cf/cloudflare/clef-flash",
            },
            transport=transport,
        )
        run(client.ask("k", {}, {"route": ROUTE}))
        self.assertTrue(
            transport.calls[0][0].endswith("/ai/run/@cf/cloudflare/clef-flash")
        )
        self.assertEqual(transport.calls[0][1]["model"], "clef-flash")


def openai_reply(answers):
    return 200, json.dumps({"answers": answers}).encode()


class OpenAIAdapter(unittest.TestCase):
    def client(self, result):
        transport = Transport(result=result)
        return (
            jev.Client(
                "k",
                backend=jev.OPENAI,
                url="https://example.com/v1/decisions",
                model="gpt-6-luna",
                transport=transport,
            ),
            transport,
        )

    def test_questions_are_translated_out_and_answers_back(self):
        client, transport = self.client(
            openai_reply(
                [
                    {
                        "type": "choice",
                        "name": "route",
                        "choice": "equip",
                        "probabilities": [
                            {"value": "keep", "probability": 0.1},
                            {"value": "vendor", "probability": 0.1},
                            {"value": "equip", "probability": 0.8},
                        ],
                        "confidence": 0.7,
                    },
                    {
                        "type": "score",
                        "name": "sev",
                        "score": 1.1,
                        "probabilities": [
                            {"value": 0, "label": "low", "probability": 0.1},
                            {"value": 1, "label": "mid", "probability": 0.7},
                            {"value": 2, "label": "high", "probability": 0.2},
                        ],
                        "confidence": 0.55,
                    },
                    {"type": "predicate", "name": "yes", "probability": 0.92},
                ]
            )
        )
        qs = {"route": ROUTE, "sev": SCORE, "yes": NOUL}
        out = run(client.ask("k", {"a": 1}, qs))
        self.assertEqual(out.status, jev.ANSWERED)
        self.assertEqual(out.answers["route"].choice, "equip")
        self.assertEqual(out.answers["route"].probabilities["equip"], 0.8)
        self.assertEqual(out.answers["sev"].score, 1.1)
        self.assertEqual(out.answers["sev"].probabilities["1"], 0.7)
        self.assertEqual(out.answers["yes"].noul, 0.92)
        body = transport.calls[0][1]
        self.assertEqual(body["model"], "gpt-6-luna")
        sent = {q["name"]: q for q in body["questions"]}
        self.assertEqual(sent["yes"]["type"], "predicate")
        self.assertEqual(
            {c["value"] for c in sent["route"]["choices"]}, {"keep", "vendor", "equip"}
        )
        self.assertEqual(
            [x["label"] for x in sent["sev"]["levels"]], ["low", "mid", "high"]
        )
        self.assertEqual(transport.calls[0][2]["Authorization"], "Bearer k")

    def test_a_refusal_or_a_missing_answer_is_none(self):
        client, _ = self.client(openai_reply([{"type": "refusal", "name": "route"}]))
        out = run(client.ask("k", {}, {"route": ROUTE}))
        self.assertEqual(out.status, jev.INVALID)
        self.assertIsNone(out.answers)

    def test_an_option_nobody_offered_is_none(self):
        client, _ = self.client(
            openai_reply(
                [
                    {
                        "type": "choice",
                        "name": "route",
                        "choice": "bank",
                        "probabilities": [
                            {"value": "keep", "probability": 0.1},
                            {"value": "vendor", "probability": 0.1},
                            {"value": "equip", "probability": 0.8},
                        ],
                        "confidence": 0.7,
                    }
                ]
            )
        )
        out = run(client.ask("k", {}, {"route": ROUTE}))
        self.assertIsNone(out.answers)

    def test_http_402_is_none_with_the_reason(self):
        client, _ = self.client((402, b"{}"))
        out = run(client.ask("k", {}, {"route": ROUTE}))
        self.assertEqual((out.status, out.detail), (jev.ERROR, "http 402"))


class ModesStayAsCoded(unittest.TestCase):
    def test_a_new_backend_keeps_the_coded_default_mode(self):
        env = {"JEV_BACKEND": "clef"}
        self.assertEqual(jev.mode("item_keep", env, default=jev.ACT), jev.ACT)
        self.assertEqual(jev.mode("movement", env), jev.SHADOW)

    def test_kill_switch_per_kind(self):
        env = {"JEV_BACKEND": "clef", "JEV_MODE_ITEM_KEEP": "off"}
        self.assertEqual(jev.mode("item_keep", env, default=jev.ACT), jev.OFF)
        env["JEV_MODE_ITEM_KEEP"] = "shadow"
        self.assertEqual(jev.mode("item_keep", env, default=jev.ACT), jev.SHADOW)


class Compare(unittest.TestCase):
    def pair(self, active_result, shadow_result):
        rows = []

        async def sink(batch):
            rows.extend(batch)

        shadow = jev.Client(
            "s",
            backend=jev.CLEF,
            url="https://example.com/s",
            transport=Transport(result=shadow_result),
        )
        active = jev.Client(
            "a",
            url="https://example.com/a",
            transport=Transport(result=active_result),
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

    def test_both_answers_are_recorded_on_identical_questions(self):
        active, rows = self.pair(
            reply(good_choice("equip")), reply(good_choice("keep"))
        )
        out = self.settle(active)
        self.assertEqual(out.answers["route"].choice, "equip")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            (
                row["kind"],
                row["backend"],
                row["answer"],
                row["active_answer"],
                row["agree"],
            ),
            ("item_keep", "clef", "keep", "equip", False),
        )
        self.assertEqual(row["active_backend"], "jev")
        self.assertEqual(len(active.shadow._transport.calls), 1)
        self.assertEqual(len(active._compares), 0)

    def test_active_failure_does_not_block_and_is_recorded(self):
        active, rows = self.pair((402, b"{}"), reply(good_choice("keep")))
        out = self.settle(active)
        self.assertIsNone(out.answers)
        self.assertEqual(rows[0]["active_answer"], "")
        self.assertIsNone(rows[0]["agree"])

    def test_shadow_failure_never_touches_the_active_answer(self):
        active, rows = self.pair(reply(good_choice("equip")), (500, b""))
        out = self.settle(active)
        self.assertEqual(out.status, jev.ANSWERED)
        self.assertEqual(rows[0]["status"], jev.ERROR)
        self.assertEqual(len(active.shadow._transport.calls), 1)

    def test_a_repeat_is_not_recorded_twice(self):
        active, rows = self.pair(reply(good_choice()), reply(good_choice()))

        async def go():
            for _ in range(3):
                await active.ask("k", {"x": 1}, {"route": ROUTE})
                await active.drain_compare()

        run(go())
        self.assertEqual(len(rows), 1)

    def test_compare_env_builds_a_second_client(self):
        path = token_file()
        self.addCleanup(os.unlink, path)
        client = jev.Client.from_env(
            {
                "TYPESAFE_API_KEY": "k",
                "JEV_COMPARE_BACKEND": "clef",
                "CLEF_ACCOUNT_ID": "a",
                "CLEF_TOKEN_FILE": path,
            }
        )
        self.assertEqual(client.shadow.backend.name, "clef")
        self.assertIsNone(jev.Client.from_env({"TYPESAFE_API_KEY": "k"}).shadow)
        same = jev.Client.from_env({"JEV_COMPARE_BACKEND": "jev"})
        self.assertIsNone(same.shadow)


class Tally(unittest.TestCase):
    def test_one_line_per_kind_per_hour(self):
        now = [0.0]
        tally = jev.Tally(clock=lambda: now[0])
        tally.status("clef", "item_keep", jev.ANSWERED)
        tally.status("clef", "item_keep", jev.ANSWERED)
        tally.status("clef", "item_keep", jev.ERROR)
        tally.agreement("item_keep", False)
        tally.agreement("item_keep", True)
        self.assertEqual(tally.lines(), [])
        now[0] = 3601.0
        lines = tally.lines()
        self.assertEqual(len(lines), 1)
        for part in (
            "backend=clef",
            "kind=item_keep",
            "answered=2",
            "disagreed=1",
            "errors=1",
        ):
            self.assertIn(part, lines[0])
        self.assertEqual(tally.lines(), [])

    def test_failure_lines_are_collapsed_to_one_per_hour(self):
        self.addCleanup(setattr, jev, "TALLY", jev.TALLY)
        jev.TALLY = jev.Tally()
        transport = Transport(result=(402, b"{}"))
        client = jev.Client("k", url="https://example.com/a", transport=transport)

        async def go():
            for i in range(5):
                await client.ask("k", {"i": i}, {"route": ROUTE})

        with self.assertLogs("wow-overseer.jev", "INFO") as logs:
            run(go())
        failures = [x for x in logs.output if "http 402" in x]
        self.assertEqual(len(failures), 1)
        self.assertEqual(jev.TALLY._counts["k"]["errors"], 5)


class BridgeWiring(unittest.TestCase):
    BRIDGE = open(
        os.path.join(os.path.dirname(__file__), "..", "bridge.py"), encoding="utf-8"
    ).read()

    def test_the_store_gains_the_backend_column_guarded(self):
        store = self.BRIDGE[self.BRIDGE.index("def _create_jev_store(") :]
        store = store[: store.index("\n\n\n")]
        self.assertIn("COLUMN_NAME = 'backend'", store)
        self.assertIn("ADD COLUMN backend VARCHAR(12) NOT NULL DEFAULT ''", store)
        self.assertIn("ADD_ACTED_SQL", store)

    def test_a_comparison_row_binds_each_value_to_its_column(self):
        insert = self.BRIDGE[self.BRIDGE.index("def _insert_jev_comparisons(") :]
        insert = insert[: insert.index("\n\n\n")]
        executed = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, args):
                executed.append((sql, args))

        class Conn(Cursor):
            def cursor(self):
                return Cursor()

        scope = {"_connect": Conn, "json": json}
        exec(insert, scope)  # noqa: S102 - bridge.py's own source
        scope["_insert_jev_comparisons"](
            [
                {
                    "kind": "item_keep",
                    "question": "route",
                    "backend": "clef",
                    "active_backend": "jev",
                    "active_answer": "equip",
                    "answer": "keep",
                    "confidence": 0.7,
                    "probabilities": {"keep": 0.7},
                    "status": "answered",
                    "latency_ms": 40,
                    "model": "clef",
                    "agree": False,
                }
            ]
        )
        sql, args = executed[0]
        columns = sql[sql.index("(kind") + 1 : sql.index(") VALUES")].split(", ")
        values = sql[sql.index("VALUES (") + 8 :].rstrip(")").split(", ")
        self.assertEqual(len(columns), len(values))
        bound = iter(args)
        row = {
            c: (next(bound) if v == "%s" else v)
            for c, v in zip(columns, values, strict=True)
        }
        self.assertEqual(row["heuristic"], "equip")
        self.assertEqual(row["heuristic_why"], "active backend jev")
        self.assertEqual(
            (row["jev"], row["agree"], row["backend"]), ("keep", 0, "clef")
        )
        self.assertEqual((row["item_name"], row["mode"]), ("route", "'compare'"))

    def test_the_client_is_given_the_comparison_sink(self):
        self.assertIn("self._jev.compare_sink = _jev_compare_sink", self.BRIDGE)
        self.assertIn("def _insert_jev_comparisons(", self.BRIDGE)


if __name__ == "__main__":
    unittest.main()
