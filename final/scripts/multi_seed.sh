#!/bin/bash
# Multi-seed replication
set -e
cd /Users/abhijeetmiskin/AppData/MyProject

for SEED in 20260820 20260822 20260823; do
    OUT="final/results/seed_${SEED}"
    mkdir -p "$OUT"
    echo "=== Running: seed=$SEED ==="
    /Users/abhijeetmiskin/AppData/MyProject/venv/bin/python final/scripts/run_calibration.py \
        --config final/reproducibility/final_config.json \
        --out-dir "$OUT" \
        --reps 3 \
        --seed $SEED \
        2>&1 | tee "$OUT/run.log" | tail -10
    echo "Done: $OUT"
done

echo "All seed configs done."