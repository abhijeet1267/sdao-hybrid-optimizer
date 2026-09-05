# Workload Audit (Phase 3)

**Date:** 2026-08-31
**Goal:** Audit the original query generator, identify why only 3 of 5 buckets are populated, and design a more scientifically defensible workload.

---

## 1. Original query generator (legacy)

From `benchmark_hybrid_optimizer.py`:

```python
@property
def predicate_sql(self) -> str:
    if self.target_selectivity < 0.25:
        return "(category = %s AND price < %s AND in_stock = %s)"
    if self.target_selectivity < 0.60:
        return "((category = %s AND price < %s) OR in_stock = %s)"
    return "(category = %s OR price < %s OR in_stock = %s)"
```

Three templates are used. `target_selectivity` is sampled as `rng.uniform(0.01, 1.0)`, so each template is chosen with probability:
- Template A (target < 0.25): 25% of queries → narrow conjunction
- Template B (target in [0.25, 0.60)): 35% → OR-narrow
- Template C (target ≥ 0.60): 40% → OR-wide

## 2. Why only 3 of 5 buckets are populated

The actual EXPLAIN estimates for these three templates never fall in [0.05, 0.10) or [0.25, 0.50):

- **Template A** (`category = X AND price < Y AND in_stock = Z`): With price uniform in [10, 1000], in_stock split ~50/50, and 10 categories → expected selectivity ≈ 1/10 × price_fraction × 0.5 ≈ 0.05×0.5 = 0.025 for narrow Y, 0.10×0.5 = 0.05 for wide Y. Falls in [0.00, 0.05) for most narrow-Y cases; with extreme target_selectivity near 0.24, can reach [0.10, 0.25) (because EXPLAIN over-estimates on heavy price thresholds).
- **Template B** (`(category = X AND price < Y) OR in_stock = Z`): EXPLAIN sees the OR; selectivity is dominated by the `in_stock = Z` disjunct (~0.5) plus a small fraction. Almost always ≥ 0.50. Falls in [0.50, 1.00).
- **Template C** (`category = X OR price < Y OR in_stock = Z`): Disjunctive with three independent terms → selectivity ≈ 1 - (1-1/10)(1-price_frac)(1-0.5) ≈ 1 - 0.9 × 0.5 × 0.5 = 0.775 for price_frac=0.5. Always ≥ 0.50. Falls in [0.50, 1.00).

The intermediate buckets [0.05, 0.10) and [0.25, 0.50) are skipped because the templates' EXPLAIN estimates jump from ≤0.05 to ≥0.10 (Template A at its extreme) and from ≥0.50 to ≥0.50 (Templates B and C).

## 3. Why this is a problem

A workload that fails to populate 2 of 5 selectivity buckets is a biased workload:
- It cannot distinguish strategies that differ in the missing regimes.
- It over-samples very-narrow and very-wide predicates, under-sampling the mid regimes where the choice of strategy is most informative.
- It limits the paper's external validity.

The bias is **implicit** — it comes from the templates, not from the user's choice of bucket boundaries. A scientifically defensible workload should populate all buckets by design.

## 4. New workload generator (sdao_experiments/workload.py)

The newer `sdao_experiments/workload.py` defines 9 predicate templates, each targeting a different selectivity bucket:

| Template | Predicate | Expected bucket |
|---|---|---|
| category_narrow_price | category = X AND price ∈ [Y-50, Y) | [0.00, 0.05) |
| category_and_stock | category = X AND in_stock = Z | [0.00, 0.05) |
| single_category | category = X | [0.05, 0.10) |
| category_price_instock | category = X AND price < Y AND in_stock = Z | [0.05, 0.10) |
| two_categories_and_price | category = X AND price < Y AND in_stock = TRUE | [0.05, 0.10) |
| single_category_alone | category = X | [0.10, 0.25) |
| price_range_mid | price ∈ [Y-100, Y) | [0.10, 0.25) |
| category_or_stock | category = X OR in_stock = Z | [0.25, 0.50) |
| category_or_price | category = X OR price < Y | [0.25, 0.50) |
| wide_or | category = X OR price < Y OR in_stock = Z | [0.50, 1.00) |
| stock_alone | in_stock = Z | [0.50, 1.00) |

Templates are bucketed by EXPLAIN probe at generation time. Queries whose EXPLAIN estimate does not match the target bucket are DISCARDED, ensuring every query lands in its target bucket.

## 5. New workload coverage target

`bucket_target_counts=(60, 0, 37, 0, 153)` reproduces the original baseline distribution.

For the final paper we will use a balanced distribution:

```
bucket_target_counts = (50, 50, 50, 50, 50)  # 250 total
```

Each selectivity bucket gets exactly 50 queries; the disjoint calibration/held-out split preserves the bucket coverage.

## 6. Open issues with the new generator

- The category_or_stock template has expected_bucket (0.25, 0.50) but its actual EXPLAIN estimate depends on whether `in_stock` is TRUE (~50%) and category (~10%); the union can be as high as ~55%. Probes may fail.
- The price_range_mid template uses price ∈ [Y-100, Y); with Y uniformly in [110, 1000], the fraction is approximately 100/990 ≈ 0.10 → estimate ~0.10 → bucket [0.10, 0.25) ✓

The bucket-targeted generator is a significant improvement over the original, but the workload audit document explicitly notes that bucket [0.25, 0.50) is the most fragile.

## 7. Workload-generation pipeline (for reproducibility)

```bash
# Step 1: load SIFT1M into sift_hybrid (id, embedding vector(128), category, price, in_stock)
venv/bin/python load_sift_hybrid.py

# Step 2: build HNSW and IVFFLAT indexes
venv/bin/python build_indexes.py

# Step 3: generate the workload (uses EXPLAIN probes)
venv/bin/python -m sdao_experiments.runner --config final/reproducibility/final_config.json
```

Every query in the workload has a recorded EXPLAIN estimate and a recorded target bucket. Generator scripts and seeds are version-controlled.