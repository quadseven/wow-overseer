"""Where each worn item came from, in the character sheet's tooltip (#371).

Three layers: the builder (gearorigin) with rows shaped like the module's,
the /api/armory/member endpoint with the database amputated, and the page's
character sheet read as text.
"""

import io
import json
import logging
import pathlib
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import gearorigin  # noqa: E402
import map_server  # noqa: E402  (must follow the pymysql stub)

map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")

T0 = datetime(2026, 9, 12, 18, 0)
ZONES = {40: "Westfall"}
# skill -> spell -> [name, ..., created item entry], the craft book's shape.
CRAFTBOOK = {"197": {"3915": ["Brown Linen Shirt", 1, 10, 1, 4344]}}


def event(kind, entry, at, who="Aldren", **extra):
    row = {
        "id": int(at.timestamp()),
        "character_name": who,
        "kind": kind,
        "subject_id": entry,
        "subject_name": extra.pop("subject_name", "thing %d" % entry),
        "subject_quality": extra.pop("quality", 2),
        "map": extra.pop("map", 0),
        "zone": extra.pop("zone", 0),
        "first_seen": at,
        "last_seen": at,
    }
    row.update(extra)
    return row


def bought(kind, entry, at, vendor=None, outcome="bought"):
    result = {"outcome": outcome, "item": {"entry": entry, "name": "x"}}
    if vendor:
        result["vendor"] = {"entry": 1, "name": vendor}
    return {
        "kind": kind,
        "result": json.dumps(result),
        "created_at": at,
        "updated_at": at,
    }


def origin_of(entry, events=(), commands=(), rewards=None, guid=0):
    got = gearorigin.origins(
        "Aldren",
        [{"entry": entry, "item_guid": guid}],
        list(events),
        list(commands),
        rewards or {},
        CRAFTBOOK,
        ZONES,
    )
    return got[str(entry)]


class EachSourceSaysWhatItIs(unittest.TestCase):
    def test_a_quest_reward_names_the_quest_and_the_day(self):
        rewards = {100: {"items": [], "choices": [2000, 2001]}}
        events = [
            event("quest_reward", 100, T0, subject_name="The Defias Brotherhood"),
            event("item_equip", 2001, T0 + timedelta(seconds=20)),
        ]
        got = origin_of(2001, events, rewards=rewards)
        self.assertEqual(
            got,
            {
                "known": True,
                "line": "Quest reward: The Defias Brotherhood, 12 September 2026",
            },
        )

    def test_a_vendor_buy_names_the_vendor_and_an_auction_buy_says_auction(self):
        got = origin_of(3000, commands=[bought("buy", 3000, T0, vendor="Gina Lang")])
        self.assertEqual(got["line"], "Bought from Gina Lang, 12 September 2026")
        got = origin_of(3000, commands=[bought("auction", 3000, T0)])
        self.assertEqual(got["line"], "Bought at auction, 12 September 2026")

    def test_a_refused_purchase_is_not_a_purchase(self):
        got = origin_of(3000, commands=[bought("buy", 3000, T0, outcome="refused")])
        self.assertEqual(got, {"known": False, "line": "Origin not recorded"})

    def test_a_craft_is_matched_through_the_craft_book(self):
        got = origin_of(4344, [event("craft", 3915, T0)])
        self.assertEqual(got["line"], "Crafted, 12 September 2026")

    def test_a_drop_joined_by_the_items_own_guid(self):
        events = [
            event(
                "item_loot",
                5000,
                T0,
                quality=3,
                item_guid=77,
                via="loot",
                source="Mr. Smite",
                map=36,
            ),
            event("item_given", 5000, T0, who="Morka", quality=3, item_guid=78),
        ]
        got = origin_of(5000, events, guid=77)
        self.assertEqual(
            got["line"], "Dropped by Mr. Smite in The Deadmines, 12 September 2026"
        )

    def test_a_hand_over_names_the_member_who_gave_it(self):
        events = [
            event(
                "item_given",
                5000,
                T0,
                who="Morka",
                quality=3,
                item_guid=77,
                via="trade",
                counterpart="Aldren",
            )
        ]
        got = origin_of(5000, events, guid=77)
        self.assertEqual(
            got["line"], "Handed down from Morka by trade, 12 September 2026"
        )

    def test_nothing_recorded_says_so_and_where_it_was_first_worn(self):
        got = origin_of(6000, [event("item_equip", 6000, T0, zone=40)])
        self.assertEqual(
            got,
            {
                "known": False,
                "line": "Origin not recorded; first worn in Westfall, 12 September 2026",
            },
        )
        self.assertEqual(origin_of(6000)["line"], "Origin not recorded")


class TheSourceIsTimedAgainstTheFirstEquip(unittest.TestCase):
    def test_the_latest_source_before_the_first_equip_wins(self):
        rewards = {100: {"items": [(2000, 1)], "choices": []}}
        events = [
            event("quest_reward", 100, T0, subject_name="Early Quest"),
            event("item_equip", 2000, T0 + timedelta(hours=1)),
        ]
        # Bought after it was already worn: not how it was got.
        late = bought("buy", 2000, T0 + timedelta(days=1), vendor="Somebody")
        got = origin_of(2000, events, [late], rewards)
        self.assertEqual(got["line"], "Quest reward: Early Quest, 12 September 2026")
        # Bought between the turn-in and the equip: the purchase is nearer.
        mid = bought("buy", 2000, T0 + timedelta(minutes=30), vendor="Gina Lang")
        got = origin_of(2000, events, [mid], rewards)
        self.assertEqual(got["line"], "Bought from Gina Lang, 12 September 2026")

    def test_the_craft_book_reads_the_created_item(self):
        self.assertEqual(gearorigin.craft_items(CRAFTBOOK), {3915: 4344})
        self.assertEqual(gearorigin.craft_items({"1": {"5": ["First Aid", 0]}}), {})


class FakeHandler(map_server.Handler):
    def __init__(self, path):
        self.path = path
        self.rfile = io.BytesIO(b"")
        self.headers = {}
        self.sent = []

    def _send(self, code, ctype, body, cache_control="no-store"):
        self.sent.append((code, ctype, body))


ARMORY = {
    "members": [{"name": "Aldren", "slots": []}],
    "doll": {"left": [], "right": []},
}
ROWS = {
    "worn": [{"entry": 6000, "item_guid": 9}],
    "event_rows": [],
    "command_rows": [bought("buy", 6000, T0, vendor="Gina Lang")],
    "quest_rewards": {},
}


@mock.patch.object(map_server, "_fetch_family_groups", return_value=[("A", ["Aldren"])])
@mock.patch.object(map_server, "_is_family_guildmate", return_value=True)
@mock.patch.object(
    map_server, "_fetch_armory", side_effect=lambda names: {"equip_event_rows": []}
)
@mock.patch.object(map_server.armory, "build_armory", return_value=ARMORY)
class TheMemberEndpoint(unittest.TestCase):
    def get(self):
        h = FakeHandler("/api/armory/member?name=Aldren")
        h.do_GET()
        return h.sent[-1][0], json.loads(h.sent[-1][2])

    def test_the_sheet_carries_an_origin_line_per_worn_entry(self, *_):
        with mock.patch.object(map_server, "_fetch_gear_origin", return_value=ROWS):
            code, body = self.get()
        self.assertEqual(code, 200)
        self.assertEqual(
            body["origin"],
            {
                "6000": {
                    "known": True,
                    "line": "Bought from Gina Lang, 12 September 2026",
                }
            },
        )

    def test_a_failed_origin_read_still_draws_the_sheet(self, *_):
        with mock.patch.object(
            map_server, "_fetch_gear_origin", side_effect=RuntimeError("down")
        ):
            code, body = self.get()
        self.assertEqual(code, 200)
        self.assertEqual(body["origin"], {})
        self.assertEqual(body["member"]["name"], "Aldren")


class ThePageShowsIt(unittest.TestCase):
    def test_the_character_sheet_hands_the_line_to_the_tooltip(self):
        sheet = PAGE[PAGE.index("async function vcCharacter") :]
        sheet = sheet[: sheet.index("\n}\n")]
        self.assertIn("const origin = p.origin || {};", sheet)
        self.assertIn("const from = origin[String(s.entry)];", sheet)
        self.assertIn('why: from ? from.line : ""', sheet)
        tip = PAGE[PAGE.index("async function vcShowTip") :]
        tip = tip[: tip.index("\n}\n")]
        self.assertIn(
            'if (item.why) t.appendChild(el("div", "vcsub vcwhy", item.why));', tip
        )


if __name__ == "__main__":
    unittest.main()
