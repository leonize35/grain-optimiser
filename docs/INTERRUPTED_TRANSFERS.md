# Interrupted transfers: equipment unavailable during a grain transfer (step 17)

Software-independent specification. Status: written before implementation, then implemented and verified (2026-10-23); results in §7.
Out of scope: random breakdown distributions, repair-time optimisation, stock adjustments, new scheduling strategies.

## 1. Audit: what the engine had before this step

| Concept | Representation before step 17 |
|---|---|
| In-transit grain | **None as a separate stock.** A transfer drains its pit continuously (A3); the bin receives the transfer's whole quantity when it completes. Until then the grain stays counted in the pit's lot, so mass balance holds at every instant. |
| Transfer progress | The pit's drain state: quantity, rate, amount drained so far (exact fraction of a kg). Loads: a fixed end time (setup + changeover + flow). |
| Reservations | Atomic ledger claims: route segments (commodity lock, feed limit, merge rule), bin incoming space, bin outgoing stock, lanes. Held until released at completion (plus clear time). |
| Equipment availability | **Not modelled.** All equipment is always available. |
| Interruption events | **None.** A transfer, once started, always completes. |

## 2. Inputs (configuration)

`outages`: a list of deterministic, scheduled periods during which one piece of transfer equipment is unavailable:

```json
"outages": [{"equipment": "E1", "day": 1, "start": "09:30", "end": "10:15"}]
```

- `equipment`: any equipment that can be an intermediate segment of a grain route (a conveyor, a bucket elevator,
  a reclaim conveyor, ...). Not hoppers, bins, load points or truck stations. Validated against the configured
  network; no equipment names are built in.
- `day` (default 1), `start` (required), `end` (optional: missing means "not before the end of the run").
- Periods of the same equipment must not overlap.

## 3. Events

| Event | Calendar priority | Effect |
|---|---|---|
| `EQUIPMENT_DOWN(e)` at `start` | CONTROL (after completions at the same instant, before arrivals) | `e` becomes unavailable; every active transfer or load whose route contains `e` is **suspended** (§4) |
| `EQUIPMENT_UP(e)` at `end` | CONTROL | `e` becomes available; every suspended transfer or load whose route has no other unavailable equipment **resumes** |

A transfer that completes at exactly the `start` instant completes first, because completions have priority.

## 4. State transitions of a transfer (intake) or load

```
              reserve route (all segments up)
 WAITING ─────────────────────────────────────► CHANGING_OVER ──(changeover time)──► FLOWING ──(all kg)──► COMPLETED ──(clear time)──► RELEASED
    ▲  route has unavailable equipment:           │      ▲                            │    ▲
    │  reason EQUIPMENT_DOWN, waits               │down  │up                     down │    │ up
    │  (or takes another route)                   ▼      │                            ▼    │
    └──────────────────────────────────────── SUSPENDED (route + bin reservation HELD) ─────┘
```

**Recovery rule "hold"** (the only rule in this step):
1. **Suspend.** On `EQUIPMENT_DOWN` the transfer stops flowing at once (its rate becomes 0); its completion is cancelled.
   - It **keeps every reservation**: all route segments with their commodity lock, its feed slot on shared
     segments, and the bin's incoming space (loads: the bin's outgoing stock and the load point).
   - No other grain can enter the uncleared route, because the segments stay locked to the suspended grain.
2. **Quantities while suspended:**
   - **delivered** (in the bin): 0. As before, a transfer is credited to the bin when it completes.
   - **in transit on the route**: the amount drained from the pit so far, which has left the pit but not arrived.
   - **remaining at source**: the rest of the transfer's quantity.

   All three are counted in the source pit's lot for mass balance until completion. In-transit is also reported
   separately.
3. **Resume.** On `EQUIPMENT_UP`, when no equipment on its route is still down, **the same transfer** continues from
   where it stopped. Same record, same route, same bin, same grain. No changeover is needed, because the route
   carried nothing else.
4. **Shared segments.**
   - A suspended stream keeps its feed slot (it counts towards `max_concurrent_feeds`), but takes no capacity
     share: streams still flowing on a shared segment get the capacity (A2 shares among *flowing* streams only).
   - When the stopped equipment is on a shared segment, every stream on it is suspended.
5. **Changeover phase.** If the route goes down during a changeover, the changeover time keeps elapsing. Flow starts
   at the later of the planned flow start and the restart (assumption I3).
6. **Loads.** The whole load clock (setup, changeover and flow) pauses while suspended and continues on restart.
   The stock leaves the bin when the load completes. The loading truck keeps the load point.
7. **New requests** cannot reserve a route containing unavailable equipment (reason `EQUIPMENT_DOWN`). They may
   take another configured route, or wait.
8. **End of the run.** A transfer still suspended stays suspended with its reservations held. The run reports it as
   unfinished, with its in-transit and remaining quantities; mass balance still holds. A stoppage with no end and
   waiting work that nothing can unblock is reported as a stall, as before.

**Trucks are not interrupted directly.** A truck finishes unloading when it finishes tipping, as before. A
suspended transfer stops draining its pit, so later trucks may wait for pit space or for an empty pit. That is the
physical consequence, not a special rule.

## 5. Invariants (checked by the flow audit, from records only)

- **I-A** No grain flows through equipment while it is unavailable: a stream's flowing time, minus its suspensions,
  never overlaps an outage of equipment on its route.
- **I-B** No route containing unavailable equipment is reserved during the outage.
- **I-C** Every suspension of a stream ends with a resume or with the end of the run, and only one is open at a time.
- **I-D** Conservation: global, per pit, per bin and per lot, exactly as in step 16. A suspended transfer is neither
  delivered nor lost.
- **I-E** A suspended stream's route stays reserved, so no other grain on its segments during the suspension (the
  existing segment checks).

## 6. Modelling decisions that need operational confirmation

- **I1 Hold, not release.** On a stoppage the route stays reserved and the transfer later resumes. Some sites may
  instead stop, empty or clean the route, credit what reached the bin, and release it. That would be a separate
  recovery rule; it needs a model of grain on belts and legs, which does not exist yet.
- **I2 Grain on the route is not credited to the bin** until the transfer completes. Physically, grain downstream of
  the stopped equipment may keep running into the bin. Without belt and leg contents this cannot be split, so it
  stays "in transit".
- **I3 A changeover in progress keeps elapsing during a stoppage.** The alternative is that cleaning pauses too.
- **I4 A load's setup also pauses** during a stoppage of its route. The load point itself is not stopped.
- **I5 Equipment upstream of the stoppage stops too.** The whole route halts; nothing piles up on intermediate
  equipment.
- **I6 No restart delay or re-run time** after equipment comes back. Restart is immediate.
- **I7 Scope:** only route equipment (conveyors, elevators and other intermediate segments) can stop. Hopper outlets,
  bins, load points and truck stations cannot (not yet modelled).

## 7. Implementation and verification (step 17)

**Code** (no rewrite of the grain-flow engine; normal operation unchanged):

| Area | Change |
|---|---|
| Configuration | `SiteConfig.outages` (`config/schema.py`); checks in `config/rules_validation.py` (route equipment only, clock times, end after start, no overlap). The configuration hash leaves the setting out when there are no outages, so existing hashes are unchanged. |
| Ledger | `down` set: a segment claim through unavailable equipment is refused with `EQUIPMENT_DOWN`. `holders(segment)`. |
| Engine (`sim/truck_flow.py`) | Outage events: `_equipment_down` (suspend: rate 0, completion cancelled, reservations kept), `_equipment_up` / `_resume_suspended` (same record continues; changeover rule I3; load clock I4). Plant opening resumes transfers that waited for it. |
| Records | `TransferRecord.interruptions`, `LoadRecord.interruptions` (`[suspended, resumed or None]`); `LotFlow.on_route_kg` (left the pit, not yet in a bin). |
| Audit (`checks/flow_audit.py`) | Invariants I-A (no flow through unavailable equipment), I-B (no reservation through it), I-C (well-formed suspensions). |

**Deterministic tests** (`tests/test_interrupted_transfers.py`, 19 tests, hand-traced; all behaviour cases matched
on the first run):

| Case | Hand-traced result |
|---|---|
| Down before the transfer | The lot waits with `EQUIPMENT_DOWN`; the truck still leaves at 07:01; flow 07:05-07:14 |
| Alternative route | The lot goes via E2 at once |
| Down mid-flow | At 07:06: 0 delivered, 10 t on the route, 20 t at source, route held; the same transfer resumes 07:08, done 07:14 |
| After partial delivery | 20 t already in B1 kept; the second part (to B3) is interrupted with 3,333 kg on the route; done 07:14 |
| During changeover | Flow starts at the restart (07:20), done 07:29 |
| Shared route, incompatible grain | White maize kept out of the held yellow route until it completes (07:27) |
| Shared elevator | The suspended stream keeps its slot; the other runs at full rate; finishes 07:13 / 07:19 |
| Suspended at end of run | 10 t on route + 20 t at source accounted; nothing delivered or lost; no stall |
| Restart after close (transfers stop at close) | Resumes at next day's opening (done day 2, 07:06), or stays suspended on a one-day run |
| Loads | Clock paused 4 min in flow (done 07:18) or 2 min in setup (07:16); stock leaves the bin only at completion |
| Configuration | 5 invalid outage forms refused |
| Audit | Detects flow through unavailable equipment and a reservation during an outage |

**Further evidence:**
- **Generated days with outages** (sites A and B, 3 outages each on configured conveyors and elevators, both
  policies, 5 seeds, demand ×1.2): 20 runs, 28 suspensions, 0 audit problems, 0 stalls, grain balanced in every run.
- **Fault injection** (8 faults in the new code, all detected): completion not cancelled; a route reserved through
  unavailable equipment; capacity not re-shared; load clock not paused; resume ignoring transfers-stop-at-close;
  changeover flow starting as planned; on-route grain reported as 0; a flowing transfer not restarted.

**Normal operation unchanged:**
- `pytest -q`: 310 passed, 2 expected failures (the known tie-break, step 15). This includes all 291 earlier tests,
  unchanged.
- **Fingerprint:** the version-tolerant engine fingerprint (32 runs: sites A and B × 2 policies × 2 demand levels ×
  4 seeds) is identical to the committed step-16 engine. It compares records as data and ignores the new
  `interruptions` field when it is empty. The earlier repr-based fingerprint changes only because every record now
  prints `interruptions=[]`.
- Configuration hashes and the fairness baseline are unchanged; prototype selftests 12/12.

**Still to confirm operationally:** decisions I1-I7 (§6).
