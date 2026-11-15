"""The `act` timeline as the rows the judge writes.

Measured behaviour decides the shape: a job written as an `overseer_command`
row (kind `job`) is applied by the module within seconds with no bridge, while
a direct UPDATE of `overseer_roster.job` showed no effect. So a `roster` step
is shorthand for a command of kind `job`; nothing in a decree ever compiles to
a write to `overseer_roster`.
"""


def act_commands(decree):
    """Each act step as {"at"|"when": ..., "who": ..., "kind": ..., "text": ...}.

    `who` is left as written (a name, `family:<name>`, `guild:...` or `cast[N]`);
    the judge resolves it to characters.
    """
    out = []
    for step in decree.get("act") or []:
        when = {"at": step["at"]} if "at" in step else {"when": step["when"]}
        if "roster" in step:
            r = step["roster"]
            out.append({**when, "who": r["who"], "kind": "job", "text": r["job"]})
        else:
            c = step["command"]
            out.append({**when, "who": c["who"], "kind": c["kind"], "text": c["text"]})
    return out
