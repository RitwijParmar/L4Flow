# L4Flow repeated local reference benchmark

- Model: `hf-internal-testing/tiny-random-gpt2`
- Device: `cpu`
- Workload: 128 requests × 5 trials per strategy
- Generated: 2026-09-26T03:41:09.805788+00:00

| Strategy | Batch | Requests | p50 ms | p95 ms | p99 ms | Requests/s | Tokens/s | 95% throughput CI | SLO pass |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| serial_baseline | 1 | 640 | 5.892 | 7.689 | 8.641 | 163.535 | 1308.282 | [158.947, 167.499] | 100% |
| micro_batch_2 | 2 | 640 | 9.388 | 13.147 | 21.731 | 201.865 | 1614.922 | [185.026, 218.867] | 80% |
| micro_batch_4 | 4 | 640 | 11.424 | 14.574 | 16.180 | 347.712 | 2781.699 | [333.420, 363.913] | 100% |
| micro_batch_8 | 8 | 640 | 16.459 | 20.228 | 70.772 | 463.041 | 3704.328 | [427.641, 508.966] | 40% |

Recommended strategy: **micro_batch_4** under the declared SLO.
Throughput change: **2.126x** (95% CI for trial speedup [2.006, 2.227]).
Token-throughput change: **112.62%**.
P95 latency change: **-89.54%** (positive means lower p95).

The workload, raw request rows, repeated trials, and confidence interval inputs are committed with this report.
These are local reference measurements, not Cloud Run L4 results or billing data.
