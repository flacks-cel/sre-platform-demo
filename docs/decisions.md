# Praeva — Decision Log (early experiments)

This file records only decisions that are stable enough to survive the first implementation experiments. The full Praeva product will eventually live outside the lab repository; these entries are kept here while `sre-platform-demo` is the experimental environment.

## ADR-001 — CPU and memory use different risk models

**Status:** Accepted

CPU pressure and memory pressure have materially different failure modes. CPU limits commonly manifest as throttling/performance degradation. Memory limits can lead to OOM termination/restarts. Praeva must not reuse one threshold model for both resources.

For memory-limit analysis, a previously observed memory level above a proposed limit is treated as a critical warning signal; reporting must use cautious wording such as "historical memory usage exceeded the proposed limit" rather than claiming that an OOM kill was certain.

## ADR-002 — Risk and evidence quality are separate concepts

**Status:** Accepted

Praeva must not encode telemetry completeness into the risk level itself. A change can be dangerous while the available evidence is incomplete. Conversely, high-quality evidence can show a low-risk change.

The exact deterministic evidence-quality model is intentionally deferred until Spike 001 exposes real sample coverage, scrape cadence, and data gaps.

CPU throttling is an observed fact about constrained demand. It is not, by itself, evidence corruption. It can make exact unconstrained capacity estimation impossible while still being strong evidence that current demand is constrained.

## ADR-005 — Missing telemetry never implies LOW risk

**Status:** Accepted

If required runtime telemetry is absent or unusable, Praeva returns `UNKNOWN` for analyses that depend on that telemetry. Missing data must never be interpreted as evidence that a change is safe.

## ADR-003 — Use per-pod/per-container telemetry for resource sizing

**Status:** Proposed — pending Spike 001

Candidate decision: resource sizing should evaluate individual pod/container behavior rather than summing CPU across replicas. Summing replicas would incorrectly turn total workload consumption into a per-container limit recommendation.

Spike 001 must validate how duplicate series, short-lived pods, HPA scaling, and historical ReplicaSets affect this rule before it is accepted.

## ADR-004 — CPU evidence discloses the rate window

**Status:** Proposed — pending Spike 001

Candidate decision: every CPU statistic derived from a counter rate must disclose the rate window used (`rate[2m]`, `rate[5m]`, etc.). A longer window smooths short bursts and therefore changes the observed maximum.

Spike 001 explicitly compares 2m and 5m windows under a ~30s burst and a ~10m sustained load before this decision is accepted.
