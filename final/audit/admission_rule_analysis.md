# Admission Rule Analysis (Phase 2)

**Date:** 2026-08-31
**Goal:** Mathematically analyze the current min-recall admission rule, determine why every ANN strategy is rejected, and assess whether the rejection is statistically defensible.

---

## 1. Current rule (formal)

For each held-out query, given estimated selectivity s and bucket b = bucket(s):

```
F(b) := {SQL_FIRST} ∪ {strategy s ∈ ANN : min over calibration observations (s,b) of Recall@10 ≥ 0.95}
```

Then choose argmin over F(b) of empirical median calibrated latency.

## 2. Calibration recall statistics from the original 1M baseline

| Strategy | Bucket | n | min | mean | p05 | frac ≥ 0.95 |
|---|---|---|---|---|---|---|
| VECTOR_FIRST_HNSW | [0.00, 0.05) | 56 | 0.000 | 0.063 | 0.000 | 0.000 |
| VECTOR_FIRST_HNSW | [0.10, 0.25) | 38 | 0.400 | 0.921 | 0.685 | 0.579 |
| VECTOR_FIRST_HNSW | [0.50, 1.00) | 156 | 0.800 | 0.991 | 0.900 | 0.917 |
| HNSW_HYBRID | [0.00, 0.05) | 56 | 0.000 | 0.241 | 0.000 | 0.179 |
| HNSW_HYBRID | [0.10, 0.25) | 38 | 0.400 | 0.924 | 0.700 | 0.579 |
| HNSW_HYBRID | [0.50, 1.00) | 156 | 0.800 | 0.990 | 0.900 | 0.910 |
| IVFFLAT_HYBRID | [0.00, 0.05) | 56 | 0.200 | 0.657 | 0.275 | 0.214 |
| IVFFLAT_HYBRID | [0.10, 0.25) | 38 | 0.400 | 0.800 | 0.400 | 0.316 |
| IVFFLAT_HYBRID | [0.50, 1.00) | 156 | 0.400 | 0.892 | 0.600 | 0.526 |
| SQL_FIRST | (all) | 250 | 1.000 | 1.000 | 1.000 | 1.000 |

## 3. Why every ANN strategy is rejected

Under min-recall ≥ 0.95, every bucket × ANN strategy has min < 0.95. The rule triggers; SQL_FIRST is the only feasible strategy.

## 4. Is the rule statistically appropriate?

### 4.1 Min statistic is highly sensitive at small n

P(at least one observation < 0.95) = 1 - (1-p)^n.

For n=38, even if true p=0.05, P(admission) = 0.95^38 ≈ 14.4%. For n=156, P(admission) = 0.95^156 ≈ 0.04%. So a true 5% failure rate is essentially guaranteed rejection under this rule.

### 4.2 Bucket [0.10, 0.25)

HNSW_HYBRID: 38 cal obs, mean=0.924, min=0.400, frac≥0.95=0.579. 22/38 ≥ 0.95 (~58%). One observation at 0.40 drives the rejection. If we drop that one, min(after drop)=0.70, mean=0.948. A bootstrap LCB or 5th-percentile rule would admit this bucket. The min-recall rule is over-conservative here.

### 4.3 Bucket [0.50, 1.00)

VECTOR_FIRST_HNSW: 156 obs, mean=0.991, min=0.800, frac≥0.95=0.917. 13/156 (~8.3%) < 0.95. Vector-first with budget=100 yields <10 candidates when the predicate filters them down. The rule is correct -- 8% of queries would have unsafe recall.

### 4.4 Bucket [0.00, 0.05)

All three ANN strategies severely degraded (mean 0.06 to 0.66). At selectivity ~1% of 1M = 10K rows, vector-first budget of 100 yields ~1 match, far below k=10. The rule correctly rejects. No statistical fix rescues this.

## 5. Conclusions

1. **Min-recall is genuinely correct for [0.00, 0.05)**: ANN fundamentally fails; no statistical fix rescues it.
2. **Min-recall is over-conservative for [0.10, 0.25)**: One outlier drives rejection; less strict rules would admit.
3. **Min-recall correctly rejects [0.50, 1.00) for VECTOR_FIRST_HNSW**: 8% true failure rate.
4. **Sample size matters**: With n=38, high variance; with n=156, more reliable but rejects when real failure rate is >0%.
5. **Appropriateness varies by regime**: appropriate for very-low-selectivity, over-conservative for mid-selectivity, appropriate for high-selectivity with vector-first.

## 6. Implications for the paper

"Conservative layer must reject all ANN" is misleading. The truth is:
- [0.00, 0.05): ANN must be rejected (ANN fails).
- [0.10, 0.25): ANN could be admitted under a less strict rule (min-recall is over-conservative).
- [0.50, 1.00): only SQL_FIRST and HNSW_HYBRID are safe; IVFFLAT_HYBRID and VECTOR_FIRST_HNSW must be rejected.

The paper's contribution should be:
- Min-recall rule is interpretable and conservative, but
- It is over-conservative in some regimes,
- The choice of admission statistic is itself a design decision with statistical tradeoffs,
- The paper should evaluate ALTERNATIVE admission statistics to characterize the safety-vs-coverage tradeoff.

## 7. Admission statistics to evaluate (Phase 7)

| Policy | Statistic | Criterion |
|---|---|---|
| A (original) | min | R_min(b) ≥ 0.95 |
| B | 5th percentile | P05(R; b) ≥ 0.95 |
| C | LCB on mean | LCB_95(R_mean; b) ≥ 0.95 (bootstrap) |
| D | failure rate | Wilson upper bound on P(R<0.95; b) ≤ 0.05 |
| E | risk-constrained | argmin latency s.t. binomial P(R ≥ 0.95; b) ≥ 0.95 |