#!/usr/bin/env bash
# build_bundle.sh -- clean portable AE tarball (part 1/2: header+stage)
set -euo pipefail
IFS=$'\n\t'
WORKSPACE="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
OUT_DIR="${WORKSPACE}"
BUNDLE="${OUT_DIR}/submission_bundle.tar.gz"
if [ "${1:-}" = "--out" ]; then
    OUT_DIR="${2:?usage: build_bundle.sh [--out DIR]}"
    mkdir -p "${OUT_DIR}"
    BUNDLE="${OUT_DIR}/submission_bundle.tar.gz"
fi
MANUSCRIPT="${WORKSPACE}/final/manuscript"
for f in "${MANUSCRIPT}/main.pdf" \
         "${WORKSPACE}/SUBMISSION_METADATA.txt" \
         "${WORKSPACE}/REPRODUCIBILITY.md" \
         "${WORKSPACE}/REVIEWER_DEFENSE_FAQ.md" \
         "${WORKSPACE}/final/scripts/reproduce_all.sh" \
         "${WORKSPACE}/final/audit/db_config.json.template" \
         "${WORKSPACE}/final/audit/frozen_paper_summary.json"; do
    if [ ! -f "$f" ]; then echo "[FAIL] missing: $f" >&2; exit 2; fi
done
STAGE="$( mktemp -d )"
trap 'rm -rf "${STAGE}"' EXIT
ROOT="${STAGE}/artifact"
mkdir -p "${ROOT}/final/scripts/new_experiments" "${ROOT}/final/audit" \
         "${ROOT}/final/results/new_experiments/aggregated" \
         "${ROOT}/final/manuscript/tables" "${ROOT}/final/manuscript/figures"
cp "${MANUSCRIPT}/main.pdf" "${ROOT}/main.pdf"
if [ -f "${MANUSCRIPT}/main_anonymized.pdf" ]; then
    cp "${MANUSCRIPT}/main_anonymized.pdf" "${ROOT}/main_anonymized.pdf"
fi
cp "${MANUSCRIPT}/main.tex" "${ROOT}/main.tex"
cp "${MANUSCRIPT}/main.tex" "${ROOT}/final/manuscript/main.tex"
cp "${MANUSCRIPT}/tables/"*.tex "${ROOT}/final/manuscript/tables/"
# part 2/2: docs+scripts+audit+data+pack
cp "${WORKSPACE}/SUBMISSION_METADATA.txt" "${ROOT}/"
cp "${WORKSPACE}/REPRODUCIBILITY.md" "${ROOT}/"
cp "${WORKSPACE}/REVIEWER_DEFENSE_FAQ.md" "${ROOT}/"
if ls "${MANUSCRIPT}/figures/"* >/dev/null 2>&1; then
    cp "${MANUSCRIPT}/figures/"* "${ROOT}/final/manuscript/figures/" 2>/dev/null || true
fi
cp "${WORKSPACE}/final/scripts/reproduce_all.sh" "${ROOT}/final/scripts/"
cp "${WORKSPACE}/final/scripts/new_experiments/"*.py "${ROOT}/final/scripts/new_experiments/"
cp "${WORKSPACE}/final/scripts/new_experiments/README.md" "${ROOT}/final/scripts/new_experiments/" 2>/dev/null || true
cp "${WORKSPACE}/final/audit/submission_checksums.sha256" "${ROOT}/final/audit/" 2>/dev/null || true
cp "${WORKSPACE}/final/audit/frozen_paper_summary.json" "${ROOT}/final/audit/"
cp "${WORKSPACE}/final/audit/db_config.json.template" "${ROOT}/final/audit/"
cp "${WORKSPACE}/final/audit/db_config.json.template" "${ROOT}/final/audit/db_config.json"
cp "${WORKSPACE}/final/results/new_experiments/aggregated/"* "${ROOT}/final/results/new_experiments/aggregated/"
for f in results_scale.csv results_q_error.csv results_cold_cache.csv results_pac.csv results_pac_raw.csv smoke_scale.csv smoke_q_error.csv smoke_cold_cache.csv smoke_pac.csv smoke_pac_raw.csv; do
    [ -f "${WORKSPACE}/final/results/new_experiments/$f" ] && cp "${WORKSPACE}/final/results/new_experiments/$f" "${ROOT}/final/results/new_experiments/"
done
find "${ROOT}" -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "${ROOT}" \( -name '*.pyc' -o -name '.DS_Store' -o -name '*.dump' \) -delete 2>/dev/null || true
tar -czf "${BUNDLE}" -C "${STAGE}" artifact
N_FILES="$( tar -tzf "${BUNDLE}" | wc -l | tr -d ' ' )"
SIZE="$( du -sh "${BUNDLE}" | cut -f1 )"
HASH="$( shasum -a 256 "${BUNDLE}" | cut -d' ' -f1 )"
echo "wrote ${BUNDLE}"
echo "files=${N_FILES} size=${SIZE} sha256=${HASH}"
