"""GET /api/v2/roster and /api/v2/stuck: every family-guild member, and who is stuck.

WHO. The families on the roster table and every member of the guilds they
are in, as the database reports the guilds. Nothing from the request reaches
the SQL: neither read takes a parameter.

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

import nowstatus
import situation
from panel import _CLASS_NAMES, _RACE_NAMES

from . import activity, presence
from ._scope import guarded, holes

# A class quest ask newer than this means the blocker still stands: the bridge
# asks again every pass it stands, ASK_COOLDOWN_MINUTES (15) apart at the most
# in a quiet guild, so two hours is several asks missed in a row.
ASK_LIVE_SECONDS = 2 * 3600
# Asks for the same quest closer together than this are one run of the same
# blocker; a longer silence starts a new one (the bridge was down, or the
# member did something else in between).
STREAK_GAP_SECONDS = 6 * 3600
# How far back the ask history is read. A run that reaches the edge reports
# the oldest ask it can see, and the basis says so.
ASK_DAYS = 14
# A hold that has stood this long is stuck rather than a pause.
HOLD_STUCK_SECONDS = 30 * 60
# Doings that are not a hold: out of play, or a walk that is still walking.
NOT_HOLDS = frozenset({"Logged out", "Dead", "Fighting", "Idle"})
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
ASKS_SQL = (
    "SELECT asker, target, target_label, state, UNIX_TIMESTAMP(created_at) AS at "
    "FROM overseer_guild_ask WHERE kind = 'quest' AND asker IN ({holes}) "
    "AND created_at > NOW() - INTERVAL %s DAY ORDER BY asker, created_at, id"
)

BASIS = (
    "Stuck means one of two records the bridge keeps: a class quest it has "
    "asked the guild for help with in the last two hours (first seen at the "
    "first ask of that run), or a reason to wait it has logged for 30 minutes "
    "or more (first seen when the reason was first logged). Ghost is a released "
    "spirit, read from the last minute's snapshot or, offline, the last save."
)


# --------------------------------------------------------------------- reads --


def fetch(ctx) -> dict:
    """Every row build() reads, on one connection plus the now-step reads."""
    server = ctx.server
    families = server._fetch_families()
    names = [n for group in families.values() for n in group]
    if not names:
        names = list(server.family.roster())
        families = {names[0]: names} if names else {}
    rows = {
        "guild": [],
        "chars": [],
        "readings": {},
        "snaps": [],
        "asks": [],
        "jobs": [],
        "now_at": 0,
    }
    if names:
        rows = _read(ctx, names)
    everyone = sorted(set(names) | {r["name"] for r in rows["guild"]})
    facts = server._fetch_now_facts(everyone) if everyone else {}
    return dict(rows, families=families, facts=facts or {})


def _read(ctx, names: list) -> dict:
    server = ctx.server
    conn = ctx.connect()
    try:
        with conn.cursor() as cur:
            # S608 below: `holes` is a run of placeholders sized by the roster;
            # every value is bound by the driver.
            guild = guarded(
                ctx,
                cur,
                server._LINEUP_GUILD.format(holes=holes(len(names))),
                tuple(names),
                "guild_member",
            )
            everyone = sorted(set(names) | {r["name"] for r in guild})
            h = holes(len(everyone))
            chars = guarded(
                ctx, cur, CHARS_SQL.format(holes=h), tuple(everyone), "characters"
            )
            readings = presence.of(ctx, cur, everyone)
            online = [n for n in everyone if readings[n]["online"]]
            snaps = []
            if online:
                snaps = guarded(
                    ctx,
                    cur,
                    WHERE_SQL.format(holes=holes(len(online))),
                    tuple(online),
                    "overseer_snapshot",
                )
            asks = guarded(
                ctx,
                cur,
                ASKS_SQL.format(holes=h),
                (*everyone, ASK_DAYS),
                "overseer_guild_ask",
            )
            jobs = guarded(
                ctx,
                cur,
                JOBS_SQL.format(holes=h),
                (*everyone, JOB_MINUTES),
                "overseer_command",
            )
            cur.execute("SELECT UNIX_TIMESTAMP() AS now_at")
            row = cur.fetchone()
            now_at = int(row["now_at"]) if row else 0
    finally:
        conn.close()
    return {
        "guild": guild,
        "chars": chars,
        "readings": readings,
        "snaps": snaps,
        "asks": asks,
        "jobs": jobs,
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


def ask_blocker(run: list, now_at: int) -> dict | None:
    """The stuck entry for a run of class quest asks, or None when it is over."""
    if not run or now_at - int(run[-1].get("at") or 0) > ASK_LIVE_SECONDS:
        return None
    title = run[-1].get("target_label") or "a class quest"
    ran = sum(1 for r in run if r.get("state") == "ran")
    asked = "asked the guild for help %d time%s" % (
        len(run),
        "" if len(run) == 1 else "s",
    )
    if ran:
        tail = ", a party went %d time%s and it is still not done" % (
            ran,
            "" if ran == 1 else "s",
        )
    else:
        tail = ", and nobody has come"
    return {
        "step": "Class quest: " + title,
        "blocker": "Cannot finish %s alone: %s%s." % (title, asked, tail),
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
    return {
        "step": doing,
        "blocker": "Waiting for " + waiting + ".",
        "since": (now_at - int(held)) if held is not None and now_at else None,
        "kind": "hold",
    }


# -------------------------------------------------------------------- build --


def _presence(reading: dict, snap: dict | None) -> dict:
    """What nowstatus.compose reads about a character's presence."""
    return {
        "present": reading["online"],
        "condition": "dead" if reading["life"] == "dead" else "ok",
        "combat": bool(snap and snap.get("in_combat")),
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


def _identity(name: str, row: dict, char: dict, family_of: dict) -> dict:
    family, lead = family_of.get(name, ("", False))
    return {
        "name": name,
        "guild": row.get("guild_name") or "",
        "family": family,
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
    m.update(blocker=found["blocker"], since=found["since"], stuck_kind=found["kind"])
    return m


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
    families, guild, chars, snaps, asks, facts, now_at, jobs=(), readings=None
) -> dict:
    """The roster: one row per member, family first, with its stuck reading.

    `readings` is presence.of's answer for every member; `snaps` is where the
    online ones stand."""
    families = families or {}
    rows = _lookups(families, chars, snaps, facts, now_at, jobs, readings)
    guild_of = {r["name"]: r for r in guild or ()}
    streaks = ask_streaks(asks)
    members = []
    for name in _order(families, guild_of):
        if name not in rows["chars"] and name not in guild_of:
            continue
        m = _member(name, guild_of.get(name, {}), rows)
        found = _stuck_entry(m, streaks.get(name, []), rows["now_at"])
        members.append(_with_stuck(m, found))
    return {
        "members": members,
        "families": {k: list(v) for k, v in families.items()},
        "checked_at": rows["now_at"] or None,
        "basis": BASIS,
    }


def stuck_view(roster: dict) -> dict:
    """The /api/v2/stuck shape: the stuck members only, longest first."""
    stuck = [m for m in roster["members"] if m["stuck"]]
    stuck.sort(key=lambda m: (m["since"] is None, m["since"] or 0, m["name"]))
    return {
        "members": [
            {
                "name": m["name"],
                "step": m["step"],
                "blocker": m["blocker"],
                "since": m["since"],
                "kind": m["stuck_kind"],
            }
            for m in stuck
        ],
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
    )


def roster(_query: dict, ctx) -> tuple[int, dict]:
    return 200, _roster_payload(ctx)


def stuck(_query: dict, ctx) -> tuple[int, dict]:
    return 200, stuck_view(_roster_payload(ctx))


ROUTES = {"/api/v2/roster": roster, "/api/v2/stuck": stuck}
