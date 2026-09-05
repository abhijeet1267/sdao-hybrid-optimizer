#!/bin/bash
# Vector-first budget sweep
set -e
cd /Users/abhijeetmiskin/AppData/MyProject

for BUDGET in 50 100 200 500 1000; do
    OUT="final/results/budget_${BUDGET}"
    mkdir -p "$OUT"
    echo "=== Running: vf_budget=$BUDGET ==="
    /Users/abhijeetmiskin/AppData/MyProject/venv/bin/python final/scripts/run_calibration.py \
        --config final/reproducibility/final_config.json \
        --out-dir "$OUT" \
        --reps 2 \
        --vf-budget $BUDGET \
        2>&1 | tee "$OUT/run.log" | tail -10
    echo "Done: $OUT"
done

echo "All budget configs done."