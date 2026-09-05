import time
from pathlib import Path

import hnswlib
import numpy as np

DATASET_PATH = Path("/Users/abhijeetmiskin/AppData/MyProject/dataset/sift")

BASE_FILE = DATASET_PATH / "sift_base.fvecs"
QUERY_FILE = DATASET_PATH / "sift_query.fvecs"
GROUND_FILE = DATASET_PATH / "sift_groundtruth.ivecs"


def read_fvecs(filename):
    data = np.fromfile(filename, dtype=np.float32)
    dim = data.view(np.int32)[0]
    return data.reshape(-1, dim + 1)[:, 1:]


def read_ivecs(filename):
    data = np.fromfile(filename, dtype=np.int32)
    dim = data[0]
    return data.reshape(-1, dim + 1)[:, 1:]


print("Loading query vectors...")
queries = read_fvecs(QUERY_FILE)

print("Loading ground truth...")
ground = read_ivecs(GROUND_FILE)

dim = queries.shape[1]

index = hnswlib.Index(space='l2', dim=dim)
index.load_index("sift_hnsw.bin")
index.set_ef(400)

k = 10

print("Running search...")

start = time.time()
labels, distances = index.knn_query(queries, k=k)
end = time.time()

latency = (end - start) / len(queries) * 1000

correct = 0

for i in range(len(queries)):
    gt = set(ground[i][:k])
    pred = set(labels[i])
    correct += len(gt & pred)

recall = correct / (len(queries) * k)

print(f"\nRecall@10 : {recall:.4f}")
print(f"Average latency : {latency:.4f} ms/query")
