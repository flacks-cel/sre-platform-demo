# Praeva Verify 001 — CPU Evidence Contract

> Status: **pre-registered design**. No sizing recommendation, risk classification, or automatic change is implemented in this slice.

## 1. Goal

Build the first deterministic `verify` slice from the evidence rules validated by Spike 001 and Spike 002.

`verify` answers a narrower question than a recommendation engine:

> Is the CPU evidence set internally usable, and what does each explicit per-pod selector identify?

This slice does **not** answer whether a CPU limit should be reduced.

## 2. Stable constraints inherited from the ADRs

The implementation must preserve these accepted decisions:

- CPU and memory use different risk models (ADR-001).
- Risk and evidence quality are separate concepts (ADR-002).
- CPU resource evidence remains per pod/container (ADR-003).
- Every counter-rate CPU statistic discloses its rate window (ADR-004).
- Missing required telemetry never implies LOW; dependent output becomes `UNKNOWN` (ADR-005).
- Historical Prometheus evidence and live Kubernetes state have different time semantics (ADR-006).
- Invalid controlled-load evidence is never promoted to valid evidence (ADR-007).

## 3. Spike 002 constraints carried forward

### 3.1 There is no generic `worst_pod`

Spike 002 exposed an instrumentation defect in the phrase "worst pod": different metrics can select different pods in the same phase.

Verify 001 therefore forbids a single ambiguous `worst_pod` field.

It exposes independent selectors:

- `max_cpu_usage_pod`
- `max_cpu_limit_ratio_pod`
- `max_cpu_cost_rate_pod` when request-rate evidence is available

Each selector must include:

- pod name;
- metric name;
- metric value;
- rate window when applicable;
- timestamp of the selected observation;
- coverage/sample metadata for the selected pod.

A later deterministic rule that needs a "worst" pod must name the selector it depends on. If a rule still depends on an undefined generic worst pod, that rule is invalid and its conclusion must be `UNKNOWN`.

Selector disagreement is **not itself evidence corruption**. It is expected to be visible. A future conclusion becomes `UNKNOWN` only when that conclusion requires the selectors to identify the same pod and they do not.

### 3.2 Coverage is diagnostic metadata, not yet a production cutoff

Spike 002 showed that partial coverage can inflate local `cpu_cost_rate` for young pods, but its strict pre-registered scale-up decision remained `UNKNOWN`. The steady-state result did not justify a mandatory production coverage filter.

Therefore Verify 001 must report coverage and sample count, but it must **not invent an 80% production threshold** from the experiment harness.

A metric-dependent result becomes `UNKNOWN` when the series is absent or has too little data to compute the metric correctly. Partial-but-computable coverage is surfaced explicitly and left to a future pre-registered rule.

### 3.3 Steady-state and scale-up conclusions are not interchangeable

The Spike 002 line-C conclusion applies to its steady-state comparison. The scale-up phase remained `UNKNOWN` under the strict matrix, with only an A1-compatible secondary signal.

Verify 001 must not generalize a steady-state conclusion to scale-up automatically.

### 3.4 Node asymmetry was not tested by Spike 002

All `jobs-api` pods in Spike 002 ran on the same worker. Node identity should be retained as evidence metadata, but Verify 001 must not claim that cross-node asymmetry has been validated by the spike.

## 4. Input contract

Required inputs:

- `prometheus_url`
- `namespace`
- workload/pod selector
- `container`
- historical `start`
- historical `end`
- `step`
- `short_rate_window`
- `long_rate_window`

Optional inputs:

- request counter selector/query for `cpu_cost_rate`
- explicit scrape interval when it cannot be derived from configuration

The first implementation targets the current lab workload, but query construction must keep namespace/container/pod selector explicit rather than hard-code `jobs-api` into the evidence model.

## 5. Historical evidence only in the core result

The core result is built from Prometheus data evaluated over the requested historical interval.

Historical CPU usage must be compared with the historical CPU limit from the **same timestamps**, not with the current Deployment manifest or a live Kubernetes read.

Live observations may be added later under a separate `live_context` object with an explicit `observed_at` timestamp. They must never be presented as historical evidence for `start..end`.

## 6. Per-pod evidence

For every observed pod/container, Verify 001 should expose, when available:

- CPU usage rate using the short window;
- CPU usage rate using the long window;
- historical CPU limit at matching timestamps;
- pointwise CPU/limit ratio;
- sample count;
- coverage metadata;
- pod creation timestamp / age relative to the evidence interval;
- restart delta inside the interval;
- ReplicaSet/workload owner metadata;
- node identity;
- request rate and `cpu_cost_rate` when request evidence is configured.

The output must preserve pods separately. It must not sum CPU across replicas for per-container sizing evidence.

## 7. Named selectors

### 7.1 `max_cpu_usage_pod`

Select the pod containing the maximum observed CPU usage rate for the explicitly named rate window.

The output must never say merely "max CPU" without the window.

### 7.2 `max_cpu_limit_ratio_pod`

Select the pod containing the maximum historical pointwise ratio:

`cpu_usage_rate / cpu_limit_at_the_same_timestamp`

A missing historical limit makes this selector `UNKNOWN`; it must not fall back to the current manifest limit.

### 7.3 `max_cpu_cost_rate_pod`

When request evidence is available, select the pod containing the maximum valid CPU cost per request:

`cpu_usage_rate / request_rate`

The result must carry the CPU rate window, request rate window, sample/coverage metadata, and denominator validity.

If request evidence is not configured or the denominator is unusable, this selector is `UNKNOWN` without invalidating unrelated CPU selectors.

## 8. Evidence status

Status is evaluated per evidence field/selector and summarized at the top level.

Allowed values:

- `VALID`
- `UNKNOWN`

`UNKNOWN` is required when a dependent result cannot be computed from usable telemetry, including examples such as:

- required series missing;
- historical CPU limit missing for a ratio;
- insufficient points to compute the requested rate;
- unusable request-rate denominator;
- ambiguous duplicate labelsets that cannot be resolved deterministically;
- timestamp alignment required by the metric cannot be established.

A pod restart is reported as evidence. It does not automatically corrupt every historical CPU metric. Future rules may declare a restart-bearing interval unsuitable for a specific conclusion.

Likewise, throttling is reported as constrained-demand evidence; it is not automatically evidence corruption (ADR-002).

## 9. Output shape — first contract

Illustrative shape, not yet a frozen serialization schema:

```json
{
  "status": "VALID",
  "interval": {
    "start": "...",
    "end": "...",
    "step": "15s"
  },
  "windows": {
    "short": "2m",
    "long": "5m"
  },
  "pods": {
    "pod-a": {
      "sample_count": 0,
      "coverage": null,
      "restart_delta": 0,
      "node": "...",
      "owner": "..."
    }
  },
  "selectors": {
    "max_cpu_usage_pod": {},
    "max_cpu_limit_ratio_pod": {},
    "max_cpu_cost_rate_pod": {}
  },
  "unknown_reasons": []
}
```

The implementation must not create a `worst_pod` alias.

## 10. Non-goals

Verify 001 does not implement:

- `LOW` / `MEDIUM` / `HIGH` risk;
- CPU limit recommendations;
- a target CPU limit;
- automatic Git/Kubernetes changes;
- recommendation ranking;
- LLM/AI interpretation;
- memory analysis;
- a mandatory production coverage threshold;
- an assumption that all named selectors should select the same pod.

## 11. Initial acceptance tests

Before implementation is considered complete, deterministic tests must cover at least:

1. different selectors can legitimately choose different pods;
2. no generic `worst_pod` is emitted;
3. missing historical limit makes only the limit-dependent selector `UNKNOWN`;
4. missing request telemetry makes only cost-per-request evidence `UNKNOWN`;
5. missing telemetry never produces a safe/LOW interpretation;
6. short and long CPU windows remain separately labeled;
7. historical CPU/limit joins use aligned timestamps;
8. per-pod evidence is never replaced by a sum across replicas;
9. partial coverage is reported without applying an invented 80% production cutoff;
10. live Kubernetes state, if added later, cannot masquerade as historical state.

## 12. Exit criterion for this slice

Verify 001 is complete when it can deterministically produce the historical per-pod CPU evidence set and named selectors above, with explicit `VALID`/`UNKNOWN` semantics and tests for the contract.

Only after that contract is stable should Praeva add a deterministic risk/recommendation rule on top of it.

## 13. CLI / serialization contract

Before adding a Prometheus adapter, Verify 001 freezes a thin CLI around the pure evidence core.

Initial command shape:

```text
praeva verify cpu --input evidence.json
```

For this repository slice, the Python entry point may be invoked directly while packaging is deferred, but its semantics must match the command above.

The input file contains normalized evidence for `build_report`; the CLI does not query Prometheus yet.

CLI rules:

- successful execution writes exactly one JSON document to stdout;
- human progress text must not be mixed into stdout;
- serialization is deterministic (`sort_keys`/stable formatting);
- an evidence result containing `UNKNOWN` selectors is still a successful process execution and exits `0`;
- malformed JSON, unreadable input, or structurally invalid required input exits non-zero;
- execution errors go to stderr and stdout remains empty;
- the serialized result must not introduce `worst_pod`, risk levels, recommendations, or sizing targets;
- the CLI must call the same pure `build_report` core used by unit tests rather than reimplement selector logic.

The normalized file accepted by this slice contains:

- `pods`;
- `short_window`;
- `long_window`;
- optional `live_context`.

Prometheus acquisition and query construction are explicitly deferred to the next adapter slice.
