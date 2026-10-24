# Paper 2 extension: sampler access, physical queue blocking and sampler location (generated)

Source: `evidence/out/paper2-ext-sampling-v1/manifest.json` (sha256 `03fdb899e3a9fad731bdce72be1e72e15cdba9c57fdbe10c112af56cc6f86da7`), built at Git commit `deb1c2b`, extending baseline `paper2-v1` (commit `6345377`, manifest sha256 `71ca9133ee4e4534…`, unchanged). Engine source sha256 `999a8e13a0a72d9e…`.

**Synthetic configurations; software outputs, not observations of a real silo. Provisional modelling assumptions O1-O11 (`docs/SAMPLER_ACCESS_DESIGN.md` §8) apply to every result.** Layouts differ only in layout; sampling units and weighbridge bays are the same within each site. Queue policy: M-FF in every queue group (stated, not claimed as practice).

## Verification

| Check | Result |
|---|---|
| Runs (2 sites × 4 layouts × 3 sampled shares × 20 seeds) | 840 |
| Flow-audit problems (incl. access invariants) | 0 |
| max abs mass balance / engine violations | 0 kg / 0 |
| Stalled runs (operational, reported) | 0 |
| Rebuild and compare | 105/105 files identical |
| Deterministic acceptance tests S1-S4 | `tests/test_sampler_access.py` (18 tests, hand-traced) |

Sources: `evidence/out/paper2-ext-sampling-v1/verification.json` (sha256 436bda3e1bce); `evidence/out/paper2-ext-sampling-v1/audit.json` (sha256 b596b6f7278e).

## Site A: performance by layout and sampled share (n = 20 seeds; mean ± 95% CI half-width [SD])

| Share | Layout | Turnaround, sampled trucks (min) | Turnaround, unsampled trucks (min) | Sampler waiting, sampled trucks (min) | Weighbridge waiting, sampled trucks (min) | Weighbridge waiting, unsampled trucks (min) | Physically blocked behind another truck, unsampled (min) | Physically blocked behind another truck, sampled (min) | Sampler queue (excl. road blocking), unsampled (min) | Blocked in sampler bay by full holding, sampled (min) | Blocked in sampler bay by full holding, unsampled (min) | Hopper waiting (tip), all unloading trucks (min) | Unfinished at closing, waiting at a hopper (trucks) | Approach queue length (time-average) (trucks) | Completed unloading trucks (trucks/day) | Grain received (t/day) | Weighbridge bays busy (fraction) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.3 | S1 | 121.1 ± 12.3 [26.3] | 114.2 ± 11.1 [23.7] | 0.2 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.1 ± 0.0 [0.0] | 0.2 ± 0.0 [0.1] | 0.2 ± 0.1 [0.1] | 0.2 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 104.5 ± 10.8 [23.0] | 9.1 ± 4.7 [10.1] | 0.0 ± 0.0 [0.0] | 61.1 ± 2.2 [4.7] | 1910.9 ± 75.8 [162.0] | 0.171 ± 0.006 [0.013] | 0.171 ± 0.006 [0.013] |
| 0.3 | S2 | 120.9 ± 11.9 [25.5] | 115.2 ± 10.3 [22.0] | 0.2 ± 0.1 [0.1] | 0.1 ± 0.0 [0.1] | 0.2 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 105.5 ± 10.1 [21.5] | 9.3 ± 4.7 [10.0] | 0.0 ± 0.0 [0.0] | 60.8 ± 2.0 [4.2] | 1902.5 ± 65.9 [140.7] | 0.171 ± 0.006 [0.013] | 0.171 ± 0.006 [0.013] |
| 0.3 | S3 | 121.7 ± 12.0 [25.7] | 114.8 ± 10.5 [22.4] | 0.8 ± 0.2 [0.3] | 0.0 ± 0.0 [0.0] | 0.2 ± 0.0 [0.1] | 0.2 ± 0.0 [0.1] | 0.2 ± 0.1 [0.2] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 105.3 ± 10.1 [21.7] | 9.3 ± 4.7 [10.0] | 0.0 ± 0.0 [0.0] | 60.8 ± 1.9 [4.2] | 1902.5 ± 65.9 [140.7] | 0.200 ± 0.009 [0.018] | 0.200 ± 0.009 [0.018] |
| 0.3 | S4 | 121.7 ± 12.2 [26.1] | 115.4 ± 9.8 [20.9] | 0.8 ± 0.2 [0.3] | 0.0 ± 0.0 [0.0] | 0.3 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.2 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 105.8 ± 10.0 [21.4] | 9.3 ± 4.7 [9.9] | 0.0 ± 0.0 [0.0] | 60.6 ± 1.9 [4.2] | 1900.7 ± 65.8 [140.5] | 0.200 ± 0.009 [0.018] | 0.200 ± 0.009 [0.018] |
| 0.7 | S1 | 116.3 ± 10.1 [21.6] | 123.0 ± 20.8 [44.5] | 0.4 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | 0.1 ± 0.0 [0.1] | 0.3 ± 0.1 [0.2] | 0.3 ± 0.1 [0.2] | 0.4 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 105.8 ± 13.5 [28.8] | 8.9 ± 4.7 [10.1] | 0.1 ± 0.0 [0.0] | 61.2 ± 2.6 [5.5] | 1914.1 ± 79.8 [170.5] | 0.171 ± 0.006 [0.012] | 0.171 ± 0.006 [0.012] |
| 0.7 | S2 | 117.8 ± 11.6 [24.8] | 118.2 ± 22.5 [48.2] | 0.5 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | 0.1 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.2 ± 0.1 [0.2] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 105.0 ± 14.5 [31.0] | 9.7 ± 4.7 [10.1] | 0.0 ± 0.0 [0.0] | 60.5 ± 2.8 [6.0] | 1889.9 ± 90.4 [193.2] | 0.171 ± 0.006 [0.014] | 0.171 ± 0.006 [0.014] |
| 0.7 | S3 | 117.5 ± 11.8 [25.3] | 120.7 ± 21.9 [46.8] | 1.5 ± 0.2 [0.4] | 0.0 ± 0.0 [0.0] | 0.1 ± 0.1 [0.1] | 0.8 ± 0.2 [0.5] | 0.8 ± 0.3 [0.6] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 104.4 ± 15.0 [32.0] | 8.8 ± 4.1 [8.9] | 0.1 ± 0.0 [0.1] | 61.5 ± 2.5 [5.4] | 1918.2 ± 81.2 [173.6] | 0.239 ± 0.011 [0.023] | 0.239 ± 0.011 [0.023] |
| 0.7 | S4 | 116.5 ± 11.4 [24.5] | 117.9 ± 21.4 [45.7] | 1.5 ± 0.2 [0.4] | 0.0 ± 0.0 [0.0] | 0.2 ± 0.1 [0.2] | 0.0 ± 0.0 [0.0] | 0.7 ± 0.3 [0.6] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 103.5 ± 14.5 [31.1] | 9.1 ± 4.4 [9.3] | 0.1 ± 0.0 [0.1] | 61.1 ± 2.6 [5.5] | 1910.9 ± 82.5 [176.2] | 0.239 ± 0.011 [0.022] | 0.239 ± 0.011 [0.022] |
| 1 | S1 | 125.2 ± 11.6 [24.7] | – | 0.6 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | – | – | 0.5 ± 0.1 [0.1] | – | 0.0 ± 0.0 [0.0] | – | 106.8 ± 12.0 [25.7] | 8.1 ± 3.4 [7.3] | 0.1 ± 0.0 [0.0] | 62.1 ± 2.4 [5.1] | 1941.2 ± 78.9 [168.6] | 0.173 ± 0.007 [0.015] | 0.173 ± 0.007 [0.015] |
| 1 | S2 | 125.2 ± 11.6 [24.7] | – | 0.6 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | – | – | 0.5 ± 0.1 [0.1] | – | 0.0 ± 0.0 [0.0] | – | 106.8 ± 12.0 [25.7] | 8.1 ± 3.4 [7.3] | 0.1 ± 0.0 [0.0] | 62.1 ± 2.4 [5.1] | 1941.2 ± 78.9 [168.6] | 0.173 ± 0.007 [0.015] | 0.173 ± 0.007 [0.015] |
| 1 | S3 | 125.3 ± 10.9 [23.4] | – | 2.1 ± 0.2 [0.4] | 0.0 ± 0.0 [0.0] | – | – | 2.1 ± 1.0 [2.1] | – | 0.0 ± 0.0 [0.0] | – | 105.1 ± 11.1 [23.7] | 8.8 ± 3.2 [6.9] | 0.3 ± 0.1 [0.3] | 61.4 ± 2.4 [5.1] | 1918.5 ± 79.0 [168.8] | 0.270 ± 0.012 [0.026] | 0.270 ± 0.012 [0.026] |
| 1 | S4 | 125.3 ± 10.9 [23.4] | – | 2.1 ± 0.2 [0.4] | 0.0 ± 0.0 [0.0] | – | – | 2.1 ± 1.0 [2.1] | – | 0.0 ± 0.0 [0.0] | – | 105.1 ± 11.1 [23.7] | 8.8 ± 3.2 [6.9] | 0.3 ± 0.1 [0.3] | 61.4 ± 2.4 [5.1] | 1918.5 ± 79.0 [168.8] | 0.270 ± 0.012 [0.026] | 0.270 ± 0.012 [0.026] |

## Site C: performance by layout and sampled share (n = 20 seeds; mean ± 95% CI half-width [SD])

| Share | Layout | Turnaround, sampled trucks (min) | Turnaround, unsampled trucks (min) | Sampler waiting, sampled trucks (min) | Weighbridge waiting, sampled trucks (min) | Weighbridge waiting, unsampled trucks (min) | Physically blocked behind another truck, unsampled (min) | Physically blocked behind another truck, sampled (min) | Sampler queue (excl. road blocking), unsampled (min) | Blocked in sampler bay by full holding, sampled (min) | Blocked in sampler bay by full holding, unsampled (min) | Hopper waiting (tip), all unloading trucks (min) | Unfinished at closing, waiting at a hopper (trucks) | Approach queue length (time-average) (trucks) | Completed unloading trucks (trucks/day) | Grain received (t/day) | Weighbridge bays busy (fraction) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.3 | S1 | 74.2 ± 7.5 [16.1] | 67.4 ± 6.3 [13.4] | 0.1 ± 0.0 [0.0] | 0.1 ± 0.0 [0.1] | 0.2 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.1 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 56.9 ± 5.3 [11.3] | 14.2 ± 6.6 [14.1] | 0.0 ± 0.0 [0.0] | 153.4 ± 4.9 [10.5] | 4901.6 ± 161.6 [345.3] | 0.304 ± 0.008 [0.017] | 0.304 ± 0.008 [0.017] |
| 0.3 | S2 | 75.7 ± 6.1 [13.1] | 70.0 ± 7.3 [15.6] | 0.0 ± 0.0 [0.0] | 0.2 ± 0.0 [0.1] | 0.2 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 59.2 ± 5.8 [12.4] | 14.2 ± 5.5 [11.8] | 0.0 ± 0.0 [0.0] | 153.3 ± 6.1 [13.0] | 4902.6 ± 197.2 [421.4] | 0.304 ± 0.010 [0.021] | 0.304 ± 0.010 [0.021] |
| 0.3 | S3 | 74.4 ± 7.3 [15.6] | 66.1 ± 7.5 [16.1] | 1.7 ± 0.2 [0.5] | 0.0 ± 0.0 [0.0] | 0.3 ± 0.0 [0.1] | 0.8 ± 0.4 [0.9] | 0.7 ± 0.5 [1.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 54.6 ± 6.7 [14.4] | 17.2 ± 6.1 [13.1] | 0.3 ± 0.1 [0.2] | 150.6 ± 4.7 [10.1] | 4803.1 ± 152.9 [326.8] | 0.369 ± 0.012 [0.026] | 0.369 ± 0.012 [0.026] |
| 0.3 | S4 | 75.6 ± 7.0 [15.0] | 66.8 ± 7.8 [16.6] | 1.7 ± 0.2 [0.5] | 0.0 ± 0.0 [0.0] | 0.4 ± 0.1 [0.2] | 0.0 ± 0.0 [0.0] | 0.6 ± 0.4 [0.8] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 56.6 ± 6.5 [13.8] | 16.1 ± 6.0 [12.9] | 0.2 ± 0.1 [0.1] | 151.2 ± 4.8 [10.3] | 4837.3 ± 155.6 [332.4] | 0.369 ± 0.012 [0.026] | 0.369 ± 0.012 [0.026] |
| 0.7 | S1 | 70.2 ± 6.3 [13.4] | 62.2 ± 6.6 [14.2] | 0.2 ± 0.0 [0.1] | 0.1 ± 0.0 [0.0] | 0.2 ± 0.0 [0.1] | 0.1 ± 0.0 [0.1] | 0.1 ± 0.0 [0.0] | 0.2 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 52.6 ± 6.1 [13.0] | 18.6 ± 6.8 [14.4] | 0.0 ± 0.0 [0.0] | 148.7 ± 5.5 [11.8] | 4755.1 ± 173.8 [371.4] | 0.300 ± 0.008 [0.018] | 0.300 ± 0.008 [0.018] |
| 0.7 | S2 | 69.2 ± 7.1 [15.2] | 60.7 ± 10.0 [21.3] | 0.2 ± 0.0 [0.1] | 0.1 ± 0.0 [0.1] | 0.1 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 52.0 ± 7.9 [16.8] | 21.4 ± 5.3 [11.4] | 0.0 ± 0.0 [0.0] | 146.1 ± 4.9 [10.4] | 4667.8 ± 154.7 [330.5] | 0.298 ± 0.009 [0.019] | 0.298 ± 0.009 [0.019] |
| 0.7 | S3 | 81.9 ± 10.0 [21.4] | 71.7 ± 7.4 [15.9] | 4.3 ± 0.3 [0.6] | 0.0 ± 0.0 [0.0] | 0.6 ± 0.1 [0.1] | 16.2 ± 7.3 [15.7] | 15.6 ± 8.0 [17.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 45.8 ± 6.2 [13.2] | 20.3 ± 6.0 [12.9] | 4.0 ± 1.9 [4.0] | 147.3 ± 5.5 [11.7] | 4700.5 ± 183.7 [392.5] | 0.454 ± 0.015 [0.032] | 0.454 ± 0.015 [0.032] |
| 0.7 | S4 | 85.0 ± 9.1 [19.5] | 62.9 ± 9.3 [19.9] | 4.4 ± 0.3 [0.7] | 0.0 ± 0.0 [0.0] | 0.5 ± 0.1 [0.2] | 0.0 ± 0.0 [0.0] | 14.9 ± 7.6 [16.3] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 51.5 ± 5.9 [12.6] | 16.2 ± 6.0 [12.7] | 2.9 ± 1.3 [2.8] | 150.9 ± 5.3 [11.4] | 4830.1 ± 171.4 [366.3] | 0.457 ± 0.015 [0.031] | 0.457 ± 0.015 [0.031] |
| 1 | S1 | 75.6 ± 8.0 [17.1] | – | 0.3 ± 0.0 [0.1] | 0.1 ± 0.0 [0.0] | – | – | 0.1 ± 0.0 [0.1] | – | 0.0 ± 0.0 [0.0] | – | 57.4 ± 8.1 [17.4] | 14.1 ± 5.0 [10.8] | 0.1 ± 0.0 [0.0] | 153.3 ± 5.2 [11.1] | 4902.1 ± 169.8 [362.9] | 0.304 ± 0.009 [0.020] | 0.304 ± 0.009 [0.020] |
| 1 | S2 | 75.6 ± 8.0 [17.1] | – | 0.3 ± 0.0 [0.1] | 0.1 ± 0.0 [0.0] | – | – | 0.1 ± 0.0 [0.1] | – | 0.0 ± 0.0 [0.0] | – | 57.4 ± 8.1 [17.4] | 14.1 ± 5.0 [10.8] | 0.1 ± 0.0 [0.0] | 153.3 ± 5.2 [11.1] | 4902.1 ± 169.8 [362.9] | 0.304 ± 0.009 [0.020] | 0.304 ± 0.009 [0.020] |
| 1 | S3 | 123.8 ± 12.3 [26.3] | – | 5.3 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | – | – | 99.7 ± 14.8 [31.6] | – | 0.0 ± 0.0 [0.0] | – | 12.1 ± 3.9 [8.3] | 5.1 ± 2.1 [4.4] | 21.3 ± 3.7 [7.8] | 144.0 ± 2.4 [5.2] | 4631.3 ± 80.7 [172.4] | 0.480 ± 0.005 [0.011] | 0.480 ± 0.005 [0.011] |
| 1 | S4 | 123.8 ± 12.3 [26.3] | – | 5.3 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | – | – | 99.7 ± 14.8 [31.6] | – | 0.0 ± 0.0 [0.0] | – | 12.1 ± 3.9 [8.3] | 5.1 ± 2.1 [4.4] | 21.3 ± 3.7 [7.8] | 144.0 ± 2.4 [5.2] | 4631.3 ± 80.7 [172.4] | 0.480 ± 0.005 [0.011] | 0.480 ± 0.005 [0.011] |

## Site S: performance by layout and sampled share (n = 20 seeds; mean ± 95% CI half-width [SD])

| Share | Layout | Turnaround, sampled trucks (min) | Turnaround, unsampled trucks (min) | Sampler waiting, sampled trucks (min) | Weighbridge waiting, sampled trucks (min) | Weighbridge waiting, unsampled trucks (min) | Physically blocked behind another truck, unsampled (min) | Physically blocked behind another truck, sampled (min) | Sampler queue (excl. road blocking), unsampled (min) | Blocked in sampler bay by full holding, sampled (min) | Blocked in sampler bay by full holding, unsampled (min) | Hopper waiting (tip), all unloading trucks (min) | Unfinished at closing, waiting at a hopper (trucks) | Approach queue length (time-average) (trucks) | Completed unloading trucks (trucks/day) | Grain received (t/day) | Weighbridge bays busy (fraction) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.3 | S1 | 17.5 ± 0.3 [0.7] | 8.1 ± 0.4 [0.9] | 0.6 ± 0.1 [0.3] | 0.1 ± 0.0 [0.1] | 0.4 ± 0.1 [0.2] | 0.3 ± 0.2 [0.4] | 0.3 ± 0.2 [0.4] | 0.7 ± 0.1 [0.2] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.2 ± 0.0 [0.1] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 0.3 | S2 | 17.2 ± 0.3 [0.5] | 6.3 ± 0.1 [0.2] | 0.6 ± 0.1 [0.3] | 0.2 ± 0.1 [0.1] | 0.3 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | 0.1 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 0.3 | S3 | 20.1 ± 1.0 [2.1] | 8.0 ± 0.8 [1.8] | 2.0 ± 0.3 [0.6] | 0.0 ± 0.0 [0.0] | 0.5 ± 0.1 [0.2] | 0.9 ± 0.5 [1.0] | 0.8 ± 0.4 [0.8] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.3 ± 0.1 [0.2] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.440 ± 0.022 [0.046] | 0.440 ± 0.022 [0.046] |
| 0.3 | S4 | 19.9 ± 0.9 [1.9] | 7.3 ± 0.5 [1.0] | 2.1 ± 0.3 [0.7] | 0.0 ± 0.0 [0.0] | 0.7 ± 0.2 [0.5] | 0.0 ± 0.0 [0.0] | 0.7 ± 0.3 [0.7] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.2 ± 0.1 [0.1] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.440 ± 0.022 [0.046] | 0.440 ± 0.022 [0.046] |
| 0.3 | S1-h0 | 17.7 ± 0.4 [0.8] | 8.1 ± 0.4 [0.9] | 0.7 ± 0.1 [0.3] | 0.1 ± 0.0 [0.1] | 0.3 ± 0.0 [0.1] | 0.5 ± 0.3 [0.6] | 0.5 ± 0.3 [0.6] | 0.8 ± 0.1 [0.3] | 0.1 ± 0.0 [0.1] | 0.3 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.2 ± 0.1 [0.1] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 0.3 | S1-h5 | 17.4 ± 0.3 [0.7] | 8.1 ± 0.4 [0.9] | 0.6 ± 0.1 [0.3] | 0.1 ± 0.1 [0.1] | 0.4 ± 0.1 [0.2] | 0.3 ± 0.1 [0.3] | 0.3 ± 0.1 [0.3] | 0.6 ± 0.1 [0.2] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.1 ± 0.0 [0.1] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 0.7 | S1 | 20.0 ± 0.8 [1.7] | 10.7 ± 0.8 [1.7] | 1.7 ± 0.2 [0.4] | 0.1 ± 0.0 [0.0] | 0.4 ± 0.1 [0.1] | 1.8 ± 0.7 [1.4] | 1.8 ± 0.6 [1.4] | 1.8 ± 0.2 [0.3] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.6 ± 0.2 [0.3] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 0.7 | S2 | 19.4 ± 0.6 [1.4] | 6.3 ± 0.1 [0.2] | 1.9 ± 0.2 [0.4] | 0.1 ± 0.0 [0.0] | 0.2 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 1.1 ± 0.4 [0.9] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.3 ± 0.1 [0.2] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 0.7 | S3 | 35.2 ± 6.8 [14.5] | 22.0 ± 6.3 [13.6] | 4.8 ± 0.3 [0.7] | 0.0 ± 0.0 [0.0] | 0.7 ± 0.1 [0.2] | 13.6 ± 6.0 [12.9] | 13.4 ± 6.4 [13.8] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 2.8 ± 1.2 [2.7] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.575 ± 0.025 [0.054] | 0.575 ± 0.025 [0.054] |
| 0.7 | S4 | 34.6 ± 6.5 [13.8] | 8.0 ± 0.5 [1.0] | 4.9 ± 0.4 [0.7] | 0.0 ± 0.0 [0.0] | 1.0 ± 0.2 [0.5] | 0.0 ± 0.0 [0.0] | 12.9 ± 6.2 [13.2] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 2.1 ± 0.9 [1.9] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.575 ± 0.025 [0.054] | 0.575 ± 0.025 [0.054] |
| 0.7 | S1-h0 | 20.6 ± 1.1 [2.3] | 11.3 ± 1.1 [2.3] | 1.9 ± 0.2 [0.4] | 0.1 ± 0.0 [0.0] | 0.4 ± 0.0 [0.1] | 2.3 ± 0.9 [2.0] | 2.3 ± 0.9 [1.9] | 2.0 ± 0.2 [0.3] | 0.1 ± 0.0 [0.0] | 0.4 ± 0.0 [0.1] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.7 ± 0.2 [0.4] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 0.7 | S1-h5 | 19.9 ± 0.8 [1.6] | 10.6 ± 0.8 [1.6] | 1.7 ± 0.2 [0.4] | 0.1 ± 0.0 [0.0] | 0.5 ± 0.1 [0.1] | 1.7 ± 0.6 [1.3] | 1.7 ± 0.6 [1.3] | 1.8 ± 0.2 [0.3] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 0.5 ± 0.1 [0.3] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 1 | S1 | 27.8 ± 3.8 [8.2] | – | 3.1 ± 0.2 [0.5] | 0.0 ± 0.0 [0.0] | – | – | 8.3 ± 3.7 [7.8] | – | 0.0 ± 0.0 [0.0] | – | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 1.9 ± 0.7 [1.6] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 1 | S2 | 27.8 ± 3.8 [8.2] | – | 3.1 ± 0.2 [0.5] | 0.0 ± 0.0 [0.0] | – | – | 8.3 ± 3.7 [7.8] | – | 0.0 ± 0.0 [0.0] | – | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 1.9 ± 0.7 [1.6] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 1 | S3 | 103.8 ± 14.6 [31.1] | – | 6.2 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | – | – | 86.6 ± 16.4 [35.0] | – | 0.0 ± 0.0 [0.0] | – | 0.0 ± 0.0 [0.0] | 1.1 ± 0.4 [0.8] | 14.8 ± 3.2 [6.8] | 121.3 ± 1.7 [3.6] | 3881.9 ± 54.3 [116.1] | 0.632 ± 0.010 [0.020] | 0.632 ± 0.010 [0.020] |
| 1 | S4 | 103.8 ± 14.6 [31.1] | – | 6.2 ± 0.1 [0.1] | 0.0 ± 0.0 [0.0] | – | – | 86.6 ± 16.4 [35.0] | – | 0.0 ± 0.0 [0.0] | – | 0.0 ± 0.0 [0.0] | 1.1 ± 0.4 [0.8] | 14.8 ± 3.2 [6.8] | 121.3 ± 1.7 [3.6] | 3881.9 ± 54.3 [116.1] | 0.632 ± 0.010 [0.020] | 0.632 ± 0.010 [0.020] |
| 1 | S1-h0 | 28.2 ± 4.1 [8.8] | – | 3.1 ± 0.2 [0.5] | 0.0 ± 0.0 [0.0] | – | – | 8.7 ± 3.9 [8.4] | – | 0.0 ± 0.0 [0.0] | – | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 1.9 ± 0.8 [1.7] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |
| 1 | S1-h5 | 27.8 ± 3.8 [8.2] | – | 3.1 ± 0.2 [0.5] | 0.0 ± 0.0 [0.0] | – | – | 8.3 ± 3.7 [7.8] | – | 0.0 ± 0.0 [0.0] | – | 0.0 ± 0.0 [0.0] | 0.0 ± 0.0 [0.0] | 1.9 ± 0.7 [1.6] | 131.2 ± 5.5 [11.7] | 4189.6 ± 172.0 [367.5] | 0.338 ± 0.014 [0.031] | 0.338 ± 0.014 [0.031] |

Source: `evidence/out/paper2-ext-sampling-v1/summary_cells.json` (sha256 d8e9deed81a7) (all cells: `summary_cells.csv`).

## Configuration differences between scenarios (verified by the build)

Every scenario is generated from its site's S1 configuration; the build asserts that only `truck_areas`, `truck_paths`, `truck_bypasses`, `id`, `name`, `sampler.located_at`, `sampler.located_lanes` differ. Sampling units, weighbridge bays, service-time distributions, hoppers, routes and demand are identical within a site.

| Site: comparison | Differing configuration paths |
|---|---|
| A: S1 vs S1 | none (reference) |
| A: S1 vs S2 | id, name, truck_bypasses |
| A: S1 vs S3 | sampler.located_at, sampler.located_lanes, id, name, truck_areas, truck_paths.unload |
| A: S1 vs S4 | sampler.located_at, sampler.located_lanes, id, name, truck_areas, truck_bypasses, truck_paths.unload |
| C: S1 vs S1 | none (reference) |
| C: S1 vs S2 | id, name, truck_bypasses |
| C: S1 vs S3 | sampler.located_at, sampler.located_lanes, id, name, truck_areas, truck_paths.unload |
| C: S1 vs S4 | sampler.located_at, sampler.located_lanes, id, name, truck_areas, truck_bypasses, truck_paths.unload |
| S: S1 vs S1 | none (reference) |
| S: S1 vs S1-h0 | id, name, truck_areas, truck_paths.unload |
| S: S1 vs S1-h5 | id, name, truck_areas |
| S: S1 vs S2 | id, name, truck_bypasses |
| S: S1 vs S3 | sampler.located_at, sampler.located_lanes, id, name, truck_areas, truck_paths.unload |
| S: S1 vs S4 | sampler.located_at, sampler.located_lanes, id, name, truck_areas, truck_bypasses, truck_paths.unload |

Source: `evidence/out/paper2-ext-sampling-v1/layout_differences.json` (sha256 29d386e57bbb); configurations `evidence/out/paper2-ext-sampling-v1/configs/`.

## Where trucks wait: decomposition by truck class (sampled share 0.7; mean minutes per truck over 20 seeds)

Road blocking = behind another truck in the single-file approach; sampler queue = waiting for the sampler (or, for unsampled trucks, for the sampler bay to drive through), excluding road blocking; holding blocking = kept in the sampler bay after service because the holding space (or, without one, the weighbridge) was full; weighbridge = waiting for a weighbridge bay. The four parts do not overlap.

| Site | Layout | Class | Trucks/day | Road blocking | Sampler queue | Holding blocking | Weighbridge | Turnaround | Pass-throughs/day |
|---|---|---|---|---|---|---|---|---|---|
| A | S1 | sampled | 48.1 | 0.32 | 0.44 | 0.00 | 0.01 | 116.3 | 0.0 |
| A | S1 | unsampled | 22.4 | 0.33 | 0.40 | 0.00 | 0.08 | 123.0 | 22.4 |
| A | S2 | sampled | 48.1 | 0.23 | 0.46 | 0.00 | 0.02 | 117.8 | 0.0 |
| A | S2 | unsampled | 22.4 | 0.00 | 0.00 | 0.00 | 0.09 | 118.2 | 0.0 |
| A | S3 | sampled | 48.1 | 0.76 | 1.49 | 0.00 | 0.00 | 117.5 | 0.0 |
| A | S3 | unsampled | 22.4 | 0.77 | 0.00 | 0.00 | 0.14 | 120.7 | 0.0 |
| A | S4 | sampled | 48.1 | 0.75 | 1.51 | 0.00 | 0.00 | 116.5 | 0.0 |
| A | S4 | unsampled | 22.4 | 0.00 | 0.00 | 0.00 | 0.21 | 117.9 | 0.0 |
| C | S1 | sampled | 117.0 | 0.07 | 0.17 | 0.00 | 0.08 | 70.2 | 0.0 |
| C | S1 | unsampled | 51.2 | 0.06 | 0.18 | 0.00 | 0.19 | 62.2 | 51.2 |
| C | S2 | sampled | 117.0 | 0.04 | 0.17 | 0.00 | 0.10 | 69.2 | 0.0 |
| C | S2 | unsampled | 51.2 | 0.00 | 0.00 | 0.00 | 0.15 | 60.7 | 0.0 |
| C | S3 | sampled | 117.0 | 15.58 | 4.29 | 0.00 | 0.00 | 81.9 | 0.0 |
| C | S3 | unsampled | 51.2 | 16.21 | 0.00 | 0.00 | 0.56 | 71.7 | 0.0 |
| C | S4 | sampled | 117.0 | 14.90 | 4.44 | 0.00 | 0.00 | 85.0 | 0.0 |
| C | S4 | unsampled | 51.2 | 0.00 | 0.00 | 0.00 | 0.45 | 62.9 | 0.0 |
| S | S1 | sampled | 91.5 | 1.77 | 1.72 | 0.00 | 0.06 | 20.0 | 0.0 |
| S | S1 | unsampled | 39.6 | 1.81 | 1.77 | 0.00 | 0.45 | 10.7 | 39.6 |
| S | S2 | sampled | 91.5 | 1.09 | 1.89 | 0.00 | 0.10 | 19.4 | 0.0 |
| S | S2 | unsampled | 39.6 | 0.00 | 0.00 | 0.00 | 0.19 | 6.3 | 0.0 |
| S | S3 | sampled | 91.5 | 13.38 | 4.76 | 0.00 | 0.00 | 35.2 | 0.0 |
| S | S3 | unsampled | 39.6 | 13.56 | 0.00 | 0.00 | 0.74 | 22.0 | 0.0 |
| S | S4 | sampled | 91.5 | 12.87 | 4.91 | 0.00 | 0.00 | 34.6 | 0.0 |
| S | S4 | unsampled | 39.6 | 0.00 | 0.00 | 0.00 | 0.95 | 8.0 | 0.0 |
| S | S1-h0 | sampled | 91.5 | 2.25 | 1.88 | 0.07 | 0.07 | 20.6 | 0.0 |
| S | S1-h0 | unsampled | 39.6 | 2.32 | 1.98 | 0.36 | 0.36 | 11.3 | 39.6 |
| S | S1-h5 | sampled | 91.5 | 1.67 | 1.70 | 0.00 | 0.06 | 19.9 | 0.0 |
| S | S1-h5 | unsampled | 39.6 | 1.73 | 1.76 | 0.00 | 0.45 | 10.6 | 39.6 |

Source: `evidence/out/paper2-ext-sampling-v1/runs.json` (sha256 e920868baf65) (field `by_class`).

## Site C throughput: access or downstream grain handling?

| Share | Layout | Completed unloading trucks | Unfinished at closing, at a hopper | Hopper waiting (min) | Approach queue (time-avg) |
|---|---|---|---|---|---|
| 0.3 | S1 | 153.4 | 14.2 | 56.9 | 0.02 |
| 0.3 | S2 | 153.3 | 14.2 | 59.2 | 0.00 |
| 0.3 | S3 | 150.6 | 17.2 | 54.6 | 0.31 |
| 0.3 | S4 | 151.2 | 16.1 | 56.6 | 0.20 |
| 0.7 | S1 | 148.7 | 18.6 | 52.6 | 0.05 |
| 0.7 | S2 | 146.1 | 21.4 | 52.0 | 0.03 |
| 0.7 | S3 | 147.3 | 20.3 | 45.8 | 3.98 |
| 0.7 | S4 | 150.9 | 16.2 | 51.5 | 2.89 |
| 1 | S1 | 153.3 | 14.1 | 57.4 | 0.09 |
| 1 | S2 | 153.3 | 14.1 | 57.4 | 0.09 |
| 1 | S3 | 144.0 | 5.1 | 12.1 | 21.33 |
| 1 | S4 | 144.0 | 5.1 | 12.1 | 21.33 |

Per-seed paired changes: completed trucks against trucks left waiting at a hopper at closing:

| Share | Comparison | Mean change in completed | Mean change in unfinished at a hopper | Correlation across seeds |
|---|---|---|---|---|
| 0.3 | S4 - S3 | 0.7 | -1.1 | -0.99 |
| 0.3 | S2 - S1 | -0.1 | 0.0 | -0.99 |
| 0.3 | S3 - S1 | -2.9 | 3.0 | -1.00 |
| 0.7 | S4 - S3 | 3.5 | -4.0 | -1.00 |
| 0.7 | S2 - S1 | -2.6 | 2.7 | -0.99 |
| 0.7 | S3 - S1 | -1.4 | 1.6 | -1.00 |
| 1 | S4 - S3 | 0.0 | 0.0 | – |
| 1 | S2 - S1 | 0.0 | 0.0 | – |
| 1 | S3 - S1 | -9.3 | -9.0 | -0.60 |

Controlled Site S (no downstream constraint), completed trucks at share 0.7: S1 131.2, S2 131.2, S3 131.2, S4 131.2, S1-h0 131.2, S1-h5 131.2; hopper waiting in every Site S cell: max 0.00 min.

Interpretation rule used in this report: a throughput difference on Site C is attributed to truck access only where it is not accompanied by a matching change in trucks left waiting at the hoppers; Site S shows the access effect with downstream handling removed.

## Paired comparisons (by seed; common arrivals, sampling requirements and service draws)

Holm adjustment over 406 tested comparisons. Outcome counts: descriptive (CI includes 0): 145, no difference in any pair: 238, nominal only (CI excludes 0; not after Holm): 92, not applicable (no trucks of this class): 70, supported (Holm p < 0.05): 169. Listed: supported and nominal results; everything else is descriptive (`paired_comparisons.csv`).

| Site | Share | Comparison (effect) | Metric | Mean difference | 95% CI | p (Holm) | Support |
|---|---|---|---|---|---|---|---|
| A | 0.3 | S2 - S1 (bypass, separate sampler) | Weighbridge waiting, sampled trucks (min) | 0.11 | [0.07, 0.14] | 0.0019 | supported (Holm p < 0.05) |
| A | 0.3 | S2 - S1 (bypass, separate sampler) | Weighbridge waiting, unsampled trucks (min) | 0.09 | [0.06, 0.13] | 0.0051 | supported (Holm p < 0.05) |
| A | 0.3 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, unsampled (min) | -0.18 | [-0.22, -0.15] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, sampled (min) | -0.13 | [-0.17, -0.08] | 0.0012 | supported (Holm p < 0.05) |
| A | 0.3 | S2 - S1 (bypass, separate sampler) | Sampler queue (excl. road blocking), unsampled (min) | -0.22 | [-0.25, -0.19] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S2 - S1 (bypass, separate sampler) | Approach queue length (time-average) (trucks) | -0.02 | [-0.03, -0.02] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Weighbridge waiting, unsampled trucks (min) | 0.12 | [0.09, 0.14] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, unsampled (min) | -0.23 | [-0.28, -0.18] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, sampled (min) | -0.03 | [-0.05, -0.00] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| A | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Approach queue length (time-average) (trucks) | -0.01 | [-0.01, -0.00] | 0.2253 | nominal only (CI excludes 0; not after Holm) |
| A | 0.3 | S3 - S1 (location, no bypass) | Sampler waiting, sampled trucks (min) | 0.58 | [0.45, 0.71] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S3 - S1 (location, no bypass) | Weighbridge waiting, sampled trucks (min) | -0.01 | [-0.03, -0.00] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| A | 0.3 | S3 - S1 (location, no bypass) | Weighbridge waiting, unsampled trucks (min) | 0.06 | [0.03, 0.08] | 0.0335 | supported (Holm p < 0.05) |
| A | 0.3 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, unsampled (min) | 0.05 | [0.01, 0.09] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| A | 0.3 | S3 - S1 (location, no bypass) | Sampler queue (excl. road blocking), unsampled (min) | -0.22 | [-0.25, -0.19] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S3 - S1 (location, no bypass) | Approach queue length (time-average) (trucks) | 0.01 | [0.01, 0.02] | 0.0335 | supported (Holm p < 0.05) |
| A | 0.3 | S3 - S1 (location, no bypass) | Weighbridge bays busy (fraction) | 0.03 | [0.02, 0.03] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S3 - S1 (location, no bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.03 | [0.02, 0.03] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S4 - S2 (location, with bypass) | Sampler waiting, sampled trucks (min) | 0.58 | [0.46, 0.70] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S4 - S2 (location, with bypass) | Weighbridge waiting, sampled trucks (min) | -0.12 | [-0.16, -0.08] | 0.0006 | supported (Holm p < 0.05) |
| A | 0.3 | S4 - S2 (location, with bypass) | Weighbridge waiting, unsampled trucks (min) | 0.08 | [0.05, 0.11] | 0.0036 | supported (Holm p < 0.05) |
| A | 0.3 | S4 - S2 (location, with bypass) | Physically blocked behind another truck, sampled (min) | 0.13 | [0.08, 0.18] | 0.0031 | supported (Holm p < 0.05) |
| A | 0.3 | S4 - S2 (location, with bypass) | Approach queue length (time-average) (trucks) | 0.03 | [0.03, 0.03] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S4 - S2 (location, with bypass) | Weighbridge bays busy (fraction) | 0.03 | [0.02, 0.03] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.3 | S4 - S2 (location, with bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.03 | [0.02, 0.03] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.7 | S2 - S1 (bypass, separate sampler) | Sampler waiting, sampled trucks (min) | 0.03 | [0.01, 0.05] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| A | 0.7 | S2 - S1 (bypass, separate sampler) | Weighbridge waiting, sampled trucks (min) | 0.01 | [0.00, 0.02] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| A | 0.7 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, unsampled (min) | -0.33 | [-0.43, -0.23] | 0.0003 | supported (Holm p < 0.05) |
| A | 0.7 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, sampled (min) | -0.09 | [-0.12, -0.06] | 0.0002 | supported (Holm p < 0.05) |
| A | 0.7 | S2 - S1 (bypass, separate sampler) | Sampler queue (excl. road blocking), unsampled (min) | -0.40 | [-0.47, -0.33] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.7 | S2 - S1 (bypass, separate sampler) | Approach queue length (time-average) (trucks) | -0.02 | [-0.02, -0.02] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Weighbridge waiting, unsampled trucks (min) | 0.06 | [0.02, 0.11] | 0.9824 | nominal only (CI excludes 0; not after Holm) |
| A | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, unsampled (min) | -0.77 | [-1.01, -0.53] | 0.0005 | supported (Holm p < 0.05) |
| A | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Approach queue length (time-average) (trucks) | -0.02 | [-0.02, -0.01] | 0.0069 | supported (Holm p < 0.05) |
| A | 0.7 | S3 - S1 (location, no bypass) | Sampler waiting, sampled trucks (min) | 1.06 | [0.91, 1.20] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.7 | S3 - S1 (location, no bypass) | Weighbridge waiting, sampled trucks (min) | -0.01 | [-0.02, -0.01] | 0.0666 | nominal only (CI excludes 0; not after Holm) |
| A | 0.7 | S3 - S1 (location, no bypass) | Weighbridge waiting, unsampled trucks (min) | 0.07 | [0.04, 0.09] | 0.0071 | supported (Holm p < 0.05) |
| A | 0.7 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, unsampled (min) | 0.44 | [0.24, 0.64] | 0.0417 | supported (Holm p < 0.05) |
| A | 0.7 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, sampled (min) | 0.44 | [0.21, 0.67] | 0.1755 | nominal only (CI excludes 0; not after Holm) |
| A | 0.7 | S3 - S1 (location, no bypass) | Sampler queue (excl. road blocking), unsampled (min) | -0.40 | [-0.47, -0.33] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.7 | S3 - S1 (location, no bypass) | Approach queue length (time-average) (trucks) | 0.08 | [0.06, 0.11] | 0.0008 | supported (Holm p < 0.05) |
| A | 0.7 | S3 - S1 (location, no bypass) | Weighbridge bays busy (fraction) | 0.07 | [0.06, 0.07] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.7 | S3 - S1 (location, no bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.07 | [0.06, 0.07] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.7 | S4 - S2 (location, with bypass) | Sampler waiting, sampled trucks (min) | 1.05 | [0.89, 1.20] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.7 | S4 - S2 (location, with bypass) | Weighbridge waiting, sampled trucks (min) | -0.02 | [-0.04, -0.01] | 0.1876 | nominal only (CI excludes 0; not after Holm) |
| A | 0.7 | S4 - S2 (location, with bypass) | Weighbridge waiting, unsampled trucks (min) | 0.12 | [0.07, 0.17] | 0.0222 | supported (Holm p < 0.05) |
| A | 0.7 | S4 - S2 (location, with bypass) | Physically blocked behind another truck, sampled (min) | 0.52 | [0.29, 0.75] | 0.0363 | supported (Holm p < 0.05) |
| A | 0.7 | S4 - S2 (location, with bypass) | Approach queue length (time-average) (trucks) | 0.09 | [0.06, 0.11] | 0.0001 | supported (Holm p < 0.05) |
| A | 0.7 | S4 - S2 (location, with bypass) | Weighbridge bays busy (fraction) | 0.07 | [0.06, 0.07] | 0.0000 | supported (Holm p < 0.05) |
| A | 0.7 | S4 - S2 (location, with bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.07 | [0.06, 0.07] | 0.0000 | supported (Holm p < 0.05) |
| A | 1 | S3 - S1 (location, no bypass) | Sampler waiting, sampled trucks (min) | 1.46 | [1.29, 1.62] | 0.0000 | supported (Holm p < 0.05) |
| A | 1 | S3 - S1 (location, no bypass) | Weighbridge waiting, sampled trucks (min) | -0.01 | [-0.02, -0.01] | 0.0981 | nominal only (CI excludes 0; not after Holm) |
| A | 1 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, sampled (min) | 1.63 | [0.65, 2.62] | 0.4782 | nominal only (CI excludes 0; not after Holm) |
| A | 1 | S3 - S1 (location, no bypass) | Approach queue length (time-average) (trucks) | 0.24 | [0.13, 0.35] | 0.0515 | nominal only (CI excludes 0; not after Holm) |
| A | 1 | S3 - S1 (location, no bypass) | Weighbridge bays busy (fraction) | 0.10 | [0.09, 0.10] | 0.0000 | supported (Holm p < 0.05) |
| A | 1 | S3 - S1 (location, no bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.10 | [0.09, 0.10] | 0.0000 | supported (Holm p < 0.05) |
| A | 1 | S4 - S2 (location, with bypass) | Sampler waiting, sampled trucks (min) | 1.46 | [1.29, 1.62] | 0.0000 | supported (Holm p < 0.05) |
| A | 1 | S4 - S2 (location, with bypass) | Weighbridge waiting, sampled trucks (min) | -0.01 | [-0.02, -0.01] | 0.0981 | nominal only (CI excludes 0; not after Holm) |
| A | 1 | S4 - S2 (location, with bypass) | Physically blocked behind another truck, sampled (min) | 1.63 | [0.65, 2.62] | 0.4782 | nominal only (CI excludes 0; not after Holm) |
| A | 1 | S4 - S2 (location, with bypass) | Approach queue length (time-average) (trucks) | 0.24 | [0.13, 0.35] | 0.0515 | nominal only (CI excludes 0; not after Holm) |
| A | 1 | S4 - S2 (location, with bypass) | Weighbridge bays busy (fraction) | 0.10 | [0.09, 0.10] | 0.0000 | supported (Holm p < 0.05) |
| A | 1 | S4 - S2 (location, with bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.10 | [0.09, 0.10] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S2 - S1 (bypass, separate sampler) | Sampler waiting, sampled trucks (min) | -0.03 | [-0.04, -0.01] | 0.0511 | nominal only (CI excludes 0; not after Holm) |
| C | 0.3 | S2 - S1 (bypass, separate sampler) | Weighbridge waiting, sampled trucks (min) | 0.04 | [0.00, 0.07] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.3 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, unsampled (min) | -0.03 | [-0.04, -0.01] | 0.1158 | nominal only (CI excludes 0; not after Holm) |
| C | 0.3 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, sampled (min) | -0.02 | [-0.03, -0.01] | 0.0044 | supported (Holm p < 0.05) |
| C | 0.3 | S2 - S1 (bypass, separate sampler) | Sampler queue (excl. road blocking), unsampled (min) | -0.07 | [-0.08, -0.05] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S2 - S1 (bypass, separate sampler) | Approach queue length (time-average) (trucks) | -0.02 | [-0.02, -0.01] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Sampler waiting, sampled trucks (min) | 0.05 | [0.00, 0.10] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, unsampled (min) | -0.77 | [-1.19, -0.35] | 0.2061 | nominal only (CI excludes 0; not after Holm) |
| C | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, sampled (min) | -0.11 | [-0.19, -0.02] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Approach queue length (time-average) (trucks) | -0.11 | [-0.17, -0.05] | 0.2305 | nominal only (CI excludes 0; not after Holm) |
| C | 0.3 | S3 - S1 (location, no bypass) | Sampler waiting, sampled trucks (min) | 1.61 | [1.39, 1.82] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S3 - S1 (location, no bypass) | Weighbridge waiting, sampled trucks (min) | -0.12 | [-0.15, -0.09] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S3 - S1 (location, no bypass) | Weighbridge waiting, unsampled trucks (min) | 0.17 | [0.13, 0.21] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, unsampled (min) | 0.75 | [0.34, 1.16] | 0.2323 | nominal only (CI excludes 0; not after Holm) |
| C | 0.3 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, sampled (min) | 0.66 | [0.20, 1.12] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.3 | S3 - S1 (location, no bypass) | Sampler queue (excl. road blocking), unsampled (min) | -0.07 | [-0.08, -0.05] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S3 - S1 (location, no bypass) | Approach queue length (time-average) (trucks) | 0.29 | [0.18, 0.39] | 0.0046 | supported (Holm p < 0.05) |
| C | 0.3 | S3 - S1 (location, no bypass) | Weighbridge bays busy (fraction) | 0.06 | [0.06, 0.07] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S3 - S1 (location, no bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.06 | [0.06, 0.07] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S4 - S2 (location, with bypass) | Sampler waiting, sampled trucks (min) | 1.68 | [1.46, 1.91] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S4 - S2 (location, with bypass) | Weighbridge waiting, sampled trucks (min) | -0.16 | [-0.20, -0.11] | 0.0001 | supported (Holm p < 0.05) |
| C | 0.3 | S4 - S2 (location, with bypass) | Weighbridge waiting, unsampled trucks (min) | 0.19 | [0.13, 0.25] | 0.0005 | supported (Holm p < 0.05) |
| C | 0.3 | S4 - S2 (location, with bypass) | Physically blocked behind another truck, sampled (min) | 0.57 | [0.19, 0.96] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.3 | S4 - S2 (location, with bypass) | Approach queue length (time-average) (trucks) | 0.20 | [0.14, 0.25] | 0.0001 | supported (Holm p < 0.05) |
| C | 0.3 | S4 - S2 (location, with bypass) | Weighbridge bays busy (fraction) | 0.07 | [0.06, 0.07] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.3 | S4 - S2 (location, with bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.07 | [0.06, 0.07] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, unsampled (min) | -0.06 | [-0.09, -0.03] | 0.0568 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, sampled (min) | -0.03 | [-0.04, -0.02] | 0.0105 | supported (Holm p < 0.05) |
| C | 0.7 | S2 - S1 (bypass, separate sampler) | Sampler queue (excl. road blocking), unsampled (min) | -0.18 | [-0.21, -0.14] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S2 - S1 (bypass, separate sampler) | Approach queue length (time-average) (trucks) | -0.02 | [-0.02, -0.01] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Sampler waiting, sampled trucks (min) | 0.15 | [0.12, 0.18] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Weighbridge waiting, unsampled trucks (min) | -0.11 | [-0.18, -0.04] | 0.6525 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, unsampled (min) | -16.21 | [-23.54, -8.88] | 0.0437 | supported (Holm p < 0.05) |
| C | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, sampled (min) | -0.68 | [-1.19, -0.18] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Hopper waiting (tip), all unloading trucks (min) | 5.76 | [0.22, 11.31] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Approach queue length (time-average) (trucks) | -1.09 | [-1.65, -0.53] | 0.1330 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S3 - S1 (location, no bypass) | Turnaround, sampled trucks (min) | 11.69 | [2.34, 21.04] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S3 - S1 (location, no bypass) | Sampler waiting, sampled trucks (min) | 4.12 | [3.83, 4.41] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S3 - S1 (location, no bypass) | Weighbridge waiting, sampled trucks (min) | -0.08 | [-0.09, -0.06] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S3 - S1 (location, no bypass) | Weighbridge waiting, unsampled trucks (min) | 0.37 | [0.30, 0.45] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, unsampled (min) | 16.15 | [8.83, 23.46] | 0.0443 | supported (Holm p < 0.05) |
| C | 0.7 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, sampled (min) | 15.51 | [7.50, 23.52] | 0.1407 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S3 - S1 (location, no bypass) | Sampler queue (excl. road blocking), unsampled (min) | -0.18 | [-0.21, -0.14] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S3 - S1 (location, no bypass) | Approach queue length (time-average) (trucks) | 3.94 | [2.05, 5.82] | 0.0731 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S3 - S1 (location, no bypass) | Weighbridge bays busy (fraction) | 0.15 | [0.14, 0.16] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S3 - S1 (location, no bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.15 | [0.14, 0.16] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S4 - S2 (location, with bypass) | Turnaround, sampled trucks (min) | 15.80 | [7.91, 23.70] | 0.1070 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S4 - S2 (location, with bypass) | Sampler waiting, sampled trucks (min) | 4.27 | [3.97, 4.58] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S4 - S2 (location, with bypass) | Weighbridge waiting, sampled trucks (min) | -0.10 | [-0.13, -0.07] | 0.0003 | supported (Holm p < 0.05) |
| C | 0.7 | S4 - S2 (location, with bypass) | Weighbridge waiting, unsampled trucks (min) | 0.30 | [0.23, 0.38] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S4 - S2 (location, with bypass) | Physically blocked behind another truck, sampled (min) | 14.86 | [7.24, 22.48] | 0.1333 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S4 - S2 (location, with bypass) | Unfinished at closing, waiting at a hopper (trucks) | -5.10 | [-9.63, -0.57] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S4 - S2 (location, with bypass) | Approach queue length (time-average) (trucks) | 2.86 | [1.53, 4.19] | 0.0561 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S4 - S2 (location, with bypass) | Completed unloading trucks (trucks/day) | 4.85 | [0.15, 9.55] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S4 - S2 (location, with bypass) | Grain received (t/day) | 162.34 | [13.23, 311.44] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 0.7 | S4 - S2 (location, with bypass) | Weighbridge bays busy (fraction) | 0.16 | [0.15, 0.17] | 0.0000 | supported (Holm p < 0.05) |
| C | 0.7 | S4 - S2 (location, with bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.16 | [0.15, 0.17] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S3 - S1 (location, no bypass) | Turnaround, sampled trucks (min) | 48.24 | [38.53, 57.95] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S3 - S1 (location, no bypass) | Sampler waiting, sampled trucks (min) | 5.01 | [4.94, 5.09] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S3 - S1 (location, no bypass) | Weighbridge waiting, sampled trucks (min) | -0.05 | [-0.06, -0.04] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, sampled (min) | 99.54 | [84.78, 114.29] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S3 - S1 (location, no bypass) | Hopper waiting (tip), all unloading trucks (min) | -45.29 | [-53.54, -37.04] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S3 - S1 (location, no bypass) | Unfinished at closing, waiting at a hopper (trucks) | -9.00 | [-15.09, -2.91] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 1 | S3 - S1 (location, no bypass) | Approach queue length (time-average) (trucks) | 21.24 | [17.59, 24.89] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S3 - S1 (location, no bypass) | Completed unloading trucks (trucks/day) | -9.35 | [-15.38, -3.32] | 0.7814 | nominal only (CI excludes 0; not after Holm) |
| C | 1 | S3 - S1 (location, no bypass) | Grain received (t/day) | -270.80 | [-464.59, -77.01] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 1 | S3 - S1 (location, no bypass) | Weighbridge bays busy (fraction) | 0.18 | [0.17, 0.18] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S3 - S1 (location, no bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.18 | [0.17, 0.18] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S4 - S2 (location, with bypass) | Turnaround, sampled trucks (min) | 48.24 | [38.53, 57.95] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S4 - S2 (location, with bypass) | Sampler waiting, sampled trucks (min) | 5.01 | [4.94, 5.09] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S4 - S2 (location, with bypass) | Weighbridge waiting, sampled trucks (min) | -0.05 | [-0.06, -0.04] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S4 - S2 (location, with bypass) | Physically blocked behind another truck, sampled (min) | 99.54 | [84.78, 114.29] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S4 - S2 (location, with bypass) | Hopper waiting (tip), all unloading trucks (min) | -45.29 | [-53.54, -37.04] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S4 - S2 (location, with bypass) | Unfinished at closing, waiting at a hopper (trucks) | -9.00 | [-15.09, -2.91] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 1 | S4 - S2 (location, with bypass) | Approach queue length (time-average) (trucks) | 21.24 | [17.59, 24.89] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S4 - S2 (location, with bypass) | Completed unloading trucks (trucks/day) | -9.35 | [-15.38, -3.32] | 0.7814 | nominal only (CI excludes 0; not after Holm) |
| C | 1 | S4 - S2 (location, with bypass) | Grain received (t/day) | -270.80 | [-464.59, -77.01] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| C | 1 | S4 - S2 (location, with bypass) | Weighbridge bays busy (fraction) | 0.18 | [0.17, 0.18] | 0.0000 | supported (Holm p < 0.05) |
| C | 1 | S4 - S2 (location, with bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.18 | [0.17, 0.18] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S2 - S1 (bypass, separate sampler) | Turnaround, sampled trucks (min) | -0.24 | [-0.37, -0.10] | 0.2759 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S2 - S1 (bypass, separate sampler) | Turnaround, unsampled trucks (min) | -1.74 | [-2.09, -1.38] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S2 - S1 (bypass, separate sampler) | Sampler waiting, sampled trucks (min) | 0.05 | [0.01, 0.09] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S2 - S1 (bypass, separate sampler) | Weighbridge waiting, sampled trucks (min) | 0.10 | [0.06, 0.15] | 0.0171 | supported (Holm p < 0.05) |
| S | 0.3 | S2 - S1 (bypass, separate sampler) | Weighbridge waiting, unsampled trucks (min) | -0.11 | [-0.15, -0.06] | 0.0325 | supported (Holm p < 0.05) |
| S | 0.3 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, unsampled (min) | -0.35 | [-0.54, -0.15] | 0.2738 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, sampled (min) | -0.27 | [-0.43, -0.11] | 0.3996 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S2 - S1 (bypass, separate sampler) | Sampler queue (excl. road blocking), unsampled (min) | -0.66 | [-0.77, -0.55] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S2 - S1 (bypass, separate sampler) | Approach queue length (time-average) (trucks) | -0.12 | [-0.16, -0.08] | 0.0015 | supported (Holm p < 0.05) |
| S | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Turnaround, sampled trucks (min) | -0.17 | [-0.32, -0.03] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Turnaround, unsampled trucks (min) | -0.74 | [-1.14, -0.34] | 0.2066 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Weighbridge waiting, unsampled trucks (min) | 0.21 | [0.06, 0.35] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, unsampled (min) | -0.86 | [-1.31, -0.41] | 0.1673 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, sampled (min) | -0.14 | [-0.24, -0.04] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S4 - S3 (bypass, sampler at weighbridge) | Approach queue length (time-average) (trucks) | -0.08 | [-0.11, -0.04] | 0.1162 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S3 - S1 (location, no bypass) | Turnaround, sampled trucks (min) | 2.64 | [1.93, 3.35] | 0.0001 | supported (Holm p < 0.05) |
| S | 0.3 | S3 - S1 (location, no bypass) | Sampler waiting, sampled trucks (min) | 1.45 | [1.23, 1.66] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S3 - S1 (location, no bypass) | Weighbridge waiting, sampled trucks (min) | -0.09 | [-0.12, -0.06] | 0.0033 | supported (Holm p < 0.05) |
| S | 0.3 | S3 - S1 (location, no bypass) | Weighbridge waiting, unsampled trucks (min) | 0.17 | [0.12, 0.23] | 0.0004 | supported (Holm p < 0.05) |
| S | 0.3 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, unsampled (min) | 0.51 | [0.24, 0.79] | 0.1946 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, sampled (min) | 0.49 | [0.24, 0.74] | 0.1282 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S3 - S1 (location, no bypass) | Sampler queue (excl. road blocking), unsampled (min) | -0.66 | [-0.77, -0.55] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S3 - S1 (location, no bypass) | Approach queue length (time-average) (trucks) | 0.14 | [0.08, 0.19] | 0.0098 | supported (Holm p < 0.05) |
| S | 0.3 | S3 - S1 (location, no bypass) | Weighbridge bays busy (fraction) | 0.10 | [0.09, 0.11] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S3 - S1 (location, no bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.10 | [0.09, 0.11] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S4 - S2 (location, with bypass) | Turnaround, sampled trucks (min) | 2.70 | [2.00, 3.40] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S4 - S2 (location, with bypass) | Turnaround, unsampled trucks (min) | 0.98 | [0.60, 1.36] | 0.0096 | supported (Holm p < 0.05) |
| S | 0.3 | S4 - S2 (location, with bypass) | Sampler waiting, sampled trucks (min) | 1.45 | [1.22, 1.68] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S4 - S2 (location, with bypass) | Weighbridge waiting, sampled trucks (min) | -0.19 | [-0.24, -0.13] | 0.0002 | supported (Holm p < 0.05) |
| S | 0.3 | S4 - S2 (location, with bypass) | Weighbridge waiting, unsampled trucks (min) | 0.49 | [0.30, 0.68] | 0.0083 | supported (Holm p < 0.05) |
| S | 0.3 | S4 - S2 (location, with bypass) | Physically blocked behind another truck, sampled (min) | 0.62 | [0.34, 0.89] | 0.0361 | supported (Holm p < 0.05) |
| S | 0.3 | S4 - S2 (location, with bypass) | Approach queue length (time-average) (trucks) | 0.19 | [0.13, 0.24] | 0.0002 | supported (Holm p < 0.05) |
| S | 0.3 | S4 - S2 (location, with bypass) | Weighbridge bays busy (fraction) | 0.10 | [0.09, 0.11] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S4 - S2 (location, with bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.10 | [0.09, 0.11] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S1-h0 - S1 (holding: none vs 2) | Turnaround, sampled trucks (min) | 0.18 | [0.09, 0.27] | 0.1070 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S1-h0 - S1 (holding: none vs 2) | Turnaround, unsampled trucks (min) | 0.09 | [0.04, 0.14] | 0.2566 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S1-h0 - S1 (holding: none vs 2) | Sampler waiting, sampled trucks (min) | 0.11 | [0.07, 0.14] | 0.0012 | supported (Holm p < 0.05) |
| S | 0.3 | S1-h0 - S1 (holding: none vs 2) | Weighbridge waiting, unsampled trucks (min) | -0.09 | [-0.14, -0.05] | 0.0316 | supported (Holm p < 0.05) |
| S | 0.3 | S1-h0 - S1 (holding: none vs 2) | Physically blocked behind another truck, unsampled (min) | 0.13 | [0.05, 0.20] | 0.3531 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S1-h0 - S1 (holding: none vs 2) | Physically blocked behind another truck, sampled (min) | 0.12 | [0.04, 0.19] | 0.9207 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S1-h0 - S1 (holding: none vs 2) | Sampler queue (excl. road blocking), unsampled (min) | 0.11 | [0.08, 0.13] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S1-h0 - S1 (holding: none vs 2) | Blocked in sampler bay by full holding, sampled (min) | 0.08 | [0.05, 0.10] | 0.0011 | supported (Holm p < 0.05) |
| S | 0.3 | S1-h0 - S1 (holding: none vs 2) | Blocked in sampler bay by full holding, unsampled (min) | 0.27 | [0.24, 0.30] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.3 | S1-h0 - S1 (holding: none vs 2) | Approach queue length (time-average) (trucks) | 0.04 | [0.02, 0.05] | 0.0186 | supported (Holm p < 0.05) |
| S | 0.3 | S1-h5 - S1 (holding: 5 vs 2) | Sampler waiting, sampled trucks (min) | -0.03 | [-0.05, -0.00] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S1-h5 - S1 (holding: 5 vs 2) | Weighbridge waiting, unsampled trucks (min) | 0.03 | [0.01, 0.05] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 0.3 | S1-h5 - S1 (holding: 5 vs 2) | Sampler queue (excl. road blocking), unsampled (min) | -0.02 | [-0.04, -0.01] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S2 - S1 (bypass, separate sampler) | Turnaround, sampled trucks (min) | -0.54 | [-0.79, -0.29] | 0.0638 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S2 - S1 (bypass, separate sampler) | Turnaround, unsampled trucks (min) | -4.43 | [-5.20, -3.67] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S2 - S1 (bypass, separate sampler) | Sampler waiting, sampled trucks (min) | 0.17 | [0.12, 0.22] | 0.0004 | supported (Holm p < 0.05) |
| S | 0.7 | S2 - S1 (bypass, separate sampler) | Weighbridge waiting, sampled trucks (min) | 0.03 | [0.02, 0.05] | 0.2907 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S2 - S1 (bypass, separate sampler) | Weighbridge waiting, unsampled trucks (min) | -0.25 | [-0.31, -0.19] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, unsampled (min) | -1.81 | [-2.47, -1.16] | 0.0036 | supported (Holm p < 0.05) |
| S | 0.7 | S2 - S1 (bypass, separate sampler) | Physically blocked behind another truck, sampled (min) | -0.68 | [-0.95, -0.41] | 0.0110 | supported (Holm p < 0.05) |
| S | 0.7 | S2 - S1 (bypass, separate sampler) | Sampler queue (excl. road blocking), unsampled (min) | -1.77 | [-1.92, -1.62] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S2 - S1 (bypass, separate sampler) | Approach queue length (time-average) (trucks) | -0.23 | [-0.30, -0.16] | 0.0007 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Turnaround, sampled trucks (min) | -0.60 | [-1.06, -0.15] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Turnaround, unsampled trucks (min) | -14.05 | [-20.22, -7.88] | 0.0332 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Sampler waiting, sampled trucks (min) | 0.15 | [0.10, 0.20] | 0.0020 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Weighbridge waiting, unsampled trucks (min) | 0.22 | [0.03, 0.41] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, unsampled (min) | -13.56 | [-19.58, -7.54] | 0.0363 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Physically blocked behind another truck, sampled (min) | -0.51 | [-0.90, -0.13] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S4 - S3 (bypass, sampler at weighbridge) | Approach queue length (time-average) (trucks) | -0.69 | [-1.05, -0.34] | 0.1389 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S3 - S1 (location, no bypass) | Turnaround, sampled trucks (min) | 15.26 | [9.20, 21.31] | 0.0110 | supported (Holm p < 0.05) |
| S | 0.7 | S3 - S1 (location, no bypass) | Turnaround, unsampled trucks (min) | 11.34 | [5.71, 16.96] | 0.1012 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S3 - S1 (location, no bypass) | Sampler waiting, sampled trucks (min) | 3.04 | [2.83, 3.25] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S3 - S1 (location, no bypass) | Weighbridge waiting, sampled trucks (min) | -0.06 | [-0.07, -0.05] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S3 - S1 (location, no bypass) | Weighbridge waiting, unsampled trucks (min) | 0.29 | [0.23, 0.35] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, unsampled (min) | 11.75 | [6.31, 17.19] | 0.0543 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, sampled (min) | 11.61 | [5.73, 17.49] | 0.1202 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S3 - S1 (location, no bypass) | Sampler queue (excl. road blocking), unsampled (min) | -1.77 | [-1.92, -1.62] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S3 - S1 (location, no bypass) | Approach queue length (time-average) (trucks) | 2.24 | [1.13, 3.34] | 0.0980 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S3 - S1 (location, no bypass) | Weighbridge bays busy (fraction) | 0.24 | [0.23, 0.25] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S3 - S1 (location, no bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.24 | [0.23, 0.25] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S2 (location, with bypass) | Turnaround, sampled trucks (min) | 15.19 | [9.22, 21.17] | 0.0099 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S2 (location, with bypass) | Turnaround, unsampled trucks (min) | 1.72 | [1.31, 2.14] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S2 (location, with bypass) | Sampler waiting, sampled trucks (min) | 3.02 | [2.82, 3.22] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S2 (location, with bypass) | Weighbridge waiting, sampled trucks (min) | -0.10 | [-0.12, -0.07] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S2 (location, with bypass) | Weighbridge waiting, unsampled trucks (min) | 0.76 | [0.56, 0.96] | 0.0001 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S2 (location, with bypass) | Physically blocked behind another truck, sampled (min) | 11.77 | [5.92, 17.63] | 0.1033 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S4 - S2 (location, with bypass) | Approach queue length (time-average) (trucks) | 1.78 | [0.96, 2.60] | 0.0523 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S4 - S2 (location, with bypass) | Weighbridge bays busy (fraction) | 0.24 | [0.23, 0.25] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S4 - S2 (location, with bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.24 | [0.23, 0.25] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S1-h0 - S1 (holding: none vs 2) | Turnaround, sampled trucks (min) | 0.63 | [0.32, 0.94] | 0.0981 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S1-h0 - S1 (holding: none vs 2) | Turnaround, unsampled trucks (min) | 0.58 | [0.27, 0.88] | 0.1633 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S1-h0 - S1 (holding: none vs 2) | Sampler waiting, sampled trucks (min) | 0.16 | [0.13, 0.20] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S1-h0 - S1 (holding: none vs 2) | Weighbridge waiting, unsampled trucks (min) | -0.08 | [-0.12, -0.05] | 0.0181 | supported (Holm p < 0.05) |
| S | 0.7 | S1-h0 - S1 (holding: none vs 2) | Physically blocked behind another truck, unsampled (min) | 0.51 | [0.20, 0.81] | 0.4511 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S1-h0 - S1 (holding: none vs 2) | Physically blocked behind another truck, sampled (min) | 0.48 | [0.19, 0.78] | 0.5352 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S1-h0 - S1 (holding: none vs 2) | Sampler queue (excl. road blocking), unsampled (min) | 0.21 | [0.16, 0.26] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S1-h0 - S1 (holding: none vs 2) | Blocked in sampler bay by full holding, sampled (min) | 0.07 | [0.05, 0.08] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S1-h0 - S1 (holding: none vs 2) | Blocked in sampler bay by full holding, unsampled (min) | 0.36 | [0.32, 0.40] | 0.0000 | supported (Holm p < 0.05) |
| S | 0.7 | S1-h0 - S1 (holding: none vs 2) | Approach queue length (time-average) (trucks) | 0.11 | [0.05, 0.17] | 0.1673 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S1-h5 - S1 (holding: 5 vs 2) | Sampler waiting, sampled trucks (min) | -0.02 | [-0.03, -0.01] | 0.4025 | nominal only (CI excludes 0; not after Holm) |
| S | 0.7 | S1-h5 - S1 (holding: 5 vs 2) | Sampler queue (excl. road blocking), unsampled (min) | -0.02 | [-0.03, -0.00] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 1 | S3 - S1 (location, no bypass) | Turnaround, sampled trucks (min) | 75.98 | [64.24, 87.72] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S3 - S1 (location, no bypass) | Sampler waiting, sampled trucks (min) | 3.09 | [2.88, 3.30] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S3 - S1 (location, no bypass) | Weighbridge waiting, sampled trucks (min) | -0.02 | [-0.03, -0.01] | 0.0029 | supported (Holm p < 0.05) |
| S | 1 | S3 - S1 (location, no bypass) | Physically blocked behind another truck, sampled (min) | 78.29 | [64.68, 91.91] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S3 - S1 (location, no bypass) | Unfinished at closing, waiting at a hopper (trucks) | 1.10 | [0.73, 1.47] | 0.0015 | supported (Holm p < 0.05) |
| S | 1 | S3 - S1 (location, no bypass) | Approach queue length (time-average) (trucks) | 12.97 | [10.41, 15.54] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S3 - S1 (location, no bypass) | Completed unloading trucks (trucks/day) | -9.90 | [-14.55, -5.25] | 0.0617 | nominal only (CI excludes 0; not after Holm) |
| S | 1 | S3 - S1 (location, no bypass) | Grain received (t/day) | -307.70 | [-453.51, -161.88] | 0.0667 | nominal only (CI excludes 0; not after Holm) |
| S | 1 | S3 - S1 (location, no bypass) | Weighbridge bays busy (fraction) | 0.29 | [0.28, 0.31] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S3 - S1 (location, no bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.29 | [0.28, 0.31] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S4 - S2 (location, with bypass) | Turnaround, sampled trucks (min) | 75.98 | [64.24, 87.72] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S4 - S2 (location, with bypass) | Sampler waiting, sampled trucks (min) | 3.09 | [2.88, 3.30] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S4 - S2 (location, with bypass) | Weighbridge waiting, sampled trucks (min) | -0.02 | [-0.03, -0.01] | 0.0029 | supported (Holm p < 0.05) |
| S | 1 | S4 - S2 (location, with bypass) | Physically blocked behind another truck, sampled (min) | 78.29 | [64.68, 91.91] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S4 - S2 (location, with bypass) | Unfinished at closing, waiting at a hopper (trucks) | 1.10 | [0.73, 1.47] | 0.0015 | supported (Holm p < 0.05) |
| S | 1 | S4 - S2 (location, with bypass) | Approach queue length (time-average) (trucks) | 12.97 | [10.41, 15.54] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S4 - S2 (location, with bypass) | Completed unloading trucks (trucks/day) | -9.90 | [-14.55, -5.25] | 0.0617 | nominal only (CI excludes 0; not after Holm) |
| S | 1 | S4 - S2 (location, with bypass) | Grain received (t/day) | -307.70 | [-453.51, -161.88] | 0.0667 | nominal only (CI excludes 0; not after Holm) |
| S | 1 | S4 - S2 (location, with bypass) | Weighbridge bays busy (fraction) | 0.29 | [0.28, 0.31] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S4 - S2 (location, with bypass) | Weighbridge bays occupied (incl. sampling at bay and blocking) (fraction) | 0.29 | [0.28, 0.31] | 0.0000 | supported (Holm p < 0.05) |
| S | 1 | S1-h0 - S1 (holding: none vs 2) | Turnaround, sampled trucks (min) | 0.41 | [0.11, 0.70] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 1 | S1-h0 - S1 (holding: none vs 2) | Sampler waiting, sampled trucks (min) | 0.03 | [0.02, 0.04] | 0.0542 | nominal only (CI excludes 0; not after Holm) |
| S | 1 | S1-h0 - S1 (holding: none vs 2) | Physically blocked behind another truck, sampled (min) | 0.38 | [0.09, 0.66] | 1.0000 | nominal only (CI excludes 0; not after Holm) |
| S | 1 | S1-h0 - S1 (holding: none vs 2) | Blocked in sampler bay by full holding, sampled (min) | 0.02 | [0.01, 0.02] | 0.0024 | supported (Holm p < 0.05) |
| S | 1 | S1-h0 - S1 (holding: none vs 2) | Approach queue length (time-average) (trucks) | 0.07 | [0.02, 0.12] | 1.0000 | nominal only (CI excludes 0; not after Holm) |

Source: `evidence/out/paper2-ext-sampling-v1/paired_comparisons.json` (sha256 e9c108a5df31).

## Figures

| Figure | Shows | Basis |
|---|---|---|
| `figures/site_A_turnaround_unsampled.svg` | Site A: mean turnaround of unsampled trucks by layout and sampled share, mean ± 95% CI | 20 seeds per bar, common random numbers; differences judged from the paired table, not overlapping whiskers |
| `figures/site_A_turnaround_sampled.svg` | Site A: mean turnaround of sampled trucks by layout and sampled share, mean ± 95% CI | 20 seeds per bar, common random numbers; differences judged from the paired table, not overlapping whiskers |
| `figures/site_A_blocked_unsampled.svg` | Site A: time unsampled trucks were physically blocked behind another truck by layout and sampled share, mean ± 95% CI | 20 seeds per bar, common random numbers; differences judged from the paired table, not overlapping whiskers |
| `figures/site_C_turnaround_unsampled.svg` | Site C: mean turnaround of unsampled trucks by layout and sampled share, mean ± 95% CI | 20 seeds per bar, common random numbers; differences judged from the paired table, not overlapping whiskers |
| `figures/site_C_turnaround_sampled.svg` | Site C: mean turnaround of sampled trucks by layout and sampled share, mean ± 95% CI | 20 seeds per bar, common random numbers; differences judged from the paired table, not overlapping whiskers |
| `figures/site_C_blocked_unsampled.svg` | Site C: time unsampled trucks were physically blocked behind another truck by layout and sampled share, mean ± 95% CI | 20 seeds per bar, common random numbers; differences judged from the paired table, not overlapping whiskers |
| `figures/site_S_turnaround_unsampled.svg` | Site S: mean turnaround of unsampled trucks by layout and sampled share, mean ± 95% CI | 20 seeds per bar, common random numbers; differences judged from the paired table, not overlapping whiskers |
| `figures/site_S_turnaround_sampled.svg` | Site S: mean turnaround of sampled trucks by layout and sampled share, mean ± 95% CI | 20 seeds per bar, common random numbers; differences judged from the paired table, not overlapping whiskers |
| `figures/site_S_blocked_unsampled.svg` | Site S: time unsampled trucks were physically blocked behind another truck by layout and sampled share, mean ± 95% CI | 20 seeds per bar, common random numbers; differences judged from the paired table, not overlapping whiskers |

## Limitations

- Provisional assumptions O1-O11 (unconfirmed): no travel times, sampling then weighing at a probe bay without overlap, drive-through time 0.3-1.0 min, bypass lanes hold no trucks, no staff discretion, grading result awaited in the yard.
- A bypass into a holding place promised to the truck being sampled gives no benefit under `reserve_next_space` (tested); the experiment's S2 bypass therefore leads to the weighbridge.
- Throughput on Site C is partly driven by downstream grain dynamics: access layouts change the order in which trucks reach the hoppers, and pit-compatibility waits depend on that order (most trucks unfinished at closing wait at the hoppers).
- Synthetic sites and demand; one queue-policy mapping; one day; one platform. No empirical validation.

