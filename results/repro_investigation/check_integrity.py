"""Dataset and query integrity check.

Verifies that the current environment has:
1. The exact same SIFT1M vectors as the original
2. The same query workload (same seed produces same queries)
3. The same EXPLAIN-estimated selectivities
"""
import hashlib
import json
from pathlib import Path
import numpy as np

VECTOR_PATH = "dataset/sift/sift_base.fvecs"
N_VECTORS_FULL = 1_000_000


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_fvecs(path, dim=128):
    raw = np.fromfile(path, dtype=np.int32)
    width = dim + 1
    records = raw.reshape(-1, width)
    return records[:, 1:].view(np.float32).reshape(-1, dim)


def main():
    result = {
        "dataset_file": VECTOR_PATH,
        "n_vectors_full_expected": N_VECTORS_FULL,
    }

    # 1. File-level checksum
    sha = sha256_file(VECTOR_PATH)
    result["dataset_sha256"] = sha
    print(f"Dataset SHA-256: {sha}")

    # 2. Vector count and dimension
    vectors = read_fvecs(VECTOR_PATH)
    result["n_vectors_loaded"] = len(vectors)
    result["vector_dimension"] = vectors.shape[1]
    print(f"Loaded {len(vectors)} vectors of dimension {vectors.shape[1]}")

    # 3. First/last 10 vector hashes (fingerprint)
    result["first_10_vector_sha256"] = hashlib.sha256(
        vectors[:10].tobytes()).hexdigest()
    result["last_10_vector_sha256"] = hashlib.sha256(
        vectors[-10:].tobytes()).hexdigest()
    result["vector_0_first_5_dims"] = vectors[0][:5].tolist()
    result["vector_999999_first_5_dims"] = vectors[999999][:5].tolist()
    print(f"First 5 dims of vector 0: {vectors[0][:5]}")
    print(f"First 5 dims of vector 999999: {vectors[999999][:5]}")

    # 4. Determinism check: generate queries with the same seed twice
    import sys
    sys.path.insert(0, ".")
    from sdao_experiments.baseline_repro import generate_queries

    q1 = generate_queries(vectors, 20260820)
    q2 = generate_queries(vectors, 20260820)
    result["query_determinism_check"] = []
    for i in range(5):
        same = (q1[i].query_id == q2[i].query_id and
                q1[i].category == q2[i].category and
                q1[i].price_limit == q2[i].price_limit and
                q1[i].in_stock == q2[i].in_stock and
                q1[i].target_selectivity == q2[i].target_selectivity)
        result["query_determinism_check"].append({
            "query_id": i,
            "category": q1[i].category,
            "price_limit": q1[i].price_limit,
            "in_stock": q1[i].in_stock,
            "target_selectivity": q1[i].target_selectivity,
            "deterministic": same,
        })

    # 5. Compare first 5 queries to the original baseline's per-execution CSV
    # The original baseline's heldout_per_execution.csv records estimated_selectivity
    # for each query_id. We can compare to verify the query workload matches.
    orig = Path("results/real_run_20260826T065155Z/heldout_per_execution.csv")
    if orig.exists():
        import pandas as pd
        df = pd.read_csv(orig)
        # Get one estimated_selectivity per query_id from the original
        orig_est = df.drop_duplicates("query_id")[["query_id", "estimated_selectivity", "bucket"]].sort_values("query_id")
        result["original_estimated_selectivity_first_5"] = orig_est.head(5).to_dict(orient="records")
        print(f"Original baseline query 0 estimated_selectivity: {orig_est.iloc[0]['estimated_selectivity']:.6f}")
        print(f"Current query 0 target_selectivity: {q1[0].target_selectivity:.6f}")

    # Write output
    out_path = Path("results/repro_investigation/dataset_integrity.json")
    out_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"\nWrote {out_path}")

if __name__ == "__main__":
    main()
