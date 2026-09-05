"""Generate paper/tables/*.tex directly from the final run's recomputed CSVs.
No hand-typed numbers: every value is read from results/real_run_20260826T065155Z."""
import pandas as pd

RUN = "results/real_run_20260826T065155Z"
OUT = "paper/tables"
STRATEGIES = ["SQL_FIRST", "VECTOR_FIRST_HNSW", "HNSW_HYBRID", "IVFFLAT_HYBRID"]
LATEX_STRAT = {s: s.replace("_", "\\_") for s in STRATEGIES}
BUCKET_TEX = {
    "[0.00,0.05)": "$\\leq5\\%$", "[0.05,0.10)": "$5$--$10\\%$",
    "[0.10,0.25)": "$10$--$25\\%$", "[0.25,0.50)": "$25$--$50\\%$",
    "[0.50,1.00)": "$>50\\%$",
}

t1 = pd.read_csv(f"{RUN}/table1_recomputed.csv")
t2 = pd.read_csv(f"{RUN}/table2_recomputed.csv")
t3 = pd.read_csv(f"{RUN}/table3_recomputed.csv")
t4 = pd.read_csv(f"{RUN}/table4_recomputed.csv")

# ---- Table I ---------------------------------------------------------------
lines = [
    "\\begin{table*}[t]", "\\centering",
    "\\caption{Observed strategy-only performance on the 250-query held-out test "
    "workload. Recall@10 is the mean over 250 queries; Min recall and Frac $\\geq$0.95 "
    "are computed over the same observations.}",
    "\\label{tab:strategy-comparison}", "\\scriptsize",
    "\\begin{tabular}{lrrrrrr}", "\\toprule",
    "Strategy & Mean ms & Median ms & P95 ms & Recall@10 & Min recall & Frac $\\geq$0.95 \\\\",
    "\\midrule",
]
for row in t1.itertuples(index=False):
    name = "Adaptive" if row[0] == "Adaptive" else LATEX_STRAT[row[0]]
    lines.append(
        f"{name} & {row[1]:.1f} & {row[2]:.1f} & {row[3]:.1f} & "
        f"{row[4]:.3f} & {row[5]:.3f} & {row[6]:.3f} \\\\")
lines += ["\\bottomrule", "\\end{tabular}", "\\end{table*}", ""]
open(f"{OUT}/strategy_comparison.tex", "w").write("\n".join(lines))

# ---- Table II ---------------------------------------------------------------
order = ["[0.00,0.05)", "[0.05,0.10)", "[0.10,0.25)", "[0.25,0.50)", "[0.50,1.00)"]
t2 = t2.set_index("bucket") if "bucket" in t2.columns else t2
if "Total" in t2.index:
    t2 = t2.drop(index="Total")
lines = [
    "\\begin{table}[t]", "\\centering",
    "\\caption{Adaptive selections across estimated-selectivity buckets on the "
    "250-query held-out test set. The feasibility gate admitted only "
    "\\texttt{SQL\\_FIRST}; two buckets received no queries (see "
    "Section~\\ref{sec:limitations}).}",
    "\\label{tab:selection-by-bucket}", "\\scriptsize",
    "\\resizebox{\\columnwidth}{!}{%",
    "\\begin{tabular}{lrrrrr}", "\\toprule",
    "Bucket & Queries & SQL\\_FIRST & VECTOR\\_FIRST\\_HNSW & HNSW\\_HYBRID & "
    "IVFFLAT\\_HYBRID \\\\", "\\midrule",
]
for b in order:
    r = t2.loc[b]
    cells = " & ".join(str(int(r[s])) for s in STRATEGIES)
    lines.append(f"{BUCKET_TEX[b]} & {int(r['Queries'])} & {cells} \\\\")
total = t2[STRATEGIES].sum()
lines.append("\\midrule")
lines.append(f"Total & {int(t2['Queries'].sum())} & " +
             " & ".join(str(int(total[s])) for s in STRATEGIES) + " \\\\")
lines += ["\\bottomrule", "\\end{tabular}}", "\\end{table}", ""]
open(f"{OUT}/selection_by_bucket.tex", "w").write("\n".join(lines))

# ---- Table III ---------------------------------------------------------------
r = t3.iloc[0]
lines = [
    "\\begin{table}[t]", "\\centering",
    "\\caption{Adaptive decision-to-verified-execution wall time per held-out "
    "query (EXPLAIN + calibration decision + verified execution of the selected "
    "strategy, single execution per query). Not directly comparable to the "
    "median-of-repetitions strategy-only latency in Table~\\ref{tab:strategy-comparison}.}",
    "\\label{tab:decision-overhead}", "\\small",
    "\\begin{tabular}{rrr}", "\\toprule",
    "Mean ms & Median ms & P95 ms \\\\", "\\midrule",
    f"{r.Mean_ms:.2f} & {r.Median_ms:.2f} & {r.P95_ms:.2f} \\\\",
    "\\bottomrule", "\\end{tabular}", "\\end{table}", "",
]
open(f"{OUT}/decision_overhead.tex", "w").write("\n".join(lines))

# ---- Table IV ---------------------------------------------------------------
lines = [
    "\\begin{table}[t]", "\\centering",
    "\\caption{Named-access-path verification for the 250-query held-out test "
    "set. ANN strategies are verified against their own index type; planner-chosen "
    "exact bitmap fallbacks are logged separately via the access-path field rather "
    "than counted as failures.}",
    "\\label{tab:plan-verification}", "\\scriptsize",
    "\\resizebox{\\columnwidth}{!}{%",
    "\\begin{tabular}{lrr}", "\\toprule",
    "Execution scope & Records & Named path verified \\\\", "\\midrule",
]
for row in t4.itertuples(index=False):
    scope = (row.Scope.replace("VECTOR_FIRST_HNSW", LATEX_STRAT["VECTOR_FIRST_HNSW"])
             .replace("HNSW_HYBRID", LATEX_STRAT["HNSW_HYBRID"])
             .replace("IVFFLAT_HYBRID", LATEX_STRAT["IVFFLAT_HYBRID"])
             .replace("SQL_FIRST", "SQL\\_FIRST"))
    lines.append(f"{scope} & {row.records} & {row.named_path_verified} \\\\")
lines += ["\\bottomrule", "\\end{tabular}}", "\\end{table}", ""]
open(f"{OUT}/plan_verification.tex", "w").write("\n".join(lines))

print("wrote 4 table files to", OUT)
print(open(f"{OUT}/strategy_comparison.tex").read())
print(open(f"{OUT}/selection_by_bucket.tex").read())
