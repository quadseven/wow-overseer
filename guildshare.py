"""Which family surplus goes to which guildmate, and why it can land (#3908).

THE OTHER DIRECTION FROM THE GUILD TASK. `GuildTaskMgr` (infra#3787) already
gives a recruit a way to ASK: it mails a request under the guild master's
name and mails the reward back. That is recruit-initiated, item-specific and
already shipping, and nothing here duplicates it. This module is the push
half: the family holds more of something than its own crafting rhythm will
ever consume, somebody else in the guild can use it, and nobody had to ask.

WHY THIS IS NOT `materials.py` WITH A WIDER NAME LIST. `materials.py` answers
"whose bags does this reagent belong in" for five characters who share one
profession plan, and its answer comes out of `professions.ROSTER` - a table a
person wrote, naming who is the family's tailor. There is no such table for
the other thirty-five and there cannot be one: they are ordinary
mod-playerbots AI, nobody assigned them anything, and they take no commands.
So the question has to be asked the other way round. Not "who is assigned
this", which has no answer outside the family, but "who is already carrying
the skill this item requires", which the world itself can answer for every
character on the realm. That is a different decision with a different input,
so it is a different module, and `materials.py` is untouched.

THIS IS A WORKAROUND FOR THE GUILD BANK, AND SHOULD BE REVISITED WHEN THAT
LANDS. The natural home for guild surplus is the guild bank. There isn't one:
`guild_bank_tab` is empty for every guild on this realm, and the two C++ gaps
that would change it - tab purchase, and tab rights for non-master ranks - are
open and unimplemented (mod-overseer#456, #457). `guildbank.py`'s own
docstring records the same dead end for item deposit: it can format a
perfectly correct deposit command that has nowhere to go. Character-to-
character `give` is the only channel that carries an item between two members
today, so that is the channel this module plans for. When tabs exist, the
right shape is almost certainly "deposit the surplus and let members take what
they need", which is one writer instead of N-by-M and does not need both
parties online at the same instant. Do not read this module as an argument
against that; read it as what works while that cannot be built.

WHAT WAS MEASURED LIVE, BECAUSE THE WHOLE DESIGN TURNS ON IT
------------------------------------------------------------
`DoGive`'s real contract was probed on the running realm rather than reasoned
about, by queueing four `kind='give'` rows that could not move anything (a
nonexistent item guid) and reading the refusals back:

    receiver              where they were         refusal
    a family member       same map, ~1000 yards   no carried item with that
                                                  guid on the giver
    a guild recruit       DIFFERENT MAP (530 vs   no carried item with that
                          1), different continent guid on the giver
    an offline member     not in the world        receiver not online
    a name that does      nowhere                 receiver not online
    not exist

Two things follow, and both shape this module:

  THE RECEIVER GATE IS PRESENCE AND ONLY PRESENCE. A recruit on another
  continent produced the SAME refusal as a family member standing next to the
  giver: the receiver resolved, and the command failed on the item instead.
  There is no party gate, no guild gate, no roster gate and no distance gate
  on `DoGive`. It already works guild-wide; the gap this module fills is
  entirely on the planning side. This is why every gift here is `give` and
  never `trade` - `gear.py` picks between the two on distance, and a guildmate
  is essentially never inside `gear.TRADE_YARDS`.

  NO LONGER TRUE OF THE MODULE (#189). mod-overseer#566 added the distance
  gate: a give now needs the two on one map and inside trade range. The plan
  here is unchanged; the bridge asks `handover.verdict` how each gift moves,
  which is a give when the two stand together, a `kind='mail'` send
  (`Gift.post_command`) when the family holder stands at a mailbox, and
  otherwise a logged wait.

  AN ABSENT NAME AND AN OFFLINE ONE ARE THE SAME REFUSAL, so this module may
  never treat "I have a name for them" as evidence they are there.
  `ObjectAccessor::FindPlayerByName` returns null for both, and a typo, a
  renamed character and a logged-out one are indistinguishable from here. That
  is why presence is a required field on `Member` rather than an optimistic
  default, and why `plan` drops an offline member instead of queueing a row
  that is already known to fail.

AND ONE FACT ABOUT SCALE THAT IS EASY TO MISS. Of the forty members, SIX were
online at the moment this was measured: the five family characters and one
recruit. The other thirty-four were not in the world at all. A pass that
assumed a forty-name roster was forty available receivers would spend every
cycle writing rows that refuse; this one plans against whoever is actually
standing in the world and says how many that was.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import craft_rhythm

# Item classes this module will move. Deliberately two, and deliberately not
# "anything in a bag".
#
# TRADE_GOODS is the raw-material half - cloth, leather, ore, herbs, enchanting
# dust. CONSUMABLE is the crafted half, and only three of its subclasses (see
# SHAREABLE_CONSUMABLES): the raid-prep goods the guild was asked for.
#
# Everything else a character carries is out of scope rather than unhandled:
# gear is `gear.py`'s decision and already has one, bags are `bag_upgrade.py`'s,
# quest items belong to whoever is on the quest, and a tool like an enchanting
# rod is a thing its owner needs to work at all. A module that shared "whatever
# looked spare" would eventually give away something load-bearing, and the
# damage is not recoverable - `DoGive` has no undo.
CONSUMABLE = 0
TRADE_GOODS = 7

# `item_template.subclass` for class 0. A potion, an elixir and a bandage are
# what a raid actually consumes, and they are what the family's own professions
# can produce (Alchemy on one character, First Aid on all five).
#
# FOOD AND DRINK (subclass 5) IS EXCLUDED ON PURPOSE and it is the exclusion
# most likely to be "fixed" by a later reader, so: the family's food and drink
# is CONJURED. Measured live, four of the five were carrying stacks of Conjured
# Cinnamon Roll, Conjured Crystal Water and Conjured Sparkling Water. Conjured
# items are bound to the conjuring session and vanish; handing one to a
# guildmate is at best a no-op and at worst an item the receiver watches
# disappear out of their bags. The mage can conjure for anyone standing there,
# which is the real answer to a hungry guildmate and is not this module's job.
POTION = 1
ELIXIR = 2
BANDAGE = 7
SHAREABLE_CONSUMABLES = (POTION, ELIXIR, BANDAGE)

# `item_template.subclass` for class 7, against the profession skill lines that
# consume it. The mapping is the game's own item taxonomy, not an invention:
# every subclass below was read off `acore_world.item_template` rows for items
# the family is actually carrying, and the names in the comments are those
# rows' own names.
#
# WHY A SUBCLASS MAP AND NOT A NAME LIST. `materials.REAGENTS` is a six-entry
# table keyed on item NAME, and its own docstring says why it is small: it
# records what a person observed in five characters' bags. That is the right
# shape for five characters and the wrong shape for forty, because the
# thirty-five carry materials nobody has looked at. A subclass is a fact the
# world database states about every item that will ever exist on this realm,
# including the ones nobody has seen yet, so this rule keeps working as the
# guild levels instead of going quiet on everything outside the original six.
#
# THE MAP IS MANY-TO-MANY WHERE THE GAME IS. Cloth feeds Tailoring and First
# Aid both, and that competition is real rather than a modelling artefact -
# `craft_rhythm.GATHERED` records the same collision, where one Linen Cloth is
# two thirds of a Bolt of Linen and all of a Linen Bandage. Metal feeds
# Blacksmithing and Engineering the same way. A member holding EITHER skill can
# use the material, which is what the tuple means.
FEEDS: dict[int, tuple[str, ...]] = {
    4: ("jewelcrafting",),  # Jewelcrafting stones
    5: ("tailoring", "first aid"),  # Linen Cloth, Bolt of Linen, Silk
    6: ("leatherworking",),  # Light Leather, Raptor Hide
    7: ("blacksmithing", "engineering"),  # Copper Ore, Silver Bar, Solid Stone
    8: ("cooking",),  # Red Wolf Meat, Giant Egg
    9: ("alchemy",),  # Silverleaf, Briarthorn, Purple Lotus
    12: ("enchanting",),  # Strange Dust, Illusion Dust
}

# Skill line ids, as `character_skills.skill` spells them. Read off the live
# table rather than a wiki: every id below appeared in this realm's own
# `character_skills` rows for the guild's members, paired with the profession
# by the items those members were carrying and the recipes they could cast.
SKILL_LINES: dict[str, int] = {
    "first aid": 129,
    "blacksmithing": 164,
    "leatherworking": 165,
    "alchemy": 171,
    "herbalism": 182,
    "cooking": 185,
    "mining": 186,
    "tailoring": 197,
    "engineering": 202,
    "enchanting": 333,
    "fishing": 356,
    "skinning": 393,
    "inscription": 773,
    "jewelcrafting": 755,
}

# `item_template.Bonding`. 0 is "binds to nothing", which is every raw trade
# good and every crafted consumable checked on this realm.
#
# ONLY ZERO IS SHARED, AND THE STRICTNESS IS THE POINT. A bind-on-pickup item
# in somebody's bags is already bound to them and cannot be given at all; a
# bind-on-equip one can be, but this module has no business deciding that a
# guildmate should receive something the family might still want to wear -
# that is `gear.py`'s question and `gear.py` has an answer for it. Refusing
# everything but Bonding 0 means this pass can never be the reason a piece of
# gear left the family.
BINDS_TO_NOBODY = 0

# How much of a reagent the family keeps for itself before any of it is spare.
#
# THIS NUMBER IS NOT NEW AND MUST NOT BECOME NEW. It is `craft_rhythm`'s own
# "stocked" threshold, imported rather than copied, and it already means
# exactly the right thing: twelve casts of the recipe that consumes the
# reagent is the point at which that module declares a crafter supplied and
# sends the family off to do something other than gather. A second, larger
# number invented here would mean the family reads as stocked, stops
# gathering, and then hands away the stock that made it stocked - which is the
# starvation loop this module is explicitly not allowed to create. A second,
# smaller one would hoard past the point the family itself calls enough.
#
# Reading it through the module rather than re-spelling the literal is what
# keeps that true when somebody retunes it: there is one 12 in this codebase.
RESERVE_CASTS = craft_rhythm.STOCK_CASTS


@dataclass(frozen=True)
class Holding:
    """One stack in one family character's bags, with the item's own rules.

    ONE ROW PER `item_instance.guid`, the same unit `materials.Holding` uses
    and for the same reason: `DoGive` moves one guid and cannot address "forty
    Bolts of Linen, wherever they happen to sit". Og was measured holding 151
    Bolts across EIGHT separate stacks, so this distinction is not theoretical.

    The four `required_*`/`bonding` fields are read straight off
    `acore_world.item_template` and are the item stating its own terms. They
    are carried here rather than looked up later because the alternative is a
    per-item query inside the planning loop, and because an item whose terms
    could not be read must be refused rather than guessed at - which a caller
    expresses by not building a Holding for it at all.
    """

    holder: str
    item: str
    entry: int
    count: int
    guid: int
    item_class: int
    subclass: int
    bonding: int = BINDS_TO_NOBODY
    required_skill: int = 0
    required_rank: int = 0
    required_level: int = 0


@dataclass(frozen=True)
class Member:
    """One guild member, as the world currently describes them.

    `online` IS A MEASURED FACT AND HAS NO DEFAULT. The live probe recorded
    above proved that an offline receiver and a nonexistent one produce the
    identical refusal, so presence cannot be inferred from having a name.
    Callers read it from `overseer_snapshot` on the 60-second freshness rule
    every other pass in this service already uses - the same table that,
    measured live, carried a fresh row for all 106 characters in the world,
    recruits included, not just the five the family knows about.

    `skills` is `{skill line id: current value}` from `character_skills`. That
    table IS authoritative for skill LINES, which is a narrower claim than it
    sounds and is worth stating because the neighbouring one is not:
    `character_spell` is NOT authoritative for which RECIPES a playerbot knows,
    because recipes granted at runtime never persist to it. This module asks
    only "does this character carry Tailoring, and at what rank", never "do
    they know this pattern", so it stays on the side of that line where the
    database can be believed.

    `family` marks the five characters the overseer drives. They are kept in
    the roster rather than filtered out by the caller so that `plan` can say
    why it skipped them, and so a family name can never silently become a
    receiver here - `materials.py` owns hand-offs inside the family, and two
    modules writing gives for the same pair is the second-writer bug this
    project has fixed more than once.
    """

    name: str
    class_id: int = 0
    level: int = 0
    skills: Mapping[int, int] = None
    online: bool = False
    family: bool = False

    def rank_in(self, skill_id: int) -> int:
        """Current value in one skill line, 0 for a line they do not have."""
        return int((self.skills or {}).get(int(skill_id), 0) or 0)


@dataclass(frozen=True)
class Gift:
    """One stack, moving from a family member's bags to a guildmate's.

    Same field discipline as `materials.Grant`: no `said` field, because one
    guid is not one sentence. Og's 151 Bolts are eight guids and eight
    commands, and at most one thing worth saying about it.

    `need` is why the RECEIVER can use this, in their own terms - the skill
    they hold, or the level the item asks for. `reason` is why the family can
    spare it. Both are stored rather than rebuilt at display time so that what
    a person reads on the page and what the log records cannot drift apart.
    """

    holder: str
    taker: str
    item: str
    entry: int
    count: int
    guid: int
    need: str
    reason: str

    @property
    def command(self) -> str:
        """What mod-overseer's `DoGive` parses out of `overseer_command.command`."""
        return "guid:%d" % int(self.guid)

    @property
    def post_command(self) -> str:
        """The `kind='mail'` send that posts the same stack from a mailbox (#189).

        A guildmate is rarely within trade range of the family, and
        mod-overseer#566 refuses a give outside it, so the surplus goes by
        post when its holder stands at a mailbox.
        """
        return "send item:%d subject:%s" % (int(self.guid), self.item)

    @property
    def said(self) -> str:
        """The one line the giver speaks, naming the reason the receiver has.

        Kept short and in the family's own register, matching
        `materials._said_for`: who gives what to whom, then why the receiver
        can use it. A sentence that claimed more than `need` supports is the
        exact failure `materials.py` records against itself, where "Og need it
        for tailoring" was a fact about a roster table and not about Og.
        """
        return "%s give %s %d %s. %s" % (
            self.holder,
            self.taker,
            self.count,
            self.item,
            self.need,
        )


@dataclass(frozen=True)
class Plan:
    """What this pass decided, including everything it decided against."""

    gifts: tuple = ()
    # Surplus nobody online can use, and guildmates nothing suits. One note
    # each, said rather than dropped, the same rule `materials.Plan.notes`
    # holds: a pass that goes quiet when it finds nothing is indistinguishable
    # from a pass that is broken.
    notes: tuple = ()
    # Pairs the world has refused enough times to be believed, from
    # `materials.stuck`. Reused rather than reimplemented - the refusal
    # counting, the threshold and the give-up rule are one decision and this
    # module has no reason to hold a second copy of it.
    blocked: tuple = ()
    # How many guild members were in the world when this ran. Carried because
    # "nothing to share" and "nobody was online to share it with" are
    # different findings and a reader must be able to tell them apart.
    present: int = 0


def reserve_for(entry: int, craft_spells) -> int:
    """How many of this item the family keeps back, in units, not casts.

    THE ARITHMETIC IS `craft_rhythm`'S, TURNED AROUND. That module asks "how
    many casts do these units buy"; this one asks "how many units does twelve
    casts cost", which is the same `per_cast` read the other way. Doing it
    here rather than re-deriving reagent quantities is what keeps a single
    source of truth: if `GATHERED` says a Bolt of Linen eats two Linen Cloth,
    both questions get answers from that one statement.

    THE MAXIMUM ACROSS EVERY FAMILY RECIPE THAT WANTS IT, not the sum and not
    the first match. Linen Cloth feeds Og's Bolt of Linen at two per cast and
    every character's Linen Bandage at one; the family needs the larger
    reserve to keep both ladders alive, and adding them would reserve stock
    for a cast nobody is queued to make. Cloth is the case that actually
    occurs on this realm, so it is the case the rule is written for.

    ZERO FOR AN ITEM NO FAMILY RECIPE CONSUMES, which is a real answer and not
    a fallback. Nothing in the family's crafting rhythm is waiting on it, so
    none of it has to be held back for crafting. That is not on its own a
    reason to give it away - the receiver still has to be able to use it, and
    `plan` still has to find one - but it is not this function's question.
    """
    wanted = 0
    for spell in craft_spells or ():
        for reagent in craft_rhythm.GATHERED.get(int(spell or 0), ()):
            if int(reagent.entry) != int(entry):
                continue
            wanted = max(wanted, RESERVE_CASTS * int(reagent.per_cast))
    return wanted


def surplus(holdings, craft_spells) -> tuple:
    """The stacks the family can spare, whole stacks only.

    THE RESERVE IS COUNTED ACROSS THE WHOLE FAMILY AND NOT PER CHARACTER, and
    that is the conservative direction rather than the convenient one. Cloth
    moves between these five constantly - it is what `materials.py` does all
    day - so a per-holder reserve would let five characters each hold back a
    full twelve-cast reserve of the same reagent and call 84 of the 151 Bolts
    untouchable. Reserving once for the family and sharing only what is above
    that keeps the number honest in the one direction that matters: the family
    never ends a pass with less than it told itself it needed.

    WHOLE STACKS, BECAUSE `DoGive` MOVES WHOLE STACKS. There is no partial
    transfer in the verb - one guid, all of it - so a stack is shareable only
    if the family is still above its reserve after the whole stack is gone.
    Stacks are considered smallest first for exactly this reason: giving away
    Og's stack of 11 leaves more room under the reserve than giving away one
    of his stacks of 20, so the small ones move and the reserve is reached
    later. Sorting by guid inside equal counts keeps two runs over unchanged
    bags identical, which is what lets the caller's dedupe recognise a repeat
    instead of seeing a reshuffled plan every cycle.
    """
    reserves: dict = {}
    pools: dict = {}
    for holding in holdings:
        entry = int(holding.entry)
        pools.setdefault(entry, []).append(holding)
        if entry not in reserves:
            reserves[entry] = reserve_for(entry, craft_spells)

    spare = []
    for entry, stacks in pools.items():
        held = sum(int(s.count) for s in stacks)
        keep = reserves[entry]
        for stack in sorted(stacks, key=lambda s: (int(s.count), int(s.guid))):
            if held - int(stack.count) < keep:
                continue
            held -= int(stack.count)
            spare.append(stack)
    return tuple(sorted(spare, key=lambda s: (s.holder, s.item, int(s.guid))))


def shareable(holding: Holding) -> bool:
    """Whether this module will move this KIND of item at all.

    Asked before anything about who wants it, because the answer is a property
    of the item and a cheap one. An item that binds to its holder cannot be
    given by anyone to anyone, and an item outside the two classes above is
    somebody else's decision.
    """
    if int(holding.bonding) != BINDS_TO_NOBODY:
        return False
    if int(holding.item_class) == TRADE_GOODS:
        return int(holding.subclass) in FEEDS
    if int(holding.item_class) == CONSUMABLE:
        return int(holding.subclass) in SHAREABLE_CONSUMABLES
    return False


def _trade_named(skill_id: int) -> str:
    """The profession a skill line id spells, or '' for one not in the table."""
    for name, known in SKILL_LINES.items():
        if int(known) == int(skill_id):
            return name
    return ""


def can_use(holding: Holding, member: Member) -> str:
    """Why this member could use this item, or '' if they could not.

    A SENTENCE OR NOTHING, the three-answer discipline `gear.claimant` keeps:
    the caller gets back either the receiver's own reason - which goes into
    what the giver says out loud - or an empty string, and never a bare True
    that a log line then has to guess a justification for.

    `RequiredSkill` MEANS TWO DIFFERENT THINGS AND MUST BE READ TWO DIFFERENT
    WAYS. This is the trap in this function and it was found by running the
    real query against the live realm rather than by reasoning, so it is
    written down at length.

    On a CONSUMABLE the field is a genuine usage gate. Measured on this realm,
    every bandage carries `RequiredSkill = 129` (First Aid) with a real
    `RequiredSkillRank` and `RequiredLevel = 0`, while every potion and elixir
    carries `RequiredSkill = 0` and a real `RequiredLevel` - Minor Healing
    Potion 1, Greater Healing Potion 21. So a bandage is a profession question
    and a potion is a level question, and the item row says which without this
    module needing a table of its own.

    On a TRADE GOOD the same field is a PROCESSING hint, and reading it as a
    usage gate is wrong in a way that silently inverts the answer. Measured on
    the same pass: Silverleaf, Briarthorn, Purple Lotus and Swiftthistle - the
    alchemist's own herbs, sitting in the family alchemist's bags - all carry
    `RequiredSkill = 773`, INSCRIPTION, with ranks of 1, 25 and 175. That is
    the skill needed to MILL them, not to use them. Treating it as a gate
    would have refused every herb to every alchemist in the guild while
    cheerfully offering them to a scribe, which is the exact opposite of what
    the field appears to say.

    So for a trade good the profession that CONSUMES it - out of `FEEDS`, on
    the subclass - is asked first and is the real answer. The declared
    `RequiredSkill` is then accepted as a SECOND, additional way to qualify,
    because it is not meaningless: a scribe genuinely can use Silverleaf, just
    by milling it rather than brewing with it. Both readings are true at once,
    which is why the answer is a union rather than a choice.

    Without the `FEEDS` step the rule would degenerate into "anyone can use
    anything", and sending a warlock a stack of Rugged Leather is not sharing,
    it is moving the clutter somewhere else.
    """
    if int(holding.required_level) > int(member.level):
        return ""
    required = int(holding.required_skill)

    if int(holding.item_class) == CONSUMABLE:
        if required:
            if member.rank_in(required) < int(holding.required_rank):
                return ""
            return "%s has %s" % (
                member.name,
                _trade_named(required) or "the skill it needs",
            )
        return "%s is level %d" % (member.name, int(member.level))

    for trade in FEEDS.get(int(holding.subclass), ()):
        if member.rank_in(SKILL_LINES.get(trade, 0)):
            return "%s has %s" % (member.name, trade)
    if required and member.rank_in(required) >= int(holding.required_rank):
        return "%s has %s" % (
            member.name,
            _trade_named(required) or "the skill it needs",
        )
    return ""


def _best_taker(holding: Holding, members, given: Mapping) -> tuple:
    """Which online guildmate gets this stack, and their reason.

    ONE GIFT PER MEMBER PER PASS, budgeted across the whole plan rather than
    checked per stack. `gear.deliverable` learned this the expensive way: a
    character measured at 62 of 62 bag slots had eight pieces planned for it,
    and checking "has room" eight times against one free slot writes seven
    rows that were doomed when they were written. The wider guild is worse,
    not better - none of the thirty-five are polled, nobody manages their bags,
    and the family's own most-repeated refusal is "receiver bags are full".
    One stack per member per cycle is the version of that budget this module
    can defend without a bag read it does not have.

    LOWEST LEVEL FIRST AMONG THOSE WHO QUALIFY. The surplus is the family's,
    the guild's recruits are levelling, and a stack of cloth is worth more to
    the level 16 than to the level 55 - who, being level 55, is closer to
    outgrowing it entirely. Ties break on name so the plan is deterministic.
    """
    best = None
    for member in sorted(members, key=lambda m: (int(m.level), m.name)):
        if member.family or not member.online:
            continue
        if given.get(member.name):
            continue
        need = can_use(holding, member)
        if need:
            best = (member, need)
            break
    return best or (None, "")


def plan(
    holdings, members, craft_spells=(), stuck_pairs: Mapping | None = None
) -> Plan:
    """Every family stack that should leave the family, in one pass.

    THE ORDER OF THE THREE GATES IS THE DESIGN. What kind of item is this
    (`shareable`), can the family spare it (`surplus`), and is there somebody
    online who can use it (`_best_taker`). They are asked in that order because
    each is cheaper and more certain than the next, and because reversing the
    last two would let "somebody wants this" become a reason to break the
    family's own reserve - which is the one outcome this module is not allowed
    to produce.

    `stuck_pairs` is `materials.stuck`'s answer and is honoured exactly as
    `materials.plan` honours it: a pair the world has refused enough times to
    be believed produces nothing rather than another doomed row. Reusing that
    function rather than writing a second refusal counter means one threshold,
    one give-up rule, and one place to change either.
    """
    refused = stuck_pairs or {}
    roster = list(members)
    present = sum(1 for m in roster if m.online and not m.family)

    gifts, notes, blocked = [], [], []
    given: dict = {}
    seen_blocks = set()

    if not present:
        notes.append(
            "no guild member outside the family is in the world right now, so "
            "nothing can be handed over - a give needs both characters online"
        )
        return Plan(gifts=(), notes=tuple(notes), blocked=(), present=0)

    movable = [h for h in holdings if shareable(h)]
    for holding in surplus(movable, craft_spells):
        member, need = _best_taker(holding, roster, given)
        if member is None:
            note = "%s has spare %s and nobody online can use it" % (
                holding.holder,
                holding.item,
            )
            if note not in notes:
                notes.append(note)
            continue
        refusal = refused.get((holding.holder, member.name))
        if refusal:
            mark = (holding.holder, member.name)
            if mark not in seen_blocks:
                seen_blocks.add(mark)
                blocked.append((holding.holder, member.name, refusal))
            continue
        given[member.name] = True
        keep = reserve_for(int(holding.entry), craft_spells)
        gifts.append(
            Gift(
                holder=holding.holder,
                taker=member.name,
                item=holding.item,
                entry=int(holding.entry),
                count=int(holding.count),
                guid=int(holding.guid),
                need=need,
                reason=(
                    "%s is above the family's own reserve of %d %s (%d casts' "
                    "worth), and %s - so the stack does more good in their bags "
                    "than in %s's."
                    % (
                        holding.holder,
                        keep,
                        holding.item,
                        RESERVE_CASTS,
                        need.lower(),
                        holding.holder,
                    )
                ),
            )
        )
    return Plan(
        gifts=tuple(gifts), notes=tuple(notes), blocked=tuple(blocked), present=present
    )


def lines(share_plan: Plan) -> list:
    """The family saying it, "Name: words".

    Same shape `materials.lines` and `professions.lines` speak in, so a
    guild-wide hand-off reads in party chat exactly like a family one rather
    than arriving as a silent database write.
    """
    return ["%s: %s" % (gift.holder, gift.said) for gift in share_plan.gifts]


def headline(share_plan: Plan) -> str:
    """One line over the plan, saying nothing rather than inventing a finding.

    THE THREE EMPTY CASES ARE DIFFERENT AND ARE SAID DIFFERENTLY. Nobody
    online, nobody who can use what is spare, and nothing spare in the first
    place are three distinct states of a healthy guild, and collapsing them
    into "0 gifts" is how a reader concludes the pass is broken when it is
    working perfectly.
    """
    if not share_plan.present:
        return "no guildmate is in the world right now"
    if not share_plan.gifts:
        return (
            "%d guildmate%s online, and nothing the family can spare suits "
            "any of them" % (share_plan.present, "" if share_plan.present == 1 else "s")
        )
    return "%d stack%s going out to %d of the %d guildmate%s online" % (
        len(share_plan.gifts),
        "" if len(share_plan.gifts) == 1 else "s",
        len({g.taker for g in share_plan.gifts}),
        share_plan.present,
        "" if share_plan.present == 1 else "s",
    )
