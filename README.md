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