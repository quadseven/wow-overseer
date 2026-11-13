"""A worn grey or white piece gives way to a usable green with more item level (#2372)."""

import contextlib
import unittest

from test_family_economy_parity import _load

import gearup


def offer(inv, subclass, item_class, ilvl, quality, entry=500, id=9, price=100):
    return {
        "id": id,
        "entry": entry,
        "class": item_class,
        "subclass": subclass,
        "InventoryType": inv,
        "RequiredLevel": 1,
        "AllowableClass": 0,
        "ItemLevel": ilvl,
        "Quality": quality,
        "buyout": price,
    }


def warrior(worn):
    return {
        "class": "warrior",
        "level": 52,
        "purse": 100000,
        "skills": {"weapons": {8}},
        "equipped": worn,
    }


WHITE_GREATSWORD = {"item_level": 45, "item_class": 2, "item_subclass": 8, "quality": 1}
GREEN_GREATSWORD = offer(17, 8, 2, ilvl=46, quality=2)


class WhiteFloorTests(unittest.TestCase):
    def test_a_worn_white_weapon_gives_way_to_a_usable_green_one_level_up(self):
        buys = gearup.plan_buys(
            {"Zug": warrior({"mainhand": WHITE_GREATSWORD})}, [GREEN_GREATSWORD]
        )

        self.assertEqual([("mainhand", 9)], [(b.slot, b.listing_id) for b in buys])

    def test_a_worn_green_weapon_still_needs_the_usual_gain(self):
        green = dict(WHITE_GREATSWORD, quality=2)

        buys = gearup.plan_buys(
            {"Zug": warrior({"mainhand": green})}, [GREEN_GREATSWORD]
        )

        self.assertEqual((), buys)

    def test_a_white_offer_does_not_replace_a_worn_white_on_quality(self):
        white_offer = offer(17, 8, 2, ilvl=46, quality=1)

        buys = gearup.plan_buys(
            {"Zug": warrior({"mainhand": WHITE_GREATSWORD})}, [white_offer]
        )

        self.assertEqual((), buys)

    def test_the_green_must_still_carry_more_item_level(self):
        lower = offer(17, 8, 2, ilvl=44, quality=2)

        buys = gearup.plan_buys(
            {"Zug": warrior({"mainhand": WHITE_GREATSWORD})}, [lower]
        )

        self.assertEqual((), buys)

    def test_a_worn_white_trinket_is_kept_since_its_effect_is_unpriced(self):
        commission = {
            "item_level": 50,
            "item_class": 4,
            "item_subclass": 0,
            "quality": 1,
        }
        trinket = offer(12, 0, 4, ilvl=51, quality=2)
        character = warrior({"trinket1": commission, "trinket2": commission})

        self.assertEqual((), gearup.plan_buys({"Zug": character}, [trinket]))


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self.rows


class TheGearupFactsCarryWornQuality(unittest.TestCase):
    def test_each_worn_slot_carries_the_item_quality(self):
        row = {
            "name": "Zug",
            "class_id": 1,
            "level": 52,
            "purse": 100,
            "slot": 15,
            "item_level": 45,
            "item_class": 2,
            "item_subclass": 8,
            "item_quality": 1,
        }
        cursor = _Cursor([row])

        @contextlib.contextmanager
        def connect():
            yield types_conn(cursor)

        ns = _load(
            ["_fetch_gearup_facts"],
            {
                "_GEARUP_EQUIPPED_SQL": "%s",
                "_connect": connect,
                "_read_weapon_skills": lambda cur, names: {},
            },
        )

        facts = ns["_fetch_gearup_facts"](["Zug"])

        self.assertEqual(1, facts["Zug"]["equipped"]["mainhand"]["quality"])


def types_conn(cursor):
    class _Conn:
        @contextlib.contextmanager
        def cursor(self):
            yield cursor

    return _Conn()


if __name__ == "__main__":
    unittest.main()
