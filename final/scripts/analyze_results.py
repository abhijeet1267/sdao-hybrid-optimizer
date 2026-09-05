"""Analyze and tabulate results from all experiment runs.

Reads:
- final/results/main_run/summary.csv, per_query.csv, calibration_map.json
- final/results/sweep_*/summary.csv
- final/results/budget_*/summary.csv
- final/results/seed_*/summary.csv
- final/results/main_run/policy_comparison.csv

Writes:
- final/results/tables/sweep_table.csv (parameter sensitivity)
- final/results/tables/budget_table.csv (vector-first budget)
- final/results/tables/seed_table.csv (multi-seed)
- final/results/tables/policy_table.csv (admission policy)
- final/results/tables/main_summary.csv (headline)
"""
import json
from ast import literal_eval
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/abhijeetmiskin/AppData/MyProject")
RES = ROOT / "final" / "results"
TABLES = RES / "tables"
TABLES.mkdir(parents=True, exist_ok=True)


def load_summary(d):
    return pd.read_csv(d / "summary.csv")


def load_calibration_with_recalls(d):
    raw = json.loads((d / "calibration_map.json").read_text())
    cal = {}
    for k, v in raw.items():
        key = literal_eval(k)
        cal[key] = v
    if any(v.get("recalls") for v in cal.values()):
        return cal
    # recover from raw CSV
    df = pd.read_csv(d / "raw_per_execution.csv")
    df = df[df["phase"] == "calibration"]
    out = {}
    for (strat, bucket), g in df.groupby(["strategy", "bucket"]):
        recs = g["recall_at_10"].values
        lats = g["latency_ms"].values
        out[(strat, bucket)] = {
            "n": len(recs),
            "median_latency_ms": float(np.median(lats)),
            "min_recall": float(recs.min()),
            "mean_recall": float(recs.mean()),
            "p05_recall": float(np.quantile(recs, 0.05)),
            "frac_above_target": float((recs >= 0.95).mean()),
            "recalls": recs.tolist(),
        }
    return out


def main():
    # 1. Main summary
    main = load_summary(RES / "main_run")
    main.to_csv(TABLES / "main_summary.csv", index=False)
    print("=== Main summary ===")
    print(main.to_string(index=False))

    # 2. Sweep table
    sweep_rows = []
    for d in sorted((RES).glob("sweep_*")):
        ef_search = int(d.name.split("ef")[1].split("_")[0])
        probes = int(d.name.split("probes")[1])
        s = load_summary(d)
        for _, row in s.iterrows():
            if row["strategy"] == "Adaptive": continue
            sweep_rows.append({
                "ef_search": ef_search, "probes": probes,
                "strategy": row["strategy"],
                "mean_latency_ms": row["mean_latency_ms"],
                "mean_recall_at_10": row["mean_recall_at_10"],
                "fraction_recall_at_least_target": row["fraction_recall_at_least_target"],
            })
    sweep_df = pd.DataFrame(sweep_rows)
    sweep_df.to_csv(TABLES / "sweep_table.csv", index=False)
    print("\n=== Sweep (ef_search × probes × strategy) ===")
    print(sweep_df.pivot_table(
        index=["ef_search", "probes"], columns="strategy", values="mean_recall_at_10"
    ).round(3).to_string())

    # 3. Budget table
    budget_rows = []
    for d in sorted((RES).glob("budget_*")):
        budget = int(d.name.split("_")[1])
        s = load_summary(d)
        for _, row in s.iterrows():
            if row["strategy"] == "Adaptive": continue
            budget_rows.append({
                "vf_budget": budget, "strategy": row["strategy"],
                "mean_latency_ms": row["mean_latency_ms"],
                "mean_recall_at_10": row["mean_recall_at_10"],
                "fraction_recall_at_least_target": row["fraction_recall_at_least_target"],
            })
    budget_df = pd.DataFrame(budget_rows)
    budget_df.to_csv(TABLES / "budget_table.csv", index=False)
    print("\n=== Vector-first budget ===")
    print(budget_df.pivot_table(
        index="vf_budget", columns="strategy", values="mean_recall_at_10"
    ).round(3).to_string())

    # 4. Multi-seed table
    seed_rows = []
    for d in sorted((RES).glob("seed_*")):
        seed = int(d.name.split("_")[1])
        s = load_summary(d)
        for _, row in s.iterrows():
            if row["strategy"] == "Adaptive": continue
            seed_rows.append({
                "seed": seed, "strategy": row["strategy"],
                "mean_latency_ms": row["mean_latency_ms"],
                "mean_recall_at_10": row["mean_recall_at_10"],
                "fraction_recall_at_least_target": row["fraction_recall_at_least_target"],
            })
    seed_df = pd.DataFrame(seed_rows)
    seed_df.to_csv(TABLES / "seed_table.csv", index=False)
    print("\n=== Multi-seed ===")
    print(seed_df.pivot_table(
        index="seed", columns="strategy", values="mean_recall_at_10"
    ).round(3).to_string())

    # 5. Policy table (from main_run/policy_comparison.csv)
    pol = pd.read_csv(RES / "main_run" / "policy_comparison.csv")
    pol.to_csv(TABLES / "policy_table.csv", index=False)
    print("\n=== Admission policies ===")
    print(pol.to_string(index=False))

    print(f"\nWrote tables to {TABLES}")


if __name__ == "__main__":
    main()