"""A guild run to a keyed wing seats a member who carries the key (#785), and
Dire Maul's doors are on the ladder once the finder finds their wings (#783).

The dungeon-clear brain used to open the Armory's and the Cathedral's doors,
Dire Maul's Gordok and Crescent doors and Blackrock Depths' Shadowforge gates
as if the tank held the key, which a party without it cannot do. It now opens a
keyed door only for a party member who carries the key or picks the lock, so a
guild run to a keyed wing must bring one: the Scarlet Key to the Armory and the
Cathedral, the Crescent Key to Dire Maul West and North, the Shadowforge Key to
Blackrock Depths. campaignplan.DOOR_KEYS already held a family's planned run to
the same rule; the guild runs now read the same table.

Each key has a natural way in, and none is ever granted: the Scarlet Key from
Doan's Strongbox in the Library, the Crescent Key from Pusillin in Dire Maul
East, the Shadowforge Key from the quest Dark Iron Legacy, the Key to the City
from Magistrate Barthilas in Stratholme.
"""

import datetime
import pathlib
import unittest

import campaignplan
import guildrun
import guildsocial as gs

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

WARRIOR, ROGUE, PRIEST, MAGE, WARLOCK = 1, 4, 5, 8, 9
PROTECTION = "12301"
HOLY = "14913"
HUMAN = 1
SCARLET_KEY, CRESCENT_KEY, SHADOWFORGE_KEY, KEY_TO_THE_CITY = 7146, 18249, 11000, 12382
NOW = datetime.datetime(2026, 10, 10, 20, 0, 0)
DOORS = guildrun.doors()
BY_KEYWORD = {d.keyword: d for d in DOORS}
ARMORY = BY_KEYWORD["scarlet-armory"]
# By Scarlet Monastery's doors, in Tirisfal Glades.
NEAR = (2870.0, -820.0)
ENTRANCES = {"189": {"map": 0, "x": 2913.0, "y": -802.0}}


def row(name, level, class_id, **kw):
    x, y = kw.pop("at", NEAR)
    out = {
        "name": name,
        "level": level,
        "class_id": class_id,
        "map_id": 0,
        "race": HUMAN,
        "zone_id": 85,
        "in_combat": 0,
        "health": 300,
        "group_leader": 0,
        "guild_name": "Cave",
        "talent_spells": None,
        "target_tree": "",
        "pos_x": x,
        "pos_y": y,
        "worn_slots": 6,
        "has_weapon": 1,
    }
    out.update(kw)
    return out


def mate(name, level, class_id, **kw):
    return gs.mate_from_row(row(name, level, class_id, **kw))


def armory_five(keys_for=None, key=SCARLET_KEY):
    """An asker and four guildmates at 37 and 38, inside both the Library's
    band (33 to 38) and the Armory's (36 to 41); `keys_for` names the one who
    carries the key."""

    def k(name):
        return {"door_keys": str(key)} if name == keys_for else {}

    return [
        mate("Auren", 38, ROGUE, **k("Auren")),
        mate(
            "Tanky", 38, WARRIOR, talent_spells=PROTECTION, has_shield=1, **k("Tanky")
        ),
        mate("Healy", 38, PRIEST, talent_spells=HOLY, **k("Healy")),
        mate("Zappy", 37, MAGE, **k("Zappy")),
        mate("Locky", 38, WARLOCK, **k("Locky")),
    ]


def ask(id_, asker, target="scarlet-armory"):
    return gs.ask_from_row(
        {
            "id": id_,
            "guild": "Cave",
            "asker": asker,
            "kind": "dungeon",
            "target": target,
            "target_label": "Scarlet Monastery (the Armory)",
            "roles_needed": "tank,healer,dps,dps",
            "reason": "",
            "said": "",
            "created_at": NOW - datetime.timedelta(minutes=2),
            "expires_at": NOW + datetime.timedelta(minutes=8),
            "state": "open",
            "run_id": None,
        }
    )


def yes(id_, ask_id, member, role):
    return gs.answer_from_row(
        {
            "id": id_,
            "ask_id": ask_id,
            "member": member,
            "role": role,
            "stance": "need",
            "said": "",
            "state": "yes",
        }
    )


def armory_yeses():
    return [
        yes(1, 7, "Tanky", "tank"),
        yes(2, 7, "Healy", "healer"),
        yes(3, 7, "Zappy", "dps"),
        yes(4, 7, "Locky", "dps"),
    ]


def free_of(mates):
    return {m.member.name: m.member for m in mates}


class OneKeyTableForFamiliesAndGuilds(unittest.TestCase):
    def test_every_keyed_wing_names_its_key(self):
        keys = {k: v[0] for k, v in campaignplan.DOOR_KEYS.items()}
        self.assertEqual(keys["scarlet-armory"], SCARLET_KEY)
        self.assertEqual(keys["scarlet-cathedral"], SCARLET_KEY)
        self.assertEqual(keys["dire-maul-west-north"], CRESCENT_KEY)
        self.assertEqual(keys["dire-maul-north"], CRESCENT_KEY)
        self.assertEqual(keys["blackrock-depths"], SHADOWFORGE_KEY)
        self.assertEqual(keys["stratholme-undead"], KEY_TO_THE_CITY)
        self.assertNotIn("dire-maul-east-east", keys, "the East wing needs no key")
        self.assertNotIn("scarlet-library", keys)

    def test_every_key_is_read(self):
        for entry in (SCARLET_KEY, CRESCENT_KEY, SHADOWFORGE_KEY, KEY_TO_THE_CITY):
            self.assertIn(entry, campaignplan.KEY_ITEMS)

    def test_the_door_carries_its_key(self):
        self.assertEqual(ARMORY.key, SCARLET_KEY)
        self.assertEqual(ARMORY.key_name, "the Scarlet Key")
        self.assertEqual(BY_KEYWORD["blackrock-depths"].key, SHADOWFORGE_KEY)
        self.assertEqual(BY_KEYWORD["deadmines"].key, 0)


class AMemberSaysWhichKeysItCarries(unittest.TestCase):
    def test_the_keys_column_is_read(self):
        m = guildrun.member_from_row(row("Auren", 38, ROGUE, door_keys="7146,11000"))
        self.assertEqual(m.keys, frozenset({SCARLET_KEY, SHADOWFORGE_KEY}))

    def test_no_keys_read_is_no_key(self):
        m = guildrun.member_from_row(row("Auren", 38, ROGUE, door_keys=None))
        self.assertEqual(m.keys, frozenset())

    def test_the_holder_of_a_keyed_door_is_named(self):
        five = [m.member for m in armory_five(keys_for="Zappy")]
        self.assertEqual(guildrun.key_holder(five, ARMORY).name, "Zappy")
        self.assertTrue(guildrun.opens_for(five, ARMORY))
        none = [m.member for m in armory_five()]
        self.assertIsNone(guildrun.key_holder(none, ARMORY))
        self.assertFalse(guildrun.opens_for(none, ARMORY))
        self.assertTrue(guildrun.opens_for(none, BY_KEYWORD["scarlet-library"]))

    def test_the_wrong_key_opens_nothing(self):
        five = [m.member for m in armory_five(keys_for="Zappy", key=CRESCENT_KEY)]
        self.assertFalse(guildrun.opens_for(five, ARMORY))

    def test_the_holder_is_said(self):
        five = [m.member for m in armory_five(keys_for="Zappy")]
        self.assertEqual(
            guildrun.key_words(five, ARMORY), "'Zappy' carries the Scarlet Key"
        )
        self.assertEqual(guildrun.key_words(five, BY_KEYWORD["scarlet-library"]), "")


class TheKeyedWingsAreOnTheLadder(unittest.TestCase):
    KEYED = {
        "scarlet-armory", "scarlet-cathedral", "dire-maul-east-east",
        "dire-maul-west-north", "dire-maul-north",
    }  # fmt: skip

    def test_both_sides_offer_them(self):
        for faction in ("Alliance", "Horde"):
            self.assertLessEqual(self.KEYED, guildrun.GUILD_DOORS[faction], faction)

    def test_no_door_is_held_back_any_more(self):
        self.assertEqual(guildrun.BLOCKED_DOORS, {})


class AGuildGroupToAKeyedWingSeatsAKeyHolder(unittest.TestCase):
    def test_no_key_no_group(self):
        mates = armory_five()
        self.assertIsNone(
            gs.seat(ask(7, "Auren"), armory_yeses(), free_of(mates), ARMORY, "Alliance")
        )

    def test_a_seated_key_holder_forms_it(self):
        mates = armory_five(keys_for="Locky")
        seated = gs.seat(
            ask(7, "Auren"), armory_yeses(), free_of(mates), ARMORY, "Alliance"
        )
        self.assertIsNotNone(seated)
        comp = seated[0]
        self.assertIn("Locky", comp.names)

    def test_a_key_holder_who_said_yes_takes_a_damage_seat(self):
        mates = armory_five() + [mate("Keyra", 38, MAGE, door_keys=str(SCARLET_KEY))]
        yeses = armory_yeses() + [yes(5, 7, "Keyra", "dps")]
        seated = gs.seat(ask(7, "Auren"), yeses, free_of(mates), ARMORY, "Alliance")
        self.assertIsNotNone(seated, "a surplus yes carrying the key is seated")
        comp, used, declined, _helpers = seated
        self.assertIn("Keyra", comp.names)
        self.assertIn("Auren", comp.names, "the asker keeps its seat")
        self.assertEqual(len(comp.names), 5)
        self.assertIn(5, used)
        self.assertEqual(len(declined), 1, "the damage dealer it replaced is declined")

    def test_a_door_with_no_key_is_unchanged(self):
        mates = armory_five()
        library = BY_KEYWORD["scarlet-library"]
        self.assertIsNotNone(
            gs.seat(
                ask(7, "Auren", "scarlet-library"),
                armory_yeses(),
                free_of(mates),
                library,
                "Alliance",
            )
        )


class NobodyAsksForAWingNobodyFreeCanOpen(unittest.TestCase):
    def need(self, keyword):
        return gs.Need(
            member="Auren",
            keyword=keyword,
            item="Raging Berserker's Helm",
            entry=7719,
            gain=10.0,
            slot="head",
        )

    def plan(self, mates):
        return gs.plan_pass(
            list(mates),
            {},
            [],
            [],
            {"Auren": [self.need("scarlet-armory")]},
            DOORS,
            ENTRANCES,
            NOW,
            room=2,
            can_form=True,
        )

    def test_no_key_in_the_guild_no_ask(self):
        posts = self.plan(armory_five()).posts
        self.assertFalse([p for p in posts if p.target == "scarlet-armory"])

    def test_a_free_key_holder_lets_it_be_asked(self):
        posts = self.plan(armory_five(keys_for="Locky")).posts
        self.assertTrue([p for p in posts if p.target == "scarlet-armory"])


class TheCoordinatorsOwnPickHoldsToTheKeyToo(unittest.TestCase):
    def test_a_plan_offers_no_keyed_door_its_group_cannot_open(self):
        pool = guildrun.Pool(
            guild="Cave", members=tuple(m.member for m in armory_five())
        )
        plan = guildrun.plan_for(pool, [ARMORY, BY_KEYWORD["scarlet-library"]], {})
        self.assertIsNotNone(plan)
        self.assertNotIn("scarlet-armory", [d.keyword for d in plan.doors])

    def test_with_the_key_it_is_offered(self):
        pool = guildrun.Pool(
            guild="Cave", members=tuple(m.member for m in armory_five(keys_for="Zappy"))
        )
        plan = guildrun.plan_for(pool, [ARMORY], {})
        self.assertIsNotNone(plan)
        self.assertIn("scarlet-armory", [d.keyword for d in plan.doors])


class TheBridgeReadsTheKeysAndSaysTheHolder(unittest.TestCase):
    def test_the_member_read_carries_the_keys_column(self):
        start = BRIDGE.index("_GUILD_RUN_MEMBERS_SQL = (")
        sql = BRIDGE[start : BRIDGE.index("\n)\n", start)]
        self.assertIn("AS door_keys", sql)
        self.assertIn("campaignplan.KEY_ITEMS", sql)
        # A key in the bank opens nothing: bank slots (39 to 73) and bank bags
        # are left out, as the dungeon brain's HasItemCount leaves them out.
        self.assertIn("ci.slot NOT BETWEEN 39 AND 73", sql)

    def test_the_formed_run_names_the_key_holder(self):
        self.assertTrue("guildrun.key_words(social.form.composition.members" in BRIDGE)


if __name__ == "__main__":
    unittest.main()
