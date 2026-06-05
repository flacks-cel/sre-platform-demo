## Additional Documentation

- [Project Overview](docs/project-overview.md)
- [Architecture](docs/architecture.md)
- [Project Status](docs/project-status.md)

# SRE Platform Demo

A production-inspired SRE platform demonstrating modern DevOps and Site Reliability Engineering practices using FastAPI, Docker, Prometheus, Grafana, Terraform, Kubernetes, and Helm.

## Project Goals

This project was created to demonstrate:

- Infrastructure as Code (Terraform)
- Containerization with Docker
- Kubernetes orchestration
- Observability with Prometheus and Grafana
- CI/CD automation
- SRE best practices
- Health checks and readiness probes
- Automated testing and code quality

---

## Architecture

```text
FastAPI
   ↓
Prometheus
   ↓
Grafana

Terraform
   ↓
Kind Kubernetes Cluster
   ↓
Helm Deployments

## Observability

The platform includes a complete observability stack:

- Prometheus for metrics collection
- Grafana for visualization
- Loki for centralized logging
- Promtail for log shipping
- ServiceMonitor for automatic Prometheus discovery

### Custom Dashboard

The `jobs-api-observability` dashboard provides:

- Request Rate
- Error Percentage
- Jobs Created
- Latency p99

Dashboard definitions are versioned as code in:

observability/grafana/dashboards/jobs-api-observability.json