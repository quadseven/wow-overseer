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
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pymysql

import achievements
import agenda
import armory
import basepath
import chat
import council
import decree
import dungeonplan
import eye
import family
import frames
import guildcraft
import modelviewer
import needs
import partystatus
import questlog
import recap
import realm
import standing
import stream
import voice
import wealth
from map_core import build_payload
from panel import build_character_panel
from transform import Geometry

log = logging.getLogger("wow-map")

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = Geometry.load(HERE)
# The frozen client talent tables, read once at import exactly as GEO is.
# `character_talent` stores nothing but spell ids, and acore_world's own
# talent_dbc and talenttab_dbc are EMPTY tables, so this committed file is
# the only thing that can turn a learned spell back into "2/3 Improved
# Renew". Built by tools/gen_talents.py; see armory.py for why it is a
# file rather than a mount or a database load.
BOOK = armory.TalentBook.load(HERE)
# And the item tables, for the same reason: icons, spell text, sets and the
# random-suffix tables are client data, frozen by tools/gen_items.py.
ITEMS = armory.ItemBook.load(HERE)
# The skill, faction and recipe tables, third of the frozen books and read
# once for the same reason as the other two: acore_world's skillline_dbc,
# faction_dbc and skilllineability_dbc are EMPTY, and `acore_world.faction`
# does not exist at all, so a name for a skill or a faction can come from
# nowhere else. Built by tools/gen_standing.py.
STANDING = standing.StandingBook.load(HERE)
PORT = int(os.environ.get("PORT", "8080"))
# WHERE THIS COPY IS MOUNTED. "" at the root, "/dev" under a path. Read
# once at import exactly as PORT is, and deliberately allowed to raise:
# basepath.py says why a value that was SET and cannot be read must stop
# the process rather than quietly become the root. The ingress strips the
# prefix before proxying, so nothing below this line ever reads it - the
# only thing it changes is the URLs the page emits.
BASE_PATH = basepath.normalize(os.environ.get(basepath.ENV_VAR))

# The model-viewer cache (modelviewer.py): an emptyDir on the pod, a temp
# directory locally, capped in bytes either way. The fetcher is the one
# outbound call this server makes to the internet, and it is made only for
# a path modelviewer.classify has admitted.
MODEL_CACHE = modelviewer.DiskCache(
    modelviewer.default_cache_dir(),
    int(os.environ.get("MODEL_CACHE_MB", "512")) * 1024 * 1024,
)


def _fetch_upstream(url: str) -> tuple[int, bytes]:
    # S310: `url` is modelviewer.UPSTREAM plus an allowlisted, charset-checked
    # path - never anything the request wrote - so no scheme other than
    # https can reach here.
    req = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": modelviewer.USER_AGENT})
    try:
        with urllib.request.urlopen(  # noqa: S310
                req, timeout=modelviewer.UPSTREAM_TIMEOUT_SECONDS) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


MODELS = modelviewer.Store(MODEL_CACHE, _fetch_upstream)

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


# --- which realm this is (quadseven/mod-overseer#184) ------------------------
#
# FIRST AMONG THE FETCHES ON PURPOSE, and the handler is likewise first among
# the routes. Every other read on this page answers a question about the world;
# this one answers which world, and that is the question the rest of the page's
# answers are only meaningful inside of. It also keeps this code out of the
# windows that seven other suites slice map_server.py by, none of which start
# above _fetch_rows.
#
# WHY THIS READS THREE PLACES AND NOT ONE. The realms are deliberately not
# rolled together, so on any given day they are running different builds of the
# module, and the newest table is absent on the oldest realm. The banner has to
# be at its most useful exactly there:
#
#   overseer_build       everything, when the realm's worldserver is new enough
#                        to have it. The only source that knows the realm kind.
#   acore_world.version  AzerothCore writing down its own revision at startup,
#                        with no module involved. Present on every realm that
#                        has ever started, which is what lets this banner name
#                        the core before a single worldserver has been rolled.
#   acore_auth.realmlist the realm's client-facing name, for the same reason.
#
# EVERY ONE OF THE THREE IS GUARDED, INCLUDING THE TWO CORE TABLES that nothing
# else on this page bothers to guard. That is not consistency for its own sake.
# The rule elsewhere is that a core table is always there and a module table may
# not be, and the rule is right - but it is a rule about tables, and this is the
# one banner on the site whose whole job is to be trustworthy when something is
# wrong. A page that renders "REALM NOT VERIFIED" is doing its job; a page that
# 500s has told the reader nothing at all about what they are looking at.
_BUILD_SQL = "SELECT name, value, source, reported_at FROM overseer_build"
_WORLD_VERSION_SQL = "SELECT core_version FROM acore_world.version LIMIT 1"
_REALMLIST_SQL = "SELECT name FROM acore_auth.realmlist ORDER BY id LIMIT 1"


def _realm_guarded(cur, sql: str, what: str) -> list:
    """Run `sql`, returning [] on a degraded schema and raising on anything else.

    WHY THIS DOES NOT REUSE _guarded, WHICH DOES ALMOST THE SAME THING. That
    helper catches pymysql.err.ProgrammingError, and error 1054 is NOT a
    ProgrammingError. Verified against pymysql 1.4.6 as deployed, by asking the
    live realm's own database for a column that does not exist:

        MISSING TABLE  -> pymysql.err.ProgrammingError 1146
        MISSING COLUMN -> pymysql.err.OperationalError  1054

    1054 is absent from pymysql's error_map, so raise_mysql_exception falls back
    to OperationalError for it. The base class MySQLError is the only catch that
    covers both, and it is what bridge.py already uses for exactly this pair.
    Copying the more obvious helper would have produced a guard that reads
    correctly, passes review, and never once fires on half of what it names.

    (The same gap exists in _guarded itself. Widening it is a real fix and it
    belongs to the banner it would change the behaviour of, not to this one.)
    """
    try:
        cur.execute(sql)
        return list(cur.fetchall())
    except pymysql.err.MySQLError as exc:
        # 1146 missing table, 1054 missing column: this realm's worldserver
        # predates the migration. A thinner banner, not a broken one. Anything
        # else is a real fault and must still reach the handler's 503, because
        # a banner that silently reported "not verified" for a network blip
        # would train the alarm away.
        if not (exc.args and exc.args[0] in (1054, 1146)):
            raise
        log.info("realm: %s unavailable (%s); the banner runs without it",
                 what, exc.args[0])
        return []


def _fetch_realm() -> dict:
    """Everything the realm banner reads, in one connection.

    No parameters and no user input anywhere in it: this endpoint answers a
    question about the deployment, not about anybody the caller can name.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            build_rows = _realm_guarded(cur, _BUILD_SQL, "overseer_build")
            version_rows = _realm_guarded(cur, _WORLD_VERSION_SQL,
                                          "acore_world.version")
            realmlist_rows = _realm_guarded(cur, _REALMLIST_SQL,
                                            "acore_auth.realmlist")
    finally:
        conn.close()
    return {"build_rows": build_rows, "version_rows": version_rows,
            "realmlist_rows": realmlist_rows}


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


def _fetch_family() -> list[dict]:
    """The family's fresh snapshot rows, in one query.

    Deliberately the same 60s freshness rule as /api/map and /api/character:
    a member the sweep has already removed must read as "left the world" on
    the card at the same moment they leave the map, or the two surfaces
    disagree about who is online.

    Names come from bonds via family.roster(), never from the request, so
    this is a fixed IN list of five - there is no user input in this SQL.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # S608: `holes` is a run of "%s" placeholders whose only input is
            # the LENGTH of family.roster() - a constant five, from bonds.
            # Every VALUE is still bound by the driver on the line below,
            # nothing from the request reaches this string, and this endpoint
            # takes no name parameter at all. Hard-coding five placeholders
            # to dodge the f-string would silently query the wrong number of
            # characters the day the family gains or loses somebody.
            cur.execute(
                "SELECT guid, name, level, race, class, health, max_health, "  # noqa: S608
                "in_combat, is_bot, group_leader, map_id, pos_x, pos_y, "
                "TIMESTAMPDIFF(SECOND, updated_at, NOW()) AS age_seconds "
                "FROM overseer_snapshot "
                f"WHERE name IN ({holes}) AND updated_at > NOW() - INTERVAL 60 SECOND",
                tuple(names),
            )
            return list(cur.fetchall())
    finally:
        conn.close()


# --- the Wealth and Bags view (quadseven/mod-overseer#88) -----------------
# Everything wealth.py reads off an item, which is a far shorter list than a
# tooltip needs: a bag grid wants the picture, the colour, the price and how
# big the bag is, and nothing else. Listed once, here, so the query and the
# builder's row contract are the same list.
_WEALTH_ITEM_COLUMNS = (
    "it.name AS item_name, it.Quality AS quality, it.ItemLevel AS item_level, "
    "it.SellPrice AS sell_price, it.class, it.subclass, it.displayid, "
    "it.ContainerSlots AS container_slots"
)


def _fetch_wealth() -> dict:
    """The family's purse, every inventory row they own, and the auction house.

    NOT read from overseer_snapshot and, like /api/armory, deliberately not
    subject to its 60s freshness rule: money and bags are what the core has
    SAVED, so they survive a logout and they still answer "what is he
    carrying" for somebody who is not in the world right now.

    THE INVENTORY QUERY IS UNBOUNDED BY SLOT ON PURPOSE. /api/armory asks for
    `ci.bag = 0 AND ci.slot < len(armory.EQUIPPED_SLOTS)` because it draws a
    paper doll. This view draws everything a character owns, and deciding
    which (bag, slot) pair is a bag, the backpack or the bank is exactly the
    judgement that lives in wealth.split_inventory where the suite can reach
    it. Filtering here would move that decision into SQL nothing tests.

    Names come from bonds via family.roster(), never from the request, so
    every IN list here is a fixed five with no user input in it.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # S608 on all three: `holes` is a run of "%s" placeholders whose
            # only input is the LENGTH of family.roster() - a constant five,
            # from bonds. Every VALUE is still bound by the driver, and this
            # endpoint takes no parameters at all.
            cur.execute(
                "SELECT c.name, c.level, c.class, c.money "  # noqa: S608
                f"FROM characters c WHERE c.name IN ({holes})",
                tuple(names),
            )
            char_rows = list(cur.fetchall())
            # The item's name, quality, price and container size live in the
            # WORLD database, not this one, so this is the same cross-schema
            # join panel's inventory query already makes. LEFT, so a custom
            # or removed item still occupies its slot rather than vanishing
            # out of a fullness count that exists to be believed.
            # ci.item is the item_instance guid, and it is what the rows
            # INSIDE a bag name in their own `bag` column: without it there
            # is no way to tell which container an item is in.
            cur.execute(
                "SELECT c.name, ci.bag, ci.slot, ci.item AS item_guid, "  # noqa: S608
                "ii.itemEntry AS entry, ii.count, "
                f"{_WEALTH_ITEM_COLUMNS} "
                "FROM characters c "
                "JOIN character_inventory ci ON ci.guid = c.guid "
                "JOIN item_instance ii ON ii.guid = ci.item "
                "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            inventory_rows = list(cur.fetchall())
            # auctionhouse holds LIVE auctions only - the core deletes the row
            # when one completes - and it keys owner and bidder by character
            # guid, so both are joined back to a name here rather than left as
            # numbers the builder would have to resolve. Two IN lists: their
            # own listings, and anything they are the top bidder on.
            cur.execute(
                "SELECT a.id, a.startbid, a.lastbid, a.buyoutprice, "  # noqa: S608
                "a.deposit, a.time, o.name AS owner_name, b.name AS buyer_name, "
                "ii.itemEntry AS entry, ii.count, "
                f"{_WEALTH_ITEM_COLUMNS} "
                "FROM auctionhouse a "
                "JOIN item_instance ii ON ii.guid = a.itemguid "
                "LEFT JOIN characters o ON o.guid = a.itemowner "
                "LEFT JOIN characters b ON b.guid = a.buyguid "
                "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
                f"WHERE o.name IN ({holes}) OR b.name IN ({holes})",
                tuple(names) * 2,
            )
            auction_rows = list(cur.fetchall())
            # WHETHER THERE IS A GUILD AT ALL, asked rather than assumed. The
            # guild bank panel says there is no guild bank because there is no
            # guild, and that sentence has to stop being drawn on the day
            # somebody makes one - which a constant in the builder could never
            # do. An INNER JOIN, so no rows means nobody is in a guild.
            cur.execute(
                "SELECT c.name, g.name AS guild_name "  # noqa: S608
                "FROM characters c "
                "JOIN guild_member gm ON gm.guid = c.guid "
                "JOIN guild g ON g.guildid = gm.guildid "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            guild_rows = list(cur.fetchall())
    finally:
        conn.close()
    return {"char_rows": char_rows, "inventory_rows": inventory_rows,
            "auction_rows": auction_rows, "guild_rows": guild_rows}


# Everything a tooltip draws, straight off item_template. Listed once, here,
# so the query and the builder's row contract are the same list.
_ITEM_TEMPLATE_COLUMNS = (
    "it.name AS item_name, it.Quality AS quality, it.ItemLevel AS item_level, "
    "it.RequiredLevel AS required_level, it.MaxDurability AS max_durability, "
    "it.displayid, it.class, it.subclass, it.InventoryType AS inventory_type, "
    "it.armor, it.block, it.bonding, it.itemset, it.SellPrice AS sell_price, "
    "it.AllowableClass AS allowable_class, it.description, "
    "it.dmg_min1, it.dmg_max1, it.delay, "
    "it.holy_res, it.fire_res, it.nature_res, it.frost_res, it.shadow_res, it.arcane_res, "
    + ", ".join(f"it.stat_type{n}, it.stat_value{n}" for n in range(1, 11)) + ", "
    + ", ".join(f"it.spellid_{n}, it.spelltrigger_{n}" for n in range(1, 6))
)


def _fetch_armory() -> dict:
    """The family's saved gear, talents and stats, in a handful of queries.

    NOT read from overseer_snapshot, and deliberately NOT subject to its 60s
    freshness rule. Gear and talents are what the core has SAVED, so they
    survive a logout and they still answer "what is he carrying" for someone
    who is not in the world right now - which is a good part of the reason to
    open the tab. It also means this endpoint keeps answering while the
    worldserver is down, because nothing here needs the worldserver.

    Names come from bonds via family.roster(), never from the request, so all
    three of these are a fixed IN list of five with no user input in them.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # S608 on all three: `holes` is a run of "%s" placeholders whose
            # only input is the LENGTH of family.roster() - a constant five,
            # from bonds. Every VALUE is still bound by the driver, and this
            # endpoint takes no parameters at all. Same reasoning, and the
            # same refusal to hard-code five, as _fetch_family.
            # The guild is a LEFT JOIN because most of the family are in
            # none, and a character in no guild is a character with no
            # guild line, not a missing row.
            cur.execute(
                "SELECT c.name, c.level, c.race, c.class, c.gender, c.online, "  # noqa: S608
                "c.activeTalentGroup, c.totalKills, g.name AS guild, "
                # The face the character was made with, for the 3D model:
                # five indexes into the race's choice lists (armory.viewer_model).
                "c.skin, c.face, c.hairStyle, c.hairColor, c.facialStyle "
                "FROM characters c "
                "LEFT JOIN guild_member gm ON gm.guid = c.guid "
                "LEFT JOIN guild g ON g.guildid = gm.guildid "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            char_rows = list(cur.fetchall())
            # The item's name, quality and level live in the WORLD database,
            # not this one, so this is a cross-schema join - the same one
            # panel's inventory query already makes. LEFT, so a custom or
            # removed item still reports as equipped rather than as an empty
            # slot. bag = 0 and the slot bound are the equipped paper doll;
            # the bound comes from armory so the query and the grid cannot
            # disagree about how many slots there are.
            # enchantments and randomPropertyId are the item INSTANCE's:
            # they are what makes this belt a "Belt of the Tiger" and not
            # the template's plain belt, and they are where half the family's
            # stats actually live.
            cur.execute(
                "SELECT c.name, ci.slot, ii.itemEntry AS entry, "  # noqa: S608
                "ii.durability, ii.enchantments, "
                "ii.randomPropertyId AS random_property_id, "
                f"{_ITEM_TEMPLATE_COLUMNS} "
                "FROM characters c "
                "JOIN character_inventory ci ON ci.guid = c.guid "
                "AND ci.bag = 0 AND ci.slot < %s "
                "JOIN item_instance ii ON ii.guid = ci.item "
                "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
                f"WHERE c.name IN ({holes})",
                (len(armory.EQUIPPED_SLOTS), *names),
            )
            equipment_rows = list(cur.fetchall())
            # The equip record, for the provenance line under each item. It is
            # guarded where the reads above are not, and for a reason: those
            # are core tables that are always there, and overseer_event is
            # written by the in-world module, so a realm whose schema predates
            # it must still get a paper doll. A grid with no provenance is a
            # thinner tab; a 503 is a blank one (infra#3172).
            equip_event_rows = _wide_guarded(
                cur, _RECAP_EQUIPS.format(holes=holes), tuple(names), "",  # noqa: S608
                "overseer_event")
            # The set a piece belongs to lists its other pieces by entry, and
            # the tooltip names them: one more query, bounded by the sets
            # anybody is actually wearing (usually none).
            sets = sorted({r["itemset"] for r in equipment_rows if r["itemset"]})
            set_rows: list[dict] = []
            if sets:
                set_holes = ", ".join(["%s"] * len(sets))
                cur.execute(
                    "SELECT entry, name AS item_name "  # noqa: S608
                    "FROM acore_world.item_template "
                    f"WHERE itemset IN ({set_holes})",
                    tuple(sets),
                )
                set_rows = list(cur.fetchall())
            cur.execute(
                "SELECT c.name, t.spell, t.specMask "  # noqa: S608
                "FROM characters c JOIN character_talent t ON t.guid = c.guid "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            talent_rows = list(cur.fetchall())
            # character_stats is the core's own derived numbers - written on
            # save when PlayerSave.Stats.MinLevel allows, so a member may
            # have no row yet. The builder falls back to base + gear for
            # what it can and says "unavailable" for the rest.
            cur.execute(
                "SELECT c.name, s.maxhealth, s.maxpower1, s.maxpower2, "  # noqa: S608
                "s.maxpower4, s.maxpower7, s.strength, s.agility, s.stamina, "
                "s.intellect, s.spirit, s.armor, s.blockPct, s.dodgePct, "
                "s.parryPct, s.critPct, s.rangedCritPct, s.spellCritPct, "
                "s.attackPower, s.rangedAttackPower, s.spellPower "
                "FROM characters c JOIN character_stats s ON s.guid = c.guid "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            stats_rows = list(cur.fetchall())
            # The base stats a race and class have at a level, for the
            # fallback. Two world tables, joined on nothing: the race row is
            # a flat modifier added to every level of the class row.
            cur.execute(
                "SELECT r.Race AS race, cs.Class AS class, cs.Level AS level, "  # noqa: S608
                "cs.BaseHP AS health, cs.BaseMana AS mana, "
                "cs.Strength + r.Strength AS strength, cs.Agility + r.Agility AS agility, "
                "cs.Stamina + r.Stamina AS stamina, cs.Intellect + r.Intellect AS intellect, "
                "cs.Spirit + r.Spirit AS spirit "
                "FROM acore_world.player_class_stats cs "
                "JOIN acore_world.player_race_stats r "
                "JOIN characters c ON c.class = cs.Class AND c.level = cs.Level "
                "AND c.race = r.Race "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            base_rows = list(cur.fetchall())
    finally:
        conn.close()
    return {"equip_event_rows": equip_event_rows,
            "char_rows": char_rows, "equipment_rows": equipment_rows,
            "talent_rows": talent_rows, "stats_rows": stats_rows,
            "base_rows": base_rows, "set_rows": set_rows}


def _fetch_standing() -> dict:
    """What the family has LEARNED: trades, skills, reputations, talents.

    Five queries, all against acore_characters and all of them plain reads.
    NOT read from overseer_snapshot and, like /api/armory, deliberately not
    subject to its 60s freshness rule: every one of these is a SAVE, so it
    answers for a character who is logged out and it keeps answering while
    the worldserver is down.

    Nothing here joins a `*_dbc` table, and that is the point rather than an
    omission - every one of them is empty on this realm (see standing.py).
    The names come from the frozen book instead.

    Names come from bonds via family.roster(), never from the request, so
    every IN list is a fixed five with no user input in it.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # S608 on all five, and the same reasoning as _fetch_armory:
            # `holes` is a run of "%s" placeholders whose only input is the
            # LENGTH of family.roster() - a constant five, from bonds. Every
            # VALUE is bound by the driver and this endpoint takes no
            # parameters at all.
            cur.execute(
                "SELECT c.name, c.level, c.race, c.class, "  # noqa: S608
                "c.activeTalentGroup "
                "FROM characters c "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            char_rows = list(cur.fetchall())
            cur.execute(
                "SELECT c.name, s.skill, s.value, s.max "  # noqa: S608
                "FROM characters c JOIN character_skills s ON s.guid = c.guid "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            skill_rows = list(cur.fetchall())
            # Every faction in the game has a row here for every character,
            # met or not - about a hundred each. `flags` is what tells them
            # apart and the filtering is standing.met's job, not SQL's, so
            # the rule lives where the suite can reach it.
            cur.execute(
                "SELECT c.name, r.faction, r.standing, r.flags "  # noqa: S608
                "FROM characters c JOIN character_reputation r ON r.guid = c.guid "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            reputation_rows = list(cur.fetchall())
            cur.execute(
                "SELECT c.name, t.spell, t.specMask "  # noqa: S608
                "FROM characters c JOIN character_talent t ON t.guid = c.guid "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            talent_rows = list(cur.fetchall())
            # Every spell the character knows, which is where the recipes
            # are. Around forty rows each; the book decides which of them
            # are recipes rather than the query, because "is this spell a
            # recipe" is a question about client data this database has
            # none of.
            cur.execute(
                "SELECT c.name, s.spell "  # noqa: S608
                "FROM characters c JOIN character_spell s ON s.guid = c.guid "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            spell_rows = list(cur.fetchall())
    finally:
        conn.close()
    return {"char_rows": char_rows, "skill_rows": skill_rows,
            "reputation_rows": reputation_rows, "talent_rows": talent_rows,
            "spell_rows": spell_rows}


# The quest log query, written out rather than generated. Forty column
# spellings in one string is not pretty, but the alternative - building the
# list in a loop - means the one place a person goes to check what this query
# reads no longer says what it reads. bridge.py's _QUEST_SQL makes the same
# choice for the same reason.
#
# The two %s are filled in with runs of "%s" placeholders sized by
# len(family.roster()) and len(questlog.IN_LOG) - both constants from this
# codebase, neither from the request. Every VALUE is still bound by the
# driver, and this endpoint takes no parameters at all.
_QUESTLOG_SQL = (
    "SELECT c.name, q.quest, q.status, "
    "q.mobcount1, q.mobcount2, q.mobcount3, q.mobcount4, "
    "q.itemcount1, q.itemcount2, q.itemcount3, "
    "q.itemcount4, q.itemcount5, q.itemcount6, q.playercount, "
    "t.LogTitle, t.QuestLevel, t.RequiredPlayerKills, "
    "t.RequiredNpcOrGo1, t.RequiredNpcOrGo2, "
    "t.RequiredNpcOrGo3, t.RequiredNpcOrGo4, "
    "t.RequiredNpcOrGoCount1, t.RequiredNpcOrGoCount2, "
    "t.RequiredNpcOrGoCount3, t.RequiredNpcOrGoCount4, "
    "t.RequiredItemId1, t.RequiredItemId2, t.RequiredItemId3, "
    "t.RequiredItemId4, t.RequiredItemId5, t.RequiredItemId6, "
    "t.RequiredItemCount1, t.RequiredItemCount2, t.RequiredItemCount3, "
    "t.RequiredItemCount4, t.RequiredItemCount5, t.RequiredItemCount6, "
    "t.ObjectiveText1, t.ObjectiveText2, t.ObjectiveText3, t.ObjectiveText4 "
    "FROM characters c "
    "JOIN character_queststatus q ON q.guid = c.guid "
    "JOIN acore_world.quest_template t ON t.ID = q.quest "
    "WHERE c.name IN (%s) AND q.status IN (%s)"
)


def _fetch_names(cur, table: str, entries: list) -> dict:
    """entry -> name, for one acore_world template table.

    Looked up by id AFTER the quest rows are in hand rather than as ten more
    LEFT JOINs on the query above: a quest may name four creatures and six
    items, the same murloc shows up in half the family's logs, and joining
    would fetch each name once per row that mentions it. `table` is a literal
    from the one call site below and never touches the request.
    """
    if not entries:
        return {}
    holes = ", ".join(["%s"] * len(entries))
    # S608: `holes` is a run of placeholders sized by len(entries), and
    # `table` is one of three hard-coded literals from _fetch_questlog. Every
    # VALUE is still bound by the driver on the next line.
    cur.execute(
        f"SELECT entry, name FROM acore_world.{table} "  # noqa: S608
        f"WHERE entry IN ({holes})",
        tuple(entries),
    )
    return {int(row["entry"]): row["name"] for row in cur.fetchall()}


def _fetch_questlog() -> dict:
    """The family's quest logs, and enough of acore_world to read them.

    NOT from overseer_snapshot and, like /api/armory, deliberately not subject
    to its 60s freshness rule: a quest log is SAVED state, so it still answers
    "what was he working on" for somebody who logged out an hour ago - which
    is a good part of the reason to look.

    Names come from bonds via family.roster(), never from the request, so the
    roster clause is a fixed IN list of five with no user input in it.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    statuses = ", ".join(["%s"] * len(questlog.IN_LOG))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, level, class, online "  # noqa: S608
                f"FROM characters WHERE name IN ({holes})",
                tuple(names),
            )
            char_rows = list(cur.fetchall())
            cur.execute(_QUESTLOG_SQL % (holes, statuses),
                        (*names, *questlog.IN_LOG))
            quest_rows = list(cur.fetchall())
            # Turn-ins, counted in SQL rather than fetched as rows: this is
            # 160 rows across the five today and grows for the life of the
            # realm, and the only thing anything does with them is len().
            cur.execute(
                "SELECT c.name, COUNT(*) AS turned_in "  # noqa: S608
                "FROM characters c "
                "JOIN character_queststatus_rewarded r ON r.guid = c.guid "
                f"WHERE c.name IN ({holes}) GROUP BY c.guid, c.name",
                tuple(names),
            )
            rewarded_rows = list(cur.fetchall())
            # WHO HAS ALREADY TURNED IN what somebody else still holds
            # (infra#88): the board dims those portraits so "everyone else
            # did this one" is visible. Restricted to quests in a live log
            # by the subquery, so this stays a few dozen rows rather than
            # every turn-in the realm has ever recorded.
            cur.execute(
                "SELECT c.name, r.quest "  # noqa: S608
                "FROM characters c "
                "JOIN character_queststatus_rewarded r ON r.guid = c.guid "
                f"WHERE c.name IN ({holes}) AND r.quest IN ("
                "SELECT q.quest FROM character_queststatus q "
                "JOIN characters h ON h.guid = q.guid "
                f"WHERE h.name IN ({holes}) AND q.status IN ({statuses}))",
                (*names, *names, *questlog.IN_LOG),
            )
            done_rows = list(cur.fetchall())
            # WHO IS GROUPED WITH WHOM, from the same fresh snapshot window
            # /api/family reads: a helper is a party member who does not
            # hold the quest, and a party is a live fact, not a saved one.
            cur.execute(
                "SELECT guid, name, group_leader FROM overseer_snapshot "  # noqa: S608
                f"WHERE name IN ({holes}) "
                "AND updated_at > NOW() - INTERVAL 60 SECOND",
                tuple(names),
            )
            party_rows = list(cur.fetchall())
            # WHICH ids to look up is a decision about column spellings, and
            # RequiredNpcOrGo being negative for a gameobject is exactly the
            # kind of thing an adapter should not know. questlog owns it.
            wanted = questlog.objective_entries(quest_rows)
            lookups = {
                "creatures": _fetch_names(cur, "creature_template",
                                          wanted["creatures"]),
                "gameobjects": _fetch_names(cur, "gameobject_template",
                                            wanted["gameobjects"]),
                "items": _fetch_names(cur, "item_template", wanted["items"]),
            }
    finally:
        conn.close()
    return {"char_rows": char_rows, "quest_rows": quest_rows,
            "rewarded_rows": rewarded_rows, "names": lookups,
            "done_rows": done_rows, "party_rows": party_rows}


def _fetch_achievements() -> dict:
    """What the family has done: runs, events, deaths, and the world rows
    that name what they gained.

    Not subject to the 60s freshness rule, for the same reason /api/armory is
    not: everything here already happened. overseer_dungeon_run ships in a
    later migration than overseer_event, so a realm whose schema predates it
    (error 1146) still gets its quests and levels - the runs are the bonus,
    not the condition, in the pattern bridge.py established for the digest.

    Names come from bonds via family.roster(), never from the request.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "SELECT id, leader_name, map_id, state, started_at, "
                    "last_progress_at, ended_at, ended_reason "
                    "FROM overseer_dungeon_run ORDER BY started_at DESC LIMIT 500"
                )
                run_rows = list(cur.fetchall())
            except pymysql.err.ProgrammingError as exc:
                if not (exc.args and exc.args[0] == 1146):
                    raise
                log.info("overseer_dungeon_run absent; achievements run without it")
                run_rows = []
            # S608 on the three below: `holes` is a run of placeholders sized
            # by the roster, and every VALUE is bound by the driver. Deaths
            # come from overseer_death, the un-coalesced record, so the
            # hourly-bucketed death rows in overseer_event are skipped here.
            # THE SAME 1146 GUARD AS THE RUN TABLE ABOVE, AND FOR THE SAME
            # REASON, LEARNED THE HARD WAY IN PRODUCTION. These tables are
            # created by the in-world module, so a realm running an older
            # worldserver simply does not have all of them yet: the live
            # realm had `overseer_event` but no `overseer_death` on the day
            # this tab shipped, and an unguarded query turned the whole tab
            # into a 503 there while every other tab was fine. A world with
            # no death record has nothing to say about deaths, which is a
            # thinner page, not a broken one.
            try:
                cur.execute(
                    "SELECT character_name, kind, subject_id, subject_name, detail, "  # noqa: S608
                    "level, map, zone, first_seen, last_seen, occurrences "
                    "FROM overseer_event "
                    f"WHERE kind <> 'death' AND character_name IN ({holes}) "
                    "ORDER BY first_seen ASC LIMIT 20000",
                    tuple(names),
                )
                event_rows = list(cur.fetchall())
            except pymysql.err.ProgrammingError as exc:
                if not (exc.args and exc.args[0] == 1146):
                    raise
                log.info("overseer_event absent; achievements run without it")
                event_rows = []
            try:
                cur.execute(
                    "SELECT character_name, map, zone, killer_name, killer_type, "  # noqa: S608
                    f"created_at FROM overseer_death WHERE character_name IN ({holes}) "
                    "ORDER BY created_at ASC LIMIT 20000",
                    tuple(names),
                )
                death_rows = list(cur.fetchall())
            except pymysql.err.ProgrammingError as exc:
                if not (exc.args and exc.args[0] == 1146):
                    raise
                log.info("overseer_death absent; achievements run without deaths")
                death_rows = []
            # Which world rows to look up is a decision about event kinds and
            # dungeon boss lists; achievements owns it, the adapter just asks.
            quest_ids = achievements.wanted_quests(event_rows)
            quest_rows = []
            if quest_ids:
                qholes = ", ".join(["%s"] * len(quest_ids))
                cur.execute(
                    "SELECT ID, RewardItem1, RewardItem2, RewardItem3, RewardItem4, "  # noqa: S608
                    "RewardAmount1, RewardAmount2, RewardAmount3, RewardAmount4, "
                    "RewardChoiceItemID1, RewardChoiceItemID2, RewardChoiceItemID3, "
                    "RewardChoiceItemID4, RewardChoiceItemID5, RewardChoiceItemID6 "
                    f"FROM acore_world.quest_template WHERE ID IN ({qholes})",
                    tuple(quest_ids),
                )
                quest_rows = list(cur.fetchall())
            quest_rewards = achievements.quest_rewards_from_rows(quest_rows)
            bosses = achievements.wanted_bosses(run_rows)
            drop_rows = []
            if bosses:
                bholes = ", ".join(["%s"] * len(bosses))
                cur.execute(
                    "SELECT c.entry AS creature, l.Item AS item "  # noqa: S608
                    "FROM acore_world.creature_template c "
                    "JOIN acore_world.creature_loot_template l ON l.Entry = c.lootid "
                    "JOIN acore_world.item_template i ON i.entry = l.Item "
                    f"WHERE c.entry IN ({bholes}) AND l.Reference = 0 "
                    "AND i.Quality >= %s",
                    (*bosses, achievements.SIGNATURE_QUALITY),
                )
                drop_rows = list(cur.fetchall())
            boss_drops = achievements.boss_drops_from_rows(drop_rows)
            entries = achievements.wanted_entries(event_rows, quest_rewards, boss_drops)
            items = {}
            if entries:
                iholes = ", ".join(["%s"] * len(entries))
                # READ WIDE ENOUGH FOR A TOOLTIP (infra#3501). This used to
                # select five columns, which is a name in a colour and
                # nothing a reader could act on; the Chronicle's gear names
                # now open the item's own lines in place, and those lines are
                # built from these columns rather than fetched from wowhead.
                # The list is bounded by achievements.wanted_entries, which is
                # already narrowed to the items these cards actually draw, so
                # the wider read is over the same handful of rows.
                cur.execute(
                    f"SELECT it.entry, {_ITEM_TEMPLATE_COLUMNS} "  # noqa: S608
                    "FROM acore_world.item_template it "
                    f"WHERE it.entry IN ({iholes})",
                    tuple(entries),
                )
                items = {int(r["entry"]): r for r in cur.fetchall()}
    finally:
        conn.close()
    return {"run_rows": run_rows, "event_rows": event_rows, "death_rows": death_rows,
            "items": items, "icons": ITEMS.icons, "book": ITEMS,
            "boss_drops": boss_drops,
            "quest_rewards": quest_rewards, "roster": names}


# --- the Family view's needs, handovers and bonds (infra#2597) ------------
#
# WHERE THIS SITS AND WHY. Below every other fetch and above
# _ensure_stream_store, which puts it inside the Armory's fetch window and
# outside the Wealth one - and that is the constraint, not a preference. The
# Wealth suite reads `# --- the Wealth and Bags view` to
# `# Everything a tooltip draws` as that view's SQL and asserts the inventory
# query is NOT bounded by slot; the durability read below is bounded by slot,
# because a paper doll is exactly what it wants. Dropping it in there would
# fail an assertion about a query it has nothing to do with.
#
# SIX READS, ON A THIRTY SECOND POLL. Every one of them is SAVED state - bags,
# durability and money are written on the core's own player-save timer, and
# the give rows and thoughts are written by the bridge - so none of it can
# change faster than the cadence, and putting any of it on /api/family's 5s
# poll would re-fetch an identical answer six times per actual change.
#
# Names come from bonds via family.roster(), never from the request, so every
# IN list here is a fixed five with no user input in it.
def _fetch_needs() -> dict:
    """The bags, gear, purse, trades, give attempts and thoughts of the five.

    Fetches rows and does nothing else (infra#2597). Which slot is a bag,
    which skill is a profession, which thought was said out loud, what counts
    as "no room" and when the family has given up are all decisions, and every
    one of them lives in needs.py where the stdlib suite can reach it.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # S608 on all of these: `holes` is a run of "%s" placeholders
            # whose only input is the LENGTH of family.roster() - a constant
            # five, from bonds. Every VALUE is still bound by the driver, and
            # this endpoint takes no parameters at all.
            cur.execute(
                "SELECT c.name, c.money FROM characters c "  # noqa: S608
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            char_rows = list(cur.fetchall())
            # The same unbounded inventory read /api/wealth makes, with the
            # same column list, so the two views cannot come to different
            # answers about how full a bag is. Unbounded because which
            # (bag, slot) pair is a bag, the backpack or the bank is
            # wealth.split_inventory's judgement to make.
            cur.execute(
                "SELECT c.name, ci.bag, ci.slot, ci.item AS item_guid, "  # noqa: S608
                "ii.itemEntry AS entry, ii.count, "
                f"{_WEALTH_ITEM_COLUMNS} "
                "FROM characters c "
                "JOIN character_inventory ci ON ci.guid = c.guid "
                "JOIN item_instance ii ON ii.guid = ci.item "
                "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            inventory_rows = list(cur.fetchall())
            # DURABILITY, off the worn slots only. Bounded by
            # len(armory.EQUIPPED_SLOTS) for the same reason /api/armory is:
            # the bound and the paper doll must come from one list, and a 19
            # typed here would silently drop a slot the day that list grows.
            # LEFT, so a custom item still occupies its slot; MaxDurability of
            # 0 is an item that cannot break, which needs.py tells apart from
            # one that is broken.
            cur.execute(
                "SELECT c.name, ci.slot, ii.durability, "  # noqa: S608
                "it.MaxDurability AS max_durability "
                "FROM characters c "
                "JOIN character_inventory ci ON ci.guid = c.guid "
                "AND ci.bag = 0 AND ci.slot < %s "
                "JOIN item_instance ii ON ii.guid = ci.item "
                "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
                f"WHERE c.name IN ({holes})",
                (len(armory.EQUIPPED_SLOTS), *names),
            )
            equipment_rows = list(cur.fetchall())
            # EVERY skill row, unfiltered. character_skills also holds
            # languages, Defence and every weapon skill, and which of them is
            # a profession is needs.held_skills' decision - an IN list of ids
            # built here would be that decision in SQL nothing tests.
            cur.execute(
                "SELECT c.name, k.skill, k.value "  # noqa: S608
                "FROM characters c JOIN character_skills k ON k.guid = c.guid "
                f"WHERE c.name IN ({holes})",
                tuple(names),
            )
            skill_rows = list(cur.fetchall())
            # The give commands the bridge has already tried, and how the
            # world answered. GUARDED: a world whose image predates the give
            # machinery has refused nothing, so a missing table or column is
            # an empty list rather than a 503 that takes the whole view down -
            # the same treatment _fetch_achievements gives overseer_dungeon_run.
            try:
                cur.execute(
                    "SELECT target_name, target_arg, status, detail "
                    "FROM overseer_command WHERE kind = 'give' "
                    "AND created_at > NOW() - INTERVAL %s HOUR",
                    (needs.HISTORY_HOURS,),
                )
                give_rows = list(cur.fetchall())
            except pymysql.err.MySQLError as exc:
                if exc.args and exc.args[0] in (1054, 1146):
                    log.info("overseer_command give rows absent; needs runs without them")
                    give_rows = []
                else:
                    raise
            # NEWEST FIRST, and one read for two jobs: the quotation box on a
            # card wants the last thing somebody SAID, and the bonds count the
            # `reflection` rows underneath. Sieving them apart is needs.py's
            # decision; ORDER BY id DESC then a LIMIT is the same window shape
            # bridge._fetch_reflections uses, and for the same reason - a
            # plain ASC LIMIT would pin the window to the oldest rows in the
            # table and never move.
            try:
                cur.execute(
                    "SELECT character_name, source, text "  # noqa: S608
                    "FROM overseer_thought "
                    f"WHERE character_name IN ({holes}) "
                    "AND created_at > NOW() - INTERVAL %s HOUR "
                    "ORDER BY id DESC LIMIT %s",
                    (*names, needs.HISTORY_HOURS, needs.HISTORY_MAX),
                )
                thought_rows = list(cur.fetchall())
            except pymysql.err.MySQLError as exc:
                if exc.args and exc.args[0] in (1054, 1146):
                    log.info("overseer_thought absent; needs runs without bonds history")
                    thought_rows = []
                else:
                    raise
    finally:
        conn.close()
    return {"char_rows": char_rows, "inventory_rows": inventory_rows,
            "equipment_rows": equipment_rows, "skill_rows": skill_rows,
            "give_rows": give_rows, "thought_rows": thought_rows}


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


# --- the Council and the Eye (infra#2597) -----------------------------------
#
# TWO FETCHES AND NO JUDGEMENT. Both hand their rows straight to a pure module
# (council.build_council, eye.build_eye) and neither decides anything: not the
# order of a transcript, not whether a family is high enough for a dungeon,
# not whether a tier is real. That is the seam rule this whole directory is
# built on, and these two views are the ones most tempting to break it - a
# transcript wants sorting and a rollup wants counting, and both look like
# nothing until the page and the module disagree about the family.
#
# THEY SIT HERE, between the stream store and the current-goal banner, because
# every other fetch window in this file is claimed by a suite that slices it
# by name. The names are not repeated in this comment on purpose: the slices
# are taken with a string index, so a comment that spells a boundary out
# BECOMES that boundary, and the first draft of this block moved the Wealth
# suite's window up here by saying where it started.
#
# EVERY OVERSEER TABLE GOES THROUGH _guarded, for the reason the banner below
# spells out at length: infra#3172 turned a whole tab into a 503 on the live
# realm over one unguarded read of a table that world does not have. _guarded
# itself is defined with that banner, a few dozen lines down, and is reached
# here by name at call time like every other helper in this file.

# Nobody reads a transcript longer than this, and a council is a handful of
# lines. Enough to hold the last sitting several times over, so the module can
# find the sitting boundary rather than being handed a truncated one.
_COUNCIL_LINES = 60


def _fetch_council() -> dict:
    """Everything the Council view reads, in one connection.

    Names come from bonds via family.roster(), never from the request, so
    every roster clause is a fixed IN list of five with no user input in it.

    Not subject to the 60s snapshot freshness rule and deliberately so: a
    council is a thing that HAPPENED, and it is still worth reading an hour
    after everybody logged out.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # S608: `holes` is a run of placeholders sized by the roster, and
            # every VALUE is bound by the driver on the line below.
            thought_rows = _guarded(
                cur,
                "SELECT character_name, text, created_at "  # noqa: S608
                "FROM overseer_thought "
                f"WHERE source = %s AND character_name IN ({holes}) "
                f"ORDER BY id DESC LIMIT {_COUNCIL_LINES}",
                (council.COUNCIL_SOURCE, *names), "", "overseer_thought")
            goal_rows = _guarded(
                cur,
                "SELECT character_name, kind, skill_name, target, status, "
                "quest_id, created_at FROM overseer_goal "
                "ORDER BY created_at DESC LIMIT 200",
                (), "", "overseer_goal")
            # SAVED levels, not the snapshot's. The gate on a dungeon has to
            # answer "are they high enough" for a family who logged out ten
            # minutes ago, and a snapshot swept clean would report every
            # member at level 0 and every door shut.
            level_rows = _guarded(
                cur,
                f"SELECT name, level FROM characters WHERE name IN ({holes})",  # noqa: S608
                tuple(names), "", "characters")
            wanted = {int(r["quest_id"]) for r in goal_rows
                      if int(r.get("quest_id") or 0)}
            quest_titles = {}
            if wanted:
                qholes = ", ".join(["%s"] * len(wanted))
                cur.execute(
                    "SELECT ID, LogTitle FROM acore_world.quest_template "  # noqa: S608
                    f"WHERE ID IN ({qholes})",
                    tuple(sorted(wanted)),
                )
                quest_titles = {int(r["ID"]): r["LogTitle"]
                                for r in cur.fetchall()}
    finally:
        conn.close()
    return {"thought_rows": thought_rows, "goal_rows": goal_rows,
            "level_rows": level_rows, "quest_titles": quest_titles}


def _fetch_eye() -> dict:
    """The four counts the rollup is built from.

    THE GUILD COUNT IS A REAL READ. The Eye reports no guild because the guild
    table was counted and had nothing in it, not because somebody remembered
    that no guild had been made - and the day one exists that tier turns on
    with no change to this file or to eye.py.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # Same 60s freshness rule as /api/map: the two surfaces must not
            # disagree about who is in the world.
            snapshot_rows = _guarded(
                cur,
                "SELECT name, is_bot, group_leader FROM overseer_snapshot "
                "WHERE updated_at > NOW() - INTERVAL 60 SECOND",
                (), "", "overseer_snapshot")
            family_rows = _guarded(
                cur,
                f"SELECT name FROM characters WHERE name IN ({holes})",  # noqa: S608
                tuple(names), "", "characters")
            realm_rows = _guarded(
                cur, "SELECT COUNT(*) AS characters FROM characters",
                (), "", "characters")
            guild_rows = _guarded(
                cur, "SELECT COUNT(*) AS guilds FROM guild",
                (), "", "guild")
    finally:
        conn.close()
    return {"snapshot_rows": snapshot_rows, "family_rows": family_rows,
            "realm_rows": realm_rows, "guild_rows": guild_rows}


# --- what the guild can make, and what it cannot (infra#3507) ---------------
#
# TEN WHOLE-SET READS IN TWO PHASES, AND THAT IS THE WHOLE COST STORY. This
# view is a cross product - every covered character against every trade against
# every recipe in it - and the obvious shape for it is a loop that asks the
# world for one trade's recipes, then one recipe's vendors, then one recipe's
# drops. That is thousands of round trips on an endpoint with no auth in front
# of it. Every read below covers EVERY trade at once and is bucketed in Python,
# and nothing in guildcraft.py goes back to the database.
#
# THE TWO PHASES ARE THE ROSTER AND EVERYTHING ELSE. Which characters this page
# covers is the family plus whoever shares a guild with them, and that is not
# known until the guild read has answered - so the skills and spells reads bind
# `guildcraft.covered_names`, the module's own answer, rather than a list this
# file works out for itself and lets drift.
#
# Guarded for both 1146 and 1054 like every other read in this file. A world
# without `guild_member` gets an empty guild and a page covering the family,
# rather than a 503 on a tab that has nothing to do with the missing table
# (infra#3172). `_wide_guarded` is defined further down with the recap's reads,
# for the same reason `_fetch_dungeonplan` below sits above it: this section
# must stay OUTSIDE the recap suite's fetch window, and a module-level function
# is resolved when it is called rather than when this one is defined.

# The trade skill ids, inlined as text rather than bound, exactly as
# bridge.py's `_TRADE_SKILL_IDS` is and for the same reason: every element is
# an int from goals.SKILL_IDS, a table in this repository, and NOTHING a caller
# can reach ever touches it. /api/trades takes no parameters at all.
#
# THAT IS ALSO WHAT EVERY `noqa: S608` BELOW IS SAYING. ruff sees a query
# built by concatenation and cannot tell a constant from a request; the
# fragments joined into these six are this constant, `_TRADE_RECIPE_ITEMS`
# (itself built from this one) and `guildcraft.RECIPE_CLASS`, all of them ints
# and column names from code in this repository. Every VALUE that varies is
# still bound by the driver, and the markers are anchored on the FIRST line of
# each expression because that is where ruff anchors the rule - a marker on the
# line carrying the `+` silences nothing, which bridge.py learned first.
_TRADE_SKILL_LIST = ", ".join(str(i) for i in guildcraft.recipe_skills())

# EVERY GUILD THE COVERED CHARACTERS ARE IN, and their whole membership. Not a
# guild named in the request: there is no request parameter here, exactly as
# /api/armory and /api/family refuse a name. The family is in none of this
# realm's twenty guilds today, so this returns nothing and the page says so.
_TRADE_GUILD = (
    "SELECT g.name AS guild, c.name FROM guild_member gm "
    "JOIN guild g ON g.guildid = gm.guildid "
    "JOIN characters c ON c.guid = gm.guid "
    "WHERE gm.guildid IN (SELECT guildid FROM guild_member WHERE guid IN "
    "(SELECT guid FROM characters WHERE name IN ({holes})))"
)
_TRADE_MEMBERS = (
    "SELECT name, level, class FROM characters WHERE name IN ({holes})"
)
# `max` IS THE HALF THAT MAKES THE VALUE MEAN ANYTHING. A tailoring of 1 out of
# 75 and a tailoring of 1 out of 300 are different characters, and the ceiling
# is also what bounds which missing recipes this page is willing to list.
# Backticked because it is a function name everywhere else in SQL.
_TRADE_SKILLS = (
    "SELECT c.name, cs.skill, cs.value, cs.`max` FROM characters c "  # noqa: S608 - joined fragments are constants, not caller input
    "JOIN character_skills cs ON cs.guid = c.guid "
    "WHERE c.name IN ({holes}) AND cs.skill IN (" + _TRADE_SKILL_LIST + ")"
)
# THE SPELLBOOK IS WHAT "KNOWS A RECIPE" MEANS. A crafting recipe IS a spell,
# so the only honest test for "do they already know this" is whether the craft
# spell a recipe item teaches is in their `character_spell` rows.
_TRADE_SPELLS = (
    "SELECT c.name, sp.spell FROM characters c "
    "JOIN character_spell sp ON sp.guid = c.guid WHERE c.name IN ({holes})"
)
# WHAT THE FAMILY DECIDED, which is allowed to disagree with what the world
# granted and is the more interesting half when it does. professions.py's whole
# design is that this column never causes a `character_skills` row.
_TRADE_ROSTER = "SELECT name, professions FROM overseer_roster"
# EVERY RECIPE ITEM IN THE WORLD, narrowed to the trades this page is about.
# class 9 is Recipe, which is every recipe, pattern, plan, formula, design,
# technique and manual. `spellid_2 > 0` is what makes it a recipe that TEACHES
# something rather than a token: the taught craft spell is the only bridge back
# to `character_spell` this database has, because skilllineability_dbc is empty
# on this realm.
_TRADE_RECIPES = (
    "SELECT it.entry, it.RequiredSkill, it.RequiredSkillRank, "  # noqa: S608 - joined fragments are constants, not caller input
    + _ITEM_TEMPLATE_COLUMNS + " FROM acore_world.item_template it "
    "WHERE it.class = " + str(guildcraft.RECIPE_CLASS) + " "
    "AND it.RequiredSkill IN (" + _TRADE_SKILL_LIST + ") AND it.spellid_2 > 0"
)
# The one table on this realm that DOES map a spell to a skill line. It carries
# no name, which is why the page counts trainer crafts and never names them.
# DISTINCT because one spell is taught by many trainers and would otherwise be
# counted once per trainer.
_TRADE_TRAINER = (
    "SELECT DISTINCT SpellId, ReqSkillLine, ReqSkillRank, ReqLevel "
    "FROM acore_world.trainer_spell "
    "WHERE ReqSkillLine IN (" + _TRADE_SKILL_LIST + ")"
)
# WHERE A RECIPE COMES FROM, THREE WAYS. The item filter is a SUBQUERY and not
# a bound list of entries: binding it would mean reading the recipes first and
# then sending a few thousand ids back over the wire, which is the same rows
# twice. ONE SPAWN per creature, the lowest guid, as a scalar subquery: joined
# plainly, a vendor with twelve spawn rows would be twelve copies of the same
# sentence, and the basis says only one is named.
_TRADE_RECIPE_ITEMS = (
    "SELECT entry FROM acore_world.item_template "  # noqa: S608 - joined fragments are constants, not caller input
    "WHERE class = " + str(guildcraft.RECIPE_CLASS) + " "
    "AND RequiredSkill IN (" + _TRADE_SKILL_LIST + ")"
)
_TRADE_VENDORS = (
    "SELECT nv.item, ct.name, cr.map, cr.position_x, cr.position_y "  # noqa: S608 - joined fragments are constants, not caller input
    "FROM acore_world.npc_vendor nv "
    "JOIN acore_world.creature_template ct ON ct.entry = nv.entry "
    "LEFT JOIN acore_world.creature cr ON cr.guid = "
    "(SELECT MIN(guid) FROM acore_world.creature WHERE id = ct.entry) "
    "WHERE nv.item IN (" + _TRADE_RECIPE_ITEMS + ")"
)
# `Reference = 0` is the same filter the loot board and the dungeon plan both
# carry: a row with a Reference points at reference_loot_template rather than
# at an item. What lives behind those references is NOT followed, which is
# where most world drops live, and the page's own basis says so rather than
# letting a recipe with no row read as a recipe with nowhere to come from.
_TRADE_DROPS = (
    "SELECT clt.Item AS item, clt.Chance, ct.name, ct.minlevel, ct.maxlevel, "  # noqa: S608 - joined fragments are constants, not caller input
    "cr.map, cr.position_x, cr.position_y "
    "FROM acore_world.creature_loot_template clt "
    "JOIN acore_world.creature_template ct ON ct.lootid = clt.Entry "
    "LEFT JOIN acore_world.creature cr ON cr.guid = "
    "(SELECT MIN(guid) FROM acore_world.creature WHERE id = ct.entry) "
    "WHERE clt.Reference = 0 AND clt.Item IN (" + _TRADE_RECIPE_ITEMS + ")"
)
# TEN REWARD COLUMNS AND NO WAY TO UNPIVOT THEM. quest_template carries four
# fixed rewards and six choices as ten separate columns, so a UNION of ten
# narrow reads is what turns them into rows. Written as a UNION rather than as
# a join on `IN (ten columns)` because each arm's subquery is materialised once
# and probed by index, while the join shape makes the optimiser's choice the
# difference between a hash probe and a scan of the whole quest table per item.
_TRADE_QUEST_COLUMNS = (
    "RewardItem1", "RewardItem2", "RewardItem3", "RewardItem4",
    "RewardChoiceItemID1", "RewardChoiceItemID2", "RewardChoiceItemID3",
    "RewardChoiceItemID4", "RewardChoiceItemID5", "RewardChoiceItemID6",
)
_TRADE_QUESTS = " UNION ".join(
    "SELECT %s AS item, ID, LogTitle, QuestLevel "  # noqa: S608 - joined fragments are constants, not caller input
    "FROM acore_world.quest_template "
    "WHERE %s IN (%s)" % (column, column, _TRADE_RECIPE_ITEMS)
    for column in _TRADE_QUEST_COLUMNS
)


def _fetch_guildcraft() -> dict:
    """Every trade, every recipe in it, and where each one can be got.

    One connection, ten reads, none of them per trade, per character or per
    recipe. Names come from bonds via family.roster() and never from the
    request, exactly as /api/armory and /api/family refuse a name parameter.

    THE SECOND PHASE IS THE POINT. `covered` is the family plus their guild,
    and it is `guildcraft.covered_names` that decides it, so the two reads that
    bind a roster cannot fall behind the list the page draws rows for. A name
    with a row and no spells read would render as "knows nothing", which is a
    claim rather than a gap.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # S608 on every roster read below: `holes` is a run of "%s"
            # placeholders sized by len(family.roster()), and every VALUE is
            # still bound by the driver. The skill-id lists are ints from
            # goals.SKILL_IDS and no request can reach them.
            guild = _wide_guarded(cur, _TRADE_GUILD.format(holes=holes),  # noqa: S608
                                  tuple(names), "", "guild_member")
            covered = guildcraft.covered_names(names, guild)
            choles = ", ".join(["%s"] * len(covered))
            members = _wide_guarded(cur, _TRADE_MEMBERS.format(holes=choles),  # noqa: S608
                                    tuple(covered), "", "characters")
            skills = _wide_guarded(cur, _TRADE_SKILLS.format(holes=choles),  # noqa: S608
                                   tuple(covered), "", "character_skills")
            spells = _wide_guarded(cur, _TRADE_SPELLS.format(holes=choles),  # noqa: S608
                                   tuple(covered), "", "character_spell")
            # THE ONE READ WHOSE ABSENCE CHANGES A SENTENCE. An empty list here
            # is either "nobody is assigned anything" or "the column is not in
            # this world yet", and those are different admissions, so the page
            # is told which it got rather than being left to guess from a
            # length.
            roster_rows = _wide_guarded(cur, _TRADE_ROSTER, (), "",
                                        "overseer_roster")
            recipes = _wide_guarded(cur, _TRADE_RECIPES, (), "",
                                    "item_template")
            trainer = _wide_guarded(cur, _TRADE_TRAINER, (), "",
                                    "trainer_spell")
            vendors = _wide_guarded(cur, _TRADE_VENDORS, (), "", "npc_vendor")
            drops = _wide_guarded(cur, _TRADE_DROPS, (), "",
                                  "creature_loot_template")
            quests = _wide_guarded(cur, _TRADE_QUESTS, (), "",
                                   "quest_template")
    finally:
        conn.close()
    return {"guild_rows": guild, "member_rows": members, "skill_rows": skills,
            "spell_rows": spells, "roster_rows": roster_rows,
            "recipe_rows": recipes, "trainer_rows": trainer,
            "vendor_rows": vendors, "drop_rows": drops, "quest_rows": quests,
            "roster_read": bool(roster_rows)}


# --- which dungeon is worth running next (infra#3500) ------------------------
#
# THREE WHOLE-WORLD READS, AND THAT IS THE WHOLE COST STORY. This view is a
# cross product - every dungeon's boss loot against all five characters - and
# the obvious shape for it is a loop that asks the world for one dungeon's
# encounters and one dungeon's loot at a time. That is forty round trips for
# twenty dungeons on an endpoint with no auth in front of it. The catalogue,
# the encounters and the loot each arrive ONCE for every map at the same time,
# bucketed by map in Python, and nothing in dungeonplan.py goes back to the
# database.
#
# THE MAP LIST COMES FROM THE CATALOGUE AND NEVER FROM THE CALLER. There is no
# parameter on this endpoint at all: it asks about every dungeon, so there is
# nothing for a request to steer. The map ids bound into the two reads below
# are the ones the world's own access table just handed over.
#
# Guarded for both 1146 and 1054 like every other read in this file. A world
# without dungeon_access_template gets an empty catalogue and a page that says
# so, rather than a 503 on a tab that has nothing to do with the missing
# table (infra#3172).
_PLAN_CATALOGUE = (
    "SELECT map_id, difficulty, min_level, max_level, comment "
    "FROM acore_world.dungeon_access_template ORDER BY map_id, difficulty"
)
# `difficulty` is what picks ONE row per map when a map has several. A world
# whose table predates that column still gets its dungeons, and _catalogue
# treats the missing value as difficulty 0, which is the row it would have
# picked anyway.
_PLAN_CATALOGUE_OLD = (
    "SELECT map_id, min_level, max_level, comment "
    "FROM acore_world.dungeon_access_template ORDER BY map_id"
)
# THE MAP HAS TO COME OFF THE SPAWN, because instance_encounters carries no
# map column: the worldserver reads that from DungeonEncounter.dbc, which this
# service will never see. `creditType` 0 is a creature and 1 is a SPELL, and
# without that filter the join reads a spell id as a creature entry and names
# an encounter after whatever creature happens to share the number.
#
# DISTINCT IS LOAD BEARING. A boss with two spawn rows on the same map is two
# rows out of this join and would be counted as two bosses.
_PLAN_ENCOUNTERS = (
    "SELECT DISTINCT cr.map AS map_id, ie.creditEntry AS creature, ct.name "
    "FROM acore_world.instance_encounters ie "
    "JOIN acore_world.creature_template ct ON ct.entry = ie.creditEntry "
    "JOIN acore_world.creature cr ON cr.id = ie.creditEntry "
    "WHERE ie.creditType = 0 AND cr.map IN ({holes})"
)
# The loot board's own query widened from one map to all of them. The spawn
# test stays a SUBQUERY rather than becoming a fourth join for the reason
# above: joined, a boss with two spawns would multiply every one of its loot
# rows by two. `Reference = 0` is the same filter the loot board and the
# achievements drop query both carry - a row with a Reference points at
# reference_loot_template rather than at an item, so joining it on
# `it.entry = clt.Item` surfaces something unrelated as a boss drop. What
# lives behind those references is not followed, and the basis says so.
# NO `Chance` AND NO `GroupId`, WHICH THE LOOT BOARD'S OWN VERSION SELECTS.
# Those two are what `recap._chance` turns into "80%" or "one roll shared with
# three others", and this page does not ask how likely anything is - the loot
# board asks that one dungeon at a time, and the basis says so. Selecting them
# here would be two unread columns on the widest read this service makes, and
# the next person to see them would reasonably add the sentence they support.
_PLAN_LOOT = (
    "SELECT clt.Item, ct.entry AS creature, " + _ITEM_TEMPLATE_COLUMNS + " "
    "FROM acore_world.creature_loot_template clt "
    "JOIN acore_world.creature_template ct ON ct.lootid = clt.Entry "
    "JOIN acore_world.item_template it ON it.entry = clt.Item "
    "WHERE clt.Reference = 0 AND ct.entry IN "
    "(SELECT DISTINCT id FROM acore_world.creature WHERE map IN ({holes})) "
    "AND ct.entry IN "
    "(SELECT creditEntry FROM acore_world.instance_encounters "
    "WHERE creditType = 0)"
)
# WHERE THE FAMILY ARE STANDING, which is the half of "is it on their
# continent" that is about them rather than about the dungeon. `map` is on
# the characters row already, so this is _RECAP_CHARS with one more column
# rather than a second read.
_PLAN_CHARS = (
    "SELECT name, level, class, map FROM characters WHERE name IN ({holes})"
)


def _fetch_dungeonplan() -> dict:
    """Every dungeon, every boss drop, and what the five are wearing.

    One connection, six reads, none of them per dungeon. Names come from bonds
    via family.roster() and never from the request, exactly as /api/armory and
    /api/family refuse a name parameter.

    `_wide_guarded` and the two roster reads this borrows are defined with the
    loot board's below, and this section sits ABOVE that one deliberately. The
    recap suite slices its own fetch window from that function to the
    current-goal banner and forbids an unguarded read anywhere inside it, so a
    section dropped in there would be asserted about by a suite that knows
    nothing of it - and naming that function here would move the START of
    their window into this docstring, which is a subtler version of the same
    fault.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            catalogue = _wide_guarded(cur, _PLAN_CATALOGUE, (),
                                      _PLAN_CATALOGUE_OLD,
                                      "dungeon_access_template")
            # THE UNION, AND THE MODULE DECIDES IT. The page draws a row per
            # access-table map AND per map this site already names, so binding
            # the access table's maps alone would leave a site-named dungeon
            # rendering "no boss loot" over loot that was simply never asked
            # for. dungeonplan.map_ids is the one answer to which maps get a
            # row, and it is asked here so the reads cannot fall behind it.
            #
            # NO MAPS MEANS NOTHING TO BIND, and `IN ()` is a syntax error
            # rather than an empty result. The page says the world listed no
            # dungeons it could read, which is what happened.
            maps = dungeonplan.map_ids(catalogue, achievements.MAP_NAMES)
            encounters: list = []
            loot: list = []
            if maps:
                mholes = ", ".join(["%s"] * len(maps))
                encounters = _wide_guarded(
                    cur, _PLAN_ENCOUNTERS.format(holes=mholes),  # noqa: S608
                    tuple(maps), "", "instance_encounters")
                loot = _wide_guarded(
                    cur, _PLAN_LOOT.format(holes=mholes),  # noqa: S608
                    tuple(maps), "", "creature_loot_template")
            # S608 on the roster reads: `holes` is a run of placeholders sized
            # by len(family.roster()), and every VALUE is still bound by the
            # driver.
            chars = _wide_guarded(cur, _PLAN_CHARS.format(holes=holes),  # noqa: S608
                                  tuple(names), "", "characters")
            worn = _wide_guarded(cur, _RECAP_WORN.format(holes=holes),  # noqa: S608
                                 (len(armory.EQUIPPED_SLOTS), *names), "",
                                 "character_inventory")
            # Guarded like everything else, and the empty list this hands back
            # on a degraded schema is a real answer: recap.family_members
            # turns "no rows for this character" into an unknown, an unknown
            # proficiency ranks the page the way it was ranked before, and the
            # basis keeps printing the line that says so.
            skills = _wide_guarded(cur, _RECAP_SKILLS.format(holes=holes),  # noqa: S608
                                   tuple(names), "", "character_skills")
    finally:
        conn.close()
    return {"catalogue_rows": catalogue, "encounter_rows": encounters,
            "loot_rows": loot, "char_rows": chars, "equipped_rows": worn,
            "skill_rows": skills}


# --- the live dungeon recap and the loot board (infra#2597) ------------------
#
# EVERY READ BELOW IS GUARDED FOR BOTH 1146 AND 1054, and this endpoint is the
# one most exposed to the pair. It joins five overseer_* tables written by the
# in-world module across migrations that land weeks apart, plus four world
# tables, and the two realms this image serves run different worldserver
# builds. The failures are the ones this file has already been bitten by:
#
#   1146 missing TABLE   turned the whole Achievements tab into a 503 on the
#                        live realm (infra#3172): it had overseer_event and no
#                        overseer_death.
#   1054 missing COLUMN  is the nastier one, because MySQL fails a SELECT
#                        naming an absent column WHOLE. infra#2846 is the
#                        worked example.
#
# `overseer_dungeon_run.outcome` arrived on 2026-09-02 and is exactly that
# shape of risk, so the run read has a thinner fallback naming only columns
# that have always been there.
_RECAP_RUNS = (
    "SELECT id, leader_name, map_id, state, started_at, last_progress_at, "
    "ended_at, ended_reason, outcome FROM overseer_dungeon_run "
    "ORDER BY started_at DESC LIMIT 200"
)
_RECAP_RUNS_OLD = (
    "SELECT id, leader_name, map_id, state, started_at, last_progress_at, "
    "ended_at, ended_reason FROM overseer_dungeon_run "
    "ORDER BY started_at DESC LIMIT 200"
)
# The whole equip history, not a window of it. recap.first_equips needs the
# EARLIEST row for each (character, item) pair, and the earliest row for gear
# somebody has worn for a fortnight is a fortnight old: narrowing this to the
# run would reproduce exactly the bug the module exists to fix. It is 355 rows
# on the live realm for five characters.
_RECAP_EQUIPS = (
    "SELECT character_name, kind, subject_id, subject_name, detail, map, zone, "
    "occurrences, first_seen, last_seen FROM overseer_event "
    "WHERE kind = 'item_equip' AND character_name IN ({holes})"
)
_RECAP_DEATHS = (
    "SELECT character_name, map, zone, killer_name, killer_type, created_at "
    "FROM overseer_death WHERE character_name IN ({holes})"
)
_RECAP_SNAPSHOT = (
    "SELECT name, level, map_id, health, max_health, in_combat, updated_at "
    "FROM overseer_snapshot WHERE name IN ({holes})"
)
# The lockout the family is bound to. Every join is on an integer or on
# characters.name, which is utf8mb4_bin and outranks any collation it meets,
# so the 1267 trap infra#3173 documents cannot bite here.
_RECAP_INSTANCE = (
    "SELECT DISTINCT i.id, i.map, i.completedEncounters FROM instance i "
    "JOIN character_instance ci ON ci.instance = i.id "
    "JOIN characters c ON c.guid = ci.guid WHERE c.name IN ({holes})"
)
# The bosses, from the core's own encounter table narrowed to the creatures
# actually spawned on the map. instance_encounters carries no map column (the
# worldserver reads that from DungeonEncounter.dbc, which this service will
# never see), and the spawn table is what supplies it.
# `creditType` 0 is a creature and 1 is a SPELL, and there are 34 of the
# latter on this realm. Without the filter the join reads a spell id as a
# creature entry and names the encounter after whatever creature happens to
# share that number.
_RECAP_ENCOUNTERS = (
    "SELECT ie.entry, ie.creditEntry, ct.name "
    "FROM acore_world.instance_encounters ie "
    "JOIN acore_world.creature_template ct ON ct.entry = ie.creditEntry "
    "WHERE ie.creditType = 0 AND ie.creditEntry IN "
    "(SELECT DISTINCT id FROM acore_world.creature WHERE map = %s)"
)
_RECAP_LOOT = (
    # The item half of this list is _ITEM_TEMPLATE_COLUMNS, which is every
    # column a tooltip draws (infra#3501). It was eight of them, enough for a
    # name, a level and the class gate; a drop on this board opens its own
    # lines now, and they come from here rather than from wowhead. The rows
    # the PAYLOAD carries are narrowed by build_lootboard to the drops that
    # can be equipped at all, which is a fraction of what this selects.
    "SELECT clt.Entry, clt.Item, clt.Chance, clt.GroupId, ct.entry AS creature, "
    f"{_ITEM_TEMPLATE_COLUMNS} "
    "FROM acore_world.creature_loot_template clt "
    "JOIN acore_world.creature_template ct ON ct.lootid = clt.Entry "
    "JOIN acore_world.item_template it ON it.entry = clt.Item "
    # `Reference = 0` is the same filter the achievements drop query carries,
    # and for the same reason: a row with a Reference points at
    # reference_loot_template rather than at an item, so joining it on
    # `it.entry = clt.Item` can surface something unrelated as a boss drop.
    # The loot behind those references is not followed, and build_lootboard's
    # `basis` says so rather than letting the board read as complete.
    "WHERE clt.Reference = 0 AND ct.entry IN "
    "(SELECT DISTINCT id FROM acore_world.creature WHERE map = %s) "
    "AND ct.entry IN "
    "(SELECT creditEntry FROM acore_world.instance_encounters "
    "WHERE creditType = 0)"
)
_RECAP_CHARS = "SELECT name, level, class FROM characters WHERE name IN ({holes})"
_RECAP_WORN = (
    "SELECT c.name, ci.slot, ii.itemEntry AS entry, it.name AS item_name, "
    "it.Quality AS quality, it.ItemLevel AS item_level, it.class, it.subclass, "
    "it.InventoryType AS inventory_type, it.displayid FROM characters c "
    "JOIN character_inventory ci ON ci.guid = c.guid AND ci.bag = 0 "
    "AND ci.slot < %s JOIN item_instance ii ON ii.guid = ci.item "
    "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN ({holes})"
)
_RECAP_ITEMS = (
    # Same widening, same reason (infra#3501). Bounded by recap.wanted_items,
    # which is already "only the items somebody has actually worn".
    "SELECT it.entry, " + _ITEM_TEMPLATE_COLUMNS + " "
    "FROM acore_world.item_template it WHERE it.entry IN ({holes})"
)
# WHAT EACH CHARACTER MAY ACTUALLY HOLD (mod-overseer#411). The loot board
# offered a staff to a rogue, because `item_template.allowable_class` was the
# only class gate it had and that column restricts nobody on a staff. Whether a
# character may hold a weapon is not on the item at all; it is one of these
# rows. `value` comes with it because the core's own test is
# `GetSkillValue(skill) == 0`, not "is there a row".
_RECAP_SKILLS = (
    "SELECT c.name, cs.skill, cs.value FROM characters c "
    "JOIN character_skills cs ON cs.guid = c.guid WHERE c.name IN ({holes})"
)


def _wide_guarded(cur, sql: str, params: tuple = (), fallback: str = "",
                  what: str = "") -> list:
    """Run `sql`, dropping to `fallback` (then to []) on a degraded schema.

    A THIRD GUARD IN THIS FILE, AND DELIBERATELY NOT ONE OF THE TWO ALREADY
    HERE. `_guarded` takes a fallback but catches only ProgrammingError, and
    error 1054 is NOT a ProgrammingError: pymysql has no entry for it in
    error_map, so raise_mysql_exception falls back to OperationalError. A
    read guarded by `_guarded` therefore survives a missing table and dies on
    a missing column, which is half a guard. `_realm_guarded` catches the
    right base class but takes neither parameters nor a fallback.

    This is the widened form with both, and the note in `_realm_guarded` is
    why it is a new function rather than an edit to `_guarded`: widening that
    one changes the behaviour of the banner it belongs to, which is a
    different change with a different blast radius, and it is not this one.

    Anything that is not 1146 or 1054 still reaches the handler's 503. A guard
    that swallowed a network blip would render an empty recap and train the
    alarm away.
    """
    for attempt in (sql, fallback):
        if not attempt:
            break
        try:
            cur.execute(attempt, params)
            return list(cur.fetchall())
        except pymysql.err.MySQLError as exc:
            if not (exc.args and exc.args[0] in (1054, 1146)):
                raise
            log.info("recap: %s unavailable (%s) - trying a thinner read",
                     what, exc.args[0])
    log.info("recap: %s unavailable; the recap runs without it", what)
    return []


def _fetch_recap(map_id: int | None) -> dict:
    """Everything the recap and the loot board read, in one connection.

    `map_id` is the ONLY thing a caller may steer, it is an int the handler
    has already parsed, and it is bound by the driver. Names come from bonds
    via family.roster() and never from the request, exactly as /api/armory and
    /api/family refuse a name parameter, so every roster clause is a fixed IN
    list with no user input in it.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            runs = _wide_guarded(cur, _RECAP_RUNS, (), _RECAP_RUNS_OLD,
                                 "overseer_dungeon_run")
            # S608 on the roster reads below: `holes` is a run of placeholders
            # sized by len(family.roster()), and every VALUE is still bound by
            # the driver.
            equips = _wide_guarded(cur, _RECAP_EQUIPS.format(holes=holes),  # noqa: S608
                                   tuple(names), "", "overseer_event")
            deaths = _wide_guarded(cur, _RECAP_DEATHS.format(holes=holes),  # noqa: S608
                                   tuple(names), "", "overseer_death")
            snaps = _wide_guarded(cur, _RECAP_SNAPSHOT.format(holes=holes),  # noqa: S608
                                  tuple(names), "", "overseer_snapshot")
            instances = _wide_guarded(cur, _RECAP_INSTANCE.format(holes=holes),  # noqa: S608
                                      tuple(names), "", "instance")
            chars = _wide_guarded(cur, _RECAP_CHARS.format(holes=holes),  # noqa: S608
                                  tuple(names), "", "characters")
            worn = _wide_guarded(cur, _RECAP_WORN.format(holes=holes),  # noqa: S608
                                 (len(armory.EQUIPPED_SLOTS), *names), "",
                                 "character_inventory")
            # GUARDED LIKE EVERYTHING ELSE HERE, and the empty list this hands
            # back on a degraded schema is a real answer rather than a silent
            # one: recap.family_members turns "no rows for this character" into an
            # unknown, and an unknown proficiency ranks the board exactly the
            # way it was ranked before and keeps printing the caveat that says
            # so. A failed read must not be able to empty the board.
            skills = _wide_guarded(cur, _RECAP_SKILLS.format(holes=holes),  # noqa: S608
                                   tuple(names), "", "character_skills")
            # TWO MAPS, AND THEY ARE ONLY USUALLY THE SAME ONE. The board is
            # whichever dungeon is being browsed; the progress bar is the map
            # the family is actually in. Both decisions are the module's, and
            # conflating them counted a Wailing Caverns lockout mask against
            # the Deadmines' encounter list.
            board = recap.board_map(runs, map_id)
            here = recap.run_map(runs)
            board_encounters = _wide_guarded(cur, _RECAP_ENCOUNTERS, (board,),
                                             "", "instance_encounters")
            encounters = board_encounters if here in (None, board) else (
                _wide_guarded(cur, _RECAP_ENCOUNTERS, (here,), "",
                              "instance_encounters"))
            loot = _wide_guarded(cur, _RECAP_LOOT, (board,), "",
                                 "creature_loot_template")
            # Only the items somebody has actually worn need naming, and which
            # those are is the module's answer, not a guess here.
            wanted = recap.wanted_items(equips)
            items = []
            if wanted:
                iholes = ", ".join(["%s"] * len(wanted))
                items = _wide_guarded(cur, _RECAP_ITEMS.format(holes=iholes),  # noqa: S608
                                      tuple(wanted), "", "item_template")
    finally:
        conn.close()
    return {"run_rows": runs, "event_rows": equips, "death_rows": deaths,
            "snapshot_rows": snaps, "instance_rows": instances,
            "encounter_rows": encounters,
            "board_encounter_rows": board_encounters, "loot_rows": loot,
            "char_rows": chars, "equipped_rows": worn,
            "skill_rows": skills,
            "item_rows": items, "board_map": board}


# --- the current-goal banner (infra#3205) -----------------------------------
#
# WHY THIS FETCH IS ALL GUARDS. Every table below except `instance` and
# `characters` is created by the in-world module, across migrations that land
# weeks apart, and the two realms this image serves run different worldserver
# builds. So a read here can fail two ways and both have already taken a tab
# down in production:
#
#   1146 missing TABLE   - what turned the whole Achievements tab into a 503
#                          on the live realm (infra#3172): it has overseer_event
#                          but no overseer_death.
#   1054 missing COLUMN  - the same class of failure one level down, and the
#                          nastier one, because MySQL fails a SELECT naming an
#                          absent column WHOLE. infra#2846 is the worked
#                          example: adding `travel_npc` to one query stopped
#                          the family questing on every older world, silently,
#                          for a feature they had nothing to do with.
#
# This banner reads the NEWEST columns in the schema - dungeon_runs_wanted,
# dungeon_runs_done, campaign_id, run_number, outcome and members all arrived
# on 2026-09-02 - so it is the single most likely thing in this file to meet a
# world that predates them. Each read therefore falls back to the columns that
# have always existed rather than raising, and agenda.build_agenda is written
# to say less when it is handed less.
_ROSTER_FULL = (
    "SELECT name, enabled, `lead`, job, drive_quest, travel_npc, learn_skill, "
    "dungeon_runs_wanted, dungeon_runs_done FROM overseer_roster"
)
# The lead column is back-quoted because it is a reserved word in MySQL 8; an
# unquoted one is a syntax error, not a missing column, so no schema fallback
# below would catch it - it would take the whole banner out on every world.
_ROSTER_OLD = "SELECT name, enabled, `lead` FROM overseer_roster"

_RUNS_FULL = (
    "SELECT id, leader_name, map_id, state, started_at, ended_at, "
    "ended_reason, campaign_id, run_number, outcome, members "
    "FROM overseer_dungeon_run ORDER BY started_at DESC LIMIT 200"
)
_RUNS_OLD = (
    "SELECT id, leader_name, map_id, state, started_at, ended_at, ended_reason "
    "FROM overseer_dungeon_run ORDER BY started_at DESC LIMIT 200"
)

# The lockout the family is BOUND to, which is the only way to find the right
# `instance` row: several may exist for one map, and the bind is what says
# which one is theirs. Every join here is on an integer or on characters.name,
# which is utf8mb4_bin and so outranks any collation it meets - the 1267 trap
# infra#3173 documents needs two overseer tables to bite, and there are none
# in this statement.
_INSTANCE_SQL = (
    "SELECT DISTINCT i.id, i.map, i.completedEncounters, i.resettime "
    "FROM instance i "
    "JOIN character_instance ci ON ci.instance = i.id "
    "JOIN characters c ON c.guid = ci.guid "
    "WHERE c.name IN (%s)"
)


def _guarded(cur, sql: str, params: tuple = (), fallback: str = "",
             what: str = "") -> list:
    """Run `sql`, dropping to `fallback` (then to []) on a degraded schema.

    Returns rows. 1146 and 1054 are the only two errors swallowed, and only
    those two: anything else is a real fault and must still reach the handler's
    503 rather than being silently rendered as an empty banner.
    """
    for attempt in (sql, fallback):
        if not attempt:
            break
        try:
            cur.execute(attempt, params)
            return list(cur.fetchall())
        except pymysql.err.ProgrammingError as exc:
            if not (exc.args and exc.args[0] in (1054, 1146)):
                raise
            log.info("agenda: %s unavailable (%s) - trying a thinner read",
                     what, exc.args[0])
    log.info("agenda: %s unavailable; the banner runs without it", what)
    return []


def _fetch_agenda() -> dict:
    """Everything the current-goal banner reads, in one connection.

    Not subject to the 60s snapshot freshness rule, and deliberately so: an
    aim is SAVED state. It still answers "what were they trying to do" for a
    family who logged out an hour ago, which is a good part of the reason to
    look at all.

    Names come from bonds via family.roster(), never from the request, so
    every roster clause is a fixed IN list of five with no user input in it.
    """
    names = family.roster()
    holes = ", ".join(["%s"] * len(names))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            roster_rows = _guarded(cur, _ROSTER_FULL, (), _ROSTER_OLD,
                                   "overseer_roster")
            run_rows = _guarded(cur, _RUNS_FULL, (), _RUNS_OLD,
                                "overseer_dungeon_run")
            goal_rows = _guarded(
                cur,
                "SELECT character_name, kind, skill_name, target, status, "
                "channel_id, last_report, created_at, quest_id "
                "FROM overseer_goal ORDER BY created_at DESC LIMIT 200",
                (), "", "overseer_goal")
            trade_rows = _guarded(
                cur,
                "SELECT character_name, verb, skill_name, reason, status, "
                "decided_at FROM overseer_trade ORDER BY decided_at DESC "
                "LIMIT 200",
                (), "", "overseer_trade")
            # ONE ROW PER EVENT KIND, not the feed. The banner asks the event
            # table exactly one question - when did anything last actually
            # happen - and grouping in SQL answers it in seven rows instead of
            # ten thousand. S608: `holes` is a run of placeholders sized by the
            # roster, and every VALUE is bound by the driver below.
            event_rows = _guarded(
                cur,
                "SELECT kind, MAX(last_seen) AS last_seen "  # noqa: S608
                f"FROM overseer_event WHERE character_name IN ({holes}) "
                "GROUP BY kind",
                tuple(names), "", "overseer_event")
            instance_rows = _guarded(cur, _INSTANCE_SQL % holes, tuple(names),
                                     "", "instance")
            # The quests anything is aimed at, named. Looked up after the rows
            # are in hand rather than joined, because acore_world is a second
            # schema and the ids are a handful.
            wanted = {int(r["drive_quest"]) for r in roster_rows
                      if int(r.get("drive_quest") or 0)}
            wanted |= {int(r["quest_id"]) for r in goal_rows
                       if int(r.get("quest_id") or 0)}
            quest_titles = {}
            if wanted:
                qholes = ", ".join(["%s"] * len(wanted))
                cur.execute(
                    "SELECT ID, LogTitle FROM acore_world.quest_template "  # noqa: S608
                    f"WHERE ID IN ({qholes})",
                    tuple(sorted(wanted)),
                )
                quest_titles = {int(r["ID"]): r["LogTitle"]
                                for r in cur.fetchall()}
    finally:
        conn.close()
    return {"roster_rows": roster_rows, "run_rows": run_rows,
            "instance_rows": instance_rows, "goal_rows": goal_rows,
            "trade_rows": trade_rows, "event_rows": event_rows,
            "quest_titles": quest_titles}


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
            " detail = 'nobody was watching', last_seen = NOW()"
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


# WHO ASKED, for a row this process wrote. One constant rather than a literal
# at each call site: the decree console reads its own orders back by matching
# on it, and a second spelling would silently hand it an empty console while
# the orders themselves went through perfectly.
WEB_SOURCE = "web:overseer"


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
# Latest-only, in memory, and deliberately not on disk or in the database.
# A frame is worth seconds; keeping history would need a cleanup job, and
# base64 in a TEXT column is how a table becomes unqueryable. Bounded by
# construction: one record per roster character, each capped at
# frames.MAX_FRAME_BYTES. Lost on restart, which is correct - a picture from
# before the process died is not evidence of anything now.
_FRAMES: dict = {}
_FRAMES_LOCK = threading.Lock()


# Where the page reaches the model-viewer cache. Also the value of the
# page's window.CONTENT_PATH, which the viewer appends its file paths to.
MODEL_PREFIX = "/modelviewer/"


def _fetch_decree() -> dict:
    """Everything the decree console reads, in one connection.

    Two questions, one trip: what the roster COLUMNS are set to, and what
    became of the orders this page has already sent.

    THE COMMAND ROWS ARE SCOPED TO THIS SURFACE, by `source`. Every order the
    web console sends is inserted with WEB_SOURCE (_insert_command, which is
    the same road the Discord path takes), so this reads back what THIS page
    caused and nothing else. A console that also showed the bridge's own
    traffic would report somebody else's orders as if the operator had given
    them, and the whole point of the view is that a line on it can be traced
    back to a thing that was pressed.

    Sits between `_ask_llm` and the Handler class deliberately: the Armory,
    Achievements, Questlog and Wealth endpoint suites each slice this file by
    their own fetch window, and a fetch dropped into one of them is read as
    part of a contract it has nothing to do with.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            roster_rows = _guarded(cur, _ROSTER_FULL, (), _ROSTER_OLD,
                                   "overseer_roster")
            command_rows = _guarded(
                cur,
                "SELECT id, target_name, command, kind, status, detail, "
                "created_at FROM overseer_command WHERE source = %s "
                "ORDER BY id DESC LIMIT %s",
                (WEB_SOURCE, decree.OUTCOME_ROWS), "", "overseer_command")
    finally:
        conn.close()
    return {"roster_rows": roster_rows, "command_rows": command_rows}


# --- the console's write path (infra#3345) -----------------------------------
#
# ONE STATEMENT PER COLUMN, LOOKED UP BY NAME. decree.plan_order decides which
# column and what value; these two tables are the only place a column name
# reaches SQL, and they are fixed dicts keyed by that module's own constants -
# the same shape as GET_ROUTES, and for the same reason. An Update naming a
# column that is not in here is a miss, not a statement assembled out of a
# string. Values are still bound, always.
_ROSTER_SET = {
    decree.CAMPAIGN_WANTED:
        "UPDATE overseer_roster SET dungeon_runs_wanted = %s WHERE name = %s",
    decree.CAMPAIGN_DONE:
        "UPDATE overseer_roster SET dungeon_runs_done = %s WHERE name = %s",
    decree.TRAVEL_COLUMN:
        "UPDATE overseer_roster SET travel_npc = %s WHERE name = %s",
}
# THE GUARDED FORM, and it is bridge._write_trade_errand's own WHERE clause
# rather than a new one: an aim given from this page must not erase an errand
# the profession planner wrote. decree.Update.if_free is what picks it.
_ROSTER_SET_IF_FREE = {
    decree.TRAVEL_COLUMN:
        "UPDATE overseer_roster SET travel_npc = %s WHERE name = %s "
        "AND (travel_npc = '' OR travel_npc = %s)",
}

# ONE ORDER AT A TIME FROM THIS PROCESS. ThreadingHTTPServer runs a thread per
# request, and a job order is one INSERT per character: two taps a second
# apart would otherwise interleave their fan-outs and leave half the family on
# one mode and half on another - the split agenda.job_split exists to REPORT,
# and nothing this page does should be the thing that causes it. The lock is
# held across the plan as well as the writes, so an order is planned against
# the roster it is about to be applied to.
_DECREE_LOCK = threading.Lock()

# 1146 missing table, 1054 missing column, 1265 an ENUM value this realm's
# schema has never heard of. The same three a degraded schema produces on the
# read side, plus the one bridge._insert_share already guards kind= inserts
# with: 'job' arrives with mod-overseer's SQL and this process deploys
# separately, so a worldserver that predates it rejects the row under strict
# mode rather than storing something else.
_DEGRADED = (1054, 1146, 1265)


def _fetch_roster_rows() -> list:
    """The roster an order is planned against.

    THE SAME TWO STATEMENTS as the console's own read, so a plan and the page
    agree about who is enabled - and every planner needs only `name`, `enabled`
    and `lead`, which is exactly what the fallback carries.

    IT DOES NOT REUSE _guarded, AND THE REASON IS NOT STYLE. That helper
    catches pymysql.err.ProgrammingError, and 1054 is absent from pymysql's
    error_map so a MISSING COLUMN arrives as an OperationalError instead -
    _realm_guarded documents the measurement. On the read side that gap costs
    a banner; here it would 503 every order on a realm whose overseer_roster
    predates the campaign columns, which is the one realm most likely to need
    the fallback. So this guards on _DEGRADED like the writes below it.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for attempt in (_ROSTER_FULL, _ROSTER_OLD):
                try:
                    cur.execute(attempt)
                    return list(cur.fetchall())
                except pymysql.err.MySQLError as exc:
                    if not (exc.args and exc.args[0] in _DEGRADED):
                        raise
                    log.info("decree: overseer_roster is thinner than this "
                             "image expects (%s) - trying a thinner read",
                             exc.args[0])
    finally:
        conn.close()
    return []


def _apply_order(order) -> int:
    """Run one planned order and report how many writes CHANGED a row.

    Decides nothing. `order` already carries the exact rows and columns, and
    every guard below is about a degraded schema rather than about whether the
    order was a good idea - decree.plan_order made that call.

    CHANGED, NOT MATCHED. pymysql does not set CLIENT_FOUND_ROWS, so an UPDATE
    writing the value a row already holds reports 0. decree.order_result owns
    the sentence that says so.

    A DEGRADED WRITE IS LOGGED AND SKIPPED, never swallowed silently and never
    allowed to cost the rest of the family - the same rule bridge._set_job
    keeps on the identical fan-out. The count comes back short, and the count
    is what the operator is shown.
    """
    changed = 0
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for row in order.rows:
                try:
                    cur.execute(
                        "INSERT INTO overseer_command "
                        "(target_name, command, kind, source) "
                        "VALUES (%s, %s, %s, %s)",
                        (row.target_name, row.command, row.kind, WEB_SOURCE),
                    )
                except pymysql.err.MySQLError as exc:
                    if not (exc.args and exc.args[0] in _DEGRADED):
                        raise
                    log.warning(
                        "decree: overseer_command will not take kind=%r for %s "
                        "(%s) - this realm needs the worldserver image "
                        "carrying mod-overseer's SQL",
                        row.kind, row.target_name, exc.args[0],
                    )
                    continue
                changed += 1
            for up in order.updates:
                table = _ROSTER_SET_IF_FREE if up.if_free else _ROSTER_SET
                sql = table.get(up.column)
                if sql is None:
                    # Unreachable while decree.py and these tables agree, and
                    # said out loud rather than passed over: the one way to
                    # get here is a new column planned with no statement
                    # behind it, which would otherwise look like a write that
                    # simply did nothing.
                    log.error("decree: no statement for column %r", up.column)
                    continue
                params = ((up.value, up.name, up.value) if up.if_free
                          else (up.value, up.name))
                try:
                    cur.execute(sql, params)
                except pymysql.err.MySQLError as exc:
                    if not (exc.args and exc.args[0] in _DEGRADED):
                        raise
                    log.warning(
                        "decree: overseer_roster.%s is not writable on this "
                        "realm (%s) - %s keeps whatever it had",
                        up.column, exc.args[0], up.name,
                    )
                    continue
                changed += cur.rowcount
    finally:
        conn.close()
    return changed


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (stdlib naming)
        # A lookup and nothing else. Every GET endpoint takes the parsed
        # query and owns its own method, so adding one is a row in the table
        # at the foot of this class - not another branch here. The chain this
        # replaced had reached eight and tripped the complexity cap when
        # /api/watch landed (infra#2663).
        path = self.path.split("?", 1)[0]
        handler = self.GET_ROUTES.get(path)
        if handler is None:
            # The one prefix route: a model-viewer file is named by its
            # path, so the table cannot hold every one.
            if path.startswith(MODEL_PREFIX):
                self._modelviewer(path[len(MODEL_PREFIX):])
                return
            self._send(404, "text/plain", b"not found")
            return
        handler(self, parse_qs(urlsplit(self.path).query))

    def _modelviewer(self, path: str) -> None:
        """GET /modelviewer/<path> - Wowhead's model data, through the cache.

        The page cannot fetch this from wow.zamimg.com itself (see
        modelviewer.py), so it is fetched here once and kept. A refused
        path is a 404 that never leaves the pod; an unreachable upstream
        is a 502, which the page's own timeout turns into the paper doll.
        """
        r = MODELS.serve(path)
        if r.status == 502:
            log.warning("model viewer: upstream failed for %s", path)
        self._send(r.status, r.content_type, r.body, r.cache_control)

    def _index(self, _query: dict) -> None:
        # THE ONE FILE HERE THAT IS NOT SERVED VERBATIM. Every other
        # static file is the same bytes on every realm; the page is not,
        # because it has to know which path it was reached under before it
        # can build a single URL. basepath.py says what goes wrong when it
        # does not, and it is not a broken link.
        self._send_file("index.html", "text/html; charset=utf-8",
                        transform=lambda body: basepath.apply(body, BASE_PATH))

    def _zones_file(self, _query: dict) -> None:
        self._send_file("zones.json", "application/json")

    def _jquery_file(self, _query: dict) -> None:
        # Wowhead's model viewer needs jQuery. Vendored (3.7.1, verified
        # against the hash code.jquery.com publishes) and served from here
        # so the page reaches no third host for it.
        self._send_file("jquery.min.js", "text/javascript; charset=utf-8")

    def _shapes_file(self, _query: dict) -> None:
        # The zone REGIONS, built from zones.json by tools/gen_shapes.py.
        # Served rather than inlined so the page and the dots keep reading
        # the same committed geometry.
        self._send_file("shapes.json", "application/json")

    def _realm(self, _query: dict) -> None:
        """GET /api/realm - which world this page is showing, and its build.

        FIRST AMONG THE HANDLERS, above even the map, and outside every window
        the tab suites slice this class by. Every other endpoint answers a
        question about a world; this one answers which world, and that is the
        question the rest of the answers are only meaningful inside of.

        No parameters. This describes the deployment, not anybody the caller
        can name, so there is no user input to validate and none is read.

        A FAILED POLL LEAVES THE LAST BANNER STANDING, like every other poll on
        this page - but the reason is sharper here. The realm has not changed
        because a query timed out, so replacing a correct label with an empty
        one would be the page losing information it already had. The case that
        actually matters is the FIRST poll failing, and that is handled in the
        page rather than here: index.html ships the not-verified state as its
        static markup, so a page that never hears from this endpoint at all
        shows the alarm rather than nothing.
        """
        try:
            payload = realm.build_realm(**_fetch_realm())
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            log.exception("realm query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

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

    def _family(self, query: dict) -> None:
        """GET /api/family - the five, with enough to decide whether to look.

        No name parameter on purpose: WHO the family is belongs to bonds, and
        letting a caller pass a roster would make this a general character
        query with a friendly name.
        """
        try:
            payload = family.build_family(_fetch_family(), GEO)
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as /api/map: the tab shows its stale banner on a
            # failed poll and keeps the last cards it drew. A blank Family tab
            # is indistinguishable from a family who all logged out.
            log.exception("family query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _armory(self, query: dict) -> None:
        """GET /api/armory - what the five are wearing, and how they are specced.

        No name parameter, for the same reason /api/family takes none: WHO the
        family is belongs to bonds, and accepting a roster here would turn this
        into a general character query wearing a friendly name.
        """
        try:
            fetched = _fetch_armory()
            # WHERE each worn item was first seen worn, from the same equip
            # record the Chronicle reads and by the same rule. The adapter
            # hands over rows; recap decides which row is the first one, what
            # the place is called and what to say when there is no row at all.
            equip_rows = fetched.pop("equip_event_rows")
            payload = armory.build_armory(**fetched, book=BOOK, items=ITEMS)
            payload["provenance"] = recap.provenance_index(
                equip_rows, fetched["equipment_rows"], achievements.MAP_NAMES,
                recap.zone_names(GEO.continents))
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll: the tab keeps the grid it has
            # already drawn and says it may be stale. A blank Armory tab reads
            # as "they are wearing nothing", which is a worse lie than silence.
            log.exception("armory query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _standing(self, query: dict) -> None:
        """GET /api/standing - what the five have learned, and what they have not.

        No name parameter, for the same reason /api/armory takes none: WHO
        the family is belongs to bonds, and accepting a roster here would
        turn this into a general character query wearing a friendly name.
        """
        try:
            payload = standing.build_standing(**_fetch_standing(), book=STANDING,
                                              talents=BOOK)
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll: the panel keeps what it has
            # already drawn and says it may be stale. A blank standing panel
            # reads as "they have learned nothing", which is a worse lie
            # than an old answer honestly labelled.
            log.exception("standing query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _questlog(self, query: dict) -> None:
        """GET /api/questlog - what each of the five is actually working on.

        No name parameter, for the same reason /api/family and /api/armory
        take none: WHO the family is belongs to bonds, and accepting a roster
        here would turn this into a general character query wearing a
        friendly name.
        """
        try:
            payload = questlog.build_questlog(**_fetch_questlog())
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll: the tab keeps the logs it has
            # already drawn and says they may be stale. A blank quest log
            # reads as "they have nothing to do", which is the opposite of
            # what this view exists to report.
            log.exception("questlog query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _achievements(self, query: dict) -> None:
        """GET /api/achievements - what the family has done, newest first.

        No name parameter, for the same reason the other family endpoints
        take none: WHO the family is belongs to bonds.
        """
        try:
            payload = achievements.build_achievements(**_fetch_achievements())
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll: the tab keeps the timeline it
            # has drawn and says it may be stale. A blank achievements tab
            # reads as "they have done nothing", which is the one thing this
            # view exists to disprove.
            log.exception("achievements query failed")
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

    def _trades(self, _query: dict) -> None:
        """GET /api/trades - who can make what, and where the rest comes from.

        NO PARAMETERS AT ALL, and that is the shape of the view rather than an
        omission: it asks about every trade and every recipe in the world at
        once, so there is nothing for a caller to steer and no id to validate.
        WHO the guild is belongs to bonds and to the world's own guild table,
        exactly as /api/armory and /api/family refuse a name.
        """
        try:
            fetched = _fetch_guildcraft()
            payload = guildcraft.build_guildcraft(
                **fetched, icons=ITEMS.icons, book=ITEMS,
                roster=family.roster(), names=achievements.MAP_NAMES, geo=GEO)
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll: the tab keeps what it has
            # drawn and says it may be stale. A blanked list reads as "the
            # guild can make nothing and needs nothing", which is a far
            # stronger claim than "this one read failed".
            log.exception("guild trades query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _dungeons(self, _query: dict) -> None:
        """GET /api/dungeons - every dungeon, and who would gain by running it.

        NO PARAMETERS AT ALL, and that is the shape of the view rather than an
        omission: it asks about every dungeon in the world at once, so there
        is nothing for a caller to steer and no map id to validate. WHO the
        family is belongs to bonds, exactly as /api/armory and /api/family
        refuse a name.
        """
        try:
            payload = dungeonplan.build_dungeonplan(
                **_fetch_dungeonplan(), icons=ITEMS.icons, book=ITEMS,
                roster=family.roster(), names=achievements.MAP_NAMES,
                entrances=GEO.entrances, continents=GEO.continents)
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll: the tab keeps what it has
            # drawn and says it may be stale. A blanked list reads as "there
            # is nothing worth running anywhere", which is a far stronger
            # claim than "this one read failed".
            log.exception("dungeon plan query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _recap(self, query: dict) -> None:
        """GET /api/recap[?map=N] - what is happening in there right now, and
        what can drop where.

        `map` is the only parameter, it is a dungeon map id, and it is parsed
        to an int here and bound by the driver below. Anything unparseable is
        dropped rather than rejected: the recap of the live run is still the
        right answer to a request with a broken query string, and a 400 would
        blank a tab over a typo in a URL somebody pasted.
        """
        # ONLY A MAP THIS SITE ALREADY NAMES. `?map=1` is Kalimdor, and both
        # world reads below would then scan a whole continent's spawn table on
        # an endpoint that takes no auth and is polled every thirty seconds.
        # achievements.MAP_NAMES is the list of dungeons this site knows, so
        # it is the allowlist; anything else falls back to the live run's map
        # rather than being rejected, because the recap is still the right
        # answer to a request with a bad query string and a 400 would blank
        # the tab over a typo in a pasted URL.
        asked = query.get("map", [None])[0]
        map_id = int(asked) if asked and asked.isdigit() else None
        if map_id not in achievements.MAP_NAMES:
            map_id = None
        try:
            fetched = _fetch_recap(map_id)
            board_map = fetched.pop("board_map")
            board_encounters = fetched.pop("board_encounter_rows")
            item_rows = fetched.pop("item_rows")
            loot_rows = fetched.pop("loot_rows")
            char_rows = fetched.pop("char_rows")
            equipped_rows = fetched.pop("equipped_rows")
            skill_rows = fetched.pop("skill_rows")
            payload = recap.build_recap(
                roster=family.roster(),
                items={int(row["entry"]): row for row in item_rows},
                icons=ITEMS.icons, book=ITEMS,
                dungeons=achievements.MAP_NAMES,
                zones=recap.zone_names(GEO.continents),
                now=datetime.now(), **fetched)
            payload["board"] = recap.build_lootboard(
                board_map, achievements.MAP_NAMES.get(board_map,
                                                      "map %d" % board_map),
                board_encounters, loot_rows, char_rows, equipped_rows,
                ITEMS.icons, family.roster(), skill_rows, ITEMS)
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll: the tab keeps what it has
            # drawn and says it may be stale. A blank recap reads as "nothing
            # is happening", which is the one thing this view exists to answer.
            log.exception("recap query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _council(self, query: dict) -> None:
        """GET /api/council - the last sitting, what it carried, where next.

        Deliberately BELOW the thought handler and ABOVE the wealth one. Four
        suites slice this class by handler name - the Family and Armory ones
        end at the thought handler, the Wealth and current-goal ones run from
        theirs to the POST dispatcher - and this gap is the only window none
        of them claims. Naming those boundaries in full here would be worse
        than useless: the slices are taken by string index, so a docstring
        that spells one out becomes the boundary.

        The Chronicle's own builder is called here to supply what the family
        has watched drop, rather than the prospects panel re-deriving it: which
        run a drop belongs to is a question achievements.py already answers,
        and a second answer to it here would be free to disagree about the
        only knowledge this view can honestly report.

        No name parameter, like every other family endpoint: WHO the family is
        belongs to bonds.
        """
        try:
            cards = achievements.build_achievements(**_fetch_achievements())["cards"]
            payload = council.build_council(**_fetch_council(), cards=cards)
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll: the view keeps the transcript
            # it has drawn and says it may be stale. A blanked council reads as
            # "the family has stopped talking", which is a far stronger claim
            # than "this one read failed".
            log.exception("council query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _eye(self, query: dict) -> None:
        """GET /api/eye - the server rollup, tier by tier, honestly.

        Beside the council handler, in the same unclaimed window and for the
        same reason.

        No name parameter: this asks about the realm as one thing, and the one
        roster clause it does have comes from bonds.
        """
        try:
            payload = eye.build_eye(**_fetch_eye())
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Blanking this one would be the worst failure on the page: a
            # rollup that exists to say what is NOT real, rendering empty,
            # reads as a realm where nothing is real at all.
            log.exception("eye query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _wealth(self, query: dict) -> None:
        """GET /api/wealth - what the five are carrying, and what it is worth.

        Deliberately BELOW _thoughts rather than beside _armory: the Armory
        tab's suite slices this class from `def _armory` to `def _thoughts`
        and asserts about everything it finds in that window, so a second
        handler dropped into it would be read as part of the Armory's own
        contract.

        No name parameter, for the same reason /api/family and /api/armory
        take none: WHO the family is belongs to bonds, and accepting a roster
        here would turn this into a general character query wearing a
        friendly name.
        """
        try:
            payload = wealth.build_wealth(**_fetch_wealth(), icons=ITEMS.icons)
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll: the view keeps the bags it
            # has already drawn and says they may be stale. A blank wealth
            # panel reads as "they own nothing", and an empty bag grid reads
            # as "they have plenty of room", which is the exact opposite of
            # the finding this view exists to surface.
            log.exception("wealth query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _needs(self, query: dict) -> None:
        """GET /api/needs - what the five need, and what is being done about it.

        Deliberately BELOW _thoughts and beside _wealth, for exactly the
        reason _wealth gives for being there: the Armory tab's suite slices
        this class from `def _armory` to `def _thoughts` and reads everything
        it finds as the Armory's own contract, so a handler dropped into that
        window is read as part of a feature it has nothing to do with.

        No name parameter, for the same reason /api/family and /api/armory
        take none: WHO the family is belongs to bonds, and accepting a roster
        here would turn this into a general character query wearing a
        friendly name.
        """
        try:
            payload = needs.build_needs(**_fetch_needs())
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll: the view keeps the bars it
            # has already drawn and says they may be stale. A blank needs
            # panel reads as "there is nothing wrong with any of them", which
            # is the one claim this view exists to be able to disprove.
            log.exception("needs query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _agenda(self, query: dict) -> None:
        """GET /api/agenda - what the family is trying to do right now.

        Below _wealth for the same reason _wealth is below _thoughts: the
        Family tab's suite slices this class from `def _family` to
        `def _thoughts` and the Armory's from `def _armory` to the same place,
        so a handler dropped into either window is read as part of a contract
        it has nothing to do with.

        No name parameter, like every other family endpoint: WHO the family is
        belongs to bonds, and this asks about the family as one thing anyway -
        a per-character agenda is the split it exists to report.
        """
        try:
            payload = agenda.build_agenda(**_fetch_agenda())
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll, and it matters more here than
            # anywhere else on the page. This banner is the first thing read
            # and the most confidently worded; blanking it on a failed poll
            # would read as "the family has no goal", and replacing it with a
            # cheerful default would be the page inventing one. So the last
            # good answer stays up and the page marks it stale.
            log.exception("agenda query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

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
        # None when the voice picked no command, which is an ordinary answer:
        # the reply below always carries the key, so a caller can tell "no
        # order was queued" from "an order was queued and I lost the id".
        row_id = None
        if decision.command is not None:
            # voice.parse_decision already gated this string; the web
            # surface delivers it down the same road as Discord.
            row_id = _insert_command(name, decision.command, WEB_SOURCE)
            log.info("web chat queued command %s for %s: %s", row_id, name, decision.command)
        self._send(200, "application/json", json.dumps({
            "present": True,
            "say": decision.say,
            "command": decision.command,
            "degraded": degraded,
            # THE ROW ID, so a caller can follow what became of the order
            # instead of assuming. Queued is not delivered, and delivered is
            # not applied; the decree console reads all three off the row
            # this names (infra#2819).
            "command_id": row_id,
        }).encode())

    def _decree(self, query: dict) -> None:
        """GET /api/decree - the console's own state, fully decided.

        BELOW the chat handler and above the watch one, which is the one
        gap in this class no other endpoint suite claims: the Family, Armory,
        Wealth and current-goal windows all end at the thoughts handler or at
        do_POST, and the watch window starts below this. Those suites slice
        this file on the literal string "def <name>", which is why no name
        above is written that way.

        No name parameter, like every other family endpoint: a job is
        family-wide by construction and a campaign belongs to one party, so a
        per-character console would answer a question this view does not ask.
        """
        try:
            payload = decree.build_console(**_fetch_decree())
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll, and it matters here for a
            # particular reason: this console exists to say what is real. A
            # blanked card would read as "no job is set" and a cheerful
            # default would be the page inventing an order nobody gave, so
            # the last good answer stays up and the page marks it stale.
            log.exception("decree query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

    def _decree_post(self) -> None:
        """POST /api/decree - the console gives an order.

        VALIDATES NOTHING ITSELF, which is the rule this whole view is built
        on. The body and the roster go to decree.plan_order; back comes either
        a refusal with a reason or a concrete list of rows to insert and
        columns to set. There is no `if` here about job modes, campaign
        numbers or character names, and there must not be one.

        THE REFUSAL IS A 400 AND CARRIES THE MODULE'S OWN SENTENCE, printed
        verbatim: a status code alone would have the browser composing an
        explanation of a system it knows nothing about.
        """
        request = self._read_json_body()
        if request is None:
            return
        try:
            # THE LOCK COVERS THE PLAN AND THE WRITES AND NOTHING ELSE. A
            # _send inside it would hold every other order behind one slow
            # socket, which is a queue nobody asked for on a page polled every
            # ten seconds.
            with _DECREE_LOCK:
                order = decree.plan_order(request, _fetch_roster_rows())
                changed = 0 if order.refusal else _apply_order(order)
            if order.refusal:
                log.info("decree: refused section=%r", order.section)
                self._send(400, "application/json", json.dumps({
                    "error": order.refusal, "section": order.section,
                }).encode())
                return
            log.info("decree: section=%s asked=%d changed=%d",
                     order.section, order.asked, changed)
            self._send(200, "application/json",
                       json.dumps(decree.order_result(order, changed)).encode())
        except Exception:
            # Same contract as every other endpoint, and it matters on a write
            # more than on a read: a console that reported an order it could
            # not place would be the exact failure this view is named after.
            log.exception("decree order failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

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
        now = time.time()
        payload = {
            "channels_in_use": stream.channels_in_use(rows),
            "max_channels": stream.MAX_CHANNELS,
            "heartbeat_seconds": stream.HEARTBEAT_SECONDS,
            # How long a login HONESTLY takes, so the page can show the wait
            # against a stated budget rather than an unexplained spinner. The
            # number belongs to the lifecycle, not to the page: hard-coding
            # "45-60s" in HTML would drift the day the agent gets faster.
            "startup_seconds": stream.STARTUP_SECONDS,
            "watching": None,
            # Why the last attempt stopped, while that is still news. The
            # agent answers a request it cannot honour by ending the row with
            # a reason, so this is the ONLY path that reason has to a screen.
            "outcome": stream.outcome_of(mine, now) if mine else None,
        }
        if mine and mine.get("state") in stream.OCCUPIES_A_CLIENT:
            payload["watching"] = {
                "state": mine.get("state"),
                "mode": mine.get("mode"),
                "detail": mine.get("detail") or "",
                "delivery": stream.delivery_of(mine),
                # The two clocks a waiting viewer needs. `waited_seconds` is
                # measured from requested_at (the heartbeat rewrites last_seen
                # every ten seconds and would read "3s" for the whole minute);
                # `unclaimed` separates a slow login from nothing running on
                # the box at all, which look identical on screen and are fixed
                # in entirely different places.
                "waited_seconds": stream.waited_seconds(mine, now),
                "unclaimed": stream.looks_unclaimed(mine, now),
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

    def _frame_get(self, query: dict) -> None:
        """GET /api/frame?name=X - the last picture, or what went wrong.

        `meta=1` answers in JSON; without it the JPEG itself comes back, so
        the page can point an <img> straight at this.
        """
        name = query.get("name", [""])[0]
        if not _NAME_RE.fullmatch(name):
            self._send(400, "application/json", b'{"error": "not a character name"}')
            return
        with _FRAMES_LOCK:
            record = dict(_FRAMES.get(name) or {})
        if query.get("meta", [""])[0]:
            payload = frames.describe(record, time.time())
            self._send(200, "application/json", json.dumps(payload).encode())
            return
        jpeg = record.get("jpeg")
        if not jpeg:
            self._send(404, "application/json", b'{"error": "no frame yet"}')
            return
        self._send(200, "image/jpeg", jpeg)

    def _frame_post(self) -> None:
        """POST /api/frame?name=X&status=ok|black|failed[&detail=...]

        The frame and its status arrive in ONE request on purpose. Posting a
        picture and then its status separately is two chances for the panel to
        show an image with the wrong status attached.
        """
        query = parse_qs(urlsplit(self.path).query)
        name = query.get("name", [""])[0]
        if not _NAME_RE.fullmatch(name):
            self._send(400, "application/json", b'{"error": "not a character name"}')
            return
        status = query.get("status", [frames.OK])[0]
        detail = query.get("detail", [""])[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > frames.MAX_FRAME_BYTES:
            self._send(413, "application/json", b'{"error": "frame too large"}')
            return
        body = self.rfile.read(length) if length else b""
        why = frames.refusal(name, status, body, detail)
        if why:
            # A sentence, not a bare 400: the agent posting these runs on
            # another machine, and a refusal with no reason is the same dead
            # end as a capture that goes quiet.
            self._send(400, "application/json",
                       json.dumps({"error": why}).encode())
            return
        with _FRAMES_LOCK:
            _FRAMES[name] = frames.accept(_FRAMES.get(name), status, body,
                                          detail, time.time())
        if status != frames.OK:
            log.info("frame: %s reported %s%s", name, status,
                     " - " + frames.clean_detail(detail) if detail else "")
        self._send(200, "application/json",
                   json.dumps(frames.describe(_FRAMES[name], time.time())).encode())

    def _party_status(self, _query: dict) -> None:
        """GET /api/party-status - one line the in-game addon can render.

        infra#3334. The party frames in five game clients say who the family
        are and nothing about what they are doing. This is the half of that
        answer no client can see for itself; the other half - dead, offline,
        out of sight, fighting, out of range - the addon observes and needs
        nothing from here.

        READS NOTHING THE AGENDA BANNER DOES NOT ALREADY READ. `_fetch_agenda`
        is reused whole rather than replaced by a thinner query of its own, for
        the same reason agenda.py adds no table: two surfaces querying the same
        family separately is two surfaces that can disagree about it, and every
        `overseer_*` read in there is already behind `_guarded` for 1146 and
        1054.

        No name parameter. The line carries the whole roster because the addon
        renders the whole party, and a per-character endpoint would answer a
        question no viewer of a party frame is asking.

        BELOW _frame_post and above _read_json_body, which is the one window in
        this class no other endpoint suite slices: the Agenda, Armory,
        Questlog, Wealth, Decree and Watch suites each cut this file by their
        own handler's name, and a handler dropped inside one of those windows
        is read as part of a contract it has nothing to do with.
        """
        try:
            rows = _fetch_agenda()
            payload = partystatus.build_push(
                roster_rows=rows["roster_rows"],
                run_rows=rows["run_rows"],
                event_rows=rows["event_rows"],
            )
            self._send(200, "application/json", json.dumps(payload).encode())
        except Exception:
            # Same contract as every other poll. It matters particularly here:
            # a blank line rendered as success would blank five labels in the
            # game and read as "nobody is doing anything", which is a specific
            # and alarming claim rather than the absence of one.
            log.exception("party status query failed")
            self._send(503, "application/json", b'{"error": "world unreachable"}')

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

    def _send_file(self, name: str, ctype: str, transform=None) -> None:
        # A file missing from the image must be a readable 500, not a bare
        # connection reset - the page keys its error banner off r.ok.
        #
        # A REFUSED TRANSFORM IS THE SAME CLASS OF FAILURE AND GETS THE
        # SAME TREATMENT. basepath.apply raises when the page has lost the
        # placeholder that tells it where it is mounted, and the whole
        # point of that raise is that serving the page anyway would look
        # perfectly normal while addressing the realm at the root. So it
        # has to reach the browser as an error rather than as a page.
        try:
            with open(os.path.join(HERE, name), "rb") as f:
                body = f.read()
            if transform is not None:
                body = transform(body)
        except (OSError, ValueError):
            log.exception("static file %s cannot be served", name)
            self._send(500, "text/plain", b"static file missing from image")
            return
        self._send(200, ctype, body)

    def _send(self, code: int, ctype: str, body: bytes,
              cache_control: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # no-store for everything the page polls; the model-viewer files
        # are the one immutable thing here and say so themselves.
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.info("%s " + fmt, self.address_string(), *args)

    # The tables sit at the foot of the class so every method they name is
    # already defined. Values are plain functions, called with the handler
    # instance - a new endpoint is one row, and an unknown path is one miss.
    GET_ROUTES = {
        # First, because it is the question every other row here answers
        # inside of (quadseven/mod-overseer#184).
        "/api/realm": _realm,
        "/api/map": _map,
        "/api/character": _character,
        "/api/family": _family,
        "/api/armory": _armory,
        "/api/standing": _standing,
        "/api/wealth": _wealth,
        "/api/questlog": _questlog,
        "/api/needs": _needs,
        "/api/achievements": _achievements,
        "/api/dungeons": _dungeons,
        "/api/trades": _trades,
        "/api/recap": _recap,
        "/api/council": _council,
        "/api/eye": _eye,
        "/api/agenda": _agenda,
        "/api/party-status": _party_status,
        "/api/decree": _decree,
        "/api/thoughts": _thoughts,
        "/api/watch": _watch_state,
        "/": _index,
        "/index.html": _index,
        "/zones.json": _zones_file,
        "/shapes.json": _shapes_file,
        "/jquery.min.js": _jquery_file,
        "/api/frame": _frame_get,
        "/healthz": _healthz,
    }
    POST_ROUTES = {
        "/api/chat": _chat_post,
        "/api/decree": _decree_post,
        "/api/watch": _watch_post,
        "/api/frame": _frame_post,
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
