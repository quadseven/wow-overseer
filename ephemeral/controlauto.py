"""`submit --control auto`: the pure decisions (issue 3273).

Nothing here reads a registry, a cluster or a file the deploy side owns; the
caller hands in the history, a fix-presence function and a digest check, so a
fake history and a fake registry pin every branch.

A history entry is a dict: {"worldserver": ref, "dbimport": ref, "pin": sha,
"bridge": ref (optional), "bridge_commit": sha (optional)}. Entries are listed
newest first. The list is runner config, never a literal in this repository.
"""

import re

from . import confmerge

_SHA = re.compile(r"^[a-f0-9]{40}$")
_DIGEST_REF = re.compile(r"^[^\s@]+@sha256:[a-f0-9]{64}$")
_COMMENTED_KEY = re.compile(r"^\s*[#/]+\s*([A-Za-z][A-Za-z0-9_.]*)\s*=")


class AutoError(Exception):
    """No control image set can be chosen; the message says why."""


def pick_control(history, presence, resolves, bridge_fix=False):
    """The newest image set whose pin lacks the fix and whose digests resolve.

    presence(sha) -> "present" | "absent" | "unchecked".
    resolves(ref) -> True when the registry still has the digest.
    bridge_fix: the fix is in the bridge code, so the set is judged by its
    bridge_commit and the bridge image must resolve too.
    Returns the entry. Raises AutoError when none qualifies.
    """
    if not history:
        raise AutoError("the control history is empty")
    refs = ("worldserver", "dbimport") + (("bridge",) if bridge_fix else ())
    lacking = unresolved = 0
    for entry in history:
        commit = entry.get("bridge_commit" if bridge_fix else "pin")
        if not _SHA.match(str(commit or "")):
            continue
        if presence(commit) != "absent":
            continue
        lacking += 1
        got = [entry.get(r) for r in refs]
        if all(g and _DIGEST_REF.match(g) and resolves(g) for g in got):
            return entry
        unresolved += 1
    if not lacking:
        raise AutoError("no past image set lacks the fix")
    raise AutoError(
        f"{unresolved} past image set(s) lack the fix but their digests do not resolve"
    )


def dropped_keys(control_dist, override_text):
    """Override keys the control image's dist does not know, sorted.

    A key counts as known when the dist has it as a live line or as a
    commented `Key = value` default.
    """
    known = set(confmerge.parse(control_dist or ""))
    for line in (control_dist or "").splitlines():
        m = _COMMENTED_KEY.match(line)
        if m:
            known.add(m.group(1))
    return sorted(set(confmerge.parse(override_text or "")) - known)
