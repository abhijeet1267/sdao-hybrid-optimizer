# Draft figure captions

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
