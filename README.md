# L4Flow

L4Flow is a cost-aware, cold-start-aware LLM inference gateway for Google Cloud Run GPU. It exposes one OpenAI-compatible endpoint and chooses a CPU-first or GPU route using request size, output budget, GPU readiness, and in-flight pressure.

The project is intentionally an inference-systems benchmark, not a chatbot. The primary result is a reproducible comparison of:

1. always CPU;
2. always GPU;
3. adaptive routing with fallback and saturation handling.

## Local quickstart

```bash
cd L4Flow
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn l4flow.app:app --reload --port 8080
```

The default `dry-run` mode uses deterministic mock backends so the routing logic can be tested without downloading a model or spending cloud credits.

```bash
curl -s http://127.0.0.1:8080/healthz | jq
curl -i -s http://127.0.0.1:8080/v1/chat/completions -H 'content-type: application/json' -d '{"model":"l4flow-router","messages":[{"role":"user","content":"hello"}],"max_tokens":64}'
l4flow-benchmark --url http://127.0.0.1:8080 --requests 20 --concurrency 4 --policies auto,cpu,gpu --output reports/local-benchmark.json --markdown-output reports/local-benchmark.md
```

Run the tests with:

```bash
pytest -q
```

## Verified local improvement

Run the real local reference benchmark with the optional Transformers dependencies:

    python -m pip install -e '.[local-benchmark]'
    python benchmarks/local_reference.py --device cpu --requests 16 --batch-size 4 --max-new-tokens 8 --p95-slo-ms 15 --json-output reports/local_reference_cpu.json --markdown-output reports/local_reference_cpu.md

The committed report measured 2.72x request-throughput improvement and 172.27% token-throughput improvement from micro-batching, with both strategies under the 15 ms p95 SLO. These are local CPU reference metrics from the tiny-random-gpt2 checkpoint; they are not Cloud Run L4 results.

## Routing contract

The gateway accepts standard `/v1/chat/completions` JSON. For controlled experiments, set `x-l4flow-route` to `auto`, `cpu`, or `gpu`. Every successful response includes:

- `x-l4flow-route`: actual backend used;
- `x-l4flow-reason`: policy decision;
- `x-l4flow-estimated-prompt-tokens`: cheap pre-tokenization estimate;
- `x-l4flow-latency-ms`: end-to-end gateway latency;
- `x-l4flow-fallback: true` when a GPU failure was served by CPU.

/metrics exposes Prometheus-compatible counters. /metrics/summary returns machine-readable route mix, decision reasons, p50/p95 latency, fallback rate, token totals, and estimated cost per 1,000 completion tokens.

## GCP deployment

The Terraform path creates:

- an internal Cloud Run L4/vLLM inference service with `min_instance_count=0` and `max_instance_count=1`;
- a CPU Cloud Run router with a bounded maximum instance count;
- service-to-service Cloud Run identity-token authentication;
- no public exposure of the GPU backend.

The router is public in the starter Terraform for easy demo access. Before a real deployment, replace the `allUsers` invoker grant with an authenticated caller or an API gateway.

Prerequisites:

```bash
gcloud auth login
export PROJECT_ID="your-project-id"
export REGION="us-east4"
./infra/scripts/deploy.sh
```

The GPU service uses one NVIDIA L4 with no zonal redundancy, and the deployment bounds it to one instance. Confirm GPU quota and configure a billing budget before applying Terraform. GPU instances can scale to zero, but an active GPU instance is billed for its full lifecycle.

## Resume metrics

The repository includes resume evidence and claim boundaries in docs/RESUME.md. The code can produce strong performance metrics, but live latency, throughput, GPU utilization, and savings must come from a real GCP run. Dry-run numbers are only routing/observability tests and should not be presented as GPU performance.

## Evaluation plan

The benchmark report should record at least:

- p50/p95 latency and time-to-first-token;
- completion tokens/second;
- cold-start delay;
- GPU utilization and in-flight queue pressure;
- failures and fallback rate;
- cost per 1,000 output tokens;
- SLO violations under bursty load.

Do not claim savings until the three policies are run against the same prompt set, concurrency schedule, region, model, and output budget.
