# Resume evidence for L4Flow

## Safe to claim now

These claims are supported by the current source tree and test suite:

- Built an OpenAI-compatible LLM inference gateway with CPU-first/GPU escalation, explicit route overrides, GPU saturation handling, fallback behavior, and request correlation IDs.
- Implemented a three-policy benchmark (auto, cpu, gpu) that reports p50/p95 latency, failure rate, route mix, completion tokens/second, estimated cost per 1,000 output tokens, and workload-class breakdown.
- Added Prometheus-compatible metrics plus a JSON summary endpoint covering route counts, decision reasons, fallback rate, token totals, latency, and estimated serving cost.
- Added Cloud Run/Terraform guardrails: GPU scale-to-zero, maximum one GPU instance, private GPU ingress, and service-to-service identity-token authentication.
- Added a 13-test regression suite covering routing decisions, saturation, fallback selection, API headers, metrics, benchmark reports, and cost accounting.

## Verified local improvement

The committed report in reports/local_reference_cpu.md records a real local reference run using the safe tiny-random-gpt2 checkpoint, 16 requests, batch size 4, and an explicit 15 ms p95 SLO:

- throughput increased from 186.864 to 508.765 requests/second: 2.72x;
- generated-token throughput increased from 1,494.909 to 4,070.120 tokens/second: 172.27%;
- p95 latency remained under the 15 ms SLO for both serial and micro-batched strategies: 6.117 ms and 8.824 ms.

Resume bullet for this exact local result:

    Benchmarked serial vs micro-batched Transformers inference on a CPU reference path; improved throughput 2.72x (186.9 to 508.8 requests/s) and token throughput 172.3% (1,494.9 to 4,070.1 tokens/s) while keeping p95 latency under a 15 ms SLO.

## Do not claim until a live GCP run is completed

Do not invent throughput, latency, savings, or GPU-utilization numbers. The project is intentionally prepared to produce them, but this repository does not yet contain a live GCP benchmark result.

After a live run, use the generated report to fill this bullet:

    Benchmarked L4Flow across [N] requests at concurrency [C] on [region] with [model], achieving [p95] ms p95 latency and [tok/s] completion throughput; adaptive routing sent [GPU share]% of traffic to GPU and reduced estimated cost per 1K output tokens by [X]% versus always-GPU, at [success rate]% success.

Run the report with:

    l4flow-benchmark --url "$L4FLOW_URL" --requests 300 --concurrency 16 --policies auto,cpu,gpu --output reports/live-benchmark.json --markdown-output reports/live-benchmark.md

Only copy values from reports/live-benchmark.md into the resume after checking that all policies used the same model, region, workload, output budget, and concurrency.
