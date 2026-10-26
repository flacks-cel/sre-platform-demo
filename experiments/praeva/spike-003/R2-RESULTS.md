# Spike 003 — R2 Churn Results

> Observed after the preregistered `R2-churn-rollout` run. This document records experimental findings only. It does not change product semantics, `WORKLOAD-OWNERSHIP-001`, `CHANGE-JOIN-001`, `CHANGE-RISK-001`, or Analyze wiring.

## Run provenance

Controlled mutation:

```text
annotation key      = praeva-spike-003-churn
mutation_before     = 1793035540
mutation_after      = 1793035541
mutation_grid_before= 1793035530
mutation_grid_after = 1793035545
analysis_start      = 1793035230
analysis_end        = 1793036145
ownership_start     = 1793034930
step                = 15s
short_window        = 2m
long_window         = 5m
```

The raw evidence was captured successfully by `r2_collect.py` and replayed offline by `r2_analyze.py`. Raw lab evidence remains local/ignored; the analyzer and this result record are versioned.

`application_version_relation` remains `UNVERIFIED`.

## R2-F1 — Real churn reconstructs population overlap on the ownership grid

The real `WORKLOAD-OWNERSHIP-001` path reconstructed these target-match identities:

```text
jobs-api-849859f688-z6zck
  uid = 169ef855-2e34-485a-8090-ca7c1868ad3f
  rs  = jobs-api-849859f688
  target-match grid = 1793034930 .. 1793035575

jobs-api-68bc8467b5-wbd22
  uid = 676ccd6c-76eb-411b-98a7-b3f74f147fc5
  rs  = jobs-api-68bc8467b5
  target-match grid = 1793035560 .. 1793036145
```

The captured window also contained a pre-mutation target Pod on the old ReplicaSet:

```text
jobs-api-849859f688-8qw9f
  uid = 34a035c5-3526-4e33-8bb8-0da84b19416e
  target-match grid = 1793035110 .. 1793035395
```

The spike does not infer the cause of that pre-mutation Pod transition.

Target-owned population transitions included:

```text
1793035410: {old-8qw9f, old-z6zck} -> {old-z6zck}
1793035560: {old-z6zck} -> {new-wbd22, old-z6zck}
1793035590: {new-wbd22, old-z6zck} -> {new-wbd22}
```

### Finding

> A real Deployment rollout can be reconstructed as explicit target-owned population transitions on the frozen evaluation grid, including an overlap interval where old and new Pods are simultaneously valid `TARGET_MATCH` members of the same Deployment population.

This is still evaluation-grid evidence, not continuous Kubernetes event-time proof.

## R2-F2 — New target ownership can precede rate-derived evidence

At timestamp `1793035560`, the new Pod was already part of the target-owned population, while all four captured rate-derived families were still absent for that Pod:

```text
derived_evidence_missing:cpu_short           = true at 1793035560
derived_evidence_missing:cpu_long            = true at 1793035560
derived_evidence_missing:cfs_throttled_short = true at 1793035560
derived_evidence_missing:cfs_throttled_long  = true at 1793035560
```

No selector omission was required to produce this state.

The support analysis also observed creation-bound failures:

```text
cpu_short: creation_bound NOT_PROVEN = 6 witnesses
cpu_long:  creation_bound NOT_PROVEN = 29 witnesses
```

with diagnostic:

```text
uid_not_present_at_support_start
```

### Finding

> A newly target-owned Pod can be historically attributable at evaluation time while its rate-derived fact is not yet usable because the Pod did not exist for the full required support envelope and/or the derived series is not yet available.

This is the real-lab counterpart to the synthetic young-Pod and derived-evidence-missing scenarios. Ownership-at-T and fact usability are therefore distinct.

## R2-F3 — Rate evidence can outlive current ownership at evaluation time

After Pods left the target-owned population, rate queries continued to return those Pod names for additional evaluation points.

The population reducer observed at least one `extra_observed + ownership_unresolved` rate result over these timestamp spans:

```text
cpu_short / cfs_throttled_short
  timestamps = 10
  first      = 1793035410
  last       = 1793035650

cpu_long / cfs_throttled_long
  timestamps = 29
  first      = 1793035410
  last       = 1793035830
```

The longer 5-minute window remained affected over a longer span than the 2-minute window.

### Finding

> A rate result at evaluation time T can remain observable after the Pod no longer resolves as a current target-owned member at T.

Therefore, current ownership at T is not sufficient to explain the provenance of a derived rate fact. Attribution must reason over the fact's support interval and must not reinterpret a residual rate result as current workload membership.

`ownership_unresolved` here is a population diagnostic for the current timestamp, not proof that the historical support was foreign or invalid.

## R2-F4 — Real churn exercises support-coverage failure modes

Across the captured rate witnesses, the experimental support reducer reported:

```text
cpu_short
  identity_continuity PROVEN      = 68
  identity_continuity NOT_PROVEN  = 17
  ownership_unknown_within_support_grid = 17
  creation_bound PROVEN           = 69
  creation_bound NOT_PROVEN       = 6
  creation_bound NOT_EVALUATED    = 10

cpu_long
  identity_continuity PROVEN      = 44
  identity_continuity NOT_PROVEN  = 65
  ownership_unknown_within_support_grid = 65
  creation_bound PROVEN           = 46
  creation_bound NOT_PROVEN       = 29
  creation_bound NOT_EVALUATED    = 34
```

The `NOT_EVALUATED` creation cases occur when the witness cannot provide a usable Pod UID/creation identity at the evaluation point; they are not silently converted to proof.

### Finding

> Real rollout churn produces both provable and non-provable support witnesses under the same frozen query geometry. A future attribution contract therefore needs a per-fact usability decision rather than a workload-global boolean.

The longer window naturally exposes more support-history failures than the short window in this run.

## R2-F5 — Source-sample ages remained observable but no freshness threshold is justified

Observed evaluation-time minus source-sample-time ages were:

```text
pod_owner_source_timestamp
  min = 6.349s
  max = 22.89s

replicaset_owner_source_timestamp
  min = 6.349s
  max = 22.89s

pod_created_source_timestamp
  min = 6.349s
  max = 22.89s
```

### Finding

The diagnostic source timestamps remained mechanically available across the churn run. This run does not choose or justify a freshness threshold.

## R2 conclusion

The real-lab churn boundary validates the spike's central separation:

```text
historical workload attribution
!= identity continuity
!= selector scope
!= derived evidence availability
!= population completeness
!= support-grid geometry
```

The consumer-facing contract should project these richer diagnostics into a smaller decision surface, such as:

```text
can this fact be used?
which risk levels are still provable?
is the analysis globally invalid/out of scope?
```

This projection is follow-up design work. No Analyze/Join/Risk wiring is introduced by SPIKE-003.
