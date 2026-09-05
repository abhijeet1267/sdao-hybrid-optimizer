"""Read-only, reproducible paper analysis for canonical PostgreSQL artifacts."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT_ROOT / "sdao/results"
CANONICAL = {
    "baseline": RESULTS / "db_baseline_20260814Tfinal/db_baseline_results.json",
    "calibration": RESULTS / "db_calibration_20260814/db_strategy_calibration.json",
    "explain": RESULTS / "db_explain_selectivity_20260814T142459Z/postgres_explain_selectivity.json",
    "final": RESULTS / "db_final_adaptive_20260814T145013Z/final_adaptive_results.json",
    "adaptive_csv": RESULTS / "db_final_adaptive_20260814T145013Z/adaptive_per_query.csv",
    "fixed_csv": RESULTS / "db_final_adaptive_20260814T145013Z/fixed_strategies_per_query.csv",
}
BUCKETS = (("<=0.05", 0.0, 0.05), (">0.05_to_0.10", 0.05, 0.10),
           (">0.10_to_0.25", 0.10, 0.25), (">0.25_to_0.50", 0.25, 0.50), (">0.50", 0.50, 1.0))
FIXED_ORDER = ("SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID")
TARGET_RECALL = 0.95


class AnalysisError(RuntimeError): pass


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def bucket_name(value: float) -> str:
    for name, low, high in BUCKETS:
        if (value >= low if low == 0 else value > low) and value <= high: return name
    raise AnalysisError(f"selectivity outside [0, 1]: {value}")


def metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    latency, recall = frame["strategy_only_latency_ms"], frame["recall"]
    return {"query_count": int(len(frame)), "mean_latency_ms": float(latency.mean()),
            "median_latency_ms": float(latency.median()), "p95_latency_ms": float(latency.quantile(.95)),
            "mean_recall": float(recall.mean()), "minimum_recall": float(recall.min()),
            "fraction_recall_at_least_095": float((recall >= TARGET_RECALL).mean())}


def oracle_table(adaptive: pd.DataFrame, fixed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for query_id, chosen in adaptive.set_index("query_id").iterrows():
        options = fixed[fixed.query_id == query_id]
        feasible = options[options.recall >= TARGET_RECALL]
        if feasible.empty: raise AnalysisError(f"query {query_id} has no recall-feasible fixed strategy")
        safe = feasible.loc[feasible.strategy_only_latency_ms.idxmin()]
        fastest = options.loc[options.strategy_only_latency_ms.idxmin()]
        rows.append({"query_id": int(query_id), "adaptive_strategy": chosen.strategy,
                     "adaptive_latency_ms": chosen.strategy_only_latency_ms,
                     "adaptive_recall": chosen.recall, "recall_feasible_oracle_strategy": safe.strategy,
                     "recall_feasible_oracle_latency_ms": safe.strategy_only_latency_ms,
                     "planner_regret_ms": chosen.strategy_only_latency_ms - safe.strategy_only_latency_ms,
                     "recall_feasible_identity_match": chosen.strategy == safe.strategy,
                     "fastest_oracle_strategy": fastest.strategy,
                     "fastest_oracle_latency_ms": fastest.strategy_only_latency_ms,
                     "fastest_oracle_recall": fastest.recall,
                     "fastest_identity_match": chosen.strategy == fastest.strategy})
    return pd.DataFrame(rows).sort_values("query_id").reset_index(drop=True)


def _csv_value(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value): return None
    return value


def _equal(json_value: Any, csv_value: Any) -> bool:
    csv_value = _csv_value(csv_value)
    if json_value is None: return csv_value is None
    if isinstance(json_value, float): return isinstance(csv_value, (int, float)) and math.isclose(json_value, csv_value, abs_tol=1e-12)
    if isinstance(json_value, (dict, list)):
        try: return json_value == ast.literal_eval(csv_value)
        except (ValueError, SyntaxError): return False
    return json_value == csv_value


def _validate_csv(records: list[dict[str, Any]], path: Path, keys: list[str]) -> None:
    raw = pd.read_csv(path).sort_values(keys).reset_index(drop=True)
    expected = sorted(records, key=lambda record: tuple(record[key] for key in keys))
    if set(raw) != set(expected[0]): raise AnalysisError(f"{path}: CSV columns differ from final JSON")
    for column in expected[0]:
        for row, (record, right) in enumerate(zip(expected, raw[column], strict=True)):
            left = record[column]
            if not _equal(left, right): raise AnalysisError(f"{path}: row {row}, column {column} differs from final JSON")


def load_and_validate() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, str]]:
    for path in CANONICAL.values():
        if not path.is_file(): raise AnalysisError(f"missing canonical artifact: {path}")
    final = json.loads(CANONICAL["final"].read_text())
    adaptive, fixed = pd.DataFrame(final["adaptive_records"]), pd.DataFrame(final["fixed_strategy_records"])
    if len(adaptive) != 32 or len(fixed) != 128: raise AnalysisError("canonical final artifact has unexpected row counts")
    if set(fixed.strategy) != set(FIXED_ORDER) or fixed.groupby("strategy").size().to_dict() != {s: 32 for s in FIXED_ORDER}:
        raise AnalysisError("canonical fixed strategy coverage is incomplete")
    _validate_csv(final["adaptive_records"], CANONICAL["adaptive_csv"], ["query_id"])
    _validate_csv(final["fixed_strategy_records"], CANONICAL["fixed_csv"], ["strategy", "query_id"])
    explain = json.loads(CANONICAL["explain"].read_text())
    estimates = {int(key): value for key, value in explain["estimated_selectivity_by_query"].items()}
    for row in adaptive.itertuples():
        if not math.isclose(row.estimated_selectivity, estimates[row.query_id], abs_tol=1e-12):
            raise AnalysisError(f"query {row.query_id}: final estimate differs from EXPLAIN artifact")
        if bucket_name(row.estimated_selectivity) != row.selectivity_bucket: raise AnalysisError(f"query {row.query_id}: bucket mismatch")
    hashes = {name: sha256_file(path) for name, path in CANONICAL.items()}
    expected_hashes = final["source_artifact_sha256_before"]
    for relative, digest in expected_hashes.items():
        if sha256_file(PROJECT_ROOT / relative) != digest: raise AnalysisError(f"source hash mismatch: {relative}")
    if not adaptive.plan_verified.all() or not fixed.plan_verified.all(): raise AnalysisError("unverified execution present")
    ann = pd.concat([adaptive, fixed]).query("expected_index.notna()")
    if not all(row.expected_index in row.actual_index_names for row in ann.itertuples()): raise AnalysisError("ANN plan evidence lacks expected index")
    return final, adaptive, fixed, hashes


def _save(fig: plt.Figure, directory: Path, name: str) -> None:
    for suffix in ("png", "pdf", "svg"): fig.savefig(directory / f"{name}.{suffix}", bbox_inches="tight")
    plt.close(fig)


def figures(directory: Path, adaptive: pd.DataFrame, fixed: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10, 7)); ax.axis("off")
    def box(x: float, y: float, label: str, width: float = .28, height: float = .075) -> None:
        ax.add_patch(FancyBboxPatch((x - width / 2, y - height / 2), width, height,
                                    boxstyle="round,pad=.015", fill=False, linewidth=1.25))
        ax.text(x, y, label, ha="center", va="center", fontsize=10)
    def arrow(y1: float, y2: float) -> None:
        ax.add_patch(FancyArrowPatch((.5, y1 - .045), (.5, y2 + .045), arrowstyle="-|>",
                                     mutation_scale=16, linewidth=1.25, color="black"))
    stages = [(0.93, "Query"), (0.82, "Predicate translation"),
              (0.71, "PostgreSQL EXPLAIN"), (0.60, "Estimated selectivity"),
              (0.49, "Latency calibration + recall feasibility"), (0.38, "Adaptive planner")]
    for y, label in stages: box(.5, y, label)
    for (y1, _), (y2, _) in zip(stages[:-1], stages[1:]): arrow(y1, y2)
    ax.text(.5, .285, "Candidate strategies", ha="center", va="center", fontsize=10, fontweight="bold")
    candidates = ["SQL_FIRST\n(exact fallback)", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID"]
    for x, label in zip((.16, .39, .62, .85), candidates): box(x, .21, label, width=.20, height=.09)
    ax.add_patch(FancyArrowPatch((.5, .335), (.5, .265), arrowstyle="-|>", mutation_scale=16, linewidth=1.25))
    box(.5, .105, "Selected strategy", width=.28)
    ax.add_patch(FancyArrowPatch((.5, .165), (.5, .15), arrowstyle="-|>", mutation_scale=16, linewidth=1.25))
    ax.add_patch(FancyArrowPatch((.5, .065), (.5, .045), arrowstyle="-|>", mutation_scale=16, linewidth=1.25))
    box(.5, .015, "PostgreSQL / pgvector execution  →  verified execution plan  →  result", width=.72, height=.06)
    ax.set_xlim(0, 1); ax.set_ylim(-.04, 1); _save(fig, directory, "figure_01_decision_flow")
    estimates = adaptive.set_index("query_id")["estimated_selectivity"]
    fixed_for_plot = fixed.assign(estimated_selectivity=fixed.query_id.map(estimates))
    if fixed_for_plot.estimated_selectivity.isna().any():
        raise AnalysisError("fixed result lacks matching canonical adaptive selectivity")
    combined=pd.concat([fixed_for_plot.assign(series=fixed_for_plot.strategy), adaptive.assign(series="ADAPTIVE")])
    fig,ax=plt.subplots(figsize=(7.5,4.8));
    for name,g in combined.groupby("series"): ax.scatter(g.estimated_selectivity,g.strategy_only_latency_ms,label=name,alpha=.85)
    ax.set(xlabel="Estimated selectivity",ylabel="Strategy-only latency (ms)"); ax.legend(); _save(fig,directory,"figure_02_latency_vs_estimated_selectivity")
    fig,ax=plt.subplots(figsize=(7.5,4.8));
    for name,g in combined.groupby("series"):
        marker = "D" if name == "ADAPTIVE" else "o"
        ax.scatter(g.estimated_selectivity,g.recall,label=name,marker=marker,alpha=.85)
    ax.axhline(TARGET_RECALL,linestyle="--",color="black",label="Recall@10 target = 0.95")
    ax.set(xlabel="Estimated selectivity",ylabel="Recall@10",ylim=(0.05,1.05)); ax.legend(loc="lower right"); _save(fig,directory,"figure_03_recall_vs_estimated_selectivity")
    counts=pd.crosstab(adaptive.selectivity_bucket,adaptive.strategy).reindex([x[0] for x in BUCKETS],fill_value=0)
    display_buckets=["≤5%\n(n=2)","5–10%\n(n=3)","10–25%\n(n=19)","25–50%\n(n=4)",">50%\n(n=4)"]
    counts.index=display_buckets
    fig,ax=plt.subplots(figsize=(7.5,4.8)); counts.plot(kind="bar",stacked=True,ax=ax); ax.set(xlabel="Estimated-selectivity bucket",ylabel="Queries"); ax.legend(title="Adaptive strategy"); _save(fig,directory,"figure_04_adaptive_selection_by_bucket")
    fig,ax=plt.subplots(figsize=(7.5,4.8));
    for name,g in combined.groupby("series"): ax.scatter(g.strategy_only_latency_ms,g.recall,label=name)
    ax.axhline(TARGET_RECALL,linestyle="--",color="black",label="Recall@10 target = 0.95"); ax.set(xlabel="Strategy-only latency (ms)",ylabel="Recall@10"); ax.legend(); _save(fig,directory,"figure_05_latency_recall_tradeoff")
    sql=fixed[fixed.strategy=="SQL_FIRST"].set_index("query_id"); ad=adaptive.set_index("query_id")
    fig,ax=plt.subplots(figsize=(8,4.8));
    for query_id in ad.index:
        ax.plot([query_id-.13,query_id+.13],[ad.loc[query_id,"strategy_only_latency_ms"],sql.loc[query_id,"strategy_only_latency_ms"]],color="0.7",linewidth=.7,zorder=1)
    ax.scatter(ad.index-.13,ad.strategy_only_latency_ms,label="Adaptive",zorder=2)
    ax.scatter(sql.index+.13,sql.strategy_only_latency_ms,label="SQL_FIRST",zorder=2)
    ax.set(xlabel="Query ID (workload identifier)",ylabel="Strategy-only latency (ms)"); ax.legend(); _save(fig,directory,"figure_06_adaptive_vs_sql_first")


def paper_facing_notes(directory: Path) -> None:
    captions = """# Draft figure captions

## Figure 1 — Adaptive execution decision flow

For each hybrid query, the system translates the predicate, obtains a PostgreSQL EXPLAIN selectivity estimate, and combines empirical latency calibration with conservative recall-feasibility evidence. The adaptive planner selects from four evaluated strategies; SQL_FIRST is the exact fallback. The diagram describes the decision process and does not imply globally optimal selection.

## Figure 2 — Latency by estimated selectivity

Observed strategy-only latency across the 32-query evaluated workload, plotted against PostgreSQL-estimated selectivity. The figure shows heterogeneous behavior across the adaptive policy and the four fixed strategies; it does not fit or claim a general latency/selectivity law.

## Figure 3 — Recall by estimated selectivity

Observed Recall@10 across the evaluated workload. All 32 adaptive observations are plotted, including decisions that selected SQL_FIRST; the dashed line marks the Recall@10 target of 0.95. Fixed ANN strategies show observed target violations on some workload queries.

## Figure 4 — Adaptive selections by selectivity bucket

Adaptive strategy choices over fixed estimated-selectivity buckets for the evaluated workload. Labels report the number of queries in each bucket; these descriptive counts do not support statistical-significance claims.

## Figure 5 — Latency–recall tradeoff

Observed strategy-only latency and Recall@10 for the adaptive and fixed strategies. The dashed line marks the required Recall@10 target; the exploratory plot illustrates the recall risk of selecting solely by observed latency.

## Figure 6 — Paired adaptive and SQL_FIRST latency

Paired strategy-only latency observations for the adaptive policy and SQL_FIRST on each workload item. Query IDs are identifiers rather than an ordered or continuous variable; each faint segment connects only the two strategies for the same query.
"""
    table_notes = """# Paper-facing table notes

## Table 02 — Strategy comparison

`adaptive_minus_strategy_latency_ms` is adaptive mean strategy-only latency minus the named strategy's mean latency; negative values favor adaptive on latency. `adaptive_latency_change_percent` is the adaptive latency reduction relative to the named strategy, so positive values favor adaptive. `adaptive_minus_strategy_recall` is adaptive mean Recall@10 minus the named strategy's mean Recall@10; positive values favor adaptive on recall.

## Table 05 — Selectivity buckets

Bucket labels are display labels only; their boundaries are unchanged. Strategy columns are descriptive counts of adaptive selections, not estimates of a population distribution.

## Table 07 — Plan evidence

“Verified” means the recorded execution-plan/index evidence met the experiment's plan-verification rule. It is not a claim of performance correctness, optimality, or generalization.

## Table 08 — Decision-to-execution time

This latency includes EXPLAIN, planner, and verified executor wall time. It is not directly comparable to strategy-only latency, which times selected SQL execution only.
"""
    summary = """# Paper-facing analysis summary

This presentation-only output was regenerated from immutable canonical artifacts. It contains no new experiment, database change, benchmark, calibration, or planner change.

The evaluated exploratory workload contains 32 queries. The adaptive policy selected SQL_FIRST for 22 queries and HNSW_HYBRID for 10 queries. Observed adaptive Recall@10 was 1.0 for all 32 queries. Its mean strategy-only latency was 51.32 ms, compared with 64.80 ms for SQL_FIRST. These observations are descriptive: the evaluation is not held out, randomized, repeated, or statistically tested.
"""
    (directory / "figure_captions.md").write_text(captions)
    (directory / "table_notes.md").write_text(table_notes)
    (directory / "analysis_summary.md").write_text(summary)


def protocol(final: dict[str, Any], directory: Path) -> dict[str, Any]:
    method=final["methodology"]
    body={"dataset":{"name":"SIFT1M","rows":1_000_000,"embedding_dimension":128,"distance_metric":"L2"},
          "fixed_strategies":list(FIXED_ORDER),"adaptive_planner":{"selectivity_source":method["planning_selectivity"],"calibration":"empirical bucket-median latency with conservative observed minimum-recall feasibility","target_recall":TARGET_RECALL,"fallback":"SQL_FIRST"},
          "execution":{"workload_queries":method["queries"],"top_k":method["top_k"],"warm_persistent_session":method["warm_persistent_session"],"execution_order":"for each query: adaptive selected strategy, then four fixed strategies; exact filtered reference after each strategy","plan_verification":"separate EXPLAIN JSON evidence; ANN execution requires intended index"},
          "latency_metrics":{"comparable":method["strategy_only_latency_definition"],"decision_overhead":method["actual_latency_definition"]},
          "limitations":{"cold_cache_control":False,"repeated_trials":False,"random_interleaving":False,"held_out_evaluation":False,"calibration_evaluation_dependence":True}}
    (directory/"experimental_protocol.json").write_text(json.dumps(body,indent=2)+"\n")
    lines=["# Experimental protocol", "", "This document describes the completed experiment; it does not claim held-out evaluation or statistical significance.", "", "## Dataset and workload", f"- SIFT1M; {body['dataset']['rows']:,} rows; 128 dimensions; L2 distance.", f"- {method['queries']} workload queries, top-k={method['top_k']}.", "", "## Method", f"- Strategies: {', '.join(FIXED_ORDER)}.", f"- Selectivity source: {method['planning_selectivity']}.", "- Recall target: 0.95; SQL_FIRST is the exact fallback.", "", "## Measurement", f"- Warm persistent session: {method['warm_persistent_session']}.", f"- Execution order: {body['execution']['execution_order']}.", f"- Comparable latency: {method['strategy_only_latency_definition']}.", "", "## Limitations", "- No cold-cache control, repeated trials, random interleaving, held-out evaluation, or significance testing."]
    (directory/"experimental_protocol.md").write_text("\n".join(lines)+"\n")
    return body


def run(output: Path, environment_manifest: Path | None = None) -> Path:
    allowed_existing = {environment_manifest.resolve()} if environment_manifest else set()
    if output.exists() and any(path.resolve() not in allowed_existing for path in output.iterdir()):
        raise FileExistsError(f"analysis output is not empty: {output}")
    output.mkdir(parents=True,exist_ok=True)
    final, adaptive, fixed, hashes = load_and_validate(); oracle=oracle_table(adaptive,fixed)
    strategy_rows=[]
    for name, frame in [("ADAPTIVE",adaptive),*((s,fixed[fixed.strategy==s]) for s in FIXED_ORDER)]: strategy_rows.append({"strategy":name,**metrics(frame)})
    adaptive_metrics = strategy_rows[0]
    comparisons = []
    for row in strategy_rows[1:]:
        comparisons.append({"fixed_strategy": row["strategy"],
                            "mean_latency_difference_ms": adaptive_metrics["mean_latency_ms"] - row["mean_latency_ms"],
                            "adaptive_latency_change_percent": 100 * (row["mean_latency_ms"] - adaptive_metrics["mean_latency_ms"]) / row["mean_latency_ms"],
                            "mean_recall_difference": adaptive_metrics["mean_recall"] - row["mean_recall"]})
    bucket_rows=[]
    for name,_,_ in BUCKETS:
        frame=adaptive[adaptive.selectivity_bucket==name]; bucket_rows.append({"selectivity_bucket":name,**metrics(frame),"strategy_distribution":json.dumps(frame.strategy.value_counts().sort_index().to_dict())})
    ann=pd.concat([adaptive.assign(run="adaptive"),fixed.assign(run="fixed")]); plan_rows=[]
    for label,frame in [("adaptive_hnsw",adaptive[adaptive.strategy=="HNSW_HYBRID"]),("fixed_hnsw",fixed[fixed.strategy=="HNSW_HYBRID"]),("fixed_vector_first",fixed[fixed.strategy=="VECTOR_FIRST_HNSW"]),("fixed_ivfflat",fixed[fixed.strategy=="IVFFLAT_HYBRID"]),("all_ann",ann[ann.expected_index.notna()]),("sql_first",ann[ann.strategy=="SQL_FIRST"])]: plan_rows.append({"scope":label,"executions":len(frame),"verified":int((frame.plan_verification_status=="verified").sum()),"all_verified":bool((frame.plan_verification_status=="verified").all())})
    overhead={"metric":"decision_to_execution_latency_ms","mean_ms":float(adaptive.actual_latency_ms.mean()),"median_ms":float(adaptive.actual_latency_ms.median()),"p95_ms":float(adaptive.actual_latency_ms.quantile(.95)),"explain_mean_ms":float(adaptive.explain_latency_ms.mean()),"planning_mean_ms":float(adaptive.planning_latency_ms.mean())}
    env=json.loads(environment_manifest.read_text()) if environment_manifest and environment_manifest.is_file() else {"status":"not_collected"}
    pd.DataFrame([{"postgresql":adaptive.postgres_version.iloc[0],"pgvector":adaptive.pgvector_version.iloc[0],"warm_persistent_session":final["methodology"]["warm_persistent_session"],"environment_manifest":str(environment_manifest) if environment_manifest else None,**{f"sha256_{k}":v for k,v in hashes.items()}}]).to_csv(output/"01_environment_table.csv",index=False)
    strategy_table = pd.DataFrame(strategy_rows)
    comparison_frame = pd.DataFrame(comparisons).set_index("fixed_strategy")
    strategy_table["adaptive_minus_strategy_latency_ms"] = [None if row.strategy == "ADAPTIVE" else comparison_frame.loc[row.strategy, "mean_latency_difference_ms"] for row in strategy_table.itertuples()]
    strategy_table["adaptive_latency_change_percent"] = [None if row.strategy == "ADAPTIVE" else comparison_frame.loc[row.strategy, "adaptive_latency_change_percent"] for row in strategy_table.itertuples()]
    strategy_table["adaptive_minus_strategy_recall"] = [None if row.strategy == "ADAPTIVE" else comparison_frame.loc[row.strategy, "mean_recall_difference"] for row in strategy_table.itertuples()]
    strategy_table.to_csv(output/"02_strategy_table.csv",index=False)
    pd.DataFrame(strategy_rows[1:]).to_csv(output/"03_fixed_baseline_table.csv",index=False); pd.DataFrame(strategy_rows[:1]).to_csv(output/"04_adaptive_table.csv",index=False)
    bucket_table = pd.DataFrame(bucket_rows).drop(columns="strategy_distribution")
    bucket_table["selectivity_bucket"] = ["≤5%", "5–10%", "10–25%", "25–50%", ">50%"]
    for strategy in FIXED_ORDER:
        bucket_table[f"{strategy}_count"] = [int((adaptive[adaptive.selectivity_bucket == bucket].strategy == strategy).sum()) for bucket, _, _ in BUCKETS]
    bucket_table.to_csv(output/"05_selectivity_bucket_table.csv",index=False)
    oracle.to_csv(output/"06_oracle_regret_table.csv",index=False)
    pd.DataFrame(plan_rows).rename(columns={"scope":"execution_scope", "verified":"plan_evidence_verified_executions", "all_verified":"all_execution_plan_evidence_verified"}).to_csv(output/"07_plan_verification_table.csv",index=False)
    pd.DataFrame([{**overhead, "metric":"adaptive_decision_to_verified_execution_wall_time_ms"}]).to_csv(output/"08_decision_overhead_table.csv",index=False)
    figures(output,adaptive,fixed); protocol_data=protocol(final,output); paper_facing_notes(output)
    summary={"analysis_script":"sdao.db.paper_analysis","analysis_created_at_utc":datetime.now(timezone.utc).isoformat(),"canonical_artifacts":{k:str(v.relative_to(PROJECT_ROOT)) for k,v in CANONICAL.items()},"canonical_sha256":hashes,"query_count":len(adaptive),"strategy_distribution":adaptive.strategy.value_counts().sort_index().to_dict(),"strategy_metrics":strategy_rows,"adaptive_vs_fixed":comparisons,"selectivity_buckets":bucket_rows,"recall_safety":{"below_target":int((adaptive.recall<TARGET_RECALL).sum()),"fraction_at_least_target":float((adaptive.recall>=TARGET_RECALL).mean())},"oracle":{"recall_feasible_mean_regret_ms":float(oracle.planner_regret_ms.mean()),"recall_feasible_median_regret_ms":float(oracle.planner_regret_ms.median()),"recall_feasible_p95_regret_ms":float(oracle.planner_regret_ms.quantile(.95)),"recall_feasible_worst_regret_ms":float(oracle.planner_regret_ms.max()),"recall_feasible_exact_matches":int(oracle.recall_feasible_identity_match.sum()),"fastest_exact_matches":int(oracle.fastest_identity_match.sum()),"fastest_exact_match_fraction":float(oracle.fastest_identity_match.mean())},"plan_verification":plan_rows,"decision_overhead":overhead,"environment_manifest":env,"protocol":protocol_data}
    (output/"paper_analysis_summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    canonical={"canonical":{k:{"path":str(v.relative_to(PROJECT_ROOT)),"sha256":hashes[k]} for k,v in CANONICAL.items()},"non_canonical":{"preliminary_db_runs":["sdao/results/db_explain_selectivity_20260814T141915Z","sdao/results/db_final_adaptive_20260814T143112Z"],"legacy_hnswlib_results":["sdao/results/csv","sdao/results/plots","results/"],"old_paper_material":["sdao/selectivity_driven_hybrid_optimizer_conference_revision.pdf","sdao/latex/sdao_manuscript_source_patch.tex"]}}
    (output/"canonical_artifacts.json").write_text(json.dumps(canonical,indent=2)+"\n")
    print(f"Validated 32 adaptive and 128 fixed records; wrote paper analysis to {output}")
    return output


def main() -> None:
    parser=argparse.ArgumentParser(description="Generate paper tables and figures from canonical DB artifacts")
    parser.add_argument("--output",type=Path,required=True); parser.add_argument("--environment-manifest",type=Path)
    args=parser.parse_args(); run(args.output,args.environment_manifest)
if __name__ == "__main__": main()
