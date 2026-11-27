"""The `act` timeline as the rows the judge writes.

Measured behaviour decides the shape: a job written as an `overseer_command`
row (kind `job`) is applied by the module within seconds with no bridge, while
a direct UPDATE of `overseer_roster.job` showed no effect. So a `roster` step
is shorthand for a command of kind `job`. A `travel_guard` step sets or clears
only the named cast member's operator guard through the dedicated world guard.
A `quest_aim` step sets a standing intent for a quest the named member holds.
"""

TRAVEL_GUARD = "travel_guard"
QUEST_AIM = "quest_aim"


def act_commands(decree):
    """Each act step as {"at"|"when": ..., "who": ..., "kind": ..., "text": ...}.

    `who` is left as written (a name, `family:<name>`, `guild:...` or `cast[N]`);
    the judge resolves it to characters.
    """
    out = []
    for step in decree.get("act") or []:
        when = {"at": step["at"]} if "at" in step else {"when": step["when"]}
        if "by" in step:
            when["by"] = step["by"]
        if "roster" in step:
            r = step["roster"]
            out.append({**when, "who": r["who"], "kind": "job", "text": r["job"]})
        elif TRAVEL_GUARD in step:
            g = step[TRAVEL_GUARD]
            out.append(
                {
                    **when,
                    "who": g["who"],
                    "kind": TRAVEL_GUARD,
                    "text": "",
                    "guard_enabled": g["enabled"],
                }
            )
        elif QUEST_AIM in step:
            aim = step[QUEST_AIM]
            out.append({
                **when, "who": aim["who"], "kind": QUEST_AIM,
                "text": str(aim["quest"]), "quest_id": aim["quest"],
            })  # fmt: skip
        else:
            c = step["command"]
            out.append({**when, "who": c["who"], "kind": c["kind"], "text": c["text"]})
    return out
