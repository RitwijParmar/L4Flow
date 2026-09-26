# L4Flow inference FinOps report

- Rate card: `cloud-run-request-based-us-east4-on-demand-l4`
- Region: `us-east4`
- Billing model: `request-based`
- Billing quantum: `0.100s`
- Evidence scope: `modeled_cost_from_trace_and_rate_card`

| Strategy | Resource groups | p95 ms | Output tokens | Gross cost | Cost / 1K output tok | SLO |
|---|---:|---:|---:|---:|---:|---|
| micro_batch_2 | 320 | 13.147 | 5120 | $0.00060800 | $0.000119 | PASS |
| micro_batch_4 | 160 | 14.574 | 5120 | $0.00030400 | $0.000059 | PASS |
| micro_batch_8 | 80 | 20.228 | 5120 | $0.00015200 | $0.000030 | FAIL |
| serial_baseline | 640 | 7.689 | 5120 | $0.00121600 | $0.000237 | PASS |

Recommendation: **micro_batch_4** at $0.000059/1K output tokens among SLO-passing strategies.

Modeled cost is not a billing export. Reconcile with Cloud Billing export or Cloud Monitoring before reporting spend.
