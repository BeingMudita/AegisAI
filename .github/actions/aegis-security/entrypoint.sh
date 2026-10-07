#!/usr/bin/env bash
# Run the AegisAI security gate and surface the result to GitHub.
#
# Writes a Markdown report to aegis-gate-report.md and the job summary, sets the
# `passed` / `score` step outputs, and exits non-zero when the gate fails so the
# workflow (and therefore the deploy) is blocked.
set -uo pipefail

TARGET="${AEGIS_TARGET:-aegis.yaml}"
THRESHOLD="${AEGIS_THRESHOLD:-90}"
REDTEAM_FLAG=""
if [ "${AEGIS_REDTEAM:-true}" != "true" ]; then
  REDTEAM_FLAG="--no-redteam"
fi

echo "::group::AegisAI security gate — ${TARGET} (threshold ${THRESHOLD})"

# JSON for machine-readable outputs; Markdown for the human report.
aegis gate "${TARGET}" --threshold "${THRESHOLD}" ${REDTEAM_FLAG} --json > aegis-gate.json
GATE_STATUS=$?
aegis gate "${TARGET}" --threshold "${THRESHOLD}" ${REDTEAM_FLAG} --markdown > aegis-gate-report.md

cat aegis-gate-report.md
echo "::endgroup::"

# Surface the report in the GitHub Actions run summary.
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  cat aegis-gate-report.md >> "${GITHUB_STEP_SUMMARY}"
fi

# Step outputs (parsed from the JSON, with python already on the runner).
if [ -n "${GITHUB_OUTPUT:-}" ] && [ -f aegis-gate.json ]; then
  PASSED=$(python -c "import json;print(str(json.load(open('aegis-gate.json'))['passed']).lower())")
  SCORE=$(python -c "import json;print(json.load(open('aegis-gate.json'))['score'])")
  echo "passed=${PASSED}" >> "${GITHUB_OUTPUT}"
  echo "score=${SCORE}" >> "${GITHUB_OUTPUT}"
fi

# `aegis gate` exits 2 on FAIL, 0 on PASS — propagate it as the gate verdict.
exit "${GATE_STATUS}"
