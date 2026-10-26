#!/usr/bin/env python3
"""Experimental SPIKE-003 support-grid reducers.

This module belongs to the spike only. It does not change WORKLOAD-OWNERSHIP-001,
CHANGE-JOIN-001, CHANGE-RISK-001, or Analyze semantics.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal, InvalidOperation
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


def _grid(*, start: Decimal, end: Decimal, step: Decimal) -> list[Decimal]:
    if step <= 0:
        raise ValueError("step must be positive")
    if end < start:
        raise ValueError("end must be >= start")

    points: list[Decimal] = []
    current = start
    while current <= end:
        points.append(current)
        current += step
    return points


def evaluate_support_geometry(
    *,
    analysis_start: str,
    analysis_end: str,
    step: str,
    w_max_seconds: str,
    witness_timestamp: str,
    window_seconds: str,
) -> dict[str, Any]:
    """Evaluate phase alignment and support-boundary observability.

    This is experimental geometry only. A support boundary that is not an
    ownership-grid point is reported explicitly; the reducer does not round the
    boundary or decide whether another evidence source is sufficient to prove it.
    """
    start = _parse_decimal_timestamp(analysis_start, field="analysis_start")
    end = _parse_decimal_timestamp(analysis_end, field="analysis_end")
    step_value = _parse_decimal_timestamp(step, field="step")
    w_max = _parse_decimal_timestamp(w_max_seconds, field="w_max_seconds")
    witness = _parse_decimal_timestamp(witness_timestamp, field="witness_timestamp")
    window = _parse_decimal_timestamp(window_seconds, field="window_seconds")

    if w_max <= 0 or window <= 0:
        raise ValueError("windows must be positive")
    if window > w_max:
        raise ValueError("window_seconds must be <= w_max_seconds")

    verify_grid = _grid(start=start, end=end, step=step_value)
    if witness not in verify_grid:
        raise ValueError("witness_timestamp must be on the Verify grid")

    extension_steps = (w_max / step_value).to_integral_value(rounding=ROUND_CEILING)
    extended_start = start - extension_steps * step_value
    ownership_grid = _grid(start=extended_start, end=end, step=step_value)

    support_start = witness - window
    support_grid = [point for point in ownership_grid if support_start <= point <= witness]
    boundary_on_grid = support_start in ownership_grid
    phase_aligned = set(verify_grid).issubset(ownership_grid)

    result: dict[str, Any] = {
        "model_id": MODEL_ID,
        "analysis_start": _decimal_text(start),
        "analysis_end": _decimal_text(end),
        "step": _decimal_text(step_value),
        "w_max_seconds": _decimal_text(w_max),
        "extension_steps": _decimal_text(extension_steps),
        "extended_ownership_start": _decimal_text(extended_start),
        "witness_timestamp": _decimal_text(witness),
        "window_seconds": _decimal_text(window),
        "support_start": _decimal_text(support_start),
        "verify_grid": [_decimal_text(point) for point in verify_grid],
        "ownership_grid": [_decimal_text(point) for point in ownership_grid],
        "support_grid": [_decimal_text(point) for point in support_grid],
        "verify_subset_of_ownership": phase_aligned,
        "support_boundary_on_grid": boundary_on_grid,
    }
    if not boundary_on_grid:
        result["diagnostic"] = "support_boundary_not_on_grid"
    return result


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
