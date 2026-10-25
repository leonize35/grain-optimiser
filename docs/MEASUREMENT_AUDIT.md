# Performance measurement: audit and proposed corrections (for review; nothing implemented)

Status: audit and design (2026-10-25). No engine, metric or evidence file was changed. `paper2-v1`,
`paper2-ext-sampling-v1` and their manifests are untouched. No dispatching intervention (overtaking limits or
similar) is proposed until the operational queueing rules are verified.

**Revised (2026-10-25):** §3–§6 are superseded by `docs/MEASUREMENT_FRAMEWORK.md` after review. In particular, the §3
"RMST" is an occupancy measure, not an unbiased turnaround estimate; turned-away trucks are a separate outcome;
failed runs are not censored data; and drain-down clearance must be verified. §1–§2 (C1–C10) stand.

Objective: future experiments must distinguish improvements in **average turnaround** from improvements in
**throughput**, **backlog** and **fairness**, without survivorship bias.

## 1. Audit: how each measure is calculated now

| Measure | Where | Definition now | Population |
|---|---|---|---|
| Turnaround (mean, median, p90, max) | `TruckFlowModel._summaries` → `ActivitySummary`; KPI `{act}.mean_turnaround_min` | Departure − gate arrival, **completed trucks only** | Departed trucks |
| Turnaround incl. unfinished | `ActivitySummary.mean_turnaround_incl_unfinished_min` | Mean of completed turnarounds and unfinished trucks' time on site so far (to the last day's hard stop) | Completed + unfinished (turned away excluded). A **lower bound**, mixing censored and uncensored values. |
| Unfinished waiting | `ActivitySummary.unfinished_waiting_min` | Time on site so far, per unfinished truck | Unfinished |
| Total waiting per truck | `_fairness` → `TruckMetrics.total_waiting_min` | Time on site not in service, up to departure, being turned away, or the end | All arrived trucks |
| Per-commodity waits | `CommodityFairness` | Mean, median, p95, max over **all** trucks (mixed); completed-only and censored figures kept separately (since step 14) | All arrived trucks of the commodity |
| Overtaking | Dispatcher overtake log → `overtaken_by_later`, `overtaken_at_hopper`, in-queue, feasible / infeasible | Counted while the truck waits; for unfinished trucks, **so far** | All arrived trucks |
| Starvation | `TruckMetrics.starved` | Total waiting ≥ threshold (default 120 min), or overtakes ≥ threshold if set | All arrived trucks. Unfinished trucks below the threshold are counted **not starved**. |
| Throughput | KPIs `received_t` (grain tipped), `{act}.completed` | Within the run horizon | — |
| Backlog | KPI `{act}.unfinished`; `unfinished` list | Count still on site at the end (end-of-day policy dependent) | — |
| Experiment summaries | `experiments.runner.run_experiment` | Mean and CI over replications with status `ok`; **stalled or invalid replications are excluded** | Successful replications |
| Paired differences | `experiments.runner.paired` | Uses only replications where **both arms** have a value | Pairs where neither arm failed |
| Evidence tools | `tools/evidence/runner.py`, `export.py`, `sampling_ext.py` | Means and paired comparisons over **all** runs, stalled ones included (stall reported separately) | All runs |

## 2. Where unfinished trucks cause censoring or biased comparisons

| # | Problem | Evidence | Effect |
|---|---|---|---|
| C1 | **Survivorship bias in completed-only turnaround.** A policy that leaves difficult trucks unfinished looks faster. | `paper2-v1`, EV-C1, Site A ×1.2: M-FF 117.3 min completed-only against M-PT 191.7 (gap 74 min). Including unfinished trucks' time on site: 209.9 against 231.1 (gap 21 min). M-FF leaves 22.2 unfinished, M-PT 24.2. | The policy effect on turnaround is **overstated about 3.5×** when measured on completed trucks only. |
| C2 | **Mixed means.** The incl-unfinished mean and the per-commodity waits mix censored and uncensored values. | `ActivitySummary`, `CommodityFairness` | Lower bounds whose bias depends on the number unfinished. They are comparable across arms only because arrivals are identical (C6), and only at the same horizon. |
| C3 | **Starvation under-counted.** Unfinished trucks below the threshold may later starve. | `_fairness`: `starved = waiting >= limit` | Starvation incidence is a **lower bound**. It is worse for policies with more unfinished trucks. |
| C4 | **Overtaking for unfinished trucks is partial.** | Overtake log ends at the run end | Lower bound; the same direction as C3. |
| C5 | **Throughput excludes work in progress.** Grain tipped by a truck not yet weighed out counts in `received_t` but not in `completed`. | `received_t` vs `completed` | Two throughput measures that can rank policies differently. Both must be reported, with their definitions. |
| C6 | **Demand identity under common random numbers** holds for runs without stalls. | EV-C1: truck counts identical across policies in every (site, demand, seed) cell (checked: 0 differing cells) | Paired comparisons are valid. |
| C7 | **A stall cancels all remaining events, including arrivals.** The stalled arm then has fewer trucks. | EV-S2 seed 1: M-SF 108 trucks against 187 for M-FF and M-PT | The populations differ. Means over a stalled run compare different demand. |
| C8 | **Silent pair dropping and exclusion.** `run_experiment` excludes stalled replications; `paired` drops pairs where one arm failed. | `experiments/runner.py` (`good = ...status == "ok"`; `paired`) | **Selection bias**: arms are compared on the replications that favour neither failing. The evidence tools avoid this, but include truncated runs instead (C7). |
| C9 | **Horizon dependence.** All "unfinished" figures depend on the end-of-day rule and the horizon (1 day, carry-over not simulated). | `EndOfDay`, `days = 1` | Backlog and censoring change with the horizon; results are horizon-specific. |
| C10 | **Turned-away trucks** are outside turnaround and waiting statistics (correct), but their number can depend on policy at the hard stop (`unfinished_trucks: turned_away`). | `_service_stops` | Must be reported as an outcome, never dropped. |

## 3. Proposed reporting design (backward compatible: new fields only; existing fields keep their meaning)

**Population.** Every truck generated for the run's arrival window is **one observation**, with exactly one outcome:
- `completed`;
- `unfinished` (right-censored at T_end, the last day's hard stop);
- `turned_away`, with its reason;
- `not_arrived`, which happens only when a stall cancelled its arrival. That flags the run as truncated for population
  comparisons.

**Measures per activity, and per commodity for fairness:**

| Measure | Definition | Notes |
|---|---|---|
| **Completion rate** | completed / arrived | Primary throughput-for-trucks measure; comparable under common random numbers |
| **Completed-truck turnaround** | Mean, median, p90 over completed trucks | Always labelled **"conditional on completion"**; never used alone to rank policies |
| **Restricted mean time on site (RMST)** | Mean over all arrived trucks of min(time on site, T_end − arrival), turned-away trucks to their send-away time | Unbiased for the same arrivals and the same T_end; the primary turnaround comparison. It equals today's incl-unfinished mean with turned-away trucks added. |
| Kaplan-Meier time-on-site curve and median (optional) | Standard right-censoring estimator | Handles censoring without imputation; median defined while ≥ 50% have completed |
| **Unfinished-truck waiting** | Count, and the distribution of time on site so far | Reported as censored (lower bounds) |
| **Backlog** | (a) unfinished trucks and tonnes at T_end; (b) **time-integrated backlog**, truck-hours on site (∫ trucks present dt); (c) queue at the hard stop per stage | (b) is horizon-consistent and captures congestion over the day |
| **Throughput** | Tonnes received in the horizon; completed trucks; tonnes of completed trucks | Definitions stated explicitly (C5) |
| **Fairness** | Per commodity: completion rate, RMST, distribution of overtakes by later arrivals (all trucks), starvation as **[lower, upper] bounds** | Lower bound counts censored trucks below the threshold as not starved; upper bound counts them as starved |
| **Clearance (drain-down only)** | Time from the admission cut-off until the last admitted truck departs; total time on site, all uncensored | §5 |

**Run validity flags:**
- `truncated_by_stall`: arrivals cancelled. Population measures are flagged and reported separately.
- `horizon`: T_end.
- `end_of_day_rule`.

**Implementation scope (when approved):**
- outcome per truck, RMST, completion rate, backlog integral, starvation bounds and validity flags in
  `TruckFlowResult`;
- new experiment figures;
- evidence tools updated to use them.

Existing figures stay. Existing packages are not rebuilt or edited; new figures appear only in new, separately
versioned packages.

## 4. Statistical comparisons

- **Pairing:** by seed under common random numbers. Arrivals are identical, which is verified per pair (truck-count
  and arrival-hash check; C6).
- **Primary measures:**
  - RMST;
  - completion rate (paired difference in proportions per seed);
  - time-integrated backlog;
  - throughput (tonnes, completed trucks);
  - fairness per commodity: RMST, completion rate, starvation bounds.
- **Secondary:** completed-truck turnaround, always labelled conditional, and reported with the completion rate
  beside it.
- **Inference:** paired Student *t* CIs, with paired bootstrap CIs as a robustness check (skewed waits). Holm
  adjustment within each pre-declared family (throughput, backlog, turnaround, fairness).
- **No silent exclusion:**
  - pairs in which either arm stalled or truncated are **reported separately and counted**;
  - the primary analysis uses complete pairs, with the number excluded stated;
  - a sensitivity analysis treats a stalled arm as censored at the stall time.
- **Precision:** replication counts set from the observed paired half-widths, for example to resolve a stated
  minimum difference.

## 5. Optional drain-down experiment (no engine change needed)

- **Setup:** same arrivals and admission cut-off as the base day. The hard stop is moved far out with an overtime
  overlay (e.g. `overtime: 12` hours), so every admitted truck can complete.
- **Measures, uncensored:**
  - clearance time;
  - total time on site;
  - turnaround of every truck;
  - throughput to clearance.
- **Use:** removes censoring entirely, and so separates "faster for completed trucks" from "clears the same demand
  faster".
- **Limitation:** an unlimited working day is an analysis device, not an operating plan. Real overtime limits must
  come from the silo manager.

## 6. Acceptance tests (to write first, hand-traced, before implementation)

1. **Outcome classification:** every generated truck has exactly one outcome; counts add up to arrivals (scripted
   day with completed, unfinished and turned-away trucks).
2. **RMST:** a three-truck hand case with one unfinished truck. RMST equals the hand value, and equals today's
   incl-unfinished mean when nobody is turned away.
3. **Completion rate and survivorship:** two policies on identical arrivals where the completed-only mean ranks them
   opposite to RMST (constructed case). The report must show both.
4. **Backlog integral:** trucks-on-site ∫ dt equals the hand value; equals the sum of RMST × arrivals for the same
   horizon.
5. **Starvation bounds:** a censored truck below the threshold counts in the upper bound, not the lower.
6. **Stall truncation:** a stalled run is flagged `truncated_by_stall`, its cancelled arrivals counted as
   `not_arrived`, and paired analysis reports the pair as excluded, not silently dropped.
7. **Demand identity:** paired arms have identical arrival hashes; a deliberately altered arrival list is detected.
8. **Drain-down:** with long overtime, unfinished = 0 and RMST = completed mean = full mean.
9. **Backward compatibility:** existing fields unchanged, version-tolerant fingerprint identical, both evidence
   packages reproduce unchanged.

## 7. Decisions requiring operational input

- **D1 Horizon and end of day:** do unfinished trucks stay overnight (carry-over), go home, or are they served in
  overtime? This sets T_end, the backlog meaning and whether drain-down is realistic.
- **D2 Overtime limits:** how long a drain-down may realistically run.
- **D3 Starvation threshold:** what waiting time management regards as unacceptable, possibly per commodity
  (today: 120 min, a reporting default).
- **D4 Fairness criterion:** which matters most for this silo: the longest waits, completion rate per commodity, or
  overtaking? Decides the primary fairness measure.
- **D5 Lost demand:** whether turned-away trucks, or trucks deterred by queues, are lost business. Per CLAUDE.md
  lost demand is unknown unless supported, so no revenue inference is made.
- **D6 Commodity priorities:** whether any commodity (e.g. soybeans) has a contractual or operational priority. Only
  then can an intervention such as overtaking limits be evaluated.
- **D7 Queueing rules** (the prerequisite for any dispatching intervention): the actual order of service at each
  stage (connects to O2, O10 and O11 in the sampler-access review).

## 8. What this means for existing results (no file changed)

- The Paper 2 baseline's completed-only turnaround comparisons overstate the policy differences where unfinished
  counts differ (C1). Its export also reports completed and unfinished trucks per cell; the incl-unfinished means
  exist in `runs.json` as KPI `unload.mean_turnaround_incl_unfinished_min`. A future write-up should lead with RMST
  and completion rate.
- **Fairness (soybeans worse under feasible-first):** the direction is supported by mixed waits and overtakes. The
  magnitudes are lower bounds for unfinished trucks (C2-C4).
- **Stalled runs** (2 in `paper2-v1` EV-S2) compare truncated populations (C7). They are already reported separately
  as operational outcomes.
