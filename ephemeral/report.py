"""Publish one decree batch as evidence on the issue it names.

This command is intentionally separate from collection: it can add a comment
and tick one uniquely matched checkbox, but it never changes issue state.
"""

import datetime as dt
import hashlib
import json
import pathlib
import re

from . import collect, runids

_BATCH = re.compile(r"^[a-f0-9]{6}$")
_DECREE_ID = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$|^[a-z0-9]$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CHECKBOX = re.compile(r"^(\s*(?:[-*+] |\d+\. )\[)([ xX])(\].*)$")
_HOST = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\b", re.I)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_POD = re.compile(r"\b[a-z0-9-]+-[a-f0-9]{8,10}-[a-z0-9]{5}\b", re.I)
_RUN_NAME = re.compile(r"\beph-[a-f0-9]{6}-[ct][1-9]\b", re.I)
_ROLE_NAME = re.compile(r"\b(?:node|pod)\s*(?:name\s*)?[:= ]\s*[a-z0-9-]+", re.I)


class ReportError(Exception):
    """The batch is incomplete or cannot be safely attributed to one issue."""


def _utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wanted_pairs(record):
    wanted = record.get("runs_wanted") or {"control": 3, "treatment": 3}
    control, treatment = wanted.get("control"), wanted.get("treatment")
    if (
        not isinstance(control, int)
        or isinstance(control, bool)
        or control < 1
        or not isinstance(treatment, int)
        or isinstance(treatment, bool)
        or treatment < 1
    ):
        return None, max(
            (
                v
                for v in (control, treatment)
                if isinstance(v, int) and not isinstance(v, bool) and v > 0
            ),
            default=3,
        )
    return (control if control == treatment else None), max(control, treatment)


def _safe_reason(reason, private_names=()):
    text = " ".join(str(reason).split()).replace("|", "/")[:500]
    if not text:
        return "[empty reason]"
    if any(
        name and re.search(rf"\b{re.escape(name)}\b", text, re.I)
        for name in private_names
    ):
        return "[reason withheld by privacy guard]"
    if any(
        pattern.search(text) for pattern in (_HOST, _IPV4, _POD, _RUN_NAME, _ROLE_NAME)
    ):
        return "[reason withheld by privacy guard]"
    return text


def _result_verdict(record, run, results):
    result = results.get(run["run_id"])
    if not isinstance(result, dict):
        return "MISSING", None, ["no result received"]
    verdict = result.get("verdict")
    if verdict not in ("PASS", "FAIL", "INVALID") or result.get(
        "decree_sha256"
    ) != record.get("decree_sha256"):
        verdict = "INVALID"
    reasons = result.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = ["result reasons were not a list"]
    return verdict, result, reasons


def _checkbox_result(body, target, standard_met, timestamps_complete):
    if not standard_met:
        return body, "standard not met"
    if not timestamps_complete:
        return body, "missing UTC start time"
    target = " ".join(str(target).casefold().split())
    matches = []
    lines = body.split("\n")
    for index, line in enumerate(lines):
        m = _CHECKBOX.match(line)
        if not m:
            continue
        text = " ".join(m.group(3)[1:].casefold().split())
        # A prefix must end on a word boundary: `foo` never matches `foobar`.
        if text.startswith(target) and not text[len(target) :][:1].isalnum():
            matches.append((index, m))
    if not matches:
        return body, "no matching checkbox"
    if len(matches) != 1:
        return body, "ambiguous checkbox prefix"
    index, match = matches[0]
    if match.group(2).casefold() == "x":
        return body, "already checked"
    lines[index] = match.group(1) + "x" + match.group(3)
    return "\n".join(lines), "ticked"


def build_report(record, results, job_starts, issue_body, private_names=()):
    """Return the parseable comment, proposed issue body and standard result."""
    if not isinstance(record.get("proves"), int) or isinstance(
        record.get("proves"), bool
    ):
        raise ReportError("batch has no numeric proves issue")
    if record["proves"] < 1:
        raise ReportError("batch proves issue must be positive")
    box = record.get("box")
    if not isinstance(box, str) or not box.strip():
        raise ReportError("batch has no checkbox box text")
    pair_count, rows_expected = _wanted_pairs(record)
    declared = {
        (run.get("arm"), run.get("n")): run
        for run in record.get("runs", [])
        if isinstance(run, dict)
    }
    rows_to_render = max(
        rows_expected,
        max(
            (n for _, n in declared if isinstance(n, int) and not isinstance(n, bool)),
            default=0,
        ),
    )
    rows, reasons = [], []
    verdicts = {"control": [], "treatment": []}
    for n in range(1, rows_to_render + 1):
        for arm in ("control", "treatment"):
            run = declared.get((arm, n))
            if run is None:
                run = {
                    "arm": arm,
                    "n": n,
                    "run_id": runids.run_id(record["batch"], arm, n),
                    "source_batch": "not submitted",
                }
            verdict, result, why = _result_verdict(record, run, results)
            if result is None:
                started = _utc(job_starts.get(run["run_id"]))
            else:
                started = _utc(job_starts.get(run["run_id"])) or _utc(
                    result.get("started_at_utc")
                )
            verdicts[arm].append(verdict)
            rows.append(
                {
                    "pair": n,
                    "batch_id": run.get("source_batch", record["batch"]),
                    "arm": arm,
                    "verdict": verdict,
                    "started_at_utc": started or "not recorded",
                }
            )
            for line in why:
                reasons.append(
                    {
                        "pair": n,
                        "batch_id": run.get("source_batch", record["batch"]),
                        "arm": arm,
                        "reason": _safe_reason(line, private_names),
                    }
                )
    standard_met = bool(
        pair_count
        and len(verdicts["control"]) == pair_count
        and len(verdicts["treatment"]) == pair_count
        and all(v == "FAIL" for v in verdicts["control"])
        and all(v == "PASS" for v in verdicts["treatment"])
    )
    timestamps_complete = all(
        row["verdict"] == "MISSING" or row["started_at_utc"] != "not recorded"
        for row in rows
    )
    updated_body, checkbox_status = _checkbox_result(
        issue_body, box, standard_met, timestamps_complete
    )
    stable_box_state = (
        "checked"
        if checkbox_status in ("ticked", "already checked")
        else checkbox_status
    )
    state = json.dumps(
        {
            "standard_met": standard_met,
            "timestamps_complete": timestamps_complete,
            "checkbox": stable_box_state,
            "rows": rows,
            "reasons": reasons,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    report_sha = hashlib.sha256(state.encode("utf-8")).hexdigest()[:12]
    batch_ids = record.get("batch_ids") or [record["batch"]]
    batch_label = ",".join(batch_ids)
    marker = (
        f"<!-- eph-report:v1 {record['decree_id']} {record['decree_sha256']} "
        f"{batch_label} {report_sha} -->"
    )
    lines = [
        marker,
        "Ephemeral decree batch evidence",
        f"decree_id: {record['decree_id']}",
        f"batch_ids: {batch_label}",
        f"standard: {'met' if standard_met else 'not met'}",
        f"declared_pairs: {pair_count if pair_count else 'unequal or invalid arm counts'}",
        f"timestamps_complete: {'yes' if timestamps_complete else 'no'}",
        f"checkbox: {checkbox_status}",
        "",
        "| pair | batch_id | arm | verdict | started_at_utc |",
        "|---:|---|---|---|---|",
    ]
    lines.extend(
        f"| {row['pair']} | {row['batch_id']} | {row['arm']} | {row['verdict']} | {row['started_at_utc']} |"
        for row in rows
    )
    lines.extend(
        (
            "",
            "Judge reason lines",
            "",
            "| pair | batch_id | arm | reason |",
            "|---:|---|---|---|",
        )
    )
    if reasons:
        lines.extend(
            f"| {row['pair']} | {row['batch_id']} | {row['arm']} | {row['reason']} |"
            for row in reasons
        )
    else:
        lines.append("| - | - | - | none |")
    return {
        "body": "\n".join(lines),
        "updated_issue_body": updated_body,
        "standard_met": standard_met,
        "timestamps_complete": timestamps_complete,
        "checkbox_status": checkbox_status,
        "rows": rows,
    }


class Reporter:
    def __init__(self, cfg, kube, gh, env=None, out=print):
        self.cfg, self.kube, self.gh, self.out = cfg, kube, gh, out
        self.env = env if env is not None else {}

    def run(self, batches, dry_run=False):
        batch_ids = [batches] if isinstance(batches, str) else list(batches)
        if not batch_ids or len(set(batch_ids)) != len(batch_ids):
            raise ReportError("provide one or more distinct batch ids")
        records, paths = [], {}
        for batch in batch_ids:
            if not _BATCH.fullmatch(batch or ""):
                raise ReportError("each batch must be a six-character hexadecimal id")
            matches = sorted(
                pathlib.Path(self.cfg.results_dir).glob(f"*/batch-{batch}.json")
            )
            if len(matches) != 1:
                raise ReportError(f"batch {batch} record is missing or ambiguous")
            record = json.loads(matches[0].read_text(encoding="utf-8"))
            if record.get("batch") != batch:
                raise ReportError("batch record id does not match the requested batch")
            if record.get("decree_id") != matches[0].parent.name:
                raise ReportError("batch record decree does not match its directory")
            if not _DECREE_ID.fullmatch(record.get("decree_id", "")):
                raise ReportError("batch decree id is not label-safe")
            if not _SHA256.fullmatch(record.get("decree_sha256", "")):
                raise ReportError("batch decree hash is invalid")
            records.append(record)
            paths[batch] = matches[0]
        first = records[0]
        if any(
            record.get(field) != first.get(field)
            for record in records[1:]
            for field in ("decree_id", "decree_sha256", "proves", "box", "runs_wanted")
        ):
            raise ReportError("all batches must use the same decree and issue proof")

        results = collect.Collector(self.cfg, self.kube, self.gh, env=self.env).fetch()
        for record in records:
            for run in record.get("runs", []):
                if run["run_id"] in results:
                    continue
                path = paths[record["batch"]].parent / f"{run['run_id']}.json"
                if path.exists():
                    try:
                        results[run["run_id"]] = json.loads(
                            path.read_text(encoding="utf-8")
                        )["result"]
                    except (KeyError, ValueError, OSError):
                        results[run["run_id"]] = {
                            "verdict": "INVALID",
                            "reasons": ["copied result is unreadable"],
                        }

        starts, jobs = {}, []
        for batch in batch_ids:
            selected = self.kube.list(
                "jobs", selector=f"{runids.JOB_LABEL_BATCH}={batch}"
            )
            jobs.extend(selected)
            for job in selected:
                rid = runids.run_of_job(job)
                if rid:
                    starts[rid] = (job.get("status") or {}).get("startTime")

        combined = {**first, "batch_ids": batch_ids, "runs": []}
        pair_index = 0
        for record in records:
            declared = {
                (run.get("arm"), run.get("n")): run
                for run in record.get("runs", [])
                if isinstance(run, dict)
            }
            local_ns = sorted(
                {
                    n
                    for _, n in declared
                    if isinstance(n, int) and not isinstance(n, bool)
                }
            )
            for local_n in local_ns:
                local = []
                for arm in ("control", "treatment"):
                    run = declared.get((arm, local_n))
                    rid = (
                        run["run_id"]
                        if run
                        else runids.run_id(record["batch"], arm, local_n)
                    )
                    if rid not in results and starts.get(rid) is None:
                        continue
                    local.append(
                        (arm, run or {"run_id": rid, "arm": arm, "n": local_n})
                    )
                if not local:
                    continue
                pair_index += 1
                for arm in ("control", "treatment"):
                    run = next((r for a, r in local if a == arm), None)
                    if run is None:
                        run = {
                            "run_id": runids.run_id(record["batch"], arm, local_n),
                            "arm": arm,
                            "n": pair_index,
                        }
                    else:
                        run = {**run, "n": pair_index}
                    run["source_batch"] = record["batch"]
                    combined["runs"].append(run)

        issue_number = first.get("proves")
        if not isinstance(issue_number, int) or isinstance(issue_number, bool):
            raise ReportError("decree must name one issue with numeric proves")
        issue = self.gh.issue(self.cfg.decree_repo, issue_number)
        private_names = tuple(getattr(self.cfg, "nodes", {}).keys()) + tuple(
            job.get("metadata", {}).get("name", "") for job in jobs
        )
        preview = build_report(
            combined, results, starts, issue.get("body") or "", private_names
        )
        self.out(preview["body"])
        if dry_run:
            self.out("dry run: no issue changes made")
            return preview

        target = self.cfg.decree_repo
        if preview["updated_issue_body"] != (issue.get("body") or ""):
            self.gh.edit_body(target, issue_number, preview["updated_issue_body"])
        marker = preview["body"].splitlines()[0]
        already_posted = any(
            marker in (comment.get("body") or "")
            for comment in self.gh.comments(target, issue_number)
        )
        if already_posted:
            self.out("evidence comment already exists")
        else:
            made = self.gh.comment(target, issue_number, preview["body"])
            self.out(made.get("html_url", "evidence comment posted"))
        return preview
