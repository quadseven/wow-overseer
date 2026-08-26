"""Which five this process is serving: the live family, or the dev one.

WHY THIS EXISTS. Everything the overseer knows about who these characters are
lives in two name-keyed tables - `bonds.FAMILY` (who they are to each other)
and `professions.ROSTER` (what each one's trade is). Both are keyed by the LIVE
five, because until infra#2791 there was only one world.

There are two worlds now, and the dev one had no family. Which meant every
experiment - a new quest aim, a strategy change, a profession errand, a party
re-leadership - was still run on Grug, Ugga, Grog, Bork and Og, in the world
Evan actually plays in. That is how five characters spent a day dead on a loop
in a level-45 zone, and how one of them was aimed into Redridge and killed.

WHAT THIS MODULE IS, AND WHAT IT DELIBERATELY IS NOT. It is a RENAMING, not a
second family. The dev five are the live five with different names on them:
same roles, same races, same classes, same specs, same trades, same seniority,
same suspicion. That is the point. A dev family with a different SHAPE would
exercise different code paths - a party with two healers takes a branch the
live party never takes - and a validation world that validates something else
is worse than no validation world, because it produces a green result.

So the only thing this file holds is a name map, and the only thing it does is
substitute. Every fact about the family stays in exactly one place.

WHY A SUBSTITUTION AND NOT A SECOND TABLE. A second table is a copy, and a copy
drifts: somebody adds a sixth persona clause to Grug, dev's Thak keeps the old
one, and the dev world quietly stops predicting the live one. There is no edit
that can make these two disagree, because there is only one set of facts.

HOW IT IS SELECTED. `OVERSEER_FAMILY` in the environment, read once at import.
Unset means live, and that is the load-bearing default: every process that
exists today - the Discord bridge, the map, the metrics emitter - sets nothing,
and must keep behaving exactly as it does. Only ../../oke/manifests/wow-dev
sets it, and its isolation suite asserts that.

THE ONE THING THE DEV NAMES MUST BE. Disjoint from the live names. Chained
substitution over an overlapping map corrupts (rename Grug->Grog and Grog->Bork
and the first output becomes the second's input), so the substitution below is
a SINGLE PASS with one alternation, and `_check()` refuses an overlapping map
outright rather than trusting the pass to survive one.
"""

from __future__ import annotations

import os
import re

LIVE = "live"
DEV = "dev"

ENV_VAR = "OVERSEER_FAMILY"

# The live five, in the order bonds.FAMILY declares them. Held here as well so
# that the substitution has something to match on without importing bonds -
# bonds imports THIS module, and the other way round is a cycle.
#
# Kept honest by tests/test_cast.py, which asserts this tuple is exactly
# `set(bonds.family_for(LIVE))`. A name added to the family and not here would
# silently pass through the rename unchanged - which in the dev world means a
# LIVE name on a dev character, the one outcome this whole file exists to stop.
LIVE_NAMES = ("Grug", "Ugga", "Grog", "Bork", "Og")

# The dev five. Cavemen, like the originals, and deliberately nothing like them
# to read: at a realm-select screen or in a log line, "Thak" is never a typo for
# "Grug". Checked 2026-08-26 against `acore_characters.characters` in BOTH
# namespaces - none of these five names, and none of the five uppercase account
# names they imply, existed on either realm.
#
#   Thak  <- Grug   father, human warrior, protection - the tank who leads
#   Muna  <- Ugga   mother, human priest, holy        - the healer
#   Durn  <- Grog   elder son, dwarf paladin, ret
#   Pik   <- Bork   younger son, gnome rogue, combat
#   Vek   <- Og     neighbour, human mage, frost
#
# The race/class pairs are the live ones unchanged, which is also what makes
# them known-legal: `playercreateinfo` has to have a row for each, and these
# five pairs demonstrably do, because the live family is made of them.
DEV_NAMES = {
    "Grug": "Thak",
    "Ugga": "Muna",
    "Grog": "Durn",
    "Bork": "Pik",
    "Og": "Vek",
}

_SETS: dict[str, dict[str, str]] = {
    # Identity. Spelled out as an empty map rather than as a special case in
    # every function, so the live path is the same code path as the dev one -
    # a "live" branch that skips the substitution is a branch that never gets
    # exercised by the world it protects.
    LIVE: {},
    DEV: DEV_NAMES,
}


def _check(mapping: dict[str, str]) -> dict[str, str]:
    """Refuse a name map that could corrupt a substitution.

    Overlap between the two sides is the failure: it makes the result depend on
    iteration order, and a single-pass regex would silently pick one. There is
    no reason to ever want it, so it is an error rather than a documented
    hazard.
    """
    collisions = set(mapping) & set(mapping.values())
    if collisions:
        raise ValueError(
            f"family rename map is not disjoint: {sorted(collisions)} appears "
            "on both sides. A name that is both an input and an output makes "
            "the substitution order-dependent."
        )
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("family rename map maps two names onto one")
    return mapping


for _which, _map in _SETS.items():
    _check(_map)


def selected(environ=None) -> str:
    """Which set this process serves. Unset, unknown or blank means live.

    UNKNOWN FALLS BACK TO LIVE ON PURPOSE, and it is worth saying why, because
    the opposite reflex - fail loudly on a typo - is usually right. Not here:
    the only processes that read this are the bridge, the map and the emitter,
    all of which set nothing at all today. A raise would turn a typo in a dev
    overlay into a crash-looping LIVE deployment the moment the value was ever
    templated somewhere shared. Falling back to live is the behaviour every
    caller already has.

    The dev side is protected differently and better: the wow-dev isolation
    suite asserts the rendered value is exactly `dev`, so a typo there is
    caught before it is applied rather than after.
    """
    environ = os.environ if environ is None else environ
    value = (environ.get(ENV_VAR) or "").strip().lower()
    return value if value in _SETS else LIVE


def names(which: str | None = None) -> dict[str, str]:
    """live name -> this set's name. Empty for the live set itself."""
    return dict(_SETS[which or selected()])


def _pattern(mapping: dict[str, str]):
    # \b on both sides so "Og" never matches inside another word, and a single
    # alternation so every name is replaced from the ORIGINAL text exactly once.
    # Longest-first is not strictly needed for today's names (none is a prefix
    # of another) and is done anyway, because the day one is, a shorter
    # alternative winning would be a silent partial rename.
    if not mapping:
        return None
    alternation = "|".join(sorted(map(re.escape, mapping), key=len, reverse=True))
    return re.compile(rf"\b({alternation})\b")


_PATTERNS = {which: _pattern(m) for which, m in _SETS.items()}


def rename(name: str, which: str | None = None) -> str:
    """This set's spelling of a live name. Anything unknown passes through.

    Passes through rather than raising because the callers are table builders
    and prose rewriters, and a name outside the family - a trainer, a zone, a
    stranger in a chat line - is an ordinary thing for them to be handed.
    """
    return names(which).get(name, name)


def retext(text: str, which: str | None = None) -> str:
    """Every live family name inside `text`, replaced. One pass.

    The family's facts are PROSE as much as they are fields: a persona says
    "Watches Og around Ugga", a trade reason says "Inscription runs on Ugga's
    herbs". Renaming the dict keys and leaving those sentences alone would give
    the dev family five biographies about five people who are not there - and
    would put live names in front of the LLM that voices the dev characters,
    which is exactly the leak this module exists to prevent.
    """
    which = which or selected()
    pattern = _PATTERNS[which]
    if pattern is None or not text:
        return text
    mapping = _SETS[which]
    return pattern.sub(lambda m: mapping[m.group(1)], text)


def rekey(mapping: dict, which: str | None = None) -> dict:
    """A name-keyed table, re-keyed into this set. Order preserved.

    Order matters: `professions.ORDER` and the family's declaration order are
    both read positionally by callers that assume a stable answer, and a table
    rebuilt in a different order is an answer that changes between restarts.
    """
    return {rename(key, which): value for key, value in mapping.items()}
