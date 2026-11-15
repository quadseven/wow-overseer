"""GET /api/v2/journeys: every epic copy's journey, at the route seam.

Run against the in-memory realm reader, which raises on any statement it was
not given, so what the handler reads is checked too.
"""

import pathlib
import sys
import types
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import apiv2
    import realmread
    from apiv2 import journeys
    from test_apiv2_guilds import FAMILIES

AXE = {
    "entry": 2291,
    "item_name": "Kang the Decapitator",
    "quality": 4,
    "class": 2,
    "subclass": 1,
    "inventory_type": 17,
    "allowable_class": -1,
    "required_level": 51,
    "displayid": 7,
}


def ev(id_, who, kind, guid, at, **kw):
    row = {
        "id": id_, "character_name": who, "kind": kind, "subject_id": 2291,
        "subject_name": "Kang the Decapitator", "subject_quality": 4, "detail": "",
        "map": 230, "zone": 1584, "at": at, "prior_state": "", "prior_name": "",
        "item_guid": guid, "counterpart": "", "via": "", "source": "",
    }  # fmt: skip
    row.update(kw)
    return row


EVENTS = [
    ev(1, "Zug", "item_loot", 11, 100, via="greed", source="Anvilrage Footman"),
    ev(2, "Zug", "item_given", 11, 200, via="trade", counterpart="Oz"),
    ev(3, "Grug", "item_loot", 22, 300, via="need", source="Lord Roccor"),
]
SALES = [
    {"id": 9, "character_name": "Oz", "kind": "vendor_sale", "subject_id": 2291,
     "detail": "1 for 44580 copper", "map": 0, "zone": 0, "at": 250}
]  # fmt: skip
MEMBERS = [
    {"name": "Zug", "class": 8, "level": 55, "guild": "Bonkers"},
    {"name": "Oz", "class": 8, "level": 55, "guild": "Bonkers"},
    {"name": "Crag", "class": 1, "level": 58, "guild": "Bonkers"},
    {"name": "Grug", "class": 1, "level": 60, "guild": "Cave"},
]


class Ctx:
    def __init__(self, events=EVENTS, epics=None):
        found = epics if epics is not None else [
            {"item_guid": r["item_guid"], "subject_id": r["subject_id"]} for r in events
        ]  # fmt: skip
        self.read = realmread.Memory(
            {
                journeys.EPICS_SQL: found,
                journeys.EVENTS_SQL: list(events),
                journeys.SALES_SQL: list(SALES),
                journeys.COUNCIL_SQL: [],
                journeys.MEMBERS_SQL: list(MEMBERS),
                journeys.ITEMS_SQL: [AXE],
            }
        )
        self.server = types.SimpleNamespace()
        self.families = FAMILIES


def get(ctx, **q):
    return apiv2.handle("/api/v2/journeys", {k: [v] for k, v in q.items()}, ctx)


class TheRoute(unittest.TestCase):
    def test_route_is_registered(self):
        self.assertIn("/api/v2/journeys", apiv2.ROUTES)

    def test_every_journey_newest_first_with_its_item(self):
        status, out = get(Ctx())
        self.assertEqual(status, 200)
        self.assertEqual([j["item_guid"] for j in out["journeys"]], [22, 11])
        first = out["journeys"][0]
        self.assertEqual(first["item"]["entry"], 2291)
        self.assertEqual(first["item"]["name"], "Kang the Decapitator")
        self.assertEqual(first["item"]["quality"], 4)
        self.assertIn("basis", out)

    def test_a_sale_and_its_flag_reach_the_payload(self):
        _s, out = get(Ctx(), guild="bonkers")
        j = out["journeys"][0]
        self.assertEqual(j["ending"]["state"], "sold")
        self.assertIn(
            "Oz sold it to a vendor for 4g 45s while Crag could have used it.",
            j["flags"],
        )

    def test_filters_by_guild_and_by_character(self):
        _s, out = get(Ctx(), guild="cave")
        self.assertEqual([j["item_guid"] for j in out["journeys"]], [22])
        self.assertEqual(out["guild"], "Cave")
        _s, out = get(Ctx(), name="Oz")
        self.assertEqual([j["item_guid"] for j in out["journeys"]], [11])

    def test_a_guild_outside_the_family_guilds_is_refused(self):
        status, out = get(Ctx(), guild="Adventurer Unionx")
        self.assertEqual(status, 404)

    def test_a_name_outside_the_members_is_refused_before_any_read(self):
        ctx = Ctx()
        status, _out = get(ctx, name="Stranger")
        self.assertEqual(status, 404)
        status, _out = get(ctx, name="Bad;name")
        self.assertEqual(status, 400)
        self.assertEqual(ctx.read.asked, [])

    def test_no_epic_on_record_is_an_empty_list_not_an_error(self):
        status, out = get(Ctx(events=[], epics=[]))
        self.assertEqual((status, out["journeys"]), (200, []))
        self.assertTrue(out["empty"])


if __name__ == "__main__":
    unittest.main()
