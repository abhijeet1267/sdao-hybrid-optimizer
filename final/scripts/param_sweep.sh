#!/bin/bash
# Run parameter sweep on the 200K subset.
# Each config takes ~3-5 minutes.
# Outputs: final/results/sweep_<config_name>/

set -e
cd /Users/abhijeetmiskin/AppData/MyProject

for EF in 40 100 200 400; do
    for PROBES in 1 10 50; do
        OUT="final/results/sweep_ef${EF}_probes${PROBES}"
        mkdir -p "$OUT"
        echo "=== Running: ef_search=$EF probes=$PROBES ==="
        /Users/abhijeetmiskin/AppData/MyProject/venv/bin/python final/scripts/run_calibration.py \
            --config final/reproducibility/final_config.json \
            --out-dir "$OUT" \
            --reps 2 \
            --hnsw-ef-search $EF \
            --ivfflat-probes $PROBES \
            2>&1 | tee "$OUT/run.log" | tail -10
        echo "Done: $OUT"
    done
done

echo "All sweep configs done."