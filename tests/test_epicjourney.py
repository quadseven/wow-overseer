"""The epic journey builder: event rows in, one journey per item copy out.

A pure module, so every test hands it rows shaped like the realm's own
overseer_event and overseer_loot_council rows and reads the journeys back.
"""

import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import epicjourney  # noqa: E402

KANG = 2291
BRD = 230  # a dungeon map the site names
# item_template rows: a two-handed axe, and a plate chest.
ITEMS = {
    KANG: {
        "entry": KANG,
        "item_name": "Kang the Decapitator",
        "quality": 4,
        "class": 2,
        "subclass": 1,
        "inventory_type": 17,
        "allowable_class": -1,
        "required_level": 51,
    },
    500: {
        "entry": 500,
        "item_name": "Test Breastplate",
        "quality": 4,
        "class": 4,
        "subclass": 4,
        "inventory_type": 5,
        "allowable_class": -1,
        "required_level": 50,
    },
}
# class ids: 1 warrior, 4 rogue, 8 mage
MEMBERS = [
    {"name": "Zug", "class": 8, "level": 55, "guild": "Bonkers"},
    {"name": "Uzza", "class": 8, "level": 55, "guild": "Bonkers"},
    {"name": "Ugga", "class": 8, "level": 55, "guild": "Bonkers"},
    {"name": "Grog", "class": 4, "level": 55, "guild": "Bonkers"},
    {"name": "Saevor", "class": 1, "level": 58, "guild": "Bonkers"},
]
FAMILIES = {"Zug": ["Zug", "Uzza", "Ugga", "Grog"]}


def ev(id_, who, kind, guid, at, **kw):
    row = {
        "id": id_,
        "character_name": who,
        "kind": kind,
        "subject_id": kw.pop("entry", KANG),
        "subject_name": kw.pop("name", "Kang the Decapitator"),
        "subject_quality": kw.pop("quality", 4),
        "detail": "",
        "map": BRD,
        "zone": 1584,
        "at": at,
        "prior_state": "",
        "prior_name": "",
        "item_guid": guid,
        "counterpart": "",
        "via": "",
        "source": "",
    }
    row.update(kw)
    return row


def sale(id_, who, at, copper, entry=KANG, count=1):
    return {
        "id": id_,
        "character_name": who,
        "kind": "vendor_sale",
        "subject_id": entry,
        "subject_name": "",
        "subject_quality": 0,
        "detail": "%d for %d copper" % (count, copper),
        "map": 0,
        "zone": 85,
        "at": at,
        "item_guid": 0,
    }


# The three journeys of one sword on the dev realm, as the brief tells them.
ROWS = [
    ev(1, "Zug", "item_loot", 11, 100, via="greed", source="Anvilrage Footman"),
    ev(2, "Zug", "loot_won", 11, 100, via="greed", source="Anvilrage Footman"),
    ev(3, "Zug", "item_given", 11, 200, via="mail", counterpart="Saevor",
       source="Mailbox", map=0, zone=10),
    ev(4, "Uzza", "item_loot", 22, 300, via="greed", source="Doomforge Craftsman"),
    ev(5, "Uzza", "loot_won", 22, 300, via="greed", source="Doomforge Craftsman"),
    ev(6, "Ugga", "item_loot", 33, 500, via="greed", source="Twilight Emissary"),
    ev(7, "Ugga", "loot_won", 33, 500, via="greed", source="Twilight Emissary"),
    ev(8, "Ugga", "item_given", 33, 510, via="trade", counterpart="Grog"),
    ev(9, "Ugga", "tidy", 33, 520, via="trade", counterpart="Grog", quality=0,
       detail="moved: Ugga passed Kang the Decapitator to Grog (in hand), "
       "confirmed in Grog's bags"),
]  # fmt: skip
SALES = [sale(20, "Uzza", 400, 44580), sale(21, "Grog", 600, 44580)]


def build(rows=ROWS, sales=SALES, council=(), members=MEMBERS, **kw):
    return epicjourney.build(
        rows,
        sales=sales,
        council=council,
        members=members,
        items=kw.pop("items", ITEMS),
        zones=kw.pop("zones", {10: "Duskwood"}),
        families=kw.pop("families", FAMILIES),
        **kw,
    )


def by_guid(journeys):
    return {j["item_guid"]: j for j in journeys}


class GroupedByCopy(unittest.TestCase):
    def test_three_copies_of_one_item_are_three_journeys_newest_first(self):
        out = build()
        self.assertEqual([j["item_guid"] for j in out], [33, 22, 11])
        self.assertTrue(all(j["name"] == "Kang the Decapitator" for j in out))

    def test_a_copy_below_epic_is_not_a_journey(self):
        rows = [ev(1, "Zug", "item_loot", 44, 100, via="need", quality=3)]
        self.assertEqual(build(rows=rows, sales=[]), [])

    def test_the_roll_and_the_loot_row_are_one_step(self):
        steps = by_guid(build())[11]["steps"]
        self.assertEqual([s["kind"] for s in steps], ["won", "handed"])


class TheTimeline(unittest.TestCase):
    def test_a_greed_win_names_the_creature_and_the_dungeon(self):
        won = by_guid(build())[11]["steps"][0]
        self.assertEqual(won["who"], "Zug")
        self.assertEqual(won["how"], "greed")
        self.assertIn("Zug won it on a greed roll from Anvilrage Footman", won["text"])
        self.assertIn("Blackrock Depths", won["text"])

    def test_a_mail_to_a_guild_member_outside_the_family_says_so(self):
        handed = by_guid(build())[11]["steps"][1]
        self.assertEqual(
            handed["text"],
            "Zug mailed it to Saevor, a guild member outside the family.",
        )
        self.assertEqual(by_guid(build())[11]["ending"]["who"], "Saevor")
        self.assertEqual(by_guid(build())[11]["ending"]["state"], "in_bags")

    def test_a_tidy_that_confirms_a_trade_is_not_a_second_hand_over(self):
        steps = by_guid(build())[33]["steps"]
        self.assertEqual([s["kind"] for s in steps], ["won", "handed", "sold"])
        self.assertEqual(steps[1]["text"], "Ugga traded it to Grog.")

    def test_a_tidy_on_its_own_is_a_hand_over(self):
        rows = [
            ev(1, "Zug", "item_loot", 11, 100, via="need", source="X"),
            ev(2, "Zug", "tidy", 11, 150, via="trade", counterpart="Grog", quality=0,
               detail="moved: Zug passed Kang the Decapitator to Grog (in hand)"),
        ]  # fmt: skip
        steps = build(rows=rows, sales=[])[0]["steps"]
        self.assertEqual(steps[1]["kind"], "handed")
        self.assertIn("passed it to Grog", steps[1]["text"])

    def test_an_equip_names_what_it_replaced(self):
        rows = [
            ev(1, "Saevor", "item_loot", 55, 100, via="need", source="Lord Roccor",
               entry=500, name="Test Breastplate"),
            ev(2, "Saevor", "item_equip", 55, 110, prior_state="item",
               prior_name="Old Chest", entry=500, name="Test Breastplate"),
        ]  # fmt: skip
        j = build(rows=rows, sales=[])[0]
        self.assertEqual(j["steps"][1]["text"], "Saevor equipped it over Old Chest.")
        self.assertEqual(j["ending"]["state"], "worn")
        self.assertEqual(
            j["ending"]["text"], "Worn by Saevor, as far as the record shows."
        )


class TheEnding(unittest.TestCase):
    def test_a_sale_without_a_guid_joins_the_copy_its_seller_held(self):
        j = by_guid(build())
        self.assertEqual(j[22]["ending"]["state"], "sold")
        self.assertEqual(
            j[22]["ending"]["text"], "Sold to a vendor by Uzza for 4g 45s."
        )
        self.assertEqual(j[22]["ending"]["copper"], 44580)
        self.assertEqual(j[33]["ending"]["who"], "Grog")
        self.assertEqual(j[11]["ending"]["state"], "in_bags")

    def test_a_sale_by_someone_who_never_held_the_copy_joins_nothing(self):
        out = build(sales=[sale(20, "Saevor", 50, 44580)])
        self.assertTrue(all(j["ending"]["state"] != "sold" for j in out))

    def test_a_sale_is_used_once(self):
        rows = ROWS[3:5] + [
            ev(10, "Uzza", "item_loot", 23, 310, via="need", source="Y"),
        ]
        out = by_guid(build(rows=rows, sales=[sale(20, "Uzza", 400, 44580)]))
        sold = [g for g, j in out.items() if j["ending"]["state"] == "sold"]
        self.assertEqual(sold, [23])  # the copy got last, then nothing left to sell


class TheCouncil(unittest.TestCase):
    COUNCIL = {
        "council_key": "roll:1",
        "kind": "roll",
        "family": "Zug",
        "source": "",
        "item_entry": KANG,
        "item_name": "Kang the Decapitator",
        "item_quality": 4,
        "candidates": json.dumps(
            [
                {
                    "name": "Saevor",
                    "family": False,
                    "wearable": True,
                    "comparison": "better",
                    "score": 180.5,
                    "upgrade_percent": 17,
                },
                {
                    "name": "Zug",
                    "family": True,
                    "wearable": False,
                    "comparison": "not_better",
                    "score": 0,
                    "upgrade_percent": 0,
                },
            ]
        ),  # fmt: skip
        "heuristic": "Saevor",
        "heuristic_why": "the biggest upgrade",
        "status": "given",
        "recipient": "Saevor",
        "reason": "Heuristic: the biggest upgrade",
        "decided_by": "heuristic",
        "given_to": "Zug",
        "item_guid": 11,
        "outcome": "won on the roll",
    }

    def test_the_councils_decision_rides_on_its_copy(self):
        j = by_guid(build(council=[self.COUNCIL]))
        c = j[11]["council"]
        self.assertEqual(c["decided_by"], "heuristic")
        self.assertEqual(c["recipient"], "Saevor")
        self.assertEqual(c["heuristic_why"], "the biggest upgrade")
        self.assertEqual(
            [(x["name"], x["score"], x["upgrade_percent"]) for x in c["candidates"]],
            [("Saevor", 180.5, 17), ("Zug", 0.0, 0)],
        )
        self.assertIsNone(j[22]["council"])
        self.assertIn("council", [s["kind"] for s in j[11]["steps"]])

    def test_a_pick_that_went_to_someone_else_is_flagged(self):
        flags = by_guid(build(council=[self.COUNCIL]))[11]["flags"]
        self.assertIn("The loot council picked Saevor, but Zug got it.", flags)


class TheFlags(unittest.TestCase):
    def test_a_greed_win_by_a_member_who_cannot_use_it_is_flagged(self):
        flags = by_guid(build())[11]["flags"]
        self.assertTrue(
            any("Zug won it on greed but cannot use it" in f for f in flags)
        )
        self.assertTrue(any("Saevor could have" in f for f in flags), flags)

    def test_an_epic_sold_while_a_guild_member_could_wear_it_is_flagged(self):
        flags = by_guid(build())[33]["flags"]
        self.assertIn(
            "Grog sold it to a vendor for 4g 45s while Saevor could have used it.",
            flags,
        )

    def test_a_seller_who_could_have_used_it_is_named_as_such(self):
        members = [
            dict(m, **{"class": 1}) if m["name"] == "Grog" else m for m in MEMBERS
        ]
        flags = by_guid(build(members=members))[33]["flags"]
        self.assertIn(
            "Grog sold it to a vendor for 4g 45s though it was Grog's own kind of piece, "
            "and Saevor could have used it too.",
            flags,
        )

    def test_a_sale_nobody_could_use_is_not_flagged_as_a_sale(self):
        members = [m for m in MEMBERS if m["name"] != "Saevor"]
        flags = by_guid(build(members=members))[33]["flags"]
        self.assertFalse(any("sold" in f for f in flags))

    def test_an_unknown_class_is_not_measured_and_not_flagged(self):
        flags = by_guid(build(members=[]))[11]["flags"]
        self.assertEqual(flags, [])


class CanUse(unittest.TestCase):
    def test_weapons_follow_the_class_weapon_skills(self):
        axe = ITEMS[KANG]
        self.assertTrue(epicjourney.can_use(axe, {"class": 1, "level": 60}))
        self.assertFalse(epicjourney.can_use(axe, {"class": 8, "level": 60}))

    def test_armor_is_the_classes_own_kind_at_its_level(self):
        plate = ITEMS[500]
        self.assertTrue(epicjourney.can_use(plate, {"class": 1, "level": 50}))
        self.assertFalse(epicjourney.can_use(plate, {"class": 1, "level": 39}))
        self.assertFalse(epicjourney.can_use(plate, {"class": 4, "level": 60}))

    def test_a_lighter_armor_kind_can_be_worn_but_is_not_the_classes_own(self):
        mail = dict(ITEMS[500], subclass=3)
        warrior = {"class": 1, "level": 60}
        self.assertTrue(epicjourney.can_use(mail, warrior))
        self.assertFalse(epicjourney.can_use(mail, warrior, own_kind=True))

    def test_a_council_that_picked_nobody_does_not_take_the_item(self):
        council = dict(TheCouncil.COUNCIL, recipient="", heuristic="", given_to="Zug")
        j = by_guid(build(council=[council]))[11]
        self.assertEqual(j["ending"]["who"], "Saevor")
        self.assertIn("The loot council picked nobody", j["steps"][1]["text"])

    def test_the_required_level_and_class_mask_count(self):
        plate = ITEMS[500]
        self.assertFalse(epicjourney.can_use(plate, {"class": 1, "level": 45}))
        only_paladin = dict(plate, allowable_class=2)
        self.assertFalse(epicjourney.can_use(only_paladin, {"class": 1, "level": 60}))

    def test_an_unknown_item_or_class_is_none(self):
        self.assertIsNone(epicjourney.can_use({}, {"class": 1, "level": 60}))
        self.assertIsNone(epicjourney.can_use(ITEMS[KANG], {}))


class Pick(unittest.TestCase):
    def test_filters_by_guild_and_character(self):
        out = build()
        self.assertEqual(len(epicjourney.pick(out, guild="Bonkers")), 3)
        self.assertEqual(epicjourney.pick(out, guild="Cave"), [])
        self.assertEqual(
            [j["item_guid"] for j in epicjourney.pick(out, name="grog")], [33]
        )
        self.assertEqual(
            [j["item_guid"] for j in epicjourney.pick(out, name="Saevor")], [11]
        )


if __name__ == "__main__":
    unittest.main()
