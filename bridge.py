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
import auction
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
import guildbank
import guildshare
import craft
import craft_rhythm
import gatheraim
import gatherband
import craft_supply
import dungeonprogression
import item_plan
import jobs
import kin
import learnaim
# NOT `mailbox` - that is a Python standard library module, and this package is
# imported with its own directory first on sys.path. See mailrun.py's docstring.
import mailrun
import materials
import overhear
import persona
import professions
import protect
import questbook
import questshare
import quests
import raidcraft
import raidprep
import recipebook
import recruit
import relay
import skillgoal
import tabard
import towntrip
import townslot
import vendor_stall
import trainjob
import travel
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


def _insert_guild(name: str, command: str, source: str, target_arg: str = "") -> int:
    """One overseer_command row for mod-overseer's DoGuild.

    kind='guild', for the same reason _insert_job uses its own kind: the guild
    verbs are not mod-playerbots chat commands, so handing one to the bot's own
    parser would be accepted and do nothing.

    `target_arg` IS THE WHOLE OF THE `invite` VERB, and until infra#3651 this
    function could not write it. The 2026_09_11 guild migration is explicit:
    "target_arg - the character to invite, for `invite`", and DoGuild's invite
    branch refuses an empty one outright with "no character to invite (put the
    name in target_arg)". So every `invite` row written before this change
    would have been refused on arrival, which is the reason no `invite` had
    ever been issued from Python. It defaults to the empty string rather than
    to NULL for the reason _insert_bank spells out for its own kind: a row of
    another verb carrying a name in `target_arg` would still be delivered and
    would still be wrong, so the emptiness is written rather than left to a
    column default nobody re-reads.

    GUARDED LIKE ITS SIBLINGS, which it was not. `_insert_share` and
    `_insert_bank` both catch the MySQL error a world without their machinery
    raises and return 0; this one let it out, so a realm whose `kind` ENUM has
    no 'guild' value (a db-import that has not run 2026_09_11 yet) took down
    whichever loop called it rather than skipping a pass. 1265 is a truncated
    ENUM value, 1146 a missing table, 1054 a missing column.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, 'guild', %s, %s)",
                (name, command, target_arg, source),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                log.warning(
                    "overseer_command has no 'guild' machinery yet - dropping "
                    "%r for %s rather than failing the pass", command, name,
                )
                return 0
            raise
        return cur.lastrowid or 0


def _fetch_family_kin() -> list[dict]:
    """name, race and class for every member of the family.

    FROM bonds.FAMILY, NOT FROM WHO IS LOGGED IN, and that is deliberate. The
    council reads `_protected_guids` because what today is for depends on who
    is here; a tabard does not. Taking the online roster would make the design
    a function of who happened to be awake when the loop ran, so the same
    family could agree on two different flags on two different evenings - and
    `test_the_same_family_always_arrives_at_the_same_tabard` would be pinning
    a property the bridge did not actually have.

    bonds.FAMILY is already put through cast.py's rename for whichever world
    this process serves, so the names match the characters table on dev and
    live alike.

    `class` is a reserved word in Python but not in MySQL, and it is the real
    column name, so it is read as-is and unpacked at the call site rather than
    aliased into something that would not match `characters`.
    """
    names = list(bonds.FAMILY)
    if not names:
        return []
    # Placeholders from a COUNT, values still bound - the same construction and
    # the same suppression as travel.aim_statements and _aim_traveller. Nothing
    # from `names` reaches the query text: `marks` is a run of `%s` whose only
    # input is how many there are, and the names themselves go to the driver as
    # parameters.
    marks = ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, race, class "  # noqa: S608 - placeholders from a COUNT, values still bound
            "FROM characters WHERE name IN (%s)" % marks,
            names,
        )
        return list(cur.fetchall())


TABARD_SOURCE = "overseer:tabard"


def _tabard_already_held() -> dict | None:
    """Did the family actually HOLD the argument - not did this bridge try.

    THE SUCCESS CASE IS NOT THE DANGEROUS ONE. A guild wearing a tabard has
    non-zero emblem columns and the debate is unreachable on that alone. The
    case that bites is the one where nothing landed, because the columns stay
    at zero and the scene would replay every hour - the infra#2807 shape the
    ticket warns about.

    SO THE QUESTION IS WHAT COUNTS AS HAVING HAPPENED, and the first answer
    was wrong in a way that took a live rollout to show. It asked "is there a
    `tabard %` command row", which answers "did we TRY", and those are not the
    same question. On 2026-09-12 the bridge - which deploys on merge in
    seconds, while the module it talks to needs a full image build and a
    digest promotion, so the two halves of one feature land on clocks 15-20
    minutes apart - fired its first debate at 12:35 into a worldserver that
    was still rolling. All eleven lines came back `target not online`, the
    guild row came back `target not online`, NOTHING reached the world, and
    the guard would nonetheless have said "asked" and suppressed the scene
    for good. It took a hand-deleted row to recover.

    A pod swap is not a rare event, so this needed to be self-healing rather
    than merely documented.

    What it asks now: did any line of the scene reach a character. A chat row
    at `delivered` was SPOKEN; one at `error` was not. If even one was heard
    the argument happened and must not be staged again - partial delivery
    counts as happened, deliberately, because re-speaking three lines
    somebody already heard is the stutter this whole guard exists to prevent.
    If none was heard, nothing happened, and the next cycle may hold it.

    Note this no longer looks at the guild command row at all. A scene that
    was heard but whose command was refused is NOT re-staged: the family had
    the argument, and the refusal is a thing to report, not to re-enact.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            # `last_heard`, not `last`: `last` is a reserved word in MySQL 8
            # and an unquoted one is a syntax error, which is the same trap
            # `lead` set when it crash-looped the worldserver. Caught here by
            # test_protect.ReservedWordTest rather than in production.
            "SELECT COUNT(*) AS heard, MAX(created_at) AS last_heard "
            "  FROM overseer_command "
            " WHERE kind = 'chat' AND source = %s AND status = 'delivered'",
            (TABARD_SOURCE,),
        )
        row = cur.fetchone()
        return row if row and row["heard"] else None


def _fetch_family_guild() -> dict | None:
    """The guild the family's head leads, and what it currently wears.

    Keyed off the head of the family rather than off a guild name, because the
    name is a decision that has already been made once and re-deriving it here
    would be a second answer to which guild is theirs.

    Returns None when they are in none, which is the ordinary answer for most
    of this family's life and is not an error.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT g.guildid, g.name, g.EmblemStyle, g.EmblemColor, "
            "       g.BorderStyle, g.BorderColor, g.BackgroundColor, c.money "
            "  FROM characters c "
            "  JOIN guild_member gm ON gm.guid = c.guid "
            "  JOIN guild g ON g.guildid = gm.guildid "
            " WHERE c.name = %s",
            (bonds.head_of_family(),),
        )
        return cur.fetchone()


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

# HOW LONG ONE TOWN PASS MAY KEEP THE FAMILY'S TRAVELLER WHILE ANOTHER WAITS
# (infra#3703). The argument for the number is on `townslot.LEASE_SECONDS`,
# which is where it lives; this is the env knob, in the shape every other
# cadence in this file already has one, so a realm that is walking further
# between counters than wow-dev can be given a longer lease without a deploy.
# It is NOT a cycle: nothing sleeps for this. It is the age at which a held
# errand stops outranking a pass that has been waiting for the column.
TOWN_SLOT_LEASE_SECONDS = float(
    os.environ.get("TOWN_SLOT_LEASE_SECONDS", townslot.LEASE_SECONDS)
)


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
    # WHO IS OUT GATHERING DECIDES WHO CAN PICK ANYTHING UP (infra#3769).
    # Read per character rather than reduced to one family-wide answer,
    # because `overseer_roster.job` IS per row on the far side - DriveCraft
    # skips anyone whose job is not `craft` and the quest gate stands the
    # drive down for every non-quest value, both one row at a time - and a
    # roster that disagrees mid-fan-out would otherwise hand somebody the
    # strategies for a mode they are no longer in.
    #
    # THIS IS THE HALF THAT WAS MISSING RATHER THAN THE HALF THAT WAS WRONG.
    # `craft_rhythm` has been ordering the family out to gather correctly for
    # a day; what nothing did was give them `gather` and `loot`, without which
    # roaming walks past every node it passes. See goals.GATHER_STRATEGIES for
    # the measurement - `nc +loot` has never been issued on this realm - and
    # note that this loop is exactly where it belongs, because neither
    # strategy survives the ResetStrategies that runs on every login.
    gathering = {
        name for name, mode in _standing_jobs().items()
        if mode == craft_rhythm.MODE_GATHER
    }
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
            gathering=(name in gathering),
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


def _fetch_scarlet_completion() -> dict[str, int] | None:
    """Read the durable per-wing completion ledger when deployed.

    ``portal_keyword`` is added by the matching mod-overseer migration. Older
    realms must not make the council fail, and must not cause it to guess an
    ordered campaign from map 189 alone.
    """
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT portal_keyword, outcome FROM overseer_dungeon_run "
                "WHERE map_id = 189 AND state = 'ended'"
            )
            return dungeonprogression.successful_runs(cur.fetchall())
    except pymysql.err.MySQLError as exc:
        if exc.args and exc.args[0] in (1054, 1146):
            log.info(
                "dungeon progression ledger unavailable; council keeps the "
                "legacy dungeon ranking until portal identity is deployed"
            )
            return None
        raise


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

# Primary AND secondary, unlike _TRADE_SKILL_IDS above (which the council's
# trade-count deliberately keeps primary-only, per its own comment). craft.py
# (infra#2757's Cooking/First Aid slice) needs First Aid/Cooking values to
# aim `job='craft'` at a secondary recipe - a second constant rather than
# widening _TRADE_SKILL_IDS itself, so the council's count is untouched.
_SECONDARY_SKILL_IDS = ",".join(
    str(goals.SKILL_IDS[name]) for name in sorted(professions.SECONDARY)
    if name in goals.SKILL_IDS
)

_TRADE_SKILL_SQL = (
    "SELECT c.name, k.skill, k.value "
    "FROM characters c JOIN character_skills k ON k.guid = c.guid "
    "WHERE c.name IN (%s) AND k.skill IN ("
    + _TRADE_SKILL_IDS + "," + _SECONDARY_SKILL_IDS + ")"
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

    Professions only - primary AND secondary (First Aid, Cooking, Fishing).
    `character_skills` also holds languages, Defense and every weapon skill,
    and handing those to a module that reasons about profession slots is how
    `trades` came to mean nothing (see _TRADE_SKILL_IDS, which the council's
    own primary-only trade count still uses unchanged).

    READ-ONLY, and that is the whole contract of this function. It is the only
    place in the bridge that touches character_skills at all.

    LATE, BUT IT DOES CONVERGE (infra#3695). Written on the ordinary
    player-save timer, so it trails live state by minutes: Ugga crafted seven
    Minor Healing Potions on 2026-09-13 while her Alchemy still read 1/75
    here, and it had caught up to 14 ten minutes later. That is fine for the
    one thing this feeds - craft.craft_errand CHOOSING a recipe bracket, where
    being a few points stale picks a slightly easier recipe and nothing worse.

    Do not generalise that tolerance to `character_spell`, which does not
    converge at all because the write never happens for a runtime-granted
    recipe. craft.py's header has the full argument; the short version is that
    a stale number is usable and a missing row is not.
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


def _crafting_roster() -> list:
    """Every enabled character currently on `job='craft'` (infra#440).

    A PLAIN COLUMN READ, not a decision - _craft_once uses this to know WHO
    to write a craft_spell errand for, never WHETHER anyone should be on
    job='craft' in the first place. That call is an operator/decree/council
    one this module does not make.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM overseer_roster WHERE enabled = 1 AND job = %s",
            ("craft",),
        )
        return [row["name"] for row in cur.fetchall()]


def _standing_jobs() -> dict:
    """name -> `job` for every enabled roster row (infra#3696).

    THE SIBLING OF `_crafting_roster`, AND THE REASON IT IS NOT THAT FUNCTION.
    That one asks "who is on job='craft'" and answers with names, which is
    exactly right for handing DriveCraft its errands. `_craft_rhythm_once` asks
    a different question - "what mode is the family in, and do all five agree" -
    and a list of the rows matching one value cannot answer it: a family half
    on craft and half on quest is indistinguishable there from a family wholly
    on craft. `craft_rhythm.standing_mode` needs every row's value to tell
    those apart, and refuses to act when they disagree.

    READ-ONLY, like every other roster reader here. The only thing that writes
    this column is mod-overseer's own DoJob, on an `overseer_command` row that
    `_set_job` inserts.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, job FROM overseer_roster WHERE enabled = 1")
        return {row["name"]: row["job"] for row in cur.fetchall()}


def _standing_travel_aims() -> dict:
    """name -> `travel_npc` for every enabled roster row, READ ONLY.

    Used for one thing and one thing only: saying out loud that a gathering
    order will not move a character who is still holding a travel errand,
    because mod-overseer's `TravelHoldsTheWheel` stands the quest drive down
    for exactly that. Nothing in this file may WRITE the column off the back of
    this read - the sanctioned writers are the existing economy passes, and a
    second one is how the family spent half an hour pinned in a Gadgetzan shop
    (infra#3703, infra#3708, infra#3728).
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, travel_npc FROM overseer_roster WHERE enabled = 1")
        return {row["name"]: (row["travel_npc"] or "") for row in cur.fetchall()}


class _LogChannel:
    """A stand-in for a Discord channel, for an order nobody asked for.

    `_set_job` reports what it did by speaking - the refusal when `jobs.why_not`
    turns a mode down, and `jobs.describe` when it lands. An automatic caller
    has no channel to speak into, and the two ways of dealing with that are to
    fork the write path or to give it somewhere to talk. Forking it would mean
    a second place that has to remember to ask `jobs.why_not` first, which is
    precisely the omission infra#3338 was filed about; this is the cheaper
    half of that choice.

    IT IS NOT A SILENT SINK. Every sentence reaches the log at INFO, which is
    where an unattended pass is read from and where DD can alert on it. A null
    object that threw the text away would turn "the pass explained itself" into
    "the pass did something" - the shape this codebase keeps meeting.
    """

    async def send(self, text: str) -> None:
        log.info("job: %s", text)


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
    """Write the decision down, refresh pending leases, and return NEW rows.

    A duplicate still-planned row refreshes ``decided_at``. The six-hour
    leadership lease therefore measures time since the bridge last observed
    the errand, not time since it was first created. A settled duplicate is
    left untouched, so a completed trade is never revived or re-announced.
    """
    if not plan.assignments:
        return []
    fresh = []
    with _connect() as conn, conn.cursor() as cur:
        for assignment in plan.assignments:
            cur.execute(
                "INSERT INTO overseer_trade "
                "(character_name, verb, skill_name, skill_id, reason) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE decided_at = "
                "IF(status = 'planned', NOW(), decided_at)",
                (assignment.character, assignment.verb, assignment.skill,
                 assignment.skill_id, assignment.reason[:2000]),
            )
            if cur.rowcount == 1:
                fresh.append(assignment)
    return fresh


def _activate_training() -> bool:
    """Promote a unanimous questing family when training work is pending."""
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT name, job FROM overseer_roster WHERE enabled = 1")
            jobs = {row["name"]: row["job"] for row in cur.fetchall()}
            if not trainjob.should_activate(jobs, True):
                return False
            for name in jobs:
                cur.execute(
                    "INSERT INTO overseer_command "
                    "(target_name, command, kind, source) VALUES (%s, %s, 'job', %s)",
                    (name, trainjob.MODE, "overseer:trades"),
                )
            return bool(jobs)
    except pymysql.err.MySQLError as exc:
        if exc.args and exc.args[0] == 1146:
            log.warning("training activation skipped: roster table is absent")
            return False
        raise


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


def _drive_dungeon(keyword: str, wanted: int) -> tuple:
    """Turn a decided dungeon goal into the roster writes that actually send
    the family in: job='dungeon:<keyword>' (or the bare 'dungeon') on every
    ENABLED character, plus the campaign cap the coordinator counts against.

    WHY THE WHOLE FAMILY AND NOT ONE TRAVELLER, UNLIKE _aim_traveller ABOVE. A
    quest needs one character to hold the drive so the rest can follow into
    it; a dungeon run needs everybody IN THE INSTANCE, which is exactly the
    same reasoning bridge._set_job already applies to every other job-schedule
    mode (jobs.py's own docstring). This is that fan-out, mirrored rather than
    reinvented, with a dungeon-specific campaign write alongside it.

    GATED ON BAG PRESSURE, AND DELIBERATELY HERE RATHER THAN IN goals.py.
    Whether the family's bags are already too full to loot a run is a
    live-world fact a pure decision module has no way to see, and
    mod-overseer's own bag-pressure evacuation (#423/#424/#430) will evacuate
    and fail a run for a family that cannot loot - sending them in anyway
    would spend the very campaign this pass exists to advance on a run the
    module is about to cut short. Reuses bag_pressure.family_town_run_needed
    rather than a second threshold: it is the same "is this family too full to
    keep going" question the economy pass already answers, asked here before
    a run rather than mid-run.

    Returns (jobs written, campaign rows written), both possibly 0 when bag
    pressure withholds the whole pass or the roster is empty - the same
    "count what actually landed" honesty _set_job's own fan-out keeps.
    """
    names = _fetch_enabled_names()
    if not names:
        return 0, 0

    free_slots = _fetch_free_slots(names)
    if bag_pressure.family_town_run_needed(free_slots):
        log.info(
            "goal: withholding dungeon:%s for %d enabled character(s) - bags "
            "are already near full and a run started now would be evacuated "
            "before it could progress (mod-overseer#423/#424/#430)",
            keyword or "(default)", len(names),
        )
        return 0, 0

    mode = "dungeon:%s" % keyword if keyword else "dungeon"
    jobs_written = 0
    for name in names:
        try:
            _insert_job(name, mode, "overseer:goal")
            jobs_written += 1
        except Exception:
            # One failed insert must not cost the rest of the family; see
            # _set_job's identical reasoning.
            log.exception("dungeon job insert failed for %s (mode=%s)", name, mode)

    campaign_written = 0
    with _connect() as conn, conn.cursor() as cur:
        for name in names:
            try:
                cur.execute(
                    "UPDATE overseer_roster SET dungeon_runs_wanted = %s "
                    "WHERE name = %s",
                    (int(wanted), name),
                )
                campaign_written += cur.rowcount
            except pymysql.err.MySQLError as exc:
                if exc.args and exc.args[0] in (1054, 1146):
                    log.warning(
                        "overseer_roster.dungeon_runs_wanted missing - this "
                        "realm predates mod-overseer's campaign columns "
                        "(mod-overseer#302)",
                    )
                    break
                raise
    log.info("goal: dungeon:%s -> %d job(s), %d campaign row(s) of %d enabled",
             keyword or "(default)", jobs_written, campaign_written, len(names))
    return jobs_written, campaign_written


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
#
# `guild banker` joined for infra#2831/mod-overseer#437, and belongs here for
# the identical reason. It is a town errand the leader runs and comes back
# from, not a standing plan - and mod-overseer#438 (this same session) is the
# whole reason to get the categorization right rather than assume: that fix
# closed exactly this hole on the C++ side (a dungeon-crossing goal
# overwriting a standing profession errand's travel_npc unconditionally).
# `_write_trade_errand`'s two branches are this file's OWN version of that
# same fork - the ECONOMY_ERRANDS branch retasks only an idle traveller, the
# other branch overwrites unconditionally because it exists for a standing
# plan. Writing "guild banker" down the unconditional branch would silently
# steal a leader's own outstanding profession-trainer errand the moment the
# guild-bank pass runs - the identical bug, self-inflicted, one file over.
#
# THE KEYWORD IS "guild banker", NOT "guild bank" (infra#3657 follow-up,
# found live the same night the deposit crash itself was fixed): mod-overseer's
# own `TravelAimBook::TravelRoles()` names exactly one guild-vault keyword,
# `"guild banker"`, matched whole against `travel_npc` - there is no
# `"guild bank"` entry in that table. A mismatched keyword resolves to
# nothing, so the leader was never actually walked anywhere; every deposit
# queued came back `status='error'`, `detail='no guild bank in reach'`,
# because nobody was ever in reach of one. Confirmed against the live
# `mod-overseer` source, not assumed - a stale comment in that same file
# claimed `travel_npc='guild bank'` "already resolves", which was the exact
# unverified assumption that shipped this bug in the first place.
# `auctioneer` JOINED FOR infra#3712, AND IT IS A FIX RATHER THAN AN ADDITION.
# The C++ side has carried this keyword in `CounterRoleForAim` since
# mod-overseer#402, and that function's own comment says the drift this tuple
# was on the wrong side of: "`auctioneer` has always been one of the keywords
# TravelRoles() resolves, so a character could be sent to one and did arrive;
# the role came back None, the arrival released without a hold, which is why no
# auction row has ever found its character still standing at the counter."
# #402 fixed that half. This is the other half, and until it was added an
# auctioneer aim was in neither vocabulary properly:
#
#   IT WOULD HAVE BLANKED A TRAINER ERRAND. `_retaskable_from` returns () for
#   any aim that is not in this tuple, not a ground aim and not numeric, so
#   `travel_npc='auctioneer'` took `_write_trade_errand`'s OTHER branch - the
#   unconditional one that also writes `learn_skill`, `unlearn_skill` and
#   `unlearn_max`. A `professions.Errand` built for a travel aim leaves those
#   at 0, so writing an auctioneer aim would have silently zeroed an
#   outstanding learn errand every single time the auction pass ran. That is
#   mod-overseer#438's bug, self-inflicted, one file over, and it is exactly
#   what the comment above warns about for `guild banker`.
#
#   AND IT COULD NEVER HAVE BEEN HANDED BACK. `_release_trade_errand` guards on
#   this same tuple, so an auctioneer errand would have latched the leader
#   permanently - a fifth fuel line of infra#3728, added by the very change
#   that needed the column.
#
# THE `guild banker` HALF OF infra#3712 IS DELIBERATELY NOT TOUCHED HERE. That
# entry points the other way (it is Python-only, and since infra#3702 nothing
# writes the keyword at all because it aims at the vault's own spawn instead),
# so the honest resolution is probably to drop it from both sides rather than
# add it to the C++ - which is a judgement about a keyword this change does not
# use, and it belongs in #3712 with the two-way mirror test that issue asks
# for. Adding `auctioneer` here is the half that has a caller to prove it.
ECONOMY_ERRANDS = ("vendor", "banker", "repair", "guild banker", "auctioneer")


def _retaskable_from(travel_npc: str) -> tuple:
    """Which standing `travel_npc` values this aim may be written over, or ()
    for an aim that overwrites whatever is there.

    THE TUPLE IS THE GUARD, and pulling it out of the UPDATE is what let a
    second kind of aim exist without a second copy of the WHERE clause. An
    empty answer is not "overwrite nothing", it is "this is not an economy
    errand at all" - a profession-trainer errand is a standing plan that
    outlives a town run, it carries `learn_skill`/`unlearn_skill` with it, and
    it goes down `_write_trade_errand`'s other branch exactly as it always
    has. Getting that backwards would silently zero a learn errand every time
    somebody went shopping.

    A BARE CREATURE ENTRY IS AN ECONOMY ERRAND TOO (infra#3692), and it is the
    only numeric aim this process writes: `craft_supply.supply_trip` names one
    specific vendor because the role keyword resolves to the nearest one,
    which is not the one that stocks the reagent. It belongs in the guarded
    branch for precisely the reason the keywords do - it must never erase a
    trainer errand somebody is already walking to.

    AND IT MAY REFINE AN OUTSTANDING `vendor`, WHICH THE KEYWORDS MAY NOT DO
    TO EACH OTHER. This is the one asymmetry here and it is deliberate, so it
    is worth stating why it is not the theft the ECONOMY_ERRANDS comment above
    exists to prevent. `vendor` and `5594` are not two errands competing for
    one traveller; they are the SAME errand at two resolutions. The sell pass
    asks for a vendor because any vendor will buy - mod-overseer's DoSell
    never consults VendorItemData - so a walk to a named vendor still
    satisfies it, and satisfies the reagent purchase as well, which the
    nearest-anything walk does not. Refusing to refine would have left this
    fix inert on the live realm: the leader was measured holding
    `travel_npc = 'vendor'` from the sell pass at the moment the craft-supply
    pass ran, so an idle-only guard would have declined the better aim every
    cycle and reported a perfectly honest "already on somebody else's errand"
    forever. The refinement is self-limiting: once the family is standing at
    the named vendor the reagent is in `town.stocks`, no need is raised, and
    the column goes back to being the vendor pass's own.
    """
    aim = str(travel_npc or "")
    if aim in ECONOMY_ERRANDS:
        return ("", aim)
    # A GROUND AIM IS AN ECONOMY ERRAND TOO (infra#3702). The guild bank pass
    # no longer writes the `guild banker` keyword - the flag it names matches
    # no creature in this expansion, see travel.ROLES - it writes the vault's
    # own spawn as `at:<map>:<x>,<y>,<z>`. That string is in neither
    # ECONOMY_ERRANDS nor `isdigit`, so without this it would fall through to
    # the empty tuple and take `_write_trade_errand`'s OTHER branch, blanking
    # `learn_skill` / `unlearn_skill` on its way past - which is exactly the
    # bug the ECONOMY_ERRANDS comment above says mod-overseer#438 closed on
    # the C++ side, re-created one file over.
    #
    # IDLE OR THE SAME AIM, AND NOT A REFINEMENT OF ANYTHING. Unlike the
    # numeric vendor aim below, a vault aim is not a sharper spelling of some
    # keyword already in the column - the vault is a different errand in a
    # different place (measured: 121 yards from the vendor counter the leader
    # was standing at), so overwriting `vendor` with it would be the theft
    # this guard exists to prevent, not a refinement. That the guild bank is
    # therefore starved behind a live vendor errand is real, measured, and
    # infra#3703's to fix - it is not fixed by widening this tuple.
    if travel.is_ground_aim(aim):
        return ("", aim)
    if aim.isdigit():
        # craft_supply.VENDOR_ROLE rather than a fourth spelling of the word:
        # it is read from travel.ROLES there, and the numeric aim exists only
        # because that keyword was the wrong answer, so the two belong in one
        # place.
        return ("", aim, craft_supply.VENDOR_ROLE)
    return ()


def _is_economy_aim(travel_npc: str) -> bool:
    """Could the ECONOMY have written this aim, and so may it hand it back?

    ONE PREDICATE FOR THE WRITE AND THE RELEASE, because they were two and they
    disagreed (infra#3703). `_write_trade_errand` decides what is an economy
    errand by asking `_retaskable_from`, which has answered "yes" for a ground
    aim since infra#3702 and for a bare creature entry since infra#3692.
    `_release_trade_errand` decided the same question by testing membership of
    `ECONOMY_ERRANDS`, which is keywords only. So the guild bank pass and the
    forge pass could WRITE a ground aim down the economy branch and then no
    caller anywhere could hand it back:

        guild bank: queued 0/5 deposit(s), leader=Grug aimed at
        at:1:-7203.1,-3821.1,8.6

    and `_release_trade_errand` would have refused that exact string as "not an
    economy errand" if anybody had tried. An aim that one guard calls economy
    and the other calls untouchable is an aim with no terminal path at all,
    which is infra#3708's latch rebuilt out of two half-agreeing guards.

    THE FENCE IT KEEPS IS THE ONE THAT MATTERS. A profession trainer errand is
    not in `ECONOMY_ERRANDS`, is not a ground aim and is not numeric, so
    `_retaskable_from` returns the empty tuple for it and this returns False -
    exactly as the old membership test did. `learnaim.statements` writes
    `TRAINER_ROLE`, a keyword, and that keyword is still untouchable by every
    caller here (mod-overseer#438).

    AND THE EMPTY COLUMN IS NOT AN ERRAND. "" reaches none of
    `_retaskable_from`'s branches, so releasing nothing is refused rather than
    run as a blanking UPDATE that would match every idle character.
    """
    return bool(_retaskable_from(travel_npc))


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
            retaskable = _retaskable_from(errand.travel_npc)
            if retaskable:
                # Economy must never erase a profession trainer errand. A
                # vendor or bank pass may coexist with a stale row, but only
                # a traveller that is idle - or already on an errand this aim
                # is a refinement of - can be retasked for the town run. See
                # `_retaskable_from` for which values those are and why a
                # bare creature entry may refine a plain `vendor`.
                #
                # The placeholder run comes from a COUNT of the values the
                # guard returned; every value is still bound, the same
                # construction and the same suppression `_aim_traveller` and
                # `travel.aim_statements` already use.
                marks = ", ".join(["%s"] * len(retaskable))
                cur.execute(
                    "UPDATE overseer_roster SET travel_npc = %%s "  # noqa: S608 - placeholders from a COUNT, values still bound
                    "WHERE name = %%s AND travel_npc IN (%s)" % marks,
                    (errand.travel_npc, errand.character, *retaskable),
                )
                # rowcount 0 is AMBIGUOUS, and this connection does not ask
                # MySQL to resolve it (no CLIENT_FOUND_ROWS): the server's
                # default UPDATE semantics count ROWS CHANGED, not rows
                # matched. Re-asserting the SAME keyword this traveller
                # already carries - the exact idempotent re-write this
                # function's own docstring says happens "every trade cycle"
                # - changes nothing, so rowcount is 0 even though the WHERE
                # matched and this errand is still this caller's own. Live
                # on the dev realm: `UPDATE ... SET travel_npc='vendor'
                # WHERE name='Grog' AND travel_npc='vendor'` measured
                # rowcount=0 while Grog genuinely held 'vendor' the whole
                # time - not stolen, just unchanged - which is what made
                # every economy cycle log "already on somebody else's
                # errand" for a leader that was never actually refused
                # (infra#3663 follow-up). A real refusal (WHERE matched zero
                # rows because some OTHER keyword owns the column) is
                # unaffected by this - it stays a real 0 - so only the
                # matched-but-unchanged case needs telling apart from it.
                if cur.rowcount:
                    return True
                cur.execute(
                    "SELECT travel_npc FROM overseer_roster WHERE name = %s",
                    (errand.character,),
                )
                row = cur.fetchone()
                current = row["travel_npc"] if row else None
                return current == errand.travel_npc
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


def _release_trade_errand(character: str, travel_npc: str) -> bool:
    """Give an economy errand back, and only one this process could have written.

    THE MIRROR OF `_write_trade_errand`, AND THE HALF THAT WAS NEVER BUILT
    (infra#3708). That function's docstring says `travel_npc` "IS WRITTEN HERE
    AND NOWHERE ELSE IN THIS PROCESS", which was true and only ever half the
    sentence: it was CLEARED nowhere else either, or anywhere at all. One writer
    that only ever sets is a latch, and the family stood in it for half an hour.

    WHY THE WORLD DOES NOT DO THIS FOR US. It tries. `TravelAimBook::Release`
    reaches "errand done, releasing" on arrival and then skips the column write,
    because the aim book never claimed an aim the bridge wrote and
    `IsMaintenanceErrand` says a vendor errand is the bridge's business. That
    refusal is infra#3655 and is correct: a crossing releasing a straggler must
    not blank an unresolved vendor aim. It is paired with a comment naming who
    is expected to do it instead - "the bridge owns the column too and clears it
    when it re-aims the family" - and nothing here ever did.

    GUARDED ON THE KEYWORD, LIKE THE WRITE IT MIRRORS. The economy may only hand
    back an errand the economy could have issued, so a profession errand is
    untouchable here for the reason `_write_trade_errand` will not overwrite one
    (mod-overseer#438). The keyword is in the WHERE clause rather than trusted
    from the caller, so a stale reading of who owns the column cannot become an
    erase. A numeric aim craft_supply refined (infra#3692, `_retaskable_from`)
    is therefore NOT released here: it is that pass's errand, not this one's.

    AND ROWCOUNT IS UNAMBIGUOUS HERE, WHICH IT IS NOT ON THE WRITE. The write
    must tell "matched but unchanged" from "somebody else owns this", because
    re-asserting a keyword already carried changes no row (infra#3663). Clearing
    has no such case, so a zero here means the column was genuinely not ours.

    THE GUARD IS `_is_economy_aim` AND NO LONGER `ECONOMY_ERRANDS` DIRECTLY
    (infra#3703). Same fence, asked of the same tuple the WRITE is guarded by,
    so the two can no longer disagree about a ground aim - which they did, and
    the disagreement is why a vault aim or a forge aim could be written by an
    economy pass and then handed back by nobody. See `_is_economy_aim`. The
    sentence above about a numeric aim stands as a statement about CALLERS: no
    caller releases craft_supply's refined vendor entry, because it is that
    pass's errand to end. What has changed is that the guard no longer refuses
    to let one be named at all.
    """
    if not _is_economy_aim(travel_npc):
        # Refused rather than obeyed. A caller asking to blank a profession
        # errand is a caller with a bug, and answering "no" is cheaper to find
        # than an erased trainer errand three passes later.
        log.warning(
            "refusing to release travel_npc=%r for %s - only an economy errand "
            "may be handed back here", travel_npc, character,
        )
        return False
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "UPDATE overseer_roster SET travel_npc = '' "
                "WHERE name = %s AND travel_npc = %s",
                (character, travel_npc),
            )
        except pymysql.err.OperationalError as exc:
            if exc.args and exc.args[0] == 1054:
                # Same degradation as every other reader of these columns: a
                # world image without them cannot be holding an errand in them.
                log.warning(
                    "overseer_roster is missing the travel errand column - "
                    "%s's %s errand cannot be handed back (infra#2757)",
                    character, travel_npc,
                )
                return False
            raise
        return bool(cur.rowcount)


# HOISTED FOR THE S608 ANCHOR, the same reason `_OUTSTANDING_SALES_SQL` and
# `_TRADE_CLASS_SQL` are: ruff anchors S608 at the START of the expression, so a
# noqa on the line carrying the % does not silence a multi-line query. The
# constant makes the interpolation one short line that can carry its own
# annotation.
#
# `%%s` FOR THE KEYWORD, `%s` FOR THE NAME RUN. Only the second is interpolated
# by Python; the first survives the `%` as a literal `%s` and reaches MySQL as a
# bound placeholder, exactly as `_write_trade_errand`'s own guarded UPDATE does
# it. Getting that backwards formats the keyword into the SQL text, which is
# what the noqa below would then be lying about.
_ERRAND_HOLDERS_SQL = (
    "SELECT name FROM overseer_roster "
    "WHERE enabled = 1 AND travel_npc = %%s AND name IN (%s)"
)


def _errand_holders(travel_npc: str, names: list) -> list:
    """Who among `names` is actually carrying this economy errand (infra#3746).

    THE READ THAT WAS MISSING FROM THE RELEASE. `_release_trade_errand` above is
    a compare-and-swap on one name, and every caller so far has fed it
    `_head_now()` - which is correct for the errand the leader is walking and
    silently wrong for one that is not on the leader at all. Nothing in this
    process ever NAMED the follower, so its column could not empty: measured on
    wow-dev 2026-09-13, `Bork | lead=0 | travel_npc=vendor` stood for hours
    while `_settle_vendor_errand` released Grug's column every cycle it could.

    A SECOND READER OF `travel_npc`, AND DELIBERATELY NOT `_standing_travel_aims`.
    That function reads the same column for the whole roster, and its docstring
    forbids exactly this: "Nothing in this file may WRITE the column off the
    back of this read". The prohibition is right for what it guards - a
    gathering order must not turn a glance at the column into an erase - and
    re-using it here would either break that rule or quietly weaken it for the
    gather pass too. One reader per intention is cheaper than one reader with
    two contracts.

    AND A STALE READ CANNOT BECOME A WRONG ERASE, which is the property that
    makes a second reader safe here at all (`_current_travel_npc` warns about
    the opposite case, a second reader that BRANCHES against a decision
    `_write_trade_errand` has already made). Whatever this returns is only ever
    a list of candidates: the keyword is asserted again in
    `_release_trade_errand`'s WHERE clause, so a row that changed hands between
    this SELECT and that UPDATE matches nothing and is left alone. The worst a
    stale answer can do is waste one queue read.

    GUARDED LIKE THE RELEASE IT FEEDS. Refusing a profession keyword here means
    no caller can even assemble the list of rows it would need to blank one,
    which is the same fence one step earlier (mod-overseer#438). It asks
    `_is_economy_aim` rather than `ECONOMY_ERRANDS` for the reason the release
    now does (infra#3703): one predicate, the same one the WRITE is guarded by,
    so a ground aim cannot be economy enough to write and too profession to
    look for.

    DEGRADES TO NOBODY. A world image without the column cannot be holding an
    errand in it, and "nobody is carrying this" is the direction that releases
    nothing - the safe way to not know, matching every other reader of these
    columns.
    """
    if not _is_economy_aim(travel_npc):
        log.warning(
            "refusing to look up holders of travel_npc=%r - only an economy "
            "errand may be handed back, so only one may be hunted for",
            travel_npc,
        )
        return []
    if not names:
        return []
    placeholders = ",".join(["%s"] * len(names))
    sql = _ERRAND_HOLDERS_SQL % placeholders  # noqa: S608 - placeholders from a COUNT, values still bound
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, (travel_npc, *names))
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning(
                    "overseer_roster is missing the travel errand column - no "
                    "%s errand can be found to hand back (infra#2757)",
                    travel_npc,
                )
                return []
            raise
        return sorted(str(row["name"]) for row in cur.fetchall())


def _write_craft_errand(character: str, spell_id: int) -> bool:
    """Put one character's standing craft errand where mod-overseer's
    DriveCraft reads it (infra#440).

    UNCONDITIONAL, unlike `_write_trade_errand`'s ECONOMY_ERRANDS guard -
    `craft_spell` has no other writer to collide with yet (no economy pass
    aims it, no dungeon coordinator touches it), so there is no "somebody
    else owns this column right now" case to protect against. If one is
    ever added, it needs a guard exactly like `_write_trade_errand`'s.

    RE-ASSERTED EVERY CALL, same reasoning as the trade errand: mod-overseer
    clears `craft_spell` itself on a hard failure (unknown spell, spell not
    known), so re-writing an outstanding errand is a no-op, and re-writing
    one a worldserver restart lost is a repair.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "UPDATE overseer_roster SET craft_spell = %s WHERE name = %s",
                (spell_id, character),
            )
        except pymysql.err.OperationalError as exc:
            if exc.args and exc.args[0] == 1054:
                log.warning(
                    "overseer_roster.craft_spell is missing - %s cannot be sent "
                    "to craft until the db-import image carrying mod-overseer's "
                    "SQL has shipped (infra#440)",
                    character,
                )
                return False
            raise
    return bool(cur.rowcount)


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


def _raidprep_members() -> list:
    """The roster rows `job = raid prep` is decided from, with the skills observed.

    The same two reads as `_train_members` and no join, for the same reason:
    `character_skills` is keyed by guid and `overseer_roster` by name, and the
    collation split documented above this file's other cross-table read makes
    every such join a thing to get right once and then never notice again.

    Guarded for 1146 and 1054 like every other overseer_* read: a realm whose
    db-import image predates the profession columns has no errand to drive, and
    the honest answer there is an empty family rather than an exception that
    costs the whole protect cycle.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT name, job, professions, level "
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
            if not (exc.args and exc.args[0] in (1054, 1146)):
                raise
            log.warning("character_skills is unreadable; raid prep can decide nothing")
        return [
            raidprep.Member(
                name=row["name"],
                job=row["job"] or "",
                wanted=raidprep.parse_wanted(row["professions"]),
                holds=tuple(sorted(held.get(row["name"], ()))),
                level=int(row["level"] or 0),
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


def _learn_aim_rows() -> list:
    """The roster and the trade table, as learnaim reads them (infra#3686).

    TWO READS AND NO JOIN, deliberately, and it is the same choice
    `_train_members` makes one screen down for the same reason. Five rows come
    back from each, there is no ordering requirement between them - and these
    two tables sit on opposite sides of the collation split documented above
    `_errand_traveller`, so a join would need an explicit COLLATE on the trade
    operand to avoid MySQL 1267. Not joining removes that question rather than
    answering it. The names are matched in Python, exactly as `_train_members`
    matches `character_skills`, and it is safe for the same reason: both
    columns are written from `characters.name`, so they agree byte for byte.

    FAILS CLOSED, and that is not the usual degrade. Every other overseer_*
    read answers 1054/1146 with an empty or narrowed result and carries on;
    this one returns nothing at all, because its caller writes to the two most
    collision-prone columns in the schema and a HALF-read roster would make a
    live errand look derived and an unsettled one look settled. A cycle that
    cannot see both tables does nothing, and the next cycle is ten minutes
    away.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                # `lead` BACKTICKED: reserved word in MySQL 8, the same trap
                # _mark_party_leader's own comment records.
                "SELECT name, `lead`, professions, travel_npc, learn_skill "
                "FROM overseer_roster WHERE enabled = 1"
            )
            roster = list(cur.fetchall())
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                return []
            raise
        if not roster:
            return []

        traded: dict = {}
        settled: dict = {}
        try:
            # No alias on the table and no join: tests/test_collation_split.py
            # expects exactly ONE `overseer_trade t` join in this tree and this
            # is deliberately not a second one.
            cur.execute(
                "SELECT character_name, skill_id, status FROM overseer_trade "
                "WHERE verb = 'learn'"
            )
            for row in cur.fetchall():
                name = row["character_name"]
                skill = int(row["skill_id"] or 0)
                traded.setdefault(name, []).append(skill)
                if row["status"] == "learned":
                    settled.setdefault(name, []).append(skill)
        except pymysql.err.MySQLError as exc:
            if not (exc.args and exc.args[0] in (1054, 1146)):
                raise
            log.warning(
                "overseer_trade is unreadable; no learn errand can be shown "
                "to have settled or to be derived this cycle, so none is "
                "touched"
            )
            return []

    return [
        learnaim.Row(
            character=row["name"],
            learn_skill=int(row["learn_skill"] or 0),
            travel_npc=row["travel_npc"] or "",
            leads=bool(int(row["lead"] or 0)),
            wanted=trainjob.parse_wanted(row["professions"]),
            traded=tuple(sorted(set(traded.get(row["name"], ())))),
            settled=tuple(sorted(set(settled.get(row["name"], ())))),
        )
        for row in roster
    ]


def _derived_errand_traveller() -> str:
    """Who leads because a learn errand nothing else can see is outstanding.

    THE THIRD AND NARROWEST BORROWER OF THE LEAD (infra#3686). mod-overseer
    writes `overseer_roster.learn_skill` for itself through `AimLearnAt` and
    then cannot act on it - nothing in the worldserver ever writes
    `travel_npc = 'profession trainer'` - so a derived errand is born with no
    journey attached, and `TravelAimBook::Claim` refuses every other aim for
    that character while it stands. Aiming it is half the answer; the C++ is
    explicit that the other half is leadership, because `AimedMover` answers
    `RefuseInFormation` for a follower and names the remedy itself.

    ASKED LAST BY `_head_now`, behind an order a person gave and a trade the
    family decided, and ahead only of seniority - so it borrows the lead only
    from a family that is otherwise resting, and can never preempt either of
    the other two.

    NO ERRAND_LEAD_HOURS HERE, and learnaim.derived carries the argument: that
    bound exists for a worldserver built WITHOUT the professions verbs, which
    never clears the column - and an errand `AimLearnAt` wrote is proof those
    verbs are running on this realm.

    Same contract as `_errand_traveller`'s own handler on failure: loudly
    logged, still answers "nobody", never costs the caller its cycle.
    """
    try:
        return learnaim.traveller(_learn_aim_rows())
    except pymysql.err.MySQLError:
        log.exception(
            "derived errand traveller lookup failed; leading the family by "
            "seniority this cycle"
        )
        return ""


def _run_learn_aim_plan(statements) -> int:
    """Run learnaim's writes, in order, on one cursor. Returns rows changed.

    Same shape and same degrade as `_aim_train_traveller` above, and for the
    same reasons: the statements are BUILT IN THE PURE MODULE, every value is
    bound there, and this function has no opinion it could get wrong.

    THE COUNT IS WORTH RETURNING, because every statement is a
    compare-and-swap (learnaim.statements says why). A zero is not a failure -
    it is another writer having taken the column between the read and the
    write, which is exactly the collision the compare-and-swap exists to lose
    gracefully. The next cycle re-reads and re-decides, and whoever won is
    untouched.
    """
    landed = 0
    with _connect() as conn, conn.cursor() as cur:
        for sql, params in statements:
            try:
                cur.execute(sql, params)
            except pymysql.err.MySQLError as exc:
                if exc.args and exc.args[0] in (1054, 1146):
                    log.warning(
                        "overseer_roster is missing the profession errand "
                        "columns - no learn errand can be reconciled on this "
                        "realm until the db-import image carrying "
                        "mod-overseer's SQL has shipped (infra#2757)"
                    )
                    return landed
                raise
            landed += cur.rowcount
    return landed

def _head_now() -> str:
    """Who leads the family this cycle.

    bonds.head_of_family() is the resting answer and the overwhelmingly common
    one: Grug, the father, by seniority, forever. An errand borrows it, because
    the leader is the family's one traveller and an errand is somewhere to
    travel to. A standing `job = train` borrows it FIRST - see
    _train_traveller for why an order a person just gave outranks a plan the
    family drifted into. The third borrower is _derived_errand_traveller, and
    it is asked last of the three: an errand mod-overseer wrote for itself is
    real, and it is still the weakest claim on the lead of the three, because
    nobody outside the worldserver asked for it (infra#3686).

    EVERY CALLER ASKS THIS FUNCTION AND NOT ITS PARTS, which is the whole
    point of it existing. Two of those callers must agree or the family
    splits: _mark_party_leader writes the `lead` flag the module enforces, and
    _give_them_a_life hands out the strategies, so a family told to follow a
    character that is about to stop leading is a party in two pieces. The
    others - the vendor, bank, guild-bank, tabard and repair trips - anchor a
    walk on "whoever can actually walk" and get the same answer for free. NO
    COUNT IS GIVEN HERE ON PURPOSE: this docstring said "asked in exactly two
    places" while there were seven, because a number in prose rots silently
    every time somebody adds a caller and the invariant above does not.

    WHY THERE IS NO LONGER A BIND OVERRIDE (infra#3420, retired here).
    REVIVAL USES THE GROUP LEADER'S BIND AND NEVER THE CHARACTER'S OWN
    (mod_overseer.cpp, RevivalHome reads group->GetLeaderGUID()), so every
    death gathers all five wherever the leader is bound. That fact is
    unchanged and is why this answer matters so much. What changed is the
    binds: on 2026-09-07 the father was bound in Elwynn while the campaign ran
    on Kalimdor, and a module-level HOMEWARD_LEAD pinned the lead to the one
    character bound at the port town on the working continent. Read live on
    2026-09-13, all five are bound in Ratchet (map 1, zone 392) within four
    yards of each other, beside the same innkeeper. The override was selecting
    one character for a property every one of them now has, so it could only
    ever disagree with seniority and never improve on it. Deleted rather than
    set to None: a constant that cannot change the answer is a third state for
    the next reader to rule out. If a bind ever strands the head again, the
    seam to re-add it is the `or` chain below, where three borrowers already
    demonstrate the shape.
    """
    return (_train_traveller() or _errand_traveller()
            or _derived_errand_traveller()
            or bonds.head_of_family())


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
        # WHO HAS THE FAMILY'S ONE TRAVELLER, AND SINCE WHEN (infra#3703).
        # `overseer_roster.travel_npc` is a single slot that seven passes write
        # and, because only the leader carries `new rpg`, it is one slot for the
        # whole family rather than one per character. Nothing arbitrated between
        # them: whichever pass ran first held the column and the rest were
        # refused for their whole cycle. The ledger is in memory because there
        # is nowhere else to put it - the overseer tables ship in mod-overseer's
        # db-import image and would not reach the realm with this change - and
        # townslot.Slot is written to survive that: a restart finds the column
        # still set, adopts it as an errand with no owner, and gives it the
        # longer of the two leases.
        self._town_slot = townslot.Slot(
            lease=TOWN_SLOT_LEASE_SECONDS,
            releasable=_is_economy_aim,
        )
        # Leader snapshot history used only to detect a vendor aim that has
        # stopped moving. The decision itself lives in vendor_stall.py.
        self._vendor_movement: dict[str, vendor_stall.Movement] = {}
        # The leader can keep moving while the family is split across maps or
        # far enough apart that nobody reaches one usable vendor counter.
        # vendor_stall owns the pure cohesion clock; this bridge only retains
        # its last observation between polls.
        self._vendor_family_movement: vendor_stall.FamilyMovement | None = None

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
                self._design_tabard,
                self._assign_trades,
                self._assign_crafts,
                self._sample_family,
                self._share_quests_loop,
                self._move_materials_loop,
                self._guild_share_loop,
                self._vendor_loop,
                self._bank_loop,
                self._guild_bank_loop,
                self._mail_loop,
                self._recruit_loop,
                self._craft_supply_loop,
                self._craft_rhythm_loop,
                self._forge_loop,
                self._auction_loop,
                self._recipebook_loop,
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
        # What council._dungeon_proposal needs to reason about the whole
        # family, alongside the per-member rows assess() already gets.
        # level_rows comes straight from `members` rather than a second
        # query: they are the exact characters the council can hear from,
        # which is also what _dungeon_proposal requires of its weakest voice
        # (a member absent from THIS sitting cannot be made to speak).
        #
        # cards IS DELIBERATELY EMPTY HERE. achievements.build_achievements
        # needs the full Chronicle fetch (item templates, boss-drop
        # inference, quest rewards - map_server._fetch_achievements) to
        # build it properly, and replicating that whole pipeline in the
        # bridge for an hourly decision was more than this pass could take
        # on. The cost is real but bounded: _drops_seen with no cards only
        # changes the verdict SENTENCE and which already-cleared, far-off
        # dungeons stay listed past HORIZON - it does not change whether a
        # dungeon in the family's current level range reads as ready, which
        # is the whole of what the proposal acts on. Tracked as a follow-up
        # rather than silently declared complete.
        level_rows = [{"name": m.name, "level": m.level} for m in members]
        completed_wings = await asyncio.to_thread(_fetch_scarlet_completion)
        held = council.hold(members, history=history,
                            level_rows=level_rows, cards=[],
                            completed_wings=completed_wings)
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

    async def _design_tabard(self) -> None:
        """The family argues about the tabard, once (infra#2831).

        WHY THIS IS NOT PART OF THE COUNCIL. The council decides what TODAY is
        for and is meant to run forever; this decides one thing once and then
        has nothing further to say. Folding it in would have made every hourly
        sitting carry a question that is already answered.

        AND WHY IT CANNOT RESTAGE ITSELF, which is the risk the ticket names
        out loud - "a tabard debate that never ends would be a very funny way
        to rediscover that bug". The guard is not a memory of having spoken, it
        is the world: a guild with any of its five emblem columns set has a
        tabard, so the debate is unreachable the moment it succeeds. Nothing to
        get out of step, and a tabard cleared by hand correctly starts the
        argument again.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("TABARD_CYCLE_SECONDS", "3600"))
        await asyncio.sleep(min(cycle, 180.0))
        while not self.is_closed():
            try:
                await self._tabard_once()
            except Exception:
                log.exception("tabard failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _tabard_once(self) -> None:
        row = await asyncio.to_thread(_fetch_family_guild)
        if not row:
            log.debug("tabard: the family is in no guild")
            return
        worn = [row[f.name] for f in tabard.FIELDS]
        if any(worn):
            log.debug("tabard: %s already wears %s", row["name"], worn)
            return

        # ASKED ONCE, EVEN IF ASKING DID NOT WORK. See _tabard_already_asked:
        # the emblem columns alone only guard the case where the command
        # SUCCEEDED, and the whole point of the guard is the case where it did
        # not. Logged at info and not debug when the ask failed, because a
        # tabard the family agreed on and never got is worth noticing.
        held = await asyncio.to_thread(_tabard_already_held)
        if held:
            log.debug("tabard: the family already had this argument (%s lines "
                      "heard, last %s)", held["heard"], held["last_heard"])
            return

        # The ids the world stores for what each of them is, read from their
        # own character rows rather than from a table in tabard.py. race and
        # class are public - you can see a gnome rogue - so this breaks none
        # of the council's private/public rule.
        kin = [tabard.Kin(name=r["name"], race=r["race"], char_class=r["class"])
               for r in await asyncio.to_thread(_fetch_family_kin)]

        # EVERY SPEAKER HAS TO BE IN THE WORLD, and this is checked BEFORE the
        # scene is built rather than discovered from eleven failed rows.
        #
        # Two things go wrong without it, and the second is the bad one.
        #
        # 1. COST. Voicing a line is an LLM call (_in_character -> _ask_llm),
        #    so an unheard scene is eleven of them, every cycle, for as long
        #    as nobody is logged in. The family was offline for five hours on
        #    2026-09-12 and the loop kept paying for a conversation nobody
        #    could hear.
        # 2. A HALF-TOLD ARGUMENT, PERMANENTLY. _tabard_already_held counts
        #    PARTIAL delivery as held - deliberately, because re-speaking
        #    lines somebody already heard is the stutter the guard exists to
        #    prevent. So with three of five in the world, six lines land, the
        #    guard closes, and the family is stuck having had two thirds of
        #    an argument with no way to finish it. Waiting for all five costs
        #    an hour; getting this wrong costs the scene.
        #
        # _bot_held_names is reused rather than reimplemented: same table,
        # same 60-second freshness window, and it already carries the
        # is_bot rule - a character Evan is holding at the keyboard has no
        # PlayerbotAI and could not say its line anyway.
        present = set(await asyncio.to_thread(
            _bot_held_names, [k.name for k in kin]))
        absent = [k.name for k in kin if k.name not in present]
        if absent:
            log.debug("tabard: not staging, %s not in the world",
                      ", ".join(sorted(absent)))
            return

        held = tabard.debate(kin)
        if held.design is None:
            # Same shape as _council_once: a conversation with nothing in it
            # is reported, not staged.
            log.info("tabard: %s", held.reason)
            return
        design = held.design

        # ASKED BEFORE THE SCENE, not after. The core refuses an emblem the
        # guild master cannot pay for, and a family that argues its way to a
        # tabard and is then quietly refused has held the conversation for
        # nothing - the lines are already in Discord by then.
        if not design.affordable(row["money"]):
            log.info("tabard: %s holds %d copper and an emblem costs %d",
                     design.applied_by, row["money"], tabard.EMBLEM_PRICE)
            return

        context = held.reason
        for line in held.lines:
            speaker, _, plain = line.partition(": ")
            text = await self._in_character(speaker, plain, context)
            # party, not say - the same 25-yard problem the council hit.
            await asyncio.to_thread(
                _insert_speak,
                relay.SpeakCommand(speaker, "party", text, "", TABARD_SOURCE),
            )
            await asyncio.to_thread(_insert_thought, speaker, "council", text)

        # TO THE GUILD MASTER BY NAME, because Guild::HandleSetEmblem refuses
        # anybody else - it is not whoever happens to be carrying the row.
        await asyncio.to_thread(
            _insert_guild, design.applied_by, design.command(), TABARD_SOURCE,
        )
        log.info("tabard: %s -> %s (%s)", row["name"], design.command(), held.reason)

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

        await asyncio.to_thread(_activate_training)

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

    async def _craft_once(self) -> None:
        """Aim every `job='craft'` character at the recipe craft.recipe_for
        picks for its current skill (infra#440).

        DELIBERATELY DOES NOT DECIDE WHO GETS `job='craft'`. That is an
        operator/decree/council decision this pass does not make - v1's own
        design doc leaves "when does a character start crafting" open, the
        same way `job='train'`/`'rest'`/every other stand-down-only mode
        already does. This loop only answers "given that a character IS on
        job='craft' right now, which recipe should it be casting" - the
        `craft_spell` column, re-asserted every cycle exactly like the trade
        errand, so a worldserver restart cannot lose it.

        A character on `job='craft'` with no matching entry in
        `craft.RECIPES` (profession not yet in the table, or skill value
        outside every bracket) gets `craft_spell = 0` written - explicit
        "nothing to do" rather than a stale spell id left standing from a
        bracket the character has since grown past.

        AND A MINER MAY BE HANDED ITS SMELT INSTEAD (infra#3748). `craft.py`
        now carries a Mining bracket, and a character holding mining has TWO
        recipes it could legally be casting - the crafting one and the smelt.
        Which of them it should carry depends on what is in its bags, which
        `craft.craft_errand` deliberately cannot see, so the choice is
        `craft_rhythm.errand`'s and this pass just writes what it answers. The
        extra query that costs is `_fetch_item_counts`, already batched one
        round trip per DISTINCT item entry across the whole family, and only
        the family's two miners contribute an entry to it at all.
        """
        names = await asyncio.to_thread(_crafting_roster)
        if not names:
            return
        skills = await asyncio.to_thread(_fetch_trade_skills, names)
        # BOTH CANDIDATES' REAGENTS, FETCHED BEFORE EITHER IS CHOSEN. The choice
        # compares what is held for the spend against what is held for the
        # smelt, so counting only the chosen recipe's reagents would need the
        # choice to have been made already. See craft_rhythm.reagents_to_count.
        wanted = {
            (name, entry)
            for name in names
            for entry in craft_rhythm.reagents_to_count(name, skills.get(name, {}))
        }
        counts = await asyncio.to_thread(_fetch_item_counts, sorted(wanted))
        for name in names:
            held = {entry: count for (who, entry), count in counts.items()
                    if who == name}
            chosen = craft_rhythm.errand(name, skills.get(name, {}), held)
            await asyncio.to_thread(_write_craft_errand, name, chosen.spell)
            if chosen.spell:
                log.info("craft: %s aimed at %s spell %s - %s",
                         name, "smelt" if chosen.smelting else "recipe",
                         chosen.spell, chosen.why)

    async def _assign_crafts(self) -> None:
        """Same cadence family as _assign_trades - a standing errand needs
        re-asserting far more often than it needs re-deciding, but nothing
        here is decided at all (see _craft_once), so this loop is cheaper:
        no council announcement, no party-chat line, just the errand column
        kept correct for whoever operations has put on job='craft'.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("CRAFT_CYCLE_SECONDS", "300"))
        await asyncio.sleep(min(cycle, 90.0))
        while not self.is_closed():
            try:
                await self._craft_once()
            except Exception:
                log.exception("craft failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _craft_supply_once(self) -> None:
        """Buy the vendor reagent a standing craft errand needs (infra#3613).

        THE GAP THIS CLOSES. Every crafting recipe craft.py verified tonight
        that names a vial - all ten Alchemy potions but one - was proven live
        to stall on it: Ugga sat on job='craft' with 20 Silverleaf, 13
        Peacebloom and zero Empty Vials, casting nothing. craft.py's own
        docstring is explicit that it never checks reagents; this is the pass
        that does, for the reagent classes (craft_supply.REAGENT, single
        reagent per spell) verified against the live world database rather
        than guessed.

        THE SHOPPING LIST IS PER CANDIDATE; THE WALK IS NOT (infra#3692).
        This function used to write one `travel_npc = 'vendor'` per
        candidate, and this paragraph used to argue for it: a vial is a
        personal shopping list keyed to whichever recipe THIS character's
        craft_spell names, not a party errand the leader can carry for
        everyone. The premise is right and the conclusion did not follow. A
        follower aimed at anything does not move. The family carries exactly
        one `new rpg` and it is on the LEADER, deliberately - it acts at
        relevance 3.0-11.0 against follow's 1.0, so a follower holding both
        wanders off every tick, which is infra#2812's 937-yard scatter, and
        `professions.traveller` is the whole written argument. mod-overseer
        says it outright when it happens: "'Ugga' was sent to '5594' but does
        not carry `new rpg` - nothing walks it anywhere. Followers travel by
        following the leader; aim the leader instead."

        So the WALK is `_vendor_once`'s shape - one aim, on `_head_now()`'s
        leader, through the same ECONOMY_ERRANDS-guarded
        `_write_trade_errand` - while the SHOPPING LIST stays per candidate,
        because `DoBuy` runs for whoever `overseer_command.target_name` names
        and looks for a vendor near THAT buyer, exactly as the per-holder
        sell rows already rely on. Both halves are true at once: the family
        walks together, and each character buys their own reagent once they
        are standing there.

        AND THE WALK IS TO A NAMED VENDOR, NOT TO THE `vendor` ROLE. The
        keyword resolves to the NEAREST vendor this character may deal with,
        which answers "where is a shop" when the question asked was "where is
        a shop that sells Empty Vial" - measured live in Gadgetzan those were
        90 yards and one whole different NPC apart, and the family went to
        the wrong one and bought nothing. `craft_supply.supply_trip` chooses
        the creature entry, `_fetch_reagent_vendors` reads the candidates it
        chooses between, and craft_supply's own docstring has why a bare
        entry needs no C++ change and why no coordinate is ever authored.

        A SECOND PASS BELOW HANDLES `craft_supply.REAGENTS` (infra#3609/
        #3611's Tailoring/Leatherworking thread and dye) - kept as its own
        block rather than folded into the loop above because a REAGENTS
        recipe can name TWO vendor reagents on one cast (thread AND dye),
        which needs a per-candidate SET of held counts and can queue more
        than one buy errand per candidate per pass; craft_supply.py's own
        docstring explains why REAGENTS is a second dict rather than more
        REAGENT entries, and the same reasoning is why this is a second
        block rather than a single loop trying to cover both shapes.

        THE ERRAND IS PER CHARACTER AND THE MODE IS THE FAMILY'S (infra#3805).
        This used to read `_fetch_craft_spells`, which answers both at once by
        filtering `job='craft'`, and that is what made the pass dark: the
        family sits on `job='quest'` whenever anybody is short of a gathered
        reagent, which is the steady state AND the state in which buying the
        rest is the useful thing to do. Measured on wow-dev 2026-09-14 - zero
        `craft_supply:` lines in ninety minutes, four craft errands standing,
        the auction pass logging thirty-five. `_fetch_standing_crafts` carries
        the whole argument and names this call site; it is now the caller.

        THE MODE IS STILL READ, AND THE ANSWER IS CRAFT AND QUEST, NOT ANY
        JOB. A purchase is personal, but `_aim_at_reagent_vendor` asks for the
        family's ONE traveller, so this pass can pull the leader across a
        zone. Those two are what `craft_rhythm` alternates between, and in
        both of them fetching a recipe's reagents is what the family is
        already doing. `dungeon`, `train` and `rest` are standing orders this
        pass knows nothing about and must not outrank - the run coordinator's
        SOLE trigger is the leader's `job='dungeon'` (mod-overseer#88/#144),
        so widening to any job with no gate would walk the leader out of an
        instance to buy thread. Read once and family-wide, because jobs.py
        says a job IS family-wide; rows that disagree are a half-landed
        fan-out, which `standing_mode` answers with '' - ask again next cycle,
        and say so rather than shop through the confusion.

        EVERY OUTCOME IS LOGGED, INCLUDING THE ONES WHERE NOTHING HAPPENS -
        `_recruit_once`'s house rule, and this pass had two silent `return`s
        above its summary line, which is how a quiet cycle and a pass that
        never ran looked identical for ninety minutes.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names:
            log.info(
                "craft_supply: no protected character to shop for, so nothing "
                "is bought this pass"
            )
            return

        mode = craft_rhythm.standing_mode(
            await asyncio.to_thread(_standing_jobs)
        )
        if mode not in (craft_rhythm.MODE_CRAFT, craft_rhythm.MODE_GATHER):
            log.info(
                "craft_supply: the family is on job=%s rather than %s or %s, "
                "so no reagent is bought and the traveller is left alone",
                mode or "nothing agreed", craft_rhythm.MODE_CRAFT,
                craft_rhythm.MODE_GATHER,
            )
            return

        spells = await asyncio.to_thread(_fetch_standing_crafts, names)
        candidates = {
            name: spell_id
            for name, (spell_id, _) in spells.items()
            if spell_id in craft_supply.REAGENT
        }
        multi_candidates = {
            name: spell_id
            for name, (spell_id, _) in spells.items()
            if spell_id in craft_supply.REAGENTS
        }
        if not candidates and not multi_candidates:
            log.info(
                "craft_supply: %d craft errand(s) standing on job=%s, none of "
                "which names a vendor-bought reagent, so there is nothing to "
                "buy this pass", len(spells), mode,
            )
            return

        queued = 0
        # EVERY REAGENT NOBODY CAN REACH A COUNTER FOR, from both blocks
        # below, collected rather than acted on one at a time (infra#3692).
        # One walk can serve only one of them - the family has one traveller
        # - so the choice of which is a decision about the whole family and
        # is made once, at the end, by craft_supply.supply_trip.
        needs: list = []
        if candidates:
            free_slots = await asyncio.to_thread(_fetch_free_slots, list(candidates))
            # ONE BATCH, NOT ONE QUERY PER CANDIDATE - holdings for every
            # candidate's reagent are fetched together (at most four round
            # trips, one per DISTINCT item entry craft_supply.REAGENT's
            # eleven recipes resolve to - three vials plus Weak Flux), the
            # same batching discipline _fetch_free_slots/_fetch_craft_spells
            # already hold to. Town is the one thing that genuinely cannot
            # batch this way: it is a read of wherever `name` is CURRENTLY
            # STANDING, which is exactly as per-character as
            # `_vendor_once`'s own per-holder `_fetch_town` calls already
            # are.
            pairs = [
                (name, craft_supply.REAGENT[craft_spell][0])
                for name, craft_spell in candidates.items()
            ]
            held_by = await asyncio.to_thread(_fetch_item_counts, pairs)
            for name, craft_spell in sorted(candidates.items()):
                entry, _label, _price = craft_supply.REAGENT[craft_spell]
                town = await asyncio.to_thread(_fetch_town, name)
                held = held_by.get((name, entry), 0)
                # A NEED, NOT AN AIM (infra#3692). What used to stand here
                # was one `travel_npc = 'vendor'` write per candidate, and
                # both halves of it were wrong - the keyword cannot see the
                # reagent, and the character it was written onto is usually a
                # follower, who does not walk. Whether a trip is warranted at
                # all is craft_supply's decision and not this loop's: a
                # character already carrying TARGET needs no journey, which
                # `entry not in town.stocks` alone cannot tell you.
                need = craft_supply.reagent_need(name, craft_spell, held, town)
                if need:
                    needs.append(need)
                _spell_id, money = spells[name]
                errand, note = craft_supply.reagent_errand(
                    name, craft_spell, held, money, free_slots.get(name, 0), town,
                )
                if note:
                    log.info("craft_supply: %s", note)
                    continue
                if errand and await asyncio.to_thread(_insert_town_errand, errand):
                    queued += 1
                    log.info(
                        "craft_supply: %s %s - %s", name, errand.command, errand.why
                    )

        if multi_candidates:
            free_slots2 = await asyncio.to_thread(
                _fetch_free_slots, list(multi_candidates)
            )
            pairs2 = [
                (name, entry)
                for name, craft_spell in multi_candidates.items()
                for entry, _label, _price, _qty in craft_supply.REAGENTS[craft_spell]
            ]
            held_by2 = await asyncio.to_thread(_fetch_item_counts, pairs2)
            for name, craft_spell in sorted(multi_candidates.items()):
                needed = craft_supply.REAGENTS[craft_spell]
                town = await asyncio.to_thread(_fetch_town, name)
                held = {
                    entry: held_by2.get((name, entry), 0)
                    for entry, _label, _price, _qty in needed
                }
                # ONE NEED PER MISSING REAGENT, AND NO `continue` (infra#3692).
                # Thread and dye need not share a counter, so each becomes its
                # own need and `supply_trip` takes whichever has the nearer
                # vendor this pass; the pass after that finds it carried and
                # only the other still outstanding. Two vendors, no second
                # mechanism - just the willingness to take more than one pass,
                # which a ten-minute loop has in abundance.
                #
                # Falling through rather than skipping the buy is the other
                # half of that: standing at the thread vendor with no dye in
                # reach, the thread should still be bought.
                # `craft_reagent_errands` has always returned per-reagent
                # errands AND per-reagent refusals for exactly this case
                # (tests/test_craft_supply.py has held it to that since it
                # shipped), and a `continue` above it meant that half had no
                # caller.
                needs.extend(
                    craft_supply.craft_reagent_needs(name, craft_spell, held, town)
                )
                _spell_id, money = spells[name]
                errands, notes = craft_supply.craft_reagent_errands(
                    name, craft_spell, held, money, free_slots2.get(name, 0), town,
                )
                for note in notes:
                    log.info("craft_supply: %s", note)
                for errand in errands:
                    if await asyncio.to_thread(_insert_town_errand, errand):
                        queued += 1
                        log.info(
                            "craft_supply: %s %s - %s",
                            name, errand.command, errand.why,
                        )

        if needs:
            await self._aim_at_reagent_vendor(needs)

        # The mode is named here too, so ONE line proves the fix: `on
        # job=quest` is this pass shopping while the family gathers, which is
        # the cycle infra#3805 says it kept missing.
        log.info(
            "craft_supply: queued %d buy errand(s) across %d candidate(s) on "
            "job=%s, %d reagent(s) still need a trip",
            queued, len(candidates) + len(multi_candidates), mode, len(needs),
        )

    async def _claim_town_slot(self, claimant: str, character: str,
                               aim: str, urgent: bool = False) -> bool:
        """Ask for the family's one traveller, and act on the answer (infra#3703).

        THE ONE DOOR EVERY TOWN ERRAND NOW GOES THROUGH. Seven passes write
        `travel_npc` and each of them used to write it directly, read the
        refusal, and log its own version of "already on somebody else's
        errand". Nothing decided between them, so the winner was whichever pass
        happened to run first and the loser was starved for its whole cycle -
        measured on wow-dev with the auction pass refused two minutes after the
        guild bank pass took the column, and the guild bank pass itself starved
        behind the sell pass for its entire life before that.

        WHAT IS DECIDED HERE AND WHAT IS NOT. `townslot` decides turn and lease
        out of facts this method reads; the pass itself still decides whether it
        wants a journey at all, and its own `_settle_*` step still decides when
        its errand is over. This adds arbitration between passes and nothing
        else.

        THE LEADER IS READ HERE RATHER THAN TRUSTED FROM THE CALLER, which
        costs one row and buys the guarantee that "only the leader travels" is
        enforced in one place instead of remembered in seven. mod-overseer
        refuses to walk anybody who is not carrying `new rpg` - "nothing walks
        it anywhere. Followers travel by following the leader" - and a follower
        aim is not merely inert: it is never released, and it bills that
        character fifteen seconds of economy errand budget on every travel poll
        until the character is refused for fifteen minutes.

        THE COLUMN IS READ, AND A STALE READING CANNOT BECOME A WRONG WRITE.
        `_current_travel_npc` says of itself that nothing branches on its
        answer; this is the deliberate second caller that does, and it is safe
        for the reason `_errand_holders` gives for being a second reader. Both
        effects below are compare-and-swaps: the release names the exact aim it
        is handing back, and the write carries `_write_trade_errand`'s own
        `travel_npc IN (...)` guard. A column that changed hands between the
        read and the write therefore matches nothing, and the worst a stale
        answer costs is one wasted cycle.

        RETURNS WHETHER THE LEADER NOW CARRIES THIS AIM, which is what every
        caller already did with `_write_trade_errand`'s return value. `hold`
        returns True and writes nothing: the column already says what this pass
        wanted it to say, and re-asserting it makes mod-overseer's aim book
        erase its own state and read a standing errand as a new one (infra#3708).
        """
        leader = await asyncio.to_thread(_head_now)
        column = await asyncio.to_thread(_current_travel_npc, leader)
        now = time.monotonic()
        decision = self._town_slot.want(
            claimant=claimant, character=character, aim=aim, leader=leader,
            column=column, retaskable=_retaskable_from(aim), now=now,
            urgent=urgent,
        )
        if not decision.granted:
            log.info("%s", townslot.report(decision))
            return False
        if decision.release is not None:
            # HANDED BACK BEFORE IT IS TAKEN, because `_write_trade_errand`'s
            # economy guard retasks only an IDLE traveller and that guard is
            # not being weakened here - mod-overseer#438 is why it exists. A
            # preemption is therefore two statements: give the stuck errand
            # back, then take the empty column the ordinary way.
            released = await asyncio.to_thread(
                _release_trade_errand, decision.release.character,
                decision.release.aim,
            )
            if not released:
                # Not a failure, and not a reason to stop. The column changed
                # hands between the read and this write, so there was nothing
                # of that shape to hand back; the guarded write below is what
                # decides whether this pass gets the traveller anyway.
                log.info(
                    "town slot: %s was no longer carrying %r, so nothing was "
                    "handed back before %s asked for it",
                    decision.release.character, decision.release.aim, claimant,
                )
        if decision.verdict == townslot.SLOT_HOLD:
            self._town_slot.settle(decision, True, now)
            log.debug("%s", townslot.report(decision))
            return True
        taken = await asyncio.to_thread(
            _write_trade_errand,
            professions.Errand(character=character, travel_npc=aim),
        )
        self._town_slot.settle(decision, taken, now)
        if not taken:
            # THE SLOT SAID YES AND THE COLUMN SAID NO, which is a race rather
            # than a contradiction: something wrote the column between the read
            # above and the UPDATE. The ledger has already been told (settle),
            # so this pass keeps its place in the order and tries again next
            # cycle.
            log.info(
                "town slot: %s was granted the traveller %s for %r but the "
                "column had already changed hands, so no aim was written",
                claimant, character, aim,
            )
            return False
        log.info("%s", townslot.report(decision))
        return True

    async def _idle_town_slot(self, claimant: str) -> bool:
        """Ask for the family's traveller to be idle, with no successor aim."""
        leader = await asyncio.to_thread(_head_now)
        column = await asyncio.to_thread(_current_travel_npc, leader)
        now = time.monotonic()
        decision = self._town_slot.want_idle(
            claimant=claimant, character=leader, leader=leader,
            column=column, now=now,
        )
        if not decision.granted:
            log.info("%s", townslot.report(decision))
            return False
        if decision.release is None:
            self._town_slot.settle(decision, True, now)
            log.debug("%s", townslot.report(decision))
            return True
        released = await asyncio.to_thread(
            _release_trade_errand, decision.release.character,
            decision.release.aim,
        )
        self._town_slot.settle(decision, released, now)
        if released:
            log.info("%s", townslot.report(decision))
            return True
        log.info(
            "town slot: %s was no longer carrying %r, so nothing was handed "
            "back when %s asked for an idle traveller",
            decision.release.character, decision.release.aim, claimant,
        )
        return False

    async def _aim_at_reagent_vendor(self, needs: list) -> None:
        """Walk the family to a vendor that actually stocks one of the
        outstanding reagents (infra#3692).

        ONE TRIP, ON THE LEADER. `_head_now()` is what `_mark_party_leader`
        writes into `lead` and what `_give_them_a_life` reads to decide who
        carries `new rpg`, so it names the character that can actually walk -
        the same reason `_vendor_once` asks it rather than
        `bonds.head_of_family()`. Nothing here borrows leadership the way
        `_errand_traveller` does for a trainer errand, and it deliberately
        does not need to: a purchase is performed by the BUYER wherever the
        buyer is standing, so the shopper has to arrive, not to lead. Making
        a shopper the leader would reorganise the family around an errand
        that does not require it.

        THE LEADER'S OWN POSITION IS WHAT THE SEARCH IS ANCHORED ON, because
        the leader is the one whose walk has to exist. `ResolveTravelTarget`
        refuses a spawn that is not on the aimed character's map, so a vendor
        chosen from anywhere else would be an aim that silently resolves to
        nothing; `craft_supply._usable` asserts the same rule again on this
        side, where a test can reach it.

        A LEADER NOBODY CAN SEE IS A PASS THAT WRITES NOTHING. `_fetch_positions`
        is bounded to snapshots under a minute old, so an empty answer means
        the leader is offline or the snapshot machinery is not deployed - and
        a vendor chosen from a stale position is a vendor chosen for where
        somebody used to be.

        WHAT A NUMERIC AIM GIVES UP ON THE C++ SIDE, SAID HERE BECAUSE IT IS A
        REAL COST AND NOT A THEORETICAL ONE. `OverseerDecisions::IsMaintenance
        Errand` answers off `CounterRoleForAim`, which knows the three counter
        KEYWORDS and nothing else, so a bare creature entry is not a
        maintenance errand as far as mod-overseer is concerned. Two things
        follow, both verified by reading that file rather than assumed:

          * `TravelAimBook::Claim` will overwrite this aim, where it would
            have refused to overwrite `vendor`. That refusal is infra#3655,
            added for THIS pass - a dungeon escort's catch-up walk kept
            re-claiming Ugga before her vial errand could resolve. Aiming the
            LEADER rather than the straggler sidesteps most of it (a catch-up
            walk claims followers), but dungeon staging aims the leader and
            would still win. The consequence is a lost cycle, not a wrong
            write: the next pass raises the same need and re-aims.
          * `TravelAimBook::Release` will blank this aim on a release that
            book did not claim, where it would have left `vendor` standing.
            Same consequence, same recovery - and measured live, that is
            exactly what happened to a hand-written `5594`, which is how we
            know the column does come back to '' rather than sticking.

        Teaching that vocabulary about a numeric aim is a mod-overseer change
        and is deliberately not made here; this pass needs no C++ change to
        work, and a ten-minute loop that re-asserts is a cheaper answer than a
        core rebuild.
        """
        leader = await asyncio.to_thread(_head_now)
        positions = await asyncio.to_thread(
            _fetch_positions, [leader] if leader else []
        )
        spot = positions.get(leader)
        if not spot:
            log.info(
                "craft_supply: %d reagent(s) need a trip, but nothing can say "
                "where leader=%s is standing, so no vendor was chosen",
                len(needs), leader or "nobody",
            )
            return

        entries = sorted({int(need.entry) for need in needs})
        spawns = await asyncio.to_thread(_fetch_reagent_vendors, spot, entries)
        # WHERE THE SHOPPERS THEMSELVES ARE STANDING, read in the same bounded
        # window as the leader's own row. Following does not cross a map, so a
        # shopper on the other continent cannot be served by any walk the
        # leader takes - and this family has been split across an ocean
        # before. `_fetch_positions` already batches, so this is one query.
        shopper_maps = {
            name: int(row.get("map_id") or 0)
            for name, row in (
                await asyncio.to_thread(
                    _fetch_positions, sorted({n.shopper for n in needs})
                )
            ).items()
        }
        trip = craft_supply.supply_trip(
            needs, spawns, leader, int(spot.get("map_id") or 0),
            shopper_maps=shopper_maps,
        )
        # WARNING, NOT INFO, AND SAID EVERY PASS. A reagent nothing on this
        # map sells is a craft errand that can never complete where the
        # family is, and it needs a person to change the recipe or the
        # continent. It was invisible before this: "vendor aim taken=True"
        # and then nothing, forever.
        for note in trip.unreachable:
            log.warning("craft_supply: %s", note)
        if not trip.target:
            log.info("craft_supply: %s", craft_supply.report(trip))
            return

        # THE RETURN VALUE IS READ, for the reason infra#3464 gave when it
        # was not: the guard in `_write_trade_errand` can legitimately refuse
        # this write, and a caller that assumes it took would report a
        # journey nobody was sent on.
        #
        # THROUGH THE TOWN SLOT SINCE infra#3703, like every other pass that
        # wants the family's one traveller. The refusal this used to report is
        # now decided rather than raced: a numeric vendor entry is a REFINEMENT
        # of a standing `vendor` errand (see `_retaskable_from`), so the slot
        # grants it while the sell pass holds the column - it would be inert
        # otherwise - and only a genuinely different errand makes it wait.
        aimed = await self._claim_town_slot(
            "craft_supply", trip.traveller, trip.target)
        log.info("craft_supply: %s (aim taken=%s)", craft_supply.report(trip), aimed)
        if not aimed:
            log.info(
                "craft_supply: leader=%s is on an errand that a reagent trip "
                "may not retask, so the walk to creature %s waits for the "
                "next pass", trip.traveller, trip.target,
            )

    async def _craft_supply_loop(self) -> None:
        """Own loop and own clock, the same reasoning _bank_loop gives for
        itself: a failed pass is logged and retried rather than swallowed.
        Staggered past _vendor_loop (90s), _bank_loop (150s) and
        _guild_bank_loop (240s), all of which also write `travel_npc`
        through the same ECONOMY_ERRANDS guard - this one goes last so it
        never wins a race against a pass with more to do that cycle.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("CRAFT_SUPPLY_CYCLE_SECONDS", "600"))
        await asyncio.sleep(min(cycle, 300.0))
        while not self.is_closed():
            try:
                await self._craft_supply_once()
            except Exception:
                log.exception("craft_supply failed; retrying next cycle")
            await asyncio.sleep(cycle)

    def _rhythm_channel(self):
        """Where an automatic job order says what it did.

        `_set_job` is the sanctioned write path and it SPEAKS its answers -
        every refusal, and the `jobs.describe` line at the end. That is right
        for a person who has just typed an order and is waiting on a reply, and
        it is why this pass reuses that function rather than growing a second
        writer next to it: the guard, the fan-out and the report are all things
        this pass wants and none of them should exist twice.

        An automatic pass has no channel, though, and the honest way to give it
        one is not to let those sentences fall on the floor. `_LogChannel`
        below is the null object that keeps every one of them, at INFO, which
        is where anything running unattended is actually read from. The real
        overseer channel is preferred when the gateway has one, for the same
        reason `_goal_channel` prefers it: the operator watches a stream, and a
        family that just walked away from its anvil should say so where they
        will see it.
        """
        if OVERSEER_CHANNEL_ID:
            channel = self.get_channel(int(OVERSEER_CHANNEL_ID))
            if channel is not None:
                return channel
        return _LogChannel()

    async def _craft_rhythm_once(self) -> None:
        """Alternate the family between gathering and crafting (infra#3696).

        THE KEYSTONE OF infra#3731, AND THE ONLY THING HERE THAT WAS MISSING.
        Every other piece of the loop already worked and was measured working:
        `craft.craft_errand` picks the right recipe, `_craft_once` writes it,
        DriveCraft casts it, `craft_supply` buys the vendor half of its
        reagents, and ordinary `job='quest'` roaming gathers the rest. What
        nothing did was SWITCH between the two halves, so a family that ran out
        mid-session stood still until a person changed the column by hand. The
        operator did exactly that all afternoon on 2026-09-13; this is the pass
        that ends the need for it.

        THE ERRAND IS DERIVED, NOT READ OFF THE ROSTER, and that is load
        bearing rather than a shortcut. `overseer_roster.craft_spell` is only
        written by `_craft_once`, which is itself gated on job='craft'
        (`_crafting_roster`). So on a family that has never crafted, every
        craft_spell is 0 - and a pass that judged stock from that column would
        find nobody to have an opinion about, never order craft, never let
        `_craft_once` run, and never populate the column. That is a closed
        loop with no way in. Asking `craft.craft_errand` the same question
        `_craft_once` asks answers what this pass actually needs to know -
        "if the family were told to craft, what would each of them cast" -
        which is a question about a mode they are not currently in and which
        the column therefore cannot answer at all.

        IT WRITES ONLY A JOB MODE, AND ONLY THROUGH `_set_job`. Nothing here
        touches `travel_npc`: this project has been pinned in a shop for half
        an hour by a second writer for that column more than once (infra#3703,
        infra#3708, infra#3728) and the sanctioned writers are the existing
        economy passes. Nothing here touches `craft_spell` either - that is
        `_craft_once`'s, and re-deriving it is a read, not a write.

        AND IT WRITES ONLY ON A CHANGE. `craft_rhythm.rhythm` returns `changed`
        precisely so this can be a one-line gate: re-asserting the mode the
        family is already in would insert one `overseer_command` row per
        character per cycle for ever, which is command spam rather than a
        decision. The report is still logged every pass, changed or not,
        because the starvation it names is the half of infra#3696 that has
        nothing to do with the mode.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names:
            return
        standing = craft_rhythm.standing_mode(
            await asyncio.to_thread(_standing_jobs)
        )
        skills = await asyncio.to_thread(_fetch_trade_skills, names)

        # ONE BATCH FOR THE WHOLE FAMILY, the same discipline
        # `_craft_supply_once` already holds `_fetch_item_counts` to: one round
        # trip per DISTINCT item entry, not one per character. Five characters
        # short of four distinct materials is four queries, not twenty.
        # BOTH CANDIDATES, NOT JUST THE CRAFTING ONE (infra#3748). A miner may
        # be carrying its smelt rather than its craft, and judging its stock
        # against the recipe it is NOT casting would be the same class of error
        # as reading `craft_spell` off the roster: a sentence about the wrong
        # reagent. `craft_rhythm.errand` makes the same choice `_craft_once`
        # makes and from the same counts, so the two passes cannot disagree
        # about which recipe a character is on.
        wanted = {
            (name, entry)
            for name in names
            for entry in craft_rhythm.reagents_to_count(name, skills.get(name, {}))
        }
        counts = await asyncio.to_thread(_fetch_item_counts, sorted(wanted))
        # `carried` and not `held`: the gather branch at the foot of this
        # function already binds `held` to the standing travel aims, and one
        # name meaning two things inside one function is how a later edit
        # reads the wrong one.
        carried = {
            name: {entry: count for (who, entry), count in counts.items()
                   if who == name}
            for name in names
        }
        spells = {
            name: craft_rhythm.errand(
                name, skills.get(name, {}), carried[name]).spell
            for name in names
        }

        stands = [
            craft_rhythm.stand(
                name, spells[name],
                {reagent.entry: carried[name].get(reagent.entry, 0)
                 for reagent in craft_rhythm.GATHERED.get(spells[name], ())},
            )
            for name in names
        ]
        plan = craft_rhythm.rhythm(stands, standing)
        log.info("craft_rhythm: %s", craft_rhythm.report(plan))

        # HOW FAR THE FAMILY IS FROM THE RAID'S OWN SHOPPING LIST, every pass,
        # on the inputs this function already holds. `raidcraft` is the join
        # between the LEVELING table this pass drives (craft.RECIPES) and the
        # RAID plan on the Raid page (raidgoals.RECIPES), and its whole reason
        # for existing is that a crafter can climb a perfectly good ladder
        # without a single rung producing anything forty people would drink.
        #
        # IT IS LOGGED RATHER THAN ACTED ON, AND THAT IS THE HONEST SHAPE
        # TODAY. Not one of the twenty-two raid consumables on this realm is
        # castable by anybody in the family - the cheapest a trainer teaches is
        # Elixir of Fortitude at Alchemy 175 and Ugga is at 14/75 - so a pass
        # that BRANCHED on this would be a mechanism with no reachable case,
        # which this repo has been bitten by before. The preference itself is
        # exercised where it can be: in craft.RECIPES' own brackets, gated by
        # test_raidcraft.ThePreferenceIsTakenWhereItIsFree. What this line buys
        # is that the distance is visible while it closes, the same half of
        # infra#3696 `craft_rhythm.report` exists for.
        #
        # It costs no query: `skills` above is already the whole family's trade
        # skills, fetched for the rhythm decision itself.
        log.info("raidcraft: %s", raidcraft.report(names, skills))

        if plan.mode == craft_rhythm.MODE_GATHER:
            await self._idle_town_slot("craft_rhythm")

        if not plan.changed:
            return

        await self._set_job(
            core.JobDirective(mode=plan.mode, source="overseer:craft_rhythm"),
            self._rhythm_channel(),
        )

        # A GATHERING ORDER THAT CANNOT MOVE ANYBODY IS SAID OUT LOUD
        # (infra#3728). The idle request above leaves a live lease alone and
        # only hands a stale economy errand back through the same guarded
        # release path as every town pass. Until that bound is reached,
        # mod-overseer's `TravelHoldsTheWheel` still stands the quest drive
        # down, so name the aim that is keeping the family from roaming.
        if plan.mode == craft_rhythm.MODE_GATHER:
            held = {name: aim for name, aim
                    in (await asyncio.to_thread(_standing_travel_aims)).items()
                    if aim}
            if held:
                log.info(
                    "craft_rhythm: the family is told to gather, but %s still "
                    "carry a travel aim (%s) and a travel aim stands the quest "
                    "drive down - they will not roam until it clears "
                    "(infra#3728)",
                    ", ".join(sorted(held)),
                    ", ".join("%s=%s" % pair for pair in sorted(held.items())),
                )

    async def _craft_rhythm_loop(self) -> None:
        """Own loop and own clock, the same reasoning `_craft_supply_loop`
        gives for itself.

        THE CADENCE MATCHES `CRAFT_CYCLE_SECONDS` ON PURPOSE (300 by default,
        the clock `_assign_crafts` already runs on), so the mode decision and
        the errand refresh see the same world a poll apart rather than
        interleaving on unrelated clocks. Polling faster than the worldserver's
        own 900-second `PlayerSaveInterval` re-reads numbers that have not
        moved, which is harmless here only because the write gate is `changed`:
        three identical polls produce one order and then two no-ops.

        Staggered LAST, after `_craft_supply_loop`'s own 300-second settle. A
        vial trip that is already under way should get its pass in before this
        one considers moving the family off craft, so the two never race over
        the same cycle.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("CRAFT_RHYTHM_CYCLE_SECONDS", "300"))
        await asyncio.sleep(min(cycle, 330.0))
        while not self.is_closed():
            try:
                await self._craft_rhythm_once()
            except Exception:
                log.exception("craft_rhythm failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _settle_auction_errand(self, names: list, leader: str) -> str:
        """Is the auctioneer errand the leader already carries finished?

        THE SAME THREE-WORD STEP `_settle_vendor_errand` USES, and deliberately
        the same shape rather than a new one: infra#3708 established that an
        economy errand with no terminal path is a latch, infra#3717 built the
        release for `vendor`, and infra#3728 is the standing issue that the
        other keywords still have none. Adding a fifth aim without its release
        would be adding a fifth entry to that issue in the same change that
        needed the column, so the release ships with the aim.

        `bag_pressure.vendor_errand_step` IS REUSED RATHER THAN COPIED, because
        the question is identical once the two facts are supplied: "am I at the
        counter" and "does the world still owe me answers". Its name is about
        where it was born and not about what it decides - a second copy under a
        different name would be two things to keep in step for no behaviour
        difference, which is the drift infra#3712 exists to complain about.
        """
        at_counter = await asyncio.to_thread(_fetch_auctioneer, leader)
        outstanding = await asyncio.to_thread(_outstanding_auctions, names)
        step = bag_pressure.vendor_errand_step(bool(at_counter), outstanding)
        if step == bag_pressure.VENDOR_ERRAND_HOLD:
            log.info(
                "auction: leader=%s is standing at %s with %s purchase(s) "
                "unanswered, so the aim it carries is left exactly as it is",
                leader, (at_counter or {}).get("name") or "an auctioneer",
                "an unreadable number of" if outstanding < 0 else outstanding,
            )
        elif step == bag_pressure.VENDOR_ERRAND_RELEASE:
            # THE AIM IS FOR WALKING AND THIS CHARACTER HAS ARRIVED. It is
            # mod-overseer's COUNTER HOLD that keeps them at the auctioneer
            # while rows execute, not this column - and for `auctioneer` that
            # hold only started existing with mod-overseer#402, which is the
            # whole reason no auction row had ever found its character still
            # standing at the counter. An aim left on somebody already there
            # buys nothing and costs the quest drive everything.
            released = await asyncio.to_thread(
                _release_trade_errand, leader, auction.AUCTIONEER_ROLE,
            )
            if released:
                log.info(
                    "auction: leader=%s has answered every purchase the last "
                    "trip queued, so the errand is handed back", leader,
                )
            else:
                log.debug(
                    "auction: leader=%s is not carrying an auctioneer errand, "
                    "so there was nothing to hand back", leader,
                )
        return step

    async def _auction_once(self) -> None:
        """Buy the gathered reagents a standing craft errand needs (infra#3731).

        THE GAP THIS CLOSES, AND THE ONE IT DOES NOT. All five of the family
        hold a craft errand naming a reagent they have none of, and
        `DriveCraft` skips a character with no reagents silently.
        `craft_supply.py` already buys the reagents a VENDOR sells; none of
        these five is vendor-bought, which is why that module cannot answer it
        and this one exists. See auction.py's docstring for the reagent table
        (which is `craft_rhythm.GATHERED`, deliberately not a second copy), why
        a table exists at all rather than a query, and the price ceiling.

        IT RUNS ALONGSIDE THE GATHERING MODE RATHER THAN INSTEAD OF IT
        (infra#3734). `craft_rhythm` sends the family out to gather the moment
        any of them is short, and that is the right call - a character that
        gathers its own materials is the better steady state. This pass is what
        makes the trip cheaper: the same shortfall that starts a gathering
        rotation is a shortfall a few silver would close outright, and the two
        answers compose. Which is why the shopper list is read from
        `craft_spell` and NOT from `job`.

        IT BUYS AND IT DOES NOT FEED, and that is stated here as well as in the
        module because it is the thing a reader will otherwise assume. A bought
        auction arrives BY MAIL - `DoAuction` says so on its own success path -
        and `DriveCraft` reads the bags. Collecting needs a character at a
        mailbox, which on this world is a gameobject rather than a creature (no
        creature template carries UNIT_NPC_FLAG_MAILBOX at all), so it is a
        ground aim, a second counter and a second release: its own issue, not
        this pass. Until it lands this pass fills mailboxes.

        WHICH IS SAFE ONLY BECAUSE THE MAIL IS COUNTED. `auction.short_of`
        takes the carried count AND the mail count, so a reagent already bought
        and not yet collected is not bought again. Without that the shortfall
        would never fall and this pass would re-buy the same reagent every
        cycle until the house was empty or the purse was.

        THE HOUSE COMES FROM THE AUCTIONEER AND NOTHING IS PLANNED UNTIL THEY
        HAVE ARRIVED. The three auction houses are disjoint on this realm
        (`AllowTwoSide.Interaction.Auction = 0`) and `DoAuction` shops in
        exactly the one its auctioneer's faction serves, refusing every other
        id as `WrongHouse`. So the listings are not even read until somebody is
        standing at a counter, at which point the house is a fact rather than a
        guess - the same discipline `_towntrip_once` states, and the reason
        this pass holds no state and survives a restart.

        THE WALK IS THE LEADER'S AND THE PURCHASES ARE EVERYBODY'S, the shape
        `_craft_supply_once` settled on: a follower aimed at anything does not
        move (`AimedMover` answers `RefuseInFormation`; the family carries one
        `new rpg` and it is on the leader), while `DoAuction` acts for whoever
        `target_name` names, wherever that character is standing. So one aim,
        five shoppers.

        AND THE AIM IS THE KEYWORD, NOT A CREATURE ENTRY, which is the one
        place this deliberately differs from `_craft_supply_once`. That pass
        names an entry because "the nearest vendor" and "the nearest vendor
        that stocks it" are different questions. Here they are not: any
        auctioneer reaches a whole house. What a bare entry would cost is real
        and measured - `IsMaintenanceErrand` answers off `CounterRoleForAim`,
        which knows keywords only, so a numeric aim is released within a cycle
        and hand-aiming the leader at 8661 closed only 1,027 to 674 yards
        before being blanked. The keyword survives the cycle AND takes the
        counter hold that keeps them there while the rows run.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names or await self._mid_run(names):
            return

        # SETTLING THE LAST ERRAND COMES BEFORE DECIDING ON A NEW ONE AND ABOVE
        # EVERY GATE BELOW, which is infra#3717's ordering fix rather than
        # tidiness: an errand is only finished BECAUSE the buying worked, and a
        # release written below the gates would never fire on the cycles that
        # matter.
        leader = await asyncio.to_thread(_head_now)
        if not leader:
            log.info(
                "auction: nobody leads the family right now, and a follower "
                "aimed at an auctioneer does not walk, so this pass takes no "
                "trip"
            )
            return
        step = await self._settle_auction_errand(names, leader)
        await self._auction_sales_once(names, leader, step)

        # NOT `_fetch_craft_spells`, WHICH FILTERS job='craft' (infra#3734).
        # `craft_rhythm` moves the family to MODE_GATHER the moment any of
        # them is short, which is exactly when this pass has something to buy,
        # so gating on the crafting job would make this dark on every cycle
        # that mattered and green on every cycle with nothing to do.
        spells = await asyncio.to_thread(_fetch_standing_crafts, names)
        shoppers = {
            name: spell_id
            for name, (spell_id, _money) in spells.items()
            if spell_id in auction.GATHERED
        }
        if not shoppers:
            log.info("auction: nobody is on a craft errand this pass can supply")
            return

        # THE SHORTFALL IS ASKED BEFORE THE TRIP, because whether to WALK has
        # nothing to do with where anybody is standing: a family already
        # carrying twenty casts' worth needs no journey, and taking one would
        # be a walk with nothing at the end of it. Same separation
        # `craft_supply.reagent_need` draws from `reagent_errand`.
        entries, needs = await self._auction_shortfall(shoppers)
        if not needs:
            log.info(
                "auction: every craft errand is stocked for %d casts, so no "
                "trip is taken", auction.CASTS_PER_TRIP,
            )
            return

        # ResolveTravelTarget can only search auctioneer spawns on the
        # leader's current map. Do not keep re-arming an aim that the module
        # must release when the map has no auctioneer at all.
        live_maps = await asyncio.to_thread(_fetch_live_maps, [leader])
        auctioneer_maps = await asyncio.to_thread(_fetch_auctioneer_maps)
        leader_map = live_maps.get(leader) if live_maps is not None else None
        if (live_maps is not None and leader_map is None) or (
            auctioneer_maps is not None and
            not auction.auctioneer_map_available(leader_map, auctioneer_maps)
        ):
            if step != bag_pressure.VENDOR_ERRAND_RELEASE:
                await asyncio.to_thread(
                    _release_trade_errand, leader, auction.AUCTIONEER_ROLE,
                )
            log.info(
                "auction: no auctioneer spawn is available on leader=%s map=%s; "
                "skipping the trip instead of re-arming a doomed aim",
                leader, leader_map if leader_map is not None else "unknown",
            )
            return

        # THE AIM, AND ITS RESULT IS READ RATHER THAN DISCARDED (infra#3464).
        # A leader already carrying another economy errand is a real and
        # expected refusal - ECONOMY_ERRANDS only retasks an idle traveller -
        # and until the guild bank pass logged the same return that starvation
        # was invisible (infra#3663).
        aimed = True
        if step == bag_pressure.VENDOR_ERRAND_AIM:
            # THROUGH THE TOWN SLOT (infra#3703). The line this used to write
            # here said the pass was "starved until that one clears" and had no
            # way of knowing whether that would ever happen; the slot answers
            # the same refusal with how long the holder has had the column, how
            # much of its lease is left, and who is ahead in the queue.
            aimed = await self._claim_town_slot(
                "auction", leader, auction.AUCTIONEER_ROLE)
            if not aimed:
                log.info(
                    "auction: leader=%s could not be aimed at an auctioneer "
                    "this pass, so nothing is bought until the town slot comes "
                    "round to it", leader,
                )

        # NOTHING IS BOUGHT UNTIL SOMEBODY IS AT A COUNTER, and which counter
        # decides which house. Asked per shopper rather than of the leader
        # because `DoAuction` runs for the buyer and looks for an auctioneer
        # near THAT character - the same per-holder reading `_vendor_once`
        # already does - so a straggler who has not arrived simply buys nothing
        # this cycle instead of queueing a row that can only be refused.
        teams = await asyncio.to_thread(_fetch_teams, list(shoppers))
        seen = await asyncio.to_thread(_recent_auction_keys, GIVE_RETRY_MINUTES)
        free_slots = await asyncio.to_thread(_fetch_free_slots, list(shoppers))
        queued = 0
        spent = 0
        for name in sorted(shoppers):
            mine = [need for need in needs if need.shopper == name]
            if not mine:
                continue
            rows, cost = await self._shop_for(
                name, mine, entries, teams.get(name, ""),
                purse=spells[name][1],
                slots=free_slots.get(name, 0),
                seen=seen,
            )
            queued += rows
            spent += cost

        log.info(
            "auction: queued %d purchase(s) worth %d copper across %d "
            "shopper(s), leader=%s aimed=%s. Bought reagents arrive by MAIL "
            "and are not craftable until a mailbox pass collects them.",
            queued, spent, len(shoppers), leader, aimed,
        )

    async def _auction_sales_once(self, names: list, leader: str,
                                  step: str) -> None:
        """List safe surplus BoE gear at the leader's reachable house.

        `auction.plan_sales` owns the sale judgement. This adapter only reads
        facts, supplies current market prices, and queues its returned rows.
        """
        gear_rows = await asyncio.to_thread(_fetch_surplus_gear, names)
        if not gear_rows:
            return
        equipped = await asyncio.to_thread(_fetch_family_equipped, names)
        fits = bag_pressure.family_fits(gear_rows, equipped, names)
        candidates = []
        entries = set()
        for row in gear_rows:
            try:
                guid = int(row["item_guid"])
                if fits.get(guid) != disposition.FIT_NOBODY:
                    continue
                if bag_pressure.item_binding(row) != disposition.BIND_ON_EQUIP:
                    continue
                entry = int(row["entry"])
                entries.add(entry)
                candidates.append({
                    "holder": row["holder"], "item_guid": guid,
                    "entry": entry, "label": row.get("name", ""),
                    "quality": int(row.get("quality", 0) or 0),
                    "binding": disposition.BIND_ON_EQUIP,
                    "quest_item": False,
                    "sell_price": int(row.get("sell_price", 0) or 0),
                })
            except (KeyError, TypeError, ValueError):
                continue
        if not candidates:
            return
        counter = await asyncio.to_thread(_fetch_auctioneer, leader)
        if not counter:
            if step == bag_pressure.VENDOR_ERRAND_AIM and await self._claim_town_slot(
                    "auction", leader, auction.AUCTIONEER_ROLE):
                log.info("auction: leader=%s aimed to list %d surplus BoE item(s)",
                         leader, len(candidates))
            return
        teams = await asyncio.to_thread(_fetch_teams, [leader])
        house = auction.reachable_house(
            teams.get(leader, ""), int(counter.get("faction") or 0))
        if not house:
            log.warning("auction: no reachable house for leader=%s", leader)
            return
        listings = await asyncio.to_thread(
            _fetch_auction_listings, sorted(entries), house)
        market = {}
        for listing in listings:
            market[listing.entry] = min(
                market.get(listing.entry, listing.per_unit), listing.per_unit)
        for candidate in candidates:
            candidate["market_price"] = market.get(candidate["entry"], 0)
        sales = auction.plan_sales(candidates)
        seen = await asyncio.to_thread(_recent_auction_keys, GIVE_RETRY_MINUTES)
        queued = 0
        for sale in sales:
            if (sale.candidate.holder, sale.command) in seen:
                continue
            if await asyncio.to_thread(_insert_auction,
                                       sale.candidate.holder, sale.command):
                queued += 1
                log.info("auction: %s %s - %s", sale.candidate.holder,
                         sale.command, sale.candidate.label or "surplus BoE")
        if queued:
            # Keep the leader at the counter while the world executor answers
            # the listing rows. A completed purchase can release the old aim
            # before this pass discovers a new sale, so reassert the same
            # guarded keyword whenever work was actually queued.
            await asyncio.to_thread(
                _write_trade_errand,
                professions.Errand(character=leader,
                                   travel_npc=auction.AUCTIONEER_ROLE),
            )
        log.info("auction: listed %d surplus BoE item(s) at house %s",
                 queued, house)

    async def _auction_shortfall(self, shoppers: dict) -> tuple:
        """Who is short of what, counting the bags and the mail separately.

        Returns `(entries, needs)` - the distinct item entries worth reading
        the house for, and one `auction.Need` per (character, reagent)
        shortfall.

        THE TWO READS MEAN TWO DIFFERENT THINGS AND THAT IS THE POINT. The
        carried count comes through `character_inventory`, which is what
        `DriveCraft` can actually cast with; the mail count comes through
        `mail`/`mail_items`, which is what has been bought and not yet
        collected. `auction.short_of` adds them, because a reagent already on
        its way must not be bought twice - without that the shortfall never
        falls and the pass re-buys every cycle for ever - but they are never
        read by one query, because an `item_instance.owner_guid` count that
        quietly means both over-counts on three separate measured grounds.

        BATCHED ACROSS THE FAMILY, not one query per character: two round
        trips total, whatever the roster size, the same batching discipline
        `_fetch_item_counts` and `_fetch_free_slots` already hold to.
        """
        entries = sorted({
            reagent.entry
            for spell_id in shoppers.values()
            for reagent in auction.GATHERED[spell_id]
        })
        names = list(shoppers)
        carried = await asyncio.to_thread(
            _fetch_counts, _CARRIED_COUNTS_SQL, names, entries, "bags",
        )
        in_mail = await asyncio.to_thread(
            _fetch_counts, _MAIL_COUNTS_SQL, names, entries, "the mail",
        )
        needs: list = []
        for name, spell_id in sorted(shoppers.items()):
            short = auction.wanted(
                spell_id,
                {e: carried.get((name, e), 0) for e in entries},
                {e: in_mail.get((name, e), 0) for e in entries},
            )
            needs.extend(
                auction.Need(shopper=name, entry=need.entry,
                             label=need.label, short=need.short)
                for need in short
            )
        return entries, needs

    async def _shop_for(self, name: str, needs: list, entries: list,
                        team: str, purse: int, slots: int, seen: set) -> tuple:
        """Buy one character's outstanding reagents where it is standing.

        LIFTED OUT OF `_auction_once` FOR THE REASON infra#3717 ALREADY
        RECORDED FOR `_settle_vendor_errand`: the complexity number is the same
        fact as "one question with one answer belongs in one place", stated as
        a measurement. The pass above decides WHO is short and walks the family;
        this decides what ONE character takes from the counter it has actually
        reached, which is a different question with a different set of ways to
        answer "nothing".

        Returns `(rows queued, copper committed)` so the caller can total a
        pass without re-deriving either.

        EVERY EXIT IS A SENTENCE. A character still walking, a counter whose
        house cannot be named, an empty market - all of them are ordinary and
        all of them get logged, because the failure this whole family of passes
        keeps re-learning is the silent one: a pass that does nothing and says
        nothing looks exactly like a pass that is working.
        """
        counter = await asyncio.to_thread(_fetch_auctioneer, name)
        if not counter:
            log.info(
                "auction: %s is not standing at an auctioneer yet, so nothing "
                "is bought for it this cycle", name,
            )
            return 0, 0

        house = auction.reachable_house(team, int(counter.get("faction") or 0))
        if not house:
            # NOT A GUESS AND NOT A ROW. `DoAuction` picks the pool from the
            # auctioneer's faction and refuses everything else as `WrongHouse`,
            # so a house this side cannot name is a house it must not shop in.
            log.warning(
                "auction: %s is at %s (faction %s) but this pass cannot say "
                "which auction house that serves, so it buys nothing rather "
                "than queueing rows that would be refused as the wrong house",
                name, counter.get("name") or "an auctioneer",
                counter.get("faction"),
            )
            return 0, 0

        listings = await asyncio.to_thread(_fetch_auction_listings, entries, house)
        buys, notes = auction.plan_buys(
            needs, listings, house, {name: purse}, free_slots={name: slots},
        )
        for note in notes:
            log.info("auction: %s", note)

        queued = 0
        spent = 0
        for buy in buys:
            if (buy.shopper, buy.command) in seen:
                continue
            if await asyncio.to_thread(_insert_auction, buy.shopper, buy.command):
                queued += 1
                spent += buy.spend
                log.info("auction: %s %s - %s",
                         buy.shopper, buy.command, buy.why)
        return queued, spent

    async def _auction_loop(self) -> None:
        """Own loop and own clock, the same reasoning _craft_supply_loop gives.

        Staggered LAST, past _vendor_loop (90s), _bank_loop (150s),
        _guild_bank_loop (240s) and _craft_supply_loop (300s), every one of
        which also writes `travel_npc` through the same ECONOMY_ERRANDS guard.
        Last because this is the pass with the least urgent errand: a bag at
        100 per cent stops the family looting now, while a reagent they have
        been short of for a day keeps perfectly well for another ten minutes.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("AUCTION_CYCLE_SECONDS", "600"))
        await asyncio.sleep(min(cycle, 360.0))
        while not self.is_closed():
            try:
                await self._auction_once()
            except Exception:
                log.exception("auction pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _recipebook_once(self) -> None:
        """Learn the recipes already in the bags, and buy one that is in reach.

        TWO HALVES, AND THE FIRST ONE COSTS NOTHING. A class-9 item - a Pattern,
        Formula, Manual, Recipe, Plans, Schematic or Design - teaches its recipe
        when it is USED, and the family loots them constantly and opens none.
        Measured 2026-09-14: 43 unlearned class-9 items across the five of them
        (18, 13, 5, 5 and 2), and none of them usable yet - see recipebook's own
        header for why that is the finding and not a disappointment.
        That half needs no counter, no walk and no gold, so it runs first and
        unconditionally.

        THE SECOND HALF ONLY RUNS WHERE SOMEBODY ALREADY IS. This pass writes no
        `travel_npc` and claims no town slot: `_auction_once` already walks the
        family to an auctioneer on its own clock, and a second writer of that
        column is the collision infra#3712 records. So a recipe is bought when a
        character happens to be standing at a counter, which costs a cycle of
        latency and no new machinery at all.

        NOTHING HERE DECIDES ANYTHING. recipebook.py holds the reachability
        rule, the ordering and the caps; this reads rows and writes rows.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names or await self._mid_run(names):
            return

        skills = await asyncio.to_thread(_fetch_recipe_skills, names)
        verdicts = await asyncio.to_thread(_fetch_recipe_verdicts)
        settled = recipebook.settled_from_rows(verdicts)
        seen = await asyncio.to_thread(_recent_recipe_keys, GIVE_RETRY_MINUTES)

        held = await asyncio.to_thread(_fetch_held_recipes, names)
        learns, skipped = recipebook.plan_learns(held, skills, settled, seen)

        queued = 0
        for learn in learns:
            if await asyncio.to_thread(_insert_learn, learn.holder, learn.command):
                queued += 1
                log.info("recipebook: %s %s - %s (%s)",
                         learn.holder, learn.command, learn.label, learn.why)

        # ---- and the shopping, for whoever is at a counter right now ---------
        counters = {}
        for name in names:
            found = await asyncio.to_thread(_fetch_auctioneer, name)
            if found:
                counters[name] = found
        purchases: list = []
        if counters:
            teams = await asyncio.to_thread(_fetch_teams, list(counters))
            houses = {
                name: auction.reachable_house(teams.get(name, ""),
                                              int(counters[name].get("faction") or 0))
                for name in counters
            }
            listings = await asyncio.to_thread(
                _fetch_recipe_listings, list(houses.values()))
            # `_fetch_guild_money` REUSED FOR ITS PURSE, and the name is the
            # only awkward thing about it: it reads `characters.money` for a
            # list of names and happens to carry a guild flag this pass ignores.
            # A second near-identical reader is the duplication this codebase
            # keeps paying for, and `characters.money` LAGS either way - which
            # is safe in this direction, because DoAuction checks the purse
            # itself and refuses rather than overdrawing.
            purses = {
                row["name"]: int(row["money"] or 0)
                for row in await asyncio.to_thread(_fetch_guild_money, list(counters))
            }
            slots = await asyncio.to_thread(_fetch_free_slots, list(counters))
            # WHAT THEY ALREADY HAVE, from the SAME read the learning half used
            # rather than a second query: a recipe teaches once and is destroyed
            # doing it, so buying one that is already in the bag is gold for
            # nothing - and the overlap is the normal case, because the reason a
            # character is holding an unlearned Pattern is that the trade is not
            # high enough yet, and the moment it is, this pass would find the
            # same recipe on the house.
            carried = {(item.holder, int(item.entry)) for item in held}
            purchases, shop_skipped = recipebook.plan_purchases(
                list(counters), listings, skills, houses, purses, slots,
                settled, seen, carried)
            skipped = list(skipped) + list(shop_skipped)
            for buy in purchases:
                if await asyncio.to_thread(_insert_recipe_buy, buy.shopper, buy.command):
                    queued += 1
                    log.info("recipebook: %s %s - %s for %d copper (%s)",
                             buy.shopper, buy.command, buy.label, buy.spend,
                             buy.why)

        log.info("%s", recipebook.report(learns, purchases, skipped))

    async def _recipebook_loop(self) -> None:
        """Own loop and own clock, the same reasoning _auction_loop gives.

        Staggered past the auction pass rather than before it, because the
        shopping half only acts on a character already standing at an
        auctioneer and that pass is what puts one there. The learning half needs
        no counter at all, so an early cycle is not wasted either way.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("RECIPEBOOK_CYCLE_SECONDS", "600"))
        await asyncio.sleep(min(cycle, 420.0))
        while not self.is_closed():
            try:
                await self._recipebook_once()
            except Exception:
                log.exception("recipebook pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

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
                # `_head_now()` INSIDE THE THREAD, not evaluated on the loop
                # and handed in as an argument. It asks three borrowers and
                # every one of them reads the database; written the other way
                # those reads happen on the event loop, which this file's own
                # docstring forbids, and infra#3686 added the third borrower
                # that made it worth correcting rather than merely noting.
                await asyncio.to_thread(lambda: _mark_party_leader(_head_now()))

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

                # ...and the family's learn errands are reconciled in the same
                # pass: one that is already over comes off the roster, and one
                # that nobody is walking gets the journey it was missing.
                # Leaving either alone is not merely untidy - mod-overseer
                # refuses EVERY travel aim for a character whose `learn_skill`
                # is set, and the only thing that clears it inside the
                # worldserver is arriving at a trainer, which needs a travel
                # aim. Written here rather than earlier because it reads both
                # the `professions` permission and the `lead` column that the
                # two steps above have just written (infra#3686).
                await self._reconcile_learn_aims()

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
        live_maps = await asyncio.to_thread(_fetch_live_maps, names)
        if not chat.run_has_present_member(run, live_maps):
            log.info(
                "run: ignoring stale active row %s because no named member "
                "has a fresh snapshot on map %s",
                run.get("id", "unknown"), run.get("map_id", "unknown"),
            )
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

    async def _guild_share_once(self) -> None:
        """One pass of infra#3908: family surplus goes out to the guild.

        THE MIRROR OF _move_materials_once, AND THE ORDER IS THE SAME: fetch,
        decide in the pure module, write the command, and only then speak. A
        gift that could not be written - already queued inside the retry
        window, or refused enough times to be believed - has nothing to
        announce.

        IT RUNS AFTER THE FAMILY'S OWN REAGENTS HAVE MOVED, not before, and
        that ordering is the whole safety argument. `_move_materials_once`
        gathers the family's cloth into the tailor's bags; this pass then asks
        what is left over after the family's own twelve-cast reserve. Reversed,
        the guild would be offered stock the family had not yet collected and
        `craft_rhythm` would read the family as short a cycle later.

        MID-RUN IS A WAIT, NOT A SKIP TO BE FIXED - the same judgement
        `_move_materials_once` records for itself. The surplus will still be
        surplus when the run ends, and a family that stops a boss pull to hand
        a guildmate some cloth is not reading the room.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names:
            return
        if await self._mid_run(names):
            log.info("guildshare: the family is in a dungeon run - "
                     "the surplus waits")
            return

        roster = await asyncio.to_thread(_fetch_guild_roster, names)
        if len(roster) <= len(names):
            # Not an error and not worth a warning every ten minutes: the
            # family is in no guild, or in one with nobody else in it. This
            # pass has nothing to do and says so once per cycle at info.
            log.info("guildshare: no guildmates outside the family")
            return

        holdings = await asyncio.to_thread(_fetch_guild_surplus, names)
        crafts = await asyncio.to_thread(_fetch_standing_crafts, names)
        spells = tuple(sorted({
            int(spell or 0) for spell, _money in crafts.values() if spell
        }))
        refused = materials.stuck(
            await asyncio.to_thread(_give_attempts, GIVE_GIVE_UP_HOURS)
        )
        share = await asyncio.to_thread(
            guildshare.plan, holdings, roster,
            craft_spells=spells, stuck_pairs=refused,
        )
        log.info("guildshare: %s", guildshare.headline(share))
        for note in share.notes:
            log.info("guildshare: %s", note)
        for holder, taker, refusal in share.blocked:
            log.info("guildshare: %s stopped asking %s - %s",
                     holder, taker, refusal)
        await self._guild_gear_share_once(names, roster)
        if not share.gifts:
            return

        seen = await asyncio.to_thread(
            _recent_guild_gift_keys, GIVE_RETRY_MINUTES
        )
        fresh = []
        for gift in share.gifts:
            if (gift.holder, gift.taker, gift.command) in seen:
                continue
            if await asyncio.to_thread(_insert_guild_gift, gift):
                fresh.append(gift)
        if not fresh:
            log.info("guildshare: %d gift(s) already queued or refused",
                     len(share.gifts))
            return

        for gift in fresh:
            log.info("guildshare: %s -> %s, %d %s - %s",
                     gift.holder, gift.taker, gift.count, gift.item,
                     gift.reason)
            await self._say_guild_gift(gift)

    async def _guild_gear_share_once(self, family_names: list,
                                     roster: list) -> None:
        """Offer unclaimed family BoE upgrades to online guildmates.

        SQL remains a fact fetch. `bag_pressure.guild_gear_gifts_from_rows`
        owns family-first recipient priority, class/slot eligibility, and the
        observed presence and room gates. This pass deliberately shares only
        the guild half of that result; `_hand_gear` remains the sole family
        gear writer.
        """
        gear_rows = await asyncio.to_thread(
            _fetch_surplus_gear, family_names,
        )
        if not gear_rows:
            return
        all_names = [str(member.name) for member in roster]
        equipped = await asyncio.to_thread(_fetch_family_equipped, all_names)
        positions = await asyncio.to_thread(_fetch_positions, all_names)
        free_slots = await asyncio.to_thread(_fetch_free_slots, all_names)
        plan = bag_pressure.guild_gear_gifts_from_rows(
            gear_rows, equipped, family_names, roster,
            position_rows=positions, free_slots=free_slots,
        )
        for note in plan.notes:
            log.info("guild gear: %s", note)
        if not plan.grants:
            return
        seen = await asyncio.to_thread(_recent_trade_keys, GIVE_RETRY_MINUTES)
        fresh = []
        for grant in plan.grants:
            if (grant.holder, grant.taker, grant.command) in seen:
                continue
            if await asyncio.to_thread(_insert_gear_handoff, grant):
                fresh.append(grant)
        for grant in fresh:
            log.info("guild gear: %s -> %s by %s, %s - %s",
                     grant.holder, grant.taker, grant.verb, grant.name,
                     grant.reason)
        log.info("guild gear: queued %d/%d hand-off(s), %d already queued",
                 len(fresh), len(plan.grants), len(plan.grants) - len(fresh))

    async def _say_guild_gift(self, gift) -> None:
        """Say it in guild chat, because the guild is who it is addressed to.

        `materials.py` speaks its hand-offs in PARTY, which is right for five
        characters standing together and wrong here: the receiver is a
        guildmate who is, measured live, usually on another continent and
        never in the party. A line nobody in earshot can act on is not
        legibility, it is noise in the family's own channel.
        """
        await asyncio.to_thread(
            _insert_speak,
            relay.SpeakCommand(gift.holder, "guild", gift.said, "",
                               "overseer:guildshare"),
        )

    async def _guild_share_loop(self) -> None:
        """Own loop and own clock, the same reasoning _move_materials_loop
        gives for itself.

        Staggered to 420s, which puts it behind every pass that writes
        `overseer_roster.travel_npc` (vendor 90, bank 150, guild bank 240,
        craft supply 300) even though this one writes none of them. It is
        behind `_move_materials_loop` (90) on purpose and for a reason that
        is not about column contention at all: the family's own reagents must
        be gathered into the right bags before what is left over can honestly
        be called spare.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("GUILD_SHARE_CYCLE_SECONDS", "600"))
        await asyncio.sleep(min(cycle, 420.0))
        while not self.is_closed():
            try:
                await self._guild_share_once()
            except Exception:
                log.exception("guildshare pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _settle_vendor_errand(self, names: list, leader: str) -> str:
        """Is the vendor errand the leader already carries finished? (infra#3708)

        LIFTED OUT WHOLE, AND THE REASON IS A BUG RATHER THAN A METRIC. A draft
        of this change put the release at the BOTTOM of `_vendor_once`, below
        three early returns, where it could never fire on the cycles that matter
        - an errand is only finished BECAUSE the selling worked, and selling
        empties the bags, so the cycle that should hand the column back is the
        cycle `family_town_run_needed` returns False. That is a control-flow bug
        in a function whose control flow had grown past the point anybody could
        hold it, and the complexity number grug-tribe flagged is the same fact
        stated as a measurement. One question with one answer belongs in one
        place, which is the shape `bag_pressure.vendor_errand_step` already has
        on the pure side.

        SO THIS RUNS ABOVE EVERY GATE IN THE PASS, DELIBERATELY. Ending an old
        errand and deciding on a new trip are different questions; nothing about
        a quiet bag makes a standing errand less finished.

        IT SETTLES ONLY `vendor`, AND ONLY THIS PASS'S OWN. `travel_npc` is a
        single slot four passes write, and each of them must hand back what it
        wrote: releasing the town trip's `repair` from here would be exactly the
        cross-pass theft `_write_trade_errand`'s guard exists to prevent
        (mod-overseer#438). The other three are latched the same way this one
        was and are filed separately - measured 2026-09-13, the leader re-armed
        as `repair` about five minutes after the column was cleared by hand.
        """
        leader_town = await asyncio.to_thread(_fetch_town, leader)
        outstanding = await asyncio.to_thread(_outstanding_sales, names)
        free_slots = await asyncio.to_thread(_fetch_free_slots, names)
        pressure = bag_pressure.family_town_run_needed(free_slots)
        current_aim = await asyncio.to_thread(_current_travel_npc, leader)
        stall = None
        if current_aim == "vendor":
            observed = await asyncio.to_thread(_fetch_vendor_position, leader)
            stall = vendor_stall.progress(
                self._vendor_movement.get(leader), observed, time.monotonic(),
            )
            if stall.current is not None:
                self._vendor_movement[leader] = stall.current
            family_stall = vendor_stall.family_progress(
                self._vendor_family_movement,
                await asyncio.to_thread(_fetch_positions, names),
                tuple(names),
                time.monotonic(),
            )
            if family_stall.current is not None:
                self._vendor_family_movement = family_stall.current
            decision = vendor_stall.decide(
                pressure=pressure,
                at_counter=bool(leader_town.vendor),
                sales_outstanding=outstanding,
                movement_readable=stall.readable,
                movement_progressed=stall.progressed,
                stalled_seconds=stall.stalled_seconds,
                family_readable=family_stall.readable,
                family_split=family_stall.split,
                family_progressed=family_stall.progressed,
                family_split_seconds=family_stall.split_seconds,
            )
            if decision.action == vendor_stall.RELEASE:
                released = await asyncio.to_thread(
                    _release_trade_errand, leader, "vendor",
                )
                if released:
                    log.warning(
                        "economy: vendor aim recovered after stalled movement; "
                        "leader=%s stall_seconds=%d free_slots=%s reason=%s",
                        leader, int(stall.stalled_seconds),
                        sorted((str(name), int(slots))
                               for name, slots in free_slots.items()),
                        decision.reason,
                    )
                    self._vendor_movement.pop(leader, None)
                    self._vendor_family_movement = None
                    return bag_pressure.VENDOR_ERRAND_RELEASE
        step = bag_pressure.vendor_errand_step(
            bool(leader_town.vendor), outstanding,
            pressure=pressure,
        )
        if (step == bag_pressure.VENDOR_ERRAND_HOLD
                and outstanding == 0
                and bag_pressure.family_town_run_needed(free_slots)):
            # This is deliberately a warning rather than a release. A quiet
            # queue can mean the holder rows have not reached the counter yet;
            # releasing here would send the family away with the same full
            # bags. The snapshot makes the actionable failure visible: the
            # family is under pressure at a counter, but the executor has no
            # sell work in flight.
            log.warning(
                "economy: vendor aim held with bag pressure but no sell rows "
                "outstanding; leader=%s counter=%s free_slots=%s pressure=%s",
                leader, bool(leader_town.vendor),
                sorted((str(name), int(slots))
                       for name, slots in free_slots.items()),
                True,
            )
        if step == bag_pressure.VENDOR_ERRAND_HOLD:
            log.info(
                "economy: leader=%s is already standing at a vendor with %s "
                "sale(s) unanswered, so the aim it carries is left exactly as "
                "it is - re-asserting one is what makes the world read a "
                "standing errand as a new one", leader,
                "an unreadable number of" if outstanding < 0 else outstanding,
            )
        elif step == bag_pressure.VENDOR_ERRAND_RELEASE:
            # THE AIM IS FOR WALKING, AND THIS CHARACTER HAS ARRIVED. It is the
            # module's COUNTER HOLD that keeps it at the merchant while rows
            # execute, not the column - mod-overseer takes that hold and
            # releases the errand in the same breath, and says why: "the
            # release IS the signal ... a character not already pinned by then
            # has an AI tick in which to roll RPG_IDLE into something that
            # walks". So an aim left on a character already standing at the
            # counter buys nothing and costs the quest drive everything.
            released = await asyncio.to_thread(
                _release_trade_errand, leader, "vendor",
            )
            if released:
                log.info(
                    "economy: leader=%s has answered every sale the last vendor "
                    "trip queued, so the errand is handed back and the family "
                    "walks again", leader,
                )
            else:
                # Not a failure. The column belongs to somebody else now - a
                # profession errand, or another town pass that won it - and the
                # keyword guard is what stops this pass taking it from them.
                log.debug(
                    "economy: leader=%s is not carrying a vendor errand, so "
                    "there was nothing to hand back", leader,
                )
        return step

    async def _release_stranded_vendor_errands(self, names: list,
                                               leader: str) -> int:
        """Hand back a `vendor` aim that is standing on somebody who is not the
        leader (infra#3746). Returns how many were released.

        THE HALF infra#3717 COULD NOT REACH. `_settle_vendor_errand` above
        settles the errand `_head_now()` carries and nothing else, and
        `_release_trade_errand`'s UPDATE is `WHERE name = %s AND travel_npc = %s`
        - so an aim on any OTHER row is released by nobody, because nobody ever
        names it. Measured on wow-dev 2026-09-13 20:20 with infra#3717 deployed:
        `Bork | lead=0 | job=craft | travel_npc=vendor` while Grug led, and at
        20:45 it was unchanged.

        HOW A FOLLOWER ENDS UP CARRYING ONE, AND WHY IT IS NOT A ONE-OFF. Before
        infra#3553 the sell pass wrote `travel_npc = 'vendor'` once per HOLDER
        rather than once per leader, so every follower with something sellable
        was aimed; that write was fixed and the rows it had already left behind
        were not. The same state is reachable today without any old row: the
        errand is written to whoever led at the time, and `overseer_roster.lead`
        moving while an aim stands leaves the previous leader holding a column
        the next pass asks a different name to hand back. A sweep, not a
        migration, because the second cause has no last occurrence.

        IT IS NOT INERT WHILE IT STANDS. `_aimed_names` is
        `drive_quest <> 0 OR travel_npc <> ''`, `_give_them_a_life` hands every
        aimed character `nc +new rpg`, and mod-overseer's `CanBeSentToNpc` is
        exactly `HasStrategy("new rpg")` - so `TravelHoldsTheWheel` makes itself
        true off the stale column and that follower's quest drive stands down
        for ever. It is also billed `ERRAND_BUDGET_POLL_SECONDS` on every travel
        poll for as long as it holds a maintenance errand, unless `job='craft'`
        exempts it - and the live row was `job='quest'` by 20:45, so the exempt
        case is not the steady one.

        THE LEADER IS EXCLUDED, AND THAT EXCLUSION IS LOAD-BEARING RATHER THAN
        TIDY. The two completion predicates are genuinely different, and running
        this one over the leader would break the working half of infra#3717: a
        leader that has been AIMED and is still walking has no rows queued yet,
        because rows are only written for a holder already in reach of a
        counter - so its own queue reads 0, this rule would say "release", and
        the journey would be cancelled on the cycle it was ordered. The leader's
        errand ends on arrival plus a quiet queue and is settled above; a
        follower's aim walks nobody (`AimedMover::RefuseInFormation`, and
        `_head_now` never borrows the lead for an economy errand), so it has no
        journey to cancel and arrival cannot be asked about.

        AND WITHOUT A LEADER IT DOES NOTHING AT ALL. "Stranded" is defined
        against `_head_now()`; with no answer to that there is no way to tell
        the one character that can walk from the four that cannot, and every
        standing aim would be swept including the live one. A cycle that cannot
        name the leader gives nothing back, which costs 90 seconds.

        ONE QUEUE READ PER CHARACTER, NOT ONE FOR THE SET. The leader's half
        asks `_outstanding_sales(names)` about the whole family on purpose - the
        family walks as one, so the leader must stand at the counter while any
        holder's rows execute. A stranded aim is the opposite shape by
        construction: it is on one row and moves one character nowhere, so
        holding it open because a SIBLING still has rows outstanding would latch
        it on exactly the realm state this defect was found in.
        """
        if not leader:
            log.info(
                "economy: no character can be named as the family leader this "
                "pass, so no vendor errand is treated as stranded"
            )
            return 0
        holders = await asyncio.to_thread(_errand_holders, "vendor", names)
        stranded = [name for name in holders if name != leader]
        if not stranded:
            return 0
        released = 0
        for name in stranded:
            # THIS CHARACTER'S OWN QUEUE, NOT THE FAMILY'S. See the docstring:
            # a sibling's unanswered rows say nothing about whether this row's
            # errand has work left, and reading them would re-latch the column.
            outstanding = await asyncio.to_thread(_outstanding_sales, [name])
            step = bag_pressure.stranded_errand_step(outstanding)
            if step != bag_pressure.VENDOR_ERRAND_RELEASE:
                log.info(
                    "economy: %s carries a vendor errand nobody is walking, but "
                    "%s sale(s) of its own are still unanswered, so it is left "
                    "exactly as it is - an errand is given back when its work is "
                    "done and never because it looks stale", name,
                    "an unreadable number of" if outstanding < 0 else outstanding,
                )
                continue
            # THE KEYWORD IS NAMED AGAIN HERE, and it is the same word the aim
            # was written with. `_release_trade_errand` puts it in the WHERE
            # clause and refuses anything outside ECONOMY_ERRANDS, so this
            # cannot blank a profession errand however wrong the read above was
            # (mod-overseer#438), and it cannot take the town trip's `repair` or
            # the bank pass's `banker` either - each pass hands back what it
            # wrote.
            if await asyncio.to_thread(_release_trade_errand, name, "vendor"):
                released += 1
                log.info(
                    "economy: %s was carrying a vendor errand with nothing left "
                    "to sell and is not the leader=%s anybody is walking, so the "
                    "column is handed back and its quest drive is free again",
                    name, leader,
                )
            else:
                # Not a failure, and the same reading the leader's half gives:
                # the column changed hands between the SELECT and the UPDATE,
                # and the keyword guard is what stopped this pass taking
                # somebody else's errand off them.
                log.debug(
                    "economy: %s's vendor errand was gone by the time it was "
                    "handed back, so nothing was written", name,
                )
        return released

    async def _release_stranded_ground_errands(self, names: list,
                                               leader: str) -> int:
        """Release stale positional economy aims left on non-leaders.

        A positional town aim is valid for the leader, but a follower cannot
        execute it: mod-overseer deliberately refuses to steer followers and
        leaves their non-empty aim in place. This sweep is only used outside an
        active dungeon run, so it cannot erase a party staging escort.
        """
        aims = await asyncio.to_thread(_standing_travel_aims)
        stranded = townslot.stranded_nonleader_aims(
            aims, leader, ground=travel.is_ground_aim, releasable=_is_economy_aim,
        )
        released = 0
        for name in stranded:
            aim = aims.get(name, "")
            if await asyncio.to_thread(_release_trade_errand, name, aim):
                released += 1
                log.warning(
                    "economy: released stale ground aim %s from non-leader %s; "
                    "only %s can walk the family's town errands",
                    aim, name, leader,
                )
        return released

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
        if not names:
            return

        # SETTLING THE LAST ERRAND COMES BEFORE DECIDING ON A NEW ONE, AND
        # ABOVE EVERY GATE BELOW (infra#3708, infra#3703's option 2).
        #
        # THE ORDER IS THE FIX, NOT TIDINESS. A first draft put the release at
        # the BOTTOM of the pass, which reads naturally and rebuilt the same
        # latch one step along: an errand is only ever finished BECAUSE the
        # selling worked, and selling empties the bags, so the very cycle that
        # would hand the column back is the cycle `family_town_run_needed`
        # returns False and the cycle `candidates` is empty. Every exit between
        # here and there is one a finished errand would be abandoned on, and a
        # family that sold everything would be parked for having succeeded.
        # Measured after infra#3714 freed Og's bags, that is now most cycles.
        #
        # ENDING AN OLD ERRAND AND STARTING A NEW ONE ARE DIFFERENT QUESTIONS.
        # The gates below decide whether the family should make a trip; this
        # decides whether the trip it already made is over. Nothing about a
        # quiet bag makes a standing errand less finished.
        #
        # `_head_now()` rather than bonds.head_of_family(), for the reason
        # `_drive_train` gives: it names the character that can actually walk.
        # Read once and used for both halves, because releasing an errand from
        # one leader and aiming another would be two leaders.
        leader = await asyncio.to_thread(_head_now)
        step = await self._settle_vendor_errand(names, leader)
        # AND THE SAME SETTLING FOR EVERY OTHER ROW CARRYING THIS PASS'S OWN
        # KEYWORD (infra#3746). The line above hands back the errand the LEADER
        # is walking; this one hands back a `vendor` aim that ended up on
        # somebody who is not walking anywhere, which nothing in this process
        # ever named and so nothing could clear.
        #
        # IT IS ABOVE THE GATES FOR A SHARPER REASON THAN THE SETTLING IS, and
        # the realm measured the difference. A stranded aim's completion signal
        # is its own sell queue going quiet - and a quiet queue is precisely the
        # state in which this pass has nothing to sell and returns early. On
        # wow-dev the last `kind='sell'` row was written at 18:02:30 and the
        # roster still read `Bork | lead=0 | travel_npc=vendor` at 20:45, so a
        # sweep below `family_town_run_needed` would have had roughly 108
        # consecutive cycles (90 seconds each) in which it never ran at all. A
        # release under an early return passes every unit test and does nothing,
        # which is the ordering trap infra#3708's own sequence test caught one
        # function along.
        await self._release_stranded_vendor_errands(names, leader)

        # A positional economy aim left on a follower is equally inert, but
        # unlike the old vendor keyword it can be mistaken for dungeon staging.
        # Do this only when no run is active; an active coordinator owns every
        # party escort and must be allowed to hold its barrier points.
        in_run = await self._mid_run(names)
        if not in_run:
            await self._release_stranded_ground_errands(names, leader)

        free_slots = await asyncio.to_thread(_fetch_free_slots, names)

        # A stale positional aim on the leader can block the vendor pass just
        # as surely as one on a follower. Full bags are the urgent case: when
        # no dungeon run owns the party, hand that economy aim back so the next
        # arbitration cycle can claim a real vendor target.
        current_aim = await asyncio.to_thread(_current_travel_npc, leader)
        if townslot.urgent_ground_release(
                aim=current_aim,
                pressure=bag_pressure.family_town_run_needed(free_slots),
                in_run=in_run,
                ground=travel.is_ground_aim):
            if await asyncio.to_thread(_release_trade_errand, leader, current_aim):
                log.warning(
                    "economy: released stale leader ground aim %s under bag "
                    "pressure; vendor maintenance gets the town slot next",
                    current_aim,
                )

        # THE RECIPE HAND-OFF RUNS ABOVE THE TOWN-RUN GATE, ON PURPOSE, and it
        # is the only half of this pass that does (infra#3731).
        #
        # WHY IT CANNOT SIT WITH THE OTHERS. The gate below is the right
        # question for a vendor trip and the wrong one for this: the comment
        # above it already records that `family_town_run_needed` is False on
        # MOST cycles now that Og's bags are free, and a Pattern in the wrong
        # bag is no less misfiled on a quiet cycle. Wiring this underneath
        # would have shipped a rule that fires only when somebody is nearly
        # full - which for a family whose bags were just freed is close to
        # never, and is indistinguishable from not shipping it.
        #
        # AND IT COSTS NOTHING THE GATE IS PROTECTING. The gate exists to stop
        # the family walking to town. This writes kind='trade'/'give' rows
        # between two characters wherever they already stand: no vendor, no
        # leader, no counter, and no `travel_npc` - the same argument
        # `_hand_gear` makes for needing no travel errand, which is why these
        # two can run on different cycles without racing each other.
        await self._hand_recipes(names, free_slots)

        if not bag_pressure.family_town_run_needed(free_slots):
            log.info("economy: carried vendor goods exist, but bag pressure is below "
                     "the town-run trigger")
            return
        if in_run:
            # Bag pressure outranks an unfinished dungeon. The world-side
            # coordinator already treats job=quest as the operator's request
            # to exit through the known portal; issuing it here prevents a
            # full inventory from trapping the party in an instance forever.
            for name in names:
                await asyncio.to_thread(
                    _insert_job, name, "quest", "overseer:vendor"
                )
            log.warning(
                "economy: bag pressure is urgent during a dungeon; requested "
                "quest mode for %d roster members before vendor maintenance",
                len(names),
            )
            return
        rows = await asyncio.to_thread(_fetch_vendor_items, names)
        gear_rows = await asyncio.to_thread(_fetch_surplus_gear, names)
        worn = await asyncio.to_thread(_fetch_family_equipped, names)
        bag_rows = await asyncio.to_thread(_fetch_surplus_bags, names)
        equipped_bag_slots = await asyncio.to_thread(
            _fetch_equipped_bag_slots, names
        )
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
        ) + (
            # Redundant spare bags nobody has equipped (infra#4163): dead
            # weight in the exact shape `it.class <> 1` in `_VENDOR_ITEMS_SQL`
            # was written to never see, so they never reached this pass at
            # all until now.
            bag_pressure.bag_candidates(
                bag_rows, equipped_bag_slots, keep_names=OWNER_KEEPS,
            )
        )
        if not candidates:
            log.info("economy: no safe carried vendor goods")
            return
        # A sale is owned by the character carrying that item, so the ROWS are
        # grouped by holder. The ERRAND is not, and that distinction is the
        # whole of infra#3553 - see the aim written below the gate.
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

        # ONE ERRAND, ON THE LEADER, AND NEVER ONE PER HOLDER (infra#3553).
        #
        # WHAT THIS USED TO DO AND WHY IT LOOKED RIGHT. It wrote
        # `travel_npc = 'vendor'` once per HOLDER, arguing that "a single
        # leader aim cannot make the other four characters pass a
        # vendor-range check". The first half of that sentence is true and
        # the conclusion drawn from it is not: a follower does pass the
        # range check, by FOLLOWING THE LEADER to the counter. That is how
        # the bank pass has always worked - "a follower cannot be sent to an
        # NPC on its own ... So the errand goes to the leader, every
        # character's rows are queued together, and each command stays
        # pending until its holder reaches the counter" - and the repair
        # half of the town trip is the same shape again.
        #
        # AIMING A FOLLOWER IS AN UPDATE THAT MOVES NOBODY, and mod-overseer
        # says so in the log every time:
        #
        #     'Ugga' was sent to 'vendor' but does not carry `new rpg` -
        #     nothing walks it anywhere. Followers travel by following the
        #     leader; aim the leader instead
        #
        # (mod_overseer.cpp DriveTravel, the AimedMover::RefuseInFormation
        # branch). `_drive_train` already wrote the rule down: "only the
        # leader carries it, so aiming anybody else is an UPDATE that moves
        # nobody."
        #
        # AND IT IS NOT MERELY INERT - IT COSTS THE FAMILY THE ERRAND.
        # Two things charge for those four dead aims:
        #
        #   * mod-overseer bills an outstanding economy errand 15 seconds of
        #     an ErrandBudgetLimits bucket on every travel poll, and a
        #     follower's aim is never released, because the arrival check
        #     that would release it sits BELOW the refusal above. 420
        #     seconds of budget against a 1,800 second window drains at
        #     0.233 s/s and fills at 1 s/s, so a follower reaches the line in
        #     about nine minutes, every time, and is then refused for fifteen
        #     ("economy errands had taken more than their share of this
        #     character's time"). Every sell row queued during that window
        #     answers `vendor not in range`. Measured all-time on the dev
        #     realm: 17,333 `vendor not in range` against 1,689 delivered.
        #
        #   * `_aimed_names` counts a non-empty `travel_npc` as aimed, and
        #     `_give_them_a_life` hands every aimed character
        #     `goals.life_strategies(...)` -> `nc +new rpg`. So five vendor
        #     aims can also put the wander strategy on all five, which is the
        #     937-yard scatter goals.py exists to prevent.
        #
        #     SAID CAREFULLY, BECAUSE IT IS CONDITIONAL AND THE FIRST DRAFT OF
        #     THIS COMMENT OVERSTATED IT. `_aimed_names` is
        #     `drive_quest <> 0 OR travel_npc <> ''`, and `_aim_quest` already
        #     writes `drive_quest` for EVERY holder of the party's quest
        #     (infra#2801) - so while the family is questing together they are
        #     all aimed and all carrying `new rpg` whatever this pass does, and
        #     these aims add nothing there. The scatter is this pass's doing
        #     only when `drive_quest` is clear. That is a real window and not
        #     the steady state, and it is not why selling stalls; the two
        #     reasons above are.
        #
        # THE HOLDER GATE BELOW IS UNCHANGED and is still per holder, which
        # is the half of infra#3464 that was right: each seller's own DoSell
        # answers on its own range, so each holder's rows wait for that
        # holder to be standing at the counter.
        #
        # (`leader` is read at the top of the pass now, with `_head_now` rather
        # than bonds.head_of_family for the reason recorded there.)
        #
        # AN ERRAND THAT HAS ALREADY LANDED IS NOT RE-ISSUED (infra#3708). This
        # pass used to write `travel_npc = 'vendor'` on every cycle regardless,
        # and nothing anywhere ever wrote it back to empty. `hold` therefore
        # does nothing rather than writing the same word again: a fresh write
        # makes the aim book erase its own state and read a standing errand as
        # a new one, releasing and re-taking the counter hold. The argument and
        # the measurements are on `bag_pressure.vendor_errand_step`.
        aimed = False
        if step == bag_pressure.VENDOR_ERRAND_AIM:
            # THE RETURN VALUE IS READ. The economy guard in _write_trade_errand
            # only retasks an IDLE traveller, so this write is a no-op while the
            # town trip owns `travel_npc = 'repair'` - which is a legitimate
            # outcome and the exact thing infra#3464 called silent. It was still
            # silent afterwards: the caller hardcoded `aimed = True` and threw
            # the answer away.
            #
            # AND IT GOES THROUGH THE TOWN SLOT (infra#3703), which is where
            # "somebody else's errand" stopped being the end of the sentence:
            # the slot says whose, for how long, and what ends it.
            aimed = await self._claim_town_slot(
                "economy", leader, "vendor", urgent=True,
            )
            if not aimed:
                log.info(
                    "economy: leader=%s is already on somebody else's errand, so "
                    "no vendor aim was taken this pass", leader,
                )

        inserted = 0
        considered = 0
        holder_town = {}
        leader_town = await asyncio.to_thread(_fetch_town, leader)
        holder_town[leader] = leader_town
        leader_at_counter = bool(leader_town.vendor)
        for holder in sorted(by_holder):
            town = await asyncio.to_thread(_fetch_town, holder)
            holder_town[holder] = town
        queue_holders = set(bag_pressure.vendor_holders_to_queue(
            candidates,
            leader=leader,
            leader_at_counter=leader_at_counter,
            holder_at_counter=lambda holder: bool(holder_town[holder].vendor),
        ))
        for holder in sorted(by_holder):
            holder_candidates = tuple(by_holder[holder])
            town = holder_town[holder]
            if not town.vendor:
                if holder not in queue_holders:
                    log.info(
                        "economy: %d carried candidate(s) for %s but no vendor "
                        "within reach - leader=%s aim taken=%s",
                        len(holder_candidates), holder, leader, aimed,
                    )
                    continue
            elif holder not in queue_holders:
                log.info(
                    "economy: %d carried candidate(s) for %s but no vendor "
                    "within reach - leader=%s aim taken=%s",
                    len(holder_candidates), holder, leader, aimed,
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
        log.info("economy: queued %d/%d vendor sale(s) across %d holder(s), "
                 "one errand on leader=%s (taken=%s)",
                 inserted, considered, len(by_holder), leader, aimed)

    async def _hand_gear(self, gear_rows: list, worn: list, names: list) -> None:
        """Move every carried piece that suits a sibling better (infra#3464).

        THE VERB FOLLOWS WHERE THE TWO OF THEM ARE STANDING. It was always
        kind='trade', because DoTrade drives the core's WorldSession trade
        handlers and the exchange renders and animates where DoGive is a
        silent database move - a piece of gear changing hands is a thing the
        party should be seen doing. That reasoning was right and it is kept:
        what was missing is that nothing ever asked WHERE they were standing,
        and 343 of 755 trade rows died on `characters are too far apart`.
        `gear.deliverable` now picks the verb from the measured distance, so
        an exchange that can be watched still is one and an exchange across
        744 yards - which renders nothing either way - becomes a give that
        lands. See its banner for the full 41-of-755 measurement.

        NO TRAVEL ERRAND IS WRITTEN, deliberately, and this is why that is
        still right rather than merely convenient: the alternative to
        choosing the verb is steering five characters into one place, and
        #3554 has just finished removing the second writer of travel aims.
        This pass still needs no counter, no leader and no `travel_npc`,
        which is why it can run beside the vendor half.

        NOTHING IS DESTROYED AND NOTHING SOULBOUND IS OFFERED.
        `gear.is_upgrade_for` refuses a soulbound item outright, so a piece
        that cannot legally reach a sibling never becomes a grant, and both
        DoTrade and DoGive refuse one again on their own side.
        """
        # Both facts are read here rather than passed down from _vendor_once,
        # because this pass is reached on cycles that return before the
        # vendor half and must not depend on how far that half got.
        free_slots = await asyncio.to_thread(_fetch_free_slots, names)
        positions = await asyncio.to_thread(_fetch_positions, names)
        plan = bag_pressure.family_gifts(
            gear_rows, worn, names, keep_names=OWNER_KEEPS,
            position_rows=positions, free_slots=free_slots,
        )
        for note in plan.notes:
            log.info("gear: %s", note)
        # ONE NOTE PER WITHHELD GRANT, so this is the number the family
        # decided on rather than a second count to trust.
        decided = len(plan.grants) + len(plan.notes)
        if not plan.grants:
            log.info(
                "gear: considered %d carried piece(s), decided %d hand-off(s), "
                "queued none - %d held back above, %d of the family visible",
                len(gear_rows), decided, len(plan.notes), len(positions),
            )
            return
        seen = await asyncio.to_thread(_recent_trade_keys, GIVE_RETRY_MINUTES)
        fresh = []
        for grant in plan.grants:
            if (grant.holder, grant.taker, grant.command) in seen:
                continue
            if await asyncio.to_thread(_insert_gear_handoff, grant):
                fresh.append(grant)
        for grant in fresh:
            log.info("gear: %s -> %s by %s, %s - %s", grant.holder,
                     grant.taker, grant.verb, grant.name, grant.reason)
        log.info(
            "gear: queued %d/%d hand-off(s) (%d trade, %d give), "
            "%d held back, %d already queued",
            len(fresh), decided,
            sum(1 for g in fresh if g.verb == "trade"),
            sum(1 for g in fresh if g.verb == "give"),
            len(plan.notes), len(plan.grants) - len(fresh),
        )

    async def _hand_recipes(self, names: list, free_slots: dict) -> None:
        """Move every carried recipe into the bag of whoever works its trade.

        THE CLAIM THE OWNER ASKED FOR, for the one category where "who wants
        this" has an exact answer instead of a judgement. 13 of the 15 recipes
        the family carries were measured in the wrong bag on 2026-09-13, and
        neither half of the economy pass could see one: the gear query selects
        `class IN (2, 4)` so `decide` was never asked, and `sellable` refuses
        every Quality 2 so the junk half declined them too. Nothing was
        mis-routing them - nothing was routing them at all.

        NO NEW VERB AND NO NEW `kind`. Every recipe on the realm is bonding 0
        with a clear instance flag, so this is kind='trade'/'give' through the
        hand-off path that has already written 137 rows, and it rides the same
        `_recent_trade_keys` dedupe so a recipe waiting on a taker who is
        offline is not re-queued every cycle.

        THE ROOM BUDGET IS THIS PASS'S OWN, and that is a known, bounded
        imprecision rather than an oversight. `gear.deliverable` budgets free
        slots across the grants IT is handed, so this pass and `_hand_gear`
        can each promise the same last slot to the same taker on the same
        cycle. That is already true between `_hand_gear`, materials.py and
        bag_upgrade.py - all four read `character_inventory`, which lags
        fifteen minutes (`PlayerSaveInterval = 900000`), so no reader can see
        another's queued rows anyway and a shared counter here would be
        precision the underlying data does not have. The cost when it happens
        is one refused row and the item staying put, which is the direction
        every gate in this pass already fails in.

        NO TRAVEL ERRAND IS WRITTEN, deliberately, for exactly the reason
        `_hand_gear` gives: choosing the verb from the measured distance costs
        no `travel_npc` column, and #3554 has just finished removing the second
        writer of travel aims.

        POSITIONS ARE READ HERE rather than passed down, the same choice
        `_hand_gear` makes and for the same reason: this pass now runs on
        cycles that return before the vendor half ever reads them.
        """
        rows = await asyncio.to_thread(_fetch_surplus_recipes, names)
        if not rows:
            log.info("recipes: nobody is carrying a recipe with a skill gate")
            return
        positions = await asyncio.to_thread(_fetch_positions, names)
        skills = await asyncio.to_thread(_fetch_recipe_skills, names)
        plan = bag_pressure.recipe_gifts(
            rows, _recipe_holders_by_skill(skills), keep_names=OWNER_KEEPS,
            position_rows=positions, free_slots=free_slots,
        )
        for note in plan.notes:
            log.info("recipes: %s", note)
        decided = len(plan.grants) + len(plan.notes)
        if not plan.grants:
            log.info(
                "recipes: considered %d carried recipe(s), decided %d "
                "hand-off(s), queued none - %d held back above",
                len(rows), decided, len(plan.notes),
            )
            return
        seen = await asyncio.to_thread(_recent_trade_keys, GIVE_RETRY_MINUTES)
        fresh = []
        for grant in plan.grants:
            if (grant.holder, grant.taker, grant.command) in seen:
                continue
            if await asyncio.to_thread(_insert_gear_handoff, grant):
                fresh.append(grant)
        for grant in fresh:
            log.info("recipes: %s -> %s by %s, %s - %s", grant.holder,
                     grant.taker, grant.verb, grant.name, grant.reason)
        log.info(
            "recipes: queued %d/%d hand-off(s) (%d trade, %d give), "
            "%d held back, %d already queued",
            len(fresh), decided,
            sum(1 for g in fresh if g.verb == "trade"),
            sum(1 for g in fresh if g.verb == "give"),
            len(plan.notes), len(plan.grants) - len(fresh),
        )

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

    async def _settle_bank_errand(self, names: list, leader: str,
                                  moves_unasked: bool) -> str:
        """Aim, hold or hand back the bank pass's `banker` errand (infra#3728).

        THE HALF THAT WAS NEVER BUILT, HERE TOO. `banker` is one of the four
        aims `OverseerDecisions::IsMaintenanceErrand` covers, so mod-overseer
        reaches "errand done, releasing" on arrival and then deliberately skips
        the column write (infra#3655) - its own comment names the bridge as the
        side that "owns the column too and clears it", and the bridge never did
        in any of the four passes. One writer that only ever sets is a latch.

        LIFTED OUT WHOLE AND CALLED ABOVE THE `no moves` GATE, which is the
        whole ordering argument of infra#3717 restated for this pass: an errand
        is finished BECAUSE the moves landed, and moves that landed are moves
        `bank.plan` no longer proposes, so the very cycle that should hand the
        column back is the cycle this pass used to return early on.

        IT SETTLES ONLY `banker`. `travel_npc` is one slot several passes write
        and each must hand back what it wrote; releasing the town trip's
        `repair` or the sell pass's `vendor` from here is the cross-pass theft
        `_write_trade_errand`'s guard exists to prevent (mod-overseer#438).

        IT HAS AN ARRIVAL TEST NOW, AND THE SENTENCE THAT SAID IT NEEDED NONE
        IS QUOTED RATHER THAN DELETED, because the correction is unreadable
        without it (infra#3815). It said:

            "NO ARRIVAL TEST, AND THAT IS NOT AN OVERSIGHT ... A bank row is
            written from wherever the family is standing and waits `pending`
            until its holder reaches the counter ... The town trip needs an
            arrival test precisely because its rows cannot be written until it
            has one."

        The premise is false, and `bank.errand_step` now carries the C++ and
        the measurement. What it cost HERE: the rows went terminal about a
        second after they were written, so `outstanding` read zero on the very
        next cycle, this method took that for a finished errand, and the
        `banker` aim was handed back BEFORE the family arrived - every trip
        called off at roughly the moment it started. The old reasoning is true
        now that `_bank_once` writes a row only from the counter: its rows
        cannot be written until it has arrived either, which is exactly the
        town trip's shape.

        THE ARRIVAL IS READ THROUGH `_fetch_town`, which is what
        `_settle_vendor_errand` asks one counter over (`town.vendor`) and reads
        the live snapshot rather than the quarter-hour-stale save timer. A
        banker is a creature, so it is this reader and not infra#3804's
        `travel.vault_in_reach`, which judges a GAMEOBJECT spawn row.
        """
        leader_town = await asyncio.to_thread(_fetch_town, leader)
        outstanding = await asyncio.to_thread(_outstanding_bank_moves, names)
        step = bank.errand_step(
            bool(leader_town.banker), outstanding, moves_unasked,
        )
        if step == bank.BANK_ERRAND_AIM:
            # THE RETURN VALUE IS READ, the same defect infra#3660 fixed in the
            # guild bank pass. An economy errand may only retask an IDLE
            # traveller, so this write is a no-op while another town pass owns
            # the column - a real, expected refusal (infra#3703) that was
            # invisible for as long as nobody logged it.
            # THROUGH THE TOWN SLOT (infra#3703): the refusal is now a turn in
            # a queue with a lease on it rather than a race this pass lost.
            aimed = await self._claim_town_slot("bank", leader, "banker")
            if not aimed:
                log.info(
                    "bank: leader=%s is already on somebody else's errand, so "
                    "no banker aim was taken this pass", leader,
                )
        elif step == bank.BANK_ERRAND_HOLD:
            # THE TWO HOLDS READ IDENTICALLY IN A LOG AND ARE DIFFERENT STATES
            # (infra#3815): "rows are executing" and "the leader has just
            # arrived and the rows are written below". A person watching a trip
            # that never lands needs to know which one this is.
            log.info(
                "bank: leader=%s keeps the errand it carries - %s. Re-asserting "
                "one is what makes the world read a standing errand as a new "
                "one", leader,
                "the queue cannot be read" if outstanding < 0
                else "%d row(s) unanswered" % outstanding if outstanding
                else "it is standing at the counter and the rows are written "
                     "below this line",
            )
        else:
            released = await asyncio.to_thread(
                _release_trade_errand, leader, "banker",
            )
            if released:
                log.info(
                    "bank: leader=%s has nothing left to ask the counter for "
                    "and every row this trip queued has been answered, so the "
                    "errand is handed back and the family walks again", leader,
                )
            else:
                # Not a failure. The column belongs to somebody else now, and
                # the keyword guard is what stops this pass taking it.
                log.debug(
                    "bank: leader=%s is not carrying a banker errand, so there "
                    "was nothing to hand back", leader,
                )
        return step

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
        leader and the other four arrive behind it. The errand is written
        BEFORE the rows for the same reason the vendor pass writes it first: a
        queue that outlives the journey is the failure this ordering avoids.

        BUT THE ROWS ARE NOT WRITTEN IN THE SAME BREATH ANY MORE, AND THE
        SENTENCE THAT SAID THEY WERE IS THE WHOLE DEFECT (infra#3815). This
        paragraph used to end:

            "So the errand goes to the leader, every character's rows are
            queued together, and each command stays pending until its holder
            reaches the counter (mod-overseer#209, infra#3311)."

        Nothing stays pending - `bank.errand_step` carries the C++ and the
        measurement, and the short of it is that DoBank refuses the row where
        the character stands, terminally, 1.05 seconds after it is written.
        141 error rows against 1 delivered in eight days, while the family
        stood 437 yards from the nearest banker.

        SO IT AIMS ON ONE CYCLE AND QUEUES ON A LATER ONE, the shape
        `_vendor_once` and `_auction_once` already have and infra#3804 gave the
        guild vault. The reach question is asked PER MOVER, because
        `BankerInReach(who, ...)` measures the character whose row it is - the
        same reason `_vendor_once` calls `_fetch_town` per seller.
        `TOWN_COUNTER_YARDS` is deliberately LOOSER than the core's 5-yard
        INTERACTION_DISTANCE: a walk only lands within
        `travel.ARRIVED_POSITION_YARDS` of its aim, so a gate tightened to five
        would hold back characters that had arrived correctly and the move
        would never be attempted at all. Slack costs lateness, never a wrong
        decision.

        AND THE ERRAND IS HANDED BACK WHEN THE TRIP IS OVER (infra#3728). It
        never was: `banker` is a maintenance errand as far as mod-overseer is
        concerned, so the module refuses to clear the column on arrival and
        expects the bridge to. `_settle_bank_errand` does that, and it runs
        above the `no moves` return because a finished trip is exactly a trip
        with no moves left.

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
        # `_head_now()` RATHER THAN bonds.head_of_family() (infra#3553, same
        # defect #3554 fixed in _vendor_once). The two differ exactly when it
        # matters: `_head_now` is what `_mark_party_leader` writes into
        # `lead` and what `_give_them_a_life` reads to decide who carries
        # `new rpg`, so it names the character that can actually walk.
        # bonds.head_of_family() is a pure seniority answer that never moves -
        # measured live, it named 'Grug' for six-plus hours while
        # `overseer_roster.lead` (and the character actually carrying
        # `new rpg`) was 'Grog', on a trade errand. Aiming the static father
        # wrote a `travel_npc` nothing walked, and the module's own guard
        # ("'Grug' was sent to 'banker' but does not carry `new rpg`") burned
        # the errand budget into a 900s refusal every cycle - every personal
        # bank on the realm sat empty because of it.
        #
        # READ BEFORE THE `no moves` GATE NOW (infra#3728). An errand this pass
        # left standing has to be handed back on the cycle it is finished, and
        # the cycle it is finished is very often the cycle there is nothing left
        # to bank - so every step of the settling has to sit ABOVE that return
        # or it could never fire. Same ordering bug, same reasoning, as
        # infra#3717's `_settle_vendor_errand`.
        leader = await asyncio.to_thread(_head_now)
        # THE RETRY WINDOW IS READ BEFORE THE ERRAND IS SETTLED, because it is
        # half of "has this trip anything left to ask for": a move bank.plan
        # proposes again because `character_inventory` has not been flushed yet
        # is not a reason to keep walking to a banker.
        seen = await asyncio.to_thread(_recent_bank_keys, GIVE_RETRY_MINUTES)
        # AND WHO THE WORLD CAN SEE AT ALL, THE OTHER HALF OF THAT QUESTION
        # (infra#3815). Without it the gate below would build a new latch -
        # `bank.errand_step` has the argument. `_fetch_positions` returns only
        # snapshot rows fresher than a minute, so this also ends the 17
        # all-time `target not online` rows.
        watched = await asyncio.to_thread(_fetch_positions, names)
        planned = [(move, bank.command(move)) for move in bank_plan.moves]
        unasked = [move for move, command in planned
                   if (move.character, command) not in seen
                   and move.character in watched]
        await self._settle_bank_errand(names, leader, bool(unasked))

        if not bank_plan.moves:
            log.info("bank: nothing to put down and nothing to fetch back")
            return
        # THE ROW IS ONLY WRITTEN WHERE IT CAN WORK, AND "WHERE" IS THE MOVER'S
        # OWN FEET (infra#3815; the docstring has the reasoning). One answer
        # per character rather than one per row: several rows share a holder
        # and the counter does not move between them.
        #
        # A READ PER MOVER, AND NOT BATCHED, WHICH IS A DECISION (Grug Elder
        # marked it as a query in a loop). `_vendor_once` reads the same table
        # the same way per SELLER, and batching would mean a second town
        # reader keyed on a name list - the third reader infra#3815 exists to
        # avoid. The cost is bounded by the family, not by the queue: at most
        # five reads, once per BANK_CYCLE_SECONDS (600).
        at_the_counter: dict = {}
        walking = []
        fresh = []
        for move, command in planned:
            if (move.character, command) in seen:
                continue
            if move.character not in at_the_counter:
                mover_town = await asyncio.to_thread(_fetch_town, move.character)
                at_the_counter[move.character] = bool(mover_town.banker)
            if not at_the_counter[move.character]:
                walking.append(move.character)
                continue
            if await asyncio.to_thread(_insert_bank, move, command):
                fresh.append(move)
        if walking:
            # LOGGED: a pass that writes nothing and a broken one look
            # identical otherwise (infra#3660, restated for the rows).
            log.info(
                "bank: %s has no banker within %d yards of where the world can "
                "see them, so no row is queued for them until the walk lands - "
                "one written now comes back 'banker not in range' a second "
                "later", ", ".join(sorted(set(walking))), TOWN_COUNTER_YARDS,
            )
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

    async def _guild_bank_once(self) -> None:
        """One pass of the guild bank: park gold above each character's float.

        Deposit only (mod-overseer#437, infra#2831) - see guildbank.py for
        why withdrawal is a separate, harder feature and not attempted here.

        THE AIM IS SHAPED LIKE _bank_once'S AND THE ROWS ARE NOT. Only the
        leader can be aimed (followers arrive by following, mod-overseer#209),
        so the errand goes to the leader once and the other four arrive behind
        it - but the rows are not written in the same breath.

        THE SENTENCE THAT USED TO SIT HERE WAS FACTUALLY WRONG, AND IT IS WHY
        NOBODY LOOKED (infra#3804). It said every character's deposit row was
        "queued alongside it, each staying pending until its holder reaches
        the vault (`GuildBankInReach`, mod-overseer#441)". Nothing waits. The
        row is answered on the next poll from wherever that character stands
        AT THAT INSTANT - DoGuild's own comment says so, "this executor moves
        the money where the character already stands, or names why it cannot"
        - and a failed `GuildBankInReach` goes to `refuse()`, a one-argument
        lambda that writes `status='refused'` and returns. No retry class of
        the kind mod-overseer#230 gave `vendor not in range`, and nothing puts
        the row back to `pending`. It is terminal. So every row this pass ever
        wrote died about a second later, before anybody had walked a yard: 73
        of them on wow-dev in 24 hours, and zero deliveries all-time.

        SO IT AIMS ON ONE CYCLE AND QUEUES ON A LATER ONE, the shape
        `_vendor_once` and `_auction_once` already have, and it asks PER
        DEPOSITOR because `GuildBankInReach(who, ...)` measures the range of
        the character whose row it is - which is why `_vendor_once` calls
        `_fetch_town` per seller. `travel.spawn_in_reach` is that question,
        judged at TOWN_COUNTER_YARDS: looser than the core's 5-yard
        INTERACTION_DISTANCE on purpose, because a walk only lands within
        `travel.ARRIVED_POSITION_YARDS` of its aim and a gate tightened to
        five would refuse characters that had arrived correctly. It ends a
        second dead class too: `_fetch_positions` returns only rows fresher
        than a minute, so a character the world is not ticking is not queued -
        the other 36 rows in the same day, `target not online`.

        AND THE AIM IS THE VAULT'S OWN SPAWN, NOT A ROLE KEYWORD (infra#3702).
        Two previous fixes here argued about which KEYWORD to write - `guild
        bank` (never defined) and then `guild banker` (defined on both sides,
        infra#3657) - and both were answering the wrong question, because no
        keyword can work. Counted against the live world database:

            SELECT COUNT(*) FROM acore_world.creature_template
             WHERE npcflag & 0x8000000;   -> 0

        Not one creature carries UNIT_NPC_FLAG_GUILD_BANKER, and
        `ResolveTravelTarget`'s role branch only ever searches creature
        spawns, so `travel_npc='guild banker'` resolved to nothing for exactly
        the same reason `guild bank` did - it just did so one layer deeper,
        which is why the second fix looked right and changed nothing. Every
        deposit still came back `no guild bank in reach`; measured on the dev
        realm the night this was found, 20 of them in three hours while five
        characters carried ~170 gold each.

        A guild bank on 3.3.5 is a GAMEOBJECT - "Guild Vault",
        `gameobject_template.type = 34` - and the same database has 41 of them
        spawned across four maps, two of them 123 and 131 yards from where the
        family was standing. So this pass reads the nearest one out of the
        live `gameobject` spawn table and writes its own surveyed position as
        an `at:<map>:<x>,<y>,<z>` aim, which `ResolveTravelTarget` answers with
        ground before it ever builds the NPC index. That is the same
        resolution the module already does for creature spawns, against the
        table the answer is in; see travel.vault_aim for why reading a spawn
        row is not hand-authoring a coordinate, and _VAULT_SQL for the
        same-map rule.

        NOT IN THE MIDDLE OF A DUNGEON RUN, for the same reason the personal
        bank pass skips one: pulling the leader out to bank is how the party
        spreads.

        THE AIM RESULT IS LOGGED, NOT DISCARDED (infra#3660 follow-up).
        `_write_trade_errand` returns whether the aim was actually taken -
        every other economy pass tonight (craft_supply, the vendor pass) logs
        that return, and this one silently dropped it, which is exactly the
        "written and unread" failure mode `_write_trade_errand`'s own
        docstring already warns about for a different caller (infra#3464).
        A leader who already carries the party's OWN standing vendor/repair
        errand is a real, expected reason `_write_trade_errand` refuses -
        `ECONOMY_ERRANDS` only retasks an idle traveller - but until this
        logged it, that refusal was invisible: the guild bank could starve
        for as long as the leader's other errand ran and nothing said so.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names or await self._mid_run(names):
            return
        setup = await asyncio.to_thread(_fetch_guild_bank_setup, names)
        if setup:
            actions = guildbank.plan_setup(
                leader=await asyncio.to_thread(_head_now),
                purchased_tabs=setup["purchased_tabs"],
                rank_ids=setup["rank_ids"],
                deposit_rank_ids=setup["deposit_rank_ids"],
            )
            if actions:
                leader = await asyncio.to_thread(_head_now)
                positions = await asyncio.to_thread(
                    _fetch_positions, sorted({leader}))
                where = positions.get(leader)
                spawn = await asyncio.to_thread(_nearest_vault, leader)
                vault = travel.vault_aim(spawn, where.get("map_id") if where else None)
                if vault.aim:
                    aimed = await self._claim_town_slot("guild bank", leader, vault.aim)
                    at_the_vault = travel.spawn_in_reach(spawn, where, TOWN_COUNTER_YARDS)
                    # THREE STATES, NOT TWO (infra#3713). This read
                    # `if aimed or at_the_vault:`, which queued the purchase on
                    # the strength of the CLAIM. `_claim_town_slot` returns True
                    # the moment this pass wins the right to walk - the start of
                    # the journey, not the end - so on 2026-09-19 the column was
                    # claimed at 03:47:08 and `bank buy-tab` queued at 03:47:09
                    # with the leader 3311 yards from the vault. The core
                    # refused it ("the core did not buy the next guild bank
                    # tab"); not permissions (Guild Master, rights 1962495) and
                    # not funds (198g against a 100g tab) - simply not there.
                    #
                    # `aimed` IS STILL READ, because it answers a different and
                    # still-needed question: whether this pass is STARVED
                    # (infra#3464 - the pass used to discard it and say nothing
                    # while the leader sat on another errand for 15+ minutes).
                    # Starved, walking and arrived are three outcomes and each
                    # gets its own sentence.
                    if not aimed and not at_the_vault:
                        log.info(
                            "guild bank setup: leader=%s could not be aimed at "
                            "the vault (%s) this pass, so no setup row is "
                            "queued", leader, vault.aim)
                        return
                    if not at_the_vault:
                        log.info(
                            "guild bank setup: %s is walking to the vault (%s) "
                            "- the row waits for the arrival, because one "
                            "queued now comes back 'no guild bank in reach'",
                            leader, vault.aim)
                        return
                    if at_the_vault:
                        seen = await asyncio.to_thread(_recent_guild_setup_keys, GIVE_RETRY_MINUTES)
                        action = next((a for a in actions
                                       if (leader, a.command) not in seen), None)
                        if action:
                            await asyncio.to_thread(_insert_guild, leader,
                                                    action.command, "guildbank-setup")
                            log.info("guild bank setup: queued %s for %s",
                                     action.command, leader)
                        return
                log.info("guild bank setup: aiming %s at %s", leader, vault.aim)
                return
        members = await asyncio.to_thread(_fetch_guild_money, names)
        deposits = guildbank.plan_deposits(members)
        if not deposits:
            log.info("guild bank: nobody is carrying more than the float")
            return
        leader = await asyncio.to_thread(_head_now)
        # ONE POSITION READ, FOR TWO QUESTIONS (infra#3804): which map the
        # LEADER aims from, and whether each DEPOSITOR is at the vault now.
        # `_fetch_positions` batches, so this is the one query it always was.
        positions = await asyncio.to_thread(
            _fetch_positions, sorted({leader} | {d.name for d in deposits}))
        where = positions.get(leader)
        spawn = await asyncio.to_thread(_nearest_vault, leader)
        vault = travel.vault_aim(spawn, where.get("map_id") if where else None)
        if not vault.aim:
            # NOT A FAILURE, AND NOT QUEUED EITHER. Every refusal here means
            # no character can stand at a vault this cycle, and a deposit row
            # queued into that is a row whose only possible answer is `no
            # guild bank in reach` - which is precisely the error this pass
            # has been manufacturing every ten minutes for its whole life.
            # The sentence comes from travel.vault_aim already actionable.
            log.info("guild bank: nobody can be sent to a vault - %s", vault.refused)
            return
        aimed = await self._claim_town_slot("guild bank", leader, vault.aim)
        # ALREADY STANDING THERE COUNTS AS AIMED, because it is the state the
        # aim exists to produce. mod-overseer RELEASES a travel aim the moment
        # the walk arrives (it clears `travel_npc`, which is the signal the
        # writing pass reads as "arrived"), so the cycle after the family
        # reaches the vault finds the column empty - and if any other economy
        # pass claims it in that gap, `aimed` comes back false while five
        # characters are stood at the vault with gold to hand over. Gating the
        # queue on the aim alone would skip exactly the cycle that was going
        # to work. TOWN_COUNTER_YARDS rather than a second threshold of its
        # own: "is a counter within reach of where this character is standing"
        # is the same question the town reader already answers, sized to the
        # core's own interact gate, and one answer to it is better than two.
        #
        # IT IS THE LEADER'S DISTANCE, so it decides only whether the pass
        # keeps going (infra#3804): which rows get written is asked again
        # below, per depositor, because an arrived leader never meant five.
        # Through that same reader rather than `spawn["d2"]`, which is this
        # same distance for this same leader: one answer, one function.
        at_the_vault = travel.spawn_in_reach(spawn, where, TOWN_COUNTER_YARDS)
        if not aimed and not at_the_vault:
            # WHAT HOLDS THE COLUMN, NOT JUST THAT SOMETHING DOES (infra#3702).
            # The predecessor of this line said "already on another errand"
            # and stopped there, so the one fact needed to tell a starved
            # pass from a broken one - WHICH errand, and therefore whether it
            # was live or left behind - was never written down, and the next
            # reader had to go and measure it by hand. An economy errand may
            # only retask an IDLE traveller (see _write_trade_errand), so a
            # leader holding any other one outranks this pass indefinitely.
            # That starvation was infra#3703's, and the answer it took is the
            # town slot: this pass is now in a queue with a lease on the
            # holder, so a live errand still wins - measured on wow-dev the
            # leader's `vendor` errand was delivering sales, not a leftover -
            # and one that never finishes stops winning after LEASE_SECONDS.
            # `_claim_town_slot` has already logged whose errand it is, how
            # long they have had it and who is ahead in the queue.
            log.info(
                "guild bank: leader=%s could not be aimed at the vault (%s) "
                "this pass, so no deposit is queued - every row queued into a "
                "trip nobody is taking comes back 'no guild bank in reach'",
                leader, vault.aim,
            )
            return
        if not at_the_vault:
            # AIMED BUT STILL WALKING, WHICH IS ITS OWN ANSWER (infra#3713).
            # The arm above reports STARVATION - no column, nobody moving. This
            # one reports a journey in progress, and the two used to be one
            # branch that fell through to queueing. The leader-level gate is
            # what the setup path needed too: a purchase queued mid-walk is
            # refused by the core on range, exactly as a deposit would be.
            #
            # The per-depositor `spawn_in_reach` below is NOT made redundant by
            # this: an arrived leader never meant five (infra#3804), so this
            # decides whether the pass proceeds at all and that one decides
            # which rows get written.
            log.info(
                "guild bank: leader=%s is walking to the vault (%s) - no "
                "deposit is queued until the walk lands, because one written "
                "now comes back 'no guild bank in reach' a second later",
                leader, vault.aim)
            return
        seen = await asyncio.to_thread(_recent_guild_bank_keys, GIVE_RETRY_MINUTES)
        fresh = []
        walking = []
        for deposit in deposits:
            command = f"bank deposit {deposit.copper}"
            if (deposit.name, command) in seen:
                continue
            # THE ROW IS ONLY WRITTEN WHERE IT CAN WORK, AND THE HOLDER IS WHO
            # IT HAS TO WORK FOR (infra#3804; the docstring has the reasoning
            # and the measurement).
            if not travel.spawn_in_reach(
                    spawn, positions.get(deposit.name), TOWN_COUNTER_YARDS):
                walking.append(deposit.name)
                continue
            await asyncio.to_thread(_insert_guild, deposit.name, command, "guildbank")
            fresh.append(deposit)
        if walking:
            # LOGGED: a pass that writes nothing and a broken one look
            # identical otherwise (infra#3660, restated for the rows).
            log.info(
                "guild bank: %s not within %d yards of the vault at %s, so no "
                "deposit is queued for them until the walk lands - one written "
                "now comes back 'no guild bank in reach' a second later",
                ", ".join(sorted(walking)), TOWN_COUNTER_YARDS, vault.aim,
            )
        log.info("guild bank: queued %d/%d deposit(s), leader=%s aimed at %s",
                 len(fresh), len(deposits), leader, vault.aim)

    async def _recruit_once(self) -> None:
        """One pass of the recruit sweep: shortlist, or invite, or say why not.

        infra#3651, and the thing it turns from manual into unattended. The
        `shortlist` and `invite` verbs have existed since mod-overseer#413 but
        only ever ran when somebody wrote a row by hand, and nobody ever had -
        measured against the live command log, not one `shortlist` or `invite`
        row has ever been issued.

        ONE ACTION PER PASS, AND NEVER BOTH. The two verbs are separate
        commands run asynchronously by the worldserver; this process writes a
        row and cannot wait for it. So a pass either asks for a shortlist or
        acts on the newest one that has already come back, which means every
        invite is drawn from a list a person could have read first. See
        recruit.plan_recruit for the gate order.

        EVERY OUTCOME IS LOGGED, INCLUDING THE ONES WHERE NOTHING HAPPENS.
        infra#3651's complaint about the manual path is that a quiet day and a
        broken loop look identical, so `wait` carries a reason and it is logged
        at info rather than swallowed.

        THE JUDGEMENT IS NOT HERE AND MUST NOT MOVE HERE. Who is worth asking
        is mod-overseer's `RecruitVerdictFor` and `RecruitShortlist`, against
        the guild's real holes. This pass decides pace and turn only.
        """
        actors = await asyncio.to_thread(_online_guild_members)
        result, age = await asyncio.to_thread(_latest_guild_shortlist)
        members, target = recruit.roster_from_shortlist(result or {})
        action = recruit.plan_recruit(
            actors=actors,
            shortlist=recruit.names_from_shortlist(result or {}),
            shortlist_age_minutes=age,
            shortlist_asked_minutes_ago=await asyncio.to_thread(_minutes_since_shortlist_asked),
            asked=await asyncio.to_thread(_guild_invites_asked, recruit.ASKED_MEMORY_DAYS),
            minutes_since_last_invite=await asyncio.to_thread(_minutes_since_last_guild_invite),
            member_count=members,
            target_size=target,
        )

        if action.verb == "wait":
            log.info("recruit: nothing this pass - %s", action.reason)
            return

        row = await asyncio.to_thread(
            _insert_guild, action.actor, action.command, "recruit", action.target_arg,
        )
        if not row:
            # _insert_guild already said why. Logged again here with the verb,
            # because "the guild machinery is missing" is a different day's
            # problem from "this pass had nothing to do".
            log.warning("recruit: %s row was not written", action.verb)
            return
        log.info(
            "recruit: queued %s via %s (%s) - roster %d of %d",
            action.command, action.actor, action.reason, members, target,
        )

    async def _recruit_loop(self) -> None:
        """Recruit toward the guild's target size, unattended (infra#3651).

        THE CADENCE IS THE RATE LIMIT'S PARTNER, NOT A SECOND ONE. The pass
        runs every five minutes so that a stale shortlist is refreshed
        promptly and a pass held back by the clock retries soon after it
        clears; how often an INVITE may actually be written is
        recruit.MIN_MINUTES_BETWEEN_INVITES, checked against the command log
        rather than against this timer. A limit that lived in a loop's sleep
        would be reset by every restart.

        NOT ONCE A DAY, which is what infra#3651 asked for when the target
        roster was 15. Thirty-five seats at one invite a day is thirty-five
        days. See recruit.py's docstring for the argument, and the comment on
        infra#3650.

        No `travel_npc` stagger: this pass never writes that column, so it
        does not compete with the vendor, bank, guild-bank or craft-supply
        passes for it.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("RECRUIT_CYCLE_SECONDS", "300"))
        while not self.is_closed():
            try:
                await self._recruit_once()
            except Exception:
                log.exception("recruit pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _guild_bank_loop(self) -> None:
        """Keep the guild bank fed (mod-overseer#437, infra#2831).

        Own loop and own clock, the same reasoning as _bank_loop.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("GUILD_BANK_CYCLE_SECONDS", "600"))
        # Staggered past every other loop that writes `travel_npc` (vendor,
        # bank, towntrip all claim earlier slots) so this pass never arrives
        # in the same instant and races one of them for the column.
        await asyncio.sleep(min(cycle, 240.0))
        while not self.is_closed():
            try:
                await self._guild_bank_once()
            except Exception:
                log.exception("guild bank pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _mail_once(self) -> None:
        """One pass of the mail: collect what is already addressed to the family.

        infra#3741, and the third shipped-but-uncalled executor this package has
        had to go back for. `kind='mail'` has carried five verbs since
        mod-overseer's mail migration and no process had ever written one row of
        it; measured 2026-09-13 the family's own mailboxes held 21 letters, 9
        attachments and 4,100 copper, and the auction pass had spent the day
        putting bought reagents into a mailbox nothing read. What lands in a bag
        because of this pass is what `DriveCraft`, the vendor pass and the bank
        pass can all finally see.

        THE AIM IS SHAPED LIKE _guild_bank_once'S AND THE ROWS ARE NOT. Only the
        leader can be aimed (followers arrive by following, mod-overseer#209), so
        the errand goes to the leader once and the other four arrive behind it.
        And the aim is a GROUND aim for the same reason the vault's is: a mailbox
        on 3.3.5 is a gameobject, `TravelRoles()` has no `mailbox` keyword to
        write and no creature on this world carries UNIT_NPC_FLAG_MAILBOX
        (travel.MAILBOX_GO_TYPE has the counts), so the only thing that can reach
        one is the spawn's own surveyed position through `travel.mailbox_aim`.

        THE SENTENCE THAT USED TO FINISH THAT PARAGRAPH WAS FACTUALLY WRONG,
        AND SO WAS THE ONE #3788 PUT IN FRONT OF A REVIEWER (infra#3830). It
        said the errand went to the leader "and every character's take is
        queued alongside it, each staying pending until its holder reaches a
        mailbox"; the PR body said this pass "fails safe (queues nothing until
        someone can stand at a mailbox)". Neither is true, and the second is
        why nobody looked: the only gate this pass had was on the AIM being
        taken, which asks whether a mailbox EXISTS on the leader's map - never
        whether anybody is at one - so the first cycle that won the column
        queued the lot.

        NOTHING STAYS PENDING. `DoMail` requires a mailbox for all five verbs
        (`FindMailboxInReach` runs before the verb branches, because all five
        handlers open with `CanOpenMailBox`), and an empty sweep goes to
        `refuse()`, a one-argument lambda that describes the row and returns.
        mod-overseer#230 took the push-back-to-`pending` path out of every verb
        in that module - "a retry that keeps its place at the head of a FIFO is
        not a retry, it is a lock" - so the row is terminal where it stands.
        `MailRefusalRetryable` DOES class this refusal retryable, and that is
        the one real difference from infra#3804's vault: it is a flag carried
        OUT in the result JSON for the SENDER to act on, not something that
        moves a row. The only thing on this side that acts on it is
        `_recent_mail_keys`, which suppresses an identical take for
        GIVE_RETRY_MINUTES and bills it to `mailrun.room_for` as spent bag
        budget. So a take written early does not merely die - it takes the
        retry window and the bag room with it.

        MEASURED, MINUTES AFTER THIS PASS FIRST RAN ON THE REALM (infra#3830):
        ten takes written at 04:22:43, ten `mailbox not in range` answered 0.8
        seconds later, zero delivered all-time. Ten minutes on, the five were
        still 1,092 to 1,140 yards from the nearest mailbox on their own map.
        Half an hour after that, having walked into Gadgetzan, they were 47 to
        52 - in the town, at the aim, and still six times outside the gate.
        That second reading is the case this is really for: the extreme one
        only says the pass can be wrong, the near one says it is wrong on the
        ordinary cycle where the walk has nearly landed.

        SO IT AIMS ON ONE CYCLE AND QUEUES ON A LATER ONE, the shape
        `_vendor_once` and `_auction_once` already have and infra#3804 gave the
        guild vault. The reach question is asked PER TAKER, because
        `FindMailboxInReach(who, ...)` sweeps around the character whose row it
        is - the same reason `_vendor_once` calls `_fetch_town` per seller.
        `travel.spawn_in_reach` is that question, and it is named for neither
        counter because nothing in it is about either; its docstring has that
        argument. It is judged at TOWN_COUNTER_YARDS, deliberately looser than
        the core's five-yard interact gate, because a walk only lands within
        `travel.ARRIVED_POSITION_YARDS` of its aim and a gate tightened to five
        would refuse characters that had arrived correctly. Slack costs
        lateness, never a wrong row.

        AND THERE IS NO ERRAND TO HAND BACK, WHICH IS NOT AN OVERSIGHT. A ground
        aim is not a maintenance errand: `IsMaintenanceErrand` is
        `CounterRoleForAim(aim) != CounterRole::None`, and `CounterRoleForAim`
        matches four whole keywords (`vendor`, `banker`, `repair`, `auctioneer`)
        and nothing else. So `TravelAimBook::Release` takes its own terminal
        branch on arrival and blanks `travel_npc` itself, exactly as it already
        does for the guild bank's vault aim. `_bank_once` needs
        `_settle_bank_errand` because `banker` IS one of those four; this pass
        would be inventing a second writer for a column the world already
        clears.

        NOTHING IS QUEUED UNTIL SOMEBODY CAN ACTUALLY STAND AT A MAILBOX. Every
        refusal from `travel.mailbox_aim` means no character can reach one this
        cycle, and a take queued into that is a row whose only possible answer is
        `mailbox not in range` - which is precisely the queue of 84 dead
        `no guild bank in reach` rows the guild bank pass manufactured before
        infra#3702. The plan is still computed first, because its notes are the
        only thing that can say the mailboxes were empty rather than unreachable.

        AND THAT HEADING IS A SMALLER CLAIM THAN IT READS AS (infra#3830).
        "Actually stand at a mailbox" is what a reader takes from it and is not
        what the paragraph under it proves: every refusal it names comes from
        `travel.mailbox_aim`, which asks whether a mailbox EXISTS on the
        leader's map. Whether anybody has ARRIVED at one is the per-taker gate
        above, and reading this paragraph as the whole of the guarantee is how
        ten rows came to be manufactured in precisely the state it describes.

        NOT IN THE MIDDLE OF A DUNGEON RUN, for the same reason the two bank
        passes skip one: a mail run is a town errand, and pulling the leader out
        of a run to make one is how the party spreads.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names or await self._mid_run(names):
            return
        letters = mailrun.letters_from_rows(
            await asyncio.to_thread(_fetch_mail, names), names)
        if not letters:
            log.info("mail: nothing is waiting in anybody's mailbox")
            return
        # THE WINDOW IS READ BEFORE THE PLAN, because it is an input to the
        # plan and not only a filter on it: `attachments_asked` turns the takes
        # already queued into spent bag budget, which is what stops a stale
        # `character_inventory` reading being asked the same optimistic question
        # every cycle. See mailrun.room_for.
        seen = await asyncio.to_thread(_recent_mail_keys, GIVE_RETRY_MINUTES)
        mail_plan = mailrun.plan(
            letters,
            await asyncio.to_thread(_fetch_free_slots, names),
            mailrun.attachments_asked(seen),
        )
        for note in mail_plan.notes:
            log.info("mail: %s", note)
        if not mail_plan.takes:
            log.info("mail: %d letter(s) are waiting and none of them can be "
                     "collected this pass", len(letters))
            return

        # `_head_now()` RATHER THAN bonds.head_of_family(), the defect infra#3553
        # found in the vendor pass and infra#3554 fixed: `_head_now` names the
        # character that actually carries `new rpg` and can therefore walk, where
        # the seniority answer is a static table that named a follower for six
        # hours while the real leader was on a trade errand.
        leader = await asyncio.to_thread(_head_now)
        # ONE POSITION READ, FOR TWO QUESTIONS (infra#3830): which map the
        # LEADER aims from, and whether each TAKER is at the mailbox now.
        # `_fetch_positions` batches, so this is the one query it always was.
        positions = await asyncio.to_thread(
            _fetch_positions,
            sorted({leader} | {t.character for t in mail_plan.takes}))
        where = positions.get(leader)
        spawn = await asyncio.to_thread(_nearest_mailbox, leader)
        post = travel.mailbox_aim(spawn, where.get("map_id") if where else None)
        if not post.aim:
            log.info("mail: nobody can be sent to a mailbox - %s", post.refused)
            return
        # THROUGH THE TOWN SLOT, LIKE EVERY OTHER TOWN ERRAND (infra#3703,
        # infra#3822). This pass and the town slot were written in parallel and
        # merged eighty-six seconds apart, so it landed still writing the column
        # directly - which is not merely a broken invariant. A direct write is a
        # third racer for the family's one traveller, it takes no lease, it
        # answers to no turn order, and the aim it writes is a GROUND aim: the
        # shape that had no terminal path at all until infra#3703 taught
        # `_release_trade_errand` to hand one back. Left as it was, the pass that
        # measured 21 letters waiting would have been the one pass nothing could
        # ever preempt, holding the column while the auction pass that BUYS what
        # arrives by mail starved behind it.
        aimed = await self._claim_town_slot("mail", leader, post.aim)
        # ALREADY STANDING THERE COUNTS AS AIMED, the reasoning `_guild_bank_once`
        # sets out: mod-overseer releases a travel aim the moment the walk
        # arrives, so the cycle AFTER the family reaches the mailbox finds the
        # column empty, and gating the queue on the aim alone would skip exactly
        # the cycle that was going to work. TOWN_COUNTER_YARDS rather than a
        # threshold of this pass's own, because "is a counter within reach of
        # where this character is standing" is the same question the town reader
        # already answers, sized to the core's own interact gate - and
        # `CanOpenMailBox` is that same gate.
        #
        # IT IS THE LEADER'S DISTANCE, so it decides only whether the pass keeps
        # going (infra#3830): which rows get written is asked again below, per
        # taker, because an arrived leader never meant five. Through the same
        # reader rather than the spawn's own `d2`, which is this same distance
        # for this same leader: one answer, one function.
        at_the_mailbox = travel.spawn_in_reach(spawn, where, TOWN_COUNTER_YARDS)
        if not aimed and not at_the_mailbox:
            # WHAT IT IS COSTING, WHICH THE SLOT CANNOT SAY. `_claim_town_slot`
            # has already named the holder, how long it has had the column, how
            # much lease is left and who is queued ahead - one sentence, in one
            # place, for every town pass. What only this pass knows is how much
            # is sitting in the mailbox going uncollected, and that the auction
            # pass is buying reagents that arrive there.
            log.info(
                "mail: leader=%s could not be aimed at a mailbox (%s) this "
                "pass, so %d letter(s) stay uncollected until the town slot "
                "comes round", leader, post.aim, len(letters),
            )
            return

        # THE ROW IS ONLY WRITTEN WHERE IT CAN WORK, AND THE TAKER IS WHO IT HAS
        # TO WORK FOR (infra#3830; the docstring has the reasoning and the
        # measurement). It decides the list this loop walks rather than sitting
        # inside it, so a take whose holder has not arrived never reaches
        # `_insert_mail` at all.
        fresh = []
        for take in _mail_takes_in_reach(
                mail_plan.takes, spawn, positions, TOWN_COUNTER_YARDS,
                post.aim):
            command = mailrun.command(take)
            if (take.character, command) in seen:
                continue
            if await asyncio.to_thread(_insert_mail, take, command):
                fresh.append(take)
        for line in mailrun.lines(fresh):
            log.info("mail: %s", line)
        log.info("mail: queued %d/%d take(s) from %d letter(s), leader=%s "
                 "aimed at %s",
                 len(fresh), len(mail_plan.takes), len(letters), leader, post.aim)

    async def _mail_loop(self) -> None:
        """Keep the family's mailboxes emptied (infra#3741).

        Own loop and own clock, the same reasoning as _bank_loop: a failed pass
        is logged and retried rather than swallowed, because a mail pass that has
        quietly stopped looks exactly like a family with no post.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("MAIL_CYCLE_SECONDS", "600"))
        # Behind every other loop that writes `travel_npc` (vendor, bank,
        # towntrip and the guild bank all claim earlier slots) so this pass never
        # arrives in the same instant and races one of them for the column.
        await asyncio.sleep(min(cycle, 300.0))
        while not self.is_closed():
            try:
                await self._mail_once()
            except Exception:
                log.exception("mail pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _forge_once(self) -> None:
        """Stand the family at a Forge when somebody is holding a smelt errand
        (infra#3748, part of infra#3731).

        THE WALK THAT UNBLOCKS SMELTING, AND IT IS `_guild_bank_once` WITH A
        DIFFERENT WHERE CLAUSE. infra#3617 parked the forge/anvil question
        having concluded that reaching a spell-focus GameObject "means indexing
        GameObject spawns the same way creatures are indexed today - a new
        second index, not a one-line addition". That was already untrue when it
        was written: infra#3702 shipped `_guild_bank_once`, which walks the
        leader to a Guild Vault - a GAMEOBJECT, not a creature - by reading the
        nearest spawn out of `acore_world.gameobject` and handing its surveyed
        position to `travel.ground_aim`, producing the `at:<map>:<x>,<y>,<z>`
        form `ResolveTravelTarget` answers with ground before it ever builds the
        creature-only `_travelSpawns` index. This pass is that pass with
        `gt.type = 8 AND gt.Data0 = 3`.

        AND SMELTING IS THE ONE CASE THAT NEEDS ONLY THE WALK. infra#3617's
        other half is the Blacksmith Hammer: every Anvil-gated recipe also needs
        a tool equipped, an unsolved "swap it in and put the weapon back"
        problem, and that issue noted the travel half "could ship alone ... for
        Anvil-only recipes if any existed without a tool requirement (none do
        here)". Every smelt spell reads `EquippedItemClass = -1`. So this
        unblocks the whole smelting chain and leaves the hammer question exactly
        where it is - `craft.FOCUS_AIMS` is the fence that keeps it there.

        THE LEADER, BECAUSE ONLY THE LEADER CAN BE AIMED. mod-overseer grants
        `new rpg` to the leader alone and `ReadAimedMover` answers
        `RefuseInFormation` for a follower, so aiming Grog - who is the family's
        engineer and the character the bars are FOR - would move nobody. The
        followers arrive by following, which is the same reason
        `_guild_bank_once` and `_bank_once` both aim one character and queue
        five rows.

        DEMAND-DRIVEN, AND THAT IS THE SAFETY PROPERTY RATHER THAN AN
        OPTIMISATION. `_forge_errands` returns empty unless somebody on
        `job='craft'` is holding a recipe that actually needs a focus, and this
        pass then writes nothing at all. A background pass that latched
        `travel_npc` unconditionally is what pinned the family in a shop for
        half an hour (infra#3703, infra#3708, infra#3728) and cost four release
        fixes in one night; this one cannot, because on the overwhelming
        majority of passes it has nothing to ask for.

        ONE WRITER, AND THE GUARD IT NEEDS IS ALREADY THERE. The aim goes
        through `_write_trade_errand` like every other travel errand this
        process issues. No change to `_retaskable_from` is required and none was
        made: infra#3702 already taught it that a ground aim is an economy
        errand (`travel.is_ground_aim`), so a forge aim takes the guarded branch
        that retasks only an IDLE traveller and can never blank an outstanding
        `learn_skill`/`unlearn_skill` on its way past - which is mod-overseer#438's
        bug, and the one `ECONOMY_ERRANDS`' own comment warns about re-creating
        one file over.

        AND IT IS HANDED BACK BY THE MODULE, NOT LATCHED. `TravelAimBook::Release`
        skips its column write only when the book never claimed the aim AND
        `LearnSkillPending` or `IsMaintenanceErrand` holds. `CounterRoleForAim`
        answers `None` for an `at:` aim, so neither holds, and the release
        clears `travel_npc` the moment the traveller is within
        `TRAVEL_ARRIVED_POSITION_YARDS` of the forge. That is the same terminal
        path the vault aim already relies on - measured and documented in
        `_guild_bank_once`, which reads the emptied column as "arrived" - and it
        is why this pass adds nothing to `_release_trade_errand`, whose
        `ECONOMY_ERRANDS` guard is deliberately keyword-only.

        NOT IN THE MIDDLE OF A DUNGEON RUN, for the reason both bank passes skip
        one: pulling the leader out is how the party spreads.
        """
        smelters = await asyncio.to_thread(_forge_errands)
        if not smelters:
            return
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names or await self._mid_run(names):
            return
        leader = await asyncio.to_thread(_head_now)
        where = (await asyncio.to_thread(_fetch_positions, [leader])).get(leader)
        spawn = await asyncio.to_thread(_nearest_forge, leader)
        forge = travel.forge_aim(spawn, where.get("map_id") if where else None)
        if not forge.aim:
            # THE FAILURE IS LEGIBLE HERE BECAUSE IT CANNOT BE LEGIBLE THERE.
            # DriveCraft does not tell SPELL_FAILED_REQUIRES_SPELL_FOCUS from a
            # cooldown - it logs a bare numeric SpellCastResult at INFO and
            # retries every twenty seconds - so a smelt that never lands looks
            # like a transient for ever. Filed as mod-overseer's own issue; this
            # is the half that can be said from this side, and it names the
            # characters it is costing rather than just the refusal.
            log.info(
                "forge: %s hold a focus-gated craft errand (%s) and nobody can "
                "be sent to a forge - %s",
                ", ".join(sorted(smelters)),
                ", ".join("%s=%d" % pair for pair in sorted(smelters.items())),
                forge.refused,
            )
            return
        if travel.within_focus(spawn):
            # ALREADY THERE, SO THE COLUMN IS LEFT ALONE. Writing an aim for a
            # walk of nought yards would claim `travel_npc` from whatever
            # economy pass could otherwise be using it, and would stand the
            # quest drive down for a journey that is already over - a cost with
            # no matching benefit. Judged against the FORGE's own radius rather
            # than a constant of ours, because that is the distance CheckCast
            # itself measures (see travel.within_focus).
            log.info(
                "forge: leader=%s is already inside the %d-yard focus of the "
                "nearest forge on map %s, so %s can smelt where they stand and "
                "no aim is written",
                leader, forge.radius,
                where.get("map_id") if where else "?",
                ", ".join(sorted(smelters)),
            )
            return
        aimed = await self._claim_town_slot("forge", leader, forge.aim)
        if not aimed:
            # WHAT IT IS COSTING, WHICH THE SLOT CANNOT SAY. `_claim_town_slot`
            # has already named the holder, its lease and the queue - that is
            # the half infra#3702 added here and infra#3703 moved into one
            # place for all seven passes. What only this pass knows is WHO
            # cannot smelt because of it, and DriveCraft cannot say that: it
            # logs a bare numeric SpellCastResult and retries for ever.
            log.info(
                "forge: leader=%s could not be aimed at the forge (%s) this "
                "pass, so %s cannot smelt until the town slot comes round",
                leader, forge.aim, ", ".join(sorted(smelters)),
            )
            return
        log.info(
            "forge: leader=%s aimed at %s (%d-yard focus) so %s can smelt - %s",
            leader, forge.aim, forge.radius, ", ".join(sorted(smelters)),
            ", ".join("%s=%d" % pair for pair in sorted(smelters.items())),
        )

    async def _forge_loop(self) -> None:
        """Keep a smelter standing at a forge (infra#3748).

        Own loop and own clock, the same reasoning `_guild_bank_loop` and
        `_craft_supply_loop` give for themselves.

        THE CADENCE MATCHES `CRAFT_CYCLE_SECONDS` (300 by default), so the walk
        and the errand that needs it are decided a poll apart rather than on
        unrelated clocks - the same argument `_craft_rhythm_loop` makes.

        STAGGERED LAST OF ALL, after `_craft_rhythm_loop`'s own 330-second
        settle. The order is deliberate and it is the order the decisions
        happen in: the rhythm decides whether the family crafts at all,
        `_assign_crafts` writes whichever recipe follows from that, and only
        then is there a smelt errand for this pass to see. Arriving first would
        read a stale `craft_spell` and, worse, would put this pass into the same
        instant as every other writer of `travel_npc`.
        """
        await self.wait_until_ready()
        cycle = float(os.environ.get("CRAFT_FORGE_CYCLE_SECONDS", "300"))
        await asyncio.sleep(min(cycle, 360.0))
        while not self.is_closed():
            try:
                await self._forge_once()
            except Exception:
                log.exception("forge pass failed; retrying next cycle")
            await asyncio.sleep(cycle)

    async def _settle_town_errand(self, names: list, leader: str, town,
                                  work_unasked: bool) -> str:
        """Aim, hold or hand back the town trip's `repair` errand (infra#3728).

        THE OTHER END OF AN ERRAND THAT ONLY EVER HAD ONE. `_towntrip_once`
        wrote `travel_npc = 'repair'` unconditionally, before anything was
        planned, and nothing anywhere ever wrote it back - the same shape
        infra#3708 found in the sell pass, in the same column, four passes deep.
        Measured on wow-dev 2026-09-13: the column was cleared by hand for all
        five at 18:47 and the family walked for the first time in ninety
        minutes; by about 18:52 the leader was re-armed as `repair` from HERE,
        not from the sell pass, and all five had stopped again.

        LIFTED OUT WHOLE, FOR THE REASON `_settle_vendor_errand` GIVES. A draft
        that leaves the release at the bottom of the pass puts it below
        `if not trip.errands: return`, which is the single most likely state for
        a FINISHED trip to be in - nothing left to repair and nothing left to
        buy is exactly what "done" looks like - so the release could never fire
        on the cycles that matter. One question with one answer belongs in one
        place, and the pure side already has that shape in
        `towntrip.errand_step`.

        IT SETTLES ONLY `repair`, AND ONLY THIS PASS'S OWN. `travel_npc` is a
        single slot several passes write and each of them must hand back what it
        wrote: releasing the sell pass's `vendor` from here would be exactly the
        cross-pass theft `_write_trade_errand`'s guard exists to prevent
        (mod-overseer#438), and tests/test_vendor_errand.py pins the mirror of
        this on the other side.

        THE AIM STILL GOES BEFORE ANY ROW THAT NEEDS ONE, which is why this is
        called from above the insert loop rather than after it. What changed is
        that it is no longer written on every cycle whatever the family needs:
        an aim asserted at a counter the family is already standing at makes the
        aim book erase its own state and read a standing errand as brand new,
        and an aim asserted for work already inside the retry window walks them
        to a counter this pass will refuse to queue anything at.
        """
        outstanding = await asyncio.to_thread(_outstanding_town_work, names)
        step = towntrip.errand_step(
            bool(town.repairs), outstanding, work_unasked,
        )
        if step == towntrip.TOWN_ERRAND_AIM:
            # THE RETURN VALUE IS READ, for the reason infra#3464 gave when it
            # was not: `_write_trade_errand`'s economy guard only retasks an
            # IDLE traveller, so this write is a no-op while the sell pass owns
            # `travel_npc = 'vendor'`. That is a legitimate outcome and a
            # starvation worth seeing in the log (infra#3703), not a failure.
            # THROUGH THE TOWN SLOT (infra#3703), which is what turns "the sell
            # pass owns the column" from a permanent answer into a turn.
            aimed = await self._claim_town_slot("towntrip", leader, "repair")
            if not aimed:
                log.info(
                    "towntrip: leader=%s is already on somebody else's errand, "
                    "so no repair aim was taken this pass", leader,
                )
        elif step == towntrip.TOWN_ERRAND_HOLD:
            log.info(
                "towntrip: leader=%s keeps the errand it carries - %s. "
                "Re-asserting one is what makes the world read a standing "
                "errand as a new one", leader,
                "the queue cannot be read" if outstanding < 0 else
                "%d counter row(s) unanswered" % outstanding if outstanding else
                "the rows for this counter are about to be queued",
            )
        else:
            released = await asyncio.to_thread(
                _release_trade_errand, leader, "repair",
            )
            if released:
                log.info(
                    "towntrip: leader=%s has nothing left to ask a counter for "
                    "and every row this trip queued has been answered, so the "
                    "errand is handed back and the family walks again", leader,
                )
            else:
                # Not a failure. The column belongs to somebody else now - a
                # profession errand, or another town pass that won it - and the
                # keyword guard is what stops this pass taking it from them.
                log.debug(
                    "towntrip: leader=%s is not carrying a repair errand, so "
                    "there was nothing to hand back", leader,
                )
        return step

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
        they are still walking sees an empty Town and plans no counter row. The
        cycle after they arrive is the one that queues them. That is why this
        pass needs no state of its own and survives a restart: every step is
        re-derived from the world.

        AND THE ERRAND THAT GETS THEM THERE NOW HAS AN END (infra#3728). It used
        to be written unconditionally at the top of this pass and cleared by
        nobody, which made `travel_npc` a latch with an entry and no exit -
        mod-overseer reaches "errand done, releasing" on arrival and then
        deliberately skips the column write for a maintenance errand its aim book
        never claimed (infra#3655), naming the bridge as the half that clears it.
        `_settle_town_errand` is that half. It is called ABOVE the insert loop so
        the aim still precedes any row that needs one, and above the
        `not trip.errands` return because that return is what a FINISHED trip
        looks like - which is the ordering bug infra#3717 caught in the sell
        pass by running its own sequence model.
        """
        names = sorted((await asyncio.to_thread(_protected_guids)).values())
        if not names or await self._mid_run(names):
            return

        # `_head_now()` RATHER THAN bonds.head_of_family() - same reasoning
        # as the bank pass just above (infra#3553): the leader that can
        # actually be walked to the repair counter is whoever `_head_now`
        # names this cycle, not the family's resting seniority answer, which
        # can be sitting on somebody else's errand right now.
        leader = await asyncio.to_thread(_head_now)

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

        # THE RETRY WINDOW IS READ BEFORE THE ERRAND IS SETTLED NOW, because it
        # is half of the answer to "has this trip anything left to ask for"
        # (infra#3728). `_recent_town_keys` is what already stops a walk that
        # has not finished from filling the queue; the same window is what tells
        # a trip that is FINISHED from one that is about to start, and reading it
        # twice would be two answers to one question.
        seen = await asyncio.to_thread(_recent_town_keys, GIVE_RETRY_MINUTES)
        unasked = [key for key in towntrip.counter_keys(members, trip)
                   if key not in seen]
        await self._settle_town_errand(names, leader, town, bool(unasked))

        if not trip.errands:
            log.info(
                "towntrip: nothing to do at this counter (repairs=%s, %d item(s) stocked)",
                town.repairs, len(town.stocks),
            )
            return

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
        """Apply one typed action from goals.reconcile.

        A TABLE RATHER THAN A CHAIN OF `elif isinstance`, and the change bought
        two things beyond the tangle it untangled (infra#3731). goals.py has
        grown an action kind roughly per epic - StrategyCommand, DriveQuest,
        DriveDungeon, now DriveSkill - and each one used to arrive as another
        limb on a branch that already read past the point a person could hold
        it in their head.

        THE UNHANDLED ACTION IS NOW LOUD, which the chain could not be. A
        `goals.reconcile` that emitted a kind this method did not name fell off
        the end of the `elif` chain and did nothing at all, silently, for ever -
        a correct mechanism with no caller, which is this repository's single
        most repeated failure. That is exactly how `DriveSkill` could have
        shipped inert; tests/test_goals.py walks BOTH modules' ASTs and fails
        when reconcile can emit something this table does not name, because
        neither the chain nor the table can be trusted to notice on its own.

        EXACT TYPE AND NOT isinstance, deliberately. Every goals action is a
        concrete frozen dataclass and none subclasses another, so the two agree
        today - and a dict keyed on exact type means a future action that DID
        subclass an existing one would land in the warning below rather than
        being quietly handled as its parent, which is the safer way round.
        """
        handlers = {
            goals.StrategyCommand: self._goal_strategy,
            goals.DriveQuest: self._goal_drive_quest,
            goals.DriveSkill: self._drive_skill,
            goals.DriveDungeon: self._goal_drive_dungeon,
            goals.MilestoneThought: self._goal_thought,
            goals.Report: self._goal_report,
            goals.RecordProgress: self._goal_record,
            goals.MarkComplete: self._goal_complete,
        }
        handler = handlers.get(type(action))
        if handler is None:
            log.warning(
                "goal %s produced a %s, which nothing here applies - the "
                "action was decided and then dropped on the floor",
                row.get("id"), type(action).__name__,
            )
            return
        await handler(row, action)

    async def _goal_strategy(self, row: dict, action) -> None:
        await asyncio.to_thread(
            _insert_command,
            core.InsertCommand(action.target_name, action.command, "overseer:goal"),
        )

    async def _goal_drive_quest(self, row: dict, action) -> None:
        aimed = await asyncio.to_thread(_aim_traveller, action.quest_id)
        # Logged every time it is renewed, with the count of rows actually
        # written: this project has been burned repeatedly by "delivered"
        # meaning nothing happened, and 0 rows here is the difference
        # between an aim that landed and one that went nowhere.
        log.info("goal: aiming the party at quest %d for %s (%d row(s))",
                 action.quest_id, action.beneficiary, aimed)

    async def _goal_drive_dungeon(self, row: dict, action) -> None:
        # _drive_dungeon is what decides whether bag pressure withholds
        # this cycle; 0 written either means that, or an empty roster, and
        # both are already logged there with the reason.
        await asyncio.to_thread(_drive_dungeon, action.keyword, action.wanted)

    async def _goal_thought(self, row: dict, action) -> None:
        await asyncio.to_thread(
            _insert_thought, action.character_name, "goal", action.text)

    async def _goal_report(self, row: dict, action) -> None:
        channel = self._goal_channel(row)
        if channel is not None:
            await channel.send(action.text[:1990])

    async def _goal_record(self, row: dict, action) -> None:
        await asyncio.to_thread(
            _record_goal_progress, action.goal_id, action.value, action.stalls
        )

    async def _goal_complete(self, row: dict, action) -> None:
        await asyncio.to_thread(_complete_goal, action.goal_id)

    async def _gather_destination(self):
        """Where the family should go to gather, or a Choice saying why not.

        EVERY READ HERE ALREADY EXISTED. `_head_now` is the same leader every
        town errand uses, `_fetch_positions` is what `_forge_once` asks for a
        standing map, and `_fetch_trade_skills` is the one place in this bridge
        that touches `character_skills`. Adding a second reader for any of them
        would be a second answer to a question already answered.

        THE TWO-PHASE SHAPE IS FORCED BY THE DATA. `gatheraim.choose` wants a
        danger reading per candidate, but the only danger reading this database
        can give is a proximity one - `creature.zoneId` is unpopulated for
        144,944 of 150,063 rows - and a proximity reading needs a point, which
        is the candidate itself. So candidates are ranked first, each one's own
        neighbourhood is measured, and the choice is made over the measured
        set. Only the densest few are measured: the ranking is long and each
        reading is a creature scan, so measuring all of them every goal cycle
        would be work about zones the family will never be sent to.
        """
        leader = await asyncio.to_thread(_head_now)
        if not leader:
            return gatheraim.Choice(
                refused="no leader is marked on overseer_roster, so there is "
                        "nobody to aim and no map to aim them on",
                why="no roster lead.")

        names = await asyncio.to_thread(_fetch_enabled_names)
        skills = await asyncio.to_thread(_fetch_trade_skills, names)
        skill_name, value = gatheraim.lowest_gatherer(skills)
        if skill_name is None:
            return gatheraim.Choice(
                refused="nobody enabled on the roster holds mining or "
                        "herbalism, so there is no gathering destination to "
                        "choose - skinning comes off corpses, not nodes",
                why="no aimable gathering skill in the roster.")

        where = (await asyncio.to_thread(_fetch_positions, [leader])).get(leader)
        standing_on = where.get("map_id") if where else None

        rows = await asyncio.to_thread(_fetch_family_levels, names)
        # The WEAKEST character sets the danger ceiling, for the same reason
        # the weakest gatherer sets the band: the family arrives together.
        level = min(rows.values()) if rows else 0

        locks = gatherband.reachable_locks(skill_name, value)
        spawns = await asyncio.to_thread(_survey_gather_nodes, leader, locks)

        candidates = gatheraim.fields_in_band(
            spawns, skill_name, value, standing_on)
        zone_levels = {}
        for cand in candidates[:GATHER_DANGER_CANDIDATES]:
            top = await asyncio.to_thread(
                _gather_danger, cand.map_id, cand.spawn.x, cand.spawn.y)
            if top is not None:
                zone_levels[cand.zone_id] = top

        return gatheraim.choose(skills=skills, standing_on=standing_on,
                                spawns=spawns, family_level=level,
                                zone_levels=zone_levels)

    async def _drive_skill(self, row: dict, action) -> None:
        """Turn a skill goal into a profession order, or into the sentence
        saying why there is no order to give (infra#3731).

        THE ADAPTER HALF OF THE FIX. goals.py decided WHEN; this reads the two
        live facts the decision needs - the skill's rank cap and the mode the
        family is standing in - hands them to skillgoal.plan, and applies
        whatever comes back. Nothing is decided here, exactly as nothing is
        decided in `_drive_dungeon`: the pure module owns the reasoning and this
        owns the reads and the writes, which is the seam that lets the reasoning
        be tested without a database.

        THE JOB WRITE GOES THROUGH `_set_job` AND NOTHING ELSE. That is the
        sanctioned path because it asks `jobs.why_not` first, fans out to the
        whole enabled roster rather than to one name, and speaks its own answer.
        A second writer for the `job` column is a mistake this repo has paid for
        more than once, and `skillgoal.plan` is built so that this can only ever
        be an ENTRY into the gather/craft rhythm - once the family is inside it,
        the plan's mode is '' and craft_rhythm keeps sole ownership of the
        alternation. See that module's handover comment for the full argument.

        IT SPEAKS ONLY WHEN THE ACTION SAYS TO. A blocked goal is blocked on
        every cycle by definition - fishing will still have no drive in sixty
        seconds - so narrating it once a minute would bury the channel and teach
        the operator to ignore it. `goals._reconcile_skill` sets `speak` on the
        first sighting and then once every SKILL_BARREN_CYCLES, which is a
        sentence at the moment the goal is set and one every half hour while it
        is stuck. The full verdict is logged at INFO every pass regardless,
        which is where an unattended service is actually read from.
        """
        cap = await asyncio.to_thread(
            _fetch_skill_cap, action.beneficiary, action.skill_id
        )
        standing = craft_rhythm.standing_mode(
            await asyncio.to_thread(_standing_jobs)
        )
        # infra#3789. A GATHERED skill is answerable only with somewhere to
        # stand, and the survey that finds it is a database read - so it
        # happens here and `skillgoal.plan` stays pure. Only gathering pays
        # for the survey: a crafting goal has no use for a node field, and
        # this runs on every goal cycle.
        destination = None
        if skillgoal.shape_for(action.skill_name) == skillgoal.GATHERED:
            destination = await self._gather_destination()

        plan = skillgoal.plan(
            skill_name=action.skill_name,
            skill_id=action.skill_id,
            target=action.target,
            observed=action.observed,
            cap=cap,
            beneficiary=action.beneficiary,
            standing=standing,
            stalls=action.stalls,
            destination=destination,
        )
        log.info("goal: %s", skillgoal.report(plan))

        if plan.mode:
            # `_rhythm_channel` and not `_goal_channel`: this is an automatic
            # job order and its reply belongs where every other automatic one
            # goes, and that helper never returns None - a goal whose Discord
            # channel has been deleted must not take the order down with it.
            await self._set_job(
                core.JobDirective(mode=plan.mode, source="overseer:goal"),
                self._rhythm_channel(),
            )

        said = plan.blocked or plan.stalled
        if said and action.speak:
            await asyncio.to_thread(
                _insert_thought, action.beneficiary, "goal", said
            )
            channel = self._goal_channel(row)
            if channel is not None:
                await channel.send(said[:1990])

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

    async def _resolve_band(self, expression: str) -> tuple[list[str], str]:
        """Read the three live inputs a band needs, and resolve it.

        ONE PLACE, because there are two callers and they must agree. `_muster`
        and `_conjure` both resolve the same expression - `_conjure` to ground
        the inner voice in a real member, `_muster` again afterwards so the
        rows match who is in the world when they are written - and a band that
        resolved in one and refused in the other would make a natural-language
        order to a group behave unlike the same group's raw order.

        `family` is the enabled roster names, which only the "recruits"
        expression reads (see fanout._resolve_recruits). Fetched for every band
        rather than behind a check on the expression, because which inputs an
        expression needs is fanout.py's grammar to know and not this class's.
        It is the same single-table read `_set_job` makes on every job order.
        """
        roster = await asyncio.to_thread(_fetch_roster)
        guild_names = await asyncio.to_thread(_fetch_guild_names)
        family = await asyncio.to_thread(_fetch_enabled_names)
        return fanout.resolve_targets(expression, roster, guild_names, family)

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
        names, reason = await self._resolve_band(d.expression)
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

        if d.mode == raidprep.MODE:
            blocked = raidprep.readiness(await asyncio.to_thread(_raidprep_members))
            if blocked:
                log.info("job: refused mode=%r - nothing to prepare", d.mode)
                await channel.send(("Refusing to set job=raid prep. " + blocked)[:1990])
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
        # Same reasoning for craft, and the same idempotence: _craft_once only
        # re-derives `craft_spell` from each character's current skill, so
        # running it here and again on the next cycle is the same two writes.
        # Without it a family put on job='craft' waits up to CRAFT_CYCLE_SECONDS
        # (default 300) before anybody carries an errand at all.
        #
        # NOT PAIRED WITH A READINESS REFUSAL, unlike train directly above, and
        # that asymmetry is deliberate - see craft.py's own header (infra#3695).
        # Whether a craft can actually happen is a fact only the worldserver
        # holds: `character_spell` omits every recipe mod-playerbots granted at
        # runtime, so a Python guard reading it refuses characters who are
        # crafting successfully at that moment. Driving the errand and letting
        # DriveCraft decide is the honest shape; forecasting its answer is not.
        if d.mode == craft.MODE and written:
            await self._craft_once()
        # Same reasoning for raid prep: drive the shipped sub-passes so a
        # family put on job='raid prep' does not wait a cycle before the mail,
        # craft and guild-bank passes run. Each sub-pass is idempotent.
        if d.mode == raidprep.MODE and written:
            await self._drive_raid_prep()
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

    async def _drive_raid_prep(self) -> None:
        """Make `job = raid prep` mean something: drive the shipped sub-passes.

        THE POSITIVE HALF OF A MODE THAT ONLY EVER HAD A NEGATIVE ONE. Setting
        any non-quest job stands the quest drive down inside the worldserver;
        until this ran, nothing put anything in its place, which is the whole
        of infra#3338. What replaces it is composing the passes this process
        already ships, each one a complete decision module:

          * `_mail_once` collects what is already addressed to the family -
            the reagents and recipes that let the other passes see the world.
          * `_craft_once` re-asserts `craft_spell` from each character's
            current skill, so professions keep progressing toward rank.
          * `_guild_bank_once` deposits gold above each character's float to
            the guild bank, growing the raid-materials fund.

        EACH PASS KEEPS ITS OWN GATE. `_mail_once` refuses when nobody can
        stand at a mailbox (the aim/reach gate of infra#3830); `_craft_once`
        only acts on characters whose `job` is `craft` (DriveCraft's own
        permission); `_guild_bank_once` refuses per-depositor on range. This
        drive does not override those - it is the cadence that lets them run on
        a family whose job is raid prep, not a new opinion about each one.

        A WIRED MODE WITH NOTHING TO DO IS SAID OUT LOUD. The order was
        refused at the moment it was given if there was nothing to prepare, but
        an errand that COMPLETES leaves the family on a mode with no work in
        it - and that is the idle #3338 is about, arrived at from the other
        side. Logged at warning rather than silently returned, because the
        answer is a person deciding what they should do instead.
        """
        try:
            members = await asyncio.to_thread(_raidprep_members)
            plan = raidprep.plan(members, mail_items=0)
            if not plan.why_not:
                log.info("%s", raidprep.report(plan))
            # Run the shipped sub-passes. None of them decides anything about
            # job; they act on the world and each carries its own refusal.
            await self._mail_once()
            await self._craft_once()
            await self._guild_bank_once()
        except Exception:
            # LOUD, AND STILL NOT FATAL, mirroring _drive_train: an exception
            # escaping here would cost the protect cycle that runs it. The
            # next cycle re-asserts the aim, and this call site has nothing to
            # roll back.
            log.exception("raid prep drive failed; the family keeps its current aim")

    async def _reconcile_learn_aims(self) -> None:
        """Finish a learn errand that is over, and walk one that nobody is on.

        THE FLAG OUTLIVES THE ERRAND AND NOTHING INSIDE THE WORLDSERVER CAN
        NOTICE (infra#3686). `overseer_roster.learn_skill` is cleared in
        exactly one place - mod-overseer's `ClearLearnAim`, reached only from
        `TrainOnArrival` - so a character must ARRIVE at a trainer to clear it,
        and `TravelAimBook::Claim` refuses EVERY travel aim while it is set.
        The gate is behind the fence it is the gate for. One character sat like
        that for ten days, its aim refused 359 times in six hours, while the
        family waited twenty minutes for it and then walked off without it.

        THE AIM IS THE HALF THAT MATTERS MORE. Clearing throws an instruction
        away; aiming carries it out and lets `TrainOnArrival` reach its own
        verdict - including the verdicts this side cannot reach, because only a
        trainer standing in front of a character knows whether it has a next
        tier to sell (mod-overseer#74). learnaim.plan says which rows get
        which, and it never does both to the same row.

        RUN AFTER `_write_declared_professions` AND AFTER `_mark_party_leader`,
        and both orderings are load-bearing. The first writes the `professions`
        permission one of learnaim's two clear reasons is measured against; the
        second writes the `lead` column the aim is gated on, so the aim lands
        on the character the worldserver is about to let walk rather than on
        one this pass merely believes should.

        LOUD, AND STILL NOT FATAL, for the reason `_drive_train` gives one
        screen up: this sits in the middle of the protect cycle, so an
        exception escaping here would cost the spec tabs and the randomize
        guards that come after it. Nothing here has anything to roll back, and
        the next cycle re-reads the same rows.
        """
        try:
            rows = await asyncio.to_thread(_learn_aim_rows)
            learn_plan = learnaim.plan(rows)
            if not (learn_plan.clear or learn_plan.aim or learn_plan.waiting):
                return
            landed = await asyncio.to_thread(
                _run_learn_aim_plan, learnaim.statements(learn_plan)
            )
            # WARNING WHEN SOMETHING WAS WRITTEN, and INFO when the only news
            # is that somebody is waiting for the lead. A row this pass acts on
            # is a character that had been fenced out of ALL travel - a fault
            # that happened, not a tidy-up that succeeded, and the number worth
            # watching is how often it keeps happening once the fence itself is
            # narrowed (quadseven/mod-overseer#453). A wait is the ordinary
            # one-traveller queue, and at warning it would be the loudest line
            # in the log while being the least urgent.
            say = log.warning if (learn_plan.clear or learn_plan.aim) else log.info
            say("%s (%d row(s) changed)", learnaim.report(learn_plan), landed)
        except Exception:
            log.exception(
                "learn-aim reconcile failed; an errand may still be fencing a "
                "character out of all travel until the next cycle"
            )
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
        names, reason = await self._resolve_band(d.expression)
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
            # goals.KIND_COLUMN, not a hardcoded literal, and that is the
            # fix and not a style choice. This exact string was the trap the
            # comment two lines down describes: it was hand-kept in sync with
            # GOAL_KINDS once already for 'quest' and stayed one kind behind
            # again the moment 'dungeon' was added the same way. Reading the
            # constant means the CREATE and the migration can never drift
            # apart a second time.
            " kind " + goals.KIND_COLUMN + ","
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
        if row["kind"] == "dungeon":
            # dungeon_runs_done is written to EVERY enabled roster row alike
            # (decree.py's own campaign-counter comment explains why: the
            # coordinator counts against whoever leads, and the count does not
            # travel with the crown), so the beneficiary's own row is as good
            # a read as any other enabled member's. A missing row - a realm
            # whose overseer_roster predates the campaign columns, or the
            # character has never been enabled - is "cannot be seen", not
            # zero runs done.
            try:
                cur.execute(
                    "SELECT dungeon_runs_done FROM overseer_roster "
                    "WHERE name = %s",
                    (row["character_name"],),
                )
            except pymysql.err.MySQLError as exc:
                if exc.args and exc.args[0] in (1054, 1146):
                    return None
                raise
            found = cur.fetchone()
            return int(found["dungeon_runs_done"]) if found else None
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


def _fetch_skill_cap(name: str, skill_id: int) -> int:
    """`character_skills.max` for one character's skill, or 0 when unreadable.

    THE RANK CEILING, AND IT IS A DIFFERENT COLUMN FROM THE ONE `_observe_goal`
    READS. `.value` is what the character has earned; `.max` is the rank they
    have bought - 75 for Apprentice, 150 Journeyman, 225 Expert - and the engine
    will not let `.value` exceed it by a single point. A skill goal targeting
    above the cap is therefore a goal that can only park where it is, and
    skillgoal.plan refuses it out loud rather than letting it sit on job='craft'
    for ever reporting health. That is the same bug this whole change is about,
    one layer along, so it gets its own read rather than an assumption.

    0 FOR AN ABSENT ROW, NOT AN ERROR, and skillgoal treats 0 as "not read" and
    declines to make a cap argument from it. A character who has never held the
    skill has no row at all, and inferring a ceiling of zero from that would
    refuse every goal for a trade somebody is about to learn.

    Lags like every other `character_skills` read - PlayerSaveInterval is 900
    seconds - and the lag is harmless here for a reason worth stating: a rank is
    bought once and then never moves, so a stale `.max` is wrong only in the
    window between a purchase and the next save, and it is wrong in the
    direction that refuses a goal the family could now pursue. It says so; it
    does not act.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT cs.max FROM character_skills cs "
            "JOIN characters c ON c.guid = cs.guid "
            "WHERE c.name = %s AND cs.skill = %s",
            (name, int(skill_id)),
        )
        found = cur.fetchone()
        return int(found["max"]) if found else 0


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
    # Spark-authored: qwen3-coder-next:q8_0 on a DGX Spark,
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


# Every stack in the family's bags this module is allowed to move outward
# (infra#3908). Deliberately a WIDER item filter than _HOLDINGS_SQL's
# `it.name IN (...)` and a NARROWER one than "everything carried".
#
# The name list works for `materials.REAGENTS` because that table is six rows
# a person wrote after looking in five characters' bags. It cannot work here:
# the point of this pass is items nobody has looked at, so the filter has to
# be a property the world database states about every item that will ever
# exist. `it.class` and `it.subclass` are that property.
#
# `it.bonding = 0` IS IN THE QUERY AND ALSO IN `guildshare.shareable`, AND THE
# DUPLICATION IS DELIBERATE. In SQL it keeps the result set small; in Python
# it is the rule a test can hold. A bound item cannot be given by anybody to
# anybody, and this pass must never be the reason the family lost a piece of
# gear, so it is worth stating twice and cheap to.
#
# The `NOT (ci.bag = 0 AND ci.slot < 19)` exclusion is _HOLDINGS_SQL's, for
# _HOLDINGS_SQL's reason: that range is worn equipment, not carried stock.
_GUILD_SURPLUS_SQL = (
    "SELECT c.name AS holder, it.name AS item, it.entry AS entry, "
    "       ii.count AS count, ii.guid AS item_guid, "
    "       it.class AS item_class, it.subclass AS subclass, "
    "       it.bonding AS bonding, it.RequiredSkill AS required_skill, "
    "       it.RequiredSkillRank AS required_rank, "
    "       it.RequiredLevel AS required_level "
    "FROM character_inventory ci "
    "JOIN characters c                  ON c.guid = ci.guid "
    "JOIN item_instance ii              ON ii.guid = ci.item "
    "JOIN acore_world.item_template it  ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s) "
    "  AND NOT (ci.bag = 0 AND ci.slot < 19) "
    "  AND it.bonding = 0 "
    "  AND (it.class = 7 OR (it.class = 0 AND it.subclass IN (1, 2, 7)))"
)


def _fetch_guild_surplus(names: list) -> list:
    """guildshare.Holding for every stack the family could hand outward."""
    if not names:
        return []
    sql = _GUILD_SURPLUS_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        return [
            guildshare.Holding(
                holder=row["holder"], item=row["item"],
                entry=int(row["entry"]), count=int(row["count"]),
                guid=int(row["item_guid"]),
                item_class=int(row["item_class"]),
                subclass=int(row["subclass"]),
                bonding=int(row["bonding"] or 0),
                required_skill=int(row["required_skill"] or 0),
                required_rank=int(row["required_rank"] or 0),
                required_level=int(row["required_level"] or 0),
            )
            for row in cur.fetchall()
        ]


# The guild the family is in, and everyone else in it - the same widening
# `map_server._RAID_GUILD` does for raid seating (mod-overseer#464), and
# deliberately the same shape rather than a second way to ask the question.
#
# THE GUILD IS FOUND THROUGH THE FAMILY AND IS NEVER NAMED HERE. A literal
# guildid would be one more thing to change the day the family joins a
# different guild, and `guild_member` already knows the answer.
#
# PRESENCE COMES FROM `overseer_snapshot`, NOT FROM `characters.online`. That
# is this service's rule everywhere else (_fetch_roster, _fetch_grounding, and
# ~20 more) and it is the right one here for a measured reason: the snapshot
# carried a fresh row for all 106 characters in the world when this was
# written, recruits included, so the wider guild costs no new presence
# mechanism at all. A LEFT JOIN on the freshness window, so a member with no
# fresh row reads as absent rather than dropping out of the roster - the
# difference between "they are not here" and "we did not ask about them",
# which guildshare.plan needs to keep apart.
_GUILD_ROSTER_SQL = (
    "SELECT c.name AS name, c.class AS class_id, c.level AS level, "
    "       (s.name IS NOT NULL) AS online "
    "FROM guild_member gm "
    "JOIN characters c ON c.guid = gm.guid "
    "LEFT JOIN overseer_snapshot s ON s.name = c.name "
    "     AND s.updated_at > NOW() - INTERVAL 60 SECOND "
    "WHERE gm.guildid IN (SELECT gm2.guildid FROM guild_member gm2 "
    "                     JOIN characters c2 ON c2.guid = gm2.guid "
    "                     WHERE c2.name IN (%s))"
)

# What each of them can actually do. `character_skills` IS authoritative for
# skill LINES, which is a narrower claim than it looks and is why this read is
# safe where a `character_spell` read would not be: a playerbot's runtime
# granted RECIPES never persist, so that table is permanently wrong about what
# a recruit knows how to make. This asks only "do they carry Tailoring, and at
# what rank", which is exactly what the table does record.
_GUILD_SKILLS_SQL = (
    "SELECT c.name AS name, cs.skill AS skill, cs.value AS value "
    "FROM guild_member gm "
    "JOIN characters c ON c.guid = gm.guid "
    "JOIN character_skills cs ON cs.guid = c.guid "
    "WHERE gm.guildid IN (SELECT gm2.guildid FROM guild_member gm2 "
    "                     JOIN characters c2 ON c2.guid = gm2.guid "
    "                     WHERE c2.name IN (%s)) "
    "  AND cs.skill IN (%s)"
)


def _fetch_guild_roster(names: list) -> list:
    """guildshare.Member for everyone sharing a guild with the family.

    Two reads and not one per member: the cross product of forty characters
    against fourteen skill lines is one query, the same batching discipline
    the recap and the dungeon plan already hold themselves to.

    Degrades to "no guild" rather than raising when `guild_member` is missing,
    the direction `_wide_guarded` takes on the map-server side: a realm image
    without the table is a family that shares with nobody, which is exactly
    what this service did before this pass existed.
    """
    if not names:
        return []
    marks = ",".join(["%s"] * len(names))
    skill_ids = sorted(guildshare.SKILL_LINES.values())
    family = set(names)
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(_GUILD_ROSTER_SQL % marks, names)
            rows = list(cur.fetchall())
            cur.execute(
                _GUILD_SKILLS_SQL % (marks, ",".join(["%s"] * len(skill_ids))),
                list(names) + skill_ids,
            )
            skills: dict = {}
            for row in cur.fetchall():
                skills.setdefault(row["name"], {})[int(row["skill"])] = int(
                    row["value"] or 0
                )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("guildshare: no guild tables on this realm - "
                            "the family shares with nobody")
                return []
            raise
    return [
        guildshare.Member(
            name=row["name"], class_id=int(row["class_id"] or 0),
            level=int(row["level"] or 0), skills=skills.get(row["name"], {}),
            online=bool(row["online"]), family=row["name"] in family,
        )
        for row in rows
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
    "ii.itemEntry AS entry, "
    "it.name AS name, it.Quality AS quality, it.SellPrice AS sell_price, "
    # The two columns disposition's trade-tool gate reads (infra#3709). The
    # bit is handed over raw and read in disposition rather than in SQL, the
    # same rule _SURPLUS_GEAR_SQL already states for `ii.flags`.
    "it.class AS item_class, it.BagFamily AS bag_family, "
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
    "it.class AS item_class, it.subclass AS item_subclass, "
    # The trade-tool gate again (infra#3709). Quality 1 keeps every tool the
    # family owns TODAY below this query's own `Quality >= 2` floor, so the
    # junk half of the pass is where that bug actually lives - but Finkle's
    # Skinner and Brann's Trusty Pick are real, lootable, uncommon-or-better
    # trade tools, and the two halves of one pass must not answer differently
    # about the same pick.
    "it.BagFamily AS bag_family, "
    "it.ItemLevel AS item_level, "
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


# Carried RECIPES, and a separate query on purpose (infra#3731).
#
# WHY NOT JUST WIDEN `_SURPLUS_GEAR_SQL` TO `class IN (2, 4, 9)`. That one read
# feeds three consumers - `family_fits`, `gear_candidates` and `family_gifts` -
# and every one of them judges by slot and item level. Class 9 would have been
# harmless in all three (a recipe answers UNJUDGEABLE, which keeps it), but
# "harmless today" is exactly the kind of silent input change that the next
# person to touch a slot rule has no way to see. A recipe is a different
# question with a different claimant, so it gets its own read and its own pass.
#
# THE COLUMN THAT MATTERS IS `RequiredSkill`, which is the skill line the
# recipe teaches into and the whole basis of the claim. `ii.flags` comes along
# for the same reason it does on the gear query: a recipe that has been used is
# soulbound on the INSTANCE while its template still reads bonding 0, and only
# the instance can say so. Same bag-and-backpack scope as the other two, so
# nothing equipped and nothing already banked is offered.
_SURPLUS_RECIPES_SQL = (
    "SELECT c.name AS holder, ii.guid AS item_guid, ii.itemEntry AS entry, "
    "ii.count AS count, ii.flags AS instance_flags, it.name AS name, "
    "it.Quality AS quality, it.SellPrice AS sell_price, it.bonding AS bonding, "
    "it.class AS item_class, it.BagFamily AS bag_family, "
    "it.RequiredSkill AS required_skill, "
    "it.RequiredSkillRank AS required_skill_rank "
    "FROM character_inventory ci "
    "JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s) AND ((ci.bag = 0 AND ci.slot BETWEEN 19 AND 38) "
    "OR ci.bag IN (SELECT bag.item FROM character_inventory bag "
    "WHERE bag.guid = ci.guid AND bag.bag = 0 AND bag.slot BETWEEN 19 AND 22)) "
    "AND it.class = 9 AND it.RequiredSkill > 0"
)


def _fetch_surplus_recipes(names: list) -> list:
    """Read carried recipes; every route decision stays in bag_pressure."""
    if not names:
        return []
    sql = _SURPLUS_RECIPES_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
        except pymysql.err.MySQLError as exc:
            # Same two codes the gear read forgives, for the same reason: on a
            # world image without `item_instance.flags` this side cannot tell a
            # used recipe from a fresh one, and an empty list keeps everything.
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("carried recipe facts unavailable on this world image")
                return []
            raise
        return [dict(row) for row in cur.fetchall()]


def _recipe_holders_by_skill(skills=None) -> dict:
    """Skill line id -> master followed by eligible backup crafters.

    Built from `professions.ROSTER` through `professions.skill_id` so the
    roster is spelled once. `bag_pressure.recipe_gifts` takes this rather than
    importing professions itself, the same seam `disposition.profession_keeps`
    already uses for `worked` and `named`.

    PRIMARIES ONLY, AND THAT IS A REFUSAL RATHER THAN AN OVERSIGHT. Nobody is
    "assigned" First Aid, Cooking or Fishing - all five hold them - so a
    Manual: Strong Anti-Venom has no single claimant and answers
    LEARNER_NOBODY, which keeps it exactly where it is. The family carries
    three of those today. Handing them to an arbitrary member would be this
    module inventing a roster the roster does not contain, and the fail-closed
    direction for a claim nobody can name is to move nothing.
    """
    out = {}
    for name in professions.ROSTER:
        for trade in professions.assigned(name):
            try:
                out[professions.skill_id(trade)] = [name]
            except KeyError:
                # A trade with no id in goals.SKILL_IDS names no skill line,
                # so it can claim nothing. Skipped rather than guessed at.
                continue
    # Backups are observed holders, never invented skill grants. The assigned
    # master remains first even when a backup currently has a higher rank.
    for skill_id, names in out.items():
        observed = []
        for name, values in (skills or {}).items():
            rank = int(values.get(int(skill_id), 0) or 0)
            if rank > 0 and name not in names:
                observed.append((rank, name))
        names.extend(name for _, name in sorted(observed, key=lambda x: (-x[0], x[1])))
    return {skill: tuple(names) for skill, names in out.items()}


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


# Where each of the family is standing, and therefore whether they are in the
# world at all - the two facts that decide whether a hand-off can land.
#
# POSITION COMES FROM overseer_snapshot AND NOT FROM `characters`, the same
# rule _TOWN_COUNTERS_SQL states and for the same reason: the characters row
# is written on the player-save timer and can be a quarter of an hour stale,
# which here would mean trading with somebody who logged out ten minutes ago.
# The freshness filter is also what makes this ONE read answer both
# questions: a character who is not online has no fresh row, so a name
# missing from the result is a name nobody can hand anything to.
# The family's levels, for the gathering level guard only (infra#3789).
#
# NOT folded into _FAMILY_POSITION_SQL, which `gear.spots_from_rows` also
# reads: widening a shared SELECT to serve one new caller makes every other
# caller carry a column it has no use for, and the next person trimming that
# SELECT cannot tell which column anybody still needs. The freshness window is
# the same 60 seconds for the same reason - a level read from a stale snapshot
# is a level guard judging a family that has since moved.
_FAMILY_LEVEL_SQL = (
    "SELECT name, level FROM overseer_snapshot "
    "WHERE name IN (%s) AND updated_at > NOW() - INTERVAL 60 SECOND"
)


def _fetch_family_levels(names: list) -> dict:
    """name -> level for whoever has a fresh snapshot row. Never None."""
    if not names:
        return {}
    sql = _FAMILY_LEVEL_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                return {}
            raise
        return {row["name"]: int(row["level"]) for row in cur.fetchall()
                if row.get("level") is not None}


_FAMILY_POSITION_SQL = (
    "SELECT name, map_id, pos_x, pos_y FROM overseer_snapshot "
    "WHERE name IN (%s) AND updated_at > NOW() - INTERVAL 60 SECOND"
)


def _fetch_positions(names: list) -> dict:
    """name -> its snapshot row; gear.spots_from_rows decides what it means.

    Returns a MAPPING and never None, because None means "nobody asked" to
    `gear.deliverable` and this function has asked. An empty result is the
    honest answer that nobody is visible, and it withholds every hand-off -
    which is right: both DoGive and DoTrade refuse an offline receiver.
    """
    if not names:
        return {}
    sql = _FAMILY_POSITION_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("position facts unavailable on this world image")
                return {}
            raise
        return {row["name"]: dict(row) for row in cur.fetchall()}


# Which item entry each trade's OWN recipes send somebody to a vendor for,
# derived from the two tables that already hold it rather than restated here
# (infra#3709). `craft.RECIPES` is keyed by skill id and names the spells;
# `craft_supply.REAGENT`/`REAGENTS` name what each of those spells has to buy.
# Joining them is the only way to get "Empty Vial belongs to Alchemy" without
# writing a third copy of a fact that already exists twice - and a third copy
# is a third thing that can disagree.
#
# THIS IS WHY THE ITEM'S OWN BAG IS NOT ENOUGH. Empty Vial (3371) is bagged as
# INSCRIPTION supplies, which `professions.UNASSIGNED` says nobody here works,
# so the bag alone would sell the alchemist's vials - see disposition's
# PROFESSION_BAGS block. One entry can be claimed by two trades (Coarse Thread
# is bought for Tailoring's Linen Belt and Leatherworking's gloves), so the
# value is a tuple and any worked claim is enough to keep it.
def _reagent_trades() -> dict:
    """entry -> the trades whose own recipes buy it, from the craft tables."""
    claims: dict = {}
    for skill_id, recipes in craft.RECIPES.items():
        trade = _SKILL_NAMES.get(skill_id, "")
        if not trade:
            continue
        for recipe in recipes:
            bought = list(craft_supply.REAGENTS.get(recipe.spell_id, ()))
            single = craft_supply.REAGENT.get(recipe.spell_id)
            if single:
                bought.append(single)
            for reagent in bought:
                claimed = claims.setdefault(int(reagent[0]), [])
                if trade not in claimed:
                    claimed.append(trade)
    return {entry: tuple(trades) for entry, trades in claims.items()}


REAGENT_TRADES = _reagent_trades()


def _fetch_vendor_items(names: list) -> list:
    """Read carried sale facts; all routing remains in bag_pressure."""
    if not names:
        return []
    sql = _VENDOR_ITEMS_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        rows = [dict(row) for row in cur.fetchall()]
    # THE FAMILY'S OWN TRADE STOCK IS NOT VENDOR GOODS (infra#3709). The
    # declared roster is the permission - `professions.assigned` is the end
    # state the family is being walked towards, and a miner still on his way
    # to a trainer must not have his pick sold on the journey. Measured live
    # 2026-09-13: this is what sold Grug's Mining Pick and Blacksmith Hammer
    # eight times each, Bork's Skinning Knife four times, and Ugga's 25 Empty
    # Vials ten minutes after craft_supply bought them.
    worked = {trade for name in names for trade in professions.assigned(name)}
    keeps = disposition.profession_keeps(
        rows, worked=worked, named=REAGENT_TRADES,
    )
    for item in rows:
        # Trade goods such as Linen are class 7, not class 5. The
        # profession roster is the stronger fact and must protect them
        # even when item_template calls them ordinary trade goods.
        profession_material = item.get("name") in materials.REAGENTS
        item["reagent"] = bool(item.get("reagent")) or profession_material
        item["profession_needed"] = bool(
            profession_material or item.get("item_guid") in keeps
        )
    summary = bag_pressure.protection_counts(rows)
    log.info(
        "economy: carried inventory protection summary rows=%d quest=%d "
        "reagent=%d profession=%d rare_or_better=%d unknown=%d",
        summary["rows"], summary["quest"], summary["reagent"],
        summary["profession"], summary["rare_or_better"], summary["unknown"],
    )
    if keeps:
        # Said out loud, because a protection nobody can see in the log is
        # indistinguishable from one that never fired. It counts every stack
        # the rule CLAIMS, not every sale it prevented - most of these would
        # have been refused by quality or price anyway, and pretending
        # otherwise would overstate what this gate does.
        log.info("economy: %d carried stack(s) are the family's own trade "
                 "stock and are not vendor goods: %s", len(keeps),
                 "; ".join(sorted(set(keeps.values()))))
    return rows


# The four bags each holder has EQUIPPED right now (bag 0, slots 19-22), read
# for their ContainerSlots alone (infra#4163). `bag_pressure.bag_candidates`
# never touches an equipped bag itself - this is only the yardstick it uses
# to tell a redundant spare from an upgrade nobody has worn yet.
_EQUIPPED_BAG_SLOTS_SQL = (
    "SELECT c.name AS holder, it.ContainerSlots AS container_slots "
    "FROM character_inventory ci "
    "JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s) AND ci.bag = 0 AND ci.slot BETWEEN 19 AND 22 "
    "AND it.class = 1"
)


def _fetch_equipped_bag_slots(names: list) -> dict:
    """holder -> the ContainerSlots of every bag they have equipped now.

    A holder missing from the result has no known equipped bags, and
    `bag_candidates` keeps everything of theirs rather than guess a size to
    compare against - the same fail-closed shape `_fetch_family_equipped`
    already states for worn gear.
    """
    if not names:
        return {}
    sql = _EQUIPPED_BAG_SLOTS_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("equipped bag facts unavailable on this world image")
                return {}
            raise
        rows = cur.fetchall()
    out: dict = {}
    for row in rows:
        out.setdefault(row["holder"], []).append(int(row["container_slots"]))
    return {holder: tuple(sizes) for holder, sizes in out.items()}


# Carried CONTAINERS (class 1) that are not equipped right now: the exact
# complement of `_EQUIPPED_BAG_SLOTS_SQL`'s scope (infra#4163). Slots 19-22
# are deliberately excluded here - that range is where the equipped bags
# THEMSELVES sit, and this query is only for the ones nobody is using.
_SURPLUS_BAGS_SQL = (
    "SELECT c.name AS holder, ii.guid AS item_guid, ii.count AS count, "
    "ii.flags AS instance_flags, it.name AS name, it.Quality AS quality, "
    "it.SellPrice AS sell_price, it.bonding AS bonding, "
    "it.class AS item_class, it.ContainerSlots AS container_slots "
    "FROM character_inventory ci "
    "JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s) AND it.class = 1 AND ("
    "(ci.bag = 0 AND ci.slot BETWEEN 23 AND 38) "
    "OR ci.bag IN (SELECT bag.item FROM character_inventory bag "
    "WHERE bag.guid = ci.guid AND bag.bag = 0 AND bag.slot BETWEEN 19 AND 22))"
)


def _fetch_surplus_bags(names: list) -> list:
    """Read carried-but-unequipped bag facts; bag_pressure decides the route."""
    if not names:
        return []
    sql = _SURPLUS_BAGS_SQL % ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("surplus bag facts unavailable on this world image")
                return []
            raise
        return [dict(row) for row in cur.fetchall()]


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


# Hoisted for the same reason as _BOT_HELD_SQL: ruff anchors S608 at the START
# of the expression, so a noqa on the line carrying the % does not silence a
# multi-line query. Only the NUMBER of placeholders is interpolated; every name
# reaches MySQL as a bound parameter.
_OUTSTANDING_SALES_SQL = (
    "SELECT COUNT(*) AS waiting FROM overseer_command "
    "WHERE kind = 'sell' AND status IN ('pending', 'claimed') "
    "AND target_name IN (%s)"
)


def _outstanding_sales(names: list) -> int:
    """Sell rows the world still owes an answer on, or -1 if it cannot be read.

    THE ONE FACT THAT ENDS A VENDOR ERRAND (infra#3708). Everything else about a
    trip is a guess from outside: where the leader stands is a snapshot, the bags
    are a save timer minutes behind, and "it looks finished" would have released
    an errand that was still selling. An empty queue is not a guess - the rows
    were written by this pass and answered by the world.

    `pending` AND `claimed` ARE THE WHOLE OF "UNANSWERED". `delivered`, `error`,
    `applied`, `unchanged` and `verifying` are all answers, refusals included.
    Counting the answered ones would hold the errand open on the 17,536 all-time
    `vendor not in range` rows for ever, which is the same latch one table over.

    -1 IS "COULD NOT MEASURE" AND IT IS NOT ZERO. Returning 0 on a failed read
    would make an unreadable database look exactly like a finished errand, which
    is the fail-open direction; `vendor_errand_step` holds on any non-zero.
    """
    if not names:
        return 0
    placeholders = ",".join(["%s"] * len(names))
    sql = _OUTSTANDING_SALES_SQL % placeholders  # noqa: S608 - placeholders from a COUNT, values still bound
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
            row = cur.fetchone()
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning(
                    "economy: cannot read the sell queue, so no vendor errand "
                    "is handed back this pass"
                )
                return -1
            raise
    return int(row["waiting"] or 0) if row else 0


# The town trip's own version of the query above, and the two differences from
# it are both deliberate (infra#3728).
#
# SCOPED TO source='towntrip', exactly as `_recent_town_keys` is and for the
# same reason: the materials and bag passes write kind='give' rows of their own,
# and a count that could not tell them apart would hold the repair errand open
# on somebody else's hand-off.
#
# AND SCOPED TO THE KINDS A COUNTER SERVES. towntrip.COUNTER_KINDS is repair and
# buy; conjure and give are free, work anywhere, and are not what the travel
# column is for. The kinds are bound rather than written into the string so that
# the vocabulary stays towntrip's, which is the one place it is tested.
_OUTSTANDING_TOWN_SQL = (
    "SELECT COUNT(*) AS waiting FROM overseer_command "
    "WHERE kind IN (%s) AND source = 'towntrip' "
    "AND status IN ('pending', 'claimed') "
    "AND target_name IN (%s)"
)

# The bank pass's version. No source scope: kind='bank' has exactly one writer
# (`_insert_bank`, which stamps source='economy'), so there is nothing to tell
# apart, and adding a scope that could drift from the insert would be a filter
# that silently counts nothing.
_OUTSTANDING_BANK_SQL = (
    "SELECT COUNT(*) AS waiting FROM overseer_command "
    "WHERE kind = 'bank' AND status IN ('pending', 'claimed') "
    "AND target_name IN (%s)"
)


def _outstanding_counts(sql: str, kinds: tuple, names: list, what: str) -> int:
    """Rows the world still owes an answer on, or -1 if it cannot be read.

    THE SIBLING OF `_outstanding_sales`, GENERALISED ONLY AS FAR AS IT HONESTLY
    GOES (infra#3728). Every argument that function makes applies here word for
    word - `pending` and `claimed` are the whole of "unanswered", every other
    status is an answer including a refusal, and -1 is "could not measure" and
    is emphatically not 0 - so repeating them in two more docstrings would be
    three copies of one rule. What differs between the three callers is only
    WHICH rows belong to the errand being settled, which is what `sql` and
    `kinds` say. `_outstanding_sales` keeps its own body because its query takes
    no kind list and its S608 argument is pinned by name in
    tests/test_vendor_errand.py.

    EVERY VALUE STILL REACHES MYSQL AS A BOUND PARAMETER. What is interpolated
    is a run of `%s` placeholders whose count comes from `len(kinds)` and
    `len(names)`; the kinds come from `towntrip.COUNTER_KINDS` and the names from
    `_protected_guids`, and both are passed to `cur.execute` as parameters.
    """
    if not names:
        return 0
    marks = [",".join(["%s"] * len(kinds))] if kinds else []
    marks.append(",".join(["%s"] * len(names)))
    statement = sql % tuple(marks)  # noqa: S608 - placeholders from a COUNT, values still bound
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(statement, (*kinds, *names))
            row = cur.fetchone()
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table, 1265 a `kind` ENUM this
            # world image does not carry. A queue that cannot be read is not a
            # finished errand.
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                log.warning(
                    "economy: cannot read the %s queue, so no errand is handed "
                    "back this pass", what,
                )
                return -1
            raise
    return int(row["waiting"] or 0) if row else 0


def _outstanding_town_work(names: list) -> int:
    """Counter-bound town-trip rows still unanswered, or -1 if unreadable."""
    return _outstanding_counts(
        _OUTSTANDING_TOWN_SQL, towntrip.COUNTER_KINDS, names, "town trip",
    )


def _outstanding_bank_moves(names: list) -> int:
    """Bank rows still unanswered, or -1 if the queue cannot be read."""
    return _outstanding_counts(_OUTSTANDING_BANK_SQL, (), names, "bank")


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


def _fetch_live_maps(names: list) -> dict[str, int] | None:
    """Read fresh member locations for stale-run arbitration.

    ``None`` is reserved for a missing or unreadable snapshot table. An empty
    mapping is a successful read that proves nobody in the requested family
    has a fresh world row, which is exactly the evidence needed to release a
    durable run row and let vendor maintenance proceed.
    """
    if not names:
        return {}
    sql = (
        "SELECT name, map_id FROM overseer_snapshot "  # noqa: S608 - placeholders only
        "WHERE updated_at > NOW() - INTERVAL 60 SECOND AND name IN (%s)"
        % ",".join(["%s"] * len(names))  # noqa: S608 - placeholders only
    )
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                return None
            raise
        return {str(row["name"]): int(row["map_id"]) for row in cur.fetchall()}


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


def _recent_guild_gift_keys(minutes: int) -> set:
    """(holder, taker, command) triples this pass already proposed.

    KEYED ON `source` AND NOT ON `kind`, for the reason _recent_trade_keys
    spells out at length: `kind='give'` is now written by three passes, and a
    window shared across them would let one pass silence another's retry.
    `source` is the column that names which pass wrote a row, so it is the one
    that can answer "did I already ask for this".
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT target_name, target_arg, command FROM overseer_command "
            "WHERE source = 'guildshare' "
            "  AND created_at > NOW() - INTERVAL %s MINUTE",
            (int(minutes),),
        )
        return {
            (row["target_name"], row["target_arg"], row["command"])
            for row in cur.fetchall()
        }


def _insert_guild_gift(gift) -> int:
    """One overseer_command row handing one stack to a guildmate (infra#3908).

    THE SAME VERB `materials.py` USES, AND THE SAME ONE `gear.py` FALLS BACK
    TO WHEN THE TWO CHARACTERS ARE APART. Nothing new was needed in C++ for
    this, and that was verified live rather than assumed: four probe gives
    with an unmovable item guid established that `DoGive` refuses on the ITEM
    for a receiver on another continent exactly as it does for one standing
    next to the giver, and refuses on the RECEIVER only when that receiver is
    not in the world. There is no party, guild, roster or distance gate on the
    verb - see guildshare.py's module docstring for the full table.

    ALWAYS `give` AND NEVER `trade`. `gear.deliverable` picks between the two
    on distance because the family is usually standing together; a guildmate
    is not, and the one online recruit measured while this was written was on
    a different continent from every one of the five.

    Guarded on 1265 exactly as `_insert_give` is: a worldserver behind the
    ENUM migration must warn rather than raise.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, 'give', %s, %s)",
                (gift.holder, gift.command, gift.taker, "guildshare"),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] == 1265:
                log.warning(
                    "overseer_command.kind has no 'give' value - handing %d "
                    "%s from %s to %s needs the worldserver image carrying "
                    "mod-overseer's give SQL (infra#2597)",
                    gift.count, gift.item, gift.holder, gift.taker,
                )
                return 0
            raise
        return cur.lastrowid or 0


def _recent_trade_keys(minutes: int) -> set:
    """(holder, taker, command) triples already proposed inside the window.

    Its own reader rather than a widened _recent_give_keys, because the two
    passes have to stay tellable apart: a reagent hand-off and a gear hand-off
    can name the same guid form, and a shared window would let one pass
    silence the other's retry. Degrades to "nothing is queued" on a world
    image with no 'trade' value, the same direction _recent_town_keys takes.

    KEYED ON `source` AND NOT ON `kind`. It read kind='trade' when trade was
    the only verb this pass could write; now that the verb follows where the
    two of them are standing, a gear hand-off issued as a give would have
    been invisible to its own retry window and re-proposed every cycle.
    `source` is the column that actually names the pass, and it is the one
    _insert_gear_handoff has always written.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, target_arg, command FROM overseer_command "
                "WHERE source = 'gear' AND created_at > NOW() - INTERVAL %s MINUTE",
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


def _insert_gear_handoff(grant) -> int:
    """One overseer_command row handing one carried piece to a sibling.

    The giver in target_name, the receiver in target_arg and the
    item_instance guid in the command - the same three roles kind='give'
    already uses, so an operator reading the queue does not have to learn a
    second layout. source='gear' is what separates this from the reagent and
    bag hand-offs in the log and in the retry window above.

    THE KIND IS `grant.verb` AND NOT A LITERAL. Which verb can land is a fact
    about where the two of them are standing, and `gear.deliverable` has
    already looked - see its banner for the 41-of-755 measurement that moved
    this decision out of this function and into a place that can see the
    world. This writes what it was told.

    Guarded on 1265 like every other kind this process writes: a worldserver
    behind mod-overseer's trade migration must warn rather than raise and
    take the whole economy pass down with it.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, %s, %s, %s)",
                (grant.holder, grant.command, grant.verb, grant.taker, "gear"),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1146, 1265):
                log.warning(
                    "overseer_command.kind has no '%s' value - handing %s "
                    "from %s to %s needs the worldserver image carrying "
                    "mod-overseer's trade SQL (mod-overseer#14)",
                    grant.verb, grant.name, grant.holder, grant.taker,
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


def _fetch_guild_money(names: list) -> list:
    """Rows for guildbank.plan_deposits; no judgement and no arithmetic here.

    LIVE BUG, FIXED (infra#3652): this used to read `characters.guildid`,
    which does not exist on this world - confirmed by `DESCRIBE characters`
    against the live wow-dev database, not assumed the way the previous
    docstring's claim was. Guild membership lives in `guild_member` (keyed
    by `guid`), the same table this session already used elsewhere tonight
    to check a character's guild. The crash was silent: `_guild_bank_loop`
    caught the exception every cycle and logged it, so gold sat undeposited
    for hours with no deposit ever queued and nothing surfacing it as
    broken until this session checked the live guild_bank_once traceback
    directly. A LEFT JOIN, not an INNER one - a character with no guild_member
    row is not in a guild, which the query should say plainly (in_guild=0)
    rather than silently drop the row and make a caller wonder if they were
    skipped for a different reason."""
    if not names:
        return []
    marks = ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.name AS name, c.money AS money, "  # noqa: S608 - placeholders from a COUNT, values still bound
            "gm.guildid IS NOT NULL AS in_guild "
            "FROM characters c LEFT JOIN guild_member gm ON gm.guid = c.guid "
            "WHERE c.name IN (%s)" % marks,
            names,
        )
        return [dict(row) for row in cur.fetchall()]


def _fetch_guild_bank_setup(names: list) -> dict | None:
    """Read the persisted guild-bank setup state, or None when unavailable."""
    if not names:
        return None
    marks = ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT gm.guildid FROM guild_member gm "
                "JOIN characters c ON c.guid = gm.guid "
                "WHERE c.name IN (%s) ORDER BY gm.guildid LIMIT 1" % marks,
                names,
            )
            guild = cur.fetchone()
            if not guild:
                return None
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name IN "
                "('guild_bank_tab','guild_bank_right','guild_rank')"
            )
            if len(cur.fetchall()) != 3:
                return None
            guild_id = guild["guildid"]
            cur.execute("SELECT COUNT(*) AS n FROM guild_bank_tab WHERE guildid = %s",
                        (guild_id,))
            purchased = int(cur.fetchone()["n"])
            cur.execute("SELECT rid FROM guild_rank WHERE guildid = %s ORDER BY rid",
                        (guild_id,))
            rank_ids = tuple(int(row["rid"]) for row in cur.fetchall())
            cur.execute(
                "SELECT rid FROM guild_bank_right WHERE guildid = %s "
                "AND TabId = 0 AND (gbright & 3) = 3",
                (guild_id,),
            )
            deposit_ranks = tuple(int(row["rid"]) for row in cur.fetchall())
            return {"purchased_tabs": purchased, "rank_ids": rank_ids,
                    "deposit_rank_ids": deposit_ranks}
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("guild bank setup tables are unavailable")
                return None
            raise


def _recent_guild_setup_keys(minutes: int) -> set[tuple[str, str]]:
    """Commands already queued for tab purchase or rank setup."""
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                # `%%` IS NOT A TYPO. pymysql renders a parameterised query with
                # `query % args`, so every literal percent in the SQL has to be
                # doubled or it is read as a format spec. This LIKE pattern's
                # trailing `%` was bare, which made the whole string demand two
                # arguments when one is passed, and `mogrify` raised
                # `TypeError: not enough arguments for format string` before the
                # query ever reached MySQL. That is also why the handler below
                # did not save it: TypeError is not a `MySQLError`, so it escaped
                # this function and killed the entire guild-bank pass on every
                # cycle - which is why no guild on the realm had ever bought a
                # bank tab (infra#3713).
                "SELECT target_name, command FROM overseer_command "
                "WHERE kind = 'guild' AND created_at > NOW() - INTERVAL %s MINUTE "
                "AND (command = 'bank buy-tab' OR command LIKE 'bank grant-deposit %%')",
                (int(minutes),),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return set()
            raise
        return {(row["target_name"], row["command"]) for row in cur.fetchall()}


# The nearest Guild Vault on the map a character is STANDING ON.
#
# THE SAME SHAPE AS _TOWN_COUNTERS_SQL, AGAINST A DIFFERENT TABLE, and that is
# the whole of infra#3702. The town reader joins overseer_snapshot to
# `acore_world.creature` to find a counter near the leader; a guild bank is not
# a creature on 3.3.5, so this joins the identical snapshot to
# `acore_world.gameobject` instead. Everything else is deliberately unchanged:
# the same live-position source, the same freshness filter, the same reason for
# both (the `characters` row is written on the player-save timer and can be a
# quarter of an hour stale, which here would aim the family at a vault near
# where they USED to be).
#
# `g.map = s.map_id` IS THE SAME-MAP RULE, ENFORCED IN THE JOIN. A vault on
# another continent is not a longer walk - MoveFarTo paths through
# PathGenerator and there is no navmesh across an ocean - so a cross-map spawn
# is not a worse candidate, it is not a candidate. travel.vault_aim re-checks
# it anyway to turn it into a sentence; this is what stops it being found.
#
# ORDERED BY THE SQUARE OF THE DISTANCE, NOT THE DISTANCE. The square root is
# monotonic, so it cannot change which spawn is nearest, and skipping it keeps
# this a plain arithmetic sort. Z is left out of the ranking on purpose: two
# vaults a few yards apart in a bank hall differ by a stair, not by a journey,
# and the walk is planar anyway.
_VAULT_SQL = (
    "SELECT g.map AS map_id, g.position_x AS x, g.position_y AS y, "
    "g.position_z AS z, "
    "(POW(g.position_x - s.pos_x, 2) + POW(g.position_y - s.pos_y, 2)) AS d2 "
    "FROM overseer_snapshot s "
    "JOIN acore_world.gameobject g ON g.map = s.map_id "
    "JOIN acore_world.gameobject_template gt ON gt.entry = g.id "
    "WHERE s.name = %s AND s.updated_at > NOW() - INTERVAL 120 SECOND "
    "AND gt.type = %s "
    "ORDER BY d2 LIMIT 1"
)


def _nearest_vault(name: str):
    """The nearest Guild Vault spawn row on `name`'s own map, or None.

    A ROW OUT OF THE SPAWN TABLE, NOT A COORDINATE THIS PROCESS INVENTED.
    `gameobject.position_x/y/z` is where the world actually put that vault,
    surveyed with the rest of the map, which is what makes it safe to walk to
    - see travel.vault_aim, which turns it into the aim.

    None covers three different absences on purpose - no fresh snapshot row,
    no vault on this map, no gameobject tables at all - because every one of
    them means the same thing to the caller: nobody can be sent to a vault
    this pass. travel.vault_aim is where they are told apart for the log.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(_VAULT_SQL, (name, travel.GUILD_VAULT_GO_TYPE))
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table. A world image with no
            # overseer_snapshot cannot say where anybody is standing, and one
            # with no gameobject tables has no vaults to find; both are
            # honestly "no vault in reach" rather than an error to raise.
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("guild bank: cannot see where the family is standing")
                return None
            raise
        row = cur.fetchone()
        return dict(row) if row else None


# THE MAILBOX QUERY (infra#3741), AND IT IS `_VAULT_SQL` WITH ONE CHANGE.
#
# `gt.type = 19` (GAMEOBJECT_TYPE_MAILBOX) rather than 34, and nothing else:
# same snapshot join, same 120-second freshness filter, same `g.map = s.map_id`
# same-map rule enforced in the JOIN, same squared-distance ordering with z left
# out of the ranking. Every argument in `_VAULT_SQL`'s own comment above applies
# here word for word, which is the point - infra#3741 recorded reaching a
# mailbox as the hard, open part of collecting the post, and the query that
# already walks the family to a Guild Vault answers it with a different WHERE.
#
# NO RADIUS FILTER, UNLIKE `_FORGE_SQL`. A forge is judged by its own `Data1`
# focus radius, which can be narrower than the travel drive's arrival tolerance;
# a mailbox is judged by `WorldSession::CanOpenMailBox`, which asks
# `GetGameObjectIfCanInteractWith` - the core's own interact gate, the same one
# a Guild Vault is judged by. So any spawn will do.
_MAILBOX_SQL = (
    "SELECT g.map AS map_id, g.position_x AS x, g.position_y AS y, "
    "g.position_z AS z, "
    "(POW(g.position_x - s.pos_x, 2) + POW(g.position_y - s.pos_y, 2)) AS d2 "
    "FROM overseer_snapshot s "
    "JOIN acore_world.gameobject g ON g.map = s.map_id "
    "JOIN acore_world.gameobject_template gt ON gt.entry = g.id "
    "WHERE s.name = %s AND s.updated_at > NOW() - INTERVAL 120 SECOND "
    "AND gt.type = %s "
    "ORDER BY d2 LIMIT 1"
)


def _nearest_mailbox(name: str):
    """The nearest mailbox spawn row on `name`'s own map, or None.

    A ROW OUT OF THE SPAWN TABLE, NOT A COORDINATE THIS PROCESS INVENTED - the
    identical guarantee `_nearest_vault` gives, against the identical tables.
    `gameobject.position_x/y/z` is where the world actually put that mailbox,
    surveyed with the rest of the map.

    None covers three different absences on purpose - no fresh snapshot row, no
    mailbox on this map, no gameobject tables at all - because every one of them
    means the same thing to the caller: nobody can be sent to a mailbox this
    pass. `travel.mailbox_aim` is where they are told apart for the log.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(_MAILBOX_SQL, (name, travel.MAILBOX_GO_TYPE))
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table. A world image with no
            # overseer_snapshot cannot say where anybody is standing, and one
            # with no gameobject tables has no mailboxes to find; both are
            # honestly "no mailbox in reach" rather than an error to raise.
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("mail: cannot see where the family is standing")
                return None
            raise
        row = cur.fetchone()
        return dict(row) if row else None


# EVERY LETTER IN THE FAMILY'S MAILBOXES, ONE ROW PER ATTACHMENT.
#
# A LEFT JOIN ONTO `mail_items`, NOT AN INNER ONE, and that is the whole
# difference between this query and the one somebody reaches for first. A letter
# carrying only money has no `mail_items` row at all, and an inner join would
# drop it - which on this realm means dropping the auction house settlement
# sitting on 4,100 copper, the single most valuable thing in any of these
# mailboxes. The fold back into one Letter per id is `mailrun.letters_from_rows`.
#
# `deliver_time <= UNIX_TIMESTAMP()` IS ANSWERED IN SQL, where the clock is.
# The pure module has none, and a Python clock disagreeing with the database's
# would be a second opinion on a question the executor already answers by
# refusing `mail has not been delivered yet`. What is passed across is the
# ANSWER, not the timestamp.
#
# NOTHING IS FILTERED OUT HERE. A COD letter, an undelivered one and an empty
# one are all fetched and all told apart by `mailrun.plan`, which says in a note
# why each was left alone. A WHERE clause would make those three cases
# indistinguishable from an empty mailbox, and "nothing to collect" is the one
# answer this pass must never give by accident.
_MAIL_SQL = (
    "SELECT c.name AS holder, m.id AS mail_id, m.money AS money, "
    "m.cod AS cod, m.expire_time AS expire_time, "
    "(m.deliver_time <= UNIX_TIMESTAMP()) AS delivered, "
    "mi.item_guid AS item_guid "
    "FROM mail m "
    "JOIN characters c ON c.guid = m.receiver "
    "LEFT JOIN mail_items mi ON mi.mail_id = m.id "
    "WHERE c.name IN (%s)"
)


def _fetch_mail(names: list) -> list:
    """Rows for mailrun.letters_from_rows; no judgement and no arithmetic here.

    A missing `mail` or `mail_items` table is an empty mailbox rather than a
    dead pass, the same guard `_recent_bank_keys` gives its own read: a world
    image without the mail schema has nothing to collect, and taking the loop
    down over it would hide every other pass's log behind a traceback.
    """
    if not names:
        return []
    marks = ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(_MAIL_SQL % marks, names)  # noqa: S608 - placeholders from a COUNT, values still bound
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("mail: this world image has no mail tables to read")
                return []
            raise
        return [dict(row) for row in cur.fetchall()]


# THE FORGE QUERY (infra#3748), AND IT IS `_VAULT_SQL` WITH TWO CHANGES.
#
# Same snapshot join, same 120-second freshness filter, same `g.map = s.map_id`
# same-map rule enforced in the JOIN, same squared-distance ordering with z left
# out of the ranking - every argument in `_VAULT_SQL`'s own comment above applies
# here unchanged, which is the point: infra#3617 concluded that walking to a
# spell-focus GameObject "means indexing GameObject spawns the same way
# creatures are indexed today - a new second index", and the answer is that the
# query already written for the Guild Vault answers this one too with a
# different WHERE.
#
# THE TWO CHANGES:
#
#   `gt.type = 8 AND gt.Data0 = 3` rather than `gt.type = 34`. Data0 is the
#   SpellFocusObject id CheckCast matches (3 = Forge); Data1 is the RADIUS.
#   infra#3617 read Data1 as the focus id, which happens to look right because
#   anvils and forges both mostly carry Data1 = 10 - see travel.FORGE_FOCUS_ID
#   for the counts that tell them apart.
#
#   `AND gt.Data1 > %s` - the radius filter, which the vault query has no need
#   of. A Guild Vault is judged by `GuildBankInReach`'s own interact gate, so
#   any spawn will do; a smelt is judged by the FORGE's own focus radius, and
#   the travel drive only promises to land an `at:` aim within
#   TRAVEL_ARRIVED_POSITION_YARDS. Two of this world's 149 forge templates have
#   a radius at or inside that tolerance, so walking to one would leave the
#   smelter outside the focus and CheckCast would refuse every cast - as a bare
#   numeric SpellCastResult at INFO, which reads exactly like a cooldown. A
#   forge that cannot be reliably stood in is not a worse candidate, it is not
#   a candidate, the same reasoning that keeps a cross-map spawn out.
#
# `gt.Data1 AS radius` IS SELECTED AND NOT JUST FILTERED ON, because
# `travel.within_focus` needs it to answer "is this character ALREADY in the
# focus" - a question whose right threshold is per-forge and which a constant of
# ours would get wrong in both directions.
# ---------------------------------------------------------------------------
# WHERE A GATHERING FAMILY SHOULD STAND (infra#3789).
#
# `gatheraim` decides; these two reads are what it decides ON. Both are the
# same shape as `_FORGE_SQL` and for the same reason: a destination has to be a
# row the world was built from, never a coordinate this process computed.
#
# ZONE FILTER, NOT A ZONE JOIN. `gameobject.zoneId` is populated for only
# 38,990 of 96,628 rows on this realm, so `zoneId <> 0` is a filter on what can
# be grouped at all rather than an assumption that it is complete. A node whose
# zone the world never recorded is dropped - it cannot be ranked against the
# others, and inventing a zone for it would be the same class of guess as
# inventing its Z.
_GATHER_NODE_SQL = (
    "SELECT g.map AS map_id, g.zoneId AS zone_id, g.position_x AS x, "
    "g.position_y AS y, g.position_z AS z, gt.Data0 AS lock_id, "
    "gt.name AS name "
    "FROM overseer_snapshot s "
    "JOIN acore_world.gameobject g ON g.map = s.map_id "
    "JOIN acore_world.gameobject_template gt ON gt.entry = g.id "
    "WHERE s.name = %s AND s.updated_at > NOW() - INTERVAL 120 SECOND "
    "AND gt.type = %s AND gt.Data0 IN ({placeholders}) AND g.zoneId <> 0"
)

# THE LEVEL GUARD MEASURES A NEIGHBOURHOOD, NOT A ZONE, because it has to:
# `creature.zoneId` is unpopulated on this realm for 144,944 of 150,063 rows,
# so "the top level in zone 17" is not a number this database can answer. What
# it CAN answer is "the top level within N yards of this exact spawn", which is
# the better question anyway - a zone's average says nothing about the elite
# standing on the vein. A ground `at:` aim early-returns before every level
# check in mod_overseer.cpp (9839-9857), so this is the only guard there is.
_GATHER_DANGER_SQL = (
    "SELECT MAX(ct.maxlevel) AS top, COUNT(*) AS mobs "
    "FROM acore_world.creature c "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "WHERE c.map = %s "
    "AND POW(c.position_x - %s, 2) + POW(c.position_y - %s, 2) < POW(%s, 2)"
)

# How wide a circle around the destination counts as "there". 400 yards is
# roughly the distance a character will wander working a field of nodes, and it
# is wide enough that a quiet pocket inside a dangerous zone does not read as
# safe.
GATHER_DANGER_YARDS = 400

# How many of the densest candidate fields get a danger reading. Each reading
# is a creature-table scan, and the ranking below the top few is academic - the
# family is sent to the densest field that passes, so measuring the twentieth
# is work about a zone nothing will choose.
GATHER_DANGER_CANDIDATES = 5


def _survey_gather_nodes(leader: str, lock_ids):
    """Every in-band node spawn on the leader's own map.

    `lock_ids` is what `gatherband` says this family can open, so the filter is
    applied in SQL rather than in Python - the unfiltered table is 96,628 rows
    and almost none of them are reachable by a Mining 1 character.
    """
    if not lock_ids:
        return []
    placeholders = ",".join(["%s"] * len(lock_ids))
    sql = _GATHER_NODE_SQL.format(placeholders=placeholders)
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, (leader, travel.CHEST_GO_TYPE, *lock_ids))
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return []
            raise
        return [gatheraim.Spawn(
            map_id=int(row["map_id"]), zone_id=int(row["zone_id"]),
            x=float(row["x"]), y=float(row["y"]), z=float(row["z"]),
            lock_id=int(row["lock_id"]), name=str(row["name"] or ""))
            for row in cur.fetchall()]


def _gather_danger(map_id: int, x: float, y: float):
    """Highest creature level spawned within GATHER_DANGER_YARDS of a point.

    None when nothing was measured, and the caller treats None as "refuse"
    rather than "safe" - the asymmetry is deliberate, because the failure it
    exists to prevent already happened: five characters at 43-48 wiped twice on
    a level 61 elite, eight deaths in four minutes.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(_GATHER_DANGER_SQL,
                        (int(map_id), float(x), float(y), GATHER_DANGER_YARDS))
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return None
            raise
        row = cur.fetchone()
    if not row or row.get("top") is None or not row.get("mobs"):
        return None
    return int(row["top"])


_FORGE_SQL = (
    "SELECT g.map AS map_id, g.position_x AS x, g.position_y AS y, "
    "g.position_z AS z, gt.Data1 AS radius, "
    "(POW(g.position_x - s.pos_x, 2) + POW(g.position_y - s.pos_y, 2)) AS d2 "
    "FROM overseer_snapshot s "
    "JOIN acore_world.gameobject g ON g.map = s.map_id "
    "JOIN acore_world.gameobject_template gt ON gt.entry = g.id "
    "WHERE s.name = %s AND s.updated_at > NOW() - INTERVAL 120 SECOND "
    "AND gt.type = %s AND gt.Data0 = %s AND gt.Data1 > %s "
    "ORDER BY d2 LIMIT 1"
)


def _nearest_forge(name: str):
    """The nearest usable Forge spawn row on `name`'s own map, or None.

    A ROW OUT OF THE SPAWN TABLE, NOT A COORDINATE THIS PROCESS INVENTED - the
    identical guarantee `_nearest_vault` gives, against the identical tables.
    `gameobject.position_x/y/z` is where the world actually put that forge,
    surveyed with the rest of the map.

    None covers four absences on purpose - no fresh snapshot row, no forge on
    this map, no forge on this map whose focus clears the arrival tolerance, no
    gameobject tables at all - because every one of them means the same thing to
    the caller: nobody can be stood at a forge this pass. `travel.forge_aim` is
    where they are told apart for the log.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(_FORGE_SQL, (
                name,
                travel.SPELL_FOCUS_GO_TYPE,
                travel.FORGE_FOCUS_ID,
                travel.ARRIVED_POSITION_YARDS,
            ))
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table. Same degradation as
            # `_nearest_vault`: a world image that cannot say where anybody is
            # standing, or that has no gameobject tables, honestly has no forge
            # in reach rather than an error to raise.
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("forge: cannot see where the family is standing")
                return None
            raise
        row = cur.fetchone()
        return dict(row) if row else None


def _forge_errands() -> dict:
    """name -> craft_spell, for every `job='craft'` row whose recipe needs a
    FORGE (infra#3748).

    THE FORGE SPECIFICALLY, NOT "ANY FOCUS", AND THAT IS LOAD-BEARING RATHER
    THAN PEDANTRY (infra#3760). `craft.RECIPES` carries entries for two
    different `SpellFocusObject` ids now that the eleven Anvil-gated
    Engineering brackets declare the value they always needed: Forge is 3 and
    Anvil is 1, and they are different objects in different places. A pass that
    read "needs some focus" would walk Grog to a forge for Handful of Copper
    Bolts, which needs an anvil - a journey that ends in the same silent
    `SPELL_FAILED_REQUIRES_SPELL_FOCUS` it was supposed to cure, having moved
    the whole family to do it. `craft.FOCUS_AIMS` is the mapping from a focus
    id to the pass that serves it, and this is that mapping read backwards.

    THE DEMAND SIGNAL, AND THE WHOLE REASON THE FORGE PASS IS NOT A NEW
    UNCONDITIONAL WRITER OF `travel_npc`. This project has been pinned in a
    Gadgetzan shop for half an hour by a background pass that latched that
    column (infra#3703, infra#3708, infra#3728), and four release fixes shipped
    in one night because of it. So the forge aim is strictly demand-driven: no
    standing smelt errand, no aim, no competition for the column at all. When
    this returns empty - which is every pass until a miner is actually told to
    smelt - `_forge_once` writes nothing and reads nothing further.

    GATED ON `job='craft'` IN THE SAME QUERY, because that column is DriveCraft's
    own permission (`jobIt->second != "craft"` skips everyone else). A character
    walked to a forge while the family is out gathering is a character standing
    at a forge casting nothing, AND a character whose non-empty `travel_npc`
    stands the quest drive down (`TravelHoldsTheWheel`), so the walk would cost
    the gathering trip it was supposed to be paid for by.

    DEGRADES TO NOBODY, matching every other reader of these columns: a world
    image without the column cannot be holding a smelt errand in it.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT name, craft_spell FROM overseer_roster "
                "WHERE enabled = 1 AND job = %s AND craft_spell > 0",
                (craft.MODE,),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                return {}
            raise
        return {row["name"]: int(row["craft_spell"] or 0)
                for row in cur.fetchall()
                if craft.focus_for(row["craft_spell"]) == travel.FORGE_FOCUS_ID}


def _current_travel_npc(name: str) -> str:
    """Whatever `name`'s travel aim says right now, for a log line.

    READ ONLY, AND ONLY EVER TO SAY SO. This exists because "the leader is on
    another errand" is not an actionable sentence and "the leader holds
    'vendor'" is: the first cannot tell a pass that is starved by a live
    errand from one starved by an errand left behind, and that distinction
    cost this session an afternoon of guessing. Nothing branches on the
    answer - `_write_trade_errand` has already decided by the time this is
    asked, and adding a second reader that could disagree with it would be
    the "two writers for one aim" fault this file argues against elsewhere.

    THERE IS NOW ONE CALLER THAT DOES BRANCH ON IT, AND THE PARAGRAPH ABOVE IS
    LEFT STANDING BECAUSE IT IS THE RULE THE EXCEPTION HAS TO ANSWER TO
    (infra#3703). `_claim_town_slot` reads this to decide whose errand the
    column is carrying and whether its lease has run out. What makes that safe
    is not that the reading is fresh - it is not, and cannot be - but that
    every effect downstream of it is a compare-and-swap:
    `_release_trade_errand` names the exact aim it is handing back, and
    `_write_trade_errand` carries its own `travel_npc IN (...)` guard. A column
    that changed hands between this SELECT and either UPDATE therefore matches
    nothing and is left alone, which is the same property `_errand_holders`
    gives for being the other deliberate second reader. A caller that branched
    on this and then wrote WITHOUT a guard would be the fault this docstring
    was written to prevent, and would still be.

    The empty string covers every absence - no row, no column, no table -
    because a log line that cannot say what holds the column should say
    nothing rather than guess at a reason. It is also the reading that means
    "the column is free" to the town slot, which is the right way round: a
    world this process cannot read the column out of is one where it should be
    asking for the traveller through the guarded write, not refusing to.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT travel_npc FROM overseer_roster WHERE name = %s", (name,))
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                return ""
            raise
        row = cur.fetchone()
        return (row or {}).get("travel_npc") or ""


def _recent_guild_bank_keys(minutes: int) -> set:
    """(character, command) pairs already proposed inside the retry window.

    The `kind='guild'` sibling of _recent_bank_keys, and needed for the same
    reason: `bank deposit <copper>` rows go through `_insert_guild`, which
    also carries tabard/invite/shortlist commands under the same kind - the
    `LIKE 'bank deposit %'` filter is what keeps this read to only the
    deposit rows this pass itself is responsible for re-queuing.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, command FROM overseer_command "
                "WHERE kind = 'guild' AND command LIKE %s "
                "AND created_at > NOW() - INTERVAL %s MINUTE",
                ("bank deposit %", int(minutes)),
            )
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table, 1265 a `kind` ENUM with
            # no 'guild' value. A world with none of the guild machinery has
            # been asked for nothing, so nothing is already queued.
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return set()
            raise
        return {(row["target_name"], row["command"]) for row in cur.fetchall()}


# -- the recruit sweep's reads (infra#3651) ----------------------------------
#
# EVERY AGE IS COMPUTED BY MYSQL AND NOT BY THIS PROCESS. The rows were stamped
# by the database's clock and the bridge runs in a different pod; subtracting a
# local `time.time()` from a `created_at` would be comparing two clocks that
# have never agreed and calling the difference a rate limit. TIMESTAMPDIFF asks
# the one clock that wrote the row.


def _latest_guild_shortlist() -> tuple:
    """(result dict, age in minutes) for the newest delivered shortlist.

    (None, None) when no shortlist has ever come back, which the planner reads
    as "ask for one" rather than as "there is nobody".

    `status = 'delivered'` IS THE FILTER THAT MATTERS. A shortlist row sits
    'pending' until the worldserver claims it and only carries a `result` once
    it has run; reading a pending row would hand the planner an empty shortlist
    and it would conclude the band admits nobody, which is the same sentence
    for a completely different fact.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT result, TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_s "
                "FROM overseer_command "
                "WHERE kind = 'guild' AND command LIKE %s AND status = 'delivered' "
                "AND result IS NOT NULL "
                "ORDER BY id DESC LIMIT 1",
                ("shortlist%",),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return (None, None)
            raise
        row = cur.fetchone()
    if not row:
        return (None, None)
    try:
        result = json.loads(row["result"])
    except (TypeError, ValueError):
        # A result this loop cannot parse is a module answering something it
        # does not understand. Treated as "there has never been a shortlist",
        # so the next pass asks for a fresh one instead of acting on a shape
        # it guessed at.
        log.warning("recruit: newest shortlist result did not parse as JSON")
        return (None, None)
    return (result, float(row["age_s"] or 0) / 60.0)


def _minutes_since_shortlist_asked() -> float | None:
    """How long since a shortlist was last ASKED for, whatever became of it.

    NO STATUS FILTER, WHICH IS THE ENTIRE POINT. `_latest_guild_shortlist`
    reads only 'delivered' rows because only those carry an answer; this reads
    every one, because a row stuck at 'pending' or come back 'error' still
    means the question has been asked. Without it the planner reads a world
    where shortlists never complete as a world where none was ever requested,
    and writes a fresh row every pass for as long as that lasts.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_s "
                "FROM overseer_command "
                "WHERE kind = 'guild' AND command LIKE %s "
                "ORDER BY id DESC LIMIT 1",
                ("shortlist%",),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return None
            raise
        row = cur.fetchone()
    if not row:
        return None
    return float(row["age_s"] or 0) / 60.0


def _guild_invites_asked(days: int) -> set:
    """Names invited inside the memory window, however the invite went.

    THE MEMORY infra#3650 ASKED FOR, READ OFF THE COMMAND LOG RATHER THAN A
    SECOND TABLE. Every invite this loop issues is a row carrying the name in
    `target_arg`; that row IS the record, and a purpose-built table beside it
    would be a second answer that could disagree. The same move bonds.py makes
    for help-history.

    OUTCOME IS DELIBERATELY NOT FILTERED ON. A refused invite will be refused
    again for the same reason - the band, the faction, the roster being full -
    so re-asking is waste; and a successful one takes the candidate out of the
    next shortlist by itself, because they now have a guild.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_arg FROM overseer_command "
                "WHERE kind = 'guild' AND command LIKE %s "
                "AND created_at > NOW() - INTERVAL %s DAY",
                ("invite %", int(days)),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return set()
            raise
        return {row["target_arg"] for row in cur.fetchall() if row["target_arg"]}


def _minutes_since_last_guild_invite() -> float | None:
    """How long since an invite was last issued, or None if never."""
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT TIMESTAMPDIFF(SECOND, created_at, NOW()) AS age_s "
                "FROM overseer_command "
                "WHERE kind = 'guild' AND command LIKE %s "
                "ORDER BY id DESC LIMIT 1",
                ("invite %",),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return None
            raise
        row = cur.fetchone()
    if not row:
        return None
    return float(row["age_s"] or 0) / 60.0


def _online_guild_members() -> list:
    """Family names that are in a guild AND in the world right now.

    BOTH HALVES ARE REQUIRED AND FOR DIFFERENT REASONS. In a guild, because
    DoGuild resolves "which guild this is about" from the acting character's
    own guild id and answers `not in a guild` otherwise. In the world, because
    the command executor needs a live Player to run the verb on.

    ONLY THE ACTOR HAS TO BE ONLINE. The candidate does not: mod-overseer's
    invite is `Guild::AddMember`, the core's own offline-capable path, and not
    the invite packet - so there is no dialog for an absent character to fail
    to answer, and an offline candidate joins exactly as well as a present one.

    The 60-second freshness rule is `_fetch_grounding`'s, unchanged: a
    snapshot row older than that means the character left the world.
    """
    names = [n.strip() for n in os.environ.get("OVERSEER_NOTABLE_NAMES", "").split(",") if n.strip()]
    if not names:
        return []
    marks = ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT c.name AS name "  # noqa: S608 - placeholders from a COUNT, values still bound
                "FROM characters c "
                "JOIN guild_member gm ON gm.guid = c.guid "
                "JOIN overseer_snapshot s ON s.name = c.name "
                "WHERE c.name IN (%s) "
                "AND s.updated_at > NOW() - INTERVAL 60 SECOND" % marks,
                names,
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                return []
            raise
        return [row["name"] for row in cur.fetchall()]


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


def _mail_takes_in_reach(takes, spawn, positions, yards, aim) -> list:
    """The takes whose holder is standing at `spawn`, and it says who is not.

    ONE ANSWER PER CHARACTER, NOT ONE PER ROW (infra#3830): several takes share
    a holder and the mailbox does not move between them. It is asked of the
    TAKER because `FindMailboxInReach(who, ...)` sweeps around the character
    whose row it is, so an arrived leader never meant five.

    A FUNCTION OF ITS OWN, AND MAIL-NAMED ON PURPOSE. `travel.spawn_in_reach`
    below it is geometry with no noun in it, which is why that one is shared
    between counters. This is the opposite case and the same criterion: it
    carries mail's own vocabulary - a `take`, its `character`, and a sentence
    about mailboxes that sends a reader somewhere - so the noun is the value,
    exactly as `mailbox_aim` argues against sharing a body with `vault_aim`.

    THE HELD-BACK ARE LOGGED HERE RATHER THAN COUNTED AND DROPPED, because a
    pass that writes nothing and a broken one look identical otherwise
    (infra#3660, restated for the rows). One line naming everybody, not one per
    take: a character with four letters is one person walking.

    IT DOES NOT KNOW ABOUT THE RETRY WINDOW, and the caller filters on that
    afterwards. The consequence, stated rather than hidden: a holder whose takes
    were all asked for recently AND who is not at the mailbox is named in this
    line even though no row was going to be written for them this pass. That is
    the honest sentence - they are not at a mailbox - and the alternative is
    this function taking a second argument to stay quiet about a true thing.
    """
    close, walking = [], []
    for take in takes:
        if travel.spawn_in_reach(spawn, positions.get(take.character), yards):
            close.append(take)
        else:
            walking.append(take.character)
    if walking:
        log.info(
            "mail: %s not within %d yards of the mailbox at %s, so no take is "
            "queued for them until the walk lands - one written now comes back "
            "'mailbox not in range' a second later",
            ", ".join(sorted(set(walking))), yards, aim,
        )
    return close


def _recent_mail_keys(minutes: int) -> set:
    """(character, command) pairs already proposed inside the retry window.

    The mail sibling of `_recent_bank_keys`, and it does two jobs rather than
    one. The first is the usual: a take whose holder is still walking to the
    mailbox is refused `mailbox not in range`, and an identical row every cycle
    would turn one slow journey into a hundred dead commands.

    The second is the bag budget. `mailrun.attachments_asked` counts the
    `take-item` pairs in this set to work out how much room this pass has
    already spent on a character, which is what stops a stale
    `character_inventory` reading being asked the same optimistic question every
    cycle. See `mailrun.room_for` for why that staleness exists at all and which
    direction it errs in.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, command FROM overseer_command "
                "WHERE kind = 'mail' AND created_at > NOW() - INTERVAL %s MINUTE",
                (int(minutes),),
            )
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table, 1265 a `kind` ENUM with
            # no 'mail' value. A world with none of the mail machinery has been
            # asked for nothing, so nothing is already queued.
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return set()
            raise
        return {(row["target_name"], row["command"]) for row in cur.fetchall()}


def _insert_mail(take, command: str) -> int:
    """One overseer_command row taking one thing out of one mailbox.

    THE COLUMNS MEAN WHAT THEY MEAN FOR A BANK ROW, NOT FOR A GIVE.
    mod-overseer's mail migration puts THE CHARACTER in `target_name` and uses
    `target_arg` for the RECIPIENT OF A `send` ONLY - the four other verbs leave
    it unused. A `take-item` row carrying a name in `target_arg` would still be
    delivered and would still be wrong, which is why the empty string is written
    literally rather than left to a column default nobody re-reads.

    Guarded on 1146 and 1265 exactly as `_insert_bank` and `_insert_guild` are:
    a worldserver whose image predates the mail migration must warn rather than
    take the whole pass down.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, 'mail', '', %s)",
                (take.character, command, "economy"),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1146, 1265):
                log.warning(
                    "overseer_command.kind has no 'mail' value - %s cannot %s "
                    "from letter %d until the worldserver image carrying "
                    "mod-overseer's mail SQL has shipped",
                    take.character, take.verb, take.mail_id,
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
    "AND ABS(cr.position_z - s.pos_z) <= %s "
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


def _fetch_craft_spells(names: list) -> dict:
    """name -> (craft_spell, money) for whoever is on job='craft' right now.

    craft_supply only needs a candidate list, and job='craft' is the same
    gate _craft_once already reads via _crafting_roster - a character not on
    it is not standing an errand this pass should touch, per the same
    permission discipline craft.craft_errand holds for `professions.assigned`.
    """
    if not names:
        return {}
    marks = ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT r.name, r.craft_spell, c.money "  # noqa: S608 - placeholders from a COUNT, values still bound
            "FROM overseer_roster r JOIN characters c ON c.name = r.name "
            "WHERE r.name IN (%s) AND r.job = 'craft'" % marks,
            names,
        )
        return {row["name"]: (row["craft_spell"], row["money"]) for row in cur.fetchall()}


def _fetch_standing_crafts(names: list) -> dict:
    """name -> (craft_spell, money) for everyone holding a craft errand at all.

    THE SIBLING OF `_fetch_craft_spells`, AND THE DIFFERENCE IS THE WHOLE
    REASON IT EXISTS. That one filters `r.job = 'craft'`, which LOOKS right
    for `craft_supply`: it buys a vial for somebody about to sit down and
    cast. It was not: this clause excused the pass that then logged nothing
    at all for ninety measured minutes (infra#3805). `craft_supply` reads
    THIS function now, so `_fetch_craft_spells` is left with no caller, kept
    as the contrast below rather than as a reader anything should pick up.
    This pass is the opposite case. `craft_rhythm.rhythm` moves the family to
    `MODE_GATHER` (job='quest') the moment ANY of them is short of a gathered
    reagent, which is precisely the state in which buying that reagent is the
    useful thing to do - so a job='craft' filter here would make this pass
    dark exactly when it was needed, and green on the cycles when there was
    nothing to buy. That is the "true and meaningless dry run" failure this
    project has shipped before.

    `craft_spell` IS THE ERRAND AND `job` IS THE MODE, and they are genuinely
    different facts: the column keeps naming the recipe a character is aimed
    at while the family is out gathering for it. Reading the errand without
    the mode is what lets the shopping happen on the way.
    """
    if not names:
        return {}
    marks = ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT r.name, r.craft_spell, c.money "  # noqa: S608 - placeholders from a COUNT, values still bound
            "FROM overseer_roster r JOIN characters c ON c.name = r.name "
            "WHERE r.name IN (%s) AND r.craft_spell > 0" % marks,
            names,
        )
        return {
            row["name"]: (row["craft_spell"], row["money"])
            for row in cur.fetchall()
        }


def _fetch_item_counts(pairs: list) -> dict:
    """How many of each (name, item entry) pair this character carries right
    now, summed across every stack - craft_supply's `held` is a total, not a
    stack size.

    ONE ROUND TRIP PER DISTINCT ENTRY, NOT PER CHARACTER - the same batching
    discipline `_fetch_free_slots`/`_fetch_craft_spells` already hold to.
    `craft_supply.REAGENT`'s eleven recipes resolve to four distinct item
    entries (three vials, Weak Flux), so a full-family cycle is at most four
    queries regardless of how many characters are shopping.
    """
    if not pairs:
        return {}
    by_entry: dict = {}
    for name, entry in pairs:
        by_entry.setdefault(entry, []).append(name)
    counts: dict = {}
    with _connect() as conn, conn.cursor() as cur:
        for entry, names in by_entry.items():
            marks = ",".join(["%s"] * len(names))
            cur.execute(
                "SELECT c.name AS name, COALESCE(SUM(ii.count), 0) AS n "  # noqa: S608 - placeholders from a COUNT, values still bound
                "FROM characters c LEFT JOIN item_instance ii "
                "ON ii.owner_guid = c.guid AND ii.itemEntry = %s "
                f"WHERE c.name IN ({marks}) GROUP BY c.name",
                (entry, *names),
            )
            for row in cur.fetchall():
                counts[(row["name"], entry)] = int(row["n"] or 0)
    return counts


# WHERE A REAGENT CAN ACTUALLY BE BOUGHT (infra#3692). This is
# `_TOWN_COUNTERS_SQL` turned inside out: that one asks "what is within eight
# yards of where this character is standing", which is the right question for
# deciding whether a purchase can be made NOW. This one asks "where is the
# nearest spawn on this map that stocks THIS item", which is the question the
# craft-supply travel aim was answering with a role keyword that cannot see
# the item at all.
#
# `cr.id`, NOT `cr.id1`. acore_world.creature's spawn-to-template column is
# `id` on this world - read off SHOW COLUMNS rather than remembered - and it
# is the same column `_TOWN_COUNTERS_SQL` already joins on, so there is one
# spelling of this join in the file and not two.
#
# THE VENDOR FLAG IS CHECKED, AND AGAINST creature_template. npc_vendor rows
# exist on spawns that carry no vendor flag, and `towntrip.town_from_rows`
# already refuses to count a stock list that no vendor flag stands behind
# ("a repairer that happens to have npc_vendor rows it cannot sell from would
# otherwise make `plan` promise a purchase nobody can make"). Walking to one
# would be the same promise, with a journey attached. The template's flag
# rather than the per-spawn override for the same reason _TOWN_COUNTERS_SQL
# uses it: one spelling of "is this a shop" across both reads.
#
# MIN() PER ENTRY, BECAUSE THE AIM NAMES AN ENTRY AND NOT A GUID. A creature
# with four spawns is one travel target as far as `travel_npc` is concerned,
# and ResolveTravelTarget chooses which copy of it this character walks to;
# ranking the duplicates against each other here would only crowd the
# shortlist with the same shop four times and hide the genuine alternatives.
#
# NO LIMIT ON DISTANCE, deliberately. A vendor 3,000 yards away is a bad trip
# and `supply_trip` will prefer any nearer one, but it is a REAL answer, and
# a distance cut-off here would turn "the only shop on this continent that
# sells it is far" into the same silence this issue exists to remove. The map
# bound is the only hard one, because it is the only one MoveFarTo cannot
# cross.
_REAGENT_VENDOR_SQL = (
    "SELECT cr.id AS entry, ct.name AS name, ct.faction AS faction, "
    "cr.map AS map_id, "
    "MIN(SQRT(POW(cr.position_x - %s, 2) + POW(cr.position_y - %s, 2))) AS yards "
    "FROM acore_world.npc_vendor nv "
    "JOIN acore_world.creature cr ON cr.id = nv.entry "
    "JOIN acore_world.creature_template ct ON ct.entry = cr.id "
    "WHERE nv.item = %s AND cr.map = %s AND (ct.npcflag & %s) <> 0 "
    "GROUP BY cr.id, ct.name, ct.faction, cr.map "
    "ORDER BY yards LIMIT %s"
)

# How many stocking vendors to read back per reagent: the one that gets
# chosen, plus the runners-up `craft_supply.report` names so a person can
# tell a silent faction refusal apart from a shop that was simply never
# reached. Derived from craft_supply.SHORTLIST rather than spelled, so the
# query cannot come to read back fewer rows than the log promises to print.
REAGENT_VENDOR_ROWS = craft_supply.SHORTLIST + 1


def _fetch_reagent_vendors(spot: dict, entries: list) -> dict:
    """item entry -> the nearest vendors on `spot`'s map that stock it.

    `spot` is one `overseer_snapshot` row - the LEADER's, because the leader
    is the character that actually walks and the rest arrive by following, so
    the map and the distance that matter are the leader's own.

    ONE QUERY PER DISTINCT ITEM ENTRY, the same batching discipline
    `_fetch_item_counts` already holds to and for the same reason: the whole
    of `craft_supply.REAGENT` plus `REAGENTS` resolves to a dozen item
    entries, and a pass only ever asks about the ones somebody is actually
    short of, so a full family cycle is a handful of queries however many
    characters are shopping. The cadence is ten minutes, and npc_vendor is
    37,753 rows on this world - this is not a read worth optimising further
    until something says it is.

    Degrades to an empty mapping on 1054/1146 exactly as `_fetch_town` does.
    A world image that cannot say which vendors stock what has not said there
    are none, and the only safe reading of "I cannot tell" is to walk nobody
    anywhere.
    """
    if not spot or not entries:
        return {}
    map_id = int(spot.get("map_id") or 0)
    at_x = float(spot.get("pos_x") or 0.0)
    at_y = float(spot.get("pos_y") or 0.0)
    found: dict = {}
    with _connect() as conn, conn.cursor() as cur:
        for entry in entries:
            try:
                cur.execute(
                    _REAGENT_VENDOR_SQL,
                    (at_x, at_y, int(entry), map_id,
                     towntrip.NPC_FLAG_VENDOR, REAGENT_VENDOR_ROWS),
                )
            except pymysql.err.MySQLError as exc:
                if exc.args and exc.args[0] in (1054, 1146):
                    log.warning(
                        "craft_supply: this world image cannot say which "
                        "vendors stock anything, so nobody is sent shopping"
                    )
                    return {}
                raise
            found[int(entry)] = [
                craft_supply.VendorSpawn(
                    entry=int(row["entry"]),
                    name=row["name"] or "",
                    faction=int(row["faction"] or 0),
                    map_id=int(row["map_id"] or 0),
                    yards=float(row["yards"] or 0.0),
                )
                for row in cur.fetchall()
            ]
    return found


# WHICH AUCTIONEER A CHARACTER IS ACTUALLY STANDING AT, AND ITS FACTION
# (infra#3731's auction half). The same shape as `_TOWN_COUNTERS_SQL` against
# the same snapshot, narrowed to the auctioneer npcflag, and it returns the
# FACTION because that is the only thing that decides which auction house the
# character is shopping in: `DoAuction` asks
# `GetAuctionsMap(auctioneer->GetFaction())` and refuses every auction id from
# any other pool as `WrongHouse`.
#
# ORDERED BY DISTANCE AND LIMITED TO ONE, because `FindAuctioneerInReach` on
# the C++ side keeps the NEAREST auctioneer that passes
# `GetNPCIfCanInteractWith`, so a second candidate a yard further away is not
# the one the executor will use and planning against it would plan against the
# wrong house.
_AUCTIONEER_IN_REACH_SQL = (
    "SELECT ct.entry AS entry, ct.name AS name, ct.faction AS faction, "
    "SQRT(POW(cr.position_x - s.pos_x, 2) + POW(cr.position_y - s.pos_y, 2)) AS yards "
    "FROM overseer_snapshot s "
    "JOIN acore_world.creature cr ON cr.map = s.map_id "
    "AND ABS(cr.position_x - s.pos_x) <= %s AND ABS(cr.position_y - s.pos_y) <= %s "
    "JOIN acore_world.creature_template ct ON ct.entry = cr.id "
    "WHERE s.name = %s AND s.updated_at > NOW() - INTERVAL 120 SECOND "
    "AND (ct.npcflag & %s) <> 0 "
    "ORDER BY yards LIMIT 1"
)

# UNIT_NPC_FLAG_AUCTIONEER. Named here rather than written as a bare 2097152 in
# a WHERE clause, the same way towntrip.NPC_FLAG_VENDOR is: it is a fact about
# the game, and `travel.ROLES` already carries the same flag under its own
# keyword so the two cannot silently mean different things.
NPC_FLAG_AUCTIONEER = 0x200000

_AUCTIONEER_MAPS_SQL = (
    "SELECT DISTINCT cr.map AS map_id "
    "FROM acore_world.creature cr "
    "JOIN acore_world.creature_template ct ON ct.entry = cr.id "
    "WHERE (ct.npcflag & %s) <> 0"
)


def _fetch_auctioneer_maps() -> set[int] | None:
    """Return maps with an auctioneer, or None when the read is unavailable."""
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(_AUCTIONEER_MAPS_SQL, (NPC_FLAG_AUCTIONEER,))
            return {int(row["map_id"]) for row in cur.fetchall()}
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("auction: cannot read auctioneer spawns by map")
                return None
            raise


def _fetch_auctioneer(name: str) -> dict | None:
    """The auctioneer `name` is standing at, or None.

    None means "not at a counter", which is the normal state for most of a
    trip - it is what the world looks like while they are still walking - and
    the pass plans nothing from it rather than planning against a guess. That
    is the same "nothing is planned until they have arrived" discipline
    `_towntrip_once` states and the reason this pass needs no state of its own.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                _AUCTIONEER_IN_REACH_SQL,
                (TOWN_COUNTER_YARDS, TOWN_COUNTER_YARDS, name,
                 NPC_FLAG_AUCTIONEER),
            )
            row = cur.fetchone()
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table. A world image without
            # the snapshot cannot say where anybody is standing, and the honest
            # reading of that is "nobody is at a counter".
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("auction: cannot see where the family is standing")
                return None
            raise
    return dict(row) if row else None


# EVERY LIVE LISTING OF THE REAGENTS THIS PASS WANTS, IN ONE HOUSE.
#
# NEITHER THE ITEM ENTRY NOR THE STACK SIZE IS IN `auctionhouse`, and the
# obvious query is wrong because of it. That table has exactly ten columns and
# holds neither: no `item_template` column and no `itemcount` column (read off
# SHOW COLUMNS, not remembered - the same discipline `_REAGENT_VENDOR_SQL`
# records for `cr.id` versus `cr.id1`). The entry is `item_instance.itemEntry`
# and the stack size is `item_instance.count`, reached through
# `auctionhouse.itemguid`, which is UNIQUE and one-to-one with
# `item_instance.guid`. Join integrity was checked against the live table
# rather than assumed: 2,248 auction rows produced 2,248 rows after both joins,
# no orphans, so INNER JOIN is safe.
#
# `buyoutprice > 0` IS IN THE WHERE CLAUSE AND ALSO IN `auction.usable`. The
# duplication is deliberate, the same reason `craft_supply._usable` re-applies
# its own same-map rule: a bid-only listing is a hard exclusion (a bid buys
# nothing, and `DoAuction` refuses one by name) and a hard rule belongs where a
# test with no database can reach it as well as in the query that makes the
# read cheap.
_AUCTION_LISTINGS_SQL = (
    "SELECT a.id AS auction_id, a.houseid AS house, a.buyoutprice AS buyout, "
    "ii.itemEntry AS entry, ii.count AS count, it.name AS label "
    "FROM auctionhouse a "
    "JOIN item_instance ii ON ii.guid = a.itemguid "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE a.houseid = %%s AND a.buyoutprice > 0 AND ii.itemEntry IN (%s)"
)


def _fetch_auction_listings(entries: list, house: int) -> list:
    """Every live buyout listing of `entries` in one auction house.

    ONE QUERY FOR THE WHOLE PASS rather than one per reagent: the six entries
    `auction.GATHERED` names are a short IN list against a table holding a
    couple of thousand rows, so a single read is both cheaper and a consistent
    snapshot - two reads a second apart can disagree, because the seller bot
    relists on a one minute cycle.
    """
    if not entries or int(house) <= 0:
        return []
    marks = ",".join(["%s"] * len(entries))
    sql = _AUCTION_LISTINGS_SQL % marks  # noqa: S608 - placeholders from a COUNT, values still bound
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, (int(house), *[int(e) for e in entries]))
            rows = cur.fetchall()
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning(
                    "auction: this world image has no readable auction house, "
                    "so nothing is bought this pass"
                )
                return []
            raise
    return [
        auction.Listing(
            auction_id=int(row["auction_id"]),
            entry=int(row["entry"]),
            label=row["label"] or "",
            count=int(row["count"] or 0),
            buyout=int(row["buyout"] or 0),
            house=int(row["house"] or 0),
        )
        for row in rows
    ]


# WHAT A CHARACTER ACTUALLY HOLDS, JOINED THROUGH `character_inventory` AND NOT
# THROUGH `item_instance.owner_guid` (infra#3731). This is a different query
# from `_fetch_item_counts` on purpose and the difference is load-bearing here.
#
# An owner-keyed count silently includes the mailbox: measured on this realm,
# all 469 live mail attachments keep a fully populated `item_instance` row with
# `owner_guid` set, and not one of them has a `character_inventory` row. It
# over-counts on two further grounds - stale rows owned by a character but in
# neither the bags, the mail nor the house (three of them on this family), and
# a letter in flight whose `owner_guid` still names the SENDER, which
# attributes the item to the wrong character entirely. Ugga reads 54 items by
# owner and 48 by inventory.
#
# For THIS pass the distinction decides whether a reagent that has been bought
# and not yet collected counts as held. It must - see `auction.short_of` - but
# it must count as MAIL and not as carried, because `DriveCraft` reads the bags
# and a reagent in the mailbox cannot be cast with. So the two facts are read
# by two queries that mean two different things.
_CARRIED_COUNTS_SQL = (
    "SELECT c.name AS name, ii.itemEntry AS entry, "
    "COALESCE(SUM(ii.count), 0) AS n "
    "FROM characters c "
    "JOIN character_inventory ci ON ci.guid = c.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "WHERE c.name IN (%s) AND ii.itemEntry IN (%s) "
    "GROUP BY c.name, ii.itemEntry"
)

# WHAT IS BOUGHT AND NOT YET COLLECTED. `mail_items` joined back to `mail` for
# the receiver, because `mail_items.receiver` exists but `mail.receiver` is the
# column with the index and the one that survives a letter being returned.
# Counted per (character, entry) exactly like the carried side so the two can
# be added without either knowing about the other.
_MAIL_COUNTS_SQL = (
    "SELECT c.name AS name, ii.itemEntry AS entry, "
    "COALESCE(SUM(ii.count), 0) AS n "
    "FROM mail m "
    "JOIN mail_items mi ON mi.mail_id = m.id "
    "JOIN item_instance ii ON ii.guid = mi.item_guid "
    "JOIN characters c ON c.guid = m.receiver "
    "WHERE c.name IN (%s) AND ii.itemEntry IN (%s) "
    "GROUP BY c.name, ii.itemEntry"
)


def _fetch_counts(sql: str, names: list, entries: list, what: str) -> dict:
    """`{(name, entry): count}` for one of the two holdings queries above.

    Shared because the two differ only in their FROM clause and the sentence
    they log when the world image cannot answer; a second copy of the binding
    and degradation logic would be a second place for the placeholder
    arithmetic to drift.
    """
    if not names or not entries:
        return {}
    bound = sql % (",".join(["%s"] * len(names)),  # noqa: S608 - placeholders from a COUNT, values still bound
                   ",".join(["%s"] * len(entries)))
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(bound, (*names, *[int(e) for e in entries]))
            rows = cur.fetchall()
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("auction: cannot read %s on this world image", what)
                return {}
            raise
    return {(row["name"], int(row["entry"])): int(row["n"] or 0) for row in rows}


_OUTSTANDING_AUCTIONS_SQL = (
    "SELECT COUNT(*) AS waiting FROM overseer_command "
    "WHERE kind = 'auction' AND status IN ('pending', 'claimed') "
    "AND target_name IN (%s)"
)


def _outstanding_auctions(names: list) -> int:
    """Auction rows the world still owes an answer on, or -1 if unreadable.

    THE ONE FACT THAT ENDS AN AUCTIONEER ERRAND, and the exact shape
    `_outstanding_sales` already has for the vendor one (infra#3708/#3717).
    `pending` and `claimed` are the whole of "unanswered"; `delivered` and
    `error` are both answers, refusals included, and counting the answered ones
    would hold the errand open for ever on every `auctioneer not in range` row
    the pass ever wrote - which is the same latch one table over.

    -1 IS "COULD NOT MEASURE" AND IT IS NOT ZERO, for the reason that function
    gives: returning 0 on a failed read would make an unreadable database look
    exactly like a finished errand, which is the fail-open direction.
    """
    if not names:
        return 0
    sql = _OUTSTANDING_AUCTIONS_SQL % ",".join(["%s"] * len(names))  # noqa: S608 - placeholders from a COUNT, values still bound
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
            row = cur.fetchone()
        except pymysql.err.MySQLError as exc:
            # 1265 is a `kind` ENUM with no 'auction' value: a world whose
            # image predates the auction migration has been asked for nothing,
            # so nothing is outstanding.
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                log.warning(
                    "auction: cannot read the auction queue, so no errand is "
                    "handed back this pass"
                )
                return -1
            raise
    return int(row["waiting"] or 0) if row else 0


def _fetch_teams(names: list) -> dict:
    """`{name: "alliance"|"horde"|""}` from each character's own race.

    READ FROM THE WORLD RATHER THAN CONFIGURED, because a family's faction is
    exactly the kind of fact that gets assumed from names and turns out wrong -
    this one is Gnome, Dwarf and three Humans behind five orcish-sounding
    names, and another pass had the same mistake corrected in it today.
    `auction.team_of` owns the race-to-side mapping so there is one copy.
    """
    if not names:
        return {}
    marks = ",".join(["%s"] * len(names))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, race FROM characters WHERE name IN (%s)" % marks,  # noqa: S608 - placeholders from a COUNT, values still bound
            names,
        )
        return {
            row["name"]: auction.team_of(int(row["race"] or 0))
            for row in cur.fetchall()
        }


def _insert_auction(member: str, command: str) -> int:
    """Queue one kind='auction' row for the world executor.

    `target_arg` is left empty: the auction executor does not read it (the
    column carries a receiving character for kind='give' and kind='trade', and
    an auction has no other side this process names).
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, %s, %s, %s)",
                (member, command, auction.AUCTION_KIND, "", "auction"),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1146, 1265):
                log.warning(
                    "overseer_command.kind has no 'auction' value - %s cannot "
                    "be sent to the auction house until the worldserver image "
                    "carrying mod-overseer's auction SQL has shipped",
                    member,
                )
                return 0
            raise
        return cur.lastrowid or 0


def _recent_auction_keys(minutes: int) -> set:
    """(character, command) pairs already proposed inside the retry window.

    The auction sibling of `_recent_town_keys`, and it matters more here than
    it does there: an auction id is bought exactly once, so a second row naming
    the same id can only ever be refused, and a walk that has not finished yet
    would otherwise queue an identical row every cycle for as long as the
    journey takes.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, command FROM overseer_command "
                "WHERE kind = 'auction' AND source = 'auction' "
                "AND created_at > NOW() - INTERVAL %s MINUTE",
                (int(minutes),),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return set()
            raise
        return {(row["target_name"], row["command"]) for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# RECIPES TAUGHT BY AN ITEM (infra#3792's other half, mod-overseer#467).
#
# A Pattern, Formula, Manual, Recipe, Plans, Schematic or Design is
# item_template.class 9, and USING it teaches the recipe and destroys the item.
# recipebook.py decides which one is worth using or buying; everything here only
# reads.
#
# THE SKILL GATE IS READ AS NUMBERS, NOT AS PROFESSION NAMES, which is why this
# does not reuse `_fetch_trade_skills`. That function maps skill ids to the
# words `professions.py` reasons in, and the question here is the CORE's:
# Player::CanUseItem compares `character_skills`.value against
# `item_template`.RequiredSkillRank for a skill named by id, so an id is what
# has to come back. A recipe can also gate on a skill no roster row mentions -
# Cooking and First Aid are the ones the family can actually reach today - and a
# profession-name filter would drop exactly those.
_RECIPE_SKILL_SQL = (
    "SELECT c.name AS name, cs.skill AS skill, cs.value AS value "
    "FROM character_skills cs "
    "JOIN characters c ON c.guid = cs.guid "
    "WHERE c.name IN (%s)"
)


def _fetch_recipe_skills(names: list) -> dict:
    """`{name: {skill_id: value}}` for the whole of `character_skills`.

    EVERY SKILL AND NOT A SHORTLIST. Filtering to the profession ids here would
    be this module deciding which recipes are allowed to exist, and it would be
    wrong today: the only class-9 items the family can currently use are Cooking
    ones, and Cooking is a secondary nobody's roster row declares.

    LATE, BUT IT CONVERGES, and the tolerance is safe for the same reason
    `_fetch_trade_skills` gives: a value a few points stale picks a slightly
    easier recipe, and the worldserver makes the real decision anyway - the
    `use` verb asks Player::CanUseItem itself and refuses with `the character
    skill is too low to use that item` if this was optimistic. Nothing is spent
    on a wrong guess in that direction.
    """
    if not names:
        return {}
    sql = _RECIPE_SKILL_SQL % ",".join(["%s"] * len(names))  # noqa: S608 - placeholders from a COUNT, values still bound
    out: dict = {name: {} for name in names}
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, names)
            rows = cur.fetchall()
        except pymysql.err.MySQLError as exc:
            # 1054 missing column, 1146 missing table. A world that cannot say
            # what anybody's skills are has not said they are high enough, and
            # `within_reach` then refuses everything, which is the safe way to
            # be wrong.
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("recipebook: cannot read character_skills this pass")
                return out
            raise
    for row in rows:
        out.setdefault(row["name"], {})[int(row["skill"])] = int(row["value"] or 0)
    return out


# EVERY CLASS-9 ITEM IN THE FAMILY'S BAGS, WITH THE GATE THAT DECIDES IT.
#
# `character_inventory` is the carried side only, which is what this wants: the
# `use` verb reaches worn gear, the backpack and equipped bags and deliberately
# not the bank, so a recipe sitting in a bank is not one this pass can drive.
_RECIPE_HELD_SQL = (
    "SELECT c.name AS holder, ci.item AS item_guid, ii.itemEntry AS entry, "
    "it.name AS label, it.RequiredSkill AS required_skill, "
    "it.RequiredSkillRank AS required_rank, it.spellid_2 AS recipe_spell "
    "FROM character_inventory ci "
    "JOIN characters c ON c.guid = ci.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN (%s) AND it.class = %%s AND it.spellid_2 > 0"
)


def _fetch_held_recipes(names: list) -> list:
    """Every class-9 item the named characters are carrying."""
    if not names:
        return []
    sql = _RECIPE_HELD_SQL % ",".join(["%s"] * len(names))  # noqa: S608 - placeholders from a COUNT, values still bound
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, (*names, recipebook.RECIPE_ITEM_CLASS))
            rows = cur.fetchall()
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("recipebook: cannot read the bags this pass")
                return []
            raise
    return [
        recipebook.Held(
            holder=row["holder"],
            item_guid=int(row["item_guid"]),
            entry=int(row["entry"]),
            label=row["label"] or "",
            required_skill=int(row["required_skill"] or 0),
            required_rank=int(row["required_rank"] or 0),
            recipe_spell=int(row["recipe_spell"] or 0),
        )
        for row in rows
    ]


# EVERY LIVE CLASS-9 LISTING IN THE HOUSES THIS FAMILY CAN REACH.
#
# Built on the same join and the same warning `_AUCTION_LISTINGS_SQL` carries:
# neither the item entry nor anything about the item is in `auctionhouse`, which
# has ten columns and holds only `itemguid`. The entry comes from
# `item_instance.itemEntry` and the skill gate from `item_template`.
_RECIPE_LISTINGS_SQL = (
    "SELECT a.id AS auction_id, a.houseid AS house, a.buyoutprice AS buyout, "
    "ii.itemEntry AS entry, it.name AS label, "
    "it.RequiredSkill AS required_skill, it.RequiredSkillRank AS required_rank, "
    "it.spellid_2 AS recipe_spell "
    "FROM auctionhouse a "
    "JOIN item_instance ii ON ii.guid = a.itemguid "
    "JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE a.houseid IN (%s) AND a.buyoutprice > 0 "
    "AND it.class = %%s AND it.spellid_2 > 0"
)


def _fetch_recipe_listings(houses: list) -> list:
    """Every live buyout listing of a class-9 item in the given houses.

    ONE QUERY FOR THE WHOLE PASS, the same call `_fetch_auction_listings` makes
    and for the same reason: two reads a second apart can disagree, because the
    seller bots relist on their own cycle, and a single read is a consistent
    snapshot as well as a cheaper one.
    """
    houses = sorted({int(h) for h in houses if int(h) > 0})
    if not houses:
        return []
    sql = _RECIPE_LISTINGS_SQL % ",".join(["%s"] * len(houses))  # noqa: S608 - placeholders from a COUNT, values still bound
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(sql, (*houses, recipebook.RECIPE_ITEM_CLASS))
            rows = cur.fetchall()
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning(
                    "recipebook: this world image has no readable auction "
                    "house, so no recipe is bought this pass"
                )
                return []
            raise
    return [
        recipebook.Listing(
            auction_id=int(row["auction_id"]),
            entry=int(row["entry"]),
            label=row["label"] or "",
            buyout=int(row["buyout"] or 0),
            house=int(row["house"] or 0),
            required_skill=int(row["required_skill"] or 0),
            required_rank=int(row["required_rank"] or 0),
            recipe_spell=int(row["recipe_spell"] or 0),
        )
        for row in rows
    ]


def _fetch_recipe_verdicts() -> list:
    """What the worldserver has already said about a recipe this pass sent.

    THE ONLY WAY TO KNOW WHETHER A CHARACTER KNOWS A RECIPE, and the reason is
    worth the space because the obvious query is not merely useless here but
    actively dangerous. `character_spell` cannot answer: Player::_SaveSpells
    writes only spells whose state is not UNCHANGED, so a recipe granted to a
    playerbot at runtime never reaches that table (craft.py's infra#3695 header
    has the measurement). A pass that read it would conclude `not known` about a
    recipe the character has, send the row, and the core would DESTROY the item
    teaching it again - Spell::TakeCastItem consumes it whether or not anything
    was learned, and nothing in the core asks the question either.

    So the `use` verb asks Player::HasSpell itself, before it sends anything,
    and writes its answer into `detail`. This reads those answers back.

    THE ENTRY COMES OUT OF THE RESULT JSON AND NOT OUT OF `command`, because the
    command names an item_instance guid - `use guid:<n>` - and that guid is gone
    the moment the item is consumed. The executor puts the entry in its result
    for exactly this kind of read-back, the same way DoGive reports the guid that
    actually moved.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, detail, result FROM overseer_command "
                "WHERE kind = %s AND source = %s "
                "AND status IN ('delivered', 'applied', 'unchanged', 'error')",
                (recipebook.LEARN_KIND, recipebook.LEARN_SOURCE),
            )
            rows = cur.fetchall()
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return []
            raise
    out = []
    for row in rows:
        entry = 0
        try:
            entry = int((json.loads(row["result"] or "{}") or {}).get("entry") or 0)
        except (ValueError, TypeError):
            # A result that is not JSON is a row from a world that wrote
            # something else there. Skipped rather than raised: one unreadable
            # row must not cost the pass every other verdict it can read.
            entry = 0
        out.append({"target_name": row["target_name"],
                    "detail": row["detail"], "entry": entry})
    return out


def _insert_learn(member: str, command: str) -> int:
    """Queue one `use` row for the world executor.

    kind='cast' AND NOT A KIND OF ITS OWN. mod-overseer routes on the first
    word - a cast row begins with a spell id, which is digits, and this one
    begins with `use` - so the verb needed no ENUM value and this insert needs
    no migration to have shipped. The 1265 guard is kept anyway, for the same
    reason `_insert_share` keeps its own: a world whose `kind` ENUM predates
    'cast' entirely would reject the row, and a pass that never lands must warn
    rather than kill the loop.

    `target_arg` is empty: the learn executor does not read it.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, %s, %s, %s)",
                (member, command, recipebook.LEARN_KIND, "",
                 recipebook.LEARN_SOURCE),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1146, 1265):
                log.warning(
                    "overseer_command.kind has no 'cast' value - %s cannot be "
                    "told to use a recipe until the worldserver image carrying "
                    "mod-overseer's cast SQL has shipped",
                    member,
                )
                return 0
            raise
        return cur.lastrowid or 0


def _recent_recipe_keys(minutes: int) -> set:
    """(character, command) pairs already proposed inside the retry window.

    It matters here for the reason it matters to the auction sibling and one
    more: a `use` row is `verifying` for the length of spell 483's own three
    second cast plus the window that judges it, so a pass on a shorter clock
    than that window would queue a second row for an item the first one is
    about to consume.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "SELECT target_name, command FROM overseer_command "
                "WHERE kind IN (%s, 'auction') AND source = %s "
                "AND created_at > NOW() - INTERVAL %s MINUTE",
                (recipebook.LEARN_KIND, recipebook.LEARN_SOURCE, int(minutes)),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146, 1265):
                return set()
            raise
        return {(row["target_name"], row["command"]) for row in cur.fetchall()}


def _insert_recipe_buy(member: str, command: str) -> int:
    """Queue one kind='auction' buyout for a recipe item.

    THE SAME EXECUTOR `_insert_auction` FEEDS, and deliberately not a second
    one: DoAuction already buys an auction id for a character standing at an
    auctioneer, and it does not care what the item is. What differs is `source`,
    so a recipe this pass bought can be told from a reagent the auction pass
    bought at the same counter in the same minute - which is also what
    `_recent_recipe_keys` needs to dedupe against.
    """
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO overseer_command "
                "(target_name, command, kind, target_arg, source) "
                "VALUES (%s, %s, %s, %s, %s)",
                (member, command, auction.AUCTION_KIND, "",
                 recipebook.LEARN_SOURCE),
            )
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1146, 1265):
                log.warning(
                    "overseer_command.kind has no 'auction' value - %s cannot "
                    "buy a recipe until the worldserver image carrying "
                    "mod-overseer's auction SQL has shipped",
                    member,
                )
                return 0
            raise
        return cur.lastrowid or 0


def _fetch_town(leader: str):
    """What the counters within reach of `leader` can do, as a towntrip.Town.

    THE PARAMETER NAME IS A HOLDOVER, NOT A CONTRACT - test_towntrip_pass.py
    pins this exact signature text, so it stays `leader` here, but this
    reads whatever position the NAMED CHARACTER has, leader or not.
    `_vendor_once` already calls this per SELLING HOLDER, not just the party
    leader, and `_craft_supply_once` does the same per character shopping
    for their own reagent - the town-trip pass is the one caller that
    happens to only ever want the leader's own position.

    An empty answer is the normal state for most of a trip: it is what the world
    looks like while they are still walking. towntrip.plan turns that into notes
    rather than errands, which is what keeps the queue clean.

    IT ANSWERS FOR THE BANK COUNTER TOO NOW (infra#3815), which is a third bit
    in the mask and nothing else: `_bank_once` asks this exact question of this
    exact table, and one reader for three counters is cheaper to keep true than
    three. Widening the mask cannot change what the older callers see -
    `town_from_rows` sets `repairs` and `vendor` off their own bits, and a
    banker with no npc_vendor rows adds no `stocks`.
    """
    want = (towntrip.NPC_FLAG_VENDOR | towntrip.NPC_FLAG_REPAIR
            | towntrip.NPC_FLAG_BANKER)
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                _TOWN_COUNTERS_SQL,
                (TOWN_COUNTER_YARDS, TOWN_COUNTER_YARDS, TOWN_COUNTER_YARDS,
                 leader, want),
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


_VENDOR_POSITION_SQL = (
    "SELECT map_id, pos_x, pos_y, pos_z FROM overseer_snapshot "
    "WHERE name = %s AND updated_at > NOW() - INTERVAL 120 SECOND"
)


def _fetch_vendor_position(name: str):
    """Read the leader position used by the pure vendor stall detector."""
    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(_VENDOR_POSITION_SQL, (name,))
        except pymysql.err.MySQLError as exc:
            if exc.args and exc.args[0] in (1054, 1146):
                log.warning("vendor stall: snapshot position is unavailable")
                return None
            raise
        row = cur.fetchone()
    if not row:
        return None
    return (row.get("map_id"), row.get("pos_x"), row.get("pos_y"),
            row.get("pos_z"))


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
#
# 'dungeon' joined the tuple once the council could actually decide one
# (infra dungeon-decision gap) - see _persist_council_plan for what gets
# stored and _apply_goal_action for what execing a dungeon goal does.
DRIVEN_KINDS = ("level", "quest", "dungeon")


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
            "SELECT kind, target, quest_id, skill_name FROM overseer_goal "
            "WHERE character_name = %s AND status = 'active'",
            (plan.beneficiary,),
        )
        return goals.already_working(
            plan.kind, int(plan.target), list(cur.fetchall()), quest_id=quest_id,
            keyword=plan.keyword,
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

    # skill_name IS THE JOB KEYWORD FOR kind='dungeon', not a skill. There is
    # no column on overseer_goal for it, the same gap 'quest' hit before it
    # - the id had nowhere to live either, until it was threaded onto
    # Proposal/Plan themselves. skill_name is the only spare TEXT column the
    # row has, and it is otherwise unused for both 'level' and 'quest' goals,
    # so a dungeon row is the one place it carries meaning other than a
    # profession name. "" (the bare 'dungeon' job) is stored as "" and not
    # NULL, matching how goals.already_working and goals._describe both read
    # it back with `or ""`.
    skill_name = plan.keyword if plan.kind == "dungeon" else None

    with _connect() as conn, conn.cursor() as cur:
        # An identical goal already being worked is LEFT ALONE. The council
        # meets hourly and keeps reaching the same conclusion while the work is
        # still in progress, so replacing it wiped last_report every hour: the
        # progress record restarted, and with it the stall counter that
        # re-issues a lost strategy. Four cancelled duplicates of one goal sat
        # in the table before this was noticed, and the supervisor never once
        # got far enough to re-assert.
        cur.execute(
            "SELECT kind, target, quest_id, skill_name FROM overseer_goal "
            "WHERE character_name = %s AND status = 'active'",
            (plan.beneficiary,),
        )
        if goals.already_working(plan.kind, int(plan.target), list(cur.fetchall()),
                                 quest_id=quest_id, keyword=plan.keyword):
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
        # which is an observation and not a destination. A dungeon goal's
        # target IS a destination (council.DUNGEON_RUNS_WANTED runs done), so
        # it takes the same road as 'level'.
        target = goals.QUEST_TARGET if plan.kind == "quest" else int(plan.target)
        cur.execute(
            "INSERT INTO overseer_goal "
            "(character_name, kind, skill_name, target, quest_id, status, "
            "channel_id) VALUES (%s, %s, %s, %s, %s, 'active', %s)",
            (plan.beneficiary, plan.kind, skill_name, target, quest_id,
             OVERSEER_CHANNEL_ID or ""),
        )
        log.info("council: persisted %s goal for %s (quest %d, keyword %r, row %s)",
                 plan.kind, plan.beneficiary, quest_id, skill_name, cur.lastrowid)
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
                self._design_tabard,
                self._assign_trades,
                self._assign_crafts,
                self._sample_family,
                self._share_quests_loop,
                self._move_materials_loop,
                self._guild_share_loop,
                self._vendor_loop,
                self._bank_loop,
                self._guild_bank_loop,
                self._mail_loop,
                self._recruit_loop,
                self._craft_supply_loop,
                self._craft_rhythm_loop,
                self._forge_loop,
                self._auction_loop,
                self._recipebook_loop,
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
