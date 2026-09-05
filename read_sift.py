import numpy as np
from pathlib import Path

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


base = read_fvecs(BASE_FILE)
query = read_fvecs(QUERY_FILE)
ground = read_ivecs(GROUND_FILE)

print("Base vectors:", base.shape)
print("Query vectors:", query.shape)
print("Ground truth:", ground.shape)
