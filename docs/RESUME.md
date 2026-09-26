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
- Added an 18-test regression suite covering trace normalization, gate pass and
  fail decisions, routing, fallback, metrics, API headers, and benchmark
  reports.

## Verified local performance evidence

The committed report in `reports/local_reference_cpu.md` records a real local
reference run using `hf-internal-testing/tiny-random-gpt2`, 16 requests, batch
size 4, and an explicit 15 ms p95 SLO:

- request throughput increased from 186.864 to 508.765 requests/s: **2.72x**;
- generated-token throughput increased from 1,494.909 to 4,070.120 tokens/s:
  **172.27%**;
- p95 latency remained under the SLO for both strategies: 6.117 ms and
  8.824 ms.

Resume bullet for this exact local result:

    Built an engine-agnostic inference release gate and benchmarked serial vs micro-batched Transformers inference on a CPU reference path; improved throughput 2.72x (186.9 to 508.8 requests/s) and token throughput 172.3% (1,494.9 to 4,070.1 tokens/s) while keeping both p95 latencies under a 15 ms SLO.

Alternative systems-focused bullet:

    Built a black-box LLM serving regression gate that normalizes OpenAI-compatible traces and blocks releases on p95 latency, streamed TTFT, error-rate, and cost regressions across SGLang/vLLM-style endpoints; added JSON/Markdown evidence reports and 18 regression tests.

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
