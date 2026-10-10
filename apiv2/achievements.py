"""GET /api/v2/achievements?guild=G | ?name=X: the announcer's achievements.

Flavor, and nothing else. An achievement is a line of dry commentary on
something a member already did, read after the fact from rows the realm
already keeps. Nothing is granted in the game, nothing is stored, and nothing
here writes: there is no table of achievements, so every read builds them
again from the same rows and gets the same answer.

WHERE EACH ONE COMES FROM, every read bounded by a window and a row cap:

  overseer_death       how a member died: drowned, fell, a creature well
                       below its level, another player, a corpse run, and how
                       often (DEATH_DAYS)
  overseer_guild_run   how a guild run came back: firsts per dungeon, clears,
                       wipes, timeouts, refusals (RUN_DAYS); the deaths of a
                       wiped run inside its own window say who fell first
  overseer_level       level milestones (RUN_DAYS)
  overseer_event       loot, equips, quests, crafts, learning to ride, town
                       trips, repairs, gifts and fishing (EVENT_DAYS)
  overseer_guild_ask   the class quest asks members.py reads as stuck: the
                       same quest asked for again and again, and a run of
                       asks that stood for a day (ASK_DAYS)
  overseer_command     the realm's own answers to two orders: a cloth sale at
                       a vendor, and a hearthstone that arrived (DEATH_DAYS)

ONCE EACH. A member earns a rule once, at the earliest row that meets it; a
guild earns a first once per dungeon. Ties on the same second go to the lower
source id, so the same rows always give the same list. An achievement whose
row ages out of its window drops off the list, and the basis says so.

Gated like every v2 read that takes a name: a family member or a member of a
family guild, else a 404 before any connection is opened; a guild must be a
family guild.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import readcache

import council
import guildrun

from .members import STREAK_GAP_SECONDS

from ._scope import (
    NOT_A_MEMBER,
    holes,
    may_answer,
    name_shaped,
    wanted_name,
)
from . import _scope

TIERS = ("bronze", "silver", "gold", "dubious")
CONTINENTS = frozenset({0, 1, 530, 571})

# A self-attributed death in water, read fresh, with no drop worth the name:
# the module's own reading of a drowning (overseer_decisions, SelfDeathReading).
FALL_GUARD_IN_WATER = 1 << 5
FRESH_SECONDS = 5
LETHAL_FALL_YARDS = 30.0


@dataclass(frozen=True)
class Rule:
    title: str
    line: str
    tier: str
    guild_first: bool = False


RULES: dict[str, Rule] = {
    "drowned_dungeon": Rule(
        "Indoor Swimming",
        "Drowned in {place}. A building full of monsters, and the water got "
        "there first.",
        "dubious",
    ),
    "drowned": Rule(
        "Lungs Optional",
        "Drowned. Breathing turns out to be a skill you have to keep doing.",
        "dubious",
    ),
    "punched_down": Rule(
        "Punched Down",
        "Killed by {killer}, a creature {gap} levels beneath you. It has "
        "already told its friends.",
        "dubious",
    ),
    "humbled": Rule(
        "Humbled by the Wildlife",
        "Killed by {killer}, {gap} levels below you. Somewhere a level "
        "{klevel} is having the best day of its life.",
        "dubious",
    ),
    "death_spiral": Rule(
        "Revolving Door",
        "Died 5 times in 10 minutes. The spirit healer has started saving you a seat.",
        "dubious",
    ),
    "death_marathon": Rule(
        "Frequent Flier",
        "Died 10 times in one hour. That is not a strategy. That is a schedule.",
        "dubious",
    ),
    "professional_corpse": Rule(
        "Professional Corpse",
        "Died 100 times in {days} days. Consistency is a talent, technically.",
        "dubious",
    ),
    "fall_death": Rule(
        "Gravity Check",
        "Fell {yards} yards and stopped all at once. The ground was not consulted.",
        "dubious",
    ),
    "fall_survived": Rule(
        "Stuck the Landing",
        "Fell {yards} yards and lived, right up until {killer} noticed. "
        "Partial credit.",
        "silver",
    ),
    "corpse_run": Rule(
        "Ghost Commute",
        "Walked back to your own body as a ghost. It was right where you left "
        "it, still dead.",
        "bronze",
    ),
    "dungeon_corpse_run": Rule(
        "The Long Way Back In",
        "Ran a corpse run all the way back into {place}. The monsters "
        "respected the effort and nothing else.",
        "silver",
    ),
    "pvp_death": Rule(
        "Player Versus Pavement",
        "Killed by another player, {killer}. Nothing personal. Probably.",
        "bronze",
    ),
    "friendly_fire": Rule(
        "Friendly Fire",
        "Killed by {killer}, who is supposed to be on your side. The family "
        "has declined to comment.",
        "dubious",
    ),
    "hearth_after_one": Rule(
        "Strategic Withdrawal",
        "Died once, then hearthed home {minutes} minutes later. One was "
        "plenty, apparently.",
        "dubious",
    ),
    "first_boss": Rule(
        "First Blood: {place}",
        "{guild} put its first boss of {place} on the floor. The boss had "
        "plans for the evening.",
        "gold",
        guild_first=True,
    ),
    "first_clear": Rule(
        "Cleared Out: {place}",
        "{guild} cleared {place} for the first time. The dungeon will need a moment.",
        "gold",
        guild_first=True,
    ),
    "flawless": Rule(
        "Not a Scratch",
        "Cleared {place} without a single death. Suspicious, but noted.",
        "gold",
    ),
    "speed_clear": Rule(
        "Tourist Rate",
        "Cleared {place} in {minutes} minutes. The bosses barely had time to stand up.",
        "gold",
    ),
    "so_close": Rule(
        "One Boss Short",
        "Wiped in {place} with one boss left. The last boss would like you to "
        "know it was never worried.",
        "dubious",
    ),
    "group_nap": Rule(
        "Group Nap",
        "Part of a full wipe in {place}. Everyone lay down together. Very supportive.",
        "dubious",
    ),
    "wipe_connoisseur": Rule(
        "Wipe Connoisseur",
        "Ten wipes. You now know the floor of {place} on a first-name basis.",
        "dubious",
    ),
    "scenic_route": Rule(
        "The Scenic Route",
        "Spent {minutes} minutes in {place} and left with a time limit instead "
        "of a clear.",
        "dubious",
    ),
    "stood_at_door": Rule(
        "Stood at the Door",
        "Went all the way to {place} and did not go in. Very brave of the door.",
        "dubious",
    ),
    "healer_first": Rule(
        "Healer Down, Everyone Down",
        "Died first in {place}, as the healer. The rest of the party did the math.",
        "dubious",
    ),
    "tank_alone": Rule(
        "Party of One, Again",
        "Died alone at the front in {place}, again. The party was nearby, "
        "presumably taking notes.",
        "dubious",
    ),
    "level_10": Rule(
        "Double Digits",
        "Reached level 10. The tutorial is over. Nobody told you, so here we are.",
        "bronze",
    ),
    "level_20": Rule(
        "Twenty Questions",
        "Reached level 20. Most of the wildlife now hesitates before biting. Most.",
        "bronze",
    ),
    "level_30": Rule(
        "Thirty and Thriving",
        "Reached level 30. Still dying, just at a more respectable level.",
        "silver",
    ),
    "level_40": Rule(
        "Halfway to Relevant",
        "Reached level 40. The world is starting to take you seriously. It should not.",
        "silver",
    ),
    "level_50": Rule(
        "Old Enough to Know Better",
        "Reached level 50. Old enough to know better. Does not.",
        "gold",
    ),
    "level_60": Rule(
        "Out of Numbers",
        "Reached level 60. The world has run out of levels to give you. It has "
        "not run out of ways to kill you.",
        "gold",
    ),
    "first_epic": Rule(
        "Purple Prose",
        "Picked up {item}, an epic. Try not to make it your whole personality.",
        "gold",
    ),
    "first_rare": Rule(
        "Blue Period",
        "Looted {item}. Blue: the color of mild competence.",
        "bronze",
    ),
    "need_roll": Rule(
        "Needed It",
        "Won {item} on a need roll. Need is a strong word. We will allow it.",
        "bronze",
    ),
    "first_mount": Rule(
        "Legs Retired",
        "Learned to ride. Your feet have filed for early retirement.",
        "gold",
    ),
    "cottage_industry": Rule(
        "Cottage Industry",
        "Made {n} {item}. The market for {item} has never been this saturated.",
        "bronze",
    ),
    "errand_runner": Rule(
        "Errand Runner",
        "Turned in {n} quests. Every farmer in the region has your number.",
        "silver",
    ),
    "window_shopping": Rule(
        "Window Shopping",
        "Walked to town, did nothing, and walked back. {n} times.",
        "dubious",
    ),
    "held_by_spite": Rule(
        "Held Together by Spite",
        "Repaired {n} pieces of gear that were fully broken. They had been "
        "decorative for a while.",
        "bronze",
    ),
    "hand_me_down": Rule(
        "Hand-Me-Down",
        "Gave away {item}, a perfectly good rare. Generosity, or a cry for help.",
        "bronze",
    ),
    "water_starer": Rule(
        "Professional Water Starer",
        "Went fishing. Stared at water for a while. Called it a hobby.",
        "bronze",
    ),
    "cloth_liquidator": Rule(
        "Cloth Liquidator",
        "Sold {n} cloth to a vendor for pocket change. Somewhere a tailor felt "
        "a chill.",
        "dubious",
    ),
    "cq_ten": Rule(
        "Persistence Is Not a Plan",
        "Asked for help with {quest} ten times. The quest remains unimpressed.",
        "dubious",
    ),
    "cq_fifty": Rule(
        "Legally Stubborn",
        "Asked for help with {quest} fifty times. At this point it is a relationship.",
        "dubious",
    ),
    "stuck_day": Rule(
        "Local Landmark",
        "Stuck on {quest} for a full day. The pigeons have started using you "
        "for directions.",
        "dubious",
    ),
    "stuck_three_days": Rule(
        "Permanent Fixture",
        "Stuck on {quest} for three days running. You are part of the map now.",
        "dubious",
    ),
}

# Thresholds, each the plain reading of its rule's name.
PUNCHED_DOWN_LEVELS = 5
HUMBLED_LEVELS = 10
SPIRAL = (5, 600)  # deaths, seconds
MARATHON = (10, 3600)
CORPSE_COUNT = 100
FALL_SURVIVED_YARDS = 40.0
HEARTH_AFTER_SECONDS = 15 * 60
HEARTH_QUIET_SECONDS = 3600
DEATH_DAYS = 7
SPEED_CLEAR_SECONDS = 20 * 60
WIPES = 10
ALONE_SECONDS = 60
MILESTONES = (10, 20, 30, 40, 50, 60)
RIDING_SKILL = 762
CRAFTS = 50
QUESTS = 50
POINTLESS_TRIPS = 10
CLOTH = 20
CQ_ASKS = ((10, "cq_ten"), (50, "cq_fifty"))
STUCK = ((24 * 3600, "stuck_day"), (72 * 3600, "stuck_three_days"))
CLEARED = "cleared"
WIPED = "wiped"
TIMED_OUT = "timed out"
NOT_IN = ("refused", "not entered")


# --------------------------------------------------------------- the rules --


def _earn(rule: str, member: str, at, table: str, sid, **facts) -> dict:
    return {
        "rule": rule,
        "member": member,
        "at": int(at or 0),
        "source": {"table": table, "id": int(sid or 0)},
        "facts": facts,
    }


def drowned(d: dict) -> bool:
    """The module's drowning: self-attributed, in water by a fresh reading,
    and no fall that could have done it."""
    mask, seconds = _int(d, "fall_guard_standdown"), _int(d, "fall_guard_seconds")
    if d.get("killer_type") not in ("self", "environment") or mask < 0:
        return False
    if not 0 <= seconds <= FRESH_SECONDS:
        return False
    return bool(mask & FALL_GUARD_IN_WATER) and _yards(d) < LETHAL_FALL_YARDS


def _yards(d: dict) -> float:
    return float(d.get("yards_fallen") or 0.0)


def _int(row: dict, key: str, default: int = -1) -> int:
    v = row.get(key)
    return default if v is None else int(v)


def _death(rule: str, d: dict, **facts) -> dict:
    return _earn(rule, d["name"], d["at"], "overseer_death", d["id"], **facts)


def _how_it_died(d: dict, place, roster: dict):
    """The rules one death row meets on its own."""
    kind, killer = d.get("killer_type"), d.get("killer_name") or "something"
    if drowned(d):
        yield _death("drowned_dungeon" if place else "drowned", d, place=place)
    elif kind == "self" and _yards(d) >= LETHAL_FALL_YARDS:
        yield _death("fall_death", d, yards=round(_yards(d)))
    if kind in ("creature", "player") and _yards(d) >= FALL_SURVIVED_YARDS:
        yield _death("fall_survived", d, yards=round(_yards(d)), killer=killer)
    if kind == "player":
        mine = killer in roster and killer != d["name"]
        yield _death("friendly_fire" if mine else "pvp_death", d, killer=killer)
    if d.get("ghost_recovery") == "corpse_run":
        yield _death("dungeon_corpse_run" if place else "corpse_run", d, place=place)


def _punched_down(d: dict):
    klevel = d.get("killer_level")
    if d.get("killer_type") != "creature" or klevel is None:
        return
    gap = _int(d, "level", 0) - int(klevel)
    facts = {
        "killer": d.get("killer_name") or "something",
        "gap": gap,
        "klevel": klevel,
    }
    if gap >= PUNCHED_DOWN_LEVELS:
        yield _death("punched_down", d, **facts)
    if gap >= HUMBLED_LEVELS:
        yield _death("humbled", d, **facts)


def _death_rules(r: dict, roster: dict):
    maps = r.get("maps") or {}
    for d in r.get("deaths") or ():
        place = maps.get(_int(d, "map", 0))
        yield from _how_it_died(d, place, roster)
        yield from _punched_down(d)


def _by_member(rows) -> dict:
    """name -> its rows, oldest first (ties by id)."""
    out: dict = {}
    for row in rows or ():
        out.setdefault(row["name"], []).append(row)
    for got in out.values():
        got.sort(key=lambda x: (int(x["at"]), int(x["id"])))
    return out


def burst(times: list, n: int, seconds: int):
    """The row that makes `n` deaths inside `seconds`, the earliest, or None."""
    for i in range(len(times) - n + 1):
        if int(times[i + n - 1]["at"]) - int(times[i]["at"]) <= seconds:
            return times[i + n - 1]
    return None


def _count_rules(r: dict, roster: dict):
    for times in _by_member(r.get("death_times")).values():
        for rule, (n, seconds) in (
            ("death_spiral", SPIRAL),
            ("death_marathon", MARATHON),
        ):
            hit = burst(times, n, seconds)
            if hit:
                yield _death(rule, hit)
        if len(times) >= CORPSE_COUNT:
            yield _death(
                "professional_corpse", times[CORPSE_COUNT - 1], days=DEATH_DAYS
            )


def _hearth_rules(r: dict, roster: dict):
    deaths = _by_member(r.get("death_times"))
    for h in r.get("hearths") or ():
        at = int(h["at"])
        before = [
            d
            for d in deaths.get(h["name"], ())
            if at - HEARTH_AFTER_SECONDS - HEARTH_QUIET_SECONDS <= int(d["at"]) <= at
        ]
        if len(before) == 1 and at - int(before[0]["at"]) <= HEARTH_AFTER_SECONDS:
            minutes = max(1, round((at - int(before[0]["at"])) / 60))
            yield _earn(
                "hearth_after_one",
                h["name"],
                at,
                "overseer_command",
                h["id"],
                minutes=minutes,
            )


# -- guild runs --


def seats(members: str) -> list:
    """'Grug:tank:warrior:30,...' -> [(name, role)], in seat order."""
    out = []
    for seat in (members or "").split(","):
        parts = seat.split(":")
        if parts and parts[0]:
            out.append((parts[0], parts[1] if len(parts) > 1 else ""))
    return out


def _place(keyword: str) -> str:
    return council.keyword_place(keyword)


def _run_earn(rule: str, member: str, run: dict, **facts) -> dict:
    return _earn(rule, member, run["at"], "overseer_guild_run", run["id"], **facts)


def _firsts(run: dict, place: str):
    """The guild firsts one run can be: its first boss, its first clear."""
    who = [n for n, _ in seats(run["members"])]
    hits = []
    if int(run.get("bosses_done") or 0) >= 1:
        hits.append("first_boss")
    if run.get("outcome") == CLEARED:
        hits.append("first_clear")
    for rule in hits:
        e = _run_earn(rule, "", run, place=place, key=run.get("keyword") or "")
        yield dict(e, guild=run["guild"], who=who)


def _run_rule(run: dict) -> str | None:
    """The member rule every seat of this run earns, if any."""
    outcome = run.get("outcome")
    if outcome == TIMED_OUT:
        return "scenic_route"
    if outcome in NOT_IN:
        return "stood_at_door"
    if outcome == WIPED:
        last = int(run.get("bosses_total") or 0) - int(run.get("bosses_done") or 0)
        return "so_close" if last == 1 else "group_nap"
    return None


def _clear_rules(run: dict) -> list:
    if run.get("outcome") != CLEARED:
        return []
    out = []
    if int(run.get("deaths") or 0) == 0:
        out.append("flawless")
    if 0 < int(run.get("seconds_inside") or 0) <= SPEED_CLEAR_SECONDS:
        out.append("speed_clear")
    return out


def _seat_rules(run: dict, place: str):
    minutes = round(int(run.get("seconds_inside") or 0) / 60)
    rules = _clear_rules(run)
    single = _run_rule(run)
    if single:
        rules.append(single)
    for name, _role in seats(run["members"]):
        for rule in rules:
            yield _run_earn(rule, name, run, place=place, minutes=minutes)


def _wipe_count(runs: list):
    wiped: dict = {}
    for run in runs:
        if run.get("outcome") != WIPED:
            continue
        for name, _ in seats(run["members"]):
            wiped[name] = wiped.get(name, 0) + 1
            if wiped[name] == WIPES:
                yield _run_earn(
                    "wipe_connoisseur", name, run, place=_place(run.get("keyword"))
                )


def _deaths_in(run: dict, deaths: dict) -> list:
    """The run's members' deaths inside its own window, oldest first."""
    names = {n for n, _ in seats(run["members"])}
    start, end = int(run.get("started_at") or 0), int(run["at"])
    got = [d for n in names for d in deaths.get(n, ()) if start <= int(d["at"]) <= end]
    return sorted(got, key=lambda d: (int(d["at"]), int(d["id"])))


def _alone(death: dict, got: list) -> bool:
    return not any(
        d is not death and abs(int(d["at"]) - int(death["at"])) <= ALONE_SECONDS
        for d in got
    )


def _wipe_order(runs: list, deaths: dict):
    """Who fell first in a wiped run, and the tank who keeps falling alone."""
    lonely: dict = {}
    for run in runs:
        if run.get("outcome") != WIPED:
            continue
        roles = dict(seats(run["members"]))
        got = _deaths_in(run, deaths)
        place = _place(run.get("keyword"))
        if got and roles.get(got[0]["name"]) == "healer":
            yield _death("healer_first", got[0], place=place)
        tank = run.get("tank") or next((n for n, r in roles.items() if r == "tank"), "")
        mine = [d for d in got if d["name"] == tank and _alone(d, got)]
        if mine:
            lonely[tank] = lonely.get(tank, 0) + 1
            if lonely[tank] == 2:
                yield _death("tank_alone", mine[0], place=place)


def _run_rules(r: dict, roster: dict):
    runs = sorted(r.get("runs") or (), key=lambda x: (int(x["at"]), int(x["id"])))
    for run in runs:
        place = _place(run.get("keyword"))
        yield from _firsts(run, place)
        yield from _seat_rules(run, place)
    yield from _wipe_count(runs)
    yield from _wipe_order(runs, _by_member(r.get("run_deaths")))


# -- levels, events, sales --


def _level_rules(r: dict, roster: dict):
    for row in r.get("levels") or ():
        old, new = int(row.get("old") or 0), int(row.get("level") or 0)
        for mark in MILESTONES:
            if old < mark <= new:
                yield _earn(
                    "level_%d" % mark,
                    row["name"],
                    row["at"],
                    "overseer_level",
                    row["id"],
                )


def _event(rule: str, e: dict, **facts) -> dict:
    return _earn(rule, e["name"], e["at"], "overseer_event", e["id"], **facts)


def _item_rules(e: dict):
    kind, quality = e.get("kind"), int(e.get("quality") or 0)
    item = e.get("subject_name") or "something"
    if kind in ("item_loot", "item_equip") and quality == 4:
        yield _event("first_epic", e, item=item)
    if kind == "item_loot" and quality == 3:
        yield _event("first_rare", e, item=item)
    if kind == "item_loot" and e.get("via") == "need":
        yield _event("need_roll", e, item=item)
    if kind == "item_given" and quality >= 3:
        yield _event("hand_me_down", e, item=item)


BROKEN = re.compile(r"\((\d+) broken\) before")


def _odd_jobs(e: dict):
    kind = e.get("kind")
    name = (e.get("subject_name") or "").lower()
    if kind == "learn" and (
        int(e.get("subject_id") or 0) == RIDING_SKILL or "riding" in name
    ):
        yield _event("first_mount", e)
    if kind == "fish":
        yield _event("water_starer", e)
    broken = BROKEN.search(e.get("detail") or "") if kind == "repair" else None
    if broken and int(broken.group(1)) > 0:
        yield _event("held_by_spite", e, n=int(broken.group(1)))


def _pointless(e: dict) -> bool:
    return e.get("kind") == "town_trip" and str(e.get("detail") or "").startswith(
        "vendor: nothing happened"
    )


# rule -> (does this row count, how many it takes)
TALLIES = {
    "errand_runner": (lambda e: e.get("kind") == "quest_reward", QUESTS),
    "window_shopping": (_pointless, POINTLESS_TRIPS),
}


def _tallies(events: list):
    """Rules earned at the row where a member's running count crosses a line."""
    counts: dict = {}
    for e in events:
        n = int(e.get("occurrences") or 1)
        for rule, (counts_it, need) in TALLIES.items():
            if not counts_it(e):
                continue
            k = (rule, e["name"])
            before = counts.get(k, 0)
            counts[k] = before + n
            if before < need <= counts[k]:
                yield _event(rule, e, n=need)
        if e.get("kind") == "craft":
            k = ("craft", e["name"], e.get("subject_name"))
            before = counts.get(k, 0)
            counts[k] = before + n
            if before < CRAFTS <= counts[k]:
                yield _event(
                    "cottage_industry",
                    e,
                    n=counts[k],
                    item=e.get("subject_name") or "things",
                )


def _event_rules(r: dict, roster: dict):
    events = sorted(r.get("events") or (), key=lambda x: (int(x["at"]), int(x["id"])))
    for e in events:
        yield from _item_rules(e)
        yield from _odd_jobs(e)
    yield from _tallies(events)


def _sale_rules(r: dict, roster: dict):
    sold: dict = {}
    for row in sorted(r.get("sales") or (), key=lambda x: (int(x["at"]), int(x["id"]))):
        if not str(row.get("item") or "").endswith("Cloth"):
            continue
        before = sold.get(row["name"], 0)
        sold[row["name"]] = before + int(row.get("count") or 0)
        if before < CLOTH <= sold[row["name"]]:
            yield _earn(
                "cloth_liquidator",
                row["name"],
                row["at"],
                "overseer_command",
                row["id"],
                n=sold[row["name"]],
            )


# -- class quests, and being stuck on them --


def ask_runs(rows: list) -> list:
    """Unbroken runs of asks for one quest by one member, each oldest first:
    the same quest, no silence over members.STREAK_GAP_SECONDS."""
    by: dict = {}
    for row in rows or ():
        by.setdefault((row["asker"], row.get("target")), []).append(row)
    runs = []
    for got in by.values():
        got.sort(key=lambda x: (int(x["at"]), int(x["id"])))
        run = [got[0]]
        for row in got[1:]:
            if int(row["at"]) - int(run[-1]["at"]) > STREAK_GAP_SECONDS:
                runs.append(run)
                run = []
            run.append(row)
        runs.append(run)
    return runs


def _ask(rule: str, row: dict) -> dict:
    return _earn(
        rule,
        row["asker"],
        row["at"],
        "overseer_guild_ask",
        row["id"],
        quest=row.get("target_label") or "a class quest",
    )


def _ask_rules(r: dict, roster: dict):
    by: dict = {}
    for row in r.get("asks") or ():
        by.setdefault((row["asker"], row.get("target")), []).append(row)
    for got in by.values():
        got.sort(key=lambda x: (int(x["at"]), int(x["id"])))
        for need, rule in CQ_ASKS:
            if len(got) >= need:
                yield _ask(rule, got[need - 1])
    for run in ask_runs(r.get("asks")):
        start = int(run[0]["at"])
        for span, rule in STUCK:
            hit = next((x for x in run if int(x["at"]) - start >= span), None)
            if hit:
                yield _ask(rule, hit)


SOURCES = (
    _death_rules,
    _count_rules,
    _hearth_rules,
    _run_rules,
    _level_rules,
    _event_rules,
    _sale_rules,
    _ask_rules,
)


# ------------------------------------------------------------- the awards --


def _key(e: dict) -> tuple:
    if RULES[e["rule"]].guild_first:
        return (e["rule"], e.get("guild") or "", e["facts"].get("key", ""))
    return (e["rule"], e["member"])


def _instance_id(e: dict) -> str:
    return ":".join(str(p) for p in _key(e))


def _shape(e: dict, roster: dict) -> dict:
    rule = RULES[e["rule"]]
    guild = e.get("guild") or roster.get(e["member"], "")
    facts = dict(e["facts"], guild=guild, member=e["member"])
    return {
        "id": _instance_id(dict(e, guild=guild)),
        "rule": e["rule"],
        "title": rule.title.format(**facts),
        "line": rule.line.format(**facts),
        "tier": rule.tier,
        "member": e["member"],
        "who": [n for n in e.get("who") or [e["member"]] if n in roster],
        "guild": guild,
        "earned_at": e["at"],
        "source": e["source"],
    }


def build(r: dict, roster: dict, now_at: int) -> list:
    """Every achievement the rows earn, once each, newest first."""
    best: dict = {}
    for source in SOURCES:
        for e in source(r, roster):
            if e["member"] and e["member"] not in roster:
                continue
            k = _key(dict(e, guild=e.get("guild") or roster.get(e["member"], "")))
            order = (e["at"], e["source"]["id"])
            if k not in best or order < (best[k]["at"], best[k]["source"]["id"]):
                best[k] = e
    out = [_shape(e, roster) for e in best.values()]
    out.sort(key=lambda a: (-a["earned_at"], a["id"]))
    return out


# --------------------------------------------------------------- the reads --
#
# Every read is windowed and capped, oldest first: an achievement is earned at
# its EARLIEST row, so a cap that cuts the newest rows never moves one.
# S608 on each: {holes} and {spans} are runs of placeholders; every value is
# bound by the driver.

DEATH_DAYS_NOTABLE = DEATH_DAYS
RUN_DAYS = 90
EVENT_DAYS = 30
ASK_DAYS = 14
MAX_ROWS = 20000
TIMES_MAX_ROWS = 40000
WIPED_RUNS_READ = 200
# guildrun owns the run table; its read is newest first, so a cap well over
# a window's runs keeps every first in it.
RUNS_READ = 5000
FEED_LIMIT = 120
CACHE_SECONDS = 60.0

EVENT_KINDS = (
    "item_loot",
    "item_equip",
    "item_given",
    "learn",
    "craft",
    "quest_reward",
    "town_trip",
    "repair",
    "fish",
)

MEMBERS_SQL = (
    "SELECT c.name, g.name AS guild FROM characters c "
    "JOIN guild_member gm ON gm.guid = c.guid "
    "JOIN guild g ON g.guildid = gm.guildid WHERE g.name IN ({holes})"
)
NOW_SQL = "SELECT UNIX_TIMESTAMP() AS now_at"
# The deaths worth a second look: anything but an open-world creature kill,
# plus the open-world creature kills by something well below the victim. The
# killer's level is the world's own (creature_template.maxlevel).
DEATHS_SQL = (
    "SELECT d.id, d.character_name AS name, d.level, d.map, d.zone, "
    "d.killer_type, d.killer_name, d.killer_entry, ct.maxlevel AS killer_level, "
    "d.yards_fallen, d.fall_guard_standdown, d.fall_guard_seconds, "
    "d.ghost_recovery, UNIX_TIMESTAMP(d.created_at) AS at "
    "FROM overseer_death d "
    "LEFT JOIN acore_world.creature_template ct "
    "ON d.killer_type = 'creature' AND ct.entry = d.killer_entry "
    "WHERE d.character_name IN ({holes}) "
    "AND d.created_at > NOW() - INTERVAL %s DAY "
    "AND (d.killer_type <> 'creature' OR d.map NOT IN (0, 1, 530, 571) "
    "OR d.yards_fallen >= %s OR d.ghost_recovery = 'corpse_run' "
    "OR ct.maxlevel + %s <= d.level) "
    "ORDER BY d.id LIMIT %s"
)
DEATH_TIMES_SQL = (
    "SELECT id, character_name AS name, UNIX_TIMESTAMP(created_at) AS at "
    "FROM overseer_death WHERE character_name IN ({holes}) "
    "AND created_at > NOW() - INTERVAL %s DAY ORDER BY id LIMIT %s"
)
RUN_DEATHS_SQL = (
    "SELECT id, character_name AS name, UNIX_TIMESTAMP(created_at) AS at "
    "FROM overseer_death WHERE character_name IN ({holes}) AND ({spans}) "
    "ORDER BY id LIMIT %s"
)
RUN_SPAN = "created_at BETWEEN FROM_UNIXTIME(%s) AND FROM_UNIXTIME(%s)"
LEVELS_SQL = (
    "SELECT id, character_name AS name, old_level AS old, new_level AS level, "
    "UNIX_TIMESTAMP(created_at) AS at FROM overseer_level "
    "WHERE character_name IN ({holes}) "
    "AND created_at > NOW() - INTERVAL %s DAY ORDER BY id LIMIT %s"
)
EVENTS_SQL = (
    "SELECT id, character_name AS name, kind, subject_id, subject_name, "
    "subject_quality AS quality, detail, via, occurrences, map, "
    "UNIX_TIMESTAMP(first_seen) AS at FROM overseer_event "
    "WHERE character_name IN ({holes}) AND kind IN ({kinds}) "
    "AND first_seen > NOW() - INTERVAL %s DAY ORDER BY id LIMIT %s"
)
ASKS_SQL = (
    "SELECT id, asker, target, target_label, state, "
    "UNIX_TIMESTAMP(created_at) AS at FROM overseer_guild_ask "
    "WHERE kind = 'quest' AND asker IN ({holes}) "
    "AND created_at > NOW() - INTERVAL %s DAY ORDER BY id LIMIT %s"
)
# The realm's own answers: a sale it read back as sold, and a hearthstone
# whose caster arrived. Only the rows whose answer says so are read.
SALES_SQL = (
    "SELECT id, target_name AS name, result, UNIX_TIMESTAMP(created_at) AS at "
    "FROM overseer_command WHERE kind = 'sell' AND status = 'delivered' "
    "AND target_name IN ({holes}) AND created_at > NOW() - INTERVAL %s DAY "
    "AND result LIKE %s ORDER BY id LIMIT %s"
)
HEARTHS_SQL = (
    "SELECT id, target_name AS name, UNIX_TIMESTAMP(updated_at) AS at "
    "FROM overseer_command WHERE kind = 'hearth' "
    "AND target_name IN ({holes}) AND created_at > NOW() - INTERVAL %s DAY "
    "AND result LIKE %s ORDER BY id LIMIT %s"
)
SOLD_CLOTH_LIKE = '%"outcome":"sold"%Cloth"%'
ARRIVED_LIKE = '%"outcome":"arrived"%'


def sale_row(row: dict) -> dict | None:
    """A vendor sale the realm read back as sold, as {id, name, at, item,
    count}; None for anything else."""
    try:
        answer = json.loads(row.get("result") or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(answer, dict) or answer.get("outcome") != "sold":
        return None
    item = answer.get("item") or {}
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "at": int(row["at"]),
        "item": str(item.get("name") or ""),
        "count": int(item.get("count") or 0),
    }


def _roster(ctx) -> dict:
    """name -> guild for every member a v2 read may answer about: the family
    guilds' members, and the families (a member in no guild reads as "")."""
    names = list(_scope.guilds(ctx).values())
    found = []
    if names:
        sql = MEMBERS_SQL.format(holes=holes(len(names)))
        found = ctx.read.rows(sql, tuple(names), what="guild_member")
    out = {n: "" for n in ctx.server.FAMILIES.names()}
    out.update({r["name"]: r["guild"] for r in found})
    return out


def _named(rd, sql: str, names: list, args: tuple, what: str, **fmt) -> list:
    text = sql.format(holes=holes(len(names)), **fmt)
    return rd.rows(text, (*names, *args), what=what)


def _deaths(rd, names: list) -> dict:
    notable = (DEATH_DAYS, LETHAL_FALL_YARDS, PUNCHED_DOWN_LEVELS, MAX_ROWS)
    return {
        "deaths": _named(rd, DEATHS_SQL, names, notable, "overseer_death"),
        "death_times": _named(
            rd, DEATH_TIMES_SQL, names, (DEATH_DAYS, TIMES_MAX_ROWS), "overseer_death"
        ),
        "hearths": _named(
            rd,
            HEARTHS_SQL,
            names,
            (DEATH_DAYS, ARRIVED_LIKE, MAX_ROWS),
            "overseer_command",
        ),
    }


def _run_deaths(rd, runs: list, roster: dict) -> list:
    wiped = [r for r in runs if r.get("outcome") == WIPED][-WIPED_RUNS_READ:]
    names = sorted({n for r in wiped for n, _ in seats(r["members"]) if n in roster})
    if not names:
        return []
    spans = " OR ".join([RUN_SPAN] * len(wiped))
    times = tuple(t for r in wiped for t in (int(r["started_at"]), int(r["at"])))
    return _named(
        rd, RUN_DEATHS_SQL, names, (*times, MAX_ROWS), "overseer_death", spans=spans
    )


def run_row(row: dict) -> dict:
    """A guildrun row in the shape the run rules read: times in seconds, and
    a run with no end time ending when it was formed."""
    started = int(row.get("created_unix") or 0)
    return dict(row, started_at=started, at=int(row.get("ended_unix") or started))


def _runs(rd, guilds: list, roster: dict) -> dict:
    if not guilds:
        return {"runs": [], "run_deaths": []}
    found = guildrun.ended_since(rd, guilds, RUN_DAYS, RUNS_READ)
    runs = sorted(map(run_row, found), key=lambda r: (r["at"], r["id"]))
    return {"runs": runs, "run_deaths": _run_deaths(rd, runs, roster)}


def _the_rest(rd, names: list) -> dict:
    kinds = holes(len(EVENT_KINDS))
    events = _named(
        rd,
        EVENTS_SQL,
        names,
        (*EVENT_KINDS, EVENT_DAYS, MAX_ROWS),
        "overseer_event",
        kinds=kinds,
    )
    sales = _named(
        rd,
        SALES_SQL,
        names,
        (DEATH_DAYS, SOLD_CLOTH_LIKE, MAX_ROWS),
        "overseer_command",
    )
    return {
        "levels": _named(rd, LEVELS_SQL, names, (RUN_DAYS, MAX_ROWS), "overseer_level"),
        "events": events,
        "asks": _named(rd, ASKS_SQL, names, (ASK_DAYS, MAX_ROWS), "overseer_guild_ask"),
        "sales": [x for x in map(sale_row, sales) if x],
    }


def fetch(ctx, names: list | None, guilds: list) -> dict:
    """The roster, the database's clock, and every row build() reads, for
    `names` (None: every member of `guilds`) and the runs of `guilds`."""
    rd = ctx.read
    roster_ = _roster(ctx)
    now = rd.must(NOW_SQL)
    if names is None:
        names = sorted(n for n, g in roster_.items() if g in guilds)
    r = {"maps": ctx.server.achievements.MAP_NAMES}
    r.update(_runs(rd, guilds, roster_))
    if names:
        r.update(_deaths(rd, names))
        r.update(_the_rest(rd, names))
    now_at = int(now[0]["now_at"]) if now else 0
    return {"rows": r, "roster": roster_, "now_at": now_at}


# ----------------------------------------------------------------- payload --

WINDOWS = {
    "deaths": DEATH_DAYS,
    "runs": RUN_DAYS,
    "levels": RUN_DAYS,
    "events": EVENT_DAYS,
    "asks": ASK_DAYS,
    "sales": DEATH_DAYS,
}
BASIS = (
    "Flavor only: nothing is granted in the game. Each achievement is read "
    "after the fact from rows the realm already keeps, once per member (a "
    "first clear or first boss, once per guild and dungeon), at the earliest "
    "row that earns it. Deaths, sales and hearths are read for the last %d "
    "days, loot, quests and crafts for %d, class quest asks for %d, and runs "
    "and levels for %d; an achievement whose row ages out drops off."
    % (DEATH_DAYS, EVENT_DAYS, ASK_DAYS, RUN_DAYS)
)


def tiers(found: list) -> dict:
    return {t: sum(1 for a in found if a["tier"] == t) for t in TIERS}


def member_view(name: str, f: dict) -> dict:
    found = build(f["rows"], f["roster"], f["now_at"])
    mine = [a for a in found if a["member"] == name or name in a["who"]]
    return {
        "name": name,
        "guild": f["roster"].get(name, ""),
        "earned": mine,
        "count": len({a["rule"] for a in mine}),
        "of": len(RULES),
        "tiers": tiers(mine),
        "days": WINDOWS,
        "checked_at": f["now_at"] or None,
        "basis": BASIS,
    }


def feed_view(guilds: list, f: dict) -> dict:
    found = [
        a for a in build(f["rows"], f["roster"], f["now_at"]) if a["guild"] in guilds
    ]
    return {
        "guilds": guilds,
        "items": found[:FEED_LIMIT],
        "count": len(found),
        "days": WINDOWS,
        "checked_at": f["now_at"] or None,
        "basis": BASIS,
    }


# ----------------------------------------------------------------- handler --

_CACHE = readcache.ReadCache(CACHE_SECONDS)


def clear_cache() -> None:
    _CACHE.clear()


def _for_member(ctx, name: str) -> dict:
    def make():
        guild = _roster(ctx).get(name, "")
        return member_view(name, fetch(ctx, [name], [guild] if guild else []))

    return _CACHE.get("name:" + name, make)


def _for_guilds(ctx, guilds: list) -> dict:
    key = "guilds:" + ",".join(guilds)
    return _CACHE.get(key, lambda: feed_view(guilds, fetch(ctx, None, guilds)))


def achievements(query: dict, ctx) -> tuple[int, dict]:
    name = wanted_name(query)
    if name or "name" in query:
        if not name_shaped(name) or not may_answer(ctx, name):
            return 404, dict(NOT_A_MEMBER)
        return 200, _for_member(ctx, name)
    asked = (query.get("guild") or [""])[0].strip()
    if asked:
        guild = _scope.guild(ctx, asked)
        if guild is None:
            return 404, _scope.no_such_guild(ctx)
        return 200, _for_guilds(ctx, [guild])
    return 200, _for_guilds(ctx, sorted(_scope.guilds(ctx).values()))


ROUTES = {"/api/v2/achievements": achievements}
