"""Pure builder for the Chronicle: what the family has DONE.

The view was called Achievements until infra#2597 redesigned it; the tickets
below and several comments in this file still use the old name, and they are
about the same view. What the redesign changed here is that the WORDS on a
card are built in this module now - the kind, the hue it is drawn in, the body
line and the character's own line about it - rather than being assembled in
JavaScript where no test in this suite could reach them.

Every other tab answers a present-tense question - where are they, are they
all right, what are they wearing, what are they working on. This one answers
"what happened", as an achievement screen would: a dungeon run with its loot
and its deaths, a quest turned in with what it paid, a level reached, and the
handful of firsts that only ever happen once.

NOTHING HERE IS RECORDED AS AN ACHIEVEMENT. There is no table of them. Every
card is assembled after the fact from three tables the module already keeps:

  overseer_dungeon_run   one row per instance visit (leader, map, times)
  overseer_event         item_equip / quest_complete / quest_reward /
                         level_up, de-duplicated per hour, each stamped with
                         the map it happened on
  overseer_death         one row per death, with map and killer

and loot is bound to a run by the only two facts they share: the run's map
and the run's time window. An item equipped on map 36 while a Deadmines run
was active is that run's loot. That rule is why this module exists as a pure
one - it is a judgement, and the judgement is what the tests reach.

BOSS KILLS ARE NOT RECORDED YET. The module emits no event when a boss dies,
so a run's bosses are INFERRED from its loot: Smite's Mighty Hammer means Mr.
Smite fell. That is honest as far as it goes and no further - a boss whose
drop nobody equipped is "not confirmed", never "not killed" - and every card
says which it is. mod-overseer#159 asks the module for a `boss_kill` event
kind (subject_id = creature entry, subject_name = boss name); it slots
straight in, because infer_bosses reads those rows first and falls back to
loot only for bosses no event names.

Same seam rule as family, armory and questlog (infra#2597): the HTTP adapter
fetches rows and does nothing else. Which run an item belongs to, which boss
a drop proves, what counts as a first, and what order the timeline runs in
are all decided here.

THE mod-overseer TICKETS BELOW ARE IN THE MODULE'S OWN TRACKER, and are
spelled that way on purpose (infra#2597, just above, is this repository's).
The run coordinator that writes overseer_dungeon_run is C++ and lives over
there, so the epic that owns "what a run IS" does too. A bare #88 here is a
closed issue about an SNMP collector with nothing to do with any of this,
which is exactly the kind of confident wrong citation that stops the next
reader from going to look.

Tickets: mod-overseer#88 (the epic), mod-overseer#152, mod-overseer#159.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from armory import QUALITY_NAMES, UNKNOWN_QUALITY

# --- the vocabulary the module writes, and this reads --------------------
#
# Spelled once. overseer_event.kind is a free varchar; these are the values
# mod_overseer.cpp actually writes today, plus the two this page is designed
# to grow into the moment the module records them.
ITEM_EQUIP = "item_equip"
QUEST_COMPLETE = "quest_complete"   # objectives done; the log says "complete"
QUEST_REWARD = "quest_reward"       # turned in; the reward was taken
LEVEL_UP = "level_up"
BOSS_KILL = "boss_kill"             # not emitted yet - see infer_bosses
FLIGHT = "flight"                   # not emitted yet - see first_flight

# Card kinds, in the order they win a tie on the same second. A run ends
# with a turn-in and a level-up in the same instant more often than seems
# likely; the run is the bigger fact, so it is read first.
RUN = "run"
FIRST = "first"
QUEST = "quest"
LEVEL = "level"
_KIND_ORDER = {RUN: 0, FIRST: 1, QUEST: 2, LEVEL: 3}

# A quest's chosen reward is not in the event (detail is empty), so it is
# read from the item_equip the same character makes straight afterwards -
# bots equip an upgrade the moment they hold it. Five minutes is generous;
# the observed gap is seconds.
CHOICE_WINDOW = timedelta(minutes=5)
# A level gained by a turn-in lands in the same second as the reward event or
# the one after; two minutes leaves room for a slow save.
LEVEL_WINDOW = timedelta(minutes=2)

# Levels that get a card of their own on the timeline. Every level_up is
# still in the payload - a run lists the ones inside it - but sixty small
# cards would bury the ten that matter, and the ten that matter are the
# round ones.
MILESTONE_LEVELS = frozenset({10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 70, 80})
# The firsts the page names by number: the first of the family to reach
# each of these gets a "First to N" card, in addition to the level card.
FIRST_LEVELS = (10, 20, 25, 30, 40, 50, 60, 70, 80)

# The instance maps this realm's family can reach, by map id, in the order
# their bosses are met. acore_world has no map table (that is DBC, client
# data) and no "which creatures are this dungeon's bosses" table either, so
# the boss LIST is frozen here; what each boss DROPS is read from
# creature_loot_template at fetch time and passed in, so the inference
# tracks the world database rather than anybody's memory of it. The last
# boss in a list is the one whose fall means the dungeon was cleared.
#
# Only Deadmines is filled in because only Deadmines has been run. Adding a
# dungeon is one entry here; the page needs nothing else.
DUNGEONS = {
    36: {
        "name": "The Deadmines",
        "bosses": [
            (644, "Rhahk'Zor"),
            (642, "Sneed's Shredder"),
            (643, "Sneed"),
            (1763, "Gilnid"),
            (646, "Mr. Smite"),
            (645, "Cookie"),
            (647, "Captain Greenskin"),
            (639, "Edwin VanCleef"),
        ],
    },
    43: {"name": "Wailing Caverns", "bosses": []},
    389: {"name": "Ragefire Chasm", "bosses": []},
    33: {"name": "Shadowfang Keep", "bosses": []},
    34: {"name": "The Stockade", "bosses": []},
    48: {"name": "Blackfathom Deeps", "bosses": []},
    90: {"name": "Gnomeregan", "bosses": []},
    47: {"name": "Razorfen Kraul", "bosses": []},
    189: {"name": "Scarlet Monastery", "bosses": []},
    129: {"name": "Razorfen Downs", "bosses": []},
    70: {"name": "Uldaman", "bosses": []},
    209: {"name": "Zul'Farrak", "bosses": []},
    349: {"name": "Maraudon", "bosses": []},
    109: {"name": "Sunken Temple", "bosses": []},
    230: {"name": "Blackrock Depths", "bosses": []},
    229: {"name": "Blackrock Spire", "bosses": []},
    289: {"name": "Scholomance", "bosses": []},
    329: {"name": "Stratholme", "bosses": []},
    429: {"name": "Dire Maul", "bosses": []},
}

# How the run was confirmed. The page draws these differently and says which.
BY_EVENT = "event"
BY_LOOT = "loot"

# Rare and up. A green can drop from any trash mob in the instance, so only
# a rare or better drop is evidence of WHICH creature died.
SIGNATURE_QUALITY = 3

# The timeline is capped; the firsts are not. A first is computed over every
# row handed in, so it stays a first however long the realm runs, and the
# timeline shows the newest of everything else.
MAX_CARDS = 200


def dungeon_name(map_id: int) -> str:
    entry = DUNGEONS.get(map_id)
    return entry["name"] if entry else "map %d" % map_id


def boss_creatures(map_id: int) -> list[int]:
    """Creature entries whose loot the adapter should fetch for this map."""
    entry = DUNGEONS.get(map_id)
    return [creature for creature, _ in entry["bosses"]] if entry else []


# --- time --------------------------------------------------------------------

def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.strftime("%Y-%m-%dT%H:%M:%S")


def run_window(run: dict, now: datetime) -> tuple[datetime, datetime]:
    """When a run's loot may have dropped: started_at to ended_at, or to now.

    A run still marked active has no ended_at, and its loot is still landing
    - so its window runs to the moment of the read rather than to nothing.
    """
    end = run.get("ended_at") or now
    return run["started_at"], end


def in_run(run: dict, when: datetime, map_id: int, now: datetime) -> bool:
    """Whether something that happened at `when` on `map_id` belongs to a run.

    BOTH facts, always. Time alone would claim a quest turned in outside the
    instance while the run row was still open - overseer_dungeon_run is closed
    by a cold heartbeat, so a row can outlive the visit by two minutes and
    open before it by hours (id 18392 opened at 08:47 for a clear that ran
    15:16 to 16:01). Map alone would claim last week's Deadmines loot for
    today's run.
    """
    if map_id != run["map_id"]:
        return False
    start, end = run_window(run, now)
    return start <= when <= end


def _duration(start: datetime, end: datetime) -> str:
    seconds = max(0, int((end - start).total_seconds()))
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours:
        return "%dh %02dm" % (hours, minutes)
    return "%dm" % minutes


# --- items ----------------------------------------------------------------------

def item_payload(entry: int, items: dict, icons: dict) -> dict:
    """One item, as the page draws it: name in its quality colour, an icon
    when the frozen book knows one, and the wowhead link for the tooltip.

    `items` is entry -> item_template row (name, Quality, ItemLevel,
    displayid); `icons` is displayid -> icon name from the frozen ItemBook.
    An entry the world database no longer knows (a custom item, a removed
    one) still renders, by entry, rather than vanishing from the loot list.
    """
    row = items.get(entry) or {}
    quality = row.get("Quality")
    displayid = row.get("displayid")
    return {
        "entry": entry,
        "name": row.get("name") or ("item %d" % entry),
        "quality": quality,
        "quality_name": QUALITY_NAMES.get(quality, UNKNOWN_QUALITY)
        if quality is not None else UNKNOWN_QUALITY,
        "ilvl": row.get("ItemLevel"),
        "icon": icons.get(displayid) if displayid is not None else None,
        "wowhead": "https://www.wowhead.com/wotlk/item=%d" % entry,
    }


def _loot_line(event: dict, items: dict, icons: dict) -> dict:
    line = item_payload(int(event["subject_id"]), items, icons)
    line["who"] = event["character_name"]
    line["at"] = _iso(event["first_seen"])
    line["slot"] = event.get("detail") or ""
    return line


# --- bosses -------------------------------------------------------------------

def infer_bosses(map_id: int, loot_entries: set[int], boss_drops: dict,
                 kill_events: list[dict]) -> dict:
    """Which of a dungeon's bosses fell, and how anyone knows.

    `boss_drops` is creature entry -> set of item entries that creature drops
    (rare and up), from creature_loot_template. `kill_events` are boss_kill
    rows for this run, if the module ever writes them; they win over loot.

    Returns {"known": [...], "unconfirmed": [...], "final": bool, "how": str}
    where `how` is BY_EVENT when at least one kill event was seen, else
    BY_LOOT - so the page can say "inferred from loot" rather than let a list
    of four names read as a list of four kills.
    """
    entry = DUNGEONS.get(map_id) or {"bosses": []}
    killed = {int(e["subject_id"]) for e in kill_events}
    known, unconfirmed = [], []
    for creature, name in entry["bosses"]:
        if creature in killed:
            known.append({"entry": creature, "name": name, "how": BY_EVENT})
        elif loot_entries & set(boss_drops.get(creature, ())):
            known.append({"entry": creature, "name": name, "how": BY_LOOT})
        else:
            unconfirmed.append({"entry": creature, "name": name})
    bosses = entry["bosses"]
    final = bool(bosses) and any(b["entry"] == bosses[-1][0] for b in known)
    return {
        "known": known,
        "unconfirmed": unconfirmed,
        "final": final,
        "how": BY_EVENT if kill_events else BY_LOOT,
        "total": len(bosses),
    }


# --- runs -------------------------------------------------------------------------

def _run_loot(inside: list[dict], items: dict, icons: dict) -> list[dict]:
    loot = [_loot_line(e, items, icons) for e in inside if e["kind"] == ITEM_EQUIP]
    loot.sort(key=lambda line: line["at"])
    return loot


def _run_levels(inside: list[dict]) -> list[dict]:
    return [{"who": e["character_name"], "level": int(e["level"]),
             "at": _iso(e["first_seen"])}
            for e in inside if e["kind"] == LEVEL_UP]


def _run_quests(inside: list[dict]) -> list[dict]:
    return [{"who": e["character_name"], "quest": int(e["subject_id"]),
             "title": e["subject_name"], "turned_in": e["kind"] == QUEST_REWARD,
             "at": _iso(e["first_seen"])}
            for e in inside if e["kind"] in (QUEST_COMPLETE, QUEST_REWARD)]


def _run_deaths(died: list[dict]) -> list[dict]:
    return [{"who": d["character_name"], "killer": d.get("killer_name") or "",
             "at": _iso(d["created_at"])} for d in died]


def _who_was_there(run: dict, inside: list[dict], died: list[dict]) -> set:
    """Anyone the tables place inside the instance during the window, plus the
    leader the run row names.

    A member who neither looted nor died nor levelled inside is invisible to
    this, which is the honest answer and why the card says "seen", not
    "present".
    """
    present = {run["leader_name"]}
    present.update(e["character_name"] for e in inside)
    present.update(d["character_name"] for d in died)
    return present


def _activity_span(inside: list[dict], died: list[dict]) -> tuple:
    """When anything actually happened, as against when the row was open.

    The run row's span is when the module THOUGHT they were inside. For 18392
    the two are seven hours and twenty minutes apart, and this one is what a
    person means by "how long did it take".
    """
    moments = [e["first_seen"] for e in inside] + [d["created_at"] for d in died]
    if not moments:
        return None, None
    return min(moments), max(moments)


def _all_together(roster: list[str], present: set) -> bool:
    """Whether the WHOLE family was inside, which is a first worth a card.

    An empty roster is not "everybody", which a bare subset test would call
    true and then award a first to nobody.
    """
    return bool(roster) and set(roster) <= present


def _run_active_duration(active_from, active_to) -> str | None:
    return _duration(active_from, active_to) if active_from else None


def _run_members(roster: list[str], present: set) -> list[str]:
    """The roster in its own order first, then anyone else who was inside.

    Roster order is seniority (bonds.speaking_order), the same order the
    Family tab draws; sorting the whole set by name instead would put a
    passing stranger between two members of the family.
    """
    return [n for n in roster if n in present] + sorted(present - set(roster))


def _gained(loot: list, bosses: dict, levels: list, quests: list) -> bool:
    """Whether the visit produced anything at all.

    A visit that gained nothing - a death at the door, a look inside - is an
    ATTEMPT, and the card says so. Calling a four-minute wipe a "run" would
    put it on the same footing as the forty-six minutes that took four
    bosses, and the first of these is not the first dungeon run.
    """
    return bool(loot or bosses["known"] or levels or quests)


def _run_state(run: dict) -> str:
    """What the row says it is, and what it must be when the row says nothing.

    A run with an ended_at is over whatever the state column holds; the
    column is the authority only while the run is open.
    """
    return run.get("state") or ("ended" if run.get("ended_at") else "active")


def _card_moment(run: dict, active_to: datetime | None, start: datetime) -> datetime:
    """Where the run sits on the timeline.

    Its END, not its start: a card that appears when the party walked in
    would sort above everything that happened during the run it describes.
    Falls back to the last thing that happened, then to the start, so a run
    still open is still placed.
    """
    return run.get("ended_at") or active_to or start


def assemble_run(run: dict, events: list[dict], deaths: list[dict], items: dict,
                 icons: dict, boss_drops: dict, roster: list[str],
                 now: datetime) -> dict:
    """One dungeon run, with everything that happened inside it.

    `events` and `deaths` are the WHOLE tables (or the fetched horizon); the
    binding to this run is done here, by in_run, so the rule lives in one
    place and the tests can hand in a stray row and watch it stay out. What
    each section of the card is made of lives in the helpers above, so this
    reads as the shape of a card rather than as five list comprehensions.
    """
    start, end = run_window(run, now)
    inside = [e for e in events
              if in_run(run, e["first_seen"], int(e["map"]), now)]
    died = [d for d in deaths
            if in_run(run, d["created_at"], int(d["map"]), now)]
    map_id = int(run["map_id"])
    loot = _run_loot(inside, items, icons)
    levels = _run_levels(inside)
    quests = _run_quests(inside)
    bosses = infer_bosses(map_id, {line["entry"] for line in loot}, boss_drops,
                          [e for e in inside if e["kind"] == BOSS_KILL])
    present = _who_was_there(run, inside, died)
    active_from, active_to = _activity_span(inside, died)
    gained = _gained(loot, bosses, levels, quests)
    name = dungeon_name(map_id)
    return {
        "kind": RUN,
        "id": int(run["id"]),
        "at": _iso(_card_moment(run, active_to, start)),
        "title": "%s: %s" % ("Dungeon run" if gained else "Dungeon attempt", name),
        "gained": gained,
        "map_id": map_id,
        "dungeon": name,
        "leader": run["leader_name"],
        "state": _run_state(run),
        "started_at": _iso(start),
        "ended_at": _iso(run.get("ended_at")),
        "duration": _duration(start, end),
        "active_from": _iso(active_from),
        "active_to": _iso(active_to),
        "active_duration": _run_active_duration(active_from, active_to),
        "ended_reason": run.get("ended_reason") or "",
        "members": _run_members(roster, present),
        "all_together": _all_together(roster, present),
        "bosses": bosses,
        "cleared": bosses["final"],
        "deaths": _run_deaths(died),
        "loot": loot,
        "level_ups": levels,
        "quests": quests,
    }


# --- quests --------------------------------------------------------------------------

def _after(events: list[dict], who: str, kind: str, since: datetime,
           window: timedelta) -> list[dict]:
    return [e for e in events
            if e["character_name"] == who and e["kind"] == kind
            and since <= e["first_seen"] <= since + window]


def assemble_quest(event: dict, events: list[dict], quest_rewards: dict,
                   items: dict, icons: dict) -> dict:
    """One turn-in: who, what it paid, and whether it was the level.

    `quest_rewards` is quest id -> {"items": [(entry, count)], "choices":
    [entry]} from quest_template. The fixed rewards are certain; the CHOSEN
    reward is not recorded anywhere, so it is the first item_equip by the
    same character within CHOICE_WINDOW whose entry is one of the choices -
    and when no such equip exists the card says the choice is unknown rather
    than guessing at one.
    """
    who = event["character_name"]
    qid = int(event["subject_id"])
    template = quest_rewards.get(qid) or {"items": [], "choices": []}
    at = event["first_seen"]
    rewards = []
    for entry, count in template["items"]:
        line = item_payload(int(entry), items, icons)
        line["count"] = int(count or 1)
        line["chosen"] = False
        rewards.append(line)
    chosen = None
    if template["choices"]:
        choices = {int(c) for c in template["choices"]}
        for equip in sorted(_after(events, who, ITEM_EQUIP, at, CHOICE_WINDOW),
                            key=lambda e: e["first_seen"]):
            if int(equip["subject_id"]) in choices:
                chosen = item_payload(int(equip["subject_id"]), items, icons)
                chosen["count"] = 1
                chosen["chosen"] = True
                rewards.append(chosen)
                break
    gained = _after(events, who, LEVEL_UP, at, LEVEL_WINDOW)
    turned_in = event["kind"] == QUEST_REWARD
    return {
        "kind": QUEST,
        "id": "%s:%d:%s" % (who, qid, _iso(at)),
        "at": _iso(at),
        "title": "Quest: %s" % (event.get("subject_name") or ("quest %d" % qid)),
        "quest": qid,
        "who": who,
        "level": int(event.get("level") or 0),
        "turned_in": turned_in,
        "rewards": rewards,
        "choice_unknown": bool(template["choices"]) and chosen is None,
        "level_gained": max((int(e["level"]) for e in gained), default=None),
        "map_id": int(event.get("map") or 0),
    }


def quest_cards(events: list[dict], quest_rewards: dict, items: dict,
                icons: dict) -> list[dict]:
    """A card per turn-in, and one per completion that was never turned in.

    quest_complete fires when the objectives are done and quest_reward when
    the reward is taken; the second is the achievement, so a quest with both
    gets one card, from the reward. A completion with no reward event for the
    same character and quest is still a thing that happened - the card just
    says "objectives done" instead of "turned in".
    """
    rewarded = {(e["character_name"], int(e["subject_id"]))
                for e in events if e["kind"] == QUEST_REWARD}
    cards = []
    for e in events:
        if e["kind"] == QUEST_REWARD:
            cards.append(assemble_quest(e, events, quest_rewards, items, icons))
        elif e["kind"] == QUEST_COMPLETE:
            if (e["character_name"], int(e["subject_id"])) not in rewarded:
                cards.append(assemble_quest(e, events, quest_rewards, items, icons))
    return cards


# --- levels ---------------------------------------------------------------------------

def level_cards(events: list[dict]) -> list[dict]:
    cards = []
    for e in events:
        if e["kind"] != LEVEL_UP:
            continue
        level = int(e["level"])
        cards.append({
            "kind": LEVEL,
            "id": "%s:%d" % (e["character_name"], level),
            "at": _iso(e["first_seen"]),
            "title": "Level %d!" % level,
            "who": e["character_name"],
            "level": level,
            "milestone": level in MILESTONE_LEVELS,
            "map_id": int(e.get("map") or 0),
        })
    return cards


# --- firsts ---------------------------------------------------------------------------

def _first_card(key: str, title: str, at: str | None, who, detail: str) -> dict:
    return {"kind": FIRST, "id": "first:" + key, "key": key, "at": at,
            "title": title, "who": who, "detail": detail}


def _earliest(rows, key):
    """The earliest row by `key`, or None. THE rule every first is built on.

    min() rather than sorted()[0] because the answer is one row, and because
    naming it here is what stops one of the firsts below quietly becoming
    "the last one" during an edit.
    """
    rows = [r for r in rows if r[key] is not None]
    return min(rows, key=lambda r: r[key]) if rows else None


def _run_firsts(runs: list[dict], roster: list[str]) -> list[dict]:
    """The three firsts that are facts about a RUN rather than about a row."""
    firsts = []
    first_run = _earliest([r for r in runs if r["gained"]], "active_from")
    if first_run:
        firsts.append(_first_card(
            "dungeon_run", "First dungeon run", first_run["active_from"],
            first_run["members"],
            "%s, led by %s" % (first_run["dungeon"], first_run["leader"])))
    cleared = _earliest([r for r in runs if r["cleared"]], "at")
    if cleared:
        firsts.append(_first_card(
            "dungeon_clear", "First dungeon clear", cleared["at"],
            cleared["members"], "%s: the final boss fell" % cleared["dungeon"]))
    together = _earliest([r for r in runs if r["all_together"]], "at")
    if together:
        firsts.append(_first_card(
            "all_together", "All %d in one instance" % len(roster),
            together["at"], together["members"],
            "%s, the whole family inside at once" % together["dungeon"]))
    return firsts


def _quality_firsts(events: list[dict], items: dict) -> list[dict]:
    """First rare, first epic: the earliest equip of that quality OR BETTER.

    Or better, because an epic equipped before any rare still means the day
    they first wore something rare has passed - a first that could be missed
    by an exact-quality test is a first that never appears at all.
    """
    firsts = []
    equips = [e for e in events if e["kind"] == ITEM_EQUIP]
    for quality, key, title in ((3, "rare_item", "First rare item"),
                                (4, "epic_item", "First epic item")):
        good = [e for e in equips
                if (items.get(int(e["subject_id"])) or {}).get("Quality", -1) >= quality]
        hit = _earliest(good, "first_seen")
        if hit:
            firsts.append(_first_card(
                key, title, _iso(hit["first_seen"]), hit["character_name"],
                items[int(hit["subject_id"])]["name"]))
    return firsts


def _level_firsts(events: list[dict]) -> list[dict]:
    """First of the family to reach each round level."""
    ups = sorted((e for e in events if e["kind"] == LEVEL_UP),
                 key=lambda e: e["first_seen"])
    firsts = []
    for level in FIRST_LEVELS:
        hit = next((e for e in ups if int(e["level"]) >= level), None)
        if hit:
            firsts.append(_first_card(
                "level_%d" % level, "First to level %d" % level,
                _iso(hit["first_seen"]), hit["character_name"],
                "%s reached %d" % (hit["character_name"], int(hit["level"]))))
    return firsts


def _flight_first(events: list[dict]) -> list[dict]:
    """Waits for an event kind the module does not write yet, and says nothing
    until it does rather than inventing one from a zone change."""
    hit = _earliest([e for e in events if e["kind"] == FLIGHT], "first_seen")
    if not hit:
        return []
    return [_first_card("flight", "First flight", _iso(hit["first_seen"]),
                        hit["character_name"],
                        hit.get("subject_name") or hit.get("detail") or "")]


def first_cards(runs: list[dict], events: list[dict], items: dict,
                roster: list[str]) -> list[dict]:
    """The things that only happen once, each found from the whole history.

    `runs` are assembled run cards (assemble_run output), oldest or newest,
    the order does not matter here. Every first is the EARLIEST qualifying
    row, so the list is stable however many rows arrive after it - which is
    why each group above goes through _earliest rather than through its own
    sort.
    """
    return (_run_firsts(runs, roster)
            + _quality_firsts(events, items)
            + _level_firsts(events)
            + _flight_first(events))


# --- reading the world tables --------------------------------------------------
#
# Two row-to-dict helpers, here rather than in the adapter, because which
# column carries a boss's drop and how many reward slots a quest has are
# facts about acore_world's spellings - decisions, and testable ones.

REWARD_SLOTS = 4
CHOICE_SLOTS = 6


def quest_rewards_from_rows(rows: list[dict]) -> dict:
    """quest_template rows -> quest id -> {"items": [(entry, count)], "choices": [entry]}."""
    out = {}
    for row in rows:
        fixed = []
        for i in range(1, REWARD_SLOTS + 1):
            entry = int(row.get("RewardItem%d" % i) or 0)
            if entry:
                fixed.append((entry, int(row.get("RewardAmount%d" % i) or 1)))
        choices = [int(row.get("RewardChoiceItemID%d" % i) or 0)
                   for i in range(1, CHOICE_SLOTS + 1)]
        out[int(row["ID"])] = {"items": fixed, "choices": [c for c in choices if c]}
    return out


def boss_drops_from_rows(rows: list[dict]) -> dict:
    """(creature entry, item entry) rows -> creature entry -> set of item entries."""
    out: dict[int, set[int]] = {}
    for row in rows:
        out.setdefault(int(row["creature"]), set()).add(int(row["item"]))
    return out


def wanted_entries(event_rows: list[dict], quest_rewards: dict, boss_drops: dict) -> list[int]:
    """Every item entry the cards may name, so the adapter fetches them in one query."""
    entries = {int(e["subject_id"]) for e in event_rows if e["kind"] == ITEM_EQUIP}
    for reward in quest_rewards.values():
        entries.update(entry for entry, _ in reward["items"])
        entries.update(reward["choices"])
    for drops in boss_drops.values():
        entries.update(drops)
    return sorted(entries)


def wanted_quests(event_rows: list[dict]) -> list[int]:
    return sorted({int(e["subject_id"]) for e in event_rows
                   if e["kind"] in (QUEST_COMPLETE, QUEST_REWARD)})


def wanted_bosses(run_rows: list[dict]) -> list[int]:
    creatures: set[int] = set()
    for run in run_rows:
        creatures.update(boss_creatures(int(run["map_id"])))
    return sorted(creatures)


# --- the Chronicle's card furniture (infra#2597) -----------------------------------------
#
# A card is drawn as a date, a KIND in a hue, a title, a muted body, and the
# line the character gets to say about it. All five are judgement and all five
# live here. They used to be assembled in the page - "led by X, 21m in the
# instance" was three JavaScript ternaries - which meant the sentence a reader
# saw was written somewhere no test in this suite could reach.
#
# THE HUE IS A TOKEN NAME, NEVER A COLOUR. index.html owns what --cyan looks
# like and it owns it twice, once per theme; a hex chosen here would be mixed
# for one ground and wrong on the other.

# The word each kind is announced by. Status words, in the mono face.
KIND_WORDS = {RUN: "DUNGEON RUN", QUEST: "QUEST", LEVEL: "LEVEL",
              FIRST: "FIRST"}
# A run nobody got anything out of is not a run, and calling it one flatters
# the family. It gets its own word and its own quiet hue.
ATTEMPT_WORD = "ATTEMPT"
ATTEMPT_HUE = "muted"
KIND_HUES = {RUN: "cyan", QUEST: "green", LEVEL: "amber", FIRST: "vermilion"}


def card_word(card: dict) -> str:
    """The kind, as the word the page prints."""
    if card["kind"] == RUN and not card.get("gained"):
        return ATTEMPT_WORD
    return KIND_WORDS.get(card["kind"], card["kind"].upper())


def card_hue(card: dict) -> str:
    """The token name the kind is drawn in."""
    if card["kind"] == RUN and not card.get("gained"):
        return ATTEMPT_HUE
    return KIND_HUES.get(card["kind"], "muted")


def _run_body(card: dict) -> str:
    """How long they were in there, and who took them.

    The run ROW and the time anything actually happened are two different
    spans, and the difference matters: a row left open by a crash says three
    hours while the family was inside for twenty minutes. Both are reported
    when they disagree, and only the honest one when they do not.
    """
    fight = card.get("active_duration") or card["duration"]
    if card.get("active_duration") and card["duration"] != card["active_duration"]:
        fight = "%s in the instance (the run row stayed open %s)" % (
            card["active_duration"], card["duration"])
    elif card.get("active_duration"):
        fight = "%s in the instance" % card["active_duration"]
    body = "led by %s, %s" % (card["leader"], fight)
    if card.get("state") == "active":
        body += ", still inside"
    return body


def card_body(card: dict) -> str:
    """The muted line under the title: who, and how it went."""
    kind = card["kind"]
    if kind == RUN:
        return _run_body(card)
    if kind == QUEST:
        return "%s %s at level %d" % (
            card["who"],
            "turned it in" if card["turned_in"] else "finished the objectives",
            card["level"])
    if kind == LEVEL:
        return str(card["who"])
    if kind == FIRST:
        who = card["who"]
        who = ", ".join(who) if isinstance(who, list) else str(who)
        return who + (": " + card["detail"] if card.get("detail") else "")
    return ""


def _first_name(who) -> str:
    if isinstance(who, list):
        return str(who[0]) if who else ""
    return str(who or "")


def card_line(card: dict) -> dict | None:
    """The line the character gets to say about it, or None.

    SHORT, PRESENT TENSE, AND TIED TO A FACT ON THE CARD. Everyone in this
    family talks the same way - bonds.py says so, and says why - so these are
    written in that register rather than in five. Every one of them names
    something the row actually contains: the dungeon, the level, the deed.
    Nothing here invents an event; it only says the one on the card out loud.

    A card with nobody to attribute a line to gets None, and the page draws
    nothing. An unattributed quote is the worst of both: it reads as a voice
    and belongs to no one.
    """
    kind = card["kind"]
    if kind == RUN:
        where = card["dungeon"]
        if card.get("gained"):
            if card.get("cleared"):
                return {"who": card["leader"],
                        "text": "We finished %s." % where}
            return {"who": card["leader"],
                    "text": "We got into %s, and we got out again." % where}
        if card.get("deaths"):
            return {"who": card["deaths"][0]["who"],
                    "text": "%s put me down." % where}
        return {"who": card["leader"],
                "text": "We walked into %s and nothing came of it." % where}
    if kind == QUEST:
        if card["turned_in"]:
            return {"who": card["who"],
                    "text": "I gave it back. That is one less thing."}
        return {"who": card["who"],
                "text": "The work is done. The walking back is not."}
    if kind == LEVEL:
        return {"who": card["who"], "text": "%d now." % card["level"]}
    if kind == FIRST:
        who = _first_name(card["who"])
        if not who:
            return None
        return {"who": who, "text": "Nobody in the family had done that before."}
    return None


def dress(card: dict) -> dict:
    """One card, with the four things the page is not allowed to decide."""
    card["word"] = card_word(card)
    card["hue"] = card_hue(card)
    card["body"] = card_body(card)
    card["line"] = card_line(card)
    return card


def strip(visits: int, runs: int, attempts: int, firsts: int,
          boss_kills_recorded: bool) -> list[dict]:
    """The stat strip over the timeline: five counted things, in mono.

    The last tile is not a count and is the most useful one on the strip. Boss
    kills are INFERRED from loot somebody equipped, because the module does not
    write boss_kill events yet, and a strip that quietly showed a number would
    be presenting a guess as a measurement. The day those events arrive the
    tile turns into the word RECORDED on its own.
    """
    return [
        {"label": "RUNS", "value": str(runs)},
        {"label": "ATTEMPTS", "value": str(attempts)},
        {"label": "VISITS", "value": str(visits)},
        {"label": "FIRSTS", "value": str(firsts)},
        {"label": "BOSS KILLS",
         "value": "RECORDED" if boss_kills_recorded else "INFERRED"},
    ]


def provenance(boss_kills_recorded: bool) -> str:
    """What the reader has to know to read the strip honestly. Empty when nothing does."""
    if boss_kills_recorded:
        return ""
    return ("Boss kills are not recorded yet. Where this page names a boss it "
            "inferred one from a drop somebody equipped, so a boss it does not "
            "name may well have fallen.")


# --- the timeline -----------------------------------------------------------------------

def sort_key(card: dict) -> tuple:
    """Newest first; on the same second, the bigger kind of fact first."""
    return (card["at"] or "", -_KIND_ORDER.get(card["kind"], 9))


def timeline(cards: list[dict]) -> list[dict]:
    """Newest first, capped, with the undated (never) dropped."""
    dated = [c for c in cards if c["at"]]
    dated.sort(key=sort_key, reverse=True)
    return dated[:MAX_CARDS]


def build_achievements(run_rows: list[dict], event_rows: list[dict],
                       death_rows: list[dict], items: dict, icons: dict,
                       boss_drops: dict, quest_rewards: dict,
                       roster: list[str], now: datetime | None = None) -> dict:
    """Rows in, the Chronicle's JSON out.

    run_rows      overseer_dungeon_run rows
    event_rows    overseer_event rows, any kind
    death_rows    overseer_death rows
    items         item entry -> item_template row (name, Quality, ItemLevel, displayid)
    icons         displayid -> icon name (armory.ItemBook.icons)
    boss_drops    creature entry -> iterable of item entries (rare and up)
    quest_rewards quest id -> {"items": [(entry, count)], "choices": [entry]}
    roster        the family, from family.roster()
    """
    now = now or datetime.now()
    events = [e for e in event_rows if e["kind"] != "death"]
    runs = [assemble_run(r, events, death_rows, items, icons, boss_drops, roster, now)
            for r in run_rows]
    # A visit in which nothing happened at all - opened by a heartbeat at the
    # door and closed by the next cold one - is not even an attempt. It is
    # still in the payload's count so the page can say how many there were.
    visits = len(runs)
    runs = [r for r in runs if r["active_from"]]
    quests = quest_cards(events, quest_rewards, items, icons)
    levels = [c for c in level_cards(events) if c["milestone"]]
    firsts = first_cards(runs, events, items, roster)
    cards = [dress(c) for c in timeline(runs + quests + levels + firsts)]
    recorded = any(e["kind"] == BOSS_KILL for e in events)
    done = sum(1 for r in runs if r["gained"])
    tried = sum(1 for r in runs if not r["gained"])
    return {
        "generated_at": _iso(now),
        "roster": list(roster),
        "visits": visits,
        "runs": done,
        "attempts": tried,
        "firsts": firsts,
        "cards": cards,
        "boss_kills_recorded": recorded,
        # The stat strip and the sentence under it. Counted here rather than
        # composed in the page, for the same reason every card's body is: a
        # number with a word beside it is a claim, and a claim is judgement.
        "strip": strip(visits, done, tried, len(firsts), recorded),
        "provenance": provenance(recorded),
    }
