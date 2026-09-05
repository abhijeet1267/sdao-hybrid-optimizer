"""Analyze workload distribution in original baseline."""
import pandas as pd
import numpy as np

pq = pd.read_csv('results/real_run_20260826T065155Z/heldout_per_query.csv')
sql = pq[pq['strategy']=='SQL_FIRST']
print(f"Held-out SQL_FIRST rows: {len(sql)}")
print(f"Unique query_ids: {sql['query_id'].nunique()}")
print()
print("Per-bucket count of queries:")
print(sql.groupby('bucket').size())
print()
print("Distribution of estimated_selectivity:")
print(sql['estimated_selectivity'].describe())
print()
print("Sample query 0 row:")
print(sql.iloc[0].to_dict())
print()
cal = pd.read_csv('results/real_run_20260826T065155Z/calibration_per_execution.csv')
print(f"Calibration SQL_FIRST rows: {(cal['strategy']=='SQL_FIRST').sum()}")
sql_cal = cal[cal['strategy']=='SQL_FIRST']
print(f"Calibration per-bucket count:")
print(sql_cal.groupby('bucket').size())