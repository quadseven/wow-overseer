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
_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_.]*")
_DIST_KEY = re.compile(r"^\s*#?\s*([A-Za-z][A-Za-z0-9_.]*)\s*=")
_PLAYERBOTS = "Playerbots."
_OLD_PLAYERBOTS = "AiPlayerbot."
_BOT_COUNTS = ("MinRandomBots", "MaxRandomBots")


class AutoError(Exception):
    """The control image selection or config could not be verified."""


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


def dist_keys(text):
    """Keys that seed-conf accepts, including single-# commented defaults."""
    return {
        match[1]
        for line in (text or "").splitlines()
        if (match := _DIST_KEY.match(line))
    }


def dropped_keys(control_dist, override_text):
    """Override keys the control image's dist does not know, sorted."""
    return sorted(confmerge.parse(override_text).keys() - dist_keys(control_dist))


def _inventory_groups(inventory, worldserver):
    if not isinstance(inventory, dict) or set(inventory) != {
        "worldserver",
        "platform",
        "groups",
    }:
        raise AutoError("dist_inventory needs worldserver, platform and groups")
    if inventory["worldserver"] != worldserver:
        raise AutoError("dist_inventory worldserver must match the selected digest")
    if inventory["platform"] != "linux/amd64":
        raise AutoError("dist_inventory platform must be linux/amd64")
    groups = inventory["groups"]
    if not isinstance(groups, dict) or groups.keys() - confmerge.FILES.keys():
        raise AutoError("dist_inventory groups must be known override groups")
    known = {}
    for group, keys in groups.items():
        if not isinstance(keys, list) or any(
            not isinstance(key, str) or not _KEY.fullmatch(key) for key in keys
        ):
            raise AutoError(f"dist_inventory {group} keys must be config key names")
        known[group] = set(keys)
        if len(known[group]) != len(keys):
            raise AutoError(f"dist_inventory {group} has duplicate keys")
    return known


def _rename_old_playerbots(text, keys, required, known):
    old_counts = {_OLD_PLAYERBOTS + name for name in _BOT_COUNTS}
    if not known & old_counts:
        return text, keys, required, False
    if known & {_PLAYERBOTS + name for name in _BOT_COUNTS}:
        raise AutoError("dist_inventory playerbots has both random bot key prefixes")

    renames = {
        key: _OLD_PLAYERBOTS + key.removeprefix(_PLAYERBOTS)
        for key in keys
        if key.startswith(_PLAYERBOTS)
    }
    collisions = keys.intersection(renames.values())
    if collisions:
        raise AutoError(
            "playerbots prefix would duplicate: " + ", ".join(sorted(collisions))
        )
    return (
        confmerge.rename_prefix(text, _PLAYERBOTS, _OLD_PLAYERBOTS),
        {renames.get(key, key) for key in keys},
        {renames.get(key, key) for key in required},
        True,
    )


def inventory_overrides(entry, files, required):
    """Control override files and fidelity deltas for the selected image."""
    worldserver = entry["worldserver"]
    groups = _inventory_groups(entry["dist_inventory"], worldserver)
    output = files.copy()
    deltas = []
    for group, text in sorted(files.items()):
        keys = set(confmerge.parse(text))
        if not keys:
            continue
        known = groups.get(group)
        if not known:
            raise AutoError(
                f"dist_inventory has no keys for active override group {group}"
            )
        protected = keys & required
        if group == "playerbots":
            text, keys, protected, renamed = _rename_old_playerbots(
                text, keys, protected, known
            )
            if renamed:
                deltas.append(
                    f"control arm: {worldserver} playerbots keys written as AiPlayerbot.*"
                )
        missing = keys - known
        if group == "worldserver":
            # seed-conf allows dynamically named loggers and appenders.
            missing = {
                key for key in missing if not key.startswith(("Logger.", "Appender."))
            }
        if missing & protected:
            names = ", ".join(sorted(missing & protected))
            raise AutoError(f"dist_inventory {group} lacks required keys: {names}")
        if missing:
            deltas.append(
                f"control arm: {worldserver} {group} override keys dropped: "
                + ", ".join(sorted(missing))
            )
        output[group] = confmerge.drop_keys(text, missing) if missing else text
    return output, deltas
