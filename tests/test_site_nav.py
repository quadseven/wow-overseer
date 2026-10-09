"""The hubs, the Watch wall of heads, and the headless family cards.

Asserted against index.html as source, the way test_family_tab.py and
test_raid_tab.py do: map_server.py imports pymysql and the page has no other
test seam.

What the operator asked for, and what each class pins:

  - a scrolling tab row with More and Maps groups became five hubs (a bottom
    bar on a phone), with every address still routed by HASH_VIEWS;
  - the Watch tab shows both families' heads, from one endpoint that reads
    every family, instead of whichever family the Family tab last looked at;
  - a family member with no game client has no empty video box and no
    "watch" button;
  - the quest board and the needs panels read the family on screen.
"""

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")


def between(text, start, end):
    at = text.index(start)
    return text[at : text.index(end, at)]


class TheWatchWallIsBothHeads(unittest.TestCase):
    def test_the_server_reads_every_family_once(self):
        self.assertIn('"/api/wall": _wall,', SERVER)
        handler = between(SERVER, "    def _wall(", "    def _armory(")
        self.assertIn("_fetch_rosters()", handler)
        self.assertIn("_fetch_family(everyone)", handler)
        self.assertIn("watchwall.build_heads(", handler)
        self.assertNotIn("query.get", handler)
        self.assertIn("self._send(503", handler)

    def test_each_family_is_built_on_its_own_rows(self):
        """build_family finds the leader by guid among the rows it is handed;
        a merged set would crown one family's head on the other."""
        handler = between(SERVER, "    def _wall(", "    def _armory(")
        self.assertIn('mine = [r for r in rows if r["name"] in names]', handler)


if __name__ == "__main__":
    unittest.main()
