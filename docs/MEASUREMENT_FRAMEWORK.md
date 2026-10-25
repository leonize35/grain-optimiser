# Performance measurement framework: revised definitions (for review; nothing implemented)

Status: revision of `docs/MEASUREMENT_AUDIT.md` §3–§6 after the user's review (2026-10-25). The audit's §1–§2 findings
(C1–C10) stand. This document replaces its proposed reporting design, statistics, drain-down and acceptance tests.
No engine, metric, configuration or evidence file was changed. `paper2-v1`, `paper2-ext-sampling-v1` and their
manifests are untouched. **No dispatching intervention** is proposed until the actual queueing rules are verified.

## 0. Corrections to the audit

| # | Audit said | Problem | Revision |
|---|---|---|---|
| R1 | "RMST: mean over all arrived trucks of min(time on site, T_end − arrival) … unbiased" | Each truck is cut off at its own bound T_end − aᵢ, so this is **not** a restricted mean survival time (that needs one common τ). It is an exact description of the run, not an estimate of eventual turnaround. For trucks still on site it is a **lower bound**, and its bias grows with the number unfinished and the lateness of arrivals | Renamed **mean observed time on site within the horizon** (K6b), an occupancy measure. A proper RMST is defined separately (K7) |
| R2 | Turned-away trucks enter RMST "to their send-away time" | That treats being sent away as an ordinary exit with a short stay. A policy that sends trucks away early would look faster | Turned-away is a **separate outcome** (K3) and a **competing event** in K7, never a completion |
| R3 | Test 4: "backlog integral = RMST × arrivals" | It holds only for the per-truck-truncated occupancy, not for any RMST | The identity is restated for occupancy (§2, K6) |
| R4 | Sensitivity analysis: "a stalled arm censored at the stall time" | Treats a failed simulation as valid partial data | Dropped. A failed run is a **failure outcome**, never data for KPI comparison (§3) |
| R5 | Drain-down: "overtime 12 h, so every admitted truck can complete" | Not guaranteed: full or incompatible bins, operator shifts ending, outages, gridlock, trucks held at the gate | Clearance must be **verified per run** and the operating assumptions stated (§4) |
| R6 | "Primary turnaround comparison" (a single measure) | One metric can rank policies wrongly (C1) | A **set** of complementary measures; no single one decides the best policy (§2.3) |

## 1. Population and outcomes

**Intended population.** The trucks generated (or scripted) for a run are fixed **before** the run, from the seed and
the demand inputs. Let N be their number, and aᵢ the scheduled gate arrival of truck i. Under common random numbers
every policy arm receives the same N trucks with the same aᵢ, checked by an arrival hash.

**Horizon.** H is the last day's hard stop (close + overtime). The admission cut-off is c ≤ H.

**Outcomes.** Every intended truck in a **valid** run has exactly one outcome:

| Outcome | Definition | Engine today |
|---|---|---|
| `completed` | Departed at Dᵢ ≤ H after its last step | `departed` set |
| `unfinished_on_site` | Admitted, still on site at H | `unfinished`, `admitted` set |
| `unfinished_at_gate` | Arrived but never admitted (e.g. late arrival held for the next day on the last day) | `unfinished`, `admitted` is None. **Not distinguished in KPIs today** |
| `turned_away` (reason) | Sent away at Rᵢ without finishing. Reasons today: "arrived after the admission cut-off" and "still on site when service stopped". **Grading rejection** exists as a config field (`reject`) but the engine does not use it | `turned_away`, `turned_away_at` |

**Failed runs** (stall, rule violation or grain imbalance) have no valid outcomes. For diagnosis each intended truck is
labelled `completed_before_failure`, `affected_by_failure` (on site or at the gate at the failure time), or
`not_arrived_due_to_failure` (aᵢ after the failure time). Records exist today only for trucks that arrived, so the
last label must be derived from the intended list.

**Time origin.** Time on site counts from gate arrival aᵢ, as today. Because the current turnaround includes waiting
before opening, every time measure is also reported from **admission** (operational time). Which one management uses
is question Q-M5.

## 2. Revised KPI definitions

Every KPI is reported per activity (unload, load, weigh) and per commodity. For Ventersdorp it is also reported per
silo (A, B) and site total (§5). All are computed from valid runs only.

### 2.1 Measures

**K1 Completed turnaround, completed trucks only.**
- Tᵢ = Dᵢ − aᵢ over completed trucks: mean, median, p90, max.
- Also from admission.
- Always printed with n_completed and K2 beside it, and labelled "completed trucks only".
- Never used alone to rank policies.
- This is the existing `mean_turnaround_min`, unchanged.

**K2 Completion rate.**
- n_completed / N, with the full outcome split (`completed` / `unfinished_on_site` / `unfinished_at_gate` / `turned_away`) beside it.
- Paired across arms by seed.

**K3 Turned-away trucks** (a separate outcome, not a departure).
- Count and share of N, per reason.
- Time on site before being sent away, Rᵢ − aᵢ (count, mean, max).
- Tonnes not handled.
- Never included in K1. Not interpreted as lost demand (D5).

**K4 Tonnes handled.** Three figures, stated together:
- (a) tonnes received into pits or bins by H (`received_t`);
- (b) tonnes of completed unload trucks;
- (c) tonnes loaded out by completed load trucks.

(a) − (b) is grain tipped by trucks not yet weighed out (work in progress). (a) must tie to the grain balance
(conservation invariant).

**K5 Unfinished backlog at H.**
- Trucks and tonnes, split on-site and at-gate.
- On-site trucks split by where they wait (queue for sampler, incoming weighbridge, hopper, outgoing weighbridge, …).
- Elapsed time on site so far for each unfinished truck, labelled **censored (lower bound)**.

**K6 Truck-hours on site** (occupancy).
- Let Eᵢ be the exit time (Dᵢ or Rᵢ; ∞ if none) and N(t) the number of trucks with aᵢ ≤ t < Eᵢ.
- (a) Truck-hours O = ∫₀^H N(t) dt = Σᵢ oᵢ with oᵢ = min(Eᵢ, H) − aᵢ (exact by exchanging sum and integral; every truck in a valid run has aᵢ ≤ H).
- (b) Mean observed time on site within the horizon = O / N.
- Split O into gate waiting (before admission), operating hours and, in multi-day runs, overnight hours (Q-M1, Q-M3).
- Interpretation:
  - O measures congestion borne by drivers;
  - O / N is **not** an estimate of turnaround;
  - O falls when trucks are sent away, so it is never read without K2 and K3.

**K7 Restricted mean time to completion, RMST(τ)**, with a fixed, pre-declared τ (Q-M4).
- **Cohort with full follow-up:** 𝒜_τ = { i : aᵢ ≤ H − τ }. Every cohort truck is observed for at least τ, so no censoring occurs before τ.
- **Per truck:** Xᵢ = min(Tᵢ, τ) if completed; Xᵢ = τ if turned away or unfinished. A truck sent away never completes; it counts as not completed for the rest of τ.
- **Measure:** RMST_C(τ) = (1/|𝒜_τ|) Σ Xᵢ = ∫₀^τ (1 − F_C(t)) dt, where F_C is the empirical cumulative incidence of completion in the cohort.
- **Reported with it:**
  - F_C(τ), the share completed within τ;
  - F_R(τ), the share turned away within τ;
  - |𝒜_τ| and the number of trucks outside the cohort.
- **Consistency checks** (tests):
  - with no turn-aways and τ ≥ the cohort's longest Tᵢ, RMST_C(τ) equals the cohort's completed mean;
  - Xᵢ ≤ τ always;
  - F_C(τ) + F_R(τ) + (share neither) = 1.
- **Why a cohort and not Kaplan-Meier:**
  - Truck i's censoring time, H − aᵢ, depends on the time of day, and congestion depends on the time of day. The independent-censoring assumption behind Kaplan-Meier and Aalen-Johansen is therefore doubtful.
  - The cohort needs no such assumption, but leaves out late arrivals. K5 and K6 cover those trucks.
  - A Kaplan-Meier version may be shown as secondary, with the assumption stated.
- Multi-day carry-over: τ is elapsed time. A τ crossing a night is flagged.

**K8 Commodity-level fairness** (and per silo for Ventersdorp). Per group:
- K2, K3, K7;
- the distribution of overtakes by later arrivals (all trucks, with unfinished trucks so far);
- starvation as **[lower, upper] bounds**: unfinished trucks below the threshold count as not starved in the lower bound and starved in the upper.

Disparity is reported as the spread between groups (max − min, and ratio) of K7 and K2. No single fairness index
decides; the criterion is D4.

**K9 Shared-resource diagnostics** (Ventersdorp: sampler, incoming weighbridge, outgoing weighbridge). Per resource:
- utilisation and time-average queue;
- waiting attributed to it, split by destination silo;
- **blocking time**: a truck has finished its service but holds the station or hopper because the next place is not free. It is derivable from step records (finished → next entry).

Blocking matters because a full queue at the outgoing weighbridge can hold trucks on the hoppers of **both** silos.
Diagnostic only; it does not rank policies.

### 2.2 Measures kept as they are

The existing fields (`mean_turnaround_min`, `mean_turnaround_incl_unfinished_min`, `received_t`, fairness tables) keep
their meaning, so existing results and packages reproduce. In reports, `mean_turnaround_incl_unfinished_min` is
renamed to "mean observed time on site (completed and unfinished; excludes turned-away)" and marked as a lower bound.

### 2.3 How policies are compared

- No single measure determines the best policy.
- A policy is reported as better on a measure only where the paired difference is clear after Holm adjustment within its family:
  - completion (K2, K3);
  - throughput (K4);
  - congestion (K5, K6);
  - time (K7, then K1);
  - fairness (K8).
- **Trade-offs** (better on one family, worse on another) are reported as trade-offs.
- K1 is always shown with K2. K6 is always shown with K3.

## 3. Failed (stalled or invalid) runs

1. **Population preserved.** N and the arrival hash come from the intended list, not from the trucks that happened to
   arrive.
2. **Failure is an outcome of the replication**, reported per arm and cell: count, type (stall, violation,
   imbalance), failure time, and the number of intended trucks not observed.
3. **No silent exclusion.** For every comparison the output states:
   - M replications planned;
   - k with a failure (by arm);
   - M − k complete pairs used.

   Estimates over complete pairs are labelled "conditional on both arms running".
4. **A policy with failures cannot be ranked best** on the remaining pairs. Its failure rate is reported as a result in
   its own right.
5. **No imputation and no partial use.** A failed run's KPIs are not used, not even censored at the failure time.
6. **Model defect or operating outcome.** A stall caused by an engine defect is fixed in the engine and all arms are
   re-run under a new engine version, never patched. A modelled physical gridlock (possible only under `detect_only`)
   may represent a real situation. How operators would resolve it is Q-M8. Until then it is treated as a failure.
7. **Code change needed:**
   - `experiments.runner.run_experiment` excludes failed replications today (`good = … status == "ok"`), and `paired` drops pairs. Both must report the counts above.
   - The evidence tools include truncated runs today; they must exclude them from KPI means and report them separately.
   - Existing packages are not rebuilt.

## 4. Clearance (drain-down) verification

An extended hard stop does **not** guarantee that every admitted truck finishes. In this engine a truck can stay
unfinished indefinitely when:
- no compatible bin has space (it can never tip);
- operator shifts end (labour-constrained steps stop);
- an outage covers the overtime;
- a gridlock occurs;
- it is held at the gate for the next day.

Procedure:

1. State the drain-down assumptions explicitly in the result:
   - overtime length O;
   - whether operators work through the overtime (an explicit staffing overlay, else the configured shifts apply);
   - equipment availability;
   - no admissions after the cut-off c.
2. Clearance population: trucks admitted by c.
3. **Verify** after the run that every admitted truck completed or was turned away for a stated reason.
   - If so, report clearance time = max Dᵢ − c and all times as uncensored.
   - If not, report **"not cleared within O h"** with each remaining truck's waiting reasons (from the dispatcher). Never report it as cleared.
4. A longer O may be tried up to a pre-declared maximum. A truck still unfinished then indicates a structural cause
   (e.g. no bin space), which is reported.
5. The drain-down is an analysis device, not an operating plan. Real overtime limits are D2.

## 5. Ventersdorp configuration in the framework

Confirmed (user, 2026-10-25): Silo A and Silo B are one integrated site with two subsystems sharing **one sampling
station**, **one dedicated incoming weighbridge** and **one dedicated outgoing weighbridge**, not interchangeable.

What this means for measurement:
- KPIs K1–K8 are reported per silo and for the site.
- K9 covers the three shared resources.
- The engine already enforces direction: `weigh_in` uses only `in` (or `both`) bridges. The Ventersdorp config will have no `both` bridge.
- **Per-silo attribution depends on routing.** A truck's silo is known today only once it reaches a hopper. Trucks unfinished or turned away before tipping have no silo unless the silo is decided at arrival or grading. Until V7 (gap analysis) is answered, per-silo K2, K3 and K5 carry an "unassigned" group.
- Per-silo reporting needs the equipment of each silo to be tagged. That is a small optional config field, added only with the Ventersdorp topology (V1). No Ventersdorp configuration is created until then. See `docs/ventersdorp/VENTERSDORP_GAP_ANALYSIS.md`.

## 6. Acceptance tests (written first, hand-traced; reviewed before any implementation)

| # | Test | Proves |
|---|---|---|
| T1 | Scripted day with each outcome (completed, unfinished on site, unfinished at gate, turned away after cut-off, turned away at service stop): counts sum to N | Outcome partition |
| T2 | Turned-away trucks are absent from K1 and present in K3 with reason and time on site | R2 |
| T3 | Staggered arrivals, one turned away: Σ oᵢ equals a hand-computed ∫ N(t) dt | K6 identity (R3) |
| T4 | τ cohort: a late truck is excluded; a turned-away truck counts τ; with no turn-away and τ large, RMST_C(τ) equals the completed mean | K7 consistency (R1) |
| T5 | Two arms, identical arrivals, built so the completed-only mean ranks them opposite to K2 and K7: the report shows all | Survivorship (C1) |
| T6 | A censored truck below the threshold is in the upper starvation bound, not the lower | K8 bounds |
| T7 | Stalled arm: N preserved, trucks after the stall `not_arrived_due_to_failure`, run's KPIs excluded, comparison prints "k of M failed", that arm not rankable | §3 |
| T8 | `run_experiment` and `paired` report failed counts, never dropping silently | §3.7 |
| T9 | Altered arrival list detected by the arrival hash | Demand identity (C6) |
| T10 | Drain-down: (a) clears, uncensored; (b) does not clear because a bin is full, reported "not cleared" with the reason; (c) does not clear because the operator shift ends | §4 (R5) |
| T11 | K4: (a) − (b) equals tipped-not-departed tonnes, and (a) ties to the grain balance | Tonnes consistency |
| T12 | Synthetic Ventersdorp-shaped site (shared sampler, `in` and `out` bridges, two subsystems): per-silo figures sum to the site, weigh-out never on the incoming bridge, blocking at the outgoing bridge recorded | §5, K9 |
| T13 | Multi-day carry-over: K6 split into operating and overnight hours | K6 split |
| T14 | Existing fields unchanged; version-tolerant fingerprint identical; `paper2-v1` (90/90) and `paper2-ext-sampling-v1` (105/105) rebuild checks pass | Backward compatibility |

## 7. Outstanding operational questions

The audit's D1–D7 remain open:
- D1 horizon and end of day;
- D2 overtime limits;
- D3 starvation threshold;
- D4 fairness criterion;
- D5 lost demand;
- D6 commodity priorities;
- D7 queueing rules.

New questions:

1. **Q-M1:** Where do trucks wait before admission? Does that time count as "on site" (inside the gate or on the public road)?
2. **Q-M2:** Which turn-away reasons actually occur at Ventersdorp: after the cut-off, end of day, rejection at grading, no bin space? Rejection at grading would need implementing.
3. **Q-M3:** Do unfinished trucks stay overnight? Should overnight hours count in truck-hours?
4. **Q-M4:** Which τ is meaningful to management for K7 (e.g. 2 h or 4 h)?
5. **Q-M5:** Is turnaround measured from gate arrival or from admission?
6. **Q-M6 (D7 for Ventersdorp):**
   - What is the order of service at the shared sampler and at each weighbridge: one queue across both silos, or priorities?
   - Where does a truck that has finished tipping wait for the outgoing weighbridge, and how many trucks fit there?
7. **Q-M7:** Are operators available during overtime?
8. **Q-M8:** If trucks gridlock physically, how do operators resolve it?
9. **Q-M9:** Do dispatch and weigh-only trucks share the weighbridge queues with receiving trucks, and with what priority?

## 8. Implementation sequence (only after this document and the tests are reviewed)

Each step follows the same cycle: failing test, minimal change, invariants, full suite, reproduction checks, commit.

1. **Outcomes (T1, T2):** per-truck outcome with the gate/site split and failure labels, derived from the intended list. New fields only.
2. **Occupancy (T3, T13):** truck-hours and mean observed time on site, with the gate, operating and overnight split.
3. **RMST (T4, T5):** RMST_C(τ) cohort, F_C(τ), F_R(τ); τ as a run parameter with no default until Q-M4 is answered.
4. **Tonnes and fairness (T11, T6):** tonnes consistency; fairness bounds and disparity per commodity.
5. **Run validity (T7–T9):** runner and paired comparisons report failures; arrival hash. The evidence tools gain these fields only for a **new, separately versioned** package.
6. **Clearance (T10):** clearance verification utility; no default changes.
7. **Ventersdorp (T12):** per-silo and shared-resource breakdowns, after the topology (V1) and routing (V7) answers.
8. **Reproduction (T14):** both existing packages reproduce unchanged.

No dispatching intervention (overtaking limits, priorities, reservation changes) is part of any step.
