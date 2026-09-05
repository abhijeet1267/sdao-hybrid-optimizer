"""Workload design for SDAO experiments.

The original ``benchmark_hybrid_optimizer.generate_queries`` used three predicate
templates and a uniform target-selectivity draw, which produced EXPLAIN-estimated
selectivities clustered into only three of the five intended buckets. This module
replaces that generator with a deterministic, bucket-targeted design.

Design principles
-----------------

1. The decision input is the **EXPLAIN-estimated** selectivity, never the
   target. The target is only a design aid.
2. Each generated query is constructed so its EXPLAIN estimate falls inside
   a target bucket. A small ``EXPLAIN`` probe is used to verify the bucket
   assignment; queries that fall outside their target bucket are discarded.
3. Disjoint TUNING / CALIBRATION / HELD-OUT splits are generated with
   separate seeds so the adaptive policy is never tuned on test data.
4. Seeds are deterministic. The exact same workload is reproduced across runs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import psycopg2

from .config import ExperimentConfig


# Predicate templates ordered by expected selectivity on a 1M-row table with
# 10 categories, 2 in_stock values, and price uniform in [10, 1000].
#
# Each template returns a (predicate_sql, params) tuple. The bucket listed
# is the *expected* EXPLAIN-estimated bucket. The actual bucket is verified
# by probing EXPLAIN before assignment.
PREDICATE_TEMPLATES: dict[str, dict[str, Any]] = {
    "single_category": {
        "expected_bucket": (0.05, 0.10),
        "build_simple": lambda category, _pl, _is: ("(category = %s)", (category,)),
    },
    "category_narrow_price": {
        "expected_bucket": (0.0, 0.05),
        "build_simple": lambda category, price_limit, _is: (
            "(category = %s AND price < %s AND price >= %s)",
            (category, price_limit, max(price_limit - 50, 10)),
        ),
    },
    "category_or_stock": {
        "expected_bucket": (0.25, 0.50),
        "build_simple": lambda category, _pl, in_stock: (
            "(category = %s OR in_stock = %s)", (category, in_stock),
        ),
    },
    "wide_or": {
        "expected_bucket": (0.50, 1.01),
        "build_simple": lambda category, price_limit, in_stock: (
            "(category = %s OR price < %s OR in_stock = %s)",
            (category, price_limit, in_stock),
        ),
    },
    "single_category_alone": {
        "expected_bucket": (0.10, 0.25),
        "build_simple": lambda category, _pl, _is: ("(category = %s)", (category,)),
    },
    "category_price_instock": {
        "expected_bucket": (0.05, 0.10),
        "build_simple": lambda category, price_limit, in_stock: (
            "(category = %s AND price < %s AND in_stock = %s)",
            (category, price_limit, in_stock),
        ),
    },
    "category_and_stock": {
        "expected_bucket": (0.0, 0.05),
        "build_simple": lambda category, _pl, in_stock: (
            "(category = %s AND in_stock = %s)", (category, in_stock),
        ),
    },
    "stock_alone": {
        "expected_bucket": (0.50, 1.01),
        "build_simple": lambda _c, _pl, in_stock: ("(in_stock = %s)", (in_stock,)),
    },
    "price_range_mid": {
        "expected_bucket": (0.10, 0.25),
        "build_simple": lambda _c, price_limit, _is: (
            "(price >= %s AND price < %s)",
            (max(price_limit - 100, 10), price_limit),
        ),
    },
    "two_categories_and_price": {
        "expected_bucket": (0.05, 0.10),
        "build_simple": lambda c1, price_limit, _is: (
            "(category = %s AND price < %s AND in_stock = TRUE)",
            (c1, price_limit),
        ),
    },
    "category_or_price": {
        "expected_bucket": (0.25, 0.50),
        "build_simple": lambda category, price_limit, _is: (
            "(category = %s OR price < %s)", (category, price_limit),
        ),
    },
}


def _build_two_categories(category: str) -> tuple[str, tuple]:
    c_idx = int(category.split("_")[-1])
    c2 = f"category_{(c_idx + 1) % 10:02d}"
    return ("(category IN (%s, %s))", (category, c2))


def _build_three_categories(category: str) -> tuple[str, tuple]:
    c_idx = int(category.split("_")[-1])
    c2 = f"category_{(c_idx + 1) % 10:02d}"
    c3 = f"category_{(c_idx + 2) % 10:02d}"
    return (
        "(category = %s OR category = %s OR category = %s)",
        (category, c2, c3),
    )


def _normalize_template(
    category: str, price_limit: int, in_stock: bool, template_name: str
) -> tuple[str, tuple]:
    if template_name == "two_categories":
        return _build_two_categories(category)
    if template_name == "three_categories":
        return _build_three_categories(category)
    return PREDICATE_TEMPLATES[template_name]["build_simple"](
        category, price_limit, in_stock
    )


def bucket_for(selectivity: float, buckets: Iterable[tuple[float, float]]) -> str:
    for lower, upper in buckets:
        if lower <= selectivity < upper:
            return f"[{lower:.2f},{min(upper, 1.0):.2f})"
    return f"[{list(buckets)[-1][0]:.2f},1.00]"


@dataclass(frozen=True)
class WorkloadQuery:
    query_id: int
    vector: np.ndarray
    template: str
    category: str
    price_limit: int
    in_stock: bool
    target_bucket_idx: int
    estimated_selectivity: float = -1.0
    bucket: str = ""


def read_fvecs(path: Path, dim: int) -> np.ndarray:
    """Read a standard SIFT .fvecs file."""
    raw = np.fromfile(path, dtype=np.int32)
    width = dim + 1
    if raw.size % width:
        raise ValueError(f"Malformed .fvecs file: {path}")
    records = raw.reshape(-1, width)
    if not np.all(records[:, 0] == dim):
        raise ValueError(f"Expected {dim}-dimensional vectors")
    return records[:, 1:].view(np.float32).reshape(-1, dim)
class WorkloadGenerator:
    """Generate a workload with controlled per-bucket counts."""

    def __init__(self, config, connection):
        self.config = config
        self.connection = connection
        self._bucket_templates = {}
        for idx, bounds in enumerate(config.selectivity_buckets):
            templates = []
            for name, tdef in PREDICATE_TEMPLATES.items():
                if (abs(tdef["expected_bucket"][0] - bounds[0]) < 1e-6 and
                    abs(tdef["expected_bucket"][1] - bounds[1]) < 1e-6):
                    templates.append(name)
            if abs(bounds[0] - 0.10) < 1e-6 and abs(bounds[1] - 0.25) < 1e-6:
                templates.append("two_categories")
            if abs(bounds[0] - 0.25) < 1e-6 and abs(bounds[1] - 0.50) < 1e-6:
                templates.append("three_categories")
            self._bucket_templates[idx] = templates

    def _probe_selectivity(self, predicate_sql, params):
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"EXPLAIN (FORMAT JSON) SELECT id FROM {self.config.table_name} "
                f"WHERE {predicate_sql}", params)
            row = cursor.fetchone()
        plan = row[0] if not isinstance(row[0], str) else json.loads(row[0])
        return float(plan[0]["Plan"]["Plan Rows"]) / self.config.dataset_size

    def _bucket_index(self, selectivity):
        for idx, (lo, hi) in enumerate(self.config.selectivity_buckets):
            if lo <= selectivity < hi:
                return idx
        return len(self.config.selectivity_buckets) - 1

    def _generate_for_bucket(self, rng, query_vectors, bucket_idx, count, starting_id):
        templates = self._bucket_templates.get(bucket_idx, [])
        if not templates:
            return []
        queries = []
        attempts = 0
        max_attempts = max(count * 30, 100)
        qid = starting_id
        categories = [f"category_{i:02d}" for i in range(self.config.n_categories)]
        while len(queries) < count and attempts < max_attempts:
            attempts += 1
            template = templates[rng.integers(0, len(templates))]
            category = str(rng.choice(categories))
            price_limit = int(np.clip(
                self.config.price_min + rng.uniform(0, 1) * (self.config.price_max - self.config.price_min),
                self.config.price_min + 1, self.config.price_max))
            in_stock = bool(rng.integers(0, 2))
            try:
                predicate_sql, params = _normalize_template(
                    category, price_limit, in_stock, template)
                est = self._probe_selectivity(predicate_sql, params)
            except Exception:
                continue
            est_clamped = float(np.clip(est, 0.0, 1.0))
            actual_bucket_idx = self._bucket_index(est_clamped)
            if actual_bucket_idx != bucket_idx:
                continue
            vector = query_vectors[int(rng.integers(0, len(query_vectors)))].copy()
            qid += 1
            queries.append(WorkloadQuery(
                query_id=qid, vector=vector, template=template,
                category=category, price_limit=price_limit, in_stock=in_stock,
                target_bucket_idx=bucket_idx, estimated_selectivity=est_clamped,
                bucket=bucket_for(est_clamped, self.config.selectivity_buckets)))
        return queries

    def generate(self, query_vectors, bucket_counts):
        rng = np.random.default_rng(self.config.seed)
        all_queries = []
        for bucket_idx, count in enumerate(bucket_counts):
            if count <= 0:
                continue
            bucket_queries = self._generate_for_bucket(
                rng=rng, query_vectors=query_vectors, bucket_idx=bucket_idx,
                count=count, starting_id=len(all_queries))
            if len(bucket_queries) < count:
                print(f"WARNING: bucket {bucket_idx} requested {count} queries, "
                      f"only generated {len(bucket_queries)}")
            all_queries.extend(bucket_queries)
        return all_queries

    def split_workload(self, queries):
        rng = np.random.default_rng(self.config.split_seed)
        order = rng.permutation(len(queries))
        n = self.config.total_queries()
        if len(queries) != n:
            raise ValueError(f"workload has {len(queries)} queries, config expects {n}")
        tuning = [queries[i] for i in order[:self.config.tuning_count]]
        calibration = [queries[i] for i in order[
            self.config.tuning_count:self.config.tuning_count + self.config.calibration_count]]
        test = [queries[i] for i in order[
            self.config.tuning_count + self.config.calibration_count:]]
        return tuning, calibration, test
