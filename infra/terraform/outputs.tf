output "router_url" {
  value       = google_cloud_run_v2_service.router.uri
  description = "Public L4Flow router URL."
}

output "inference_url" {
  value       = google_cloud_run_v2_service.inference.uri
  description = "Internal GPU backend URL."
}
