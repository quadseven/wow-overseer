"""GET /api/v2/operator: whether operator actions are on for this deployment.

Talking to a character, decrees, starting and stopping streams and pointing
the Watcher queue commands the realm acts on. The app keeps them on their own
route and draws that route locked unless this says so. The setting is the
server's, read from the environment, and off unless it is set: a deployment
that sets nothing shows a read-only app.

This only gates what the app draws. The existing POST endpoints are unchanged.
"""

from __future__ import annotations

import os

ENV_VAR = "OVERSEER_OPERATOR_ACTIONS"
_ON = {"1", "on", "true", "yes"}


def enabled(environ=None) -> bool:
    value = (environ if environ is not None else os.environ).get(ENV_VAR, "")
    return value.strip().lower() in _ON


def operator(_query: dict, _ctx) -> tuple[int, dict]:
    on = enabled()
    return 200, {
        "enabled": on,
        "setting": ENV_VAR,
        "says": "Operator actions are on."
        if on
        else "Operator actions are off on this deployment.",
    }


ROUTES = {"/api/v2/operator": operator}
