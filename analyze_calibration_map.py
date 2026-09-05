#!/usr/bin/env python3
"""Explain adaptive strategy eligibility and bucket-level selection.

The input is the bucket summary emitted by ``sdao.db.calibration``. For every
selectivity bucket, this reports the conservative minimum-recall gate, the
calibrated bucket-median latency, the feasible strategies, and the winner
among feasible strategies. It also distinguishes recall rejection from losing
the calibrated-latency comparison.

Example:
    venv/bin/python analyze_calibration_map.py
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


STRATEGY_ORDER = (
    "SQL_FIRST",
    "VECTOR_FIRST_HNSW",
    "HNSW_HYBRID",
    "IVFFLAT_HYBRID",
)
BUCKET_ORDER = (
    "<=0.05",
    ">0.05_to_0.10",
    ">0.10_to_0.25",
    ">0.25_to_0.50",
    ">0.50",
)
TARGET_RECALL = 0.95


def load_rows(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as input_file:
        rows = list(csv.DictReader(input_file))
    required = {
        "strategy",
        "bucket",
        "latency_median_ms",
        "recall_minimum",
        "recall_fraction_meeting_target",
        "observation_count",
    }
    missing = required - set(rows[0] if rows else ())
    if missing:
        raise ValueError(f"Calibration map is missing columns: {', '.join(sorted(missing))}")
    result = {(row["strategy"], row["bucket"]): row for row in rows}
    expected = {(strategy, bucket) for strategy in STRATEGY_ORDER for bucket in BUCKET_ORDER}
    if set(result) != expected:
        raise ValueError("Calibration map must contain exactly four strategies in five buckets")
    return result


def analyze(rows: dict[tuple[str, str], dict[str, str]]) -> list[dict[str, object]]:
    report = []
    for bucket in BUCKET_ORDER:
        entries = []
        for strategy in STRATEGY_ORDER:
            row = rows[(strategy, bucket)]
            minimum = float(row["recall_minimum"])
            feasible = strategy == "SQL_FIRST" or minimum >= TARGET_RECALL
            entries.append(
                {
                    "strategy": strategy,
                    "feasible": feasible,
                    "minimum_recall": minimum,
                    "recall_fraction": float(row["recall_fraction_meeting_target"]),
                    "median_latency_ms": float(row["latency_median_ms"]),
                    "observations": int(row["observation_count"]),
                }
            )
        feasible_entries = [entry for entry in entries if entry["feasible"]]
        winner = min(feasible_entries, key=lambda entry: (entry["median_latency_ms"], entry["strategy"]))
        for entry in entries:
            if entry["feasible"]:
                reason = "selected" if entry["strategy"] == winner["strategy"] else "feasible_but_slower"
            else:
                reason = "rejected_minimum_recall"
            entry["reason"] = reason
        report.append({"bucket": bucket, "entries": entries, "winner": winner["strategy"]})
    return report


def print_report(report: list[dict[str, object]]) -> None:
    print(f"Recall feasibility target: {TARGET_RECALL:.2f}")
    print("Decision uses calibrated bucket-median latency among recall-feasible strategies.\n")
    for bucket_report in report:
        print(f"Bucket {bucket_report['bucket']} | winner: {bucket_report['winner']}")
        print("  Strategy                 MinRecall  Recall>=target  MedianMs  Feasible  Reason")
        for entry in bucket_report["entries"]:
            print(
                f"  {entry['strategy']:<24} {entry['minimum_recall']:>9.3f}"
                f" {entry['recall_fraction']:>15.3f} {entry['median_latency_ms']:>9.2f}"
                f" {str(entry['feasible']):>9}  {entry['reason']}"
            )
        print()

    for strategy in STRATEGY_ORDER[1:]:
        rejected = sum(
            any(entry["strategy"] == strategy and entry["reason"] == "rejected_minimum_recall" for entry in item["entries"])
            for item in report
        )
        feasible = len(report) - rejected
        print(f"{strategy}: recall-rejected in {rejected}/{len(report)} buckets; feasible in {feasible}/{len(report)}")


def write_csv(report: list[dict[str, object]], path: Path) -> None:
    fields = [
        "bucket",
        "strategy",
        "observations",
        "minimum_recall",
        "recall_fraction_meeting_target",
        "calibrated_median_latency_ms",
        "recall_feasible",
        "reason",
        "bucket_winner",
    ]
    with path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields)
        writer.writeheader()
        for bucket_report in report:
            for entry in bucket_report["entries"]:
                writer.writerow(
                    {
                        "bucket": bucket_report["bucket"],
                        "strategy": entry["strategy"],
                        "observations": entry["observations"],
                        "minimum_recall": f"{entry['minimum_recall']:.6f}",
                        "recall_fraction_meeting_target": f"{entry['recall_fraction']:.6f}",
                        "calibrated_median_latency_ms": f"{entry['median_latency_ms']:.6f}",
                        "recall_feasible": entry["feasible"],
                        "reason": entry["reason"],
                        "bucket_winner": bucket_report["winner"],
                    }
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("sdao/results/db_calibration_20260814/db_strategy_calibration_buckets.csv"),
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = analyze(load_rows(args.input))
    print_report(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_csv(report, args.output)
        print(f"\nWrote diagnostic CSV to {args.output}")


if __name__ == "__main__":
    main()