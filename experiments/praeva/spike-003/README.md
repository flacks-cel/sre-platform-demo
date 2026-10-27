# Spike 003 — Evidence Attribution & Population Feasibility

> Status: **PRE-REGISTRATION — no experiment executed yet.**
> Base: `main @ ca4fbec19cbfbe66afde43304299ac7e1ead1255`.
> Branch: `praeva/spike-003-evidence-attribution`.
> This spike is investigative only. It does **not** change `PRAEVA-ANALYZE-001`, `CHANGE-JOIN-001`, `CHANGE-RISK-001`, or `WORKLOAD-OWNERSHIP-001` semantics.

---

## 1. Question

> Can Praeva attribute historical CPU/throttling facts to the target Deployment with enough temporal identity and population evidence to replace `CALLER_ASSERTED`, without silently claiming event-time precision that the available Prometheus/KSM wire cannot prove?

The spike exists because a historical fact derived from `rate(...[W])` has more structure than a point labeled by `max_timestamp`.

For a rate fact evaluated at `T`, define the **support envelope** as:

```text
[T - W, T]
```

This is deliberately an envelope, not a claim that Prometheus selected raw samples at both endpoints. A Prometheus range vector uses a left-open/right-closed raw sample interval `(T-W, T]`, while `rate()` may extrapolate the calculated rate to the range boundaries. The experiment must keep those semantics distinct.

The product must distinguish at least three questions:

1. **workload attribution** — which Pod UID/controller chain is observed for `pod="X"` on the evaluation grid;
2. **identity continuity** — whether the same Pod UID remains the identity behind `pod="X"` across the grid covering the support envelope of the fact;
3. **population completeness** — whether the evidence domain contains the target Deployment population needed by the logical step being evaluated.

These are not one global `ownership_verified` boolean.

---

## 2. Existing baseline

`WORKLOAD-OWNERSHIP-001` already supplies historical temporal resolution from:

```text
kube_pod_owner
kube_replicaset_owner
```

with exact **Prometheus evaluation timestamps** and the per-timestamp states:

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

### 3.1 Evaluation timestamp is not scrape timestamp

The ownership wire is evaluated through PromQL instant-vector semantics at each `query_range` evaluation time. The sample used by an instant selector may have been scraped before the evaluation timestamp, subject to Prometheus lookback/staleness semantics.

The spike must therefore record this distinction instead of saying that a KSM sample was physically scraped exactly at the evaluation timestamp.

Where practical, diagnostic companion queries should expose the source-sample timestamp by applying `timestamp()` **before** aggregation, for example conceptually:

```promql
max by (namespace, pod, uid, owner_kind, owner_name, owner_is_controller) (
  timestamp(kube_pod_owner{...})
)
```

This is diagnostic provenance only. The spike does not introduce a freshness threshold.

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

define:

```text
support_start    = T - W
support_envelope = [support_start, T]
raw range vector = (support_start, T]
```

The closed support envelope is used for conservative identity reasoning because `rate()` extrapolates to the boundaries. It does **not** mean Praeva can prove continuous event-time ownership at every real instant in that interval.

The candidate operational proof to test is:

```text
same Pod UID on every required Praeva ownership evaluation point in the support envelope
AND
TARGET_MATCH on those required ownership evaluation points
AND
kube_pod_created(uid) <= support_start
```

This candidate is intentionally named **evaluation-grid support coverage**, not continuous event-time proof.

The experiment must preserve residual limitations explicitly. Events can occur entirely between two evaluation points, including a short-lived name-reuse lifecycle or a controller-owner mutation that begins and ends between observations. No nearest-neighbor, interpolation, or invented event-time precision is allowed.

### 4.3 Verify grid and phase-aligned extended ownership grid

Let the Verify evaluation grid be:

```text
G_verify = { start + n*step | n >= 0 and point <= end }
```

Every Verify witness timestamp `T` must be one of those evaluation points.

A naive ownership start of exactly `start-W_max` is unsafe when `W_max` is not an integer multiple of `step`, because it shifts the phase of `query_range` and may no longer evaluate ownership at the same timestamps as Verify.

The phase-aligned candidate to test is:

```text
extension_steps         = ceil(W_max / step)
extended_ownership_start = start - extension_steps*step

G_ownership = {
  extended_ownership_start + n*step
  | n >= 0 and point <= end
}
```

This guarantees:

```text
extended_ownership_start <= start - W_max
G_verify ⊆ G_ownership
```

while preserving exact decimal arithmetic and the Verify grid phase.

For a witness `(T, W)`, the first candidate support-grid definition is:

```text
G_support(T,W) = {
  g in G_ownership
  | support_start <= g <= T
}
```

If `support_start` itself is not on `G_ownership`, the spike must **not** silently round it and call the boundary proven. It must test whether the creation bound plus the first grid observation is sufficient for the eventual contract, or whether an additional boundary/shifted-grid query is required. This is an experimental question, not a decision hidden in the implementation.

### 4.4 Left-edge acquisition

Ownership/identity acquisition is therefore tested over the phase-aligned interval:

```text
[extended_ownership_start, end]
```

rather than discarding witnesses near Verify's left edge merely because their support begins before `start`.

No product default for `W_max` is introduced: the value is derived from the explicit rate windows already supplied to the analysis.

---

## 5. Ownership is not assumed immutable

This spike must not depend on an axiom that a Pod UID's `ownerReferences` can never change.

The tested proof therefore observes the controller chain at the required evaluation points rather than inferring the full interval from one successful ownership observation.

`kube_pod_created` is used only to strengthen the existence/identity boundary of the support; it does not replace temporal owner observations.

The spike must also distinguish:

```text
Prometheus evaluation time
KSM source-sample time
Kubernetes event time
```

Only the first two are observable through the proposed wire. Continuous Kubernetes event-time history is not claimed.

---

## 6. Population model to test

A single `V(T)` is too coarse because absence from a derived `rate()` result can mean something different from exclusion by the user selector. The spike must keep selector scope and derived-evidence availability separate.

### 6.1 Target-owned population

For each evaluation timestamp `T`:

```text
O(T) = pods whose historical Pod -> ReplicaSet -> Deployment chain resolves
       as VALID / TARGET_MATCH for the target Deployment at T
```

This set must be derived from historical ownership telemetry in the namespace, not from the user-supplied pod regex or a pod-name prefix.

### 6.2 Selector-admitted target population

For the same `T`, evaluate the declared pod regex against the names in `O(T)`:

```text
S_target(T) = { pod in O(T) | pod name matches the declared pod regex }
```

This is a syntactic selector-scope fact. It does not require the pod to have produced a CPU/rate sample.

Then:

```text
selector_omissions(T) = O(T) - S_target(T)
```

A selector omission is therefore distinguishable from missing telemetry.

### 6.3 Per-fact Verify evidence population

For every relevant Verify query/fact family `q`, define:

```text
V_q(T) = pods for which the current Verify acquisition produced a usable q result at T
```

Examples include:

```text
V_cpu_short(T)
V_cpu_long(T)
V_cfs_short(T)
V_cfs_long(T)
V_cpu_limit(T)
```

The spike must document precisely how each `V_q(T)` is reconstructed from raw/current adapter output.

For target pods that are selector-admitted but lack a derived fact:

```text
derived_evidence_missing_q(T) = S_target(T) - V_q(T)
```

This may happen for reasons such as a young series with too few counter samples. It must not be mislabeled as a regex omission.

### 6.4 Foreign/unattributable observed population

For each `q`:

```text
extra_observed_q(T) = V_q(T) - O(T)
```

The spike must further separate, where the ownership substrate permits it:

```text
foreign_target_differs_q(T) = observed pods with VALID/TARGET_DIFFERS
ownership_unresolved_q(T)   = observed pods whose ownership is UNKNOWN
```

Do not collapse foreign evidence and unresolved evidence.

### 6.5 Set differences are diagnostics, not product policy

The conditions represent different failure modes:

- selector omission can hide a worse target pod;
- selector-admitted but missing derived evidence is an evidence-completeness problem;
- inclusion can introduce evidence from a foreign workload;
- unresolved ownership means the acquired fact cannot yet be attributed.

This spike does not freeze whether an extra foreign pod invalidates an entire future analysis or is rejected locally by an attribution layer. It must produce enough evidence to make that later contract explicit.

---

## 7. Risk-ladder consequence to validate, not implement

The spike should construct or identify cases sufficient to validate this logical distinction:

| Population/evidence incomplete | Candidate product consequence to evaluate later |
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
2. Can phase-aligned ownership acquisition over `[extended_ownership_start, end]` be executed on the same explicit evaluation step as Verify without schema or volume problems?
3. Does `G_verify` remain an exact subset of `G_ownership` for the real run?
4. For each existing CPU short/long witness, can the spike construct its support envelope and candidate support-grid points deterministically?
5. What happens when `W` is not an integer multiple of `step`; is a separate boundary/shifted grid required?
6. Can one UID be resolved consistently for the pod name across every required support point?
7. Can `kube_pod_created(uid) <= support_start` be proved for those witnesses?
8. Does the Pod -> ReplicaSet -> Deployment chain remain `TARGET_MATCH` across the required evaluation points?
9. Can a UID change within a fact support be detected deterministically from the available KSM telemetry?
10. Can target-owned population `O(T)` be enumerated independently from the Verify regex?
11. Can selector omission be distinguished from selector-admitted-but-missing derived telemetry?
12. Can per-fact `V_q(T)` and `O(T)` be compared without using live Kubernetes state as historical evidence?
13. Do normal lab runs expose selector omissions, missing derived evidence, foreign observed pods, or unresolved ownership under the current `jobs-api-.*` selector?
14. What happens during an actual rollout/HPA churn boundary?
15. What is the observed difference between KSM source-sample timestamps and Prometheus evaluation timestamps?
16. Is query/result volume still small enough for replay fixtures and deterministic CI tests?
17. Does the current wire expose any systematic condition that makes evaluation-grid support coverage practically unattainable?

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

### S5 — selector omission

A target-owned pod exists in `O(T)` but its name does not satisfy the declared regex.

Expected experimental outcome:

```text
selector omission is observable independently of telemetry completeness
```

### S6 — selector-admitted target pod without derived rate evidence

A target-owned pod matches the regex but does not produce a usable rate-derived result at `T`.

Expected experimental outcome:

```text
missing derived telemetry is not mislabeled as selector omission
```

### S7 — extra observed pod

A Verify fact is produced for a pod that is not in `O(T)`.

Expected experimental outcome:

```text
foreign/unresolved acquisition is observable and named independently of omission
```

### S8 — left-edge support

A witness at or near Verify `start` whose support begins before Verify `start` but is covered by the phase-aligned extended ownership acquisition.

Expected experimental outcome:

```text
support is testable without dropping the witness solely because of the analysis left edge
```

### S9 — population-incomplete HIGH counterexample

Synthetic deterministic fixture containing A/B observed and C omitted with a long-window contradiction.

Expected experimental outcome:

```text
subset-only universal reasoning is demonstrably unsafe for HIGH
```

### S10 — non-divisible window/step

Synthetic deterministic fixture where `W % step != 0`.

Expected experimental outcome:

```text
phase alignment is preserved and support_start is not silently rounded into a proof
```

### S11 — stale/lookback diagnostic

Capture source-sample timestamps for KSM owner observations and compare them with evaluation timestamps, including at least one churn boundary if the lab provides one.

Expected experimental outcome:

```text
evaluation time and source-sample time remain explicitly distinguishable
```

No freshness threshold is chosen in this spike.

---

## 10. Candidate diagnostic vocabulary for the spike

These names are experimental outputs only; they are **not product reason codes yet**:

```text
uid_not_present_at_support_start
uid_change_within_support_grid
ownership_unknown_within_support_grid
ownership_target_differs_within_support_grid
support_boundary_not_on_grid
selector_omission
derived_evidence_missing
foreign_target_differs
ownership_unresolved
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

Where practical, also capture diagnostic source-sample timestamp responses for:

```text
kube_pod_owner
kube_replicaset_owner
kube_pod_created
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
extension_steps
extended_ownership_start
namespace
target Deployment
container
pod regex
Prometheus version
Prometheus lookback configuration if exposed by the server
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
- claim continuous event-time identity or ownership;
- add recommendation/sizing behavior;
- choose policy for foreign acquired pods;
- choose an evidence-freshness threshold;
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

Prometheus/KSM source-sample age recorded by this spike is acquisition provenance. It must not be reinterpreted as `application_version_relation`.

---

## 14. Exit criteria

The spike is complete only when the findings can answer all of the following without product-policy guesswork:

- [ ] exact support-envelope and raw range-vector semantics are demonstrated;
- [ ] phase-aligned extended ownership acquisition is tested;
- [ ] `G_verify ⊆ G_ownership` is demonstrated for the real run;
- [ ] non-divisible `W/step` behavior is exercised without silent boundary rounding;
- [ ] `kube_pod_created` existence-bound check is tested;
- [ ] same-UID continuity on the support grid is tested;
- [ ] target ownership on the support grid is tested;
- [ ] KSM evaluation time versus source-sample time is measured;
- [ ] target-owned population enumeration is demonstrated;
- [ ] selector omission is separated from missing derived evidence;
- [ ] foreign TARGET_DIFFERS is separated from ownership UNKNOWN;
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
