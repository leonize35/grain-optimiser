# Engine interfaces — contracts to agree before routing, reservations and changeovers are built

Status: **DRAFT for review.** Only the storage bin (§5) is implemented so far. Everything else here is a contract: who asks whom for what, what is returned, and what must always hold. Rules referenced as R1–R7 are in DOMAIN_DECISIONS.md.

## 0. How a decision flows

```
event (arrival, service done, transfer done, space freed)
   └─> Dispatcher.reconsider()
         for each pending Request, in Policy order:
            plans = RoutePlanner.candidates(request, state)        # physically possible, statically compatible
            for plan in plans (planner's preference order):
               delay = ChangeoverPolicy.required(plan, state)      # minutes before grain may move
               result = ReservationLedger.try_reserve(plan)        # all-or-nothing
               if result is a Reservation: schedule start / changeover / completion; next request
               else: remember result.reasons for this request      # explainable "why waiting"
         stop when a full pass reserves nothing
```

Policies (FIFO, feasible-first, commodity batching) only decide the **order** of requests and whether a later request may overtake an earlier blocked one. They never bypass the ledger.

## 1. Requests (what is waiting)

| Request | Raised when | Needs |
|---|---|---|
| `TruckServiceRequest` | A truck reaches a step (sample, weigh_in, tip, …) | A station unit; for `tip`: pit space (R2), a graded result if required (R4); a place in the next area (R5) |
| `IntakeTransferRequest` | A pit holds a lot | A route pit → bin: segment slots (R1), bin incoming reservation (R7), changeover (R3) |
| `LoadTransferRequest` | A loading truck is at the load point | A route bin → load point: bin outgoing commitment (R7), segment slots, the load point |

Each request has a stable id, a creation time and a sequence number for deterministic ordering.

## 2. `RoutePlanner`

```python
class RoutePlanner(Protocol):
    def candidates(self, request: Request, state: PlantState) -> list[RoutePlan]: ...
```

- Uses only the configured graph (compiled once per configuration; `config.routes.build_routes` today).
- Returns plans in preference order (configurable later: fewest changeovers, preferred bin, shortest path).
- Filters out plans that are statically impossible: no physical path, or a bin never allowed for this commodity and grade. Dynamic availability is the ledger's job.

`RoutePlan`: ordered equipment ids; source (pit lot or bin); destination (bin or load point); commodity; grade; kilograms requested (may be clipped to available bin space, giving a partial transfer).

## 3. `ReservationLedger` (atomic whole-route reservation)

```python
class ReservationLedger(Protocol):
    def try_reserve(self, plan: RoutePlan | TruckStepPlan, now: int) -> Reservation | Blocked: ...
    def release(self, reservation_id: str, now: int, outcome: Literal["completed", "cancelled", "failed"]) -> None: ...
    def check_invariants(self) -> list[str]: ...
```

Claims it manages, all checked first and then all taken, or none taken:

| Claim | Owner | Capacity unit |
|---|---|---|
| Segment stream slot | conveyor or elevator | `max_concurrent_feeds`, commodity lock (R1) |
| Pit space | hopper | kilograms (R2) |
| Bin incoming / outgoing | storage bin | kilograms (R7, implemented) |
| Station unit | sampler, grader, weighbridge, load point | trucks |
| Area place | staging area | trucks (R5) |

Guarantees:
- **All-or-nothing:** a refused `try_reserve` leaves no trace (tested by comparing the full ledger state before and after).
- **Release is total:** completion, cancellation and failure all free every claim of the reservation, and partial transfers release unused bin space.
- **No double allocation:** no claim exceeds its capacity at any instant.
- **Deadlock:** circular waits are prevented by the R5 policy or reported. They are never silent.

`Blocked.reasons` is a list of `(code, equipment_id, detail)`. Codes: `NO_PHYSICAL_ROUTE`, `EQUIPMENT_BUSY`, `COMMODITY_LOCK`, `MERGE_PATH_DIFFERS`, `PIT_SPACE`, `BIN_NOT_ALLOWED`, `BIN_INCOMPATIBLE`, `BIN_FULL`, `STOCK_SHORT`, `GRADE_PENDING`, `AREA_FULL`, `OUT_OF_SERVICE`. These feed the "why is this truck waiting" view.

## 4. `ChangeoverPolicy`

```python
class ChangeoverPolicy(Protocol):
    def required(self, plan: RoutePlan, state: PlantState) -> ChangeoverNeed: ...
```

- Looks up each segment's last commodity and grade against the R3 matrix (most specific rule wins).
- Returns per-segment minutes, plus the route total under A5 (parallel, i.e. the maximum).
- Configuration validation calls the same lookup for every commodity pair that can meet on shared equipment, so a missing rule is caught before any run.

## 5. Storage bin — implemented (`silo_engine.domain.storage`)

`StorageBin` with `reserve_incoming`, `receive`, `release_incoming`, `reserve_outgoing`, `dispatch`, `release_outgoing`, `reassign`, `set_in_service`, `check_invariants`, and read-only state: tonnage, fill fraction, identity, free space, available stock. Refusals return reason codes and change nothing. `MixingRules` implements R4 grade mixing.

## 6. Monitoring (independent checks)

Every claim and release is written to an event log: time, reservation id, claim, kilograms, commodity, grade. A separate checker replays the log, without engine code, to verify material balance, segregation, capacity, sample-to-truck identity and completion consistency (CLAUDE.md §6).

## 7. Build order once this is agreed

1. Truck stations with unlimited areas (R5 default) and the dispatcher skeleton with FIFO and feasible-first; hand-traced scripted tests.
2. Pit model (R2: `full_load_space`, `empty_pit`) and intake transfers with exclusive segments (R1 default) and bin reservations.
3. Changeover matrix (R3) and its configuration validation.
4. Concurrent feeds (R1 `max_concurrent_feeds` > 1) with rate sharing and rescheduling.
5. Grades end to end (R4).
6. Finite areas and blocking (R5).
7. Hours, cut-off and carry-over (R6).
