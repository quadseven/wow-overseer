"""IO shell for the wow-overseer bridge.

Everything here is adapters: Discord in, MySQL in/out, Discord out. All
decisions live in core.py, which this module treats as a black box. Keep it
that way - logic added here escapes the test seam (infra#2597).

Blocking MySQL calls are pushed off the event loop with asyncio.to_thread;
nothing in this file may call the database directly from an async handler.
"""
# Spark-authored: qwen3-coder-next:q8_0 on an on-prem DGX Spark, 2026-09-02; reviewed by
# hand the same day: the give-up window was the retry window, so it could never fire,
# and it counted transient refusals; then a rolling-window threshold, which Codex
# showed only pauses the loop. The decision is now questshare.backed_off().
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import urllib.request

import discord
import pymysql

import achievements
import armory
import bag_pressure
import bag_upgrade
import bank
import chat
import council
import core
import craftpleas
import digest
import disposition
import events
import fanout
import goals
import bonds
import item_plan
import jobs
import kin
import materials
import overhear
import persona
import professions
import protect
import questbook
import questshare
import quests
import relay
import towntrip
import trainjob
import voice
from transform import Geometry

log = logging.getLogger("wow-overseer")

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))
# The overseer's own channel: unaddressed messages there get answered
# (roster / help) instead of the shared-channel silence rule.
OVERSEER_CHANNEL_ID = os.environ.get("OVERSEER_CHANNEL_ID", "")
# Where world chat is relayed to. Falls back to the overseer's own channel.
CHAT_CHANNEL_ID = os.environ.get("CHAT_CHANNEL_ID", "")

# THE CHANNELS THIS BRIDGE IS ALLOWED TO ACT IN, AND WHY THAT IS NOW A RULE
# RATHER THAN A HINT.
#
# on_message used to parse EVERY message in EVERY channel the bot could see,
# using the overseer channel only to decide whether an UNaddressed message
# also deserved an answer. That was harmless while one world existed. It stops
# being harmless the moment a second bridge shares the token: parse_directive
# acts on any line starting with `@` from an allowed user, in any channel, so
# "@Grug .additem" typed in a DEV channel would be seen by the dev bridge AND
# the production one, and production would run it on the live Grug. That is
# the double-delivery failure 70-overseer.yaml warns about, reached through
# channels rather than through two tokens.
#
# So a bridge now ignores, completely, any channel it was not given. The two
# worlds are separated by which channels they were told about, which is a fact
# each process holds about itself rather than a convention both must honour.
#
# EMPTY MEANS EVERYWHERE, deliberately preserved. A single-world install that
# names no channel has always listened everywhere, and silently going deaf
# would be a far worse failure than the one this prevents - the bridge would
# look healthy and answer nobody. Isolation is what you get by CONFIGURING a
# channel, which every multi-world deployment does.
OWNED_CHANNEL_IDS = frozenset(
    cid for cid in (OVERSEER_CHANNEL_ID, CHAT_CHANNEL_ID) if cid
)
RELAY_SECONDS = float(os.environ.get("RELAY_SECONDS", "3"))
# On restart, anything older than this is marked relayed WITHOUT being sent.
# Same contract as the outcome poller: the bridge reports what happens while
# it is watching, and never replays hours of history into the channel.
RELAY_BACKLOG_GRACE_SECONDS = int(os.environ.get("RELAY_BACKLOG_GRACE_SECONDS", "120"))
# How many times one batch may fail to send before it is dropped so the rest
# of the conversation can get through.
RELAY_MAX_ATTEMPTS = int(os.environ.get("RELAY_MAX_ATTEMPTS", "3"))

LLM_URL = os.environ.get(
    "LLM_URL", "http://spark-gateway.spark-gateway.svc.cluster.local:8080/v1/chat/completions"
)
LLM_MODEL = os.environ.get("LLM_MODEL", "spark:warm-any")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
# What gets said in game when NOBODY in the family could answer an order Evan
# gave - the voice is down, or none of them are in the world. Said once, by the
# most senior of them, and in the family's own register because it is one of
# them saying it. The alternative is what this replaced: returning silently,
# which looks exactly like not having been heard at all.
VOICE_SILENT = "Words come to us wrong. Say again."

GEO = Geometry.load(os.path.dirname(os.path.abspath(__file__)))

RACE_NAMES = {1: "Human", 2: "Orc", 3: "Dwarf", 4: "Night Elf", 5: "Undead",
              6: "Tauren", 7: "Gnome", 8: "Troll", 10: "Blood Elf", 11: "Draenei"}
CLASS_NAMES = {1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest",
               6: "Death Knight", 7: "Shaman", 8: "Mage", 9: "Warlock", 11: "Druid"}


def _connect():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        user="root",
        password=os.environ["MYSQL_ROOT_PASSWORD"],
        database="acore_characters",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        # Bounded like the map server: PyMySQL's default read timeout is
        # infinite, and a hung poll would silently stop outcome reporting.
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )


def _insert_command(cmd: core.InsertCommand) -> int:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO overseer_command (target_name, command, source) VALUES (%s, %s, %s)",
            (cmd.target_name, cmd.command, cmd.source),
        )
        return cur.lastrowid


def _insert_speak(cmd: relay.SpeakCommand) -> int:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO overseer_command "
            "(target_name, command, kind, channel, target_arg, source) "
            "VALUES (%s, %s, 'chat', %s, %s, %s)",
            (cmd.target_name, cmd.text, cmd.channel, cmd.whisper_to, cmd.source),
        )
        return cur.lastrowid


def _insert_gm(cmd: relay.GmCommand) -> int:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO overseer_command (target_name, command, kind, source) "
            "VALUES (%s, %s, 'gm', %s)",
            (cmd.target_name, cmd.command, cmd.source),
        )
        return cur.lastrowid


def _insert_job(name: str, mode: str, source: str) -> int:
    """One overseer_command row asking mod-overseer to set `name`'s job.

    kind='job', not 'bot': "job quest" is not a mod-playerbots chat command,
    so handing it to PlayerbotAI::HandleCommand the way a real vocabulary
    entry is handed would be accepted and do nothing - precisely the
    voice.py "sell junk" failure this codebase already paid for once. A
    dedicated kind puts it through mod_overseer.cpp's DoJob instead, the same
    way kind='give' and kind='share' get their own handlers rather than
    going through the bot's own chat parser (mod_overseer.cpp:4018).
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO overseer_command (target_name, command, kind, source) "
            "VALUES (%s, %s, 'job', %s)",
            (name, mode, source),
        )
        return cur.lastrowid


def _fetch_enabled_names() -> list[str]:
    """Every character the roster currently drives. A job order is family-wide
    (jobs.py's own docstring explains why), so this is what it fans out over.
    Chosen over overseer_snapshot's online-right-now view so the report names
    the whole family the order was meant for - mod_overseer.cpp's DoJob still
    requires the target to be in the world to act on the row (same rule every
    other command kind follows), so an offline member's row comes back
    'target not online' rather than silently landing later; the muster-style
    report in _set_job says exactly what was written, not what was intended."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM overseer_roster WHERE enabled = 1")
        return [row["name"] for row in cur.fetchall()]


def _fetch_unrelayed_chat() -> list[dict]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, heard_by, sender_name, sender_is_bot, channel, channel_name, text "
            "FROM overseer_chat WHERE relayed = 0 ORDER BY id ASC LIMIT %s",
            (relay.MAX_LINES_PER_POST,),
        )
        return list(cur.fetchall())


def _mark_relayed(ids: list) -> None:
    if not ids:
        return
    # Fully parameterized on purpose, exactly like _fetch_outcomes: a dynamic
    # IN-list is the one shape here that would mean assembling a statement out
    # of strings. One statement per id costs nothing at this batch size, which
    # relay.MAX_LINES_PER_POST bounds.
    with _connect() as conn, conn.cursor() as cur:
        cur.executemany(
            "UPDATE overseer_chat SET relayed = 1 WHERE id = %s", [(i,) for i in ids]
        )


def _skip_chat_backlog(seconds: int) -> int:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE overseer_chat SET relayed = 1 "
            "WHERE relayed = 0 AND created_at < NOW() - INTERVAL %s SECOND",
            (seconds,),
        )
        return cur.rowcount


# How long a claim may sit before the bridge gives up waiting for it.
#
# Deliberately far longer than a command needs (delivery is within one 2s
# worldserver poll), because elapsed time is NOT proof that the worldserver
# stopped: a stalled database or a paused process can still be mid-command.
# The cost of guessing wrong is the worst kind here - telling someone their
# ".additem" failed when it did not, and inviting them to run it again - so
# the wording below never says "failed", and this window is generous.
#
# A lease token and heartbeat would settle it properly. That is the right
# design for several worldservers; there is one, and it owns the row it
# claimed, so the cheap correct move is to be slow and honest instead.
CLAIM_STALE_SECONDS = int(os.environ.get("CLAIM_STALE_SECONDS", "300"))


def _expire_stale_claims(seconds: int) -> int:
    """Move abandoned claims to a terminal state.

    A worldserver that dies mid-command leaves its row claimed forever, which
    is deliberate - it is what stops the command running twice. But left
    there it also pins the outcome poller's floor, so every poll re-scans the
    whole tail of the table and the seen-set grows without bound, for as long
    as the bridge lives. Ending the row does two jobs: it bounds the poll, and
    it finally tells whoever gave the order that nothing came of it.

    Never re-runs anything: the row goes straight to 'error'.

    'verifying' (infra#2819) is swept the same way and for the same reason,
    with its own wording. That row HAS been handed to the bot - what was lost
    is the read-back that would have said whether the bot changed - and
    telling someone their command never ran when it did is the exact mistake
    the paragraph above exists to avoid. The module keeps its outstanding
    read-backs in memory (mod_overseer.cpp, _pendingChecks), so a worldserver
    restart is precisely when this fires.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE overseer_command SET status = 'error', "
            "detail = 'no result from the worldserver; it MAY still have run, "
            "check before repeating it' "
            "WHERE status = 'claimed' AND updated_at < NOW() - INTERVAL %s SECOND",
            (seconds,),
        )
        swept = cur.rowcount
        cur.execute(
            "UPDATE overseer_command SET status = 'error', "
            "detail = 'handed to the bot, but the worldserver never reported "
            "whether anything changed' "
            "WHERE status = 'verifying' AND updated_at < NOW() - INTERVAL %s SECOND",
            (seconds,),
        )
        return swept + cur.rowcount


def _fetch_roster() -> list[dict]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            # guild_id rides along for fan-out target resolution
            # (infra#2605); core.format_roster ignores the extra column.
            "SELECT name, level, race, map_id, in_combat, is_bot, guild_id "
            "FROM overseer_snapshot WHERE updated_at > NOW() - INTERVAL 60 SECOND"
        )
        return list(cur.fetchall())


def _ensure_thought_store() -> None:
    # Bridge-owned state, deliberately NOT module SQL: the thought store is
    # the overseer's memory, never touched by the worldserver, and coupling
    # it to a 90-minute game-server image rebuild would be pure friction.
    # CREATE TABLE IF NOT EXISTS is idempotent, unlike module ALTERs - the
    # #2595 one-mechanism rule was about dbimport-managed schema, and this
    # is not that. Deviation from the epic's shipped-as-module-SQL wording
    # is recorded on infra#2600.
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS overseer_thought ("
            " id INT UNSIGNED NOT NULL AUTO_INCREMENT,"
            " character_name VARCHAR(12) NOT NULL,"
            " source ENUM('command','chat','goal','event','reflection','council') NOT NULL,"
            " text VARCHAR(2000) NOT NULL,"
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " PRIMARY KEY (id), KEY idx_char (character_name, id),"
            " KEY idx_source (source, id)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        # CREATE TABLE IF NOT EXISTS is a no-op on the table that already
        # exists in the live DB, so the index above would never reach it.
        # MySQL has no CREATE INDEX IF NOT EXISTS, hence the lookup; without
        # it _fetch_reflections walks the primary key backwards past every
        # command/chat/goal/event row, and reflection rows are the sparse
        # ones - the scan lengthens as the store grows, on the chat relay's
        # own path.
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.STATISTICS "
            "WHERE table_schema = DATABASE() AND table_name = 'overseer_thought' "
            "  AND index_name = 'idx_source'"
        )
        if not (cur.fetchone() or {}).get("n"):
            cur.execute("ALTER TABLE overseer_thought ADD KEY idx_source (source, id)")
            log.info("overseer_thought: added idx_source")

        # 'council' is its own source, and separating it is a correctness fix
        # rather than tidiness. Council speech was written as 'reflection', the
        # same tag kin uses for "X called for help. I regrouped." - and
        # bonds.history_from_thoughts reads a bounded window of reflection rows
        # to count who has helped whom. Measured on the live table: 66 of the
        # 71 rows in that window were council lines and 5 were real memories.
        # A busier council evicts the memories entirely, and the jealousy and
        # fatigue rules stop being able to fire, silently.
        cur.execute(
            "SELECT COLUMN_TYPE AS t FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'overseer_thought' "
            "  AND COLUMN_NAME = 'source'"
        )
        column = (cur.fetchone() or {}).get("t") or ""
        if "'council'" not in column:
            cur.execute(
                "ALTER TABLE overseer_thought MODIFY source "
                "ENUM('command','chat','goal','event','reflection','council') NOT NULL"
            )
            log.info("overseer_thought: source gained 'council'")


def _insert_thought(name: str, source: str, text: str) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO overseer_thought (character_name, source, text) VALUES (%s, %s, %s)",
            (name, source, text[:2000]),
        )


# Grug sulking is a mood, not a life sentence. The window is a CLOCK, not a
# row count: a row-count window only advances when rows are written, and a
# muster that everyone refuses writes none - so the family could reach a state
# where nobody comes, which then produced no memories, which kept nobody
# coming. Deadlock, and silent, since refusals only ever hit the log. Six
# hours means the counts drain on their own whether or not anyone helps.
REFLECTION_WINDOW_HOURS = 6
REFLECTION_WINDOW_MAX = 400


def _fetch_reflections() -> list[dict]:
    """The recent `reflection` rows bonds judges on, oldest first.

    ORDER BY id DESC then reverse: a plain ASC LIMIT would pin the window to
    the oldest rows in the table and never move. The LIMIT is a backstop on a
    busy stream, not the window itself.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT character_name, text FROM overseer_thought "
            "WHERE source = 'reflection' "
            "  AND created_at > NOW() - INTERVAL %s HOUR "
            "ORDER BY id DESC LIMIT %s",
            (REFLECTION_WINDOW_HOURS, REFLECTION_WINDOW_MAX),
        )
        return list(reversed(cur.fetchall()))


def _persona_for(grounding: dict) -> str | None:
    """The character to prompt this one as: the family's own, or the bots'.

    The family is described in bonds.py, in text Evan wrote, and that beats
    `mod_ollama_chat_personality` outright - it is not a fallback for them.
    See persona.characterisation: that table holds ANCIENT_WISE_ONE for Bork
    and Og and nothing for the other three, which is why the youngest son
    answered "lets go sell junk in town" as a sage.

    The JOIN stays for everyone else. _fetch_grounding also serves Discord
    orders aimed at any of the five hundred random bots on this realm, and for
    them that row is the only characterisation there is - dropping it would
    trade one family's wrong voice for everybody else's missing one.
    """
    return persona.characterisation(grounding["name"]) or grounding["personality"]


def _fetch_grounding(name: str) -> dict | None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT s.name, s.level, s.race, s.class, s.map_id, s.pos_x, s.pos_y, "
            "       p.personality "
            "FROM overseer_snapshot s "
            "LEFT JOIN characters c ON c.name = s.name "
            "LEFT JOIN mod_ollama_chat_personality p ON p.guid = c.guid "
            "WHERE s.name = %s AND s.updated_at > NOW() - INTERVAL 60 SECOND",
            (name,),
        )
        return cur.fetchone()


def _ask_llm(prompt: str, system: str = "") -> str:
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            # Reasoning models think aloud in the content stream and then
            # answer; the first live run hit max_tokens mid-thought and never
            # reached the JSON. Ask for silence, disable thinking where the
            # backend honors it (vLLM chat_template_kwargs; ollama ignores
            # the key), and budget enough tokens that a backend which thinks
            # anyway still reaches the answer. parse_decision takes the LAST
            # JSON object for the same reason.
            {"role": "system", "content": "Answer with the JSON object only. No reasoning, no preamble."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 1500,
        "temperature": 0.7,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        LLM_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"]


# One `%s` per terminal status, and nothing else is ever interpolated: the
# count comes from a tuple length, never from a value, and every status still
# travels as a bound parameter. An IN clause of unknown width has no other
# form in DB-API.
_TERMINAL_STATUS_MARKS = ",".join(["%s"] * len(core.COMMAND_TERMINAL_STATUSES))


def _fetch_outcomes(min_id: int) -> list[dict]:
    # Static, fully parameterized SQL on purpose (a dynamic IN-list means
    # assembling the statement from strings). Rows at or above the oldest
    # pending id that we did not insert ourselves come back too - they route
    # to no channel and are dropped, and core's seen-set keeps every report
    # exactly-once.
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            # 'claimed' and 'verifying' are in-flight, not finished: reporting
            # either would call a command that is still running a failure.
            # The terminal set is core.COMMAND_TERMINAL_STATUSES and NOT a
            # literal list here - it is the same rule as the reply formatting
            # forty lines away in core.report_outcomes, and two copies of one
            # rule is how a status gets added in one place and dropped on the
            # floor in the other (infra#2819).
            "SELECT id, target_name, command, kind, status, detail FROM overseer_command "
            f"WHERE status IN ({_TERMINAL_STATUS_MARKS}) AND id >= %s",  # noqa: S608
            (*core.COMMAND_TERMINAL_STATUSES, min_id),
        )
        return list(cur.fetchall())


def _ensure_roster(names: list) -> int:
    """Put the notable characters on the roster mod-overseer logs in.

    One list, not two: the same OVERSEER_NOTABLE_NAMES that decides who is
    worth protecting decides who is worth keeping online. A character we
    refuse to let be re-rolled but never log in is a contradiction.

    INSERT IGNORE, so a row disabled by hand stays disabled - parking a
    character is a decision, and a loop that silently re-enabled it every
    cycle would make that decision unmakeable.

    The table belongs to mod-overseer's SQL, which arrives with the
    worldserver image. Until that image ships the table is absent, and this
    says so once per cycle rather than failing quietly - the bridge cannot
    create it without becoming a second owner of one schema (#2595).
    """
    if not names:
        return 0
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.executemany(
                "INSERT IGNORE INTO overseer_roster (name, note) VALUES (%s, %s)",
                [(n, "notable character") for n in names],
            )
            return cur.rowcount or 0
        except pymysql.err.ProgrammingError as exc:
            if "overseer_roster" in str(exc):
                log.warning(
                    "overseer_roster missing - roster login needs the worldserver "
                    "image carrying mod-overseer's SQL (infra#2656)"
                )
                return 0
            raise


# Everything a character says that is worth hearing. Whisper stays in despite
# being where the addon noise arrived: bots whispering each other is exactly
# the conversation worth watching, and relay.partition_addon removes the
# machine traffic without removing the channel.
WATCH_CHANNELS = "say,yell,emote,whisper,party,raid,guild,officer"


_BOT_HELD_SQL = (
    "SELECT name FROM overseer_snapshot "
    "WHERE is_bot = 1 AND updated_at > NOW() - INTERVAL 60 SECOND "
    "  AND name IN (%s)"
)


def _bot_held_names(names: list) -> list:
    """Of `names`, the ones currently driven by the AI rather than by a person.

    A character Evan is holding at the keyboard has no PlayerbotAI, so every
    bot command aimed at it is refused - and the roster loop would aim one
    every cycle, forever, filling the command table with errors against the
    one character he happens to be playing.
    """
    if not names:
        return []
    placeholders = ",".join(["%s"] * len(names))
    # The rule is right to look and wrong here: the only thing interpolated
    # is the NUMBER of placeholders, computed from len(names) one line above.
    # Every name reaches MySQL as a bound parameter, and a variable-length IN
    # list cannot be written with a static string. The query is hoisted to a
    # constant so the interpolation sits on one short line: ruff anchors S608
    # at the START of the expression, so a noqa on the line carrying the %
    # does not silence a multi-line one.
    sql = _BOT_HELD_SQL % placeholders
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        return [r["name"] for r in cur.fetchall()]


def _aimed_names() -> set:
    """Who currently has somewhere to be, by name.

    A QUEST AIM IS NOT THE ONLY KIND OF SOMEWHERE. This asked only for
    `drive_quest` until 2026-09-07, so a character carrying a travel errand
    and no quest did not count as aimed, and the strategy pass below took
    `new rpg` straight back off it. The module then could not walk it
    anywhere and logged that it does not carry `new rpg`, advising the
    reader to aim the leader instead, which was the character it had just
    refused. One follower stood motionless for nineteen minutes with its
    errand still set, until the errand own twenty-minute backstop released
    it as unreachable, and the party leader was refused the same way.

    The tell was that a sibling with a quest aim walked the identical
    errand successfully in the same minute. That is this line and nothing
    else: one had `drive_quest` set and the other did not.

    This function own docstring already named the failure it exists to end,
    "an aim that never reaches a strategy is the exact silent failure".
    It ended it for quest aims and not for errands.

    Read fresh rather than carried down from _aim_traveller: the aim is
    standing state on the roster row and survives both a bridge restart and a
    worldserver one, so the strategy pass has to ask the table what is true now
    rather than remember what it last wrote.

    THE COLUMN CAN LEGITIMATELY BE ABSENT, exactly as it can in _aim_traveller:
    drive_quest arrives with mod-overseer's SQL, applied by the worldserver at
    startup, and the bridge is a separate deployment with its own restarts.
    Returning an empty set on 1054 degrades to the old leader-only behaviour,
    which is the safe direction - nobody gets the wander strategy who did not
    have it before. Warned, because an aim that never reaches a strategy is the
    exact silent failure this function exists to end.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT name FROM overseer_roster "
                "WHERE enabled = 1 AND (drive_quest <> 0 "
                "OR (travel_npc IS NOT NULL AND travel_npc <> ''))"
            )
        except pymysql.err.OperationalError as exc:
            # 1054 is ER_BAD_FIELD_ERROR. Matched on the code, not the message
            # text, which is localised.
            if exc.args and exc.args[0] == 1054:
                log.warning(
                    "overseer_roster has no drive_quest column - nobody can be "
                    "aimed, so the family falls back to leader-only travel"
                )
                return set()
            raise
        return {row["name"] for row in cur.fetchall()}


def _travelling_names() -> set:
    """Who is part-way through a travel errand, by name.

    A NARROWER QUESTION THAN _aimed_names ABOVE, and the two are not
    interchangeable. That one asks who has somewhere to be, and a quest aim
    counts. This one asks who is ALREADY WALKING somewhere under an errand,
    which is the window in which the module owns the character's task and this
    process must not hand it a second one - see goals.life_strategies.

    THE COLUMN IS THE SIGNAL, AND IT IS THE MODULE'S OWN DEFINITION:

        WHAT COUNTS AS TRAVELLING HERE. Any character with a live errand in
        `travel_npc` that it can actually act on. The dungeon run's BARRIER
        escort, DriveCatchUp's catch-up walk and an operator's own travel aim
        are three names for one row in one column, and from this angle they
        are the same thing.

    That is not merely a convention the callers follow. mod_overseer.cpp opens
    a stand-down in exactly one place, and it sits inside a loop over
    `WHERE enabled = 1 AND travel_npc <> ''`, so the module CANNOT have a
    strategy stood down for a character whose column is empty. Withholding on
    a non-empty column therefore cannot miss a window in which it does.

    Asked separately from _aimed_names rather than folded into it, because the
    two mean different things and a single query returning both would invite
    the next reader to use whichever set was nearer. It is one more indexed
    read on a five-row table, on a cadence measured in minutes.

    THE COLUMN CAN LEGITIMATELY BE ABSENT, exactly as in _aimed_names, and for
    the same reason: it arrives with mod-overseer's SQL, applied by the
    worldserver at startup, and this bridge is a separate deployment with its
    own restarts. Returning an empty set degrades to the behaviour from before
    infra#3423 - the task strategy is granted as it always was - which is the
    right direction, because a realm with no such column has no errands for
    this to collide with either.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT name FROM overseer_roster "
                "WHERE enabled = 1 AND travel_npc IS NOT NULL AND travel_npc <> ''"
            )
        except pymysql.err.OperationalError as exc:
            # 1054 is ER_BAD_FIELD_ERROR. Matched on the code, not the message
            # text, which is localised.
            if exc.args and exc.args[0] == 1054:
                log.warning(
                    "overseer_roster has no travel_npc column - nobody counts "
                    "as travelling, so a character on an errand can still be "
                    "handed the strategy that pulls it off the errand"
                )
                return set()
            raise
        return {row["name"] for row in cur.fetchall()}


def _give_them_a_life(names: list) -> int:
    """Keep every family member on the strategy that makes them live.

    Re-issued on the roster cadence rather than once, for the same reason the
    goal supervisor re-asserts: PlayerbotAI::ResetStrategies runs on login and
    rebuilds from defaults, and every autonomous default is gated behind
    IsRandomBot(), false for named characters. After the last worldserver
    restart only the one character with an active goal got a strategy back.
    The other four stood in a huddle in Northshire and nothing anywhere said
    so - their levels simply stopped moving.

    Idempotent at the game's end: adding a strategy already present is a no-op.
    """
    driven = _bot_held_names(names)
    # NOT bonds.head_of_family() DIRECTLY. A character running a trade errand
    # borrows the lead for the duration, because the leader is the family's one
    # traveller - see _head_now and _errand_traveller. Asked once for the whole
    # pass, like `aimed` below and for the same reason: a head that changed
    # underneath a single sweep would leave two characters holding `new rpg`.
    head = _head_now()
    # WHO IS AIMED DECIDES WHO TRAVELS, not the lead flag alone. Fetched once
    # for the whole pass: it is one query, and asking per character would let
    # the set change underneath a single roster sweep, so two members could be
    # given contradictory strategies for the same quest.
    aimed = _aimed_names()
    # WHO IS ALREADY WALKING DECIDES WHO IS LEFT ALONE. Fetched once for the
    # whole pass, like `head` and `aimed` above and for the same reason: a
    # character that started an errand halfway through a sweep would otherwise
    # be told twice, contradictorily, in one pass.
    travelling = _travelling_names()
    for name in driven:
        # The leader always travels. A follower travels when it has somewhere
        # to be - see goals.life_strategies: an UNAIMED follower given the
        # wander strategy is what scattered them across a thousand yards with
        # the healer in her own fight, and an AIMED one converges instead,
        # because everyone aimed at a quest is walking to the same place.
        # An errand in flight means the module already owns this character's
        # task and has stood down everything that would divert it. Granting
        # the task strategy on top is infra#3423, which the module catches and
        # undoes within one poll - bounded, but two writers should not both be
        # answering one question.
        for command in goals.life_strategies(
            leads=(name == head),
            aimed=(name in aimed),
            travelling=(name in travelling),
        ):
            _insert_command(core.InsertCommand(name, command, "overseer:life"))
    return len(driven)


def _ensure_chat_watch(names: list) -> int:
    """Put the notable characters on the chat watch list.

    The list was hand-populated and had exactly one name on it, so four of the
    five family members could not be heard at all - their conversation reached
    neither Discord nor the thought store, and nothing anywhere said so. It is
    the same failure the roster had: a list maintained by hand beside a list
    maintained by code, drifting quietly.

    INSERT IGNORE, so a row narrowed by hand keeps its channels.
    """
    if not names:
        return 0
    with _connect() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT IGNORE INTO overseer_chat_watch (name, channels) VALUES (%s, %s)",
            [(n, WATCH_CHANNELS) for n in names],
        )
        return cur.rowcount or 0


# Quest progress, joined to the names a character would actually say. The
# creature and item lookups are LEFT JOINs on purpose: a missing name yields a
# vaguer sentence, never a dropped quest.
_QUEST_SQL = """
SELECT c.name AS character_name, q.quest,
       q.mobcount1, q.mobcount2, q.mobcount3, q.mobcount4,
       q.itemcount1, q.itemcount2, q.itemcount3, q.itemcount4,
       t.LogTitle,
       t.RequiredNpcOrGoCount1, t.RequiredNpcOrGoCount2,
       t.RequiredNpcOrGoCount3, t.RequiredNpcOrGoCount4,
       t.RequiredItemCount1, t.RequiredItemCount2,
       t.RequiredItemCount3, t.RequiredItemCount4,
       n1.name AS npc_name1, n2.name AS npc_name2,
       i1.name AS item_name1, i2.name AS item_name2
FROM character_queststatus q
JOIN characters c              ON c.guid = q.guid
JOIN acore_world.quest_template t ON t.ID = q.quest
LEFT JOIN acore_world.creature_template n1 ON n1.entry = t.RequiredNpcOrGo1
LEFT JOIN acore_world.creature_template n2 ON n2.entry = t.RequiredNpcOrGo2
LEFT JOIN acore_world.item_template i1     ON i1.entry = t.RequiredItemId1
LEFT JOIN acore_world.item_template i2     ON i2.entry = t.RequiredItemId2
WHERE q.status IN (1, 3) AND c.name IN (%s)
"""


# One character, one quest: the goal supervisor's observation. DERIVED from
# _QUEST_SQL by replacing its WHERE clause rather than written out again, so
# the join and the twenty-odd column spellings live in exactly one place. A
# hand-copied second query would drift the first time quest_template's columns
# move, and it would drift silently - the counts would simply stop matching
# what the family says out loud.
# The status filter is deliberately OUTSIDE the replaced text, so this
# derivation cannot drop it. Swapping "WHERE ... IN (%s)" wholesale is what
# would let the single-quest read drift back to counting abandoned rows -
# the same bug as infra#2892, one query along.
_QUEST_ONE_SQL = _QUEST_SQL.replace(
    "c.name IN (%s)", "c.name = %s AND q.quest = %s"
)
if "c.name = %s" not in _QUEST_ONE_SQL:  # pragma: no cover - import-time tripwire
    # A plain `assert` would vanish under python -O and leave this query with
    # _QUEST_SQL's IN-clause and two bound parameters, which fails at the one
    # moment it is needed - inside the supervision cycle, once an hour.
    raise RuntimeError("_QUEST_SQL WHERE clause moved; _QUEST_ONE_SQL is stale")


def _authored_lines(minutes: int = 30) -> set:
    """Every line the bridge recently put in a character's mouth.

    This is how an order is told apart from the family's own speech. The bot
    flag cannot do it: with selfbot on, the AI attaches to Evan's character and
    everything he types is flagged as bot speech. Authorship holds either way.

    Bounded by time so the set stays small and so a sentence the family said an
    hour ago cannot mute Evan saying the same words now.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT command FROM overseer_command "
            "WHERE kind = 'chat' AND created_at > NOW() - INTERVAL %s MINUTE",
            (minutes,),
        )
        return {r["command"] for r in cur.fetchall()}


def _fetch_quest_progress(names: list) -> dict:
    """name -> (sentence, objectives left, quest id) for their closest quest.

    THE ID IS THE POINT OF THE TUPLE. The sentence is what a character says;
    the id is what mod-overseer can actually aim a bot at, and the council's
    plan carries `target` = objectives remaining, which names no quest at all.
    Carrying the id out of the SAME quests.focus() call that produced the
    sentence is what guarantees the goal drives the quest the family talked
    about; re-deriving it later from the same table can legitimately pick a
    different one, because focus() breaks ties on live counts that move.

    Bounded by the roster, and every number in the sentence comes from a row.
    A character inventing its own progress is a character the overseer can no
    longer be believed about, which is worth more than a livelier line.
    """
    if not names:
        return {}
    placeholders = ",".join(["%s"] * len(names))
    sql = _QUEST_SQL % placeholders
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        rows = cur.fetchall()

    by_name: dict = {}
    for row in rows:
        progress = quests.read(row, row)
        if progress is None:
            continue
        by_name.setdefault(progress.character, []).append(progress)

    out: dict = {}
    for name, progress in by_name.items():
        chosen = quests.focus(progress)
        if chosen is not None:
            out[name] = (quests.say_remaining(chosen), chosen.left, chosen.quest_id)
    return out


# The `character_skills.skill` ids that are actually TRADES, as one string, so
# the council's own count means what its variable is called.
#
# WHY THIS EXISTS (infra#2757). This subquery was a bare `COUNT(*)`, and
# `character_skills` holds every skill a character has: Language: Orcish,
# Defense, Swords, Axes, Unarmed, and a class skill besides. So `trades` was
# never below TRADES_EXPECTED (2) for anybody who had ever logged in, and
# council.assess's "I have no trade to speak of" branch was unreachable code
# from the day it was written. The council could not raise the very thing this
# issue is about.
#
# Primaries only. First aid, cooking and fishing are secondary skills that cost
# no profession slot, and counting them would put every character at five and
# reintroduce the same always-true bug in a smaller font.
_TRADE_SKILL_IDS = ",".join(
    str(goals.SKILL_IDS[name]) for name in sorted(professions.PRIMARY)
)

_COUNCIL_MEMBER_SQL = (
    "SELECT c.name, c.class, c.money, "
    "       (SELECT COUNT(*) FROM character_skills k "
    "         WHERE k.guid = c.guid AND k.skill IN (" + _TRADE_SKILL_IDS + ")"
    "       ) AS trades, "
    "       s.level AS live_level "
    "FROM characters c "
    "LEFT JOIN overseer_snapshot s "
    "       ON s.name = c.name AND s.updated_at > NOW() - INTERVAL 60 SECOND "
    "WHERE c.name IN (%s)"
)


def _fetch_council_members(names: list) -> list:
    """The state each family member brings to a council.

    Level comes from the snapshot (5s fresh) rather than `characters`, which
    only persists on the periodic save and reads minutes stale - a council
    planning around a level that changed twenty minutes ago is planning around
    fiction.

    Gold and trade count are private to their owner. They are gathered here in
    one query because one query is cheaper than five, and handed out one member
    at a time; council.assess never sees the list.
    """
    if not names:
        return []
    placeholders = ",".join(["%s"] * len(names))
    # Hoisted for the same reason as _BOT_HELD_SQL: ruff anchors S608 at the
    # START of the expression, so a noqa on the line carrying the % does not
    # silence a multi-line query. This one carried exactly that mistake and was
    # only invisible because the lint is scoped to the diff.
    sql = _COUNCIL_MEMBER_SQL % placeholders
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            sql,
            names,
        )
        rows = cur.fetchall()

    progress = _fetch_quest_progress(names)
    # What the family has already agreed this character will go and learn, and
    # has not learned yet. Read here rather than derived, because `trades` is a
    # count and the family's shortfall is a NAME - see _TRADE_SKILL_IDS.
    owed = _pending_trades()
    members = []
    for row in rows:
        level = row.get("live_level")
        if level is None:
            # Offline, or the snapshot went stale. A member nobody can see is
            # not at the table; guessing their level from a stale row is how a
            # council decides to help someone who already caught up.
            continue
        said, left, quest_id = progress.get(row["name"], ("", 0, 0))
        members.append(
            council.Member(
                name=row["name"],
                level=int(level),
                class_name=CLASS_NAMES.get(row["class"], "adventurer"),
                gold=int(row["money"] or 0),
                trades=int(row["trades"] or 0),
                trade_wanted=owed.get(row["name"], ""),
                quest=said,
                quest_left=left,
                quest_id=quest_id,
            )
        )
    return members


# --- trades: who takes what, and the proof that nobody was handed it --------
#
# THE ONE RULE (infra#2757). Nothing below writes `character_skills`. A
# profession is learned at a trainer or it is not learned, exactly as a bag is
# crafted or not crafted (#2823) and a trainer spell is taught or not taught
# (#2782). What this section does is DECIDE, say it out loud, write the
# decision down, and then watch the world to see whether it has happened. A row
# reaching 'learned' is a report about the world, never a cause of it.
#
# The learning step is a DELIBERATE FOLLOW-UP, not a blocked one. Sending a
# character to a named NPC used to be impossible and is the reason this section
# stops where it does; #2840 built it (travel.ROLES has "profession trainer"),
# so what is left is the transaction at the far end - walking there is not
# training. professions.BLOCKERS carries the citations for what remains, and
# they are logged once per plan so the reason sits beside the plan.

_TRADE_SKILL_SQL = (
    "SELECT c.name, k.skill, k.value "
    "FROM characters c JOIN character_skills k ON k.guid = c.guid "
    "WHERE c.name IN (%s) AND k.skill IN (" + _TRADE_SKILL_IDS + ")"
)

_TRADE_CLASS_SQL = "SELECT name, class FROM characters WHERE name IN (%s)"

# skill id -> the lowercase name professions and goals both use. Inverted from
# the one table rather than restated, so a wrong number here is impossible.
_SKILL_NAMES = {number: name for name, number in goals.SKILL_IDS.items()}


def _ensure_trade_store() -> None:
    """The trade decision, created the same way the goal store is.

    Bridge-owned state: the worldserver never reads it, so coupling it to a
    90-minute game-server image rebuild would be friction for nothing (the
    deviation is recorded on infra#2600 and this follows it).

    `status` has exactly two values and no third. There is deliberately NO
    'granted' - an assignment is 'planned' until the world is observed to
    already agree, and then it is 'learned'. A status this service could set by
    fiat is the shape of the bug the whole issue is about.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS overseer_trade ("
            " id INT UNSIGNED NOT NULL AUTO_INCREMENT,"
            " character_name VARCHAR(12) NOT NULL,"
            " verb ENUM('learn','unlearn') NOT NULL,"
            " skill_name VARCHAR(32) NOT NULL,"
            " skill_id SMALLINT UNSIGNED NOT NULL,"
            " reason TEXT NOT NULL,"
            " status ENUM('planned','learned') NOT NULL DEFAULT 'planned',"
            " decided_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " settled_at TIMESTAMP NULL DEFAULT NULL,"
            " PRIMARY KEY (id),"
            " UNIQUE KEY uq_char_verb_skill (character_name, verb, skill_name)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )


def _fetch_trade_skills(names: list) -> dict:
    """name -> {profession: value}, PRIVATE to its owner.

    Professions only. `character_skills` also holds languages, Defense and
    every weapon skill, and handing those to a module that reasons about
    profession slots is how `trades` came to mean nothing (see
    _TRADE_SKILL_IDS).

    READ-ONLY, and that is the whole contract of this function. It is the only
    place in the bridge that touches character_skills at all.
    """
    if not names:
        return {}
    placeholders = ",".join(["%s"] * len(names))
    # Hoisted for the same reason as _COUNCIL_MEMBER_SQL: ruff anchors S608 at
    # the START of the expression, so a noqa on the line carrying the % does
    # not silence a multi-line query.
    sql = _TRADE_SKILL_SQL % placeholders
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        rows = cur.fetchall()

    out: dict = {name: {} for name in names}
    for row in rows:
        name = _SKILL_NAMES.get(int(row["skill"]))
        if name is None:
            continue
        out.setdefault(row["name"], {})[name] = int(row["value"] or 0)
    return out


def _pending_trades() -> dict:
    """name -> the trade they still owe the family, for the council to raise.

    Only 'learn'. An unlearn is a chore on the way, not something a character
    would announce it wants; what Og would say at the table is that he is going
    to learn to sew, not that he is giving up an alchemy he never used.
    """
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT character_name, skill_name FROM overseer_trade "
                "WHERE status = 'planned' AND verb = 'learn'"
            )
            return {r["character_name"]: r["skill_name"] for r in cur.fetchall()}
    except Exception:
        # A council that cannot read the trade table is still a council. This
        # is a decoration on one proposal, not a reason to lose the scene.
        log.exception("trades: could not read the plan; the council goes without it")
        return {}


def _council_family() -> list:
    """The family as professions.plan sees them: class, seniority, own skills."""
    names = sorted(_protected_guids().values())
    if not names:
        return []
    skills = _fetch_trade_skills(names)
    placeholders = ",".join(["%s"] * len(names))
    # Hoisted, same as _COUNCIL_MEMBER_SQL and _TRADE_SKILL_SQL: ruff anchors
    # S608 at the START of the expression, so a noqa on the line carrying the %
    # does not silence a multi-line query.
    sql = _TRADE_CLASS_SQL % placeholders
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        rows = cur.fetchall()

    family = []
    for row in rows:
        bond = bonds.member(row["name"])
        family.append(professions.Member(
            name=row["name"],
            class_name=CLASS_NAMES.get(row["class"], ""),
            skills=skills.get(row["name"], {}),
            seniority=bond.seniority if bond else 0,
        ))
    return family


def _record_trade_plan(plan) -> list:
    """Write the decision down, and return the assignments that are NEW.

    INSERT IGNORE against the unique key, so a plan the family reached last
    hour and reaches again this hour is not re-decided and - the half that
    matters - not re-announced. The scene is played once.
    """
    if not plan.assignments:
        return []
    fresh = []
    with _connect() as conn, conn.cursor() as cur:
        for assignment in plan.assignments:
            cur.execute(
                "INSERT IGNORE INTO overseer_trade "
                "(character_name, verb, skill_name, skill_id, reason) "
                "VALUES (%s, %s, %s, %s, %s)",
                (assignment.character, assignment.verb, assignment.skill,
                 assignment.skill_id, assignment.reason[:2000]),
            )
            if cur.rowcount:
                fresh.append(assignment)
    return fresh


def _settle_trades(skills: dict) -> list:
    """Move rows to 'learned' where the WORLD already agrees. Returns those rows.

    THE NO-MAGIC HINGE. professions.settled is handed the observed skills and
    answers a question; it cannot go and get them, and this function cannot
    make one up - the only input is a live read of character_skills. So a row
    can only reach 'learned' by somebody actually having been to a trainer, by
    whatever route that happened, INCLUDING Evan walking Og there himself.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, character_name, verb, skill_name, skill_id, reason "
            "FROM overseer_trade WHERE status = 'planned'"
        )
        planned = list(cur.fetchall())

        done = []
        for row in planned:
            observed = skills.get(row["character_name"])
            if observed is None:
                # Not seen this cycle. Silence is not evidence of anything.
                continue
            assignment = professions.Assignment(
                character=row["character_name"], verb=row["verb"],
                skill=row["skill_name"], skill_id=int(row["skill_id"]),
                reason=row["reason"], said="",
            )
            if not professions.settled(assignment, observed):
                continue
            cur.execute(
                "UPDATE overseer_trade SET status = 'learned', settled_at = NOW() "
                "WHERE id = %s AND status = 'planned'",
                (row["id"],),
            )
            done.append(assignment)
    return done


def _mark_party_leader(head: str) -> None:
    """Record which roster character should lead, for mod-overseer to enforce.

    A flag rather than a command. `.group leader <name>` works, but only from a
    session carrying GM security, and a playerbot session does not have it:
    with account 318 at gmlevel 3, `.pinfo` and `.gps` issued as the bot are
    both refused. The whole kind='gm' path only works while a real client holds
    the character - so correcting leadership from here produced an error every
    cycle, forever, and never once worked.

    The module cannot decide this itself: it has no idea who these characters
    are to each other. bonds does, so the answer is written down here and
    enforced there.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            # `lead` BACKTICKED: it is a reserved word in MySQL 8 (the LEAD()
            # window function). Unquoted it is a syntax error - which took the
            # worldserver down in a crash loop when the module's SELECT hit it,
            # because the core treats a malformed query as unrecoverable.
            "UPDATE overseer_roster SET `lead` = IF(name = %s, 1, 0)", (head,)
        )


def _aim_traveller(quest_id: int) -> int:
    """Tell mod-overseer which quest the party leader should be working.

    WHY THE LEADER AND NOT THE BENEFICIARY. The family has exactly ONE
    traveller, on purpose. `new rpg` is what walks a character to a quest
    objective, and it runs at relevance 3.0-11.0 against `follow`'s 1.0, so a
    follower given both wanders off every tick - measured live at a 937-yard
    spread, with the healer 600 yards from the tank. goals.life_strategies
    keeps `new rpg` on the leader alone and that is not negotiable here; a
    quest goal changes WHERE the traveller goes, never WHO travels. The rest of
    the family arrives with him, on `nc +follow`, and a quest they all hold
    advances for all of them from the same kills.

    WHY A ROSTER COLUMN AND NOT AN overseer_command ROW. Commands are
    at-most-once and consumed. RPG_DO_QUEST self-expires after 30 minutes and
    the bot then re-rolls a RANDOM quest out of its own log, so an aim is a
    standing intent that has to survive both that and the leader relogging -
    which is what `lead` and `spec_tab` already are. The supervisor re-asserts
    on its own cadence (goals._reconcile_quest) and this write is idempotent.

    BY NAME, AND EVERY HOLDER, not the leader row (infra#2801, "quest
    together"). Aiming only the leader meant a follower's aim was written and
    never read, and since turn-in is reachable ONLY through the rpg strategy a
    follower that cannot be aimed can never hand anything in - which is exactly
    why four of them hoarded completed quests while the leader handed his own
    in. The aim is set for precisely the characters that HOLD the quest and
    cleared for everyone else: aiming a non-holder makes NewRpgDoQuestAction
    idle it on the next tick, and an unaimed follower carrying `new rpg`
    free-roams its own log, which is the 937-yard scatter. Cohesion comes from
    the shared destination, not from following.

    THE COLUMN CAN LEGITIMATELY BE ABSENT, exactly as spec_tab can: it arrives
    with mod-overseer's SQL, applied by the worldserver at startup, and the
    bridge is a separate deployment with its own restarts. Warned once rather
    than swallowed - an aim that never lands is a real fault and must be
    visible without being fatal.
    """
    holders = sorted(_holders_of(int(quest_id))) if quest_id else []
    with _connect() as conn, conn.cursor() as cur:
        try:
            if holders:
                marks = ", ".join(["%s"] * len(holders))
                # AIM EVERYONE WHO HOLDS IT. A follower that is never aimed can
                # never hand a quest in - turn-in is reachable only through the
                # rpg strategy - which is why four of them hoarded completed
                # quests while the leader handed his own in.
                cur.execute(
                    "UPDATE overseer_roster SET drive_quest = %%s "  # noqa: S608 - placeholders from a COUNT, values still bound
                    "WHERE name IN (%s)" % marks,
                    (int(quest_id), *holders),
                )
                aimed = cur.rowcount or 0
                # AND CLEAR EVERYONE ELSE. Aiming a character at a quest it does
                # not hold makes NewRpgDoQuestAction idle it on the next tick,
                # and an unaimed follower carrying `new rpg` free-roams its own
                # log, which is the 937-yard scatter. Both failure modes are
                # avoided by the aim being exactly the set of holders.
                cur.execute(
                    "UPDATE overseer_roster SET drive_quest = 0 "  # noqa: S608 - placeholders from a COUNT, values still bound
                    "WHERE drive_quest <> 0 AND name NOT IN (%s)" % marks,
                    tuple(holders),
                )
            else:
                cur.execute("UPDATE overseer_roster SET drive_quest = 0 "
                            "WHERE drive_quest <> 0")
                aimed = 0
        except pymysql.err.OperationalError as exc:
            # 1054 is ER_BAD_FIELD_ERROR. Matched on the code, not the message
            # text, which is localised and has changed between versions.
            if exc.args and exc.args[0] == 1054:
                log.warning(
                    "overseer_roster.drive_quest missing - aiming the party at "
                    "quest %d needs the worldserver image carrying "
                    "mod-overseer's SQL (infra#2597)", int(quest_id),
                )
                return 0
            raise
        log.info("aim: quest %d -> %d of the family (%s)",
                 int(quest_id), aimed, ", ".join(holders) or "nobody")
        return aimed



def _holders_of(quest_id: int) -> set:
    """Which protected characters actually hold this quest in an actionable
    state.

    The aim is only meaningful for a character that HOLDS the quest:
    NewRpgDoQuestAction dispatches on QUEST_STATUS_INCOMPLETE and
    QUEST_STATUS_COMPLETE and otherwise idles, so aiming anyone else is a
    silent no-op - the "delivered but nothing happened" failure this epic keeps
    repeating. Quest sharing (#2793) is what makes the holder set usually the
    whole family rather than one character.
    """
    if not quest_id:
        return set()
    names = sorted((_protected_guids()).values())
    if not names:
        return set()
    marks = ", ".join(["%s"] * len(names))
    sql = (
        "SELECT c.name FROM characters c "  # noqa: S608 - placeholders from a COUNT, values still bound
        "JOIN character_queststatus q ON q.guid = c.guid "
        "WHERE c.name IN (%s) AND q.quest = %%s AND q.status IN (1, 3)" % marks
    )
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (*names, int(quest_id)))
        return {row["name"] for row in cur.fetchall()}



def _aim_for_plea(caller: str, helpers: list, about: str = "") -> int:
    """Point the family at what the caller actually asked for.

    THE FAILURE THIS EXISTS TO FIX. In Evan's Discord on 2026-08-24, at 14:35,
    15:06 and 16:05, Ugga says she needs one more Large Candle and all four
    agree to help her. Nothing happens, three times, hours apart. She sat at 7
    of 8 for quest 60 throughout. The muster wrote a regroup command and a
    memory, and that was the whole of "helping" - the family said yes and
    carried on with what they were already doing.

    WHICH QUEST. The caller's own INCOMPLETE quests, because a complete one
    needs no help - it needs a walk to a questgiver, which is the caller's
    own errand and not a favour anyone can do for them. Of those, only a quest
    at least one helper ALSO holds is a candidate: aiming a helper at a quest
    it does not hold makes NewRpgDoQuestAction idle it on the next tick, so a
    helper who cannot act on it is worse than no helper at all - it looks like
    help and is not. Quest sharing (#2793) is what usually makes such a
    candidate exist.

    WHAT THEY ASKED FOR WINS. Ugga holds six incomplete quests; the most
    widely-held is Bounty on Murlocs, and picking by popularity would send the
    family off to kill murlocs while she stood there still wanting a candle.
    She NAMED the quest - "1 more Large Candle for Kobold Candles" - so the
    plea text is matched against quest titles first, and only if nothing
    matches does it fall back to the quest most of them hold. Helping someone
    with a thing they did not ask for is its own kind of not listening.

    Returns the number of characters aimed; 0 means nothing shared could be
    found, and in that case nobody is aimed at all. A false aim would be the
    same empty promise in a new place.
    """
    names = sorted((_protected_guids()).values())
    if not names or not caller:
        return 0
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT q.quest FROM characters c "
            "JOIN character_queststatus q ON q.guid = c.guid "
            "WHERE c.name = %s AND q.status = 3",
            (caller,),
        )
        wanted = [int(row["quest"]) for row in cur.fetchall()]
    if not wanted:
        log.info("plea aim: %s holds no incomplete quest to be helped with", caller)
        return 0

    party = set(helpers) | {caller}
    best, named = _pick_plea_quest(wanted, party, about)
    if not best:
        log.info(
            "plea aim: nothing %s needs is held by any helper (%s) - not aiming; "
            "quest sharing has to catch up first", caller, ", ".join(helpers) or "none")
        return 0
    aimed = _aim_traveller(best)
    # Re-read the ONE title rather than reaching for the picker's local map:
    # `titles` lives inside _pick_plea_quest since the complexity split, and
    # naming it here raised NameError on every answered plea - after the aim
    # had already been written, so the errand landed and the line that says so
    # never printed. Swallowed whole by the best-effort handler in
    # _aim_after_muster, which is why it survived review and a merge.
    title = _quest_titles([best]).get(best, "?")
    log.info("plea aim: %s asked%s, family aimed at quest %d (%s) - %d aimed",
             caller, " by name" if named else " (no title matched, took the "
             "most widely held)", best, title, aimed)
    return aimed



def _pick_plea_quest(wanted: list, party: set, about: str) -> tuple:
    """Choose which of the caller's quests the family should be aimed at.

    Split out of _aim_for_plea to keep both readable (Grug - Elder, cyclomatic
    cap). Returns (quest_id, was_named); 0 means no candidate.

    A candidate needs at least TWO holders inside the party: the caller alone
    is not help, and aiming a helper at a quest it does not hold idles it on
    the next tick. Among candidates, one whose title the plea actually names
    wins outright over one merely held by more of them - see the caller's
    docstring for why that ordering is load-bearing.
    """
    asked = (about or "").lower()
    titles = _quest_titles(wanted)
    best, best_holders = 0, 0
    for quest_id in wanted:
        holders = _holders_of(quest_id) & party
        if len(holders) < 2:
            continue
        title = (titles.get(quest_id) or "").lower()
        if title and title in asked:
            return quest_id, True
        if len(holders) > best_holders:
            best, best_holders = quest_id, len(holders)
    return best, False


def _quest_titles(quest_ids: list) -> dict:
    """Titles for a handful of quest ids, so a plea can be matched by name."""
    ids = [int(q) for q in quest_ids if q]
    if not ids:
        return {}
    marks = ", ".join(["%s"] * len(ids))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ID, LogTitle FROM acore_world.quest_template "  # noqa: S608 - placeholders from a COUNT, values still bound
            "WHERE ID IN (%s)" % marks, tuple(ids))
        return {int(r["ID"]): r["LogTitle"] for r in cur.fetchall()}


def _mark_specs(specs: dict) -> None:
    """Write each character's talent tree onto the roster.

    WHY THE BRIDGE. Same division as the party leader: the module knows a
    character's class and level and nothing about who it is, and a spec is a
    role. bonds holds the roles, so bonds is where the answer comes from.

    WHY IT IS WRITTEN EVERY CYCLE. The module reads this column to decide where
    to spend talent points, and a role changed in bonds has to be able to reach
    a character that is already on the roster - an INSERT-time-only value would
    make every later decision unreachable without a hand-edit of the game DB.

    Rewriting an unchanged value costs one indexed UPDATE against five rows and
    does NOT cause retraining: the module gates that on trained_level and on
    there being free points to spend, neither of which this touches.

    THE COLUMN CAN LEGITIMATELY BE ABSENT. It arrives with mod-overseer's SQL,
    which is applied by the worldserver on startup, and the bridge is a separate
    deployment with its own image and its own restarts. Any order is possible: a
    bridge that rolls before the worldserver, a bridge that crash-restarts on a
    cluster whose worldserver has not come up yet, a cold start of the whole
    namespace. Without this the first cycle raises and takes the REST of that
    cycle with it - the randomize guards that keep these characters from being
    re-rolled are written further down the same loop body.

    Warned once per cycle rather than swallowed, for the same reason
    _ensure_roster says so out loud: a column that never appears is a real
    fault, and it should be visible without being fatal.
    """
    if not specs:
        return
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.executemany(
                "UPDATE overseer_roster SET spec_tab = %s WHERE name = %s",
                [(tab, name) for name, tab in sorted(specs.items())],
            )
        except pymysql.err.OperationalError as exc:
            # 1054 is ER_BAD_FIELD_ERROR. Matched on the code rather than on the
            # message text, which is localised and has changed between versions.
            if exc.args and exc.args[0] == 1054:
                log.warning(
                    "overseer_roster.spec_tab missing - talent trees need the "
                    "worldserver image carrying mod-overseer's SQL (infra#2756)"
                )
                return
            raise


# How long a decided-but-unsettled learn errand may move the family's
# leadership around.
#
# WHY THERE IS A BOUND AT ALL. An errand takes the head of the family off the
# character bonds says should have it and gives it to whoever is going to a
# trainer. That is right while the errand is live and wrong the moment it is
# not - and "not live" has a failure mode with no error in it: mod-overseer
# clears `learn_skill` when the trade is bought, so a worldserver that has not
# been built with the professions verbs yet NEVER clears it. Without a bound,
# one undeployed image would quietly and permanently reorganise the family
# around an errand nothing can finish.
#
# Six hours, because the errand is one walk on one map and the travel drive's
# own backstop gives up after twenty minutes. Anything still outstanding after
# six hours is not a slow journey, it is a broken one.
ERRAND_LEAD_HOURS = float(os.environ.get("ERRAND_LEAD_HOURS", "6"))


def _write_declared_professions() -> None:
    """Write each character's ASSIGNED primaries onto the roster.

    THIS IS THE PERMISSION, NOT A HINT, and that is why it is written on the
    protect cycle next to the talent trees rather than once when a trade is
    decided. mod-overseer will only ever learn a skill that appears here and
    will never unlearn one that does, so this column is what makes a wrong
    `learn_skill` or a stale `unlearn_skill` harmless. A permission that is
    written only when an errand is created is a permission that is missing for
    every character that does not currently have one - including Ugga, who
    needs no errand precisely because she is already correct, and whose two
    professions must still be declared so that nothing can take them.

    Same shape and same degrade as _mark_specs, for the same reasons.
    """
    values = [
        (professions.wanted_ids(name), name)
        for name in sorted(bonds.FAMILY)
        if professions.assigned(name)
    ]
    if not values:
        return
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.executemany(
                "UPDATE overseer_roster SET professions = %s WHERE name = %s", values
            )
        except pymysql.err.OperationalError as exc:
            # 1054 is ER_BAD_FIELD_ERROR. Matched on the code, not the message
            # text, which is localised and has changed between versions.
            if exc.args and exc.args[0] == 1054:
                log.warning(
                    "overseer_roster.professions missing - the family's trade "
                    "assignment cannot reach the worldserver until the "
                    "db-import image carrying mod-overseer's SQL has shipped "
                    "(infra#2757)"
                )
                return
            raise


# The travel roles the ECONOMY may aim, as opposed to the ones the trade
# plan owns. Both of these are town errands the family runs and comes back
# from; a profession trainer errand is a standing plan that outlives them,
# so an economy pass may only retask a traveller that is idle or already
# doing the same errand (see the UPDATE guard below). travel.ROLES is the
# vocabulary these come from, and mod-overseer's DriveTravel is what reads
# the column.
# `repair` joined for the town trip: it walks the leader to a repairer,
# and it is an economy errand for the same reason the other two are - it
# may be retasked off an idle traveller but must never erase a profession
# trainer errand somebody is already walking to.
ECONOMY_ERRANDS = ("vendor", "banker", "repair")


def _write_trade_errand(errand) -> bool:
    """Put one character's outstanding trade plan where the worldserver reads it.

    RETURNS WHETHER THE AIM WAS ACTUALLY TAKEN (infra#3464). The economy guard
    below only retasks an IDLE traveller, so a vendor aim written while the
    town-trip pass owns `travel_npc = repair` matches no row and changes
    nothing. That was silent: the update ran, the pass carried on, and it
    queued a queue-full of sales for a journey nobody had been sent on.
    Measured on the live realm over three hours, 1,950 sell rows ended in
    error and 1,860 of them said `vendor not in range`.

    THE ROAD THAT WAS MISSING. professions.plan() has been reaching the right
    answer since 2026-08-26 and writing it to `overseer_trade`, which is a
    Python table nothing in the worldserver has ever read. These four columns
    are on `overseer_roster`, which mod-overseer polls.

    IDEMPOTENT AND RE-ASSERTED, not written once. mod-overseer clears
    `learn_skill` and `unlearn_skill` itself when each verb succeeds, so
    re-writing an errand every trade cycle either changes nothing (still
    outstanding) or is skipped entirely (the plan is empty because the trade
    settled). What it protects against is the case in between: a worldserver
    restart loses runtime state, and an errand that had been half-applied would
    otherwise need somebody to notice.

    `travel_npc` IS WRITTEN HERE AND NOWHERE ELSE IN THIS PROCESS. It is the
    only column that makes a character walk, and the only reason to make one
    walk is an errand.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            if errand.travel_npc in ECONOMY_ERRANDS:
                # Economy must never erase a profession trainer errand. A
                # vendor or bank pass may coexist with a stale row, but only
                # an idle traveller can be retasked for the town run.
                cur.execute(
                    "UPDATE overseer_roster SET travel_npc = %s "
                    "WHERE name = %s AND (travel_npc = '' OR travel_npc = %s)",
                    (errand.travel_npc, errand.character, errand.travel_npc),
                )
                # rowcount 0 is "somebody else's errand owns this traveller",
                # which is a legitimate outcome and not an error - but it means
                # nobody is walking anywhere, and the caller has to know.
                return bool(cur.rowcount)
            else:
                cur.execute(
                    "UPDATE overseer_roster SET learn_skill = %s, unlearn_skill = %s, "
                    "unlearn_max = %s, travel_npc = %s WHERE name = %s",
                    (
                        errand.learn_skill,
                        errand.unlearn_skill,
                        errand.unlearn_max,
                        errand.travel_npc,
                        errand.character,
                    ),
                )
        except pymysql.err.OperationalError as exc:
            if exc.args and exc.args[0] == 1054:
                log.warning(
                    "overseer_roster is missing the profession errand columns - "
                    "%s cannot be sent to a trainer until the db-import image "
                    "carrying mod-overseer's SQL has shipped (infra#2757)",
                    errand.character,
                )
                return False
            raise
    return True


# THE overseer_* TABLES DO NOT SHARE ONE COLLATION, AND THIS SIDE CANNOT FIX
# THAT (infra#3173). Read this before writing any join between two of them.
#
# mod-overseer creates them across many migrations, and the ones created before
# the server's default moved carry a different collation from the ones created
# after. Measured on both realms on 2026-09-02:
#
#     utf8mb4_unicode_ci   overseer_roster, overseer_event, overseer_death
#     utf8mb4_0900_ai_ci   overseer_snapshot, overseer_trade, overseer_command,
#                          overseer_thought, overseer_goal, overseer_chat,
#                          overseer_chat_watch, overseer_stream,
#                          overseer_dungeon_run, overseer_sample
#
# Comparing a name column from the first group against one from the second
# raises MySQL 1267, "Illegal mix of collations": both operands are IMPLICIT,
# neither outranks the other, and MySQL fails the WHOLE statement rather than
# returning fewer rows. It is not a bad row, it is every row - measured at six
# raises in twenty minutes on dev, taking the protect cycle and the life
# recheck down with them.
#
# SO ANY JOIN THAT CROSSES THE TWO GROUPS ON A NAME MUST CARRY AN EXPLICIT
# `COLLATE utf8mb4_unicode_ci`, written on the operand from the
# utf8mb4_0900_ai_ci side. COLLATE is EXPLICIT coercibility, which outranks
# both IMPLICIT sides and settles the whole predicate in one collation.
# utf8mb4_unicode_ci is the one to name because it is what overseer_roster.name
# already is, so the roster's own index stays usable and only the joined side is
# converted. The two collations differ only in Unicode version, and every value
# compared here is an ASCII character name, so no pair that matched before stops
# matching. tests/test_collation_split.py fails the suite on a new join written
# without it, which is the only reason this comment is not the whole defence.
#
# A JOIN AGAINST `characters` NEEDS NONE OF THIS, and must not be given it:
# characters.name is utf8mb4_bin, a binary collation already outranks either
# group on its own, and forcing utf8mb4_unicode_ci onto it would quietly turn an
# exact-match join into a case- and accent-insensitive one.
#
# Normalising the tables belongs to mod-overseer, which owns the DDL. The bridge
# has to work against the realms that already have the split, today.
def _errand_traveller() -> str:
    """The character that must lead the family right now, or '' for nobody.

    THIS IS THE WHOLE ANSWER TO "A FOLLOWER CANNOT RUN AN ERRAND", and it is
    worth being explicit about what it is NOT. It is not giving a follower
    `new rpg`. `new rpg` is what walks a character to an NPC, it acts at
    relevance 3.0-11.0 against follow's 1.0, and a follower carrying both
    wanders off every tick - measured at a 937-yard spread with the healer in
    her own fight (infra#2812). Nothing here changes who carries it.

    What changes is WHO LEADS. The family has exactly one traveller by design;
    this makes the traveller be the character with somewhere to be, and the
    other four follow it there. Every piece of machinery that needs is already
    built and is untouched: `lead` is written by _mark_party_leader,
    KeepRosterGrouped promotes that character to group leader, and
    KeepRosterFollowing points the rest at whoever the group leader actually
    is. The invariant holds throughout - one `new rpg`, on the leader - and the
    party arrives at the trainer together.

    THE JOIN IS THE BOUND, and it is doing three jobs. It requires the roster
    errand to still be set, the `overseer_trade` row behind it to still be
    'planned', and the decision to be recent. Any one of those going false
    hands leadership back to bonds.head_of_family() on the next protect cycle -
    which is what makes an undeployed worldserver a no-op rather than a
    permanent reorganisation of the family around an errand nothing can finish.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT r.name FROM overseer_roster r "
                # overseer_roster is utf8mb4_unicode_ci and overseer_trade is
                # utf8mb4_0900_ai_ci, so this predicate crosses the split - see
                # the block above the def. Without the COLLATE this is MySQL
                # 1267, every cycle, for as long as both tables exist.
                "JOIN overseer_trade t "
                "  ON t.character_name COLLATE utf8mb4_unicode_ci = r.name "
                "WHERE r.enabled = 1 AND r.learn_skill <> 0 "
                "AND t.verb = 'learn' AND t.skill_id = r.learn_skill "
                "AND t.status = 'planned' "
                "AND t.decided_at > NOW() - INTERVAL %s HOUR "
                "ORDER BY t.id LIMIT 1",
                (ERRAND_LEAD_HOURS,),
            )
            row = cur.fetchone()
        except pymysql.err.MySQLError as exc:
            # 1054 is a missing column, 1146 a missing table. Either means the
            # errand machinery is not deployed here, and the honest answer to
            # "who is on an errand" is nobody.
            if exc.args and exc.args[0] in (1054, 1146):
                return ""
            # ANYTHING ELSE IS LOGGED LOUDLY AND STILL ANSWERS "nobody", rather
            # than being re-raised (infra#3173). Re-raising is what let one
            # query cost a whole cycle. Both the protect cycle and the life
            # recheck reach this through _give_them_a_life, a third of the way
            # in, so a 1267 here took every later step with it - the declared
            # professions, the spec tabs, the randomize guards, the report -
            # none of which have anything to do with an errand.
            #
            # This is a poll loop, and that is what makes the trade right. The
            # caller's question has a safe answer: nobody is travelling, so
            # leadership falls back to bonds.head_of_family(), which is the
            # resting state anyway and is re-decided from scratch on the next
            # cycle. Nothing is written on this path, so a wrong "nobody" costs
            # one cycle of a slower errand and can corrupt nothing.
            #
            # It is not swallowed, and this is not a quiet degrade like the two
            # codes above. log.exception writes the traceback at ERROR every
            # cycle the fault persists - exactly as often as the loop's own
            # handler used to, because the loop runs just as often either way -
            # so nothing that was visible before becomes invisible now. It is
            # scoped to pymysql's own base class rather than Exception, so a bug
            # in this function still propagates instead of being reported as a
            # database problem.
            log.exception(
                "errand traveller lookup failed; leading the family by seniority "
                "this cycle"
            )
            return ""
    return row["name"] if row else ""


def _train_members() -> list:
    """The roster rows `job = train` is decided from, with the skills observed.

    TWO READS AND NO JOIN, deliberately. `character_skills` is keyed by guid and
    `overseer_roster` by name, and the collation split documented above this
    file's other cross-table read makes every such join a thing to get right
    once and then never notice again. There is no ordering requirement between
    the two, five rows come back from each, and a plan built from a roster row
    with no skills observed simply has an empty `holds` - which trainjob treats
    as "not held", the conservative direction.

    Guarded for 1146 and 1054 like every other overseer_* read: a realm whose
    db-import image predates the profession columns has no errand to drive, and
    the honest answer there is an empty family rather than an exception that
    costs the whole protect cycle.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT name, job, professions, learn_skill "
                "FROM overseer_roster WHERE enabled = 1"
            )
            rows = list(cur.fetchall())
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                return []
            raise
        if not rows:
            return []
        held: dict = {}
        try:
            cur.execute(
                "SELECT c.name AS name, s.skill AS skill "
                "FROM character_skills s JOIN characters c ON c.guid = s.guid "
                "WHERE c.name IN (%s)" % ", ".join(["%s"] * len(rows)),  # noqa: S608 - placeholders from a COUNT, values still bound
                tuple(r["name"] for r in rows),
            )
            for row in cur.fetchall():
                held.setdefault(row["name"], []).append(int(row["skill"]))
        except pymysql.err.MySQLError as exc:
            # `characters` and `character_skills` are core tables, so 1146 here
            # means something much stranger than a missing migration. It is
            # still not worth an exception: an unobserved family produces no
            # errand, which is the same refusal an observed one with nothing
            # outstanding produces.
            if not (exc.args and exc.args[0] in (1054, 1146)):
                raise
            log.warning("character_skills is unreadable; train can decide nothing")
        return [
            trainjob.Member(
                name=row["name"],
                job=row["job"] or "",
                wanted=trainjob.parse_wanted(row["professions"]),
                learn_skill=int(row["learn_skill"] or 0),
                holds=tuple(sorted(held.get(row["name"], ()))),
            )
            for row in rows
        ]


def _train_traveller() -> str:
    """Who must lead the family because `job = train` is sending them somewhere.

    Asked from _head_now, ahead of the trade errand and ahead of seniority, and
    it answers '' for every family that is not on this mode - so the resting
    order of leadership is untouched by this file existing.

    IT OUTRANKS _errand_traveller ON PURPOSE. That function is bounded by
    ERRAND_LEAD_HOURS against `overseer_trade.decided_at`, which is the right
    bound for a plan the family drifted into and the wrong one for an order a
    person just gave: an operator saying "go train" at hour seven of a
    six-hour-old plan would otherwise be told nothing and see nobody move
    (quadseven/mod-overseer#167). The job column IS the standing intent, so
    while it says train there is no staleness to bound.
    """
    try:
        return trainjob.plan(_train_members()).traveller
    except pymysql.err.MySQLError:
        # Same contract as _errand_traveller's own handler: loudly logged,
        # still answers "nobody", never costs the caller its cycle.
        log.exception("train traveller lookup failed; leading by seniority this cycle")
        return ""


def _aim_train_traveller(statements) -> None:
    """Run trainjob's aim, in order, on one cursor.

    The statements are BUILT IN THE PURE MODULE and only executed here, which
    is the same seam travel.aim_statements was written for: the aim and its
    clearing half are one decision, they are tested without a database, and
    this function has no opinion it could get wrong.
    """
    with _connect() as conn, conn.cursor() as cur:
        for sql, params in statements:
            try:
                cur.execute(sql, params)
            except pymysql.err.MySQLError as exc:
                if exc.args and exc.args[0] in (1054, 1146):
                    log.warning(
                        "overseer_roster has no travel_npc column - the family "
                        "cannot be sent to a trainer on this realm (infra#2783)"
                    )
                    return
                raise


# WHO THE PARTY FOLLOWS WHEN SENIORITY WOULD STRAND IT. Normally None, and
# then nothing changes: the father leads, as he always has.
#
# Set when the resting head is bound on a continent the family is not working
# on, because REVIVAL USES THE GROUP LEADER'S BIND AND NEVER THE CHARACTER'S
# OWN (mod_overseer.cpp, RevivalHome reads group->GetLeaderGUID()). Every
# death therefore gathers all five wherever the leader is bound, so a leader
# bound across an ocean turns every death into a party split, and no drive in
# the module can rejoin one.
#
# DELIBERATELY NOT bonds.head_of_family(). That answer is the family's, not
# the logistics', and other things read it as story: speaking_order puts the
# head first in every digest, and bonds.SUSPICION is asserted to be the head's
# because the jealousy is the father's. Overriding there would have made the
# man he is suspicious of the head of his family, and changed who narrates the
# day. This seam already exists for exactly this shape: an errand borrows the
# lead here without anybody's standing changing.
#
# WHICH CHARACTER, AND WHY IT MOVED. It is no longer only about the bind.
# The route to the dungeon door was replayed against the shipped heightmaps
# from both places the family could stage from, and the same code opens a run
# or fails purely on which one it walks out of:
#
#     from the mountains   7.5 to 24 minutes   against a 12 minute window
#     from the port town   4 to 7 minutes      against the same window
#
# So the lead is the character bound at the port town on the working
# continent, and the family gathers on flat ground beside the dungeon rather
# than in a mountain range with a wall between it and the door. The bind
# argument above still holds and now points the same way: every death sends
# all five to the leader's bind, and that bind is now somewhere worth being.
#
# REMOVE IT once the resting head can be bound on the family's own continent
# AND can walk out of where it stands. The crossing is no longer the blocker
# it was when this was written: a character can now reach the other continent
# on its own hearthstone, and a split party can be rejoined on the game's own
# summoning stone (quadseven/mod-overseer#308, #313). What remains is routing
# around terrain (quadseven/mod-overseer#316).
HOMEWARD_LEAD: str | None = "Grog"


def _head_now() -> str:
    """Who leads the family this cycle.

    bonds.head_of_family() is the resting answer and the overwhelmingly common
    one: Grug, the father, by seniority, forever. An errand borrows it, because
    the leader is the family's one traveller and an errand is somewhere to
    travel to. A standing `job = train` borrows it FIRST - see
    _train_traveller for why an order a person just gave outranks a plan the
    family drifted into. Asked in exactly two places - _give_them_a_life,
    which hands out the strategies, and _mark_party_leader, which writes the
    flag - so those
    two can never be looking at different answers to the same question. Getting
    that wrong is a family following a character that is about to stop leading,
    which is a party split in two. HOMEWARD_LEAD above outranks seniority and
    is outranked by both borrowers, because a character actually walking
    somewhere is a better leader for that moment than one merely bound well.
    """
    return (_train_traveller() or _errand_traveller()
            or HOMEWARD_LEAD or bonds.head_of_family())


def _protected_guids() -> dict:
    """guid -> name for the characters we refuse to let be re-rolled.

    Reads the same OVERSEER_NOTABLE_NAMES the story filter uses: a
    character worth following is a character worth protecting, and one
    list is easier to keep honest than two.
    """
    names = [n.strip() for n in os.environ.get("OVERSEER_NOTABLE_NAMES", "").split(",") if n.strip()]
    if not names:
        return {}
    placeholders = ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        # Static shape, parameterized values - the list length is ours, the
        # contents never reach SQL as text.
        cur.execute(
            "SELECT guid, name FROM characters WHERE name IN (%s)" % placeholders,
            names,
        )
        return {r["guid"]: r["name"] for r in cur.fetchall()}


def _randomize_rows(guids: list) -> dict:
    if not guids:
        return {}
    placeholders = ",".join(["%s"] * len(guids))
    conn = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        user="root",
        password=os.environ["MYSQL_ROOT_PASSWORD"],
        database="acore_playerbots",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5, read_timeout=10, write_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bot, time, validIn FROM playerbots_random_bots "
                "WHERE event = 'randomize' AND owner = 0 AND bot IN (%s)" % placeholders,
                guids,
            )
            return {r["bot"]: r for r in cur.fetchall()}
    finally:
        conn.close()


def _write_randomize_guard(guid: int, now: int) -> None:
    conn = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        user="root",
        password=os.environ["MYSQL_ROOT_PASSWORD"],
        database="acore_playerbots",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5, read_timeout=10, write_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            # DELETE+INSERT rather than UPSERT: the table has an
            # auto_increment id and no unique key on (owner, bot, event),
            # so ON DUPLICATE KEY would never fire and we would pile up
            # rows the manager then reads unpredictably.
            cur.execute(
                "DELETE FROM playerbots_random_bots "
                "WHERE event = 'randomize' AND owner = 0 AND bot = %s",
                (guid,),
            )
            cur.execute(
                "INSERT INTO playerbots_random_bots (owner, bot, time, validIn, event, value) "
                "VALUES (0, %s, %s, %s, 'randomize', 1)",
                (guid, now, protect.PROTECT_HORIZON_SECONDS),
            )
    finally:
        conn.close()


def _fetch_notable_names() -> set:
    """Characters whose heartbeat is worth recording, not just their arc.

    Mortals (a real person is playing), anyone under an active goal, and
    the reserved characters from OVERSEER_NOTABLE_NAMES. Everyone else
    contributes level ups and zone changes but not combat chatter - see
    events.filter_for_story.
    """
    names = {
        n.strip() for n in os.environ.get("OVERSEER_NOTABLE_NAMES", "").split(",") if n.strip()
    }
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM overseer_snapshot "
            "WHERE is_bot = 0 AND updated_at > NOW() - INTERVAL 60 SECOND"
        )
        names.update(r["name"] for r in cur.fetchall())
        try:
            cur.execute(
                "SELECT character_name FROM overseer_goal WHERE status = 'active'"
            )
            names.update(r["character_name"] for r in cur.fetchall())
        except Exception:
            # The goal store is created by on_ready; a cycle that lands
            # first must not lose the mortals it already collected.
            log.debug("goal store not ready yet; notable set is mortals only")
    return names


def _fetch_event_snapshot() -> list[dict]:
    # Freshness-filtered like _fetch_roster on purpose: a stale row means
    # the character left the world, and events.detect_events treats a
    # disappearance as churn rather than story - this filter is what makes
    # logouts (and logins, on the reappearance side) silent.
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, level, map_id, zone_id, pos_x, pos_y, health, in_combat "
            "FROM overseer_snapshot WHERE updated_at > NOW() - INTERVAL 60 SECOND"
        )
        return list(cur.fetchall())


class Bridge(discord.Client):
    def __init__(self, allowed_ids: frozenset[str]):
        intents = discord.Intents.default()
        intents.message_content = True
        # Nothing this bridge sends may ever ping anyone. It relays untrusted
        # world chat and LLM-generated text, so the guarantee belongs at the
        # client rather than in each call site's formatting: Discord will not
        # resolve @everyone, @here, a role or a user in ANY message from this
        # process, whatever the text turns out to contain.
        super().__init__(
            intents=intents, allowed_mentions=discord.AllowedMentions.none()
        )
        self._allowed = allowed_ids
        # Row id -> the channel its directive came from. Only rows this
        # process inserted are ever reported, which is core.py's restart
        # contract: history is never re-announced.
        self._pending: dict[int, discord.abc.Messageable] = {}
        self._seen: set[int] = set()
        # (oldest row id, consecutive send failures) for the chat relay.
        self._stuck: tuple[int, int] = (0, 0)
        # Monotonic clock of the last kin muster, so a fight that produces
        # several pleas answers once. None means "never" - deliberately not 0.0,
        # which on a monotonic clock is a real moment the process may be near.
        self._last_muster_at: float | None = None
        self._last_overheard_at: float | None = None
        # Every INTENT this process has already said out loud, and when
        # (monotonic). chat.should_say reads it, chat.remember_said prunes it.
        # The same shape as the two clocks above, one per conversation rather
        # than one per feature: a handover and a craft answer are different
        # things to say and must not silence each other, while the SAME
        # handover said twice is the whole of infra#3197.
        self._said: dict = {}

    async def setup_hook(self) -> None:
        # Held, not fired and forgotten. asyncio keeps only a weak reference to
        # a running task, so one with no other referent can be garbage
        # collected mid-flight - and the loop it was running simply stops, with
        # no error and nothing in the log. Every loop in this service is a
        # forever-loop, so that failure would read as the feature quietly not
        # working, which is the shape this repo keeps meeting.
        self._loops = {
            asyncio.create_task(coro())
            for coro in (
                self._poll_outcomes,
                self._protect_characters,
                self._narrate_events,
                self._supervise_goals,
                self._relay_chat,
                self._hold_council,
                self._assign_trades,
                self._sample_family,
                self._share_quests_loop,
                self._move_materials_loop,
                self._vendor_loop,
                self._bank_loop,
                self._towntrip_loop,
                self._restore_lost_lives,
            )
        }

    async def on_ready(self) -> None:
        log.info("connected as %s", self.user)
        if not self.guilds:
            # A gateway connection succeeds with zero guilds and then hears
            # nothing forever - exactly how the never-invited bot hid for an
            # hour on 2026-08-21. Say so where DD can alert on it.
            log.error("connected but in ZERO guilds - the bot cannot hear anything")
        await asyncio.to_thread(_ensure_thought_store)
        await asyncio.to_thread(_ensure_goal_store)
        await asyncio.to_thread(_ensure_sample_store)
        await asyncio.to_thread(_ensure_trade_store)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        # Not mine, not my business. See OWNED_CHANNEL_IDS: without this, a
        # directive typed in the dev channel is executed by BOTH bridges, and
        # the production one runs it on the live family.
        if OWNED_CHANNEL_IDS and str(message.channel.id) not in OWNED_CHANNEL_IDS:
            return
        dedicated = OVERSEER_CHANNEL_ID and str(message.channel.id) == OVERSEER_CHANNEL_ID
        decisions = core.parse_directive(
            message.content, str(message.author.id), self._allowed, dedicated=bool(dedicated)
        )
        for decision in decisions:
            await self._act_on(decision, message.channel)

    # Decision type -> the adapter that queues it, and what to call it in the
    # log. All three do the same three things, so they are a table rather than
    # three near-identical branches.
    _QUEUED = (
        (core.InsertCommand, _insert_command, "command"),
        (relay.SpeakCommand, _insert_speak, "chat line"),
        (relay.GmCommand, _insert_gm, "gm command"),
    )

    async def _act_on(self, decision, channel) -> None:
        """Carry out one parsed decision."""
        for kind, insert, label in self._QUEUED:
            if isinstance(decision, kind):
                row_id = await asyncio.to_thread(insert, decision)
                # Remembering the channel is what lets the outcome poller
                # report back to wherever the order was given.
                self._pending[row_id] = channel
                log.info("queued %s %s for %s", label, row_id, decision.target_name)
                return

        if isinstance(decision, core.NLDirective):
            await self._interpret(decision, channel)
        elif isinstance(decision, core.FanoutCommand):
            await self._muster(decision, decision.command, channel)
        elif isinstance(decision, core.FanoutDirective):
            await self._conjure(decision, channel)
        elif isinstance(decision, core.JobDirective):
            await self._set_job(decision, channel)
        elif isinstance(decision, core.RosterQuery):
            rows = await asyncio.to_thread(_fetch_roster)
            await channel.send(core.format_roster(rows).text[:1990])
        elif isinstance(decision, core.DigestQuery):
            await self._report_digest(decision, channel)
        else:
            await channel.send(decision.text)

    async def _interpret(self, d: core.NLDirective, channel) -> None:
        """Natural language -> vocabulary command via the inner voice.

        Ticket contract (infra#2600): an LLM outage degrades to raw relay
        with a plain acknowledgment - an order is never silently dropped.
        """
        # Goal-shaped orders skip the voice: they persist a supervised goal
        # (infra#2601) instead of becoming a one-shot command.
        if await self._maybe_handle_goal(d, channel):
            return
        grounding = await asyncio.to_thread(_fetch_grounding, d.target_name)
        if grounding is None:
            await channel.send(f"{d.target_name} is not in the world right now.")
            return
        prompt = voice.build_prompt(
            name=grounding["name"],
            level=grounding["level"],
            race_name=RACE_NAMES.get(grounding["race"], "creature"),
            class_name=CLASS_NAMES.get(grounding["class"], "adventurer"),
            zone=GEO.zone_name(grounding["map_id"], grounding["pos_x"], grounding["pos_y"]),
            personality=_persona_for(grounding),
            text=d.text,
        )
        try:
            decision = voice.parse_decision(await asyncio.to_thread(_ask_llm, prompt))
        except Exception:
            log.exception("inner voice unreachable; relaying raw")
            row_id = await asyncio.to_thread(
                _insert_command, core.InsertCommand(d.target_name, d.text, d.source)
            )
            self._pending[row_id] = channel
            await channel.send(
                f"The voice is silent, so I passed your words to {d.target_name} untranslated."
            )
            return
        await asyncio.to_thread(_insert_thought, d.target_name, "command", d.text)
        await asyncio.to_thread(_insert_thought, d.target_name, "chat", decision.say)
        if decision.command is None:
            await channel.send(decision.say)
            return
        row_id = await asyncio.to_thread(
            _insert_command, core.InsertCommand(d.target_name, decision.command, d.source)
        )
        self._pending[row_id] = channel
        await channel.send(f"{decision.say}  [{decision.command}]")

    async def _answer_pleas(self, rows: list[dict], channel) -> None:
        """Answer a call for help, and never let doing so break the relay.

        The guard lives here rather than at the call site so `_relay_chat`
        keeps one branch fewer - it was already at Elder's cyclomatic cap.
        Swallowing is deliberate and total: every failure inside is logged,
        and chat relaying must continue regardless.
        """
        try:
            await self._muster_for_pleas(rows, channel)
        except Exception:
            log.exception("kin muster failed; chat relay continues")

    async def _answer_craft_asks(self, rows: list[dict], channel) -> None:
        """Answer "who can make X" / "need a bag" (infra#2829), best-effort.

        Same swallow-everything contract as _answer_pleas, for the same
        reason: chat relaying is the product, and a craft answer is a bonus
        on top of it that must never be able to break the relay.
        """
        try:
            await self._speak_craft_asks(rows, channel)
        except Exception:
            log.exception("craft ask answering failed; chat relay continues")

    async def _speak_craft_asks(self, rows: list[dict], channel) -> None:
        """Read the lines the relay just fetched; name the crafter for any
        that ask for one.

        Only bot speech is considered, same as _muster_for_pleas - a human
        asking "who can make bags" in game is talking to a person, not
        summoning a scripted answer. At most one per tick, the same
        restraint _muster_for_pleas gives a burst of pleas: a fight or a
        busy channel should not turn into several characters all naming
        crafters at once.

        `channel` is accepted only to match _answer_pleas's shape; nothing is
        posted to Discord here. The answer is spoken IN THE WORLD, through
        the same party-chat path council.py and professions.py already
        speak through - that is the whole point of #2829 ("in party chat, in
        character, using the existing voice layer"), not a bot reply in a
        text channel nobody in the family can hear.
        """
        heard = [
            ((row.get("text") or "").strip(), a)
            for row in rows
            if row.get("sender_is_bot")
            for a in (craftpleas.parse_ask(
                row.get("sender_name") or "", row.get("text") or ""
            ),)
            if a is not None
        ]
        if not heard:
            return
        # NOT ITS OWN ECHO. overhear.py already tells an order from the
        # bridge's own speech this way, and the craft answer needed it for the
        # same reason: every line the family says comes back through this
        # relay, so an answer that mentions cloth reads as an ask about cloth
        # unless something says otherwise. craftpleas now refuses to let a
        # crafter answer itself as well - both guards, because they fail on
        # different halves of the loop, and the read below costs one query
        # only once something has actually asked for something.
        authored = await asyncio.to_thread(_authored_lines)
        asks = [ask for said, ask in heard if said not in authored]
        if not asks:
            return
        ask = asks[0]
        now = time.monotonic()
        if not chat.should_say(self._said, craftpleas.ask_key(ask), now=now):
            log.info(
                "craft ask: %s already answered %s about %s - saying nothing",
                ask.crafter, ask.asker, ask.skill,
            )
            return
        if await self._stood_down_for_craft(ask, now):
            return
        await self._answer_craft_ask(ask, now)

    async def _stood_down_for_craft(self, ask, now: float) -> bool:
        """Mid-run, the answer is "not now" - said once, and only once.

        Evan, watching a Deadmines pull stop so somebody could talk about
        cloth: "They should say shut up we are in a dungeon just wait."
        Either end of the conversation being in the run is enough; the party
        chat window is the same window whoever is standing where.
        """
        run = await asyncio.to_thread(_active_dungeon_run)
        if not run:
            return False
        roster_jobs = await asyncio.to_thread(_roster_jobs)
        if not any(chat.mid_run(who, run=run, jobs=roster_jobs)
                   for who in (ask.crafter, ask.asker)):
            return False
        key = chat.say_key(
            speaker=ask.crafter, subject="stand down", listener=ask.asker
        )
        if not chat.should_say(self._said, key, now=now):
            log.info("craft ask: mid-run and already said so; staying quiet")
            return True
        plain = chat.stand_down(
            ask.crafter, subject=ask.product, place=_run_place(run)
        )
        text = await self._in_character(
            ask.crafter, plain, "the family is in the middle of a dungeon run"
        )
        await asyncio.to_thread(
            _insert_speak,
            relay.SpeakCommand(
                ask.crafter, "party", text, "", f"overseer:craft:{ask.asker}"
            ),
        )
        # Remembered like every other line the family says out loud, so the
        # web timeline shows why the answer never came rather than a gap.
        await asyncio.to_thread(_insert_thought, ask.crafter, "council", text)
        chat.remember_said(self._said, key, now=now)
        log.info(
            "craft ask: %s asked for %s mid-run - %s said to wait",
            ask.asker, ask.product, ask.crafter,
        )
        return True

    async def _answer_craft_ask(self, ask, now: float) -> None:
        """The answer itself, checked against the world before it is said.

        THE SKILLS ARE READ HERE, at the moment of speaking, and never taken
        from the plan. professions.crafter_for names who is ASSIGNED a trade,
        which is all this path ever knew, and so the family spent a night
        telling the stream that Og knows tailoring. He does not: the learn has
        been 'planned' since 2026-08-26 (mod-overseer#160, #167, #168) and
        `character_skills` gives him herbalism.

        Silence is a real outcome. craftpleas.answer returns "" when there is
        nothing true to say, and the key is stamped anyway so the same
        question is not re-costed every tick.
        """
        held = await asyncio.to_thread(_fetch_trade_skills, [ask.crafter])
        plain = craftpleas.answer(ask, held=held)
        key = craftpleas.ask_key(ask)
        state = craftpleas.state(ask, held)
        if not plain:
            chat.remember_said(self._said, key, now=now)
            log.info(
                "craft ask: %s wants %s and nobody has %s - saying nothing "
                "rather than promising it",
                ask.asker, ask.product, ask.skill,
            )
            return
        text = await self._in_character(
            ask.crafter, plain, "a family member asking who can craft something",
        )
        if not chat.honest_claim(text, skill=ask.skill, state=state):
            # The voice reworded a hedge into a boast. The plan is what is
            # true, so the plan is what gets said - the same ordering
            # _in_character's own docstring sets out, one rule further on.
            log.warning(
                "craft ask: the voice claimed %s for %s, who is only %s it - "
                "speaking plainly instead",
                ask.skill, ask.crafter, state,
            )
            text = plain
        await asyncio.to_thread(
            _insert_speak,
            relay.SpeakCommand(
                ask.crafter, "party", text, "", f"overseer:craft:{ask.asker}"
            ),
        )
        await asyncio.to_thread(_insert_thought, ask.crafter, "council", text)
        chat.remember_said(self._said, key, now=now)
        log.info(
            "craft ask: %s asked for %s -> %s (%s, %s)",
            ask.asker, ask.product, ask.crafter, ask.skill, state,
        )

    async def _aim_after_muster(self, plea, muster) -> None:
        """Point the responders at what the caller asked for.

        Best-effort by design: the muster has already landed, and a family that
        regrouped but could not be aimed is still better off than one that did
        neither. Extracted from _muster_for_pleas to keep that function under
        the complexity cap (Grug - Elder).
        """
        try:
            await asyncio.to_thread(
                _aim_for_plea,
                plea.caller,
                [a.character_name for a in muster.actions],
                plea.about or "",
            )
        except Exception:
            log.exception("plea aim failed; the muster itself stands")


    async def _muster_for_pleas(self, rows: list[dict], channel) -> None:
        """Read the lines the relay just fetched; answer any call for help.

        Runs over the SAME rows the relay is about to post, so a muster cannot
        answer a plea the channel never saw, and cannot answer one twice - the
        relay marks those ids relayed immediately afterwards.

        Only bot speech is considered. A human typing "help me" in game is
        talking to a person, and pulling four characters off their quests for
        it would be a surprise, not a feature.
        """
        pleas = [
            p
            for row in rows
            if row.get("sender_is_bot")
            for p in (kin.parse_plea(row.get("sender_name") or "", row.get("text") or ""),)
            if p is not None
        ]
        if not pleas:
            return

        # Cooldown first, roster once. Both were per-row and the roster fetch
        # came BEFORE the cooldown test, so a burst paid N serial pymysql
        # connects to then refuse N-1 of them - all of it in front of the chat
        # relay, which this code calls the product.
        if (
            self._last_muster_at is not None
            and (time.monotonic() - self._last_muster_at) < kin.COOLDOWN_SECONDS
        ):
            log.info("kin muster: cooldown, %d plea(s) ignored", len(pleas))
            return

        roster = await asyncio.to_thread(_fetch_roster)
        plea = pleas[0]
        muster = kin.plan_muster(
            plea,
            roster,
            family=bonds.FAMILY,
            last_muster_at=self._last_muster_at,
            now=time.monotonic(),
        )
        # kin decides who CAN come; bonds decides who WILL. Split on purpose:
        # kin is about the realm (is this one of ours, are they alive, are we
        # in cooldown) and bonds is about the family (Grug always goes, unless
        # Og has been playing husband; Bork gets helped less the more he asks).
        rows = await asyncio.to_thread(_fetch_reflections)
        history = bonds.history_from_thoughts(rows)
        # Both numbers, always. history_from_thoughts skips a row it cannot
        # parse, so if kin's memory wording ever drifts from the regex, every
        # bond rule quietly passes and every muster looks perfectly healthy.
        # Rows arriving while pairs sit at zero is the only visible symptom.
        log.info("kin history: %d row(s) -> %d pair(s)", len(rows), len(history))
        muster = bonds.apply(muster, plea, history=history)

        if not muster.actions:
            # Refusals are logged, never posted. fanout reports its refusals
            # because a human typed the order and is owed an answer; a plea is
            # emitted by autonomous characters, so a posted refusal per plea is
            # unbounded channel noise nobody asked for.
            log.info("kin muster refused: %s", muster.reason)
            return

        # Stamp BEFORE issuing: at-most-once matters more than at-least-once
        # when the cost of a double is pulling the family off their quests
        # twice. The partial-muster risk that creates is handled by counting
        # what actually landed, below, rather than by assuming it all did.
        self._last_muster_at = time.monotonic()
        written = 0
        for action in muster.actions:
            try:
                await asyncio.to_thread(
                    _insert_command,
                    core.InsertCommand(
                        action.character_name, action.command, f"kin:{plea.caller}"
                    ),
                )
                await asyncio.to_thread(
                    _insert_thought,
                    action.character_name,
                    "reflection",
                    muster.responder_memories[action.character_name],
                )
                written += 1
            except Exception:
                # Same shape as _muster: one bad row must not cost the rest,
                # and the report must describe what landed. A report that
                # over-claims would make the channel lie about the world.
                log.exception("kin muster insert failed for %s", action.character_name)
        try:
            await asyncio.to_thread(
                _insert_thought, plea.caller, "reflection", muster.caller_memory
            )
        except Exception:
            log.exception("kin caller memory insert failed for %s", plea.caller)

        # AND ACTUALLY HELP. Everything above regroups them and records that
        # they came; none of it points anyone at what was asked for. That is
        # why "Bork help Ugga" could be said three times in two hours while she
        # stayed on 7 of 8 candles.
        if written:
            await self._aim_after_muster(plea, muster)
        log.info("kin muster: %s (%d of %d written)", muster.reason, written,
                 len(muster.actions))
        if channel is not None and written:
            # sanitize + clamp, exactly like every other world-text path here:
            # plea.about is untrusted (LLM-written or typed by any character),
            # and AllowedMentions.none() is only the first defence.
            report = relay.sanitize(kin.muster_report(muster, plea))[:1990]
            try:
                await channel.send(report)
            except Exception:
                # Commands are written and memories stored; a missing Discord
                # line must not undo the help.
                log.exception("kin muster report send failed")

    async def _poll_outcomes(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(POLL_SECONDS)
            if not self._pending:
                continue
            try:
                stale = await asyncio.to_thread(_expire_stale_claims, CLAIM_STALE_SECONDS)
                if stale:
                    log.warning("%s command(s) abandoned by the worldserver", stale)
                rows = await asyncio.to_thread(_fetch_outcomes, min(self._pending))
            except Exception:
                # The worldserver (and its database) restarting must never
                # kill the bridge; pending rows are retried next poll.
                log.exception("outcome poll failed; retrying next cycle")
                continue
            replies, self._seen = core.report_outcomes(rows, self._seen)
            for row_id, reply in replies:
                channel = self._pending.pop(row_id, None)
                # reply is None for a spoken line, which the chat relay is
                # already carrying back; popping it is the whole point.
                if channel is not None and reply is not None:
                    await channel.send(reply.text)

    async def _obey_evan_in_game(self, rows: list) -> None:
        """Act on an order Evan typed in game rather than in Discord.

        He is sitting at the keyboard playing one of these characters, so that
        is the natural place to talk to them - and until now nothing was
        listening: "i just asked for the sword that dropped with +4 stamina and
        they arent listening".

        Runs over the SAME rows the relay is about to post, so an order cannot
        be obeyed that the channel never saw, nor obeyed twice.
        """
        try:
            await self._obey_once(rows)
        except Exception:
            # Never let an order take the chat relay with it. The relay is the
            # product; obeying is a bonus on top of it.
            log.exception("overheard order failed; the relay carries on")

    async def _obey_once(self, rows: list) -> None:
        directive = overhear.hear(
            rows, family=bonds.FAMILY,
            authored=await asyncio.to_thread(_authored_lines),
            last_at=self._last_overheard_at, now=time.monotonic(),
        )
        if directive is None:
            return

        # Oldest first. audience() sorts alphabetically, which is fine for
        # deciding WHO acts and wrong for deciding who speaks first: it put
        # Bork at the head of the queue every time Evan spoke as Grug.
        who = bonds.speaking_order(overhear.audience(directive, family=bonds.FAMILY))
        if not who:
            return

        # Stamp BEFORE issuing. At-most-once matters more than at-least-once
        # when the cost of a double is the whole family acting on one sentence
        # twice, and a missed order is one Evan can simply repeat.
        self._last_overheard_at = time.monotonic()

        # EVERY member answers, each from their own situation. This used to ask
        # the voice once, about who[0], and then apply that one answer to all
        # four - so Bork answered every order Evan ever gave (he is first
        # alphabetically), and the other three carried out a decision taken
        # from Bork's level, Bork's zone and Bork's bags. Evan: "i want them
        # all to answer to be honest, and it should all synthesize based on
        # their own brain and needs based on what they are doing."
        #
        # They may well pick DIFFERENT commands. That is the point of asking
        # them separately; a family that always agrees is one character.
        #
        # Concurrently, because this is now four LLM round trips on a relay
        # that ticks every RELAY_SECONDS - serially they would hold the next
        # tick's chat behind them for as long as four inferences take.
        decisions = await asyncio.gather(
            *(self._answer_as(name, directive) for name in who)
        )

        answered = 0
        # strict=True: asyncio.gather returns exactly one result per awaitable,
        # in the order they were passed, so `decisions` is the same length as
        # `who` by construction. If that ever stops holding, a member would be
        # silently dropped from the answer - which is the bug this whole
        # function exists to fix - so fail loudly instead.
        for name, decision in zip(who, decisions, strict=True):
            if decision is None:
                continue
            answered += 1
            # A decision with no command is a refusal: the vocabulary could not
            # express the order, so this character says so and does nothing.
            # Inventing an approximation of an order nobody gave is worse than
            # admitting it was not understood, when the order moves characters
            # around a world.
            if decision.command is None:
                log.info("overheard '%s': no command fits for %s",
                         directive.text[:50], name)
            else:
                await asyncio.to_thread(
                    _insert_command,
                    core.InsertCommand(name, decision.command, "heard:%s" % directive.speaker),
                )
            await asyncio.to_thread(_insert_thought, name, "command", directive.text)
            await asyncio.to_thread(_insert_thought, name, "chat", decision.say)
            # Written one at a time, in speaking order, and not staggered in
            # time. mod-overseer takes pending commands ORDER BY id ASC, twenty
            # per two-second poll, so insertion order IS the order Evan reads -
            # and overhear.COOLDOWN_SECONDS already caps the whole family at
            # one exchange per twenty seconds, which is four lines, not a
            # flood. Sleeping between them would only park the relay tick.
            await asyncio.to_thread(
                _insert_speak,
                relay.SpeakCommand(name, "party", decision.say, "", "overseer:heard"),
            )
            log.info("overheard '%s' -> %s: %s", directive.text[:50], name, decision.command)

        if not answered:
            # Say something. The old code returned here without a word, and
            # silence in party chat is indistinguishable from nobody having
            # heard - which is most of why one character answering for four
            # went unnoticed for as long as it did.
            await asyncio.to_thread(
                _insert_speak,
                relay.SpeakCommand(who[0], "party", VOICE_SILENT, "", "overseer:heard"),
            )
            log.warning("overheard '%s' but not one of %s could answer",
                        directive.text[:50], ", ".join(who))

    async def _answer_as(self, name: str, directive) -> voice.Decision | None:
        """What THIS character decides to do about the order, or None.

        None means this one could not answer at all - it is not in the world,
        or its own call to the voice failed. Every failure is contained here on
        purpose: four members share one gather, and one unreachable inference
        must not take the other three's answers with it.
        """
        try:
            grounding = await asyncio.to_thread(_fetch_grounding, name)
            if grounding is None:
                log.info("overheard an order but %s is not in the world", name)
                return None
            prompt = voice.build_prompt(
                name=grounding["name"], level=grounding["level"],
                race_name=RACE_NAMES.get(grounding["race"], "creature"),
                class_name=CLASS_NAMES.get(grounding["class"], "adventurer"),
                zone=GEO.zone_name(grounding["map_id"], grounding["pos_x"], grounding["pos_y"]),
                personality=_persona_for(grounding), text=directive.text,
            )
            return voice.parse_decision(await asyncio.to_thread(_ask_llm, prompt))
        except Exception:
            log.exception("overheard '%s' but %s's voice is unreachable",
                          directive.text[:60], name)
            return None

    async def _retire_addon_traffic(self, rows: list) -> list:
        """Mark addon rows relayed and return only what is worth posting.

        Its own method to keep the branch out of _relay_chat, which Elder
        already had at the complexity cap. Acknowledged rather than dropped:
        left unrelayed they are re-read every tick, and since the relay takes
        only the oldest MAX_LINES_PER_POST rows, a steady trickle of addon
        whispers would push real speech out of the window for good.
        """
        rows, addon_ids = relay.partition_addon(rows)
        rows, echo_ids = relay.collapse_hearers(rows)
        retire = addon_ids + echo_ids
        if retire:
            await asyncio.to_thread(_mark_relayed, retire)
            log.info(
                "chat relay: retired %d addon, %d per-listener copies",
                len(addon_ids), len(echo_ids),
            )
        return rows

    async def _relay_chat(self) -> None:
        """Carry world chat into Discord (infra#2597).

        Rows are marked relayed only AFTER Discord accepts them, so a crash
        mid-tick re-sends a line rather than losing it. A partially-sent
        batch is re-sent whole next tick: a duplicate line is a far cheaper
        failure than a missing one, and the batch is normally one post.
        """
        await self.wait_until_ready()
        channel_id = CHAT_CHANNEL_ID or OVERSEER_CHANNEL_ID
        if not channel_id:
            log.warning(
                "no CHAT_CHANNEL_ID and no OVERSEER_CHANNEL_ID - world chat "
                "is being captured but has nowhere to go"
            )
            return
        try:
            skipped = await asyncio.to_thread(
                _skip_chat_backlog, RELAY_BACKLOG_GRACE_SECONDS
            )
            if skipped:
                log.info("skipped %s lines of chat backlog on start", skipped)
        except Exception:
            log.exception("could not skip chat backlog; may re-post history")

        while not self.is_closed():
            await asyncio.sleep(RELAY_SECONDS)
            try:
                rows = await asyncio.to_thread(_fetch_unrelayed_chat)
                if not rows:
                    continue
                channel = self.get_channel(int(channel_id))
                if channel is None:
                    # Not fatal and not silent: the rows stay unrelayed, so
                    # fixing the id or the invite recovers the conversation.
                    log.warning("chat relay channel %s is not visible", channel_id)
                    continue
                # A call for help is answered BEFORE the batch is posted, so
                # the muster line lands next to the plea rather than a tick
                # later. _answer_pleas swallows its own failures by contract -
                # chat is the product, help is a bonus on top of it - which
                # also keeps this function under Elder's complexity cap.
                await self._answer_pleas(rows, channel)
                # Same reasoning, same guarantee, a second bonus on top of
                # the same batch (infra#2829): a family member asking who can
                # craft something gets an answer next to the question.
                await self._answer_craft_asks(rows, channel)

                # Post by post, acknowledging each one on its own. Marking a
                # whole batch after a partial failure would skip lines that
                # never went out AND re-send the ones that did.
                rows = await self._retire_addon_traffic(rows)

                # Before the relay posts them, so an order and the reply to it
                # arrive in Discord in the order they happened. Guarded inside
                # the callee: _relay_chat was already at Elder's complexity cap
                # and one more except here tips it over.
                await self._obey_evan_in_game(rows)

                for post, ids in relay.format_batch(rows):
                    head = ids[0] if ids else 0
                    try:
                        await channel.send(post)
                    except Exception:
                        # The same oldest rows come back next tick, so a post
                        # Discord will never accept would block every later
                        # line behind it until retention cleared it - the
                        # relay would simply look dead. Give it a few goes,
                        # then drop THAT post's rows, loudly, and carry on.
                        self._stuck = (
                            head,
                            self._stuck[1] + 1 if self._stuck[0] == head else 1,
                        )
                        log.exception(
                            "chat relay send failed at id %s (attempt %s of %s)",
                            head, self._stuck[1], RELAY_MAX_ATTEMPTS,
                        )
                        if self._stuck[1] >= RELAY_MAX_ATTEMPTS and ids:
                            log.error(
                                "dropping %s undeliverable chat line(s) at id %s "
                                "so the relay can continue",
                                len(ids), head,
                            )
                            await asyncio.to_thread(_mark_relayed, ids)
                            self._stuck = (0, 0)
                        # Stop here: later posts are newer, and sending them
                        # now would put the conversation out of order.
                        break
                    self._stuck = (0, 0)
                    await asyncio.to_thread(_mark_relayed, ids)
            except Exception:
                log.exception("chat relay tick failed; retrying next cycle")

    async def _in_character(self, speaker: str, plain: str, context: str) -> str:
        """The line as this character would say it, or the plain line.

        The plan is already decided before this runs, and the fallback is the
        line that was going to be said anyway - so a model that is offline,
        slow, or having a bad day costs the family its voice and never its
        plan. That ordering is the point; do not move this before the rules.
        """
        prompt = persona.build_prompt(speaker, plain, context=context)
        if prompt is None:
            return plain
        try:
            said = await asyncio.to_thread(
                _ask_llm, prompt,
                "Answer with the sentence only. No reasoning, no preamble, "
                "no quotation marks.",
            )
        except Exception:
            # Deliberately not .exception(): the LLM being unreachable is an
            # expected weather condition here, and a stack trace per council
            # line would bury the councils themselves.
            log.info("persona: %s spoke plainly (voice unavailable)", speaker)
            return plain
        return persona.clean(said, plain)

    async def _hold_council(self) -> None:
        """The family decides what today is for (infra#2724).

        Runs on a long cadence. A council is a conversation in the world - the
        lines are SAID by the characters, so they reach Discord through the
        ordinary relay rather than by this loop posting a summary. The relay is
        already the one path world speech takes, and a second one would drift.

        The plan is persisted as an ordinary goal, so the supervisor drives it
        with the machinery that already exists and a council that decides
        something is indistinguishable, downstream, from Evan asking for it.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("COUNCIL_CYCLE_SECONDS", "3600"))
        # Deliberately not on the minute a deploy happens to land: a council is
        # a scene, and one at every restart would make it wallpaper.
        await asyncio.sleep(min(cycle, 120.0))
        while not self.is_closed():
            try:
                await self._council_once()
            except Exception:
                log.exception("council failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _council_once(self) -> None:
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        members = await asyncio.to_thread(_fetch_council_members, names)
        history = bonds.history_from_thoughts(
            await asyncio.to_thread(_fetch_reflections)
        )
        held = council.hold(members, history=history)
        if not held.lines:
            log.info("council: %s", held.reason)
            return

        # A council that reaches the conclusion the family is ALREADY working
        # on does not re-stage itself. Nothing has changed, so re-speaking the
        # whole scene every hour is not deliberation, it is a stuck record -
        # and it is what filled Discord with the same six lines over and over.
        # The plan still stands; there is simply nothing new to say about it.
        if held.plan is not None and await asyncio.to_thread(
            _already_agreed, held.plan
        ):
            log.info("council: nothing new to decide (%s)", held.reason)
            return

        # What the council is about, so a voiced line can sit in the moment
        # rather than floating free of it.
        context = held.reason
        for line in held.lines:
            speaker, _, plain = line.partition(": ")
            text = await self._in_character(speaker, plain, context)
            # PARTY, not say. /say carries about 25 yards and the family grinds
            # in different zones, so the first council was five characters
            # talking to themselves in empty air - every captured line came
            # back with heard_by equal to sender_name while Discord showed a
            # conversation that never happened. Party chat has no range, and
            # when there is no party the module answers "not in a group",
            # which is a loud failure instead of a convincing one.
            await asyncio.to_thread(
                _insert_speak,
                relay.SpeakCommand(speaker, "party", text, "", "overseer:council"),
            )
            # 'council', not 'reflection'. What a character argued for is worth
            # remembering, but it is not a memory of helping anyone, and the
            # bond rules count only the latter.
            await asyncio.to_thread(_insert_thought, speaker, "council", text)

        if held.plan is not None:
            await asyncio.to_thread(_persist_council_plan, held.plan)
        log.info("council: %d line(s), %s", len(held.lines), held.reason)

    async def _restore_lost_lives(self) -> None:
        """Give a character its life back the moment the AI has it again.

        `_give_them_a_life` already re-issues on the roster cadence, and that
        was enough while the only thing that stripped a strategy was a
        worldserver restart - the same sweep covers startup. It is not enough
        now that #2663 logs a character in and out on demand: every watch ends
        with a re-login, ResetStrategies rebuilds from defaults that do not
        include `new rpg` for named characters, and the character comes back
        with nothing to do.

        PROTECT_CYCLE_SECONDS is 600, so that gap is up to TEN MINUTES. On the
        leader it is ten minutes of the whole family standing still, because
        four of them are following him. Measured at eight minutes on live.

        Watching for the transition rather than shortening the sweep is
        deliberate: these commands reach the game as whispers, and re-issuing
        fifteen of them a minute to characters that never lost anything is
        visible noise in Evan's chat. A character that did not relog needs
        nothing, and gets nothing.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("LIFE_RECHECK_SECONDS", "20"))
        seen: frozenset | None = None
        while not self.is_closed():
            try:
                protected = await asyncio.to_thread(_protected_guids)
                names = sorted(protected.values())
                current = frozenset(
                    await asyncio.to_thread(_bot_held_names, names)
                )
                back = goals.returned_to_ai(seen, current)
                # Seeded even on the first look, so the NEXT transition is
                # measurable. Assigning only when something returned would
                # leave `seen` None forever and fire for everyone the first
                # time anybody relogged.
                seen = current
                if back:
                    log.info(
                        "life: %s back under the AI - re-issuing strategies",
                        ", ".join(sorted(back)),
                    )
                    await asyncio.to_thread(_give_them_a_life, sorted(back))
            except Exception:
                # Never fatal. A failed recheck costs latency on the next
                # relog, and the 600s sweep is still underneath it.
                log.exception("life recheck failed")
            await asyncio.sleep(cycle)

    async def _assign_trades(self) -> None:
        """Decide who takes which trade, and watch for it actually happening.

        Runs on the council's own long cadence, because it IS a council-shaped
        decision: it is about the family as a whole, it is said out loud in
        party chat, and it is reached the same way twice from the same state.

        WHAT IT DOES NOT DO, WRITTEN HERE SO NOBODY HAS TO GO LOOKING. It does
        not teach anybody a profession. There is no path from this loop to
        `character_skills`, and there is no command row it could send that
        would do it either. That has not changed and must not.

        WHAT IT NOW DOES INSTEAD IS ASK. This docstring used to end by saying
        the transaction was somebody else is change - first because nothing
        could aim a bot at a chosen NPC (#2840 made that false), then because
        arriving did not train (#2757 made that false too). What it writes now
        is an ERRAND: four columns on `overseer_roster` saying which trade this
        character should end up with, which one to buy, which one to give up
        and at what price. mod-overseer walks the character to a trainer that
        can teach it and buys it there, through the core is own
        Trainer::TeachSpell - so the money is taken, the free-slot rule is
        enforced, and nothing appears in `character_skills` that a trainer was
        not paid for (#2782).

        THE SETTLE PATH IS UNCHANGED AND IS STILL THE ONLY PROOF. A written
        column says the module was asked, never that anything happened; the row
        moves to 'learned' only when `character_skills` is OBSERVED to agree -
        by whatever honest route, including Evan walking Ugga to a trainer
        himself.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("TRADE_CYCLE_SECONDS", "3600"))
        await asyncio.sleep(min(cycle, 90.0))
        while not self.is_closed():
            try:
                await self._trades_once()
            except Exception:
                log.exception("trades failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _announce_settled(self, skills: dict) -> None:
        """Say out loud what the WORLD has already done.

        Runs before the plan is computed, because a plan reached against a
        stale reading would re-decide a trade the family has already been to a
        trainer for and announce it a second time. `professions.settled` is the
        only thing that can move a row forward and it takes this observation as
        an argument, so nothing here can mark a trade done by believing it.
        """
        for done in await asyncio.to_thread(_settle_trades, skills):
            text = (f"{done.character} has {done.skill}." if done.verb == "learn"
                    else f"{done.character} no longer has {done.skill}.")
            log.info("trades: settled - %s", text)
            await asyncio.to_thread(_insert_thought, done.character, "council", text)

    async def _send_trade_errand(self, plan, skills: dict) -> None:
        """Put the outstanding plan where the worldserver can read it.

        WRITTEN EVERY CYCLE, not only when the plan is new. A plan that was
        already decided is still a plan that has not happened, and the roster
        row it needs is as necessary the second hour as the first - more so,
        because by then the interesting case is a worldserver that restarted
        with the errand half applied. mod-overseer clears each column itself
        when its verb succeeds, so re-writing is either a no-op or a repair.
        """
        errand = professions.to_errand(plan, skills)
        if not errand:
            return
        await asyncio.to_thread(_write_trade_errand, errand)
        log.info(
            "trades: errand on the roster - %s learn=%s unlearn=%s "
            "(price %s) travel=%r; traveller=%s",
            errand.character, errand.learn_skill, errand.unlearn_skill,
            errand.unlearn_max, errand.travel_npc,
            professions.traveller(errand) or "nobody has to move",
        )

    async def _speak_trade_plan(self, plan, fresh: list) -> None:
        """The family saying it, in party chat, in its own voice.

        ONLY THE NEW ASSIGNMENTS SPEAK. `plan` is recomputed every cycle and
        returns the same answer while a trade is outstanding, so speaking all
        of it would have Og announce the same decision once an hour forever.
        `fresh` is what `_record_trade_plan`'s INSERT IGNORE actually created.
        """
        fresh_names = {(a.character, a.verb, a.skill) for a in fresh}
        for line in professions.lines(plan):
            speaker, _, plain = line.partition(": ")
            if not any(speaker == c for c, _, _ in fresh_names):
                continue
            text = await self._in_character(speaker, plain, "the family's trades")
            await asyncio.to_thread(
                _insert_speak,
                relay.SpeakCommand(speaker, "party", text, "", "overseer:trades"),
            )
            await asyncio.to_thread(_insert_thought, speaker, "council", text)

    async def _trades_once(self) -> None:
        family = await asyncio.to_thread(_council_family)
        if not family:
            log.info("trades: nobody visible to plan for")
            return

        skills = {m.name: dict(m.skills) for m in family}
        await self._announce_settled(skills)

        plan = professions.plan(family)
        for note in plan.notes:
            log.info("trades: %s", note)
        if not plan.assignments:
            log.info("trades: nothing to decide")
            return

        # Before the `fresh` check below, which returns early on the common
        # case of a plan that is unchanged and still outstanding.
        await self._send_trade_errand(plan, skills)

        fresh = await asyncio.to_thread(_record_trade_plan, plan)
        if not fresh:
            # Already decided and still not done. What is missing is logged
            # with the plan rather than filed away, because a decision that has
            # not been acted on needs its reason next to it.
            for blocker in professions.BLOCKERS:
                log.info("trades: STILL TO BUILD - %s", blocker)
            return

        for assignment in fresh:
            log.info("trades: %s - %s", professions.errand(assignment),
                     assignment.reason)
        # NOT "the errand stops at the trainer's door" any more - it does not,
        # since infra#2757 built the transaction. What is left is that none of
        # it is real until both images ship, which is what BLOCKERS now says.
        for blocker in professions.BLOCKERS:
            log.warning("trades: what could still stop this - %s", blocker)

        await self._speak_trade_plan(plan, fresh)

    async def _protect_characters(self) -> None:
        """Hold the manager's own randomize bookkeeping open (infra#2656).

        Cheap and idempotent: a handful of SELECTs, and a write only when a
        guard is missing or nearing expiry. Runs first and often so a
        freshly created protected character is covered before the manager
        has any chance to reach it.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("PROTECT_CYCLE_SECONDS", "600"))
        while not self.is_closed():
            try:
                protected = await asyncio.to_thread(_protected_guids)
                added = await asyncio.to_thread(
                    _ensure_roster, sorted(protected.values())
                )
                if added:
                    log.info("overseer_roster: added %d character(s)", added)
                heard = await asyncio.to_thread(
                    _ensure_chat_watch, sorted(protected.values())
                )
                if heard:
                    log.info("overseer_chat_watch: added %d character(s)", heard)
                await asyncio.to_thread(_give_them_a_life, sorted(protected.values()))

                # mod-overseer forms the party in name order, which put Bork,
                # the youngest, in charge of his own father. It cannot know
                # better - it has no idea who these characters are to each
                # other - so the answer is written down for it here.
                # ...and, while a trade errand is outstanding, whoever is
                # going to the trainer leads instead, so the family travels
                # there together behind its one traveller (infra#2757).
                await asyncio.to_thread(_mark_party_leader, _head_now())

                # ...and while that job is `train`, the traveller is aimed at
                # a trainer in the SAME pass, so leadership and destination can
                # never disagree for a cycle. Both read _train_members, and
                # both no-op for a family on any other mode (infra#3338).
                await self._drive_train()

                # The family's trade assignment. Written every cycle rather
                # than with the errand, because it is a PERMISSION and not an
                # instruction: it is what stops a stale errand column doing
                # anything, and it has to be present for characters that have
                # no errand at all.
                await asyncio.to_thread(_write_declared_professions)

                # Which tree each of them puts talent points in. Without this
                # the module leaves talents alone entirely, which is the safe
                # default for a character nobody has decided a role for and the
                # wrong one for a family that needs a tank and a healer.
                await asyncio.to_thread(_mark_specs, bonds.spec_tabs())

                rows = await asyncio.to_thread(_randomize_rows, list(protected))
                now = int(time.time())
                due = protect.rows_needing_refresh(protected, rows, now)
                for guid in due:
                    await asyncio.to_thread(_write_randomize_guard, guid, now)
                log.info("%s", protect.report(protected, due, now))
            except Exception:
                # The horizon is ten years; a failed cycle costs nothing,
                # and saying so is what keeps a lapse visible.
                log.exception("protect cycle failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _share_quests_loop(self) -> None:
        """Keep every quest one of them holds within reach of all of them.

        Its own loop rather than a step inside _protect_characters, because
        the two answer to different clocks: the protect cycle exists to beat
        the randomize manager and runs every ten minutes whatever happens,
        while sharing is worth doing shortly after somebody picks a quest up
        and costs three SELECTs when there is nothing to do.

        A failed cycle costs nothing and is retried; it is logged rather than
        swallowed, because a sharing pass that has quietly stopped looks
        exactly like a family that has nothing left to share.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("SHARE_CYCLE_SECONDS", "300"))
        while not self.is_closed():
            await asyncio.sleep(cycle)
            try:
                await asyncio.to_thread(_share_quests)
            except Exception:
                log.exception("quest sharing pass failed; retrying next cycle")

    async def _move_materials_once(self) -> None:
        """One pass of infra#2830: reagents move to whoever is assigned the
        profession they feed.

        Same shape as _trades_once: fetch, decide in the pure module, write
        the command, and only then speak - a give that could not be written
        (missing ENUM, or already queued inside GIVE_RETRY_MINUTES) has
        nothing to announce.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if await self._mid_run(names):
            # NOT A FAILURE AND NOT A SKIP TO BE FIXED. Reagents are still in
            # the wrong bags and will still be in the wrong bags when the run
            # ends; what changes is that the family is not made to stop a
            # boss pull to discuss cloth. Evan, watching one: they should say
            # they are in a dungeon and wait. See chat.mid_run.
            log.info("materials: the family is in a dungeon run - reagents wait")
            return
        # BAGS BEFORE REAGENTS. A give into full bags is refused, and the
        # family was measured at 273 of 274 slots used with six bags carried
        # as cargo. Handing those over is what makes the reagent gives below
        # land, so it goes first and shares the same queue and retry window.
        await self._hand_bags_once(names)
        holdings = await asyncio.to_thread(_fetch_holdings, names)
        refused = materials.stuck(
            await asyncio.to_thread(_give_attempts, GIVE_GIVE_UP_HOURS)
        )
        refused = materials.retryable_stuck(
            refused, await asyncio.to_thread(_fetch_free_slots, names)
        )
        material_plan = await asyncio.to_thread(
            materials.plan, holdings, stuck_pairs=refused
        )
        for note in material_plan.notes:
            log.info("materials: %s", note)
        await self._say_blocked(material_plan.blocked)
        if not material_plan.grants:
            log.info("materials: nothing to move")
            return

        seen = await asyncio.to_thread(_recent_give_keys, GIVE_RETRY_MINUTES)
        fresh = []
        for grant in material_plan.grants:
            key = (grant.holder, grant.taker, grant.command)
            if key in seen:
                continue
            if await asyncio.to_thread(_insert_give, grant):
                fresh.append(grant)
        if not fresh:
            log.info(
                "materials: %d grant(s) already queued or refused",
                len(material_plan.grants),
            )
            return

        for grant in fresh:
            log.info(
                "materials: %s -> %s, %d %s (%s) - %s",
                grant.holder, grant.taker, grant.count, grant.material,
                grant.skill, grant.reason,
            )
        await self._speak_handovers(fresh)

    async def _hand_bags_once(self, names: list) -> None:
        """Give every idle bag to whoever has an empty bag position.

        Measured on the dev family: four of five had no free bag position
        while carrying spare bags as cargo, and the fifth had an empty
        position and no bag. Per-character logic decides nothing there; only
        a family-wide match does, and bag_upgrade.plan_family_bags is that
        match. The move is an ordinary kind='give' - DoGive equips a
        container straight into the receiver's bag position and needs no
        free inventory slot to do it, which is why this works on bags that
        are already full.

        The SQL fetches containers and where they sit; which of them is worn,
        carried or out of reach in the bank is decided in bag_upgrade, not
        here.
        """
        rows = await asyncio.to_thread(_fetch_bag_state, names)
        moves = bag_upgrade.plan_family_bags(
            bag_upgrade.members_from_rows(rows, names)
        )
        if not moves:
            log.info("bags: nothing to hand over")
            return
        seen = await asyncio.to_thread(_recent_give_keys, GIVE_RETRY_MINUTES)
        for move in moves:
            command = bag_upgrade.give_command(move)
            if (move.giver, move.receiver, command) in seen:
                continue
            if await asyncio.to_thread(_insert_bag_give, move, command):
                log.info(
                    "bags: %s -> %s, %s (%s, +%d slots) - %s",
                    move.giver, move.receiver, move.bag, command,
                    move.slots_gained, move.why,
                )

    async def _mid_run(self, names: list) -> bool:
        """Is any of these characters in the middle of a dungeon run?"""
        run = await asyncio.to_thread(_active_dungeon_run)
        if not run:
            return False
        roster_jobs = await asyncio.to_thread(_roster_jobs)
        return any(chat.mid_run(name, run=run, jobs=roster_jobs) for name in names)

    async def _say_blocked(self, blocked) -> None:
        """Say once that a handover keeps failing, then stop asking.

        The four `receiver bags are full` errors that ran for six hours are
        why this exists (mod-overseer#169). A give nobody has answered yet
        stays in the plan; a give the world has refused materials.GIVE_UP_AFTER
        times is spoken once, as the refusal the world actually gave, and then
        left alone until GIVE_GIVE_UP_HOURS has passed.
        """
        now = time.monotonic()
        for stop in blocked:
            log.info(
                "materials: %s -> %s %s is stuck - %s",
                stop.holder, stop.taker, stop.material, stop.refusal,
            )
            if not chat.should_say(self._said, stop.key, now=now):
                continue
            text = await self._in_character(
                stop.holder, stop.said, "a handover the world keeps refusing"
            )
            await asyncio.to_thread(
                _insert_speak,
                relay.SpeakCommand(stop.holder, "party", text, "", "overseer:materials"),
            )
            await asyncio.to_thread(_insert_thought, stop.holder, "council", text)
            chat.remember_said(self._said, stop.key, now=now)

    async def _speak_handovers(self, fresh: list) -> None:
        """One line per handover, not one per stack, and each of them once.

        Two stacks of Linen Cloth in Grug's bags are two give commands - the
        world moves one `item_instance.guid` at a time - and were two lines,
        one saying 20 and one saying 19. That pair is what made the family
        read as a loop re-evaluating rather than as somebody handing over a
        bundle, so the commands stay separate and the sentence is merged.

        The taker's live skills come along because the sentence used to end
        "Og need it for tailoring" about a character who has never had it.
        """
        held = await asyncio.to_thread(
            _fetch_trade_skills, sorted({g.taker for g in fresh})
        )
        now = time.monotonic()
        for hand in materials.handovers(fresh, held=held):
            if not chat.should_say(self._said, hand.key, now=now):
                log.info(
                    "materials: %s already told %s about %s - moving it quietly",
                    hand.holder, hand.taker, hand.material,
                )
                continue
            # PARTY, not say - the same reason council speaks in party
            # (bridge.py:2178-2184): the family grinds in different zones
            # and /say has no cross-zone range at all.
            text = await self._in_character(
                hand.holder, hand.said, "handing over a crafting material"
            )
            state = chat.skill_state(
                hand.taker, hand.skill, held=held,
                planned={hand.taker: professions.assigned(hand.taker)},
            )
            if not chat.honest_claim(text, skill=hand.skill, state=state):
                log.warning(
                    "materials: the voice claimed %s for %s, who is only %s "
                    "it - speaking plainly instead",
                    hand.skill, hand.taker, state,
                )
                text = hand.said
            await asyncio.to_thread(
                _insert_speak,
                relay.SpeakCommand(hand.holder, "party", text, "", "overseer:materials"),
            )
            await asyncio.to_thread(_insert_thought, hand.holder, "council", text)
            chat.remember_said(self._said, hand.key, now=now)

    async def _move_materials_loop(self) -> None:
        """Keep every reagent moving toward the crafter it feeds (infra#2830).

        Own loop, own clock, same reasoning as _share_quests_loop: this is
        worth doing on a shorter cycle than the ten-minute protect sweep, and
        a failed pass is retried rather than swallowed - a materials pass
        that has quietly stopped looks exactly like a family with nothing
        left to move.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("MATERIALS_CYCLE_SECONDS", "600"))
        await asyncio.sleep(min(cycle, 90.0))
        while not self.is_closed():
            try:
                await self._move_materials_once()
            except Exception:
                log.exception("materials pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _vendor_once(self) -> None:
        """Queue carried junk and outgrown gear for the world sell executor.

        TWO SOURCES, ONE PASS, ONE ERRAND. Junk comes from bag_pressure and
        outgrown equipment from disposition, but both end as a kind='sell'
        row for a character walking to the same vendor, so splitting them
        into two loops would only mean two errands fighting over one leader.

        NOTHING HERE DECIDES ANYTHING. What is worth selling is bag_pressure's
        and disposition's; whether a decision an earlier poll already made is
        still true is item_plan's. This method fetches, calls them, and writes
        what comes back.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names or await self._mid_run(names):
            return
        free_slots = await asyncio.to_thread(_fetch_free_slots, names)
        if not bag_pressure.family_town_run_needed(free_slots):
            log.info("economy: carried vendor goods exist, but bag pressure is below "
                     "the town-run trigger")
            return
        rows = await asyncio.to_thread(_fetch_vendor_items, names)
        gear_rows = await asyncio.to_thread(_fetch_surplus_gear, names)
        worn = await asyncio.to_thread(_fetch_family_equipped, names)
        # THE SAME OPINION THAT DECIDES HAND-OFFS DECIDES WHAT MAY BE SOLD.
        # gear.py judges who would wear a carried piece; only the answer
        # "nobody, and we asked all five" lets it reach a vendor. An empty
        # `worn` (older world image, missing columns) yields no fits at all,
        # every piece is UNASKED, and the gear half of this pass offers
        # nothing - which is the safe way to not know.
        fits = bag_pressure.family_fits(gear_rows, worn, names)
        # THE HAND-OFF IS TRIED FIRST, AND IT IS TRIED WHETHER OR NOT ANYTHING
        # IS FOR SALE. A piece a sibling should be wearing is worth more on
        # that sibling than in anybody's purse, and the two answers come from
        # one gate over one read of the world, so asking for them in one place
        # is what stops a sale and a hand-off ever being proposed for the same
        # item. It sits above the `no candidates` return because a family with
        # nothing to sell can still be carrying somebody else's upgrade.
        await self._hand_gear(gear_rows, worn, names)
        candidates = bag_pressure.vendor_candidates(
            rows, keep_names=OWNER_KEEPS,
        ) + (
            bag_pressure.gear_candidates(
                gear_rows, disposition.Family(vendor_reachable=True),
                available=SELL_ROUTES, fits=fits, keep_names=OWNER_KEEPS,
            )
        )
        if not candidates:
            log.info("economy: no safe carried vendor goods")
            return
        # A sale is owned by the character carrying that item. A single
        # leader aim cannot make the other four characters pass a vendor-range
        # check, and their sell rows would otherwise be retried forever from
        # wherever the party happened to be standing. Plan one vendor pass per
        # holder so every seller reaches the NPC that will answer its command.
        by_holder: dict[str, list] = {}
        for candidate in candidates:
            by_holder.setdefault(candidate.holder, []).append(candidate)

        # THE ROW IS ONLY WRITTEN WHERE IT CAN WORK (infra#3464).
        #
        # THE MEASUREMENT. Over three hours on the live realm the sell verb
        # was answered 1,950 times and 1,940 of those were errors: 1,860
        # `vendor not in range`, 48 `seller is dead`, 42 `seller is in
        # flight`. Ten sales succeeded. That is roughly 650 attempts an hour
        # issued from wherever the party happened to be standing.
        #
        # WHY IT LOOKED LIKE A DECISION BUG AND IS NOT ONLY ONE. A sale rule
        # that never runs at a vendor leaves exactly the same 197 greens in
        # the bags as a sale rule that refuses to sell them. Both were true
        # here, and this is the half that was doing the damage.
        #
        # WHAT THE WORLD ALREADY SAID AND NOBODY READ. mod-overseer#230
        # stopped pushing a refused row back to `pending` - twenty of them
        # held the head of a FIFO for half an hour and livelocked the drain -
        # and carries the retry class out instead: `vendor not in range` is
        # classified ELSEWHERE, whose whole meaning is "this row can work, but
        # not from where this character is standing". The comment on that
        # change says the deciding side re-queues a fresh row. This side never
        # read the word (item_plan honours only `never`), so it re-queued from
        # the same spot every cycle, for ever.
        #
        # THE GATE IS THE READER THE TOWN TRIP ALREADY USES. The town reader
        # reads the counters within TOWN_COUNTER_YARDS of where the leader is
        # STANDING, from the live snapshot rather than the save timer, and
        # that box is deliberately sized to the core's own 5.5 yard
        # interaction distance. So "a vendor is in reach" here is a tight
        # proxy for "DoSell will not refuse on range", not a loose "we are in
        # town somewhere".
        #
        # WHY `town.vendor` AND NOT `town.stocks`. What a vendor SELLS is
        # never consulted when a player sells TO it, so a merchant with no
        # npc_vendor rows still buys; gating on stock would refuse exactly the
        # vendors that would have taken the greens.
        attempts = await asyncio.to_thread(_sell_attempts, SELL_MEMORY_HOURS)
        inserted = 0
        considered = 0
        for holder in sorted(by_holder):
            holder_candidates = tuple(by_holder[holder])
            await asyncio.to_thread(
                _write_trade_errand,
                professions.Errand(character=holder, travel_npc="vendor"),
            )
            aimed = True
            town = await asyncio.to_thread(_fetch_town, holder)
            if not town.vendor:
                log.info(
                    "economy: %d carried candidate(s) for %s but no vendor "
                    "within reach - travel aim queued=%s",
                    len(holder_candidates), holder,
                    aimed,
                )
                continue
            # The world has already answered some of these. A sale that was
            # delivered, or refused with a reason retrying cannot change, must
            # not be proposed again: 819 of 822 `item not carried` refusals in
            # one day were re-issues of an item that had already been sold
            # (infra#3330).
            plan = item_plan.plan(holder_candidates, attempts)
            considered += len(holder_candidates)
            for candidate in plan.write:
                if await asyncio.to_thread(_insert_sell, candidate):
                    inserted += 1
            log.info(
                "economy: holder=%s queued %d/%d vendor sale(s), held back %s",
                holder, len(plan.write), len(holder_candidates),
                item_plan.reasons(plan.skipped),
            )
        log.info("economy: queued %d/%d vendor sale(s) across %d holder(s)",
                 inserted, considered, len(by_holder))

    async def _hand_gear(self, gear_rows: list, worn: list, names: list) -> None:
        """Move every carried piece that suits a sibling better (infra#3464).

        THE VERB IS kind='trade' AND NOT kind='give', and gear.py's own banner
        argues it: DoTrade drives the core's WorldSession trade handlers, so
        the exchange renders and animates between two characters standing
        together, where DoGive is a database move. Both exist; a piece of gear
        changing hands is a thing the party should be seen doing, and the
        materials pass keeps kind='give' for a stack of cloth.

        NO TRAVEL ERRAND IS WRITTEN, deliberately. A trade happens where the
        two of them already are, so this needs no counter, no leader and no
        `travel_npc` - which is also why it can run beside the vendor half
        without joining the queue of passes that all want to aim the leader
        somewhere.

        NOTHING IS DESTROYED AND NOTHING SOULBOUND IS OFFERED.
        `gear.is_upgrade_for` refuses a soulbound item outright, so a piece
        that cannot legally reach a sibling never becomes a grant, and
        DoTrade refuses one again on its own side.
        """
        grants = bag_pressure.family_gifts(gear_rows, worn, names,
                                           keep_names=OWNER_KEEPS)
        if not grants:
            return
        seen = await asyncio.to_thread(_recent_trade_keys, GIVE_RETRY_MINUTES)
        fresh = []
        for grant in grants:
            if (grant.holder, grant.taker, grant.command) in seen:
                continue
            if await asyncio.to_thread(_insert_gear_trade, grant):
                fresh.append(grant)
        for grant in fresh:
            log.info("gear: %s -> %s, %s - %s",
                     grant.holder, grant.taker, grant.name, grant.reason)
        log.info("gear: queued %d/%d hand-off(s)", len(fresh), len(grants))

    async def _vendor_loop(self) -> None:
        await self.wait_until_ready()
        cycle = float(os.environ.get("VENDOR_CYCLE_SECONDS", "300"))
        await asyncio.sleep(min(cycle, 90.0))
        while not self.is_closed():
            try:
                await self._vendor_once()
            except Exception:
                log.exception("economy vendor pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _bank_once(self) -> None:
        """One pass of the bank: park what the family keeps but cannot use.

        Same shape as _hand_bags_once and _vendor_once, and deliberately no
        more than that shape: fetch rows in a thread, hand them to the pure
        planner, write the rows it returns. There is no slot arithmetic here
        and no rule about what belongs in a bank - bank.py owns both, and
        disposition owns the verdict bank.py consumes.

        THE TRAVEL PROBLEM IS THE VENDOR'S, SOLVED THE VENDOR'S WAY. DoBank
        refuses with `banker not in range` unless a banker is within
        INTERACTION_DISTANCE and will deal with the character, and a follower
        cannot be sent to an NPC on its own - only the family leader takes
        `new rpg`, and the rest arrive by following. So the errand goes to the
        leader, every character's rows are queued together, and each command
        stays pending until its holder reaches the counter (mod-overseer#209,
        infra#3311). The errand is written BEFORE the rows for the same reason
        the vendor pass writes it first: a queue that outlives the journey is
        the failure this ordering avoids.

        NOT IN THE MIDDLE OF A DUNGEON RUN, for the same reason reagents wait.
        A bank trip is a town errand, and pulling the leader out of a run to
        make one is how the party spreads.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names or await self._mid_run(names):
            return
        rows = await asyncio.to_thread(_fetch_bank_items, names)
        held = await asyncio.to_thread(_fetch_trade_skills, names)
        bank_plan = bank.plan(
            bank.members_from_rows(rows, names), bank.family_from_skills(held)
        )
        for note in bank_plan.notes:
            log.info("bank: %s", note)
        if not bank_plan.moves:
            log.info("bank: nothing to put down and nothing to fetch back")
            return
        leader = bonds.head_of_family()
        await asyncio.to_thread(
            _write_trade_errand,
            professions.Errand(character=leader, travel_npc="banker"),
        )
        seen = await asyncio.to_thread(_recent_bank_keys, GIVE_RETRY_MINUTES)
        fresh = []
        for move in bank_plan.moves:
            command = bank.command(move)
            if (move.character, command) in seen:
                continue
            if await asyncio.to_thread(_insert_bank, move, command):
                fresh.append(move)
        for line in bank.lines(fresh):
            log.info("bank: %s", line)
        log.info("bank: queued %d/%d move(s), leader=%s",
                 len(fresh), len(bank_plan.moves), leader)

    async def _bank_loop(self) -> None:
        """Keep the family's bank in use (mod-overseer#207).

        Own loop and own clock, the same reasoning as _vendor_loop: a failed
        pass is logged and retried rather than swallowed, because a bank pass
        that has quietly stopped looks exactly like a family with nothing left
        to put down.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("BANK_CYCLE_SECONDS", "600"))
        # Behind the vendor pass on purpose. Both send the leader to town and
        # both write `travel_npc`, and the guard in _write_trade_errand lets
        # only an idle traveller be retasked - so the two must not arrive in
        # the same instant and race for the column every cycle.
        await asyncio.sleep(min(cycle, 150.0))
        while not self.is_closed():
            try:
                await self._bank_once()
            except Exception:
                log.exception("economy bank pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _towntrip_once(self) -> None:
        """Repair and restock between two dungeon runs.

        THE EXECUTORS SHIPPED WITHOUT A WRITER. mod-overseer#227 landed
        `kind='repair'` and `kind='buy'`, both driven through the core's own
        handlers, and towntrip.plan has been complete and tested since
        infra#3357 - and nothing has ever called it or written one of those
        rows. Two working verbs with no producer is the whole of this pass.

        AND kind='conjure' WAS THE THIRD OF THEM (infra#3464). mod-overseer#147
        landed a verb that makes a party's food and water out of nothing, and
        nothing in this process has ever written one either, so the only
        conjuring on the realm was the mage feeding himself one stack at a time
        through mod-playerbots patch 0015. towntrip.plan now asks for the
        party's worth and hands the surplus on with kind='give'.

        NOT IN THE MIDDLE OF A DUNGEON RUN, the same gate the vendor and bank
        passes use and for the same reason: a town errand pulls the leader out
        of the instance and the party spreads.

        NOTHING IS PLANNED UNTIL THEY HAVE ARRIVED, and that falls out of the
        Town read rather than being sequenced here. `_fetch_town` reads what is
        within reach of where the leader is STANDING, so a pass that runs while
        they are still walking sees an empty Town, plans nothing, and writes the
        travel errand again. The cycle after they arrive is the one that queues
        rows. That is why this pass needs no state of its own and survives a
        restart: every step is re-derived from the world.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names or await self._mid_run(names):
            return

        leader = bonds.head_of_family()
        # THE AIM GOES FIRST, before anything is planned, exactly as the bank
        # pass writes its banker errand first. A row queued for a counter
        # nobody is walking to is a refusal waiting to be logged.
        await asyncio.to_thread(
            _write_trade_errand,
            professions.Errand(character=leader, travel_npc="repair"),
        )

        town = await asyncio.to_thread(_fetch_town, leader)
        members = towntrip.members_from_rows(
            await asyncio.to_thread(_fetch_town_worn, names),
            await asyncio.to_thread(_fetch_town_carried, names),
            await asyncio.to_thread(_fetch_town_spells, names),
            await asyncio.to_thread(_fetch_free_slots, names),
            names,
        )
        trip = towntrip.plan(members, town)
        for note in trip.notes:
            log.info("towntrip: %s", note)
        for stopped in trip.blocked:
            log.warning("towntrip: %s", stopped)
        if not trip.errands:
            log.info(
                "towntrip: nothing to do at this counter (repairs=%s, %d item(s) stocked)",
                town.repairs, len(town.stocks),
            )
            return

        seen = await asyncio.to_thread(_recent_town_keys, GIVE_RETRY_MINUTES)
        queued = 0
        for errand in trip.errands:
            if (errand.member, errand.command) in seen:
                continue
            if await asyncio.to_thread(_insert_town_errand, errand):
                queued += 1
                log.info("towntrip: %s %s%s - %s",
                         errand.member, errand.kind,
                         " -> %s" % errand.taker if errand.taker else "",
                         errand.why)
        log.info("towntrip: queued %d/%d errand(s), leader=%s",
                 queued, len(trip.errands), leader)

    async def _towntrip_loop(self) -> None:
        """Keep the family repaired and fed between runs (mod-overseer#226).

        Own loop and own clock, the same reasoning as _vendor_loop and
        _bank_loop: a failed pass is logged and retried rather than swallowed,
        because a maintenance pass that has quietly stopped looks exactly like
        a family that needs nothing.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("TOWNTRIP_CYCLE_SECONDS", "300"))
        # Third in the queue behind the vendor pass (90s) and the bank pass
        # (150s), for the reason _bank_loop gives about itself: all three send
        # the leader to town and all three write `travel_npc`, and the guard in
        # _write_trade_errand only lets an idle traveller be retasked, so they
        # must not arrive in the same instant and race for the column.
        await asyncio.sleep(min(cycle, 210.0))
        while not self.is_closed():
            try:
                await self._towntrip_once()
            except Exception:
                log.exception("town trip pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _narrate_events(self) -> None:
        """The world narrates itself (infra#2602).

        Consecutive snapshot polls are diffed by events.detect_events - pure
        delta logic, the LLM never decides what happened. At most ONE LLM
        call per cycle voices at most EVENT_VOICE_CAP events; that pair of
        bounds is what keeps 500 bots from flooding spark-gateway. Overflow
        and LLM outages degrade to events.template_line, so an event thought
        is never dropped because the model failed.
        """
        await self.wait_until_ready()
        # Env read lives here, not in the module constants block, to keep
        # this feature's bridge diff append-only (sibling features are
        # editing this file concurrently).
        cycle = float(os.environ.get("EVENT_CYCLE_SECONDS", "30"))
        cap = int(os.environ.get("EVENT_VOICE_CAP", "8"))
        prev: dict[str, dict] = {}
        while not self.is_closed():
            await asyncio.sleep(cycle)
            try:
                rows = await asyncio.to_thread(_fetch_event_snapshot)
            except Exception:
                # A worldserver/database restart must never kill the bridge;
                # prev is kept so the next good poll still diffs sensibly.
                log.exception("event snapshot poll failed; retrying next cycle")
                continue
            curr = {r["name"]: r for r in rows}
            detected = events.detect_events(prev, curr, GEO)
            try:
                notable = await asyncio.to_thread(_fetch_notable_names)
            except Exception:
                # Losing the notable set must not lose the cycle: fall
                # back to arc-only, which is the quiet direction.
                log.exception("notable lookup failed; arc-only this cycle")
                notable = set()
            detected = events.filter_for_story(detected, frozenset(notable))
            prev = curr
            voiced, overflow = events.split_for_voicing(detected, cap)
            texts: list[str] = []
            if voiced:
                try:
                    reply = await asyncio.to_thread(
                        _ask_llm, events.build_batch_prompt(voiced)
                    )
                    texts = events.voice_events(voiced, reply)
                except Exception:
                    log.exception("event voice unreachable; templated lines only")
                    texts = [events.template_line(e) for e in voiced]
            written = 0
            # strict=True enforces what events.voice_events promises: one
            # line per event, always (skipped or garbled model output
            # degrades to a template line rather than a short list). A
            # lenient zip would silently DROP thoughts if that contract
            # ever broke - the exact silent-failure class this repo hunts.
            for event, text in list(zip(voiced, texts, strict=True)) + [
                (e, events.template_line(e)) for e in overflow
            ]:
                try:
                    await asyncio.to_thread(_insert_thought, event.name, "event", text)
                    written += 1
                except Exception:
                    # One failed insert must not cost the rest of the batch.
                    log.exception("event thought insert failed for %s", event.name)
            # Emitted every cycle, quiet ones included: this line is the
            # Datadog-observable cap the ticket demands - alerting and
            # dashboards key off "event cycle" counts.
            log.info(
                "event cycle: detected=%d voiced=%d templated=%d written=%d cap=%d",
                len(detected), len(voiced), len(overflow), written, cap,
            )
    # --- goal supervision (infra#2601): thin adapters over goals.py -------

    async def _maybe_handle_goal(self, d: core.NLDirective, channel) -> bool:
        """Persist a goal (or cancel one) instead of issuing a command."""
        parsed = goals.parse_goal(d.text)
        if parsed is None:
            return False
        if isinstance(parsed, goals.CancelGoal):
            cancelled = await asyncio.to_thread(_cancel_goals, d.target_name)
            await channel.send(goals.cancel_text(d.target_name, cancelled))
            return True
        row_id = await asyncio.to_thread(
            _insert_goal, d.target_name, parsed, str(channel.id)
        )
        ack = goals.ack_text(d.target_name, parsed)
        await asyncio.to_thread(_insert_thought, d.target_name, "goal", ack)
        await channel.send(ack)
        log.info("goal %s persisted for %s: %s", row_id, d.target_name, goals.describe(parsed))
        return True

    async def _supervise_goals(self) -> None:
        """Reconcile every active goal once a minute; decisions in goals.py."""
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(GOAL_INTERVAL)
            try:
                rows = await asyncio.to_thread(_fetch_active_goals)
            except Exception:
                # A database restart must never kill the supervisor; the
                # store is durable, so next cycle simply retries.
                log.exception("goal fetch failed; retrying next cycle")
                continue
            for row in rows:
                try:
                    observed = await asyncio.to_thread(_observe_goal, row)
                    for action in goals.reconcile(row, observed):
                        await self._apply_goal_action(row, action)
                except Exception:
                    # One wedged goal (or one Discord hiccup) must not
                    # stall the rest; state lives in the store, so the
                    # failed goal is retried whole next cycle.
                    log.exception("goal %s reconcile failed; retrying next cycle", row.get("id"))

    async def _apply_goal_action(self, row: dict, action) -> None:
        if isinstance(action, goals.StrategyCommand):
            await asyncio.to_thread(
                _insert_command,
                core.InsertCommand(action.target_name, action.command, "overseer:goal"),
            )
        elif isinstance(action, goals.DriveQuest):
            aimed = await asyncio.to_thread(_aim_traveller, action.quest_id)
            # Logged every time it is renewed, with the count of rows actually
            # written: this project has been burned repeatedly by "delivered"
            # meaning nothing happened, and 0 rows here is the difference
            # between an aim that landed and one that went nowhere.
            log.info("goal: aiming the party at quest %d for %s (%d row(s))",
                     action.quest_id, action.beneficiary, aimed)
        elif isinstance(action, goals.MilestoneThought):
            await asyncio.to_thread(_insert_thought, action.character_name, "goal", action.text)
        elif isinstance(action, goals.Report):
            channel = self._goal_channel(row)
            if channel is not None:
                await channel.send(action.text[:1990])
        elif isinstance(action, goals.RecordProgress):
            await asyncio.to_thread(
                _record_goal_progress, action.goal_id, action.value, action.stalls
            )
        elif isinstance(action, goals.MarkComplete):
            await asyncio.to_thread(_complete_goal, action.goal_id)

    def _goal_channel(self, row: dict):
        # The channel the goal was set from, falling back to the overseer's
        # own hall so a deleted channel cannot silence completion reports.
        for raw in (row.get("channel_id"), OVERSEER_CHANNEL_ID):
            if raw:
                channel = self.get_channel(int(raw))
                if channel is not None:
                    return channel
        log.warning("goal %s has no reachable channel; report dropped", row.get("id"))
        return None

    # --- fan-out (infra#2605): the hive mind -------------------------------

    async def _muster(self, d, command: str, channel) -> None:
        """Fan one order out to a resolved band, then report what landed.

        The reply's numbers come from the rows that actually reached
        overseer_command, never from the intended set: a muster report that
        over-claims would make the channel lie about the world, and that
        honesty is this ticket's acceptance criterion.

        Fan-out rows deliberately do NOT join self._pending. Forty rows
        would mean forty "heard the order" lines in the channel; the muster
        report is the acknowledgment for a band, and per-row reporting stays
        the single-character path's job.
        """
        roster = await asyncio.to_thread(_fetch_roster)
        guild_names = await asyncio.to_thread(_fetch_guild_names)
        names, reason = fanout.resolve_targets(d.expression, roster, guild_names)
        if not names:
            await channel.send(reason[:1990])
            return
        thought = fanout.thought_text(d.expression, command)
        written = 0
        for name in names:
            try:
                await asyncio.to_thread(
                    _insert_command, core.InsertCommand(name, command, d.source)
                )
                written += 1
            except Exception:
                # One failed insert must not cost the rest of the band; the
                # report below counts only what landed, so the loss is said
                # out loud rather than rounded away.
                log.exception("fan-out command insert failed for %s", name)
                continue
            try:
                await asyncio.to_thread(_insert_thought, name, "command", thought)
            except Exception:
                # A lost thought is cosmetic - the order still stands, and
                # the row it counts is already written.
                log.exception("fan-out thought insert failed for %s", name)
        # Emitted for every muster: this is the Datadog-observable cap the
        # ticket asks for - called vs written vs the cap, in one line.
        log.info(
            "muster: expression=%r called=%d written=%d cap=%d command=%r",
            d.expression, len(names), written, fanout.MAX_FANOUT_TARGETS, command,
        )
        await channel.send(
            fanout.muster_report(
                reason=reason, command=command, called=len(names), written=written
            )[:1990]
        )

    # --- job schedule (infra#2834) ------------------------------------------

    async def _set_job(self, d: core.JobDirective, channel) -> None:
        """Fan a job-schedule mode out to the WHOLE family, one kind='job' row
        per enabled character.

        Mirrors _muster's fan-out shape (a resolved set, one insert each, a
        report of what actually landed) with one deliberate difference: the
        set is not a fanout.resolve_targets band, it is the enabled roster in
        full, because a job is family-wide by construction - see
        core.JobDirective and jobs.py. Rows deliberately do NOT join
        self._pending, same reasoning as _muster: one report for the whole
        family, not five "heard the order" lines for one sentence.
        """
        # THE GUARD, AND IT IS HERE BECAUSE HERE IS WHERE THE HARM WAS
        # (infra#3338). jobs.py has always known which modes are wired; nothing
        # consulted it at the point an order was written, so `job craft` was
        # accepted, stood the quest drive down, and left five characters
        # standing still with nothing in the channel and nothing in the log to
        # say why. Refused BEFORE _fetch_enabled_names, so a refusal costs no
        # query and cannot half-write a family.
        refusal = jobs.why_not(d.mode)
        if refusal:
            log.info("job: refused mode=%r - not wired", d.mode)
            await channel.send(refusal[:1990])
            return

        # THE SECOND HALF OF THE SAME GUARD. A mode can be wired and still have
        # nothing to do, and setting it then is the same idle by a longer road.
        # Only `train` can answer this today because only `train` has a drive
        # in this process to ask; quest and dungeon are driven inside the
        # worldserver and have no equivalent question to put.
        if d.mode == trainjob.MODE:
            blocked = trainjob.readiness(await asyncio.to_thread(_train_members))
            if blocked:
                log.info("job: refused mode=%r - nothing to train", d.mode)
                await channel.send(("Refusing to set job=train. " + blocked)[:1990])
                return

        names = await asyncio.to_thread(_fetch_enabled_names)
        if not names:
            await channel.send("Nobody is on the roster to give a job to.")
            return
        written = 0
        for name in names:
            try:
                await asyncio.to_thread(_insert_job, name, d.mode, d.source)
                written += 1
            except Exception:
                # One failed insert must not cost the rest of the family; see
                # _muster's identical reasoning.
                log.exception("job insert failed for %s (mode=%s)", name, d.mode)
                continue
        log.info(
            "job: mode=%r called=%d written=%d", d.mode, len(names), written
        )
        # DRIVEN NOW, NOT ONLY ON THE NEXT CYCLE. The protect cycle re-asserts
        # this every ten minutes, which is right for a restart and far too slow
        # for a person who has just given an order and is watching a stream.
        # Idempotent either way: the aim is the same two UPDATEs whichever pass
        # runs them.
        if d.mode == trainjob.MODE and written:
            await self._drive_train()
        await channel.send(
            f"{jobs.describe(d.mode)} ({written}/{len(names)} of the family told)"
        )

    async def _drive_train(self) -> None:
        """Make `job = train` mean something: aim the traveller at a trainer.

        THE POSITIVE HALF OF A MODE THAT ONLY EVER HAD A NEGATIVE ONE. Setting
        any non-quest job stands the quest drive down inside the worldserver;
        until this ran, nothing put anything in its place, which is the whole
        of infra#3338. What replaces it is one write to `overseer_roster.
        travel_npc` - the column that makes a character walk, and the one the
        C++ derives learn errands for and then cannot act on, because nothing
        in mod_overseer.cpp ever writes a role keyword into it.

        NOT A SECOND OPINION ABOUT WHO TRAVELS. `_head_now` already asks
        `_train_traveller` first, so the character aimed here is the character
        `_mark_party_leader` made the leader in the same pass. That matters
        more than it looks: mod-overseer refuses to send anybody who is not
        carrying `new rpg`, and only the leader carries it, so aiming anybody
        else is an UPDATE that moves nobody.

        A WIRED MODE WITH NOTHING TO DO IS SAID OUT LOUD. The order was
        refused at the moment it was given if there was nothing to train, but
        an errand that COMPLETES leaves the family on a mode with no work in
        it - and that is the idle #3338 is about, arrived at from the other
        side. Logged at warning rather than silently returned, because the
        answer is a person deciding what they should do instead.
        """
        try:
            members = await asyncio.to_thread(_train_members)
            plan = trainjob.plan(members)
            if not plan.traveller:
                if trainjob.family_mode(members) == trainjob.MODE:
                    log.warning("job train drives nothing: %s", plan.why_not)
                return
            await asyncio.to_thread(_aim_train_traveller, trainjob.statements(plan))
            log.info("%s", trainjob.report(plan))
        except Exception:
            # LOUD, AND STILL NOT FATAL, for the reason infra#3173 wrote down:
            # this runs a third of the way into the protect cycle, so an
            # exception escaping here would take the declared professions, the
            # spec tabs and the randomize guards with it - a failed aim costing
            # every unrelated thing that comes after it. The next cycle
            # re-asserts the aim, and this call site has nothing to roll back.
            log.exception("train drive failed; the family keeps its current aim")

    async def _conjure(self, d: core.FanoutDirective, channel) -> None:
        """A conjured event: natural language aimed at a whole band.

        The band is resolved first so the inner voice can be grounded in a
        real character - voice.py's vocabulary is written per character, and
        asking the model once per character is exactly the flood the cap
        exists to prevent. One call, one allowlisted command, fanned out to
        everyone who answered.

        _muster resolves again afterwards on purpose: the voice may take a
        minute, and the rows must match who is in the world when they are
        written, not who was there when the order was typed.
        """
        roster = await asyncio.to_thread(_fetch_roster)
        guild_names = await asyncio.to_thread(_fetch_guild_names)
        names, reason = fanout.resolve_targets(d.expression, roster, guild_names)
        if not names:
            await channel.send(reason[:1990])
            return
        # The strongest of the band speaks for it - resolve_targets orders
        # by level, so names[0] is a stable choice, not an arbitrary one.
        grounding = await asyncio.to_thread(_fetch_grounding, names[0])
        if grounding is None:
            await channel.send(f"{names[0]} slipped out of the world; ask again.")
            return
        prompt = voice.build_prompt(
            name=grounding["name"],
            level=grounding["level"],
            race_name=RACE_NAMES.get(grounding["race"], "creature"),
            class_name=CLASS_NAMES.get(grounding["class"], "adventurer"),
            zone=GEO.zone_name(grounding["map_id"], grounding["pos_x"], grounding["pos_y"]),
            personality=_persona_for(grounding),
            text=d.text,
        )
        try:
            decision = voice.parse_decision(await asyncio.to_thread(_ask_llm, prompt))
        except Exception:
            # The single-character path relays raw words on an outage; a band
            # must not. Guessing an order for forty characters is worse than
            # saying no, so a conjured event is refused outright instead.
            log.exception("inner voice unreachable; muster refused")
            await channel.send(
                f"The voice is silent, so I will not guess an order for {len(names)} "
                f"characters. Give {fanout.describe_expression(d.expression)} a plain "
                "command instead."
            )
            return
        if decision.command is None:
            await channel.send(decision.say[:1990])
            return
        await channel.send(f"{decision.say}  [{decision.command}]"[:1990])
        await self._muster(d, decision.command, channel)

    # --- catching up on the family (infra#2597) ---------------------------

    async def _sample_family(self) -> None:
        """Write one overseer_sample row per family member, forever.

        THIS LOOP IS THE ONLY REASON "what changed in the last six hours" CAN
        EVER BE ANSWERED. Levels, gold, turn-ins, spells and talents are all
        stored as they are NOW - characters.money is a balance, not a ledger,
        and character_queststatus_rewarded is (guid, quest, active) with no
        time on it at all. Nothing in the schema remembers what any of them
        were an hour ago. A sample row is that memory, and a delta is the
        difference between two of them.

        Which also means: this reaches FORWARDS only. The first useful window
        opens one interval after the first deploy, and digest.changes reports
        BASIS_NO_BASELINE until then rather than a zero that would read as
        "nothing happened".
        """
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                names = await asyncio.to_thread(_family_names)
                written = await asyncio.to_thread(_take_sample, names)
                pruned = await asyncio.to_thread(_prune_samples)
                log.info("sample cycle: characters=%d written=%d pruned=%d",
                         len(names), written, pruned)
            except Exception:
                # A missed sample costs resolution at one instant, never the
                # series. Taking the bridge down with it would cost all of it.
                log.exception("sample cycle failed; retrying next interval")
            await asyncio.sleep(SAMPLE_INTERVAL)

    async def _report_digest(self, query: core.DigestQuery, channel) -> None:
        """Answer "how are they?" with an account of the window asked for.

        The account is rendered by digest.render from facts this method
        fetches - deterministic, and posted whatever the LLM does. The model
        is asked for ONE line of greeting on top, grounded in the finished
        text, exactly as events.py has it voice what already happened. An
        outage costs a greeting; the numbers are never at risk.
        """
        ask = digest.Ask(hours=query.hours)
        try:
            report = await asyncio.to_thread(_build_digest, ask)
        except Exception:
            log.exception("digest failed")
            await channel.send(
                "I cannot read the family's state right now. The database or "
                "the worldserver is not answering; ask again in a minute."
            )
            return
        speaker = bonds.head_of_family()
        try:
            said = await asyncio.to_thread(
                _ask_llm, digest.build_prompt(report, speaker=speaker))
        except Exception:
            log.exception("digest voice unreachable; the account stands alone")
            said = ""
        opening = relay.sanitize(digest.opening_line(report, said, speaker=speaker))
        body = relay.sanitize(digest.render(report))
        log.info(
            "digest: hours=%.1f characters=%d measured=%s moments=%d gaps=%d",
            report.window.hours, len(report.standings), report.measured,
            len(report.moments), len(report.gaps),
        )
        # Two messages, not one clipped to 1990: the account is the product
        # and losing its tail to a greeting would be the wrong thing to drop.
        await channel.send(opening[:1990])
        for chunk in _chunks(body, 1990):
            await channel.send(chunk)


def _chunks(text: str, limit: int) -> list:
    """`text` split on line boundaries into Discord-sized pieces.

    Splitting mid-sentence is what a naive [:1990] does, and this report has
    one fact per line - a line cut in half is a number cut in half.
    """
    out, current = [], ""
    for line in text.split("\n"):
        line = line[:limit]
        if current and len(current) + 1 + len(line) > limit:
            out.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return out


# --- goal store adapters (infra#2601) --------------------------------------

GOAL_INTERVAL = float(os.environ.get("GOAL_INTERVAL_SECONDS", "60"))


def _ensure_goal_store() -> None:
    # Bridge-owned state, same reasoning as _ensure_thought_store above:
    # the worldserver never reads this table, so coupling it to a module
    # SQL rebuild would be pure friction. Deviation recorded on infra#2600.
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS overseer_goal ("
            " id INT UNSIGNED NOT NULL AUTO_INCREMENT,"
            " character_name VARCHAR(12) NOT NULL,"
            " kind ENUM('level','skill','quest') NOT NULL,"
            " skill_name VARCHAR(32) NULL,"
            " target SMALLINT UNSIGNED NOT NULL,"
            " quest_id INT UNSIGNED NOT NULL DEFAULT 0,"
            " status ENUM('active','completed','cancelled') NOT NULL DEFAULT 'active',"
            " channel_id VARCHAR(32) NOT NULL DEFAULT '',"
            " last_report TEXT NULL,"
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " completed_at TIMESTAMP NULL DEFAULT NULL,"
            " PRIMARY KEY (id), KEY idx_char_status (character_name, status)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        # CREATE TABLE IF NOT EXISTS IS A NO-OP ON A TABLE THAT ALREADY EXISTS,
        # and that includes every word of the column definitions above. The
        # live overseer_goal table was created with ENUM('level','skill'), so
        # without the two explicit migrations below a kind='quest' INSERT is
        # rejected by MySQL with "Data truncated for column 'kind'" - on the
        # live database only. Every test would pass, the feature would ship,
        # and the council's quest decisions would keep being thrown away with
        # nothing in the log to say why. This is the same trap the
        # overseer_thought 'council' enum walked into three functions up, and
        # it is written the same way here on purpose.
        #
        # Both are guarded by information_schema rather than run every start:
        # an ALTER on a table in use takes a metadata lock, and running one
        # unconditionally at every bridge restart would be a needless one.
        # Both are also idempotent by construction - the guards read the
        # CURRENT shape, so a fresh database whose CREATE above already
        # produced the final shape does nothing, and a re-run does nothing.
        cur.execute(
            "SELECT COLUMN_NAME AS c, COLUMN_TYPE AS t "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'overseer_goal' "
            "  AND COLUMN_NAME IN ('kind', 'quest_id')"
        )
        shape = {row["c"]: row["t"] for row in cur.fetchall()}
        # The DECISION is goals.goal_migrations, where it can be tested against
        # both a legacy and an already-migrated table; this end only reads the
        # current shape and executes what it is told. Statements are logged as
        # they run, because a schema change nobody can see afterwards is how
        # "it should have been applied" becomes an argument instead of a fact.
        for statement in goals.goal_migrations(
            shape.get("kind", ""), "quest_id" in shape
        ):
            cur.execute(statement)
            log.info("overseer_goal migration: %s", statement)


def _insert_goal(name: str, goal: goals.Goal, channel_id: str) -> int:
    with _connect() as conn, conn.cursor() as cur:
        # A restated goal supersedes its predecessor of the same kind, so
        # two supervisors never drive one character toward two targets.
        # <=> is MySQL's NULL-safe equality: level goals carry skill_name
        # NULL, and NULL = NULL is not true under plain equality.
        cur.execute(
            "UPDATE overseer_goal SET status = 'cancelled' "
            "WHERE character_name = %s AND kind = %s AND skill_name <=> %s "
            "AND status = 'active'",
            (name, goal.kind, goal.skill_name),
        )
        cur.execute(
            "INSERT INTO overseer_goal "
            "(character_name, kind, skill_name, target, quest_id, channel_id) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (name, goal.kind, goal.skill_name, goal.target, goal.quest_id, channel_id),
        )
        return cur.lastrowid


def _cancel_goals(name: str) -> int:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE overseer_goal SET status = 'cancelled' "
            "WHERE character_name = %s AND status = 'active'",
            (name,),
        )
        return cur.rowcount


def _fetch_active_goals() -> list[dict]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, character_name, kind, skill_name, target, quest_id, "
            "status, channel_id, last_report FROM overseer_goal "
            "WHERE status = 'active'"
        )
        return list(cur.fetchall())


def _observe_goal(row: dict) -> int | None:
    """The character's current level, skill value, or quest progress.

    None whenever the answer cannot be seen, which reconcile treats as "say
    nothing this cycle" rather than as a zero.
    """
    with _connect() as conn, conn.cursor() as cur:
        if row["kind"] == "quest":
            quest_id = int(row.get("quest_id") or 0)
            if not quest_id:
                return None
            cur.execute(_QUEST_ONE_SQL, (row["character_name"], quest_id))
            found = cur.fetchone()
            if found is None:
                # The character is not holding the quest. That is a real
                # state, not an error: the whole point of the epic's quest
                # sharing half is that the family does NOT all hold the same
                # log yet. Observing None keeps the goal alive and quiet
                # rather than completing it on a row that does not exist -
                # a missing row read as "0 objectives left" would report the
                # quest finished by somebody who never took it.
                return None
            progress = quests.read(found, found)
            if progress is None:
                # A quest with no countable objective ("go and speak to
                # someone"). There is nothing to supervise, so there is
                # nothing to say.
                return None
            return goals.observed_from_left(progress.left)
        if row["kind"] == "level":
            cur.execute(
                "SELECT level FROM overseer_snapshot "
                "WHERE name = %s AND updated_at > NOW() - INTERVAL 60 SECOND",
                (row["character_name"],),
            )
            found = cur.fetchone()
            return int(found["level"]) if found else None
        skill_id = goals.SKILL_IDS.get(row["skill_name"] or "")
        if skill_id is None:
            return None
        # character_skills is flushed on character save (minutes, not
        # seconds), so skill progress can lag reality - fine at a
        # once-a-minute supervision cadence, and it only ever under-reports.
        cur.execute(
            "SELECT cs.value FROM character_skills cs "
            "JOIN characters c ON c.guid = cs.guid "
            "WHERE c.name = %s AND cs.skill = %s",
            (row["character_name"], skill_id),
        )
        found = cur.fetchone()
        return int(found["value"]) if found else None


_LEDGER_MEMBER_SQL = (
    "SELECT c.name, c.class, c.race, COALESCE(s.level, c.level) AS level "
    "FROM characters c "
    "LEFT JOIN overseer_snapshot s "
    "       ON s.name = c.name AND s.updated_at > NOW() - INTERVAL 60 SECOND "
    "WHERE c.name IN (%s)"
)
# Held and rewarded are separate TABLES, not a status column, and questbook
# needs both: only a rewarded quest satisfies a prerequisite, while a held one
# is what the traveller can actually be aimed at.
_LEDGER_HELD_SQL = (
    # Spark-authored: qwen3-coder-next:q8_0 on DGX Spark sparkles (10.0.0.66),
    # 2026-09-01 -- the filter and its placement are the Spark's; the comment,
    # the string termination and the test were reworked by Claude before merge.
    # Its first pass left this constant an unterminated literal (bridge.py did
    # not parse) with the explanation INSIDE the SQL text as a `--` comment.
    # status: 0 none/abandoned, 1 complete, 3 incomplete. Without this filter an
    # abandoned row reads as "this character holds this quest", so questshare
    # proposes a share the worldserver can only refuse -- 167 identical retries
    # on quest 3361 before anyone noticed, because a refusal is not an error
    # anywhere it would be seen (#2892). Same statuses _QUEST_SQL already uses;
    # the two reads must not disagree about what "held" means.
    "SELECT c.name, q.quest FROM character_queststatus q "
    "JOIN characters c ON c.guid = q.guid "
    "WHERE c.name IN (%s) AND q.status IN (1, 3)"
)
_LEDGER_REWARDED_SQL = (
    "SELECT c.name, q.quest FROM character_queststatus_rewarded q "
    "JOIN characters c ON c.guid = q.guid WHERE c.name IN (%s)"
)
# Flags rides along for QUEST_FLAGS_SHARABLE (0x8), which is the server's own
# answer to "may this quest be handed to a party member": Player::CanShareQuest
# (core PlayerQuest.cpp:1517-1536) refuses without it, so questshare has to
# know before it proposes a share the worldserver can only refuse.
_LEDGER_CATALOG_SQL = (
    "SELECT t.ID, t.LogTitle, t.QuestLevel, t.MinLevel, t.AllowableRaces, "
    "       t.Flags, "
    "       a.MaxLevel, a.AllowableClasses, a.PrevQuestID, a.NextQuestID, "
    "       a.ExclusiveGroup "
    "FROM acore_world.quest_template t "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = t.ID "
    "WHERE t.ID IN (%s)"
)


def _fetch_family_quests(names: list) -> tuple:
    """(members, catalog) for the family, from live rows.

    All the reading for questbook.py AND questshare.py in one place, because
    two halves that disagree about the family are worse than one half: who is
    behind, what can be caught up, and what may be handed to whom are all
    computed against the same Members and the same catalog, in one pass.

    THE CATALOG IS THE UNION OF WHAT THE FAMILY HOLDS AND HAS TURNED IN, and
    nothing wider. questbook only ever asks about quests somebody in the family
    is carrying or has finished - behind() requires that another member was
    REWARDED for it - so pulling the whole 10,000-row quest_template would cost
    a large query to answer questions nobody asks. Around 90 ids in practice.

    ZONE IS DELIBERATELY LEFT UNKNOWN (0). questbook.Quest.zone is what marks
    Bork's Coldridge Valley rows as stalls, and quest_template's QuestSortID
    would plausibly supply it - but its positive/negative encoding has not been
    read against THIS server, and the module's own rule is that an unknown zone
    never blocks anything. Guessing it wrong would mark reachable work
    unreachable and quietly drop it out of the catch-up plan, which is the
    exact failure questbook was written to prevent. Reporting stalls is left to
    a follow-up that can verify the column first.
    """
    if not names:
        return [], {}
    placeholders = ",".join(["%s"] * len(names))
    # Hoisted for the same reason as _BOT_HELD_SQL: ruff anchors S608 at the
    # START of the expression, so a noqa on the line carrying the % does not
    # silence a multi-line query. Only the NUMBER of placeholders is
    # interpolated; every name reaches MySQL as a bound parameter.
    member_sql = _LEDGER_MEMBER_SQL % placeholders  
    held_sql = _LEDGER_HELD_SQL % placeholders      
    rewarded_sql = _LEDGER_REWARDED_SQL % placeholders
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(member_sql, names)
        rows = list(cur.fetchall())
        cur.execute(held_sql, names)
        held_rows = list(cur.fetchall())
        cur.execute(rewarded_sql, names)
        rewarded_rows = list(cur.fetchall())

        held: dict = {}
        for row in held_rows:
            held.setdefault(row["name"], set()).add(int(row["quest"]))
        rewarded: dict = {}
        for row in rewarded_rows:
            rewarded.setdefault(row["name"], set()).add(int(row["quest"]))

        wanted = sorted({q for ids in held.values() for q in ids}
                        | {q for ids in rewarded.values() for q in ids})
        catalog: dict = {}
        if wanted:
            catalog_sql = _LEDGER_CATALOG_SQL % ",".join(["%s"] * len(wanted))
            cur.execute(catalog_sql, wanted)
            for row in cur.fetchall():
                quest = questbook.Quest.from_row(row)
                catalog[quest.id] = quest

    members = [
        questbook.Member(
            name=row["name"],
            class_id=int(row["class"]),
            race_id=int(row["race"]),
            level=int(row["level"] or 0),
            rewarded=frozenset(rewarded.get(row["name"], ())),
            held=frozenset(held.get(row["name"], ())),
        )
        for row in rows
    ]
    return members, catalog


def _fetch_questbook(names: list) -> tuple:
    """(ledger, name -> held quest ids), the shape the drive path already uses.

    A thin wrapper over _fetch_family_quests, and thin ON PURPOSE: the sharing
    pass needs the Members and the catalog rather than the Ledger built out of
    them, and a second query path for the same facts is how the two halves end
    up describing different families. `held` is read back off the Members
    instead of being carried separately, so it cannot drift from them.
    """
    members, catalog = _fetch_family_quests(names)
    return questbook.build(members, catalog), {m.name: m.held for m in members}


# How long a share command is remembered before the pass is allowed to propose
# the same one again.
#
# The pass recomputes from live rows, so a share that LANDS disappears from the
# plan on its own - the taker now holds the quest and it is no longer a
# candidate. This window is for the other case: a share the worldserver
# refuses. Without it the pass would re-insert an identical doomed row every
# cycle forever, and the queue would fill with the same refusal. With it, the
# refusal is retried occasionally - which is right, because most refusals are
# temporary (log full, out of range, prerequisite not yet turned in) and the
# permanent ones are already excluded by questshare before they get here.
SHARE_RETRY_MINUTES = int(os.environ.get("SHARE_RETRY_MINUTES", "60"))

# The window above retries a refusal about once an hour. This is where that
# stops being hourly: a (holder, taker, command) the worldserver has refused
# for a PERMANENT reason waits SHARE_RETRY_MINUTES * 2**n before the next
# offer, capped at SHARE_BACKOFF_CAP_HOURS. infra#2892 was 167 identical
# attempts at a quest Bork held at status 0 - the read is fixed, this is what
# keeps the next wrong row from paging hourly. Which reasons are permanent,
# and the arithmetic, live in questshare (backed_off), not here: a taker who
# was offline or on another map five times is offered the quest again as soon
# as that changes, and a delivered share resets the streak. The bridge fetches
# SHARE_REFUSAL_MEMORY_DAYS of rows; the table is never pruned, this only
# bounds the query.
SHARE_BACKOFF_CAP_HOURS = int(os.environ.get("SHARE_BACKOFF_CAP_HOURS", "168"))
SHARE_REFUSAL_MEMORY_DAYS = int(os.environ.get("SHARE_REFUSAL_MEMORY_DAYS", "90"))


def _recent_share_keys(minutes: int) -> set:
    """(holder, taker, command) triples already proposed inside the window."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT target_name, target_arg, command FROM overseer_command "
            "WHERE kind = 'share' AND created_at > NOW() - INTERVAL %s MINUTE",
            (int(minutes),),
        )
        return {
            (row["target_name"], row["target_arg"], row["command"])
            for row in cur.fetchall()
        }


def _answered_share_rows(days: int, depth: int) -> list:
    """The youngest `depth` answers per (holder, taker, quest, status,
    reason) the worldserver wrote inside the window - delivered or refused
    - with the JSON it wrote and how long ago it ANSWERED, by the
    database's own clock, for questshare.backed_off() to judge. Rows only:
    which refusals are permanent, which gate each came from, that a later
    gate resets an earlier streak, and how long a streak holds are the pure
    module's call.

    `depth` is questshare.history_depth(): the streak length at which the
    doubling reaches its cap, past which more refusals of the same reason
    change nothing, and one row of any other reason (or one delivery) says
    everything a younger answer can say. Windowed per reason in SQL, the
    read is bounded by the number of live triples, not by ninety days of
    hourly transient retries - a party split for a season would otherwise
    hand this loop two hundred thousand rows every five minutes and the
    read timeout would stop EVERY share, not just the backed-off ones.
    The partition key extracts result.reason with JSON_VALID guarding
    JSON_EXTRACT (a row the worldserver never answered has NULL there,
    and JSON_EXTRACT on non-JSON is an error, not a NULL).

    updated_at, not created_at: a row can wait pending or claimed before
    the worldserver reaches it, and the backoff clock must start at the
    refusal, not at the ask - measured from created_at, a queue delay would
    eat the quiet time. The terminal write stamps updated_at. The index
    this reads through is 2026_09_02_00_overseer_share_backoff.sql."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT target_name, target_arg, command, status, result, age_s "
            "FROM ("
            "  SELECT target_name, target_arg, command, status, result, "
            "    TIMESTAMPDIFF(SECOND, updated_at, NOW()) AS age_s, "
            "    ROW_NUMBER() OVER ("
            "      PARTITION BY target_name, target_arg, command, status, "
            "        CASE WHEN JSON_VALID(result) "
            "             THEN JSON_UNQUOTE(JSON_EXTRACT(result, '$.reason')) END "
            "      ORDER BY updated_at DESC) AS rn "
            "  FROM overseer_command "
            "  WHERE kind = 'share' AND status IN ('delivered', 'error') "
            "    AND updated_at > NOW() - INTERVAL %s DAY"
            ") AS answered "
            "WHERE rn <= %s",
            (int(days), int(depth)),
        )
        return [
            (
                row["target_name"], row["target_arg"], row["command"],
                row["status"], row["result"], row["age_s"],
            )
            for row in cur.fetchall()
        ]


def _insert_share(grant) -> int:
    """One overseer_command row for one grant.

    target_name is the HOLDER and target_arg is the TAKER, the same column
    roles kind='give' uses for giver and receiver, so an operator reading the
    queue does not have to learn a second convention.

    THE ENUM CAN LEGITIMATELY BE MISSING, exactly as overseer_roster.drive_quest
    can: 'share' arrives with mod-overseer's SQL, applied by the worldserver at
    startup, and the bridge is a separate deployment with its own restarts.
    MySQL in strict mode rejects the unknown value with 1265 rather than
    quietly storing something else. Warned rather than swallowed - a sharing
    pass that never lands is a real fault and has to be visible without killing
    the loop.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, 'share', %s, %s)",
                (grant.holder, grant.command, grant.taker, "questshare"),
            )
        except pymysql.err.MySQLError as exc:
            # 1265 is ER_WARN_DATA_TRUNCATED, which is what an unknown ENUM
            # value raises under strict mode. Matched on the code, not the
            # message text, which is localised.
            if exc.args and exc.args[0] == 1265:
                log.warning(
                    "overseer_command.kind has no 'share' value - sharing quest "
                    "%d from %s to %s needs the worldserver image carrying "
                    "mod-overseer's SQL (infra#2778)",
                    grant.quest_id, grant.holder, grant.taker,
                )
                return 0
            raise
        return cur.lastrowid or 0


def _share_quests() -> questshare.Plan:
    """Hand every family member the quests the others are already carrying.

    THE DECISION IS NOT MADE HERE. questshare.plan() answers what may be
    shared, to whom, and in what order, against questbook's rules - class
    locks, the Alliance mask, the class-id-versus-bitmask conversion, the
    prerequisite chain, and the Coldridge Valley rows that would otherwise
    march the family to another continent. This function reads rows, inserts
    commands, and says what it did.

    IT SAYS WHAT IT DID EVEN WHEN IT DID NOTHING. questshare.say() carries both
    counts and the refusal breakdown, so "nothing to share" and "everything was
    refused because no quest in this zone carries QUEST_FLAGS_SHARABLE" are one
    log line apart rather than indistinguishable silence.
    """
    names = sorted(_protected_guids().values())
    members, catalog = _fetch_family_quests(names)
    plan = questshare.plan(members, catalog)

    seen = _recent_share_keys(SHARE_RETRY_MINUTES)
    held = questshare.backed_off(
        _answered_share_rows(
            SHARE_REFUSAL_MEMORY_DAYS,
            questshare.history_depth(SHARE_RETRY_MINUTES, SHARE_BACKOFF_CAP_HOURS),
        ),
        SHARE_RETRY_MINUTES,
        SHARE_BACKOFF_CAP_HOURS,
    )
    inserted = 0
    for grant in plan.grants:
        if not grant.holder:
            # questshare only emits a grant for a quest somebody is carrying,
            # so this cannot happen - and if it ever does, it is a bug worth a
            # line rather than a command row naming nobody.
            log.warning("questshare: no holder for quest %d, skipping", grant.quest_id)
            continue
        if (grant.holder, grant.taker, grant.command) in seen:
            continue
        if (grant.holder, grant.taker, grant.command) in held:
            log.info(
                "questshare: holding off %s -> %s quest %d, the worldserver keeps "
                "refusing it for a permanent reason; the wait doubles each time, "
                "up to %dh",
                grant.holder, grant.taker, grant.quest_id, SHARE_BACKOFF_CAP_HOURS,
            )
            continue
        if _insert_share(grant):
            inserted += 1
    log.info("%s; %d command(s) inserted", questshare.say(plan), inserted)
    return plan


# One row per reagent stack currently sitting in a family member's bags,
# for whichever materials materials.REAGENTS names. Joined the same way
# _QUEST_SQL joins acore_world for item names (i1.name/i2.name above) - a
# LEFT JOIN would be wrong here, deliberately: an item whose entry has no
# item_template row cannot be given a name and cannot be matched against
# REAGENTS, so it is correctly invisible to this query rather than showing up
# as a material named NULL.
#
# `NOT (ci.bag = 0 AND ci.slot < 19)` excludes EQUIPMENT_SLOT_END-in-bag-0,
# the same range _STANDING_SQL's `equipped` subquery counts - reagents are
# never worn, so this only ever excludes gear, never a bag or backpack slot.
#
# UNVERIFIED AGAINST A LIVE SERVER. wow-dev is mid-RAM-swap (see the PR this
# landed in) - this join has not been run against real character_inventory
# rows. materials.py's own tests cover the DECISION against synthetic
# Holdings; this query is the one part of #2830 that could not be watched.
_HOLDINGS_SQL = (
    "SELECT c.name AS holder, it.name AS material, "
    "       ii.count AS count, ii.guid AS item_guid "
    "FROM character_inventory ci "
    "JOIN characters c                  ON c.guid = ci.guid "
    "JOIN item_instance ii              ON ii.guid = ci.item "
    "JOIN acore_world.item_template it  ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s) "
    "  AND NOT (ci.bag = 0 AND ci.slot < 19) "
    "  AND it.name IN (%s)"
)


def _fetch_holdings(names: list) -> list:
    """materials.Holding for every reagent stack the family is carrying."""
    reagent_names = sorted(materials.REAGENTS)
    if not names or not reagent_names:
        return []
    sql = _HOLDINGS_SQL % (
        ",".join(["%s"] * len(names)), ",".join(["%s"] * len(reagent_names))
    )
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names + reagent_names)
        return [
            materials.Holding(
                holder=row["holder"], material=row["material"],
                count=int(row["count"]), guid=int(row["item_guid"]),
            )
            for row in cur.fetchall()
        ]


def _fetch_free_slots(names: list) -> dict:
    """Read carried capacity facts; materials decides which refusals reopen."""
    if not names:
        return {}
    sql = (
        "SELECT c.name, "
        "SUM(CASE WHEN ci.bag = 0 AND ci.slot BETWEEN 23 AND 38 "
        "         THEN 1 ELSE 0 END) AS backpack_used, "
        "SUM(CASE WHEN ci.bag <> 0 THEN 1 ELSE 0 END) AS bag_used, "
        "SUM(CASE WHEN ci.bag = 0 AND ci.slot BETWEEN 19 AND 22 "
        "         THEN COALESCE(it.ContainerSlots, 0) ELSE 0 END) AS bag_slots "
        "FROM character_inventory ci "
        "JOIN characters c ON c.guid = ci.guid "
        "LEFT JOIN item_instance ii ON ii.guid = ci.item "
        "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
        "WHERE c.name IN (%s) GROUP BY c.name"
    ) % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        return {
            row["name"]: max(
                0,
                16 + int(row["bag_slots"] or 0)
                - int(row["backpack_used"] or 0)
                - int(row["bag_used"] or 0),
            )
            for row in cur.fetchall()
        }


# How long a give command is remembered before the pass is allowed to propose
# the same one again - the give sibling of SHARE_RETRY_MINUTES, for the same
# reason: a give the worldserver refuses (receiver offline, bags full since
# measured) must not fill the queue with an identical doomed row every cycle.
GIVE_RETRY_MINUTES = int(os.environ.get("GIVE_RETRY_MINUTES", "60"))


# How far back the family looks before deciding the world means it. A day,
# not GIVE_RETRY_MINUTES: the live refusals were SEVEN identical
# `receiver bags are full` errors spread over six hours, so an hour-wide
# window sees one or two of them and never reaches materials.GIVE_UP_AFTER.
# Bounded rather than unbounded on purpose - a give that has been refused all
# day is worth trying once more tomorrow, in case the bags were emptied.
GIVE_GIVE_UP_HOURS = int(os.environ.get("GIVE_GIVE_UP_HOURS", "24"))


# How far back the vendor pass looks for sales the world has already
# answered. A day, not GIVE_RETRY_MINUTES, and for the opposite reason to a
# retry window: a `delivered` sale or an `item not carried` refusal is a
# PERMANENT fact about that item, and forgetting it after an hour brings the
# whole retry storm back. Bounded rather than unbounded because item guids
# are eventually recycled by the core, and a day is far longer than any
# vendor errand.
SELL_MEMORY_HOURS = int(os.environ.get("SELL_MEMORY_HOURS", "24"))

# The routes the family can actually carry out today. Adding AUCTION here is
# the whole of the change when mod-overseer#208 lands, and BANK when the
# bank pass starts writing rows (infra#3329).
SELL_ROUTES = disposition.EXECUTABLE_TODAY

# Items the owner has marked as never-dispose, by name, comma separated.
# Empty by default: this is a hand brake the owner pulls, not a policy the
# process invents. Checked on both halves of the vendor pass, before any
# other rule, so a marked item cannot be reached by any route that ends in a
# merchant.
OWNER_KEEPS = tuple(
    part.strip() for part in os.environ.get("OWNER_KEEPS", "").split(",")
    if part.strip()
)


def _give_attempts(hours: int) -> list:
    """Every give this family has tried lately, and how the world answered.

    READ-ONLY, and it reads `status`/`detail` rather than counting rows: a
    pending give is one nobody has answered yet, which is not the same thing
    as a refusal, and materials.stuck depends on being able to tell them
    apart (mod-overseer#169).
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, target_arg, status, detail "
                "FROM overseer_command "
                "WHERE kind = 'give' AND created_at > NOW() - INTERVAL %s HOUR",
                (int(hours),),
            )
            rows = cur.fetchall()
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table: a world without the
            # give machinery has refused nothing, so nothing is stuck.
            if exc.args and exc.args[0] in (1054, 1146):
                return []
            raise
    return [
        materials.Attempt(
            holder=row["target_name"], taker=row["target_arg"],
            status=row["status"] or "", detail=row["detail"] or "",
        )
        for row in rows
    ]


_VENDOR_ITEMS_SQL = (
    "SELECT c.name AS holder, ii.guid AS item_guid, ii.count AS count, "
    "it.name AS name, it.Quality AS quality, it.SellPrice AS sell_price, "
    "(it.class = 12) AS quest_item, (it.class = 5) AS reagent "
    "FROM character_inventory ci "
    "JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s) AND ((ci.bag = 0 AND ci.slot BETWEEN 19 AND 38) "
    "OR ci.bag IN (SELECT bag.item FROM character_inventory bag "
    "WHERE bag.guid = ci.guid AND bag.bag = 0 AND bag.slot BETWEEN 19 AND 22)) "
    "AND it.class <> 1"
)


# Carried weapons and armour of uncommon quality or better, with the two
# facts that decide what may be done with them: the wearer's level, and
# whether THIS COPY is already soulbound. `ii.flags` is handed over raw so
# the bit is read in bag_pressure.item_binding rather than in SQL; the same
# bag-and-backpack scope as _VENDOR_ITEMS_SQL, so nothing worn is offered.
_SURPLUS_GEAR_SQL = (
    "SELECT c.name AS holder, c.level AS level, ii.guid AS item_guid, "
    "ii.itemEntry AS entry, "
    "ii.count AS count, ii.flags AS instance_flags, it.name AS name, "
    "it.Quality AS quality, it.SellPrice AS sell_price, "
    "it.RequiredLevel AS required_level, it.bonding AS bonding, "
    "it.class AS item_class, it.ItemLevel AS item_level, "
    "it.AllowableClass AS allowable_class, "
    "it.InventoryType AS inventory_type "
    "FROM character_inventory ci "
    "JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s) AND ((ci.bag = 0 AND ci.slot BETWEEN 19 AND 38) "
    "OR ci.bag IN (SELECT bag.item FROM character_inventory bag "
    "WHERE bag.guid = ci.guid AND bag.bag = 0 AND bag.slot BETWEEN 19 AND 22)) "
    "AND it.class IN (2, 4) AND it.Quality >= 2"
)


def _fetch_surplus_gear(names: list) -> list:
    """Read carried gear facts; every route decision stays in bag_pressure."""
    if not names:
        return []
    sql = _SURPLUS_GEAR_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
        except pymysql.err.MySQLError as exc:
            # 1054 on a world image whose item_instance predates `flags`.
            # Without that column this side cannot tell a worn green from a
            # tradable one, and guessing is how value gets vendored away.
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("surplus gear facts unavailable on this world image")
                return []
            raise
        return [dict(row) for row in cur.fetchall()]


# What each of the five is WEARING, which is the half of the family-fit gate
# the carried-gear query cannot see (infra#3449). LEFT JOINed from
# `characters` on purpose: a character wearing nothing must still come back
# with a name, a class and a level, because gear.characters_from_rows leaving
# them out means every piece they carry answers UNJUDGEABLE and is kept.
#
# bag 0 and slot < 19 is the worn range, the exact complement of the range
# _SURPLUS_GEAR_SQL selects, so no item can appear in both.
_FAMILY_EQUIPPED_SQL = (
    "SELECT c.name AS name, c.class AS class_id, c.level AS level, "
    "it.InventoryType AS inventory_type, it.ItemLevel AS item_level "
    "FROM characters c "
    "LEFT JOIN character_inventory ci ON ci.guid = c.guid "
    "AND ci.bag = 0 AND ci.slot < 19 "
    "LEFT JOIN item_instance ii ON ii.guid = ci.item "
    "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s)"
)


def _fetch_family_equipped(names: list) -> list:
    """Read what the family is wearing; gear.py decides what it means.

    Same 1054/1146 swallow as _fetch_surplus_gear, and the same consequence
    stated plainly: no rows means no CharacterStates, which means every
    carried piece is UNJUDGEABLE and the vendor pass offers nothing. Refusing
    to sell is the correct answer to not knowing what anybody is wearing.
    """
    if not names:
        return []
    sql = _FAMILY_EQUIPPED_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("equipped facts unavailable on this world image")
                return []
            raise
        return [dict(row) for row in cur.fetchall()]


def _fetch_vendor_items(names: list) -> list:
    """Read carried sale facts; all routing remains in bag_pressure."""
    if not names:
        return []
    sql = _VENDOR_ITEMS_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        rows = []
        for row in cur.fetchall():
            item = dict(row)
            # Trade goods such as Linen are class 7, not class 5. The
            # profession roster is the stronger fact and must protect them
            # even when item_template calls them ordinary trade goods.
            profession_material = item.get("name") in materials.REAGENTS
            item["reagent"] = bool(item.get("reagent")) or profession_material
            item["profession_needed"] = profession_material
            rows.append(item)
        return rows


def _sell_attempts(hours: int) -> list:
    """Every sale the world has already answered, as item_plan reads them.

    READ-ONLY, and it reads `status`, `detail` and `result` rather than
    counting rows. What may be re-issued is decided by what the world SAID,
    and `result` carries the retry word and the true stack beside the refusal
    literal. The predecessor of this function compared a bare `guid:N` key
    against the stored `guid:N count:M` command, so it never matched anything
    and the retry window it was supposed to enforce was never enforced.

    A world with no sell history has answered nothing, so 1146 (missing
    table) and 1054 (missing column) return an empty history rather than
    raising. That is deliberately the FAIL-OPEN direction: it degrades to the
    behaviour this pass already had, where a gate that cannot read its
    evidence would otherwise quietly stop the family selling anything.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, command, status, detail, result "
                "FROM overseer_command "
                "WHERE kind = 'sell' AND created_at > NOW() - INTERVAL %s HOUR",
                (int(hours),),
            )
            rows = cur.fetchall()
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                return []
            raise
    attempts = [item_plan.attempt_from_row(row) for row in rows]
    return [attempt for attempt in attempts if attempt is not None]


def _insert_sell(candidate: bag_pressure.SellCandidate) -> int:
    """Queue one explicitly chosen stack for the world-side vendor executor."""
    command = "guid:%d count:%d" % (candidate.item_guid, candidate.count)
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, 'sell', '', %s)",
                (candidate.holder, command, "economy"),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1146, 1265):
                log.warning("sell command unavailable on this world image")
                return 0
            raise
        return cur.lastrowid or 0


def _active_dungeon_run() -> dict | None:
    """The run the family is in the middle of, or None.

    `overseer_dungeon_run` is written by the C++ side and can legitimately be
    absent on a world whose image predates it - map_server.py already treats
    it that way ("overseer_dungeon_run absent; achievements run without it").
    Absent means "no run", which is the answer that lets the family carry on
    talking rather than going silent forever.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT leader_name, map_id, state, members "
                "FROM overseer_dungeon_run WHERE state = 'active' "
                "ORDER BY id DESC LIMIT 1"
            )
            return cur.fetchone()
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                return None
            raise


def _roster_jobs() -> dict:
    """name -> `overseer_roster.job`, the fallback half of chat.mid_run."""
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT name, job FROM overseer_roster WHERE enabled = 1")
            return {row["name"]: row["job"] for row in cur.fetchall()}
        except pymysql.err.MySQLError as exc:
            # `job` arrived in a migration (infra#2834); a world without it
            # has no job to read and mid_run falls back to the member list.
            if exc.args and exc.args[0] in (1054, 1146):
                return {}
            raise


def _run_place(run: dict | None) -> str:
    """What the family would call where they are, for a stand-down line."""
    if not run:
        return ""
    dungeon = achievements.DUNGEONS.get(int(run.get("map_id") or 0), {})
    return dungeon.get("name", "")


def _recent_give_keys(minutes: int) -> set:
    """(holder, taker, command) triples already proposed inside the window."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT target_name, target_arg, command FROM overseer_command "
            "WHERE kind = 'give' AND created_at > NOW() - INTERVAL %s MINUTE",
            (int(minutes),),
        )
        return {
            (row["target_name"], row["target_arg"], row["command"])
            for row in cur.fetchall()
        }


def _insert_give(grant: materials.Grant) -> int:
    """One overseer_command row moving one material stack (infra#2830).

    Reuses kind='give' (infra#2597) rather than adding a new kind: DoGive
    already moves exactly one item_instance guid from one living character's
    bags into another's, in one CharacterDatabase transaction, and does not
    care why. See tests/test_give.py for what is already proven about the
    mechanism, and professions.py's own "this module DECIDES and never
    GRANTS" rule for why that mechanism - and not a database row pretending
    the material moved - is the only acceptable shape here.

    Guarded against the missing-ENUM case on the same 1265 code _insert_share
    checks, for the same reason: a worldserver behind the migration must
    warn rather than raise.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, 'give', %s, %s)",
                (grant.holder, grant.command, grant.taker, "materials"),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] == 1265:
                log.warning(
                    "overseer_command.kind has no 'give' value - moving %d "
                    "%s from %s to %s needs the worldserver image carrying "
                    "mod-overseer's give SQL (infra#2597)",
                    grant.count, grant.material, grant.holder, grant.taker,
                )
                return 0
            raise
        return cur.lastrowid or 0


def _recent_trade_keys(minutes: int) -> set:
    """(holder, taker, command) triples already proposed inside the window.

    Its own reader rather than a widened _recent_give_keys, because the two
    kinds have to stay tellable apart: a reagent hand-off and a gear hand-off
    can name the same guid form, and a shared window would let one pass
    silence the other's retry. Degrades to "nothing is queued" on a world
    image with no 'trade' value, the same direction _recent_town_keys takes.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, target_arg, command FROM overseer_command "
                "WHERE kind = 'trade' AND created_at > NOW() - INTERVAL %s MINUTE",
                (int(minutes),),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return set()
            raise
        return {
            (row["target_name"], row["target_arg"], row["command"])
            for row in cur.fetchall()
        }


def _insert_gear_trade(grant) -> int:
    """One overseer_command row handing one carried piece to a sibling.

    The giver in target_name, the receiver in target_arg and the
    item_instance guid in the command - the same three roles kind='give'
    already uses, so an operator reading the queue does not have to learn a
    second layout. source='gear' is what separates this from the reagent and
    bag hand-offs in the log and in the retry window above.

    Guarded on 1265 like every other kind this process writes: a worldserver
    behind mod-overseer's trade migration must warn rather than raise and
    take the whole economy pass down with it.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, 'trade', %s, %s)",
                (grant.holder, grant.command, grant.taker, "gear"),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1146, 1265):
                log.warning(
                    "overseer_command.kind has no 'trade' value - handing %s "
                    "from %s to %s needs the worldserver image carrying "
                    "mod-overseer's trade SQL (mod-overseer#14)",
                    grant.name, grant.holder, grant.taker,
                )
                return 0
            raise
        return cur.lastrowid or 0


# Every container the family owns and where it sits. `used` is how many items
# are inside it, for the worn bags. ITEM_CLASS_CONTAINER is 1; quivers and
# ammo pouches are a different class and would not take ordinary loot, so
# they are not bags for this purpose. The bank ranges come back too and are
# set aside in bag_upgrade.members_from_rows, where the rule can be tested.
_BAG_STATE_SQL = (
    "SELECT c.name AS holder, ii.guid AS guid, it.name AS name, "
    "       it.ContainerSlots AS slots, ci.bag AS bag, ci.slot AS slot, "
    "       COALESCE(fill.n, 0) AS used "
    "FROM character_inventory ci "
    "JOIN characters c                  ON c.guid = ci.guid "
    "JOIN item_instance ii              ON ii.guid = ci.item "
    "JOIN acore_world.item_template it  ON it.entry = ii.itemEntry "
    "LEFT JOIN (SELECT bag, COUNT(*) AS n FROM character_inventory "
    "           WHERE bag <> 0 GROUP BY bag) fill ON fill.bag = ii.guid "
    "WHERE c.name IN (%s) AND it.class = 1 AND it.ContainerSlots > 0"
)


def _fetch_bag_state(names: list) -> list:
    """Rows for bag_upgrade.members_from_rows; no judgement here."""
    if not names:
        return []
    sql = _BAG_STATE_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        return [dict(row) for row in cur.fetchall()]


def _insert_bag_give(move, command: str) -> int:
    """One overseer_command row handing one bag over, source='bags'.

    Same row shape and the same 1265 guard as _insert_give: the giver in
    target_name, the receiver in target_arg, the item_instance guid in the
    command. A different `source` so the log and the queue can tell a bag
    handover from a reagent one.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, 'give', %s, %s)",
                (move.giver, command, move.receiver, "bags"),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] == 1265:
                log.warning(
                    "overseer_command.kind has no 'give' value - handing %s "
                    "from %s to %s needs the worldserver image carrying "
                    "mod-overseer's give SQL (infra#2597)",
                    move.bag, move.giver, move.receiver,
                )
                return 0
            raise
        return cur.lastrowid or 0


# Every item the family owns and where it sits, both sides of the bank
# counter. ONE query and no WHERE on the geography, because the bank pass has
# to see both sides at once: what is in the bags decides what goes down, what
# is in the bank decides what comes back, and the free room on each side is
# counted from the same rows. Filtering here would mean counting room in SQL,
# and slot arithmetic is exactly what belongs in the pure module.
#
# `it.class` and `it.bonding` come along raw. Which class is a container and
# which bonding is soulbound is bank.item_from_row's to say, against the same
# constants disposition already reasons in.
#
# UNVERIFIED AGAINST A LIVE SERVER, the same caveat _HOLDINGS_SQL carries:
# nothing in this change has been run against real character_inventory rows.
# bank.py's own tests cover the DECISION against rows written by hand.
_BANK_ITEMS_SQL = (
    "SELECT c.name AS holder, c.level AS level, ii.guid AS item_guid, "
    "       ii.count AS count, it.name AS name, it.Quality AS quality, "
    "       it.SellPrice AS sell_price, it.RequiredLevel AS required_level, "
    "       it.bonding AS bonding, it.class AS item_class, "
    "       it.ContainerSlots AS container_slots, "
    "       ci.bag AS bag, ci.slot AS slot "
    "FROM character_inventory ci "
    "JOIN characters c                  ON c.guid = ci.guid "
    "JOIN item_instance ii              ON ii.guid = ci.item "
    "JOIN acore_world.item_template it  ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s)"
)


def _fetch_bank_items(names: list) -> list:
    """Rows for bank.members_from_rows; no judgement and no arithmetic here."""
    if not names:
        return []
    sql = _BANK_ITEMS_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        return [dict(row) for row in cur.fetchall()]


def _recent_bank_keys(minutes: int) -> set:
    """(character, command) pairs already proposed inside the retry window.

    The bank sibling of _recent_sell_keys, and the reason a walk that has not
    finished does not fill the queue: a deposit whose character is still on
    the road to the banker is refused with `banker not in range`, and an
    identical row every cycle would turn one slow journey into a hundred dead
    commands.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, command FROM overseer_command "
                "WHERE kind = 'bank' AND created_at > NOW() - INTERVAL %s MINUTE",
                (int(minutes),),
            )
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table, 1265 a `kind` ENUM with
            # no 'bank' value. A world with none of the bank machinery has
            # been asked for nothing, so nothing is already queued.
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return set()
            raise
        return {(row["target_name"], row["command"]) for row in cur.fetchall()}


def _insert_bank(move, command: str) -> int:
    """One overseer_command row moving one item across a banker's counter.

    THE COLUMNS DO NOT MEAN WHAT THEY MEAN FOR A GIVE. mod-overseer#207 puts
    THE CHARACTER in `target_name` and leaves `target_arg` unused, where a
    give puts the giver in one and the receiver in the other. A bank row with
    a name in `target_arg` would still be delivered and would still be wrong,
    which is why the empty string is written literally rather than left to a
    default.

    Guarded on 1146 and 1265 exactly as _insert_sell and _insert_give are: a
    worldserver whose image predates the bank migration must warn rather than
    take the whole pass down.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, 'bank', '', %s)",
                (move.character, command, "economy"),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1146, 1265):
                log.warning(
                    "overseer_command.kind has no 'bank' value - %s cannot "
                    "%s %s until the worldserver image carrying "
                    "mod-overseer's bank SQL has shipped (mod-overseer#207)",
                    move.character, move.verb, move.item,
                )
                return 0
            raise
        return cur.lastrowid or 0


# How close a counter has to be before this pass will plan against it.
#
# THE CORE'S OWN INTERACTION DISTANCE IS 5 YARDS, and DoRepair and DoBuy both
# fail against anything further, so a plan built from a wider net is a queue of
# refusals. The box below is per-axis rather than a radius - it is what an index
# can use - so its corner is about eleven yards, which is the core's five plus
# the few a bot actually stops short by.
#
# THE CONSEQUENCE, NAMED RATHER THAN HIDDEN: a repairer and a food vendor
# standing further apart than this are not both "in town" as far as this pass is
# concerned. The leader is aimed at the repairer, so the repair rows land and
# the purchases come back as a note saying no reachable vendor stocks the item.
# That is the honest answer for one aim, and a second leg that walks them to a
# vendor afterwards is the obvious next change rather than something to fake
# here by widening the net.
TOWN_COUNTER_YARDS = 8

# Every spawn near the leader that can repair or sell, and what it sells.
#
# POSITION COMES FROM overseer_snapshot AND NOT FROM `characters`. The
# characters row is written on the player-save timer, so its position can be a
# quarter of an hour stale - long enough to still show the family at the dungeon
# door after they have walked to town, which would make this read the wrong
# town's counters. The snapshot is refreshed continuously by the module itself,
# and a stale one is filtered out rather than trusted.
_TOWN_COUNTERS_SQL = (
    "SELECT ct.npcflag AS npcflag, nv.item AS item "
    "FROM overseer_snapshot s "
    "JOIN acore_world.creature cr ON cr.map = s.map_id "
    "AND ABS(cr.position_x - s.pos_x) <= %s AND ABS(cr.position_y - s.pos_y) <= %s "
    "JOIN acore_world.creature_template ct ON ct.entry = cr.id "
    "LEFT JOIN acore_world.npc_vendor nv ON nv.entry = cr.id "
    "WHERE s.name = %s AND s.updated_at > NOW() - INTERVAL 120 SECOND "
    "AND (ct.npcflag & %s) <> 0"
)

# Worn items and their wear, plus the three facts about the wearer that come
# free with the join. LEFT on item_template on purpose: a missing template row
# means the item cannot be priced, not that the wearer should vanish from the
# trip. The slot bound is len(armory.EQUIPPED_SLOTS) and never a literal 19.
_TOWN_WORN_SQL = (
    "SELECT c.name AS holder, c.class AS klass_id, c.money AS money, "
    "COALESCE(s.level, c.level) AS level, ii.itemEntry AS entry, "
    "it.name AS item_name, ii.durability AS durability, "
    "it.MaxDurability AS max_durability "
    "FROM characters c "
    "LEFT JOIN overseer_snapshot s ON s.name = c.name "
    "AND s.updated_at > NOW() - INTERVAL 60 SECOND "
    "JOIN character_inventory ci ON ci.guid = c.guid AND ci.bag = 0 AND ci.slot < %s "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s)"
)

# EVERY CARRIED STACK OF ANYTHING EATEN OR DRUNK, ONE ROW PER STACK, ASKED OF
# THE WORLD RATHER THAN OF A LIST (infra#3464).
#
# The predecessor of this query filtered `ii.itemEntry IN (...)` against the
# twelve vendor tiers towntrip.FOOD and towntrip.DRINK name, so conjured food,
# conjured water and anything looted were all invisible to it and every one of
# their holders read as carrying nothing. `it.spellcategory_1` is the game's
# own classification (11 eaten, 59 drunk) and is what mod-playerbots and
# mod-overseer both ask; towntrip.CATEGORY_KIND decides what the number means,
# because that is a decision and decisions do not belong in a WHERE clause.
#
# NOT GROUPED ANY MORE EITHER. A hand-off moves one item_instance, so the guid
# of each stack has to survive the crossing; towntrip sums them. `it.Flags`
# comes over raw for the same reason `ii.flags` does on the gear path - the
# conjured bit is read in the pure module where a test can reach it.
#
# The bag scope is the carried one: bag 0 slot < 19 is what a character is
# WEARING and nobody eats their boots.
_TOWN_CARRIED_SQL = (
    "SELECT c.name AS holder, ii.guid AS guid, ii.itemEntry AS entry, "
    "it.name AS name, ii.count AS carried, "
    "it.spellcategory_1 AS spell_category, it.Flags AS item_flags "
    "FROM characters c "
    "JOIN character_inventory ci ON ci.guid = c.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s) AND it.spellcategory_1 IN (%%s, %%s) "
    "AND NOT (ci.bag = 0 AND ci.slot < 19)"
)

# The spellbook, for the conjure check and nothing else. Written on the
# player-save timer like the position above, so it can be a quarter of an hour
# behind - and towntrip.py already writes down why that is safe in this
# direction: a rank nobody has measured yet only means a stack of water bought
# that was not needed.
_TOWN_SPELLS_SQL = (
    "SELECT c.name AS holder, sp.spell AS spell "
    "FROM characters c JOIN character_spell sp ON sp.guid = c.guid "
    "WHERE c.name IN (%s)"
)


def _fetch_town(leader: str):
    """What the counters within reach of the leader can do, as a towntrip.Town.

    An empty answer is the normal state for most of a trip: it is what the world
    looks like while they are still walking. towntrip.plan turns that into notes
    rather than errands, which is what keeps the queue clean.
    """
    want = towntrip.NPC_FLAG_VENDOR | towntrip.NPC_FLAG_REPAIR
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                _TOWN_COUNTERS_SQL,
                (TOWN_COUNTER_YARDS, TOWN_COUNTER_YARDS, leader, want),
            )
            rows = [dict(row) for row in cur.fetchall()]
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table. A world image without
            # overseer_snapshot cannot say where anybody is standing, and the
            # honest reading of that is "no counter is in reach", which plans
            # nothing rather than planning against a guess.
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("towntrip: cannot see where the family is standing")
                return towntrip.Town()
            raise
    return towntrip.town_from_rows(rows)


def _fetch_town_worn(names: list) -> list:
    """One row per worn item, with the wearer's class, level and purse."""
    if not names:
        return []
    sql = _TOWN_WORN_SQL % ("%s", ",".join(["%s"] * len(names)))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (len(armory.EQUIPPED_SLOTS), *names))
        rows = [dict(row) for row in cur.fetchall()]
    # The class arrives as the core's integer and towntrip wants the lowercase
    # word its MANA_CLASSES set is keyed on. Named here, at the edge, so the
    # pure module never sees a number it would have to know how to decode.
    for row in rows:
        row["klass"] = CLASS_NAMES.get(row.get("klass_id") or 0, "")
    return rows


def _fetch_town_carried(names: list) -> list:
    """Every carried stack of food or drink; towntrip decides what it means.

    Degrades to "they carry nothing" on 1054 or 1146, which is the direction
    the rest of this pass takes: a world image with no `spellcategory_1` or no
    item_template cannot say what a consumable is, and planning against a
    guess is how a stack gets bought for somebody who has two.
    """
    if not names:
        return []
    sql = _TOWN_CARRIED_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, (*names, towntrip.CONSUMABLE_CATEGORY_FOOD,
                              towntrip.CONSUMABLE_CATEGORY_DRINK))
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("towntrip: cannot read what anybody is carrying")
                return []
            raise
        return [dict(row) for row in cur.fetchall()]


def _fetch_town_spells(names: list) -> list:
    """Known spell ids, for the conjure check and nothing else."""
    if not names:
        return []
    sql = _TOWN_SPELLS_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        return [dict(row) for row in cur.fetchall()]


def _recent_town_keys(minutes: int) -> set:
    """(character, command) pairs already proposed inside the retry window.

    The town-trip sibling of _recent_bank_keys, and it is what stops a walk that
    has not finished from filling the queue: a repair whose character is still
    on the road is refused with `repairer not in range`, and an identical row
    every cycle would turn one slow journey into a hundred dead commands.

    SCOPED TO source='towntrip' NOW THAT IT READS kind='give' TOO (infra#3464).
    The materials and bag passes write their own give rows with the same
    `guid:N` command shape, and a window that could not tell them apart would
    let one pass silence another's retry - a give of a conjured stack held back
    for an hour because a bag handover happened to name the same guid.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, command FROM overseer_command "
                "WHERE kind IN ('repair', 'buy', 'conjure', 'give') "
                "AND source = 'towntrip' "
                "AND created_at > NOW() - INTERVAL %s MINUTE",
                (int(minutes),),
            )
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table, 1265 a `kind` ENUM with
            # no 'repair' or 'buy' value. A world with none of that machinery
            # has been asked for nothing, so nothing is already queued.
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return set()
            raise
        return {(row["target_name"], row["command"]) for row in cur.fetchall()}


def _insert_town_errand(errand) -> int:
    """Queue one repair, buy, conjure or give row for the world executor.

    `target_arg` carries the receiving character on a hand-off and is empty on
    everything else, which is the role that column already holds for
    kind='give' in the materials and bag passes.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, %s, %s, %s)",
                (errand.member, errand.command, errand.kind,
                 errand.taker, "towntrip"),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1146, 1265):
                log.warning(
                    "overseer_command.kind has no %r value - %s cannot be sent "
                    "to the counter until the worldserver image carrying "
                    "mod-overseer's repair and buy SQL has shipped "
                    "(mod-overseer#227)",
                    errand.kind, errand.member,
                )
                return 0
            raise
        return cur.lastrowid or 0


def _choose_drive_quest(plan) -> int:
    """Which quest the family's traveller should actually be aimed at, or 0.

    The council decides THAT the family will do a quest; questbook decides
    WHICH, because it is the only thing here that knows the difference between
    a quest four of them are behind on and a quest one of them can never do.
    Reimplementing that choice next to the persistence would be a second,
    quieter answer to a question already answered properly.

    THE CANDIDATE RULE LIVES IN questbook.aimable, and deliberately not here.
    It used to be an intersection with the party leader's holdings, which was
    correct while the leader was the only character that could be aimed and
    became a silent wedge the moment mod-overseer started aiming every holder
    (infra#2801). Keeping the rule next to the quest module that owns it is
    what lets a test hold it directly - bridge cannot be imported by the
    tests, so a rule written inline here can only ever be asserted as text.
    """
    leader = bonds.head_of_family()
    names = sorted((_protected_guids()).values())
    ledger, held = _fetch_questbook(names)
    driveable = questbook.aimable(held, plan.beneficiary, leader)
    chosen = questbook.drive_target(
        ledger,
        held_by_traveller=driveable,
        wanted=int(plan.quest_id or 0),
        beneficiary=plan.beneficiary,
    )
    log.info(
        "council: quest choice leader=%s beneficiary=%s wanted=%s chosen=%s "
        "driveable=%d (quests the beneficiary holds, any holder is aimed) "
        "behind=%s",
        leader, plan.beneficiary, plan.quest_id, chosen, len(driveable),
        ledger.furthest_behind,
    )
    return chosen


# The plan kinds the supervisor can actually act on. ONE tuple, read by both
# _already_agreed and _persist_council_plan: they were two identical literals
# and 'quest' has to be added to BOTH or the council re-stages the same scene
# every hour against a goal it did persist. A council that agrees to a quiet
# day ('idle') or to learning a trade ('trades') has still decided something
# real - it is simply not something the supervisor knows how to drive, and
# writing it as a goal would have it issue grind commands for an afternoon off.
DRIVEN_KINDS = ("level", "quest")


def _already_agreed(plan) -> bool:
    """Is the family already working on exactly this?

    Asked BEFORE the council speaks, not after. Persisting already refused a
    duplicate goal, but the scene was played out in full first, which is the
    half Evan actually sees.
    """
    if plan.kind not in DRIVEN_KINDS:
        return False
    quest_id = 0
    if plan.kind == "quest":
        # Resolved the SAME way _persist_council_plan resolves it, and that is
        # not a tidiness point. The row carries the quest questbook CHOSE, not
        # the one the council named; comparing against the council's raw id
        # would find no match, the scene would be re-staged in full every hour
        # against a goal that was persisted the first time, and Discord would
        # fill with the same six lines - the exact stuck record this guard was
        # added to prevent. Two ledger builds an hour is the price.
        quest_id = _choose_drive_quest(plan)
        if not quest_id:
            # Nothing driveable: let the council speak. Persisting will refuse
            # and say why, which is the honest place for that to be reported.
            return False
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT kind, target, quest_id FROM overseer_goal "
            "WHERE character_name = %s AND status = 'active'",
            (plan.beneficiary,),
        )
        return goals.already_working(
            plan.kind, int(plan.target), list(cur.fetchall()), quest_id=quest_id,
        )


def _persist_council_plan(plan) -> int | None:
    """Turn an agreed plan into a goal the supervisor already knows how to drive.

    Only kinds the supervisor can actually act on are persisted. A council that
    agrees to a quiet day has decided something real, and writing that as a
    goal would have the supervisor issue grind commands for it - the opposite
    of what was agreed.

    Replaces any active goal for that character rather than stacking: the
    family just agreed on today, and an older goal underneath would have the
    supervisor driving yesterday's plan at the same time.
    """
    if plan.kind not in DRIVEN_KINDS:
        log.info("council: plan '%s' is not a goal the supervisor drives", plan.kind)
        return None

    quest_id = 0
    if plan.kind == "quest":
        quest_id = _choose_drive_quest(plan)
        if not quest_id:
            # Nothing the traveller holds AND the beneficiary can be measured
            # on. Said out loud rather than persisted: a goal nobody can drive
            # and nobody can observe would sit 'active' forever, and the
            # supervisor would report it healthy the whole time. The fix for
            # this state is quest SHARING (the other half of infra#2597), not
            # a different aim.
            log.warning(
                "council: %s's quest cannot be driven - the party leader is "
                "not holding a quest %s is also working on; nothing persisted",
                plan.beneficiary, plan.beneficiary,
            )
            return None

    with _connect() as conn, conn.cursor() as cur:
        # An identical goal already being worked is LEFT ALONE. The council
        # meets hourly and keeps reaching the same conclusion while the work is
        # still in progress, so replacing it wiped last_report every hour: the
        # progress record restarted, and with it the stall counter that
        # re-issues a lost strategy. Four cancelled duplicates of one goal sat
        # in the table before this was noticed, and the supervisor never once
        # got far enough to re-assert.
        cur.execute(
            "SELECT kind, target, quest_id FROM overseer_goal "
            "WHERE character_name = %s AND status = 'active'",
            (plan.beneficiary,),
        )
        if goals.already_working(plan.kind, int(plan.target), list(cur.fetchall()),
                                 quest_id=quest_id):
            log.info("council: %s is already working towards %s %d (quest %d)",
                     plan.beneficiary, plan.kind, int(plan.target), quest_id)
            return None

        cur.execute(
            "UPDATE overseer_goal SET status = 'cancelled' "
            "WHERE character_name = %s AND status = 'active'",
            (plan.beneficiary,),
        )
        # target for a quest goal is always goals.QUEST_TARGET (0 objectives
        # left); the council's plan.target is objectives REMAINING right now,
        # which is an observation and not a destination.
        target = goals.QUEST_TARGET if plan.kind == "quest" else int(plan.target)
        cur.execute(
            "INSERT INTO overseer_goal "
            "(character_name, kind, target, quest_id, status, channel_id) "
            "VALUES (%s, %s, %s, %s, 'active', %s)",
            (plan.beneficiary, plan.kind, target, quest_id,
             OVERSEER_CHANNEL_ID or ""),
        )
        log.info("council: persisted %s goal for %s (quest %d, row %s)",
                 plan.kind, plan.beneficiary, quest_id, cur.lastrowid)
        return cur.lastrowid


def _record_goal_progress(goal_id: int, value: int, stalls: int = 0) -> None:
    # "<value>/<stalls>" once a goal has stalled, bare "<value>" otherwise, so
    # the common row keeps the shape every existing row already has.
    report = "%d/%d" % (value, stalls) if stalls else str(value)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE overseer_goal SET last_report = %s WHERE id = %s",
            (report, goal_id),
        )


def _complete_goal(goal_id: int) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE overseer_goal SET status = 'completed', completed_at = NOW() "
            "WHERE id = %s",
            (goal_id,),
        )


def _fetch_guild_names() -> dict[int, str]:
    """guildid -> name for every guild on the realm.

    Static SQL: the guild name typed in Discord is NEVER interpolated here.
    Matching happens in fanout.py against this map, so a message can only
    ever select a guild that already exists - it can never shape a query.
    The realm carries about twenty guilds, so reading all of them is both
    cheaper than a per-message lookup and the reason this stays constant.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT guildid, name FROM guild")
        return {int(row["guildid"]): row["name"] for row in cur.fetchall()}


# --- family digest adapters (infra#2597) -----------------------------------
#
# Everything digest.py needs, read here and nowhere else. The module itself is
# pure - it never learns that any of this came from a database - which is the
# same seam questbook.py and bonds.py sit on.

# Ten minutes. The cheapest interval that still resolves a night into
# something with shape, at 5 characters x 144 rows a day; a one-minute sample
# would buy resolution nobody reads and pay for it in a hot table forever.
SAMPLE_INTERVAL = float(os.environ.get("SAMPLE_INTERVAL_SECONDS", "600"))
# Long enough that "what did they do last week" works, short enough that the
# table never becomes something anyone has to think about.
SAMPLE_RETENTION_DAYS = int(os.environ.get("SAMPLE_RETENTION_DAYS", "30"))
# Bound on how much conversation one report will read. A busy night is
# thousands of chat rows and the digest quotes four of them.
DIGEST_MAX_MOMENTS = int(os.environ.get("DIGEST_MAX_MOMENTS", "400"))


def _ensure_sample_store() -> None:
    """The counters table, created the same way the thought store is.

    Bridge-owned state, deliberately NOT module SQL, for exactly the reason
    written on _ensure_thought_store: this is the overseer's memory, the
    worldserver never touches it, and coupling it to a 90-minute game-server
    image rebuild would be friction for nothing. CREATE TABLE IF NOT EXISTS is
    idempotent.

    UNSIGNED on the counters and SIGNED deltas: every column here only ever
    goes up in the world, but money genuinely falls (repairs, training), so
    the delta digest computes is a Python int and never a SQL subtraction that
    would underflow.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS overseer_sample ("
            " id INT UNSIGNED NOT NULL AUTO_INCREMENT,"
            " character_name VARCHAR(12) NOT NULL,"
            " level SMALLINT UNSIGNED NOT NULL DEFAULT 0,"
            " money INT UNSIGNED NOT NULL DEFAULT 0,"
            " quests_rewarded SMALLINT UNSIGNED NOT NULL DEFAULT 0,"
            " spells SMALLINT UNSIGNED NOT NULL DEFAULT 0,"
            " talents SMALLINT UNSIGNED NOT NULL DEFAULT 0,"
            " equipped SMALLINT UNSIGNED NOT NULL DEFAULT 0,"
            " taken_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " PRIMARY KEY (id), KEY idx_char_time (character_name, taken_at)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )


def _family_names() -> list:
    """The characters a digest is about, best available answer.

    The protected set is the real one - it is what OVERSEER_NOTABLE_NAMES
    already means everywhere else in this file - but it is a database lookup
    that can come back empty on a cold realm, and a digest about nobody is
    worse than a digest about the five names the family table has always
    known. bonds.FAMILY is the fallback, never the first answer: a member
    renamed in the world would otherwise be sampled under a name that no
    longer exists.
    """
    try:
        names = sorted(_protected_guids().values())
    except Exception:
        log.exception("protected lookup failed; falling back to bonds.FAMILY")
        names = []
    return names or sorted(bonds.FAMILY)


# One row per character with every counter the digest reports. The correlated
# counts are cheap here and only here: this runs against FIVE guids on a ten
# minute timer, not against the realm.
#
# equipped counts bag 0, slots 0-18 - EQUIPMENT_SLOT_END in 3.3.5a. Bags and
# bank rows live at other (bag, slot) pairs, so a plain COUNT(*) over
# character_inventory would count a full backpack as gear.
_STANDING_SQL = (
    "SELECT c.name, c.guid, c.money, c.leveltime, c.online, "
    "       COALESCE(s.level, c.level) AS level, "
    "       s.map_id, s.pos_x, s.pos_y, "
    "       (SELECT COUNT(*) FROM character_queststatus_rewarded r "
    "          WHERE r.guid = c.guid) AS quests_rewarded, "
    "       (SELECT COUNT(*) FROM character_spell sp WHERE sp.guid = c.guid) AS spells, "
    "       (SELECT COUNT(*) FROM character_talent t WHERE t.guid = c.guid) AS talents, "
    "       (SELECT COUNT(*) FROM character_inventory i "
    "          WHERE i.guid = c.guid AND i.bag = 0 AND i.slot < 19) AS equipped "
    "FROM characters c "
    "LEFT JOIN overseer_snapshot s "
    "       ON s.name = c.name AND s.updated_at > NOW() - INTERVAL 60 SECOND "
    "WHERE c.name IN (%s) "
    "ORDER BY c.name"
)


def _fetch_standing_rows(names: list) -> list:
    if not names:
        return []
    sql = _STANDING_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        return list(cur.fetchall())


def _fetch_standings(names: list) -> list:
    """digest.Standing per character, with the provenance of each figure.

    THE TWO CLOCKS ARE KEPT APART ON PURPOSE. `level` prefers
    overseer_snapshot, which the module refreshes about once a minute;
    `spells` and `talents` can only come from character_spell and
    character_talent, which the worldserver writes on PlayerSaveInterval
    (900000 ms, staggered per player) and which are therefore up to a quarter
    of an hour behind the world. Both land in one object, so each carries the
    string that says which it is and digest.render prints them in the footer.
    Mixing them silently is how a report becomes confidently wrong about a
    spell somebody learned ten minutes ago.
    """
    out = []
    for row in _fetch_standing_rows(names):
        zone = ""
        if row.get("map_id") is not None and row.get("pos_x") is not None:
            zone = GEO.zone_name(row["map_id"], row["pos_x"], row["pos_y"])
        out.append(digest.Standing(
            name=row["name"],
            level=int(row["level"] or 0),
            copper=int(row["money"] or 0),
            quests_done=int(row["quests_rewarded"] or 0),
            spells=int(row["spells"] or 0),
            talents=int(row["talents"] or 0),
            equipped=int(row["equipped"] or 0),
            online=bool(row.get("online")),
            zone=zone,
            level_time_seconds=int(row.get("leveltime") or 0),
            live_source=digest.SOURCE_SNAPSHOT,
            saved_source=digest.SOURCE_SAVED,
        ))
    return out


def _take_sample(names: list) -> int:
    rows = _fetch_standing_rows(names)
    if not rows:
        return 0
    with _connect() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO overseer_sample "
            "(character_name, level, money, quests_rewarded, spells, talents, equipped) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [(r["name"], int(r["level"] or 0), int(r["money"] or 0),
              int(r["quests_rewarded"] or 0), int(r["spells"] or 0),
              int(r["talents"] or 0), int(r["equipped"] or 0)) for r in rows],
        )
        return cur.rowcount


def _prune_samples() -> int:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM overseer_sample WHERE taken_at < NOW() - INTERVAL %s DAY",
            (SAMPLE_RETENTION_DAYS,),
        )
        return cur.rowcount


# Hoisted for the reason _LEDGER_MEMBER_SQL and _BOT_HELD_SQL are: ruff
# anchors S608 at the START of the expression, so a noqa on the line carrying
# the % does not silence a query whose literal spans several lines. Only the
# NUMBER of placeholders is ever interpolated; every name reaches MySQL as a
# bound parameter.
_SAMPLE_SQL = (
    "SELECT character_name, level, money, quests_rewarded, spells, talents, "
    "       equipped, taken_at FROM overseer_sample "
    "WHERE character_name IN (%s) AND taken_at > NOW() - INTERVAL %%s HOUR "
    "ORDER BY taken_at ASC"
)


def _fetch_samples(names: list, hours: float) -> list:
    """Samples covering the window, plus the last one BEFORE it.

    The extra row is the whole point. digest.changes takes its baseline from
    the last sample at or before the window opened, so a query bounded at the
    window edge would hand it nothing to subtract from and every window would
    come back BASIS_NO_BASELINE. Reaching one interval further back is what
    makes the arithmetic possible; two intervals of slack covers a sampler
    that missed a beat.
    """
    if not names:
        return []
    reach = hours + (SAMPLE_INTERVAL * 2 / 3600.0)
    sql = _SAMPLE_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, [*names, reach])
        return [
            digest.Sample(
                name=r["character_name"],
                at=r["taken_at"],
                level=int(r["level"] or 0),
                copper=int(r["money"] or 0),
                quests_done=int(r["quests_rewarded"] or 0),
                spells=int(r["spells"] or 0),
                talents=int(r["talents"] or 0),
                equipped=int(r["equipped"] or 0),
            )
            for r in cur.fetchall()
        ]


# What an overseer_event row must look like before this reads it. A sibling
# ticket owns that table and its column spellings are not ours to assume, so
# the shape is DISCOVERED rather than declared: the first alias present for
# each role wins, and a table missing any role is simply not used.
#
# Getting this wrong in the confident direction would be a crash in the middle
# of answering a question, on a table that may not exist yet at all - so the
# absent case is the DESIGNED case and the enriched one is the bonus.
_EVENT_ROLES = {
    "name": ("character_name", "name", "character"),
    "kind": ("kind", "event", "event_type", "type"),
    "text": ("detail", "text", "description", "data"),
    "at": ("created_at", "occurred_at", "at", "logged_at"),
}


def _event_columns() -> dict | None:
    """Role -> real column name for overseer_event, or None if unusable."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'overseer_event'"
        )
        have = {r["c"].lower() for r in cur.fetchall()}
    if not have:
        return None
    picked = {}
    for role, aliases in _EVENT_ROLES.items():
        for alias in aliases:
            if alias in have:
                picked[role] = alias
                break
    # text is optional - a typed event with no detail is still a fact about
    # when something happened, and the digest counts those.
    if not {"name", "kind", "at"} <= set(picked):
        log.info("overseer_event exists but lacks name/kind/time columns: %s",
                 sorted(have))
        return None
    return picked


# Same hoist. The interpolated values here are COLUMN NAMES, which cannot be
# bound parameters in any SQL dialect - but they are not user input either:
# every one of them came back from information_schema in _event_columns, was
# matched against the fixed _EVENT_ROLES allowlist, and is backquoted. Nothing
# a Discord message contains can reach this string.
_EVENT_MOMENT_SQL = (
    "SELECT `%s` AS name, `%s` AS kind, %s AS detail, `%s` AS at_time "
    "FROM overseer_event WHERE `%s` IN (%s) AND `%s` > NOW() - INTERVAL %%s HOUR "
    "ORDER BY `%s` ASC LIMIT %%s"
)


def _fetch_event_moments(names: list, hours: float) -> list:
    cols = _event_columns()
    if cols is None or not names:
        return []
    text_col = cols.get("text")
    parts = (
        cols["name"], cols["kind"],
        ("`%s`" % text_col) if text_col else "''",
        cols["at"], cols["name"], ",".join(["%s"] * len(names)),
        cols["at"], cols["at"],
    )
    sql = _EVENT_MOMENT_SQL % parts
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, [*names, hours, DIGEST_MAX_MOMENTS])
        return [
            digest.Moment(
                at=r["at_time"], name=r["name"], kind=str(r["kind"] or "event"),
                text=str(r["detail"] or ""), source=digest.SOURCE_EVENT,
            )
            for r in cur.fetchall()
        ]


# Same hoist, same guarantee: placeholders counted, names bound.
_CHAT_MOMENT_SQL = (
    "SELECT id, sender_name, channel, channel_name, text, created_at "
    "FROM overseer_chat "
    "WHERE sender_name IN (%s) AND created_at > NOW() - INTERVAL %%s HOUR "
    "ORDER BY id DESC LIMIT %%s"
)


def _fetch_chat_moments(names: list, hours: float) -> list:
    """What the family actually said in the window.

    Passed through relay.collapse_hearers and relay.partition_addon, which
    already exist and already know the two traps: overseer_chat holds one row
    per LISTENER, so a party line with five in the party is five identical
    rows, and addon protocol traffic is chat by every measure the schema can
    see. Re-solving either here would be a second answer that could disagree
    with what the relay posts in the channel.
    """
    if not names:
        return []
    sql = _CHAT_MOMENT_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, [*names, hours, DIGEST_MAX_MOMENTS])
        rows = list(reversed(cur.fetchall()))
    spoken, _ = relay.collapse_hearers(rows)
    spoken, _ = relay.partition_addon(spoken)
    return [
        digest.Moment(
            at=r["created_at"], name=r["sender_name"], kind="said",
            text=str(r["text"] or ""), source=digest.SOURCE_CHAT,
        )
        for r in spoken
    ]


def _fetch_moments(names: list, hours: float) -> tuple:
    """(moments, whether the typed event log supplied any of them).

    Chat is always read; it is the one timestamped record of the family that
    has existed since before any of this, and it is what makes a report about
    an unsampled night still worth reading.
    """
    events_ = []
    try:
        events_ = _fetch_event_moments(names, hours)
    except Exception:
        # The table belongs to a concurrent ticket. Absent, half-built or
        # renamed, none of that may cost the report the rest of its facts.
        log.info("overseer_event unavailable; digest runs without it",
                 exc_info=True)
    said = []
    try:
        said = _fetch_chat_moments(names, hours)
    except Exception:
        log.exception("chat moments unavailable; digest runs without them")
    return list(events_) + list(said), bool(events_)


def _db_now():
    """NOW() as the DATABASE sees it.

    THE WINDOW MUST BE ANCHORED ON THE SAME CLOCK AS THE ROWS IT FILTERS.
    Every timestamp digest compares - overseer_sample.taken_at,
    overseer_chat.created_at - is a MySQL TIMESTAMP, read back as a naive
    datetime in the DATABASE's timezone. The bridge is a separate pod with its
    own. Anchoring the window on datetime.now() here would work perfectly in
    every test and then, on a pod an hour off the database, silently drop
    every moment in the window and report a quiet night.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT NOW() AS now")
        return (cur.fetchone() or {})["now"]


def _build_digest(ask) -> digest.Digest:
    """Every read one report needs, then digest.build.

    Built in ONE place and from ONE set of reads so the sections cannot
    contradict each other - the same rule _fetch_questbook follows, and for
    the same reason: a report whose standings disagree with its gaps is worse
    than no report.

    The questbook Ledger is an INPUT, never recomputed. Who is behind, in what
    order they can catch up, and what they should abandon are questions
    questbook.py already answers against the class masks and chain rules that
    make them hard, and the council acts on that answer. A second opinion here
    would be a second answer, given to Evan, that could disagree with what the
    family then does.
    """
    now = _db_now()
    names = _family_names()
    standings = _fetch_standings(names)
    samples = _fetch_samples(names, ask.hours)
    moments, has_events = _fetch_moments(names, ask.hours)
    try:
        ledger, _ = _fetch_questbook(names)
    except Exception:
        # Quest catalogue reads cross into acore_world; losing them costs the
        # catch-up section and nothing else.
        log.exception("questbook unavailable; digest runs without catch-up")
        ledger = None
    return digest.build(
        digest.window_for(ask, now),
        standings, samples, moments,
        ledger=ledger, has_event_log=has_events,
    )


class _RedactSecret(logging.Filter):
    """Blot a secret out of every log record, whatever module emitted it.

    discord.py's own logging flows through the root handler we configure, so
    a token appearing in any future log path (library change, traceback text,
    debug level turned up) leaves this process already redacted.
    """

    def __init__(self, secret: str):
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if self._secret and self._secret in message:
            record.msg = message.replace(self._secret, "[REDACTED]")
            record.args = ()
        return True


class HeadlessBridge(Bridge):
    """The world-driving half, with no Discord gateway at all.

    WHY THIS EXISTS. wow-dev runs this deployment scaled to ZERO, and for a
    good reason that has not changed: this process holds a Discord gateway
    session on a bot token, and two sessions on one token both see the same
    message and both act on it. A dev bridge on the live token would answer
    real people, in real time, from a world they are not in.

    But the Discord session is not what drives the family. Nine of the eleven
    loops started by setup_hook only read and write the overseer tables:
    _supervise_goals is what aims the party at a quest at all, _hold_council
    picks what the family should be doing, _share_quests_loop spreads it, and
    _restore_lost_lives is the safety net. Scaling to zero to protect Discord
    also switched off the entire questing brain, which is why the dev family
    stood in Elwynn for 39 minutes with nothing to do while the live family -
    which HAS this process - was being aimed at quest 14 the whole time.
    Measured 2026-08-29, both worlds side by side.

    WHAT MAKES IT SAFE, AND IT IS NOT A PROMISE IN A COMMENT. No gateway is
    ever connected, so `discord.Client.get_channel` reads an empty connection
    state and returns None for every id. Every send site in this file is
    already guarded on exactly that (`_goal_channel` returns None and logs;
    `_apply_goal_action` checks `is not None`; `_relay_chat` warns and
    continues), because a deleted or invisible channel was always possible.
    So a headless process CANNOT post to Discord - not by policy, but because
    there is nothing to post through. No token is read, either.

    The two overrides are the whole mechanism. Every loop opens with
    `await self.wait_until_ready()`, which waits on an event only a gateway
    READY sets, and spins on `while not self.is_closed()`. Without these it
    would not be that the loops misbehave - they would never run at all, and
    nothing would say so.

    THE ECONOMY PASSES WERE MISSING FROM THIS LIST AND ARE NOT ANY MORE
    (infra#3464, named as a known gap by infra#3450 and left alone there).
    `_vendor_loop` and `_bank_loop` were started by setup_hook and not by
    `run_headless`, so a dev world could never answer "did the vendor pass
    empty the bags" - the one question a validation world exists to answer
    about a change to the vendor pass. The list below and setup_hook's now
    differ by exactly the skip set declared underneath this docstring, and
    tests/test_headless_bridge.py holds them to that rather than to a
    hand-kept enumeration.
    """

    # The chat relay is left out ON PURPOSE rather than allowed to no-op. Its
    # entire job is carrying in-world chat TO Discord; headless it can only
    # log "channel is not visible" every RELAY_SECONDS forever, which buries
    # the lines that matter. Nothing else is skipped: _poll_outcomes is
    # harmless (its _pending map is filled by on_message, which never fires).
    HEADLESS_SKIP = frozenset({"_relay_chat"})

    async def wait_until_ready(self) -> None:
        return

    def is_closed(self) -> bool:
        return False

    async def run_headless(self) -> None:
        # The same setup on_ready does. Skipping it would leave the goal and
        # thought stores uncreated and every loop failing on its first query.
        await asyncio.to_thread(_ensure_thought_store)
        await asyncio.to_thread(_ensure_goal_store)
        await asyncio.to_thread(_ensure_sample_store)
        await asyncio.to_thread(_ensure_trade_store)

        loops = [
            coro for coro in (
                self._poll_outcomes,
                self._protect_characters,
                self._narrate_events,
                self._supervise_goals,
                self._relay_chat,
                self._hold_council,
                self._assign_trades,
                self._sample_family,
                self._share_quests_loop,
                self._move_materials_loop,
                self._vendor_loop,
                self._bank_loop,
                self._towntrip_loop,
                self._restore_lost_lives,
            ) if coro.__name__ not in self.HEADLESS_SKIP
        ]
        log.info("headless: no Discord gateway; driving %d loop(s): %s",
                 len(loops), ", ".join(c.__name__ for c in loops))
        # Held in a set for the same reason setup_hook does it: asyncio keeps
        # only a weak reference to a running task, and a collected one stops
        # its forever-loop silently.
        self._loops = {asyncio.create_task(coro()) for coro in loops}
        await asyncio.gather(*self._loops)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # HEADLESS IS CHOSEN, NEVER FALLEN INTO. An absent token could mean "this
    # is the dev world" or "the secret failed to mount in production", and
    # guessing the first would turn a broken live deploy into a bridge that
    # looks like it is working while answering nobody.
    if os.environ.get("OVERSEER_HEADLESS", "").strip() in ("1", "true", "yes"):
        bridge = HeadlessBridge(frozenset())
        asyncio.run(bridge.run_headless())
        return

    token = os.environ["DISCORD_BOT_TOKEN"]
    for handler in logging.getLogger().handlers:
        handler.addFilter(_RedactSecret(token))
    allowed = frozenset(
        part.strip() for part in os.environ["DISCORD_ALLOWED_USERS"].split(",") if part.strip()
    )
    Bridge(allowed).run(token, log_handler=None)


if __name__ == "__main__":
    main()
