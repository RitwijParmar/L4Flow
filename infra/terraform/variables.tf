variable "project_id" {
  type        = string
  description = "Google Cloud project hosting L4Flow."
}

variable "region" {
  type        = string
  description = "Cloud Run region with L4 GPU availability."
  default     = "us-east4"
}

variable "router_image" {
  type        = string
  description = "Container image for the L4Flow router."
}

variable "inference_image" {
  type        = string
  description = "Container image for the vLLM GPU backend."
}

variable "model_name" {
  type        = string
  default     = "Qwen/Qwen2.5-3B-Instruct"
}

variable "router_max_instances" {
  type        = number
  default     = 3
}
