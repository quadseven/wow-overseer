"""The durable admission record for a fully staged automatic proof batch."""

import hashlib
import json
import os
import pathlib
import re
import tempfile

from . import runids

STAGED_LABEL = "eph/staged"
COMMIT_LABEL = "eph/batch-state"
COMMITTED = "committed"
_DECREE = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?")
_BATCH = re.compile(r"[a-f0-9]{6}")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def name(decree_id):
    return f"eph-due-{decree_id}"


def _json(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def fingerprint(data):
    return hashlib.sha256(_json(data).encode("utf-8")).hexdigest()


def manifest(namespace, record, members):
    """Publish the receipt once all Job-owned inputs have been created."""
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name(record["decree_id"]),
            "namespace": namespace,
            "labels": {COMMIT_LABEL: COMMITTED},
        },
        "immutable": True,
        "data": {"batch.json": _json(record), "members.json": _json(members)},
    }


def _matches(pattern, value):
    return isinstance(value, str) and bool(pattern.fullmatch(value))


def _members(record):
    """Map each expected run to its arm and ordinal, or refuse the receipt."""
    wanted = record["runs_wanted"]
    if set(wanted) != set(runids.ARM_LETTER) or any(
        type(count) is not int or not 1 <= count <= 9 for count in wanted.values()
    ):
        return None
    expected = {
        runids.run_id(record["batch"], arm, n): (arm, n)
        for arm, count in wanted.items()
        for n in range(1, count + 1)
    }
    runs = record["runs"]
    actual = {run["run_id"]: (run["arm"], run["n"]) for run in runs}
    if actual != expected or len(runs) != len(expected):
        return None
    if any(
        type(run["n"]) is not int or not isinstance(run["images"]["worldserver"], str)
        for run in runs
    ):
        return None
    return expected


def _valid_proves(record):
    proves = record["proves"]
    if type(proves) is int:
        box = record["box"]
        return proves > 0 and isinstance(box, str) and bool(box.strip())
    return (
        isinstance(proves, list)
        and bool(proves)
        and all(
            _matches(_REPO, entry["repo"])
            and (
                entry["issue"] == "TODO"
                or (type(entry["issue"]) is int and entry["issue"] > 0)
            )
            and isinstance(entry.get("criterion", ""), str)
            for entry in proves
        )
    )


def _valid_record(record):
    return (
        _matches(_DECREE, record["decree_id"])
        and _matches(_BATCH, record["batch"])
        and _matches(_SHA256, record["decree_sha256"])
        and _valid_proves(record)
        and set(record["presence"]) == set(runids.ARM_LETTER)
        and all(isinstance(arm, dict) for arm in record["presence"].values())
    )


def _valid_identity(member):
    return _matches(_SHA256, member["input_sha256"]) and all(
        isinstance(member[key], str) and bool(member[key])
        for key in ("job_uid", "input_uid")
    )


def parse(cm, namespace):
    """Read an immutable complete receipt. Invalid inputs never admit Jobs."""
    try:
        meta = cm["metadata"]
        if (
            cm.get("immutable") is not True
            or meta["namespace"] != namespace
            or meta["labels"].get(COMMIT_LABEL) != COMMITTED
        ):
            return None
        record = json.loads(cm["data"]["batch.json"])
        if not _valid_record(record) or meta["name"] != name(record["decree_id"]):
            return None
        members = json.loads(cm["data"]["members.json"])
        expected = _members(record)
        if (
            not isinstance(members, dict)
            or expected is None
            or members.keys() != expected.keys()
        ):
            return None
        if not all(_valid_identity(member) for member in members.values()):
            return None
        if any(
            len({member[key] for member in members.values()}) != len(members)
            for key in ("job_uid", "input_uid")
        ):
            return None
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return record, members


def install_record(results_dir, record):
    """Atomically install a local copy without replacing a different record."""
    directory = pathlib.Path(results_dir) / record["decree_id"]
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"batch-{record['batch']}.json"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, delete=False
    ) as staged:
        temporary = pathlib.Path(staged.name)
        try:
            json.dump(record, staged, indent=2, sort_keys=True)
            staged.flush()
            os.fsync(staged.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if json.loads(destination.read_text(encoding="utf-8")) != record:
                    raise ValueError(
                        f"existing batch record differs: {destination.name}"
                    ) from None
        finally:
            temporary.unlink()
    return destination
