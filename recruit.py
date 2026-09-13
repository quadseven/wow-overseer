"""Who the family asks into its guild next, and when.

THE PURE HALF OF THE RECRUIT SWEEP (infra#3651). Rows in, one decision out.
No database, no clock, no logging - the same seam guildbank.py keeps, and for
the same reason: every branch below is a case somebody has to be able to write
a test for without a realm running.

WHAT THIS MODULE IS NOT ALLOWED TO DECIDE, and the line is worth stating
because it is easy to cross by accident. It does NOT judge candidates. Which
character is worth asking, and why, is answered by `RecruitVerdictFor` and
`RecruitShortlist` in mod-overseer's pure layer, against the guild's real
holes - a profession nobody holds, a service no class brings, a role nobody
can fill. That rule scores nobody and this module must not start. What this
module decides is only PACE and TURN: is there anybody online to carry the
row, has the shortlist gone stale, was this name already asked, and is it too
soon since the last invite.

WHY A TWO-STEP SWEEP AND NOT ONE. `shortlist` and `invite` are separate
commands executed by the worldserver, asynchronously, and the bridge only ever
writes a row - it cannot call into the module and wait. So a pass either asks
for a fresh shortlist or acts on the newest one that has already come back.
A pass never does both, which means the shortlist an invite is drawn from is
always one a person could have read first.

THE RATE, AND WHY IT IS NOT ONE A DAY. infra#3650 specified
`MAX_INVITES_PER_DAY = 1`, written when the target roster was 15 and the fear
was an unbounded loop against a two-thousand-bot population. Both halves of
that have changed. The guild is now recruiting toward a 40-man raid, so 35
seats at one a day is thirty-five days, which is not a pace, it is a refusal.
And the unbounded-loop fear does not apply to this shape: the terminal state
is `roster == target size`, mod-overseer's own `RecruitVerdictFor` refuses
`RosterFull` at it on the INVITE path, and this module refuses before ever
writing the row. A loop with a hard stop that both ends enforce is bounded by
construction rather than by a timer.

So the rate limit stays - it is still the thing that keeps a bad shortlist
from emptying the realm into the guild in one pass - but it is expressed as a
gap between invites, defaulting to five minutes. Thirty-five seats then fill
in about three hours, which is an evening, and every one of them is a row in
`overseer_command` that a person can read afterwards. See the issue comment on
infra#3650 for the argument in full; this is not a silent inversion of it.

WHAT COUNTS AS ALREADY ASKED, and why it is not a new table. infra#3650 wanted
a memory so a declined candidate is not re-offered every sweep. That memory
already exists: every invite this loop issues is an `overseer_command` row
with the name in `target_arg`, and reading it back is the same move bonds.py
makes for help-history rather than keeping a second tally. A candidate asked
inside the window is skipped whatever the answer was - an invite that was
refused will be refused again for the same reason, and an invite that worked
takes the candidate out of the next shortlist by itself, because they now have
a guild.
"""

from __future__ import annotations

from dataclasses import dataclass

# How many names to ask mod-overseer for. Comfortably more than one pass can
# use, so that a shortlist survives several invites before it goes stale and
# a few already-asked names near the top do not exhaust it. The module's own
# cap is 100.
SHORTLIST_SIZE = 20

# A shortlist older than this is re-asked rather than acted on. The world
# moves underneath it: a candidate joins somebody else's guild, levels out of
# the band, or is deleted, and an invite drawn from a stale list is refused by
# the module for a reason that looks like a bug in this loop.
SHORTLIST_FRESH_MINUTES = 30

# The gap between invites. See the module docstring for why this is not one a
# day.
MIN_MINUTES_BETWEEN_INVITES = 5

# How long a name stays "already asked". Long enough that a sweep does not
# re-offer somebody the same evening; short enough that a candidate whose real
# situation has changed is reachable again. infra#3650 chose 30 days for the
# same reasons and this keeps its number rather than inventing a second one.
ASKED_MEMORY_DAYS = 30


@dataclass(frozen=True)
class RecruitAction:
    """One thing to do, or one reason nothing is being done.

    `reason` IS ALWAYS SET, on an action and on a refusal alike. A sweep that
    goes by with no recruit has to say which of the five reasons it was -
    nobody online, roster full, no shortlist yet, nobody left to ask, too soon
    - because infra#3651's whole complaint about the manual path is that a
    silent no-op is indistinguishable from a broken one.
    """

    verb: str  # 'shortlist', 'invite', or 'wait'
    actor: str  # the guild member who carries the row; '' when waiting
    command: str  # what goes in overseer_command.command
    target_arg: str  # the character to invite; '' otherwise
    reason: str


def _wait(reason: str) -> RecruitAction:
    return RecruitAction(verb="wait", actor="", command="", target_arg="", reason=reason)


def plan_recruit(
    *,
    actors: list,
    shortlist: list,
    shortlist_age_minutes: float | None,
    asked: set,
    minutes_since_last_invite: float | None,
    member_count: int,
    target_size: int,
) -> RecruitAction:
    """The one thing this sweep should do.

    `actors`          guild members online now and able to carry a row. Only
                      the ACTING character has to be online - mod-overseer's
                      invite is `Guild::AddMember`, not the invite packet, so
                      the candidate may be offline and cannot decline.
    `shortlist`       names off the newest delivered shortlist, in the order
                      the module ranked them. Empty when the newest shortlist
                      found nobody.
    `shortlist_age_minutes`
                      how old that shortlist is, or None when there has never
                      been one.
    `asked`           names invited inside the memory window.
    `minutes_since_last_invite`
                      or None when none has ever been issued.
    `member_count`    the guild's size as the module last reported it.
    `target_size`     the size it is aiming at, as the module last reported it.

    THE ORDER OF THE GATES IS THE DESIGN. Roster-full is asked before anything
    about candidates, because a full guild has no question to answer and a
    sweep that shortlisted first would keep asking the world for names it can
    never use.
    """
    if not actors:
        return _wait("no guild member is online to carry the row")

    # A target size of 0 means the module was configured with no size gate;
    # trust it rather than inventing a ceiling here. Two places deciding when
    # the roster is full is exactly one place too many.
    if target_size and member_count >= target_size:
        return _wait(f"the roster is at its target size ({member_count} of {target_size})")

    actor = sorted(actors)[0]

    if shortlist_age_minutes is None:
        return RecruitAction(
            verb="shortlist",
            actor=actor,
            command=f"shortlist {SHORTLIST_SIZE}",
            target_arg="",
            reason="no shortlist has been asked for yet",
        )

    if shortlist_age_minutes > SHORTLIST_FRESH_MINUTES:
        return RecruitAction(
            verb="shortlist",
            actor=actor,
            command=f"shortlist {SHORTLIST_SIZE}",
            target_arg="",
            reason=(
                f"the last shortlist is {shortlist_age_minutes:.0f} minutes old, "
                f"past the {SHORTLIST_FRESH_MINUTES} it stays good for"
            ),
        )

    if not shortlist:
        return _wait(
            "the last shortlist found nobody - the band or the target size is "
            "refusing every candidate, which is a policy question and not a "
            "fault in this loop"
        )

    # THE RATE LIMIT IS ASKED AFTER THE SHORTLIST IS KNOWN TO BE USABLE, so
    # that a pass held back by the clock still says "too soon" rather than
    # hiding behind an older reason. It is asked BEFORE the pick so that a
    # held-back pass does not spend the shortlist.
    if (
        minutes_since_last_invite is not None
        and minutes_since_last_invite < MIN_MINUTES_BETWEEN_INVITES
    ):
        return _wait(
            f"the last invite was {minutes_since_last_invite:.0f} minutes ago, "
            f"and invites are held to one every {MIN_MINUTES_BETWEEN_INVITES}"
        )

    for name in shortlist:
        if name in asked:
            continue
        return RecruitAction(
            verb="invite",
            actor=actor,
            # The name goes in BOTH. `target_arg` is what mod-overseer reads
            # (DoGuild refuses an empty one outright); the command text carries
            # it too so that the command log reads as a sentence rather than as
            # a bare verb, and so infra#3650's `command LIKE 'invite %'` query
            # matches exactly as that issue wrote it. ParseGuildRequest ignores
            # what follows the verb on purpose - see its own comment.
            command=f"invite {name}",
            target_arg=name,
            reason=f"top of the shortlist and not asked in the last {ASKED_MEMORY_DAYS} days",
        )

    return _wait(
        f"every one of the {len(shortlist)} shortlisted names was already asked "
        f"inside {ASKED_MEMORY_DAYS} days"
    )


def names_from_shortlist(result: dict) -> list:
    """The shortlisted names, in rank order, out of a `guild shortlist` result.

    TOLERANT ON PURPOSE, and it fails toward doing nothing. This reads JSON
    written by another process and parsed by a caller; a shape that is not what
    is expected means the module answered something this loop does not
    understand, and the safe reading of that is "no candidates" rather than a
    traceback that takes the whole sweep down. The same rule guildbank.py's
    plan_deposits keeps for a stale or absent read.
    """
    picks = result.get("shortlist") if isinstance(result, dict) else None
    if not isinstance(picks, list):
        return []
    names = []
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        name = pick.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def roster_from_shortlist(result: dict) -> tuple:
    """(members, target_size) as the module last reported them, or (0, 0).

    READ OFF THE MODULE'S ANSWER RATHER THAN COUNTED HERE. `target_size` is
    configuration the worldserver holds and this process does not; counting
    `guild_member` rows on this side would give a member count that could
    disagree with the one the invite gate actually uses, and the disagreement
    would only show up as invites that are refused `RosterFull` by a loop that
    thought there were seats left.
    """
    if not isinstance(result, dict):
        return (0, 0)
    members = result.get("members")
    target = result.get("target_size")
    return (
        members if isinstance(members, int) else 0,
        target if isinstance(target, int) else 0,
    )
