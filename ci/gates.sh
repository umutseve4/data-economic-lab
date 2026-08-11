#!/usr/bin/env bash
#
# Run every quality gate, record the full output of each one in the GitHub job
# summary, and exit non-zero if any gate failed.
#
# Rationale: with one gate per workflow step, a run stops at the first failure
# and the annotation only says "Process completed with exit code 1". Running the
# gates here means a single CI run reports every problem, with its output, on the
# run page itself.

set -uo pipefail

SUMMARY="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
LOGDIR="$(mktemp -d)"
DETAILS="${LOGDIR}/details.md"
: >"${DETAILS}"

NAMES=()
CODES=()

gate() {
  local name="$1"
  shift
  local log="${LOGDIR}/${name}.log"
  local rc=0

  echo "::group::${name}"
  "$@" >"${log}" 2>&1 || rc=$?
  cat "${log}"
  echo "::endgroup::"

  NAMES+=("${name}")
  CODES+=("${rc}")

  local open=""
  if [ "${rc}" -ne 0 ]; then
    open=" open"
    echo "::error::gate '${name}' failed with exit code ${rc}"
  fi

  {
    printf '<details%s><summary><code>%s</code> &mdash; exit %s</summary>\n\n' \
      "${open}" "${name}" "${rc}"
    echo '```text'
    tail -n 300 "${log}"
    echo '```'
    printf '\n</details>\n\n'
  } >>"${DETAILS}"
}

gate ruff-check ruff check .
gate ruff-format ruff format --check .
gate mypy mypy src/ecolab
gate pytest pytest --cov=ecolab --cov-report=term-missing --cov-branch
gate sample-drift python scripts/gen_sample.py --check
gate end-to-end bash ci/e2e.sh

failed=0
{
  echo '### Gate results'
  echo
  echo '| gate | exit code | result |'
  echo '| --- | ---: | --- |'
  for i in "${!NAMES[@]}"; do
    if [ "${CODES[$i]}" -eq 0 ]; then
      printf '| `%s` | %s | pass |\n' "${NAMES[$i]}" "${CODES[$i]}"
    else
      printf '| `%s` | %s | **FAIL** |\n' "${NAMES[$i]}" "${CODES[$i]}"
      failed=1
    fi
  done
  echo
  cat "${DETAILS}"
} >>"${SUMMARY}"

if [ "${failed}" -ne 0 ]; then
  echo "one or more quality gates failed; see the job summary for full output" >&2
fi
exit "${failed}"
