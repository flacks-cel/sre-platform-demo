#!/usr/bin/env python3
"""Experimental SPIKE-003 support-grid reducers.

This module belongs to the spike only. It does not change WORKLOAD-OWNERSHIP-001,
CHANGE-JOIN-001, CHANGE-RISK-001, or Analyze semantics.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

MODEL_ID = "SPIKE-003-CANDIDATE"


def _parse_decimal_timestamp(value: str, *, field: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be an exact decimal timestamp") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def evaluate_identity_continuity(
    *,
    ownership_report: dict[str, Any],
    pod: str,
    required_timestamps: list[str],
) -> dict[str, Any]:
    """Evaluate same-UID continuity across required ownership-grid points.

    Per-timestamp ownership remains owned by WORKLOAD-OWNERSHIP-001. This
    reducer only asks whether those resolved target-match observations carry one
    Pod UID across the requested support grid.
    """
    pod_report = ownership_report.get("pods", {}).get(pod, {})
    ownership = pod_report.get("ownership", {})

    observed_uids: list[str] = []

    for timestamp in required_timestamps:
        fact = ownership.get(timestamp)
        if not isinstance(fact, dict) or fact.get("evidence_status") != "VALID":
            return {
                "model_id": MODEL_ID,
                "identity_continuity": "NOT_PROVEN",
                "diagnostic": "ownership_unknown_within_support_grid",
                "required_timestamps": list(required_timestamps),
                "observed_uids": sorted(set(observed_uids)),
            }

        if fact.get("relation") != "TARGET_MATCH":
            return {
                "model_id": MODEL_ID,
                "identity_continuity": "NOT_PROVEN",
                "diagnostic": "ownership_target_differs_within_support_grid",
                "required_timestamps": list(required_timestamps),
                "observed_uids": sorted(set(observed_uids)),
            }

        identity = fact.get("pod_identity", {})
        uid = identity.get("uid") if isinstance(identity, dict) else None
        if not isinstance(uid, str) or not uid:
            return {
                "model_id": MODEL_ID,
                "identity_continuity": "NOT_PROVEN",
                "diagnostic": "ownership_unknown_within_support_grid",
                "required_timestamps": list(required_timestamps),
                "observed_uids": sorted(set(observed_uids)),
            }
        observed_uids.append(uid)

    unique_uids = sorted(set(observed_uids))
    if len(unique_uids) != 1:
        return {
            "model_id": MODEL_ID,
            "identity_continuity": "NOT_PROVEN",
            "diagnostic": "uid_change_within_support_grid",
            "required_timestamps": list(required_timestamps),
            "observed_uids": unique_uids,
        }

    return {
        "model_id": MODEL_ID,
        "identity_continuity": "PROVEN",
        "required_timestamps": list(required_timestamps),
        "observed_uids": unique_uids,
    }


def evaluate_creation_bound(
    *,
    creation_timestamp: str,
    support_start: str,
) -> dict[str, Any]:
    """Evaluate the candidate Pod-creation existence bound for one support.

    Inputs are normalized exact-decimal Unix timestamps. This reducer does not
    decide ownership, freshness, or event-time continuity; it only tests the
    pre-registered condition ``kube_pod_created(uid) <= support_start``.
    """
    created = _parse_decimal_timestamp(creation_timestamp, field="creation_timestamp")
    start = _parse_decimal_timestamp(support_start, field="support_start")

    result: dict[str, Any] = {
        "model_id": MODEL_ID,
        "creation_bound": "PROVEN" if created <= start else "NOT_PROVEN",
        "creation_timestamp": _decimal_text(created),
        "support_start": _decimal_text(start),
    }
    if created > start:
        result["diagnostic"] = "uid_not_present_at_support_start"
    return result
