# Verify enrichment — per-pod CPU limit ratio evidence

> Status: **pre-registered prerequisite for RULE-001**. This document freezes the evidence shape before implementation. It does not implement RULE-001 and does not change risk/recommendation semantics.

## 1. Goal

Expose `cpu_limit_ratio` evidence for every CPU-observed pod so downstream deterministic rules can reason about partial completeness without reimplementing historical joins or parsing selector error strings.

This enrichment belongs to Verify because `cpu/limit` is evidence derived from historical CPU and historical limit at aligned timestamps. RULE-001 consumes that evidence; it must not recompute it.

## 2. Per-pod output

Each entry under `report["pods"][pod]` gains a `cpu_limit_ratio` object.

When computable:

```json
{
  "status": "VALID",
  "window": "2m",
  "max": 0.8,
  "max_timestamp": 30,
  "points": 3
}
```

When not computable:

```json
{
  "status": "UNKNOWN",
  "window": "2m",
  "reason_code": "missing_limit",
  "reason": "historical CPU limit is missing"
}
```

`points` is the number of aligned CPU/limit timestamp pairs used to compute the ratio. Coverage and sample count remain existing pod-level metadata; they are not converted into a pass/fail threshold here.

## 3. Exact historical join semantics

For one pod:

1. short-window CPU points are indexed by their exact Prometheus timestamps;
2. historical CPU-limit points are indexed by their exact Prometheus timestamps;
3. timestamps must match as sets;
4. no nearest-neighbor matching, interpolation, backfill, or current Deployment limit is permitted;
5. each aligned ratio is `cpu_usage_rate / historical_cpu_limit`;
6. the per-pod evidence reports the maximum ratio and its timestamp.

The short CPU window remains explicit in the output.

## 4. Structured UNKNOWN reasons

The closed `reason_code` set for this enrichment is:

- `missing_cpu` — short-window CPU series is absent or empty;
- `missing_limit` — historical CPU-limit series is absent or empty;
- `duplicate_timestamp` — CPU or limit contains more than one value for the same timestamp, preventing a deterministic join;
- `timestamp_misalignment` — CPU and limit timestamp sets differ;
- `non_positive_limit` — at least one aligned historical CPU limit is `<= 0`.

If more than one defect is present, deterministic precedence is:

1. `missing_cpu`;
2. `missing_limit`;
3. `duplicate_timestamp`;
4. `timestamp_misalignment`;
5. `non_positive_limit`.

Human-readable `reason` accompanies `reason_code`, but downstream rules consume `reason_code`, not string parsing.

## 5. Relationship to existing selectors

This enrichment does **not** redefine `max_cpu_limit_ratio_pod` in this slice. Existing selector behavior remains backward-compatible.

In particular:

- the selector may still be `UNKNOWN` if any pod makes its current all-pod join requirement fail;
- per-pod evidence must still expose which pods are individually `VALID` and which are `UNKNOWN`;
- top-level report status keeps its existing meaning and is not promoted/demoted merely because this field was added.

RULE-001 will consume the per-pod field to distinguish a complete exceedance witness from an incomplete pod. The rule is not implemented as part of this enrichment.

## 6. Non-goals

This enrichment does not add:

- `WITHIN_CEILING`, `EXCEEDS_CEILING`, or any RULE-001 conclusion;
- LOW/MEDIUM/HIGH risk;
- a default ceiling ratio;
- recommendation or target CPU limit;
- coverage threshold;
- request-rate/cost-rate enrichment;
- live Kubernetes fallback;
- silent filtering of churned pods;
- `worst_pod`.

## 7. Acceptance tests before implementation

RED tests must prove at least:

1. aligned positive CPU/limit evidence yields per-pod `VALID` with max ratio, timestamp, window, and point count;
2. missing limit yields `UNKNOWN/missing_limit` while another pod can remain `VALID`;
3. timestamp mismatch yields `UNKNOWN/timestamp_misalignment`;
4. non-positive limit yields `UNKNOWN/non_positive_limit`;
5. duplicate timestamps yield `UNKNOWN/duplicate_timestamp`;
6. existing aggregate selector semantics remain unchanged while per-pod statuses stay independently visible.
