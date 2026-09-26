# Resume evidence for L4Flow

## Project positioning

L4Flow is the black-box verification layer for inference deployments. It is
intentionally complementary to TickYantra: TickYantra changes the live
SGLang serving path; L4Flow compares endpoint traces and makes a release
decision.

## Safe to claim now

These claims are supported by the current source tree and test suite:

- Built an engine-agnostic inference SLO/cost regression gate for
  OpenAI-compatible endpoints, normalizing JSONL traces from different
  serving stacks.
- Implemented release checks for p95 latency, p95 streamed TTFT, absolute
  error-rate increase, and estimated cost per 1,000 output tokens, with
  machine-readable JSON and Markdown evidence.
- Added an endpoint benchmark fixture with Prometheus-compatible metrics,
  route/fallback accounting, token totals, and estimated serving cost.
- Added Cloud Run/Terraform guardrails for an optional experiment target:
  GPU scale-to-zero, maximum one GPU instance, private GPU ingress, and
  service-to-service identity-token authentication.
- Added a 22-test regression suite covering workload validation, trace normalization, gate pass and
  fail decisions, routing, fallback, metrics, API headers, and benchmark
  reports.

## Verified local performance evidence

The committed report in `reports/repeated_local_reference_cpu.md` records a
real local reference experiment using `hf-internal-testing/tiny-random-gpt2`,
a fixed 128-request workload, five trials per strategy, and a declared 20 ms
p95 SLO:

- micro-batch 2 improved throughput from 143.740 to 219.696 requests/s:
  **1.528x**, with a 95% trial-speedup CI of **[1.422, 1.629]**;
- generated-token throughput increased from 1,149.924 to 1,757.569 tokens/s:
  **52.84%**;
- compute-seconds per 1,000 output tokens fell from 0.869623 to 0.568968:
  **34.57% lower**;
- p95 latency increased from 9.480 ms to 12.059 ms, but all 5/5 trials passed
  the 20 ms p95 SLO;
- larger batch 4 reached 2.372x throughput but passed the SLO in only 4/5
  trials; batch 8 reached 3.144x but passed 0/5 trials.

Resume bullet for this exact local result:

    Built an engine-agnostic inference release gate and ran 2,560 trace-backed local inference requests across five trials and four batch policies; selected micro-batch 2 under a 20 ms p95 SLO, improving throughput 1.528x (95% CI 1.422–1.629), token throughput 52.84%, and compute efficiency 34.57% while passing the SLO in 5/5 trials.

Alternative systems-focused bullet:

    Built a black-box LLM serving regression gate that normalizes OpenAI-compatible traces and blocks releases on p95 latency, streamed TTFT, error-rate, and cost regressions across SGLang/vLLM-style endpoints; added deterministic workload generation, raw per-request evidence, bootstrap confidence intervals, and 22 regression tests.

The first bullet's performance numbers are local CPU reference evidence. The
second bullet describes implemented behavior and does not imply a live GCP
result.

## Do not claim until a live GCP run is completed

Do not invent throughput, latency, savings, utilization, or capacity numbers.
After a live run, use the captured trace and gate report to fill this bullet:

    Evaluated [N] equivalent requests across [baseline] and [candidate] on [region] with [model]; the release gate measured [p95] ms p95 latency, [TTFT] ms p95 TTFT, [success rate]% success, and $[cost]/1K output tokens, [passing/failing] the declared SLO policy.

Only copy values from a trace-backed report after checking that both runs used
the same prompt set, model, region, concurrency, output budget, and accounting
method.
