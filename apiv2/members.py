"""GET /api/v2/roster and /api/v2/stuck: every family-guild member, and who is stuck.

WHO. The families on the roster table and every member of the guilds they
are in, as the database reports the guilds. Nothing from the request reaches
the SQL: neither read takes a parameter. A guild's questers (raidteams.QUESTERS)
carry `group` "quester"; every other member an empty one.

WHAT EACH MEMBER IS DOING is nowstatus.compose's sentence, the same one the
Watch wall prints under a stream: the module's intent book, the steps the
bridge stored from its own log (overseer_now_step), and the roster's job.

WHO IS STUCK, AND SINCE WHEN. Two records, both the bridge's own, read and
never written here:

  a class quest it cannot do alone   classquest names the blocker and, once
                                     every class quest of a member waits on
                                     help, classask asks the guild for it
                                     (overseer_guild_ask, kind 'quest'). The
                                     ask is repeated every pass the blocker
                                     stands. A member whose latest ask is
                                     under ASK_LIVE_SECONDS old is stuck, and
                                     the first ask of that unbroken run (no
                                     gap over STREAK_GAP_SECONDS, the same
                                     quest) is the first-seen time.
  a hold that does not lift          a stored step with a reason to wait (bag
                                     room, a vendor, the queue) that has stood
                                     for HOLD_STUCK_SECONDS or more. Its
                                     first-seen time is the step's own.

A MEMBER THAT ONLY FOLLOWS has neither record of its own. Near its leader it
is stuck when the leader is, since the leader's hold began, and its blocker
names that hold (`follows` is the leader); far behind or on another map it is
stuck on being left there (follower_blocker).

`since` is None when the blocker is known but nothing recorded when it began;
the page says "since not measured" and never guesses.

ONLINE AND GHOSTS are presence.of's reading, the same one the Guild page and
the gear table serve: online is a snapshot written in the last minute, and
`life` is "alive", "dead" (a corpse), "ghost" (a released spirit) or None (an
offline member the save says nothing about). Where a member stands and whether
it is fighting come from that snapshot, read only for the members it reads as
online.
"""

from __future__ import annotations

import re

import agenda
import nowstatus
import raidteams
import situation
from panel import _CLASS_NAMES, _RACE_NAMES

from . import activity, presence
from ._scope import holes

# A class quest ask newer than this means the blocker still stands: the bridge
# asks again every pass it stands, ASK_COOLDOWN_MINUTES (15) apart at the most
# in a quiet guild, so two hours is several asks missed in a row.
ASK_LIVE_SECONDS = 2 * 3600
# Asks for the same quest closer together than this are one run of the same
# blocker; a longer silence starts a new one (the bridge was down, or the
# member did something else in between).
STREAK_GAP_SECONDS = 6 * 3600
# An ask whose party a step stopped before it formed keeps that step in its
# reason column after this (the bridge's classask.STOPPED, #1001).
STOPPED = "stopped: "
# How far back the ask history is read. A run that reaches the edge reports
# the oldest ask it can see, and the basis says so.
ASK_DAYS = 14
# A hold that has stood this long is stuck rather than a pause.
HOLD_STUCK_SECONDS = 30 * 60
# Doings that are not a hold: out of play, or a walk that is still walking.
NOT_HOLDS = frozenset(
    {"Logged out", "Dead", "Fighting", "Idle", "Buying a bank bag slot"}
)
WALKING = "to get there"
CHARS_SQL = (
    "SELECT name, race, gender, class AS class_id, level, zone, map "
    "FROM characters WHERE name IN ({holes})"
)
# Where the members presence.of reads as online stand. Freshness is that
# reading's rule, so this read does not restate it.
WHERE_SQL = (
    "SELECT name, zone_id, map_id, in_combat FROM overseer_snapshot "
    "WHERE name IN ({holes})"
)
# The newest guild job each member was given, for a member whose step the
# now-step feed cannot name: guildjobs writes its rows with the source
# "guildjobs:<job>:<name>", and the row's status is the realm's answer.
JOBS_SQL = (
    "SELECT target_name AS name, source, command, status, detail, "
    "LEFT(result, 600) AS result, "
    "UNIX_TIMESTAMP(created_at) AS at FROM overseer_command "
    "WHERE target_name IN ({holes}) AND source LIKE 'guildjobs:%%' "
    "AND created_at > NOW() - INTERVAL %s MINUTE ORDER BY id DESC"
)
JOB_MINUTES = 30
# When each family member last made progress: the Now page's STALLED reading
# (agenda.MOVEMENT_KINDS, a quest, level or gear change; deaths are not).
MOVED_SQL = (
    "SELECT character_name AS name, UNIX_TIMESTAMP(MAX(last_seen)) AS at "
    "FROM overseer_event WHERE character_name IN ({holes}) "
    "AND kind IN ({kinds}) GROUP BY character_name"
)
ASKS_SQL = (
    "SELECT asker, target, target_label, reason, state, UNIX_TIMESTAMP(created_at) AS at, "
    "(SELECT COUNT(*) FROM overseer_guild_answer an "
    "WHERE an.ask_id = overseer_guild_ask.id) AS yeses "
    "FROM overseer_guild_ask WHERE kind = 'quest' AND asker IN ({holes}) "
    "AND created_at > NOW() - INTERVAL %s DAY ORDER BY asker, created_at, id"
)

BASIS = (
    "Stuck means one of two records the bridge keeps: a class quest it has "
    "asked the guild for help with in the last two hours (first seen at the "
    "first ask of that run), or a reason to wait it has logged for 30 minutes "
    "or more (first seen when the reason was first logged). A family's leader "
    "is also stuck when the family is STALLED on the Now page (no quest, level "
    "or gear change for 20 minutes; first seen when it last made one), named by "
    "what the leader is doing and waiting for. A member that only "
    "follows is stuck when its leader is (first seen when the leader's reason "
    "was) or when it is left far behind. Ghost is a released "
    "spirit, read from the last minute's snapshot or, offline, the last save."
)


# --------------------------------------------------------------------- reads --


def fetch(ctx) -> dict:
    """Every row build() reads, on one connection plus the now-step reads."""
    server = ctx.server
    families = server.FAMILIES.families()
    names = server.FAMILIES.names()
    rows = {
        "guild": [],
        "chars": [],
        "readings": {},
        "snaps": [],
        "asks": [],
        "jobs": [],
        "moved": {},
        "now_at": 0,
    }
    if names:
        rows = _read(ctx, names)
    everyone = sorted(set(names) | {r["name"] for r in rows["guild"]})
    facts = server._fetch_now_facts(everyone) if everyone else {}
    return dict(rows, families=families, facts=facts or {})


def _read(ctx, names: list) -> dict:
    server = ctx.server
    rd = ctx.read
    # S608 below: `holes` is a run of placeholders sized by the roster;
    # every value is bound by the driver.
    guild = rd.rows(
        server._LINEUP_GUILD.format(holes=holes(len(names))),
        tuple(names),
        what="guild_member",
    )
    everyone = sorted(set(names) | {r["name"] for r in guild})
    h = holes(len(everyone))
    chars = rd.rows(CHARS_SQL.format(holes=h), tuple(everyone), what="characters")
    readings = presence.of(rd, everyone)
    online = [n for n in everyone if readings[n]["online"]]
    snaps = []
    if online:
        snaps = rd.rows(
            WHERE_SQL.format(holes=holes(len(online))),
            tuple(online),
            what="overseer_snapshot",
        )
    asks = rd.rows(
        ASKS_SQL.format(holes=h),
        (*everyone, ASK_DAYS),
        what="overseer_guild_ask",
    )
    jobs = rd.rows(
        JOBS_SQL.format(holes=h),
        (*everyone, JOB_MINUTES),
        what="overseer_command",
    )
    kinds = sorted(agenda.MOVEMENT_KINDS)
    moved = rd.rows(
        MOVED_SQL.format(holes=holes(len(names)), kinds=holes(len(kinds))),
        (*names, *kinds),
        what="overseer_event",
    )
    clock = rd.must("SELECT UNIX_TIMESTAMP() AS now_at")
    now_at = int(clock[0]["now_at"]) if clock else 0
    return {
        "guild": guild,
        "chars": chars,
        "readings": readings,
        "snaps": snaps,
        "asks": asks,
        "jobs": jobs,
        "moved": {r["name"]: int(r["at"]) for r in moved or () if r.get("at")},
        "now_at": now_at,
    }


# --------------------------------------------------------------------- words --


def place_words(name: str) -> str:
    """'SwampOfSorrows' -> 'Swamp of Sorrows': the client's zone keys in words."""
    words = re.findall(r"[A-Z][a-z']*|[a-z']+|\d+", name or "") or [name or ""]
    small = {"Of", "The", "And"}
    out = [w.lower() if i and w in small else w for i, w in enumerate(words)]
    return " ".join(out).strip()


def _first(row: dict, *keys):
    """The first of `keys` with a value: a present None does not count."""
    return next((row[k] for k in keys if row.get(k) is not None), None)


def zone_of(snap: dict | None, char: dict | None) -> str:
    """Where a member stands: the fresh snapshot's zone, else the last save's."""
    row = snap or char or {}
    zone = _first(row, "zone_id", "zone")
    map_id = _first(row, "map_id", "map")
    if zone is None and map_id is None:
        return ""
    name = situation.zone_name(int(zone or 0), None if map_id is None else int(map_id))
    return place_words(name)


def job_step(row: dict | None) -> str:
    """'guildjobs:classquest-walk:Chopp' -> 'Guild job: classquest walk'."""
    if not row:
        return ""
    parts = str(row.get("source") or "").split(":")
    job = (
        parts[1].replace("-", " ").replace("classquest", "class quest")
        if len(parts) > 2
        else ""
    )
    return "Guild job: " + job if job else ""


def job_answer(row: dict | None) -> str:
    """The realm's answer to that job: its status, and why when it refused."""
    if not row:
        return ""
    return activity.answer_words(
        row.get("status"), row.get("detail"), row.get("result")
    )


# -------------------------------------------------------------------- stuck --


def ask_streaks(asks: list) -> dict:
    """asker -> the newest run of asks for one quest, oldest first."""
    by: dict = {}
    for row in asks or ():
        by.setdefault(str(row.get("asker")), []).append(row)
    out = {}
    for asker, rows in by.items():
        rows = sorted(rows, key=lambda r: int(r.get("at") or 0))
        run = [rows[-1]]
        for row in reversed(rows[:-1]):
            gap = int(run[0].get("at") or 0) - int(row.get("at") or 0)
            if row.get("target") != run[0].get("target") or gap > STREAK_GAP_SECONDS:
                break
            run.insert(0, row)
        out[asker] = run
    return out


def _ask_blocker_tail(run: list) -> str:
    """The latest reason a class quest ask remains stuck."""
    ran = sum(1 for r in run if r.get("state") == "ran")
    latest_failure = next(
        (
            str(r.get("reason") or "")[8:]
            for r in reversed(run)
            if r.get("state") == "ran"
            and str(r.get("reason") or "").startswith("failed: ")
        ),
        "",
    )
    if latest_failure:
        return ", the last party %s" % latest_failure
    elif ran:
        return ", a party went %d time%s and it is still not done" % (
            ran,
            "" if ran == 1 else "s",
        )
    yeses = sum(int(r.get("yeses") or 0) for r in run)
    stopped = _latest_reason(run, STOPPED)
    if stopped:
        return ", %d said yes, the party stopped: %s" % (yeses, stopped)
    return ", %d said yes, no party formed" % yeses


def _latest_reason(run: list, prefix: str) -> str:
    """The newest reason in the run that starts with `prefix`, without it."""
    return next(
        (
            str(r.get("reason") or "")[len(prefix) :]
            for r in reversed(run)
            if str(r.get("reason") or "").startswith(prefix)
        ),
        "",
    )


def ask_blocker(run: list, now_at: int) -> dict | None:
    """The stuck entry for a run of class quest asks, or None when it is over."""
    if not run or now_at - int(run[-1].get("at") or 0) > ASK_LIVE_SECONDS:
        return None
    title = run[-1].get("target_label") or "a class quest"
    asked = "asked the guild for help %d time%s" % (
        len(run),
        "" if len(run) == 1 else "s",
    )
    return {
        "step": "Class quest: " + title,
        "blocker": "Cannot finish %s alone: %s%s."
        % (
            title,
            asked,
            _ask_blocker_tail(run),
        ),
        "since": int(run[0].get("at") or 0) or None,
        "kind": "class quest",
    }


def hold_blocker(now: dict, now_at: int) -> dict | None:
    """The stuck entry for a hold that has stood HOLD_STUCK_SECONDS, or None."""
    doing, waiting = now.get("doing") or "", now.get("waiting") or ""
    if doing in NOT_HOLDS or not waiting or waiting == WALKING:
        return None
    held = now.get("for_s")
    if held is not None and held < HOLD_STUCK_SECONDS:
        return None
    kind = "walk restarts" if nowstatus.RESTART_WAITING in waiting else "hold"
    return {
        "step": doing,
        "blocker": "Waiting for " + waiting + ".",
        "since": (now_at - int(held)) if held is not None and now_at else None,
        "kind": kind,
    }


# A follower this close to its leader stands with him, so whatever holds the
# leader holds it too (vendor_stall.FAMILY_COHESION_YARDS, the yards the
# bridge's vendor trip reads as a family that follows).
FOLLOW_NEAR_YARDS = 100


def follower_blocker(leader: str, yards: str, lead: dict | None) -> dict | None:
    """The stuck entry for a member the module reads as following `leader`.

    A plain follower has no clock and no hold of its own (#1059): read alone,
    "Following Zug (0 yards behind)" with "Waiting for Zug to move on" was
    stuck the moment it was read, since not measured, beside a leader the list
    did not name. So a follower near its leader is stuck exactly when the
    leader is, since the leader's hold began, and its blocker names that hold
    (`lead`, the leader's own stuck entry). A follower far behind, on another
    map, or with its leader out of the world is not following in fact: it stays
    stuck on that, since not measured, with the leader's hold named when he has
    one.
    """
    near = yards.isdigit() and int(yards) <= FOLLOW_NEAR_YARDS
    if near and lead is None:
        return None
    if near:
        own = "Waiting for %s to move on." % leader
    elif yards.isdigit():
        own = "Left %s yards behind %s, read as following, not walking back." % (
            yards,
            leader,
        )
    elif yards == "another map":
        own = "On another map than %s, read as following, not walking back." % leader
    else:
        own = "Waiting for %s, who is not in the world." % leader
    if lead is not None:
        own += " %s's own hold: %s" % (leader, lead["blocker"])
    return {
        "step": "",
        "blocker": own,
        "since": lead["since"] if near else None,
        "kind": lead["kind"] if near else "hold",
        "follows": leader,
    }


def _asking(entry: dict | None) -> bool:
    """A class quest ask is the member's own blocker, follower or not."""
    return entry is not None and entry["kind"] == "class quest"


def _resolve_followers(members: list, found: dict, follows: dict) -> None:
    """Each plain follower's stuck entry from its leader's (follower_blocker)."""
    for m in members:
        if m["name"] not in follows:
            continue
        leader, yards = follows[m["name"]]
        entry = follower_blocker(leader, yards, found.get(leader))
        if entry is not None:
            entry["step"] = m["doing"]
        found[m["name"]] = entry


# -------------------------------------------------------------------- build --


def _presence(reading: dict, snap: dict | None) -> dict:
    """What nowstatus.compose reads about a character's presence."""
    life = reading["life"]
    return {
        "present": reading["online"],
        "condition": "dead" if life in ("dead", "ghost") else "ok",
        "combat": bool(snap and snap.get("in_combat")),
        "life": life,
    }


def _family_of(families: dict) -> dict:
    out = {}
    for key, names in (families or {}).items():
        for i, n in enumerate(names):
            out[n] = (key, i == 0)
    return out


def _either(char: dict, row: dict, key: str) -> int:
    """A number from the character's own row, else from the guild row."""
    return int(char.get(key) or row.get(key) or 0)


def group_of(name: str, guild: str) -> str:
    """'quester' for a guild's quester (raidteams.QUESTERS), else ''."""
    return "quester" if guild and name in raidteams.quester_names(guild) else ""


def _identity(name: str, row: dict, char: dict, family_of: dict) -> dict:
    family, lead = family_of.get(name, ("", False))
    guild = row.get("guild_name") or ""
    return {
        "name": name,
        "guild": guild,
        "family": family,
        "group": group_of(name, guild),
        "lead": lead,
        "level": _either(char, row, "level"),
        "class": _CLASS_NAMES.get(_either(char, row, "class_id"), ""),
        "race": _RACE_NAMES.get(_either(char, row, "race"), ""),
        "gender": "female" if char.get("gender") else "male",
    }


def _doing(now: dict, job: dict | None) -> dict:
    return {
        "doing": now.get("doing") or "",
        "waiting": now.get("waiting") or "",
        "for_s": now.get("for_s"),
        "line": now.get("line") or "",
        "job": job_step(job),
        "job_answer": job_answer(job),
        "job_at": int(job["at"]) if job and job.get("at") else None,
    }


# A member presence.of was not asked about: nothing is known.
UNREAD = {"online": False, "life": None, "fresh_at": None}


def _member(name, row, ctx_rows) -> dict:
    char = ctx_rows["chars"].get(name) or {}
    reading = ctx_rows["readings"].get(name) or UNREAD
    snap = ctx_rows["snaps"].get(name) if reading["online"] else None
    now = nowstatus.compose(
        _presence(reading, snap),
        ctx_rows["facts"].get(name),
        ctx_rows["now_at"] or None,
    )
    out = _identity(name, row, char, ctx_rows["family"])
    out.update(zone=zone_of(snap, char), online=reading["online"], life=reading["life"])
    out.update(_doing(now, ctx_rows["jobs"].get(name)))
    return out


def _stuck_entry(member: dict, run: list, now_at: int) -> dict | None:
    if member["life"] in ("dead", "ghost"):
        return None
    return ask_blocker(run, now_at) or hold_blocker(member, now_at)


def _newest(rows) -> dict:
    """name -> the first row seen for it (the reads are newest first)."""
    out: dict = {}
    for r in rows or ():
        out.setdefault(r["name"], r)
    return out


def _step_of(m: dict, found: dict | None) -> str:
    if found:
        return found["step"]
    if m["doing"] in ("", "Idle") and m["job"]:
        return m["job"]
    return m["doing"]


def _with_stuck(m: dict, found: dict | None) -> dict:
    """The member with its stuck reading: the blocker, or none."""
    m["stuck"] = found is not None
    m["step"] = _step_of(m, found)
    found = found or {"blocker": "", "since": None, "kind": ""}
    m.update(
        blocker=found["blocker"],
        since=found["since"],
        stuck_kind=found["kind"],
        follows=found.get("follows", ""),
    )
    return m


def stall_entry(leader: dict, moved_at: int | None, now_at: int) -> dict | None:
    """The stuck entry for a family that is STALLED (agenda.stalled: no quest,
    level or gear change for agenda.STALL_AFTER), on its leader, or None.

    The Now page called Grug's family STALLED while its realm report said "No
    current blocker recorded": a stall was not a stuck record, and a hold had
    to stand 30 minutes before it was one. So the stall is its own record,
    since the family last moved, named by the leader's own reading
    (agenda.stall_blocker), the same sentence the agenda's STALLED line ends
    with. A dead or released leader is not stuck, as for every other record.
    """
    if not moved_at or not now_at or leader["life"] in ("dead", "ghost"):
        return None
    still = now_at - int(moved_at)
    if still <= agenda.STALL_AFTER.total_seconds():
        return None
    return {
        "step": leader["doing"],
        "blocker": "No quest, level or gear change for the family for %s. %s"
        % (agenda.span(still), agenda.stall_blocker(leader["name"], leader)),
        "since": int(moved_at),
        "kind": "stall",
    }


def _stalled_leaders(families, members, found, moved: dict, now_at: int) -> None:
    """A stalled family's leader is stuck on the stall, unless a record of
    its own already holds it (a class quest ask or a long hold)."""
    by_name = {m["name"]: m for m in members}
    for names in (families or {}).values():
        leader = by_name.get(names[0]) if names else None
        if leader is None or found.get(leader["name"]) is not None:
            continue
        moved_at = max((moved.get(n) or 0 for n in names), default=0)
        found[leader["name"]] = stall_entry(leader, moved_at or None, now_at)


def _order(families: dict, guild_of: dict) -> list:
    """The families first, lead first, then the guilds by name."""
    names = [n for group in families.values() for n in group]
    return names + sorted(n for n in guild_of if n not in names)


def _lookups(families, chars, snaps, facts, now_at, jobs, readings) -> dict:
    """The rows build() reads, keyed by name."""
    return {
        "jobs": _newest(jobs),
        "chars": {r["name"]: r for r in chars or ()},
        "readings": readings or {},
        "snaps": {r["name"]: r for r in snaps or ()},
        "family": _family_of(families),
        "facts": facts or {},
        "now_at": int(now_at or 0),
    }


def build(
    families,
    guild,
    chars,
    snaps,
    asks,
    facts,
    now_at,
    jobs=(),
    readings=None,
    moved=None,
) -> dict:
    """The roster: one row per member, family first, with its stuck reading.

    `readings` is presence.of's answer for every member; `snaps` is where the
    online ones stand; `moved` is name -> when it last made progress (Unix
    seconds), for a stalled family (stall_entry)."""
    families = families or {}
    rows = _lookups(families, chars, snaps, facts, now_at, jobs, readings)
    guild_of = {r["name"]: r for r in guild or ()}
    streaks = ask_streaks(asks)
    members, found, follows = [], {}, {}
    for name in _order(families, guild_of):
        if name not in rows["chars"] and name not in guild_of:
            continue
        m = _member(name, guild_of.get(name, {}), rows)
        found[name] = _stuck_entry(m, streaks.get(name, []), rows["now_at"])
        followed = nowstatus.followed(rows["facts"].get(name), m)
        if followed and not _asking(found[name]):
            follows[name] = followed
        members.append(m)
    _stalled_leaders(families, members, found, moved or {}, rows["now_at"])
    # Leaders first: a follower's reading is its leader's (follower_blocker).
    _resolve_followers(members, found, follows)
    members = [_with_stuck(m, found[m["name"]]) for m in members]
    return {
        "members": members,
        "families": {k: list(v) for k, v in families.items()},
        "checked_at": rows["now_at"] or None,
        "basis": BASIS,
    }


# Nobody stays stuck longer than this (#868): the digest counts who is past
# it, so a tick reads the breach without doing the sum.
STUCK_BOUND_SECONDS = 2 * 3600
# A follower's blocker ends with its leader's: the leader's hold is the cause.
LEADER_HOLD = "'s own hold: "
_DIGITS = re.compile(r"\d+")


def stuck_cause(row: dict) -> str:
    """What a stuck row is held by, as one group of the digest.

    A class quest is one cause, whatever the quest. A hold is its blocker (the
    leader's own hold, for a follower) with every number made "#", so a retry
    time, a yard count or an ask count does not split one cause in two."""
    if row["kind"] == "class quest":
        return "class quest"
    blocker = row["blocker"]
    if LEADER_HOLD in blocker:
        blocker = blocker.split(LEADER_HOLD, 1)[1]
    return "%s: %s" % (row["kind"], _DIGITS.sub("#", blocker))


def _waited(row: dict, checked_at: int | None) -> int | None:
    """Seconds a row has been stuck at `checked_at`, None when not measured."""
    if row["since"] is None or not checked_at:
        return None
    return max(0, int(checked_at) - int(row["since"]))


def stuck_digest(rows: list, checked_at: int | None) -> dict:
    """The stuck list in the numbers a tick journals (#868): how many are
    stuck, who has waited longest, how many are past STUCK_BOUND_SECONDS, and
    the causes (stuck_cause) ranked by member-hours lost, the biggest first.

    `rows` are the /api/v2/stuck members. A row whose start was not measured
    is counted as stuck but adds no hours; `unmeasured` says how many."""
    groups: dict = {}
    longest = None
    total = over = unmeasured = 0
    for row in rows:
        waited = _waited(row, checked_at)
        group = groups.setdefault(
            stuck_cause(row), {"members": [], "seconds": 0, "longest_s": None}
        )
        group["members"].append(row["name"])
        if waited is None:
            unmeasured += 1
            continue
        total += waited
        over += waited > STUCK_BOUND_SECONDS
        group["seconds"] += waited
        group["longest_s"] = max(group["longest_s"] or 0, waited)
        if longest is None or waited > longest["seconds"]:
            longest = {"name": row["name"], "seconds": waited}
    causes = [
        {
            "cause": cause,
            "members": group["members"],
            "member_hours": round(group["seconds"] / 3600, 2),
            "longest_s": group["longest_s"],
        }
        for cause, group in groups.items()
    ]
    causes.sort(key=lambda c: (-c["member_hours"], -len(c["members"]), c["cause"]))
    return {
        "count": len(rows),
        "longest": longest,
        "member_hours": round(total / 3600, 2),
        "bound_s": STUCK_BOUND_SECONDS,
        "over_bound": over,
        "unmeasured": unmeasured,
        "causes": causes,
    }


def stuck_view(roster: dict) -> dict:
    """The /api/v2/stuck shape: the stuck members only, longest first, and
    their digest (stuck_digest)."""
    stuck = [m for m in roster["members"] if m["stuck"]]
    stuck.sort(key=lambda m: (m["since"] is None, m["since"] or 0, m["name"]))
    rows = [
        {
            "name": m["name"],
            "step": m["step"],
            "blocker": m["blocker"],
            "since": m["since"],
            "kind": m["stuck_kind"],
            "follows": m["follows"],
        }
        for m in stuck
    ]
    return {
        "members": rows,
        "digest": stuck_digest(rows, roster["checked_at"]),
        "checked_at": roster["checked_at"],
        "basis": roster["basis"],
    }


# ------------------------------------------------------------------ handlers --


def _roster_payload(ctx) -> dict:
    # /api/v2/roster and /api/v2/stuck are the same build, and a cold page
    # load asks for both at once (the view and the nav badge): one build
    # serves both when the server shares its reads.
    shared = getattr(ctx, "shared", None)
    if shared is not None:
        return shared.get("/api/v2/roster", lambda: _build_roster(ctx))
    return _build_roster(ctx)


def _build_roster(ctx) -> dict:
    f = fetch(ctx)
    return build(
        f["families"],
        f["guild"],
        f["chars"],
        f["snaps"],
        f["asks"],
        f["facts"],
        f["now_at"],
        f["jobs"],
        f["readings"],
        f.get("moved"),
    )


def roster(_query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/roster: every family-guild member, what each is doing, and who is stuck."""
    return 200, _roster_payload(ctx)


def stuck(_query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/stuck: the stuck members only, longest stuck first, and their digest."""
    return 200, stuck_view(_roster_payload(ctx))


ROUTES = {"/api/v2/roster": roster, "/api/v2/stuck": stuck}
