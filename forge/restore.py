"""Choosing and restoring the newest nightly backup.

The forge's only data source is the backup share, mounted read-only. Nothing
here opens a file for writing or connects to anything but a loopback MySQL.
"""

from __future__ import annotations

import gzip
import pathlib
import re
import shlex
import zlib
from dataclasses import dataclass

BACKUP_RE = re.compile(r"^wow-dev-characters-(?P<stamp>\d{8}T\d{6}Z)\.sql\.gz$")
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_TRAILER = b"-- Dump completed"


class NoBackup(RuntimeError):
    """The backup directory holds no finished dump."""


class IncompleteDump(RuntimeError):
    """The dump is not valid gzip or lacks mysqldump's completion trailer."""


class NotLocal(RuntimeError):
    """The forge was pointed at a MySQL server that is not on loopback."""


@dataclass(frozen=True)
class Backup:
    path: pathlib.Path
    stamp: str


def newest_backup(directory: pathlib.Path) -> Backup:
    """The finished dump with the newest stamp; partials and strays are skipped."""
    found = []
    for path in pathlib.Path(directory).iterdir():
        match = BACKUP_RE.match(path.name)
        if match and path.is_file():
            found.append(Backup(path, match["stamp"]))
    if not found:
        raise NoBackup(f"no wow-dev-characters-<stamp>.sql.gz in {directory}")
    return max(found, key=lambda b: b.stamp)


def verify_dump_complete(path: pathlib.Path) -> None:
    """Stream the whole dump and check its last line is mysqldump's trailer."""
    last = b""
    try:
        with gzip.open(path, "rb") as handle:
            for line in handle:
                if line.strip():
                    last = line
    except (OSError, EOFError, zlib.error) as err:
        raise IncompleteDump(f"{path.name}: {err}") from err
    if not last.startswith(_TRAILER):
        raise IncompleteDump(
            f"{path.name}: no completion trailer, the dump is truncated"
        )


def assert_local_mysql(host: str) -> None:
    if host not in LOOPBACK:
        raise NotLocal(
            f"refusing MySQL host {host!r}: the forge only talks to a loopback server"
        )


def restore_command(backup: Backup, port: int, host: str = "127.0.0.1") -> list[str]:
    """`gunzip -c <dump> | mysql` against the throwaway server. No password on argv."""
    assert_local_mysql(host)
    script = f"gunzip -c {shlex.quote(backup.path.as_posix())} | mysql -h{host} -P{int(port)} -uroot --protocol=TCP"
    return ["sh", "-c", script]
