"""The realm switcher, and the design actually being applied.

BOTH HALVES OF THIS FILE WERE WRITTEN AFTER THE OPERATOR SAID THE LIVE SITE
LOOKED NOTHING LIKE THE DESIGN, AND HE WAS RIGHT. Measured on the live page at
the time:

  document.fonts   Archivo, Space Mono, Zen Kaku Gothic New: all "loaded"
  every element    ui-monospace, SFMono-Regular, Menlo, monospace

Three typefaces were being downloaded on every load and rendered in none of
them. The stylesheet link had shipped, the --display/--body/--mono tokens had
shipped, and a test asserting those tokens carried fallback stacks had shipped
and passed. Not one rule used them. A token nobody references is a token that
tests green and changes nothing on screen, which is the failure this file
exists to make impossible.

The other half is the switcher: three realms have been served from one hostname
for weeks and nothing on the page said so, so moving between them meant editing
the URL by hand.
"""

import json
import os
import re
import unittest

import basepath
import realmnav

LF = chr(10)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def strip_comments(text, style):
    """`text` with its comments removed.

    THE SAME MISTAKE HAS NOW BEEN MADE FIVE TIMES IN THIS WORK: a test greps
    for the bad pattern it just removed, and matches the comment that explains
    why it was removed. A comment naming #0d1117 while saying that colour is
    gone is not that colour coming back, and a test that cannot tell the
    difference punishes writing the explanation. Every assertion of the form
    "this must be absent" reads through here.
    """
    if style == "css":
        return re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return LF.join(
        line for line in text.splitlines() if not line.strip().startswith("//")
    )


class TheSwitcherKnowsWhichWorldsExist(unittest.TestCase):
    def test_all_three_realms_are_offered(self):
        nav = realmnav.build_nav("")
        self.assertEqual([r["label"] for r in nav], ["PROD", "DEV", "HC"])

    def test_exactly_one_is_current(self):
        for mount in ("", "/dev", "/hardcore"):
            nav = realmnav.build_nav(mount)
            self.assertEqual([r["current"] for r in nav].count(True), 1, mount)
            self.assertTrue(next(r for r in nav if r["mount"] == mount)["current"])

    def test_an_unknown_mount_marks_nothing_current(self):
        """Guessing production would be the most dangerous of the three to be
        wrong about, and a switcher with no active pill is the honest
        rendering of not knowing."""
        nav = realmnav.build_nav("/somewhere-else")
        self.assertEqual([r["current"] for r in nav].count(True), 0)

    def test_hardcore_is_shown_but_not_linked(self):
        """It has no site at all, deliberately (infra#2912): its map
        Deployment and Service are excluded and nothing routes to it. A link
        would send a reader to a 404 that reads as an outage."""
        hc = next(r for r in realmnav.build_nav("") if r["mount"] == "/hardcore")
        self.assertFalse(hc["reachable"])
        self.assertEqual(hc["href"], "")
        self.assertTrue(hc["note"], "a disabled control must say why")

    def test_the_other_two_are_linked_with_a_trailing_slash(self):
        """A link to "/dev" is a redirect away from "/dev/", and a proxy that
        answers it with the root would hand back production while the switcher
        showed dev as active."""
        for r in realmnav.build_nav(""):
            if r["reachable"]:
                self.assertTrue(r["href"].endswith("/"), r["href"])

    def test_it_is_json_serialisable(self):
        """It is substituted into the page as JSON, so anything that is not
        serialisable here is a page that will not parse its own header."""
        json.dumps(realmnav.build_nav("/dev"))


class TheSwitcherReachesThePageWithTheMountPoint(unittest.TestCase):
    """Substituted in the same pass as the mount, because it is a function of
    it: the pill that is lit and the realm the page reads cannot then differ."""

    def test_apply_substitutes_real_json(self):
        out = basepath.apply(b"<x>__OVERSEER_BASE__</x><y>__OVERSEER_NAV__</y>", "/dev")
        blob = out.decode().split("<y>")[1].split("</y>")[0]
        nav = json.loads(blob)
        self.assertTrue(next(r for r in nav if r["mount"] == "/dev")["current"])

    def test_a_page_without_the_token_is_still_served(self):
        """A missing mount point is refused, because it makes every realm read
        production. A missing switcher is a visible absence somebody reports,
        so refusing to serve would turn a cosmetic loss into an outage."""
        self.assertEqual(basepath.apply(b"__OVERSEER_BASE__", "/dev"), b"/dev")


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in (
            "realmnav.py",
            "basepath.py",
            "tests/test_realm_nav.py",
        ):
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                self.assertNotIn(chr(0x2014), fh.read(), name)


if __name__ == "__main__":
    unittest.main()
