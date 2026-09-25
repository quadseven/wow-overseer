"""What the family is trying to do RIGHT NOW, in one sentence.

infra#3205. Every view this page already has answers a different question.
The map says WHERE the five are. The Family tab says whether they are alive.
The Armory says what they are wearing, the Quest board what is in their logs,
the Chronicle what they have already done. None of them says what the
family is CURRENTLY TRYING TO ACHIEVE, which is the question the operator asks out
loud every time he opens the page, and the only one he still has to ask a
person to answer.

NO NEW TABLE, AND NO NEW SOURCE OF TRUTH. The state is already recorded - it
is just scattered across five tables written by three different processes,
and nobody has ever put the pieces beside each other:

    overseer_roster.job                 the RimWorld-style schedule slot
                                        (jobs.MODES) the family is in
    overseer_roster.drive_quest         which quest the aim is pointed at
    overseer_roster.travel_npc          an errand: walk to this NPC or place
    overseer_roster.learn_skill         what the errand is FOR
    overseer_roster.dungeon_runs_*      the dungeon campaign counter
                                        (quadseven/mod-overseer#144)
    overseer_dungeon_run                one row per run: state, run_number,
                                        outcome, members
    instance.completedEncounters        the bosses-down bitmask, which is the
                                        only boss-progress number on this
                                        realm that is not a guess (see below)
    overseer_goal                       a Discord order aimed at one character
    overseer_trade                      an errand the council decided on
    overseer_event                      the movement feed, which is what makes
                                        a stall detectable at all

So this module READS. It writes nothing, invents nothing, and adds no column.
Where two of those sources disagree it says they disagree rather than picking
one, because the whole reason this page is being asked for is that a split
party is the failure the operator keeps catching by eye.

PURE MODULE, the same seam as family.py, questlog.py and achievements.py: rows
in, the banner's JSON out. No MySQL, no Discord, no LLM, and no clock of its
own unless one is not handed to it. That is what lets the decision table below
be exercised by the stdlib suite with no world running.

THREE THINGS THIS MUST NEVER DO, each of which is a bug this codebase has
already shipped once in another shape:

1. Never report a majority as if it were unanimous. If four are questing and
   one is in a dungeon, the headline says the family is split and names who is
   where. A silent majority vote is exactly the 937-yard scatter of infra#2812
   wearing a clean shirt.
2. Never let a stale reading look live. Everything here carries the timestamp
   it was derived from, and a family that has not moved in STALL_AFTER is
   labelled stalled - that is quadseven/mod-overseer#171 seen from outside the
   worldserver, and the page saying so is how it stops being invisible.
3. Never claim more progress than the record supports. Boss progress is the
   instance's own bitmask and is described as what it actually is - the state
   of the lockout the family is SAVED TO - not as "bosses killed this run",
   which no table on this realm records.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import achievements
import goals
import jobs
import travel

# How long the family may go without moving before the page calls it stalled.
#
# TWENTY MINUTES, and the number comes from the bug rather than from taste.
# quadseven/mod-overseer#171 is a run that stops making progress while its row
# still reads `state = 'active'`, so from every existing view the party looks
# busy and is not. A Deadmines clear at this level takes the family about an
# hour and puts a quest, a level or an equip on the event feed every few
# minutes, so twenty minutes of total silence is well outside normal play and
# well inside a person's patience. Below ten this would cry stall over a long
# corridor; above thirty it is slower than the operator noticing by eye, which would
# make the whole feature pointless. It is deliberately the same twenty minutes
# mod_overseer.cpp's TRAVEL_BACKSTOP_SECONDS gives a walk before giving up.
STALL_AFTER = timedelta(minutes=20)

# What counts as the family MOVING. Deliberately not every event kind: dying
# is a thing that happened, not progress, and a party wiping on a loop is the
# precise state this must still call stalled. `death` is therefore excluded on
# purpose - a stall detector that reset on a corpse run would have said the
# family was fine all the way through #171.
MOVEMENT_KINDS = frozenset(
    {
        "quest_accept",
        "quest_complete",
        "quest_reward",
        "level_up",
        "item_equip",
        "unlearn",
    }
)

# How many encounter BITS `instance.completedEncounters` has for a map, so
# "4 of 7" has a denominator that is true rather than remembered.
#
# WHY THIS IS A CONSTANT AND NOT A QUERY. The count belongs in
# DungeonEncounter.dbc, and `acore_world.dungeonencounter_dbc` is EMPTY on this
# deployment - the same hole goals.py's SKILL_IDS comment documents for
# skillline_dbc, because DBC data ships inside the client files. So it was
# measured the one way this server can be asked: acore_world.instance_encounters
# on wow-dev on 2026-09-03 holds exactly seven rows for the Deadmines credit
# creatures (entries 161-167: Rhahk'zor, Sneed, Gilnid, Mr. Smite, Cookie,
# Captain Greenskin, Edwin VanCleef), which is why a cleared Deadmines reads
# 127 and not 255.
#
# NOTE THAT IS SEVEN AND NOT EIGHT, and that achievements.DUNGEONS[36] lists
# eight creatures. Sneed's Shredder (642) is the same ENCOUNTER as Sneed (643)
# and holds no bit of its own. Deriving the denominator from that boss list
# would have printed "of 8" for a dungeon that can only ever reach 7, which is
# exactly the kind of off-by-one a remembered number produces.
#
# A map with no entry here gets its bosses counted and no denominator, which
# is a thinner sentence rather than a false one.
ENCOUNTERS = {36: 7}

# The activity kinds a headline can be about. Named rather than spelled inline
# so the page can style them and the suite can assert on them without matching
# English.
DUNGEON = "dungeon"
TRAVEL = "travel"
JOB = "job"
QUEST = "quest"
IDLE = "idle"
SPLIT = "split"


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.strftime("%Y-%m-%dT%H:%M:%S")


def _seconds(then: datetime | None, now: datetime) -> int | None:
    """Whole seconds since `then`, never negative.

    Clamped at zero rather than allowed to go negative: MySQL's clock and the
    pod's are two clocks, and a banner reading "changed -3s ago" would look
    like a bug in the page rather than the half second of skew it is.
    """
    if then is None:
        return None
    return max(0, int((now - then).total_seconds()))


def _enabled(roster_rows: list[dict]) -> list[dict]:
    """The roster rows actually being driven, leader first, then by name.

    A disabled row is not a member of the family for this purpose: nothing
    aims it, so counting its `job` into a split would invent a disagreement
    out of a character nobody is playing. mod_overseer.cpp's own loaders all
    filter `enabled = 1` the same way.
    """
    rows = [r for r in roster_rows if int(r.get("enabled") or 0)]
    return sorted(rows, key=lambda r: (-int(r.get("lead") or 0), str(r["name"])))


def _leader(rows: list[dict]) -> dict | None:
    """The row wearing the crown, or the first one if nobody does."""
    for row in rows:
        if int(row.get("lead") or 0):
            return row
    return rows[0] if rows else None


def _mode(row: dict) -> str:
    """One roster row's job, with the column's own default for a blank.

    mod_overseer.cpp's LoadJobs selects `job <> '' AND job <> 'quest'` and
    treats absence from the result as questing, so an empty string here means
    the same thing the module means by it.
    """
    return str(row.get("job") or "").strip() or jobs.DEFAULT


# --- disagreement ------------------------------------------------------------


def split_on(rows: list[dict], field: str, blank=None) -> dict | None:
    """How the family disagrees about one column, or None if they do not.

    Returns the groups largest first, each with the names in it. The caller
    decides whether a given disagreement deserves the headline; this only
    reports the shape of it.

    `blank` is the value that means "no opinion" and is folded into a group
    like any other. A character with no quest aim while four have one IS a
    disagreement, and a version of this that skipped blanks would report a
    unanimous family while one of them stood in Goldshire doing nothing.
    """
    groups: dict = {}
    for row in rows:
        value = row.get(field)
        value = blank if value in (None, "") else value
        groups.setdefault(value, []).append(str(row["name"]))
    if len(groups) < 2:
        return None
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))
    return {
        "field": field,
        "groups": [
            {"value": value, "names": sorted(names)} for value, names in ordered
        ],
    }


def job_split(rows: list[dict]) -> dict | None:
    """The job disagreement, computed off the same default the module uses."""
    return split_on([{"name": r["name"], "job": _mode(r)} for r in rows], "job")


def split_sentence(split: dict) -> str:
    """ "3 on quest, 2 on dungeon" - a split rendered for a person.

    The values are printed as they are stored. Every key in jobs.MODES is
    already an English phrase a person says out loud ("gear hunt", "town
    run"), so translating them here would only be a second vocabulary to
    keep in step with the first.
    """
    return ", ".join(
        "%d on %s" % (len(g["names"]), g["value"]) for g in split["groups"]
    )


# --- the dungeon campaign ----------------------------------------------------


def bosses_down(mask: int | None) -> int:
    """How many encounter bits are set in `instance.completedEncounters`."""
    if not mask:
        return 0
    return bin(int(mask)).count("1")


def campaign(rows: list[dict]) -> dict:
    """The dungeon campaign counter, and whether the roster agrees on it.

    THE LEADER'S ROW IS AUTHORITATIVE, which is the module's own rule rather
    than a choice made here: mod_overseer.cpp's LoadCampaignCap reads
    `dungeon_runs_wanted, dungeon_runs_done FROM overseer_roster WHERE name =
    <leader> AND enabled = 1`, and the run number it prints is `done + 1`. The
    migration says why - a per-character cap would be five opinions about one
    party.

    AND THE CROWN MOVES. Leadership is reassigned in world, and the counter
    does NOT travel with it: CountRunDone increments the row of whoever was
    leading when the run closed. Observed live on 2026-09-03 - Grug carried
    done=2 from campaign 1 while Og wore the crown with done=0, so reading the
    leader alone would have told the page the campaign had not started.

    So the leader's number is reported as the one that GOVERNS (because it is
    the one the coordinator will act on), and any higher number elsewhere on
    the roster is reported beside it as a disagreement. Silently taking the max
    would hide a real bug - a campaign that restarts every time the crown moves
    - behind a number that merely looks right.
    """
    leader = _leader(rows)
    if leader is None:
        return {"done": 0, "wanted": 0, "recorded_by": None, "disagrees": None}
    done = int(leader.get("dungeon_runs_done") or 0)
    wanted = int(leader.get("dungeon_runs_wanted") or 0)
    higher = sorted(
        str(r["name"]) for r in rows if int(r.get("dungeon_runs_done") or 0) > done
    )
    return {
        "done": done,
        "wanted": wanted,
        "recorded_by": str(leader["name"]),
        # Names carrying a HIGHER count than the leader's, if any. A lower one
        # is just a row that has never led and says nothing.
        "disagrees": higher or None,
        # The coordinator's own stop condition, so the page can say "done"
        # rather than "0 runs left" (mod_overseer.cpp's IDLE gate is
        # `done >= wanted`, and a wanted of 0 stops the campaign outright).
        "over": bool(wanted == 0 or done >= wanted),
    }


def standing_orders(roster_rows: list[dict]) -> dict:
    """What the roster COLUMNS say the family is set to right now.

    A different question from build_agenda's, and deliberately its own
    function rather than a slice of that payload. The banner answers "what
    are they doing", which is a race between five tables; this answers "what
    is set", which is four columns and the three judgements that read them.
    A surface that offers to change those columns needs the second question
    and would have to re-derive it from the first.

    THE THREE JUDGEMENTS ARE ALREADY MADE IN THIS MODULE and are used here
    rather than copied: which rows count (a disabled row is nobody), who the
    leader is, and what a blank job column means. The job reported is the
    LEADER's, for the same reason campaign() reports the leader's count -
    mod_overseer.cpp looks the leader's name up in LoadJobs() and treats
    absence as the default, and every branch that starts, stands down or
    repeats a dungeon run compares that one string. A family-wide job is
    family-wide by construction (jobs.py), so a disagreement between rows is
    something to REPORT - job_split is right here for that - and never a
    reason to average five opinions into one.
    """
    rows = _enabled(roster_rows)
    leader = _leader(rows)
    return {
        "roster": [str(r["name"]) for r in rows],
        "leader": None if leader is None else str(leader["name"]),
        "job": jobs.DEFAULT if leader is None else _mode(leader),
        "job_split": job_split(rows),
        "campaign": campaign(rows),
        "travel": [
            {"name": str(r["name"]), "target": str(r.get("travel_npc") or "")}
            for r in rows
        ],
    }


def active_run(run_rows: list[dict]) -> dict | None:
    """The run in progress, or None.

    `overseer_dungeon_run` has a unique key on the generated (active, map)
    column, so there is at most one active run per map; taking the newest
    keeps this honest on a realm running two maps at once rather than raising.
    """
    live = [r for r in run_rows if str(r.get("state") or "") == "active"]
    if not live:
        return None
    return max(live, key=lambda r: r.get("started_at") or datetime.min)


def last_ended_run(run_rows: list[dict]) -> dict | None:
    """The most recently closed run, for saying what happened last."""
    ended = [r for r in run_rows if str(r.get("state") or "") == "ended"]
    if not ended:
        return None
    return max(
        ended, key=lambda r: r.get("ended_at") or r.get("started_at") or datetime.min
    )


def instance_for(instance_rows: list[dict], map_id: int) -> dict | None:
    """The lockout the family is bound to on this map, freshest first.

    There can be several rows for one map - an old lockout not yet reset
    beside the current one - so the one with the LATEST reset time is theirs.
    """
    mine = [r for r in instance_rows if int(r.get("map") or -1) == int(map_id)]
    if not mine:
        return None
    return max(mine, key=lambda r: int(r.get("resettime") or 0))


def dungeon_progress(run: dict, instance: dict | None, counter: dict) -> dict:
    """Numbers for a run in progress: which run, and how much of it is left.

    THE BOSS NUMBER IS THE STATE OF THE LOCKOUT, NOT KILLS MADE THIS RUN, and
    it is described that way because that is what the bitmask is.
    `completedEncounters` survives the party leaving and is cleared only when
    the instance resets, so a fresh run into a saved-and-cleared Deadmines
    starts at 7 of 7 with nothing at all left to kill. That is
    `outcome = 'emptied'` in the run table, and it is a thing this page should
    make obvious rather than dress up as a finished dungeon.

    There is no better source. mod_overseer.cpp records the measurement: the
    Deadmines instance script never calls SetBossState, so InstanceScript's
    GetEncounterCount is zero for map 36 and per-boss progress is simply not
    exposed to the module. The bitmask is all there is.
    """
    map_id = int(run.get("map_id") or 0)
    total = ENCOUNTERS.get(map_id)
    down = bosses_down(instance.get("completedEncounters") if instance else None)
    return {
        "map_id": map_id,
        "dungeon": achievements.dungeon_name(map_id),
        "run_number": int(run.get("run_number") or 0) or None,
        "runs_done": counter["done"],
        "runs_wanted": counter["wanted"],
        "bosses_down": down,
        "bosses_total": total,
        # True only where there is a denominator to be sure against.
        "instance_cleared": bool(total and down >= total),
        "started_at": _iso(run.get("started_at")),
    }


def dungeon_headline(progress: dict) -> str:
    """ "Running The Deadmines, run 2 of 30, 4 of 7 bosses down"."""
    parts = [progress["dungeon"]]
    # The number the RUN ROW carries is the one to print when it has one: that
    # is what the row IS, where the roster counter is what has CLOSED. An
    # unstamped run (run_number 0 - one this coordinator did not drive, or one
    # that has not reached Clearing yet) falls back to the campaign counter
    # plus the one under way, which is the same `done + 1` the module prints.
    number = progress["run_number"] or (progress["runs_done"] + 1)
    if progress["runs_wanted"]:
        parts.append("run %d of %d" % (number, progress["runs_wanted"]))
    else:
        parts.append("run %d" % number)
    if progress["bosses_total"]:
        parts.append(
            "%d of %d bosses down" % (progress["bosses_down"], progress["bosses_total"])
        )
    elif progress["bosses_down"]:
        parts.append("%d bosses down" % progress["bosses_down"])
    return "Running " + ", ".join(parts)


# --- errands -----------------------------------------------------------------


def describe_aim(value: str) -> str:
    """How to say an overseer_roster.travel_npc value out loud.

    WHY THIS IS NOT JUST travel.describe. That function resolves through
    travel.ROLES and returns "nowhere" for anything it does not recognise, and
    mod_overseer.cpp's ResolveTravelTarget accepts two forms travel.py has
    never had a vocabulary for, because they are aimed by the module itself
    rather than by a person asking in chat:

        at:<map>:<x>,<y>,<z>    a bare place - a staging point, a quest
                                objective. The walk is the whole errand.
        trigger:<areatrigger>   a doorway. A bot has no client to send
                                CMSG_AREATRIGGER, so it walks to the trigger
                                and is stepped through it explicitly.

    Passing either of those to travel.describe would put the word "nowhere" on
    the banner for a character who is very definitely walking somewhere.
    """
    text = str(value or "").strip()
    if not text:
        return "nowhere"
    if text.startswith("at:"):
        return "a spot in the world"
    if text.startswith("trigger:"):
        return "a doorway"
    return travel.describe(text)


def errand(rows: list[dict], trade_rows: list[dict]) -> dict | None:
    """Who is walking somewhere, where, and what for.

    An aim in `travel_npc` is the one job state that is per-character by
    design (travel.py): the family walks together, so sending one of them to a
    trainer is a deliberate errand and not a split.

    THE COLUMN IS THE STATUS. mod_overseer.cpp keeps no progress field for an
    errand - TravelAimBook::Release clears `travel_npc` on arrival, on giving
    up, and on the run coordinator taking the aim back - so non-empty means in
    progress and empty means not travelling. This reads it exactly that way.

    NOT USED DURING A RUN, and the caller enforces that by deciding the
    dungeon branch first. The coordinator holds travel aims on escorted
    members to park them at a staging point, and those aims deliberately stay
    set while the character stands still; reading one as an errand would
    report "walking Og to a doorway" at every member of a party mid-clear.

    WHETHER IT IS THE FAMILY'S GOAL DEPENDS ON WHO IS WALKING, which is why
    `leads` is reported rather than left for the caller to guess. mod-overseer
    gates the RPG drive to the traveller alone, so when the LEADER walks the
    other four follow him and his errand really is what the family is doing.
    When somebody else walks, it is one character on a side trip while the
    rest carry on questing - and a headline that led with it would answer a
    question about one of the five with a sentence about all of them.
    """
    walking = [r for r in rows if str(r.get("travel_npc") or "").strip()]
    if not walking:
        return None
    # Leader first if the leader is one of them; _enabled already ordered so.
    row = walking[0]
    target = str(row["travel_npc"]).strip()
    skill = _skill_name(int(row.get("learn_skill") or 0))
    reason, decided_at = _why(str(row["name"]), skill, trade_rows)
    return {
        "name": str(row["name"]),
        "leads": bool(int(row.get("lead") or 0)),
        "target": target,
        "target_text": describe_aim(target),
        "skill": skill,
        "reason": shorten(reason),
        "decided_at": _iso(decided_at),
        "_decided_at": decided_at,
        "everyone": sorted(str(r["name"]) for r in walking),
    }


# How much of a council reason the banner will quote. These are written by an
# LLM for Discord and run to a full paragraph - the live one for Og's tailoring
# is 340 characters of ticket numbers - and a banner that is read in half a
# second cannot carry that. Cut on a word boundary so the tail is a sentence
# and not a severed word; the whole reason is still in overseer_trade for
# anyone who wants it.
REASON_CHARS = 160


def shorten(text: str | None, limit: int = REASON_CHARS) -> str | None:
    if text is None:
        return None
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > 0 else limit].rstrip(",;:.") + "..."


def _why(name: str, skill: str | None, trade_rows: list[dict]) -> tuple:
    """(reason, decided_at) for an outstanding errand, or (None, None).

    The council's own words. overseer_trade is where a learn/unlearn decision
    and its reason are recorded, and quoting it is how the banner answers
    "where did this come from" without inventing a second source of truth.

    A trade only explains this errand if it is still `planned` - a settled one
    is a thing that already happened - and, when the roster names a skill, if
    it is about THAT skill. Without the skill test a character with two trades
    on file would have the banner quote whichever row came back first.
    """
    for trade in trade_rows:
        if str(trade.get("character_name")) != name:
            continue
        if str(trade.get("status") or "") != "planned":
            continue
        if skill and str(trade.get("skill_name") or "").lower() != skill:
            continue
        return str(trade.get("reason") or "").strip() or None, trade.get("decided_at")
    return None, None


def _skill_name(skill_id: int) -> str | None:
    """Profession name for a skill id, from goals.py's live-verified table."""
    if not skill_id:
        return None
    for name, value in goals.SKILL_IDS.items():
        if value == skill_id:
            return name
    return None


def errand_headline(err: dict) -> str:
    if err["skill"]:
        return "Walking %s to %s to learn %s" % (
            err["name"],
            err["target_text"],
            err["skill"].title(),
        )
    return "Walking %s to %s" % (err["name"], err["target_text"])


# --- where the order came from -----------------------------------------------


def orders(goal_rows: list[dict], quest_titles: dict, err: dict | None) -> dict | None:
    """Where the current aim CAME FROM, when it came from an instruction.

    Two things can put an order into this world, and both record who asked: a
    Discord goal (overseer_goal, which carries the channel it was set in) and
    a council errand (overseer_trade, which carries its reason). Anything else
    the family is doing, it chose for itself, and saying so is better than
    implying an order nobody gave.

    WHEN BOTH EXIST, THE ONE THE HEADLINE IS ABOUT WINS. The family can be
    under a standing Discord quest order AND have the leader out on a council
    errand at the same time - that is the live state on 2026-09-03, with Grug
    ordered onto The Totem of Infliction while Og walks to a tailoring
    trainer. Reporting the Discord goal there would put "from a Discord order"
    under a headline about a trainer, crediting the sentence on screen to an
    instruction that did not produce it. So a LEADING errand, which is what
    _decide will headline, is preferred; a side errand is not, because then
    the headline really is about the quest.
    """
    if err and err["leads"] and err["reason"]:
        return _errand_order(err)
    live = [g for g in goal_rows if str(g.get("status") or "") == "active"]
    if live:
        newest = max(live, key=lambda g: g.get("created_at") or datetime.min)
        return _discord_order(newest, quest_titles)
    if err and err["reason"]:
        return _errand_order(err)
    return None


def _discord_order(row: dict, quest_titles: dict) -> dict:
    """One overseer_goal row, said the way the bridge says it."""
    quest_id = int(row.get("quest_id") or 0)
    title = quest_titles.get(quest_id)
    # goals.py owns how a goal is said out loud, kind by kind; borrowing it
    # keeps the banner and the Discord acknowledgement using one wording.
    what = title or goals._describe(
        str(row["kind"]), row.get("skill_name"), int(row.get("target") or 0), quest_id
    )
    return {
        "kind": "discord",
        "who": str(row["character_name"]),
        "what": what,
        "channel_id": str(row.get("channel_id") or "") or None,
        "at": _iso(row.get("created_at")),
        "_at": row.get("created_at"),
        "objectives_left": _objectives_left(row),
        "text": "Ordered in Discord: %s is on %s" % (row["character_name"], what),
    }


def _objectives_left(row: dict) -> int | None:
    """How many objectives a quest goal still has, right way up.

    goals.py stores a quest goal's progress as -objectives_left so that every
    kind moves in the same direction and `observed >= target` works for all of
    them. That inversion is an implementation detail of the supervisor; a
    banner printing -15 would be showing the reader the inside of it.
    """
    if str(row.get("kind") or "") != "quest":
        return None
    left = goals._last_progress(row)
    return None if left is None else -left


def _errand_order(err: dict) -> dict:
    return {
        "kind": "errand",
        "who": err["name"],
        "what": err["skill"] or err["target_text"],
        # None, not the empty string: the page shows its Discord badge on the
        # presence of a channel, and an errand was decided by the council in
        # world, not asked for in a channel.
        "channel_id": None,
        "at": err["decided_at"],
        "_at": err["_decided_at"],
        "objectives_left": None,
        "text": err["reason"],
    }


# --- staleness ---------------------------------------------------------------


def last_movement(event_rows: list[dict]) -> datetime | None:
    """The most recent moment the family demonstrably GOT SOMEWHERE.

    THE EVENT FEED, AND DELIBERATELY NOT overseer_dungeon_run.last_progress_at.
    That column is named for progress and does not measure it: mod_overseer.cpp
    touches it for EVERY roster character seen alive on the instance map, on
    every engagement poll, before any other decision - its own comment says it
    "answers 'when was somebody last seen in here'". A party standing still
    inside Deadmines therefore keeps that stamp warm forever, which is exactly
    why quadseven/mod-overseer#171 is invisible from inside the worldserver:
    CloseAbandonedRuns' 120-second timer only ever fires when the map EMPTIES.

    Feeding that column into a stall detector would reproduce the bug in the
    page that exists to reveal it. The event feed is independent of it and is
    written only when something actually happened, so it is the honest signal.

    Deaths are excluded (see MOVEMENT_KINDS): a party wiping in a loop writes
    a row every few minutes forever, and counting those would make this agree
    that a stuck family was busy.
    """
    stamps = [
        row["last_seen"]
        for row in event_rows
        if str(row.get("kind") or "") in MOVEMENT_KINDS
        and row.get("last_seen") is not None
    ]
    return max(stamps) if stamps else None


def stalled(moved_at: datetime | None, now: datetime) -> bool:
    """Whether the family has been quiet longer than a person would wait.

    UNKNOWN IS NOT STALLED. A realm whose worldserver predates overseer_event
    hands in no rows at all, and a page that shouted "stalled" at every such
    world would be crying wolf about a missing table rather than a stuck party.
    """
    if moved_at is None:
        return False
    return (now - moved_at) > STALL_AFTER


# --- the whole banner --------------------------------------------------------


def _span(seconds: int) -> str:
    """A duration in the largest whole unit: "25 minutes", "13 hours"."""
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = seconds // size
            return "%d %s%s" % (count, unit, "" if count == 1 else "s")
    return "%d seconds" % seconds


def stall_line(moved_at: datetime | None, now: datetime) -> str:
    """What STALLED means here, with the real gap in it.

    The banner printed "nothing has happened in over 20 minutes" for a family
    that had been still for thirteen hours, under a headline about somebody
    walking. What is measured is narrower, and is said as such: no quest,
    level or gear change (MOVEMENT_KINDS).
    """
    if moved_at is None:
        return ""
    return "STALLED: no quest, level or gear change for %s." % _span(
        max(0, int((now - moved_at).total_seconds()))
    )


def build_agenda(
    roster_rows: list[dict],
    run_rows: list[dict],
    instance_rows: list[dict],
    goal_rows: list[dict],
    trade_rows: list[dict],
    event_rows: list[dict],
    quest_titles: dict,
    now: datetime | None = None,
    members: list[str] | None = None,
) -> dict:
    """Rows in, the current-goal banner's JSON out.

    roster_rows   overseer_roster, every column this reads
    run_rows      overseer_dungeon_run, in any order
    instance_rows the `instance` rows the family is bound to, via character_instance
    goal_rows     overseer_goal, any status
    trade_rows    overseer_trade, any status
    event_rows    overseer_event, any kind (deaths are filtered here, not in SQL)
    quest_titles  quest id -> LogTitle, from acore_world.quest_template
    now           the clock, injectable so the suite can stand still

    EVERY ONE OF THOSE MAY BE EMPTY. A realm whose worldserver predates a table
    hands in [] for it and gets a thinner sentence, never an exception. The
    adapter's 1146 guard is what turns a missing table into an empty list, and
    this is the half of that contract that has to do something sensible with
    one - the Achievements tab's 503 on production (infra#3172) was the same
    contract broken at the other end.

    `members` is ONE family's roster. The roster, goal, trade and run tables
    hold every family, and reading them whole made one banner out of two
    families: "the rest (Zug, Bork, Grog, ...) hold their quests" put the
    Horde into the Alliance's sentence. Given a family, every row is narrowed
    to it here - by character for the roster, goals and trades, by leader for
    runs - so the SQL stays a plain read. None keeps every row, which is what
    every caller did before there were two families.
    """
    now = now or datetime.now()
    if members is not None:
        ours = set(members)
        roster_rows = [r for r in roster_rows if str(r.get("name")) in ours]
        goal_rows = [r for r in goal_rows if str(r.get("character_name")) in ours]
        trade_rows = [r for r in trade_rows if str(r.get("character_name")) in ours]
        run_rows = [r for r in run_rows if str(r.get("leader_name")) in ours]
    rows = _enabled(roster_rows)
    names = [str(r["name"]) for r in rows]
    counter = campaign(rows)
    run = active_run(run_rows)
    err = errand(rows, trade_rows)
    order = orders(goal_rows, quest_titles, err)
    moved_at = last_movement(event_rows)
    jsplit = job_split(rows)
    qsplit = split_on(rows, "drive_quest", blank=0)
    is_stalled = stalled(moved_at, now)

    activity, headline, detail, changed_at = _decide(
        rows,
        names,
        run,
        run_rows,
        instance_rows,
        counter,
        err,
        jsplit,
        qsplit,
        quest_titles,
        order,
        is_stalled,
    )

    return {
        "generated_at": _iso(now),
        "roster": names,
        "activity": activity,
        "headline": headline,
        "detail": detail,
        # WHEN THIS GOAL LAST CHANGED, which is not the same question as when
        # the family last moved. A goal set forty minutes ago that is still
        # being worked is fine; one set forty minutes ago that has not moved in
        # thirty is the stall. The page shows both, so neither can be mistaken
        # for the other.
        "changed_at": _iso(changed_at),
        "changed_seconds": _seconds(changed_at, now),
        "moved_at": _iso(moved_at),
        "moved_seconds": _seconds(moved_at, now),
        "stalled": is_stalled,
        "stall_after_seconds": int(STALL_AFTER.total_seconds()),
        "stall_line": stall_line(moved_at, now) if is_stalled else "",
        "orders": _public(order),
        "job_split": jsplit,
        "quest_split": qsplit,
        "campaign": counter,
        "leader": counter["recorded_by"],
    }


def _public(order: dict | None) -> dict | None:
    """The order without the private datetime the decision table needed.

    `orders` carries `_at` as a real datetime because _decide compares and
    returns it; the payload carries the ISO string beside it. Stripping the
    underscore keys here rather than never adding them keeps the one place
    that knows the difference next to the one that made it - and json.dumps
    would refuse the datetime anyway, so this cannot rot silently.
    """
    if order is None:
        return None
    return {k: v for k, v in order.items() if not k.startswith("_")}


def _order_at(order: dict | None):
    """When the standing order was given, for the goal's changed-at stamp."""
    return order["_at"] if order else None


def _decide(
    rows,
    names,
    run,
    run_rows,
    instance_rows,
    counter,
    err,
    jsplit,
    qsplit,
    quest_titles,
    order,
    is_stalled,
):
    """(activity, headline, detail lines, when the goal last changed).

    THE ORDER OF THESE BRANCHES IS THE WHOLE DESIGN, so it is written out here
    rather than left to be inferred from the code below:

    1. Nobody enabled       - there is no family to have a goal.
    2. A run in progress    - the most specific, most time-bound thing the
                              family can be doing, and the one with real
                              numbers attached. It outranks everything below
                              because a run actually under way is what is
                              happening whatever the other rows say - and
                              because the coordinator holds travel aims on
                              escorted members, which branch 4 would otherwise
                              misread as five people running errands.
    3. The family is split  - said BEFORE any single activity is claimed.
                              "Four are questing" is not the same answer as
                              "the family is questing", and the difference is
                              what the operator has been catching by eye.
    4. The LEADER on an errand- he is walking somewhere on purpose and the
                              other four follow him, so his errand is the
                              family's. A non-leader's errand is a side trip
                              and appears as a detail line under branch 7
                              instead of taking the headline off four people.
    5. The dungeon job, idle- set to dungeon with no run under way: between
                              runs, or the campaign is over, or it is stuck
                              before the first one.
    6. Another job entirely - honestly, including that most of jobs.MODES is
                              still a name with nothing wired behind it.
    7. Questing             - the ordinary case, named by its quest.
    """
    if not rows:
        return IDLE, "Nobody is being driven right now.", [], None
    if run is not None:
        return _in_a_run(run, instance_rows, counter, names, jsplit, is_stalled)
    if jsplit:
        return _split(jsplit, qsplit, quest_titles)
    if err is not None and err["leads"]:
        return _on_an_errand(err, names)
    mode = _mode(rows[0])
    # Match the dungeon job forms accepted by the run coordinator.
    if jobs.is_dungeon_job(mode):
        return _between_runs(run_rows, counter)
    if mode != jobs.DEFAULT:
        return _another_job(mode)
    return _questing(rows, err, qsplit, quest_titles, order)


def _in_a_run(run, instance_rows, counter, names, jsplit, is_stalled):
    """Branch 2. The most specific thing the family can be doing."""
    instance = instance_for(instance_rows, int(run.get("map_id") or 0))
    progress = dungeon_progress(run, instance, counter)
    detail = [_members_line(run, names)]
    if progress["instance_cleared"]:
        detail.append(
            "The instance they are saved to is already cleared (%d of %d), so "
            "there is nothing left in it until it resets."
            % (progress["bosses_down"], progress["bosses_total"])
        )
    if is_stalled:
        detail.append(
            "Nothing has happened for a while. The run still reads active, but "
            "its heartbeat only proves somebody is standing inside - not that "
            "anything is being killed (quadseven/mod-overseer#171)."
        )
    if counter["disagrees"]:
        detail.append(_counter_disagreement(counter))
    if jsplit:
        detail.append(
            "The roster does not agree on the job: %s." % split_sentence(jsplit)
        )
    return DUNGEON, dungeon_headline(progress), detail, run.get("started_at")


def _split(jsplit, qsplit, quest_titles):
    """Branch 3. Said before any single activity is claimed."""
    detail = [_who_line(jsplit)]
    if qsplit:
        detail.append(
            "Their quest aims differ too: %s." % _quest_split_line(qsplit, quest_titles)
        )
    return (SPLIT, "The family is split: %s." % split_sentence(jsplit), detail, None)


def _on_an_errand(err, names):
    """Branch 4. The LEADER is walking, so the other four follow him."""
    detail = [err["reason"]] if err["reason"] else []
    others = [n for n in err["everyone"] if n != err["name"]]
    if others:
        detail.append("Also walking: %s." % ", ".join(others))
    detail.append(_rest_line(names, err["everyone"]))
    return TRAVEL, errand_headline(err), detail, err["_decided_at"]


def _another_job(mode):
    """Branch 6. A mode that is not quest and not dungeon."""
    detail = [jobs.describe(mode)]
    if mode not in jobs.IMPLEMENTED:
        detail.append(
            "Nothing is wired behind that mode yet, so the quest drive is "
            "stood down and nothing has replaced it."
        )
    return JOB, "The family is set to %s." % mode, detail, None


def _questing(rows, err, qsplit, quest_titles, order):
    """Branch 7. The ordinary case, named by its quest."""
    # A side errand: somebody who is not the leader is walking somewhere while
    # the rest quest on. It is real and worth saying, but it is not what the
    # family is doing, so it goes under the headline rather than in it.
    side = [_side_errand_line(err)] if err is not None and not err["leads"] else []
    aims = {int(r.get("drive_quest") or 0) for r in rows}
    aim = aims.pop() if len(aims) == 1 else 0
    when = _order_at(order)
    if not aim and qsplit:
        return (
            QUEST,
            "Questing, but not on the same quest.",
            [_quest_split_line(qsplit, quest_titles)] + side,
            when,
        )
    if not aim:
        return (
            QUEST,
            "Questing - picking their own quests.",
            ["Nothing is aiming them at a particular quest right now."] + side,
            when,
        )
    title = quest_titles.get(aim) or "quest %d" % aim
    detail = _order_lines(order)
    if qsplit:
        detail.append(
            "Not everyone is on it: %s." % _quest_split_line(qsplit, quest_titles)
        )
    return QUEST, "Questing: " + title, detail + side, when


def _order_lines(order) -> list:
    """What a standing Discord order adds under a quest headline."""
    if order is None or order["kind"] != "discord":
        return []
    lines = [order["text"]]
    left = order["objectives_left"]
    if left is not None:
        lines.append("%d objective%s left on it." % (left, "" if left == 1 else "s"))
    return lines


def _side_errand_line(err: dict) -> str:
    what = (" to learn " + err["skill"].title()) if err["skill"] else ""
    return "Meanwhile %s is walking to %s%s." % (err["name"], err["target_text"], what)


def _between_runs(run_rows: list, counter: dict):
    """Set to dungeon with no run under way.

    Three genuinely different states wear this shape and the page must tell
    them apart, because two of them mean the family is waiting for something
    that is never coming:

      - the campaign is finished (done >= wanted, or wanted is 0, which
        mod_overseer.cpp's IDLE gate treats as "stop outright");
      - a run just ended and the next is about to start;
      - nothing has ever started, which on this module usually means the
        instance reset was refused three times running.
    """
    last = last_ended_run(run_rows)
    where = (
        achievements.dungeon_name(int(last["map_id"]))
        if last and last.get("map_id") is not None
        else None
    )
    if counter["over"]:
        headline = "The dungeon campaign is finished: %d of %d runs done." % (
            counter["done"],
            counter["wanted"],
        )
        detail = [
            "Set the leader's dungeon_runs_done back to 0 to start another campaign."
        ]
    else:
        headline = "Between dungeon runs: %d of %d done." % (
            counter["done"],
            counter["wanted"],
        )
        detail = ["The next run starts with an instance reset."]
    if last is not None:
        detail.append(_last_run_line(last, where))
    if counter["disagrees"]:
        detail.append(_counter_disagreement(counter))
    return DUNGEON, headline, detail, (last.get("ended_at") if last else None)


# --- sentences ---------------------------------------------------------------

# What overseer_dungeon_run.outcome can actually say, in English. Only these
# four are ever written (mod_overseer.cpp writes 'left', 'wipe', 'emptied' and
# 'reset_failed'); 'complete' and 'stalled' are named in the migration as
# deliberately never written, because the module cannot prove either one. An
# empty outcome is a run closed by the cold-heartbeat sweep, which is its own
# sentence rather than a missing one.
OUTCOMES = {
    "left": "the party walked out",
    "wipe": "the party wiped",
    "emptied": "the instance was already empty",
    "reset_failed": "the instance would not reset",
    "": "nobody was seen inside any more",
}


def _last_run_line(run: dict, where: str | None) -> str:
    outcome = str(run.get("outcome") or "")
    said = OUTCOMES.get(outcome, outcome)
    number = int(run.get("run_number") or 0)
    which = "Run %d" % number if number else "The last run"
    return "%s%s ended because %s." % (which, " of " + where if where else "", said)


def _members_line(run: dict, names: list) -> str:
    """Who went in, from the run row, falling back to the leader alone.

    `members` is stamped at the StagedInside -> Clearing transition, so a run
    that has not got that far yet legitimately has none and says so by saying
    less, rather than by claiming the party is empty.
    """
    leader = str(run.get("leader_name") or "") or "nobody"
    members = [m.strip() for m in str(run.get("members") or "").split(",") if m.strip()]
    if not members:
        return "Led by %s; the party is not stamped into the run yet." % leader
    line = "Led by %s, with %s." % (leader, ", ".join(sorted(members)))
    missing = [n for n in names if n not in members]
    if missing:
        line += " Not inside: %s." % ", ".join(sorted(missing))
    return line


def _counter_disagreement(counter: dict) -> str:
    return (
        "The campaign counter disagrees: %s leads with %d done, but %s carries "
        "a higher count. The crown moved and the counter did not."
        % (counter["recorded_by"], counter["done"], ", ".join(counter["disagrees"]))
    )


def _who_line(split: dict) -> str:
    return "; ".join(
        "%s: %s" % (g["value"], ", ".join(g["names"])) for g in split["groups"]
    )


def _quest_split_line(split: dict, quest_titles: dict) -> str:
    parts = []
    for group in split["groups"]:
        quest_id = int(group["value"] or 0)
        what = (
            quest_titles.get(quest_id) or "quest %d" % quest_id
            if quest_id
            else "no aim"
        )
        parts.append("%s on %s" % (", ".join(group["names"]), what))
    return "; ".join(parts)


def _rest_line(names: list, walking: list) -> str:
    rest = [n for n in names if n not in walking]
    if not rest:
        return "Everybody is on the road."
    return "The rest (%s) hold their quests meanwhile." % ", ".join(rest)
