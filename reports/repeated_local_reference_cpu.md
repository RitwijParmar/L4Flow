# L4Flow repeated local reference benchmark

- Model: `hf-internal-testing/tiny-random-gpt2`
- Device: `cpu`
- Workload: 128 requests × 5 trials per strategy
- Generated: 2026-09-26T03:30:34.903795+00:00

| Strategy | Batch | Requests | p50 ms | p95 ms | p99 ms | Requests/s | Tokens/s | 95% throughput CI | SLO pass |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| serial_baseline | 1 | 640 | 6.255 | 9.480 | 19.275 | 143.740 | 1149.924 | [131.267, 157.733] | 100% |
| micro_batch_2 | 2 | 640 | 8.746 | 12.059 | 16.087 | 219.696 | 1757.569 | [208.448, 230.801] | 100% |
| micro_batch_4 | 4 | 640 | 11.381 | 15.616 | 20.498 | 340.951 | 2727.610 | [325.042, 353.128] | 80% |
| micro_batch_8 | 8 | 640 | 17.343 | 23.006 | 41.140 | 451.949 | 3615.592 | [424.762, 471.629] | 0% |

Recommended strategy: **micro_batch_2** under the declared SLO.
Throughput change: **1.528x** (95% CI for trial speedup [1.422, 1.629]).
Token-throughput change: **52.84%**.
P95 latency change: **-27.20%** (positive means lower p95).

The workload, raw request rows, repeated trials, and confidence interval inputs are committed with this report.
These are local reference measurements, not Cloud Run L4 results or billing data.
