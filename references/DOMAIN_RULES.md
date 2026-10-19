# Domain rules to formalise with actual code and silo operations

## Streams
1. Unloading: arrival -> sample/grade where required -> weigh-in -> hopper -> weigh-out -> departure, with configurable sequence and optional overlap.
2. Loading: select compatible inventory -> reserve quantity and route -> transfer through eligible equipment -> load truck -> weigh/process -> leave.
3. Weighbridge-only: weighs without grain transfer.
Shared resources are reserved once for all simultaneous streams.

## Linked but different flows
Trucks are discrete physical jobs; samples are separately processed and must return to their originating truck by unique ID; grain is a bulk quantity that travels after unloading independently of the truck. Event scheduling must not assume sample results return in FIFO order.

## Capacity and connectivity
Graph: hopper -> discharge/transfer -> bottom conveyor -> elevator -> top conveyor -> bin, or an alternative configured topology. Separate connections for truck access. Example current *research model* explored 2 hoppers sharing a route, whereas the real case facility had more hoppers; **do not hardcode either**.

Availability has at least three dimensions: physical reachability, temporary resource/transfer availability, commodity/grade compatibility. Empty does not imply eligible.

## Commodity and batch rules
- Each lot has commodity, grade, quantity and destination (where known).
- Distinct commodities cannot occupy incompatible common paths under site rules.
- Batch close/changeover requires defined downstream route clearance; no premature release.
- FIFO and feasible-first/batching must be distinct documented policies. Feasible-first may overtake blocked work; fairness and starvation should be measured.
- Source/destination bin allocation must be checked against existing inventory and capacity; prevent 'inventory from nowhere'.

## Initial conditions and data
Support morning backlog and non-uniform arrival patterns. Separate observed arrivals from actual market demand; external customers deterred by queues are not present in transactions. Distinguish gate-to-exit turnaround from ERP weigh-in-to-weigh-out.

## Real-world modelling decisions requiring confirmation
- Exact sample grading and truck reunification gating.
- Whether unloading truck can depart before grain reaches bin.
- Which conveying segments can contain grain during changeover.
- Reversibility, branching and shared conveyor capacities.
- Queue/service scheduling policies by silo.
- Shift-end handling and carry-over backlog.
- Initial bin stock and commodity assignment rules.
- Load quantity reservation, source bin selection and shortages.

Document each decision with evidence source, risk and test rather than silently defaulting.
