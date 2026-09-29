"""An interlude that ends leaves the family a stretch for its campaign.

MEASURED ON wow-dev, 2026-09-29. Jev chose a ten-minute sell interlude for the
Horde family at 15:15 ET, and chose it again the second the lease ended at
15:34 ("arrived in town"), and again at 15:46. Each lease holds the campaign
queue ("holds ragefire while the family's sell interlude runs; the order
stands"), so for about forty minutes the queue held Ragefire Chasm behind
back-to-back interludes and started nothing. An interlude is meant to cost a
commitment minutes, never the order; back to back, it costs the order.

After an interlude ends the family is not asked again for a rest, long enough
for the queue to stage a run. This drives the real `Bridge._activity_holds`
and `Bridge._activity_resting`.
"""

import pathlib
import sys
import time
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import jev_activity  # noqa: E402


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


class _Pass:
    def __init__(self, until):
        self._activity_own_key = "Zug"
        self._activity_interludes = {
            "Zug": jev_activity.Interlude(jev_activity.SELL, until)
        }
        self._activity_rest = {}

    def _activity_holds(self, key=None):
        return bridge.Bridge._activity_holds(self, key)

    def _activity_resting(self, key):
        return bridge.Bridge._activity_resting(self, key)

    def _activity_paused(self, key, reason):
        return bridge.Bridge._activity_paused(self, key, reason)


class TheRestFollowsTheInterlude(unittest.TestCase):
    def test_a_live_interlude_starts_no_rest(self):
        this = _Pass(time.monotonic() + 600)
        self.assertEqual(this._activity_holds("Zug"), jev_activity.SELL)
        self.assertFalse(this._activity_resting("Zug"))

    def test_an_interlude_that_ends_leaves_a_rest(self):
        this = _Pass(time.monotonic() - 1)
        self.assertEqual(this._activity_holds("Zug"), "")
        self.assertTrue(this._activity_resting("Zug"))

    def test_the_rest_ends(self):
        this = _Pass(time.monotonic() - 1)
        this._activity_holds("Zug")
        this._activity_rest["Zug"] = time.monotonic() - 1
        self.assertFalse(this._activity_resting("Zug"))
        self.assertNotIn("Zug", this._activity_rest)

    def test_another_family_is_not_resting(self):
        this = _Pass(time.monotonic() - 1)
        this._activity_holds("Zug")
        self.assertFalse(this._activity_resting("Grug"))


class TheChoiceIsNotAskedWhileResting(unittest.TestCase):
    def test_a_resting_family_is_paused_and_a_free_one_is_not(self):
        this = _Pass(time.monotonic() - 1)
        self.assertTrue(this._activity_paused("Zug", "arrived in town"))
        this._activity_rest.clear()
        self.assertFalse(this._activity_paused("Zug", "arrived in town"))

    def test_a_live_interlude_pauses_it_too(self):
        this = _Pass(time.monotonic() + 600)
        self.assertTrue(this._activity_paused("Zug", "arrived in town"))

    def test_the_pass_checks_the_pause_before_it_asks(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()
        body = src[src.index("async def _activity_for(") :]
        body = body[: body.index("async def _activity_can(")]
        self.assertIn("self._activity_paused(key, reason)", body)
        self.assertLess(
            body.index("self._activity_paused(key, reason)"),
            body.index("await jev_activity.ask("),
        )


if __name__ == "__main__":
    unittest.main()
