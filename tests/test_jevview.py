"""The Decree's Jev card: sentences from Python, drawn by the page as text (#95)."""

import pathlib
import re
import unittest

import jevview

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")


def row(**kw):
    base = dict(
        kind="weapon_choice",
        subject="Grog",
        item_name="Destiny",
        heuristic="worn",
        jev="carried",
        confidence=0.91,
        agree=0,
        status="answered",
        mode="act",
        acted="jev",
    )
    base.update(kw)
    return base


class ViewTest(unittest.TestCase):
    def test_each_kind_says_agreement_confidence_and_who_acted(self):
        rows = [
            row(),
            row(jev="worn", agree=1, confidence=0.99, acted="both"),
            row(
                kind="item_disposition",
                mode="act",
                heuristic="keep",
                jev="keep",
                agree=1,
                confidence=0.4,
                acted="both",
            ),
            row(
                kind="item_disposition",
                jev="",
                confidence=None,
                agree=None,
                status="timeout",
                acted="heuristic",
            ),
        ]
        out = jevview.view(rows)
        self.assertEqual(
            out["kinds"],
            [
                "Weapon choice, act: 2 records, 2 answered, agreed on 1 of 2 (50%), "
                "mean confidence 0.95; Jev's answer carried out once.",
                "What to do with a carried item, act: 2 records, 1 answered, agreed "
                "on 1 of 1 (100%), mean confidence 0.40; Jev's answer carried out "
                "0 times.",
            ],
        )
        self.assertEqual(
            out["recent"][0],
            "Weapon choice: Grog, Destiny. heuristic worn, Jev carried at 0.91 "
            "(differ); Jev's answer was carried out.",
        )
        self.assertIn("Jev gave no answer (timeout)", out["recent"][3])
        self.assertIn("the heuristic's answer was carried out", out["recent"][3])

    def test_a_row_from_before_acted_existed_says_so(self):
        [line] = jevview.view([row(acted="")])["recent"]
        self.assertIn("who acted was not recorded", line)

    def test_an_unknown_kind_is_shown_by_its_key(self):
        out = jevview.view([row(kind="something_new")])
        self.assertTrue(out["kinds"][0].startswith("something_new, act:"))

    def test_nothing_on_record_is_said(self):
        out = jevview.view([])
        self.assertEqual((out["kinds"], out["recent"]), ([], []))
        self.assertTrue(out["empty"])
        self.assertEqual(out["title"], "Jev")

    def test_recent_is_bounded(self):
        self.assertEqual(len(jevview.view([row()] * 40)["recent"]), 12)

    def test_no_em_dash_reaches_the_page(self):
        out = jevview.view([row()])
        text = " ".join([out["lede"], out["empty"]] + out["kinds"] + out["recent"])
        self.assertNotIn(chr(0x2014), text)


class ThePageComposesNothing(unittest.TestCase):
    def body(self):
        fn = PAGE[PAGE.index("function dcrRenderJev(j) {") :]
        return fn[: fn.index("\n}\n")]

    def test_every_string_the_card_draws_is_the_modules(self):
        body = self.body()
        self.assertEqual(set(re.findall(r'"([^"]*)"', body)), {"", "div"})
        self.assertNotIn("innerHTML", body)
        for key in ("j.title", "j.lede", "j.kinds", "j.recent", "j.empty"):
            self.assertIn(key, body)

    def test_the_poll_draws_it(self):
        poll = PAGE[PAGE.index("async function pollDecree() {") :]
        poll = poll[: poll.index("\n}\n")]
        self.assertIn("dcrRenderJev(p.jev);", poll)

    def test_the_markup_carries_no_sentence(self):
        card = PAGE[PAGE.index('<h2 id="dcrjevtitle"></h2>') :]
        card = card[: card.index("</div>\n    </div>")]
        self.assertNotIn("Jev", card.replace("dcrjev", ""))

    def test_the_decree_carries_the_card_and_the_read_never_raises(self):
        handler = SERVER[SERVER.index("    def _decree(self") :]
        handler = handler[: handler.index("    def _decree_post(self")]
        self.assertIn('payload["jev"] = _fetch_jev_view()', handler)
        fetch = SERVER[SERVER.index("def _fetch_jev_view()") :]
        fetch = fetch[: fetch.index("\n\n\n")]
        self.assertIn("return jevview.view([])", fetch)
        self.assertIn("FROM overseer_jev_judgment", fetch)
        self.assertNotIn("INSERT", fetch)


if __name__ == "__main__":
    unittest.main()
