"""Which realm this page is showing, and what that realm is running.

WHY THIS EXISTS, AND WHY IT IS NOT A NICE-TO-HAVE. Three realms run this site's
module: a live one, a disposable one, and a small hardcore one. Until now the
only thing that told a reader which of them they were looking at was the
hostname the page came from, and those hostnames are being collapsed into one.
The Caddyfile that routes them says the stake out loud, about getting one word
wrong in a proxy target: it "does not fail - it serves the LIVE family's
positions under a hostname whose entire promise is that it is not production."

Once the hostname stops being the label, the page has to be. So this banner is
not decoration on the way to a URL change; it is the thing that makes the URL
change safe to do at all.

WHERE THE ANSWER COMES FROM, AND WHY IT COMES FROM THERE. Everything here is
read out of the realm's own database, alongside the data the rest of the page
renders. Not from the cluster, not from a manifest, and not from this process's
own configuration. That is a deliberate choice and it is the whole safety
argument: a site pointed at the wrong database renders the label of the world it
is actually reading. A label taken from anywhere else could come apart from the
data it sits above, and a label that can come apart from its data is exactly the
accident being designed out.

THE THREE SOURCES, IN DESCENDING ORDER OF WHAT THEY CAN TELL YOU:

  overseer_build     the module's own report: its version, the realm's identity
                     and kind, and the upstream commits it was built alongside.
                     The richest source and the only one that knows the realm
                     kind. Absent on a realm whose worldserver predates it.
  acore_world.version  AzerothCore writing down its own revision at startup.
                     Present on every realm that has ever started, with no
                     module involvement at all, which is what lets this banner
                     name the core on day one.
  acore_auth.realmlist  the realm's name as clients see it. Weakest, but it is
                     a real name from the real database, so a realm that has
                     reported nothing else can still be told apart from another.

PURE MODULE, the same seam as agenda.py and achievements.py: rows in, the
banner's JSON out. No MySQL, no clock of its own unless one is not handed to it.
The adapter's job is to turn a missing table into an empty list, and this
module's half of that contract is to say less rather than raise.

THE RULE UNDER EVERY DECISION HERE: an answer this page is not sure of renders
as an alarm, never as the reassuring one. There is no arrangement of missing
rows that produces a quiet banner over an unidentified realm.
"""
from __future__ import annotations

from datetime import datetime

# The three answers, named rather than spelled inline so the page can style them
# and the suite can assert on them without matching English. These strings are
# the module's contract with the worldserver: they are the exact values
# OverseerDecisions::RealmKind emits, and the C++ side normalises to them so
# that nothing here has to guess at a spelling.
PRODUCTION = "production"
NON_PRODUCTION = "non-production"
UNKNOWN = "unknown"

# What the banner actually says, in the largest text on the page.
#
# THE UNKNOWN CASE IS DELIBERATELY NOT NEUTRAL WORDING. "Unknown realm" reads
# like a shrug. The reader has to understand that the page cannot vouch for what
# they are looking at, which is a different and more urgent thing than the page
# not having the information.
LABELS = {
    PRODUCTION: "PRODUCTION",
    NON_PRODUCTION: "NOT PRODUCTION",
    UNKNOWN: "REALM NOT VERIFIED",
}

# The upstream components this banner names, in the order it names them, and
# under the names a reader would recognise from the pins file rather than under
# the environment variables that carried them.
#
# ORDER IS FIXED HERE RATHER THAN TAKEN FROM THE ROWS because the rows arrive
# from a table with no ordering worth trusting, and a list that reshuffles
# between polls is unreadable. A component the realm did not report is skipped,
# not rendered blank; a component it reported that is not in this list is
# appended after these, so a newer worldserver can add one without this file
# changing first.
UPSTREAM_ORDER = (
    "mod-playerbots",
    "mod-ollama-chat",
    "mod-dungeon-clear",
    "mod-ah-bot-plus",
)

# Rows in overseer_build that are not upstream components. Named so that the
# component list below is "everything else" and a fact added by a future module
# version shows up rather than being silently dropped.
NON_COMPONENT_NAMES = frozenset(
    {"module", "core", "core_pin", "realm", "realm_kind", "pins"})

# The verdict the module records on whether its declared pins describe the
# binary that is actually running. See the module's PinsVerdict.
PINS_MATCH = "match"
PINS_STALE = "stale"
PINS_UNKNOWN = "unknown"


def _iso(when) -> str | None:
    """A datetime as ISO text, or None. Anything else is treated as nothing.

    MySQL hands back a datetime for a TIMESTAMP column, but a realm mid-upgrade
    can hand back a string, and a zero timestamp arrives as None. None of those
    is worth an exception in the one banner that must always render.
    """
    if isinstance(when, datetime):
        return when.isoformat(sep=" ", timespec="seconds")
    return None


def _seconds(when, now: datetime) -> int | None:
    if not isinstance(when, datetime):
        return None
    return max(0, int((now - when).total_seconds()))


def _facts(build_rows: list[dict]) -> dict:
    """overseer_build's rows as a name -> row map.

    Rows arrive as name/value/source, which is the shape they have precisely so
    that a newer worldserver can report a fact this file has never heard of
    without breaking the read. A row missing its own name is skipped rather than
    crashing the banner.
    """
    out = {}
    for row in build_rows or ():
        name = (row.get("name") or "").strip()
        if name:
            out[name] = row
    return out


def _value(facts: dict, name: str) -> str:
    row = facts.get(name)
    if not row:
        return ""
    return (row.get("value") or "").strip()


def _revision(core_version: str) -> str:
    """The commit out of AzerothCore's own sentence, or "".

    The same extraction the module does in C++, and it has to agree with it:
    "AzerothCore rev. 47960183bb03+ 2026-08-28 ..." yields "47960183bb03". The
    trailing marker means the tree carried local modifications at build time,
    which is always true here because the build applies this project's patches.
    It is not part of the commit.

    Deliberately tolerant. A core that changes its banner one day gives an empty
    answer, and the banner then shows the whole sentence instead of a commit,
    which is a thinner answer rather than a wrong one.
    """
    marker = " rev. "
    at = core_version.find(marker)
    if at < 0:
        return ""
    tail = core_version[at + len(marker):]
    out = []
    for char in tail:
        if char in "0123456789abcdefABCDEF":
            out.append(char.lower())
        else:
            break
    revision = "".join(out)
    # Short enough to be a coincidence rather than a commit. Seven is the same
    # floor the module uses, and the two have to agree or a realm could show a
    # commit here that its own report considers unreadable.
    return revision if len(revision) >= 7 else ""


def _kind(facts: dict) -> str:
    """Which of the three answers this realm's own report supports.

    THE ONLY THING ON THIS PAGE THAT CHANGES ITS COLOUR, and it comes from one
    place: the module's report. Not from the realm's name, not from a
    name-to-kind table in this file, and not from this process's environment. A
    mapping kept here would be a second copy of a fact the realm already knows,
    free to drift from it, and drift in exactly this fact is the failure the
    banner exists to prevent.

    A realm that has not reported therefore has no kind, and gets UNKNOWN. So
    does a realm reporting a kind this file has never heard of: the page has no
    styling for a word it has not seen and would draw it as though it were safe.
    """
    kind = _value(facts, "realm_kind") or UNKNOWN
    return kind if kind in LABELS else UNKNOWN


def _identity(facts: dict, realmlist_rows: list[dict]) -> tuple:
    """(name, where it came from).

    The module's report first, the realm list second: the first is the name the
    deployment chose, and the second is a real name from the real database that
    is present on every realm today.
    """
    realm = _value(facts, "realm")
    if realm:
        return realm, "reported"
    for row in realmlist_rows or ():
        candidate = (row.get("name") or "").strip()
        if candidate:
            return candidate, "realmlist"
    return "", ""


def _core(facts: dict, version_rows: list[dict]) -> tuple:
    """(the core's own sentence, where it came from).

    acore_world.version by preference and the module's report only as a
    fallback, which is the OPPOSITE of the precedence used for the realm's
    identity. The reason is that acore_world.version is written by the CORE, at
    startup, with no module involved: it is present on a realm that has never
    run this module at all, and it cannot be left behind by a module that failed
    to rewrite its own report. For the one fact both of them know, the source
    that needs less to go right is the better one.
    """
    for row in version_rows or ():
        core = (row.get("core_version") or "").strip()
        if core:
            return core, "world"
    reported = _value(facts, "core")
    return (reported, "reported") if reported else ("", "")


def _upstreams(facts: dict) -> list[dict]:
    """The declared component commits, in a fixed order, with nothing dropped.

    Anything the realm reported that this file does not know about is appended
    after the known ones rather than skipped, so a newer worldserver can report
    a fifth component without this file changing first.
    """
    def entry(name: str) -> dict:
        return {"name": name, "value": _value(facts, name),
                "source": (facts[name].get("source") or "").strip()}

    known = [entry(name) for name in UPSTREAM_ORDER if _value(facts, name)]
    extra = sorted(name for name in facts
                   if name not in NON_COMPONENT_NAMES
                   and name not in UPSTREAM_ORDER
                   and _value(facts, name))
    return known + [entry(name) for name in extra]


def _warnings(kind: str, reported: bool, pins: str, facts: dict, core: str,
              core_source: str) -> list[str]:
    """Everything the reader has to be told, as full sentences.

    A list because more than one can be true at once, and full sentences rather
    than codes the page turns into English, for the same reason every other
    payload on this site arrives decided: a second implementation in JavaScript
    is a second implementation free to drift.
    """
    warnings = []
    if kind == UNKNOWN and not reported:
        warnings.append(
            "This realm has not reported a build, so this page cannot say "
            "whether it is production. Treat what you are seeing as live until "
            "it does.")
    elif kind == UNKNOWN:
        warnings.append(
            "This realm reported a build but did not say whether it is "
            "production. Treat what you are seeing as live until it does.")
    if pins == PINS_STALE:
        warnings.append(
            "The upstream commits below were declared for a different build "
            "than the one this realm is running, so they describe another "
            "image. Do not read them as fact.")
    # The realm's report naming a core that is not the core the world says it is
    # running. Both are written at startup by the same process, so this should
    # be impossible; if it happens, one of the two is left over from a previous
    # binary and everything derived from the report is suspect.
    reported_core = _value(facts, "core")
    if reported_core and core and core_source == "world" and reported_core != core:
        warnings.append(
            "The build this realm reported names a different core than the one "
            "the world is running, so the report is left over from an earlier "
            "worldserver.")
    return warnings


def _realm_line(realm: str, realm_source: str) -> str:
    if realm and realm_source == "reported":
        return realm
    if realm:
        return ("%s (name from the realm list; this realm has not reported its "
                "own identity)" % realm)
    return "this realm has not named itself"


def _build_line(reported: bool, module_version: str, core: str,
                core_revision: str, upstreams: list[dict], pins: str) -> str:
    if not reported:
        line = ("This realm has not reported a build, so its module version "
                "and upstreams are unknown.")
        if core:
            # The core is still worth printing, and on the day this ships it is
            # the ONLY thing that can be printed, because AzerothCore records
            # its own revision with no help from the module. It is also the fact
            # the realms most visibly disagree on.
            line += " The world itself reports core %s." % (core_revision or core)
        return line

    parts = ["module %s" % (module_version or "not reported"),
             "core %s" % (core_revision or core or "not reported")]
    # Twelve characters, the same abbreviation AzerothCore prints for itself, so
    # a reader can compare the two by eye without counting.
    parts += ["%s %s" % (item["name"], item["value"][:12]) for item in upstreams]
    if pins == PINS_STALE:
        parts.append("pins STALE")
    return "  |  ".join(parts)


def _reported_at(facts: dict):
    """When this realm last said any of it.

    The kind's row for preference, since that one is always written, and any
    other row as a fallback.
    """
    stamp = facts.get("realm_kind", {}).get("reported_at")
    if stamp is not None:
        return stamp
    for row in facts.values():
        if row.get("reported_at") is not None:
            return row["reported_at"]
    return None


def build_realm(build_rows: list[dict], version_rows: list[dict],
                realmlist_rows: list[dict], now: datetime | None = None) -> dict:
    """Rows in, the realm banner's JSON out.

    build_rows      overseer_build, any subset, in any order. EMPTY on a realm
                    whose worldserver predates the table, which is every realm
                    on the day this ships and is the case that matters most.
    version_rows    acore_world.version, which AzerothCore writes about itself.
    realmlist_rows  acore_auth.realmlist, for the realm's client-facing name.
    now             the clock, injectable so the suite can stand still.

    EVERY ONE OF THOSE MAY BE EMPTY, and all three empty is a valid input that
    must produce a banner rather than an exception. The adapter's guard is what
    turns a missing table into an empty list; this is the half of that contract
    that has to do something sensible with one.

    AN ASSEMBLY AND NOTHING ELSE. Every decision above answers one question and
    can be read on its own, which matters here more than it usually would: what
    this file has to be is obviously correct to somebody checking whether a live
    realm can possibly render as a safe one.
    """
    now = now or datetime.now()
    facts = _facts(build_rows)
    reported = bool(facts)

    kind = _kind(facts)
    realm, realm_source = _identity(facts, realmlist_rows)
    core, core_source = _core(facts, version_rows)
    core_revision = _revision(core)
    module_version = _value(facts, "module")
    pins = _value(facts, "pins") or (PINS_UNKNOWN if reported else "")
    upstreams = _upstreams(facts)
    warnings = _warnings(kind, reported, pins, facts, core, core_source)
    stamp = _reported_at(facts)

    return {
        "generated_at": _iso(now),
        "kind": kind,
        "label": LABELS[kind],
        "realm": realm,
        "realm_source": realm_source,
        "reported": reported,
        "reported_at": _iso(stamp),
        "reported_seconds": _seconds(stamp, now),
        "module_version": module_version,
        "core": core,
        "core_revision": core_revision,
        "core_source": core_source,
        "upstreams": upstreams,
        "pins": pins,
        "warnings": warnings,
        # The same warnings as one sentence for the page to print. Both are
        # returned on purpose: the list is what the suite asserts on, because a
        # test that matched the joined English would break on a comma, and the
        # string is what the page renders, because a page that joined them
        # itself would be deciding something.
        "warning_text": " ".join(warnings),
        "realm_line": _realm_line(realm, realm_source),
        "build_line": _build_line(reported, module_version, core, core_revision,
                                  upstreams, pins),
    }
