"""Calibration + held-out driver for SDAO experiments."""
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
from sdao_experiments.workload import WorkloadGenerator, bucket_for, read_fvecs
from sdao_experiments.runner import (
    STRATEGIES, _classify_plan, _to_raw_row, capture_plan, execute_once,
)


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def admit(calibration, bucket, policy, target_recall, conf=0.95, q=0.05):
    feasible = ["SQL_FIRST"]
    per_strategy = {}
    for strat in STRATEGIES:
        st = calibration.get((strat, bucket))
        if not st or st["n"] == 0 or not st.get("recalls"):
            per_strategy[strat] = {"feasible": False, "reason": "no cal data", "statistic": None, "n": 0}
            continue
        recalls = np.asarray(st["recalls"])
        n = len(recalls)
        if policy == "min_recall":
            statistic = float(recalls.min()); ok = statistic >= target_recall
            reason = f"R_min={statistic:.3f} target={target_recall:.3f}"
        elif policy == "mean_recall":
            statistic = float(recalls.mean()); ok = statistic >= target_recall
            reason = f"R_mean={statistic:.3f} target={target_recall:.3f}"
        elif policy == "quantile_recall":
            statistic = float(np.quantile(recalls, q)); ok = statistic >= target_recall
            reason = f"P{int(q*100)}={statistic:.3f} target={target_recall:.3f}"
        elif policy == "lcb_recall":
            rng = np.random.default_rng(42)
            bm = np.array([rng.choice(recalls, size=n, replace=True).mean() for _ in range(1000)])
            alpha = 1.0 - conf
            statistic = float(np.quantile(bm, alpha)); ok = statistic >= target_recall
            reason = f"LCB{conf:.0%}={statistic:.3f} target={target_recall:.3f}"
        elif policy == "failure_rate":
            k = int(np.sum(recalls < target_recall)); n_obs = n
            z = stats.norm.ppf(0.95); phat = k / n_obs
            denom = 1 + z*z/n_obs
            center = (phat + z*z/(2*n_obs)) / denom
            margin = z*np.sqrt((phat*(1-phat) + z*z/(4*n_obs))/n_obs) / denom
            upper = center + margin; ok = upper <= (1 - target_recall)
            statistic = float(upper)
            reason = f"Wilson-UB={statistic:.3f} budget={(1-target_recall):.3f}"
        else:
            raise ValueError(f"unknown policy: {policy}")
        per_strategy[strat] = {"feasible": bool(ok), "statistic": statistic, "reason": reason, "n": n}
        if ok:
            feasible.append(strat)
    best = "SQL_FIRST"
    best_lat = calibration.get(("SQL_FIRST", bucket), {}).get("median_latency_ms", float("inf"))
    for s in feasible:
        lat = calibration.get((s, bucket), {}).get("median_latency_ms", float("inf"))
        if lat < best_lat:
            best_lat = lat; best = s
    return best, feasible, "lowest_median_latency", best_lat, per_strategy


def run_calibration(cfg, conn, calibration_queries, raw_writer, warmup):
    observations = []
    for qi, q in enumerate(calibration_queries):
        bucket = bucket_for(q.estimated_selectivity, cfg.selectivity_buckets)
        if warmup:
            for s in STRATEGIES:
                try: execute_once(cfg, conn, q, s, reference_ids=None)
                except Exception: pass
        plan_cache = {}
        for strategy in STRATEGIES:
            if strategy == "SQL_FIRST":
                result_ids, lat, _ = execute_once(cfg, conn, q, strategy, reference_ids=None)
                reference_ids = result_ids; recall = 1.0
            else:
                result_ids, lat, recall = execute_once(cfg, conn, q, strategy, reference_ids=reference_ids)
            if strategy not in plan_cache:
                try: plan_cache[strategy] = capture_plan(cfg, conn, q, strategy)
                except Exception: plan_cache[strategy] = []
            verified, access_path = _classify_plan(strategy, plan_cache[strategy])
            obs = {
                "query_id": q.query_id, "strategy": strategy,
                "template": q.template, "category": q.category,
                "price_limit": q.price_limit, "in_stock": q.in_stock,
                "target_bucket_idx": q.target_bucket_idx,
                "estimated_selectivity": q.estimated_selectivity,
                "bucket": bucket, "latency_ms": lat,
                "recall_at_10": recall, "repetition": 0,
                "plan_verified": verified, "access_path": access_path,
            }
            observations.append(obs)
            raw_writer.writerow(_to_raw_row(obs, phase="calibration"))
        if (qi + 1) % 25 == 0:
            print(f"  cal: {qi+1}/{len(calibration_queries)}", flush=True)
    return observations


def run_heldout(cfg, conn, test_queries, calibration, raw_writer, reps, policy):
    test_records, decision_records = [], []
    for qi, q in enumerate(test_queries):
        bucket = bucket_for(q.estimated_selectivity, cfg.selectivity_buckets)
        result = admit(
            calibration, bucket, policy, cfg.target_recall,
            cfg.admission_confidence, cfg.admission_quantile,
        )
        if result is None:
            print(f"  WARN: admit returned None for q={q.query_id} bucket={bucket}", flush=True)
            continue
        selected, feasible, reason, predicted_lat, per_strategy_dec = result
        decision_records.append({
            "query_id": q.query_id, "estimated_selectivity": q.estimated_selectivity,
            "bucket": bucket, "feasible": feasible, "selected": selected,
            "reason": reason, "predicted_latency_ms": predicted_lat,
            "per_strategy_decision": per_strategy_dec,
        })
        plan_cache = {}
        per_strategy_runs = {s: [] for s in STRATEGIES}
        for rep in range(reps):
            reference_ids = None
            for strategy in STRATEGIES:
                if strategy == "SQL_FIRST" and reference_ids is None:
                    result_ids, lat, _ = execute_once(cfg, conn, q, strategy, reference_ids=None)
                    reference_ids = result_ids; recall = 1.0
                else:
                    result_ids, lat, recall = execute_once(cfg, conn, q, strategy, reference_ids=reference_ids)
                if strategy not in plan_cache:
                    try: plan_cache[strategy] = capture_plan(cfg, conn, q, strategy)
                    except Exception: plan_cache[strategy] = []
                verified, access_path = _classify_plan(strategy, plan_cache[strategy])
                obs = {
                    "query_id": q.query_id, "strategy": strategy,
                    "template": q.template, "category": q.category,
                    "price_limit": q.price_limit, "in_stock": q.in_stock,
                    "target_bucket_idx": q.target_bucket_idx,
                    "estimated_selectivity": q.estimated_selectivity,
                    "bucket": bucket, "latency_ms": lat,
                    "recall_at_10": recall, "repetition": rep,
                    "plan_verified": verified, "access_path": access_path,
                }
                raw_writer.writerow(_to_raw_row(obs, phase="heldout", adaptive_selected=selected))
                per_strategy_runs[strategy].append(obs)
        for strategy in STRATEGIES:
            runs = per_strategy_runs[strategy]
            if not runs: continue
            latencies = [r["latency_ms"] for r in runs]
            recalls = [r["recall_at_10"] for r in runs]
            test_records.append({
                "query_id": q.query_id, "strategy": strategy,
                "median_latency_ms": float(np.median(latencies)),
                "mean_latency_ms": float(np.mean(latencies)),
                "p95_latency_ms": float(np.quantile(latencies, 0.95)),
                "recall_at_10": float(np.median(recalls)),
                "estimated_selectivity": q.estimated_selectivity,
                "bucket": bucket,
                "adaptive_selected": selected,
                "is_adaptive_selection": strategy == selected,
                "repetitions": len(runs),
            })
        if (qi + 1) % 25 == 0:
            print(f"  heldout: {qi+1}/{len(test_queries)}", flush=True)
    return test_records, decision_records


def build_calibration_map(observations):
    grouped = defaultdict(list)
    for o in observations:
        grouped[(o["strategy"], o["bucket"])].append(o)
    out = {}
    for key, items in grouped.items():
        lats = [o["latency_ms"] for o in items]
        recs = [o["recall_at_10"] for o in items]
        out[key] = {
            "median_latency_ms": float(np.median(lats)),
            "mean_latency_ms": float(np.mean(lats)),
            "min_recall": float(np.min(recs)),
            "mean_recall": float(np.mean(recs)),
            "p05_recall": float(np.quantile(recs, 0.05)),
            "frac_above_target": float(np.mean([r >= 0.95 for r in recs])),
            "n": len(items), "recalls": recs,
        }
    return out


def bootstrap_ci(values, confidence=0.95, n_boot=2000, seed=42):
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n_boot)])
    alpha = (1 - confidence) / 2
    return {
        "n": int(len(arr)), "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
        "ci_lo": float(np.quantile(means, alpha)),
        "ci_hi": float(np.quantile(means, 1 - alpha)),
    }


def make_summary(test_records, cfg):
    pq = pd.DataFrame(test_records)
    rows = []
    for strategy, group in pq.groupby("strategy"):
        ci_lat = bootstrap_ci(group["median_latency_ms"])
        ci_rec = bootstrap_ci(group["recall_at_10"])
        rows.append({
            "strategy": strategy, "queries": len(group),
            "mean_latency_ms": float(group["median_latency_ms"].mean()),
            "median_latency_ms": float(group["median_latency_ms"].median()),
            "p95_latency_ms": float(group["median_latency_ms"].quantile(0.95)),
            "std_latency_ms": float(group["median_latency_ms"].std()),
            "mean_recall_at_10": float(group["recall_at_10"].mean()),
            "median_recall_at_10": float(group["recall_at_10"].median()),
            "min_recall_at_10": float(group["recall_at_10"].min()),
            "p05_recall": float(group["recall_at_10"].quantile(0.05)),
            "fraction_recall_at_least_target": float((group["recall_at_10"] >= cfg.target_recall).mean()),
            "latency_ci_lo": ci_lat["ci_lo"], "latency_ci_hi": ci_lat["ci_hi"],
            "recall_ci_lo": ci_rec["ci_lo"], "recall_ci_hi": ci_rec["ci_hi"],
        })
    summary = pd.DataFrame(rows).sort_values("strategy").reset_index(drop=True)
    adaptive_records = pq[pq["is_adaptive_selection"]]
    if len(adaptive_records) > 0:
        ci_lat = bootstrap_ci(adaptive_records["median_latency_ms"])
        ci_rec = bootstrap_ci(adaptive_records["recall_at_10"])
        ar = {
            "strategy": "Adaptive", "queries": len(adaptive_records),
            "mean_latency_ms": float(adaptive_records["median_latency_ms"].mean()),
            "median_latency_ms": float(adaptive_records["median_latency_ms"].median()),
            "p95_latency_ms": float(adaptive_records["median_latency_ms"].quantile(0.95)),
            "std_latency_ms": float(adaptive_records["median_latency_ms"].std()),
            "mean_recall_at_10": float(adaptive_records["recall_at_10"].mean()),
            "median_recall_at_10": float(adaptive_records["recall_at_10"].median()),
            "min_recall_at_10": float(adaptive_records["recall_at_10"].min()),
            "p05_recall": float(adaptive_records["recall_at_10"].quantile(0.05)),
            "fraction_recall_at_least_target": float((adaptive_records["recall_at_10"] >= cfg.target_recall).mean()),
            "latency_ci_lo": ci_lat["ci_lo"], "latency_ci_hi": ci_lat["ci_hi"],
            "recall_ci_lo": ci_rec["ci_lo"], "recall_ci_hi": ci_rec["ci_hi"],
        }
        summary = pd.concat([summary, pd.DataFrame([ar])], ignore_index=True)
    return summary, pq


def _fix_tuple_fields(d):
    out = {}
    for k, v in d.items():
        if k in ("predicate_columns", "selectivity_buckets"):
            out[k] = tuple(tuple(x) if isinstance(x, list) else x for x in v)
        elif k == "bucket_target_counts":
            out[k] = tuple(v)
        else:
            out[k] = v
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--policy", default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--skip-cal", action="store_true")
    parser.add_argument("--hnsw-ef-search", type=int, default=None)
    parser.add_argument("--ivfflat-probes", type=int, default=None)
    parser.add_argument("--vf-budget", type=int, default=None)
    args = parser.parse_args()

    cfg = ExperimentConfig.from_json(Path(args.config))
    d = cfg.to_dict()
    if args.seed is not None:
        d["seed"] = args.seed; d["split_seed"] = args.seed + 1
    d["results_dir"] = args.out_dir
    if args.policy: d["admission_policy"] = args.policy
    if args.hnsw_ef_search is not None: d["hnsw_ef_search"] = args.hnsw_ef_search
    if args.ivfflat_probes is not None: d["ivfflat_probes"] = args.ivfflat_probes
    if args.vf_budget is not None: d["vector_first_budget"] = args.vf_budget
    cfg = ExperimentConfig(**_fix_tuple_fields(d))

    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    cfg.to_json(out_dir / "config.json")
    warmup = not args.no_warmup; policy = cfg.admission_policy
    print(f"=== Run: out={out_dir} reps={args.reps} warmup={warmup} policy={policy} ===", flush=True)
    print(f"  hnsw.ef_search={cfg.hnsw_ef_search} ivfflat.probes={cfg.ivfflat_probes} vf_budget={cfg.vector_first_budget}", flush=True)

    conn = psycopg2.connect(host="localhost", user="sdao", dbname="sdao")
    conn.autocommit = False
    try:
        generator = WorkloadGenerator(cfg, conn)
        query_vectors = read_fvecs(Path(cfg.query_vector_path), cfg.vector_dimension)
        queries = generator.generate(query_vectors, list(cfg.bucket_target_counts))
        if len(queries) != cfg.total_queries():
            print(f"WARNING: generated {len(queries)} queries, expected {cfg.total_queries()}", flush=True)
        wl_path = out_dir / "workload.jsonl"
        with wl_path.open("w") as f:
            for q in queries:
                f.write(json.dumps({
                    "query_id": q.query_id, "template": q.template,
                    "category": q.category, "price_limit": q.price_limit,
                    "in_stock": q.in_stock, "target_bucket_idx": q.target_bucket_idx,
                    "estimated_selectivity": q.estimated_selectivity, "bucket": q.bucket,
                }) + "\n")
        tuning, calibration_queries, test_queries = generator.split_workload(queries)
        print(f"Workload: {len(tuning)} tuning, {len(calibration_queries)} cal, {len(test_queries)} test", flush=True)
        print(f"Cal buckets: {pd.Series([q.bucket for q in calibration_queries]).value_counts().to_dict()}", flush=True)
        print(f"Test buckets: {pd.Series([q.bucket for q in test_queries]).value_counts().to_dict()}", flush=True)

        calibration = {}
        if args.skip_cal and (out_dir / "calibration_map.json").exists():
            for k_str, v in json.loads((out_dir / "calibration_map.json").read_text()).items():
                key = tuple(json.loads(k_str))
                calibration[key] = v
            print("Loaded existing calibration_map.json", flush=True)
        else:
            raw_path = out_dir / "raw_per_execution.csv"
            with raw_path.open("w", newline="") as raw_file:
                raw_writer = csv.DictWriter(raw_file, fieldnames=(
                    "ts_utc", "phase", "repetition", "query_id", "strategy",
                    "template", "category", "price_limit", "in_stock",
                    "target_bucket_idx", "estimated_selectivity", "bucket",
                    "latency_ms", "recall_at_10", "plan_verified", "access_path",
                    "adaptive_selected", "is_adaptive_selection",
                ))
                raw_writer.writeheader()
                t0 = time.time()
                cal_obs = run_calibration(cfg, conn, calibration_queries, raw_writer, warmup)
                print(f"Calibration: {len(cal_obs)} obs in {time.time()-t0:.1f}s", flush=True)
                calibration = build_calibration_map(cal_obs)
                # Sanity check
                n_with_recalls = sum(1 for v in calibration.values() if v.get("recalls"))
                print(f"  calibration entries: {len(calibration)}, with-recalls: {n_with_recalls}", flush=True)
                cal_summary = {
                    str(k): dict(v)  # include everything including recalls
                    for k, v in calibration.items()
                }
                (out_dir / "calibration_map.json").write_text(json.dumps(cal_summary, indent=2) + "\n")
                t0 = time.time()
                test_records, decision_records = run_heldout(
                    cfg, conn, test_queries, calibration, raw_writer, args.reps, policy
                )
                print(f"Held-out: {len(test_records)} records in {time.time()-t0:.1f}s", flush=True)

        pd.DataFrame(test_records).to_csv(out_dir / "per_query.csv", index=False)
        (out_dir / "decision_log.json").write_text(json.dumps(decision_records, indent=2) + "\n")
        summary, pq = make_summary(test_records, cfg)
        summary.to_csv(out_dir / "summary.csv", index=False)
        print("\n=== Summary ===")
        print(summary.to_string(index=False), flush=True)

        sel_rows = []
        for qid, g in pq.groupby("query_id"):
            row = g.iloc[0]
            sel_rows.append({
                "query_id": qid, "bucket": row["bucket"],
                "estimated_selectivity": row["estimated_selectivity"],
                "adaptive_selected": row["adaptive_selected"],
            })
        sel_df = pd.DataFrame(sel_rows)
        sel_counts = sel_df.groupby(["bucket", "adaptive_selected"]).size().reset_index(name="count")
        sel_counts.to_csv(out_dir / "selection_by_bucket.csv", index=False)

        verification = pd.read_csv(out_dir / "raw_per_execution.csv")
        plan_summary = verification.groupby(["strategy", "plan_verified"]).size().reset_index(name="count")
        plan_summary.to_csv(out_dir / "plan_verification.csv", index=False)

        meta = {
            "started_at_utc": _utc_now(), "config_path": str(out_dir / "config.json"),
            "n_queries": len(queries), "n_calibration": len(calibration_queries),
            "n_test": len(test_queries), "reps": args.reps,
            "warmup": warmup, "admission_policy": policy,
            "hnsw_ef_search": cfg.hnsw_ef_search,
            "ivfflat_probes": cfg.ivfflat_probes,
            "vector_first_budget": cfg.vector_first_budget,
        }
        (out_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
        print(f"\nWrote artifacts to {out_dir}", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()