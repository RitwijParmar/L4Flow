#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to the GCP project that owns your credits}"
: "${REGION:=us-east4}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO="${REGION}-docker.pkg.dev/${PROJECT_ID}/l4flow"

gcloud config set project "${PROJECT_ID}"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
gcloud artifacts repositories create l4flow --repository-format=docker --location="${REGION}" 2>/dev/null || true

gcloud builds submit "${ROOT_DIR}" --tag "${REPO}/l4flow-router:latest" --project "${PROJECT_ID}"

gcloud builds submit "${ROOT_DIR}" --config=- --project "${PROJECT_ID}" <<EOF
steps:
- name: gcr.io/cloud-builders/docker
  args: [build, -f, Dockerfile.gpu, -t, ${REPO}/l4flow-vllm:latest, .]
images: [${REPO}/l4flow-vllm:latest]
options:
  machineType: E2_HIGHCPU_8
EOF

cd "${ROOT_DIR}/infra/terraform"
terraform init
terraform apply -var="project_id=${PROJECT_ID}" -var="region=${REGION}" -var="router_image=${REPO}/l4flow-router:latest" -var="inference_image=${REPO}/l4flow-vllm:latest"
