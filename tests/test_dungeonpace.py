"""The dungeon ladder: step down from a door the family keeps wiping in (mod-overseer#767).

Pure tests against dungeonpace.py, plus source checks on the bridge pass. The
fixtures are the two families as measured on wow-dev on 2026-09-27: the
Alliance family at 35 to 38 wiping in the Scarlet Library, and the Horde family
at 13 to 17 in Ragefire Chasm, the lowest rung there is.
"""

import asyncio
import pathlib
import unittest
from datetime import datetime, timedelta

import dungeonpace as pace
import jev

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

T0 = datetime(2026, 9, 27, 16, 0, 0)

ALLIANCE = [
    {"name": "Grug", "level": 38, "race": 1, "map_id": 0},
    {"name": "Grog", "level": 36, "race": 3, "map_id": 0},
    {"name": "Bork", "level": 35, "race": 7, "map_id": 0},
    {"name": "Og", "level": 35, "race": 1, "map_id": 0},
    {"name": "Ugga", "level": 35, "race": 1, "map_id": 0},
]
HORDE = [
    {"name": "Zug", "level": 17, "race": 2, "map_id": 1},
    {"name": "Oz", "level": 14, "race": 8, "map_id": 1},
    {"name": "Uzza", "level": 13, "race": 8, "map_id": 1},
    {"name": "Zork", "level": 16, "race": 6, "map_id": 1},
    {"name": "Zrog", "level": 14, "race": 2, "map_id": 1},
]


def run(outcome, minutes, map_id=189):
    return {
        "map_id": map_id,
        "outcome": outcome,
        "started_at": T0 + timedelta(minutes=minutes),
    }


def members(rows, worn=11, total=300.0, armed=True):
    return tuple(pace.Member(r["name"], r["level"], worn, total, armed) for r in rows)


def head(keyword, status="active", source="web:overseer", id_=6, runs=10):
    return {
        "id": id_,
        "keyword": keyword,
        "status": status,
        "source": source,
        "runs_wanted": runs,
        "position": 0,
    }


def facts(
    head_row,
    rows,
    runs=(),
    door=None,
    open_=None,
    changed="",
    done=0,
    level_rows=None,
    avoid=None,
):
    level_rows = level_rows or ALLIANCE
    door = door or head_row["keyword"]
    gates, notes = pace.readiness(door, rows)
    return pace.Facts(
        family="Grug",
        head=head_row,
        door=door,
        door_row=head_row,
        record=pace.viability(
            runs, pace.campaignplan.BY_KEYWORD[head_row["keyword"]].map_id
        ),
        members=rows,
        gates=gates,
        notes=notes,
        open=open_,
        changed=changed,
        done=done,
        cands=tuple(
            pace.candidates(
                head_row["keyword"],
                level_rows,
                frozenset(),
                list(runs),
                avoid=avoid or {head_row["keyword"]},
            )
        ),
    )


class TheRecordOfADoor(unittest.TestCase):
    def test_two_wipes_in_a_row_is_unclearable(self):
        v = pace.viability([run("complete", 0), run("wipe", 10), run("wipe", 20)], 189)
        self.assertEqual(2, v.streak)
        self.assertTrue(v.hard)
        self.assertFalse(v.clearable)

    def test_runs_that_never_fought_do_not_count(self):
        runs = [run("wipe", 0), run("reset_failed", 5), run("staging_failed", 8)]
        v = pace.viability(runs, 189)
        self.assertEqual((1, 1, 1), (v.fought, v.wipes, v.streak))
        self.assertTrue(v.clearable)

    def test_a_high_rate_without_a_streak_is_unclearable_but_not_hard(self):
        runs = [
            run("wipe", 0),
            run("wipe", 10),
            run("left", 20),
            run("wipe", 30),
            run("left", 40),
        ]
        v = pace.viability(runs, 189)
        self.assertFalse(v.hard)
        self.assertFalse(v.clearable)

    def test_runs_before_the_entry_started_are_not_its_record(self):
        runs = [run("wipe", 0), run("wipe", 10), run("complete", 30)]
        v = pace.viability(runs, 189, since=T0 + timedelta(minutes=25))
        self.assertEqual((1, 0, 1), (v.fought, v.wipes, v.complete))

    def test_another_map_is_another_door(self):
        v = pace.viability([run("wipe", 0), run("wipe", 10)], 389)
        self.assertEqual(0, v.fought)


class TheEasierDoors(unittest.TestCase):
    def test_the_alliance_at_35_steps_down_to_the_wing_next_door(self):
        cands = pace.candidates("scarlet-library", ALLIANCE, frozenset(), [])
        self.assertEqual("scarlet", pace.ladder(cands).keyword)
        self.assertIn("gnomeregan", [c.keyword for c in cands])
        self.assertNotIn("scarlet-library", [c.keyword for c in cands])
        beside = {c.keyword: c.beside for c in cands}
        self.assertTrue(beside["scarlet"])
        self.assertFalse(beside["gnomeregan"])

    def test_without_a_wing_beside_it_the_hardest_door_is_taken(self):
        cands = pace.candidates("razorfen-kraul", ALLIANCE, frozenset(), [])
        self.assertFalse(any(c.beside for c in cands))
        self.assertEqual(cands[0].keyword, pace.ladder(cands).keyword)

    def test_jev_is_told_which_door_is_next_door(self):
        f = facts(head("scarlet-library"), members(ALLIANCE), TheDecision.WIPES)
        d = pace.decide(f)
        _state, questions = pace.question(f, d)
        said = str(questions["dungeon"])
        self.assertIn("next door, no travel", said)
        self.assertIn("same instance", said)

    def test_ragefire_is_the_lowest_rung(self):
        self.assertEqual([], pace.candidates("ragefire", HORDE, frozenset(), []))

    def test_a_door_the_family_keeps_wiping_in_is_not_a_candidate(self):
        gnome = pace.campaignplan.BY_KEYWORD["gnomeregan"].map_id
        runs = [run("wipe", 0, gnome), run("wipe", 10, gnome)]
        cands = pace.candidates("scarlet-library", ALLIANCE, frozenset(), runs)
        self.assertNotIn("gnomeregan", [c.keyword for c in cands])


class TheDecision(unittest.TestCase):
    WIPES = [run("wipe", 0), run("wipe", 10)]

    def test_two_wipes_step_down_and_jev_may_not_keep_the_door(self):
        d = pace.decide(facts(head("scarlet-library"), members(ALLIANCE), self.WIPES))
        self.assertEqual(pace.STEP_DOWN, d.kind)
        self.assertEqual("scarlet", d.target)
        self.assertNotIn(pace.STAY, d.offer)
        self.assertIn("gnomeregan", d.offer)

    def test_a_high_rate_alone_lets_jev_keep_the_door(self):
        runs = [run("wipe", 0), run("left", 5), run("wipe", 10), run("left", 20)]
        d = pace.decide(facts(head("scarlet-library"), members(ALLIANCE), runs))
        self.assertEqual(pace.STEP_DOWN, d.kind)
        self.assertIn(pace.STAY, d.offer)

    def test_a_wipe_on_the_way_back_in_steps_down_at_once(self):
        f = facts(head("scarlet-library"), members(ALLIANCE), [run("wipe", 0)])
        self.assertFalse(pace.decide(f).acts)
        back = pace.decide(pace.replace(f, returned=True))
        self.assertEqual(pace.STEP_DOWN, back.kind)
        self.assertEqual("scarlet", back.target)
        self.assertIn("beat the family again", back.why)

    def test_an_entry_that_starts_after_the_step_back_is_the_return(self):
        """wow-dev 2026-09-28: stepped back up at 00:14:54, the Library entry
        started at 01:01:43, and the family wiped at 01:08."""
        back = T0
        self.assertTrue(pace.returned(T0 + timedelta(minutes=47), back))
        self.assertTrue(pace.returned(T0 - timedelta(minutes=5), back))
        self.assertTrue(pace.returned(None, back))
        self.assertFalse(pace.returned(T0, None))
        late = T0 + timedelta(hours=pace.RETURN_HOURS, minutes=1)
        self.assertFalse(pace.returned(late, back))

    def test_a_clearable_door_holds(self):
        runs = [run("wipe", 0), run("complete", 10)]
        d = pace.decide(facts(head("scarlet-library"), members(ALLIANCE), runs))
        self.assertFalse(d.acts)

    def test_below_the_floor_with_no_easier_door_quests(self):
        f = facts(
            head("ragefire", id_=4, runs=50), members(HORDE), [], level_rows=HORDE
        )
        self.assertEqual(("Uzza is level 13 and Ragefire Chasm wants 15",), f.gates)
        d = pace.decide(f)
        self.assertEqual(pace.QUEST, d.kind)
        self.assertEqual((pace.LEVEL,), d.offer)

    def test_questing_ends_on_a_named_change_with_the_gate_open(self):
        opened = {"id": 1, "decision": pace.QUEST, "baseline": ""}
        grown = [dict(r, level=max(r["level"], 15)) for r in HORDE]
        waiting = pace.decide(
            facts(
                head("ragefire", id_=4),
                members(HORDE),
                [],
                open_=opened,
                level_rows=HORDE,
                changed="level gained: Uzza 13 -> 14",
            )
        )
        self.assertFalse(waiting.acts)
        back = pace.decide(
            facts(
                head("ragefire", id_=4),
                members(grown, worn=14),
                [],
                open_=opened,
                level_rows=grown,
                changed="level gained: Uzza 13 -> 15",
            )
        )
        self.assertEqual(pace.RELEASE, back.kind)

    def _questing_bare(self, age):
        """The Horde family as measured 2026-09-29: levels gained, 8 slots empty."""
        opened = {"id": 1, "decision": pace.QUEST, "baseline": "", "age": age}
        grown = [dict(r, level=max(r["level"], 15)) for r in HORDE]
        return pace.decide(
            facts(
                head("ragefire", id_=4),
                members(grown, worn=9),
                [],
                open_=opened,
                level_rows=grown,
                changed="level gained: Uzza 13 -> 15",
            )
        )

    def test_bare_slots_hold_a_fresh_questing_stretch_back(self):
        d = self._questing_bare(age=60)
        self.assertFalse(d.acts)
        self.assertIn("six or more empty slots", d.why)

    def test_bare_slots_do_not_hold_a_questing_family_out_of_its_door_for_ever(self):
        """The gear hold has a ceiling so shopping cannot deadlock a campaign
        (#146); the questing release had none, and a family that cannot buy
        gear stayed on the fallback for two days with its levels gained."""
        d = self._questing_bare(age=pace.QUEST_GEAR_CEILING_SECONDS)
        self.assertEqual(pace.RELEASE, d.kind)

    def test_the_ceiling_never_waives_the_level_gate_or_the_named_change(self):
        opened = {
            "id": 1,
            "decision": pace.QUEST,
            "baseline": "",
            "age": pace.QUEST_GEAR_CEILING_SECONDS * 10,
        }
        still_low = pace.decide(
            facts(
                head("ragefire", id_=4),
                members(HORDE, worn=9),
                [],
                open_=opened,
                level_rows=HORDE,
                changed="level gained: Uzza 13 -> 14",
            )
        )
        self.assertFalse(still_low.acts)
        unchanged = [dict(r, level=max(r["level"], 15)) for r in HORDE]
        nothing_new = pace.decide(
            facts(
                head("ragefire", id_=4),
                members(unchanged, worn=9),
                [],
                open_=opened,
                level_rows=unchanged,
                changed="",
            )
        )
        self.assertFalse(nothing_new.acts)

    def _stepping(self, runs, changed="", done=0, open_=None, rows=None):
        step = head("gnomeregan", source=pace.SOURCE, id_=9, runs=5)
        f = facts(
            step,
            rows or members(ALLIANCE, worn=14),
            runs,
            door="scarlet-library",
            open_=open_ or {"id": 1, "decision": pace.STEP_DOWN, "baseline": ""},
            changed=changed,
            done=done,
        )
        return pace.decide(f)

    def test_the_step_down_door_runs_on_with_nothing_changed(self):
        self.assertFalse(self._stepping([]).acts)

    def test_the_count_reached_with_nothing_changed_extends_rather_than_goes_back(self):
        d = self._stepping([], done=5)
        self.assertEqual(pace.EXTEND, d.kind)

    def test_a_named_change_steps_back_up(self):
        d = self._stepping([], changed="level gained: Bork 35 -> 36", done=2)
        self.assertEqual((pace.STEP_UP, "scarlet-library"), (d.kind, d.target))

    def test_a_named_change_with_a_member_unarmed_does_not_step_up(self):
        """wow-dev 2026-09-28: three members filled 21 slots, the ladder went
        back up to the Library, and the family wiped at once with Og and Ugga
        still holding no weapon and nine or ten slots empty."""
        rows = tuple(
            pace.Member(
                m.name,
                m.level,
                7 if m.name in ("Og", "Ugga") else 15,
                300.0,
                m.name not in ("Og", "Ugga"),
            )
            for m in members(ALLIANCE)
        )
        d = self._stepping(
            [], changed="upgrade equipped: Bork filled 7 slot(s)", done=2, rows=rows
        )
        self.assertNotEqual(pace.STEP_UP, d.kind)
        self.assertIn("no main-hand weapon: Og, Ugga", d.why)

    def test_the_count_reached_with_a_member_unarmed_extends(self):
        rows = tuple(
            pace.Member(m.name, m.level, 14, 300.0, m.name != "Og")
            for m in members(ALLIANCE)
        )
        d = self._stepping([], changed="level gained: Bork 35 -> 36", done=5, rows=rows)
        self.assertEqual(pace.EXTEND, d.kind)

    def test_an_unclearable_step_down_door_steps_further_down(self):
        gnome = pace.campaignplan.BY_KEYWORD["gnomeregan"].map_id
        d = self._stepping([run("wipe", 0, gnome), run("wipe", 5, gnome)])
        self.assertEqual(pace.FURTHER, d.kind)
        self.assertEqual("scarlet", d.target)

    def test_a_step_down_that_ran_its_count_closes_as_a_step_up(self):
        f = facts(
            head("scarlet-library", status="queued"),
            members(ALLIANCE),
            [],
            open_={"id": 1, "decision": pace.STEP_DOWN, "baseline": ""},
        )
        self.assertEqual(pace.STEP_UP, pace.decide(f).kind)


class NamedChange(unittest.TestCase):
    def test_level_slot_and_item_levels(self):
        before = pace.baseline(members(ALLIANCE[:1], worn=10, total=250.0))
        self.assertEqual(
            "", pace.named_change(before, members(ALLIANCE[:1], 10, 252.0))
        )
        self.assertIn(
            "upgrade equipped",
            pace.named_change(before, members(ALLIANCE[:1], 11, 250.0)),
        )
        self.assertIn(
            "upgrade equipped",
            pace.named_change(before, members(ALLIANCE[:1], 10, 256.0)),
        )
        up = [dict(ALLIANCE[0], level=39)]
        self.assertIn(
            "level gained: Grug 38 -> 39",
            pace.named_change(before, members(up, 10, 250.0)),
        )


class _Answer:
    def __init__(self, choice, confidence):
        self.choice = choice
        self.confidence = confidence
        self.probabilities = {choice: confidence}


class _Outcome:
    def __init__(self, choice, confidence):
        self.answers = {"dungeon": _Answer(choice, confidence)}
        self.status = jev.ANSWERED
        self.latency_ms = 5
        self.model = "jev-test"


class _Client:
    def __init__(self, choice, confidence):
        self.outcome = _Outcome(choice, confidence)
        self.asked = []

    async def ask(self, kind, state, questions):
        self.asked.append((kind, state, questions))
        return self.outcome


class JevPicks(unittest.TestCase):
    def _ask(self, choice, confidence):
        f = facts(head("scarlet-library"), members(ALLIANCE), TheDecision.WIPES)
        d = pace.decide(f)
        rule = pace.policy({})
        client = _Client(choice, confidence)
        judgment = asyncio.run(pace.ask(client, f, d, rule))
        return d, judgment, client

    def test_a_confident_pick_is_carried_out(self):
        d, judgment, client = self._ask("gnomeregan", 0.8)
        self.assertEqual(pace.KIND, client.asked[0][0])
        self.assertEqual(jev.JEV, judgment.acted)
        self.assertEqual("gnomeregan", pace.carried(d, judgment).target)
        self.assertEqual(("jev", 0.8), pace.chooser(judgment))

    def test_below_the_floor_the_ladder_stands(self):
        d, judgment, _ = self._ask("gnomeregan", 0.3)
        self.assertEqual("scarlet", pace.carried(d, judgment).target)
        self.assertEqual(("rule", 0.3), pace.chooser(judgment))

    def test_a_door_not_offered_is_never_carried_out(self):
        d, judgment, _ = self._ask("stay", 0.99)
        self.assertEqual("scarlet", pace.carried(d, judgment).target)


class TheBridgePass(unittest.TestCase):
    def test_the_ladder_runs_before_the_gear_hold_and_the_step(self):
        body = BRIDGE[BRIDGE.index("    async def _campaign_queue_once") :]
        body = body[: body.index("    async def _leave_town_when_done")]
        self.assertLess(body.index('"_queue_holds"'), body.index("campaignqueue.step("))
        holds = BRIDGE[BRIDGE.index("    async def _queue_holds(") :]
        holds = holds[: holds.index("    async def _pace_facts(")]
        self.assertLess(holds.index("_dungeon_pace"), holds.index("_queue_gear_hold"))

    def test_the_pace_never_cancels_or_shortens_a_queue(self):
        body = BRIDGE[BRIDGE.index("def _pace_close(") :]
        body = body[: body.index("\ndef _pace_adopt(")]
        self.assertIn("SHIFT_SQL", body)
        self.assertNotIn("CANCEL_SQL", body)
        self.assertNotIn("runs_wanted -", body)
        self.assertNotIn("runs_wanted -", pace.EXTEND_SQL)

    def test_a_dungeon_writer_never_passes_the_questing_family(self):
        self.assertIn("_queue_owns_job, None, True", BRIDGE)
        self.assertIn(
            'if family in globals().get("_PACE_QUESTING", {}) and not dungeon:', BRIDGE
        )


if __name__ == "__main__":
    unittest.main()
