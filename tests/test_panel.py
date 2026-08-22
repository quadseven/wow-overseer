"""Panel-builder tests: DB rows in, character-panel JSON out.

Same seam rule as the map suite: everything the side panel renders is
decided in panel.py from plain dicts, so the whole in-game reality of a
character (hotbar, bags, vitals, target, guild, group) is testable without
MySQL. The HTTP adapter only fetches rows and calls build_character_panel.
"""
import unittest

from panel import build_character_panel

SNAP = {
    "guid": 7, "name": "Odo", "level": 5, "race": 2, "class": 1,
    "map_id": 1, "zone_id": 14, "area_id": 0,
    "health": 100, "max_health": 146, "in_combat": 0, "is_bot": 1,
    "guild_id": 0, "group_leader": 0, "target_guid": 0, "age_seconds": 3,
}

CHAR = {
    "activeTalentGroup": 0,
    "power1": 0, "power2": 350, "power3": 0, "power4": 0,
    "power5": 0, "power6": 0, "power7": 0,
}


def snap(**kw):
    d = dict(SNAP)
    d.update(kw)
    return d


def char(**kw):
    d = dict(CHAR)
    d.update(kw)
    return d


def build(**kw):
    """Call the builder with empty defaults so tests state only what matters."""
    args = {
        "name": "Odo",
        "snapshot_row": snap(),
        "char_row": char(),
        "action_rows": [],
        "inventory_rows": [],
        "guild_name": None,
        "group_rows": [],
        "target_player": None,
        "target_creature_name": None,
    }
    args.update(kw)
    return build_character_panel(**args)


class AbsenceTest(unittest.TestCase):
    def test_missing_character_is_a_calm_absent_payload(self):
        # The character logged out mid-view: the module sweeps their snapshot
        # row, the next poll finds nothing, and the page must be able to say
        # "left the world" without treating it as an error.
        p = build(snapshot_row=None, char_row=None)
        self.assertFalse(p["present"])
        self.assertEqual(p["name"], "Odo")

    def test_present_payload_says_so(self):
        self.assertTrue(build()["present"])


class IdentityAndVitalsTest(unittest.TestCase):
    def test_identity_names_race_class_and_faction(self):
        p = build()
        self.assertEqual(p["name"], "Odo")
        self.assertEqual(p["race"], "Orc")
        self.assertEqual(p["class"], "Warrior")
        self.assertEqual(p["faction"], "horde")
        self.assertEqual(p["level"], 5)
        self.assertTrue(p["bot"])

    def test_health_comes_from_the_snapshot(self):
        v = build()["vitals"]
        self.assertEqual(v["health"], 100)
        self.assertEqual(v["max_health"], 146)

    def test_warrior_rage_is_descaled(self):
        # Rage and runic power are stored x10 in characters.power*; the
        # in-game number is the descaled one.
        v = build(char_row=char(power2=350))["vitals"]
        self.assertEqual(v["power"], {"kind": "Rage", "value": 35})

    def test_mana_class_reads_power1_unscaled(self):
        v = build(snapshot_row=snap(**{"class": 8}), char_row=char(power1=284))["vitals"]
        self.assertEqual(v["power"], {"kind": "Mana", "value": 284})

    def test_missing_characters_row_means_no_power_not_a_crash(self):
        v = build(char_row=None)["vitals"]
        self.assertIsNone(v["power"])


class HotbarTest(unittest.TestCase):
    def test_buttons_group_into_bars_with_spell_labels(self):
        rows = [
            {"spec": 0, "button": 0, "action": 6603, "type": 0},
            {"spec": 0, "button": 1, "action": 78, "type": 0},
            {"spec": 0, "button": 72, "action": 20572, "type": 0},
        ]
        bars = build(action_rows=rows)["hotbar"]
        self.assertEqual([b["bar"] for b in bars], [1, 7])
        self.assertEqual(bars[0]["buttons"][0], {"slot": 0, "label": "Spell #6603", "kind": "spell", "id": 6603})
        self.assertEqual(bars[1]["buttons"][0]["slot"], 0)  # button 72 is slot 0 of bar 7

    def test_only_the_active_spec_is_shown(self):
        rows = [
            {"spec": 0, "button": 0, "action": 111, "type": 0},
            {"spec": 1, "button": 0, "action": 222, "type": 0},
        ]
        bars = build(action_rows=rows, char_row=char(activeTalentGroup=1))["hotbar"]
        self.assertEqual(bars[0]["buttons"][0]["id"], 222)

    def test_nonspell_action_types_are_labeled_not_lied_about(self):
        rows = [
            {"spec": 0, "button": 0, "action": 5175, "type": 128},
            {"spec": 0, "button": 1, "action": 3, "type": 64},
        ]
        (bar,) = build(action_rows=rows)["hotbar"]
        self.assertEqual(bar["buttons"][0]["label"], "Item #5175")
        self.assertEqual(bar["buttons"][1]["label"], "Macro #3")


def inv(bag, slot, item_guid, entry, count, name):
    return {"bag": bag, "slot": slot, "item_guid": item_guid,
            "entry": entry, "count": count, "name": name}


class InventoryTest(unittest.TestCase):
    def test_equipment_slots_get_their_worn_names(self):
        rows = [inv(0, 4, 900, 3471, 1, "Copper Chain Vest"),
                inv(0, 15, 901, 8178, 1, "Training Sword")]
        eq = build(inventory_rows=rows)["equipment"]
        self.assertEqual(eq, [{"slot": "chest", "name": "Copper Chain Vest"},
                              {"slot": "main hand", "name": "Training Sword"}])

    def test_backpack_and_bag_contents_group_under_their_container(self):
        rows = [
            inv(0, 19, 500, 51809, 1, "Portable Hole"),   # equipped bag
            inv(500, 0, 501, 118, 13, "Minor Healing Potion"),
            inv(0, 23, 502, 117, 1, "Tough Jerky"),        # backpack
        ]
        p = build(inventory_rows=rows)
        self.assertEqual(p["backpack"], [{"name": "Tough Jerky", "count": 1}])
        (bag,) = p["bags"]
        self.assertEqual(bag["name"], "Portable Hole")
        self.assertEqual(bag["items"], [{"name": "Minor Healing Potion", "count": 13}])

    def test_empty_bags_still_render_as_empty(self):
        rows = [inv(0, 19, 500, 51809, 1, "Portable Hole")]
        (bag,) = build(inventory_rows=rows)["bags"]
        self.assertEqual(bag["items"], [])

    def test_no_items_at_all_is_a_valid_naked_character(self):
        p = build(inventory_rows=[])
        self.assertEqual(p["equipment"], [])
        self.assertEqual(p["bags"], [])
        self.assertEqual(p["backpack"], [])
        self.assertEqual(p["stored_elsewhere"], 0)

    def test_bank_buyback_and_keyring_are_counted_not_listed(self):
        rows = [
            inv(0, 39, 600, 117, 5, "Tough Jerky"),        # bank slot
            inv(0, 67, 601, 51809, 1, "Portable Hole"),    # bank bag
            inv(601, 0, 602, 118, 2, "Minor Healing Potion"),  # inside bank bag
            inv(0, 80, 603, 117, 1, "Tough Jerky"),        # buyback
            inv(0, 90, 604, 6219, 1, "Arclight Spanner"),  # keyring range
        ]
        p = build(inventory_rows=rows)
        self.assertEqual(p["stored_elsewhere"], 4)  # the bank BAG itself is not cargo
        self.assertEqual(p["bags"], [])             # bank bags are not carried bags

    def test_unknown_item_name_falls_back_to_its_entry(self):
        # LEFT JOIN miss on acore_world.item_template (custom/removed item).
        rows = [inv(0, 23, 700, 99999, 1, None)]
        self.assertEqual(build(inventory_rows=rows)["backpack"],
                         [{"name": "Item #99999", "count": 1}])


class SocialTest(unittest.TestCase):
    def test_guild_name_passes_through(self):
        self.assertEqual(build(guild_name="The Horde")["guild"], "The Horde")
        self.assertIsNone(build()["guild"])

    def test_group_lists_members_leader_first(self):
        rows = [
            {"guid": 9, "name": "Paen", "level": 3, "class": 2},
            {"guid": 7, "name": "Odo", "level": 5, "class": 1},
        ]
        g = build(snapshot_row=snap(group_leader=9), group_rows=rows)["group"]
        self.assertEqual([m["name"] for m in g["members"]], ["Paen", "Odo"])
        self.assertTrue(g["members"][0]["leader"])
        self.assertFalse(g["members"][1]["leader"])
        self.assertEqual(g["members"][0]["class"], "Paladin")

    def test_no_group_when_leaderless(self):
        self.assertIsNone(build()["group"])


class TargetTest(unittest.TestCase):
    def test_no_target_is_none(self):
        self.assertIsNone(build()["target"])

    def test_player_target_wins_over_creature_with_the_same_counter(self):
        # target_guid is a bare counter: player guids and creature spawn
        # guids overlap below ~1061, so a live player match must win.
        t = build(snapshot_row=snap(target_guid=25),
                  target_player={"name": "Paen", "level": 3},
                  target_creature_name="Stabled Argent Warhorse")["target"]
        self.assertEqual(t, {"kind": "player", "name": "Paen", "level": 3})

    def test_creature_target_is_named(self):
        t = build(snapshot_row=snap(target_guid=873),
                  target_creature_name="Frostmane Troll Whelp")["target"]
        self.assertEqual(t, {"kind": "creature", "name": "Frostmane Troll Whelp"})

    def test_unresolvable_target_is_admitted_not_hidden(self):
        # Summoned/temporary units have no spawn row; say so honestly.
        t = build(snapshot_row=snap(target_guid=424242))["target"]
        self.assertEqual(t, {"kind": "unknown", "name": "unit #424242"})


if __name__ == "__main__":
    unittest.main()
