import numpy as np
import pandas as pd

NUM_VECTORS = 1_000_000

np.random.seed(42)

categories = [
    "Laptop",
    "Phone",
    "Camera",
    "Watch",
    "TV",
    "Tablet",
    "Speaker",
    "Monitor"
]

brands = [
    "Apple",
    "Samsung",
    "Sony",
    "Dell",
    "HP",
    "Lenovo",
    "Asus",
    "LG"
]

df = pd.DataFrame({
    "id": np.arange(NUM_VECTORS),
    "category": np.random.choice(categories, NUM_VECTORS),
    "brand": np.random.choice(brands, NUM_VECTORS),
    "price": np.random.randint(50, 2000, NUM_VECTORS),
    "rating": np.round(np.random.uniform(1, 5, NUM_VECTORS), 1),
    "stock": np.random.choice([True, False], NUM_VECTORS)
})

df.to_csv("attributes.csv", index=False)

print(df.head())
print("Saved attributes.csv")
