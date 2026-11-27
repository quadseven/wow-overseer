"""Emit config key metadata from a saved worldserver filesystem export.

The caller supplies the exact digest and exports it for linux/amd64. The
filesystem archive alone cannot attest either property. The command reads the
archive offline and emits no config values.
"""

import argparse
import json
import posixpath
import re
import tarfile
from pathlib import PurePosixPath

from .controlauto import dist_keys

_IMAGE_REF = re.compile(
    r"(?:[a-z0-9][a-z0-9._-]*(?::[0-9]+)?/)?"
    r"(?:[a-z0-9][a-z0-9._-]*/)*[a-z0-9][a-z0-9._-]*@sha256:[0-9a-f]{64}"
)
_ETC = "azerothcore/env/ref/etc"
_GROUPS = {
    f"{_ETC}/worldserver.conf.dist": "worldserver",
    f"{_ETC}/modules/playerbots.conf.dist": "playerbots",
    f"{_ETC}/modules/mod_overseer.conf.dist": "overseer",
    f"{_ETC}/modules/mod_dungeon_clear.conf.dist": "dungeon-clear",
    f"{_ETC}/modules/mod_ollama_chat.conf.dist": "ollama-chat",
}
_DIST_DIRS = {str(parent) for path in _GROUPS for parent in PurePosixPath(path).parents}
_DIST_DIRS.remove(".")
_MAX_DIST_BYTES = 4 * 1024 * 1024


class InventoryError(ValueError):
    """The export cannot produce a complete inventory."""


def _read_groups(path):
    groups = {}
    try:
        with tarfile.open(path, "r|*") as archive:
            for member in archive:
                # Recognize aliases of the expected paths so malformed members
                # fail closed even if a valid member is also present.
                relative = member.name.removeprefix("./")
                normalized = posixpath.normpath(
                    "/" + member.name.replace("\\", "/").lstrip("/")
                ).lstrip("/")
                group = _GROUPS.get(normalized)
                if group is None:
                    if normalized in _DIST_DIRS and (
                        relative != normalized or not member.isdir()
                    ):
                        raise InventoryError("unsafe dist path or type in archive")
                    continue
                if (
                    relative != normalized
                    or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
                    or member.issparse()
                ):
                    raise InventoryError("unsafe dist path or type in archive")
                if group in groups:
                    raise InventoryError("duplicate dist file in archive")
                if not 0 <= member.size <= _MAX_DIST_BYTES:
                    raise InventoryError("dist file exceeds the inventory read limit")
                with archive.extractfile(member) as content:
                    keys = sorted(dist_keys(content.read().decode("utf-8")))
                if not keys:
                    raise InventoryError("dist has no supported keys")
                groups[group] = keys
    except (OSError, tarfile.TarError, UnicodeError):
        raise InventoryError("could not read the dist archive") from None
    if "worldserver" not in groups:
        raise InventoryError("worldserver dist is missing from the archive")
    return groups


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worldserver", required=True, help="exported image digest ref"
    )
    parser.add_argument("--archive", required=True, help="saved filesystem export tar")
    args = parser.parse_args(argv)
    if not _IMAGE_REF.fullmatch(args.worldserver):
        parser.error("--worldserver requires a digest-pinned image")
    try:
        groups = _read_groups(args.archive)
    except InventoryError as error:
        parser.error(str(error))
    inventory = {
        "worldserver": args.worldserver,
        "platform": "linux/amd64",
        "groups": groups,
    }
    print(json.dumps(inventory, sort_keys=True))


if __name__ == "__main__":
    main()
