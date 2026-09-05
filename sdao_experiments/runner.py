"""Config-driven benchmark runner for SDAO experiments."""
from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg2

from .config import ExperimentConfig
from .workload import (
    WorkloadQuery, _normalize_template, bucket_for, read_fvecs,
)

STRATEGIES = ("SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID")
if STRATEGIES[0] != "SQL_FIRST":
    raise RuntimeError("STRATEGIES[0] must be 'SQL_FIRST'")


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _vector_literal(vector, dim):
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


def recall_at_10(result_ids, reference_ids):
    ref = set(reference_ids)
    return 1.0 if not ref else len(set(result_ids) & ref) / len(ref)


def _build_predicate(query):
    if query.template == "two_categories":
        from .workload import _build_two_categories
        return _build_two_categories(query.category)
    if query.template == "three_categories":
        from .workload import _build_three_categories
        return _build_three_categories(query.category)
    return _normalize_template(
        query.category, query.price_limit, query.in_stock, query.template
    )
def _build_statement(cfg, query, strategy, vector_literal):
    table = cfg.table_name
    predicate_sql, predicate_params = _build_predicate(query)
    if strategy == "SQL_FIRST":
        return (
            f"SELECT id FROM {table} WHERE {predicate_sql} "
            "ORDER BY embedding <-> %s::vector, id LIMIT %s",
            predicate_params + (vector_literal, cfg.top_k),
            {"enable_indexscan": "off"},
        )
    if strategy == "VECTOR_FIRST_HNSW":
        return (
            f"WITH candidates AS MATERIALIZED ("
            f"SELECT id, embedding <-> %s::vector AS distance "
            f"FROM {table} ORDER BY embedding <-> %s::vector LIMIT {cfg.vector_first_budget}) "
            f"SELECT candidates.id FROM candidates JOIN {table} item ON item.id = candidates.id "
            f"WHERE {predicate_sql} "
            "ORDER BY candidates.distance, candidates.id LIMIT %s",
            (vector_literal, vector_literal) + predicate_params + (cfg.top_k,),
            {"hnsw.ef_search": cfg.hnsw_ef_search, "ivfflat.probes": max(cfg.ivfflat_probes, 1000)},
        )
    if strategy == "HNSW_HYBRID":
        return (
            f"SELECT id FROM {table} WHERE {predicate_sql} "
            "ORDER BY embedding <-> %s::vector LIMIT %s",
            predicate_params + (vector_literal, cfg.top_k),
            {"hnsw.ef_search": cfg.hnsw_ef_search, "ivfflat.probes": max(cfg.ivfflat_probes, 1000)},
        )
    if strategy == "IVFFLAT_HYBRID":
        return (
            f"SELECT id FROM {table} WHERE {predicate_sql} "
            "ORDER BY embedding <-> %s::vector LIMIT %s",
            predicate_params + (vector_literal, cfg.top_k),
            {"ivfflat.probes": cfg.ivfflat_probes, "hnsw.ef_search": max(cfg.hnsw_ef_search, 1000)},
        )
    raise ValueError(f"unknown strategy: {strategy}")


def _classify_plan(strategy, index_names):
    lowered = [str(n).lower() for n in index_names]
    ann_used = any("hnsw" in n or "ivfflat" in n for n in lowered)
    if any("ivfflat" in n for n in lowered):
        access_path = "ivfflat_index"
    elif any("hnsw" in n for n in lowered):
        access_path = "hnsw_index"
    elif lowered:
        access_path = "exact_bitmap"
    else:
        access_path = "exact_seq"
    needle = "hnsw" if strategy in ("VECTOR_FIRST_HNSW", "HNSW_HYBRID") else (
        "ivfflat" if strategy == "IVFFLAT_HYBRID" else None
    )
    verified = (not ann_used) if needle is None else any(needle in n for n in lowered)
    return verified, access_path


def _walk_index_names(node):
    names = []
    if node.get("Index Name"):
        names.append(node["Index Name"])
    for child in node.get("Plans", []):
        names.extend(_walk_index_names(child))
    return names


def _set_session_settings(cursor, settings):
    for k, v in settings.items():
        cursor.execute("SELECT set_config(%s, %s, true)", (k, str(v)))
def execute_once(cfg, connection, query, strategy, reference_ids=None):
    vector_literal = _vector_literal(query.vector, cfg.vector_dimension)
    statement, params, settings = _build_statement(cfg, query, strategy, vector_literal)
    with connection.cursor() as cursor:
        _set_session_settings(cursor, settings)
        started = time.perf_counter_ns()
        cursor.execute(statement, params)
        result_ids = [int(r[0]) for r in cursor.fetchall()]
        latency_ms = (time.perf_counter_ns() - started) / 1_000_000
    recall = recall_at_10(result_ids, reference_ids) if reference_ids is not None else 1.0
    return result_ids, latency_ms, recall


def capture_plan(cfg, connection, query, strategy):
    vector_literal = _vector_literal(query.vector, cfg.vector_dimension)
    statement, params, settings = _build_statement(cfg, query, strategy, vector_literal)
    with connection.cursor() as cursor:
        _set_session_settings(cursor, settings)
        cursor.execute("EXPLAIN (FORMAT JSON) " + statement, params)
        row = cursor.fetchone()
    plan = row[0] if not isinstance(row[0], str) else json.loads(row[0])
    return _walk_index_names(plan[0]["Plan"])


def probe_selectivity(cfg, connection, query):
    predicate_sql, params = _build_predicate(query)
    with connection.cursor() as cursor:
        cursor.execute(
            f"EXPLAIN (FORMAT JSON) SELECT id FROM {cfg.table_name} WHERE {predicate_sql}",
            params,
        )
        row = cursor.fetchone()
    plan = row[0] if not isinstance(row[0], str) else json.loads(row[0])
    return float(plan[0]["Plan"]["Plan Rows"]) / cfg.dataset_size
def build_calibration_map(observations):
    grouped = defaultdict(list)
    for obs in observations:
        grouped[(obs["strategy"], obs["bucket"])].append(obs)
    out = {}
    for key, items in grouped.items():
        latencies = [o["latency_ms"] for o in items]
        recalls = [o["recall_at_10"] for o in items]
        out[key] = {
            "median_latency_ms": float(np.median(latencies)),
            "mean_latency_ms": float(np.mean(latencies)),
            "min_recall": float(np.min(recalls)),
            "mean_recall": float(np.mean(recalls)),
            "p05_recall": float(np.quantile(recalls, 0.05)),
            "frac_above_target": float(np.mean([r >= 0.95 for r in recalls])),
            "n": len(items),
            "recalls": recalls,
        }
    return out


def admission_decision(cfg, bucket, calibration):
    """Apply the configured admission policy.

    Returns (selected_strategy, feasible, decision_reason, predicted_latency,
             per_strategy_decision_details).
    """
    feasible = ["SQL_FIRST"]
    per_strategy = {}
    for strategy in STRATEGIES[1:]:
        stats = calibration.get((strategy, bucket))
        if stats is None or stats.get("n", 0) < cfg.min_calibration_observations:
            per_strategy[strategy] = {"feasible": False, "reason": "no calibration data"}
            continue
        recalls = np.asarray(stats["recalls"])
        n = len(recalls)
        if cfg.admission_policy == "min_recall":
            statistic = float(recalls.min())
            ok = statistic >= cfg.target_recall
            reason = f"min_recall={statistic:.3f} target={cfg.target_recall:.3f}"
        elif cfg.admission_policy == "mean_recall":
            statistic = float(recalls.mean())
            ok = statistic >= cfg.target_recall
            reason = f"mean_recall={statistic:.3f} target={cfg.target_recall:.3f}"
        elif cfg.admission_policy == "lcb_recall":
            n_boot = 1000
            rng = np.random.default_rng(cfg.seed)
            boot_means = np.empty(n_boot)
            for i in range(n_boot):
                sample = rng.choice(recalls, size=n, replace=True)
                boot_means[i] = sample.mean()
            alpha = 1.0 - cfg.admission_confidence
            statistic = float(np.quantile(boot_means, alpha))
            ok = statistic >= cfg.target_recall
            reason = (
                f"lcb{cfg.admission_confidence:.2f}={statistic:.3f} "
                f"target={cfg.target_recall:.3f}"
            )
        elif cfg.admission_policy == "quantile_recall":
            statistic = float(np.quantile(recalls, cfg.admission_quantile))
            ok = statistic >= cfg.target_recall
            reason = (
                f"p{int(cfg.admission_quantile*100)}_recall={statistic:.3f} "
                f"target={cfg.target_recall:.3f}"
            )
        else:
            raise ValueError(f"unknown admission policy: {cfg.admission_policy}")
        per_strategy[strategy] = {
            "feasible": bool(ok), "statistic": statistic, "reason": reason, "n": n,
        }
        if ok:
            feasible.append(strategy)
    best_strategy = "SQL_FIRST"
    best_latency = calibration.get(
        ("SQL_FIRST", bucket), {}).get("median_latency_ms", float("inf"))
    for strategy in feasible:
        lat = calibration.get((strategy, bucket), {}).get("median_latency_ms", float("inf"))
        if lat < best_latency:
            best_latency = lat
            best_strategy = strategy
    return best_strategy, feasible, "lowest_median_latency", best_latency, per_strategy
RAW_FIELDS = (
    "ts_utc", "phase", "repetition", "query_id", "strategy",
    "template", "category", "price_limit", "in_stock",
    "target_bucket_idx", "estimated_selectivity", "bucket",
    "latency_ms", "recall_at_10", "plan_verified", "access_path",
    "adaptive_selected", "is_adaptive_selection",
)


def _to_raw_row(obs, phase, adaptive_selected=""):
    return {
        "ts_utc": _utc_now(),
        "phase": phase,
        "repetition": obs.get("repetition", 0),
        "query_id": obs["query_id"],
        "strategy": obs["strategy"],
        "template": obs.get("template", ""),
        "category": obs.get("category", ""),
        "price_limit": obs.get("price_limit", ""),
        "in_stock": obs.get("in_stock", ""),
        "target_bucket_idx": obs.get("target_bucket_idx", -1),
        "estimated_selectivity": obs.get("estimated_selectivity", 0.0),
        "bucket": obs.get("bucket", ""),
        "latency_ms": obs.get("latency_ms", 0.0),
        "recall_at_10": obs.get("recall_at_10", 0.0),
        "plan_verified": obs.get("plan_verified", False),
        "access_path": obs.get("access_path", ""),
        "adaptive_selected": adaptive_selected,
        "is_adaptive_selection": obs.get("strategy", "") == adaptive_selected,
    }


def run_calibration_phase(cfg, connection, calibration_queries, raw_writer):
    observations = []
    for q in calibration_queries:
        bucket = bucket_for(q.estimated_selectivity, cfg.selectivity_buckets)
        plan_cache = {}
        for rep in range(cfg.repetitions_calibration):
            reference_ids = None
            for strategy in STRATEGIES:
                if strategy == "SQL_FIRST" and reference_ids is None:
                    result_ids, latency_ms, _ = execute_once(
                        cfg, connection, q, strategy, reference_ids=None
                    )
                    reference_ids = result_ids
                    recall = 1.0
                else:
                    result_ids, latency_ms, recall = execute_once(
                        cfg, connection, q, strategy, reference_ids=reference_ids
                    )
                if strategy not in plan_cache:
                    try:
                        plan_cache[strategy] = capture_plan(
                            cfg, connection, q, strategy)
                    except Exception:
                        plan_cache[strategy] = []
                verified, access_path = _classify_plan(
                    strategy, plan_cache[strategy])
                obs = {
                    "query_id": q.query_id, "strategy": strategy,
                    "template": q.template, "category": q.category,
                    "price_limit": q.price_limit, "in_stock": q.in_stock,
                    "target_bucket_idx": q.target_bucket_idx,
                    "estimated_selectivity": q.estimated_selectivity,
                    "bucket": bucket, "latency_ms": latency_ms,
                    "recall_at_10": recall, "repetition": rep,
                    "plan_verified": verified, "access_path": access_path,
                }
                observations.append(obs)
                row = _to_raw_row(obs, phase="calibration")
                raw_writer.writerow(row)
    return observations
def run_heldout_phase(cfg, connection, test_queries, calibration, raw_writer):
    test_records = []
    decision_records = []
    for q in test_queries:
        bucket = bucket_for(q.estimated_selectivity, cfg.selectivity_buckets)
        selected, feasible, reason, predicted_lat, per_strategy = admission_decision(
            cfg, bucket, calibration
        )
        decision_records.append({
            "query_id": q.query_id,
            "estimated_selectivity": q.estimated_selectivity,
            "bucket": bucket,
            "feasible": feasible,
            "selected": selected,
            "reason": reason,
            "predicted_latency_ms": predicted_lat,
            "per_strategy_decision": per_strategy,
        })
        plan_cache = {}
        per_strategy_runs = {s: [] for s in STRATEGIES}
        for rep in range(cfg.repetitions_heldout):
            reference_ids = None
            for strategy in STRATEGIES:
                if strategy == "SQL_FIRST" and reference_ids is None:
                    result_ids, latency_ms, _ = execute_once(
                        cfg, connection, q, strategy, reference_ids=None
                    )
                    reference_ids = result_ids
                    recall = 1.0
                else:
                    result_ids, latency_ms, recall = execute_once(
                        cfg, connection, q, strategy, reference_ids=reference_ids
                    )
                if strategy not in plan_cache:
                    try:
                        plan_cache[strategy] = capture_plan(
                            cfg, connection, q, strategy)
                    except Exception:
                        plan_cache[strategy] = []
                verified, access_path = _classify_plan(
                    strategy, plan_cache[strategy])
                obs = {
                    "query_id": q.query_id, "strategy": strategy,
                    "template": q.template, "category": q.category,
                    "price_limit": q.price_limit, "in_stock": q.in_stock,
                    "target_bucket_idx": q.target_bucket_idx,
                    "estimated_selectivity": q.estimated_selectivity,
                    "bucket": bucket, "latency_ms": latency_ms,
                    "recall_at_10": recall, "repetition": rep,
                    "plan_verified": verified, "access_path": access_path,
                }
                row = _to_raw_row(
                    obs, phase="heldout", adaptive_selected=selected)
                raw_writer.writerow(row)
                per_strategy_runs[strategy].append(obs)
        for strategy in STRATEGIES:
            runs = per_strategy_runs[strategy]
            if not runs:
                continue
            latencies = [r["latency_ms"] for r in runs]
            recalls = [r["recall_at_10"] for r in runs]
            test_records.append({
                "query_id": q.query_id,
                "strategy": strategy,
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
    return test_records, decision_records
def run_experiment(cfg, connection, query_vectors):
    """Run a complete experiment. Returns paths to all output files."""
    from .workload import WorkloadGenerator

    out_dir = Path(cfg.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg.to_json(out_dir / "config.json")
    run_started = _utc_now()

    # Generate workload
    bucket_counts = cfg.bucket_target_counts
    if len(bucket_counts) != len(cfg.selectivity_buckets):
        bucket_counts = tuple([cfg.total_queries() // len(cfg.selectivity_buckets)] * len(cfg.selectivity_buckets))
    generator = WorkloadGenerator(cfg, connection)
    queries = generator.generate(query_vectors, bucket_counts)
    if len(queries) != cfg.total_queries():
        print(
            f"WARNING: requested {cfg.total_queries()} queries, "
            f"got {len(queries)}. Truncating/padding not applied — "
            f"downstream split may fail."
        )
    tuning, calibration_queries, test_queries = generator.split_workload(queries)
    print(f"Workload: {len(tuning)} tuning, {len(calibration_queries)} "
          f"calibration, {len(test_queries)} test queries.")

    # Save workload metadata
    wl_path = out_dir / "workload.jsonl"
    with wl_path.open("w") as f:
        for q in queries:
            f.write(json.dumps({
                "query_id": q.query_id, "template": q.template,
                "category": q.category, "price_limit": q.price_limit,
                "in_stock": q.in_stock, "target_bucket_idx": q.target_bucket_idx,
                "estimated_selectivity": q.estimated_selectivity, "bucket": q.bucket,
            }) + "\n")

    # Open raw CSV writer
    raw_path = out_dir / "raw_per_execution.csv"
    with raw_path.open("w", newline="") as raw_file:
        raw_writer = csv.DictWriter(raw_file, fieldnames=RAW_FIELDS)
        raw_writer.writeheader()
        # Calibration
        print("Running calibration phase...")
        calib_obs = run_calibration_phase(
            cfg, connection, calibration_queries, raw_writer
        )
        calibration = build_calibration_map(calib_obs)
        # Save calibration map
        calib_summary = {
            str(k): {kk: vv for kk, vv in v.items() if kk != "recalls"}
            for k, v in calibration.items()
        }
        (out_dir / "calibration_map.json").write_text(
            json.dumps(calib_summary, indent=2) + "\n"
        )
        # Held-out
        print("Running held-out phase...")
        test_records, decision_records = run_heldout_phase(
            cfg, connection, test_queries, calibration, raw_writer
        )

    # Persist per-query and decision log
    pd.DataFrame(test_records).to_csv(out_dir / "per_query.csv", index=False)
    (out_dir / "decision_log.json").write_text(
        json.dumps(decision_records, indent=2) + "\n"
    )

    # Summary
    summary = summarize(test_records, cfg.target_recall)
    summary.to_csv(out_dir / "summary.csv", index=False)

    # Run metadata
    meta = {
        "started_at_utc": run_started,
        "finished_at_utc": _utc_now(),
        "config_path": str(out_dir / "config.json"),
        "raw_csv": str(raw_path),
        "per_query_csv": str(out_dir / "per_query.csv"),
        "summary_csv": str(out_dir / "summary.csv"),
        "decision_log": str(out_dir / "decision_log.json"),
        "calibration_map": str(out_dir / "calibration_map.json"),
        "n_queries": len(queries),
        "n_calibration": len(calibration_queries),
        "n_test": len(test_queries),
    }
    (out_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote experiment artifacts to {out_dir}")
    print(summary.to_string(index=False))
    return {
        "out_dir": out_dir,
        "summary": summary,
        "test_records": test_records,
        "decision_records": decision_records,
        "calibration": calibration,
    }


def summarize(test_records, target_recall):
    frame = pd.DataFrame(test_records)
    rows = []
    for strategy, group in frame.groupby("strategy"):
        rows.append({
            "strategy": strategy,
            "queries": len(group),
            "mean_latency_ms": float(group["median_latency_ms"].mean()),
            "median_latency_ms": float(group["median_latency_ms"].median()),
            "p95_latency_ms": float(group["median_latency_ms"].quantile(0.95)),
            "std_latency_ms": float(group["median_latency_ms"].std()),
            "mean_recall_at_10": float(group["recall_at_10"].mean()),
            "min_recall_at_10": float(group["recall_at_10"].min()),
            "fraction_recall_at_least_target": float(
                (group["recall_at_10"] >= target_recall).mean()
            ),
        })
    return pd.DataFrame(rows).sort_values("strategy").reset_index(drop=True)
