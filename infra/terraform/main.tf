provider "kind" {}

provider "kubernetes" {
  host                   = kind_cluster.this.endpoint
  client_certificate     = kind_cluster.this.client_certificate
  client_key             = kind_cluster.this.client_key
  cluster_ca_certificate = kind_cluster.this.cluster_ca_certificate
}

# ── Kind Cluster ─────────────────────────────────────────────────
resource "kind_cluster" "this" {
  name            = var.cluster_name
  kubeconfig_path = pathexpand("~/.kube/config")
  wait_for_ready  = true

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    node {
      role = "control-plane"
    }

    node {
      role = "worker"
    }
  }
}

# ── Namespaces ───────────────────────────────────────────────────
resource "kubernetes_namespace" "namespaces" {
  for_each = toset(var.namespaces)

  metadata {
    name = each.key

    labels = {
      "managed-by" = "terraform"
      "project"    = "sre-platform-demo"
    }
  }

  depends_on = [kind_cluster.this]
}

# ── ServiceAccount for jobs-api ──────────────────────────────────
resource "kubernetes_service_account" "jobs_api" {
  metadata {
    name      = "jobs-api"
    namespace = kubernetes_namespace.namespaces["app"].metadata[0].name

    labels = {
      "managed-by" = "terraform"
      "app"        = "jobs-api"
    }
  }

  depends_on = [kubernetes_namespace.namespaces]
}

# ── RBAC — Role ──────────────────────────────────────────────────
resource "kubernetes_role" "jobs_api" {
  metadata {
    name      = "jobs-api-role"
    namespace = kubernetes_namespace.namespaces["app"].metadata[0].name
  }

  rule {
    api_groups = [""]
    resources  = ["pods", "services", "endpoints"]
    verbs      = ["get", "list", "watch"]
  }

  depends_on = [kubernetes_namespace.namespaces]
}

# ── RBAC — RoleBinding ───────────────────────────────────────────
resource "kubernetes_role_binding" "jobs_api" {
  metadata {
    name      = "jobs-api-rolebinding"
    namespace = kubernetes_namespace.namespaces["app"].metadata[0].name
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.jobs_api.metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.jobs_api.metadata[0].name
    namespace = kubernetes_namespace.namespaces["app"].metadata[0].name
  }

  depends_on = [kubernetes_role.jobs_api]
}
