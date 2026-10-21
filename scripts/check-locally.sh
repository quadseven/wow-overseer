#!/usr/bin/env bash
# Run the checks that gate a pull request on this repo, locally, the way CI
# runs them (#1293).
#
# CI's unittest job (.github/workflows/check.yml) checks out WITH the
# mod-overseer submodule and hands the job's `test-cmd` to a shell: a compile
# check against the 3.12 floor, then the whole suite under uv's Python 3.12
# with tests/requirements.txt (the pinned sqlglot and PyMySQL), one process
# per test module (.github/scripts/unittest_parallel.py). A bare
# `python3 -m unittest` on whatever interpreter is at hand, on a checkout
# without the submodule (every fresh `git worktree add`), reports hundreds of
# failures and skips that CI never sees. This script closes that gap:
#
#   - initializes mod-overseer if it is missing, and warns when the checked
#     out commit is not the one this commit pins (CI tests the pin);
#   - reads `test-cmd` out of check.yml's unittest job and runs exactly that,
#     so there is no second copy here to drift from CI;
#   - sets CI=true as the runner does, so a test gated on CI fails instead of
#     skipping when its dependency is missing.
#
# Usage: scripts/check-locally.sh            (the unittest job, a few minutes)
#        scripts/check-locally.sh lint       (the lint job: pinned ruff)
#        scripts/check-locally.sh all        (both)
#        scripts/check-locally.sh print      (print what would run, run nothing)
#
# Needs bash, git, uv (https://docs.astral.sh/uv/) and a python3 on PATH that
# is at least 3.12 for compile_check.py; uv fetches 3.12 for the suite itself.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

check_yml=".github/workflows/check.yml"

die() {
  echo "check-locally: $*" >&2
  exit 1
}

# The double-quoted value of KEY inside check.yml's JOB block: the same
# first-match rule tests/test_check_locally.py applies, which compares the two.
job_value() {
  local job="$1" key="$2" value
  value="$(awk -v job="$job" -v key="$key" '
    /^  [A-Za-z0-9_-]+:[ \t]*$/ {
      current = $1
      sub(/:$/, "", current)
      next
    }
    current == job && $0 ~ "^[ \t]+" key ":[ \t]*\"" {
      sub("^[ \t]+" key ":[ \t]*\"", "")
      sub(/"[ \t]*$/, "")
      print
      exit
    }
  ' "$check_yml")"
  test -n "$value" || die "no quoted $key in the $job job of $check_yml"
  # A YAML double-quoted string unescapes backslashes; nothing here does, so
  # refuse one rather than run a command that differs from CI's.
  case "$value" in
    *\\*) die "$job $key in $check_yml has a backslash escape; teach this script to unescape it" ;;
  esac
  printf '%s\n' "$value"
}

ruff_cmd() {
  local version
  version="$(job_value lint ruff-version)"
  case "$version" in
    *[!0-9.]*) die "ruff-version in $check_yml is not a dotted version: $version" ;;
  esac
  printf 'uvx ruff@%s\n' "$version"
}

ensure_submodule() {
  if [ ! -f mod-overseer/src/mod_overseer.cpp ]; then
    echo "== mod-overseer is not checked out; initializing it (CI checks out with submodules: true)"
    git submodule update --init mod-overseer \
      || die "could not fetch the mod-overseer submodule; the suite reads its sources, so it cannot run without it"
  fi
  local status
  status="$(git submodule status mod-overseer)"
  case "$status" in
    +*)
      echo "WARNING: mod-overseer is checked out at a commit other than the one this commit pins." >&2
      echo "WARNING: CI tests the pin; run 'git submodule update mod-overseer' to match it." >&2
      echo "WARNING: $status" >&2
      ;;
  esac
}

run_unittest() {
  command -v uv >/dev/null || die "uv is not on PATH; install it from https://docs.astral.sh/uv/ (CI runs the suite through uv)"
  command -v python3 >/dev/null || die "python3 is not on PATH (compile_check.py runs on it, as in CI)"
  ensure_submodule
  local cmd
  cmd="$(job_value unittest test-cmd)"
  echo "== unittest: $cmd"
  # The same string CI's Test step runs, from this checkout's own tracked
  # check.yml, under the shell flags GitHub's runner uses for a run step.
  CI="${CI:-true}" bash --noprofile --norc -eo pipefail -c "$cmd"
}

run_lint() {
  command -v uvx >/dev/null || die "uvx is not on PATH; install uv from https://docs.astral.sh/uv/"
  local ruff
  ruff="$(ruff_cmd)"
  echo "== lint: $ruff check . && $ruff format --check ."
  # Word-split on purpose: "uvx ruff@<dotted version>", validated above.
  # shellcheck disable=SC2086
  $ruff check .
  # shellcheck disable=SC2086
  $ruff format --check .
}

mode="${1:-unittest}"
start=$SECONDS
case "$mode" in
  unittest) run_unittest ;;
  lint) run_lint ;;
  # Not `run_lint && run_unittest`: bash ignores set -e inside a function
  # on the left of &&, so a failing `ruff check` would not stop the run.
  all)
    run_lint
    run_unittest
    ;;
  print)
    # Assigned first so a failed read exits here instead of printing blank.
    test_cmd="$(job_value unittest test-cmd)"
    ruff="$(ruff_cmd)"
    printf 'unittest: %s\n' "$test_cmd"
    printf 'ruff: %s\n' "$ruff"
    exit 0
    ;;
  *) echo "usage: $0 [unittest|lint|all|print]" >&2; exit 2 ;;
esac
echo "== check-locally: $mode passed in $((SECONDS - start))s"
