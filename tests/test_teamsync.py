"""teamsync: the rows that bring an approved guild to its approved teams."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import raidteams  # noqa: E402
import teamsync  # noqa: E402


def _bonkers_now():
    """Bonkers as the guild holds it today: current names, no recruits."""
    out = []
    for s in raidteams.seats("Bonkers"):
        if s.was or s.name in ("Zug", "Uzza", "Zrog", "Zork", "Oz"):
            out.append(
                {
                    "name": s.was or s.name,
                    "class_id": s.class_id,
                    "race": teamsync.RACE_IDS[s.race],
                    "level": 20,
                }
            )
    for old, _new in raidteams.SUMMONERS["Bonkers"] + raidteams.MAINTENANCE["Bonkers"]:
        out.append({"name": old, "class_id": 9, "race": 5, "level": 20})
    for name in raidteams.LEAVING["Bonkers"]:
        out.append({"name": name, "class_id": 4, "race": 5, "level": 16})
    return out


# playerbots_account_type.account_type: 1 RNDbot (rotated by the manager),
# 2 AddClass (kept for the `addclass` chat command).
RNDBOT = 1
ADDCLASS = 2

ORC_SHAMAN = {
    "name": "Randomorc",
    "class_id": 7,
    "race": 2,
    "level": 1,
    "account_type": RNDBOT,
}
TROLL_SHAMAN = {
    "name": "Randomtroll",
    "class_id": 7,
    "race": 8,
    "level": 1,
    "account_type": RNDBOT,
}
HIGH_ORC_SHAMAN = {
    "name": "Oldorc",
    "class_id": 7,
    "race": 2,
    "level": 55,
    "account_type": RNDBOT,
}
# The AddClass pool's never-played level-1 characters, and one on a player's
# own account: the lowest levels on the realm, and never logged in by it.
POOL_ORC_SHAMAN = {
    "name": "Poolorc",
    "class_id": 7,
    "race": 2,
    "level": 1,
    "account_type": ADDCLASS,
}
ALT_ORC_SHAMAN = {
    "name": "Altorc",
    "class_id": 7,
    "race": 2,
    "level": 1,
    "account_type": None,
}


class Order(unittest.TestCase):
    def test_leavers_go_first_a_few_at_a_time(self):
        acts = teamsync.plan("Bonkers", _bonkers_now(), [], set(), False)
        removes = [a for a in acts if a.kind == "remove"]
        self.assertEqual(len(removes), teamsync.REMOVES_PER_PASS)
        self.assertTrue(all(a.target in raidteams.LEAVING["Bonkers"] for a in removes))

    def test_no_invite_while_the_guild_is_full(self):
        acts = teamsync.plan("Bonkers", _bonkers_now(), [ORC_SHAMAN], set(), False)
        # 71 members, 2 leaving this pass: room for 0 until they are gone.
        self.assertEqual([a for a in acts if a.kind == "invite"], [])

    def test_with_room_a_recruit_of_the_seat_class_and_race_is_invited(self):
        members = [
            m for m in _bonkers_now() if m["name"] not in raidteams.LEAVING["Bonkers"]
        ]
        acts = teamsync.plan(
            "Bonkers",
            members,
            [HIGH_ORC_SHAMAN, ORC_SHAMAN, TROLL_SHAMAN],
            set(),
            False,
        )
        invites = [a.target for a in acts if a.kind == "invite"]
        self.assertIn("Randomorc", invites)
        self.assertNotIn("Oldorc", invites)

    def test_a_row_in_flight_is_not_asked_twice(self):
        leaving = set(raidteams.LEAVING["Bonkers"])
        acts = teamsync.plan("Bonkers", _bonkers_now(), [], leaving, False)
        self.assertEqual([a for a in acts if a.kind == "remove"], [])


class NoInviteBesideARemoval(unittest.TestCase):
    def test_a_pass_that_removes_does_not_invite(self):
        # Room for invites (67 members) while two leavers remain.
        members = [
            m
            for m in _bonkers_now()
            if m["name"] not in raidteams.LEAVING["Bonkers"][:6]
        ]
        acts = teamsync.plan(
            "Bonkers", members, [ORC_SHAMAN, TROLL_SHAMAN], set(), False
        )
        self.assertTrue([a for a in acts if a.kind == "remove"])
        self.assertEqual([a for a in acts if a.kind == "invite"], [])

    def test_invites_follow_once_the_leavers_are_gone(self):
        members = [
            m for m in _bonkers_now() if m["name"] not in raidteams.LEAVING["Bonkers"]
        ]
        acts = teamsync.plan("Bonkers", members, [ORC_SHAMAN], set(), False)
        self.assertEqual([a.target for a in acts if a.kind == "invite"], ["Randomorc"])


def _bonkers_with_room():
    return [m for m in _bonkers_now() if m["name"] not in raidteams.LEAVING["Bonkers"]]


class RecruitsOnlyWhoTheRealmLogsIn(unittest.TestCase):
    """A seat goes to a character on a rotating random-bot account, however
    low the others' levels: an AddClass or player-account character is never
    logged in by the realm, so it would hold the seat out of the world."""

    def test_the_pool_and_an_alt_lose_to_a_rotating_bot_of_the_same_level(self):
        acts = teamsync.plan(
            "Bonkers",
            _bonkers_with_room(),
            [POOL_ORC_SHAMAN, ALT_ORC_SHAMAN, ORC_SHAMAN],
            set(),
            False,
        )
        invites = [a.target for a in acts if a.kind == "invite"]
        self.assertIn("Randomorc", invites)
        self.assertNotIn("Poolorc", invites)
        self.assertNotIn("Altorc", invites)

    def test_with_only_the_pool_and_an_alt_nobody_is_invited(self):
        acts = teamsync.plan(
            "Bonkers",
            _bonkers_with_room(),
            [POOL_ORC_SHAMAN, ALT_ORC_SHAMAN],
            set(),
            False,
        )
        self.assertEqual([a for a in acts if a.kind == "invite"], [])

    def test_an_unknown_account_type_is_not_a_rotating_bot(self):
        self.assertEqual(teamsync.ROTATING_ACCOUNT_TYPE, RNDBOT)
        self.assertTrue(teamsync.logs_in_by_itself(ORC_SHAMAN))
        self.assertFalse(teamsync.logs_in_by_itself(POOL_ORC_SHAMAN))
        self.assertFalse(teamsync.logs_in_by_itself(ALT_ORC_SHAMAN))
        self.assertFalse(
            teamsync.logs_in_by_itself({"name": "Old", "class_id": 7, "race": 2})
        )


class Renames(unittest.TestCase):
    def test_no_rename_until_the_verb_is_live(self):
        acts = teamsync.plan("Bonkers", _bonkers_now(), [], set(), False)
        self.assertEqual([a for a in acts if a.kind == "rename"], [])

    def test_approved_names_are_asked_for_a_few_at_a_time(self):
        acts = teamsync.plan("Bonkers", _bonkers_now(), [], set(), True)
        renames = [a for a in acts if a.kind == "rename"]
        self.assertEqual(len(renames), teamsync.RENAMES_PER_PASS)
        self.assertTrue(
            all((a.target, a.new_name) in raidteams.renames("Bonkers") for a in renames)
        )

    def test_a_recruit_takes_its_seat_name(self):
        members = [
            m for m in _bonkers_now() if m["name"] not in raidteams.LEAVING["Bonkers"]
        ]
        members.append(dict(ORC_SHAMAN))
        seated = teamsync.recruits_in_guild("Bonkers", members)
        orc_shaman_seats = [
            s.name
            for s in raidteams.seats("Bonkers")
            if s.class_id == 7 and s.race == "Orc" and not s.was and s.name != "Zrog"
        ]
        self.assertEqual(seated[orc_shaman_seats[0]]["name"], "Randomorc")
        acts = teamsync.plan("Bonkers", members, [], set(), True)
        renamed = {a.target: a.new_name for a in acts if a.kind == "rename"}
        # Renames go in raidteams order; the recruit's is among the wanted ones.
        wanted = [(o, n) for o, n in raidteams.renames("Bonkers")] + [
            ("Randomorc", orc_shaman_seats[0])
        ]
        self.assertTrue(set(renamed.items()) <= set(wanted))

    def test_a_name_already_taken_in_the_guild_is_not_asked_for(self):
        members = _bonkers_now()
        old, new = raidteams.renames("Bonkers")[0]
        members.append({"name": new, "class_id": 1, "race": 2, "level": 20})
        acts = teamsync.plan("Bonkers", members, [], set(), True)
        self.assertNotIn(
            (old, new), [(a.target, a.new_name) for a in acts if a.kind == "rename"]
        )


OPEN_CAVE = ("Ezzo", "Fizzog", "Fuggo", "Gorrk", "Haggo", "Hrunt")


def _cave_live():
    """Cave as it stood on 2026-10-08: 71 members, the 6 recruits invited on
    2026-10-05 still at level 1 under their own names, empty LEAVING."""
    out = []
    for s in raidteams.seats("Cave"):
        if s.name not in OPEN_CAVE:
            out.append(
                {
                    "name": s.was or s.name,
                    "class_id": s.class_id,
                    "race": teamsync.RACE_IDS[s.race],
                    "level": 20,
                }
            )
    for old, _new in raidteams.SUMMONERS["Cave"] + raidteams.MAINTENANCE["Cave"]:
        out.append({"name": old, "class_id": 9, "race": 5, "level": 20})
    recruits = [
        ("Ahesun", 7, 11),
        ("Anduum", 7, 11),
        ("Anklitlu", 9, 7),
        ("Awudis", 9, 7),
        ("Aramas", 9, 1),
        ("Caedarin", 9, 1),
    ]
    out += [{"name": n, "class_id": c, "race": r, "level": 1} for n, c, r in recruits]
    return out


class StalledOnRenames(unittest.TestCase):
    def test_the_live_cave_numbers(self):
        members = _cave_live()
        self.assertEqual(len(members), 71)
        # The 6 raid seats and, since #927, the 5 questers'.
        self.assertEqual(
            len(teamsync.open_seats("Cave", [m["name"] for m in members])), 11
        )
        self.assertEqual(len(teamsync.recruits_in_guild("Cave", members)), 6)

    def test_an_empty_plan_with_open_seats_says_why(self):
        members = _cave_live()
        pending = {m["name"] for m in members if m["level"] == 1}
        acts = teamsync.plan("Cave", members, [], pending, False)
        self.assertEqual(acts, [])
        why = teamsync.stall_reason(
            "Cave", members, [], pending, True, {"target not online": 6}
        )
        self.assertIn("6 seats are filled by recruits already in the guild", why)
        self.assertIn("Ahesun as Ezzo", why)
        self.assertIn("target not online x6", why)

    def test_a_full_guild_with_a_candidate_and_no_leaver_says_so(self):
        members = [m for m in _cave_live() if m["level"] != 1]
        members += [
            {"name": "Filler%d" % i, "class_id": 1, "race": 1, "level": 5}
            for i in range(teamsync.GUILD_SIZE - len(members))
        ]
        cand = [
            {
                "name": "Newbie",
                "class_id": 7,
                "race": 11,
                "level": 1,
                "account_type": RNDBOT,
            }
        ]
        why = teamsync.stall_reason("Cave", members, cand, set(), True)
        self.assertIn(
            "the guild is full (76) and the approved teams name no leaver", why
        )
        self.assertIn(
            "no candidate on a rotating random-bot account fits Fizzog (level 1 "
            "or under), Fuggo (level 1 or under), Gorrk (level 1 or under), "
            "Haggo (level 1 or under), Hrunt (level 1 or under), Tharn (level 10 "
            "or under), Mirra (level 10 or under), Velo (level 10 or under), "
            "Durga (level 10 or under), Fizzik (level 10 or under)",
            why,
        )

    def test_the_head_not_in_the_world_is_named(self):
        members = [m for m in _cave_live() if m["level"] != 1]
        cand = [
            {
                "name": "Newbie",
                "class_id": 7,
                "race": 11,
                "level": 1,
                "account_type": RNDBOT,
            }
        ]
        why = teamsync.stall_reason("Cave", members, cand, set(), False)
        self.assertIn("the family head is not in the world", why)

    def test_nothing_open_nothing_said(self):
        members = _cave_live()
        members = [
            dict(m, name=seat)
            for seat, m in teamsync.recruits_in_guild("Cave", members).items()
        ] + [m for m in members if m["level"] != 1]
        members += [_quester(q) for q in raidteams.QUESTERS["Cave"]]
        self.assertEqual(teamsync.stall_reason("Cave", members, [], set()), "")


def _quester(q, name="", level=1):
    return {
        "name": name or q.name,
        "class_id": q.class_id,
        "race": teamsync.RACE_IDS[q.race],
        "level": level,
    }


def _bonkers_full_raid():
    """Bonkers with every raid, summoner and maintenance seat filled under its
    approved name, and no leaver: 71 members, only the questers to come."""
    out = [
        {
            "name": s.name,
            "class_id": s.class_id,
            "race": teamsync.RACE_IDS[s.race],
            "level": 20,
        }
        for s in raidteams.seats("Bonkers")
    ]
    for _old, new in raidteams.SUMMONERS["Bonkers"] + raidteams.MAINTENANCE["Bonkers"]:
        out.append({"name": new, "class_id": 9, "race": 5, "level": 20})
    return out


ORC_WARLOCK = {
    "name": "Randomlock",
    "class_id": 9,
    "race": 2,
    "level": 4,
    "account_type": RNDBOT,
}
TROLL_ROGUE = {
    "name": "Randomrogue",
    "class_id": 4,
    "race": 8,
    "level": 2,
    "account_type": RNDBOT,
}


class Questers(unittest.TestCase):
    """The questing group (#927): recruited, renamed and reset to level 1."""

    def test_the_ten_seats_of_922_five_per_guild(self):
        self.assertEqual(sorted(raidteams.QUESTERS), ["Bonkers", "Cave"])
        for guild in raidteams.QUESTERS:
            self.assertEqual(len(raidteams.QUESTERS[guild]), 5)
        everyone = [q for g in raidteams.QUESTERS.values() for q in g]
        self.assertEqual(len({q.name for q in everyone}), 10)
        self.assertEqual({q.class_id for q in everyone}, {2, 3, 4, 5, 7, 9, 11})
        self.assertEqual(
            [(q.name, q.race, q.zone) for q in raidteams.QUESTERS["Bonkers"]],
            [
                ("Saelis", "Blood Elf", "Sunstrider Isle"),
                ("Morwick", "Undead", "Deathknell"),
                ("Hoofa", "Tauren", "Camp Narache"),
                ("Grakk", "Orc", "Valley of Trials"),
                ("Zinja", "Troll", "Valley of Trials"),
            ],
        )
        self.assertEqual(
            {q.zone for q in everyone},
            {
                "Shadowglen",
                "Northshire Valley",
                "Ammen Vale",
                "Coldridge Valley",
                "Sunstrider Isle",
                "Deathknell",
                "Camp Narache",
                "Valley of Trials",
            },
        )

    def test_the_guild_has_room_for_the_questers(self):
        self.assertEqual(len(_bonkers_full_raid()), 71)
        self.assertEqual(teamsync.GUILD_SIZE, 76)

    def test_a_random_bot_of_the_seat_race_and_class_is_invited(self):
        acts = teamsync.plan(
            "Bonkers", _bonkers_full_raid(), [ORC_WARLOCK, TROLL_ROGUE], set(), True
        )
        self.assertEqual(
            [(a.kind, a.target, a.why) for a in acts],
            [
                ("invite", "Randomlock", "recruit for Grakk's seat"),
                ("invite", "Randomrogue", "recruit for Zinja's seat"),
            ],
        )

    def test_an_in_flight_quester_invite_does_not_hold_other_seats(self):
        acts = teamsync.plan(
            "Bonkers",
            _bonkers_full_raid(),
            [ORC_WARLOCK, TROLL_ROGUE],
            {"Randomlock"},
            True,
        )
        self.assertEqual(
            [(a.kind, a.target) for a in acts if a.kind == "invite"],
            [("invite", "Randomrogue")],
        )

    def test_expired_invite_candidate_can_be_retried(self):
        # Once the bridge's bounded pending window expires, the old target is
        # no longer reserved and the next fitting candidate can be invited.
        second = dict(ORC_WARLOCK, name="Secondlock")
        acts = teamsync.plan(
            "Bonkers",
            _bonkers_full_raid(),
            [ORC_WARLOCK, second],
            {ORC_WARLOCK["name"]},
            True,
        )
        self.assertEqual(
            [(a.kind, a.target) for a in acts if a.kind == "invite"],
            [("invite", "Secondlock")],
        )

    def test_a_raid_seat_is_recruited_before_a_quester_seat(self):
        members = [m for m in _bonkers_full_raid() if m["name"] != "Hungrygrunt"]
        lock = dict(ORC_WARLOCK, level=1)
        acts = teamsync.plan("Bonkers", members, [lock], set(), False)
        self.assertEqual(
            [a.why for a in acts if a.kind == "invite"],
            ["recruit for Hungrygrunt's seat"],
        )

    def test_a_raid_seat_takes_level_1_and_a_quester_seat_up_to_10(self):
        # #1015: a raid recruit keeps its levels, so its seat takes level 1
        # only; a quester is reset to level 1, so a level-4 bot may fill one.
        members = [m for m in _bonkers_full_raid() if m["name"] != "Hungrygrunt"]
        acts = teamsync.plan("Bonkers", members, [ORC_WARLOCK], set(), False)
        self.assertEqual(
            [a.why for a in acts if a.kind == "invite"],
            ["recruit for Grakk's seat"],
        )
        self.assertEqual(teamsync.RAID_RECRUIT_MAX_LEVEL, 1)
        self.assertEqual(teamsync.QUESTER_RECRUIT_MAX_LEVEL, 10)

    def test_a_joined_recruit_takes_the_quester_name(self):
        members = _bonkers_full_raid() + [
            _quester(raidteams.QUESTERS["Bonkers"][3], "Randomlock", 4)
        ]
        acts = teamsync.plan("Bonkers", members, [], set(), True)
        self.assertIn(
            ("rename", "Randomlock", "Grakk"),
            [(a.kind, a.target, a.new_name) for a in acts],
        )

    def test_a_named_quester_is_reset_to_level_1_once(self):
        members = _bonkers_full_raid() + [
            _quester(raidteams.QUESTERS["Bonkers"][3], level=4)
        ]
        acts = teamsync.plan("Bonkers", members, [], set(), True, reset_done=set())
        resets = [a for a in acts if a.kind == "reset"]
        self.assertEqual([a.target for a in resets], ["Grakk"])
        self.assertEqual(teamsync.RESET_COMMAND, "reset-level-1")
        done = teamsync.plan("Bonkers", members, [], set(), True, reset_done={"Grakk"})
        self.assertEqual([a for a in done if a.kind == "reset"], [])
        flight = teamsync.plan(
            "Bonkers", members, [], {"Grakk"}, True, reset_done=set()
        )
        self.assertEqual([a for a in flight if a.kind == "reset"], [])

    def test_a_quester_recruit_is_invited_seated_renamed_then_reset_across_passes(self):
        guild = "Bonkers"
        recruit = dict(ORC_WARLOCK)
        invite = teamsync.plan(
            guild, _bonkers_full_raid(), [recruit], set(), True, reset_done=set()
        )
        self.assertEqual(
            [(a.kind, a.target) for a in invite], [("invite", "Randomlock")]
        )

        joined = _bonkers_full_raid() + [
            _quester(raidteams.QUESTERS[guild][3], "Randomlock", recruit["level"])
        ]
        self.assertEqual(joined[-1]["level"], recruit["level"])
        # The recruit holds Grakk's seat by class and race before taking its name.
        self.assertEqual(teamsync.recruits_in_guild(guild, joined)["Grakk"], joined[-1])
        rename = teamsync.plan(guild, joined, [], set(), True, reset_done=set())
        rename_action = next(a for a in rename if a.kind == "rename")
        self.assertEqual(
            (rename_action.target, rename_action.new_name), ("Randomlock", "Grakk")
        )

        renamed = joined[:-1] + [dict(joined[-1], name=rename_action.new_name)]
        self.assertEqual(renamed[-1]["name"], "Grakk")
        self.assertEqual(renamed[-1]["level"], recruit["level"])
        reset = teamsync.plan(guild, renamed, [], set(), True, reset_done=set())
        self.assertEqual(
            [(a.kind, a.target) for a in reset if a.kind == "reset"],
            [("reset", "Grakk")],
        )

    def test_an_unread_ledger_resets_nobody(self):
        members = _bonkers_full_raid() + [_quester(raidteams.QUESTERS["Bonkers"][3])]
        acts = teamsync.plan("Bonkers", members, [], set(), True, reset_done=None)
        self.assertEqual([a for a in acts if a.kind == "reset"], [])

    def test_a_raid_recruit_and_a_member_not_yet_named_are_never_reset(self):
        members = _bonkers_full_raid() + [
            _quester(raidteams.QUESTERS["Bonkers"][3], "Randomlock")
        ]
        acts = teamsync.plan("Bonkers", members, [], set(), True, reset_done=set())
        self.assertEqual([a for a in acts if a.kind == "reset"], [])

    def test_resets_are_paced(self):
        members = _bonkers_full_raid() + [
            _quester(q) for q in raidteams.QUESTERS["Bonkers"]
        ]
        acts = teamsync.plan("Bonkers", members, [], set(), True, reset_done=set())
        self.assertEqual(
            [a.target for a in acts if a.kind == "reset"], ["Saelis", "Morwick"]
        )

    def test_a_named_quester_is_not_taken_for_a_raid_seat(self):
        members = [m for m in _bonkers_full_raid() if m["name"] != "Hungrygrunt"]
        members.append(_quester(raidteams.QUESTERS["Bonkers"][3]))
        self.assertEqual(teamsync.recruits_in_guild("Bonkers", members), {})


if __name__ == "__main__":
    unittest.main()


REFUSED_BAND = (
    '{"outcome":"refused","reason":"too far above the guild to be doing what it does",'
    '"character":"Zug","request":"invite","guild":"Bonkers","candidate":"Randomlock"}'
)


def _refused(name, age, result=REFUSED_BAND, status="unchanged", detail=""):
    return {
        "target_arg": name,
        "status": status,
        "detail": detail,
        "result": result,
        "age": age,
    }


class Refusals(unittest.TestCase):
    """#1015: a refused invite comes back `unchanged` with its reason in
    `result`; the pass reads it and does not ask the same candidate again."""

    def test_the_reason_is_read_from_result_on_an_unchanged_row(self):
        self.assertEqual(
            teamsync.refusal_reason("unchanged", "", REFUSED_BAND),
            "too far above the guild to be doing what it does",
        )

    def test_an_error_row_says_it_in_detail(self):
        self.assertEqual(teamsync.refusal_reason("error", "boom", None), "boom")
        self.assertEqual(teamsync.refusal_reason("error", "", None), "no detail")

    def test_an_answer_that_is_not_a_refusal_is_not_one(self):
        self.assertEqual(
            teamsync.refusal_reason("unchanged", "", '{"outcome":"invited"}'), ""
        )
        self.assertEqual(teamsync.refusal_reason("unchanged", "", "not json"), "")

    def test_a_config_refusal_holds_an_hour(self):
        self.assertEqual(
            teamsync.refused_candidates([_refused("Randomlock", 59)]),
            {"Randomlock": "too far above the guild to be doing what it does"},
        )
        self.assertEqual(teamsync.refused_candidates([_refused("Randomlock", 60)]), {})

    def test_a_lasting_refusal_holds_six_hours(self):
        lasting = (
            '{"outcome":"refused","reason":"already in a guild, and this one '
            'does not take other guilds members"}'
        )
        rows = [_refused("Randomlock", 300, result=lasting)]
        self.assertIn("Randomlock", teamsync.refused_candidates(rows))
        rows = [_refused("Randomlock", 360, result=lasting)]
        self.assertEqual(teamsync.refused_candidates(rows), {})

    def test_a_refused_candidate_is_not_invited_again_and_the_next_one_is(self):
        second = dict(ORC_WARLOCK, name="Secondlock")
        refused = teamsync.refused_candidates([_refused("Randomlock", 10)])
        acts = teamsync.plan(
            "Bonkers",
            _bonkers_full_raid(),
            [ORC_WARLOCK, second],
            set(),
            True,
            refused=refused,
        )
        self.assertEqual([a.target for a in acts if a.kind == "invite"], ["Secondlock"])

    def test_the_stall_line_names_the_module_reason(self):
        rows = [_refused("Randomlock", 5), _refused("Randomrogue", 7)]
        why = teamsync.stall_reason(
            "Bonkers",
            _bonkers_full_raid(),
            [ORC_WARLOCK, TROLL_ROGUE],
            set(),
            True,
            teamsync.refusal_counts(rows),
            teamsync.refused_candidates(rows),
        )
        self.assertIn(
            "the module refused: too far above the guild to be doing what it does x2",
            why,
        )
