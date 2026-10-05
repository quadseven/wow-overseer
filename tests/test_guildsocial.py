"""The guild's social layer: asks and answers in guild chat (#568), and groups
formed only from accepted answers (#569).

Decided in #521: a member with a real need asks in guild chat, free guildmates
who would gain answer yes, at most two helpers up to ten levels above come for
goodwill, and the coordinator turns an ask and its yeses into a group, the tank
leading and the proposer credited. Nobody is ever seated who did not say yes.
These pin the pure decisions in guildsocial.py, and the bridge wiring as source.
"""

import asyncio
import datetime
import pathlib
import unittest
from dataclasses import replace

import guildrun
import guildsocial as gs
import jev
from test_jev_items import FakeJev

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

WARRIOR, PALADIN, ROGUE, PRIEST, MAGE, WARLOCK = 1, 2, 4, 5, 8, 9
PROTECTION = "12301"
HOLY = "14913"
HUMAN = 1
WESTFALL, STORMWIND, DARKSHORE, DARNASSUS = 40, 1519, 148, 1657
# By the Deadmines' door (entrances.json, map 36), in Westfall.
NEAR = (-11100.0, 1600.0)
NOW = datetime.datetime(2026, 10, 4, 20, 0, 0)
DOORS = guildrun.doors()
DEADMINES = next(d for d in DOORS if d.keyword == "deadmines")
ENTRANCES = {"36": {"map": 0, "x": -11208.5, "y": 1685.34}}


def mate(name, level, class_id, guild="Cave", **kw):
    x, y = kw.pop("at", NEAR)
    row = {
        "name": name,
        "level": level,
        "class_id": class_id,
        "map_id": 0,
        "race": HUMAN,
        "zone_id": WESTFALL,
        "in_combat": 0,
        "health": 300,
        "group_leader": 0,
        "guild_name": guild,
        "talent_spells": None,
        "target_tree": "",
        "pos_x": x,
        "pos_y": y,
        "worn_slots": 6,
        "has_weapon": 1,
    }
    row.update(kw)
    return gs.mate_from_row(row)


def ask(id_, asker, roles="tank,healer,dps,dps", **kw):
    row = {
        "id": id_,
        "guild": "Cave",
        "asker": asker,
        "kind": "dungeon",
        "target": "deadmines",
        "target_label": "The Deadmines",
        "roles_needed": roles,
        "reason": "",
        "said": "",
        "created_at": NOW - datetime.timedelta(minutes=2),
        "expires_at": NOW + datetime.timedelta(minutes=8),
        "state": "open",
        "run_id": None,
    }
    row.update(kw)
    return gs.ask_from_row(row)


def yes(id_, ask_id, member, role, stance="need", state="yes"):
    return gs.answer_from_row(
        {
            "id": id_,
            "ask_id": ask_id,
            "member": member,
            "role": role,
            "stance": stance,
            "said": "",
            "state": state,
        }
    )


def cape_need(name):
    return gs.Need(
        member=name,
        keyword="deadmines",
        item="Cape of the Black Baron",
        entry=5193,
        gain=12.0,
        slot="cloak",
    )


def plan(
    mates, asks=(), answers=(), needs=None, held=None, room=2, can_form=True, **kw
):
    return gs.plan_pass(
        list(mates),
        dict(held or {}),
        list(asks),
        list(answers),
        dict(needs or {}),
        DOORS,
        ENTRANCES,
        NOW,
        room=room,
        can_form=can_form,
        **kw,
    )


def five():
    """An asker and four guildmates who answered: a shielded Protection
    warrior, a Holy priest and two damage dealers."""
    return [
        mate("Auren", 20, ROGUE),
        mate("Tanky", 21, WARRIOR, talent_spells=PROTECTION, has_shield=1),
        mate("Healy", 20, PRIEST, talent_spells=HOLY),
        mate("Zappy", 19, MAGE),
        mate("Locky", 20, WARLOCK),
    ]


def five_yeses():
    return [
        yes(1, 7, "Tanky", "tank"),
        yes(2, 7, "Healy", "healer"),
        yes(3, 7, "Zappy", "dps"),
        yes(4, 7, "Locky", "dps"),
    ]


class TheSwitch(unittest.TestCase):
    def test_on_unless_turned_off(self):
        self.assertTrue(gs.enabled({}))
        self.assertTrue(gs.enabled({"GUILD_SOCIAL": "on"}))
        for off in ("off", "0", "false", "no", "OFF"):
            self.assertFalse(gs.enabled({"GUILD_SOCIAL": off}))

    def test_the_bridge_runs_one_picker_never_both(self):
        loop = BRIDGE[BRIDGE.index("async def _guild_run_loop") :]
        loop = loop[: loop.index("async def _guild_run_once")]
        self.assertIn("if guildsocial.enabled():", loop)
        branch = loop[loop.index("if guildsocial.enabled():") :]
        self.assertLess(
            branch.index("await self._guild_social_once()"),
            branch.index("else:"),
        )
        self.assertLess(
            branch.index("else:"), branch.index("await self._guild_run_once()")
        )
        self.assertEqual(loop.count("await self._guild_run_once()"), 1)


class TheTablesKeepTheContract(unittest.TestCase):
    """The site's guild-chat feed (#570) reads these columns as written."""

    def test_the_ask_table(self):
        for column in (
            "id INT NOT NULL AUTO_INCREMENT",
            "guild VARCHAR(32)",
            "asker VARCHAR(12)",
            "kind ENUM('dungeon','quest','battleground')",
            "target VARCHAR(64)",
            "target_label VARCHAR(96)",
            "roles_needed VARCHAR(32)",
            "reason VARCHAR(160)",
            "said VARCHAR(255)",
            "created_at DATETIME",
            "expires_at DATETIME",
            "state ENUM('open','filled','ran','expired','cancelled')",
            "run_id INT NULL",
        ):
            self.assertIn(column, gs.ASK_TABLE_SQL)

    def test_the_answer_table(self):
        for column in (
            "id INT NOT NULL AUTO_INCREMENT",
            "ask_id INT",
            "member VARCHAR(12)",
            "role ENUM('tank','healer','dps')",
            "stance ENUM('need','help')",
            "said VARCHAR(255)",
            "created_at DATETIME",
            "state ENUM('yes','seated','declined','withdrawn')",
        ):
            self.assertIn(column, gs.ANSWER_TABLE_SQL)

    def test_the_bridge_creates_both_and_credits_the_proposer(self):
        store = BRIDGE[BRIDGE.index("def _ensure_guild_run_store") :]
        store = store[: store.index("_GUILD_RUN_MEMBERS_SQL = (")]
        self.assertIn("guildsocial.ASK_TABLE_SQL", store)
        self.assertIn("guildsocial.ANSWER_TABLE_SQL", store)
        self.assertIn("ADD COLUMN proposer VARCHAR(12)", store)


class WhoAsks(unittest.TestCase):
    def test_a_free_member_with_a_need_asks_in_guild_chat(self):
        out = plan([mate("Auren", 20, ROGUE)], needs={"Auren": [cape_need("Auren")]})
        self.assertEqual(len(out.posts), 1)
        post = out.posts[0]
        self.assertEqual(
            (post.asker, post.target, post.kind), ("Auren", "deadmines", "dungeon")
        )
        self.assertEqual(post.target_label, "The Deadmines")
        # The asker plays damage, so it asks for everyone else.
        self.assertEqual(post.roles_needed, "tank,healer,dps,dps")
        self.assertEqual(post.reason, "Cape of the Black Baron for my cloak slot")
        self.assertIn("The Deadmines", post.said)
        self.assertIn("Cape of the Black Baron", post.said)
        self.assertEqual(post.state, "open")
        self.assertLessEqual(len(post.said), 255)

    def test_a_tank_asks_for_the_other_four(self):
        tank = mate("Tanky", 21, WARRIOR, talent_spells=PROTECTION, has_shield=1)
        out = plan([tank], needs={"Tanky": [cape_need("Tanky")]})
        self.assertEqual(out.posts[0].roles_needed, "healer,dps,dps,dps")

    def test_no_need_no_ask(self):
        self.assertEqual(plan([mate("Auren", 20, ROGUE)]).posts, ())

    def test_a_held_member_does_not_ask(self):
        for why in (
            "in combat",
            "a family member",
            "on a guild job",
            "resting after a run",
        ):
            out = plan(
                [mate("Auren", 20, ROGUE)],
                needs={"Auren": [cape_need("Auren")]},
                held={"Auren": why},
            )
            self.assertEqual(out.posts, (), why)

    def test_one_open_ask_per_member(self):
        out = plan(
            [mate("Auren", 20, ROGUE)],
            asks=[ask(7, "Auren", target="wailing")],
            needs={"Auren": [cape_need("Auren")]},
        )
        self.assertEqual(out.posts, ())

    def test_not_again_so_soon_after_an_ask_came_to_nothing(self):
        old = ask(
            7,
            "Auren",
            state="expired",
            created_at=NOW - datetime.timedelta(minutes=gs.ASK_COOLDOWN_MINUTES - 1),
        )
        out = plan(
            [mate("Auren", 20, ROGUE)],
            asks=[old],
            needs={"Auren": [cape_need("Auren")]},
        )
        self.assertEqual(out.posts, ())
        older = ask(
            7,
            "Auren",
            state="expired",
            created_at=NOW - datetime.timedelta(minutes=gs.ASK_COOLDOWN_MINUTES + 1),
        )
        out = plan(
            [mate("Auren", 20, ROGUE)],
            asks=[older],
            needs={"Auren": [cape_need("Auren")]},
        )
        self.assertEqual(len(out.posts), 1)

    def test_no_ask_while_every_group_the_realm_may_run_is_out(self):
        out = plan(
            [mate("Auren", 20, ROGUE)], needs={"Auren": [cape_need("Auren")]}, room=0
        )
        self.assertEqual(out.posts, ())

    def test_one_new_ask_a_guild_a_pass_the_strongest_need_first(self):
        weak = gs.Need("Bree", "deadmines", "Gloves", entry=1, gain=2.0, slot="gloves")
        strong = gs.Need(
            "Cole", "wailing", "Robe", entry=2, gain=1.0, preraid=True, slot="chest"
        )
        out = plan(
            [mate("Bree", 20, ROGUE), mate("Cole", 20, MAGE)],
            needs={"Bree": [weak], "Cole": [strong]},
        )
        self.assertEqual([p.asker for p in out.posts], ["Cole"])

    def test_a_door_the_guild_does_not_use_is_never_asked_for(self):
        # Ragefire Chasm stands in Orgrimmar: never an Alliance guild's door.
        need = gs.Need("Auren", "ragefire", "Cloak", entry=3, gain=5.0, slot="cloak")
        out = plan([mate("Auren", 16, ROGUE)], needs={"Auren": [need]})
        self.assertEqual(out.posts, ())

    def test_lines_are_varied(self):
        lines = {
            gs.ask_line(
                name, DEADMINES, ["tank", "healer", "dps", "dps"], cape_need(name)
            )
            for name in (
                "Auren",
                "Bree",
                "Cole",
                "Dain",
                "Eria",
                "Faro",
                "Gwen",
                "Hale",
            )
        }
        self.assertGreaterEqual(len(lines), 3)
        for line in lines:
            self.assertTrue(line.isascii())
            self.assertNotIn(chr(0x2014), line)

    def test_roles_in_words(self):
        self.assertEqual(
            gs.roles_words(["tank", "healer", "dps", "dps"]),
            "a tank, a healer and 2 dps",
        )
        self.assertEqual(gs.roles_words(["dps"]), "a dps")


class AFamilyCampaignIsSaidToo(unittest.TestCase):
    def test_the_head_says_its_campaign_once_and_it_runs_as_before(self):
        row = {
            "family": "Grug",
            "keyword": "gnomeregan",
            "guild_name": "Cave",
            "started_at": NOW - datetime.timedelta(minutes=1),
        }
        out = plan([], campaigns=[row])
        self.assertEqual(len(out.posts), 1)
        post = out.posts[0]
        self.assertEqual(
            (post.asker, post.target, post.state), ("Grug", "gnomeregan", "ran")
        )
        self.assertIn("Gnomeregan", post.said)
        said = ask(9, "Grug", target="gnomeregan", state="ran", created_at=NOW)
        self.assertEqual(plan([], asks=[said], campaigns=[row]).posts, ())
        stale = dict(row, started_at=NOW - datetime.timedelta(hours=3))
        self.assertEqual(plan([], campaigns=[stale]).posts, ())


class WhoAnswers(unittest.TestCase):
    def test_free_guildmates_who_would_gain_say_yes_by_their_tree(self):
        out = plan(five(), asks=[ask(7, "Auren")])
        # The scarce seats answer first, each by the tree it plays.
        self.assertEqual(
            [(r.member, r.role, r.stance) for r in out.replies],
            [("Healy", "healer", "need"), ("Tanky", "tank", "need")],
        )
        for reply in out.replies:
            self.assertTrue(reply.said)
            self.assertEqual(reply.ask_id, 7)

    def test_answers_trickle_until_the_seats_are_full(self):
        crowd = five()
        answers = [yes(1, 7, "Tanky", "tank"), yes(2, 7, "Healy", "healer")]
        out = plan(crowd, asks=[ask(7, "Auren")], answers=answers)
        self.assertEqual(sorted(r.member for r in out.replies), ["Locky", "Zappy"])
        self.assertEqual({r.role for r in out.replies}, {"dps"})

    def test_a_warrior_without_a_shield_does_not_take_the_tank_seat(self):
        crowd = [
            mate("Auren", 20, ROGUE),
            mate("Tanky", 21, WARRIOR, talent_spells=PROTECTION, has_shield=0),
        ]
        out = plan(crowd, asks=[ask(7, "Auren")])
        self.assertEqual([(r.member, r.role) for r in out.replies], [("Tanky", "dps")])

    def test_a_member_of_another_guild_never_answers(self):
        crowd = [mate("Auren", 20, ROGUE), mate("Other", 20, MAGE, guild="Bonkers")]
        self.assertEqual(plan(crowd, asks=[ask(7, "Auren")]).replies, ())

    def test_a_busy_member_never_answers(self):
        crowd = [mate("Auren", 20, ROGUE), mate("Zappy", 20, MAGE)]
        for why in (
            "in combat",
            "in a guild run",
            "on a guild job",
            "inside an instance",
        ):
            out = plan(crowd, asks=[ask(7, "Auren")], held={"Zappy": why})
            self.assertEqual(out.replies, (), why)

    def test_far_away_and_busy_questing_means_no(self):
        far = mate("Zappy", 20, MAGE, map_id=1, zone_id=DARKSHORE, at=(6400.0, 400.0))
        out = plan([mate("Auren", 20, ROGUE), far], asks=[ask(7, "Auren")])
        self.assertEqual(out.replies, ())

    def test_idle_in_town_on_the_same_continent_means_yes(self):
        town = mate("Zappy", 20, MAGE, zone_id=STORMWIND, at=(-8800.0, 640.0))
        out = plan([mate("Auren", 20, ROGUE), town], asks=[ask(7, "Auren")])
        self.assertEqual([r.member for r in out.replies], ["Zappy"])

    def test_outside_the_band_and_not_a_helper_means_no(self):
        low = mate("Tiny", 14, MAGE)
        out = plan([mate("Auren", 20, ROGUE), low], asks=[ask(7, "Auren")])
        self.assertEqual(out.replies, ())

    def test_helpers_up_to_ten_levels_above_at_most_two(self):
        crowd = [mate("Auren", 20, ROGUE)] + [
            mate("Old%s" % c, DEADMINES.ceiling + 5, MAGE, zone_id=STORMWIND, at=NEAR)
            for c in "abc"
        ]
        crowd.append(
            mate(
                "Ancient",
                DEADMINES.ceiling + gs.HELPER_LEVELS + 1,
                MAGE,
                zone_id=STORMWIND,
            )
        )
        out = plan(crowd, asks=[ask(7, "Auren")])
        self.assertEqual(len(out.replies), 2)
        self.assertEqual({r.stance for r in out.replies}, {"help"})
        self.assertNotIn("Ancient", [r.member for r in out.replies])
        more = plan(
            crowd,
            asks=[ask(7, "Auren")],
            answers=[
                yes(1, 7, "Olda", "dps", "help"),
                yes(2, 7, "Oldb", "dps", "help"),
            ],
        )
        self.assertEqual(more.replies, ())

    def test_an_upgrade_there_is_worth_the_trip(self):
        # Idle in Darnassus, across the sea: the XP alone is not worth it.
        far = mate("Zappy", 20, MAGE, map_id=1, zone_id=DARNASSUS, at=(9900.0, 2400.0))
        out = plan([mate("Auren", 20, ROGUE), far], asks=[ask(7, "Auren")])
        self.assertEqual(out.replies, ())
        out = plan(
            [mate("Auren", 20, ROGUE), far],
            asks=[ask(7, "Auren")],
            needs={"Zappy": [cape_need("Zappy")]},
        )
        self.assertEqual([r.member for r in out.replies], ["Zappy"])
        self.assertIn("Cape of the Black Baron", out.replies[0].said)

    def test_an_asker_does_not_answer_another_ask(self):
        crowd = [mate("Auren", 20, ROGUE), mate("Bree", 20, MAGE)]
        asks = [ask(7, "Auren"), ask(8, "Bree", target="wailing")]
        self.assertEqual(plan(crowd, asks=asks).replies, ())


class FormedOnlyFromAnswers(unittest.TestCase):
    def test_an_ask_with_enough_yeses_forms_and_the_tank_leads(self):
        out = plan(five(), asks=[ask(7, "Auren")], answers=five_yeses())
        form = out.form
        self.assertIsNotNone(form)
        comp = form.composition
        self.assertEqual(comp.tank.name, "Tanky")
        self.assertEqual(comp.healer.name, "Healy")
        self.assertEqual(sorted(m.name for m in comp.dps), ["Auren", "Locky", "Zappy"])
        self.assertTrue(
            comp.command("deadmines").startswith("finder-run deadmines Healy ")
        )
        self.assertEqual(form.seated, (1, 2, 3, 4))
        self.assertEqual(form.declined, ())
        self.assertIn("Auren's Deadmines group", form.said)

    def test_nobody_who_did_not_say_yes_is_seated(self):
        # A better tank stands free and idle, and said nothing.
        crowd = five() + [
            mate(
                "Shieldy",
                22,
                WARRIOR,
                talent_spells=PROTECTION,
                has_shield=1,
                zone_id=STORMWIND,
            ),
            mate("Bystander", 20, MAGE, zone_id=STORMWIND),
        ]
        out = plan(crowd, asks=[ask(7, "Auren")], answers=five_yeses())
        names = set(out.form.composition.names)
        self.assertEqual(names, {"Auren", "Tanky", "Healy", "Zappy", "Locky"})

    def test_short_of_a_healer_nothing_forms(self):
        answers = [a for a in five_yeses() if a.role != "healer"]
        out = plan(five(), asks=[ask(7, "Auren")], answers=answers)
        self.assertIsNone(out.form)

    def test_a_healer_without_armor_is_not_seated(self):
        crowd = five()
        crowd[2] = mate("Healy", 20, PRIEST, talent_spells=HOLY, worn_slots=1)
        out = plan(crowd, asks=[ask(7, "Auren")], answers=five_yeses())
        self.assertIsNone(out.form)

    def test_a_surplus_yes_is_declined(self):
        crowd = five() + [mate("Extra", 20, MAGE)]
        answers = five_yeses() + [yes(5, 7, "Extra", "dps")]
        out = plan(crowd, asks=[ask(7, "Auren")], answers=answers)
        self.assertEqual(out.form.declined, (5,))

    def test_a_yes_who_left_withdraws_and_nothing_forms(self):
        out = plan(
            five(),
            asks=[ask(7, "Auren")],
            answers=five_yeses(),
            held={"Zappy": "inside an instance"},
        )
        self.assertIsNone(out.form)
        self.assertEqual(out.withdraw, (3,))

    def test_a_yes_in_combat_is_waited_for(self):
        out = plan(
            five(),
            asks=[ask(7, "Auren")],
            answers=five_yeses(),
            held={"Zappy": "in combat"},
        )
        self.assertIsNone(out.form)
        self.assertEqual(out.withdraw, ())

    def test_the_realm_spacing_holds_a_full_ask_as_filled(self):
        out = plan(five(), asks=[ask(7, "Auren")], answers=five_yeses(), can_form=False)
        self.assertIsNone(out.form)
        self.assertEqual(out.filled, (7,))

    def test_helpers_count_in_the_key_and_stay_out_of_the_band(self):
        crowd = five()
        crowd[4] = mate("Locky", DEADMINES.ceiling + 4, WARLOCK)
        answers = five_yeses()[:3] + [yes(4, 7, "Locky", "dps", "help")]
        out = plan(crowd, asks=[ask(7, "Auren")], answers=answers)
        self.assertEqual(out.form.helpers, ("Locky",))
        self.assertTrue(out.form.key.endswith("+1help"))
        self.assertEqual(out.form.band, "20-24")

    def test_the_proposer_tanking_says_it_plainly(self):
        line = gs.formed_line("Tanky", "Tanky", DEADMINES)
        self.assertNotIn("Tanky's", line)
        self.assertIn("The Deadmines", line)


class AsksEnd(unittest.TestCase):
    def test_an_unanswered_ask_expires_and_the_asker_says_so(self):
        old = ask(7, "Auren", expires_at=NOW - datetime.timedelta(seconds=1))
        out = plan(
            [mate("Auren", 20, ROGUE), mate("Zappy", 20, MAGE)],
            asks=[old],
            answers=[yes(1, 7, "Zappy", "dps")],
        )
        self.assertEqual(len(out.expire), 1)
        ask_id, asker, line = out.expire[0]
        self.assertEqual((ask_id, asker), (7, "Auren"))
        self.assertIn("Deadmines", line)
        self.assertEqual(out.withdraw, (1,))
        self.assertEqual(out.replies, ())

    def test_an_asker_who_left_cancels_but_combat_does_not(self):
        out = plan(
            [mate("Auren", 20, ROGUE)],
            asks=[ask(7, "Auren")],
            held={"Auren": "inside an instance"},
        )
        self.assertEqual(out.cancel, (7,))
        out = plan(
            [mate("Auren", 20, ROGUE)],
            asks=[ask(7, "Auren")],
            held={"Auren": "in combat"},
        )
        self.assertEqual(out.cancel, ())


class WhatAMemberNeeds(unittest.TestCase):
    """A boss drop the member can use now that scores higher for its spec."""

    ENCOUNTERS = [{"map_id": 36, "creature": 639, "name": "Edwin VanCleef"}]

    def drop(self, **kw):
        row = {
            "Item": 5193,
            "creature": 639,
            "item_name": "Cape of the Black Baron",
            "item_level": 24,
            "required_level": 17,
            "allowable_class": -1,
            "class": 4,
            "subclass": 1,
            "inventory_type": 16,
            "armor": 21,
            "stat_type1": 3,
            "stat_value1": 10,
        }
        row.update(kw)
        return row

    def needs(self, member, drop):
        drops = gs.index_drops(self.ENCOUNTERS, [drop])
        # A leather chest, so recap knows the armor it can wear.
        chest = {
            "name": member.name,
            "slot": 4,
            "entry": 1,
            "item_name": "Tunic",
            "item_level": 10,
            "class": 4,
            "subclass": 2,
            "inventory_type": 5,
        }
        gear = gs.gear_by_name(
            [
                {
                    "name": member.name,
                    "level": member.member.level,
                    "class_id": member.member.class_id,
                }
            ],
            [chest],
            [],
        )
        member = gs.Mate(member.member, member.x, member.y, gear[member.name])
        return gs.needs_for(member, drops, DOORS, "Alliance")

    def test_an_empty_cloak_slot_and_a_cloak_at_the_door(self):
        found = self.needs(mate("Auren", 20, ROGUE), self.drop())
        self.assertEqual(
            [(n.keyword, n.entry, n.slot) for n in found],
            [("deadmines", 5193, "cloak")],
        )
        self.assertGreater(found[0].gain, 0)

    def test_a_drop_for_another_class_is_no_need(self):
        self.assertEqual(
            self.needs(mate("Auren", 20, ROGUE), self.drop(allowable_class=128)), []
        )

    def test_a_drop_above_its_level_is_no_need(self):
        self.assertEqual(
            self.needs(mate("Auren", 20, ROGUE), self.drop(required_level=25)), []
        )

    def test_a_door_above_its_level_is_no_need(self):
        self.assertEqual(self.needs(mate("Auren", 15, ROGUE), self.drop()), [])

    def test_a_dungeon_quest_in_the_log_is_a_need(self):
        quests = gs.quests_by_name(
            [
                {
                    "name": "Auren",
                    "quest": 214,
                    "title": "Red Silk Bandanas",
                    "zone": 1581,
                }
            ]
        )
        found = gs.needs_for(
            mate("Auren", 20, ROGUE), {}, DOORS, "Alliance", quests["Auren"]
        )
        self.assertEqual([(n.keyword, n.quest) for n in found], [("deadmines", 214)])
        line = gs.ask_line("Auren", DEADMINES, ["tank", "healer"], found[0])
        self.assertIn("Red Silk Bandanas", line)
        self.assertEqual(gs.ask_reason(found[0]), "the quest Red Silk Bandanas")

    def test_a_pre_raid_pick_ranks_first(self):
        plain = gs.Need("A", "deadmines", "x", entry=1, gain=50.0)
        pick = gs.Need("A", "scholomance", "y", entry=2, gain=1.0, preraid=True)
        quest = gs.Need("A", "wailing", "z", quest=9)
        self.assertEqual(
            sorted([quest, plain, pick], key=lambda n: n.rank), [pick, plain, quest]
        )


def ended(keyword, outcome, shape="class-tank/class-healer", band="20-24"):
    return {
        "keyword": keyword,
        "band": band,
        "composition": shape,
        "state": "ended",
        "outcome": outcome,
        "deaths": 4,
        "ended_at": NOW - datetime.timedelta(hours=1),
    }


def robe_need(name):
    return gs.Need(name, "wailing", "Robe", entry=2, gain=6.0, slot="chest")


class TheDoorsRecordGatesTheAsk(unittest.TestCase):
    """#584: an ask consults the door's record for the shape of group the
    guild can seat (a real tank or not, a real healer or not), counting the
    runs the finder turned away, and never asks for a door failing for it."""

    def asks_for(self, rows, mates=None):
        out = plan(
            mates or [mate("Auren", 20, ROGUE)],
            needs={"Auren": [cape_need("Auren"), robe_need("Auren")]},
            records=guildrun.shape_records(rows, NOW),
        )
        return [p.target for p in out.posts if p.asker == "Auren"]

    def test_a_door_failing_for_the_shape_is_not_asked_for(self):
        rows = [ended("deadmines", "wiped")] * guildrun.FAILING_RUNS
        self.assertEqual(self.asks_for(rows), ["wailing"])

    def test_the_finder_turning_groups_away_closes_the_door(self):
        rows = [ended("deadmines", "not entered")] * guildrun.TURNED_AWAY_RUNS
        self.assertEqual(self.asks_for(rows), ["wailing"])

    def test_another_shapes_failures_do_not(self):
        # Five free guildmates seat a real tank and a real healer: the class
        # tank's wipes are not this group's record.
        rows = [ended("deadmines", "wiped")] * guildrun.FAILING_RUNS
        self.assertEqual(self.asks_for(rows, five()), ["deadmines"])
        shaped = [
            ended("deadmines", "wiped", shape="spec-tank/spec-healer")
        ] * guildrun.FAILING_RUNS
        self.assertEqual(self.asks_for(shaped, five()), ["wailing"])

    def test_every_door_failing_still_asks_for_the_best_need(self):
        # A failing door is a preference, not a ban: with every fitting door
        # failing, the guild still asks (Cave sat silent at 15 to 19 for hours
        # with Wailing Caverns failing for every shape).
        rows = [ended("deadmines", "wiped")] * guildrun.FAILING_RUNS + [
            ended("wailing", "refused")
        ] * guildrun.TURNED_AWAY_RUNS
        self.assertEqual(self.asks_for(rows), ["deadmines"])

    def cleared_asks(self, rows, cleared):
        out = plan(
            [mate("Auren", 20, ROGUE)],
            needs={"Auren": [cape_need("Auren"), robe_need("Auren")]},
            records=guildrun.shape_records(rows, NOW),
            cleared=cleared,
        )
        return [p.target for p in out.posts if p.asker == "Auren"]

    def test_a_cleared_door_ranks_below_one_the_guild_has_not_cleared(self):
        # Bonkers cleared Ragefire twice and Jev kept choosing it over
        # Wailing Caverns: level order means the uncleared door is asked for.
        self.assertEqual(self.cleared_asks([], {("Cave", "deadmines")}), ["wailing"])

    def test_an_uncleared_failing_door_beats_a_cleared_one(self):
        rows = [ended("wailing", "wiped")] * guildrun.FAILING_RUNS
        self.assertEqual(
            self.cleared_asks(rows, {("Cave", "deadmines")}), ["wailing"]
        )

    def test_another_guilds_clear_does_not_count(self):
        self.assertEqual(
            self.cleared_asks([], {("Bonkers", "deadmines")}), ["deadmines"]
        )

    def test_a_cleared_door_is_still_asked_for_when_nothing_else_fits(self):
        self.assertEqual(
            self.cleared_asks([], {("Cave", "deadmines"), ("Cave", "wailing")}),
            ["deadmines"],
        )

    def test_cleared_doors_reads_each_guilds_clears(self):
        rows = [
            dict(ended("ragefire", "cleared"), guild="Bonkers"),
            dict(ended("wailing", "wiped"), guild="Bonkers"),
            dict(ended("deadmines", "cleared"), guild=""),
        ]
        self.assertEqual(guildrun.cleared_doors(rows), {("Bonkers", "ragefire")})

    def test_a_healthy_door_still_wins_over_a_failing_better_need(self):
        rows = [ended("deadmines", "wiped")] * guildrun.FAILING_RUNS
        out = plan(
            [mate("Auren", 20, ROGUE)],
            needs={"Auren": [cape_need("Auren"), robe_need("Auren")]},
            records=guildrun.shape_records(rows, NOW),
        )
        post = [p for p in out.posts if p.asker == "Auren"][0]
        self.assertEqual([o.door.keyword for o in post.options], ["wailing"])

    def test_the_post_carries_each_door_and_its_record(self):
        rows = [ended("wailing", "not entered")] * 2
        out = plan(
            [mate("Auren", 20, ROGUE)],
            needs={"Auren": [cape_need("Auren"), robe_need("Auren")]},
            records=guildrun.shape_records(rows, NOW),
        )
        post = out.posts[0]
        self.assertEqual((post.band, post.shape), ("20-24", "class-tank/class-healer"))
        self.assertEqual(
            [o.door.keyword for o in post.options], ["deadmines", "wailing"]
        )
        self.assertEqual(post.options[1].record.turned_away, 2)


def two_door_post():
    """Auren's ask: Deadmines first by its need, Wailing Caverns also open,
    with two groups the finder turned away there."""
    rows = [ended("wailing", "not entered")] * 2
    out = plan(
        [mate("Auren", 20, ROGUE)],
        needs={"Auren": [cape_need("Auren"), robe_need("Auren")]},
        records=guildrun.shape_records(rows, NOW),
    )
    return out.posts[0]


class JevChoosesTheDoor(unittest.TestCase):
    """#584: one Jev question per new ask with more than one door, at
    guildrun's floor; below it the best need's door stands."""

    def post(self):
        return two_door_post()

    def choose(self, fake, post=None):
        client = jev.Client("k", transport=fake)
        return asyncio.run(gs.choose_door(client, post or self.post(), environ={}))

    def test_a_confident_answer_changes_the_door_and_the_line(self):
        fake = FakeJev(picks={"door": "wailing"}, confidence=0.9)
        post, judgment = self.choose(fake)
        self.assertEqual(len(fake.requests), 1)
        criteria = fake.requests[0]["questions"]["door"]["criteria"]
        self.assertEqual(set(criteria), {"deadmines", "wailing"})
        self.assertIn("turned 2 groups away", criteria["wailing"])
        self.assertIn("class-tank/class-healer", criteria["deadmines"])
        self.assertEqual(post.target, "wailing")
        self.assertIn("Robe", post.said)
        self.assertEqual(post.reason, "Robe for my chest slot")
        self.assertEqual((judgment.kind, judgment.acted), (gs.KIND_ASK_DOOR, jev.JEV))

    def test_below_the_floor_the_best_need_stands(self):
        post, judgment = self.choose(FakeJev(picks={"door": "wailing"}, confidence=0.3))
        self.assertEqual(post.target, "deadmines")
        self.assertEqual(judgment.acted, jev.HEURISTIC)
        self.assertEqual(judgment.jev, "wailing")

    def test_an_answer_naming_a_door_not_offered_keeps_the_heuristics(self):
        # jev.parse admits only offered options; a client that returned one
        # anyway must still leave the best need's door, never fail the pass.
        class Stray:
            async def ask(self, *_a, **_k):
                stray = jev.Choice("ragefire", {"ragefire": 1.0}, 0.99)
                return jev.Outcome(jev.ANSWERED, 5, answers={"door": stray})

        post, judgment = asyncio.run(gs.choose_door(Stray(), self.post(), environ={}))
        self.assertEqual(post.target, "deadmines")
        self.assertEqual(judgment.acted, jev.HEURISTIC)

    def test_one_door_asks_nothing(self):
        fake = FakeJev()
        one = self.post()
        one = replace(one, options=one.options[:1])
        post, judgment = self.choose(fake, one)
        self.assertIsNone(judgment)
        self.assertEqual(fake.requests, [])
        self.assertEqual(post, one)

    def test_the_bridge_asks_before_it_writes(self):
        once = BRIDGE[BRIDGE.index("async def _guild_social_once") :]
        once = once[: once.index("async def _campaign_queue_loop")]
        self.assertIn("records=records", once)
        self.assertIn("guildrun.shape_records(", once)
        self.assertLess(
            once.index("_guild_social_doors("),
            once.index("_write_guild_social"),
        )


class TheBridgeWritesItAsTheCoordinatorDid(unittest.TestCase):
    def test_the_run_row_credits_the_proposer_and_the_tank_gets_the_finder_row(self):
        start = BRIDGE[BRIDGE.index("def _start_social_run") :]
        start = start[: start.index("\ndef ")]
        self.assertIn("proposer", start)
        self.assertIn("form.ask.asker", start)
        self.assertIn("comp.command(door.keyword)", start)
        self.assertIn("VALUES (%s, %s, 'guild', %s)", start)
        self.assertIn("guildsocial.ASK_RAN_SQL", start)

    def test_every_line_is_said_in_guild_chat_by_its_speaker(self):
        write = BRIDGE[BRIDGE.index("def _write_guild_social") :]
        write = write[: write.index("\ndef ")]
        self.assertIn(
            'relay.SpeakCommand(name, "guild", text, "", guildsocial.SOURCE)', write
        )

    def test_askers_and_yeses_are_kept_off_guild_jobs(self):
        loop = BRIDGE[BRIDGE.index("async def _guild_run_loop") :]
        loop = loop[: loop.index("async def _guild_run_once")]
        self.assertIn('getattr(self, "_guild_social_names", ())', loop)


class TheGuildTabSaysWhoAsked(unittest.TestCase):
    def test_an_asked_run_names_its_proposer(self):
        view = guildrun.page(
            [
                {
                    "id": 1,
                    "guild": "Cave",
                    "band": "20-24",
                    "composition": "spec-tank/spec-healer",
                    "keyword": "deadmines",
                    "tank": "Tanky",
                    "proposer": "Auren",
                    "members": "Tanky:tank:warrior:21",
                    "dungeon_by": "ask",
                    "composition_by": "answers",
                    "state": "queued",
                }
            ]
        )
        lines = view["active"][0]["lines"]
        self.assertEqual(lines[0], "dungeon: Auren asked for it in guild chat")
        self.assertIn("answered yes", lines[1])


if __name__ == "__main__":
    unittest.main()
