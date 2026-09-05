#!/usr/bin/env bash
# ============================================================================
#  reproduce_all.sh -- master verification runner for the artifact bundle
#  Paper: Recall-Constrained Admission for Hybrid ANN-SQL Plans (IEEE/ACM)
#  Author: Abhijeet L. M. <abhijeet.lm@vit.ac.in>
# ============================================================================
#  Usage:
#     bash scripts/reproduce_all.sh           # full pipeline (check+verify)
#     bash scripts/reproduce_all.sh check     # only the DB connection probe
#     bash scripts/reproduce_all.sh verify    # only the tolerance verification
#     bash scripts/reproduce_all.sh clean     # remove regenerated artefacts
#     bash scripts/reproduce_all.sh help      # this help
#
#  Exit codes:
#     0  PASS  -- all frozen numbers reproduced within tolerance
#     1  FAIL  -- one or more numbers outside tolerance
#              -- latencies/speedups: +/- 10 %; recalls: +/- 0.02;
#              -- inflations: +/- 0.10; counts/coverages: exact
#     2  ABORT -- DB connection failed or required artefact missing
#
#  Runtime (Apple M2, native Homebrew Postgres 17):
#     check   : < 5 s
#     verify  : < 1 s (in-memory, reads agg_summary.json + agg_pac.csv)
#     full    : 60-90 min (only when re-running from scratch)
# ============================================================================

set -euo pipefail
IFS=$'\n\t'

# -------- paths ------------------------------------------------------------
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "${SCRIPT_DIR}/.." && pwd )"
DB_CFG="${PROJECT_ROOT}/audit/db_config.json"
NE_DIR="${PROJECT_ROOT}/scripts/new_experiments"
RES_DIR="${PROJECT_ROOT}/results/new_experiments"
AGG_DIR="${RES_DIR}/aggregated"
SUMMARY="${AGG_DIR}/agg_summary.json"
PAC_CSV="${AGG_DIR}/agg_pac.csv"

# -------- colour helpers (no-op if not a tty) ------------------------------
if [ -t 1 ]; then
    C_RED='\033[0;31m'; C_GRN='\033[0;32m'; C_YEL='\033[0;33m'; C_RST='\033[0m'
else
    C_RED=''; C_GRN=''; C_YEL=''; C_RST=''
fi
ok()   { printf "${C_GRN}[ OK ]${C_RST} %s\n" "$1"; }
warn() { printf "${C_YEL}[WARN]${C_RST} %s\n" "$1"; }
err()  { printf "${C_RED}[FAIL]${C_RST} %s\n" "$1" >&2; }

# -------- subcommands -------------------------------------------------------
cmd_check() {
    echo "============================================================"
    echo "  1. PostgreSQL connection probe"
    echo "============================================================"
    if [ ! -f "${DB_CFG}" ]; then
        err "Missing ${DB_CFG} -- cannot probe database"
        return 2
    fi
    if grep -q 'REDACTED' "${DB_CFG}"; then
        err "audit/db_config.json still has a REDACTED password placeholder."
        err "Please copy audit/db_config.json.template to audit/db_config.json"
        err "and fill in your own password before running the pipeline."
        return 2
    fi
    python3 - <<PYEOF
import json, sys
import psycopg2
cfg = json.load(open("${DB_CFG}"))
try:
    conn = psycopg2.connect(
        host=cfg["host"], port=cfg["port"],
        dbname=cfg["dbname"], user=cfg["user"], password=cfg["password"],
        connect_timeout=5,
    )
except Exception as e:
    print(f"ABORT: cannot connect to PostgreSQL: {e}", file=sys.stderr)
    sys.exit(2)
cur = conn.cursor()
cur.execute("SELECT version();")
ver = cur.fetchone()[0]
cur.execute("SELECT extname FROM pg_extension;")
exts = sorted(r[0] for r in cur.fetchall())
cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = %s;",
            (cfg["table_name"],))
(n_tab,) = cur.fetchone()
cur.close(); conn.close()
print(f"  version        : {ver}")
print(f"  extensions     : {exts}")
print(f"  table {cfg['table_name']:15s} present: {n_tab == 1}")
if "vector" not in exts:
    print("ABORT: pgvector extension is required.", file=sys.stderr)
    sys.exit(2)
if n_tab != 1:
    print(f"WARN: table {cfg['table_name']} not found; ingestion will be re-run.")
PYEOF
    ok "PostgreSQL probe passed"
}

cmd_verify() {
    echo "============================================================"
    echo "  2. +/- 10 % (latency) / +/- 0.02 (recall) verification"
    echo "     against frozen paper numbers"
    echo "============================================================"
    if [ ! -f "${SUMMARY}" ]; then
        err "Missing ${SUMMARY} -- run aggregation first."
        return 2
    fi
    if [ ! -f "${PAC_CSV}" ]; then
        err "Missing ${PAC_CSV} -- run aggregation first."
        return 2
    fi
    python3 - <<'PYEOF'
import csv, json, sys

SUMMARY = json.load(open("results/new_experiments/aggregated/agg_summary.json"))
PAC_CSV = "results/new_experiments/aggregated/agg_pac.csv"
FROZEN = json.load(open("audit/frozen_paper_summary.json"))
FROZEN.pop("_comment", None)

# Frozen paper numbers (gold standard), flattened into dotted-key form.
# Keys starting with '_' are comments/metadata and are skipped.
EXPECTED = {f"{grp}.{fld}": val
            for grp, sub in FROZEN.items()
            for fld, val in sub.items()
            if not fld.startswith("_")}

def rel_ok(k, e, a):
    if k.endswith("empirical_coverage"):
        return a == e, "exact"
    if k.endswith("n_plan_switches_to_hnsw") or k.endswith("n_total_buckets") \
       or k.endswith("n_cells"):
        return a == e, "exact (integer)"
    # Non-numeric or range/enforcement keys are self-contained:
    if k.endswith("wall_ceiling_ms"):
        return True, "ceiling (checked separately below)"
    if isinstance(e, str) or isinstance(a, str):
        return True, "skipped (string annotation)"
    if "inflation" in k:
        return abs(a - e) <= 0.10, "abs +/- 0.10"
    if "recall" in k:
        return abs(a - e) <= 0.02, "abs +/- 0.02"
    if e == 0:
        return a == 0, "abs (denominator=0)"
    # Wall-clock latencies/speedups are noisy on shared AE hardware;
    # +/- 10 % is the community norm (SEED/NDE benchmarks). Recalls
    # and counts keep the strict +/- 0.02 / exact rules above.
    rel = abs(a - e) / abs(e)
    return rel <= 0.10, "rel +/- 10 %"

failures = []
for k, e in EXPECTED.items():
    grp, field = k.split(".", 1)
    a = SUMMARY.get(grp, {}).get(field)
    if a is None:
        # A frozen key absent from the live summary is only fatal for
        # numeric expectations (ceiling/annotations live solely in frozen).
        if isinstance(e, (int, float)) and not k.endswith("wall_ceiling_ms"):
            failures.append((k, e, None, "missing"))
        continue
    ok_flag, rule = rel_ok(k, e, a)
    if not ok_flag:
        failures.append((k, e, a, rule))

# --- Wall-clock sanity ceiling --------------------------------------------
# Only guards against catastrophic regressions / stuck planners --
# every wall latency in the summary must stay below 100 s.
ceiling = EXPECTED.get("scale.wall_ceiling_ms")
if ceiling is not None:
    for grp, sub in SUMMARY.items():
        if not isinstance(sub, dict):
            continue
        for fld, val in sub.items():
            if isinstance(val, (int, float)) and "p50" in fld and val > ceiling:
                failures.append((f"{grp}.{fld} (sanity ceiling)",
                                 f"<= {ceiling}", val, f"> {ceiling} ms"))

# PAC re-check: every row must have ci_within_pac == True
n_pac_cells_total = 0
n_pac_pass = 0
with open(PAC_CSV) as f:
    for row in csv.DictReader(f):
        n_pac_cells_total += 1
        if row["ci_within_pac"] in ("True", "true", "1"):
            n_pac_pass += 1
empirical_coverage = n_pac_pass / n_pac_cells_total if n_pac_cells_total else 0
a = SUMMARY.get("pac", {}).get("empirical_coverage")
if a is None or abs(empirical_coverage - a) > 0.001:
    failures.append(("pac.empirical_coverage (recomputed)",
                     empirical_coverage, a, "exact"))
if n_pac_cells_total != EXPECTED["pac.n_cells"]:
    failures.append(("pac.n_cells (recomputed)",
                     EXPECTED["pac.n_cells"], n_pac_cells_total,
                     "exact (integer)"))

print()
print(f"  Checked 11 summary cells + PAC re-derivation:")
print(f"    failures = {len(failures)}")
for k, e, a, rule in failures:
    print(f"     {k}: expected={e}  actual={a}  rule={rule}")

if failures:
    print()
    print("  STATUS: FAIL")
    sys.exit(1)
print()
print("  STATUS: PASS  -- all numbers within tolerance")
PYEOF
}

cmd_full() {
    cmd_check || return 2
    echo
    echo "============================================================"
    echo "  2. (Re-)running the four benchmarks (~20 min on M2)"
    echo "============================================================"
    cd "${PROJECT_ROOT}"
    python3 "${NE_DIR}/benchmark_scale.py"      --reuse-table --n-queries 25 --repeats 3
    python3 "${NE_DIR}/benchmark_q_error.py"    --reuse-table --n-queries 15
    python3 "${NE_DIR}/benchmark_cold_cache.py" --reuse-table --n-queries 15 --repeats 3
    python3 "${NE_DIR}/benchmark_pac_bounds.py" --reuse-table --n-seeds 30 --n-queries 5
    echo
    echo "============================================================"
    echo "  3. Aggregating"
    echo "============================================================"
    python3 "${NE_DIR}/aggregate_results.py"
    cmd_verify
}

cmd_clean() {
    echo "Removing regenerated CSVs (raw + aggregated) ..."
    rm -f "${RES_DIR}/results_scale.csv" \
          "${RES_DIR}/results_q_error.csv" \
          "${RES_DIR}/results_cold_cache.csv" \
          "${RES_DIR}/results_pac.csv" \
          "${RES_DIR}/results_pac_raw.csv" \
          "${AGG_DIR}/agg_scale.csv" \
          "${AGG_DIR}/agg_q_error.csv" \
          "${AGG_DIR}/agg_cold_cache.csv" \
          "${AGG_DIR}/agg_pac.csv" \
          "${AGG_DIR}/agg_summary.json"
    ok "Cleaned."
}

cmd_help() {
    sed -n '3,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# -------- dispatcher --------------------------------------------------------
case "${1:-full}" in
    check)   cmd_check   ;;
    verify)  cmd_verify  ;;
    full)    cmd_full    ;;
    clean)   cmd_clean   ;;
    help|-h|--help) cmd_help ;;
    *) err "Unknown subcommand: $1"; cmd_help; exit 2 ;;
esac

