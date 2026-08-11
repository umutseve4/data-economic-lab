#!/usr/bin/env bash
#
# Offline end-to-end run of the CLI against data/sample/.
# Requires ECOLAB_SOURCE=sample. No network access and no API key.

set -euo pipefail

rows_of() {
  local file="$1"
  local n
  n="$(sed -n 's/^Total rows in database: \([0-9]\{1,\}\).*$/\1/p' "${file}" | tail -n 1)"
  if [ -z "${n}" ]; then
    echo "could not find 'Total rows in database:' in ${file}" >&2
    echo "--- ${file} ---" >&2
    cat "${file}" >&2
    exit 1
  fi
  printf '%s' "${n}"
}

echo "== validate =="
python -m ecolab validate

echo "== ingest (run 1) =="
python -m ecolab ingest | tee /tmp/run1.txt
a="$(rows_of /tmp/run1.txt)"

echo "== ingest (run 2) =="
python -m ecolab ingest | tee /tmp/run2.txt
b="$(rows_of /tmp/run2.txt)"

if [ "${a}" != "${b}" ]; then
  echo "ingest is not idempotent: ${a} != ${b}" >&2
  exit 1
fi
echo "ingest is idempotent: ${a} rows on both runs"

echo "== analyze =="
python -m ecolab analyze | tee /tmp/analyze.txt

echo "== report =="
python -m ecolab report

if [ ! -f reports/report.md ]; then
  echo "reports/report.md was not written" >&2
  exit 1
fi

n_png="$(find reports/figures -name '*.png' -type f | wc -l | tr -d ' ')"
if [ "${n_png}" -lt 1 ]; then
  echo "no PNG figures were written to reports/figures/" >&2
  exit 1
fi

echo "end-to-end ok: rows=${a} figures=${n_png}"
