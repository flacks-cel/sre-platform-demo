# WORKLOAD-OWNERSHIP-001 — Historical workload ownership evidence

> Status: **DESIGN DRAFT — no implementation or RED yet.**
> Base: `main @ e158e8922a6d79c4eee17b9d6522373f19fbaad0`.
> Motivation: replace the current `CALLER_ASSERTED / UNVERIFIED` workload→pod relation with historical evidence before adding a second hazard.
>
> This document is intentionally committed before tests or implementation. Its semantics must be frozen in a later commit before RED starts.

---

## 1. Question

> For each historical pod evidence witness used by Praeva, can we prove from historical Kubernetes ownership telemetry that the pod belonged to the named `apps/Deployment` at the timestamp of that evidence?

The key phrase is **at the timestamp of that evidence**.

A live Kubernetes snapshot is insufficient. During normal rollout, a pod or ReplicaSet that produced historical evidence may already be gone when analysis runs. Ownership is therefore a temporal evidence problem, not only a structural lookup problem.

---

## 2. Why this is a separate substrate

`CHANGE-JOIN-001` deliberately records:

```text
identity_assertion.status = CALLER_ASSERTED
workload_to_pod_selector_relation = UNVERIFIED
application_version_relation = UNVERIFIED
```

That slice does not query Kubernetes or Prometheus for ownership and explicitly leaves `Pod -> ReplicaSet -> Deployment` for a later slice.

`WORKLOAD-OWNERSHIP-001` supplies historical ownership facts only. It does **not** classify change risk and does **not** change `CHANGE-RISK-001` semantics.

A later wiring slice may consume this output to replace `CALLER_ASSERTED / UNVERIFIED` where the evidence supports it.

---

## 3. Source of truth: historical KSM telemetry

Normative evidence comes from Prometheus range queries over kube-state-metrics owner gauges:

```text
kube_pod_owner
kube_replicaset_owner
```

The Kubernetes live API is not authoritative for this slice because deleted pods and old ReplicaSets are normal historical inputs.

The same acquisition interval used by Verify is reused explicitly:

```text
start
end
step
```

There are no ownership-specific hidden defaults and no implicit "now" lookup.

Transport/schema failure remains an execution error. Missing historical ownership telemetry is evidence incompleteness, not transport failure.

---

## 4. Unit of proof is temporal

Ownership is not asserted once for a pod name across an entire report.

The atomic fact is conceptually:

```text
(namespace, pod, timestamp)
    -> controller owner
    -> ReplicaSet
    -> controller owner at the same timestamp
    -> Deployment
```

The target is a specific workload identity:

```text
api_group = apps
kind = Deployment
namespace = ...
name = ...
```

A successful chain at timestamp `T1` does not prove the chain at `T2`.

---

## 5. Evidence timestamps are caller-supplied facts, not a policy

The component does not decide which historical CPU/throttling fact matters.

Its input includes, per pod, the exact timestamps whose ownership must be resolved. Those timestamps come from upstream evidence witnesses already selected by deterministic substrate logic.

This avoids introducing a new policy such as:

```text
"ownership must be valid for every scrape in the whole window"
```

or:

```text
"ownership at the end of the window is enough"
```

Neither statement is pre-registered here.

Each required timestamp must lie inside the explicit acquisition interval. Whether it must also lie exactly on the `start/end/step` evaluation grid is an implementation-contract decision to freeze before RED.

---

## 6. Relation and evidence quality remain separate

A valid ownership observation that points somewhere else is not `UNKNOWN`.

Per required timestamp, the output keeps two axes separate:

```text
evidence_status = VALID | UNKNOWN
relation        = TARGET_MATCH | TARGET_DIFFERS   # only when evidence_status=VALID
```

Examples:

### 6.1 Valid matching chain

```text
Pod jobs-api-abc
  -> ReplicaSet jobs-api-123
  -> Deployment jobs-api
```

for target `apps/Deployment app/jobs-api`:

```text
evidence_status = VALID
relation = TARGET_MATCH
```

### 6.2 Valid contradictory chain

If the valid controller chain points to another Deployment, or the pod controller kind is not `ReplicaSet`:

```text
evidence_status = VALID
relation = TARGET_DIFFERS
```

The component preserves the observed chain. It does not hide contradiction behind `UNKNOWN`.

### 6.3 Missing or ambiguous historical evidence

If the chain cannot be resolved from telemetry at the required timestamp:

```text
evidence_status = UNKNOWN
```

with a named reason code.

Missing telemetry never means `TARGET_MATCH`.

---

## 7. Controller ownership only

The proof follows Kubernetes controller ownership, not arbitrary owner references.

For the Pod hop, the expected Deployment path is:

```text
Pod --controller--> ReplicaSet
```

For the ReplicaSet hop:

```text
ReplicaSet --controller--> Deployment
```

The collector must not silently choose one candidate when multiple controller-owner observations are simultaneously valid at a required timestamp.

Ambiguous controller ownership is `UNKNOWN`, not an arbitrary deterministic pick.

---

## 8. Pod name reuse and UID provenance

Pod names are not assumed to be globally unique through time.

If `kube_pod_owner` exposes pod UID provenance, the output preserves it per historical observation. A pod name that maps to different UIDs at different timestamps is not automatically an error: that can be legitimate delete/recreate behavior.

What is forbidden is silently collapsing multiple simultaneously plausible pod identities at one required timestamp into one owner chain.

Exact UID requirements depend on the KSM wire actually available in the lab and must be frozen before RED. No risk policy may depend on UID until that wire contract is explicit.

---

## 9. No version claim

Proving:

```text
Pod -> ReplicaSet -> Deployment
```

does **not** prove that all evidence came from the same application revision.

A normal rollout may yield:

```text
Deployment jobs-api
  -> ReplicaSet revision A -> Pod A -> historical evidence
  -> ReplicaSet revision B -> Pod B -> historical evidence
```

Both ownership chains can be correct while application versions differ.

Therefore this slice does not promote:

```text
application_version_relation = UNVERIFIED
```

into any stronger state.

Ownership identity and application-version relation remain separate facts.

Any freshness/version policy requires a later pre-registration.

---

## 10. No cross-timestamp collapse in the first contract

The first version should preserve ownership facts per pod and required timestamp.

It must not invent a generic summary such as:

```text
worst_ownership
ownership_score
mostly_verified
coverage_percent
```

A later consumer may define an explicit reduction if needed.

This keeps normal rollout and partial historical evidence visible instead of hiding them in a single status.

---

## 11. Proposed pure semantic output shape

Conceptually:

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
    "start": "...",
    "end": "...",
    "step": "15"
  },
  "queries": {
    "pod_owner": {"promql": "..."},
    "replicaset_owner": {"promql": "..."}
  },
  "pods": {
    "jobs-api-...": {
      "required_timestamps": ["..."],
      "ownership": {
        "...": {
          "evidence_status": "VALID",
          "relation": "TARGET_MATCH",
          "pod_uid": "...",
          "pod_owner": {
            "kind": "ReplicaSet",
            "name": "jobs-api-..."
          },
          "replicaset_owner": {
            "kind": "Deployment",
            "name": "jobs-api"
          },
          "evidence_refs": ["..."]
        }
      }
    }
  }
}
```

The exact wire is not frozen by this draft yet.

---

## 12. Determinism requirements

For identical normalized Prometheus responses and identical inputs:

- output ordering is deterministic;
- no current clock is consulted;
- no live Kubernetes state is consulted;
- no random choice resolves ambiguity;
- no float is required for ownership semantics;
- the same replay must serialize identically under canonical JSON serialization.

Historical ownership should be replayable without a cluster, following the same principle established by `PRAEVA-ANALYZE-001`.

---

## 13. Explicit non-goals

This slice does not:

- classify LOW/MEDIUM/HIGH/CRITICAL;
- change `CHANGE-RISK-001`;
- decide application-version freshness;
- decide whether mixed ReplicaSet revisions block classification;
- recommend a CPU limit;
- aggregate hazards;
- call an LLM;
- mutate Kubernetes or Git;
- infer ownership from pod-name prefixes;
- treat a regex match as ownership proof;
- use the current Kubernetes snapshot as proof of historical ownership.

---

## 14. Candidate UNKNOWN reason codes to freeze before RED

The first RED contract should explicitly cover at least:

```text
pod_owner_missing_at_timestamp
pod_controller_owner_ambiguous
replicaset_owner_missing_at_timestamp
replicaset_controller_owner_ambiguous
owner_metric_invalid
required_timestamp_outside_acquisition
```

Whether additional schema-specific reason codes are needed must be decided before implementation.

---

## 15. Candidate RED cases

Before implementation, tests should freeze at least:

1. matching Pod→ReplicaSet→Deployment chain at one required timestamp;
2. valid chain to another Deployment produces `TARGET_DIFFERS`, not `UNKNOWN`;
3. Pod controller kind other than ReplicaSet is valid contradictory evidence;
4. missing pod-owner telemetry is `UNKNOWN`;
5. multiple controller owners at one timestamp are `UNKNOWN`;
6. missing ReplicaSet-owner telemetry is `UNKNOWN`;
7. multiple ReplicaSet controller owners at one timestamp are `UNKNOWN`;
8. old ReplicaSet evidence remains resolvable from historical Prometheus data even if no live object is consulted;
9. two timestamps for the same pod name may resolve through different historical observations without silent collapse;
10. ownership proof does not modify `application_version_relation`;
11. no pod-name-prefix or regex match is accepted as proof;
12. same replay produces byte-identical canonical output;
13. transport/schema failure is execution failure, not ownership `UNKNOWN`;
14. output contains no risk level, recommendation, freshness decision or ownership score.

---

## 16. Decisions still open in this draft

These must be closed **before RED**:

1. exact public Python API and module boundary;
2. exact KSM label/wire requirements, including UID handling;
3. exact PromQL query shapes;
4. whether required timestamps must exactly match the acquisition evaluation grid;
5. exact output wire and evidence-ref syntax;
6. final UNKNOWN reason-code vocabulary;
7. whether the first slice includes only the ownership evidence component or also product-level Analyze wiring.

No implementation should start while this section is non-empty.
