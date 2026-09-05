# REVIEWER RISK ASSESSMENT
## A Selectivity-Driven Adaptive Query Processing Engine for Hybrid SQL–Vector Databases

**Assessment Date**: 2026-08-15  
**Manuscript**: main_upgraded.tex  
**Intended Venue**: SIGMOD / VLDB / ICDE (top-tier systems conference)

---

## EXECUTIVE RISK SUMMARY

| Risk Category | Level | Confidence | Mitigation |
|---|---|---|---|
| **Calibration Leakage** | 🔴 HIGH | 95% | Explicitly acknowledged in §10.1, §13. Proposed disjoint splits in §11.A. |
| **Single-Run Measurements** | 🔴 HIGH | 95% | Explicitly acknowledged in §10.2, §13. Proposed repeated runs/CI in §11.D. |
| **No Held-Out Validation** | 🔴 HIGH | 95% | Explicitly acknowledged in §13. Proposed disjoint test set in §11.A. |
| **Small Workload (32 queries)** | 🟠 MEDIUM | 90% | Acknowledged in §10.5. Proposed larger workloads in §11.B. |
| **Single Dataset (SIFT1M only)** | 🟠 MEDIUM | 90% | Acknowledged in §10.12. Proposed SIFT10M/BEIR in §11.B. |
| **Overhead Not Amortized** | 🟠 MEDIUM | 85% | Deeply discussed in §9.4. Net end-to-end benefit unclear. |
| **ANN Parameters Fixed** | 🟠 MEDIUM | 85% | Acknowledged in §10.8, 10.9, 10.10. Sensitivity analysis proposed §11.E. |
| **No Statistical Significance** | 🟡 LOW | 80% | Acknowledged throughout. Proposed tests in §11.D. |
| **Plan Verification Not Proof** | 🟡 LOW | 90% | Explicitly stated in §5.3, §10.17. Clearly presented as integrity check. |

---

## DETAILED VULNERABILITY ANALYSIS

### 1. CALIBRATION LEAKAGE 🔴 HIGH RISK

**Problem**  
The adaptive policy is trained and evaluated on the *same* 32-query workload. There is no held-out test set. This violates fundamental experimental methodology: the policy is tuned to these specific 32 queries.

**Evidence in Manuscript**  
- §10.1 explicitly states: "The same 32 queries were used for calibration and evaluation, so the policy has calibration leakage."
- §7.2 describes methodology as calibration + adaptive evaluation using same workload.
- §13 (Conclusion) emphasizes: "Result specific to 32-query workload."

**Reviewer Concern**  
"The 20.81% improvement is not a genuine result; it's a memorization artifact."

**Manuscript Mitigation**  
- **Explicit**: §10.1 acknowledges this is "the most critical threat."
- **Honesty**: §13 states "calibration leakage and no held-out estimate of quality."
- **Prospective**: §11.A proposes disjoint 50/25/25 calibration/validation/test split.
- **Framing**: Positioned as "exploratory evaluation on the evaluated workload" not "generalizable evidence."

**Residual Risk Assessment**  
- **Cannot be eliminated** without additional experiments (not performed).
- **Mitigated by**: Candid acknowledgment + proposed protocol for future work.
- **Reviewer May Still Object**: Yes. Recommend stating in cover letter: "This is intentionally an exploratory evaluation; rigorous validation is proposed future work."

**Recommendation for Rebuttal**  
"Calibration leakage is acknowledged in §10.1 and §13. The policy's generalization to held-out workloads is unknown. Future rigorous evaluation using disjoint splits is outlined in §11.A. This manuscript is positioned as an exploratory feasibility study, not a claim of validated technique."

---

### 2. SINGLE-RUN MEASUREMENTS 🔴 HIGH RISK

**Problem**  
All latency measurements are from a single execution per query in a warm persistent PostgreSQL session. There are:
- No repeated runs
- No confidence intervals
- No variance estimates
- No bootstrapping
- No statistical significance testing

The 20.81% improvement and Recall@10 = 1.000 could be artifacts of a single warm-cache run.

**Evidence in Manuscript**  
- §7.6: "No statistical significance tests, confidence intervals, or bootstrapping are performed."
- §7.4: "warm persistent PostgreSQL session. The session is not restarted between queries."
- §10.2: "Measurements are single-run observations on a warm persistent-session...without controlled cold-cache conditions."
- §13: "single-run warm-session measurements."

**Reviewer Concern**  
"What are the confidence intervals? What is the variance? Is 51.32 ms significantly different from 64.80 ms?"

**Manuscript Mitigation**  
- **Explicit**: §10.2 fully acknowledges lack of repeated runs and CI.
- **Honesty**: Results presented as "descriptive single-run observations."
- **Prospective**: §11.D proposes "repeated randomized or paired trials; separate warm- and cold-cache reporting; confidence intervals."
- **Framing**: Not claimed as statistically significant.

**Residual Risk Assessment**  
- **Cannot be eliminated** without additional runs (not performed).
- **Mitigated by**: Honest presentation; no significance claims; clear methodology.
- **Reviewer May Still Object**: Likely. Suggest in rebuttal: "Confidence intervals are proposed in §11.D as part of future rigorous evaluation. This manuscript is a single-run feasibility study."

**Recommendation for Rebuttal**  
"§7.6 and §10.2 acknowledge that no confidence intervals or significance tests are performed. These are explicitly proposed for future evaluation (§11.D). The manuscript does not claim statistical significance; results are presented as descriptive measurements on the single evaluated run."

---

### 3. NO HELD-OUT VALIDATION 🔴 HIGH RISK

**Problem**  
There is no separate held-out test workload. All 32 queries are used for both calibration and evaluation. This is compounded by single-run measurements.

**Evidence in Manuscript**  
- §7.2: "Calibration and evaluation use the same 32-query workload."
- §7.7: "Explicitly not held-out evaluation."
- §10.1: "policy has calibration leakage and no held-out estimate of quality."

**Reviewer Concern**  
"How do you know the policy works on queries the system hasn't seen before?"

**Manuscript Mitigation**  
- **Explicit**: §10.1 and §13 state this directly.
- **Honesty**: Characterized as "implementation demonstration, not independent validation."
- **Prospective**: §11.A proposes disjoint calibration/validation/test splits with specific 50/25/25 percentages.

**Residual Risk Assessment**  
- **Cannot be eliminated** without held-out workload (not performed).
- **Mitigated by**: Honest framing as "exploratory" not "validated."
- **Reviewer Will Likely Object**: Yes. This is a standard criticism for ML-like systems without test set.

**Recommendation for Rebuttal**  
"This is acknowledged as the primary limitation in §10.1 and §13. The evaluation is intentionally exploratory on the developed workload. §11.A provides a detailed protocol for rigorous future evaluation using disjoint splits. This manuscript is positioned as a feasibility study and stepping stone toward validated results."

---

### 4. SMALL WORKLOAD (32 QUERIES) 🟠 MEDIUM RISK

**Problem**  
32 queries is a small sample for workload characterization. SIFT1M benchmarks typically use hundreds or thousands of queries. Selection patterns, bucket viability, and strategy dominance may not generalize to 320 or 3200 queries.

**Evidence in Manuscript**  
- §10.5: "32 queries is a small sample...Patterns observed on these 32 may not hold for 320 or 3200 queries."
- §11.B: Proposes "larger workloads" as part of rigorous evaluation.

**Reviewer Concern**  
"This is a toy workload. The results are not meaningful for real systems."

**Manuscript Mitigation**  
- **Explicit**: §10.5 acknowledges small sample size.
- **Explicit**: This is not overclaimed as general behavior.
- **Prospective**: §11.B proposes evaluation on larger workloads.

**Residual Risk Assessment**  
- **Medium Risk**: Small workload is defensible for an exploratory study, but limits inference.
- **Mitigated by**: Honest presentation; framed as exploratory.
- **Reviewer May Object**: Moderately likely. Suggest in rebuttal: "32 queries is appropriate for an exploratory evaluation. §11.B outlines evaluation protocol for larger workloads (1000+ queries) in future work."

**Recommendation for Rebuttal**  
"32 queries is acknowledged in §10.5 as a limitation. This is intentionally an exploratory study suitable for initial feasibility testing. §11.B proposes evaluation on larger workloads (1000+ queries) as part of rigorous future work. For a conference paper introducing a new technique, initial exploration on smaller workloads is standard."

---

### 5. SINGLE DATASET (SIFT1M) 🟠 MEDIUM RISK

**Problem**  
Evaluation is on SIFT1M only. No results on SIFT10M, BEIR, custom datasets, or real application workloads. Results may be SIFT1M-specific.

**Evidence in Manuscript**  
- §10.12: "Evaluation is on SIFT1M only."
- §11.B: Proposes "Multiple Datasets" (SIFT10M, BEIR, custom).

**Reviewer Concern**  
"Does this work on other datasets? How do you know?"

**Manuscript Mitigation**  
- **Explicit**: §10.12 acknowledges single-dataset limitation.
- **Prospective**: §11.B outlines multi-dataset evaluation protocol.

**Residual Risk Assessment**  
- **Medium Risk**: Single-dataset evaluation is a known limitation, but defensible for exploratory work.
- **Mitigated by**: Honest framing; no generalization claims.
- **Reviewer May Object**: Moderately likely. Suggest in rebuttal: "§11.B proposes evaluation on SIFT10M, BEIR, and custom datasets. This manuscript establishes proof-of-concept on SIFT1M; multi-dataset validation is planned future work."

**Recommendation for Rebuttal**  
"Single-dataset evaluation is acknowledged in §10.12. For an exploratory systems paper, evaluation on one established benchmark (SIFT1M) is appropriate for initial feasibility testing. §11.B provides a detailed protocol for multi-dataset evaluation as part of future rigorous work."

---

### 6. DECISION OVERHEAD NOT AMORTIZED 🟠 MEDIUM RISK

**Problem**  
Decision-to-execution wall time is 91.14 ms (mean), compared to strategy-only latency of 51.32 ms. The overhead is substantial (178% of strategy latency). EXPLAIN, planning, and verification contribute ~40+ ms. The net end-to-end benefit is unclear.

**Evidence in Manuscript**  
- §8.5: "Mean decision-to-verified-execution wall time: 91.14 ms."
- §9.4: Deep analysis of overhead implications.
- §9.4: "Net end-to-end benefit (overhead included) may be reduced or even negative for some queries."

**Reviewer Concern**  
"The actual latency benefit is 13.48 ms, but the overhead is 40+ ms. This is a net loss!"

**Manuscript Mitigation**  
- **Explicit**: §9.4 explicitly states overhead may offset benefit.
- **Honesty**: Acknowledges "net end-to-end benefit (overhead included) may be reduced or even negative."
- **Caveat**: Suggests overhead amortization over multiple queries.
- **Framing**: Does not claim end-to-end benefit without qualification.

**Residual Risk Assessment**  
- **Medium Risk**: Overhead analysis undermines practical utility claims.
- **Mitigated by**: §9.4 is honest about this.
- **Reviewer May Object**: Likely. Suggest in rebuttal: "§9.4 analyzes overhead implications. For single-query bottleneck scenarios, overhead may be justified; for batch workloads, amortizing planning overhead across multiple queries is necessary. This is an open question motivating future end-to-end evaluation."

**Recommendation for Rebuttal**  
"Overhead implications are explicitly discussed in §9.4. The 20.81% improvement applies to strategy-only latency, not total application latency. Net end-to-end benefit including planning overhead (91.14 ms wall time) remains an open question, depending on workload structure and amortization. This is flagged as a critical limitation motivating end-to-end evaluation in §11.H."

---

### 7. ANN PARAMETERS FIXED 🟠 MEDIUM RISK

**Problem**  
HNSW ef_search and IVFFlat probes are frozen at pgvector defaults. No parameter sweep or sensitivity analysis. Results may be specific to these parameter choices. Different ef_search values dramatically change HNSW latency/recall tradeoff.

**Evidence in Manuscript**  
- §6.5: "frozen for all runs and are not individually tuned."
- §10.8: "Results are specific to the tested parameter settings."
- §11.E: Proposes "ANN parameter sweep" (HNSW ef_search, IVFFlat probes).

**Reviewer Concern**  
"What if you use different ANN parameters? Does the adaptive policy still work?"

**Manuscript Mitigation**  
- **Explicit**: §10.8 and §10.9 acknowledge parameter dependency.
- **Honest**: Results limited to frozen parameters.
- **Prospective**: §11.E proposes sensitivity analysis.

**Residual Risk Assessment**  
- **Medium Risk**: Parameter dependency is a real limitation.
- **Mitigated by**: Acknowledged; not overclaimed.
- **Reviewer May Object**: Moderately. Suggest in rebuttal: "§10.8 acknowledges parameter dependency. §11.E proposes sensitivity analysis across HNSW ef_search and IVFFlat probes as part of future evaluation. Results are specific to pgvector default settings."

**Recommendation for Rebuttal**  
"Parameter sensitivity is acknowledged in §10.8-10.10. The current evaluation uses pgvector default settings. §11.E proposes a sensitivity analysis across ANN parameters (HNSW ef_search ∈ {10, 40, 100, 200}, IVFFlat probes ∈ {1, 5, 20, 100}) as part of rigorous future evaluation."

---

### 8. NO STATISTICAL SIGNIFICANCE 🟡 LOW RISK

**Problem**  
No paired t-tests, Wilcoxon signed-rank tests, or other statistical significance testing. The claim "20.81% improvement" is not statistically validated.

**Evidence in Manuscript**  
- §7.6: "No statistical significance tests...are performed."
- §8.1: "This is not a significance claim."
- §13: "does not establish statistical significance."

**Reviewer Concern**  
"Is 51.32 ms significantly different from 64.80 ms? Have you done a significance test?"

**Manuscript Mitigation**  
- **Explicit**: §7.6 states no significance testing performed.
- **Explicit**: §8.1 and §13 disavow significance claims.
- **Prospective**: §11.D proposes "paired statistical tests where appropriate."

**Residual Risk Assessment**  
- **Low Risk**: Reviewer cannot claim significance testing is necessary if author explicitly disavows significance claims.
- **Mitigated by**: Honest presentation; no significance claims made.
- **Reviewer May Object**: Less likely, because manuscript doesn't claim significance. If they do, cite §7.6.

**Recommendation for Rebuttal**  
"§7.6 explicitly states that no statistical significance tests are performed. The manuscript does not claim statistical significance. §11.D proposes paired statistical tests (t-tests, Wilcoxon) as part of future rigorous evaluation using multiple independent trials."

---

### 9. PLAN VERIFICATION NOT PROOF 🟡 LOW RISK

**Problem**  
All 106 ANN executions were verified to have the expected plan evidence. However, plan verification is an integrity check, not proof of performance or generalization.

**Evidence in Manuscript**  
- §5.3: "Plan verification...is an integrity check, not a proof of performance or generalization."
- §10.17: "Plan verification is not described as proof of performance."

**Reviewer Concern**  
"Just because the expected plan was used doesn't mean the strategy was optimal or will generalize."

**Manuscript Mitigation**  
- **Explicit**: §5.3 clearly states this is "integrity check" not "performance guarantee."
- **Honest**: No overclaiming of what verification proves.

**Residual Risk Assessment**  
- **Low Risk**: Manuscript does not overclaim what verification means.
- **Mitigated by**: Clear statement that this is integrity check only.
- **Reviewer May Object**: Unlikely, because manuscript is clear about this.

**Recommendation for Rebuttal**  
"§5.3 explicitly states that plan verification is an integrity check, not a proof of performance or generalization. The 106 verified ANN executions confirm the expected access path was used, but do not establish performance guarantees on other workloads."

---

## REVIEWER ATTACK SURFACES

### Likely Reviewer Questions

| Question | Manuscript Section | Suggested Response |
|---|---|---|
| "How do you know this generalizes?" | §10 (all threats), §13 | "It doesn't. Calibration leakage is acknowledged in §10.1. Generalization to held-out workloads is unknown. §11 proposes rigorous future evaluation protocol." |
| "What are the confidence intervals?" | §7.6, §10.2 | "§7.6 acknowledges no CI computed. §11.D proposes CI as part of future evaluation with multiple runs." |
| "Why only 32 queries?" | §10.5, §11.B | "32 queries is appropriate for exploratory evaluation. §11.B proposes evaluation on 1000+ queries in future work." |
| "Why only SIFT1M?" | §10.12, §11.B | "§11.B proposes SIFT10M and BEIR evaluation as part of future rigorous work." |
| "Is this end-to-end faster?" | §9.4 | "End-to-end benefit unclear; 91.14 ms overhead may offset 13.48 ms latency gain. §9.4 analyzes this; §11.H proposes end-to-end measurement." |
| "What about ANN parameter tuning?" | §10.8, §11.E | "Parameters are frozen at pgvector defaults. §11.E proposes sensitivity analysis across parameter regimes." |
| "Did you test significance?" | §7.6, §8.1 | "§7.6 states no significance testing. §11.D proposes significance tests as part of future evaluation." |
| "How does this compare to external systems?" | §10.18, §11.F | "No comparison with Faiss, Milvus, etc. §11.F proposes cross-system evaluation as future work." |

---

## PAPER POSTURE ASSESSMENT

**Position**: **Exploratory systems feasibility study**

**Appropriate Framing**:
- ✅ "Demonstrates feasibility of selective-aware strategy selection."
- ✅ "Provides foundation for future rigorous evaluation."
- ✅ "Motivates extended evaluation protocol."
- ❌ "Proves state-of-the-art performance."
- ❌ "Guarantees generalization."
- ❌ "Establishes optimal strategy selection."

**Manuscript Compliance**: ✅ The manuscript follows appropriate framing throughout. No overclaiming detected.

---

## REVIEWER RECOMMENDATION PREDICTION

### Most Likely Reviewer Comments

**Reviewer 1 (Negative)**:
- "Calibration leakage undermines all claims."
- "Single-run measurements are insufficient."
- "No held-out validation."
- "32 queries too small."
- **Likely Recommendation**: Reject / Major Revision required

**Reviewer 2 (Mixed)**:
- "Honest limitations discussion is appreciated."
- "Proposed evaluation protocol is reasonable."
- "But current evaluation too limited for acceptance."
- "Overhead analysis shows net benefit unclear."
- **Likely Recommendation**: Major Revision / Conditional Accept pending additional experiments

**Reviewer 3 (Positive/Systems)**:
- "Exploratory feasibility study is valuable."
- "Clear problem formulation and algorithm."
- "Honest about limitations."
- "Proposed future protocol is comprehensive."
- "Worth publishing as early-stage work to guide future research."
- **Likely Recommendation**: Accept / Minor Revision

**Meta-Prediction**: Mixed reviews likely. Paper is **defensible but not strong** without additional experiments.

---

## MITIGATION STRATEGY FOR REBUTTAL

### If R1/R2 Object to Calibration Leakage

**Response Template**:
> "Calibration leakage is acknowledged as the primary threat (§10.1). This paper is positioned as an exploratory feasibility study, not a validated technique. The policy's generalization to held-out workloads is unknown and is the focus of proposed future work (§11.A). For an exploratory systems paper, feasibility demonstration on the development workload is appropriate; rigorous validation requires disjoint splits, which we propose for future evaluation."

### If R1/R2 Object to Overhead Offsetting Benefit

**Response Template**:
> "§9.4 explicitly analyzes decision overhead (91.14 ms wall time vs. 51.32 ms strategy-only latency). End-to-end benefit remains unclear and depends on workload structure and overhead amortization. This is acknowledged as an open question. §11.H proposes end-to-end measurement as part of future evaluation. For single-query bottleneck workloads, overhead may be justified; for batch workloads, amortization is necessary."

### If R1/R2 Object to Small Workload

**Response Template**:
> "32 queries is appropriate for an exploratory feasibility study on a well-understood benchmark (SIFT1M). §11.B proposes evaluation on larger workloads (1000+ queries) and additional datasets (SIFT10M, BEIR) as part of rigorous future validation. Initial exploration with smaller workloads is standard practice in systems research."

### If R3 Supports but R1 Rejects

**Response Strategy**:
- Emphasize exploratory positioning throughout.
- Offer to add qualifications/caveats if needed.
- Propose targeted experiments if resubmitting.
- Frame proposed evaluation protocol as "roadmap for rigorous future work."

---

## PUBLICATION LIKELIHOOD ASSESSMENT

| Scenario | Probability | Venue | Notes |
|---|---|---|---|
| **Accept (current)** | 15–25% | SIGMOD/VLDB systems track | Only if reviewer 3+ types; needs very positive committee. |
| **Major Revision** | 40–50% | Any top venue | Most likely if targeting SIGMOD/VLDB/ICDE. Requires additional experiments or data. |
| **Conditional Accept** | 10–15% | VLDB Research track | "Accepted pending author response to concerns." |
| **Desk Reject** | 5–10% | Strict venues | Some conferences pre-reject exploratory work. |
| **Accept (after revision)** | 50–70% | If resubmit to VLDB/EuroSys | With proposed experiments completed. |

**Recommendation**: 
- **For SIGMOD/VLDB/ICDE**: Prepare for major revision requests. Be ready to propose a targeted experiment (e.g., held-out test set on SIFT1M, repeated runs for CI).
- **For EuroSys / SOSP**: Exploratory positioning may be better received.
- **For Workshop / Symposium**: Very likely acceptance. Positioning as "feasibility study" is perfect for workshops.

---

## FINAL ASSESSMENT

**Honest Judgment**:
- ✅ **Manuscript is rigorous and honest about limitations.**
- ✅ **No unsupported claims; no overclaiming.**
- ✅ **Detailed proposed evaluation protocol is valuable for the community.**
- ❌ **Evaluation itself (as acknowledged) is insufficient for strong claims.**
- ❌ **Reviewers will likely request additional experiments.**

**Overall Risk Level**: 🟠 **MEDIUM** (50–50 chance at top venue without additional work)

**Confidence in Assessment**: 85% (based on typical SIGMOD/VLDB/ICDE reviewer panels and standards)

---

## RECOMMENDED NEXT STEPS

1. **Reframe for Workshop Submission**: If time-sensitive, submit to a systems workshop (VLDB Industrial, SIGMOD Systems, etc.). Exploratory positioning is perfect for workshops.

2. **Plan One Targeted Experiment**:
   - If doing one experiment: **Generate held-out test set** (separate 16 queries disjoint from calibration).
   - Run adaptive + fixed strategies on held-out set.
   - Report latency/recall on held-out set vs. calibration set.
   - This addresses calibration leakage criticism most directly.

3. **Add Repeated Runs** (if feasible):
   - 3–5 independent runs on same 32 queries.
   - Compute mean, CI, variance.
   - Addresses single-run measurement concern.

4. **Compute End-to-End Latency** (if easy):
   - Break down 91.14 ms overhead.
   - Measure strategy-only latency alone (already have: 51.32 ms).
   - Compute net end-to-end benefit.

5. **If Submitting as-is**: Lean into "exploratory" positioning. Emphasize that manuscript is a stepping stone, not a final answer. Use proposed evaluation protocol to signal serious future work.

---

**This assessment is conservative and designed to prepare authors for critical review. The manuscript is actually quite strong for an exploratory systems paper; most vulnerabilities are acknowledged, not hidden.**
