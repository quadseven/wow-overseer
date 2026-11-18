"""The local owner lock for `eph dispatch`.

The cluster Lease already keeps two dispatchers from both starting worlds, but
it cannot tell an agent which dispatcher is whose, and it gave agents no way to
stop their own. This lock adds both: a file records the owner, pid and start
time; a second dispatcher is refused with the owner named; `dispatch --stop`
ends only the dispatcher whose owner matches, by pid. Nothing here ever matches
on a command line, so stopping one batch cannot touch another agent's process.

A lock is stale, and taken over with a log line, when its pid is gone or it has
not been renewed for `max_age` seconds. A running dispatcher renews it each pass.
"""

import json
import os
import pathlib
import signal
import sys
import time

from .dispatch import LeaseHeld

DEFAULT_MAX_HOURS = 6
EXIT_HELD = 3
EXIT_FAILED = 2


class LockHeld(LeaseHeld):
    """A live dispatcher already holds the local lock."""


def lock_path(env=None, home=None):
    env = os.environ if env is None else env
    if env.get("EPH_LOCK"):
        return pathlib.Path(env["EPH_LOCK"])
    return (home or pathlib.Path.home()) / ".ephemeral" / "dispatch.lock"


def owner_name(flag, env=None, ppid=None):
    env = os.environ if env is None else env
    return (
        flag
        or env.get("EPH_OWNER")
        or f"parent-{os.getppid() if ppid is None else ppid}"
    )


def pid_alive(pid):
    """Is this pid a running process. Never sends a signal on Windows."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate(pid):
    os.kill(pid, signal.SIGTERM)


def _read(path):
    try:
        rec = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if isinstance(rec, dict) and isinstance(rec.get("pid"), int):
            return rec
    except (OSError, ValueError):
        pass
    return None


def _create(path, rec):
    """Create the file only if it does not exist (atomic), else FileExistsError."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f)


def acquire(path, owner, pid=None, now=None, alive=pid_alive,
            max_age=DEFAULT_MAX_HOURS * 3600, log=print):  # fmt: skip
    pid = os.getpid() if pid is None else pid
    now = time.time() if now is None else now
    rec = {"owner": owner, "pid": pid, "started": now, "renewed": now}
    for _ in range(2):
        try:
            _create(path, rec)
            return rec
        except FileExistsError:
            pass
        cur = _read(path)
        if cur and cur["pid"] != pid:
            age = now - float(cur.get("renewed", cur.get("started", 0)))
            if alive(cur["pid"]) and age <= max_age:
                raise LockHeld(
                    f"another dispatcher is running: owner {cur.get('owner')!r}, "
                    f"pid {cur['pid']}; stop it with `dispatch --stop --owner "
                    f"{cur.get('owner')}` from that owner"
                )
            why = (
                "its process is gone" if not alive(cur["pid"]) else "it was not renewed"
            )
            log(
                f"dispatch lock: stale lock of owner {cur.get('owner')!r} pid {cur['pid']} ({why}), taking over"
            )
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    raise LockHeld("could not take the dispatch lock: lost a race for it")


def renew(path, pid=None, now=None):
    pid = os.getpid() if pid is None else pid
    cur = _read(path)
    if cur and cur["pid"] == pid:
        cur["renewed"] = time.time() if now is None else now
        pathlib.Path(path).write_text(json.dumps(cur), encoding="utf-8")


def release(path, pid=None):
    pid = os.getpid() if pid is None else pid
    cur = _read(path)
    if cur and cur["pid"] == pid:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _wait():
    time.sleep(0.5)


def stop(path, owner, alive=pid_alive, terminate=terminate, wait=_wait, log=print):
    """Stop the dispatcher this owner started, by pid. Exit code 0, 2 or 3."""
    cur = _read(path)
    if cur is None:
        log("no dispatcher lock: nothing to stop")
        return 0
    if cur.get("owner") != owner:
        log(
            f"refusing: the dispatcher (pid {cur['pid']}) belongs to owner "
            f"{cur.get('owner')!r}, not {owner!r}"
        )
        return EXIT_HELD
    pid = cur["pid"]
    if alive(pid):
        terminate(pid)
        for _ in range(20):
            wait()
            if not alive(pid):
                break
        else:
            log(f"pid {pid} is still running after the stop signal; lock kept")
            return EXIT_FAILED
        log(f"stopped dispatcher pid {pid} of owner {owner!r}")
    else:
        log(f"dispatcher pid {pid} was already gone; clearing its lock")
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    return 0
