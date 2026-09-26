# L4Flow

L4Flow is an inference FinOps and SLO cost-governor for OpenAI-compatible
endpoints. It turns request traces plus an explicit Cloud Run rate card into a
cost allocation, budget forecast, and SLO-constrained deployment
recommendation: which serving policy meets the tail-latency target at the
lowest modeled cost per 1,000 output tokens?

## Why this is not TickYantra

[TickYantra](https://github.com/RitwijParmar/TickYantra) is the live serving
control plane: it owns bounded admission, prefix affinity, adaptive SLO
feedback, and the SGLang request path.

L4Flow sits outside the serving engine and owns the economics layer. It does
not implement admission, continuous batching, prefix scheduling, KV-cache
management, or model execution. It attributes shared resource groups once,
applies versioned CPU/memory/GPU rates, forecasts spend against a budget, and
selects the cheapest SLO-passing policy. The two projects can therefore be
used together: TickYantra controls the path; L4Flow decides whether the path
is financially safe to operate.

```text
SGLang / vLLM / Vertex / Cloud Run endpoint
                    |
                    v
             JSONL request traces + rate card
                    |
                    v
     L4Flow allocate -> forecast -> SLO/cost optimize
                    |
       PASS / FAIL + budget + recommendation
```

## Quickstart: run a release gate

```bash
cd L4Flow
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

l4flow-gate \
  examples/traces/baseline.jsonl \
  examples/traces/candidate.jsonl \
  --output reports/example-gate.json \
  --markdown-output reports/example-gate.md
```

The trace loader accepts common aliases such as `request_id`/`trace_id`,
`e2e_latency_ms`/`latency_ms`, and `prompt_tokens`/`input_tokens`, so a small
adapter can feed exports from different serving stacks into the same gate.

The gate checks:

- p95 end-to-end latency regression;
- p95 TTFT regression when both traces contain streamed TTFT;
- absolute error-rate increase;
- estimated cost per 1,000 output tokens.

## Cost and budget analysis

`l4flow-cost` is the primary FinOps artifact. It loads the raw trace and a
versioned rate card, rounds resource groups to the billing quantum, attributes
shared micro-batches once, forecasts monthly spend, and recommends the
lowest-cost strategy that still passes the p95 SLO.

```bash
l4flow-cost \
  reports/repeated_local_trace_cpu.jsonl \
  --rate-card examples/rate_cards/cloud_run_request_based_us_east4.json \
  --p95-slo-ms 20 \
  --requests-per-day 100000 \
  --days 30 \
  --budget-usd 5 \
  --output reports/repeated_local_cost_cpu.json \
  --markdown-output reports/repeated_local_cost_cpu.md
```

The example rate card records Cloud Run request-based on-demand rates,
including CPU, memory, NVIDIA L4, and 100 ms billing quantization. The official
source is [Cloud Run pricing](https://cloud.google.com/run/pricing); verify
the rate card before using it for a real invoice or credit balance. The local
experiment uses the CPU profile, so its dollar result is a modeled comparison,
not GPU billing.

On the committed trace, serial execution models at $0.0002375 per 1K output
tokens, while micro-batch 4 models at $0.00005937 per 1K output tokens: **75%
lower modeled cost** while still passing the 20 ms p95 SLO. At the explicit
scenario of 100,000 requests/day, that is $5.70/month for serial versus
$1.425/month for micro-batch 4 against a $5 budget. Micro-batch 8 is cheaper
but fails the SLO, so it is rejected by the recommendation logic.

Run the tests with:

```bash
pytest -q
```

## Optional endpoint benchmark

The repository also contains a small OpenAI-compatible endpoint fixture and a
client benchmark. This is an input producer for the observability layer, not
the project's serving contribution. In default `dry-run` mode it uses
deterministic mock backends and consumes no model or GPU credits.

```bash
uvicorn l4flow.app:app --reload --port 8080
l4flow-benchmark \
  --url http://127.0.0.1:8080 \
  --requests 20 \
  --concurrency 4 \
  --policies auto,cpu,gpu \
  --output reports/local-benchmark.json \
  --markdown-output reports/local-benchmark.md \
  --trace-dir reports/traces
```

The fixture exposes `/healthz`, `/metrics`, and `/metrics/summary` so an
experiment can collect route, token, latency, fallback, and estimated-cost
evidence without coupling the gate to a particular model server. With
`--trace-dir`, the same run also emits normalized JSONL traces that can be
passed directly to `l4flow-gate`.

## Verified local reference result

The committed repeated experiment uses a fixed 128-request workload with an
observed 67/40/21 short/medium/long mix (~52%/31%/16%), 71.88% shared-prefix
reuse, and five trials per strategy. That is 640 requests per strategy and
2,560 raw request rows across the batch-size sweep. The model is the safe
`hf-internal-testing/tiny-random-gpt2` checkpoint on CPU.

| Strategy | p95 ms | p99 ms | Requests/s | Tokens/s | 20 ms SLO trial pass rate |
|---|---:|---:|---:|---:|---:|
| Serial baseline | 7.689 | 8.641 | 163.535 | 1,308.282 | 5/5 |
| Micro-batch 2 | 13.147 | 21.731 | 201.865 | 1,614.922 | 4/5 |
| Micro-batch 4 | 14.574 | 16.180 | 347.712 | 2,781.699 | 5/5 |
| Micro-batch 8 | 20.228 | 70.772 | 463.041 | 3,704.328 | 2/5 |

The SLO-constrained recommendation is micro-batch 4: **2.126x throughput**
(95% trial-speedup CI **[2.006, 2.227]**), **112.62% higher token throughput**,
and **52.97% lower compute-seconds per 1,000 output tokens**, while passing the
20 ms p95 gate in 5/5 trials. Batch 8 was faster but passed only 2/5 trials.
This is a measured SLO/cost tradeoff, not a blanket “batching is better” claim.

The full evidence is committed in
`reports/repeated_local_reference_cpu.md`, the workload in
`reports/inference_workload_128.jsonl`, and the raw rows in
`reports/repeated_local_trace_cpu.jsonl`.

These are local reference measurements, not NVIDIA L4 or Cloud Run results.
A real cloud run is required before claiming GPU utilization, billing
savings, or cloud capacity improvements.

```bash
python -m pip install -e '.[local-benchmark]'
python benchmarks/local_reference.py \
  --device cpu \
  --requests 128 \
  --trials 5 \
  --batch-sizes 2,4,8 \
  --max-new-tokens 8 \
  --p95-slo-ms 20 \
  --seed 17 \
  --workload-output reports/inference_workload_128.jsonl \
  --trace-output reports/repeated_local_trace_cpu.jsonl \
  --json-output reports/repeated_local_reference_cpu.json \
  --markdown-output reports/repeated_local_reference_cpu.md
```

To generate only the deterministic workload data:

```bash
l4flow-workload --requests 128 --seed 17 --output reports/inference_workload_128.jsonl
```

## GCP integration

Terraform in `infra/terraform` provisions a bounded Cloud Run GPU endpoint and
an authenticated CPU-side service for producing real traces. It is an
optional experiment target; the release gate remains usable against any
already-running endpoint and does not require a GPU.

The deployment deliberately keeps the GPU service private, sets scale-to-zero
and a maximum instance count of one, and uses service-to-service identity
tokens. Configure a billing budget and verify GPU quota before applying it.

```bash
gcloud auth login
export PROJECT_ID="your-project-id"
export REGION="us-east4"
./infra/scripts/deploy.sh
```

Do not report cloud metrics until the trace, model, region, concurrency,
output budget, and billing evidence are stored with the run.

## Resume evidence

See [docs/RESUME.md](docs/RESUME.md) for evidence-ranked bullets and the
boundary between verified local results and pending GCP measurements.
