# L4Flow local reference benchmark

- Model: hf-internal-testing/tiny-random-gpt2
- Device: cpu
- Requests: 16
- Generated: 2026-09-25T22:13:40.368275+00:00

| Strategy | Batch | p50 ms | p95 ms | Requests/s | Tokens/s |
|---|---:|---:|---:|---:|---:|
| Serial baseline | 1 | 5.108 | 6.117 | 186.864 | 1494.909 |
| Micro-batched | 4 | 7.765 | 8.824 | 508.765 | 4070.120 |

Measured throughput speedup: 2.72x.
Measured p95 latency change: -44.25% (positive means lower p95).
p95 SLO: 15.000 ms; serial=PASS, micro_batch=PASS.

These are local reference measurements and must not be presented as Cloud Run L4 results.
