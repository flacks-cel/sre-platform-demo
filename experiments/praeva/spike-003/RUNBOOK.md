# Spike 003 — Experimental Runbook

> Status: **R1 frozen before collector execution.**
> This runbook is experiment-only. Its numbers do not become Praeva product defaults or policy.

## R1 — stable-wire feasibility

Purpose: test the historical attribution/population wire under ordinary lab conditions before intentionally creating rollout/HPA churn.

No workload mutation is allowed during R1 for the purpose of making a scenario appear. In particular, do not change Deployment image/template, HPA limits, replicas, CPU limits, or generate a special controlled-load round solely for R1.

### Frozen parameters

```text
run_id              = R1-stable-wire
prometheus_url       = http://localhost:9091
namespace            = app
api_group            = apps
kind                 = Deployment
workload             = jobs-api
container            = jobs-api
pod_regex            = jobs-api-.*
step                 = 15s
short_window         = 2m
long_window          = 5m
W_max                = 300s
analysis_duration    = 1800s (30m)
ingestion_lag        = 120s
```

At collection start, derive the historical interval mechanically:

```text
raw_end = current Unix time - 120s
end     = floor(raw_end / 15s) * 15s
start   = end - 1800s

extension_steps          = ceil(300 / 15) = 20
extended_ownership_start = start - 20*15s
                         = start - 300s
```

R1 happens to have `W_max % step == 0`; this does **not** satisfy the required synthetic non-divisible-window scenario from the main pre-registration.

### Required collection

Capture raw Prometheus responses for:

```text
cpu_short
cpu_long
cfs_throttled_short
cfs_throttled_long
cpu_limit (current Verify query shape)
cpu_limit_uid (diagnostic UID-preserving shape)
pod_owner
replicaset_owner
pod_created
pod_owner_source_timestamp
replicaset_owner_source_timestamp
pod_created_source_timestamp
Prometheus buildinfo
Prometheus flags, when endpoint is available
```

All ownership/creation range queries use:

```text
start = extended_ownership_start
end   = end
step  = 15s
```

Verify-equivalent fact queries use:

```text
start = start
end   = end
step  = 15s
```

### R1 is not allowed to conclude

R1 cannot by itself:

- replace `CALLER_ASSERTED`;
- change CHANGE-RISK-001;
- choose policy for foreign pods;
- establish application-version homogeneity;
- prove continuous event-time ownership/identity;
- satisfy the rollout/churn scenario unless churn happens naturally and is captured cleanly.

### R1 success condition

R1 succeeds as a feasibility collection if the required Prometheus responses are captured with exact interval/query metadata and can be parsed/replayed. A surprising ownership/population result does not make the run invalid; it becomes a finding.

Transport/schema failure is a failed collection, not semantic `UNKNOWN`.
