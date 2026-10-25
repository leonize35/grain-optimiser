# Ventersdorp receiving process: sampling, grading and the incoming weighbridge

Status: the design is confirmed by the user (2026-10-25) and the engine behaviour is verified by hand-traced tests
(`tests/test_grading_blocking.py`). No Ventersdorp times or capacities are used. This answers calibration
question **Q-1** for receiving trucks.

## Confirmed rule

1. The truck is sampled at the shared sampler. **The sampler is released when sampling is complete.**
2. The sample is graded independently of the truck's movement (grader queue; sample matched back to its own truck).
3. The truck moves into the incoming-weighbridge queue. If the incoming weighbridge is free it drives on and is
   weighed, **even if its grading result is still pending.** Weighing itself does not wait for grading.
4. If the result is not ready when weighing ends, the truck **stays on the incoming weighbridge** until it is. No other
   truck can use that weighbridge meanwhile.
5. Only then is the truck assigned to a silo/hopper (assignment depends on the result) and moves on.
6. Consequence: grading delays block the incoming weighbridge and propagate upstream (weighbridge queue, then the
   sampler if the queue is full).

## Representation in the engine (no engine change was needed)

- **Receiving sequence:** `sample → weigh_in → grade → tip → weigh_out`.
- **Truck path:** must be **explicit**, with no waiting area between `weigh_in` and `grade`, e.g.

  ```
  sample → wb_queue → weigh_in → grade → hopper_queue → tip → out_queue → weigh_out
  ```

- **How the `grade` element works in a path:**
  - It means "the truck holds its current place until its result exists".
  - Directly after `weigh_in`, the place held is the incoming-weighbridge lane, released only when the truck moves on after the result.
  - If the result already exists when weighing ends, the truck moves on at once.
- **Sampling and grading:**
  - The sample enters the grader queue when sampling ends.
  - The sampler lane is released when the truck moves on (its next place being the weighbridge queue).
  - Under `reserve_next_space`, sampling starts only when a place in the next finite area is reserved, so a full weighbridge queue stops new sampling (upstream propagation).
- **Hopper:** a truck asks for a hopper only after its result (the `tip` request is made after `grade`).
- **Without an explicit path** the engine places an unlimited implicit area before every step, including `grade`, so the truck would leave the weighbridge. The default is unchanged (synthetic configurations and evidence depend on it). The Ventersdorp configuration must therefore give the receiving path explicitly. This is a configuration requirement, checked by the tests below.

## Verification (hand-traced, deterministic)

| Test | Shows |
|---|---|
| `test_truck_waiting_for_grading_holds_the_incoming_weighbridge` | Grading (10 min) takes longer than reaching and crossing the bridge. The sampler is free at the end of each sampling. T1 is weighed 07:04–07:06 and holds WB_IN until its result at 07:14. Later trucks queue. Bridge occupancy is back to back and never overlapping. No hopper before the result |
| `test_without_a_truck_path_the_truck_does_not_wait_on_the_bridge` | Why the explicit path is required |
| `test_fast_grading_releases_the_bridge_after_weighing` | A result ready before weighing ends adds no occupancy |
| `test_grading_delay_propagates_upstream_to_the_sampler` | With one queue place, a third truck's sampling is delayed from 07:08 to 07:14 by the bridge being held |

The flow audit (no double use of a lane, sample-to-truck identity, conservation) passes in every test.

## Still to confirm (does not block the representation)

- **Q-4:** capacity of the weighbridge queue, and of the waiting places before the hoppers and the outgoing bridge.
- **Travel times:** between sampler, bridge and hopper. The engine has none; they are zero in the tests. If material, they need a small extension or must be included in the service times.
- **Grading time distribution and grader capacity:** time studies, and the number of people or instruments grading (part of D-1; the sample runner of R-8).
- **Exceptions:** e.g. a truck sent off the bridge to a holding place when grading is slow. Not modelled unless confirmed.
