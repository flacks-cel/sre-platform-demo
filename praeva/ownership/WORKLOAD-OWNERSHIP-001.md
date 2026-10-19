# WORKLOAD-OWNERSHIP-001 — Historical workload ownership evidence

> Status: **PRE-REGISTRATION CLOSED — ready for RED.**
> Base: `main @ e158e8922a6d79c4eee17b9d6522373f19fbaad0`.
> Gate: **this contract is frozen before RED; no implementation exists yet.**
> Motivation: replace the current `CALLER_ASSERTED / UNVERIFIED` workload→pod relation with historical evidence before adding a second hazard.

---

## 1. Question

> For each historical pod evidence witness used by Praeva, can we prove from historical Kubernetes ownership telemetry that the pod belonged to the named `apps/Deployment` at the timestamp of that evidence?

The key phrase is **at the timestamp of that evidence**.

A live Kubernetes snapshot is insufficient. During a normal rollout, a pod or ReplicaSet that produced historical evidence may already be gone when analysis runs. Ownership is therefore a temporal evidence problem, not only a structural lookup problem.

---

## 2. Boundary of this slice

`CHANGE-JOIN-001` deliberately records:

```text
identity_assertion.status = CALLER_ASSERTED
workload_to_pod_selector_relation = UNVERIFIED
application_version_relation = UNVERIFIED
```

That slice does not query Kubernetes or Prometheus for ownership and explicitly leaves `Pod → ReplicaSet → Deployment` for a later slice.

`WORKLOAD-OWNERSHIP-001` supplies **historical ownership evidence only**. It does not:

- classify change risk;
- modify `CHANGE-RISK-001`;
- modify `CHANGE-JOIN-001`;
- wire ownership into `praeva analyze`;
- promote `application_version_relation`.

Product-level wiring is a later pre-registered slice. Keeping collection/resolution separate from wiring prevents this substrate from silently defining risk or freshness policy.

---

## 3. Source of truth and pinned wire

Normative evidence comes from Prometheus `query_range` over kube-state-metrics owner gauges:

```text
kube_pod_owner
kube_replicaset_owner
```

The lab baseline is pinned to `kube-prometheus-stack` chart `88.6.2`. That chart depends on `kube-state-metrics` chart `8.4.1`, whose application version is kube-state-metrics `2.20.0`.

For kube-state-metrics `2.20.0`, the supported owner wire is:

```text
kube_pod_owner
  pod
  namespace
  owner_kind
  owner_name
  owner_is_controller
  uid

kube_replicaset_owner
  replicaset
  namespace
  owner_kind
  owner_name
  owner_is_controller
```

Important asymmetry: `kube_pod_owner` exposes Pod UID; `kube_replicaset_owner` does **not** expose ReplicaSet UID. This slice preserves that limitation instead of inventing an identity that the metric does not provide.

The live Kubernetes API is not authoritative for this slice. Deleted pods and old ReplicaSets are normal historical inputs.

Transport failure, malformed Prometheus envelopes, non-`matrix` results, and missing required wire labels are execution/schema failures. They do not become semantic ownership `UNKNOWN`.

---

## 4. Module boundary and public APIs

The implementation will follow the existing Verify separation between Prometheus normalization and pure semantic interpretation.

### 4.1 Prometheus adapter

Module:

```text
praeva/ownership/prometheus_adapter.py
```

Public API:

```python
collect_ownership_evidence(
    *,
    prometheus_url: str,
    namespace: str,
    start: str | int | Decimal,
    end: str | int | Decimal,
    step: str | int | Decimal,
    query_range: QueryRange | None = None,
) -> dict
```

Responsibilities:

- execute the two fixed ownership range queries;
- validate Prometheus transport/envelope/result type;
- validate required KSM labels;
- preserve decimal timestamps and sample values as strings;
- return normalized temporal owner observations plus acquisition/query provenance;
- never resolve a Pod→ReplicaSet→Deployment relation.

`query_range` is the injection point, exactly as in `PRAEVA-ANALYZE-001`. Replay tests therefore exercise the real ownership adapter.

### 4.2 Pure historical resolver

Module:

```text
praeva/ownership/historical.py
```

Public API:

```python
build_ownership_report(
    *,
    evidence: dict,
    target_workload: dict,
    required_timestamps_by_pod: dict[str, list[str]],
) -> dict
```

Responsibilities:

- validate target/workload/input consistency;
- resolve ownership only at explicitly required timestamps;
- keep evidence quality separate from relation;
- preserve contradictory valid chains;
- produce deterministic output with no I/O.

The first contract supports only:

```text
api_group = apps
kind = Deployment
```

Generic arbitrary workload GVK resolution is out of scope.

---

## 5. Acquisition interval and exact evaluation grid

Ownership reuses the explicit historical interval:

```text
start
end
step
```

There are no ownership-specific defaults and no implicit `now` lookup.

Every required timestamp must satisfy both conditions exactly using decimal arithmetic:

```text
start <= timestamp <= end
(timestamp - start) % step == 0
```

A required timestamp outside the interval or off the evaluation grid is **invalid input**, not ownership `UNKNOWN`. The caller would be asking for proof at a time the acquisition contract did not evaluate.

There is no nearest-neighbor lookup, tolerance, rounding, or interpolation.

Required timestamps are de-duplicated and emitted in deterministic numeric order.

---

## 6. PromQL query shapes

The first slice intentionally queries all controller-owner facts in the target namespace rather than inferring ownership from a pod-name prefix or regex.

Pod owners:

```promql
max by (namespace, pod, uid, owner_kind, owner_name, owner_is_controller) (
  kube_pod_owner{namespace="<namespace>",owner_is_controller="true"}
)
```

ReplicaSet owners:

```promql
max by (namespace, replicaset, owner_kind, owner_name, owner_is_controller) (
  kube_replicaset_owner{namespace="<namespace>",owner_is_controller="true"}
)
```

The `max by (...)` is normalization of scrape-topology labels such as `instance`/`job`; it does **not** collapse distinct Kubernetes owner candidates because the ownership identity labels remain in the grouping key.

The queries deliberately do not filter `owner_kind`. A valid controller owner of the “wrong” kind is contradictory evidence and must remain visible as `TARGET_DIFFERS`, not disappear and become missing telemetry.

A future optimization may narrow queries only if it preserves the same semantics and is separately tested.

---

## 7. Unit of proof is temporal

Ownership is not asserted once for a pod name across an entire report.

The atomic fact is:

```text
(namespace, pod, required_timestamp)
    -> controller owner
    -> ReplicaSet
    -> controller owner at the same required_timestamp
    -> Deployment
```

The target is a specific workload identity:

```text
api_group = apps
kind = Deployment
namespace = ...
name = ...
```

A successful chain at `T1` does not prove the chain at `T2`.

The timestamp is a **Prometheus evaluation timestamp** on the explicit `start/end/step` grid. This slice does not claim sub-scrape event-time precision that the Prometheus/KSM wire does not expose.

---

## 8. Required timestamps are caller-supplied facts, not policy

The component does not decide which CPU/throttling observation matters.

Its pure resolver input contains, per pod, the exact timestamps whose ownership must be resolved. Those timestamps come from upstream evidence witnesses already selected by deterministic substrate logic.

This contract does **not** introduce either policy:

```text
ownership must be valid for every scrape in the whole window
```

or:

```text
ownership at the end of the window is enough
```

A later consumer must explicitly declare any reduction across timestamps.

---

## 9. Relation and evidence quality are separate axes

For each required timestamp:

```text
evidence_status = VALID | UNKNOWN
relation        = TARGET_MATCH | TARGET_DIFFERS   # only when evidence_status=VALID
```

A valid observation that points somewhere else is not `UNKNOWN`.

### 9.1 Matching chain

For target `apps/Deployment app/jobs-api`:

```text
Pod jobs-api-abc --controller--> ReplicaSet jobs-api-123
ReplicaSet jobs-api-123 --controller--> Deployment jobs-api
```

produces:

```text
evidence_status = VALID
relation = TARGET_MATCH
```

### 9.2 Contradictory Pod controller

If the Pod has one unambiguous valid controller owner and its kind is not `ReplicaSet`:

```text
evidence_status = VALID
relation = TARGET_DIFFERS
```

The observed Pod owner is preserved. No ReplicaSet lookup is required to establish the contradiction.

### 9.3 Contradictory ReplicaSet controller

If the Pod validly points to one ReplicaSet, and that ReplicaSet has one valid controller owner at the same timestamp, but that owner is not `Deployment/<target-name>`:

```text
evidence_status = VALID
relation = TARGET_DIFFERS
```

The observed chain is preserved.

### 9.4 Incomplete or ambiguous evidence

If a required hop cannot be established uniquely from the historical telemetry:

```text
evidence_status = UNKNOWN
```

with one named reason code from section 13.

Missing telemetry never means `TARGET_MATCH`.

---

## 10. Controller ownership only

The proof follows Kubernetes controller ownership, not arbitrary owner references.

Only series with:

```text
owner_is_controller = "true"
```

are queried.

The expected Deployment path is:

```text
Pod --controller--> ReplicaSet --controller--> Deployment
```

The collector/resolver must not silently choose one candidate when multiple controller-owner observations are simultaneously valid at a required timestamp.

Ambiguity is `UNKNOWN`, never an arbitrary deterministic pick.

---

## 11. Identity and UID semantics

### 11.1 Pod

Pod identity is based on:

```text
namespace + pod name + uid
```

because `kube_pod_owner` in the pinned KSM wire exposes `uid`.

A pod name resolving to different UIDs at different required timestamps is allowed and preserved. Delete/recreate behavior is not automatically an error.

At one required timestamp:

- one UID with one controller owner can be resolved;
- multiple UIDs simultaneously plausible for the same pod name are `UNKNOWN` with `pod_identity_ambiguous_at_timestamp`;
- one UID with multiple controller owners is `UNKNOWN` with `pod_controller_owner_ambiguous`.

### 11.2 ReplicaSet

ReplicaSet identity is based only on:

```text
namespace + replicaset name
```

because the pinned `kube_replicaset_owner` metric does not expose ReplicaSet UID.

The report makes this provenance limitation explicit. It must not fabricate a ReplicaSet UID or claim stronger object identity than the wire supports.

At one required timestamp, multiple controller-owner candidates for the same ReplicaSet name are `UNKNOWN` with `replicaset_controller_owner_ambiguous`.

### 11.3 API group limitation

`kube_replicaset_owner` exposes owner kind/name but not owner API version/group. The first slice therefore supports only the built-in expected path to `apps/Deployment`; it does not generalize the same wire into proof for arbitrary same-named kinds in arbitrary API groups.

---

## 12. Metric sample validity

Owner metrics are relationship gauges. For a candidate owner observation at a required timestamp, the sample must represent decimal value exactly equal to `1`.

A present candidate with a non-finite, non-numeric, duplicated-at-the-same-series/timestamp, or non-`1` sample cannot be used as valid ownership evidence.

Envelope/schema failures that prevent deterministic parsing are execution errors. A successfully parsed owner series whose relationship sample is semantically invalid produces:

```text
evidence_status = UNKNOWN
reason_code = owner_metric_invalid
```

There is no truthiness rule such as “non-zero means owner exists”.

---

## 13. Frozen UNKNOWN vocabulary

Only evidence incompleteness/ambiguity produces semantic ownership `UNKNOWN`.

Reason codes for this slice are:

```text
pod_owner_missing_at_timestamp
pod_identity_ambiguous_at_timestamp
pod_controller_owner_ambiguous
replicaset_owner_missing_at_timestamp
replicaset_controller_owner_ambiguous
owner_metric_invalid
```

The following are **input/execution errors**, not UNKNOWN reason codes:

```text
unsupported target api_group/kind
target namespace != acquisition namespace
required timestamp outside acquisition interval
required timestamp off acquisition grid
invalid start/end/step
Prometheus transport failure
Prometheus resultType != matrix
malformed matrix/series/sample
missing required KSM wire label
```

This distinction follows the existing Praeva rule: “could not execute/parse the acquisition” is not the same state as “executed successfully but evidence is insufficient”.

---

## 14. Frozen output wire

The report shape is:

```json
{
  "ownership_id": "WORKLOAD-OWNERSHIP-001",
  "target_workload": {
    "api_group": "apps",
    "kind": "Deployment",
    "namespace": "app",
    "name": "jobs-api"
  },
  "historical_context": {
    "start": "1792423770",
    "end": "1792424070",
    "step": "15"
  },
  "provenance": {
    "pod_identity_basis": "NAMESPACE_NAME_UID",
    "replicaset_identity_basis": "NAMESPACE_NAME",
    "replicaset_uid_available": false,
    "owner_api_version_available": false
  },
  "queries": {
    "pod_owner": {"promql": "..."},
    "replicaset_owner": {"promql": "..."}
  },
  "pods": {
    "jobs-api-abc": {
      "required_timestamps": ["1792423920"],
      "ownership": {
        "1792423920": {
          "evidence_status": "VALID",
          "relation": "TARGET_MATCH",
          "pod_identity": {
            "namespace": "app",
            "name": "jobs-api-abc",
            "uid": "..."
          },
          "pod_owner": {
            "kind": "ReplicaSet",
            "name": "jobs-api-123",
            "query_key": "pod_owner",
            "timestamp": "1792423920"
          },
          "replicaset_owner": {
            "kind": "Deployment",
            "name": "jobs-api",
            "query_key": "replicaset_owner",
            "timestamp": "1792423920"
          },
          "evidence_refs": [
            "pods.jobs-api-abc.ownership.1792423920.pod_owner",
            "pods.jobs-api-abc.ownership.1792423920.replicaset_owner"
          ]
        }
      }
    }
  }
}
```

Rules:

- pod keys are deterministic lexicographic order;
- required timestamps are exact canonical decimal strings in numeric order;
- ownership timestamp keys use the same canonical decimal strings;
- `relation` exists only when `evidence_status=VALID`;
- `reason_code` and `reason` exist for `UNKNOWN`;
- `replicaset_owner` exists only if that hop was actually observed/resolved;
- `evidence_refs` contains only observed facts that exist in the report; missing evidence does not get a fabricated ref;
- evidence-ref syntax is the dot path shown above;
- no float is allowed anywhere in the report.

There is no top-level ownership reduction in this slice.

---

## 15. No version/freshness claim

Proving:

```text
Pod → ReplicaSet → Deployment
```

does **not** prove that all evidence came from the same application revision.

A normal rollout may yield:

```text
Deployment jobs-api
  -> ReplicaSet revision A -> Pod A -> historical evidence
  -> ReplicaSet revision B -> Pod B -> historical evidence
```

Both ownership chains can be correct while application versions differ.

Therefore this slice does not consume, emit, or promote `application_version_relation`.

When ownership is later wired into Analyze, `application_version_relation = UNVERIFIED` remains unchanged unless a separately pre-registered version/freshness component proves something stronger.

---

## 16. No cross-timestamp or cross-pod collapse

The first version preserves facts per pod and required timestamp.

It must not create:

```text
worst_ownership
ownership_score
mostly_verified
coverage_percent
verified_pods_percent
```

Nor may it reduce multiple timestamps into one generic status.

A later consumer may define an explicit reduction if required by a particular precondition. This substrate does not choose it.

---

## 17. Determinism requirements

For identical normalized Prometheus responses and identical inputs:

- output ordering is deterministic;
- no current clock is consulted;
- no live Kubernetes state is consulted;
- no random choice resolves ambiguity;
- all timestamp arithmetic is exact decimal arithmetic;
- no float exists recursively in the output;
- the same replay serializes identically under canonical JSON serialization.

Historical ownership must be replayable without a cluster, following the principle established by `PRAEVA-ANALYZE-001`.

---

## 18. Explicit non-goals

This slice does not:

- classify LOW/MEDIUM/HIGH/CRITICAL;
- change `CHANGE-RISK-001`;
- change `CHANGE-JOIN-001`;
- wire ownership into `praeva analyze`;
- decide application-version freshness;
- decide whether mixed ReplicaSet revisions block classification;
- recommend a CPU limit;
- aggregate hazards;
- call an LLM;
- mutate Kubernetes or Git;
- infer ownership from pod-name prefixes;
- treat a regex match as ownership proof;
- use current Kubernetes objects as proof of historical ownership;
- fabricate ReplicaSet UID;
- perform nearest-timestamp matching;
- define a workload-wide ownership score.

---

## 19. RED plan — must fail before implementation

RED tests freeze at least these cases:

1. matching Pod→ReplicaSet→Deployment at one required timestamp produces `VALID/TARGET_MATCH`;
2. valid chain to another Deployment produces `VALID/TARGET_DIFFERS`, not `UNKNOWN`;
3. Pod controller kind other than ReplicaSet produces valid contradiction without an RS lookup;
4. ReplicaSet controller kind other than Deployment produces valid contradiction;
5. missing Pod-owner telemetry at the required timestamp is `UNKNOWN/pod_owner_missing_at_timestamp`;
6. two Pod UIDs simultaneously plausible at one timestamp are `UNKNOWN/pod_identity_ambiguous_at_timestamp`;
7. one Pod UID with multiple controller owners is `UNKNOWN/pod_controller_owner_ambiguous`;
8. missing ReplicaSet-owner telemetry is `UNKNOWN/replicaset_owner_missing_at_timestamp`;
9. multiple ReplicaSet controller owners are `UNKNOWN/replicaset_controller_owner_ambiguous`;
10. owner metric value other than exact decimal `1` is `UNKNOWN/owner_metric_invalid`;
11. Pod name reuse across different timestamps preserves distinct UIDs without silent collapse;
12. ReplicaSet output never fabricates a UID;
13. required timestamp outside interval is input error, not UNKNOWN;
14. required timestamp off the exact evaluation grid is input error, not nearest-neighbor resolution;
15. target namespace differing from acquisition namespace is input error;
16. unsupported target GVK is input error;
17. malformed/missing required KSM labels fail in the adapter as execution/schema error;
18. unexpected Prometheus `resultType` fails through the real adapter;
19. transport failure is execution error, not ownership UNKNOWN;
20. query keeps wrong-kind controller owners visible rather than filtering them away;
21. duplicate scrape-topology series are normalized by the declared `max by (...)` query shape without collapsing distinct owner identities;
22. old ReplicaSet ownership remains resolvable from replayed historical Prometheus data without live Kubernetes access;
23. ownership report contains no `application_version_relation`, risk level, recommendation, freshness decision, ownership score, or generic aggregate;
24. same normalized replay produces byte-identical canonical output;
25. no float appears recursively in normalized evidence or report.

---

## 20. Gate

Before implementation:

- [x] temporal ownership question defined;
- [x] live Kubernetes snapshot rejected as historical proof;
- [x] exact pinned KSM owner wire documented;
- [x] Pod UID support and ReplicaSet UID absence made explicit;
- [x] public module/API boundary frozen;
- [x] exact PromQL shapes frozen;
- [x] exact timestamp-grid semantics frozen;
- [x] evidence-quality and relation axes separated;
- [x] contradictory valid ownership remains visible;
- [x] UNKNOWN vocabulary frozen;
- [x] output wire/evidence-ref syntax frozen;
- [x] application version/freshness remains separate;
- [x] first slice limited to ownership substrate, no Analyze wiring;
- [x] RED plan frozen;
- [ ] RED tests written;
- [ ] RED confirmed while implementation modules are absent;
- [ ] implementation begins only after RED is recorded.
