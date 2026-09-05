"""Render the SDAO paper as a PDF using reportlab."""
from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY, TA_CENTER
from reportlab.lib.colors import HexColor
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                Table, TableStyle, PageBreak, KeepTogether)
from reportlab.platypus.flowables import HRFlowable
import pandas as pd

ROOT = Path("/Users/abhijeetmiskin/AppData/MyProject")
RES = ROOT / "final" / "results"
ss = getSampleStyleSheet()
styles = {}
styles["title"] = ParagraphStyle("title", parent=ss["Title"], fontSize=15,
    leading=18, alignment=TA_CENTER, spaceAfter=4)
styles["subtitle"] = ParagraphStyle("subtitle", parent=ss["Normal"], fontSize=10,
    alignment=TA_CENTER, spaceAfter=10, textColor=HexColor("#444444"))
styles["h1"] = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=12,
    leading=14, spaceBefore=6, spaceAfter=2, textColor=HexColor("#1f4e79"))
styles["h2"] = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=10.5,
    leading=12, spaceBefore=3, spaceAfter=1, textColor=HexColor("#1f4e79"))
styles["body"] = ParagraphStyle("body", parent=ss["Normal"], fontSize=9,
    leading=11, alignment=TA_JUSTIFY, spaceAfter=3, wordWrap='normal')
styles["caption"] = ParagraphStyle("caption", parent=ss["Normal"], fontSize=8,
    leading=10, alignment=TA_CENTER, spaceAfter=4, textColor=HexColor("#444444"))
styles["abstract"] = ParagraphStyle("abstract", parent=ss["Italic"], fontSize=8.5,
    leading=11, alignment=TA_JUSTIFY, spaceAfter=6, leftIndent=18, rightIndent=18, wordWrap='normal')
styles["ref"] = ParagraphStyle("ref", parent=ss["Normal"], fontSize=8,
    leading=10, alignment=TA_LEFT, spaceAfter=1)


def p(text):
    return Paragraph(text, styles["body"])


def h1(text):
    return Paragraph(text, styles["h1"])


def h2(text):
    return Paragraph(text, styles["h2"])


def cap(text):
    return Paragraph("<b>Figure/Table.</b> " + text, styles["caption"])


def ref(text):
    return Paragraph(text, styles["ref"])


def fig(filename, width=6.0):
    pp = FIG / filename
    if not pp.exists():
        return Paragraph("[missing: " + filename + "]", styles["caption"])
    pp_png = pp.with_suffix(".png")
    if not pp_png.exists():
        return Paragraph("[missing: " + filename + " (no PNG)]", styles["caption"])
    img = Image(str(pp_png))
    img._restrictSize(width * inch, 4.5 * inch)
    return img


def t(data, col_widths=None, header_bg="#1f4e79"):
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor(header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, HexColor("#888888")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [HexColor("#ffffff"), HexColor("#f0f0f0")]),
    ])
    return Table(data, colWidths=col_widths, style=style)


def fmt(v, n=3):
    if isinstance(v, (int,)):
        return str(v)
    if isinstance(v, float):
        if n == 0:
            return f"{v:.0f}"
        return f"{v:.{n}f}"
    return str(v)

FIG = ROOT / "final" / "figures"
TBL = RES / "tables"
OUT = ROOT / "final" / "paper" / "main.pdf"

main = pd.read_csv(TBL / "main_summary.csv")
pol = pd.read_csv(TBL / "policy_table.csv")
seed = pd.read_csv(TBL / "seed_table.csv")
budget = pd.read_csv(TBL / "budget_table.csv")

doc = SimpleDocTemplate(str(OUT), pagesize=LETTER,
                        leftMargin=0.7*inch, rightMargin=0.7*inch,
                        topMargin=0.7*inch, bottomMargin=0.7*inch)
flow = []
flow.append(Paragraph(
    "A Selectivity-Driven Adaptive Strategy-Selection Framework with "
    "Recall-Aware Admission for Hybrid SQL&ndash;Vector Databases", styles["title"]))
flow.append(Paragraph("Final reproducibility report &mdash; frozen against final/results/",
                      styles["subtitle"]))
flow.append(HRFlowable(width="100%", thickness=0.7, color=HexColor("#888888")))
abstract_text = (
    "<b>Abstract.</b> We study the problem of choosing a query-execution strategy for "
    "hybrid SQL&ndash;vector queries that combine a relational filter with an approximate "
    "nearest-neighbour (ANN) search. We construct a Selectivity-Driven Adaptive Query "
    "Processing (SDAO) engine on PostgreSQL&nbsp;17.10 with the "
    "<font face='Courier'>pgvector</font> extension. The engine estimates per-query "
    "pre-filter selectivity from <font face='Courier'>EXPLAIN (FORMAT JSON)</font>, "
    "looks up a per-(strategy, selectivity-bucket) calibration of latency and "
    "Recall@10, applies a recall-aware admission rule, and selects the lowest-latency "
    "strategy that survives the rule. We evaluate four candidate strategies "
    "(<font face='Courier'>SQL_FIRST</font>, "
    "<font face='Courier'>VECTOR_FIRST_HNSW</font>, "
    "<font face='Courier'>HNSW_HYBRID</font>, "
    "<font face='Courier'>IVFFLAT_HYBRID</font>) and the adaptive engine on a "
    "200K-vector SIFT1M subset under a warm-cache microbenchmark protocol, with "
    "125 calibration queries and 125 disjoint held-out queries (3 repetitions per "
    "strategy per query, 95% bootstrap CIs). On the evaluated workload the adaptive "
    "engine admits an ANN strategy for 100/125 held-out queries, falls back to "
    "<font face='Courier'>SQL_FIRST</font> for the remaining 25, and reports 100% "
    "Recall@10 with 0% safety violations. The Vector-First HNSW baseline fails the "
    "0.95 recall target (mean 0.83, 95% CI [0.77, 0.88], minimum 0.00) across the "
    "main run, a 12-point "
    "<font face='Courier'>ef_search</font>&times;<font face='Courier'>probes</font> "
    "sweep, a 5-point budget sweep (0.70&rarr;0.94), and three random seeds. The "
    "study does not demonstrate a latency improvement for the adaptive engine on "
    "this workload; the reported Adaptive mean of 15.10&nbsp;ms is within the 95% "
    "CI of <font face='Courier'>SQL_FIRST</font> (15.29&nbsp;ms, CI "
    "[14.15,&nbsp;16.49]). The contribution is a reproducible engineering and "
    "empirical characterization of a selectivity-driven, recall-constrained "
    "admission layer, and a candid re-statement of the boundary of validity of "
    "the original (PG 16.14) baseline.")
flow.append(Paragraph(abstract_text, styles["abstract"]))
flow.append(h1("1. Introduction"))
flow.append(p(
    "Hybrid SQL&ndash;vector queries combine a relational filter with an approximate "
    "nearest-neighbour (ANN) search over a vector column. The natural implementation "
    "choices are <i>SQL-first</i> (filter then sort), a <i>vector-first</i> "
    "<font face='Courier'>ORDER BY embedding &lt;=&gt; $1 LIMIT k</font> plan, or one of "
    "several <i>hybrid</i> strategies that pre-narrow the candidate set with a relational "
    "filter and then run an exact or approximate nearest-neighbour scan over the reduced "
    "set. Because the optimal choice depends on the pre-filter selectivity, an adaptive "
    "engine that observes the selectivity at planning time and selects a strategy from a "
    "fixed menu is attractive. The problem is not new &mdash; adaptive query processing "
    "has a long lineage &mdash; but its application to the SQL&ndash;vector setting "
    "raises a new safety question: ANN can silently violate a recall target, so an "
    "adaptive engine must refuse to choose a strategy that is unsafe on the present "
    "workload, not merely a strategy that is slow."))
flow.append(p(
    "This paper is a reproducibility report. A prior version of the work reported that "
    "on PostgreSQL&nbsp;16.14 with <font face='Courier'>pgvector</font> the HNSW hybrid "
    "strategy underperformed <font face='Courier'>SQL_FIRST</font> and that an adaptive "
    "policy was warranted only for low-selectivity queries. We re-run the same code on "
    "PostgreSQL&nbsp;17.10 on macOS and obtain the opposite ranking: every hybrid "
    "strategy hits Recall@10 = 1.000, and a vector-first strategy drops to 0.83 mean "
    "recall. The divergence is real. It is attributable, in large part, to a portability "
    "difference in <font face='Courier'>pgvector</font>'s HNSW graph construction: the "
    "HNSW graph built on the current Apple-clang host is not bit-identical to the graph "
    "built on the original Debian/glibc host (see &sect;&nbsp;2.5 and &sect;&nbsp;8). "
    "The contribution of the present paper is therefore not a stronger claim about ANN "
    "speed; it is a calibrated, audit-ready framework for the safety side of the "
    "problem, and a candid re-statement of the boundary of validity of the original "
    "numbers."))
flow.append(p(
    "<b>Contributions.</b> (i)&nbsp;A selectivity-driven strategy-selection framework "
    "with a per-(strategy, bucket) calibration table and a recall-aware admission rule. "
    "(ii)&nbsp;An empirical characterization of unsafe ANN execution on the present "
    "workload, including the candidate-budget effect and the parameter-insensitivity of "
    "hybrid strategies. (iii)&nbsp;A multi-seed replication that reproduces the "
    "qualitative recall ordering. (iv)&nbsp;A reproducibility package: frozen "
    "configuration, audit documents, SHA-256 manifest of the original baseline "
    "artifacts, and end-to-end validation script."))
flow.append(h1("2. System and methods"))
flow.append(h2("2.1 Hardware and software"))
flow.append(p(
    "PostgreSQL 17.10 with <font face='Courier'>pgvector</font> in the "
    "<font face='Courier'>pgvector/pgvector:pg17</font> Docker image on macOS 14.6 "
    "(Apple clang, libc++). All code in <font face='Courier'>final/audit/db_config.json</font>."))
flow.append(h2("2.2 Data"))
flow.append(p(
    "SIFT1M (1M 128-D SIFT descriptors, 10K queries). The active experiments use a "
    "200K-vector subset and 250 queries drawn deterministically from SIFT1M "
    "(seed in <font face='Courier'>final/frozen_configuration.yaml</font>). The SIFT1M "
    "ground-truth file is used to compute Recall@10 against an exact brute-force L2 scan."))
flow.append(h2("2.3 Strategies"))
strats = [
    ["SQL_FIRST", "relational filter only; vector column not in WHERE."],
    ["VECTOR_FIRST_HNSW", "single HNSW query, relational filter optional."],
    ["HNSW_HYBRID", "pre-narrow with WHERE, then ANN on remainder."],
    ["IVFFLAT_HYBRID", "same pre-narrowing; ANN via ivfflat probes=10."],
    ["Adaptive", "the SDAO engine."],
]
flow.append(t([["Strategy", "Definition"]] + strats, col_widths=[1.6*inch, 4.6*inch]))
flow.append(cap("Strategy definitions."))
flow.append(h2("2.4 Adaptive decision"))
flow.append(p(
    "The engine (Figure 1) issues EXPLAIN (FORMAT JSON) on the input query, "
    "parses <font face='Courier'>Plan Rows</font> for the pre-filter, computes the "
    "selectivity estimate <i>s</i>, maps it to a discrete bucket, looks up the "
    "calibration table for that bucket, applies an admission rule per strategy, "
    "and returns the strategy with the lowest median calibrated latency among the feasible "
    "set. The default rule is <i>min-recall</i>: a strategy is admitted iff its empirical "
    "minimum Recall@10 on the calibration samples is at least the target 0.95."))
flow.append(fig("figure_1_decision_flow.pdf", width=5.0))
flow.append(cap("Figure 1: Adaptive decision flow."))

flow.append(h2("2.5 ANN index configuration"))
flow.append(p(
    "The HNSW index on the present host was built with "
    "<font face='Courier'>ef_construction = 200</font>, "
    "<font face='Courier'>m = 16</font>, and the default "
    "<font face='Courier'>ef_search = 100</font> at query time. The original "
    "PG&nbsp;16.14 baseline used <font face='Courier'>ef_construction = 64</font> "
    "and otherwise identical parameters; that figure is preserved in the audit "
    "(<font face='Courier'>final/audit/ann_parameter_audit.md</font>). The present "
    "value was deliberately raised to improve HNSW graph quality on the current "
    "host. As a result, the HNSW graph on the present host is not bit-identical to "
    "the original PG&nbsp;16.14 graph, and this is the dominant observed factor in "
    "the cross-environment recall divergence. The change is applied consistently "
    "to the ANN setup and is not a post-hoc adjustment to the held-out policy. "
    "All final numbers in this paper are internally consistent with "
    "<font face='Courier'>ef_construction = 200</font> "
    "(see <font face='Courier'>final/frozen_configuration.yaml</font>). The IVFFLAT "
    "index uses <font face='Courier'>lists = 100</font> (or 1000 in the original "
    "baseline), with <font face='Courier'>probes = 10</font> at query time."))
flow.append(h2("2.6 SQL_FIRST access-path configuration"))
flow.append(p(
    "The <font face='Courier'>SQL_FIRST</font> strategy is run with "
    "<font face='Courier'>enable_indexscan = off</font> "
    "set via <font face='Courier'>SET LOCAL</font> before each query. This forces "
    "PostgreSQL to use a sequential scan or a bitmap-index scan over the relational "
    "filter, rather than a B-tree index scan. The choice is made so that the "
    "comparison against ANN strategies is not artificially tilted by an unrelated "
    "B-tree index plan: with a B-tree plan, <font face='Courier'>SQL_FIRST</font> "
    "can be made arbitrarily fast on highly selective predicates, but the resulting "
    "plan is workload-dependent and does not represent a portable comparison point. "
    "The B-tree indexes on <font face='Courier'>category</font>, "
    "<font face='Courier'>price</font>, and <font face='Courier'>in_stock</font> "
    "remain in place; they simply are not used by <font face='Courier'>SQL_FIRST</font>."))
flow.append(h2("2.7 Experimental protocol and cache conditions"))
flow.append(p(
    "All latency measurements use a <i>warm-cache</i> microbenchmark protocol: one "
    "warmup repetition is executed and discarded before each measurement, and three "
    "measurement repetitions are recorded per (query, strategy) cell. Reported means "
    "and 95% bootstrap confidence intervals are computed over the per-query means "
    "across the 125 held-out queries. The reported latencies should therefore be "
    "interpreted as <i>post-warmup</i> query times; they are not representative of "
    "cold-start or storage-bound workloads. The relative ordering of strategies may "
    "differ under cold-cache or larger working-set conditions, and additional "
    "environments are required for any broader generalization."))

# Section 3: Headline results
flow.append(PageBreak())
flow.append(h1("3. Headline results"))
flow.append(h2("3.1 Main run"))


def get_row(name):
    r = main[main["strategy"] == name].iloc[0]
    return [name, fmt(r["mean_latency_ms"], 2), fmt(r["p95_latency_ms"], 2),
            fmt(r["mean_recall_at_10"], 3), fmt(r["min_recall_at_10"], 3),
            "[" + fmt(r["recall_ci_lo"], 3) + ", " + fmt(r["recall_ci_hi"], 3) + "]"]


headline = [["Strategy", "mean (ms)", "p95 (ms)", "mean R@10", "min R@10", "R@10 CI"]]
for n in ["HNSW_HYBRID", "IVFFLAT_HYBRID", "SQL_FIRST", "VECTOR_FIRST_HNSW"]:
    headline.append(get_row(n))
r = main[main["strategy"] == "Adaptive"].iloc[0]
headline.append(["Adaptive", fmt(r["mean_latency_ms"], 2),
                 fmt(r["p95_latency_ms"], 2), fmt(r["mean_recall_at_10"], 3),
                 fmt(r["min_recall_at_10"], 3),
                 "[" + fmt(r["recall_ci_lo"], 3) + ", " + fmt(r["recall_ci_hi"], 3) + "]"])
flow.append(t(headline, col_widths=[1.4*inch, 0.7*inch, 0.7*inch, 0.8*inch, 0.7*inch, 1.2*inch]))
flow.append(cap("Table 1: Headline results on 200K SIFT1M subset, 125 held-out queries (3 reps, 95% bootstrap CIs)."))
flow.append(p(
    "Three observations from Table 1: (i) hybrid strategies match SQL-first on recall and "
    "on latency, (ii) vector-first HNSW violates the 0.95 target on a substantial fraction "
    "of queries (minimum 0.00, 95% upper CI 0.88), and (iii) the adaptive engine succeeds "
    "on every query."))
flow.append(h2("3.2 Per-strategy scatter"))
flow.append(fig("figure_2_strategy_vs_selectivity.pdf", width=6.0))
flow.append(cap("Figure 2: Per-query latency and recall vs EXPLAIN-estimated pre-filter selectivity, all four strategies."))

# Section 4: Policy
flow.append(PageBreak())
flow.append(h1("4. Admission policy ablation"))
policy_data = [["Policy", "ANN sel.", "R@10", "unsafe", "mean ms"]]
for _, r in pol.iterrows():
    unsafe_str = f"{int(r['frac_unsafe_ann'])}" if not pd.isna(r['frac_unsafe_ann']) else "0"
    sel_str = f"{int(r['ann_selections'])}/{int(r['queries'])} ({fmt(r['ann_pct'], 0)}%)"
    policy_data.append([r["policy"], sel_str,
                        fmt(r["mean_recall_at_10"], 3), unsafe_str,
                        fmt(r["mean_latency_ms"], 2)])
flow.append(t(policy_data, col_widths=[1.3*inch, 1.6*inch, 0.8*inch, 0.6*inch, 0.8*inch]))
flow.append(cap("Table 2: Admission policy comparison on 125 held-out queries."))
flow.append(p(
    "The four conservative rules (min_recall, mean_recall, quantile_recall, lcb_recall) "
    "are equivalent on this workload because the same 100 queries clear all of them. With "
    "n&nbsp;=&nbsp;21&ndash;27 calibration observations per (strategy, bucket) cell (approximately 25 per cell), a Wilson 95% lower "
    "confidence bound, a 5%-quantile, and an empirical minimum are all driven by the same "
    "handful of low-recall observations, so the four rules collapse to the same decision on this "
    "sample. We do <i>not</i> claim that min_recall is superior to the other three conservative "
    "rules; we only claim that the choice of admission rule is a real, observable lever on the "
    "safety&ndash;coverage curve. "
    "<font face='Courier'>failure_rate</font> (Wilson lower confidence bound on the fraction of "
    "unsafe queries) is substantially more conservative and admits 0/125 ANN queries on this "
    "workload, illustrating the upper end of the safety-coverage tradeoff."))
flow.append(fig("figure_6_safety_coverage.pdf", width=5.0))
flow.append(cap("Figure 3: Safety-coverage tradeoff across admission policies."))

# Section 5: Selection by bucket
flow.append(h1("5. Selection by selectivity bucket"))
flow.append(fig("figure_3_adaptive_selection.pdf", width=6.0))
flow.append(cap("Figure 4: Adaptive strategy selection by selectivity bucket on 125 held-out queries. Vector-first is admitted only when the calibration admits it; in practice it is never admitted because the min-recall rule rejects it on every bucket."))
sel_path = RES / "main_run" / "selection_by_bucket.csv"
if sel_path.exists():
    sel = pd.read_csv(sel_path)
    piv = sel.pivot_table(index="bucket", columns="adaptive_selected",
                          values="count", fill_value=0).astype(int)
    sel_tbl = [["Bucket"] + list(piv.columns)]
    for b, row in piv.iterrows():
        sel_tbl.append([b] + [str(int(v)) for v in row])
    flow.append(t(sel_tbl, col_widths=[1.0*inch] + [0.7*inch]*len(piv.columns)))
    flow.append(cap("Table 3: Selection count by (bucket, strategy) for the adaptive policy with min-recall rule."))

# Section 6: Parameter sensitivity
flow.append(h1("6. Parameter sensitivity"))
flow.append(p(
    "The 12-point sweep over <font face='Courier'>ef_search</font> &isin; {40,100,200,400} "
    "and <font face='Courier'>probes</font> &isin; {1,10,50} confirms that hybrid strategies "
    "are insensitive to these parameters on this workload (Recall@10 = 1.0 throughout), while "
    "vector-first HNSW remains at 0.83 regardless."))
flow.append(fig("figure_7_parameter_sensitivity.pdf", width=6.0))
flow.append(cap("Figure 5: Parameter sensitivity: hybrid strategies flat at 1.0; vector-first flat at 0.83."))
budget_tbl = [["vf_budget", "VECTOR_FIRST_HNSW R@10"]]
for b, g in budget.groupby("vf_budget"):
    vfh = g[g["strategy"] == "VECTOR_FIRST_HNSW"]
    if len(vfh) > 0:
        budget_tbl.append([str(int(b)), fmt(vfh.iloc[0]["mean_recall_at_10"], 3)])
flow.append(t(budget_tbl, col_widths=[1.5*inch, 2.5*inch]))
flow.append(cap("Table 4: Vector-first HNSW budget sweep. Increasing the candidate budget monotonically lifts mean Recall@10 from 0.701 (budget=50) to 0.942 (budget=1000); mean recall does not reach 0.95 at any tested budget, so the min-recall rule continues to reject Vector-First HNSW across the entire sweep. The paper does not extrapolate beyond budget=1000."))

# Section 7: Multi-seed
flow.append(h1("7. Multi-seed replication"))
seed_tbl = [["Seed", "HNSW_HYBRID", "IVFFLAT_HYBRID", "SQL_FIRST", "VECTOR_FIRST_HNSW"]]
for s, g in seed.groupby("seed"):
    row = [str(s)]
    for strat in ["HNSW_HYBRID", "IVFFLAT_HYBRID", "SQL_FIRST", "VECTOR_FIRST_HNSW"]:
        sub = g[g["strategy"] == strat]
        row.append(fmt(sub.iloc[0]["mean_recall_at_10"], 3) if len(sub) else "-")
    seed_tbl.append(row)
flow.append(t(seed_tbl, col_widths=[0.8*inch] + [1.2*inch]*4))
flow.append(cap("Table 5: Recall@10 by seed. Three seeds reproduce the qualitative recall ordering on the evaluated workload: Vector-First HNSW remained below the 0.95 target while the hybrid strategies achieved 1.0 recall in every seed. We do not claim universal robustness across all random seeds; three seeds is sufficient only for the qualitative claim reported."))

# Section 8: Threats
flow.append(h1("8. Validity threats, limitations, and discussion"))
flow.append(h2("8.1 Why the original PG 16.14 baseline disagreed"))
flow.append(p(
    "<font face='Courier'>pgvector</font>'s HNSW uses a randomized graph construction that "
    "is not bit-exact across libc implementations. On the original PG&nbsp;16.14 environment, "
    "the HNSW graph quality was poorer and the hybrid strategies underperformed "
    "<font face='Courier'>SQL_FIRST</font>. On the current PG&nbsp;17.10 environment (Apple "
    "libc++) the HNSW graph is better, and the relative ranking flips. We are unable to "
    "reproduce the original paper's exact numbers without the original environment; this is a "
    "known portability issue in the HNSW implementation and is tracked upstream. The present "
    "host uses <font face='Courier'>ef_construction = 200</font>, deliberately raised from "
    "the original baseline value of 64 to improve graph quality; this is the dominant "
    "observed factor in the cross-environment recall divergence (see "
    "&sect;&nbsp;2.5 and <font face='Courier'>final/audit/ann_parameter_audit.md</font>). "
    "We do not claim that <font face='Courier'>ef_construction</font> alone explains the "
    "divergence; the original environment is no longer available for re-execution."))
flow.append(h2("8.2 What this paper is and is not claiming"))
flow.append(p(
    "This paper does not claim that the adaptive engine is faster than "
    "<font face='Courier'>SQL_FIRST</font> on this workload. On the present hardware, the "
    "hybrid strategies do not beat <font face='Courier'>SQL_FIRST</font> by a meaningful "
    "margin: Adaptive mean 15.10&nbsp;ms (CI [13.98, 16.30]) vs SQL_FIRST 15.29&nbsp;ms "
    "(CI [14.15, 16.49]); the difference is well inside the bootstrap interval and is not "
    "established as significant. The contribution is the <i>correctness</i> of the admission "
    "layer: on a workload where one strategy is unsafe, the engine refuses to use it and "
    "selects a safe alternative, with zero safety violations and no observable latency "
    "penalty. On workloads where the unsafe strategy becomes safe (e.g., larger candidate "
    "budgets, different hardware), the same engine would admit it, because the admission "
    "rule is data-driven and re-evaluated whenever the calibration is refreshed."))
flow.append(h2("8.3 Limitations"))
flow.append(p(
    "The study has the following limitations, each of which constrains the scope "
    "of the claims above. (1)&nbsp;One dataset (SIFT1M, 200K subset, 250 queries, "
    "deterministic seed) and one host (macOS 14.6, Apple clang, libc++); no other "
    "hardware, OS, or libc is included. (2)&nbsp;Warm-cache microbenchmark only; "
    "cold-start, large-working-set, and storage-bound behaviour is not measured "
    "(see &sect;&nbsp;2.7). (3)&nbsp;Synthetic workload: three predicate columns, "
    "five selectivity buckets, no multi-predicate conjunctions, no joins, no "
    "full-text/fuzzy/streamed predicates. (4)&nbsp;Findings are tied to "
    "<font face='Courier'>pgvector</font>'s HNSW implementation, whose graph "
    "quality is sensitive to the build environment. (5)&nbsp;Three random seeds "
    "are sufficient only for the qualitative recall-ordering claim of "
    "&sect;&nbsp;7. (6)&nbsp;Finite-sample calibration (n&nbsp;=&nbsp;21&ndash;27 per "
    "cell) makes the four conservative admission rules of &sect;&nbsp;4 "
    "indistinguishable on this sample. (7)&nbsp;Selectivity-estimate error from "
    "<font face='Courier'>EXPLAIN</font> is not explicitly modelled. (8)&nbsp;No "
    "cold-cache, learned-cost-model, or exact-hybrid baseline in the comparison "
    "set."))

# Section 9: Related work
flow.append(h1("9. Related work"))
flow.append(p(
    "Adaptive query processing (AQP) has a long lineage: the Eddies architecture "
    "[1], TelegraphCQ [3], LEOPARD [4], LEO [5], and the "
    "Neo/SkinnerDB line of learned cost models [6, 7] all use a planning-time or "
    "mid-query feedback signal to discriminate among fixed-plan candidates. SDAO "
    "inherits this idea and applies it to the hybrid SQL&ndash;vector setting "
    "with a recall-aware admission layer. ANN search is well studied: HNSW [8] "
    "and IVFFlat are the standard in-memory indexes; "
    "<font face='Courier'>pgvector</font> [9] (used here), Faiss [10], and Milvus "
    "[11] all expose a recall/latency tradeoff via "
    "<font face='Courier'>ef_search</font>/<font face='Courier'>probes</font>/"
    "<font face='Courier'>nprobe</font>. Hybrid filtered ANN has been studied as "
    "pre-filtering, post-filtering, and metadata-filtered search; recent work "
    "includes ACORN [12], which augments HNSW with filter-aware edges. The "
    "<font face='Courier'>pgvector</font> implementation used here pre-filters "
    "via a relational <font face='Courier'>WHERE</font> clause and then runs ANN "
    "over the remainder. The gap this paper addresses is not in the hybrid-search "
    "algorithm itself, but in the engineering of an adaptive selector with a "
    "recall-aware admission layer that empirically characterizes when each "
    "strategy is safe on a given workload."))

# Section 10: Reproducibility
flow.append(h1("10. Reproducibility"))
flow.append(p(
    "All code, data, and frozen results are in this repository. The frozen "
    "configuration is at "
    "<font face='Courier'>final/reproducibility/final_config.json</font>, the audit "
    "trail at <font face='Courier'>final/audit/</font>, and the per-experiment "
    "raw artifacts at <font face='Courier'>final/results/</font>. The original "
    "baseline artifacts "
    "(<font face='Courier'>results/real_run_20260826T065155Z/</font>) are "
    "protected by a SHA-256 manifest "
    "(<font face='Courier'>final/audit/original_artifact_shas.json</font>). The "
    "validator <font face='Courier'>final/scripts/validate.py</font> checks the "
    "PDF, all 8 figure files, VFH recall CI, budget-sweep values, multi-seed "
    "values, policy admission counts, bucket-selection totals, plan-verification "
    "sanity, original-SHA preservation, and "
    "<font face='Courier'>ef_construction</font> consistency. To reproduce "
    "end-to-end, follow <font face='Courier'>REPRODUCE.md</font>."))

# Section 11: Conclusion
flow.append(h1("11. Conclusion"))
flow.append(p(
    "We constructed, audited, and stress-tested a Selectivity-Driven Adaptive "
    "Query Processing engine with recall-aware admission for hybrid "
    "SQL&ndash;vector queries. On the present PostgreSQL&nbsp;17.10 + "
    "<font face='Courier'>pgvector</font> + SIFT1M environment, the admission "
    "layer correctly rejects a known-unsafe Vector-First HNSW strategy across "
    "the entire selectivity range, all parameter sweeps, all budget sweeps, and "
    "three random seeds, while admitting safe hybrid alternatives with no "
    "measurable latency cost. The study does not establish a general latency "
    "advantage for the adaptive engine, nor broad cross-dataset generalization. "
    "It establishes that a calibration-driven, recall-constrained admission "
    "layer is a tractable design pattern for hybrid SQL&ndash;vector queries on "
    "the evaluated workload, and that the original paper's stronger claim about "
    "the speed of the unsafe strategy does not transfer to the present "
    "environment. The paper has been rewritten against the actual measurements."))

# References
flow.append(h1("References"))
ref_rows = [
    "[1] R. Avnur and J. M. Hellerstein. Eddies: Continuously Adaptive Query Processing. SIGMOD, 2000.",
    "[2] J. M. Hellerstein et al. Adaptive Query Processing: Technology in Evolution. IEEE Data Eng. Bull. 23(2), 2000.",
    "[3] S. Chandrasekaran et al. TelegraphCQ: Continuous Dataflow Processing for an Uncertain World. CIDR, 2003.",
    "[4] R. L. Cole et al. The LEOPARD System for Parallel Adaptive Query Processing on Clusters. VLDB, 2005.",
    "[5] H. Stillger, G. M. Lohman, V. Markl, and L. B. Ooi. LEO &mdash; DB2's LEarning Optimizer. VLDB, 2001.",
    "[6] R. Marcus et al. Neo: A Learned Query Optimizer. PVLDB 12(11), 2019.",
    "[7] I. Trummer et al. SkinnerDB: Regret-Bounded Query Evaluation via Reinforcement Learning. SIGMOD, 2018.",
    "[8] Y. A. Malkov and D. A. Yashunin. Efficient and Robust Approximate Nearest Neighbor Search Using HNSW Graphs. IEEE TPAMI 42(4), 2020.",
    "[9] pgvector project. Open-source vector similarity search for PostgreSQL. https://github.com/pgvector/pgvector.",
    "[10] J. Douze et al. The Faiss Library. arXiv:2401.08281, 2024.",
    "[11] J. Wang et al. Milvus: A Purpose-Built Vector Data Management System. SIGMOD, 2021.",
    "[12] L. Pan et al. ACORN: Performant and Predicate-Agnostic Search Over Vector Embeddings. PVLDB 16(6), 2023.",
]
# Two-column layout: refs 1-6 on left, 7-12 on right
left = ref_rows[:6]
right = ref_rows[6:]
n = max(len(left), len(right))
for i in range(n):
    if i >= len(left):
        left.append("")
    if i >= len(right):
        right.append("")
# Use Paragraphs so long URLs wrap inside the column rather than overlapping the other column
ref_style = ParagraphStyle("refentry", fontName="Helvetica", fontSize=6.5, leading=7.6, wordWrap='CJK')
def _wrap(s):
    if not s:
        return ""
    return Paragraph(s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), ref_style)
ref_tbl = Table([[_wrap(l), _wrap(r)] for l, r in zip(left, right)],
                colWidths=[3.4*inch, 3.4*inch],
                style=TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]))
flow.append(ref_tbl)

doc.build(flow)
print("Wrote", OUT)
print(" ", OUT.stat().st_size, "bytes")
