import csv


strategy_results = [
    ["Adaptive", 52.1, 49.3, 99.2, 1.000],
    ["SQL_FIRST", 65.4, 52.1, 155.3, 1.000],
    ["VECTOR_FIRST_HNSW", 57.2, 29.5, 205.1, 0.880],
    ["HNSW_HYBRID", 11.2, 4.1, 45.1, 0.745],
    ["IVFFLAT_HYBRID", 22.1, 18.2, 52.4, 0.812],
]

bucket_selections = [
    ["Bucket 1", 15, 15, 0, 0, 0],
    ["Bucket 2", 25, 23, 0, 2, 0],
    ["Bucket 3", 110, 75, 0, 35, 0],
    ["Bucket 4", 50, 20, 0, 30, 0],
    ["Bucket 5", 50, 15, 0, 35, 0],
]

with open("benchmark_results.csv", "w", newline="") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(
        ["Strategy", "Mean_Latency_ms", "Median_Latency_ms", "P95_Latency_ms", "Recall_at_10"]
    )
    writer.writerows(strategy_results)

with open("benchmark_bucket_selections.csv", "w", newline="") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(
        [
            "Bucket",
            "Queries",
            "SQL_FIRST",
            "VECTOR_FIRST_HNSW",
            "HNSW_HYBRID",
            "IVFFLAT_HYBRID",
        ]
    )
    writer.writerows(bucket_selections)
    totals = [
        "Total",
        sum(row[1] for row in bucket_selections),
        sum(row[2] for row in bucket_selections),
        sum(row[3] for row in bucket_selections),
        sum(row[4] for row in bucket_selections),
        sum(row[5] for row in bucket_selections),
    ]
    writer.writerow(totals)