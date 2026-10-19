# Architecture decision record — v0.1, pending prototype inspection

## Architectural choice
Build a standalone headless discrete-event engine. Use a **central dispatcher over a discrete-event calendar**, preserving any already-working prototype implementation. Decide *after inspection* whether to port the existing prototype to Python, wrap it or refactor it. A Python event calendar with a stable `(time, priority, sequence)` ordering is the default recommendation. SimPy can be considered for time scheduling, but generic FIFO `Resource.request()` may not own dispatch choices or piecemeal route allocation.

## Conceptual boundaries
- `domain`: trucks, samples, bulk lots, commodity/grade, bins, route requests, resource capacities and states; units and invariant definitions.
- `configuration`: versioned site schema, equipment templates, directed graph edges, commodities/grades, policy settings, arrival distributions, initial conditions, and configuration errors.
- `simulation`: event calendar, state transitions, central truck dispatcher, central grain-route dispatcher, resource reservation ledger, grain transfers, sample matching, monitoring, KPI collector.
- `experiments`: seeded runs, scenarios, comparable demand streams, replications, confidence intervals and integrity/status output.
- `api`: validation, scenario creation, asynchronous run initiation, status, cancellation, results.
- `workers`: durable job queue (choose RQ, Celery or Arq based on deployment); workers invoke headless engine; FastAPI routes do not run 30 simulations inline.
- `persistence`: site/config versions, baseline data, scenario revisions, job state, run metadata, results, audit records.
- `frontend`: guided site configuration graph, scenario inputs, KPI comparisons and decision reports, with advanced diagnostics.

## Scheduling and dispatch
1. An event or state change makes one or more requests eligible for consideration.
2. The dispatcher evaluates pending requests under policy (FIFO, commodity batch or feasible-first) and the fully required route, resource availability, inventories, commodity lock and exit conditions.
3. It **atomically reserves all resources** required for the intended transaction; either all reservations succeed or none occur.
4. Schedule start/finish/changeover/transfer events; update states and conservation records.
5. Release reservations on completion, cancellation and explicit failure; trigger dispatcher reevaluation.
6. Deterministic tie-breaking by configured priority then arrival order / unique sequence, with tests for starvation/fairness under feasible-first.

**Crucial design question to decide with domain evidence:** 'whole route' may mean the entire transfer path for the full batch, or a compatible path / set of sections for a bounded transfer operation. Reserving everything for the full lot is safe but may reduce parallelism unrealistically. Make the reservation scope configurable only after carefully specifying transfer/flush behaviour. Test both deadlock prevention and realistic throughput.

## Route feasibility predicate
A requested route is feasible only when:
- directed graph path exists from an authorised source to compatible destination;
- all links, resources and bin allocations are permitted for commodity and grade;
- available capacities and occupancy permit the planned transfer;
- any commodity changeover / flush logic and reservations are satisfied;
- needed source inventory and destination space exist;
- truck/hopper/service/shift rules permit execution.

No 'route found' outcome is sufficient by itself. Include explainable blocked reasons.

## Quantity and precision
Prefer canonical tonne quantities with `Decimal` or validated integer subunits (e.g., kg) depending on supported resolution and performance requirements. Avoid generating one token per tonne. Maintain event-level ledger entries: source, destination, quantity, time, commodity, operation ID. If fractional tonnes are allowed, include a numeric tolerance policy.

## API design (indicative; revise after prototype inspection)
- `POST /sites/{id}/validate`
- `POST /scenarios` 
- `POST /scenarios/{id}/validate`
- `POST /scenarios/{id}/runs` -> 202 + run ID
- `GET /runs/{id}` -> state, completed/total replications, errors
- `POST /runs/{id}/cancel`
- `GET /runs/{id}/results`

Use immutable snapshots of configuration per run. Idempotency keys for job creation; cancellation semantics and worker recovery need tests.

## Constraints on feasibility claims
Configuration-driven modeling applies within a clearly stated library of supported equipment/process archetypes. It does not automatically infer real physical site connections or support arbitrary mechanical physics. Two distinct site topologies are necessary but not sufficient proof of generalized adaptability.
