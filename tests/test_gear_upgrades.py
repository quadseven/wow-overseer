"""The gear upgrade tracker (#541): the builder and /api/upgrades.

Every test imports gearupgrades or hits the /api/upgrades route, so each fails
without the change. The database is amputated with fakes, as in
test_gearorigin: rows in the shape _fetch_armory and _fetch_upgrade_items read.
"""

import io
import json
import logging
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import armory  # noqa: E402
import gearscore  # noqa: E402
import gearupgrades  # noqa: E402
import map_server  # noqa: E402  (must follow the pymysql stub)

map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

SPELL_POWER = 45
INTELLECT = 5


def row(entry, spell_power=0, name=None, **extra):
    out = {
        "entry": entry,
        "item_name": name or f"Item {entry}",
        "stat_type1": SPELL_POWER if spell_power else 0,
        "stat_value1": spell_power,
    }
    out.update(extra)
    return out


# Mage head, pre-raid: 22267 then 23263; raid: 16795. Neck pre-raid: 22403.
LIST_ROWS = {
    22267: row(22267, 40, "Spellweaver's Turban"),
    23263: row(23263, 30, "Champion's Silk Cowl"),
    16795: row(16795, 60, "Arcanist Crown"),
    22403: row(22403, 20, "Diana's Pearl Necklace"),
}
MAGE = {
    "name": "Aldren",
    "class": "Mage",
    "level": 60,
    "present": True,
    "spec": {"primary": "Fire"},
}


def worn(slot_name, entry, spell_power):
    r = row(entry, spell_power, f"Worn {entry}")
    r["slot"] = armory.EQUIPPED_SLOTS.index(slot_name)
    return r


def build(equipment, member=MAGE, list_rows=LIST_ROWS):
    return gearupgrades.build(member, equipment, list_rows, list(armory.EQUIPPED_SLOTS))


def slot_of(payload, name):
    return next(s for s in payload["slots"] if s["slot"] == name)


class TheSpecIsChosenFromTheTree(unittest.TestCase):
    def test_a_known_tree_names_its_spec(self):
        self.assertEqual(
            gearupgrades.choose_spec("Paladin", "Protection"),
            ("paladin-protection", ""),
        )
        self.assertEqual(gearupgrades.choose_spec("Mage", "Frost")[0], "mage-dps")

    def test_no_tree_falls_back_to_the_first_spec_and_says_so(self):
        spec, note = gearupgrades.choose_spec("Druid", None)
        self.assertEqual(spec, "druid-balance")
        self.assertIn("first spec", note)

    def test_a_class_with_no_lists_has_no_spec(self):
        spec, note = gearupgrades.choose_spec("Death Knight", "Blood")
        self.assertIsNone(spec)
        self.assertTrue(note)

    def test_the_payload_flags_an_assumed_spec(self):
        no_tree = {**MAGE, "class": "Priest", "spec": {"primary": None}}
        out = build([], no_tree, {})
        self.assertTrue(out["spec"]["assumed"])
        self.assertEqual(out["spec"]["id"], "priest-holy")
        self.assertFalse(build([])["spec"]["assumed"])


class TheSlotsReadAgainstTheLists(unittest.TestCase):
    def test_a_worn_slot_carries_gearscores_score(self):
        out = build([worn("head", 9001, 12)])
        head = slot_of(out, "head")
        expected = gearscore.score({"spell_power": 12}, "mage-dps", 60, "head")
        self.assertEqual(head["worn"]["entry"], 9001)
        self.assertEqual(head["worn"]["score"], round(expected, 1))

    def test_targets_are_ranked_by_score_per_phase_with_sources(self):
        head = slot_of(build([worn("head", 9001, 12)]), "head")
        self.assertEqual(
            [t["entry"] for t in head["targets"]["preraid"]], [22267, 23263]
        )
        self.assertEqual([t["entry"] for t in head["targets"]["raid"]], [16795])
        first = head["targets"]["preraid"][0]
        self.assertEqual(
            first["where"], [{"kind": "dungeon", "label": "Dungeon: Blackrock Spire"}]
        )
        honor = head["targets"]["preraid"][1]["where"][0]
        self.assertEqual(honor["kind"], "honor_vendor")

    def test_the_next_upgrade_is_the_pre_raid_best_then_the_raid_best(self):
        head = slot_of(build([worn("head", 9001, 12)]), "head")
        self.assertEqual(head["next"]["entry"], 22267)
        self.assertEqual(head["next"]["phase"], "preraid")
        self.assertGreater(head["next"]["gain"], 0)
        full = slot_of(build([worn("head", 22267, 40)]), "head")
        self.assertEqual(full["next"]["entry"], 16795)
        self.assertEqual(full["next"]["phase"], "raid")

    def test_an_empty_slot_still_shows_its_targets(self):
        neck = slot_of(build([]), "neck")
        self.assertEqual(neck["state"], "empty")
        self.assertIsNone(neck["worn"])
        self.assertEqual(neck["next"]["entry"], 22403)

    def test_a_ring_is_not_told_to_buy_the_other_rings_item(self):
        rings = {22339: row(22339, 30), 942: row(942, 20)}
        out = build([worn("finger 1", 22339, 30)], MAGE, rings)
        second = slot_of(out, "finger 2")
        self.assertNotIn(22339, [t["entry"] for t in second["targets"]["preraid"]])
        self.assertEqual(second["next"]["entry"], 942)

    def test_an_item_the_world_does_not_know_is_skipped_never_scored_zero(self):
        head = slot_of(build([], MAGE, {23263: LIST_ROWS[23263]}), "head")
        self.assertEqual([t["entry"] for t in head["targets"]["preraid"]], [23263])


class ReadinessCountsSlotsAtOrNearPreRaidBest(unittest.TestCase):
    def test_share_of_scored_slots_at_or_near_best(self):
        out = build([worn("head", 22267, 40), worn("neck", 1234, 19)])
        self.assertEqual(slot_of(out, "head")["state"], "best")
        self.assertEqual(slot_of(out, "neck")["state"], "near")
        ready = out["ready"]
        self.assertEqual(ready["slots_ready"], 2)
        self.assertEqual(ready["slots_scored"], 2)
        self.assertEqual(ready["pct"], 1.0)
        self.assertIn("2 of 2", ready["line"])

    def test_a_weak_piece_is_an_upgrade_and_not_ready(self):
        out = build([worn("head", 9001, 10), worn("neck", 1234, 20)])
        self.assertEqual(slot_of(out, "head")["state"], "upgrade")
        self.assertEqual(out["ready"]["slots_ready"], 1)
        self.assertEqual(out["ready"]["pct"], 0.5)

    def test_a_class_without_data_has_no_readiness(self):
        dk = {**MAGE, "class": "Death Knight", "spec": {"primary": "Blood"}}
        out = build([], dk, {})
        self.assertIsNone(out["ready"])
        self.assertEqual(out["slots"], [])


class FakeHandler(map_server.Handler):
    def __init__(self, path):
        self.path = path
        self.rfile = io.BytesIO(b"")
        self.headers = {}
        self.sent = []

    def _send(self, code, ctype, body, cache_control="no-store"):
        self.sent.append((code, ctype, body))


def get(name="Aldren"):
    h = FakeHandler(f"/api/upgrades?name={name}")
    h.do_GET()
    return h.sent[-1][0], json.loads(h.sent[-1][2])


FETCHED = {"equipment_rows": [worn("head", 9001, 12)], "equip_event_rows": []}


@mock.patch.object(map_server, "_fetch_family_groups", return_value=[("A", ["Aldren"])])
@mock.patch.object(map_server, "_is_family_guildmate", return_value=True)
@mock.patch.object(map_server, "_fetch_armory", side_effect=lambda n: dict(FETCHED))
@mock.patch.object(map_server, "_fetch_upgrade_items", return_value=LIST_ROWS)
@mock.patch.object(
    map_server.armory, "build_armory", side_effect=lambda **k: {"members": [MAGE]}
)
class TheUpgradesEndpoint(unittest.TestCase):
    def test_it_answers_with_the_tracker_payload(self, *_):
        code, body = get()
        self.assertEqual(code, 200)
        self.assertEqual(body["name"], "Aldren")
        self.assertEqual(body["spec"]["id"], "mage-dps")
        self.assertEqual(slot_of(body, "head")["next"]["entry"], 22267)
        self.assertEqual(len(body["slots"]), len(gearupgrades.ROWS))

    def test_it_reads_only_the_ids_the_specs_lists_name(self, *mocks):
        get()
        fetch_items = mocks[1]
        ids = fetch_items.call_args[0][0]
        self.assertEqual(ids, gearupgrades.all_list_ids("mage-dps"))

    def test_the_route_is_registered(self, *_):
        self.assertIs(
            map_server.Handler.GET_ROUTES["/api/upgrades"], map_server.Handler._upgrades
        )

    def test_a_name_that_fails_the_name_rule_is_a_404(self, *_):
        code, _ = get("Bad%20Name")
        self.assertEqual(code, 404)

    def test_a_name_outside_the_family_guilds_is_a_404(self, *mocks):
        mocks[3].return_value = False  # _is_family_guildmate
        code, body = get("Stranger")
        self.assertEqual(code, 404)
        self.assertEqual(body["error"], "not a guild member")

    def test_a_missing_character_is_a_404(self, *mocks):
        mocks[0].side_effect = lambda **k: {
            "members": [{"name": "Aldren", "present": False}]
        }
        code, _ = get()
        self.assertEqual(code, 404)

    def test_an_unreachable_world_is_a_503(self, *mocks):
        mocks[2].side_effect = RuntimeError("down")  # _fetch_armory
        code, body = get()
        self.assertEqual(code, 503)
        self.assertEqual(body["error"], "world unreachable")


PAGE = (pathlib.Path(__file__).resolve().parent.parent / "index.html").read_text(
    encoding="utf-8"
)


class ThePageDrawsIt(unittest.TestCase):
    def test_the_section_and_its_controls_exist(self):
        self.assertIn('<section id="upgrades">', PAGE)
        section = PAGE[PAGE.index('<section id="upgrades">') :]
        section = section[: section.index("</section>")]
        for ident in ("upsel", "upready", "uptable", "upbasis"):
            self.assertIn(f'id="{ident}"', section)
        self.assertIn('<label for="upsel">', section)

    def test_the_tab_is_wired_and_routable(self):
        self.assertIn('const UPGRADES_VIEW = "upgrades";', PAGE)
        self.assertIn("showView(UPGRADES_VIEW)", PAGE)
        hashes = PAGE[PAGE.index("const HASH_VIEWS = [") :]
        self.assertIn("UPGRADES_VIEW", hashes[: hashes.index("];")])
        self.assertIn('upsection.style.display = isUp ? "block" : "none";', PAGE)

    def test_it_reads_the_endpoint_by_name_and_paints_text_only(self):
        block = PAGE[PAGE.index("// --- the Upgrades tab") :]
        block = block[: block.index("upsel.addEventListener")]
        self.assertIn('u("/api/upgrades?name=" + encodeURIComponent(name))', block)
        self.assertNotIn("innerHTML", block)


if __name__ == "__main__":
    unittest.main()
