"""Jev is asked with the facts a player would check, and records them (#3303).

An independent judge could not decide most movement disagreements and traced
Jev's major item_keep and family_intent mistakes to facts it was never given:
where each member's hearthstone lands, which member is dead or fighting, a
Darkmoon deck's progress across the family, who casts with a reagent, the
ranged weapon an arrow is for, the family's and the guild bank's free slots,
and each member's bags, durability and quest. Each kind now asks with them as
per-member rows, and the stored `facts` column holds the state Jev saw,
options first, in a column wide enough not to cut it.

Every test runs on fake rows and a fake Jev transport.
"""

import asyncio
import dataclasses
import json
import pathlib
import unittest

import jev
import jev_family_intent as jfi
import jev_items
import jev_keep
import jev_movement as jm
from test_jev_items import FakeJev
import test_jev_family_intent as tf
import test_jev_keep as tk
import test_jev_movement as tm

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

GOAL = "at:1:-7203.1,-3821.1,8.6"


def _block(name: str) -> str:
    body = BRIDGE[BRIDGE.index(name) :]
    return body[: body.index("\n\n\n")]


class EveryMemberRow(unittest.TestCase):
    def test_each_member_says_how_far_and_how_high_from_the_leader(self):
        rows = {m["name"]: m for m in tm.where().state()["members"]}
        self.assertNotIn("yards_from_leader", rows["Grug"])
        self.assertLess(rows["Ugga"]["yards_from_leader"], 5)
        self.assertNotIn("height_vs_leader", rows["Ugga"])
        bork = rows["Bork"]
        self.assertGreater(bork["yards_from_leader"], 1000)
        self.assertEqual(bork["height_vs_leader"], -124)

    def test_a_member_on_another_map_says_so(self):
        w = tm.where(bork=(10.0, 10.0, 10.0), map_id=0)
        bork = next(m for m in w.state()["members"] if m["name"] == "Bork")
        self.assertEqual(bork["yards_from_leader"], "another map")


def movement_facts(**kw):
    w = tm.where(deaths=tm.DYING, travel=GOAL)
    base = dict(errand=GOAL, claimant="guild bank")
    base.update(kw)
    f = tm.facts(w, **base)
    return dataclasses.replace(f, bind_zones={n: 440 for n in tm.NAMES})


class MovementHearthRows(unittest.TestCase):
    def test_each_member_row_says_where_its_hearthstone_lands(self):
        f = movement_facts(hearthed=("Og",))
        state, _q = jm.question(f, jm.options(f))
        rows = {m["name"]: m for m in state["situation"]["members"]}
        bork = rows["Bork"]["hearth"]
        self.assertEqual(bork["bind"], "Tanaris")
        self.assertIsInstance(bork["bind_yards_from_leader"], int)
        self.assertIsInstance(bork["bind_yards_from_goal"], int)
        self.assertLess(bork["bind_yards_from_goal"], 60)
        self.assertEqual(bork["hearthstone"], "ready")
        self.assertEqual(rows["Og"]["hearth"]["hearthstone"], "used in the last hour")

    def test_a_bind_on_another_map_or_unread_is_said(self):
        binds = {n: tm.TANARIS_INN for n in tm.NAMES}
        binds["Ugga"] = tm.IRONFORGE_INN
        del binds["Grog"]
        f = movement_facts(binds=binds)
        rows = jm.hearth_rows(f)
        self.assertEqual(rows["Ugga"]["bind_yards_from_leader"], "another map")
        self.assertEqual(rows["Grog"], {"hearthstone": "no bind read"})

    def test_the_hearth_rows_change_no_option(self):
        f = movement_facts()
        bare = dataclasses.replace(f, bind_zones={})
        self.assertEqual(jm.options(f), jm.options(bare))
        self.assertEqual(jm.heuristic(f), jm.heuristic(bare))

    def test_the_record_holds_the_state_jev_saw_options_first(self):
        f = movement_facts()
        client = jev.Client("k", transport=FakeJev())
        judgment = asyncio.run(jm.ask(client, f, jm.policy({})))
        self.assertTrue(judgment.facts.startswith('{"options":{'), judgment.facts[:40])
        self.assertLessEqual(len(judgment.facts), jev_items.FACTS_LIMIT)
        facts = json.loads(judgment.facts)
        self.assertIn(jm.CARRY_ON, facts["options"])
        self.assertEqual(
            facts["situation"]["deaths_last_30_min"]["who"], ["Og", "Ugga"]
        )
        self.assertEqual(
            facts["errand_in_the_travel_column"]["written_by"], "guild bank"
        )
        bork = next(m for m in facts["situation"]["members"] if m["name"] == "Bork")
        self.assertEqual(bork["hearth"]["bind"], "Tanaris")


UPKEEP_WORN = [
    dict(holder="Grug", durability=40, max_durability=100),
    dict(holder="Grug", durability=90, max_durability=100),
    dict(holder="Og", durability=0, max_durability=0),
]


class FamilyUpkeep(unittest.TestCase):
    def test_upkeep_rows_from_the_bridge_reads(self):
        rows = jfi.upkeep_from(
            ["Grug", "Og", "Bork"],
            {"Grug": (3, 58), "Og": (20, 46)},
            UPKEEP_WORN,
            {"Grug": ("I still need 4 Grimtotem slain.", 4, 5064)},
        )
        self.assertEqual(
            rows["Grug"],
            {
                "free_bag_slots": "3 of 58",
                "worst_durability_pct": 40,
                "quest": "I still need 4 Grimtotem slain. (q5064)",
            },
        )
        self.assertEqual(rows["Og"]["worst_durability_pct"], "nothing that wears")
        self.assertEqual(rows["Og"]["quest"], "none in the log with objectives left")
        self.assertEqual(rows["Bork"]["free_bag_slots"], "unknown")

    def test_a_read_that_failed_reads_unknown(self):
        rows = jfi.upkeep_from(["Grug"], None, None, None)
        self.assertEqual(
            rows["Grug"],
            {
                "free_bag_slots": "unknown",
                "worst_durability_pct": "unknown",
                "quest": "unknown",
            },
        )

    def test_the_question_carries_upkeep_per_member_leader_first(self):
        f = dataclasses.replace(
            tf.facts(),
            upkeep=jfi.upkeep_from(
                ["Grug", "Og"], {"Grug": (3, 58), "Og": (0, 46)}, UPKEEP_WORN, {}
            ),
        )
        state, _q = jfi.question(f, jfi.options(f))
        first = state["members"][0]
        self.assertEqual((first["name"], first["state"]), ("Grug", "leading"))
        self.assertEqual(first["free_bag_slots"], "3 of 58")
        og = next(m for m in state["members"] if m["name"] == "Og")
        self.assertEqual(og["free_bag_slots"], "0 of 46")
        self.assertIn("too far to walk back", og["state"])

    def test_upkeep_changes_no_option_or_signature(self):
        f = tf.facts()
        g = dataclasses.replace(f, upkeep={"Grug": {"free_bag_slots": "0 of 58"}})
        self.assertEqual(jfi.options(f), jfi.options(g))
        self.assertEqual(jfi.signature(f), jfi.signature(g))

    def test_the_record_holds_the_state_jev_saw_options_first(self):
        f = dataclasses.replace(
            tf.facts(),
            where=tm.where(deaths=tm.DYING),
            upkeep=jfi.upkeep_from(["Grug"], {"Grug": (3, 58)}, UPKEEP_WORN, {}),
        )
        judgment = tf.ask(f)
        self.assertTrue(judgment.facts.startswith('{"options":{'), judgment.facts[:40])
        facts = json.loads(judgment.facts)
        self.assertEqual(set(facts["options"]), set(jfi.options(f)))
        self.assertEqual(facts["members"][0]["worst_durability_pct"], 40)
        self.assertIn("situation", facts)


CARD = 19279  # an entry for the fixture; the deck is read by name
SEVEN = tk.row(901, CARD, "Seven of Elementals", 15, 1, 2, 12500)
FAMILY_CARDS = [
    SEVEN,
    dict(tk.row(902, 19278, "Three of Elementals", 15), holder="Bork"),
    dict(tk.row(903, 19276, "Ace of Elementals", 15), holder="Og"),
    dict(tk.row(904, 19280, "Two of Beasts", 15), holder="Og"),
]
ARROWS = tk.row(905, 2512, "Rough Arrow", 6, 200, 1, 0)
SEED = tk.row(906, 17034, "Maple Seed", 5, 5, 1, 0, reagent=True)


def keep_asks(rows, **kw):
    templates = dict(tk.TEMPLATES)
    for r in rows:
        templates.setdefault(r["entry"], dict(bonding=0, stackable=20))
    return {
        state["item"]["name"]: state
        for _j, state, _q in jev_keep.asks(
            jev_keep.protected(rows),
            templates=templates,
            holders=tk.holders(),
            people=tk.people(),
            routes={},
            market=kw.pop("market", {}),
            reagent_trades={},
            mode=jev.SHADOW,
            **kw,
        )
    }


class KeepFacts(unittest.TestCase):
    def test_a_darkmoon_card_says_what_the_family_holds_of_its_deck(self):
        state = keep_asks([SEVEN], carried=FAMILY_CARDS)["Seven of Elementals"]
        self.assertEqual(
            state["item"]["darkmoon_deck"],
            {
                "deck": "Elementals",
                "family_carries": ["Ace", "Three", "Seven"],
                "missing": ["Two", "Four", "Five", "Six", "Eight"],
                "counted": "family bags only; banks not read",
            },
        )

    def test_an_unknown_auction_price_says_why(self):
        state = keep_asks([SEVEN])["Seven of Elementals"]
        self.assertEqual(
            state["item"]["auction_price_each"],
            "not known: no live listing on the family's auction house",
        )
        state = keep_asks([SEVEN], market=None)["Seven of Elementals"]
        self.assertEqual(
            state["item"]["auction_price_each"],
            "not known: the auction house was not read",
        )

    def test_bag_room_across_the_family_and_the_guild_bank(self):
        state = keep_asks([SEVEN], family_free=dict(tk.FREE), guild_free=7)[
            "Seven of Elementals"
        ]
        self.assertEqual(
            state["bag_room"],
            {"family_free_bag_slots": dict(tk.FREE), "guild_bank_free_slots": 7},
        )
        state = keep_asks([SEVEN], family_free=dict(tk.FREE), guild_free=None)[
            "Seven of Elementals"
        ]
        self.assertEqual(state["bag_room"]["guild_bank_free_slots"], "unknown")

    def test_a_reagent_names_the_family_members_who_cast_with_it(self):
        state = keep_asks([SEED], spell_users={17034: ("Ugga", "Og")})["Maple Seed"]
        self.assertEqual(state["item"]["class_spells_use_it"], ["Ugga", "Og"])
        state = keep_asks([SEED], spell_users={})["Maple Seed"]
        self.assertEqual(
            state["item"]["class_spells_use_it"],
            "no family member knows a spell that uses it",
        )
        state = keep_asks([SEED])["Maple Seed"]
        self.assertNotIn("class_spells_use_it", state["item"])

    def test_ammunition_names_each_members_ranged_weapon(self):
        ranged = {"Ugga": "wand", "Bork": "bow", "Og": "none"}
        state = keep_asks([ARROWS], ranged=ranged)["Rough Arrow"]
        self.assertEqual(state["item"]["family_ranged_weapons"], ranged)
        state = keep_asks([ARROWS], ranged=None)["Rough Arrow"]
        self.assertEqual(state["item"]["family_ranged_weapons"], "unknown")
        state = keep_asks([SEVEN], ranged=ranged)["Seven of Elementals"]
        self.assertNotIn("family_ranged_weapons", state["item"])

    def test_the_new_facts_change_no_option(self):
        plain = jev_keep.asks(
            jev_keep.protected([SEVEN, SEED]),
            templates=dict(tk.TEMPLATES),
            holders=tk.holders(),
            people=tk.people(),
            routes={},
            market={},
            reagent_trades={},
            mode=jev.SHADOW,
        )
        rich = jev_keep.asks(
            jev_keep.protected([SEVEN, SEED]),
            templates=dict(tk.TEMPLATES),
            holders=tk.holders(),
            people=tk.people(),
            routes={},
            market={},
            reagent_trades={},
            mode=jev.SHADOW,
            carried=FAMILY_CARDS,
            family_free=dict(tk.FREE),
            guild_free=3,
            spell_users={17034: ("Og",)},
            ranged={"Og": "wand"},
        )
        for (a, _sa, qa), (b, _sb, qb) in zip(plain, rich):
            self.assertEqual(qa, qb)
            self.assertEqual((a.heuristic, a.actable), (b.heuristic, b.actable))
            self.assertLessEqual(len(b.facts), jev_items.FACTS_LIMIT)

    def test_spell_users_come_from_known_spells(self):
        reagents = {20484: ((17034, 1),), 133: ()}
        rows = [
            dict(holder="Og", spell=20484),
            dict(holder="Ugga", spell=133),
            dict(holder="Bork", spell=20484),
        ]
        self.assertEqual(
            jev_keep.spell_users_from(rows, reagents, [17034, 2512]),
            {17034: ("Bork", "Og")},
        )

    def test_ranged_words(self):
        self.assertEqual(
            jev_keep.ranged_word({"item_class": 2, "item_subclass": 2}), "bow"
        )
        self.assertEqual(
            jev_keep.ranged_word({"item_class": 2, "item_subclass": 3}), "gun"
        )
        self.assertEqual(jev_keep.ranged_word(None), "none")


class TheRecord(unittest.TestCase):
    def test_the_facts_column_is_wide_enough_for_the_state(self):
        self.assertEqual(jev_items.FACTS_LIMIT, 4000)
        store = _block("def _create_jev_store(")
        self.assertIn(" facts VARCHAR(4000) NOT NULL DEFAULT '',", store)
        self.assertIn("MODIFY COLUMN facts VARCHAR(4000) NOT NULL DEFAULT ''", store)
        self.assertIn("CHARACTER_MAXIMUM_LENGTH", store)
        insert = _block("def _insert_jev_judgment(")
        # The insert is run alone by several tests, so it names the width
        # rather than a module; it must equal the limit facts_line cuts to.
        self.assertIn("facts[:4000]", insert)

    def test_the_bridge_reads_each_new_fact(self):
        self.assertIn("h.zoneId AS zone_id", _block("_MOVEMENT_BINDS = ("))
        movement = _block("    async def _movement_facts(")
        self.assertIn("bind_zones=", movement)
        intent = _block("    async def _family_intent_for(")
        self.assertIn("_family_upkeep", intent)
        upkeep = _block("def _family_upkeep(")
        for reader in ("_fetch_bag_room", "_fetch_town_worn", "_fetch_quest_progress"):
            self.assertIn(reader, upkeep)
        keep = _block("    async def _jev_keep_once(")
        for word in (
            "carried=",
            "family_free=",
            "guild_free=",
            "spell_users=",
            "ranged=",
        ):
            self.assertIn(word, keep)

    def test_a_judgment_row_keeps_the_whole_state(self):
        line = jev_items.facts_line({"x": "y" * 3000}, {"a": "b"})
        self.assertEqual(json.loads(line)["x"], "y" * 3000)


if __name__ == "__main__":
    unittest.main()
