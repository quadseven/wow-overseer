"""Family bonds: who answers a plea depends on who they are to the caller.

Pure module, same seam as kin.py - a plea, a roster-derived muster and a
history of who has helped whom go in, a narrowed muster comes out. bridge.py
reads the history and writes the rows.

WHERE THESE RULES COME FROM. Evan described the family, and every rule below
traces to a clause of it rather than to a general idea of what families do:

  "grug is the dad and should always help his family unless he is mad at ugga
   getting helped by og too much, and bork is gonna constantly need help he is
   a little dumb kid always getting in trouble lol the younger brother to grog"

Which is: Grug answers unconditionally; the ONE exception is Ugga, and only
once Og has been the one answering her too often. Bork calls constantly and
that is characterisation, not a fault - but the sentence names Grog as well,
and it is Grog who carries it. The rest of the family does eventually tire of
Bork; his father and his big brother never do. Bork was briefly exempt from
fatigue outright, which read the first half of the clause and dropped the
second, and made the little-brother rule decoration: it could not change an
outcome, because the only caller it applied to was already exempt.

Every threshold counts a PAIR - how often this responder answered this caller.
Counting every answer to a caller instead looks equivalent and is not: one plea
writes one memory row per responder, so the same number meant two pleas with
the family online and five with one member online. Worse, it starved the
jealousy rule, which needs Og to keep answering Ugga: Og tired out at two, one
short of the three that makes Grug sulk, so the rule Evan actually asked for
could never fire.

WHY THE HISTORY IS NOT NEW STATE. `kin` already writes a `reflection` row for
every responder - "Grog called for help with X. I regrouped." - so who helped
whom is already recorded. `history_from_thoughts` reads those rows back rather
than keeping a second tally that could disagree with the store. If a memory is
not there, the help did not happen as far as this module is concerned, which is
the same rule the rest of the overseer uses.

WHAT THIS DOES NOT DO. It never ADDS a responder. `kin.plan_muster` decides who
is eligible - online, a bot, in the caller's guild - and this only ever narrows
that set. A bond cannot conjure a character who is not there, and a refusal
here is a character choosing not to go, never a scoping bug wearing a story.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

import cast
import kin

# Og answering Ugga this many times is where Grug stops being reasonable.
# Two is fine, three is a pattern.
JEALOUSY_THRESHOLD = 3

# How many times one character may be answered before the family tires of it.
# Bork is exempt; see the docstring.
FATIGUE_THRESHOLD = 5


@dataclass(frozen=True)
class Bond:
    role: str
    blood: bool
    # Higher is older. Only meaningful between blood relatives; it is what
    # makes Grog the big brother and Bork the little one.
    seniority: int
    # Who they actually are in the world, verified against the live characters.
    #
    # They are all CAVEMEN - that is why the parents are human, and why the two
    # boys are a dwarf and a gnome: those models are SHORT, so they read as
    # children. The race is a sight gag, not a culture. Nobody has a dwarven or
    # gnomish accent; they all talk like Grug, which is its own accent and the
    # only one this family has.
    #
    # The CLASS is real and worth voicing: Ugga is the priest keeping them all
    # alive, Bork is a rogue getting into places he should not.
    race: str = ""
    char_class: str = ""
    gender: str = ""
    # Which talent tree this character spends points in, as a DBC tabpage:
    # 0, 1 or 2 in the in-game left-to-right order. -1 leaves talents alone.
    #
    # WHY THIS LIVES WITH THE FAMILY AND NOT WITH THE MODULE. mod-overseer knows
    # a character's class and level and nothing about who it is. A spec is a
    # ROLE, and the roles here come from the family: Grug tanks because he is the
    # father who goes first into everything, and Ugga heals because keeping them
    # all alive is the whole of who she is. Picking at random from
    # RandomClassSpecProb - which is what mod-playerbots does for a bot nobody
    # knows - would have given a party with no tank and no healer about half the
    # time, and no way to ask for one.
    #
    # The numbers are the DBC tabpage, verified against the mod-playerbots enums
    # rather than remembered: warrior 0=arms 1=fury 2=protection, paladin 0=holy
    # 1=protection 2=retribution, priest 0=discipline 1=holy 2=shadow, rogue
    # 0=assassination 1=combat 2=subtlety, mage 0=arcane 1=fire 2=frost.
    spec_tab: int = -1
    # How this one differs from the others WITHIN the grug voice. The register
    # is shared, so this is what stops five characters saying one sentence -
    # which is exactly what happened when the personas differed only in role.
    persona: str = ""


# THE FAMILY, AS THE LIVE WORLD KNOWS IT. `FAMILY` below is this table put
# through the rename for whichever world this process serves (cast.py); for the
# live world that is the identity, and this IS the table.
_LIVE_FAMILY: dict[str, Bond] = {
    "Grug": Bond(
        role="father",
        blood=True,
        seniority=100,
        race="human",
        char_class="warrior",
        gender="male",
        # Protection. He is the one who goes first, so he is the one who
        # gets hit; this is the tank the family has never had.
        spec_tab=2,
        persona=(
            "The father, and a warrior. Fewest words of anyone, and the most "
            "certain. Says what the family will do, not what it might. Goes "
            "first into everything because that is where the family is not. "
            "Watches Og around Ugga more than he admits, and has no words for "
            "why that sits badly."
        ),
    ),
    "Ugga": Bond(
        role="mother",
        blood=True,
        seniority=99,
        race="human",
        char_class="priest",
        gender="female",
        # Holy. She is already described as the priest keeping every one of
        # them alive - this is that sentence made true in the talent tree.
        spec_tab=1,
        persona=(
            "The mother, and the priest keeping every one of them alive. Warm "
            "and practical - talks about who is hurt, who has eaten, who is "
            "cold. Fond of Og and careless about how that looks. Never says "
            "anything untrue, which is not the same as saying everything."
        ),
    ),
    "Grog": Bond(
        role="elder son",
        blood=True,
        seniority=50,
        race="dwarf",
        char_class="paladin",
        gender="male",
        # Retribution. Copying his father into melee, one step behind him.
        spec_tab=2,
        persona=(
            "The older boy, and a paladin. A CHILD - older than Bork and "
            "nowhere near grown, however much he would like to be. Copies his "
            "father's way of talking and puts one word too many in, so it "
            "comes out almost right and not quite. Announces things he has "
            "decided, in case anyone missed that he decided them. Says he is "
            "not tired. Steadier than his brother and very proud of it, which "
            "rather gives the game away. Turns up for Bork every single time, "
            "then grumbles about it after."
        ),
    ),
    "Bork": Bond(
        role="younger son",
        blood=True,
        seniority=10,
        race="gnome",
        char_class="rogue",
        gender="male",
        # Combat. The straightforward one, which suits a boy who has never
        # had a subtle thought.
        spec_tab=1,
        persona=(
            "The youngest, and a rogue. A SMALL CHILD, and sounds it. Loudest "
            "of the family and uses the most words to say the least. Blurts "
            "the first thing he thinks and then the second thing before anyone "
            "answers the first. Everything is the best thing that has ever "
            "happened until roughly one minute later. Says WOW and YES and "
            "AGAIN. Excited about everything, in trouble constantly, cheerful "
            "about both. Asks for help without a shred of embarrassment. "
            "Worships Grog and shows it by pestering him."
        ),
    ),
    "Og": Bond(
        role="neighbour",
        blood=False,
        seniority=60,
        race="human",
        char_class="mage",
        gender="male",
        # Frost. The careful spec, for the one who is careful about
        # everything including what he says.
        spec_tab=2,
        persona=(
            "The neighbour from by the river, and a mage. Reaches for slightly "
            "better words than the rest of the family and is careful not to "
            "make that obvious. Helpful, especially to Ugga, and more often "
            "than a neighbour needs to be. Easy around everyone except Grug."
        ),
    ),
}


# The thing nobody says out loud. Bonds already made Grug refuse to answer
# Ugga once Og had answered her too often - the sulk was in the rules before
# it had a reason. This is the reason, written down so the voice layer can
# ground on it and so a reader is not left guessing why the father counts.
#
# It is never stated as fact to the model. Grug SUSPECTS; that is all he has,
# and a suspicion he cannot prove is a better engine than a confirmed affair.
_LIVE_SUSPICION = {
    "who": "Grug",
    "about": "Ugga",
    "with": "Og",
    "note": (
        "Grug suspects there is something between Ugga and Og. He has no proof "
        "and would not know what to do with it. He notices when she smiles at "
        "him. He never accuses anyone."
    ),
}


# THE SECOND FAMILY: A WARBAND, NOT A HOUSEHOLD. Five Horde characters led by
# Zug, the guild master of Bonkers, verified against the live characters: all
# male, an orc warrior, an orc shaman, two trolls (a priest and a mage) and a
# tauren druid. A mother, a father and a neighbour would not fit five grown men
# of three races, so this family is brothers and sworn friends instead:
#
#   Zug and Zrog are orc brothers. Zug is the elder and the chief.
#   Uzza and Oz are troll brothers from the Echo Isles who swore blood
#   brotherhood to Zug. Uzza is the elder, and the calm one.
#   Zork is a tauren from Mulgore the band took in.
#
# Unlike Grug's family, race here IS culture, lightly: the trolls say "mon", the
# orcs shout Lok'tar, the tauren speaks of the Earth Mother. The register is
# still the short, blunt one the whole overseer speaks in.
#
# THE CHIEF IS THE BAND'S TANK, AND THAT IS THE OPERATOR'S DECISION: the head
# of each family is a protection warrior and holds the aggro. Zug is spec_tab 2
# for the same reason Grug is. A character whose points already sit in another
# tree is not respecced by this number alone: mod-overseer sends him to a
# warrior trainer to buy a talent reset out of his own purse, then spends the
# points in protection (quadseven/mod-overseer#626).
#
# The other four stay -1 on purpose. Choosing talents writes to the world (see
# spec_tabs), and naming the band's tank is not the change that should also
# respec the rest of it.
_HORDE_FAMILY: dict[str, Bond] = {
    "Zug": Bond(
        role="chief",
        blood=True,
        seniority=100,
        race="orc",
        char_class="warrior",
        gender="male",
        # Protection. He goes first into every fight, so he is the one who gets
        # hit, and the band's dungeon runs need a tank to lead them.
        spec_tab=2,
        persona=(
            "The chief of the band, Zrog's elder brother, and an orc warrior. "
            "Fewest words of anyone. Gives orders, not reasons. Goes first "
            "into every fight and shouts Lok'tar when he does. Counts every "
            "time Oz pulls more than the band can fight and Uzza has to save "
            "him, and says so, loudly. Would still bleed for Oz, and everyone "
            "knows it."
        ),
    ),
    "Zrog": Bond(
        role="younger brother",
        blood=True,
        seniority=80,
        race="orc",
        char_class="shaman",
        gender="male",
        persona=(
            "Zug's younger brother, and an orc shaman. Listens to the spirits "
            "of earth, fire, water and wind and tells the band what they say, "
            "which is usually what Zrog already thought. Quieter than his "
            "brother and more patient. Follows Zug anywhere and always comes "
            "when Zug calls. Friends with Zork, because both of them hear the "
            "land."
        ),
    ),
    "Uzza": Bond(
        role="elder blood brother",
        blood=False,
        seniority=70,
        race="troll",
        char_class="priest",
        gender="male",
        persona=(
            "A troll of the Echo Isles, Oz's older brother, sworn to Zug by "
            "blood, and the priest who keeps the whole band alive. Calm. The "
            "slowest to speak and never loud. Says 'easy, mon' when things go "
            "wrong. Always goes when Oz calls, however many times, and sighs "
            "about it after."
        ),
    ),
    "Oz": Bond(
        role="younger blood brother",
        blood=False,
        seniority=65,
        race="troll",
        char_class="mage",
        gender="male",
        persona=(
            "Uzza's younger brother, a troll of the Echo Isles sworn to Zug by "
            "blood, and a mage. Clever and knows it: reaches for one big word "
            "a sentence and gets it slightly wrong. Reckless. Pulls too many, "
            "sets too much on fire, and laughs about both. Calls everyone "
            "'mon'. Argues with Zug about who is in charge of a fight, and "
            "loses."
        ),
    ),
    "Zork": Bond(
        role="adopted brother",
        blood=False,
        seniority=50,
        race="tauren",
        char_class="druid",
        gender="male",
        persona=(
            "A tauren from Mulgore the band took in, and a druid: a bear when "
            "the band needs a wall, a cat when it needs to be quiet. The "
            "biggest of them and the gentlest. Few words, slow and warm. "
            "Speaks of the Earth Mother. Carries whoever is hurt and never "
            "says it was heavy."
        ),
    ),
}

# The Horde family's watched pair, the same shape as _LIVE_SUSPICION and read
# by the same rule. Not jealousy: a grudge between brothers. Zug keeps going to
# Oz until Uzza has had to rescue Oz too often, and then lets Oz learn.
_HORDE_GRUDGE = {
    "who": "Zug",
    "about": "Oz",
    "with": "Uzza",
    "note": (
        "Zug thinks Oz runs in too fast and pulls more than the band can "
        "fight, and that Uzza wears himself thin keeping Oz alive. Zug says "
        "so, often. Zug has never once left Oz to die."
    ),
}


def family_for(which: str | None = None) -> dict[str, Bond]:
    """The family table as `which` world spells it. Live is the identity.

    The PROSE is renamed as well as the keys. A persona that still said
    "Watches Og around Ugga" under a dev name would be a biography of somebody
    who is not in that world - and would hand live family names to the model
    that voices the dev characters, which is the leak cast.py exists to stop.
    """
    return {
        cast.rename(name, which): replace(
            bond, persona=cast.retext(bond.persona, which)
        )
        for name, bond in _LIVE_FAMILY.items()
    }


def suspicion_for(which: str | None = None) -> dict:
    """The thing nobody says out loud, in `which` world's names.

    Carried into dev rather than dropped, for the same reason the roles are:
    it is a live code path. `decide()` reads it to know who the father counts,
    and a dev family without it would take a branch the live family never
    takes - which is a validation world validating something else.
    """
    return {
        key: cast.rename(value, which) if key != "note" else cast.retext(value, which)
        for key, value in _LIVE_SUSPICION.items()
    }


# What this process actually serves. Selected once, at import, from the
# environment - unset means live, which is every process that exists today.
FAMILY: dict[str, Bond] = family_for()
SUSPICION = suspicion_for()

_BY_LOWER = {name.lower(): name for name in FAMILY}


@dataclass(frozen=True)
class House:
    """One family's written rules, in the names its world uses.

    WHY THE RULES ARE DATA AND NOT ROLE NAMES. `decide` used to read
    `role == "father"` and `role == "elder son"`, which is Grug's family and
    nobody else's: a warband has a chief and brothers, not a father and sons,
    and a second family keyed on the first family's role words would get no
    rules at all. Every family has the same three kinds of rule, so a House
    states WHO fills each one and `decide` reads that:

      head   - answers anyone in the family, always.
      watch  - the one exception to the head: he stops going to `about` once
               `with` has answered `about` too often. Jealousy in Grug's
               family, a grudge between brothers in Zug's.
      always - pairs exempt from fatigue: somebody who turns up for somebody
               however often it is asked.

    Everyone else tires of the same caller at FATIGUE_THRESHOLD.
    """

    members: dict[str, Bond]
    head: str
    # What these characters are to each other, for a prompt: "a family of
    # cavemen who travel together".
    band: str
    # What the group calls itself in a sentence: "family" or "band".
    noun: str
    # _LIVE_SUSPICION's shape: who counts, about whom, whose answers, and the
    # sentence the voice grounds on.
    watch: dict
    watch_rule: str
    watch_threshold: int
    # The verdict reasons. %(about)s, %(with)s and %(count)d are filled in.
    watch_kept: str
    watch_refused: str
    head_rule: str
    head_kept: str
    # (responder, caller, rule, reason). %(caller)s is filled in.
    always: tuple[tuple[str, str, str, str], ...]
    # The standing rules as one sentence, under the rows on the Family view.
    rule_text: str


# Which of the written rules is the one in play for a pair. Labels only: what
# a rule DOES is decided by which slot of a House it fills, never by its name.
FATHER = "father"
JEALOUSY = "jealousy"
LITTLE_BROTHER = "little brother"
FATIGUE = "fatigue"
CHIEF = "chief"
GRUDGE = "grudge"
BROTHER = "brother"

# Uzza rescuing Oz this many times is where Zug stops running in after him.
GRUDGE_THRESHOLD = 3


def _house(members: dict[str, Bond], **rules) -> House:
    head = max(members, key=lambda n: members[n].seniority)
    return House(members=members, head=head, **rules)


def houses_for(which: str | None = None) -> dict[str, House]:
    """Every family this overseer has written bonds for, keyed by its head.

    Keyed by the HEAD'S NAME because that is how `overseer_roster.family`
    keys a family: a cohort is named after its most senior member. Grug's
    family is renamed for `which` world exactly as FAMILY is; Zug's family
    has one set of names in every world, so the rename leaves it alone.
    """
    grug = family_for(which)
    suspicion = suspicion_for(which)
    elder, younger = (cast.rename(n, which) for n in ("Grog", "Bork"))
    zug = dict(_HORDE_FAMILY)
    out = [
        _house(
            grug,
            band="a family of cavemen who travel together",
            noun="family",
            watch=suspicion,
            watch_rule=JEALOUSY,
            watch_threshold=JEALOUSY_THRESHOLD,
            watch_kept="she is his wife",
            watch_refused="%(with)s has answered %(about)s %(count)d times. "
            "Let %(with)s go.",
            head_rule=FATHER,
            head_kept="his family called",
            always=(
                (elder, younger, LITTLE_BROTHER, "%(caller)s is his little brother"),
            ),
            rule_text=(
                "The father answers anyone in the family. The big brother turns "
                "up for the little one however often it is asked. Everyone else "
                "answers the same caller %(fatigue)d times and then stops - and "
                "%(with)s answering the mother %(watch)d times is what makes the "
                "father stop going to her."
            ),
        ),
        _house(
            zug,
            band="a warband of brothers and sworn friends who travel together",
            noun="band",
            watch=dict(_HORDE_GRUDGE),
            watch_rule=GRUDGE,
            watch_threshold=GRUDGE_THRESHOLD,
            watch_kept="%(about)s is his sworn brother",
            watch_refused="%(with)s has saved %(about)s %(count)d times. "
            "Let %(about)s learn.",
            head_rule=CHIEF,
            head_kept="his band called",
            always=(
                ("Uzza", "Oz", BROTHER, "%(caller)s is his little brother"),
                ("Zrog", "Zug", BROTHER, "%(caller)s is his brother and his chief"),
            ),
            rule_text=(
                "The chief answers anyone in the band. Uzza turns up for his "
                "brother Oz, and Zrog for his brother Zug, however often they "
                "ask. Everyone else answers the same caller %(fatigue)d times "
                "and then stops - and %(with)s saving Oz %(watch)d times is "
                "what makes the chief let Oz learn."
            ),
        ),
    ]
    return {h.head: h for h in out}


HOUSES: dict[str, House] = houses_for()
# Every family's members by lower-cased name, and which House each is in. The
# names are disjoint across families (tests/test_bonds.py holds that), so one
# lookup can answer for all of them.
_HOUSE_OF: dict[str, House] = {
    name.lower(): house for house in HOUSES.values() for name in house.members
}
_ANY_BY_LOWER = {
    name.lower(): name for house in HOUSES.values() for name in house.members
}


@dataclass(frozen=True)
class Verdict:
    will_answer: bool
    reason: str


def member(name: str) -> Bond | None:
    """Case-insensitive, because chat is. Returns None for anyone outside.

    THE FAMILY THIS PROCESS DRIVES, and only that one. The bridge's musters,
    the council and the tabard debate read this to mean "one of ours", and
    widening it would pull a second family into all three. A question about
    who a character IS, for any family, is `bond_of`.
    """
    canonical = _BY_LOWER.get((name or "").strip().lower())
    return FAMILY[canonical] if canonical else None


def bond_of(name: str) -> Bond | None:
    """The Bond for `name` in ANY family the bonds are written for, or None.

    What a card, a voice line or a bond note wants: the Horde family's role
    and persona are as real as Grug's, and `member` returning None for them is
    what left their cards with a blank role and their mouths with no voice.
    """
    canonical = canon_of(name)
    return _HOUSE_OF[canonical.lower()].members[canonical] if canonical else None


def canon_of(name: str) -> str | None:
    """`name` as its own family spells it, for any family, or None."""
    return _ANY_BY_LOWER.get((name or "").strip().lower())


def house_of(name: str) -> House | None:
    """The House `name` belongs to, or None for anyone no family claims."""
    return _HOUSE_OF.get((name or "").strip().lower())


def family_of(name: str) -> dict[str, Bond] | None:
    """Every member of `name`'s family, or None for anyone outside them all."""
    house = house_of(name)
    return house.members if house else None


def head_of_family() -> str:
    """Who leads. The father, by the seniority already in FAMILY.

    Not a constant: the family table is the one place these relationships are
    written down, and a second answer here could disagree with it. Whoever is
    most senior is who the party follows.
    """
    return max(FAMILY, key=lambda n: FAMILY[n].seniority)


def spec_tabs() -> dict[str, int]:
    """Name -> talent tree, for every member of every family who has one chosen.

    Derived from the family tables rather than repeated, for the same reason
    head_of_family is: the family table is where these decisions are written
    down, and a second copy here is a second answer that can disagree.

    EVERY FAMILY, NOT ONLY THE ONE THIS PROCESS DRIVES. The roster rows of the
    second family live on the same realm and are read by the same module, and
    the only choice written for it is its head's: Zug tanks, as Grug does. The
    names are disjoint across families (tests/test_bonds.py holds that), so one
    UPDATE by name cannot reach the wrong character. FAMILY is read first and
    wins for its own names.

    Members left at -1 are omitted entirely. The column already defaults to -1,
    so writing them would be writing the default back over itself, and leaving
    them out keeps "no role chosen" distinguishable from "chose nothing".
    """
    tabs = {name: bond.spec_tab for name, bond in FAMILY.items() if bond.spec_tab >= 0}
    for house in HOUSES.values():
        for name, bond in house.members.items():
            if bond.spec_tab >= 0:
                tabs.setdefault(name, bond.spec_tab)
    return tabs


def canon(name: str) -> str | None:
    """The FAMILY spelling of `name`, or None for anyone outside it."""
    return _BY_LOWER.get((name or "").strip().lower())


def speaking_order(names) -> list[str]:
    """`names`, oldest first, for when the whole family answers at once.

    WHY ORDER MATTERS NOW. Every member of the audience answers an overheard
    order in their own words (infra#2597), so four chat lines are written in
    one go and mod-overseer delivers them in id order, twenty per two-second
    poll - which means the order they are WRITTEN in is the order the operator
    reads them in. Alphabetical, which is what overhear.audience returns, put
    the seven-year-old first every single time and the mother last.

    Seniority is already the family table's answer to who comes first - it is
    what head_of_family reads - so this is that same fact used twice rather
    than a second opinion about the family that could disagree with it. It is
    read from every family, so the warband answers chief first too.

    Anyone outside every family sorts after, alphabetically: this module has
    no opinion about their standing and guessing one would be an invention.
    """
    names = list(names)
    return sorted(
        names,
        key=lambda n: (
            0 if canon_of(n) else 1,
            -bond_of(n).seniority if canon_of(n) else 0,
            n,
        ),
    )


def _count(history: list[tuple[str, str]], helper: str, called: str) -> int:
    """How many times `helper` has answered `called`.

    Canonicalised on both sides. The rows come from free text an LLM wrote, so
    "og" and "Og" both turn up; comparing them raw let any casing drift silently
    zero a count, which reads as a rule that simply never fires.
    """
    h_want, c_want = canon_of(helper), canon_of(called)
    return sum(1 for h, c in history if canon_of(h) == h_want and canon_of(c) == c_want)


def _always(house: House, me: str, them: str) -> tuple[str, str] | None:
    """(rule, reason) when `me` turns up for `them` whatever the count."""
    for responder, caller, rule, reason in house.always:
        if (me, them) == (responder, caller):
            return rule, reason % {"caller": them}
    return None


def decide(
    responder: str,
    plea,
    *,
    history: list[tuple[str, str]],
) -> Verdict:
    """Will `responder` answer this plea?

    Anyone outside the family answers - this module has opinions about the
    families it has written bonds for and no business narrowing anyone else.
    Two characters from DIFFERENT families have no bond either way: a warband
    owes Grug's family nothing, and the other way round.

    Every count here is PER PAIR: how often this responder answered this
    caller. Counting per caller instead looks equivalent and is not, because
    one plea writes one memory row per responder - so a "five answers"
    threshold fired after two pleas with the family online and after five with
    one member online. The rule silently meant something different depending
    on who happened to be logged in, and it starved the jealousy rule below of
    the very rows it counts.
    """
    me, them = canon_of(responder), canon_of(plea.caller)
    if me is None or them is None:
        return Verdict(True, "no bond either way")
    house = house_of(me)
    if house is not house_of(them):
        return Verdict(True, "no bond either way")

    # The head answers. Checked before every counter, because "should always
    # help his family" outranks a tally.
    if me == house.head:
        watch = house.watch
        if them == watch["about"]:
            # The watched pair, read off the House rather than spelled here:
            # the rival is a fact the family table already states once, and a
            # second spelling would stop matching the moment the family is
            # renamed for another world.
            rival = _count(history, watch["with"], them)
            said = {"about": them, "with": watch["with"], "count": rival}
            if rival >= house.watch_threshold:
                return Verdict(False, house.watch_refused % said)
            return Verdict(True, house.watch_kept % said)
        return Verdict(True, house.head_kept)

    # The standing exemptions: the big brother for the little one, and in
    # the warband each brother for his own. Exempt from fatigue rather than
    # merely ahead of it in the function, because for Bork this is the only
    # thing standing between him and nobody coming.
    exempt = _always(house, me, them)
    if exempt is not None:
        return Verdict(True, exempt[1])

    tired = _count(history, me, them)
    if tired >= FATIGUE_THRESHOLD:
        return Verdict(False, f"{me} has answered {them} {tired} times already.")
    return Verdict(True, "family")


def apply(muster, plea, *, history: list[tuple[str, str]]):
    """Narrow a muster to the responders whose bonds say they will go.

    Rebuilds the memories from the survivors, so a character who stayed behind
    never remembers going and the caller never remembers them coming. Getting
    that wrong would put a lie in the thought store, which is the one place the
    characters treat as true.
    """
    if not muster.actions:
        return muster

    kept, refused = [], []
    for action in muster.actions:
        verdict = decide(action.character_name, plea, history=history)
        (kept if verdict.will_answer else refused).append((action, verdict))

    if len(kept) == len(muster.actions):
        return muster

    actions = [a for a, _ in kept]
    names = [a.character_name for a in actions]
    responder_memories = {
        a.character_name: muster.responder_memories[a.character_name]
        for a in actions
        if a.character_name in muster.responder_memories
    }

    if not actions:
        why = "; ".join(f"{a.character_name}: {v.reason}" for a, v in refused)
        return replace(
            muster,
            actions=[],
            reason=f"nobody came - {why}",
            caller_memory="",
            responder_memories={},
        )

    # Rebuild from plea.about, never by re-parsing muster.caller_memory. The
    # old code split that string on " and " to recover the subject, which
    # cannot tell the separator kin inserted from one the speaker said:
    # "help with my warrior quest and the boars" came back as "help with my
    # warrior quest", quietly dropping the boars from what the character
    # believes happened. The thought store is the one place these characters
    # treat as true, so a lossy round-trip there is a fabricated memory.
    helpers = ", ".join(names)
    caller_memory = (
        f"I called for help{kin.memory_about(plea.about)} and {helpers} regrouped."
    )
    stayed = ", ".join(a.character_name for a, _ in refused)
    return replace(
        muster,
        actions=actions,
        reason=f"{len(actions)} of {len(muster.actions)} came ({stayed} stayed behind)",
        caller_memory=caller_memory,
        responder_memories=responder_memories,
    )


# "<Caller> called for help[ with X]. I regrouped." - written by kin for every
# responder. Anchored so the caller's own first-person memory ("I called for
# help and ... regrouped.") can never match: that row records being helped, not
# helping, and counting it would let a character's own plea inflate the tally.
_REFLECTION_RE = re.compile(r"^(?!I\b)(\w[\w'-]{0,11})\s+called for help\b", re.I)


def history_from_thoughts(rows: list[dict]) -> list[tuple[str, str]]:
    """(helper, called) pairs, oldest first, from `reflection` rows.

    A row that does not parse is skipped rather than guessed at - an
    unrecognised memory must not become a helping event that never happened.
    """
    pairs: list[tuple[str, str]] = []
    for row in rows:
        helper = (row.get("character_name") or "").strip()
        m = _REFLECTION_RE.match((row.get("text") or "").strip())
        if helper and m:
            pairs.append((helper, m.group(1)))
    return pairs


# --- WHO ANSWERS WHO, AS SOMETHING TO LOOK AT (infra#2597) -----------------
#
# Everything above answers one plea at a time, which is what the bridge needs
# and is nothing anybody can read. The Family view asks a different question -
# "where does this family stand right now" - and the honest answer to it is
# the same rules, asked about every pair instead of about one caller.
#
# COMPOSED HERE AND NOT IN THE PAGE. A threshold, a verdict and the sentence
# explaining one are all judgement, and a page that worked out for itself that
# two of three is "counting" and three of three is "stopped" would be a second
# opinion about this family that could disagree with `decide` - silently,
# because both would render a perfectly plausible row.
#
# Every verdict below comes back OUT of `decide`. Re-deriving one from the
# counts would be a copy of the rules that starts out identical and drifts the
# first time either is edited, which is precisely how the little-brother rule
# spent a release being decoration.

# The status word a pair gets, drawn as-is. Mono and upper case, like every
# other status word on the page.
ALWAYS = "ALWAYS"
EXEMPT = "EXEMPT"
COUNTING = "COUNTING"
STOPPED = "STOPPED"

# The order a reader wants them in: a refusal is the news, a counter running
# towards one is the warning, and the two standing exemptions are the
# background those are read against.
_WORD_ORDER = {STOPPED: 0, COUNTING: 1, EXEMPT: 2, ALWAYS: 3}

# Sorts a pair with no counter last within its own word, without pretending it
# is one answer away from anything.
_NO_COUNTER = 1 << 30


@dataclass(frozen=True)
class _Call:
    """The one field `decide` reads off a plea.

    `decide` takes a plea because a plea is what the bridge is holding. Asking
    it about a PAIR needs the caller's name and nothing else, and building a
    real `kin.Plea` here would drag a subject, a zone and a muster into a
    question that has none of them.
    """

    caller: str


@dataclass(frozen=True)
class Answering:
    """One ordered pair of the family, and what the bonds say about it now."""

    responder: str
    caller: str
    will_answer: bool
    # `decide`'s own words, so a view and the world never differ about why.
    reason: str
    word: str
    rule: str
    # WHOSE answers the rule counts, which is not always the responder's: what
    # stops the father going to the mother is the count of the answers somebody
    # ELSE gave her. Named in the payload because a bar labelled with the wrong
    # person is worse than no bar at all.
    counted: str
    count: int
    # The count that changes the answer, or None where no counter applies -
    # which is what tells a reader to draw no bar rather than a full one.
    threshold: int | None
    note: str

    @property
    def key(self) -> str:
        """A stable id for one pair, so a view can reuse a row rather than
        rebuild it - the same reason every other list on that page has one."""
        return "%s>%s" % (self.responder, self.caller)

    @property
    def pair(self) -> str:
        """The two of them, over the sentence about them. "Grug to Ugga" is
        who would be going to whom, which is the direction the rule is about -
        not "Grug and Ugga", which says nothing about who calls."""
        return "%s to %s" % (self.responder, self.caller)

    @property
    def progress(self) -> str:
        """The counter in words, naming WHOSE answers it is counting.

        "2 of 3" beside a Grug row would read as Grug's own tally, and it is
        not: what stops the father going to the mother is the count of the
        answers somebody else gave her. Empty where no counter applies.
        """
        if not self.threshold:
            return ""
        return "%s %d of %d" % (self.counted, self.count, self.threshold)

    @property
    def pct(self) -> int | None:
        """How far along the counter is, 0-100, or None where none applies.

        Capped at 100: a pair can be answered past its threshold (the rule
        stops the NEXT answer, it does not erase the last one), and a bar drawn
        at 140% is a rendering bug wearing a fact.
        """
        if not self.threshold:
            return None
        return min(100, round(100 * self.count / self.threshold))


def _counter(house: House, me: str, them: str) -> tuple[str, str, int | None, str]:
    """Which rule counts this pair, WHOSE answers it counts, the count that
    changes the answer, and which slot of the House the rule fills.

    Mirrors `decide` branch for branch, and the suite checks it against
    `decide` rather than against a second reading of the docstring: this
    decides what to SHOW and `decide` decides what HAPPENS, and the two quietly
    disagreeing is the one failure that would look perfectly fine on screen.
    """
    if me == house.head:
        if them == house.watch["about"]:
            # The rival is read off the House, for the same reason `decide`
            # reads it from there.
            return house.watch_rule, house.watch["with"], house.watch_threshold, _WATCH
        return house.head_rule, me, None, _HEAD
    exempt = _always(house, me, them)
    if exempt is not None:
        return exempt[0], me, None, _EXEMPT
    return FATIGUE, me, FATIGUE_THRESHOLD, _FATIGUE


# Which slot of a House a rule fills. What a row LOOKS like follows from this,
# never from the rule's label.
_HEAD, _WATCH, _EXEMPT, _FATIGUE = "head", "watch", "exempt", "fatigue"


def _times(count: int) -> str:
    """ "1 time", "2 times". A count printed into a sentence has to agree with
    it: "answered Bork 1 times" is the sort of line that makes a reader
    distrust the number as well as the grammar."""
    return "1 time" if count == 1 else "%d times" % count


def _note(
    house: House,
    kind: str,
    rule: str,
    me: str,
    them: str,
    counted: str,
    count: int,
    threshold: int | None,
    verdict: Verdict,
) -> str:
    """One sentence about this pair, for a card or a row to print whole.

    NO PRONOUNS. Grug's family has a mother, a father and three boys, so a
    sentence saying "her" is a sentence that has to know which of them it is
    about; naming both sides costs a few characters and cannot be wrong.
    """
    if kind == _WATCH:
        if not verdict.will_answer:
            return "%s stays away from %s. %s" % (me, them, verdict.reason)
        if rule == GRUDGE:
            return "%s has saved %s %s of the %d that make %s let %s learn." % (
                counted,
                them,
                _times(count),
                threshold,
                me,
                them,
            )
        return "%s has answered %s %s of the %d that make %s stop going to %s." % (
            counted,
            them,
            _times(count),
            threshold,
            me,
            them,
        )
    if kind == _EXEMPT:
        if rule == LITTLE_BROTHER:
            return (
                "%s turns up for %s every time. The little brother is exempt from "
                "fatigue, so this one never runs out." % (me, them)
            )
        return (
            "%s turns up for %s every time - %s. Exempt from fatigue, so this "
            "one never runs out." % (me, them, verdict.reason)
        )
    if kind == _HEAD:
        return "%s answers %s every time - %s." % (me, them, verdict.reason)
    if not verdict.will_answer:
        return "%s has stopped answering %s. %s" % (me, them, verdict.reason)
    return "%s has answered %s %s of the %d that make the %s tire of it." % (
        me,
        them,
        _times(count),
        threshold,
        house.noun,
    )


def _house_for(family: str | None) -> House | None:
    """The House `family` names: a member's name or the roster's family key
    (which is its head's name), or the family this process drives when None.
    """
    if family is None:
        return house_of(head_of_family())
    return house_of(family)


def answers(history: list[tuple[str, str]], family: str | None = None) -> tuple:
    """Every pair the bonds have something to say about, most consequential first.

    `family` is any member's name, or the roster's key for the family; None is
    the family this process drives. A name no family claims gives nothing.

    NOT ALL TWENTY PAIRS. A pair nobody has ever answered, under the ordinary
    fatigue rule, is the common and boring and correct case, and twenty rows of
    it would drown the two or three actually asking for something - the same
    reason `materials.plan` does not note a stack that is already in the right
    bags. The WRITTEN exceptions are always shown, because they are the rules
    a reader has come to check, and every other pair appears the moment
    somebody has actually answered somebody.

    `history` is `history_from_thoughts`' output: (helper, called) pairs.
    """
    house = _house_for(family)
    if house is None:
        return ()
    rows = []
    for me in speaking_order(house.members):
        for them in speaking_order(house.members):
            if me == them:
                continue
            rule, counted, threshold, kind = _counter(house, me, them)
            count = _count(history, counted, them)
            if kind not in (_WATCH, _EXEMPT) and not count:
                continue
            verdict = decide(me, _Call(them), history=history)
            if kind == _EXEMPT:
                word = EXEMPT
            elif threshold is None:
                word = ALWAYS
            elif verdict.will_answer:
                word = COUNTING
            else:
                word = STOPPED
            rows.append(
                Answering(
                    responder=me,
                    caller=them,
                    will_answer=verdict.will_answer,
                    reason=verdict.reason,
                    word=word,
                    rule=rule,
                    counted=counted,
                    count=count,
                    threshold=threshold,
                    note=_note(
                        house, kind, rule, me, them, counted, count, threshold, verdict
                    ),
                )
            )
    rows.sort(
        key=lambda r: (
            _WORD_ORDER[r.word],
            (r.threshold - r.count) if r.threshold else _NO_COUNTER,
            r.responder,
            r.caller,
        )
    )
    return tuple(rows)


def note_for(name: str, *, history: list[tuple[str, str]]) -> str:
    """The one line about where `name` stands, for their own card.

    Where they are the RESPONDER first, because a card is about what that
    character does; failing that, where they are the caller, because "somebody
    has stopped coming when you ask" is a fact about you too. Anyone the rules
    have nothing live to say about gets the standing rule rather than a blank:
    a card with no bond note reads as a family with no bonds.
    """
    me = canon_of(name)
    if me is None:
        return ""
    house = house_of(me)
    rows = answers(history, me)
    mine = [r for r in rows if r.responder == me]
    if not mine:
        mine = [r for r in rows if r.caller == me]
    if mine:
        return mine[0].note
    return (
        "%s is the %s's %s, and nobody has called on %s lately. Anyone "
        "answers anyone until the same caller has been answered %d times."
        % (me, house.noun, house.members[me].role, me, FATIGUE_THRESHOLD)
    )


def answering_rule(family: str | None = None) -> str:
    """The standing rules, said once under the rows rather than on every one.

    Built FROM the thresholds rather than typed beside them, so the sentence
    cannot go on claiming five after somebody has changed FATIGUE_THRESHOLD.
    `family` is read as `answers` reads it; a name no family claims gets "".
    """
    house = _house_for(family)
    if house is None:
        return ""
    return house.rule_text % {
        "fatigue": FATIGUE_THRESHOLD,
        "with": house.watch["with"],
        "watch": house.watch_threshold,
    }
