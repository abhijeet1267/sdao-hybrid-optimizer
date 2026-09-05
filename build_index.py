import time
from pathlib import Path

import hnswlib
import numpy as np

DATASET_PATH = Path("/Users/abhijeetmiskin/AppData/MyProject/dataset/sift")

BASE_FILE = DATASET_PATH / "sift_base.fvecs"


def read_fvecs(filename):
    data = np.fromfile(filename, dtype=np.float32)
    dim = data.view(np.int32)[0]
    return data.reshape(-1, dim + 1)[:, 1:]


print("Loading base vectors...")
base = read_fvecs(BASE_FILE)

print("Shape:", base.shape)

dim = base.shape[1]

index = hnswlib.Index(space='l2', dim=dim)

index.init_index(
    max_elements=len(base),
    ef_construction=200,
    M=16
)

start = time.time()

index.add_items(base)

end = time.time()

print(f"Index build time: {end-start:.2f} seconds")

index.set_ef(100)

index.save_index("sift_hnsw.bin")

print("Index saved as sift_hnsw.bin")
