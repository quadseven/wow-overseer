"""Pure builder for the live dungeon recap, and for what can drop where.

Two questions the operator asked while five characters were inside Wailing
Caverns and he was watching five streams with no idea what was happening:

  "how can the chronicle show like a live recap on the dungeon progress and
   loot doled out?"
  "does the website show potential loot yet that is good for them in all
   dungeons?"

The second was simply no. The first was worse than no, and that is what this
module exists for.

THE EQUIP RECORD IS A RE-SCAN, NOT AN EVENT, AND THE CHRONICLE HAS BEEN
READING IT AS AN EVENT. `overseer_event` rows of kind `item_equip` are not
written when a character equips something. Something re-evaluates gear on a
timer and every worn piece is written again, coalesced into an hourly bucket
with an `occurrences` count. Measured on the live realm on 2026-09-05:

    Ugga / Buzzer Blade     bucket 496835  occurrences 4   map 0
    Ugga / Buzzer Blade     bucket 496836  occurrences 1   map 0
    Ugga / Buzzer Blade     bucket 496837  occurrences 3   map 43

One sword, three rows, eight scans, and the last of them lands inside a
Wailing Caverns run that Ugga carried the sword into. Any filter of the form
"item_equip rows whose time falls inside the run window" therefore sweeps up
every re-scan of everything the party already wore and presents it as the
run's loot. The Chronicle's card for the run in progress read LOOT 9. Two of
the nine were from that run; the other seven were first worn between 31 August
and 3 September, in Redridge, Duskwood and the Deadmines.

So the unit here is the FIRST EVER equip of a pair, not an equip inside a
window:

    first_equips()  (character, item entry) -> the earliest row for that pair

and a run's loot is the pairs whose first row falls inside the run's window
AND on the run's map. That is `run_loot`, it is the only loot rule in this
file, and achievements.py now uses it rather than its own window filter.

WHAT THAT RULE STILL IS NOT. It is "first worn here", it is not "looted here",
and the difference is real: an item looted on Tuesday and first worn in the
instance on Friday passes it. Loot that goes into a bag and stays there writes
no row at all, so it is invisible to this module entirely. Three ways to close
that gap were considered and one was chosen:

  diff character_inventory between polls   REJECTED. The HTTP adapter has no
      loop and no memory; it answers one request and forgets. Holding the
      previous inventory means a new writer, a new table and a new failure
      mode, and it would still miss anything looted and then vendored, traded
      or destroyed between two polls, and still not know what it came off.
  emit a loot event from the C++ module    RIGHT, AND NOT HERE. It is the only
      way to record what was actually looted from what. It is a different
      repository and a worldserver build, so it is filed rather than faked:
      mod-overseer#159 already asks for `boss_kill`, and a `loot_receive` of
      the same shape (subject_id = item entry, detail = creature entry) drops
      into first_equips' place below without changing anything above it.
  show first-worn and say so               CHOSEN. Every loot list built here
      carries LOOT_CAVEAT, the count in a header counts the same rows the list
      shows, and nothing anywhere calls it looted.

PROGRESS DOES NOT COME FROM LOOT. `instance.completedEncounters` is a bitmask
the worldserver itself writes, one bit per encounter, and `character_instance`
binds the family to the instance row. It read 7 for the run in progress while
the loot inference was claiming nine items. That is the core's own account of
how far through they are and it is one join away, so `encounters_down` reads
it and the loot is never asked to guess. The one thing that record does not
carry on this realm is which bit is which encounter: DungeonEncounter.dbc is
not loaded here (`dungeonencounter_dbc` holds zero rows, and so do `map_dbc`
and `areatable_dbc`), so the bit index is taken from the order of the
dungeon's rows in `instance_encounters` and the payload says that is what was
done.

Same seam rule as family, armory, questlog and achievements (infra#2597): the
HTTP adapter fetches rows and serialises what comes back. Which run is live,
who is inside it, which equip is loot, which bit is which boss, whether a drop
beats what somebody wears and how the board is ranked are all decided here,
where the suite can reach them.

Tickets: infra#2597 (the seam), infra#3309 (the delivery budget this is
measured against), mod-overseer#88 (the run coordinator), mod-overseer#159
(the events that would make the loot rule unnecessary).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from armory import EQUIPPED_SLOTS, QUALITY_NAMES, UNKNOWN_QUALITY

ITEM_EQUIP = "item_equip"

# What the page must print beside any loot list built here. Not advisory:
# build_recap attaches it, achievements attaches it, and a test asserts the
# page prints the module's string rather than one of its own.
LOOT_CAVEAT = (
    "first worn here, which is the most the record supports. Nothing records "
    "what was picked up, so an item can be looted here and worn in town, or "
    "looted here and left in a bag, and neither of those shows up at all."
)

# A run whose coordinator has reported no progress for this long is still
# `active` in the table but is not obviously still happening. The recap says
# so rather than counting the minutes up forever.
STALL_AFTER = timedelta(minutes=10)

# A snapshot older than this is not where somebody IS, it is where they were.
# The same sixty seconds the Family tab treats as fresh.
SNAPSHOT_FRESH = timedelta(seconds=60)


# --- the equip record ------------------------------------------------------

def first_equips(event_rows: list[dict]) -> dict[tuple[str, int], dict]:
    """(character, item entry) -> the EARLIEST item_equip row for that pair.

    THE POINT OF THIS MODULE IS THIS FUNCTION, and the header says why: the
    table re-scans worn gear on a timer, so a row inside a run's window proves
    only that the character had the item on. The earliest row for a pair is
    the first time the record ever saw them in it, which is the only thing
    here that can tell new gear from old.

    Rows of other kinds are skipped rather than trusted to have been filtered
    upstream, because the adapter reads this table for four other views.
    """
    firsts: dict[tuple[str, int], dict] = {}
    for row in event_rows:
        if row.get("kind") not in (None, ITEM_EQUIP):
            continue
        key = (row["character_name"], int(row["subject_id"]))
        seen = firsts.get(key)
        if seen is None or row["first_seen"] < seen["first_seen"]:
            firsts[key] = row
    return firsts


# --- which run is open -----------------------------------------------------

def run_state(run: dict) -> str:
    """What the row says it is, and what it must be when the row says nothing.

    A run with an `ended_at` is over whatever the state column holds; the
    column is the authority only while the run is open.

    THIS USED TO BE WRITTEN TWICE AND THE TWO COPIES DISAGREED. The recap
    tested `state == "active"` directly, so a row with a NULL state and no
    `ended_at` fell into "ended" here and into "active" in
    achievements._run_state. The two views are stacked on ONE TAB: the recap
    would print "no dungeon run is open right now" directly above a Chronicle
    card for the same row saying they were still inside. achievements._run_state
    now delegates here, so there is one answer.
    """
    return run.get("state") or ("ended" if run.get("ended_at") else "active")


def is_active(run: dict) -> bool:
    return run_state(run) == "active"


# --- time and place --------------------------------------------------------

def _iso(when: datetime | None) -> str | None:
    return None if when is None else when.strftime("%Y-%m-%dT%H:%M:%S")


def elapsed(start: datetime, end: datetime) -> str:
    seconds = max(0, int((end - start).total_seconds()))
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours:
        return "%dh %02dm" % (hours, minutes)
    return "%dm" % minutes


def place_name(map_id: int, zone_id: int, dungeons: dict, zones: dict) -> str:
    """Where something happened, in the most specific words available.

    THREE SOURCES IN ORDER, AND A REFUSAL AT THE END. A dungeon map has a name
    in the caller's dungeon table, and that is the interesting case and the
    exact one. Otherwise the zone id is looked up in the frozen client zone
    table, which covers the outdoor world. Otherwise the map and zone are
    printed as numbers, because "map 169, zone 40" is a true thing to say and
    "unknown" throws away the ids somebody could go and look up.

    THERE IS NO ZONE NAME TABLE ON THIS REALM TO DO BETTER WITH. `areatable_dbc`
    exists and holds zero rows, as do `map_dbc` and `dungeonencounter_dbc`, so
    reading a zone name out of the world database is not an option that was
    passed over. zones.json is frozen 3.3.5a client data and is the only thing
    on this side that knows Duskwood is 10.
    """
    dungeon = dungeons.get(map_id)
    if dungeon:
        return dungeon
    zone = zones.get(zone_id)
    if zone:
        return zone
    if zone_id:
        return "map %d, zone %d" % (map_id, zone_id)
    return "map %d" % map_id


# --- items -----------------------------------------------------------------

def item_payload(entry: int, row: dict, icons: dict) -> dict:
    """One item as the page draws it.

    The same shape achievements.item_payload emits, so the Chronicle's two
    loot lists share one renderer. Accepts either the aliased column names the
    armory query selects (item_name, quality, item_level) or the raw
    item_template ones, because the loot board reads the world table directly.
    """
    quality = row.get("quality", row.get("Quality"))
    ilvl = row.get("item_level", row.get("ItemLevel"))
    displayid = row.get("displayid")
    name = row.get("item_name") or row.get("name")
    return {
        "entry": entry,
        "name": name or ("item %d" % entry),
        "quality": quality,
        "quality_name": (QUALITY_NAMES.get(quality, UNKNOWN_QUALITY)
                         if quality is not None else UNKNOWN_QUALITY),
        "ilvl": ilvl,
        "icon": icons.get(displayid) if displayid is not None else None,
        "wowhead": "https://www.wowhead.com/wotlk/item=%d" % entry,
    }


# --- a run's loot ----------------------------------------------------------

def run_ended(run: dict, now: datetime) -> datetime:
    """When a run stopped, for a row that is over but has no `ended_at`.

    `last_progress_at` is the last thing the coordinator saw, which is the
    honest end for a row nobody closed. Falling through to `now` for those
    would leave the window open forever: a run that stopped on 1 September
    would still be claiming gear first worn on the 4th.
    """
    if is_active(run):
        return now
    return (run.get("ended_at") or run.get("last_progress_at")
            or run["started_at"])


def run_window(run: dict, now: datetime) -> tuple[datetime, datetime]:
    """When a run's loot may have arrived.

    An OPEN run runs to the read, because its loot is still landing. A run
    that is over closes when it stopped, and `run_ended` is careful about
    what that means for a row with no `ended_at`: reading those to `now`
    reintroduced the exact overstatement this module exists to stop, in the
    summary that stands in for the live recap most of the time.
    """
    return run["started_at"], run_ended(run, now)


def run_loot(run: dict, firsts: dict, items: dict, icons: dict,
             now: datetime, dungeons: dict, zones: dict) -> list[dict]:
    """The gear whose FIRST EVER equip falls inside this run, on its map.

    Both facts, for the reason achievements.in_run gives about time and map,
    and then the first-equip rule on top of both.
    """
    start, end = run_window(run, now)
    out = []
    for (who, entry), row in firsts.items():
        if int(row.get("map") or 0) != int(run["map_id"]):
            continue
        if not (start <= row["first_seen"] <= end):
            continue
        line = item_payload(entry, items.get(entry) or {}, icons)
        line["who"] = who
        line["at"] = _iso(row["first_seen"])
        line["slot"] = row.get("detail") or ""
        line["place"] = place_name(int(row.get("map") or 0),
                                   int(row.get("zone") or 0), dungeons, zones)
        out.append(line)
    out.sort(key=lambda line: (line["at"] or "", line["who"]))
    return out


# --- how far through they are ----------------------------------------------

def encounter_order(encounter_rows: list[dict]) -> list[dict]:
    """A dungeon's encounters in the order the world database lists them.

    `instance_encounters` is the core's own encounter table and it is what the
    completedEncounters bitmask is written against, so the bosses come from it
    rather than from a list somebody typed. It carries no map column, so the
    caller narrows it by which credit creature is SPAWNED on the map: that is
    what produces exactly seven rows for Wailing Caverns, which is exactly how
    many bosses Wailing Caverns has.
    """
    return [{"entry": int(row["entry"]),
             "creature": int(row["creditEntry"]),
             "name": (row.get("name")
                      or ("creature %d" % int(row["creditEntry"])))}
            for row in sorted(encounter_rows, key=lambda r: int(r["entry"]))]


def encounters_down(mask: int | None, encounters: list[dict]) -> dict:
    """Which encounters the worldserver has recorded as beaten.

    THIS IS THE INSTANCE'S PROGRESS, NOT THE RUN ROW'S, and the difference is
    visible on the live realm: two Wailing Caverns run rows opened eleven
    minutes apart, and the single `instance` row they share reads 7 for both.
    A lockout is what the core actually tracks, so that is what is reported,
    and `basis` says it in words rather than letting a reader assume the three
    bosses fell in the run they happen to be watching.

    THE BIT INDEX IS INFERRED AND THE PAYLOAD SAYS SO. The worldserver takes
    each encounter's bit from DungeonEncounter.dbc, and `dungeonencounter_dbc`
    holds zero rows on this realm, so the bit cannot be read. What is used
    instead is the position of the row in the dungeon's own block of
    `instance_encounters`, which is the order they are numbered in. It agrees
    with the live realm, and it is an inference either way, so `basis` carries
    the word and the page prints it.

    A mask of None is not a mask of 0. No record at all and a record saying
    nothing has fallen are different things, and they read differently.
    """
    if not encounters:
        return {"known": False, "down": [], "left": [], "count": 0,
                "total": 0, "line": "no boss list for this dungeon",
                "basis": "the world database lists no encounters for this map, "
                         "so there is nothing to count progress against"}
    if mask is None:
        return {"known": False, "down": [], "count": 0,
                "left": [e["name"] for e in encounters],
                "total": len(encounters),
                "line": "%d bosses, and no record of which have fallen"
                        % len(encounters),
                "basis": "the core keeps no instance record for this run, so "
                         "nothing here can say which bosses have fallen"}
    down, left = [], []
    for index, encounter in enumerate(encounters):
        (down if mask & (1 << index) else left).append(encounter["name"])
    return {"known": True, "down": down, "left": left, "count": len(down),
            "total": len(encounters),
            "line": "%d of %d bosses down" % (len(down), len(encounters)),
            "basis": "read from the worldserver's own completedEncounters "
                     "bitmask for the instance the family is bound to. That "
                     "lockout outlives a single run row, so a boss beaten on "
                     "an earlier visit to the same instance still counts here. "
                     "Which bit is which boss is inferred from the order of "
                     "the dungeon's rows in instance_encounters, because "
                     "DungeonEncounter.dbc is not loaded on this realm"}


def bind_instance(run: dict, instance_rows: list[dict]) -> int | None:
    """The completedEncounters mask for this run's instance, or None.

    Only a row on the run's own map counts, and the newest such row wins: the
    coordinator resets the instance between runs, so an older row is a
    different visit. None when there is no row, which the caller must not
    confuse with a mask of zero.
    """
    mine = [row for row in instance_rows
            if int(row.get("map") if row.get("map") is not None else -1)
            == int(run["map_id"])]
    if not mine:
        return None
    newest = max(mine, key=lambda row: int(row.get("id") or 0))
    mask = newest.get("completedEncounters")
    return None if mask is None else int(mask)


# --- who is in there -------------------------------------------------------

def party_state(roster: list[str], snapshot_rows: list[dict], run: dict,
                now: datetime) -> list[dict]:
    """Each family member, and whether they are in the dungeon and standing.

    ALIVE IS `health > 0` AND NOTHING CLEVERER. overseer_snapshot has no dead
    flag; a corpse and a ghost both read zero health, and calling that "down"
    is the honest reading of the only column there is.

    A snapshot older than SNAPSHOT_FRESH is reported as stale rather than as
    fact. The whole value of a live recap is that it is live, so a row from
    four minutes ago saying somebody is inside must not be drawn like one from
    four seconds ago.
    """
    by_name = {row["name"]: row for row in snapshot_rows}
    out = []
    for name in roster:
        row = by_name.get(name)
        if row is None:
            note = ("no snapshot row, so nothing here knows where %s is"
                    % name)
            out.append({"name": name, "known": False, "inside": False,
                        "tone": "away", "note": note,
                        "label": "%s: %s" % (name, note)})
            continue
        seen = row.get("updated_at")
        stale = bool(seen is not None and (now - seen) > SNAPSHOT_FRESH)
        health = int(row.get("health") or 0)
        maximum = int(row.get("max_health") or 0)
        inside = int(row.get("map_id") or -1) == int(run["map_id"])
        state = {
            "name": name,
            "known": True,
            "inside": inside,
            "alive": health > 0,
            "in_combat": bool(row.get("in_combat")),
            "level": row.get("level"),
            "health": health,
            "max_health": maximum,
            "health_pct": round(100.0 * health / maximum) if maximum else None,
            "stale": stale,
            "seen_at": _iso(seen),
        }
        # THE WORD AND THE TONE ARE BOTH DECIDED HERE. The page used to work
        # the tone out from inside/alive/in_combat, which is three judgements
        # about a character made in a place no Python test can reach. It gets
        # a role name now and turns it into a class, exactly as it does with
        # the hue on a Chronicle card.
        # `label` is what the chip SAYS and `tone` is how it is painted. The
        # page used to join the name and the note itself, which is a sentence
        # assembled where no test in this suite can read it.
        if not inside:
            state["note"], state["tone"] = "not on the dungeon map", "away"
        elif health <= 0:
            state["note"], state["tone"] = "down", "dead"
        elif stale:
            state["note"] = "last seen inside, but the snapshot is old"
            state["tone"] = "away"
        elif state["in_combat"]:
            state["note"], state["tone"] = "fighting", "fighting"
        else:
            state["note"], state["tone"] = "inside", ""
        state["label"] = "%s %s" % (name, state["note"])
        out.append(state)
    return out


# --- the recap -------------------------------------------------------------

def _run_deaths(run: dict, death_rows: list[dict], now: datetime,
                dungeons: dict, zones: dict) -> list[dict]:
    start, end = run_window(run, now)
    out = []
    for row in death_rows:
        when = row.get("created_at")
        if when is None or not (start <= when <= end):
            continue
        if int(row.get("map") or -1) != int(run["map_id"]):
            continue
        out.append({
            "who": row["character_name"],
            "at": _iso(when),
            "killer": row.get("killer_name") or "something unnamed",
            "killer_type": row.get("killer_type") or "",
            "place": place_name(int(row.get("map") or 0),
                                int(row.get("zone") or 0), dungeons, zones),
        })
    out.sort(key=lambda death: death["at"] or "")
    return out


def _party_line(inside: int, standing: int, roster: int) -> str:
    """How much of the family is in there, and how much of it is upright.

    Written here rather than assembled in the page from three numbers, for
    the reason the Chronicle redesign gives (infra#2597): a number with words
    around it is a claim, and a claim is judgement. "3 of 5 inside" and "all
    5 inside" are different sentences and picking between them is not layout.
    """
    if not inside:
        return "nobody from the family is on the dungeon map"
    where = ("all %d inside" % roster if inside == roster
             else "%d of %d inside" % (inside, roster))
    if standing == inside:
        return where + ", all standing"
    return "%s, %d standing and %d down" % (where, standing, inside - standing)


# The endings the coordinator writes are sometimes whole sentences ("the
# party walked back out through areatrigger 119") and sometimes bare tokens
# ("emptied", "left", "cold_heartbeat"). The page cannot tell which it has, so
# it must not be handed either raw: a token printed into a card reads as a leak,
# and every other string on this view is a written sentence.
_ENDINGS = {
    "left": "they walked back out",
    "emptied": "the map emptied without the coordinator walking them out",
    "cleared": "they cleared it",
    "cold_heartbeat": "the heartbeat went cold, so nobody was seen on the map",
    "wiped": "the party was wiped out",
}


def _ending(run: dict) -> str:
    """How a run finished, as a sentence.

    A reason that already reads as prose is kept: the coordinator writes good
    ones and rewording them would lose detail it went to the trouble of
    recording. A short token is looked up, and an unrecognised token is
    QUOTED rather than printed bare, so a reader can tell "this is the word
    the database used" from "this is the site talking".
    """
    reason = (run.get("ended_reason") or "").strip()
    outcome = (run.get("outcome") or "").strip()
    if " " in reason:
        return reason
    for token in (reason, outcome):
        if token in _ENDINGS:
            return _ENDINGS[token]
    unknown = reason or outcome
    if unknown:
        return ('the row says "%s", which is not a word this page knows'
                % unknown)
    return "nothing on the row says how it ended"


def _ended_summary(run: dict, firsts: dict, items: dict, icons: dict,
                   now: datetime, dungeons: dict, zones: dict) -> dict:
    map_id = int(run["map_id"])
    end = run.get("ended_at") or run.get("last_progress_at") or run["started_at"]
    loot = run_loot(run, firsts, items, icons, now, dungeons, zones)
    return {
        "dungeon": dungeons.get(map_id, "map %d" % map_id),
        "leader": run.get("leader_name") or "",
        "ended_at": _iso(run.get("ended_at")),
        "ended_reason": _ending(run),
        "lasted": elapsed(run["started_at"], end),
        "loot": loot,
        "loot_line": ("nothing new was worn in there" if not loot else
                      "%d first worn in there" % len(loot)),
        "line": "the last run was %s, led by %s, and it lasted %s"
                % (dungeons.get(map_id, "map %d" % map_id),
                   run.get("leader_name") or "nobody named",
                   elapsed(run["started_at"], end)),
    }


def build_recap(run_rows: list[dict], event_rows: list[dict],
                death_rows: list[dict], snapshot_rows: list[dict],
                instance_rows: list[dict], encounter_rows: list[dict],
                roster: list[str], items: dict, icons: dict,
                dungeons: dict, zones: dict, now: datetime) -> dict:
    """The live recap, or an honest account of why there is not one.

    DEGRADING IS HALF THE JOB. Nothing is running most of the time, and a
    recap that renders an empty frame then has told the reader something is
    broken. So `live` is false, `headline` says what is true instead, and the
    last run that DID happen is summarised beside it, which is what somebody
    opening the tab five minutes late actually wants.
    """
    active = [row for row in run_rows if is_active(row)]
    ended = [row for row in run_rows if not is_active(row)]
    firsts = first_equips(event_rows)

    if not active:
        last = max(ended, key=lambda r: r["started_at"]) if ended else None
        return {
            "live": False,
            "headline": ("no dungeon run is open right now" if run_rows else
                         "no dungeon run has ever been recorded on this realm"),
            "run": None,
            "party": [],
            "inside_count": 0,
            "standing_count": 0,
            "loot": [],
            "loot_line": "",
            "loot_caveat": LOOT_CAVEAT,
            "deaths": [],
            "deaths_line": "",
            "party_line": "",
            "progress": None,
            "last": (_ended_summary(last, firsts, items, icons, now, dungeons,
                                    zones) if last is not None else None),
        }

    run = max(active, key=lambda r: r["started_at"])
    map_id = int(run["map_id"])
    dungeon = dungeons.get(map_id, "map %d" % map_id)
    progressed = run.get("last_progress_at") or run["started_at"]
    stalled = (now - progressed) > STALL_AFTER
    party = party_state(roster, snapshot_rows, run, now)
    inside = [member for member in party if member.get("inside")]
    standing = len([member for member in inside if member.get("alive")])
    loot = run_loot(run, firsts, items, icons, now, dungeons, zones)
    deaths = _run_deaths(run, death_rows, now, dungeons, zones)
    return {
        "live": True,
        "headline": "%s, %s in" % (dungeon, elapsed(run["started_at"], now)),
        "run": {
            "id": run.get("id"),
            "map_id": map_id,
            "dungeon": dungeon,
            "leader": run.get("leader_name") or "",
            "started_at": _iso(run["started_at"]),
            "elapsed": elapsed(run["started_at"], now),
            "last_progress_at": _iso(run.get("last_progress_at")),
            "stalled": stalled,
            "stall_note": ("nothing has moved for %s, so this may have ended "
                           "without the coordinator noticing"
                           % elapsed(progressed, now)) if stalled else "",
        },
        "party": party,
        "inside_count": len(inside),
        "standing_count": standing,
        "party_line": _party_line(len(inside), standing, len(party)),
        "loot": loot,
        # The COUNT AND THE LIST ARE THE SAME ROWS, which is the whole point.
        # The header used to say nine over a list of nine that had two real
        # ones in it, and a header that overstates a list is worse than no
        # header: it is what the operator read and believed.
        "loot_line": ("nothing new worn in here yet" if not loot else
                      "%d first worn in here" % len(loot)),
        "loot_caveat": LOOT_CAVEAT,
        "deaths": deaths,
        "deaths_line": ("nobody has gone down" if not deaths else
                        "%d down so far" % len(deaths)),
        # `encounter_rows` are THIS RUN'S MAP'S, which the adapter fetches
        # separately from the board's for the reason run_map explains.
        "progress": encounters_down(bind_instance(run, instance_rows),
                                    encounter_order(encounter_rows)),
        "last": None,
    }


# --- what can drop here, and whether anybody wants it -----------------------
#
# THE ONE JUDGEMENT THIS REFUSES TO MAKE IS A STAT WEIGHTING. Whether 4
# Strength beats 6 Stamina for a level 27 Warrior is a real question with a
# real answer, and nothing in this repository knows it. Ranking by item level
# is a rule a reader can check, so every verdict below prints the comparison
# that produced it and the page prints that sentence rather than a score. A
# tie is reported as a tie.

# The paper doll slots an item of each InventoryType can occupy, as indices
# into armory.EQUIPPED_SLOTS. A type absent from here is one that never goes
# on the doll at all: 18 is a bag, 24 is ammo, 0 is not equipment.
#
# A ONE-HANDER (13) IS COMPARED AGAINST THE MAIN HAND ONLY, and that is a
# deliberate narrowing rather than an oversight. It can physically go in the
# off hand too, and the first version allowed it: every one-handed drop in
# Wailing Caverns then came back "wanted by" all five, because none of them
# has anything in the off hand and an empty slot is all gain. Whether a
# character may hold a second weapon at all is a class fact this module does
# not check, so the honest move is to compare the slot it certainly fits and
# say what was not considered.
WEARABLE_SLOTS = {
    1: (0,), 2: (1,), 3: (2,), 4: (3,), 5: (4,), 20: (4,), 6: (5,), 7: (6,),
    8: (7,), 9: (8,), 10: (9,), 11: (10, 11), 12: (12, 13), 16: (14,),
    13: (15,), 17: (15,), 21: (15,), 14: (16,), 22: (16,), 23: (16,),
    15: (17,), 25: (17,), 26: (17,), 28: (17,), 19: (18,),
}

ONE_HANDED = 13
TWO_HANDED = 17
ARMOUR_CLASS = 4
WEAPON_CLASS = 2
# item_template.subclass for class 4. Only these four are a proficiency
# ladder; 6 is a shield and 0 is a cloak or a trinket, and neither is heavier
# than the other.
ARMOUR_GRADES = {1: "Cloth", 2: "Leather", 3: "Mail", 4: "Plate"}

UPGRADE = "upgrade"
SIDEGRADE = "sidegrade"
WORSE = "worse"
EMPTY = "empty"
LOCKED = "locked"
TOO_HEAVY = "too heavy"
WRONG_CLASS = "wrong class"
NO_PROFICIENCY = "no proficiency"
UNRANKED = "unranked"

# The order the board sorts a drop's readers in, best first.
_VERDICT_RANK = {EMPTY: 0, UPGRADE: 1, SIDEGRADE: 2, LOCKED: 3,
                 TOO_HEAVY: 4, WRONG_CLASS: 5, NO_PROFICIENCY: 6, WORSE: 7,
                 UNRANKED: 8}

# --- can this character hold it at all (mod-overseer#411) -------------------
#
# THE ITEM SAYS NOTHING ABOUT THIS, AND THAT IS THE WHOLE DEFECT. The board
# offered Kam's Walking Stick (entry 2280, a STAFF) to a rogue, because the
# only class gate here is `allowable_class` and that column is -1 on the
# staff, which means the ITEM restricts nobody. Whether a character may hold
# a weapon is not an item property in this game at all: it is a proficiency,
# granted by spells a class learns, kept in that character's own
# `character_skills` rows, and absent from `item_template` entirely. So a
# class mask plus an item-level comparison will keep offering staves and
# polearms to rogues for ever, and will look right every time.
#
# NOT A CLASS-TO-SUBCLASS TABLE, for the same reason `armour_grade` below
# refuses to be one: a warrior may wear plate, but not until 40, and a weapon
# master will teach a class a weapon line it did not start with. What each
# character actually holds is a row in the realm, and a table would be a guess
# that goes stale silently.
#
# THE MAP FROM SUBCLASS TO SKILL IS THE CORE'S OWN, copied in the core's own
# order out of `ItemTemplate::GetSkill` (ItemTemplate.h:782-815 at the pinned
# revision this realm runs) so the two can be diffed by eye. The ids are
# SharedDefines.h:3104-3199 of the same revision, read rather than remembered.
# A 0 is the core's own 0: a subclass it maps to no skill, which therefore
# needs none.
#
# The test itself is the core's, too. `Player::CanUseItem(Item*, bool)` refuses
# with EQUIP_ERR_NO_REQUIRED_PROFICIENCY whenever `GetSkillValue(itemSkill)`
# is 0 (PlayerStorage.cpp:2343-2367), and `Item::GetSkill` is
# `GetTemplate()->GetSkill()` (Item.cpp:556-559), so the skill line is a
# property of the template and this read reproduces the core's answer exactly.
#
# (The OTHER CanUseItem overload, the one taking an ItemTemplate, does NOT
# make this test - it returns EQUIP_ERR_NO_REQUIRED_PROFICIENCY only for the
# item's own RequiredSkill and RequiredSpell columns, both 0 on an ordinary
# weapon. It is the obvious call and it would not have caught entry 2280.)
WEAPON_SKILLS = {
    0: 44, 1: 172, 2: 45, 3: 46, 4: 54,
    5: 160, 6: 229, 7: 43, 8: 55, 9: 0,
    10: 136, 11: 0, 12: 0, 13: 473, 14: 0,
    15: 173, 16: 176, 17: 253, 18: 226, 19: 228,
    20: 356,
}
ARMOUR_SKILLS = {0: 0, 1: 415, 2: 414, 3: 413, 4: 293, 5: 0, 6: 433,
                 7: 0, 8: 0, 9: 0, 10: 0}

# For the SENTENCE only. It decides nothing, which is why it is allowed to be
# a table: a refusal a reader cannot check is a refusal they will distrust.
SKILL_NAMES = {
    43: "one-hand sword", 44: "one-hand axe", 45: "bow", 46: "gun",
    54: "one-hand mace", 55: "two-hand sword", 136: "staff",
    160: "two-hand mace", 172: "two-hand axe", 173: "dagger", 176: "thrown",
    226: "crossbow", 228: "wand", 229: "polearm", 253: "spear",
    293: "plate", 356: "fishing pole", 413: "mail", 414: "leather",
    415: "cloth", 433: "shield", 473: "fist weapon",
}

# WORN REGARDLESS, so no proficiency is asked for. A cloak's subclass is cloth
# and a shirt's and a tabard's are too, and the core exempts all three from the
# proficiency rule the same way mod-overseer's own scorer does. Gating them
# would refuse a cloak to somebody wearing one.
NO_PROFICIENCY_SLOTS = (4, 16, 19)  # shirt, back, tabard


def item_skill(drop: dict) -> int:
    """The skill line this item needs, by the core's own table. 0 for none."""
    if int(drop.get("inventory_type") or 0) in NO_PROFICIENCY_SLOTS:
        return 0
    subclass = int(drop.get("subclass") or 0)
    if drop.get("class") == WEAPON_CLASS:
        return WEAPON_SKILLS.get(subclass, 0)
    if drop.get("class") == ARMOUR_CLASS:
        return ARMOUR_SKILLS.get(subclass, 0)
    return 0


def slots_for(inventory_type: int | None) -> tuple:
    """Which paper doll slots this item could go in. Empty for a bag."""
    if inventory_type is None:
        return ()
    return WEARABLE_SLOTS.get(int(inventory_type), ())


def armour_grade(equipped: list[dict]) -> int | None:
    """The heaviest armour this character is ALREADY WEARING, 1 to 4.

    READ OFF THE CHARACTER RATHER THAN OFF A CLASS TABLE, and that is the
    whole trick. A table of what each class may wear is wrong for exactly the
    case that matters: a Warrior may wear Plate, but not until level 40, so a
    level 27 Warrior offered a plate chest is being offered something he
    cannot put on for thirteen levels. What he is wearing right now is the
    proficiency he actually has, it needs no extra query, and it cannot drift
    from the realm the way a hand-written table can.

    None when nothing worn is graded armour, which is a real state for a
    character in starting cloth-and-cloaks, and the verdict says so rather
    than guessing.

    NOW THE FALLBACK RATHER THAN THE RULE (mod-overseer#411). Reading the
    character's own `character_skills` rows answers the same question directly
    and answers it for weapons too, so `verdict` uses that whenever it has it
    and drops back to this only when the realm handed no skill rows over. This
    stays because that fallback is real - it is what the board ranked on for
    its whole life - and because it needs no query of its own.
    """
    grades = [int(row["subclass"]) for row in equipped
              if row.get("class") == ARMOUR_CLASS
              and int(row.get("subclass") or 0) in ARMOUR_GRADES]
    return max(grades) if grades else None


def _worn_in(equipped_by_slot: dict, slots: tuple) -> tuple:
    """The item this drop would replace, and the slot it sits in.

    The WEAKEST of the candidate slots, because that is the one a second ring
    or a second trinket actually displaces. (None, None) when any candidate
    slot is empty: an empty slot is the best case and costs nothing.
    """
    worn = []
    for index in slots:
        row = equipped_by_slot.get(index)
        if row is None:
            return None, index
        # An item the WORLD TABLE cannot name has no item level, and it is a
        # LEFT JOIN in the query for exactly that reason: a custom or removed
        # entry still reports as worn rather than as an empty slot. Reading a
        # missing level as zero would rank every drop in the game above it and
        # print "against the 0 of the item worn there", which is a confident
        # sentence about something nothing here knows.
        level = row.get("item_level")
        worn.append((-1 if level is None else int(level), index, row))
    _, index, row = min(worn, key=lambda entry: entry[0])
    return row, index


def _slot_name(index: int) -> str:
    """The paper doll's own word for a slot. Guarded on the high side because
    WEARABLE_SLOTS and EQUIPPED_SLOTS are two lists that have to agree."""
    if index >= len(EQUIPPED_SLOTS):
        return "no slot"
    return EQUIPPED_SLOTS[index]


def verdict(drop: dict, member: dict) -> dict:
    """Whether this drop beats what this character is wearing, and why.

    Every branch names the comparison it made in `why`, because the page
    prints that sentence and a reader has to be able to disagree with it.
    """
    slots = slots_for(drop.get("inventory_type"))
    name = member["name"]
    ilvl = int(drop.get("item_level") or 0)
    if not slots:
        return {"who": name, "verdict": UNRANKED, "slot": "no slot",
                "why": "not something that goes on the paper doll, so there is "
                       "nothing to compare it against"}

    required = int(drop.get("required_level") or 0)
    level = int(member.get("level") or 0)
    allowable = drop.get("allowable_class")
    class_id = int(member.get("class") or 0)
    worn, slot_index = _worn_in(member["by_slot"], slots)
    slot = _slot_name(slot_index)
    base = {"who": name, "slot": slot,
            "worn": (worn.get("item_name") if worn else None),
            "worn_ilvl": (int(worn.get("item_level") or 0) if worn else None)}

    if (allowable not in (None, -1, 0) and class_id
            and not (int(allowable) & (1 << (class_id - 1)))):
        base.update(verdict=WRONG_CLASS,
                    why="restricted to other classes, so %s cannot use it at "
                        "all" % name)
        return base
    # PROFICIENCY, WHICH `allowable_class` ABOVE IS NOT (mod-overseer#411).
    # Placed here because it is the same KIND of gate as the one above it and
    # answers before anything about levels or item levels: a character who can
    # never hold the thing is not "locked" and is not "worse", and printing
    # either of those about them invites a comparison that has no meaning.
    #
    # `skills` is None when the realm did not hand this character's skill rows
    # over - a degraded schema, a read that fell through its guard. That is not
    # a refusal and must never become one: an unknown answer falls through to
    # exactly the behaviour this board had before, item level and a caveat
    # saying proficiency was not checked. Silently refusing everybody on a
    # failed read would empty the board and look like a quiet dungeon.
    needed = item_skill(drop)
    skills = member.get("skills")
    if needed and skills is not None:
        if needed not in skills:
            base.update(verdict=NO_PROFICIENCY,
                        why="%s has no %s skill, so %s can never hold this "
                            "whatever its item level"
                            % (name, SKILL_NAMES.get(needed, "required"),
                               name))
            return base
        grade = None
    else:
        grade = (drop.get("subclass")
                 if drop.get("class") == ARMOUR_CLASS else None)
    if grade in ARMOUR_GRADES:
        worn_grade = member.get("armour_grade")
        if worn_grade is None:
            base.update(verdict=UNRANKED,
                        why="%s is wearing no graded armour, so nothing here "
                            "knows whether %s can wear %s"
                            % (name, name, ARMOUR_GRADES[grade]))
            return base
        if int(grade) > worn_grade:
            base.update(verdict=TOO_HEAVY,
                        why="this is %s and the heaviest %s wears is %s"
                            % (ARMOUR_GRADES[grade], name,
                               ARMOUR_GRADES[worn_grade]))
            return base
    if required > level:
        base.update(verdict=LOCKED,
                    why="needs level %d and %s is %d" % (required, name, level))
        return base

    if worn is None:
        base.update(verdict=EMPTY,
                    why="nothing is worn in %s's %s slot, so item level %d is "
                        "all gain" % (name, slot, ilvl))
        return base
    if worn.get("item_level") is None:
        base.update(verdict=UNRANKED,
                    why="the world database does not know the item worn in "
                        "%s's %s slot, so there is nothing to compare against"
                        % (name, slot))
        return base
    worn_ilvl = int(worn["item_level"])
    if ilvl > worn_ilvl:
        base.update(verdict=UPGRADE, gain=ilvl - worn_ilvl,
                    why="item level %d against the %d of the %s worn there"
                        % (ilvl, worn_ilvl, worn.get("item_name") or "item"))
    elif ilvl == worn_ilvl:
        base.update(verdict=SIDEGRADE,
                    why="item level %d, the same as the %s worn there"
                        % (ilvl, worn.get("item_name") or "item"))
    else:
        base.update(verdict=WORSE,
                    why="item level %d against the %d of the %s worn there"
                        % (ilvl, worn_ilvl, worn.get("item_name") or "item"))
    return base


def _caveats(drop: dict, proficiency_checked: bool = False) -> list[str]:
    """What the verdict above did NOT check, said out loud.

    A verdict that quietly omits this is one a reader will over-trust, and
    weapon proficiency was the case that actually bit: a staff was offered to
    a rogue because nothing here knew a rogue cannot hold one.

    AND A CAVEAT THAT OUTLIVES THE GAP IT DESCRIBED IS WORSE THAN NONE,
    because it teaches the reader to distrust the whole footer. So the two
    notes that mod-overseer#411 closed - weapon proficiency and shield
    proficiency - are printed only while `proficiency_checked` is False, which
    is when the realm did not hand over the skill rows and the verdict really
    did fall back to item level alone.

    THE OTHER TWO STAY, because their gaps are still real. Nothing here checks
    dual wield, so a one-hander is still compared against the main hand only;
    and a two-hander's cost to the off hand still is not priced, which this
    board cannot do honestly anyway - it ranks by item level, and item levels
    do not add, so "27 against 24 plus 22" would be arithmetic on a scale that
    does not support it.

    FACTS ABOUT THE ITEM, SO THEY NAME NOBODY. The first version took a member
    and interpolated their name, and the caller passed members[0] once for the
    whole list, so every weapon in the dungeon was captioned "says nothing
    about whether they can hold it" including the ones read for somebody else.
    `proficiency_checked` keeps that property: it is a fact about the board's
    own data, not about any one character.
    """
    notes = []
    if not proficiency_checked and drop.get("class") == WEAPON_CLASS:
        notes.append("weapon proficiency is not checked, so nothing here says "
                     "who can actually hold it")
    if (not proficiency_checked and drop.get("class") == ARMOUR_CLASS
            and int(drop.get("subclass") or 0) == 6):
        notes.append("shield proficiency is not checked")
    if int(drop.get("inventory_type") or 0) == ONE_HANDED:
        notes.append("compared against the main hand only: putting it in the "
                     "off hand needs dual wield, which is not checked")
    if int(drop.get("inventory_type") or 0) == TWO_HANDED:
        notes.append("a two-hander also costs the off hand, which this "
                     "comparison does not price")
    return notes


def _also_line(wanted: list[dict], best: dict | None) -> str:
    """Who else this would suit, beyond the one already named.

    Trimmed HERE against the reader actually shown, rather than in the page
    against a position it assumed. Empty when there is nobody else, so the
    page prints nothing rather than a sentence ending in nothing.
    """
    named = best["who"] if best else None
    others = [reader["who"] for reader in wanted if reader["who"] != named]
    if not others:
        return ""
    return "also wanted by " + ", ".join(others)


def _chance(row: dict, group_sizes: dict) -> str:
    """How likely a drop is, in the world table's own terms.

    THREE CASES, AND GroupId 0 IS NOT A GROUP. In creature_loot_template a
    GroupId of 0 means the row is not grouped at all and rolls on its own
    Chance; a non-zero GroupId means the rows sharing it share one roll. The
    first version bucketed every ungrouped row of a creature together and
    reported "one roll shared with 39 others in its group", which is not what
    the table says, and a group of one produced "shared with 0 others".

    A Chance of 0 inside a real group is the case worth reporting as a group
    size, because a percentage there would be a guess somebody would act on.
    A Chance of 0 outside one is the table declining to say, and so is this.
    """
    chance = float(row.get("Chance") or 0)
    if chance > 0:
        return "%g%%" % chance
    group = int(row.get("GroupId") or 0)
    if not group:
        return "the loot table gives no drop chance for this row"
    size = group_sizes.get((int(row["Entry"]), group), 1)
    if size < 2:
        return "one shared roll, and it is the only row in its group"
    return "one roll shared between the %d rows in its group" % size


def build_lootboard(map_id: int, dungeon: str, encounter_rows: list[dict],
                    loot_rows: list[dict], char_rows: list[dict],
                    equipped_rows: list[dict], icons: dict,
                    roster: list[str],
                    skill_rows: list[dict] | None = None) -> dict:
    """What each boss on this map can drop, and who it would be for.

    The bosses come from `instance_encounters` narrowed to creatures spawned
    on the map, not from a hand-written list: a hand-written list is what put
    a boss in the Chronicle that the core does not count (infra#3189), and it
    also cannot follow the family into the next dungeon on its own.

    `skill_rows` are `character_skills` rows and are what lets the verdict
    answer proficiency at all (mod-overseer#411). They default to None so a
    caller that has not got them still gets the board it always got, with the
    caveats that say proficiency was not checked still printed.
    """
    encounters = encounter_order(encounter_rows)
    members = _members(char_rows, equipped_rows, roster, skill_rows)
    # EVERY MEMBER, OR THE FOOTER STILL WARNS. A board where one character's
    # skills are missing is a board where that character's verdicts are the
    # old item-level ones, and the caveat is about the board rather than about
    # a member - so one unknown is enough to keep it printed for everybody.
    proficiency_checked = bool(members) and all(
        member["skills"] is not None for member in members)
    group_sizes: dict = {}
    for row in loot_rows:
        key = (int(row["Entry"]), int(row.get("GroupId") or 0))
        group_sizes[key] = group_sizes.get(key, 0) + 1

    by_creature: dict = {}
    for row in loot_rows:
        by_creature.setdefault(int(row["creature"]), []).append(row)

    bosses = []
    for encounter in encounters:
        drops = []
        for row in by_creature.get(encounter["creature"], []):
            if not slots_for(row.get("inventory_type")):
                continue
            entry = int(row["Item"])
            drop = item_payload(entry, row, icons)
            readers = sorted((verdict(row, member) for member in members),
                             key=lambda v: (_VERDICT_RANK.get(v["verdict"], 9),
                                            -int(v.get("gain") or 0), v["who"]))
            wanted = [r for r in readers if r["verdict"] in (UPGRADE, EMPTY)]
            slot = _slot_name(slots_for(row.get("inventory_type"))[0])
            chance = _chance(row, group_sizes)
            best = readers[0] if readers else None
            drop.update(
                chance=chance,
                slot=slot,
                # "shoulders, 80%": the page used to join these two itself.
                meta="%s, %s" % (slot, chance),
                readers=readers,
                wanted_by=[reader["who"] for reader in wanted],
                best=best,
                # THE SENTENCE, NOT THE PIECES. The page used to write
                # `best.who + ": " + best.why`, and worse, to take
                # `wanted_by.slice(1)` as "everybody except the one already
                # shown" - which is only true while _VERDICT_RANK happens to
                # sort EMPTY and UPGRADE above everything else. Re-rank the
                # verdicts here and the page would start hiding a name or
                # repeating one, with nothing failing.
                verdict_line=("%s: %s" % (best["who"], best["why"])
                              if best else ""),
                also_line=_also_line(wanted, best),
                caveats=_caveats(row, proficiency_checked),
            )
            drops.append(drop)
        drops.sort(key=lambda d: (0 if d["wanted_by"] else 1,
                                  -(d["ilvl"] or 0), d["name"]))
        wanted = len([drop for drop in drops if drop["wanted_by"]])
        bosses.append({
            "name": encounter["name"],
            "creature": encounter["creature"],
            "drops": drops,
            "wanted": wanted,
            "line": _boss_line(len(drops), wanted),
        })

    return {
        "map_id": map_id,
        "dungeon": dungeon,
        "bosses": bosses,
        "line": ("%s: %d bosses, %d pieces of gear between them"
                 % (dungeon, len(bosses),
                    sum(len(boss["drops"]) for boss in bosses))),
        "members": [{"name": m["name"], "level": m.get("level"),
                     "armour": ARMOUR_GRADES.get(m.get("armour_grade"),
                                                 "nothing graded")}
                    for m in members],
        "basis": (
            "Bosses from the core's own instance_encounters table, narrowed "
            "to the credit creatures spawned on this map. An encounter whose "
            "creature is summoned rather than spawned is therefore not "
            "listed. Drops from creature_loot_template, direct rows only: "
            "loot that lives behind reference_loot_template is not followed, "
            "so this is not a complete drop list. Ranked by item level only: "
            "no stat weighting is applied anywhere, and a tie is reported as "
            "a tie. " + (
                "Whether a character can hold a thing is read from their own "
                "character_skills rows, using the core's own "
                "subclass-to-skill map, so a weapon or a shield nobody can "
                "use is refused by name rather than ranked."
                if proficiency_checked else
                "Proficiency could not be read for every character this time, "
                "so a weapon is ranked on item level alone and the drop says "
                "so.")),
        "empty_note": ("the world database lists no encounters for this map, "
                       "so there is no boss loot to show"
                       if not encounters else ""),
    }


def _boss_line(drops: int, wanted: int) -> str:
    if not drops:
        return "nothing this boss drops goes in a gear slot"
    if not wanted:
        return "%d pieces, none of which beats what anybody wears" % drops
    return "%d pieces, %d of them worth taking" % (drops, wanted)


def _members(char_rows: list[dict], equipped_rows: list[dict],
             roster: list[str],
             skill_rows: list[dict] | None = None) -> list[dict]:
    """The family as the board compares against them.

    Built from whatever rows arrive, in roster order, so a sixth character or
    a rerolled class is a different payload and not a different code path.

    `skills` is a set of skill ids the character actually holds, or None when
    nothing was handed over for them (mod-overseer#411). None is the honest
    third state and it is NOT an empty set: an empty set says "holds nothing",
    which would refuse this character every weapon on the board, and a read
    that fell through its guard must not be able to do that. A member absent
    from `skill_rows` while other members are present therefore stays None,
    rather than inheriting somebody else's answer or a confident zero.

    A row is only counted when its value is above zero, which is what
    `Player::GetSkillValue(skill) == 0` tests in the core.
    """
    worn: dict = {}
    for row in equipped_rows:
        worn.setdefault(row["name"], []).append(row)
    held: dict = {}
    for row in skill_rows or []:
        if int(row.get("value") or 0) > 0:
            held.setdefault(row["name"], set()).add(int(row["skill"]))
    by_name = {row["name"]: row for row in char_rows}
    members = []
    for name in roster:
        char = by_name.get(name)
        if char is None:
            continue
        mine = worn.get(name, [])
        members.append({
            "name": name,
            "level": char.get("level"),
            "class": char.get("class"),
            "by_slot": {int(row["slot"]): row for row in mine},
            "armour_grade": armour_grade(mine),
            "skills": held.get(name),
        })
    return members


# --- where a worn item came from -------------------------------------------

def record_starts(event_rows: list[dict]) -> datetime | None:
    """The oldest equip the record holds. Anything worn before this is
    unknowable here, and the provenance line says so with the date rather
    than shrugging."""
    seen = [row["first_seen"] for row in event_rows
            if row.get("kind") in (None, ITEM_EQUIP)]
    return min(seen) if seen else None


def provenance_index(event_rows: list[dict], equipped_rows: list[dict],
                     dungeons: dict, zones: dict) -> dict:
    """character -> item entry -> where and when it was FIRST WORN.

    THE EARLIEST ROW, NOT THE LATEST. The latest row for a worn item is only
    the most recent re-scan, which is always a few minutes ago and wherever
    the character happens to be standing: on the live realm the newest row for
    Ugga's Buzzer Blade says Wailing Caverns today, and the oldest says the
    Deadmines on 2 September, which is where she got it.

    THE EVENT SAYS WHERE IT WAS WORN, NOT WHERE IT DROPPED, and the line says
    "first worn in" for that reason. A character can loot in a dungeon and
    equip in town, and nothing in the record can tell those apart.

    An item with no row at all still gets an entry, saying there is no record
    and from when the record runs. That distinction is the value of this: an
    item hidden because it has no provenance looks like an item with none.
    """
    firsts = first_equips(event_rows)
    starts = record_starts(event_rows)
    since = ("the equip record starts %s" % starts.strftime("%d %B %Y")
             if starts is not None else "the equip record is empty")
    out: dict = {}
    for row in equipped_rows:
        who = row["name"]
        entry = int(row["entry"])
        first = firsts.get((who, entry))
        if first is None:
            out.setdefault(who, {})[entry] = {
                "known": False,
                "line": "no record of where this came from: %s" % since,
            }
            continue
        place = place_name(int(first.get("map") or 0),
                           int(first.get("zone") or 0), dungeons, zones)
        out.setdefault(who, {})[entry] = {
            "known": True,
            "at": _iso(first["first_seen"]),
            "place": place,
            "map_id": int(first.get("map") or 0),
            "zone_id": int(first.get("zone") or 0),
            "line": "first worn in %s" % place,
        }
    return out


# --- what the adapter must ask the database for ----------------------------
#
# These three answer questions the HTTP adapter would otherwise have to decide
# for itself: which map's loot board to build, which item rows to name, and
# what a zone id is called. Each is a judgement, each is reachable from the
# suite here, and none of them is reachable inside an f-string in map_server.

def run_map(run_rows: list[dict]) -> int | None:
    """The map the live run is on, or None when nothing is open.

    SEPARATE FROM board_map ON PURPOSE, AND A BUG PROVED WHY. The two were one
    function, so asking the board for a dungeon the family is not in
    ("?map=36" while they are in Wailing Caverns) fetched the Deadmines'
    encounter list and then counted the Wailing Caverns lockout mask against
    it. The recap read "6 of 6 bosses down" over a dungeon nobody had entered.
    Progress belongs to the RUN's map and the board belongs to the map being
    browsed, and they are only usually the same.
    """
    live = [row for row in run_rows if is_active(row)]
    if not live:
        return None
    return int(max(live, key=lambda r: r["started_at"])["map_id"])


def board_map(run_rows: list[dict], asked: int | None,
              default: int = 43) -> int:
    """Which dungeon the loot board should be built for.

    An explicit `?map=` wins, because a reader browsing ahead has said what
    they want. Otherwise the live run's map, because the question "what can
    drop here" is nearly always about where they are standing. Otherwise the
    most recent run's map, and only then the default, so a page opened cold
    still has something in it rather than an empty frame.
    """
    if asked:
        return int(asked)
    live = [row for row in run_rows if is_active(row)]
    if live:
        return int(max(live, key=lambda r: r["started_at"])["map_id"])
    if run_rows:
        return int(max(run_rows, key=lambda r: r["started_at"])["map_id"])
    return default


def wanted_items(event_rows: list[dict]) -> list[int]:
    """The item entries the adapter needs names for, sorted and de-duplicated.

    Sorted so the query is stable between calls, which makes a slow-query log
    readable and a cached plan reusable.
    """
    return sorted({int(row["subject_id"]) for row in event_rows
                   if row.get("kind") in (None, ITEM_EQUIP)})


def zone_names(continents: dict) -> dict[int, str]:
    """area id -> zone name, from the frozen client zone table.

    zones.json is loaded once at import by transform.Geometry, so this is a
    reshape of something already in memory rather than a second read. It is
    here and not there because "which id is which name" is the question
    place_name asks, and both halves of that should be testable together.
    """
    out: dict[int, str] = {}
    for region in continents.values():
        for zone in region.get("zones", []):
            area = zone.get("area_id")
            if area is not None:
                out[int(area)] = zone.get("name") or ""
    return out
