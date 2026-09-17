"""The profession lease is refreshed while its trade row is still planned.

mod-overseer#167. This is a source-contract test because importing bridge.py
would construct the Discord client and open no useful database seam here.
"""
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "bridge.py"


class TradeLeaseContract(unittest.TestCase):
    def test_pending_duplicate_refreshes_decided_at(self):
        source = SOURCE.read_text(encoding="utf-8")
        body = source[source.index("def _record_trade_plan"):]
        body = body[:body.index("def _activate_training")]
        self.assertIn("ON DUPLICATE KEY UPDATE decided_at", body)
        self.assertIn("IF(status = 'planned', NOW(), decided_at)", body)

    def test_only_a_new_insert_is_announced(self):
        source = SOURCE.read_text(encoding="utf-8")
        body = source[source.index("def _record_trade_plan"):]
        body = body[:body.index("def _activate_training")]
        self.assertIn("if cur.rowcount == 1:", body)
        self.assertNotIn("if cur.rowcount:\n", body)


if __name__ == "__main__":
    unittest.main()
