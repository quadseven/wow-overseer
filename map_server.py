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
import armory
import chat
import family
import frames
import modelviewer
import questlog
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
    finally:
        conn.close()
    return {"char_rows": char_rows, "inventory_rows": inventory_rows,
            "auction_rows": auction_rows}


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
    return {"char_rows": char_rows, "equipment_rows": equipment_rows,
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
                cur.execute(
                    "SELECT entry, name, Quality, ItemLevel, displayid "  # noqa: S608
                    f"FROM acore_world.item_template WHERE entry IN ({iholes})",
                    tuple(entries),
                )
                items = {int(r["entry"]): r for r in cur.fetchall()}
    finally:
        conn.close()
    return {"run_rows": run_rows, "event_rows": event_rows, "death_rows": death_rows,
            "items": items, "icons": ITEMS.icons, "boss_drops": boss_drops,
            "quest_rewards": quest_rewards, "roster": names}


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
        self._send_file("index.html", "text/html; charset=utf-8")

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
            payload = armory.build_armory(**_fetch_armory(), book=BOOK, items=ITEMS)
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
        "/api/map": _map,
        "/api/character": _character,
        "/api/family": _family,
        "/api/armory": _armory,
        "/api/standing": _standing,
        "/api/wealth": _wealth,
        "/api/questlog": _questlog,
        "/api/achievements": _achievements,
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
