"""IO shell for the wow-overseer bridge.

Everything here is adapters: Discord in, MySQL in/out, Discord out. All
decisions live in core.py, which this module treats as a black box. Keep it
that way - logic added here escapes the test seam (infra#2597).

Blocking MySQL calls are pushed off the event loop with asyncio.to_thread;
nothing in this file may call the database directly from an async handler.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import urllib.request

import discord
import pymysql

import council
import core
import events
import fanout
import goals
import bonds
import kin
import persona
import protect
import relay
import voice
from transform import Geometry

log = logging.getLogger("wow-overseer")

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))
# The overseer's own channel: unaddressed messages there get answered
# (roster / help) instead of the shared-channel silence rule.
OVERSEER_CHANNEL_ID = os.environ.get("OVERSEER_CHANNEL_ID", "")
# Where world chat is relayed to. Falls back to the overseer's own channel.
CHAT_CHANNEL_ID = os.environ.get("CHAT_CHANNEL_ID", "")
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
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE overseer_command SET status = 'error', "
            "detail = 'no result from the worldserver; it MAY still have run, "
            "check before repeating it' "
            "WHERE status = 'claimed' AND updated_at < NOW() - INTERVAL %s SECOND",
            (seconds,),
        )
        return cur.rowcount


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


def _fetch_outcomes(min_id: int) -> list[dict]:
    # Static, fully parameterized SQL on purpose (a dynamic IN-list means
    # assembling the statement from strings). Rows at or above the oldest
    # pending id that we did not insert ourselves come back too - they route
    # to no channel and are dropped, and core's seen-set keeps every report
    # exactly-once.
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            # 'claimed' is in-flight, not finished: reporting it would call a
            # command that is still running a failure.
            "SELECT id, target_name, command, kind, status, detail FROM overseer_command "
            "WHERE status IN ('delivered', 'error') AND id >= %s",
            (min_id,),
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
    sql = _BOT_HELD_SQL % placeholders  # noqa: S608
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, names)
        return [r["name"] for r in cur.fetchall()]


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
    for name in driven:
        _insert_command(core.InsertCommand(name, goals.LIFE_STRATEGY, "overseer:life"))
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


_COUNCIL_MEMBER_SQL = (
    "SELECT c.name, c.class, c.money, "
    "       (SELECT COUNT(*) FROM character_skills k WHERE k.guid = c.guid) AS trades, "
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
    sql = _COUNCIL_MEMBER_SQL % placeholders  # noqa: S608
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            sql,
            names,
        )
        rows = cur.fetchall()

    members = []
    for row in rows:
        level = row.get("live_level")
        if level is None:
            # Offline, or the snapshot went stale. A member nobody can see is
            # not at the table; guessing their level from a stale row is how a
            # council decides to help someone who already caught up.
            continue
        members.append(
            council.Member(
                name=row["name"],
                level=int(level),
                class_name=CLASS_NAMES.get(row["class"], "adventurer"),
                gold=int(row["money"] or 0),
                trades=int(row["trades"] or 0),
            )
        )
    return members


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

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
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
        elif isinstance(decision, core.RosterQuery):
            rows = await asyncio.to_thread(_fetch_roster)
            await channel.send(core.format_roster(rows).text[:1990])
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
            personality=grounding["personality"],
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

                # Post by post, acknowledging each one on its own. Marking a
                # whole batch after a partial failure would skip lines that
                # never went out AND re-send the ones that did.
                rows = await self._retire_addon_traffic(rows)

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
                await asyncio.to_thread(
                    _mark_party_leader, bonds.head_of_family()
                )

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
            personality=grounding["personality"],
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
            " kind ENUM('level','skill') NOT NULL,"
            " skill_name VARCHAR(32) NULL,"
            " target SMALLINT UNSIGNED NOT NULL,"
            " status ENUM('active','completed','cancelled') NOT NULL DEFAULT 'active',"
            " channel_id VARCHAR(32) NOT NULL DEFAULT '',"
            " last_report TEXT NULL,"
            " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " completed_at TIMESTAMP NULL DEFAULT NULL,"
            " PRIMARY KEY (id), KEY idx_char_status (character_name, status)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )


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
            "INSERT INTO overseer_goal (character_name, kind, skill_name, target, channel_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (name, goal.kind, goal.skill_name, goal.target, channel_id),
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
            "SELECT id, character_name, kind, skill_name, target, status, "
            "channel_id, last_report FROM overseer_goal WHERE status = 'active'"
        )
        return list(cur.fetchall())


def _observe_goal(row: dict) -> int | None:
    """The character's current level or skill value, or None if unseeable."""
    with _connect() as conn, conn.cursor() as cur:
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


def _already_agreed(plan) -> bool:
    """Is the family already working on exactly this?

    Asked BEFORE the council speaks, not after. Persisting already refused a
    duplicate goal, but the scene was played out in full first, which is the
    half Evan actually sees.
    """
    if plan.kind not in ("level",):
        return False
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT kind, target FROM overseer_goal "
            "WHERE character_name = %s AND status = 'active'",
            (plan.beneficiary,),
        )
        return goals.already_working(plan.kind, int(plan.target), list(cur.fetchall()))


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
    if plan.kind not in ("level",):
        log.info("council: plan '%s' is not a goal the supervisor drives", plan.kind)
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
            "SELECT kind, target FROM overseer_goal "
            "WHERE character_name = %s AND status = 'active'",
            (plan.beneficiary,),
        )
        if goals.already_working(plan.kind, int(plan.target), list(cur.fetchall())):
            log.info("council: %s is already working towards %s %d",
                     plan.beneficiary, plan.kind, int(plan.target))
            return None

        cur.execute(
            "UPDATE overseer_goal SET status = 'cancelled' "
            "WHERE character_name = %s AND status = 'active'",
            (plan.beneficiary,),
        )
        cur.execute(
            "INSERT INTO overseer_goal (character_name, kind, target, status, channel_id) "
            "VALUES (%s, %s, %s, 'active', %s)",
            (plan.beneficiary, plan.kind, int(plan.target), OVERSEER_CHANNEL_ID or ""),
        )
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    token = os.environ["DISCORD_BOT_TOKEN"]
    for handler in logging.getLogger().handlers:
        handler.addFilter(_RedactSecret(token))
    allowed = frozenset(
        part.strip() for part in os.environ["DISCORD_ALLOWED_USERS"].split(",") if part.strip()
    )
    Bridge(allowed).run(token, log_handler=None)


if __name__ == "__main__":
    main()
