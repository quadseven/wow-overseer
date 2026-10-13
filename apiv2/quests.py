"""The quest catalogue and what the questers made of it (#923).

GET /api/v2/quests?faction=&zone=&level_min=&level_max=&status=

    {quests: [{id, title, level, min_level, zone, zone_name, faction, races,
               classes, follows, status, attempts}],
     totals: {quests, completed, broken, taken, abandoned, not_reached},
     by_faction: {horde: totals, alliance: totals}, shown}

  Every quest of the classic ruleset (questcatalogue.py) with its status off
  the quest ledger (questledger.py): completed when a quester was rewarded
  for it, else broken, taken or abandoned, else not_reached. `faction` keeps
  that side's quests and the ones both sides take; `zone` is an area id;
  `level_min` and `level_max` bound the quest level, both included. `totals`
  is the coverage of the quests those four filters keep, before `status`
  narrows the list; `by_faction` is each side's whole catalogue.

GET /api/v2/quests/{id}

    {quest: {... as above}, attempts: [{character, guid, guild, state,
             first_taken, finished, reason}]}

  One catalogue quest with every quester's attempt at it. A quest outside the
  catalogue is a 404.

GET /api/v2/questers

    {questers: [{name, guild, present, level, zone, zone_name, online,
                 current: [{id, title, status}], completed, broken, taken,
                 abandoned}]}

  The ten questers in questledger.QUESTERS order. One that is not on the
  realm yet reads present: false with no level and no counts.

A realm without the ledger table answers every quest as not_reached and
every quester with zero counts.
"""

from __future__ import annotations

import questcatalogue
import questledger
import questlog

# Read only catalogue quest ids, in bounded batches. Each result has at most
# one count per quest and state, regardless of how many questers attempted it.
LEDGER_BATCH_SIZE = 500
LEDGER_SQL = (
    "SELECT quest, state, COUNT(*) AS n FROM overseer_quest_ledger "
    "WHERE quest IN ({holes}) GROUP BY quest, state"
)
QUEST_LEDGER_SQL = (
    "SELECT quest, guid, character_name, state, first_taken, finished, reason "
    "FROM overseer_quest_ledger WHERE quest = %s ORDER BY first_taken, guid"
)
COUNTS_SQL = (
    "SELECT guid, state, COUNT(*) AS n FROM overseer_quest_ledger "
    "WHERE guid IN ({holes}) GROUP BY guid, state"
)

_LOG_WORDS = {
    questlog.COMPLETE: "complete",
    questlog.INCOMPLETE: "incomplete",
    questlog.FAILED: "failed",
}


def _catalogue(ctx) -> tuple:
    return questcatalogue.load(
        lambda sql: ctx.read.rows(sql, (), what="quest_template")
    )


def _when(value):
    if value is None:
        return None
    return value.isoformat(sep=" ") if hasattr(value, "isoformat") else str(value)


def _one(query: dict, key: str) -> str:
    return (query.get(key) or [""])[0].strip()


def _number(query: dict, key: str):
    """The integer `key`, None when absent; ValueError when not a number."""
    text = _one(query, key)
    return int(text) if text else None


def _states(ledger_rows) -> dict:
    """quest -> {state: attempts} off grouped ledger rows."""
    out: dict = {}
    for row in ledger_rows or ():
        out.setdefault(int(row["quest"]), {})[str(row.get("state") or "")] = int(
            row["n"]
        )
    return out


def _totals(quests, statuses: dict) -> dict:
    out = {"quests": len(quests)}
    for state in questledger.STATUS_ORDER:
        out[state] = 0
    for quest in quests:
        out[statuses[quest.id]] += 1
    return out


def build_quests(
    catalogue,
    ledger_rows,
    faction="",
    zone=None,
    level_min=None,
    level_max=None,
    status="",
) -> dict:
    """Catalogue and ledger rows in, the /api/v2/quests payload out. Pure."""
    states = _states(ledger_rows)
    statuses = {q.id: questledger.quest_status(states.get(q.id)) for q in catalogue}
    kept = questcatalogue.select(catalogue, faction, zone, level_min, level_max)
    shown = [q for q in kept if not status or statuses[q.id] == status]
    return {
        "quests": [
            {
                **q.view(),
                "status": statuses[q.id],
                "attempts": sum(states.get(q.id, {}).values()),
            }
            for q in shown
        ],
        "totals": _totals(kept, statuses),
        "by_faction": {
            side: _totals(questcatalogue.for_faction(catalogue, side), statuses)
            for side in (questcatalogue.HORDE, questcatalogue.ALLIANCE)
        },
        "shown": len(shown),
    }


def quests(query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/quests?faction=&zone=&level_min=&level_max=&status= -
    the classic quest catalogue with ledger coverage totals."""
    faction = _one(query, "faction").lower()
    if faction and faction not in questcatalogue.FACTIONS:
        return 400, {"error": "faction is horde, alliance or both"}
    status = _one(query, "status").lower()
    if status and status not in questledger.STATUS_ORDER:
        return 400, {"error": "status is one of " + ", ".join(questledger.STATUS_ORDER)}
    try:
        zone = _number(query, "zone")
        level_min = _number(query, "level_min")
        level_max = _number(query, "level_max")
    except ValueError:
        return 400, {"error": "zone, level_min and level_max are whole numbers"}
    catalogue = _catalogue(ctx)
    ledger = []
    for start in range(0, len(catalogue), LEDGER_BATCH_SIZE):
        ids = tuple(q.id for q in catalogue[start : start + LEDGER_BATCH_SIZE])
        ledger.extend(
            ctx.read.rows(
                LEDGER_SQL.format(holes=questledger.holes(len(ids))),
                ids,
                what="overseer_quest_ledger",
            )
        )
    return 200, build_quests(
        catalogue, ledger, faction, zone, level_min, level_max, status
    )


def _attempt(row) -> dict:
    name = str(row.get("character_name") or "")
    return {
        "character": name,
        "guid": int(row["guid"]),
        "guild": questledger.guild_of(name),
        "state": str(row.get("state") or ""),
        "first_taken": _when(row.get("first_taken")),
        "finished": _when(row.get("finished")),
        "reason": str(row.get("reason") or ""),
    }


def build_quest(quest, ledger_rows) -> dict:
    """One catalogue quest and its ledger rows in, /api/v2/quests/{id} out."""
    states = [str(r.get("state") or "") for r in ledger_rows or ()]
    return {
        "quest": {
            **quest.view(),
            "status": questledger.quest_status(states),
            "attempts": len(states),
        },
        "attempts": [_attempt(r) for r in ledger_rows or ()],
    }


def quest(query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/quests/{id} - one classic quest and every quester attempt."""
    try:
        quest_id = int(_one(query, "id"))
    except ValueError:
        return 400, {"error": "a quest id is a whole number"}
    found = next((q for q in _catalogue(ctx) if q.id == quest_id), None)
    if found is None:
        return 404, {"error": "quest %d is not in the classic catalogue" % quest_id}
    rows = ctx.read.rows(QUEST_LEDGER_SQL, (quest_id,), what="overseer_quest_ledger")
    return 200, build_quest(found, rows)


def _current_quests(log_rows, titles: dict) -> dict:
    """guid -> the quests in that character's log, by quest id."""
    current: dict = {}
    for row in log_rows or ():
        status = int(row.get("status") or 0)
        if status not in questlog.IN_LOG:
            continue
        quest_id = int(row["quest"])
        current.setdefault(int(row["guid"]), []).append(
            {
                "id": quest_id,
                "title": titles.get(quest_id, ""),
                "status": _LOG_WORDS[status],
            }
        )
    return {guid: sorted(qs, key=lambda q: q["id"]) for guid, qs in current.items()}


def _quester(name: str, row, current: dict, counts: dict) -> dict:
    """One quester's entry; `row` is its CHARACTERS_SQL row, or None."""
    entry = {
        "name": name,
        "guild": questledger.guild_of(name),
        "present": row is not None,
    }
    if row is None:
        entry.update(
            level=None,
            zone=None,
            zone_name="",
            online=False,
            current=[],
            **{s: 0 for s in questledger.STATES},
        )
        return entry
    guid = int(row["guid"])
    zone = int(row.get("zone") or 0) or None
    mine = counts.get(guid, {})
    entry.update(
        level=int(row.get("level") or 0),
        zone=zone,
        zone_name=questcatalogue.zone_name(zone),
        online=bool(row.get("online")),
        current=current.get(guid, []),
        **{state: mine.get(state, 0) for state in questledger.STATES},
    )
    return entry


def build_questers(characters, log_rows, count_rows, titles: dict) -> dict:
    """Rows in, the /api/v2/questers payload out. Pure.

    `characters` are questledger.CHARACTERS_SQL rows, `titles` quest id ->
    title for the quests the log names.
    """
    by_name = {str(r["name"]): r for r in characters or ()}
    current = _current_quests(log_rows, titles)
    counts: dict = {}
    for row in count_rows or ():
        counts.setdefault(int(row["guid"]), {})[str(row["state"])] = int(row["n"])
    return {
        "questers": [
            _quester(name, by_name.get(name), current, counts)
            for name in questledger.quester_names()
        ]
    }


def questers(_query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/questers - each quester's location, current quests and
    ledger counts."""
    names = questledger.quester_names()
    characters = ctx.read.rows(
        questledger.CHARACTERS_SQL.format(holes=questledger.holes(len(names))),
        tuple(names),
        what="characters",
    )
    # Filter missing guids before int conversion or joining quest rows.
    characters = [r for r in characters if r.get("guid") is not None]
    guids = tuple(sorted(int(r["guid"]) for r in characters))
    log_rows, count_rows = [], []
    if guids:
        marks = questledger.holes(len(guids))
        log_rows = ctx.read.rows(
            questledger.LOG_SQL.format(holes=marks), guids, what="character_queststatus"
        )
        count_rows = ctx.read.rows(
            COUNTS_SQL.format(holes=marks), guids, what="overseer_quest_ledger"
        )
    titles = {q.id: q.title for q in _catalogue(ctx)}
    return 200, build_questers(characters, log_rows, count_rows, titles)


ROUTES = {
    "/api/v2/quests": quests,
    "/api/v2/quests/{id}": quest,
    "/api/v2/questers": questers,
}
