"""The family argues about the tabard and arrives at one.

Pure module, same seam as council.py, kin.py and bonds.py: names in, a
conversation and a design out. bridge.py sends the command and writes the
result; nothing here touches a database or a socket.

WHAT THE OPERATOR ASKED FOR (infra#2831): "when they have enough money they will make
one called Cave and they will design their tabard after discussing what it
should look like". The guild exists - `Cave`, guildid 23, formed 2026-09-12
via mod-overseer's `guild form` verb, with Grug as its master and the other
four inside it. The money is not a problem either; every one of them is
carrying more than fifteen times the price. So this module is the last third
of that sentence and only the last third: the DISCUSSION.

WHY IT IS A DISCUSSION AND NOT A CONSTANT. The ticket is explicit that this is
the part that is easy to fumble - "The tabard should be the outcome of a
conversation, not a config value" - so the five fields are not assigned. They
are won. Each member wants something in every field, every field is settled by
the same tally the council already uses, and different members win different
fields, so the thing they end up wearing is a composite none of them proposed
whole. A tabard one character picked would be a config value with extra steps.

AND IT MUST CONCLUDE. The ticket names the risk itself: "A tabard debate that
never ends would be a very funny way to rediscover that bug" - the council
staged the same scene at 21:06, 22:06 and 23:07 before infra#2807 found the
cause. Conclusion here is structural rather than careful: the tally is total
and the tie-break is seniority, so the debate is a pure function of the family
table. `test_the_same_family_always_arrives_at_the_same_tabard` is that rule.

WHAT THE NUMBERS ARE, AND THE ONE THING THIS MODULE CANNOT TELL YOU
-------------------------------------------------------------------
A 3.3.5 tabard is five integers, and each is an index into a palette that
lives in the CLIENT's DBC files. This realm has no copy of those files, so
what any particular index LOOKS like is not knowable from here - not by
reading the database, not by reading AzerothCore, which stores the five
integers without ever interpreting them (`Guild::HandleSetEmblem` validates
the payer and the price and nothing else).

So this module does not name colours. Inventing a red-is-7 table would be
fabricating game data to make the transcript read better, and the transcript
is not the artefact - the tabard is. What it does instead:

  * picks values from RANGES MEASURED ON THIS REALM, not assumed. All twenty
    other guilds here were given tabards by mod-playerbots, and on
    2026-09-12 those twenty spanned:

        EmblemStyle      12..175      EmblemColor      0..17
        BorderStyle       0..7        BorderColor      0..17
        BackgroundColor   1..44

    The last one is why they are measured. Every reference to the 3.3.5
    tabard UI says the colour wheels hold eighteen entries, which would make
    17 the ceiling for all four colour fields; this realm has a guild wearing
    44. Assuming 0..17 would have quietly thrown away half the palette the
    world is already using.

  * derives each member's want from a PUBLIC, REAL fact - `characters.race`
    and `characters.class`, read from the character's own row by the caller
    and passed in as `Kin`. Not a hash and not a preference table: if Bork
    wants a different border to Og it is because they are a gnome rogue and a
    human mage, and that is visible to anyone standing next to them.

  * leaves the aesthetic judgement to the one party who can actually see it.
    The operator watches this realm live and says plainly when something looks stupid;
    that has been a real mechanism every single time. A module that guessed at
    colour names would be asking him to argue with a lookup table instead of
    with the tabard.

WHO CAN APPLY IT. Not whoever is nearest. `Guild::HandleSetEmblem` refuses
anybody but the guild master and charges EMBLEM_PRICE, so the command is
addressed to Grug by name and the affordability check is the server's own
rule restated - not a nicety, because a refusal costs a round trip and lands
in `detail` as a failure nobody asked for.
"""

from __future__ import annotations

from dataclasses import dataclass

import bonds

# AzerothCore, `src/server/game/Guilds/Guild.cpp:42`:
#   #define EMBLEM_PRICE 10 * GOLD
# GOLD is 10000 copper. Named here rather than inlined because it is the
# server's number and the module must not drift from it - the leader is
# refused with ERR_GUILDEMBLEM_NOTENOUGHMONEY, which reaches us as a failed
# command row and not as an exception.
EMBLEM_PRICE = 10 * 10000


@dataclass(frozen=True)
class Field:
    """One of the five integers, and the range this realm has evidence for.

    `low`/`high` are MEASURED (see the module docstring), which is why they
    are data rather than literals scattered through the arithmetic.

    `spoken` is what a character CALLS it. The column name is a database
    fact and five cavemen saying "EmblemColor" out loud in party chat is the
    kind of detail that breaks the spell - the ticket has them arguing about
    "border style and colours", which is how people talk about a flag.
    """

    name: str
    low: int
    high: int
    spoken: str

    def clamp(self, value: int) -> int:
        span = self.high - self.low + 1
        return self.low + (value % span)


# The five, in the order the guild table stores them, so a reader comparing
# this against `SELECT * FROM guild` is reading two lists in one order.
FIELDS = (
    Field("EmblemStyle", 12, 175, "the mark"),
    Field("EmblemColor", 0, 17, "the colour of the mark"),
    Field("BorderStyle", 0, 7, "the border"),
    Field("BorderColor", 0, 17, "the colour of the border"),
    Field("BackgroundColor", 1, 44, "the ground it all sits on"),
)


@dataclass(frozen=True)
class Claim:
    """What one member wants, in every field, and why they say it is theirs."""

    member: str
    wants: dict
    said: str


@dataclass(frozen=True)
class Design:
    """The tabard the family arrived at, and everything needed to apply it."""

    fields: dict
    won_by: dict
    applied_by: str

    def affordable(self, purse: int) -> bool:
        """The server's rule, asked before the round trip rather than after."""
        return purse >= EMBLEM_PRICE

    def command(self) -> str:
        """The row mod-overseer reads: `tabard <five integers>`, in FIELDS
        order. Positional and not named, because the module's parser takes
        the five in the order the guild table stores them."""
        return "tabard " + " ".join(str(self.fields[f.name]) for f in FIELDS)


@dataclass(frozen=True)
class Debate:
    """What was said, what was agreed, and why.

    `design` is None when there was nobody to argue - see `debate`. Callers
    check `lines` and return, which is the shape `council.hold` already has.
    """

    lines: list
    design: Design | None
    reason: str


@dataclass(frozen=True)
class Kin:
    """One member as the debate sees them.

    `race` and `char_class` are `characters.race` and `characters.class` - the
    world's own ids, passed in rather than looked up here. An earlier draft
    kept name -> id tables in this module and it was wrong twice over: it was
    a second answer to what a gnome is, next to the one `questbook.py` already
    holds, and the docstring above claimed the ids came from the character row
    when they came from a table written from memory. Now they do come from the
    row.

    Both are PUBLIC facts - you can see that Bork is a gnome rogue by standing
    next to him - so nothing here breaks the council's private/public rule.
    """

    name: str
    race: int
    char_class: int


def claim(who: Kin) -> Claim | None:
    """What `who` wants the tabard to be. None for anyone outside the family.

    Every field gets a want, because a member with an opinion in only two of
    them cannot be argued with in the other three and would drop silently out
    of the scene.
    """
    bond = bonds.member(who.name)
    if bond is None:
        return None
    race, char_class = who.race, who.char_class
    canonical = bonds.canon(who.name) or who.name
    # Race leads on the two STYLE fields and class on the two COLOUR fields,
    # with the background taking both. Written as one rule rather than five so
    # that adding a sixth field cannot accidentally leave one member out.
    seeds = {
        "EmblemStyle": race * char_class,
        "EmblemColor": char_class,
        "BorderStyle": race,
        "BorderColor": race + char_class,
        "BackgroundColor": race * char_class + bond.seniority,
    }
    wants = {f.name: f.clamp(seeds[f.name]) for f in FIELDS}
    # FIVE OPENINGS, NOT ONE. bonds.py keeps a persona per member for exactly
    # this reason - "the register is shared, so this is what stops five
    # characters saying one sentence, which is exactly what happened when the
    # personas differed only in role". A single template here would have
    # rebuilt that bug one layer down, where the LLM pass cannot fix it: what
    # persona.build_prompt is given is this line, so five copies of one
    # sentence is five characters handed the same thing to say.
    #
    # Keyed on role, which is family data, rather than on the name, so a
    # roster change does not silently drop somebody back to a default.
    # The roles are bonds.FAMILY's own words, checked against it rather than
    # guessed: father, mother, elder son, younger son, neighbour. A role that
    # is not here falls back rather than crashing, but the fallback is a smell
    # and not a plan - five characters is the whole family.
    openings = {
        "father": "{me} lead this family. Tabard say what {me} say it say:",
        "mother": "{me} keep everyone alive. {me} want to see it from far off:",
        "elder son": "{me} think on this already. Listen:",
        "younger son": "Nobody ask {me}. {me} say it anyway:",
        "neighbour": "{me} not blood, but {me} wear it too:",
    }
    template = openings.get(bond.role, "{me} have thought on it:")
    said = (
        template.format(me=canonical)
        + f" {bond.race} {bond.char_class}. That what {canonical} is."
    )
    return Claim(member=canonical, wants=wants, said=said)


def _median(values: list) -> int:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def _weight(name: str, field: Field, claims: list) -> tuple:
    """How hard `name` pushes for its own value in one field. Highest wins.

    Three terms, and the middle one is the one that makes this a debate.

    1. BACKING. A value somebody else also wants is an idea with support
       behind it, the same rule `council._tally` applies when it folds
       duplicate proposals into one. It is first because agreement should
       beat feeling, or the family never converges on anything.
    2. HOW STRONGLY THEY FEEL, measured as distance from what the family
       wants on average in this field. The member whose identity is most
       unlike everyone else's HERE is the one with something to say about
       it, and they are different members in different fields - the three
       humans want the same border and none of them is unusual in it, while
       the gnome is unusual in almost everything.
    3. SENIORITY, last, as the elder's word breaking a tie.

    Seniority CANNOT be the whole score, and this was measured rather than
    reasoned: with backing and seniority alone Grug won all five fields and
    the family wore its father. `test_more_than_one_member_gets_their_way`
    is that failure, kept.
    """
    wants = {c.member: c.wants[field.name] for c in claims}
    mine = wants[name]
    agreeing = sum(
        1 for other, value in wants.items() if other != name and value == mine
    )
    feeling = abs(mine - _median(list(wants.values())))
    bond = bonds.member(name)
    return (agreeing, feeling, bond.seniority if bond else 0)


def debate(kin: list) -> Debate:
    """Five characters, five fields, one tabard.

    Takes no `history`. The first draft accepted one to match every other
    family conversation and then never read it, which cost the bridge a live
    `_fetch_reflections` round trip per cycle to build an argument that was
    thrown away. Nothing here refuses to back anybody, so there is nothing for
    a history to change; when that stops being true the parameter comes back
    with a caller that reads it.
    """
    claims = [c for c in (claim(k) for k in kin) if c is not None]
    # NOBODY TO ARGUE IS AN ANSWER, NOT A CRASH. `claim` returns None for
    # anyone outside the family, so an empty `kin` - or a read that came back
    # short, or a roster that has drifted out of bonds.FAMILY - leaves nothing
    # here, and `max()` over an empty list raises ValueError from the void:
    # the debate dies, the bridge logs an exception, and the next cycle does
    # it again. Saying so is the difference between a family with no opinion
    # and a module that fell over.
    if not claims:
        return Debate(lines=[], design=None, reason="nobody to argue about it")
    # Sorted by name so the ARGUMENT does not depend on the caller's list
    # order; seniority decides who WINS, further down, and the two are
    # deliberately different orders.
    claims.sort(key=lambda c: c.member)

    fields, won_by = {}, {}
    for field in FIELDS:
        best = max(claims, key=lambda c: (_weight(c.member, field, claims), c.member))
        fields[field.name] = best.wants[field.name]
        won_by[field.name] = best.member

    head = bonds.head_of_family()
    lines = [f"{c.member}: {c.said}" for c in claims]
    for field in FIELDS:
        winner = won_by[field.name]
        backing, feeling, _ = _weight(winner, field, claims)
        if backing:
            lines.append(
                f"{winner}: {backing + 1} of us want same for "
                f"{field.spoken}. That settled."
            )
        elif feeling:
            lines.append(
                f"{winner}: Nobody care about {field.spoken} like "
                f"{winner} care. {winner} take it."
            )
        else:
            lines.append(f"{winner}: Then {field.spoken} is mine.")
    # The numbers stay OUT of the closing line. They are palette indices and
    # mean nothing said aloud - "Cave wear EmblemStyle 40" is a character
    # reading a database column to his family. What is worth saying is who won
    # what, which is the thing they actually argued over.
    settled = ", ".join(f"{won_by[f.name]} get {f.spoken}" for f in FIELDS)
    lines.append(f"{head}: It settled. {settled}. Cave wear that.")

    design = Design(fields=fields, won_by=won_by, applied_by=head)
    winners = len(set(won_by.values()))
    reason = (
        f"{winners} of {len(claims)} got their way; "
        f"{head} carries it to the tabard designer."
    )
    return Debate(lines=lines, design=design, reason=reason)
