# Resume evidence for L4Flow

## Project positioning

L4Flow is an inference FinOps and SLO cost-governor. It is intentionally
complementary to TickYantra: TickYantra changes the live SGLang serving path;
L4Flow attributes resource cost, forecasts budget burn, and selects a safe
operating policy from endpoint traces.

## Safe to claim now

These claims are supported by the current source tree and test suite:

- Built an engine-agnostic inference SLO/cost regression gate for
  OpenAI-compatible endpoints, normalizing JSONL traces from different
  serving stacks.
- Built a rate-card-driven FinOps analyzer that rounds Cloud Run resource
  groups to the billing quantum, charges shared micro-batches once, reports
  cost per request and per 1,000 output tokens, forecasts budget utilization,
  and recommends the cheapest SLO-passing strategy.
- Implemented release checks for p95 latency, p95 streamed TTFT, absolute
  error-rate increase, and estimated cost per 1,000 output tokens, with
  machine-readable JSON and Markdown evidence.
- Added an endpoint benchmark fixture with Prometheus-compatible metrics,
  route/fallback accounting, token totals, and estimated serving cost.
- Added Cloud Run/Terraform guardrails for an optional experiment target:
  GPU scale-to-zero, maximum one GPU instance, private GPU ingress, and
  service-to-service identity-token authentication.
- Added a 24-test regression suite covering workload validation, trace normalization, gate pass and
  fail decisions, cost allocation, budget forecasts, routing, fallback,
  metrics, API headers, and benchmark reports.

## Verified local performance evidence

The committed report in `reports/repeated_local_reference_cpu.md` records a
real local reference experiment using `hf-internal-testing/tiny-random-gpt2`,
a fixed 128-request workload, five trials per strategy, and a declared 20 ms
p95 SLO:

- micro-batch 4 improved throughput from 163.535 to 347.712 requests/s:
  **2.126x**, with a 95% trial-speedup CI of **[2.006, 2.227]**;
- generated-token throughput increased from 1,308.282 to 2,781.699 tokens/s:
  **112.62%**;
- compute-seconds per 1,000 output tokens fell from 0.764361 to 0.359493:
  **52.97% lower**;
- p95 latency increased from 7.689 ms to 14.574 ms, while all 5/5 trials
  passed the 20 ms p95 SLO.

The committed FinOps report in `reports/repeated_local_cost_cpu.md` applies
the versioned Cloud Run rate card to the same resource-group trace:

- modeled cost fell from $0.0002375 to $0.00005937 per 1K output tokens:
  **75% lower**;
- at the explicit scenario of 100,000 requests/day, monthly modeled spend
  fell from $5.70 to $1.425 against a $5 budget;
- batch 8 was cheaper but rejected because its aggregate p95 was 20.228 ms,
  above the 20 ms SLO.

These dollar values are rate-card estimates, not billing-export evidence.

Resume bullet for this exact local result:

    Built an inference FinOps/SLO cost governor and ran 2,560 trace-backed local requests across five trials and four batch policies; selected micro-batch 4 under a 20 ms p95 SLO, improving throughput 2.126x (95% CI 2.006–2.227), token throughput 112.62%, and compute efficiency 52.97% while passing the SLO in 5/5 trials.

Cost-focused bullet:

    Built a rate-card-driven inference FinOps analyzer that allocated shared Cloud Run resource groups, modeled 100 ms billing, forecast a $5.70-to-$1.425 monthly reduction at 100K requests/day, and selected a 75%-lower cost-per-1K-token policy without violating a 20 ms p95 SLO.

Alternative systems-focused bullet:

    Built a black-box LLM serving regression gate that normalizes OpenAI-compatible traces and blocks releases on p95 latency, streamed TTFT, error-rate, and cost regressions across SGLang/vLLM-style endpoints; added deterministic workload generation, raw per-request evidence, bootstrap confidence intervals, rate-card cost allocation, and 24 regression tests.

The throughput numbers are local CPU reference evidence. The dollar figures
are rate-card estimates, not a live GCP billing export.

## Do not claim until a live GCP run is completed

Do not invent throughput, latency, savings, utilization, or capacity numbers.
After a live run, use the captured trace and gate report to fill this bullet:

    Evaluated [N] equivalent requests across [baseline] and [candidate] on [region] with [model]; the release gate measured [p95] ms p95 latency, [TTFT] ms p95 TTFT, [success rate]% success, and $[cost]/1K output tokens, [passing/failing] the declared SLO policy.

Only copy values from a trace-backed report after checking that both runs used
the same prompt set, model, region, concurrency, output budget, and accounting
method.
