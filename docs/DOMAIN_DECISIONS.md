# Domain decisions — operating rules to confirm before they enter the engine

Status of every item: **PROPOSED, awaiting confirmation by the domain owner.** Nothing below is implemented beyond what the prototype already does. Once confirmed, each rule gets a behavioural test before any code.

Each item gives: what the prototype does today (observed), the proposed interpretation, why, and the test that would pin it down.

---

## D1. Can two hoppers of the same commodity share one elevator at the same time?

- **Prototype:** no. A transfer reserves every conveyor and elevator on its path, exclusively, for the whole lot (whole route × whole lot). Two hoppers carrying the same commodity alternate one lot at a time (BASELINE_RESULTS B4 trace).
- **Proposal:** keep **one lot at a time per route segment** as the default rule. It is safe, deadlock-free and matches the prototype. Design the reservation ledger so that a second rule can be switched on per site later without rewriting the dispatcher: **"commodity lock"**, where a segment may carry several streams of the *same* commodity at once and shares its t/h rate between them.
- **Why:** the default is the conservative reading of "whole-route reservation". The alternative could matter a lot for throughput (an elevator idling while a second same-commodity pit waits), but it should only be built if it happens on real plants.
- **Question for you:** at the sites you know, do two pits ever discharge onto the same conveyor or elevator at the same time? If so, is it only for the same commodity?
- **Test:** two hoppers, one elevator, same commodity, scripted arrivals at 07:00 and 07:01. Under the default rule the second lot starts exactly when the first finishes (hand-computed times).

## D2. Can an unloading truck leave before its grain reaches the bin?

- **Prototype:** yes. The truck tips into the pit and continues to weigh-out at once; the pit acts as a buffer. A truck waits only if the pit cannot take its **whole** load (no partial tipping).
- **Proposal:** adopt the prototype rule. Tipping needs a free pit with enough space for the full load, of a compatible commodity (empty, or holding the same commodity). The truck is then released, and the grain becomes a lot in the pit.
- **Question for you:** is partial tipping ever done (a truck tips half, waits, tips the rest)? Is a truck ever held at the pit until the pit has drained?
- **Test:** pit capacity 60 t holding 40 t; a 30 t truck arrives. It waits until at least 30 t has drained, and its start time is computed by hand from the discharge rate.

## D3. What happens on a commodity changeover?

- **Prototype:** a changeover is a **time penalty**. If any conveyor or elevator on the chosen route last carried a different commodity, the transfer starts after the longest changeover time among those segments. Segments are treated as empty when each lot finishes. There is no flush quantity and no contamination tracking.
- **Proposal:** keep the time-based rule. The route stays reserved during the changeover, so nothing else can use it, and the changeover is counted and reported per segment. Add an optional per-segment flush quantity later only if you confirm it happens.
- **Questions for you:** (a) Is the clearance time-based (run empty for N minutes) or volume-based (a quantity of the new commodity is diverted or downgraded)? (b) Is it needed for every commodity pair, or only some (e.g. yellow to white maize, but not white to yellow)?
- **Test:** route last carried yellow maize, next lot white maize, changeover 8 min, rate 200 t/h, lot 30 t. Transfer time = 8 + 30/200×60 = **17 min**.

## D4. Must grades be kept apart in bins?

- **Prototype:** no. A grade is drawn per truck (85% grade 1) but is never used for routing or storage.
- **Proposal:** segregate by **commodity only** in the first engine version. Record grade on each lot so it shows in reports and traces, and leave an optional per-bin "allowed grades" rule for later.
- **Question for you:** at your sites, are different grades of the same commodity stored in different bins? If so, is grade known before tipping (from the sample) so it can steer the truck to a hopper?
- **Test (if confirmed):** grade-2 maize is never routed to a bin restricted to grade 1, and a validation error appears if no bin accepts a grade that arrives.

## D5. Do waiting trucks physically block weighbridges or lanes?

- **Prototype:** no. Queues are virtual and unlimited. A truck holds the weighbridge only while being weighed and then moves to an unlimited queue for the hopper.
- **Proposal:** keep unlimited virtual queues for now. Make it a priority follow-up to add an optional **yard/lane capacity** per area (e.g. space for N trucks between the weighbridge and the hoppers). When that space is full, a truck that has finished weighing stays on the weighbridge and blocks it. This is "blocking after service" and can change weighbridge utilisation materially.
- **Question for you:** after weigh-in, where do trucks queue for the hoppers, and how many fit? When that space is full, does the truck wait on the weighbridge?
- **Test (when added):** lane capacity 1, one truck waiting for a busy hopper. The next weighed truck stays on the weighbridge until the lane frees, with times computed by hand.

## D6. What happens to trucks still on site when the silo closes?

- **Prototype:** the gate closes at closing time, and trucks inside are served during overtime. At the end of overtime the run **stops hard**. Trucks still on site are counted but **excluded from turnaround statistics**, which understates congestion on busy days (audit finding, GAP_MATRIX row 40).
- **Proposal:**
  1. No new arrivals after closing.
  2. Trucks already inside are served during overtime.
  3. At the end of overtime, every truck still on site is reported as **unserved**, with its waiting time so far, and the turnaround KPIs show the unserved count next to them. They are never silently dropped.
  4. In multi-day runs, unserved trucks become the next morning's opening queue, and grain in pits stays in the pits.
- **Question for you:** in reality, are trucks inside at closing always finished that night, or sent away? Is there a hard stop time?
- **Test:** scripted arrivals where the last truck cannot finish before the end of overtime. It appears as unserved with a waiting time computed by hand, and the KPI output reports the count.

---

## Related decisions already taken (engineering, not operating rules)

| Decision | Choice | Where |
|---|---|---|
| Time resolution | Whole milliseconds from midnight of day 1 | `sim/time.py` |
| Grain quantities | Whole kilograms; inputs at most 3 decimal tonnes | `domain/quantities.py` |
| Same-instant event order | Releases, then control, then arrivals; then scheduling order | `sim/calendar.py` |
| Scripted arrival at exactly closing time | Accepted (assumption, easy to change) | `inputs/scripted.py` |
