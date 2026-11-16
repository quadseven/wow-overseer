"""Where the world pod's two harness containers meet: one handoff file, one log.

`seed` (an init container) and `judge` (the regular container) are separate
processes. The seed leaves the variables and the resolved cast in one file and
the judge reads the same file back, so both must resolve the same path. The
command line layer applies the defaults here to both, so a template that sets
nothing still agrees with itself, and one that sets `EPH_VARS_FILE` must set it
the same on both (the infra manifest tests hold that).

    EPH_VARS_FILE   the handoff file (default: VARS_FILE, on the `tmp` volume
                    both containers mount read-write)
    EPH_LOG_FILE    the worldserver log the judge's log assertions read
    EPH_LOGS_DIR    the worldserver log directory the pod mounts; the log is
                    LOG_NAME inside it when EPH_LOG_FILE is not set
"""

import posixpath

VARS_FILE = "/tmp/eph-vars.json"
LOG_NAME = "Module.log"  # the file appender submit adds to every world (submit.BASELINE)


def with_vars_file(env):
    """A copy of the environment with the handoff path filled in."""
    out = dict(env)
    if not out.get("EPH_VARS_FILE"):
        out["EPH_VARS_FILE"] = VARS_FILE
    return out


def log_path(flag, env):
    """The log the judge reads: the flag, else EPH_LOG_FILE, else the logs directory; None if none is known."""
    if flag:
        return flag
    if env.get("EPH_LOG_FILE"):
        return env["EPH_LOG_FILE"]
    if env.get("EPH_LOGS_DIR"):
        return posixpath.join(env["EPH_LOGS_DIR"], LOG_NAME)
    return None
