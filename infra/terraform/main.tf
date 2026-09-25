terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "run" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifact_registry" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_service_account" "router" {
  account_id   = "l4flow-router"
  display_name = "L4Flow router service identity"
}

resource "google_cloud_run_v2_service" "inference" {
  name                = "l4flow-inference"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = false

  template {
    service_account = google_service_account.router.email
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    max_instance_request_concurrency = 4
    gpu_zonal_redundancy_disabled    = true

    containers {
      image   = var.inference_image
      command = ["python3", "-m", "vllm.entrypoints.openai.api_server"]
      args = [
        "--host", "0.0.0.0",
        "--port", "8080",
        "--model", var.model_name,
        "--max-model-len", "4096",
        "--dtype", "auto",
      ]
      resources {
        limits = {
          cpu              = "4"
          memory           = "16Gi"
          "nvidia.com/gpu" = "1"
        }
        cpu_idle = false
      }
    }
  }

  depends_on = [google_project_service.run]
}

resource "google_cloud_run_v2_service_iam_member" "inference_invoker" {
  name     = google_cloud_run_v2_service.inference.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.router.email}"
}

resource "google_cloud_run_v2_service" "router" {
  name                = "l4flow-router"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.router.email
    scaling {
      min_instance_count = 0
      max_instance_count = var.router_max_instances
    }
    max_instance_request_concurrency = 20

    containers {
      image = var.router_image
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }
      env {
        name  = "L4FLOW_MODE"
        value = "http"
      }
      env {
        name  = "GPU_BACKEND_URL"
        value = google_cloud_run_v2_service.inference.uri
      }
      env {
        name  = "GPU_BACKEND_AUDIENCE"
        value = google_cloud_run_v2_service.inference.uri
      }
      env {
        name  = "GPU_BACKEND_AUTH"
        value = "id_token"
      }
      env {
        name  = "FALLBACK_TO_CPU"
        value = "false"
      }
    }
  }

  depends_on = [google_project_service.run, google_cloud_run_v2_service_iam_member.inference_invoker]
}

resource "google_cloud_run_v2_service_iam_member" "router_invoker" {
  name     = google_cloud_run_v2_service.router.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
