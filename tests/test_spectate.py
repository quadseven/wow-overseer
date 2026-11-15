"""The dashboard's Watch order: one integer in, one camera order out.

The page never sends text the director's grammar has to trust: it sends a run
id, this module turns that into `run <id>`, and a second person's click inside
the dwell is refused in words rather than flipping the camera under the first.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import json
from unittest import mock

import director as d
from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import map_server

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def row(spec="run 285", ttl=None, target="Tanky", note="Tanky: follow"):
    return {
        "spec": spec,
        "ttl": d.MANDATE_TTL if ttl is None else ttl,
        "target": target,
        "note": note,
    }


class TheOrder(unittest.TestCase):
    def test_a_run_id_becomes_the_run_order(self):
        got = d.spectate_spec(285)
        self.assertEqual((got.kind, got.arg, got.text()), ("run", "285", "run 285"))

    def test_nothing_but_a_positive_integer_is_accepted(self):
        for bad in (
            None,
            "285",
            "run 1; drop",
            2.5,
            True,
            False,
            0,
            -4,
            10**9,
            [3],
            {},
        ):
            self.assertIsInstance(d.spectate_spec(bad), d.SpecError, repr(bad))

    def test_the_largest_id_the_grammar_reads_is_accepted(self):
        self.assertEqual(d.spectate_spec(999_999_999).text(), "run 999999999")

    def test_the_run_an_order_names(self):
        self.assertEqual(d.order_run("run 285"), 285)
        for other in ("", "guild Bonkers", "character Grug", "run x", "off"):
            self.assertIsNone(d.order_run(other), other)


class TwoPeopleClicking(unittest.TestCase):
    def test_no_order_means_anyone_may_choose(self):
        self.assertTrue(d.spectate_verdict(None, "run 285").allowed)
        self.assertTrue(d.spectate_verdict(row(ttl=0), "run 286").allowed)

    def test_the_same_group_again_renews_it_even_inside_the_dwell(self):
        got = d.spectate_verdict(row("run 285"), "run 285")
        self.assertTrue(got.allowed)

    def test_a_different_group_inside_the_dwell_is_refused_with_the_wait(self):
        fresh = row("run 285", ttl=d.MANDATE_TTL - 30)
        got = d.spectate_verdict(fresh, "run 286")
        self.assertFalse(got.allowed)
        self.assertEqual(got.switch_in, int(d.SPECTATE_DWELL - 30))
        self.assertIn("run 285", got.reason)
        self.assertIn(str(got.switch_in), got.reason)

    def test_after_the_dwell_the_newest_click_wins(self):
        old = row("run 285", ttl=d.MANDATE_TTL - int(d.SPECTATE_DWELL))
        got = d.spectate_verdict(old, "run 286")
        self.assertTrue(got.allowed)
        self.assertEqual(got.switch_in, 0)

    def test_a_wait_never_reads_zero_while_refusing(self):
        edge = row("run 285", ttl=d.MANDATE_TTL - int(d.SPECTATE_DWELL) + 1)
        got = d.spectate_verdict(edge, "run 286")
        self.assertFalse(got.allowed)
        self.assertGreaterEqual(got.switch_in, 1)

    def test_the_state_a_page_draws_from(self):
        live = d.spectate_state(row("run 285", ttl=d.MANDATE_TTL - 10))
        self.assertEqual(
            (live["active"], live["run"], live["target"]), (True, 285, "Tanky")
        )
        self.assertEqual(live["switch_in"], int(d.SPECTATE_DWELL - 10))
        idle = d.spectate_state(None)
        self.assertEqual(
            (idle["active"], idle["run"], idle["switch_in"]), (False, None, 0)
        )
        self.assertIsNone(d.spectate_state(row("guild Bonkers"))["run"])


class TheDoor(unittest.TestCase):
    """map_server is read as text: the suite does not start the server."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "map_server.py"), encoding="utf8") as fh:
            cls.src = fh.read()

    def test_it_is_an_operator_route_and_a_registered_route(self):
        self.assertIn('"/api/spectate"', self.src[: self.src.index("CHAT_MAX_CALLS")])
        self.assertIn('"/api/spectate": _spectate_state', self.src)
        self.assertIn('"/api/spectate": _spectate_post', self.src)

    def test_the_post_reads_only_the_run_id_and_binds_the_order(self):
        body = self.src[
            self.src.index("def _spectate_post") : self.src.index("def _read_json_body")
        ]
        self.assertIn("director.spectate_spec(", body)
        self.assertIn("director.spectate_verdict(", body)
        self.assertIn("director.SET_SQL", body)
        self.assertNotIn("_DIRECTOR_TOKEN", body)
        self.assertNotIn('request.get("watch")', body)
        self.assertIn("409", body)


class Handler(map_server.Handler):
    """A Handler with the socket amputated, as test_operator_gate does."""

    def __init__(self, body):
        raw = json.dumps(body).encode()
        self.rfile = io.BytesIO(raw)
        self.headers = {
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        }
        self.sent = []

    def _send(self, code, ctype, body):
        self.sent.append((code, json.loads(body)))


class ThePost(unittest.TestCase):
    def order(self, body, current=None):
        handler = Handler(body)
        cursor = mock.MagicMock()
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor
        with (
            mock.patch.object(map_server, "_read_watch_order", return_value=current),
            mock.patch.object(map_server, "_connect", return_value=conn),
        ):
            handler._spectate_post()
        return handler.sent[-1], cursor

    def test_a_run_id_writes_the_order_and_names_the_source(self):
        (code, body), cursor = self.order({"run": 285})
        self.assertEqual((code, body["run"], body["spec"]), (200, 285, "run 285"))
        cursor.execute.assert_called_once_with(
            d.SET_SQL, ("run 285", "web:spectate", d.MANDATE_TTL)
        )

    def test_text_in_the_run_field_is_a_400_and_writes_nothing(self):
        for bad in ("285", "run 1", None, 0, -1, True):
            (code, _body), cursor = self.order({"run": bad})
            self.assertEqual(code, 400, repr(bad))
            cursor.execute.assert_not_called()

    def test_the_watch_field_the_director_door_takes_is_ignored(self):
        (code, _body), cursor = self.order({"watch": "guild Bonkers"})
        self.assertEqual(code, 400)
        cursor.execute.assert_not_called()

    def test_a_second_group_inside_the_dwell_is_a_409_with_the_wait(self):
        current = row("run 285", ttl=d.MANDATE_TTL - 20)
        (code, body), cursor = self.order({"run": 286}, current)
        self.assertEqual(code, 409)
        self.assertEqual(body["switch_in"], int(d.SPECTATE_DWELL - 20))
        self.assertIn("run 285", body["error"])
        cursor.execute.assert_not_called()

    def test_the_same_group_again_renews_inside_the_dwell(self):
        current = row("run 285", ttl=d.MANDATE_TTL - 20)
        (code, _body), cursor = self.order({"run": 285}, current)
        self.assertEqual(code, 200)
        cursor.execute.assert_called_once()

    def test_an_unreadable_world_is_a_503_and_writes_nothing(self):
        handler = Handler({"run": 285})
        with mock.patch.object(
            map_server, "_read_watch_order", side_effect=OSError("down")
        ):
            handler._spectate_post()
        self.assertEqual(handler.sent[-1][0], 503)


if __name__ == "__main__":
    unittest.main()
