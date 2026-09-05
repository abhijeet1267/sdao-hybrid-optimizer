#!/usr/bin/env python3
"""aggregate_results.py — Statistical aggregation over the 4 production CSVs."""
from __future__ import annotations
import csv, json, math, statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # portable: <bundle>/ or final/
R = ROOT / "results" / "new_experiments"
OUT = R / "aggregated"
OUT.mkdir(parents=True, exist_ok=True)

STRATEGIES = ["SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID"]
BUCKETS = ["sel_000_005", "sel_005_010", "sel_010_025", "sel_025_050", "sel_050_100"]
BUCKET_LABEL = {
    "sel_000_005": "0.0-0.5%",
    "sel_005_010": "0.5-1.0%",
    "sel_010_025": "1.0-2.5%",
    "sel_025_050": "2.5-5.0%",
    "sel_050_100": "5.0-100%",
}


def read_csv(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def percentile(xs, p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    return s[int(k)] if f == c else s[f] + (s[c] - s[f]) * (k - f)
# ---------------------------------------------------------------------------
# 1) Scale (Table VII)
# ---------------------------------------------------------------------------

def aggregate_scale() -> dict:
    rows = read_csv(R / "results_scale.csv")
    g = defaultdict(list)
    for r in rows:
        g[(r["bucket"], r["strategy"])].append(r)

    table = []
    sql_base = {}
    for b in BUCKETS:
        if (b, "SQL_FIRST") in g:
            sql_base[b] = percentile(
                [float(r["wall_p50_ms"]) for r in g[(b, "SQL_FIRST")]], 50
            )

    for b in BUCKETS:
        for s in STRATEGIES:
            cell = g.get((b, s), [])
            if not cell:
                continue
            p50 = [float(r["wall_p50_ms"]) for r in cell]
            p95 = [float(r["wall_p95_ms"]) for r in cell]
            p99 = [float(r["wall_p99_ms"]) for r in cell]
            rec = [float(r["recall_at_10"]) for r in cell]
            sql_p50 = sql_base.get(b, float("nan"))
            sp = sql_p50 / percentile(p50, 50) if sql_p50 > 0 else float("nan")
            table.append({
                "bucket": b, "bucket_label": BUCKET_LABEL[b],
                "strategy": s, "n_queries": len(cell),
                "wall_p50_ms": round(percentile(p50, 50), 2),
                "wall_p95_ms": round(percentile(p95, 50), 2),
                "wall_p99_ms": round(percentile(p99, 50), 2),
                "recall_mean": round(statistics.mean(rec), 3),
                "recall_min": round(min(rec), 3),
                "recall_max": round(max(rec), 3),
                "speedup_vs_sql_first": round(sp, 2),
            })

    out = OUT / "agg_scale.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
        w.writeheader()
        w.writerows(table)
    return {"rows": table, "sql_baseline": sql_base}
# ---------------------------------------------------------------------------
# 2) q-Error (Table VIII)
# ---------------------------------------------------------------------------

def aggregate_q_error() -> dict:
    rows = read_csv(R / "results_q_error.csv")
    g = defaultdict(list)
    for r in rows:
        g[(r["q_error_label"], r["bucket"], r["strategy"])].append(r)

    labels = sorted({r["q_error_label"] for r in rows},
                    key=lambda x: float(x.split("x")[0]))
    summary = []
    for label in labels:
        for b in BUCKETS:
            for s in STRATEGIES:
                cell = g.get((label, b, s), [])
                if not cell:
                    continue
                rec = [float(r["recall_at_10"]) for r in cell]
                wall = [float(r["wall_ms"]) for r in cell]
                est = int(cell[0]["estimated_rows"])
                act = int(cell[0]["actual_rows"])
                mis = abs(est - act) / max(act, 1)
                summary.append({
                    "q_error_label": label,
                    "q_error_factor": float(cell[0]["q_error_factor"]),
                    "observed_q_error": float(cell[0]["observed_q_error"]),
                    "estimated_rows": est,
                    "actual_rows": act,
                    "row_misest_ratio": round(mis, 2),
                    "bucket": b, "bucket_label": BUCKET_LABEL[b],
                    "strategy": s, "n_queries": len(cell),
                    "recall_mean": round(statistics.mean(rec), 3),
                    "wall_p50_ms": round(percentile(wall, 50), 2),
                    "wall_p95_ms": round(percentile(wall, 95), 2),
                })

    out = OUT / "agg_q_error.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    switches = []
    for label in labels:
        for b in BUCKETS:
            sql_c = g.get((label, b, "SQL_FIRST"), [])
            hnsw_c = g.get((label, b, "HNSW_HYBRID"), [])
            if not sql_c or not hnsw_c:
                continue
            sp50 = percentile([float(r["wall_ms"]) for r in sql_c], 50)
            hp50 = percentile([float(r["wall_ms"]) for r in hnsw_c], 50)
            chosen = "HNSW_HYBRID" if hp50 < sp50 else "SQL_FIRST"
            switches.append({
                "q_error_label": label,
                "bucket": b, "bucket_label": BUCKET_LABEL[b],
                "sql_p50_ms": round(sp50, 2),
                "hnsw_p50_ms": round(hp50, 2),
                "dominant_strategy": chosen,
            })
    return {"rows": summary, "plan_switches": switches, "labels": labels}
# ---------------------------------------------------------------------------
# 3) Cold cache (Table IX)
# ---------------------------------------------------------------------------

def aggregate_cold_cache() -> dict:
    rows = read_csv(R / "results_cold_cache.csv")
    g = defaultdict(list)
    for r in rows:
        g[(r["cache_state"], r["bucket"], r["strategy"])].append(r)

    states = ["hot", "cold", "hot_2nd"]
    table = []
    for b in BUCKETS:
        for s in STRATEGIES:
            row = {"bucket": b, "bucket_label": BUCKET_LABEL[b], "strategy": s}
            for st in states:
                cell = g.get((st, b, s), [])
                if not cell:
                    row[f"{st}_p50"] = float("nan")
                    row[f"{st}_p95"] = float("nan")
                    row[f"{st}_recall_mean"] = float("nan")
                    row[f"{st}_n"] = 0
                else:
                    wall = [float(r["wall_p50_ms"]) for r in cell]
                    rec = [float(r["recall_at_10"]) for r in cell]
                    row[f"{st}_p50"] = round(percentile(wall, 50), 2)
                    row[f"{st}_p95"] = round(percentile(wall, 95), 2)
                    row[f"{st}_recall_mean"] = round(statistics.mean(rec), 3)
                    row[f"{st}_n"] = len(cell)
            hot = row.get("hot_p50", float("nan"))
            cold = row.get("cold_p50", float("nan"))
            ok = (isinstance(hot, (int, float)) and hot > 0
                  and not (isinstance(cold, float) and math.isnan(cold)))
            row["inflation_ratio"] = round(cold / hot, 2) if ok else float("nan")
            table.append(row)

    out = OUT / "agg_cold_cache.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
        w.writeheader()
        w.writerows(table)
    return {"rows": table}
# ---------------------------------------------------------------------------
# 4) PAC bounds (Table X)
# ---------------------------------------------------------------------------

def aggregate_pac() -> dict:
    rows = read_csv(R / "results_pac.csv")
    table = []
    for r in rows:
        table.append({
            "bucket": r["bucket"],
            "bucket_label": BUCKET_LABEL.get(r["bucket"], r["bucket"]),
            "strategy": r["strategy"],
            "n_seeds": int(r["n_seeds"]),
            "queries_per_seed": int(r["queries_per_seed"]),
            "mean_recall": float(r["mean_recall"]),
            "std_recall": float(r["std_recall"]),
            "min_recall": float(r["min_recall"]),
            "max_recall": float(r["max_recall"]),
            "empirical_ci95": (
                f"[{float(r['ci95_lower']):.3f}, {float(r['ci95_upper']):.3f}]"
            ),
            "empirical_ci_width": float(r["ci95_width"]),
            "bernstein_bound_per_query": float(r["bernstein_bound_per_query"]),
            "ci_within_pac": r["ci_within_pac"],
            "delta": float(r["delta"]),
        })
    out = OUT / "agg_pac.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
        w.writeheader()
        w.writerows(table)
    coverage = sum(1 for r in table if r["ci_within_pac"] == "True") / len(table)
    return {"rows": table, "coverage_rate": coverage, "n_cells": len(table)}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _row(rows, b, s):
    for r in rows:
        if r["bucket"] == b and r["strategy"] == s:
            return r
    return None


def main() -> None:
    print("Aggregating scale ...")
    scale = aggregate_scale()
    print(f"  -> {len(scale['rows'])} cells in {OUT / 'agg_scale.csv'}")
    print("Aggregating q_error ...")
    qerr = aggregate_q_error()
    print(f"  -> {len(qerr['rows'])} cells in {OUT / 'agg_q_error.csv'}")
    print("Aggregating cold_cache ...")
    cc = aggregate_cold_cache()
    print(f"  -> {len(cc['rows'])} cells in {OUT / 'agg_cold_cache.csv'}")
    print("Aggregating pac ...")
    pac = aggregate_pac()
    print(f"  -> {len(pac['rows'])} cells in {OUT / 'agg_pac.csv'}"
          f"  (empirical coverage: {pac['coverage_rate']*100:.1f}%)")

    summary = {
        "scale": {
            "sql_first_p50_50_100_pct_ms": _row(scale["rows"], "sel_050_100", "SQL_FIRST")["wall_p50_ms"],
            "hnsw_hybrid_p50_50_100_pct_ms": _row(scale["rows"], "sel_050_100", "HNSW_HYBRID")["wall_p50_ms"],
            "hnsw_hybrid_speedup_50_100_pct": _row(scale["rows"], "sel_050_100", "HNSW_HYBRID")["speedup_vs_sql_first"],
            "hnsw_hybrid_recall_50_100_pct": _row(scale["rows"], "sel_050_100", "HNSW_HYBRID")["recall_mean"],
            "hnsw_hybrid_recall_000_005_pct": _row(scale["rows"], "sel_000_005", "HNSW_HYBRID")["recall_mean"],
        },
        "q_error": {
            "labels": qerr["labels"],
            "n_plan_switches_to_hnsw": sum(
                1 for s in qerr["plan_switches"]
                if s["dominant_strategy"] == "HNSW_HYBRID"
            ),
            "n_total_buckets": len(qerr["plan_switches"]),
        },
        "cold_cache": {
            "hnsw_hybrid_inflation_50_100": _row(cc["rows"], "sel_050_100", "HNSW_HYBRID")["inflation_ratio"],
            "sql_first_inflation_50_100": _row(cc["rows"], "sel_050_100", "SQL_FIRST")["inflation_ratio"],
        },
        "pac": {
            "n_cells": pac["n_cells"],
            "empirical_coverage": pac["coverage_rate"],
        },
    }
    with (OUT / "agg_summary.json").open("w") as f:
        json.dump(summary, f, indent=2)
    print()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
