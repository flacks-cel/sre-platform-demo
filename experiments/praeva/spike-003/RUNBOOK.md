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

### Post-F1 operational preflight

Finding F1 showed that backend-global TSDB time coverage does not prove availability of the specific series required by R1.

After F1, before another R1 collection, run:

```bash
python experiments/praeva/spike-003/preflight.py
```

The helper checks evaluation-grid presence for the target CPU, throttling, CPU-limit, Pod-owner, ReplicaSet-owner, and Pod-created metric families over the candidate R1 geometry. It may report the earliest mechanically derived wall-clock time at which the current trailing availability could support a full R1 window.

This preflight was added **after** F1 and does not retroactively change the frozen R1 parameters, hypotheses, or exit criteria. It is only a lab-readiness guard. It does not prove population completeness, ownership semantics, raw-scrape/event-time continuity, or product eligibility.

A non-ready preflight means: preserve the observation and do not run another evidential R1 yet.

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
