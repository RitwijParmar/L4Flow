# L4Flow

L4Flow is an engine-agnostic inference SLO and cost regression gate for
OpenAI-compatible endpoints. It turns raw request traces into a release
decision: did the candidate deployment regress p95 latency, streamed TTFT,
error rate, or cost per 1,000 output tokens?

## Why this is not TickYantra

[TickYantra](https://github.com/RitwijParmar/TickYantra) is the live serving
control plane: it owns bounded admission, prefix affinity, adaptive SLO
feedback, and the SGLang request path.

L4Flow sits outside the serving engine. It does not implement admission,
continuous batching, prefix scheduling, KV-cache management, or model
execution. Instead, it evaluates any equivalent endpoint—SGLang, vLLM,
Vertex AI, or a Cloud Run service—from black-box traces and blocks a release
when the candidate violates a performance or cost policy. The two projects
can therefore be used together: TickYantra controls the path; L4Flow verifies
the path across deployments.

```text
SGLang / vLLM / Vertex / Cloud Run endpoint
                    |
                    v
             JSONL request traces
                    |
                    v
       L4Flow normalize -> summarize -> gate
                    |
             PASS / FAIL + evidence
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
| Serial baseline | 9.480 | 19.275 | 143.740 | 1,149.924 | 5/5 |
| Micro-batch 2 | 12.059 | 16.087 | 219.696 | 1,757.569 | 5/5 |
| Micro-batch 4 | 15.616 | 20.498 | 340.951 | 2,727.610 | 4/5 |
| Micro-batch 8 | 23.006 | 41.140 | 451.949 | 3,615.592 | 0/5 |

The SLO-constrained recommendation is micro-batch 2: **1.528x throughput**
(95% trial-speedup CI **[1.422, 1.629]**), **52.84% higher token throughput**,
and **34.57% lower compute-seconds per 1,000 output tokens**. Larger batches
were faster but failed the 20 ms p95 gate: batch 4 passed only 4/5 trials and
batch 8 passed 0/5. This is a measured tradeoff, not a blanket “batching is
better” claim.

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
