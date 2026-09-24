"""Who may contribute gold or items to the guild: only what was earned.

THE OPERATOR'S RULE (2026-09-24): "naturally earned only". Any guild member
may contribute, but only out of what it earned itself. Gold or items the
playerbots factory handed a character never flow to the guild, to the guild
master or to the guild bank.

WHAT MAKES A CHARACTER'S HOLDINGS EARNED. The module's `kind='naturalize'`
verbs (quadseven/mod-overseer#704) write one `overseer_naturalized` row per
character and part once a real run has done it:

  * A guild bot (a member that is not one of the families) was kitted by the
    factory: gear, gold, trade skills. Its `reset` part starts it over at level
    1 with no gold and no items, under the playerbots patch that grants it
    nothing afterwards. Everything it holds after that it earned. So a guild
    bot contributes once, and only once, it holds `reset`.
  * A family character earned its own gold, with one exception: the guild dues
    the factory-kitted guild bots mailed to the guild master. Its `gold` part
    (`discard-unearned-gold`) takes those out. So a family character that
    never took a dues letter contributes freely, and one that did contributes
    once it holds `gold`.

A LEDGER THAT CANNOT BE READ PROVES NOTHING. A realm whose table is missing
(the migration not applied yet) has reset nobody, so no guild bot contributes;
the family rule above still holds, because it does not need the table to say
who took dues.

PURE MODULE: rows in, a set and sentences out. The bridge reads the ledger and
the dues letters and passes them in.
"""

from __future__ import annotations

# The ledger's part names, as the module writes them.
RESET_PART = "reset"
GOLD_PART = "gold"


def parts_by_name(rows) -> dict:
    """name -> set of parts, from `overseer_naturalized` rows (name, part)."""
    parts: dict = {}
    for row in rows or ():
        name = str((row or {}).get("name") or "")
        part = str((row or {}).get("part") or "")
        if name and part:
            parts.setdefault(name, set()).add(part)
    return parts


def why_not(name, family_names, parts, dues_takers, ledger_readable=True) -> str:
    """Why `name` contributes nothing; "" when it may contribute."""
    name = str(name)
    held = (parts or {}).get(name, set())
    if name in {str(n) for n in family_names or ()}:
        if name in {str(n) for n in dues_takers or ()} and GOLD_PART not in held:
            return (
                "%s holds guild dues the factory-made members posted and has "
                "not had them taken out (naturalize discard-unearned-gold), "
                "so it contributes nothing" % name
            )
        return ""
    if not ledger_readable:
        return (
            "%s contributes nothing: the naturalize ledger cannot be read, "
            "so nobody has been reset to level 1" % name
        )
    if RESET_PART not in held:
        return (
            "%s contributes nothing: it has not been reset to level 1, so "
            "what it holds was handed to it" % name
        )
    return ""


def contributors(
    names, family_names, parts, dues_takers, ledger_readable=True
) -> frozenset:
    """The names among `names` whose gold and items were earned."""
    return frozenset(
        str(n)
        for n in names or ()
        if not why_not(n, family_names, parts, dues_takers, ledger_readable)
    )


def only_contributors(rows, eligible, key="name") -> list:
    """The rows whose `key` names a contributor, in their order."""
    allowed = {str(n) for n in eligible or ()}
    return [row for row in rows or () if str((row or {}).get(key) or "") in allowed]
