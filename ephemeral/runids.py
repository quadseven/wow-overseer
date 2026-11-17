"""Run, batch and result names, and what the Job and ConfigMap labels mean.

One place, so the submitter, the dispatcher and the collector cannot drift:
a run id is `<batch>-<arm letter><n>`, the Job is `eph-<run id>`, the judge's
result is ConfigMap `eph-result-<run id>`, the submitter's per-run inputs are
ConfigMap `eph-run-<run id>`.
"""

import re

RUN_RE = re.compile(r"^(?P<batch>[a-f0-9]{6})-(?P<arm>[ct])(?P<n>[1-9])$")
JOB_RE = re.compile(r"^eph-(?P<run>[a-f0-9]{6}-[ct][1-9])$")
ARM_LETTER = {"control": "c", "treatment": "t"}
ARM_NAME = {"c": "control", "t": "treatment"}
JOB_LABEL_ARM = "eph/arm"
JOB_LABEL_BATCH = "eph/batch"
JOB_LABEL_CLASS = "eph/class"
JOB_LABEL_DECREE = "eph/decree"
JOB_LABEL_REALM = "eph/realm"
LEASE_NAME = "eph-dispatcher"
TEMPLATE_CM = "eph-world-template"


def run_id(batch, arm, n):
    return f"{batch}-{ARM_LETTER[arm]}{n}"


def job_name(rid):
    return f"eph-{rid}"


def result_name(rid):
    return f"eph-result-{rid}"


def run_cm_name(rid):
    return f"eph-run-{rid}"


def parse_run(rid):
    """(batch, arm, n) or None when the id is not one this runner made."""
    m = RUN_RE.match(rid or "")
    return (m["batch"], ARM_NAME[m["arm"]], int(m["n"])) if m else None


def run_of_job(job):
    m = JOB_RE.match(job.get("metadata", {}).get("name", ""))
    return m["run"] if m else None
