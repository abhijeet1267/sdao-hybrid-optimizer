# Paper-facing table notes

## Table 02 — Strategy comparison

`adaptive_minus_strategy_latency_ms` is adaptive mean strategy-only latency minus the named strategy's mean latency; negative values favor adaptive on latency. `adaptive_latency_change_percent` is the adaptive latency reduction relative to the named strategy, so positive values favor adaptive. `adaptive_minus_strategy_recall` is adaptive mean Recall@10 minus the named strategy's mean Recall@10; positive values favor adaptive on recall.

## Table 05 — Selectivity buckets

Bucket labels are display labels only; their boundaries are unchanged. Strategy columns are descriptive counts of adaptive selections, not estimates of a population distribution.

## Table 07 — Plan evidence

“Verified” means the recorded execution-plan/index evidence met the experiment's plan-verification rule. It is not a claim of performance correctness, optimality, or generalization.

## Table 08 — Decision-to-execution time

This latency includes EXPLAIN, planner, and verified executor wall time. It is not directly comparable to strategy-only latency, which times selected SQL execution only.
