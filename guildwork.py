"""The guild's maintenance members, given a job (#234): guild dues by post.

THE LABEL HAD NO WORK BEHIND IT. `raidlineup.build_lineup` puts ten members of
each family guild on "maintenance", and until this module that was a word on
the Lineup page and nothing else. They are ordinary random playerbots: not on
`overseer_roster`, so the roster's `travel_npc` aim never reaches them, and
unmastered, so mod-playerbots' own `go` and `gb` chat actions do nothing for
them. What does reach them is the module's `walk-to-mailbox` row
(quadseven/mod-overseer#570), which walks a guild bot off the roster to the
nearest mailbox on its map, and the `send` mail verb, which posts gold from
there. Those two are the whole of this slice's reach, and both are things a
player does.

THE JOB. Once a day each maintenance member posts a share of the gold above
its float to the guild master. From there the family's existing passes carry
it: the mail pass takes money letters first (`mailrun.py`), and the guild-bank
pass deposits a family member's gold above its float into the vault
(`guildbank.py`), buying the guild's first tab before anything else when it has
none. A member cannot deposit into the vault itself: a vault is in a capital
city and no verb walks a bot off the roster to one.

WHY BY POST AND NOT BY GIVE. `kind='give'` moves an item across a continent in
one database write; nothing here uses it. A letter goes from a mailbox the bot
walked to, which is what a guildmate would do.

PURE MODULE: rows in, a plan and sentences out. No MySQL and no clock; the
bridge reads the facts and passes them in, and the page's sentences are
written here so a test can read them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import guildroute
import raidlineup
import raidroles

COPPER_PER_GOLD = 10_000

# The command log's `source` for a dues letter and for the walk that precedes
# it. Their OWN prefixes, not `guildroute`'s: the gear hand-over pass counts its
# daily walks by `guildwalk:%` and its letters by `guildroute:%`, and a dues
# walk counted there would spend the gear route's six walks a day.
SOURCE = "guilddues"
WALK_SOURCE = "guilddues-walk"

# The job's name on the page and in the log.
JOB = "guild dues"

# WHAT A MEMBER KEEPS. A hundred gold: a level 60 character's full repair and a
# trainer visit together sit well under it, so the member can still get out of
# trouble unaided. It is ten times the family's own float (`guildbank.
# FLOAT_COPPER`) because a random bot also buys its own food, ammunition and
# reagents and nobody here watches it do so.
FLOAT_COPPER = 100 * COPPER_PER_GOLD

# A QUARTER OF WHAT IS ABOVE THE FLOAT, and never more than 250 gold in one
# letter. A share rather than everything: the member's purse as the command
# log reads it lags the world by up to fifteen minutes (`PlayerSaveInterval`),
# so taking the whole surplus would post money a stale read only thinks is
# there. The cap keeps any one letter small enough that a wrong read costs
# little. Measured on dev (2026-09-23) the twenty members held 296 to 3,254
# gold, so most letters are at the cap.
SHARE_NUMERATOR, SHARE_DENOMINATOR = 1, 4
LETTER_CAP_COPPER = 250 * COPPER_PER_GOLD

# Below a gold, the walk and the thirty copper of postage are not worth it.
MIN_LETTER_COPPER = 1 * COPPER_PER_GOLD

# ONE LETTER PER MEMBER PER DAY, counted from the command log by the caller so
# a restart forgets nothing.
INTERVAL_HOURS = 24

# How many walks one guild starts in one pass. Two, so ten members are spread
# over a few passes rather than ten walks at once from one guild.
WALKS_PER_GUILD = 2

# The letter's subject. The client allows 64 characters.
SUBJECT = "Guild dues"

# What the page says a maintenance member does, before and after a letter.
_JOB_LINE = "posts a quarter of its gold above %dg to %s once a day"
_NOTHING_YET = "nothing posted yet"


def dues_for(money) -> int:
    """Copper to post from a purse of `money` copper; 0 when nothing is due.

    A missing, negative or unreadable purse posts nothing: a stale or absent
    read may suppress a letter, never manufacture one.
    """
    try:
        money = int(money)
    except (TypeError, ValueError):
        return 0
    spare = money - FLOAT_COPPER
    if spare <= 0:
        return 0
    share = spare * SHARE_NUMERATOR // SHARE_DENOMINATOR
    share = min(share, LETTER_CAP_COPPER)
    return share if share >= MIN_LETTER_COPPER else 0


def gold(copper) -> str:
    """Copper as the page and the log say it: whole gold, or copper under one."""
    copper = int(copper or 0)
    if copper >= COPPER_PER_GOLD:
        return "%dg" % (copper // COPPER_PER_GOLD)
    return "%dc" % copper


@dataclass(frozen=True)
class Member:
    """One maintenance member, as the bridge read it."""

    name: str
    guild: str
    money: int = 0
    online: bool = False


@dataclass(frozen=True)
class DuesRun:
    """One member walked to one mailbox to post one letter of dues."""

    holder: str
    taker: str
    guild: str
    copper: int
    aim: str
    yards: float
    cap: float = guildroute.MAIL_RUN_YARDS

    @property
    def command(self) -> str:
        """The letter, in `ParseMailRequest`'s grammar."""
        return "send money:%d subject:%s" % (int(self.copper), SUBJECT)

    @property
    def walk_command(self) -> str:
        """The module's walk row (#570) at the pass's cap: the gear route's own
        600 yards, or the far cap once the worldserver walks that far (#633)."""
        return guildroute.mailbox_walk_command(self.cap)

    @property
    def source(self) -> str:
        return "%s:%d" % (SOURCE, int(self.copper))

    @property
    def walk_source(self) -> str:
        return "%s:%d" % (WALK_SOURCE, int(self.copper))

    @property
    def said(self) -> str:
        return (
            "%s (%s) walks %d yards to the mailbox at %s to post %s of dues to %s"
            % (
                self.holder,
                self.guild,
                int(round(self.yards)),
                self.aim,
                gold(self.copper),
                self.taker,
            )
        )


@dataclass(frozen=True)
class DuesPlan:
    runs: tuple = ()
    notes: tuple = ()


def _not_due(member, taker, posted, eligible) -> str | None:
    """Why this member posts nothing this pass; "" to say nothing; None if due.

    The empty string is a quiet skip: a member who already posted inside
    INTERVAL_HOURS is the normal case and is not worth a log line.
    """
    name = str(member.name)
    if name not in eligible:
        return (
            "%s posts no dues: it has not been reset to level 1, so its "
            "gold was handed to it, and only earned gold is contributed" % name
        )
    if not taker:
        return "%s: %s has no guild master to post to" % (name, member.guild)
    if taker == name:
        return "%s is the guild master and posts no dues" % name
    if name in posted:
        return ""
    if not member.online:
        return "%s is offline" % name
    if not dues_for(member.money):
        return "%s carries %s, not enough above the %s float to post" % (
            name,
            gold(member.money),
            gold(FLOAT_COPPER),
        )
    return None


def _cannot_walk(name, walker, busy, max_yards) -> str:
    """Why this due member is not walked to a mailbox now, "" when it can be."""
    if name in busy:
        return "%s is already walking to a mailbox" % name
    why = guildroute.cannot_walk(walker, name, max_yards)
    if not why and not walker.by_row:
        why = "%s cannot be walked by the mailbox walk row" % name
    return "%s waits: %s" % (name, why) if why else ""


def plan_dues(
    members,
    masters,
    walkers,
    posted,
    busy,
    per_guild=WALKS_PER_GUILD,
    max_yards=guildroute.MAIL_RUN_YARDS,
    *,
    eligible,
) -> DuesPlan:
    """Which maintenance members start a dues walk this pass, and why not.

    `members` are Member rows, in the lineup's order. `masters` maps a guild
    name to its guild master's name. `walkers` maps a member name to a
    `guildroute.Walker`. `posted` holds the members that already posted, or
    were already asked to, inside INTERVAL_HOURS. `busy` holds members already
    walking to a mailbox for any pass. One note per member left out.

    NATURALLY EARNED ONLY (the operator, 2026-09-24). `eligible` names the
    members whose gold was earned (`natural.contributors`); nobody else posts.
    It has no default on purpose: a caller that forgets it must fail, not
    post the factory's gold.

    THE NEAREST FIRST (#633). Inside a guild the members nearest a mailbox are
    asked first, so the guild's two walks a pass go to the shortest ones and a
    member a continent away waits for a pass nobody nearer needs.
    """
    runs, notes = [], []
    started = {}
    busy = {str(n) for n in busy or ()}
    posted = {str(n) for n in posted or ()}
    eligible = {str(n) for n in eligible or ()}
    for member in _nearest_first(members, walkers):
        name = str(member.name)
        taker = str((masters or {}).get(member.guild) or "")
        walker = (walkers or {}).get(name)
        why = _not_due(member, taker, posted, eligible)
        due = why is None
        if due:
            why = _cannot_walk(name, walker, busy, max_yards)
        if due and not why and started.get(member.guild, 0) >= int(per_guild):
            why = "%s waits: %d dues walks per guild per pass" % (name, int(per_guild))
        if why:
            notes.append(why)
        if not due or why:
            continue
        started[member.guild] = started.get(member.guild, 0) + 1
        runs.append(
            DuesRun(
                holder=name,
                taker=taker,
                guild=str(member.guild),
                copper=dues_for(member.money),
                aim=walker.aim,
                yards=float(walker.yards),
                cap=float(max_yards),
            )
        )
        busy.add(name)
    return DuesPlan(runs=tuple(runs), notes=tuple(notes))


def _nearest_first(members, walkers) -> list:
    """The members in the order a dues pass asks them: nearest a mailbox first.

    Stable, so members at the same distance, and members whose distance is not
    known, keep the lineup's order; an unknown distance goes last.
    """
    members = list(members or ())

    def key(pair):
        index, member = pair
        walker = (walkers or {}).get(str(member.name))
        yards = getattr(walker, "yards", None)
        return (yards is None, float(yards or 0.0), index)

    return [m for _, m in sorted(enumerate(members), key=key)]


# ---------------------------------------------------------------------------
# WHAT THE PAGE SAYS: each maintenance member's job and what it has posted.


def _money_of(row) -> int:
    """Copper a sent dues letter carried, from its result, else its command."""
    result = row.get("result")
    try:
        body = json.loads(result) if isinstance(result, str) else (result or {})
    except (TypeError, ValueError):
        body = {}
    mail = body.get("mail") if isinstance(body, dict) else None
    if isinstance(mail, dict):
        try:
            return max(0, int(mail.get("money") or 0))
        except (TypeError, ValueError):
            pass
    for word in str(row.get("command") or "").split():
        if word.startswith("money:") and word[6:].isdigit():
            return int(word[6:])
    return 0


def _sent(row) -> bool:
    """A letter the world says it posted: status delivered, outcome sent."""
    if str(row.get("status") or "") != "delivered":
        return False
    result = row.get("result")
    try:
        body = json.loads(result) if isinstance(result, str) else (result or {})
    except (TypeError, ValueError):
        return False
    return isinstance(body, dict) and body.get("outcome") == "sent"


def contributions(rows) -> dict:
    """name -> {"letters", "copper", "last_refusal"} from dues letter rows.

    `rows` are the dues `send` rows the command log holds (target_name,
    command, status, detail, result), oldest first. Only a letter the world
    reports as sent counts. A refusal is kept as the last one seen, so the page
    can say why nothing has arrived.
    """
    out = {}
    for row in rows or ():
        name = str(row.get("target_name") or "")
        if not name:
            continue
        entry = out.setdefault(name, {"letters": 0, "copper": 0, "last_refusal": ""})
        if _sent(row):
            entry["letters"] += 1
            entry["copper"] += _money_of(row)
            entry["last_refusal"] = ""
        elif str(row.get("status") or "") == "error":
            entry["last_refusal"] = str(row.get("detail") or "refused")
    return out


def work_line(name, taker, contributed) -> str:
    """One sentence for a maintenance member: its job and what it has posted."""
    job = _JOB_LINE % (FLOAT_COPPER // COPPER_PER_GOLD, taker or "the guild master")
    entry = (contributed or {}).get(name) or {}
    letters = int(entry.get("letters") or 0)
    if letters:
        done = "posted %s in %d letter%s" % (
            gold(entry.get("copper")),
            letters,
            "" if letters == 1 else "s",
        )
    else:
        done = _NOTHING_YET
    if entry.get("last_refusal"):
        done += "; last refused: %s" % entry["last_refusal"]
    return "%s: %s - %s" % (JOB, job, done)


def attach_work(lineup, taker, contributed) -> dict:
    """The lineup with `job` and `work` on each maintenance member, and totals.

    `lineup` is one guild's `raidlineup.build_lineup` result, changed in place
    and returned. `contributed` is `contributions(...)` for this guild.
    """
    letters = copper = 0
    for member in lineup.get("maintenance") or ():
        name = member.get("name")
        member["job"] = JOB
        member["work"] = work_line(name, taker, contributed)
        entry = (contributed or {}).get(name) or {}
        letters += int(entry.get("letters") or 0)
        copper += int(entry.get("copper") or 0)
    lineup["dues"] = {
        "taker": taker or "",
        "letters": letters,
        "copper": copper,
        "said": "maintenance dues posted to %s: %s in %d letter%s"
        % (
            taker or "the guild master",
            gold(copper),
            letters,
            "" if letters == 1 else "s",
        ),
    }
    return lineup


def _by_guild(rows) -> tuple:
    """({guild: [rows]}, {guild: master}) out of the bridge's guild rows."""
    guilds, masters = {}, {}
    for row in rows or ():
        guild = str(row.get("guild_name") or "")
        if not guild or not row.get("name"):
            continue
        guilds.setdefault(guild, []).append(row)
        if row.get("master"):
            masters[guild] = str(row["master"])
    return guilds, masters


def _member_from(guild, row) -> Member:
    """One Member from one guild row; an unreadable purse reads as empty."""
    try:
        money = int(row.get("money") or 0)
    except (TypeError, ValueError):
        money = 0
    try:
        online = bool(int(row.get("online") or 0))
    except (TypeError, ValueError):
        online = False
    return Member(name=str(row.get("name")), guild=guild, money=money, online=online)


def maintenance_from_rows(rows, family_names):
    """(members, masters) out of the guild rows the bridge read.

    `rows` carry guild_name, name, class_id, level, money, online and master
    (the guild master's name), one per member of every guild the family is
    in. The maintenance members are exactly the ones the Lineup page shows:
    `raidlineup.build_lineup` over the same members, with the family placed
    first. `members` keeps the lineup's order; `masters` maps a guild name to
    its guild master.
    """
    family = frozenset(str(n) for n in family_names or ())
    guilds, masters = _by_guild(rows)
    members = []
    for guild in sorted(guilds):
        by_name = {str(r.get("name")): r for r in guilds[guild]}
        lineup = raidlineup.build_lineup(
            [
                {
                    "name": name,
                    "class_id": r.get("class_id"),
                    "level": r.get("level"),
                    raidroles.KEY: r.get(raidroles.KEY),
                }
                for name, r in by_name.items()
            ],
            guaranteed=[name for name in by_name if name in family],
        )
        members.extend(
            _member_from(guild, by_name[placed["name"]])
            for placed in lineup["maintenance"]
        )
    return members, masters
