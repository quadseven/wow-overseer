"""What happened to each quest a quester took (#923): the quest ledger.

WHY THIS EXISTS. The questers (#922) prove that quests work, and proving
needs a record: which quests were taken, which were finished, which broke and
why. The realm keeps only the present. character_queststatus is the log as it
is now and character_queststatus_rewarded is (guid, quest) with no time on it,
so a quest dropped an hour ago, or the hour a quest was taken, is gone.

THE TABLE (`TABLE_SQL`): overseer_quest_ledger, one row per quest and
character, in acore_characters beside the other overseer_* tables. `state`:

  taken      in the quester's log now (complete or not, but not failed)
  completed  rewarded (character_queststatus_rewarded)
  broken     cannot be finished; `reason` says why. Today that is a quest
             the log holds as failed (an escort died, a timer ran out); the
             bridge's quester mode (#924) adds the failures it can name
  abandoned  was taken, and has left the log without being rewarded

`first_taken` is when the ledger first saw the quest in the log, and
`finished` when it saw it completed, broken or abandoned. Both stay NULL
when the ledger never saw that moment: a quest already rewarded the first
time the ledger looks is completed with no `finished`, because the realm
does not say when, and a made-up time would read as a measurement.

WHO (`QUESTERS`): the questers of raidteams.QUESTERS, ten per guild (#922's
five and five more so every class has one). #927 recruits
them; until a name is on the realm it simply has no rows.

THE PASS (`changes`): the ledger rows, the quest log and the rewarded quests
of the questers in; the rows to write out. bridge.py reads and writes.

PURE: no MySQL, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import questlog
import raidteams

TAKEN = "taken"
COMPLETED = "completed"
BROKEN = "broken"
ABANDONED = "abandoned"
STATES = (TAKEN, COMPLETED, BROKEN, ABANDONED)

FAILED_REASON = "the quest failed in the log"

# The questers of #922, by guild: Cave is the Alliance guild, Bonkers the
# Horde one. #927 recruits each at level 1 in its race's starting zone.
# Read from the approved teams, never copied: a copy kept the first ten and
# would have hidden the second ten from the ledger and the site.
QUESTERS = {
    guild: tuple(q.name for q in seats) for guild, seats in raidteams.QUESTERS.items()
}


def quester_names() -> list:
    """Every quester's name, guild by guild in table order."""
    return [name for guild in QUESTERS for name in QUESTERS[guild]]


def guild_of(name: str) -> str:
    for guild, names in QUESTERS.items():
        if name in names:
            return guild
    return ""


TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS overseer_quest_ledger ("
    "quest INT UNSIGNED NOT NULL, "
    "guid INT UNSIGNED NOT NULL, "
    "character_name VARCHAR(12) NOT NULL DEFAULT '', "
    "state VARCHAR(16) NOT NULL, "
    "first_taken DATETIME NULL, "
    "finished DATETIME NULL, "
    "reason VARCHAR(255) NOT NULL DEFAULT '', "
    "ticket INT UNSIGNED NULL, "
    "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP "
    "ON UPDATE CURRENT_TIMESTAMP, "
    "PRIMARY KEY (quest, guid), KEY by_guid (guid)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)

NOW_SQL = "SELECT NOW() AS now"
CHARACTERS_SQL = (
    "SELECT guid, name, level, race, class, zone, online FROM characters "
    "WHERE name IN ({holes})"
)
LOG_SQL = (
    "SELECT guid, quest, status FROM character_queststatus WHERE guid IN ({holes})"
)
REWARDED_SQL = (
    "SELECT guid, quest FROM character_queststatus_rewarded WHERE guid IN ({holes})"
)
LEDGER_SQL = (
    "SELECT quest, guid, character_name, state, first_taken, finished, reason "
    "FROM overseer_quest_ledger WHERE guid IN ({holes})"
)
WRITE_SQL = (
    "INSERT INTO overseer_quest_ledger "
    "(quest, guid, character_name, state, first_taken, finished, reason) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
    "ON DUPLICATE KEY UPDATE character_name = VALUES(character_name), "
    "state = VALUES(state), first_taken = VALUES(first_taken), "
    "finished = VALUES(finished), reason = VALUES(reason)"
)


def holes(n: int) -> str:
    """The placeholders of an IN list. An empty list is the caller's to skip:
    `IN ()` is a syntax error, not an empty answer."""
    if n < 1:
        raise ValueError("holes needs at least one value")
    return ", ".join(["%s"] * n)


@dataclass(frozen=True)
class Entry:
    quest: int
    guid: int
    character_name: str
    state: str
    first_taken: object  # a datetime, or None
    finished: object
    reason: str

    def args(self) -> tuple:
        """WRITE_SQL's values."""
        return (
            self.quest,
            self.guid,
            self.character_name,
            self.state,
            self.first_taken,
            self.finished,
            self.reason,
        )


def _entry(row) -> Entry:
    return Entry(
        quest=int(row["quest"]),
        guid=int(row["guid"]),
        character_name=str(row.get("character_name") or ""),
        state=str(row.get("state") or ""),
        first_taken=row.get("first_taken"),
        finished=row.get("finished"),
        reason=str(row.get("reason") or ""),
    )


def _rewarded(old: Entry | None, now) -> tuple | None:
    """A quest the character was rewarded for."""
    if old and old.state == COMPLETED:
        return None
    # Seen finishing only when the ledger was already watching it.
    seen = old is not None and old.state == TAKEN
    return COMPLETED, old.first_taken if old else None, now if seen else None, ""


def _in_log(old: Entry | None, status: int, now) -> tuple | None:
    """A quest in the log, failed or still under way."""
    first = old.first_taken if old else None
    if status == questlog.FAILED:
        if old and old.state == BROKEN:
            return None
        return BROKEN, first or now, now, FAILED_REASON
    if old and old.state in (TAKEN, COMPLETED):
        # A completed quest back in the log is a repeatable taken again:
        # the ledger keeps that it was proven.
        return None
    return TAKEN, first or now, None, ""


def _next(old: Entry | None, status, rewarded: bool, now) -> tuple | None:
    """(state, first_taken, finished, reason) for one quest and character,
    or None to leave it as it is. `status` is its log status, or None when
    the quest is not in the log. Reward and log transitions live in their
    helpers so this function only selects which transition applies. It has
    four branches: rewarded, in log, abandoned, and unchanged."""
    if rewarded:
        return _rewarded(old, now)
    if status is not None and (
        int(status) == questlog.FAILED or int(status) in questlog.IN_LOG
    ):
        return _in_log(old, int(status), now)
    if old and old.state == TAKEN:
        return ABANDONED, old.first_taken, now, ""
    return None


def _index(names: dict, ledger_rows, log_rows, rewarded_rows) -> tuple:
    """(old, status, rewarded) keyed by (quest, guid), known guids only."""
    old = {}
    for row in ledger_rows or ():
        entry = _entry(row)
        if entry.guid in names:
            old[(entry.quest, entry.guid)] = entry
    status = {}
    for row in log_rows or ():
        guid = int(row["guid"])
        if guid in names:
            status[(int(row["quest"]), guid)] = row.get("status")
    rewarded = {
        (int(r["quest"]), int(r["guid"]))
        for r in rewarded_rows or ()
        if int(r["guid"]) in names
    }
    return old, status, rewarded


def changes(characters, ledger_rows, log_rows, rewarded_rows, now) -> list:
    """The Entry rows to write for these questers.

    `characters` maps guid -> name. A quester's quest is written when its
    state moves, or when the character's name has changed since.
    """
    names = {int(g): str(n) for g, n in (characters or {}).items()}
    old, status, rewarded = _index(names, ledger_rows, log_rows, rewarded_rows)
    out = []
    for key in sorted(set(old) | set(status) | rewarded):
        quest, guid = key
        was = old.get(key)
        moved = _next(was, status.get(key), key in rewarded, now)
        if moved is None:
            # names[guid] cannot miss: _index keeps only the questers' rows.
            if was is not None and was.character_name != names[guid]:
                out.append(replace(was, character_name=names[guid]))
            continue
        state, first, finished, reason = moved
        out.append(Entry(quest, guid, names[guid], state, first, finished, reason))
    return out


# --- what the endpoints read off it ------------------------------------------

# Which state a quest shows when several questers tried it: the best news
# first. A quest nobody tried is NOT_REACHED.
NOT_REACHED = "not_reached"
STATUS_ORDER = (COMPLETED, BROKEN, TAKEN, ABANDONED, NOT_REACHED)


def quest_status(states) -> str:
    """The one status of a quest off its attempts' states."""
    found = set(states or ())
    for state in STATUS_ORDER:
        if state in found:
            return state
    return NOT_REACHED
