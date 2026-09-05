"""Final experiment driver for the SDAO paper.

Runs calibration + held-out + decision + plan verification + bootstrap CIs,
writes everything to final/results/main_run/.
"""
import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from sdao_experiments.config import ExperimentConfig
from sdao_experiments.workload import (
    WorkloadGenerator, bucket_for, read_fvecs,
)
from sdao_experiments.runner import (
    STRATEGIES, _vector_literal, recall_at_10, _build_statement,
    _build_predicate, _classify_plan, _walk_index_names,
    _to_raw_row, capture_plan, execute_once,
)

OUT_ROOT = ROOT / "final" / "results" / "main_run"
OUT_ROOT.mkdir(parents=True, exist_ok=True)


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def admit(calibration, bucket, policy, target_recall, conf=0.95, q=0.05):
    """Apply an admission policy to the calibration map for one bucket."""
    feasible = ["SQL_FIRST"]
    per_strategy = {}
    for strat in STRATEGIES:
        stats_ = calibration.get((strat, bucket))
        if not stats_ or stats_["n"] == 0:
            per_strategy[strat] = {"feasible": False, "reason": "no calibration data",
                                   "statistic": None, "n": 0}
            continue
        recalls = np.asarray(stats_["recalls"])
        n = len(recalls)
        if policy == "min_recall":
            statistic = float(recalls.min())
            ok = statistic >= target_recall
            reason = f"R_min={statistic:.3f} target={target_recall:.3f}"
        elif policy == "mean_recall":
            statistic = float(recalls.mean())
            ok = statistic >= target_recall
            reason = f"R_mean={statistic:.3f} target={target_recall:.3f}"
        elif policy == "quantile_recall":
            statistic = float(np.quantile(recalls, q))
            ok = statistic >= target_recall
            reason = f"P{int(q*100)}_recall={statistic:.3f} target={target_recall:.3f}"
        elif policy == "lcb_recall":
            rng = np.random.default_rng(42)
            boot_means = np.array([
                rng.choice(recalls, size=n, replace=True).mean() for _ in range(1000)
            ])
            alpha = 1.0 - conf
            statistic = float(np.quantile(boot_means, alpha))
            ok = statistic >= target_recall
            reason = f"LCB{conf:.0%}={statistic:.3f} target={target_recall:.3f}"
        elif policy == "failure_rate":
            k = int(np.sum(recalls < target_recall))
            n_obs = n
            z = stats.norm.ppf(0.95)
            phat = k / n_obs
            denom = 1 + z * z / n_obs
            center = (phat + z * z / (2 * n_obs)) / denom
            margin = z * np.sqrt((phat * (1 - phat) + z * z / (4 * n_obs)) / n_obs) / denom
            upper = center + margin
            ok = upper <= (1 - target_recall)
            statistic = float(upper)
            reason = f"Wilson-UB-fail={statistic:.3f} budget={(1 - target_recall):.3f}"
        else:
            raise ValueError(f"unknown policy: {policy}")
        per_strategy[strat] = {"feasible": bool(ok), "statistic": statistic,
                               "reason": reason, "n": n}
        if ok:
            feasible.append(strat)
    best = "SQL_FIRST"
    best_lat = calibration.get(("SQL_FIRST", bucket), {}).get("median_latency_ms", float("inf"))
    for s in feasible:
        lat = calibration.get((s, bucket), {}).get("median_latency_ms", float("inf"))
        if lat < best_lat:
            best_lat = lat
            best = s
    return best, feasible, "lowest_median_latency", best_lat, per_strategy