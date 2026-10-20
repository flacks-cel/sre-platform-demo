# Spike 003 — Evidence Attribution & Population Feasibility

> Status: **PRE-REGISTRATION — no experiment executed yet.**
> Base: `main @ ca4fbec19cbfbe66afde43304299ac7e1ead1255`.
> Branch: `praeva/spike-003-evidence-attribution`.
> This spike is investigative only. It does **not** change `PRAEVA-ANALYZE-001`, `CHANGE-JOIN-001`, `CHANGE-RISK-001`, or `WORKLOAD-OWNERSHIP-001` semantics.

---

## 1. Question

> Can Praeva attribute historical CPU/throttling facts to the target Deployment with enough temporal identity and population evidence to replace `CALLER_ASSERTED`, without silently claiming event-time precision that the available Prometheus/KSM wire cannot prove?

The spike exists because a historical fact derived from `rate(...[W])` has more structure than a point labeled by `max_timestamp`.

For a rate fact evaluated at `T`, the relevant support is conceptually:

```text
[T - W, T]
```

The product must distinguish at least three questions:

1. **workload attribution** — which Pod UID/controller chain is observed for `pod="X"` on the evaluation grid;
2. **identity continuity** — whether the same Pod UID remains the identity behind `pod="X"` across the grid covering the support of the fact;
3. **population completeness** — whether the set of pods observed by Verify is the target Deployment population needed by the logical step being evaluated.

These are not one global `ownership_verified` boolean.

---

## 2. Existing baseline

`WORKLOAD-OWNERSHIP-001` already supplies historical temporal resolution from:

```text
kube_pod_owner
kube_replicaset_owner
```

with exact evaluation timestamps and the per-timestamp states:

```text
evidence_status = VALID | UNKNOWN
relation = TARGET_MATCH | TARGET_DIFFERS   # only when VALID
```

It intentionally does not perform Analyze/Join/Risk wiring, cross-timestamp reduction, cross-pod reduction, version/freshness proof, or population completeness.

`CHANGE-JOIN-001` still exposes:

```text
identity_assertion.status = CALLER_ASSERTED
workload_to_pod_selector_relation = UNVERIFIED
application_version_relation = UNVERIFIED
```

`CHANGE-RISK-001` currently has a risk ladder whose logical requirements are not uniform:

```text
CRITICAL: exists a valid long-window contradiction
HIGH:     exists a short-window contradiction AND all required long windows exclude CRITICAL
MEDIUM:   universal non-contradiction plus insufficient headroom
LOW:      universal non-contradiction plus sufficient headroom
```

Therefore population completeness may affect different risk levels differently. This spike measures the substrate; it does not change that rule.

---

## 3. Pinned wire additions under investigation

The existing lab pin remains:

```text
kube-prometheus-stack 88.6.2
→ kube-state-metrics chart 8.4.1
→ kube-state-metrics 2.20.0
```

For the pinned kube-state-metrics wire, this spike additionally investigates:

```text
kube_pod_created
  pod
  namespace
  uid

kube_pod_container_resource_limits
  pod
  namespace
  container
  uid
  resource
  unit
  ...
```

`kube_pod_created` is a creation-time fact for a Pod UID. It is not itself an ownership proof.

The existing Verify adapter currently aggregates historical CPU-limit evidence by pod name and therefore discards the KSM `uid` label. This spike may query the raw/preserved UID-bearing form separately for comparison, but it must not silently alter `VERIFY-WIRE-001` during the experiment.

---

## 4. Evidence-support model to test

### 4.1 Instantaneous fact

For an instantaneous KSM fact evaluated at `T`, the evidence support is treated as:

```text
{T}
```

Example:

```text
historical effective CPU limit witness at T
```

The spike tests whether Pod UID and target chain can be resolved at that evaluation timestamp without ambiguity.

### 4.2 Rate-derived fact

For a fact derived from:

```text
rate(counter[W]) evaluated at T
```

its declared support is:

```text
[T - W, T]
```

This does **not** mean Praeva can prove continuous event-time ownership at every real instant in that interval.

The candidate operational proof to test is:

```text
same Pod UID on every Praeva evaluation-grid point covering [T-W, T]
AND
TARGET_MATCH on those required ownership evaluation points
AND
kube_pod_created(uid) <= T-W
```

This candidate is intentionally named **evaluation-grid support coverage**, not continuous event-time proof.

The experiment must preserve the residual limitation that a complete name-reuse lifecycle could theoretically occur entirely between two evaluation points. No nearest-neighbor, interpolation, or invented event-time precision is allowed.

### 4.3 Left-edge acquisition

If Verify starts at `start` and the largest rate window is `W_max`, ownership/identity acquisition must be experimentally evaluated over at least:

```text
[start - W_max, end]
```

The spike tests this extended acquisition instead of discarding witnesses near the left edge merely because their support begins before Verify's evaluation interval.

No product default for `W_max` is introduced: the value is derived from the explicit rate windows already supplied to the analysis.

---

## 5. Ownership is not assumed immutable

This spike must not depend on an axiom that a Pod UID's `ownerReferences` can never change.

The tested proof therefore observes the controller chain at the required evaluation points rather than inferring the full interval from one successful ownership observation.

`kube_pod_created` is used only to strengthen the existence/identity boundary of the support; it does not replace temporal owner observations.

---

## 6. Population model to test

For each evaluation timestamp under study, derive two sets independently.

### 6.1 Verify-observed population

```text
V(T) = pods represented by the Verify acquisition at T / for the relevant fact
```

The experiment must record how this set is constructed from the current per-pod Prometheus evidence and where missing rate samples make membership ambiguous.

### 6.2 Target-owned population

```text
O(T) = pods whose historical Pod -> ReplicaSet -> Deployment chain resolves
       as VALID / TARGET_MATCH for the target Deployment at T
```

This set must be derived from historical ownership telemetry in the namespace, not from the user-supplied pod regex or a pod-name prefix.

### 6.3 Set differences

Record explicitly:

```text
missing_target_pods(T) = O(T) - V(T)
extra_observed_pods(T) = V(T) - O(T)
```

Do not collapse the two conditions.

They represent different failure modes:

- omission can hide a worse target pod;
- inclusion can introduce evidence from a foreign workload.

This spike does not freeze whether an extra foreign pod invalidates an entire future analysis or is rejected locally by an attribution layer. It must produce enough evidence to make that later contract explicit.

---

## 7. Risk-ladder consequence to validate, not implement

The spike should construct or identify cases sufficient to validate this logical distinction:

| Population incomplete | Candidate product consequence to evaluate later |
|---|---|
| valid attributed long-window contradiction exists | `CRITICAL` may remain provable |
| candidate `HIGH` | cannot exclude a hidden long-window contradiction; likely `UNKNOWN` |
| candidate `MEDIUM` | universal non-contradiction incomplete; likely `UNKNOWN` |
| candidate `LOW` | universal non-contradiction incomplete; likely `UNKNOWN` |

This table is **not a change to `CHANGE-RISK-001` in this spike**. It is a hypothesis for the later pre-registered integration contract.

The key counterexample to reproduce synthetically if the lab does not naturally produce it is:

```text
Target population: A, B, C
Verify-observed:   A, B
A: short contradiction
A/B: long windows have no contradiction
C: hidden long-window contradiction

Subset-only evaluation could emit HIGH even though the complete target population is CRITICAL.
```

---

## 8. Experimental questions

The spike must answer, with captured raw Prometheus responses where applicable:

1. Does `kube_pod_created` for the current lab provide stable `namespace + pod + uid` identity and a usable Unix creation timestamp historically?
2. Can ownership acquisition over `[start-W_max, end]` be executed on the same explicit evaluation step as Verify without schema or volume problems?
3. For each existing CPU short/long witness, can the spike construct its evaluation-grid support points deterministically?
4. Can one UID be resolved consistently for the pod name across every required support point?
5. Can `kube_pod_created(uid) <= support_start` be proved for those witnesses?
6. Does the Pod -> ReplicaSet -> Deployment chain remain `TARGET_MATCH` across the required evaluation points?
7. Can a UID change within a fact support be detected deterministically from the available KSM telemetry?
8. Can target-owned population `O(T)` be enumerated independently from the Verify regex?
9. Can `V(T)` and `O(T)` be compared without using live Kubernetes state as historical evidence?
10. Do normal lab runs expose `missing_target_pods` or `extra_observed_pods` under the current `jobs-api-.*` selector?
11. What happens during an actual rollout/HPA churn boundary?
12. Is query/result volume still small enough for replay fixtures and deterministic CI tests?
13. Does the current wire expose any systematic condition that makes evaluation-grid support coverage practically unattainable?

---

## 9. Required scenarios

At minimum capture or synthesize deterministic fixtures for these scenarios.

### S1 — mature stable pod

A rate witness whose support is fully covered by one Pod UID and `TARGET_MATCH` throughout the required evaluation grid.

Expected experimental outcome:

```text
support attribution can be proven under the candidate model
```

### S2 — pod created inside rate support

`kube_pod_created(uid) > support_start`.

Expected experimental outcome:

```text
candidate support proof must not be called complete
```

The spike records exactly how Prometheus `rate()` behaved for the young series; it must not reinterpret this as an ownership error.

### S3 — UID change for same pod name

Synthetic fixture is acceptable if the Deployment lab cannot naturally reproduce deterministic name reuse.

Expected experimental outcome:

```text
identity continuity failure is detected separately from ownership relation
```

### S4 — TARGET_DIFFERS

An observed pod resolves validly to another controller/Deployment.

Expected experimental outcome:

```text
contradictory ownership remains VALID/TARGET_DIFFERS
```

Do not convert the ownership evidence itself into `UNKNOWN`.

### S5 — missing target pod

`O(T) - V(T)` is non-empty.

Expected experimental outcome:

```text
population omission is observable and named
```

### S6 — extra observed pod

`V(T) - O(T)` is non-empty.

Expected experimental outcome:

```text
foreign acquisition is observable and named independently of omission
```

### S7 — left-edge support

A witness at or near Verify `start` whose `T-W` precedes Verify `start` but is covered by the extended ownership acquisition.

Expected experimental outcome:

```text
support is testable without dropping the witness solely because of the analysis left edge
```

### S8 — population-incomplete HIGH counterexample

Synthetic deterministic fixture containing A/B observed and C omitted with a long-window contradiction.

Expected experimental outcome:

```text
subset-only universal reasoning is demonstrably unsafe for HIGH
```

---

## 10. Candidate diagnostic vocabulary for the spike

These names are experimental outputs only; they are **not product reason codes yet**:

```text
uid_not_present_at_support_start
uid_change_within_support_grid
ownership_unknown_within_support_grid
ownership_target_differs_within_support_grid
missing_target_pod
extra_observed_pod
population_unknown_at_timestamp
```

Existing frozen `WORKLOAD-OWNERSHIP-001` UNKNOWN reason codes remain unchanged.

The spike must not silently reuse `cpu_evidence_incomplete` for an attribution/population failure because those conditions carry different remediation.

---

## 11. Data to capture

For each real-lab run, persist enough raw evidence to replay the experiment offline:

```text
CPU short query_range raw response
CPU long query_range raw response
CFS throttling short/long raw responses when used
historical CPU limit raw response
kube_pod_owner raw response
kube_replicaset_owner raw response
kube_pod_created raw response
```

If UID-preserving historical resource-limit evidence is queried separately, capture that raw response too.

Record:

```text
start
end
step
short_window
long_window
W_max
extended_ownership_start
namespace
target Deployment
container
pod regex
Prometheus version
KSM/chart pin
```

A replay must use the real normalization/resolution paths wherever practical, following the precedent of `PRAEVA-ANALYZE-001`.

---

## 12. No-goals

This spike does not:

- wire ownership into `praeva analyze`;
- modify `CHANGE-JOIN-001`;
- modify `CHANGE-RISK-001`;
- create a global ownership score;
- create a verified percentage;
- redefine existing risk levels;
- prove application revision/image/version homogeneity;
- change `application_version_relation = UNVERIFIED`;
- introduce nearest-neighbor ownership matching;
- claim continuous event-time identity;
- add recommendation/sizing behavior;
- choose policy for foreign acquired pods;
- support arbitrary workload kinds beyond the current `apps/Deployment` ownership substrate.

---

## 13. Version/freshness guardrail

Even perfect results in this spike prove only attribution to the target Deployment and bounded identity continuity under the declared evaluation-grid model.

They do **not** prove that all evidence belongs to one ReplicaSet revision, one container image, or one application version.

A Deployment may legitimately own multiple ReplicaSets during rollout.

Therefore:

```text
application_version_relation = UNVERIFIED
```

must remain unchanged until a separate pre-registered component proves stronger version/freshness semantics.

---

## 14. Exit criteria

The spike is complete only when the findings can answer all of the following without product-policy guesswork:

- [ ] exact support-grid construction for instantaneous and rate-derived facts is demonstrated;
- [ ] extended ownership acquisition `[start-W_max, end]` is tested;
- [ ] `kube_pod_created` existence-bound check is tested;
- [ ] same-UID continuity on the support grid is tested;
- [ ] target ownership on the support grid is tested;
- [ ] target-owned population enumeration is demonstrated;
- [ ] observed-vs-owned set difference is demonstrated;
- [ ] missing and extra populations are kept separate;
- [ ] left-edge witness is exercised;
- [ ] young-pod support is exercised;
- [ ] UID-change fixture is exercised;
- [ ] population-incomplete HIGH counterexample is exercised;
- [ ] raw Prometheus evidence is replayable offline;
- [ ] practical query volume and runtime are recorded;
- [ ] limitations are written before proposing product wiring.

Only after these findings may a later contract decide the shape and location of an evidence-attribution layer and how each risk-ladder step consumes its result.

---

## 15. Freeze rule

After the first evidential run, do not change the hypotheses or exit criteria merely to make the observed lab behavior pass.

Unexpected behavior may add a new finding or motivate a new spike/contract, but it must not be retrofitted into this pre-registration as though it had been predicted.
