"""GET /api/v2/raidteams: the approved Molten Core seats per guild, open seats
left open, and the raid fields per member (attuned, fire resistance,
consumables), null when the realm cannot answer a read."""

import os
import sys
import types
import unittest

from _stub_modules import PYMYSQL, stub_modules

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
with stub_modules(pymysql=PYMYSQL):
    import apiv2
    import raidready
    import raidsupply
    import raidteams
    import realmread
    from apiv2 import raidteams as v2
    from apiv2 import training as v2training

GUILD_ID = 7


def _rows(team, *, renamed=False, recruits=False, other_guild=()):
    """characters/guild_member rows for `team`: current names until the
    rename, and no recruit until one joins."""
    out = []
    for s in raidteams.seats(team):
        if not s.was and not recruits and s not in raidteams.GROUPS[team][0]:
            continue
        name = s.name if (renamed or not s.was) else s.was
        gid = 99 if name in other_guild else GUILD_ID
        out.append(
            {
                "name": name,
                "level": 30,
                "class_id": s.class_id,
                "online": 1,
                "guildid": gid,
            }
        )
    return out


def reader(members, attuned=(), worn=(), carried=(), fail=()):
    """The endpoint's four reads, answered by name; `fail` names the reads
    this realm has no table for."""
    answers = {
        v2.MEMBERS_SQL: members,
        v2.ATTUNED_SQL: list(attuned),
        v2.WORN_SQL: list(worn),
        v2.CONSUMABLES_SQL: list(carried),
        v2.KNOWN_SQL: [],
        v2training.TRAINER_SQL: [],
    }
    for sql in fail:
        answers[sql] = realmread.MISSING_TABLE
    return realmread.Memory(answers)


def _ctx(rd):
    return types.SimpleNamespace(read=rd, server=None)


class TheRoute(unittest.TestCase):
    def test_the_route_is_registered_under_v2(self):
        self.assertIn("/api/v2/raidteams", apiv2.ROUTES)

    def test_the_guild_is_matched_without_case(self):
        self.assertEqual(v2.guild_key({"guild": ["cave"]}), "Cave")
        self.assertEqual(v2.guild_key({"guild": ["BONKERS"]}), "Bonkers")
        self.assertEqual(v2.guild_key({"guild": ["nobody"]}), "")
        self.assertEqual(v2.guild_key({}), "")

    def test_an_unknown_guild_is_a_400_that_names_the_guilds(self):
        code, payload = v2.raidteams_read({"guild": ["x"]}, None)
        self.assertEqual(code, 400)
        self.assertEqual(payload["guilds"], ["cave", "bonkers"])


class TheSeats(unittest.TestCase):
    def test_eight_groups_of_five_in_the_approved_order(self):
        payload = v2.build("Cave", {"members": _rows("Cave", recruits=True)})
        self.assertEqual(len(payload["groups"]), 8)
        self.assertTrue(all(len(g) == 5 for g in payload["groups"]))
        self.assertEqual(
            payload["groups"][0], [s.name for s in raidteams.GROUPS["Cave"][0]]
        )
        self.assertEqual(payload["gaps"], {"tanks": 0, "healers": 0, "damage": 0})

    def test_a_seat_is_found_under_the_name_it_has_until_the_rename(self):
        payload = v2.build("Cave", {"members": _rows("Cave")})
        brug = raidteams.GROUPS["Cave"][1][0]
        self.assertEqual(payload["groups"][1][0], brug.was)
        self.assertEqual(payload["seats"][1][0]["approved"], brug.name)

    def test_a_recruit_not_yet_joined_is_an_open_seat_and_a_gap(self):
        payload = v2.build("Cave", {"members": _rows("Cave")})
        recruits = [
            s
            for s in raidteams.seats("Cave")
            if not s.was and s not in raidteams.GROUPS["Cave"][0]
        ]
        flat = [n for g in payload["groups"] for n in g]
        self.assertEqual(flat.count(None), len(recruits))
        want = {"tanks": 0, "healers": 0, "damage": 0}
        for s in recruits:
            want[v2._GAP_KEY[s.seat]] += 1
        self.assertEqual(payload["gaps"], want)
        self.assertEqual(payload["seated"], 40 - len(recruits))

    def test_nobody_found_leaves_every_seat_open_never_guessed(self):
        payload = v2.build("Bonkers", {"members": []})
        self.assertEqual([n for g in payload["groups"] for n in g], [None] * 40)
        self.assertEqual(sum(payload["gaps"].values()), 40)
        self.assertEqual(payload["members"], {})

    def test_a_character_in_another_guild_does_not_take_the_seat(self):
        grug = raidteams.GROUPS["Cave"][0][0].name
        payload = v2.build(
            "Cave", {"members": _rows("Cave", recruits=True, other_guild={grug})}
        )
        self.assertIsNone(payload["groups"][0][0])


class TheRaidFields(unittest.TestCase):
    def setUp(self):
        self.grug = raidteams.GROUPS["Cave"][0][0].name
        self.ugga = raidteams.GROUPS["Cave"][0][1].name
        self.potion = raidsupply.SUPPLIES[0].entry

    def _payload(self, **reads):
        fetched = {
            "members": _rows("Cave"),
            "attuned": [],
            "worn": [],
            "consumables": [],
        }
        fetched.update(reads)
        return v2.build("Cave", fetched)

    def test_fields_are_read_per_member(self):
        payload = self._payload(
            attuned=[{"name": self.grug}],
            worn=[
                {"name": self.grug, "fire_res": 7},
                {"name": self.grug, "fire_res": 10},
            ],
            consumables=[{"name": self.grug, "entry": self.potion, "count": 3}],
        )
        grug = payload["members"][self.grug]
        self.assertIs(grug["attuned"], True)
        self.assertEqual(grug["fire_resistance"], 17)
        self.assertEqual(grug["consumables"], {str(self.potion): 3})

    def test_a_measured_nothing_is_false_zero_and_empty(self):
        ugga = self._payload()["members"][self.ugga]
        self.assertIs(ugga["attuned"], False)
        self.assertEqual(ugga["fire_resistance"], 0)
        self.assertEqual(ugga["consumables"], {})

    def test_an_unreadable_read_is_null_for_every_member(self):
        payload = self._payload(attuned=None, worn=None, consumables=None)
        for m in payload["members"].values():
            self.assertIsNone(m["attuned"])
            self.assertIsNone(m["fire_resistance"])
            self.assertIsNone(m["consumables"])

    def test_fire_resistance_is_counted_as_the_raid_card_counts_it(self):
        worn = [{"name": self.grug, "fire_res": 5}, {"name": self.ugga, "fire_res": 9}]
        payload = self._payload(worn=worn)
        fire = raidready.fire_resistance(worn)
        self.assertEqual(
            payload["members"][self.grug]["fire_resistance"], fire[self.grug]
        )

    def test_the_consumables_named_are_the_nights_supplies(self):
        payload = self._payload()
        entries = [i["entry"] for i in payload["consumable_items"]]
        self.assertEqual(
            entries, list(dict.fromkeys(s.entry for s in raidsupply.SUPPLIES))
        )


class TheReads(unittest.TestCase):
    def test_the_handler_makes_the_four_reads(self):
        rd = reader(_rows("Cave"), attuned=[{"name": "Grug"}])
        code, payload = v2.raidteams_read({"guild": ["cave"]}, _ctx(rd))
        self.assertEqual(code, 200)
        self.assertIs(payload["members"]["Grug"]["attuned"], True)
        asked = [sql for sql, _ in rd.asked]
        for sql in (v2.MEMBERS_SQL, v2.ATTUNED_SQL, v2.WORN_SQL, v2.CONSUMABLES_SQL):
            self.assertTrue(any(a.startswith(sql[:40]) or a == sql for a in asked), sql)
        # The spell reads ride along: known spells plus one trainer read
        # per tank class seated.
        self.assertTrue(any(a.startswith("SELECT c.name, cs.spell") for a in asked))
        self.assertTrue(any("trainer_spell" in a for a in asked))

    def test_every_value_is_bound(self):
        rd = reader(_rows("Cave"))
        v2.fetch(rd, "Cave")
        for sql, params in rd.asked:
            self.assertEqual(sql.count("%s"), len(params), sql)

    def test_a_missing_table_thins_that_field_only(self):
        rd = reader(_rows("Cave"), fail={v2.ATTUNED_SQL})
        code, payload = v2.raidteams_read({"guild": ["cave"]}, _ctx(rd))
        self.assertEqual(code, 200)
        self.assertIsNone(payload["members"]["Grug"]["attuned"])
        self.assertEqual(payload["members"]["Grug"]["fire_resistance"], 0)

    def test_any_other_error_still_rises_to_the_503(self):
        rd = realmread.Memory({v2.MEMBERS_SQL: OSError("connection reset")})
        with self.assertRaises(OSError):
            v2.fetch(rd, "Cave")

    def test_nobody_found_reads_nothing_more(self):
        rd = reader([])
        v2.fetch(rd, "Cave")
        self.assertEqual(len(rd.asked), 1)


class TheTankAudit(unittest.TestCase):
    """The raid-teams payload carries the seated tanks' spellbook audit:
    each filled tank seat's due trainer spells it has not learned, from
    the same trainer rows and known sets the training read uses. A read
    the realm cannot answer leaves the audit null, never a guess."""

    TRAINER = [
        {"spell": 900001, "level": 10, "cost": 100, "req1": 0, "req2": 0, "req3": 0},
        {"spell": 18499, "level": 32, "cost": 100, "req1": 0, "req2": 0, "req3": 0},
    ]

    def _payload(self, **reads):
        # The trainer map the real read builds: one entry per tank class
        # actually seated, holding that class's trainer rows.
        trainer = {}
        for s in raidteams.seats("Cave"):
            if s.seat == "tank":
                trainer[s.class_id] = list(self.TRAINER)
        fetched = {
            "members": _rows("Cave"),
            "attuned": [],
            "worn": [],
            "consumables": [],
            "known": [],
            "trainer": trainer,
        }
        fetched.update(reads)
        return v2.build("Cave", fetched)

    def test_a_tank_missing_a_due_spell_is_named_in_the_audit(self):
        audit = self._payload()["tank_audit"]
        grug = [t for t in audit["tanks"] if t["name"] == "Grug"][0]
        self.assertEqual(
            grug["missing"], [{"spell": 900001, "level": 10, "state": "trainable"}]
        )
        self.assertFalse(grug["complete"])
        # Every filled tank's class trainer list carries the same due
        # spell, so every filled tank is missing it.
        missing = [t for t in audit["tanks"] if t["missing"]]
        self.assertEqual(len(missing), audit["audited"])
        self.assertEqual(audit["incomplete"], len(missing))
        self.assertEqual(audit["missing_total"], len(missing))

    def test_an_above_level_spell_is_not_missing(self):
        audit = self._payload()["tank_audit"]
        for tank in audit["tanks"]:
            self.assertNotIn(18499, [m["spell"] for m in tank["missing"]])

    def test_a_tank_that_knows_the_due_spell_is_complete(self):
        audit = self._payload(known=[{"name": "Grug", "spell": 900001}])["tank_audit"]
        grug = [t for t in audit["tanks"] if t["name"] == "Grug"][0]
        self.assertTrue(grug["complete"])
        self.assertEqual(grug["missing"], [])

    def test_only_filled_tank_seats_are_audited(self):
        audit = self._payload()["tank_audit"]
        payload = self._payload()
        seated_tanks = [
            s["name"]
            for group in payload["seats"]
            for s in group
            if s["seat"] == "tank" and s["name"]
        ]
        self.assertEqual([t["name"] for t in audit["tanks"]], seated_tanks)
        self.assertEqual(audit["audited"], len(seated_tanks))

    def test_an_unreadable_spell_read_leaves_the_audit_null(self):
        self.assertIsNone(self._payload(known=None)["tank_audit"])
        self.assertIsNone(self._payload(trainer=None)["tank_audit"])

    def test_a_tank_class_without_trainer_rows_leaves_the_audit_null(self):
        trainer = {6: list(self.TRAINER)}
        self.assertIsNone(self._payload(trainer=trainer)["tank_audit"])

    def test_an_empty_trainer_list_for_a_tank_class_leaves_the_audit_null(self):
        # The shape the real read produces when the trainer table is
        # missing: the rows read answers an empty list, not an error.
        trainer = {1: list(self.TRAINER), 6: []}
        self.assertIsNone(self._payload(trainer=trainer)["tank_audit"])

    def test_a_missing_trainer_table_leaves_the_audit_null(self):
        rd = reader(_rows("Cave"), fail={v2training.TRAINER_SQL})
        code, payload = v2.raidteams_read({"guild": ["cave"]}, _ctx(rd))
        self.assertEqual(code, 200)
        self.assertIsNone(payload["tank_audit"])


if __name__ == "__main__":
    unittest.main()
