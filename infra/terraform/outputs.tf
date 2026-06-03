output "cluster_name" {
  description = "Name of the Kind cluster"
  value       = kind_cluster.this.name
}

output "kubeconfig_path" {
  description = "Path to the kubeconfig file"
  value       = pathexpand("~/.kube/config")
}

output "namespaces" {
  description = "Namespaces created in the cluster"
  value       = [for ns in kubernetes_namespace.namespaces : ns.metadata[0].name]
}

output "jobs_api_service_account" {
  description = "ServiceAccount created for jobs-api"
  value       = kubernetes_service_account.jobs_api.metadata[0].name
}
