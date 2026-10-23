# Queue-policy architecture (step 14)

Status: designed, then implemented and verified (2026-10-23); results in §8. Scope: a common interface for queue policies and per-site
and per-experiment policy selection. **No new scheduling intervention:** no bounded overtaking, pit reservation,
adaptive scheduling or dynamic bin allocation.

## 1. Audit of the existing policies

### 1.1 Python engine (`src/silo_engine/sim/dispatcher.py`)

The dispatcher keeps every waiting request in one list. Each request belongs to a queue group: `sample`, `grade`,
`weigh`, `tip`, `load`, `move` or `intake`. One pass works like this:

1. Sort all waiting requests by **position** = (order key, submission sequence). The order key is the submission time
   (queue entry). The exception is `intake`, whose order key is the age of the pit's oldest lot.
2. Walk the sorted list. For each request:
   - Under `strict_fifo`, if an earlier request *of the same group* already failed in this pass, mark the request
     `QUEUE_ORDER` and skip it.
   - Otherwise call its `attempt` callable. The engine decides physical feasibility and reserves resources
     atomically.
3. On the first success, remove the request and log an overtake for every still-waiting request of the same group
   with an earlier position. The pass ends, and `reconsider` starts a new pass.
4. On failure, store the reasons. If the group is `strict_fifo`, the group is now blocked for this pass.

| Name | Meaning | Prototype equivalent |
|---|---|---|
| `strict_fifo` | **Strict global FIFO.** Only the earliest waiting request of the group may start. A blocked head holds back the whole group, even if a later request could use an idle parallel unit, such as another hopper. | `tip: "fifo"` (tries only the queue head) |
| `feasible_first` | **Work-conserving feasible-first FIFO.** Requests are tried in queue order, and the first one that can start does. A unit never stays idle while a waiting request could use it. | `tip: "feasible"`; `weigh: "fifo"` and `transfer: "fifo"` (both scan the whole queue) |

The policy is a **run argument**: `TruckFlowModel(policy=...)`, as one name or a mapping per group, and
`run_experiment(policy="feasible_first")`. The site's `policies` field (prototype format) is **ignored by the Python
engine**. Discrepancy: the prototype's default for `policies.tip` is `"fifo"` (strict), while `run_experiment`'s default
is `feasible_first` everywhere. Site A's configuration sets `tip: "feasible"`, so the two agree for Site A. This step
does not change it (see §4).

### 1.2 Prototype BATCH and the other prototype rules (`reference/prototype_js/silo_engine_v0.2.0.js`, not ported)

- **`policies.tip = "batch"`** (`dispatchTip`): hopper-led. Each free hopper, in configuration order, takes the earliest
  truck whose commodity matches the hopper's current (or last) commodity, otherwise the earliest truck that fits. The
  prototype mixes physical checks (`hopperFits`: lane free, commodity accepted, route exists, no mixing, space) into
  this policy. Under the new interface, the engine keeps those checks. The policy would only *reorder* candidates
  ("matching a free hopper's commodity first, then queue order") using read-only hopper state. That is not exactly
  the prototype's hopper-major loop, because the hopper choice stays with the engine (prefer the pit already holding
  the grain). The difference must be confirmed against the prototype before porting.
- **`policies.transfer = "batch"`**: a **route-choice** rule (prefer routes without a changeover over routes to bins
  already holding the grain). This is not a queue-order rule. It belongs with the engine's route preference (and
  near "dynamic bin allocation"), which is out of scope.
- **`policies.transfer = "load_first"`, `policies.weigh = "load_first" / "out_first"`**: priority orderings. These would
  be queue policies that reorder by request attributes (activity, direction). Not ported; the interface supports them.

## 2. The common interface (`src/silo_engine/sim/queue_policy.py`)

```python
@dataclass(frozen=True)
class WaitingRequest:          # read-only snapshot handed to a policy
    request_id: str
    group: str
    position: tuple[int, int]  # (order key, submission sequence): queue order at this stage
    queued_at: int             # entered this queue (ms)
    overtaken: int             # queue-order overtakes so far (dispatcher count)
    last_reasons: tuple[WaitReason, ...]
    info: Mapping[str, object] # facts from the engine: truck id, gate arrival sequence, commodity, grade, activity

@dataclass(frozen=True)
class Recommendation:
    order: tuple[str, ...]          # request ids to try, in this order; ids left out are held back this pass
    stop_at_first_blocked: bool     # True: once one fails, no later recommended request may start this pass

class QueuePolicy(Protocol):
    name: str
    def recommend(self, group: str, waiting: Sequence[WaitingRequest], now: int) -> Recommendation: ...
```

- `StrictFifo.recommend` returns all requests in position order, with `stop_at_first_blocked=True`.
- `FeasibleFirst.recommend` returns the same order, with `stop_at_first_blocked=False`.

**The dispatcher** asks each group's policy for a recommendation on every pass. It merges the per-group orders into one
attempt sequence (a k-way merge on the position of each order's next request, so that for position-ordered
recommendations the sequence is exactly today's global sort). It then attempts requests as before. A request a policy
leaves out gets the reason `POLICY_HOLD`. A recommendation naming an unknown or duplicate id is an error.

**Responsibilities stay separate.** The policy sees only the snapshot and returns an order. It cannot reserve, start or
change anything. Physical eligibility, grain compatibility, route reservation, capacity and changeovers stay in the
engine's `attempt` callables and the reservation ledger.

## 3. Policy selection

- New optional site setting (`SiteConfig.queue_policies`, Python names):
  `{"default": "feasible_first", "groups": {"tip": "strict_fifo"}}`. Group names and policy names are validated.
- Precedence: **explicit run or experiment argument > site `queue_policies` > built-in default `feasible_first`.**
  `TruckFlowModel(policy=None)` and `run_experiment(policy=None)` resolve through this chain. Every existing call passes
  a policy explicitly, or uses the old default on sites without `queue_policies`, so behaviour is unchanged.
- The resolved policy per group is recorded in the result and in the experiment metadata.
- The prototype `policies` field stays as it is (validated, not used by the engine). This discrepancy remains flagged
  (§1.1); mapping it needs the prototype `fifo` meaning per stage settled.

## 4. Reporting for the six domain decisions (reporting only; existing metrics keep their definitions)

1. **Gate arrival and queue entry.** Per truck: `arrival_seq` (gate order) and `queue_seq` per step (the dispatcher's
   submission sequence, i.e. queue-entry order). FIFO applies at the configured queue stage (per group). Fairness by
   gate arrival is reported separately: `hopper_admitted_ahead_by_later_arrivals` counts later gate arrivals that
   started tipping before this truck. `overtaken_in_queue` counts queue-order overtakes without the gate-arrival
   filter. `overtaken_by_later` is unchanged.
2. **Feasible versus infeasible overtakes** (optional split of `overtaken_by_later`, which is unchanged):
   - `overtaken_feasible`: the overtaker obtained equipment the waiting truck is configured to be able to use. For a
     hopper, that means it accepts the commodity and has an intake route for the grain. For a load point, a load
     route from a bin assigned to the commodity. For a station lane, the lane serves the step. Areas and grading count
     as feasible.
   - `overtaken_infeasible`: the rest.

   This is a configuration (static) test. It does not say whether the waiting truck could have started at that
   instant, for example with incompatible grain still in the pit.
3. **Two distinct policies:** `strict_fifo` (strict global FIFO) and `feasible_first` (work-conserving feasible-first
   FIFO), both selectable. The case-study description does not settle head-of-line blocking at parallel hoppers;
   tests document both behaviours.
4. **Ties.** Simultaneous arrivals keep the arrival-script order. Generated arrivals sort by (time, backlog first,
   activity, truck id). The calendar keeps scheduling order for equal times. `arrival_seq` records the result.
5. **Pre-opening waiting:** `pre_opening_wait_min` is time held at the gate until it opened (before opening, or after
   the admission cut-off until the next day). `operational_wait_min` = total − pre-opening. `total_waiting_min` is
   unchanged. Limitation: overnight waiting *on site* by carried-over trucks counts as operational.
6. **Right-censoring:** `wait_censored` (true for trucks unfinished at termination; their waits are lower bounds). Per
   commodity, completed-only statistics (`completed_mean/median/p95/max_wait_min`) are kept apart from censored ones
   (`censored`, `censored_mean_wait_min`, `censored_max_wait_min`). Turned-away trucks are in neither group. Existing
   mixed statistics are unchanged.

## 5. Affected files

| File | Change |
|---|---|
| `sim/queue_policy.py` (new) | `WaitingRequest`, `Recommendation`, `QueuePolicy`, `StrictFifo`, `FeasibleFirst`, registry |
| `sim/dispatcher.py` | uses policy objects. Same pass structure and overtake log; `submit` takes optional `info` and returns the sequence number |
| `sim/truck_flow.py` | policy resolution; passes truck info at submit; new reporting fields (no change to records, trace or transfers) |
| `config/schema.py`, `config/rules_validation.py` | optional `queue_policies` |
| `experiments/runner.py` | `policy=None` resolves through the site; metadata records resolved policies; new figures |
| tests | new `test_queue_policy.py`; existing tests unchanged |

## 6. Invariants

- **P1** A policy cannot change simulation state. It receives frozen snapshots and returns an order.
- **P2** Only recommended requests are attempted. Every start goes through the engine's `attempt` (atomic reservation).
- **P3** One start per pass, then a fresh pass (unchanged).
- **P4** The overtake log is measured by queue position, independent of the policy.
- **P5** Determinism: the attempt sequence is a function of positions and the policy outputs only.
- **P6** Equivalence: for `strict_fifo` and `feasible_first` the engine's decisions are byte-identical to step 13.
  The check is the fingerprint of trace, transfers, loads, records, grain and summaries over 16 Site A runs.
- **P7** A recommendation with an unknown or duplicate id raises an error.

## 7. Regression tests

- The 231 existing tests, unchanged.
- The engine fingerprint (16 runs) compared with the step-13 baseline.
- New tests:
  - interface tests: order, hold, stop-at-first-blocked, invalid recommendations, a custom reordering policy, no
    mutation;
  - equivalence: argument, per-group mapping and site setting give identical decisions;
  - precedence;
  - metadata;
  - multi-hopper head-of-line: under `strict_fifo` a later truck waits while a hopper it could use is idle, under
    `feasible_first` it does not;
  - the six reporting decisions on hand-traced cases;
  - prototype selftests 12/12.

## 8. Results (step 14)

**As implemented:** as designed, with one addition. Policies may be passed as objects in the run's policy
mapping (used by tests); `TruckFlowResult.queue_policies` and `.policy_source` record what was used.

**Tests run:**
- `pytest -q`: 253 passed. These are the 231 existing tests, unchanged, plus 22 in `tests/test_queue_policy.py`.
- `tools
un_prototype_selftests.ps1`: 12/12, prototype engine sha256 unchanged.

**Equivalence:**
- **Engine fingerprint** (16 Site A runs: 2 policies × 2 demand levels × 4 seeds): byte-identical to step 13, both
  with the policy as a run argument and with the same policy set through the site's `queue_policies`.
- **Configuration hashes** of all golden configurations: unchanged (the unset setting is left out of the hash).
- **`docs/audit/FAIRNESS_BASELINE.md`:** regenerated byte-identical.
- **Speed:** the fingerprint batch takes about 7.4 s, against 6.8 s before (policy snapshots built on every pass).

**Fault injection** (13 faults in the new code, all detected):
- strict FIFO not stopping;
- groups merged without positions;
- held requests attempted;
- invalid recommendation accepted;
- site setting ignored;
- site setting beating the argument;
- config hash including the unset setting;
- feasible split ignoring the hopper commodity;
- gate fairness ignoring arrival order;
- pre-opening wait zero;
- censored statistics including completed trucks;
- queue count filtered by arrival;
- arrival sequence off by one.

Two of these (the cross-group merge and the off-by-one in the facts shown to policies) went undetected at first.
Tests were added for both. The merge fault was also caught by the fingerprint (13 of 16 runs differ).

**Open:**
- The prototype `policies` field is still ignored by the engine.
- BATCH, `load_first` and `out_first` are not ported. Prototype BATCH is a hopper-led loop, so a port needs a
  differential check (§1.2).
- The feasible/infeasible split is a configuration test only.
- Overnight waiting on site counts as operational.

## 9. Settling the prototype policies (step 15)

### 9.1 Final policy architecture

| Layer | Where | Role |
|---|---|---|
| **Policy definitions** (the only implementation) | `sim/queue_policy.py`: `StrictFifo`, `FeasibleFirst` | Recommend an order from a read-only snapshot |
| **Authoritative configuration** | `SiteConfig.queue_policies` (`default` + per group), Python names | Per silo configuration |
| **Run / experiment selection** | `TruckFlowModel(policy=...)`, `run_experiment(policy=...)` | Overrides the site; recorded with `policy_source` |
| **Prototype names** | `policies` field (`tip`/`weigh`/`transfer`) | Validated for parity; **not applied** |
| **The one translation** | `queue_policy.from_prototype` + `PROTOTYPE_EQUIVALENTS` table | Prototype names → queue policies; raises for rules not ported |
| **Physical feasibility** | engine `attempt` callables + reservation ledger | Eligibility, compatibility, routes, capacity, changeovers |

The prototype engine stays a frozen reference (`reference/prototype_js`, sha256 unchanged), not a second
implementation. The equivalence tests tie the translation table to its decisions.

**Translation table** (from the prototype source):

| Prototype | Prototype behaviour | Queue policy |
|---|---|---|
| `tip: "fifo"` (prototype default) | `dispatchTip` tries only the queue head | `tip: strict_fifo` |
| `tip: "feasible"` | scans the whole tip queue | `tip: feasible_first` |
| `weigh: "fifo"` | `dispatchPool` scans the whole queue for a fitting weighbridge | `weigh: feasible_first` |
| `transfer: "fifo"` | intake lots and loading trucks by age, whole list scanned | `intake`, `load`: `feasible_first` |
| sampling, grading (fixed) | whole queue scanned | `sample`, `grade`: `feasible_first` |
| (none) | no waiting areas in the prototype | `move`: `feasible_first` |
| `tip: "batch"`, `transfer: "batch"`, `transfer: "load_first"`, `weigh: "load_first"`, `weigh: "out_first"` | see §1.2 | **not ported**: `UnsupportedPrototypePolicy`, never approximated |

**Behaviour preserved:**
- The engine still does not apply the prototype field.
- When a configuration *sets* `policies` and they differ from what the run uses (or have no equivalent), the run's
  assumptions say so: "The configuration's prototype policies (...) are not applied; this run uses ...".
- All 17 golden configurations set `tip: "feasible", weigh: "fifo", transfer: "fifo"`. That translates to exactly
  what they run today, so they get no note and their experiment metadata is unchanged.

### 9.2 Equivalence tests (`tests/test_policy_equivalence.py`, golden `tests/golden/policy_equivalence.json`)

`python tools/policy_equivalence.py` runs the unmodified prototype in headless Edge on 14 scenarios and stores
its traces. The Python engine runs the same configurations, the same trucks (opening backlog with identical ids,
commodities and tonnes) and the translated policies. Every admission decision is compared: weighbridge starts,
tipping (truck, hopper), transfers (time, commodity, tonnes, route), loading (truck, route) and departures.

- **Layouts:** one hopper; two independent lines (one hopper yellow-only, slow and fast tipping); two hoppers
  sharing a conveyor, one opening with grain; a two-lane weighbridge in and out; loading and intake sharing an
  elevator with opening bin stock.
- **Policies:** each layout under prototype `tip: fifo` and `tip: feasible`, with `weigh`/`transfer: fifo`. The two
  tip policies decide differently in at least 3 layouts, so the comparison is not vacuous.
- **Durations** are fixed and hoppers hold 1000 t, so the prototype's stepwise hopper level and this engine's
  continuous drain (A3) cannot affect admission.

### 9.3 Results

- **Decisions:** 8 of 10 comparable scenarios match the prototype in every decision. The remaining 2 differ only by
  the equal-age tie-break (§9.4). With the prototype's tie-break substituted inside the test, they also match in
  every decision.
- **Rules not ported:** the 4 scenarios with prototype rules lacking an equivalent are refused by the translation
  (`UnsupportedPrototypePolicy`).
- **Test suite:** `pytest -q`: 272 passed, 2 expected failures (the strict xfail marks for the tie-break scenarios).
- **Unchanged behaviour:**
  - engine fingerprint (16 Site A runs) byte-identical, with the policy as an argument and from `queue_policies`;
  - configuration hashes unchanged;
  - `FAIRNESS_BASELINE.md` regenerated byte-identical.
- **Fault injection:** 7/7 detected (each table entry flipped, BATCH silently approximated, prototype default
  changed, note suppressed).
- **Prototype selftests:** 12/12.

### 9.4 Remaining differences between the prototype and this engine

1. **Equal-age intake tie-break.** When two pits' head lots have exactly the same age:
   - the prototype transfers from the pit listed first in the configuration;
   - this engine transfers from the pit whose transfer request was queued first.

   The difference can cascade: in the shared-conveyor `tip=feasible` scenario yellow trucks tip 9 min later. It
   needs exactly equal lot ages, so it arises with fixed durations. In the 16 stochastic Site A runs, 0 of 951
   intake starts involved such a tie. **Not changed; needs approval.**
2. **The prototype `policies` field is not applied.** Honouring it would change runs whose configuration sets
   `tip: "fifo"`, or omits `policies` (the prototype's default is strict FIFO at the hopper). It would make BATCH
   configurations fail instead of running feasible-first. **Not changed; needs approval.**
3. **Not ported:** prototype `tip: "batch"`, `transfer: "batch"` (a route-choice rule), `transfer: "load_first"`,
   `weigh: "load_first"`, `weigh: "out_first"`.
4. **Known modelling differences outside queue policy** (unchanged, documented earlier):
   - continuous versus stepwise hopper drain (A3), which affects hopper space;
   - explicit changeover rules required (R3), where the prototype treats a missing value as 0;
   - Python-only waiting areas and blocking (R5).
