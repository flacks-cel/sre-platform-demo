# About This Project

## SRE Platform Demo

**Author:** Flávio Lacks

## Why I Created This Project

I created the SRE Platform Demo to demonstrate modern Site Reliability Engineering (SRE), DevOps and Platform Engineering practices in a practical and reproducible way.

Throughout my career, I have worked with automation, infrastructure, cloud platforms, CI/CD pipelines, observability and operational reliability. This project was designed to consolidate these concepts into a single platform that can be deployed, monitored and evolved using industry-standard tools and practices.

Rather than focusing on business features, the primary goal is to demonstrate how applications can be provisioned, deployed, monitored and operated using Infrastructure as Code and cloud-native technologies.

---

## What This Project Demonstrates

This project demonstrates:

* Infrastructure as Code (Terraform)
* Kubernetes platform provisioning
* Helm-based application deployments
* Docker containerization
* Application observability
* Metrics collection with Prometheus
* Dashboards with Grafana
* Health and readiness probes
* Horizontal Pod Autoscaling (HPA)
* SRE operational practices
* Git-based workflows and automation

Future phases will include:

* Loki log aggregation
* Alerting and monitoring rules
* GitHub Actions CI/CD
* Runbooks
* Incident simulation and recovery scenarios

---

## Project Architecture

The platform currently consists of:

```text
FastAPI Application
        ↓
Docker
        ↓
Kubernetes (Kind)
        ↓
Helm Deployment
        ↓
Prometheus
        ↓
Grafana
```

Infrastructure provisioning is managed through Terraform, while application deployment is managed through Helm charts.

---

## Why This Matters

Modern engineering teams are expected to deliver reliable, scalable and observable platforms.

This project reflects the same principles used in production environments:

* Automation over manual processes
* Infrastructure as Code
* Repeatable deployments
* Observability-first mindset
* Reliability and operational excellence

The goal is to showcase not only technical implementation, but also the mindset and practices required by modern SRE and Platform Engineering teams.

---

## Current Status

### Completed

* FastAPI application
* Automated testing
* Docker containerization
* Docker Compose environment
* Prometheus metrics
* Grafana dashboards
* Terraform provisioning
* Kind Kubernetes cluster
* Helm deployment
* Kubernetes health checks
* Horizontal Pod Autoscaler

### In Progress

* Kubernetes observability stack
* Loki integration
* Alerting
* CI/CD pipelines
* Runbooks

---

## About the Author

My name is Flávio Lacks and I work in DevOps and Site Reliability Engineering.

My professional focus includes:

* Cloud Platforms
* Kubernetes
* Terraform
* Infrastructure Automation
* CI/CD
* Observability
* Platform Engineering
* Operational Reliability

This repository represents my continuous learning journey and my commitment to building reliable and scalable platforms using modern engineering practices.
