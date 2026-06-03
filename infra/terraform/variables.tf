variable "cluster_name" {
  description = "Name of the Kind cluster"
  type        = string
  default     = "sre-platform"
}

variable "namespaces" {
  description = "Namespaces to create in the cluster"
  type        = list(string)
  default     = ["app", "observability"]
}
