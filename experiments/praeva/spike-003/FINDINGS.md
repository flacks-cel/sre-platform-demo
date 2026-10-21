# Spike 003 — Findings

> Findings are appended after evidence is observed. They do not retroactively change the pre-registration, frozen R1 parameters, or product semantics.

## F1 — Global TSDB time coverage does not imply required-series coverage

### Observation

The first frozen `R1-stable-wire` collection completed successfully at the Prometheus transport/schema level but every experiment query returned an empty matrix (`result_series = 0`).

Frozen R1 interval:

```text
analysis start             = 2026-10-20T18:08:30Z
analysis end               = 2026-10-20T18:38:30Z
step                       = 15s
extended ownership start   = 2026-10-20T18:03:30Z
```

The local evidence directory created by that run was:

```text
experiments/praeva/spike-003/evidence/R1-stable-wire-1792521510/
```

Prometheus itself reported TSDB head time coverage spanning the requested interval:

```text
minTime = 2026-10-20T17:38:20.952Z
maxTime = 2026-10-20T18:47:00.673Z   # value observed during diagnosis
```

However, direct `query_range` checks over the frozen R1 interval returned zero series for all of these representative required inputs:

```text
up{job="jobs-api"}
up{job="kube-state-metrics"}
kube_pod_owner{namespace="app"}
container_cpu_usage_seconds_total{namespace="app",container="jobs-api",cpu="total"}
kube_pod_container_resource_limits{namespace="app",container="jobs-api",resource="cpu"}
```

The same metric families existed after the lab recovered. The first observed evaluation-grid points after the gap were:

```text
cpu_raw                2026-10-20T18:43:30Z
cfs_throttled_raw      2026-10-20T18:43:30Z
cpu_limit              2026-10-20T18:44:00Z
pod_owner              2026-10-20T18:44:00Z
replicaset_owner       2026-10-20T18:44:00Z
pod_created            2026-10-20T18:44:00Z
```

Therefore the frozen R1 interval ended before the required target series became available again.

### What this rules out

The empty R1 matrices were not sufficient evidence that:

- the workload did not exist;
- the target Deployment had no pods;
- CPU usage was zero;
- throttling was absent;
- ownership was absent;
- the R1 PromQL selectors were necessarily wrong.

Current instant queries after recovery returned the `jobs-api` target, its cAdvisor CPU series, and its KSM ownership series.

### Finding

> Prometheus TSDB time coverage is a backend-global property and does not prove historical availability of the specific series required by an analysis.

A successful `query_range` response containing an empty matrix must not be interpreted as semantic absence without an independent required-series availability check.

### Experimental consequence

For this spike, required-series availability is treated as a precondition to interpreting attribution/population results. This is an experimental finding only; no product reason code or Analyze/Join/Risk behavior is introduced here.

For the frozen R1 geometry:

```text
latest required-series first grid point = 2026-10-20T18:44:00Z
W_max                                   = 5m
earliest safe analysis start            = 2026-10-20T18:49:00Z
analysis duration                        = 30m
earliest safe analysis end              = 2026-10-20T19:19:00Z
ingestion lag                            = 2m
earliest safe collection wall-clock     = 2026-10-20T19:21:00Z
                                         = 2026-10-20T16:21:00-03:00
```

This timestamp is derived mechanically from the observed required-series boundary plus the already frozen R1 window geometry. It is not selected after inspecting a favorable risk/ownership result.

### Open point

A later experiment/contract must decide the exact shape of a required-series availability proof. The spike does not yet freeze whether this belongs in transport validation, Verify evidence quality, or a separate precondition layer.

## F2 — Stable mature pod supports evaluation-grid attribution in the observed lab

### Observation

A later `R1-stable-wire` run captured a fully covered candidate window:

```text
extended ownership start = 2026-10-21T18:26:15Z
analysis start            = 2026-10-21T18:31:15Z
analysis end              = 2026-10-21T19:01:15Z
step                      = 15s
```

Local evidence directory:

```text
experiments/praeva/spike-003/evidence/R1-stable-wire-1792609275/
```

All Verify-scoped series carried 121/121 expected evaluation points with no gaps. All extended ownership/identity series carried 141/141 expected points with no gaps.

The observed Pod identity was stable across the full extended grid:

```text
pod = jobs-api-849859f688-z6zck
uid = 169ef855-2e34-485a-8090-ca7c1868ad3f
```

The Pod controller chain was observed consistently as:

```text
Pod/jobs-api-849859f688-z6zck
  -> ReplicaSet/jobs-api-849859f688
  -> Deployment/jobs-api
```

A second historical ReplicaSet owned by the Deployment was also present in KSM telemetry, but no observed Pod in this run referenced it. Therefore target population enumeration must follow the Pod -> ReplicaSet -> Deployment chain and must not equate "all ReplicaSets owned by the Deployment" with the Pod population.

`kube_pod_created` was stable across the grid and reported:

```text
created = 2026-10-13T18:25:20Z
```

The earliest long-window support boundary in the run was:

```text
2026-10-21T18:26:15Z
```

Therefore:

```text
kube_pod_created(uid) <= earliest support_start
```

with the Pod created 691255 seconds before that boundary.

Diagnostic source-sample timestamps were also captured for `pod_owner`, `replicaset_owner`, and `pod_created`. Across all 141 evaluation points, the observed evaluation-time minus source-sample-time age ranged from:

```text
min = 7.201s
max = 23.553s
```

The spike does not interpret those ages against a freshness threshold.

### Stable-run population result

For every Verify evaluation timestamp in this run:

```text
O(T)        = {jobs-api-849859f688-z6zck}
S_target(T) = {jobs-api-849859f688-z6zck}
V_q(T)      = {jobs-api-849859f688-z6zck}  for each captured Verify fact family q
```

Therefore, in this stable scenario:

```text
selector_omissions(T)              = empty
derived_evidence_missing_q(T)      = empty
extra_observed_q(T)                = empty
```

### Finding

> Under the frozen 15-second evaluation-grid model, the current Prometheus/KSM wire can support deterministic attribution for a mature stable Pod when required-series coverage is complete.

The observed run satisfies the candidate stable-pod proof ingredients tested by S1:

```text
same UID on every required ownership grid point
AND target ownership chain observed on every required ownership grid point
AND kube_pod_created(uid) <= support_start
```

This is evaluation-grid support coverage only. It does not prove continuous Kubernetes event-time identity or ownership between grid points.

### Experimental consequence

The stable case is feasible on the pinned lab wire and query volume is small enough for raw replay evidence. The remaining spike work must exercise the cases where the stable assumptions break: young Pod support, UID change, TARGET_DIFFERS, selector omission, missing derived evidence, extra observed pods, churn, population-incomplete reasoning, and non-divisible window/step behavior.

No Analyze/Join/Risk or product-semantic change is introduced by this finding.
