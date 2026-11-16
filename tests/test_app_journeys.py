"""The Epic journeys section, drawn by app/views/_journeys.js.

Run under node against small stand-ins for the browser, like the other app
view tests: the markup is checked as text.
"""

import json
import pathlib
import unittest

from test_app_flagship import app_file, needs_node, run_node, text_of

API_STUB = (
    'export const u = (p) => "/m" + p;\n'
    "export const peek = () => ({ data: undefined });\n"
    "export const load = () => Promise.resolve();\n"
)
FILES = {
    "views/_journeys.js": None,
    "models/time.js": None,
    "ui.js": None,
    "api.js": API_STUB,
}

SOLD = {
    "item_guid": 33,
    "item": {
        "entry": 2291,
        "name": "Kang the Decapitator",
        "quality": 4,
        "icon": "inv_axe",
    },
    "who": ["Ugga", "Grog"],
    "guilds": ["Bonkers"],
    "at": 600,
    "since": 500,
    "steps": [
        {
            "at": 500,
            "kind": "won",
            "who": "Ugga",
            "text": "Ugga won it on a greed roll from Twilight Emissary in Blackrock Depths.",
        },
        {
            "at": 510,
            "kind": "handed",
            "who": "Ugga",
            "to": "Grog",
            "text": "Ugga traded it to Grog.",
        },
        {
            "at": 600,
            "kind": "sold",
            "who": "Grog",
            "copper": 44580,
            "text": "Grog sold it to a vendor for 4g 45s.",
        },
    ],
    "council": None,
    "ending": {
        "state": "sold",
        "who": "Grog",
        "copper": 44580,
        "text": "Sold to a vendor by Grog for 4g 45s.",
    },
    "flags": ["Grog sold it to a vendor for 4g 45s while Saevor could have used it."],
}
COUNCIL = {
    "item_guid": 11,
    "item": {"entry": 2291, "name": "Kang the Decapitator", "quality": 4},
    "who": ["Zug"],
    "guilds": ["Bonkers"],
    "at": 100,
    "since": 100,
    "steps": [
        {"at": 100, "kind": "won", "who": "Zug", "text": "Zug won it on a need roll."}
    ],
    "council": {
        "decided_by": "heuristic",
        "recipient": "Zug",
        "given_to": "Zug",
        "heuristic_why": "the biggest upgrade",
        "reason": "",
        "kind": "roll",
        "candidates": [
            {
                "name": "Zug",
                "score": 180.5,
                "upgrade_percent": 17,
                "wearable": True,
                "family": True,
            }
        ],
    },  # fmt: skip
    "ending": {
        "state": "in_bags",
        "who": "Zug",
        "text": "In Zug's bags, as far as the record shows.",
    },
    "flags": [],
}


def draw(read, who=""):
    files = {k: (v if v is not None else app_file(k)) for k, v in FILES.items()}
    out = run_node(
        files,
        "globalThis.window = { addEventListener() {} };\n"
        'const J = await import("./views/_journeys.js");\n'
        "console.log(JSON.stringify({m: String(J.section(%s, %s))}));\n"
        % (json.dumps(read), json.dumps(who)),
    )
    return out["m"]


def ready(*journeys):
    return {
        "data": {"journeys": list(journeys), "empty": "No epic yet.", "basis": "How."},
        "loading": False,
    }


@needs_node
class TheSection(unittest.TestCase):
    def test_each_journey_is_a_card_with_its_item_link_and_every_step(self):
        m = draw(ready(SOLD, COUNCIL))
        self.assertEqual(m.count('class="card ej-card"'), 2)
        self.assertIn('data-item="2291"', m)
        self.assertIn("wowhead", m)
        t = text_of(m)
        self.assertIn("Ugga traded it to Grog.", t)
        self.assertIn("Sold to a vendor by Grog for 4g 45s.", t)
        self.assertLess(m.index("Ugga won it"), m.index("Ugga traded it"))

    def test_a_flag_is_one_plain_line_in_the_warning_tone(self):
        m = draw(ready(SOLD))
        self.assertIn('class="ej-flag"', m)
        self.assertIn("while Saevor could have used it.", text_of(m))

    def test_the_council_shows_candidates_scores_and_upgrade(self):
        t = text_of(draw(ready(COUNCIL)))
        self.assertIn("Zug", t)
        self.assertIn("180.5", t)
        self.assertIn("+17%", t)
        self.assertIn("decided by heuristic", t)
        self.assertIn("the biggest upgrade", t)

    def test_the_character_filter_keeps_only_their_journeys(self):
        m = draw(ready(SOLD, COUNCIL), "Grog")
        self.assertEqual(m.count('class="card ej-card"'), 1)
        self.assertIn('<option value="Grog" selected', m)
        self.assertIn('<option value="Zug"', m)

    def test_an_empty_record_says_so_and_a_pending_read_is_a_skeleton(self):
        self.assertIn("No epic yet.", draw(ready()))
        self.assertNotIn("No epic yet.", draw({"loading": True}))


class ThePhone(unittest.TestCase):
    def test_the_cards_wrap_long_words_and_the_filter_is_a_44px_target(self):
        css = (
            pathlib.Path(__file__).resolve().parent.parent / "app/views/journeys.css"
        ).read_text(encoding="utf-8")
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn("min-height: 44px", css)

    def test_the_guild_chronicle_draws_the_section(self):
        src = app_file("views/guild.js")
        self.assertIn("Epic journeys", src)
        self.assertIn("/api/v2/journeys?guild=", app_file("views/_journeys.js"))


if __name__ == "__main__":
    unittest.main()
