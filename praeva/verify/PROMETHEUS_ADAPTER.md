# Verify 001 — Prometheus Adapter Contract

> Status: **pre-registered adapter design**. This slice acquires and normalizes historical Prometheus evidence only; it does not add risk or recommendation logic.

## 1. Boundary

The adapter sits before the pure CPU evidence core:

```text
Prometheus HTTP API
       ↓
prometheus_adapter
       ↓
normalized evidence input
       ↓
cpu_evidence.build_report()
```

The adapter must not duplicate selector logic from `cpu_evidence.py` and must not create a generic `worst_pod`.

## 2. Inputs

Required inputs are explicit:

- `prometheus_url`;
- `namespace`;
- pod regex / workload selector;
- `container`;
- historical `start`;
- historical `end`;
- `step`;
- `short_rate_window`;
- `long_rate_window`.

Request-rate evidence is optional and is supplied as an explicit PromQL query. The adapter must not hard-code `jobs-api` or `/simulate/cpu-work` into generic collection logic.

## 3. Historical query semantics

The first adapter uses Prometheus `/api/v1/query_range` for every time-varying series used by the core.

It queries:

- short-window CPU usage rate per pod;
- long-window CPU usage rate per pod;
- historical CPU limit per pod at the same query-range timestamps;
- optional request rate per pod.

CPU and limit data must remain historical. The adapter must not read the current Deployment manifest as a fallback for a missing historical limit.

The generated CPU queries keep the rate window explicit and aggregate only by pod for the selected namespace/container. Replica CPU must never be summed into one workload-wide sizing value.

## 4. Normalized output

The adapter returns the existing normalized `build_report` input shape:

```json
{
  "pods": [
    {
      "name": "pod-a",
      "cpu_short": [{"timestamp": 0, "value": 0.1}],
      "cpu_long": [{"timestamp": 0, "value": 0.08}],
      "cpu_limit": [{"timestamp": 0, "value": 0.5}],
      "request_rate": null,
      "sample_count": 1,
      "coverage": 1.0,
      "restart_delta": 0,
      "node": null,
      "owner": null
    }
  ],
  "short_window": "2m",
  "long_window": "5m"
}
```

`sample_count` and `coverage` in this slice are derived from short-window CPU query-range points. Coverage is the observed point count divided by the expected number of query-range steps over the requested interval. It is diagnostic metadata only; the adapter must not apply the Spike 002 80% experiment threshold.

## 5. Pod identity and missing series

The pod universe is the union of pod labels returned by the requested historical series.

For a known pod:

- missing CPU short/long series is represented as an empty list;
- missing historical limit is represented as `null`;
- missing optional request telemetry is represented as `null`.

The adapter does not convert these cases into LOW/safe conclusions. The pure core decides which dependent selector becomes `UNKNOWN`.

If Prometheus returns more than one series for the same normalized metric and pod after the query's expected aggregation, the adapter must reject the acquisition as ambiguous rather than silently choose one.

## 6. Timestamp semantics

The adapter preserves Prometheus timestamps exactly as returned. It does not nearest-neighbor match, interpolate, or rewrite timestamps to make joins succeed.

Timestamp alignment required by CPU/limit or CPU/request ratios remains the responsibility of the pure evidence core. Misalignment therefore stays visible and can become `UNKNOWN`.

### 6.1 Rate lookback and pod churn

A PromQL expression such as `rate(...[2m])` can still return a value at evaluation time `T` for a recently terminated pod because the rate window reads counter samples from before `T`.

Metadata or request series that are instantaneous at `T` may already have disappeared for that same pod. The adapter must preserve that asymmetry rather than silently drop the pod, copy current metadata, interpolate, or backfill a denominator.

Therefore a recently terminated pod may legitimately have:

- valid short/long CPU rate points;
- no historical CPU-limit point at the evaluation timestamp;
- no request-rate point at the evaluation timestamp.

In that case the CPU-usage selector may remain `VALID`, while limit- or request-dependent selectors become `UNKNOWN`. This is expected evidence semantics, not an adapter transport failure.

## 7. Failure semantics

Transport/API/schema failures are execution failures and raise an adapter error. Examples:

- HTTP failure;
- Prometheus status other than `success`;
- result type other than `matrix`;
- malformed samples;
- duplicate per-pod series after expected aggregation.

A successful Prometheus response with missing telemetry is **not** a transport failure. It is normalized as missing evidence for the core to classify.

## 8. Non-goals

This adapter slice does not add:

- live Kubernetes reads;
- node saturation rules;
- restart/owner/node historical enrichment beyond placeholder fields;
- risk classification;
- CPU recommendations;
- automatic changes;
- LLM/AI interpretation.

Those concerns remain separate adapters/rules after the historical CPU acquisition contract is stable.
