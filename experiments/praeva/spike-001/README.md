# Praeva Spike 001 — CPU Evidence

This is an experiment harness, not product code.

## Question

Can Praeva obtain reproducible CPU evidence for `jobs-api` from the real local lab and explain exactly which pods, time window, scrape cadence, and rate window contributed to the numbers?

The spike deliberately does **not** classify risk, grade evidence quality, recommend capacity, or analyze HPA behavior.

## Lab defaults

The script defaults match the current `sre-platform-demo` lab:

- namespace: `app`
- workload: `jobs-api`
- container: `jobs-api`
- Prometheus: `http://localhost:9091`
- Jobs API: `http://localhost:8081`
- historical window: `6h`
- evaluation lag: `120s`
- CPU rate windows: `2m` and `5m`

The current Helm values define `cpu request=100m` and `cpu limit=500m`.

## Preconditions

Start the lab normally and verify:

```bash
kubectl get pods -n app
kubectl get hpa jobs-api -n app
curl http://localhost:9091/-/ready
curl http://localhost:8081/health
```

The `load` command also performs its own `/health` preflight and refuses to start if the Jobs API is unreachable. If any controlled load call fails after the round starts, the command stops, marks the round invalid, and exits non-zero.

## Time semantics

Prometheus historical queries are evaluated at the printed evaluation time `T`. Kubernetes Deployment/HPA facts and `kubectl top` are **live snapshots taken during collection**, not historical snapshots at `T`.

This distinction matters when HPA scaling or scale-down happens between `T` and the time the collector is run.

All timestamps ending in `Z` are UTC.

## 1. Baseline collection

Use an evaluation time a little in the past to avoid querying the ingestion edge:

```bash
python experiments/praeva/spike-001/cpu_evidence.py collect --lag-seconds 120
```

The output prints the exact evaluation timestamp. To reproduce the same result later, rerun with that exact value:

```bash
python experiments/praeva/spike-001/cpu_evidence.py collect \
  --evaluation-time 2026-10-09T12:30:00Z
```

The default historical window is `6h`. For an isolated round, use a shorter window when appropriate, for example:

```bash
python experiments/praeva/spike-001/cpu_evidence.py collect \
  --lag-seconds 120 \
  --window 30m
```

## 2. Burst round (~30 seconds)

```bash
python experiments/praeva/spike-001/cpu_evidence.py load \
  --duration 30 \
  --top-interval 5
```

The load command records:

- successful API preflight before the timer starts;
- start/end timestamps;
- replica count before/after;
- `kubectl top pod --containers` snapshots while the load is running;
- request failures, if any;
- whether the round is valid for follow-up collection.

After the ingestion delay printed by a valid round, collect CPU evidence again:

```bash
python experiments/praeva/spike-001/cpu_evidence.py collect --lag-seconds 120
```

Save the evaluation timestamp from that report so the query can be replayed exactly.

## 3. Sustained round (~10 minutes)

Run this as a separate experiment. The HPA is allowed to scale; the script records replicas before and after so the additional pods remain visible in the evidence.

```bash
python experiments/praeva/spike-001/cpu_evidence.py load \
  --duration 600 \
  --top-interval 15
```

After the ingestion delay printed by a valid round, collect again:

```bash
python experiments/praeva/spike-001/cpu_evidence.py collect --lag-seconds 120
```

### Port-forward limitation

The lab exposes `localhost:8081` with `kubectl port-forward svc/jobs-api`. Kubernetes port-forward selects a backing pod and forwards the connection to that pod; it is **not** a service-level load-balancing test across all HPA replicas.

Therefore the Spike 001 load harness is valid for:

- driving a known container toward CPU saturation;
- observing HPA reaction;
- validating Prometheus CPU/throttling evidence;
- preserving per-pod and ReplicaSet history.

It is **not** valid for concluding that traffic is or is not evenly redistributed after scale-out. A future distribution experiment should generate traffic from inside the cluster against `http://jobs-api.app.svc.cluster.local:8000` (or another path that exercises the Service normally).

## What the collector reports

The collector prints facts only:

- fixed Prometheus evaluation time `T`;
- collection start time for the live Kubernetes snapshot;
- Prometheus version and historical window;
- current CPU request/limit from the live Deployment;
- current HPA snapshot (informational only);
- detected kubelet/cAdvisor scrape targets and scrape interval;
- historical series count;
- samples per series;
- approximate first/last sample timestamp per pod;
- ReplicaSet history from `kube_pod_owner` when available;
- per-pod P95 and maximum for `rate[2m]` and `rate[5m]`;
- percentage by which the 5m maximum is lower than the 2m maximum for that observed workload;
- per-pod throttled-period ratio;
- a current `kubectl top` snapshot as a sanity reference.

## Sanity checks

The spike is useful only if the data behaves coherently:

1. The selected series must correspond to the expected `jobs-api` container.
2. A controlled CPU burn must increase Prometheus CPU and `kubectl top` in the same order of magnitude. Exact equality is not expected because their sampling/windows differ.
3. If demand is above the current CPU limit, observed CPU should approach the configured limit and throttling should increase. A value far above the limit or zero throttling under clear saturation is a reason to inspect series selection/query semantics.
4. `rate[2m]` and `rate[5m]` are compared in both burst and sustained rounds. Their difference is an observation about that workload shape, not a global Praeva constant.
5. A detected scrape interval of 60s or more is flagged because `rate[2m]` becomes sparse/unstable.
6. Old/short-lived pods and ReplicaSets are printed instead of silently mixed into a single number.
7. A round with a failed controlled load call is invalid and must not be used as controlled-load evidence.

## Observed Spike 001 results

The real local lab validated the core collector assumptions:

- replaying the same explicit evaluation time reproduced the historical CPU values;
- the ~30s burst showed materially stronger smoothing with `rate[5m]` than `rate[2m]` (63.86% lower maximum in that observed round);
- the sustained round converged closely between the two windows (1.51% lower `rate[5m]` maximum in that observed round);
- sustained CPU reached approximately the configured 500m limit and throttled-period ratio increased materially;
- HPA-created pods and historical ReplicaSets remained visible after scale-down.

These are observations from this lab workload, not universal thresholds or constants for Praeva.

## Known spike-only shortcuts

The default pod selector is `jobs-api-.*`. This is deliberately temporary and must not become the production selection mechanism because another workload such as `jobs-api-worker` could match it.

The collector groups multiple matching Prometheus series by pod using the worst observed value. The raw series/sample section is printed so duplicate/unexpected labelsets can be detected before this becomes a product rule.

The load runner issues one synchronous CPU request at a time. Combined with the local port-forward behavior, this is intentionally a saturation/evidence harness rather than a traffic-distribution benchmark.

## Pass criteria

Spike 001 passes if we can show that:

- the correct container series are selected;
- metrics react coherently to controlled load;
- Prometheus and `kubectl top` agree in order of magnitude;
- contributing pods/ReplicaSets and sample coverage are visible;
- rerunning a query with the same explicit `T` reproduces the result;
- the difference between 2m and 5m rate windows can be measured and explained.

The observed lab runs satisfy these criteria. A failed or invalid round remains useful as a spike finding, but it is not counted as controlled-load evidence.
