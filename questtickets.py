"""Each broken quest becomes a ticket under the questers epic (#926).

WHY THIS EXISTS. The quest ledger (questledger.py) records a broken quest
with a reason, and the Quests page shows it, but a list of hundreds is read
by nobody. A broken quest gets fixed when it is a ticket the factory picks
up, so this pass files one.

THE PASS (`run`), once a day as a scheduled job beside the realm roller:

  1. Every quest whose status off the ledger is broken (questledger.
     quest_status: no quester has completed it) and that has no row in
     overseer_quest_ticket is due, lowest id first.
  2. An issue under the epic that already carries a quest's marker (`marker`)
     is recorded for it and not filed again: an issue opened by a run whose
     database write then failed.
  3. At most `limit` of the rest are filed: one issue each, with the quest's
     id, title, zone and level, every quester that broke it and their party,
     the ledger's reason, the objective counts the log last held, and a link
     to the quest on the Quests page. Labelled `LABELS`, and attached to the
     epic as a sub-issue.

A QUEST IS FILED ONCE, EVER. overseer_quest_ticket is keyed by the quest, so
a second quester breaking it, or the ticket being closed, files nothing.
Reopening a closed ticket is the brain's call, not this pass's.

THE ORDER OF THE WRITES. The issue is opened, then recorded, then attached
to the epic, and the attach is tried even when the record fails. So a failed
record leaves an issue under the epic with its marker, which step 2 records
next time; only a failed record AND a failed attach can file a quest twice.

The GitHub side is realmroller_act's `GitHub` and `AppToken` (stdlib only,
already in the image), asking for issues and nothing else.
"""

from __future__ import annotations

import logging
import os
import re

import questcatalogue
import questledger
import realmroller_act as act

log = logging.getLogger("questtickets")

LABELS = ("loom:ticket", "loom:queued")
# Filed per run at most. A ledger that suddenly holds hundreds of broken
# quests is more likely a fault in the ledger than hundreds of broken quests,
# and a day's wait for the rest costs nothing.
LIMIT = 20
TOKEN_PERMISSIONS = {"issues": "write"}

# Every row of every quest some quester broke: the other rows decide whether
# the quest is still broken (another quester completed it) or not.
LEDGER_SQL = (
    "SELECT quest, guid, character_name, state, reason FROM overseer_quest_ledger "
    "WHERE quest IN (SELECT quest FROM overseer_quest_ledger WHERE state = 'broken')"
)
# What the log last held for each attempt, beside what the quest asks for.
OBJECTIVES_SQL = (
    "SELECT q.guid, q.quest, "
    "q.mobcount1, q.mobcount2, q.mobcount3, q.mobcount4, "
    "q.itemcount1, q.itemcount2, q.itemcount3, q.itemcount4, q.itemcount5, "
    "q.itemcount6, "
    "t.RequiredNpcOrGoCount1 AS need_mob1, t.RequiredNpcOrGoCount2 AS need_mob2, "
    "t.RequiredNpcOrGoCount3 AS need_mob3, t.RequiredNpcOrGoCount4 AS need_mob4, "
    "t.RequiredItemCount1 AS need_item1, t.RequiredItemCount2 AS need_item2, "
    "t.RequiredItemCount3 AS need_item3, t.RequiredItemCount4 AS need_item4, "
    "t.RequiredItemCount5 AS need_item5, t.RequiredItemCount6 AS need_item6 "
    "FROM character_queststatus q JOIN acore_world.quest_template t ON t.ID = q.quest "
    "WHERE q.quest IN ({quests}) AND q.guid IN ({guids})"
)

_MARKER = re.compile(r"<!-- quest-ticket:(\d+) -->")


def marker(quest: int) -> str:
    """The line in a ticket's body that names its quest to a later run."""
    return "<!-- quest-ticket:%d -->" % quest


def marked(body) -> int | None:
    m = _MARKER.search(body or "")
    return int(m.group(1)) if m else None


def due(ledger_rows, filed) -> list:
    """The broken quests with no ticket, by id. `filed` holds quest ids."""
    states: dict = {}
    for row in ledger_rows or ():
        states.setdefault(int(row["quest"]), []).append(str(row.get("state") or ""))
    return sorted(
        quest
        for quest, seen in states.items()
        if quest not in filed and questledger.quest_status(seen) == questledger.BROKEN
    )


# --- the issue ---------------------------------------------------------------


def _plain(text) -> str:
    """Realm text made safe for a public issue: an `@` never mentions anyone."""
    return str(text or "").replace("@", "@ ")


def objectives(row) -> str:
    """The counts the log last held, as `have/need` per objective."""
    if row is None:
        return "not in the log any more, so no counts"

    def counts(have, need, n):
        out = []
        for i in range(1, n + 1):
            wanted = int(row.get("%s%d" % (need, i)) or 0)
            if wanted > 0:
                out.append("%d/%d" % (int(row.get("%s%d" % (have, i)) or 0), wanted))
        return ", ".join(out)

    parts = []
    kills = counts("mobcount", "need_mob", 4)
    if kills:
        parts.append("kills or uses " + kills)
    items = counts("itemcount", "need_item", 6)
    if items:
        parts.append("items " + items)
    return "; ".join(parts) or "no objective to count"


def _zone(quest) -> str:
    if quest is None:
        return "zone unknown"
    return quest.zone_name or "no zone (a class, profession or holiday quest)"


def _level(quest) -> str:
    if quest is None:
        return "level unknown"
    if quest.level < 0:
        return "level scales with the player"
    return "level %d" % quest.level


def title(quest_id: int, quest) -> str:
    name = _plain(quest.title) if quest else "Quest %d" % quest_id
    return 'Quest %d "%s" cannot be finished (%s, %s)' % (
        quest_id,
        name,
        _zone(quest),
        _level(quest),
    )


def _quester(row, counts) -> str:
    name = str(row.get("character_name") or "")
    guild = questledger.guild_of(name)
    party = questledger.QUESTERS.get(guild, ())
    who = (
        "**%s**, of the %s questers (%s)" % (name, guild, ", ".join(party))
        if guild
        else ("**%s**" % (name or "an unnamed quester"))
    )
    return "- %s. Reason: %s. Objectives when last seen: %s." % (
        _plain(who),
        _plain(row.get("reason")) or "none recorded",
        objectives(counts),
    )


def body(
    quest_id: int, quest, attempts, objective_rows, site_url: str, epic: int
) -> str:
    """The issue body. `attempts` are this quest's broken ledger rows;
    `objective_rows` maps (quest, guid) to its OBJECTIVES_SQL row."""
    page = "%s/#/quests/%d" % (site_url.rstrip("/"), quest_id)
    level = _level(quest)
    if quest is not None and quest.level >= 0 and quest.min_level:
        level += ", taken from level %d" % quest.min_level
    lines = [
        "## Why",
        "",
        "A quester could not finish this quest naturally, and the quest ledger "
        "recorded it broken. Until it is fixed, no quester can prove it.",
        "",
        "## What",
        "",
        "- Quest: %d, %s ([on the Quests page](%s))"
        % (quest_id, _plain(quest.title) if quest else "not in the catalogue", page),
        "- Zone: %s" % _zone(quest),
        "- Level: %s" % level,
        "",
        "Who broke it:",
        "",
    ]
    for row in attempts:
        lines.append(_quester(row, objective_rows.get((quest_id, int(row["guid"])))))
    lines += [
        "",
        "Find why the quest cannot be finished by playing it, and fix that.",
        "",
        "## Acceptance criteria",
        "",
        "- [ ] A quester takes and completes quest %d naturally, and the Quests "
        "page reads it completed" % quest_id,
        "",
        "## Size",
        "",
        "S",
        "",
        "## Out of scope",
        "",
        "- Any other broken quest: each has its own ticket",
        "",
        "Part of #%d" % epic,
        "",
        marker(quest_id),
    ]
    return "\n".join(lines) + "\n"


# --- the pass ----------------------------------------------------------------


def _adopt(db, tracker, epic: int, waiting: list) -> list:
    """Record each issue under the epic that already carries a waiting quest's
    marker, and drop that quest from `waiting`; the notes to log."""
    notes = []
    for child in tracker.children(epic):
        quest = marked(child.get("body"))
        if quest in waiting:
            db.write(
                questledger.TICKET_WRITE_SQL,
                (quest, int(child["number"]), str(child.get("html_url") or "")),
            )
            waiting.remove(quest)
            notes.append("quest %d: already filed as #%d" % (quest, child["number"]))
    return notes


def _counts(db, waiting: list, broken: list) -> dict:
    """(quest, guid) -> what the log last held, for the broken attempts.
    Both lists are non-empty: every waiting quest has a broken row."""
    guids = sorted({int(r["guid"]) for r in broken})
    rows = db.rows(
        OBJECTIVES_SQL.format(
            quests=questledger.holes(len(waiting)),
            guids=questledger.holes(len(guids)),
        ),
        tuple(waiting) + tuple(guids),
    )
    return {(int(r["quest"]), int(r["guid"])): r for r in rows}


def _file(db, tracker, epic: int, quest_id: int, title_text: str, text: str) -> int:
    """Open one quest's issue, record it and attach it; its number."""
    issue = tracker.open(title_text, text, list(LABELS))
    try:
        db.write(
            questledger.TICKET_WRITE_SQL,
            (quest_id, int(issue["number"]), str(issue.get("html_url") or "")),
        )
    finally:
        # Not a swallow: a failed record still raises once the attach is done
        # (test_a_failed_record_still_attaches_so_the_next_run_does_not_refile).
        # The attach runs anyway so the next run's _adopt finds the issue under
        # the epic and records it instead of filing the quest again.
        tracker.attach(epic, issue["id"])
    return int(issue["number"])


def _file_all(db, tracker, site_url: str, epic: int, ledger, waiting: list) -> list:
    """File each waiting quest, which `run` has trimmed to the day's limit;
    the notes to log."""
    catalogue = {q.id: q for q in questcatalogue.load(lambda sql: db.rows(sql, ()))}
    broken = [
        r
        for r in ledger
        if int(r["quest"]) in waiting and r.get("state") == questledger.BROKEN
    ]
    counts = _counts(db, waiting, broken)
    notes = []
    for quest_id in waiting:
        quest = catalogue.get(quest_id)
        attempts = sorted(
            (r for r in broken if int(r["quest"]) == quest_id),
            key=lambda r: str(r.get("character_name") or ""),
        )
        number = _file(
            db,
            tracker,
            epic,
            quest_id,
            title(quest_id, quest),
            body(quest_id, quest, attempts, counts, site_url, epic),
        )
        notes.append("quest %d: filed #%d" % (quest_id, number))
    return notes


def run(db, tracker, site_url: str, epic: int, limit: int = LIMIT) -> list:
    """File what is due; the notes to log.

    `db` has rows(sql, params) and write(sql, params); `tracker` has
    children(epic), open(title, body, labels) and attach(epic, issue_id).
    """
    db.write(questledger.TICKET_TABLE_SQL, ())
    filed = {int(r["quest"]) for r in db.rows(questledger.TICKETS_SQL, ())}
    ledger = db.rows(LEDGER_SQL, ())
    waiting = due(ledger, filed)
    if not waiting:
        return ["no broken quest is waiting for a ticket"]
    notes = _adopt(db, tracker, epic, waiting)
    if len(waiting) > limit:
        notes.append("%d broken quest(s) wait for tomorrow" % (len(waiting) - limit))
        waiting = waiting[:limit]
    if not waiting:
        return notes
    return notes + _file_all(db, tracker, site_url, epic, ledger, waiting)


# --- the adapters -------------------------------------------------------------


class Tracker:
    """The epic's issues through realmroller_act's GitHub client."""

    def __init__(self, gh: act.GitHub):
        self.gh = gh

    def children(self, epic: int) -> list:
        return self.gh.pages("/issues/%d/sub_issues" % epic)

    def open(self, title: str, body: str, labels: list) -> dict:
        return self.gh.call(
            "POST",
            "/issues",
            {"title": title, "body": body, "labels": labels},
            ok=(201,),
        ).json()

    def attach(self, epic: int, issue_id: int) -> None:
        self.gh.call(
            "POST",
            "/issues/%d/sub_issues" % epic,
            {"sub_issue_id": issue_id},
            ok=(201,),
        )


class Realm:
    """rows() and write() over one autocommit connection."""

    def __init__(self, conn):
        self.conn = conn

    def rows(self, sql: str, params=()) -> list:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def write(self, sql: str, params=()) -> None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)


def main(argv=None) -> int:
    """One pass, as the daily scheduled job runs it.

        python3 questtickets.py --repo OWNER/NAME --epic N --site-url URL \\
            --app-dir DIR

    `--app-dir` is the mounted GitHub App Secret (files `app_id`,
    `installation_id`, `private_key`), as for the realm roller. The realm is
    reached as the bridge reaches it: MYSQL_HOST and MYSQL_ROOT_PASSWORD.
    """
    import argparse
    import sys

    import pymysql

    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--repo", required=True, help="the repo to file in, OWNER/NAME")
    ap.add_argument("--epic", required=True, type=int, help="the questers epic")
    ap.add_argument("--site-url", required=True, help="the overseer site's base URL")
    ap.add_argument("--app-dir", required=True, help="the mounted GitHub App Secret")
    ap.add_argument("--limit", type=int, default=LIMIT, help="issues per run at most")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    token = act.AppToken(
        act._read(os.path.join(args.app_dir, "app_id")),
        act._read(os.path.join(args.app_dir, "installation_id")),
        os.path.join(args.app_dir, "private_key"),
        args.repo,
        permissions=TOKEN_PERMISSIONS,
    )
    conn = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        user="root",
        password=os.environ["MYSQL_ROOT_PASSWORD"],
        database="acore_characters",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=30,
        write_timeout=10,
    )
    try:
        notes = run(
            Realm(conn),
            Tracker(act.GitHub(args.repo, token)),
            args.site_url,
            args.epic,
            args.limit,
        )
    except (act.ApiError, pymysql.err.MySQLError, OSError) as exc:
        print("quest tickets: stopped: %s" % exc, file=sys.stderr)
        return 1
    finally:
        conn.close()
    for line in notes:
        print("quest tickets: %s" % line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
