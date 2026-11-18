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

import contextlib
import json
import os
import pathlib
import signal
import sys
import time

from .dispatch import LeaseHeld

DEFAULT_MAX_HOURS = 6
GUARD_TRIES = 50
GUARD_WAIT = 0.1
GUARD_STALE_SECONDS = 30
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
    """The lock record, or None when the file is missing or not a record.

    Any other read error (a file being swapped under us on Windows) is raised:
    an unreadable lock is a busy lock, never a stale one."""
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        rec = json.loads(text)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) and isinstance(rec.get("pid"), int) else None


def _create(path, rec):
    """Create the file only if it does not exist (atomic), else FileExistsError."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f)


def _replace(path, rec):
    """Swap the lock for `rec` atomically: readers see the old record or the new one."""
    path = pathlib.Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def _takeover_guard(path, now):
    """Serialise stale-lock takeovers: only one process judges and swaps at a time."""
    guard = pathlib.Path(str(path) + ".takeover")
    for _ in range(GUARD_TRIES):
        try:
            _create(guard, {"pid": os.getpid()})
            break
        except FileExistsError:
            try:
                if now - guard.stat().st_mtime > GUARD_STALE_SECONDS:
                    guard.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            time.sleep(GUARD_WAIT)
    else:
        raise LockHeld("another dispatcher is taking over the lock right now")
    try:
        yield
    finally:
        guard.unlink(missing_ok=True)


def acquire(path, owner, pid=None, now=None, alive=pid_alive,
            max_age=DEFAULT_MAX_HOURS * 3600, log=print):  # fmt: skip
    pid = os.getpid() if pid is None else pid
    now = time.time() if now is None else now
    rec = {"owner": owner, "pid": pid, "started": now, "renewed": now}
    for _ in range(3):
        try:
            _create(path, rec)
            return rec
        except FileExistsError:
            pass
        # A stale lock is judged and swapped under the takeover guard, and is
        # replaced in place, never unlinked: a second dispatcher that judged the
        # same stale record cannot delete the fresh lock the first one wrote.
        with _takeover_guard(path, now):
            try:
                cur = _read(path)
            except OSError as exc:
                raise LockHeld(f"the dispatch lock is busy: {exc}") from exc
            if cur is not None and cur["pid"] != pid:
                age = now - float(cur.get("renewed", cur.get("started", 0)))
                if alive(cur["pid"]) and age <= max_age:
                    raise LockHeld(
                        f"another dispatcher is running: owner {cur.get('owner')!r}, "
                        f"pid {cur['pid']}; stop it with `dispatch --stop --owner "
                        f"{cur.get('owner')}` from that owner"
                    )
                why = (
                    "its process is gone"
                    if not alive(cur["pid"])
                    else "it was not renewed"
                )
                log(
                    f"dispatch lock: stale lock of owner {cur.get('owner')!r} pid {cur['pid']} ({why}), taking over"
                )
            elif cur is None and pathlib.Path(path).exists():
                log("dispatch lock: unreadable lock record, taking over")
            elif cur is None:
                continue  # released while we looked: go round and create it
            _replace(path, rec)
            return rec
    raise LockHeld("could not take the dispatch lock: lost a race for it")


def renew(path, pid=None, now=None):
    pid = os.getpid() if pid is None else pid
    try:
        cur = _read(path)
        if cur and cur["pid"] == pid:
            cur["renewed"] = time.time() if now is None else now
            _replace(path, cur)
    except OSError:
        pass  # best effort: the next pass renews again, well inside max_age


def release(path, pid=None, log=print):
    pid = os.getpid() if pid is None else pid
    try:
        cur = _read(path)
        if cur and cur["pid"] == pid:
            os.unlink(path)
    except OSError as exc:
        # Runs from a finally block, so it must not raise over the real result,
        # but a lock left behind has to be visible to the operator.
        log(f"dispatch lock: could not release {path}: {exc}")


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
    # Serialised with takeover, and only the record we judged is removed: if the
    # dead owner's lock was taken over meanwhile, the new owner's lock stays.
    try:
        with _takeover_guard(path, time.time()):
            now_rec = _read(path)
            if now_rec is not None and (
                now_rec["pid"] != pid or now_rec.get("owner") != owner
            ):
                log(
                    f"the lock changed hands (now owner {now_rec.get('owner')!r}, "
                    f"pid {now_rec['pid']}); leaving it in place"
                )
                return EXIT_HELD
            pathlib.Path(path).unlink(missing_ok=True)
    except LockHeld as exc:
        log(f"could not clear the lock: {exc}")
        return EXIT_FAILED
    return 0
