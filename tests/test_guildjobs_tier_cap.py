"""A guild member at a profession tier cap visits its trainer first (#1116).

Measured on the dev realm on 2026-10-18: fifteen guild members stood at
exactly 75/75 in a gathering trade, each with the level and (all but one) the
purse for Journeyman. Raiders of a guild with no craft focus never reach a
train step at all (their job is the post and the sale), and the rest reach
it only as the last rung, behind PvP, the post and the level walk, so a trade
at its ceiling waited behind every one of them. A trade at its ceiling gains
nothing until the rank is bought, so the rank walk now comes ahead of those
rungs, for every role, while the member is not inside a battleground (a
member only waiting in a queue walks too).

Pure unit tests against guildjobs.plan.
"""

import json
import unittest

import guildjobs
import pvpgear

H, M, S = guildjobs.HERBALISM, guildjobs.MINING, guildjobs.SKINNING
FA = guildjobs.FIRST_AID
ROGUE = 4


def member(name="Funkymon", role=guildjobs.RAIDER, **over):
    base = dict(
        name=name,
        guild="Bonkers",
        role=role,
        level=30,
        class_id=ROGUE,
        race=2,
        online=True,
        map_id=1,
        x=0.0,
        y=0.0,
        money=10903,
        eligible=True,
        skills={H: (75, 75), S: (75, 75), FA: (40, 75)},
    )
    base.update(over)
    return guildjobs.Member(**base)


def aim(name="Funkymon"):
    return pvpgear.Aim(name, "Bonkers", 30, 19325, "Outrider's Bow", 400, 0, pvpgear.AV)


def train_steps(result, name):
    return [s for s in result.steps if s.holder == name and s.action == "train"]


class AMemberAtATierCap(unittest.TestCase):
    def test_a_raider_with_no_craft_focus_walks_to_its_trainer(self):
        result = guildjobs.plan([member()])
        (step,) = train_steps(result, "Funkymon")
        self.assertIn(step.key, (H, S))
        self.assertIn("walk-to-trainer skill:%d" % step.key, step.rows[0].command)
        self.assertIn("up to 150", step.said)

    def test_each_tier_cap_buys_the_rank_above_it(self):
        for value, level, want in ((75, 10, 150), (150, 20, 225), (225, 35, 300)):
            with self.subTest(cap=value):
                m = member(level=level, money=60000, skills={M: (value, value)})
                (step,) = train_steps(guildjobs.plan([m]), "Funkymon")
                self.assertEqual(M, step.key)
                self.assertIn("up to %d" % want, step.said)

    def test_a_summoner_at_its_cap_trains_too(self):
        m = member(role=guildjobs.SUMMONER, class_id=9)
        self.assertEqual(1, len(train_steps(guildjobs.plan([m]), "Funkymon")))

    def test_a_summoner_a_summon_waits_on_stays_at_its_door(self):
        m = member(role=guildjobs.SUMMONER, class_id=9)
        result = guildjobs.plan([m], pending=("Funkymon",))
        self.assertEqual([], train_steps(result, "Funkymon"))

    def test_the_rank_walk_comes_before_a_pvp_buy(self):
        m = member(role=guildjobs.MAINTENANCE, skills={M: (75, 75), S: (75, 75)})
        a = aim()
        pvp = {"Funkymon": (a, pvpgear.Move(pvpgear.BUY, ""))}
        result = guildjobs.plan([m], pvp=pvp)
        self.assertEqual(1, len(train_steps(result, "Funkymon")))
        self.assertFalse(any(s.action == "pvp" for s in result.steps))

    def test_a_member_inside_a_battleground_stays_held(self):
        pvp = {"Funkymon": (aim(), pvpgear.Move(pvpgear.INSIDE, "plays"))}
        result = guildjobs.plan([member()], pvp=pvp)
        self.assertEqual((), result.steps)

    def test_a_member_waiting_in_a_queue_walks_to_its_trainer(self):
        # Live on wow-dev 2026-10-19/20: Flintt (Arathi Basin, to fill the
        # cohort) and Funkymon (Warsong Gulch) sat in a PvP queue that never
        # popped on nearly every pass, and neither got a rank walk. The module
        # walks a queued member like any other.
        pvp = {"Funkymon": (aim(), pvpgear.Move(pvpgear.WAITING, "waits"))}
        result = guildjobs.plan([member()], pvp=pvp)
        self.assertEqual(1, len(train_steps(result, "Funkymon")), result.notes)

    def test_a_member_asked_to_queue_again_walks_to_its_trainer(self):
        # A queue accepted past WAITING_MINUTES is asked again (QUEUE, queued).
        pvp = {"Funkymon": (aim(), pvpgear.Move(pvpgear.QUEUE, "queues", True))}
        result = guildjobs.plan([member()], pvp=pvp)
        self.assertEqual(1, len(train_steps(result, "Funkymon")), result.notes)
        self.assertFalse(any(s.action == "pvp" for s in result.steps))

    def test_a_trade_short_of_its_cap_keeps_its_old_place(self):
        # 72 of 75 is within RANK_UP_MARGIN, so the ordinary job buys it; the
        # PvP buy still comes first, as before.
        m = member(role=guildjobs.MAINTENANCE, skills={M: (72, 75), FA: (40, 75)})
        pvp = {"Funkymon": (aim(), pvpgear.Move(pvpgear.BUY, ""))}
        result = guildjobs.plan([m], pvp=pvp)
        self.assertEqual([], train_steps(result, "Funkymon"))
        self.assertTrue(any(s.action == "pvp" for s in result.steps))

    def test_the_top_rank_is_never_asked_for(self):
        m = member(level=60, money=900000, skills={H: (300, 300)})
        self.assertEqual([], train_steps(guildjobs.plan([m]), "Funkymon"))

    def test_a_short_purse_saves_and_says_so(self):
        result = guildjobs.plan([member(money=399)])
        self.assertEqual([], train_steps(result, "Funkymon"))
        self.assertTrue(any("saves for" in n for n in result.notes), result.notes)

    def test_a_maintenance_member_says_its_purse_note_once(self):
        m = member(role=guildjobs.MAINTENANCE, money=399, skills={H: (75, 75)})
        (note,) = [n for n in guildjobs.plan([m]).notes if "saves for" in n]
        self.assertEqual(1, note.count("saves for"), note)

    def test_a_failed_walk_cools_down_and_the_member_does_its_job(self):
        failed = tuple(
            guildjobs.Recent("Funkymon", "train", 5, "error", skill) for skill in (H, S)
        )
        result = guildjobs.plan([member()], recent=failed)
        self.assertEqual([], train_steps(result, "Funkymon"))

    def test_a_member_not_yet_natural_spends_nothing(self):
        result = guildjobs.plan([member(eligible=False)])
        self.assertEqual([], train_steps(result, "Funkymon"))

    def test_the_family_is_left_to_its_own_learn_errand(self):
        m = member(name="Oz", role=guildjobs.FAMILY)
        self.assertEqual([], train_steps(guildjobs.plan([m]), "Oz"))

    def test_capped_trades_names_only_a_trade_at_a_ceiling_below_the_top(self):
        m = member(skills={H: (75, 75), M: (74, 75), S: (300, 300), FA: (0, 0)})
        self.assertEqual((H,), guildjobs.capped_trades(m))


class TheRankWalkHasItsOwnAllowance(unittest.TestCase):
    """Live on wow-dev 2026-10-18 after eff63a7: one rank walk in about 4 hours
    while 15 trades sat at a tier cap. The members planned ahead of a capped
    one used the guild's STEPS_PER_GUILD on their own jobs, and the rank walk,
    counted against the same 4, was refused every pass."""

    def ahead(self, count=guildjobs.STEPS_PER_GUILD):
        # Planned before Funkymon (same role and guild, earlier names), each
        # with post waiting at its mailbox: a job step against STEPS_PER_GUILD.
        crew = [
            member(name="Aa%d" % i, level=40, skills={FA: (40, 75)})
            for i in range(count)
        ]
        mail = {m.name: ("take-item mail:1 item:2",) for m in crew}
        return crew, mail

    def test_the_jobs_ahead_do_not_use_up_the_rank_walk(self):
        crew, mail = self.ahead()
        result = guildjobs.plan(crew + [member()], mail=mail)
        self.assertEqual(1, len(train_steps(result, "Funkymon")), result.notes)
        collects = [s for s in result.steps if s.action == "collect"]
        self.assertEqual(guildjobs.STEPS_PER_GUILD, len(collects))

    def test_rank_walks_keep_a_cap_of_their_own(self):
        capped = [
            member(name="Cap%02d" % i)
            for i in range(guildjobs.TRAIN_STEPS_PER_GUILD + 2)
        ]
        result = guildjobs.plan(capped)
        trains = [s for s in result.steps if s.action == "train"]
        self.assertEqual(guildjobs.TRAIN_STEPS_PER_GUILD, len(trains))


def walk_row(reason, age, outcome="refused", retryable=True):
    """A trainer row the way the realm writes it (MailWalkJson): status error,
    the module's reason, and whether it calls the reason retryable."""
    result = json.dumps(
        {
            "outcome": outcome,
            "reason": reason,
            "retryable": retryable,
            "goal": "trainer",
            "character": "Funkymon",
        },
        separators=(",", ":"),
    )
    return {
        "id": age + 1,
        "target_name": "Funkymon",
        "command": "walk-to-trainer skill:%d max:3000" % H,
        "source": guildjobs.source_for("train", "Funkymon"),
        "status": "error",
        "result": result,
        "age": age,
    }


def walks(reason, *ages, outcome="refused"):
    return guildjobs.recent_from_rows([walk_row(reason, a, outcome) for a in ages])


IN_COMBAT = "character is in combat"
COMBAT_ON_THE_WAY = "entered combat on the way to the trainer"
TOO_FAR = "the nearest trainer that will teach it is beyond the cap"
GROUND = "the ground toward the trainer does not hold"


class AWalkThatEndedInAFightIsAskedAgain(unittest.TestCase):
    """A rank walk the world refused for a fight is no failed trainer walk:
    it does not double the wait, and it is asked again after the base wait."""

    def test_fights_do_not_double_the_wait(self):
        rows = walks(IN_COMBAT, 5, 65, 125, 185, 245)
        self.assertEqual(60, guildjobs.train_cooldown("Funkymon", rows, H))

    def test_the_capped_member_is_sent_again_after_the_base_wait(self):
        m = member(skills={H: (75, 75)})
        result = guildjobs.plan([m], recent=walks(IN_COMBAT, 65, 125, 185, 245))
        self.assertEqual(1, len(train_steps(result, "Funkymon")), result.notes)

    def test_a_fight_still_waits_one_cycle_before_the_walk_is_asked_again(self):
        m = member(skills={H: (75, 75)})
        result = guildjobs.plan([m], recent=walks(IN_COMBAT, 16))
        self.assertEqual([], train_steps(result, "Funkymon"))

    def test_a_fight_on_the_way_counts_as_passing(self):
        rows = walks(COMBAT_ON_THE_WAY, 65, 125, 185, outcome="abandoned")
        self.assertEqual(60, guildjobs.train_cooldown("Funkymon", rows, H))
        m = member(skills={H: (75, 75)})
        result = guildjobs.plan([m], recent=rows)
        self.assertEqual(1, len(train_steps(result, "Funkymon")), result.notes)
        early = guildjobs.plan([m], recent=walks(COMBAT_ON_THE_WAY, 16, outcome="abandoned"))
        self.assertEqual([], train_steps(early, "Funkymon"))


class APermanentRefusalStillBacksOff(unittest.TestCase):
    """The module marks many trainer walls retryable that the next pass will
    not change (a trainer beyond the cap, the ground, Outland, a follower, a
    dead character); each still doubles the wait, so a capped member is not
    sent the same refused walk every pass and reaches the rungs below."""

    def test_a_trainer_beyond_the_cap_doubles_the_wait(self):
        rows = walks(TOO_FAR, 16, 31, 46)
        self.assertEqual(480, guildjobs.train_cooldown("Funkymon", rows, H))

    def test_a_trainer_beyond_the_cap_yields_no_train_step_next_pass(self):
        m = member(skills={H: (75, 75)})
        result = guildjobs.plan([m], recent=walks(TOO_FAR, 16))
        self.assertEqual([], train_steps(result, "Funkymon"))

    def test_other_retryable_walls_back_off_too(self):
        for reason in (
            GROUND,
            "character stands in Outland or Northrend, outside the classic world",
            "character is grouped as a follower",
            "character is dead",
        ):
            with self.subTest(reason=reason):
                rows = walks(reason, 75)
                self.assertEqual(120, guildjobs.train_cooldown("Funkymon", rows, H))
                m = member(skills={H: (75, 75)})
                result = guildjobs.plan([m], recent=rows)
                self.assertEqual([], train_steps(result, "Funkymon"))

    def test_a_reason_that_only_mentions_combat_is_not_passing(self):
        row = guildjobs.Recent(
            "Funkymon",
            "train",
            75,
            "error",
            H,
            result='{"outcome":"refused","note":"was in combat earlier",'
            '"reason":"the ground toward the trainer does not hold"}',
        )
        self.assertEqual(120, guildjobs.train_cooldown("Funkymon", (row,), H))


class AWalkThatFailedForTheRoadStillBacksOff(unittest.TestCase):
    """The road refused at the gate (TrainerGround, TrainerTooFar, both written
    `refused` with retryable:true) and the road failing mid-walk both double
    the wait."""

    def test_the_gate_refusing_the_road_backs_off(self):
        for reason in (GROUND, TOO_FAR):
            with self.subTest(reason=reason):
                rows = walks(reason, 5)
                self.assertEqual(120, guildjobs.train_cooldown("Funkymon", rows, H))
                m = member(skills={H: (75, 75)})
                result = guildjobs.plan([m], recent=walks(reason, 65))
                self.assertEqual([], train_steps(result, "Funkymon"))

    def test_a_walk_that_stalled_on_the_road_backs_off(self):
        rows = walks("stopped getting nearer the trainer", 65, outcome="abandoned")
        self.assertEqual(120, guildjobs.train_cooldown("Funkymon", rows, H))
        m = member(skills={H: (75, 75)})
        result = guildjobs.plan([m], recent=rows)
        self.assertEqual([], train_steps(result, "Funkymon"))


if __name__ == "__main__":
    unittest.main()
