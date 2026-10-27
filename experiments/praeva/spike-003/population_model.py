#!/usr/bin/env python3
"""Experimental SPIKE-003 population reducers.

This module belongs to the spike only. It does not change WORKLOAD-OWNERSHIP-001,
CHANGE-JOIN-001, CHANGE-RISK-001, or Analyze semantics.
"""

from __future__ import annotations

import re
from typing import Any

MODEL_ID = "SPIKE-003-POPULATION-CANDIDATE"


def evaluate_population_at_timestamp(
    *,
    ownership_report: dict[str, Any],
    timestamp: str,
    pod_regex: str,
    verify_pods_by_query: dict[str, set[str]],
) -> dict[str, Any]:
    """Compare target-owned, selector-admitted, and Verify-observed populations."""
    pattern = re.compile(pod_regex)

    target_owned: set[str] = set()
    valid_target_differs: set[str] = set()
    ownership_unknown: set[str] = set()

    for pod, pod_report in ownership_report.get("pods", {}).items():
        fact = pod_report.get("ownership", {}).get(timestamp)
        if not isinstance(fact, dict):
            continue

        status = fact.get("evidence_status")
        relation = fact.get("relation")

        if status == "VALID" and relation == "TARGET_MATCH":
            target_owned.add(pod)
        elif status == "VALID" and relation == "TARGET_DIFFERS":
            valid_target_differs.add(pod)
        elif status == "UNKNOWN":
            ownership_unknown.add(pod)

    selector_admitted = {pod for pod in target_owned if pattern.fullmatch(pod)}
    selector_omissions = target_owned - selector_admitted

    per_query: dict[str, Any] = {}
    for query_name, observed in sorted(verify_pods_by_query.items()):
        observed_set = set(observed)
        extra_observed = observed_set - target_owned
        per_query[query_name] = {
            "verify_observed": sorted(observed_set),
            "derived_evidence_missing": sorted(selector_admitted - observed_set),
            "extra_observed": sorted(extra_observed),
            "foreign_target_differs": sorted(extra_observed & valid_target_differs),
            "ownership_unresolved": sorted(extra_observed & ownership_unknown),
        }

    return {
        "model_id": MODEL_ID,
        "timestamp": timestamp,
        "target_owned": sorted(target_owned),
        "selector_admitted": sorted(selector_admitted),
        "selector_omissions": sorted(selector_omissions),
        "per_query": per_query,
    }
