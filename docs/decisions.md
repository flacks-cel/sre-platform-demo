# Praeva — Decision Log (early experiments)

This file records only decisions that are stable enough to survive the first implementation experiments. The full Praeva product will eventually live outside the lab repository; these entries are kept here while `sre-platform-demo` is the experimental environment.

## ADR-001 — CPU and memory use different risk models

**Status:** Accepted

CPU pressure and memory pressure have materially different failure modes. CPU limits commonly manifest as throttling/performance degradation. Memory limits can lead to OOM termination/restarts. Praeva must not reuse one threshold model for both resources.

For memory-limit analysis, a previously observed memory level above a proposed limit is treated as a critical warning signal; reporting must use cautious wording such as "historical memory usage exceeded the proposed limit" rather than claiming that an OOM kill was certain.

## ADR-002 — Risk and evidence quality are separate concepts

**Status:** Accepted

Praeva must not encode telemetry completeness into the risk level itself. A change can be dangerous while the available evidence is incomplete. Conversely, high-quality evidence can show a low-risk change.

The exact deterministic evidence-quality model is intentionally deferred until later spikes define the production-grade rules for sample coverage, scrape cadence, data gaps, and environment health.

CPU throttling is an observed fact about constrained demand. It is not, by itself, evidence corruption. It can make exact unconstrained capacity estimation impossible while still being strong evidence that current demand is constrained.

## ADR-005 — Missing telemetry never implies LOW risk

**Status:** Accepted

If required runtime telemetry is absent or unusable, Praeva returns `UNKNOWN` for analyses that depend on that telemetry. Missing data must never be interpreted as evidence that a change is safe.

## ADR-003 — Use per-pod/per-container telemetry for resource sizing

**Status:** Accepted

Resource sizing evaluates individual pod/container behavior rather than summing CPU across replicas. Summing replicas would incorrectly turn total workload consumption into a per-container limit recommendation.

Spike 001 validated this assumption against the real lab. HPA-created and short-lived pods remained individually visible in Prometheus history, including their ReplicaSet ownership and sample coverage. During the sustained run, one pod approached its configured 500m CPU limit while other HPA replicas showed materially different usage, demonstrating why per-container evidence must remain separate rather than being collapsed into total workload CPU.

Historical/duplicate labelsets must still be surfaced so selection mistakes can be detected. The spike's regex selector and worst-series grouping remain experimental implementation shortcuts, not the production selection rule.

## ADR-004 — CPU evidence discloses the rate window

**Status:** Accepted

Every CPU statistic derived from a counter rate must disclose the rate window used (`rate[2m]`, `rate[5m]`, etc.). A longer window smooths short bursts and therefore changes the observed maximum.

Spike 001 demonstrated the effect directly in the real lab: for the observed ~30s burst, the 5m maximum was 63.86% lower than the 2m maximum; for the observed sustained round, the 5m maximum was only 1.51% lower. These values are workload-specific observations, not Praeva constants.

The product must therefore expose the chosen rate window with the evidence and must not compare CPU statistics from different windows as if they were equivalent.

## ADR-006 — Historical Prometheus time and live Kubernetes state are distinct

**Status:** Accepted

A Prometheus query evaluated at an explicit time `T` is historical evidence. Deployment, HPA, and `kubectl top` reads performed during collection are live observations at collection time.

Praeva must label these time semantics explicitly. A live HPA replica count must not be presented as if it were the HPA state at historical evaluation time `T` unless historical HPA telemetry is queried separately.

## ADR-007 — A failed controlled-load round is invalid evidence

**Status:** Accepted

An experiment round intended to produce controlled-load evidence is valid only if its load preconditions pass and all controlled load calls succeed.

The Spike 001 harness must preflight the Jobs API before starting the round, stop on the first failed load call, return a non-zero exit status, and avoid suggesting follow-up evidence collection for that invalid round.

This rule is about experiment validity, not production risk classification.
