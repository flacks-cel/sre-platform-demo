# Spike 003 — R2 Churn / Rollout Runbook

> Status: **R2 preregistered before execution.**
> This runbook is experiment-only. It does not change Praeva product semantics, `WORKLOAD-OWNERSHIP-001`, `CHANGE-JOIN-001`, `CHANGE-RISK-001`, or Analyze wiring.

## 1. Purpose

R2 exercises the remaining real-lab churn boundary for SPIKE-003.

The experiment intentionally creates one controlled Deployment rollout while keeping image, CPU resources, selector labels, container name, HPA configuration, and application behavior unchanged.

The questions are observational:

1. Can the historical wire reconstruct the old and new Pod/ReplicaSet populations around a real rollout?
2. Do Pod UID, `kube_pod_created`, Pod -> ReplicaSet -> Deployment ownership, and KSM source-sample timestamps remain mechanically distinguishable across the boundary?
3. Can a rate witness whose support overlaps the rollout be diagnosed without inventing continuous event-time identity or application-version semantics?
4. Does the rollout expose transient selector/population/evidence states that the stable R1 could not exercise?

R2 does **not** attempt to prove application revision/image/version homogeneity. `application_version_relation` remains `UNVERIFIED`.

## 2. Why the mutation is an annotation-only Pod-template change

The current ArgoCD Application has automated sync with `selfHeal=true`. A direct `kubectl rollout restart` while self-heal is active could be reverted as drift and create an uncontrolled second rollout.

For R2, automated sync is temporarily suspended before the mutation and restored only after the evidential window is captured.

The controlled mutation adds one annotation to `Deployment/jobs-api.spec.template.metadata.annotations`. Any Pod-template change creates a new ReplicaSet, while this chosen mutation does not deliberately alter:

- container image;
- application code;
- CPU/memory requests or limits;
- Deployment selector labels;
- Pod `app=jobs-api` label;
- HPA settings;
- container name.

The annotation key is:

```text
praeva-spike-003-churn
```

Its value is a run-specific UTC nonce.

## 3. Frozen parameters

```text
run_id                  = R2-churn-rollout
prometheus_url           = http://localhost:9091
namespace                = app
api_group                = apps
kind                     = Deployment
workload                 = jobs-api
container                = jobs-api
pod_regex                = jobs-api-.*
step                     = 15s
short_window             = 2m
long_window              = 5m
W_max                    = 300s
pre_mutation_analysis    = 300s
post_mutation_analysis   = 600s
ingestion_lag            = 120s
rollout_timeout          = 180s
```

R2 preserves the same 15-second evaluation-grid phase used by R1.

## 4. Mechanically derived interval

Record two Unix-second timestamps around the single mutation:

```text
mutation_before = UTC Unix time immediately before kubectl patch
mutation_after  = UTC Unix time immediately after kubectl patch returns
```

Derive grid bounds mechanically:

```text
mutation_grid_before = floor(mutation_before / 15) * 15
mutation_grid_after  = ceil(mutation_after / 15) * 15

analysis_start = mutation_grid_before - 300s
analysis_end   = mutation_grid_after  + 600s

extension_steps          = ceil(300 / 15) = 20
extended_ownership_start = analysis_start - 20*15s
                         = analysis_start - 300s
```

Thus the ownership acquisition reaches approximately ten minutes before the mutation and the analysis reaches at least ten minutes after the mutation.

No interval is retimed after observing whether the rollout looks favorable. If the rollout is unusually slow or incomplete inside the frozen window, that is an experimental observation, not permission to move the window.

Collection must not occur before:

```text
analysis_end + ingestion_lag
```

## 5. Pre-mutation gates

Do not mutate the Deployment until all of the following are true.

### 5.1 Prometheus ready

```bash
curl -fsS http://localhost:9091/-/ready
```

Expected transport result:

```text
Prometheus Server is Ready.
```

### 5.2 Target healthy before mutation

Capture, do not interpret beyond readiness:

```bash
kubectl get deployment jobs-api -n app -o wide
kubectl get pods -n app -l app=jobs-api -o wide
kubectl get rs -n app -l app=jobs-api -o wide
kubectl get hpa jobs-api -n app
```

The Deployment must be Available before the mutation. If it is already rolling, scaling unusually, or unavailable, do not start R2.

### 5.3 Required-series trailing availability

Before mutation, required target series must have a continuous evaluation-grid presence sufficient to cover at least:

```text
pre_mutation_analysis + W_max = 600s
```

for the required CPU/throttling/CPU-limit/Pod-owner/ReplicaSet-owner/Pod-created families.

This gate is series availability only. It does not prove ownership, population completeness, freshness, or raw-scrape continuity.

A dedicated R2 helper may implement this gate. Until that helper exists, R2 must not be executed from an ad-hoc visual judgment.

### 5.4 Record initial ArgoCD policy

Capture:

```bash
kubectl get application jobs-api -n argocd -o json
```

R2 expects the initial Application to contain automated sync with prune and self-heal enabled. If the live policy differs, preserve the observation and stop instead of guessing how to restore it.

## 6. Required pre-mutation snapshots

Persist the following before suspending automated sync:

```text
Application/jobs-api JSON
Deployment/jobs-api JSON
ReplicaSets with label app=jobs-api JSON
Pods with label app=jobs-api JSON
HPA/jobs-api JSON
UTC wall-clock timestamp
```

These snapshots are experiment provenance, not historical ownership evidence for arbitrary past timestamps.

## 7. Suspend ArgoCD automated sync

Remove only `spec.syncPolicy.automated`, preserving the rest of `syncPolicy`:

```bash
kubectl patch application jobs-api -n argocd \
  --type=merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'
```

Verify:

```bash
kubectl get application jobs-api -n argocd \
  -o jsonpath='{.spec.syncPolicy.automated}'
printf '\n'
```

The result must be empty/null before mutating the Deployment.

Do not change the Git source revision, Helm values, HPA, or Deployment replica count for R2.

## 8. Single controlled rollout mutation

Generate the run nonce:

```bash
R2_NONCE="r2-$(date -u +%Y%m%dT%H%M%SZ)"
```

Record the timestamp immediately before the patch:

```bash
MUTATION_BEFORE="$(date -u +%s)"
```

Apply exactly one Pod-template annotation mutation:

```bash
kubectl patch deployment jobs-api -n app \
  --type=merge \
  -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"praeva-spike-003-churn\":\"${R2_NONCE}\"}}}}}"
```

Immediately record:

```bash
MUTATION_AFTER="$(date -u +%s)"
printf 'R2_NONCE=%s\nMUTATION_BEFORE=%s\nMUTATION_AFTER=%s\n' \
  "$R2_NONCE" "$MUTATION_BEFORE" "$MUTATION_AFTER"
```

No second mutation is allowed inside the evidential window.

## 9. Observe rollout without steering it

Run:

```bash
kubectl rollout status deployment/jobs-api -n app --timeout=180s
```

Record the command result and its completion timestamp, but **do not** use rollout completion time to move `analysis_end`.

Capture immediate post-rollout state:

```bash
kubectl get deployment jobs-api -n app -o json
kubectl get rs -n app -l app=jobs-api -o json
kubectl get pods -n app -l app=jobs-api -o json
```

Do not delete old Pods/ReplicaSets, scale replicas manually, or trigger load specifically to make the timeline cleaner.

HPA is allowed to continue its ordinary behavior. If HPA scaling overlaps the rollout naturally, record it as observed churn; do not suppress or manufacture it after R2 starts.

## 10. Required Prometheus collection

Using the frozen R2 interval, capture the same raw response families as R1:

```text
cpu_short
cpu_long
cfs_throttled_short
cfs_throttled_long
cpu_limit
cpu_limit_uid
pod_owner
replicaset_owner
pod_created
pod_owner_source_timestamp
replicaset_owner_source_timestamp
pod_created_source_timestamp
Prometheus buildinfo
Prometheus flags, when available
```

Ownership/creation queries:

```text
start = extended_ownership_start
end   = analysis_end
step  = 15s
```

Verify-equivalent fact queries:

```text
start = analysis_start
end   = analysis_end
step  = 15s
```

The collection must persist exact query text, start/end/step, mutation timestamps, nonce, and response bytes for replay.

## 11. Required analysis after collection

R2 must reconstruct, without live-state substitution for historical timestamps:

1. Pod identities `(namespace, pod, uid)` across the full ownership grid.
2. Pod -> ReplicaSet -> Deployment relation at every required point.
3. `kube_pod_created(uid)` for old and new Pods.
4. `O(T)`, `S_target(T)`, and each available `V_q(T)` across the boundary.
5. old/new ReplicaSet overlap and Pod-population transitions.
6. support envelopes for CPU short/long witnesses that overlap the mutation interval.
7. candidate same-UID continuity result for each overlapping witness.
8. creation-bound result for young post-rollout Pods.
9. evaluation-time minus source-sample-time age around the transition.
10. selector omissions, derived-evidence missing, foreign `TARGET_DIFFERS`, or ownership `UNKNOWN`, if any naturally appear.

## 12. R2 is not allowed to conclude

R2 cannot by itself:

- prove continuous Kubernetes event-time ownership/identity between 15-second grid points;
- prove that a ReplicaSet hash is an application-version identity;
- change `application_version_relation = UNVERIFIED`;
- choose a freshness threshold from observed source-sample ages;
- change product policy for foreign `TARGET_DIFFERS`;
- wire attribution into Analyze/Join/Risk;
- introduce new risk reason codes merely because a churn diagnostic appears.

## 13. Success condition

R2 is an evidential success when:

- exactly one intentional Pod-template mutation occurred during the frozen window;
- raw Prometheus responses and mutation provenance are captured with exact metadata;
- at least one real Pod/ReplicaSet population transition is observable in the captured window;
- the evidence can be replayed offline through the real normalization/ownership paths where practical.

A surprising transition, temporary `UNKNOWN`, missing derived fact, source-timestamp lag, HPA overlap, or rollout delay is a finding, not a failed experiment.

Transport/schema failure or inability to establish the pre-mutation availability gate is a collection/readiness failure.

## 14. Restore after evidential collection

Only after the required Prometheus collection is complete, restore ArgoCD automated sync to the recorded initial policy.

For the currently preregistered expected policy:

```bash
kubectl patch application jobs-api -n argocd \
  --type=merge \
  -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
```

Then verify Application state and allow ArgoCD to reconcile any remaining drift.

Reconciliation after the evidential window may create another rollout when the temporary annotation is removed. That post-window rollout is **not part of R2 evidence** and must not be folded into the frozen R2 interval retroactively.

## 15. Freeze rule

After the first R2 mutation, do not change:

- the mutation type;
- the 15-second step;
- the 2m/5m windows;
- the pre/post analysis durations;
- the ingestion lag;
- the required query families;
- the success criteria;

merely to make the observed rollout easier to interpret.

Unexpected behavior belongs in `FINDINGS.md` or a follow-up experiment.
