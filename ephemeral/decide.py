"""The decision rule and the evidence comment, as pure functions.

An issue closes ONLY when the same decree failed on every control run and
passed on every treatment run, every run valid, with the fix verified present
in the treatment image and absent from the control. Anything else closes
nothing. INVALID never closes anything.
"""

import re
from math import comb

OUTCOMES = (
    "proven", "disproven", "non-discriminating", "pass-uncontrolled",
    "underpowered", "unclear", "pending",
)  # fmt: skip
SIGNATURE = "-- claude-code (Overseer, PC session, ephemeral worlds)"


def fisher_p(control_fail, n_control, treatment_fail, n_treatment):
    """One-sided Fisher exact p that the image made no difference to who FAILed."""
    total = n_control + n_treatment
    fails = control_fail + treatment_fail
    denom = comb(total, n_control)
    tail = sum(
        comb(fails, k) * comb(total - fails, n_control - k)
        for k in range(control_fail, min(fails, n_control) + 1)
    )
    return tail / denom if denom else 1.0


def statistics_line(verdicts):
    c = [v for a, v in verdicts if a == "control" and v in ("PASS", "FAIL")]
    t = [v for a, v in verdicts if a == "treatment" and v in ("PASS", "FAIL")]
    if not c or not t:
        return "Statistics: not computed, one arm has no valid runs."
    cf, tf = c.count("FAIL"), t.count("FAIL")
    p = fisher_p(cf, len(c), tf, len(t))
    inv = round(1 / p) if p > 0 else 0
    shown = f"p = 1/{inv}" if inv and abs(1 / inv - p) <= 1e-9 * p else f"p = {p:.4f}"
    return (
        f"Statistics: control {cf} of {len(c)} FAIL, treatment {tf} of {len(t)} FAIL; "
        f"Fisher's exact test (one-sided) that the image made no difference: {shown}."
    )


def _verdict(rec, res, run):
    got = res.get(run["run_id"])
    if got is None:
        return None
    v = got.get("verdict")
    if (
        v not in ("PASS", "FAIL", "INVALID")
        or got.get("decree_sha256") != rec["decree_sha256"]
    ):
        return "INVALID"
    return v


REQUIRED_RUNS = {"control": 3, "treatment": 3}


def wanted_runs(rec):
    return dict(rec["runs_wanted"])


def _early(pres, treat, ctrl):
    """Outcomes a single valid run settles: a treatment FAIL or a control PASS."""
    if "FAIL" in treat:
        if pres.get("treatment") != "present":
            return (
                "unclear",
                "a treatment run FAILed but the fix was not verified present in its image",
            )
        return "disproven", "a valid treatment run FAILed"
    if "PASS" in ctrl:
        return (
            "non-discriminating",
            "a control run PASSed, so the decree cannot tell fixed from broken",
        )
    return None


def _uncontrolled(wanted, treat, ctrl):
    n_treat = wanted.get("treatment", 0)
    if not (n_treat and len(treat) == n_treat and all(v == "PASS" for v in treat)):
        return False
    return not wanted.get("control") or bool(ctrl and all(v == "INVALID" for v in ctrl))


def _settled(rec, pres, treat, ctrl, runs):
    """The outcome once no single run settles it."""
    if _uncontrolled(rec["runs_wanted"], treat, ctrl):
        return "pass-uncontrolled", "treatment passed with no usable control"
    if "INVALID" in treat + ctrl:
        return "unclear", "a run was INVALID: the scenario was never reached"
    if any(v is None for _, v in runs):
        return "pending", "runs are still missing"
    if pres.get("treatment") != "present" or pres.get("control") != "absent":
        return "unclear", "fix presence was not verified in both images"
    if wanted_runs(rec) != REQUIRED_RUNS:
        return (
            "underpowered",
            "a close needs exactly 3 runs per arm (3 of 3 control FAIL, 3 of 3 treatment PASS)",
        )
    return "proven", "control FAILed and treatment PASSed on every run"


def decide(rec, res):
    """Decision for one batch: {outcome, reason, runs, statistics}."""
    runs = [(r, _verdict(rec, res, r)) for r in rec["runs"]]
    verdicts = [(r["arm"], v) for r, v in runs if v]
    pres = {a: p.get("state") for a, p in rec["presence"].items()}
    treat = [v for a, v in verdicts if a == "treatment"]
    ctrl = [v for a, v in verdicts if a == "control"]
    outcome, reason = _early(pres, treat, ctrl) or _settled(
        rec, pres, treat, ctrl, runs
    )
    return {
        "outcome": outcome,
        "reason": reason,
        "runs": [
            {"run_id": r["run_id"], "arm": r["arm"], "verdict": v or "not run"}
            for r, v in runs
        ],
        "statistics": statistics_line(verdicts),
    }


# -- boxes -------------------------------------------------------------------------

_BOX = re.compile(r"^(\s*[-*]\s+)\[ \](.*)$")


def _norm(text):
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", text.lower())).strip()


def tick_boxes(body, criterion):
    """Tick the unticked boxes that quote the criterion or are marked live."""
    want = _norm(criterion)
    lines, n = [], 0
    for line in body.split("\n"):
        m = _BOX.match(line)
        if m and (
            (want and want in _norm(m.group(2)))
            or re.search(r"\blive\b", m.group(2), re.I)
        ):
            line, n = f"{m.group(1)}[x]{m.group(2)}", n + 1
        lines.append(line)
    return "\n".join(lines), n


def unticked(body):
    return sum(1 for line in body.split("\n") if _BOX.match(line))


# -- the comment -------------------------------------------------------------------


def marker(decree_id, sha):
    return f"<!-- eph:{decree_id}:{sha} -->"


def _digest(ref):
    m = re.search(r"sha256:[a-f0-9]{64}", ref or "")
    return m.group(0) if m else "unknown"


def _cell(v):
    return str(v).replace("|", "/").replace("\n", " ")[:120]


def _evidence(rec, res, arm):
    pick = None
    for r in rec["runs"]:
        got = res.get(r["run_id"])
        if r["arm"] == arm and got:
            if (
                pick is None
                or got.get("verdict") == "FAIL"
                and res[pick["run_id"]].get("verdict") != "FAIL"
            ):
                pick = r
    if pick is None:
        return []
    lines = [f"#### {arm}, run `{pick['run_id']}`", ""]
    for a in res[pick["run_id"]].get("assertions", []):
        lines.append(
            f"- `{a.get('name')}` ({a.get('role')}): {a.get('status')}, {a.get('observed', a.get('detail', ''))}"
        )
        exp = a.get("expect")
        if exp is not None:
            lines.append(f"  - expected: `{_cell(exp)}`")
        if a.get("sql"):
            lines.append("  - SQL: `" + " ".join(a["sql"].split())[:600] + "`")
        for row in (a.get("sample") or [])[:20]:
            lines.append("  - row: " + ", ".join(_cell(c) for c in row))
        for m in (a.get("matched") or [])[:20]:
            lines.append("  - log: " + _cell(m))
    return lines + [""]


def render_comment(rec, decision, res, decree_repo, decree_commit, entry):
    sid = rec["decree_id"]
    lines = [
        marker(sid, rec["decree_sha256"]),
        f"Ephemeral world result: **{decision['outcome']}** ({decision['reason']}).",
        "",
        f"Criterion: {entry.get('criterion', '')}",
        f"Decree: https://github.com/{decree_repo}/blob/{decree_commit or 'main'}/data/decrees/{sid}.yaml "
        f"(sha256 `{rec['decree_sha256']}`)",
        "",
        "| arm | image (worldserver digest) | fix state | built from |",
        "|---|---|---|---|",
    ]  # fmt: skip
    for arm in ("control", "treatment"):
        img = next((r["images"] for r in rec["runs"] if r["arm"] == arm), None)
        if img:
            p = rec["presence"].get(arm, {})
            lines.append(
                f"| {arm} | `{_digest(img['worldserver'])}` | {p.get('state', 'unchecked')} | `{p.get('pin') or 'unknown'}` |"
            )
    lines += ["", "| run | arm | verdict |", "|---|---|---|"]
    lines += [
        f"| `{r['run_id']}` | {r['arm']} | {r['verdict']} |" for r in decision["runs"]
    ]
    lines += ["", "### Evidence", ""]
    for arm in ("control", "treatment"):
        lines += _evidence(rec, res, arm)
    lines += ["### Fidelity deltas against the base realm", ""]
    lines += [f"- {d}" for d in rec.get("fidelity_deltas", [])]
    lines += ["", decision["statistics"], "", SIGNATURE]
    text = "\n".join(lines)
    return (
        text if len(text) < 60000 else text[:59000] + "\n\n(truncated)\n\n" + SIGNATURE
    )
