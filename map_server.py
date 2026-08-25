"""HTTP adapter for the live map: serves the page and /api/map JSON.

Thin by design (the infra#2597 seam rule): MySQL rows in, build_payload
out, bytes over HTTP. No logic here that tests would want to reach.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pymysql

import chat
import stream
import voice
from map_core import build_payload
from panel import build_character_panel
from transform import Geometry

log = logging.getLogger("wow-map")

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = Geometry.load(HERE)
PORT = int(os.environ.get("PORT", "8080"))

# WoW's own name rule (same as the bridge); anything else never reaches SQL.
_NAME_RE = re.compile(r"^[A-Za-z]{2,12}$")

# The inner voice, reached exactly as the bridge reaches it. Duplicated
# rather than imported because bridge.py is the Discord process (importing
# it would pull in discord.py and its env contract); the defaults, the
# thinking-disabled body and the generous budget below must stay in step
# with bridge._ask_llm, which is why they are named identically.
LLM_URL = os.environ.get(
    "LLM_URL", "http://spark-gateway.spark-gateway.svc.cluster.local:8080/v1/chat/completions"
)
LLM_MODEL = os.environ.get("LLM_MODEL", "spark:warm-any")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))

# A chat POST is a name plus a sentence; anything larger is not a request
# this page makes, and an unbounded read would be a memory hole.
MAX_BODY = 4096

# What the inner voice is told the character IS. panel.py has its own copy
# for the panel's own labels; importing it here would couple the prompt's
# wording to the panel's rendering choices.
_MAP_RACE_NAMES = {1: "Human", 2: "Orc", 3: "Dwarf", 4: "Night Elf", 5: "Undead",
                   6: "Tauren", 7: "Gnome", 8: "Troll", 10: "Blood Elf", 11: "Draenei"}
_MAP_CLASS_NAMES = {1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest",
                    6: "Death Knight", 7: "Shaman", 8: "Mage", 9: "Warlock", 11: "Druid"}

# One short-lived connection per poll, same posture as the bridge; the map
# refresh cadence (5s, one client or two) makes pooling pure complexity.
def _connect() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        user="root",
        password=os.environ["MYSQL_ROOT_PASSWORD"],
        database="acore_characters",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        # Bounded, always: ThreadingHTTPServer spawns a thread per request
        # and the page polls every 5s whether or not the last poll returned.
        # PyMySQL's default read/write timeout is INFINITE, so a hung MySQL
        # would accumulate stuck threads (each pinning a connection) without
        # bound. With these, a hang becomes a 503 within seconds.
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )


def _fetch_rows() -> list[dict]:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, level, race, map_id, pos_x, pos_y, in_combat, is_bot, "
                "TIMESTAMPDIFF(SECOND, updated_at, NOW()) AS age_seconds "
                # Same 60s freshness rule as the bridge - the module sweeps
                # logged-out rows on this cadence, and the two readers of the
                # snapshot must not disagree about who is online.
                "FROM overseer_snapshot WHERE updated_at > NOW() - INTERVAL 60 SECOND"
            )
            return list(cur.fetchall())
    finally:
        conn.close()


def _fetch_character(name: str) -> dict:
    """Everything build_character_panel needs, from one short-lived connection.

    Row-fetching only - what the rows MEAN is panel.py's business. The 60s
    freshness rule matches /api/map and the bridge exactly: the readers of
    the snapshot must not disagree about who is online, and a swept
    (logged-out) row returning None here is what the panel's calm
    "left the world" state is built from.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT guid, name, level, race, class, health, max_health, "
                "in_combat, is_bot, guild_id, group_leader, target_guid, "
                "TIMESTAMPDIFF(SECOND, updated_at, NOW()) AS age_seconds "
                "FROM overseer_snapshot "
                "WHERE name = %s AND updated_at > NOW() - INTERVAL 60 SECOND",
                (name,),
            )
            snapshot_row = cur.fetchone()
            pieces = {
                "name": name,
                "snapshot_row": snapshot_row,
                "char_row": None,
                "action_rows": [],
                "inventory_rows": [],
                "guild_name": None,
                "group_rows": [],
                "target_player": None,
                "target_creature_name": None,
            }
            if snapshot_row is None:
                return pieces
            guid = snapshot_row["guid"]
            cur.execute(
                "SELECT activeTalentGroup, power1, power2, power3, power4, "
                "power5, power6, power7 FROM characters WHERE guid = %s",
                (guid,),
            )
            pieces["char_row"] = cur.fetchone()
            cur.execute(
                "SELECT spec, button, action, type FROM character_action WHERE guid = %s",
                (guid,),
            )
            pieces["action_rows"] = list(cur.fetchall())
            cur.execute(
                "SELECT ci.bag, ci.slot, ci.item AS item_guid, ii.itemEntry AS entry, "
                "ii.count, it.name FROM character_inventory ci "
                "JOIN item_instance ii ON ii.guid = ci.item "
                "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
                "WHERE ci.guid = %s",
                (guid,),
            )
            pieces["inventory_rows"] = list(cur.fetchall())
            if snapshot_row["guild_id"]:
                cur.execute(
                    "SELECT name FROM guild WHERE guildid = %s",
                    (snapshot_row["guild_id"],),
                )
                row = cur.fetchone()
                pieces["guild_name"] = row["name"] if row else None
            if snapshot_row["group_leader"]:
                cur.execute(
                    "SELECT guid, name, level, class FROM overseer_snapshot "
                    "WHERE group_leader = %s "
                    "AND updated_at > NOW() - INTERVAL 60 SECOND",
                    (snapshot_row["group_leader"],),
                )
                pieces["group_rows"] = list(cur.fetchall())
            if snapshot_row["target_guid"]:
                cur.execute(
                    "SELECT name, level FROM overseer_snapshot "
                    "WHERE guid = %s AND updated_at > NOW() - INTERVAL 60 SECOND",
                    (snapshot_row["target_guid"],),
                )
                pieces["target_player"] = cur.fetchone()
                if pieces["target_player"] is None:
                    # Not a live player: try the world's creature spawns.
                    # Precedence itself is decided in panel.py; this only
                    # avoids a pointless query when the player match hit.
                    cur.execute(
                        "SELECT ct.name FROM acore_world.creature c "
                        "JOIN acore_world.creature_template ct ON ct.entry = c.id "
                        "WHERE c.guid = %s",
                        (snapshot_row["target_guid"],),
                    )
                    row = cur.fetchone()
                    pieces["target_creature_name"] = row["name"] if row else None
            return pieces
    finally:
        conn.close()


def _ensure_stream_store() -> None:
    """The table the map and the Windows agent meet in.

    CREATE TABLE IF NOT EXISTS is a no-op on an EXISTING table - every word of
    it, including columns - so the ALTERs are computed from the live shape by
    stream.stream_migrations rather than hoped for. That is the overseer_goal
    kind-ENUM lesson, which was silently dead in production while CI stayed
    green because CI's database is always fresh.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS overseer_stream ("
            " `character` VARCHAR(24) NOT NULL PRIMARY KEY,"
            " mode VARCHAR(16) NOT NULL DEFAULT 'cam',"
            " state VARCHAR(16) NOT NULL DEFAULT 'requested',"
            " detail TEXT NULL,"
            " delivery VARCHAR(16) NULL,"
            " last_seen TIMESTAMP NULL DEFAULT NULL,"
            " requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            "   ON UPDATE CURRENT_TIMESTAMP"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        cur.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'overseer_stream'"
        )
        have = [r["COLUMN_NAME"] for r in cur.fetchall()]
        for sql in stream.stream_migrations(have):
            log.info("stream: migrating - %s", sql)
            cur.execute(sql)


def _fetch_streams() -> list:
    """Every stream row, with clocks as epoch seconds.

    UNIX_TIMESTAMP in SQL rather than Python datetime arithmetic: the bridge
    and MySQL do not necessarily agree on timezone, and a stream torn down an
    hour early because of it would be a maddening bug to chase.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT `character`, mode, state, detail, delivery,"
            "       UNIX_TIMESTAMP(last_seen) AS last_seen_seconds,"
            "       UNIX_TIMESTAMP(requested_at) AS requested_seconds"
            " FROM overseer_stream"
        )
        return list(cur.fetchall())


def _request_stream(name: str, mode: str) -> None:
    """Ask for a client. REPLACE, so re-watching a character that ended
    earlier reuses its row rather than colliding on the primary key."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "REPLACE INTO overseer_stream"
            " (`character`, mode, state, detail, delivery, last_seen, requested_at)"
            " VALUES (%s, %s, 'requested', NULL, NULL, NOW(), NOW())",
            (name, mode),
        )


def _touch_stream(name: str) -> None:
    """The heartbeat. The ONLY thing keeping a client alive."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE overseer_stream SET last_seen = NOW()"
            " WHERE `character` = %s AND state IN ('requested','starting','live')",
            (name,),
        )


def _stop_stream(name: str) -> None:
    """Ask for teardown. The agent moves it to 'ended' when the client is
    actually gone - this only ever says 'stop', never 'stopped'."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE overseer_stream SET state = 'stopping'"
            " WHERE `character` = %s AND state IN ('requested','starting','live')",
            (name,),
        )


def stream_expire(rows: list, now_seconds: float) -> list:
    """Move every stale row to 'stopping'. Returns the names expired.

    THE SWEEP IS THE WHOLE LIFECYCLE. A viewer who closed the tab sends
    nothing again, so their own silence cannot end anything - this runs on
    every read of the watch endpoint, which the open map does constantly.
    """
    stale = [r["character"] for r in rows if stream.is_stale(r, now_seconds)]
    if not stale:
        return []
    marks = ", ".join(["%s"] * len(stale))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE overseer_stream SET state = 'stopping',"  # noqa: S608 - placeholders from a COUNT, values bound
            " detail = 'nobody was watching'"
            " WHERE `character` IN (%s)" % marks,
            tuple(stale),
        )
    return stale


def _character_exists_by_name(name: str) -> bool:
    """A watch request for a character that does not exist should say so,
    not queue a client for nobody."""
    with _connect() as conn, conn.cursor() as cur:
        return _character_exists(cur, name)


def _character_exists(cur, name: str) -> bool:
    """Is this a real character at all (logged in or not)?

    The timeline and the chat box both outlive a logout - the module sweeps
    overseer_snapshot, but the thoughts remain - so presence in the snapshot
    is the wrong existence test. A name nobody ever rolled is a clean 404.
    """
    cur.execute("SELECT 1 AS found FROM characters WHERE name = %s", (name,))
    return cur.fetchone() is not None


def _fetch_thoughts(name: str, before: int | None, limit: int) -> tuple[list[dict], datetime] | None:
    """One page of thought rows plus the DATABASE clock, or None if no such character.

    The clock comes back with the rows on purpose: created_at is stamped by
    MySQL, so the "3m ago" labels must be computed against MySQL's now, not
    this pod's. Two static statements, picked by a branch - the cursor is a
    parameter, never string-built SQL.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if not _character_exists(cur, name):
                return None
            if before is None:
                cur.execute(
                    "SELECT id, source, text, created_at FROM overseer_thought "
                    "WHERE character_name = %s ORDER BY id DESC LIMIT %s",
                    (name, limit),
                )
            else:
                cur.execute(
                    "SELECT id, source, text, created_at FROM overseer_thought "
                    "WHERE character_name = %s AND id < %s ORDER BY id DESC LIMIT %s",
                    (name, before, limit),
                )
            rows = list(cur.fetchall())
            cur.execute("SELECT NOW() AS db_now")
            return rows, cur.fetchone()["db_now"]
    finally:
        conn.close()


def _fetch_chat_grounding(name: str) -> dict | None:
    """Snapshot + personality + recent thoughts, or None if no such character.

    Same join as the bridge's _fetch_grounding (characters.guid is what
    mod_ollama_chat_personality keys on), widened with the vitals the panel
    already shows and the recent thoughts this feature adds. A character
    who exists but is not in the fresh snapshot comes back with
    snapshot_row None - logged out, not unknown.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if not _character_exists(cur, name):
                return None
            cur.execute(
                "SELECT s.name, s.level, s.race, s.class, s.map_id, s.pos_x, s.pos_y, "
                "       s.health, s.max_health, s.in_combat, p.personality "
                "FROM overseer_snapshot s "
                "LEFT JOIN characters c ON c.name = s.name "
                "LEFT JOIN mod_ollama_chat_personality p ON p.guid = c.guid "
                "WHERE s.name = %s AND s.updated_at > NOW() - INTERVAL 60 SECOND",
                (name,),
            )
            snapshot_row = cur.fetchone()
            cur.execute(
                "SELECT id, source, text, created_at FROM overseer_thought "
                "WHERE character_name = %s ORDER BY id DESC LIMIT %s",
                (name, chat.RECENT_FOR_PROMPT),
            )
            return {"snapshot_row": snapshot_row, "recent": list(cur.fetchall())}
    finally:
        conn.close()


def _insert_thought(name: str, source: str, text: str) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO overseer_thought (character_name, source, text) "
                "VALUES (%s, %s, %s)",
                (name, source, text[:chat.MAX_TEXT]),
            )
    finally:
        conn.close()


def _insert_command(name: str, command: str, source: str) -> int:
    """Queue a playerbot command exactly as the Discord path does.

    Same table, same shape, same worldserver poller - a directive typed on
    the web page must not travel a second, divergent road to the game.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO overseer_command (target_name, command, source) "
                "VALUES (%s, %s, %s)",
                (name, command, source),
            )
            return cur.lastrowid
    finally:
        conn.close()


def _ask_llm(prompt: str) -> str:
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            # Reasoning models narrate before they answer and can burn the
            # whole budget thinking; ask for silence, disable thinking where
            # the backend honors the key (vLLM; ollama ignores it), and
            # budget enough that a backend which thinks anyway still reaches
            # the answer. chat.parse_reply takes the LAST object for the
            # same reason.
            {"role": "system", "content": "Answer with the JSON object only. No reasoning, no preamble."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 1500,
        "temperature": 0.7,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    # S310 on BOTH call sites: LLM_URL is a hardcoded http:// default or an
    # operator-set env var on this deployment, never user input, so there is
    # no file:/custom-scheme path for the rule to protect against here.
    req = urllib.request.Request(  # noqa: S310
        LLM_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:  # noqa: S310
        data = json.load(resp)
    return data["choices"][0]["message"]["content"]


# The page is tailnet-only (wow.overseer.ts.ehumps.me, reachable only over
# the tailnet), so there is deliberately NO auth layer on these endpoints:
# whoever can reach this port is already the Overseer. Every other guard -
# the name charset, the body bound, the command vocabulary gate in voice.py
# - holds regardless, because they protect the database and the game rather
# than the page.
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (stdlib naming)
        # A lookup and nothing else. Every GET endpoint takes the parsed
        # query and owns its own method, so adding one is a row in the table
        # at the foot of this class - not another branch here. The chain this
        # replaced had reached eight and tripped the complexity cap when
        # /api/watch landed (infra#2663).
        handler = self.GET_ROUTES.get(self.path.split("?", 1)[0])
        if handler is None:
            self._send(404, "text/plain", b"not found")
            return
        handler(self, parse_qs(urlsplit(self.path).query))

    def _index(self, _query: dict) -> None:
        self._send_file("index.html", "text/html; charset=utf-8")

    def _zones_file(self, _query: dict) -> None:
        self._send_file("zones.json", "application/json")

    def _shapes_file(self, _query: dict) -> None:
        # The zone REGIONS, built from zones.json by tools/gen_shapes.py.
        # Served rather than inlined so the page and the dots keep reading
        # the same committed geometry.
        self._send_file("shapes.json", "application/json")

    def _healthz(self, _query: dict) -> None:
        self._send(200, "text/plain", b"ok")

    def _map(self, _query: dict) -> None:
        """GET /api/map - every fresh snapshot row as placed dots."""
        try:
            payload = build_payload(_fetch_rows(), GEO)
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # The page shows its stale banner on failed polls; a dead
            # database must read as "stale", never a blank page.
            log.exception("map query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _character(self, query: dict) -> None:
        """GET /api/character?name=X - one character's in-game reality."""
        name = query.get("name", [""])[0]
        if not _NAME_RE.fullmatch(name):
            self._send(400, "application/json", b'{"error": "not a character name"}')
            return
        try:
            payload = build_character_panel(**_fetch_character(name))
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as /api/map: a dead database is a 503 the panel
            # can show as "unreachable", never a hang or a blank.
            log.exception("character query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _thoughts(self, query: dict) -> None:
        """GET /api/thoughts?name=X&before=<id>&limit=N - one page, newest first."""
        name = query.get("name", [""])[0]
        if not _NAME_RE.fullmatch(name):
            self._send(400, "application/json", b'{"error": "not a character name"}')
            return
        raw_before = query.get("before", [""])[0]
        if raw_before and not raw_before.isdigit():
            # Silently ignoring a malformed cursor would restart the page at
            # the newest thought and read as "history ends here".
            self._send(400, "application/json", b'{"error": "bad cursor"}')
            return
        limit = chat.page_size(query.get("limit", [""])[0])
        try:
            fetched = _fetch_thoughts(name, int(raw_before) if raw_before else None, limit)
        except Exception:
            log.exception("thought query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')
            return
        if fetched is None:
            self._send(404, "application/json", b'{"error": "no such character"}')
            return
        rows, db_now = fetched
        payload = chat.build_timeline(name, rows, db_now, limit)
        self._send(200, "application/json", json.dumps(payload).encode())

    def do_POST(self):  # noqa: N802 (stdlib naming)
        handler = self.POST_ROUTES.get(self.path.split("?", 1)[0])
        if handler is None:
            self._send(404, "text/plain", b"not found")
            return
        handler(self)

    def _chat_post(self) -> None:
        """POST /api/chat - the Overseer speaks, and one character answers.

        Routing used to live in here alongside the body checks; splitting
        them is what let do_POST become a lookup.
        """
        request = self._read_json_body()
        if request is None:
            return
        name = request.get("name") if isinstance(request.get("name"), str) else ""
        raw_text = request.get("text") if isinstance(request.get("text"), str) else ""
        if not _NAME_RE.fullmatch(name):
            self._send(400, "application/json", b'{"error": "not a character name"}')
            return
        text = chat.clean_message(raw_text)
        if not text:
            self._send(400, "application/json", b'{"error": "say something"}')
            return
        try:
            self._chat(name, text)
        except Exception:
            # Only the database can land here (the LLM leg is caught below
            # and degrades); same contract as every other endpoint.
            log.exception("chat failed for %s", name)
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _chat(self, name: str, text: str) -> None:
        grounding = _fetch_chat_grounding(name)
        if grounding is None:
            self._send(404, "application/json", b'{"error": "no such character"}')
            return
        # The human's words persist BEFORE the model is asked anything: an
        # LLM outage, a timeout, even a crash must never lose what the
        # Overseer said. This is also what makes the exchange visible on
        # Discord - one mind, one stream, whichever surface spoke.
        _insert_thought(name, "chat", chat.overseer_line(text))
        snapshot = grounding["snapshot_row"]
        if snapshot is None:
            # Exists, but not in the fresh snapshot: logged out. Saying so
            # is honest; inventing a reply from a body that is not in the
            # world is not.
            self._send(200, "application/json", json.dumps({
                "present": False,
                "say": f"{name} is not in the world right now.",
            }).encode())
            return
        prompt = chat.build_chat_prompt(
            name=snapshot["name"],
            level=snapshot["level"],
            race_name=_MAP_RACE_NAMES.get(snapshot["race"], "creature"),
            class_name=_MAP_CLASS_NAMES.get(snapshot["class"], "adventurer"),
            zone=GEO.zone_name(snapshot["map_id"], snapshot["pos_x"], snapshot["pos_y"]),
            personality=snapshot["personality"],
            health=snapshot["health"],
            max_health=snapshot["max_health"],
            in_combat=bool(snapshot["in_combat"]),
            recent=grounding["recent"],
            text=text,
        )
        degraded = False
        try:
            decision = chat.parse_reply(_ask_llm(prompt))
        except Exception:
            # An unreachable inner voice degrades to a persisted, honest
            # line - never a 500 with the Overseer's message swallowed.
            log.exception("inner voice unreachable for %s", name)
            decision = voice.Decision(None, chat.outage_line(name))
            degraded = True
        _insert_thought(name, "chat", decision.say)
        if decision.command is not None:
            # voice.parse_decision already gated this string; the web
            # surface delivers it down the same road as Discord.
            row_id = _insert_command(name, decision.command, "web:overseer")
            log.info("web chat queued command %s for %s: %s", row_id, name, decision.command)
        self._send(200, "application/json", json.dumps({
            "present": True,
            "say": decision.say,
            "command": decision.command,
            "degraded": degraded,
        }).encode())

    def _watch_state(self, query: dict) -> None:
        """GET /api/watch?name=X - is anyone watching, and how do they look?

        Also the SWEEP. A viewer who closed the tab sends nothing ever again,
        so nothing they do can end their stream - something else has to
        notice. Every read of this endpoint expires whatever has gone quiet,
        which means the map merely being open keeps the world tidy.
        """
        name = query.get("name", [""])[0]
        try:
            rows = _fetch_streams()
            expired = stream_expire(rows, time.time())
            if expired:
                log.info("stream: expiring %d stale row(s): %s",
                         len(expired), ", ".join(expired))
        except Exception:
            log.exception("stream state read failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')
            return
        mine = next((r for r in rows if r.get("character") == name), None)
        payload = {
            "channels_in_use": stream.channels_in_use(rows),
            "max_channels": stream.MAX_CHANNELS,
            "heartbeat_seconds": stream.HEARTBEAT_SECONDS,
            "watching": None,
        }
        if mine and mine.get("state") in stream.OCCUPIES_A_CLIENT:
            payload["watching"] = {
                "state": mine.get("state"),
                "mode": mine.get("mode"),
                "detail": mine.get("detail") or "",
                "delivery": stream.delivery_of(mine),
            }
        self._send(200, "application/json", json.dumps(payload).encode())

    def _watch_post(self) -> None:
        """POST /api/watch - {name, mode, action}

        action=start  ask the Windows agent for a client
        action=beat   "still here" - the ONLY thing keeping the client alive
        action=stop   the viewer said so out loud
        """
        request = self._read_json_body()
        if request is None:
            return
        name = request.get("name") if isinstance(request.get("name"), str) else ""
        action = request.get("action") if isinstance(request.get("action"), str) else ""
        mode = request.get("mode") if isinstance(request.get("mode"), str) else "cam"
        if not _NAME_RE.fullmatch(name):
            self._send(400, "application/json", b'{"error": "not a character name"}')
            return
        if action not in ("start", "beat", "stop"):
            self._send(400, "application/json", b'{"error": "unknown action"}')
            return
        try:
            self._watch_act(name, action, mode)
        except Exception:
            log.exception("watch %s failed for %s", action, name)
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _watch_act(self, name: str, action: str, mode: str) -> None:
        rows = _fetch_streams()
        stream_expire(rows, time.time())
        if action == "beat":
            # Deliberately cheap and deliberately unconditional: a heartbeat
            # for a row that has already ended is not an error, it is a viewer
            # whose tab has not noticed yet.
            _touch_stream(name)
            self._send(200, "application/json", b'{"ok": true}')
            return
        if action == "stop":
            _stop_stream(name)
            self._send(200, "application/json", b'{"ok": true}')
            return
        allowed, why = stream.can_start(rows, name, mode)
        if not allowed:
            self._send(409, "application/json",
                       json.dumps({"error": why}).encode())
            return
        if not _character_exists_by_name(name):
            self._send(404, "application/json", b'{"error": "no such character"}')
            return
        _request_stream(name, mode)
        log.info("stream: requested %s for %s", mode, name)
        self._send(200, "application/json", b'{"ok": true, "state": "requested"}')

    def _read_json_body(self) -> dict | None:
        """The POST body as a dict, or None after sending the error itself."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0:
            self._send(400, "application/json", b'{"error": "empty request"}')
            return None
        if length > MAX_BODY:
            # Bounded read: this endpoint takes a name and a sentence, and
            # an unbounded rfile.read is a memory hole on a public port.
            self._send(413, "application/json", b'{"error": "too much to say"}')
            return None
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            self._send(400, "application/json", b'{"error": "not json"}')
            return None
        if not isinstance(body, dict):
            self._send(400, "application/json", b'{"error": "not json"}')
            return None
        return body

    def _send_file(self, name: str, ctype: str) -> None:
        # A file missing from the image must be a readable 500, not a bare
        # connection reset - the page keys its error banner off r.ok.
        try:
            with open(os.path.join(HERE, name), "rb") as f:
                self._send(200, ctype, f.read())
        except OSError:
            log.exception("static file %s unreadable", name)
            self._send(500, "text/plain", b"static file missing from image")

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.info("%s " + fmt, self.address_string(), *args)

    # The tables sit at the foot of the class so every method they name is
    # already defined. Values are plain functions, called with the handler
    # instance - a new endpoint is one row, and an unknown path is one miss.
    GET_ROUTES = {
        "/api/map": _map,
        "/api/character": _character,
        "/api/thoughts": _thoughts,
        "/api/watch": _watch_state,
        "/": _index,
        "/index.html": _index,
        "/zones.json": _zones_file,
        "/shapes.json": _shapes_file,
        "/healthz": _healthz,
    }
    POST_ROUTES = {
        "/api/chat": _chat_post,
        "/api/watch": _watch_post,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # AFTER basicConfig on purpose: this is the one startup step that is
    # allowed to fail, so its exception must actually be formatted and
    # visible rather than emitted through an unconfigured root logger.
    #
    # The stream table must exist before the first watch request, and the
    # migration must run against the LIVE shape rather than be assumed by
    # a CREATE that is a no-op on an existing table. Degrades loudly and
    # keeps serving: a broken stream store must not take the map down,
    # because the map is what Evan actually uses.
    try:
        _ensure_stream_store()
    except Exception:
        log.exception("stream store unavailable - watch controls will fail")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log.info("serving on :%d (threads: %s)", PORT, threading.active_count())
    server.serve_forever()


if __name__ == "__main__":
    main()
