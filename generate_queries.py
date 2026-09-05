import pandas as pd
import numpy as np

np.random.seed(42)

df = pd.read_csv("attributes.csv")

queries = []

# Category queries
for cat in df["category"].unique():
    queries.append({
        "type": "CATEGORY",
        "predicate": f"category == '{cat}'"
    })

# Brand queries
for brand in df["brand"].unique():
    queries.append({
        "type": "BRAND",
        "predicate": f"brand == '{brand}'"
    })

# Price queries
for p in [200, 500, 800, 1200, 1600]:
    queries.append({
        "type": "PRICE",
        "predicate": f"price < {p}"
    })

# Rating queries
for r in [2.5, 3.0, 3.5, 4.0, 4.5]:
    queries.append({
        "type": "RATING",
        "predicate": f"rating > {r}"
    })

# Stock queries
queries.append({
    "type": "STOCK",
    "predicate": "stock == True"
})

queries.append({
    "type": "STOCK",
    "predicate": "stock == False"
})

# Hybrid queries
queries.append({
    "type": "HYBRID",
    "predicate": "category == 'Laptop' and price < 500"
})

queries.append({
    "type": "HYBRID",
    "predicate": "brand == 'Apple' and rating > 4"
})

queries.append({
    "type": "HYBRID",
    "predicate": "category == 'Phone' and stock == True"
})

queries.append({
    "type": "HYBRID",
    "predicate": "category == 'TV' and price < 1000"
})

pd.DataFrame(queries).to_csv("queries.csv", index=False)

print("Generated", len(queries), "queries.")