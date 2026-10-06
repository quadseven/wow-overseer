"""The economy pass says "withheld" only when a campaign is withheld.

VENDOR_MODE_COUNTER is also the quiet cycle. On wow-dev (2026-10-06) the line
said "the family's campaign is withheld for bag space" over a family with
seven or more free slots each, which sent an investigation after a bag
deadlock that did not exist.
"""

import asyncio
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import bag_pressure  # noqa: E402
from test_guildsocial_bridge import bridge  # noqa: E402


def _run(withheld: bool):
    free = {"Oz": 21, "Uzza": 7, "Zork": 8}
    sellable = {"Oz": 7, "Uzza": 1, "Zork": 2}
    self = types.SimpleNamespace()
    with (
        mock.patch.object(bridge, "_campaign_waiting", lambda names: True),
        mock.patch.object(bridge, "_town_first_hold", lambda names: False),
        mock.patch.object(bridge.jev_activity, "withheld", lambda q, f: withheld),
        mock.patch.object(
            bag_pressure, "family_town_run_needed", lambda *a, **k: False
        ),
        mock.patch.object(bridge, "log") as log,
    ):
        mode = asyncio.run(
            bridge.Bridge._vendor_pass_mode(
                self, ["Oz", "Uzza", "Zork"], free, sellable, False
            )
        )
    text = " ".join(str(c.args[0]) % c.args[1:] for c in log.info.call_args_list)
    return mode, text


class TheCounterLineIsHonest(unittest.TestCase):
    def test_a_quiet_cycle_does_not_say_withheld(self):
        mode, text = _run(False)
        self.assertEqual(mode, bag_pressure.VENDOR_MODE_COUNTER)
        self.assertIn("selling alone lifts nobody", text)
        self.assertNotIn("withheld", text.replace("no campaign is withheld", ""))
        self.assertIn("no campaign is withheld", text)

    def test_a_withheld_campaign_still_says_so(self):
        mode, text = _run(True)
        self.assertEqual(mode, bag_pressure.VENDOR_MODE_COUNTER)
        self.assertIn("the family's campaign is withheld for bag space", text)


if __name__ == "__main__":
    unittest.main()
