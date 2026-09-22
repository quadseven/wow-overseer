"""Group targeting for the wow-overseer bridge: one order, many characters.

Pure resolution. A target expression plus a roster snapshot go in, and the
exact character names that will get overseer_command rows come out.
Nothing here touches Discord, MySQL or an LLM - bridge.py does that - which
is what makes the cap, the selection order and the muster arithmetic
provable in the stdlib-only test matrix.

Two rules shape everything below:

  * The fan-out happens at INSERT time, not at delivery time. mod-overseer
    stays a dumb loop that whispers one row to one character; widening the
    target is entirely the bridge's problem, so the game server never grows
    a notion of "a guild order" it would have to bound on its own.

  * The report is honest. Nobody is dropped silently: if the cap bites, the
    reply says how many stayed home, and the count it leads with is the
    number of rows that actually landed, never the number intended.

Epic infra#2597, ticket infra#2605.
"""

from __future__ import annotations

# Faction membership already lives in core (and map_core/panel already
# import it from there); redefining the race ids here is how two answers to
# "is this character Horde" start disagreeing.
from core import _ALLIANCE_RACES, _HORDE_RACES

# One Discord line must not queue an unbounded burst. mod-overseer drains
# COMMANDS_PER_POLL=20 rows every COMMAND_POLL_MS=2000 on the world-update
# thread, i.e. about ten orders a second, so 40 rows clear in roughly four
# seconds: a band visibly converges while a follow-up single whisper is
# still answered promptly. Live guilds run ~15 online members, so a guild
# order never reaches this cap in practice; @horde (~250 online) and
# @everyone (~500) do, and the muster report says who stayed home.
MAX_FANOUT_TARGETS = 40

GROUP_USAGE = (
    'Group orders: @guild "<name>" <order>, @recruits <order>, @horde <order>, '
    "@alliance <order>, @everyone <order>"
)

_FACTIONS = {"horde": _HORDE_RACES, "alliance": _ALLIANCE_RACES}

# "@everyone" pings an entire Discord server; "@all" is the same muster
# without the siren, so both words mean the whole world.
_WHOLE_WORLD = frozenset({"everyone", "all"})

# THE GUILD MINUS THE FAMILY, and it is a separate band because ordering the
# two together is a mistake the grammar could not previously express.
#
# `@guild "<ours>" <order>` resolves to every online member of the family's
# own guild, which is the family AND the recruits. That is right for a guild
# announcement and wrong for every strategy order, because the family's
# non-combat strategies are not the operator's to set by hand: the life pass
# re-derives them from goals.life_strategies on its own cycle (who leads, who
# is aimed at a quest, who is mid-errand) and writes them back. An order typed
# at the whole guild therefore lands on five characters that will contradict
# it within one cycle, and in the meantime it has taken the family off task -
# a second writer answering a question that already has one, which is the
# failure infra#3423 is named for.
#
# The recruits have no such writer. Nothing in this directory censuses them:
# every drive reads `overseer_roster`, which holds the family's five rows and
# deliberately will not grow (mod-overseer#464 argues why - KeepRosterAttended
# evicts a roster character with no game client, and the recruits have none).
# So this band is the one place an order aimed at them is the ONLY order they
# have, and it is safe to give exactly because the family is not in it.
#
# WHAT THIS IS NOT. It is not a new way to command a recruit - there was never
# a missing one. `kind='bot'` rows are delivered by mod-overseer as a whisper
# from the character TO ITSELF, and PlayerbotSecurity::CheckLevelFor
# short-circuits on `from == bot` before the master is consulted at all
# (PlayerbotSecurity.cpp:178, and mod_overseer.cpp says so in its own words:
# "a bot that now has a master is no more and no less commandable than
# before"). A recruit with no master, no group and no roster row takes the
# full native command vocabulary today, and was measured doing so. The only
# thing missing was a way to SAY "the recruits" without also saying "the
# family". Ticket infra#3764.
RECRUITS = "recruits"

# The words that stop being character names. WoW would happily allow a
# character called "Horde", so this is a deliberate trade: five reserved
# words buy an unambiguous group grammar.
GROUP_HEADS = frozenset({"guild", RECRUITS}) | _WHOLE_WORLD | frozenset(_FACTIONS)


def split_group_order(head: str, rest: str) -> tuple[str, str] | None:
    """Split a "@<head> <rest>" line into (expression, command).

    Returns None when `head` is an ordinary character name, which is what
    keeps single-character targeting exactly what it was: core.py only
    takes the group path when this function says the line is a group one.

    A missing or unparseable guild name yields the bare expression "guild"
    with an empty command, so the caller asks for one instead of guessing.
    """
    word = head.lower()
    if word not in GROUP_HEADS:
        return None
    if word != "guild":
        return word, rest.strip()
    name, command = _split_guild_name(rest)
    return (f"guild {name}".strip(), command)


def _split_guild_name(rest: str) -> tuple[str, str]:
    """Separate a guild name from the order that follows it.

    Guild names carry spaces on this realm ("Rangers of Vengeance"), so a
    quoted name is the only unambiguous way to say where the name stops.
    Unquoted, the first word is the name: right for the single-word guilds,
    and for the rest it produces a "no such guild" reply carrying the
    quoting hint - never a correctly-sized order aimed at the wrong band.
    """
    rest = rest.strip()
    if rest[:1] in ('"', "'"):
        quote = rest[0]
        closing = rest.find(quote, 1)
        if closing == -1:
            # An unterminated quote means the name has no end; refusing to
            # guess where it stops is cheaper than mustering the wrong guild.
            return "", ""
        return rest[1:closing].strip(), rest[closing + 1 :].strip()
    name, _, command = rest.partition(" ")
    return name.strip(), command.strip()


def describe_expression(expression: str) -> str:
    """Plain-English name for a group, carrying no cap bookkeeping.

    Used both for the muster report's subject and for the thought each
    participant keeps, so the channel and the characters name the same band.
    """
    word, _, argument = expression.strip().partition(" ")
    word = word.lower()
    if word == "guild":
        return f"the guild {argument.strip()}".strip()
    if word == RECRUITS:
        # No guild name in the phrase even though the band is a guild's. The
        # expression carries no argument to put there - which guild is "ours"
        # is read off the family's own rows at resolve time, not typed - and
        # inventing a name here would be a second answer to that question.
        return "the guild's recruits"
    if word in _FACTIONS:
        return f"the {word.capitalize()}"
    if word in _WHOLE_WORLD:
        return "everyone in the world"
    return expression


def resolve_targets(
    expression: str,
    roster: list[dict],
    guild_names: dict[int, str] | None = None,
    family: list[str] | None = None,
) -> tuple[list[str], str]:
    """Resolve a group expression against a live roster snapshot.

    `roster` is overseer_snapshot-shaped rows the caller has already
    filtered for freshness. `guild_names` maps guildid -> guild name, read
    from acore_characters.guild; the name typed in Discord is compared
    against those values in Python and never becomes part of a query.

    `family` is the enabled `overseer_roster` names, and ONLY the "recruits"
    expression reads it. Passed in rather than derived here for the reason
    every other input to this module is passed in: resolution is pure, and a
    module that fetched its own roster could not be tested without a realm.
    It defaults to None rather than to the empty list so that "recruits"
    refuses when the caller did not supply one - an empty family would
    silently resolve to the WHOLE guild, which is the exact band this
    expression exists to avoid ordering.

    Returns (names, reason).

      * names non-empty: `reason` is the phrase naming who answered, with
        the cap arithmetic appended when the cap bit.
      * names empty: `reason` is the plain-English refusal to send back to
        the channel.

    Selection is deterministic - highest level first, ties alphabetical,
    the same ordering core.format_roster uses to decide who is worth
    naming. The same message therefore always musters the same band, and
    when the cap bites it is the strongest characters that are kept.
    """
    word, _, argument = expression.strip().partition(" ")
    word = word.lower()

    # A character with no PlayerbotAI cannot be whispered to by
    # mod-overseer: a row for one is a guaranteed error row that would make
    # the muster count overstate what happened.
    commandable = [r for r in roster if r.get("is_bot")]

    if word in _WHOLE_WORLD:
        if not commandable:
            return [], "Nobody I can command is in the world right now."
        matched, who = commandable, describe_expression(word)
    elif word in _FACTIONS:
        races = _FACTIONS[word]
        matched = [r for r in commandable if r["race"] in races]
        who = describe_expression(word)
        if not matched:
            return [], f"Nobody answers for {who} right now."
    elif word == "guild":
        matched, who = _resolve_guild(argument.strip(), commandable, guild_names or {})
        if not matched:
            return [], who
    elif word == RECRUITS:
        matched, who = _resolve_recruits(commandable, guild_names or {}, family)
        if not matched:
            return [], who
    else:
        return [], f"'{expression}' is not a group I know. {GROUP_USAGE}"

    ordered = sorted(matched, key=lambda r: (-r["level"], r["name"]))
    called = [r["name"] for r in ordered[:MAX_FANOUT_TARGETS]]
    dropped = len(ordered) - len(called)
    if dropped:
        who = (
            f"{who} ({len(ordered)} online, {dropped} left behind - "
            f"the muster caps at {MAX_FANOUT_TARGETS})"
        )
    return called, who


def _resolve_guild(
    wanted: str, commandable: list[dict], guild_names: dict[int, str]
) -> tuple[list[dict], str]:
    """Guild members, or ([], refusal) - the second element doubles as the
    reason so the caller has one shape to hand back."""
    if not wanted:
        return [], f"Name the guild. {GROUP_USAGE}"
    # Matching is a lookup in a map the realm handed us, so a typed name can
    # only ever select an existing guild - it can never widen the match.
    # Sorted so a duplicated guild name resolves the same way every time.
    found = sorted(
        gid for gid, name in guild_names.items() if name.lower() == wanted.lower()
    )
    if not found:
        return [], (
            f"I know no guild called '{wanted}'. Multi-word names need quotes, "
            'like @guild "Rangers of Vengeance" follow.'
        )
    guild_id = found[0]
    canonical = guild_names[guild_id]
    members = [r for r in commandable if r.get("guild_id") == guild_id]
    if not members:
        return [], f"Nobody from {canonical} is in the world right now."
    return members, describe_expression(f"guild {canonical}")


def _resolve_recruits(
    commandable: list[dict], guild_names: dict[int, str], family: list[str] | None
) -> tuple[list[dict], str]:
    """The family's guild, minus the family - or ([], refusal).

    WHICH GUILD IS OURS IS READ OFF THE FAMILY, NOT TYPED AND NOT CONFIGURED.
    Every roster character carries `guild_id` on its own snapshot row, so the
    answer is already in the data this function was handed. Asking for it a
    second way - a guild name in the expression, an environment variable, a
    query keyed off the head of the family - would be a second answer that
    could disagree with the first, which is the whole reason bridge.py's
    `_fetch_guild` says it is "keyed off the head of the family rather than
    off a guild name".

    A SPLIT FAMILY IS A REFUSAL, NOT A MAJORITY VOTE. If the online roster
    characters do not all report the same guild, one of them has been invited
    elsewhere or has just left, and this function cannot tell which guild the
    operator meant. Guessing would aim an order at a band the operator never
    named, so it says so instead. This is the same instinct `_split_guild_name`
    applies to an unterminated quote: refusing to guess where the name stops
    is cheaper than mustering the wrong guild.

    ONLY ONLINE ROSTER CHARACTERS SPEAK FOR THE FAMILY'S GUILD, but EVERY
    roster name is excluded from the result, online or not. The two are
    different questions on purpose. The guild id has to come from somebody who
    is in the world, because that is who has a fresh snapshot row. The
    exclusion has to cover the whole roster, because a family member who has
    no snapshot row this second is still family and must not be swept into a
    band defined as "everyone but the family" by the accident of a missed
    poll.
    """
    if not family:
        return [], (
            "I do not know who the family is, so I cannot tell a recruit from "
            "one of ours. Name the guild instead, like "
            '@guild "Rangers of Vengeance" follow.'
        )
    kin = {name.lower() for name in family}
    home = {r.get("guild_id") for r in commandable if r["name"].lower() in kin}
    # A character in no guild reports guild_id 0, and 0 is not a guild. Dropped
    # rather than treated as an id of its own, so one unguilded family member
    # cannot make the family look split.
    home.discard(0)
    home.discard(None)
    if not home:
        return [], (
            "Nobody from the family is in the world right now, so I cannot "
            "tell which guild the recruits are in."
        )
    if len(home) > 1:
        names = sorted(guild_names.get(gid, str(gid)) for gid in home)
        return [], (
            "The family is split across " + " and ".join(names) + ", so "
            "'recruits' names no one band. Name the guild instead."
        )
    guild_id = home.pop()
    canonical = guild_names.get(guild_id, "")
    members = [
        r
        for r in commandable
        if r.get("guild_id") == guild_id and r["name"].lower() not in kin
    ]
    if not members:
        where = f" in {canonical}" if canonical else ""
        return [], f"Nobody but the family{where} is in the world right now."
    return members, describe_expression(RECRUITS)


def muster_report(*, reason: str, command: str, called: int, written: int) -> str:
    """The line the channel sees, built from rows that actually landed.

    `written` is what reached overseer_command, not what the bridge meant
    to write: a failed insert is subtracted here rather than rounded away.
    A muster report that over-claims is worse than no report at all - the
    whole point of this line is that the number in Discord equals the
    number of rows in the table (infra#2605).
    """
    if not written:
        return f"Called {reason}, but not one order could be queued."
    orders = "order" if written == 1 else "orders"
    line = f"Called {reason}: {written} {orders} queued [{command}]."
    if written < called:
        line += f" {called - written} could not be queued."
    return line


def thought_text(expression: str, command: str) -> str:
    """What a character remembers about answering a muster.

    Names the band but not the arithmetic: how many the cap left behind is
    the channel's business, not something a character would know.
    """
    return f"The Overseer called {describe_expression(expression)} to arms, and I answered: {command}."
