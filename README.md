# SRE Platform Demo

A production-inspired SRE platform demonstrating modern DevOps and Site Reliability Engineering practices using FastAPI, Docker, Prometheus, Grafana, Loki, Promtail, Terraform, Kubernetes Kind, Helm and GitHub Actions.

## Additional Documentation

* [Project Overview](docs/project-overview.md)
* [Architecture](docs/architecture.md)
* [Project Status](docs/project-status.md)

---

## Project Goals

This project was created to demonstrate:

* Infrastructure as Code with Terraform
* Containerization with Docker
* Kubernetes orchestration using Kind
* Observability with Prometheus, Grafana, Loki and Promtail
* Metrics collection and dashboard visualization
* Centralized application logging
* CI/CD automation with GitHub Actions
* Health checks and readiness probes
* Automated testing and code quality
* SRE-oriented troubleshooting and operational visibility

---

## Architecture

```text
FastAPI Jobs API
   ↓
Prometheus Metrics
   ↓
Grafana Dashboards

Application Logs
   ↓
Promtail
   ↓
Loki
   ↓
Grafana Logs Panel

Terraform
   ↓
Kind Kubernetes Cluster
   ↓
Helm Deployments
```

---

## Dashboard Preview

![Grafana Dashboard](docs/images/grafana-dashboard.png)

The Grafana dashboard provides visibility into:

* Request Rate
* Error Percentage
* Jobs Created
* Latency p99
* Application Logs

---

## Observability

The platform includes a complete observability stack:

* Prometheus for metrics collection
* Grafana for visualization
* Loki for centralized logging
* Promtail for log shipping
* Custom Grafana dashboards for application metrics and logs

### Custom Dashboards

Dashboard definitions are versioned as code in:

```text
observability/grafana/dashboards/
```

Available dashboards:

```text
jobs-api-observability.json
```

Dashboard for application metrics:

* Request Rate
* Error Percentage
* Jobs Created
* Latency p99

```text
jobs-api-logs-only.json
```

Dashboard for application logs using Loki.

---

## Quick Start

### Start the Environment

The environment can be started locally using Docker Compose and the observability stack.

```bash
docker compose up -d --build
```

For the full local demo environment, use the local startup script if available in your workstation:

```bash
./local/start-demo.sh
```

The local script is intentionally not versioned in Git because it contains machine-specific startup automation and port-forward commands.

---

## Access URLs

| Component  | URL                   |
| ---------- | --------------------- |
| Grafana    | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| API        | http://localhost:8000 |
| Loki       | http://localhost:3102 |

---

## Application Endpoints

| Endpoint                      | Description                   |
| ----------------------------- | ----------------------------- |
| `/health`                     | Health check endpoint         |
| `/ready`                      | Readiness check endpoint      |
| `/metrics`                    | Prometheus metrics endpoint   |
| `/jobs`                       | Job creation endpoint         |
| `/simulate/error`             | Simulates application errors  |
| `/simulate/latency?seconds=1` | Simulates application latency |

Example job creation:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"name":"demo-job","payload":{"source":"interview-demo"}}'
```

---

## Prometheus

Prometheus scrapes metrics from the `jobs-api` service.

The scrape configuration is located at:

```text
observability/prometheus/prometheus.yml
```

The `jobs-api` target can be validated at:

```text
http://localhost:9090/targets
```

Expected target status:

```text
jobs-api UP
```

---

## Observability Notes

Grafana dashboards rely on Prometheus metrics labeled with:

```yaml
namespace: app
```

The Prometheus scrape configuration injects this label into the `jobs-api` target:

```yaml
static_configs:
  - targets: ["jobs-api:8000"]
    labels:
      namespace: "app"
```

Several dashboard panels use PromQL filters such as:

```promql
http_requests_total{namespace="app"}
```

and:

```promql
http_request_duration_seconds_bucket{namespace="app"}
```

If this label is removed or renamed, Grafana panels may display **No Data** even when Prometheus is successfully scraping metrics.

---

## Loki and Application Logs

Application logs are collected by Promtail and sent to Loki.

Grafana accesses Loki using:

```text
http://host.docker.internal:3102
```

The logs dashboard displays application events such as:

* Health check requests
* Readiness check requests
* Job creation events
* Simulated errors
* Latency simulation requests

---

## Demo Data Generation

The local demo script generates sample observability data automatically, including:

* HTTP request traffic
* Job creation events
* Error simulation
* Latency simulation
* Application logs

This ensures that the Grafana dashboard is populated immediately after startup.

Useful manual commands:

```bash
for i in {1..20}; do curl http://localhost:8000/health; done
```

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"name":"demo-job","payload":{"source":"manual-test"}}'
```

```bash
curl http://localhost:8000/simulate/error
```

```bash
curl "http://localhost:8000/simulate/latency?seconds=1"
```

---

## Technology Stack

* FastAPI
* Python
* Docker
* Docker Compose
* Terraform
* Kubernetes Kind
* Helm
* Prometheus
* Grafana
* Loki
* Promtail
* GitHub Actions

---

## Repository Structure

```text
.
├── .github/workflows
├── app/api
├── docs
├── infra
├── observability
│   ├── grafana
│   └── prometheus
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## CI/CD

The project includes GitHub Actions workflows for:

* Automated validation
* Testing
* Code quality checks
* Container workflow preparation

Workflow files are located in:

```text
.github/workflows/
```

---

## SRE Concepts Demonstrated

This project demonstrates practical SRE and DevOps concepts:

* Service health checks
* Readiness probes
* Metrics-based monitoring
* Centralized logging
* Dashboard-driven observability
* Error rate tracking
* Latency percentile tracking
* Infrastructure automation
* Local Kubernetes experimentation
* Troubleshooting using Prometheus, Grafana and Loki

---

## License

This project is intended for educational and portfolio purposes.
