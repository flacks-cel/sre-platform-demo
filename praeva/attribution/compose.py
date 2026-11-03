from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from praeva.attribution.fact_input import build_attribution_fact_inputs
from praeva.attribution.projection import project_attribution_decision
from praeva.attribution.summary_proof import project_summary_proof
from praeva.ownership.historical import build_ownership_report

COMPOSE_ID = "ATTRIBUTION-COMPOSE-001"


class AttributionComposeInputError(ValueError):
    """Raised when documents for attribution composition are incompatible."""


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AttributionComposeInputError(f"{field} must be an object")
    return value


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool | float) or not isinstance(
        value, str | int | Decimal
    ):
        raise AttributionComposeInputError(f"{field} must be an exact decimal")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise AttributionComposeInputError(f"{field} is invalid") from exc
    if not result.is_finite():
        raise AttributionComposeInputError(f"{field} must be finite")
    return result


def _same_temporal_value(left: Any, right: Any, *, field: str) -> None:
    if _decimal(left, field=f"{field}.left") != _decimal(
        right, field=f"{field}.right"
    ):
        raise AttributionComposeInputError(f"{field} does not match")


def _check_verify_source(
    *,
    normalized_evidence: dict[str, Any],
    verify_report: dict[str, Any],
) -> None:
    normalized = _mapping(normalized_evidence, field="normalized_evidence")
    verify = _mapping(verify_report, field="verify_report")
    windows = _mapping(verify.get("windows"), field="verify_report.windows")

    for name in ("short", "long"):
        if windows.get(name) != normalized.get(f"{name}_window"):
            raise AttributionComposeInputError(
                f"verify_report.windows.{name} differs from normalized evidence"
            )

    normalized_acq = _mapping(
        normalized.get("acquisition"),
        field="normalized_evidence.acquisition",
    )
    verify_acq = _mapping(
        verify.get("acquisition"),
        field="verify_report.acquisition",
    )
    for key in ("namespace", "container", "pod_selector"):
        if normalized_acq.get(key) != verify_acq.get(key):
            raise AttributionComposeInputError(
                f"verify_report.acquisition.{key} differs from normalized evidence"
            )
    for key in ("start", "end", "step"):
        _same_temporal_value(
            normalized_acq.get(key),
            verify_acq.get(key),
            field=f"verify_report.acquisition.{key}",
        )

    normalized_queries = _mapping(
        normalized.get("queries"),
        field="normalized_evidence.queries",
    )
    verify_queries = _mapping(
        verify.get("queries"),
        field="verify_report.queries",
    )
    if verify_queries != normalized_queries:
        raise AttributionComposeInputError(
            "verify_report.queries differs from normalized evidence"
        )


def _check_ownership_acquisition(
    *,
    ownership_evidence: dict[str, Any],
    plan: dict[str, Any],
) -> None:
    ownership = _mapping(ownership_evidence, field="ownership_evidence")
    acquisition = _mapping(
        ownership.get("acquisition"),
        field="ownership_evidence.acquisition",
    )
    required = _mapping(plan, field="fact_input.ownership_acquisition")

    if acquisition.get("namespace") != required.get("namespace"):
        raise AttributionComposeInputError(
            "ownership_evidence.acquisition.namespace differs from required plan"
        )
    for key in ("start", "end", "step"):
        _same_temporal_value(
            acquisition.get(key),
            required.get(key),
            field=f"ownership_evidence.acquisition.{key}",
        )


def compose_attribution(
    *,
    normalized_evidence: dict,
    verify_report: dict,
    ownership_evidence: dict,
    creation_by_pod_uid: dict,
    target_workload: dict,
    target_domain_status: str,
    population_evidence: dict,
    level_requirements: dict,
) -> dict[str, Any]:
    """Compose existing pure attribution stages without I/O or risk classification."""

    fact_input = build_attribution_fact_inputs(
        normalized_evidence=normalized_evidence,
        creation_by_pod_uid=creation_by_pod_uid,
    )
    _check_verify_source(
        normalized_evidence=normalized_evidence,
        verify_report=verify_report,
    )
    _check_ownership_acquisition(
        ownership_evidence=ownership_evidence,
        plan=fact_input["ownership_acquisition"],
    )

    ownership_report = build_ownership_report(
        evidence=ownership_evidence,
        target_workload=target_workload,
        required_timestamps_by_pod=fact_input["required_timestamps_by_pod"],
    )
    attribution = project_attribution_decision(
        target_domain_status=target_domain_status,
        ownership_report=ownership_report,
        facts=fact_input["facts"],
        population_evidence=population_evidence,
        level_requirements=level_requirements,
    )
    summary_proof = project_summary_proof(
        verify_report=verify_report,
        fact_input=fact_input,
        attribution_projection=attribution,
    )

    return {
        "compose_id": COMPOSE_ID,
        "fact_input": fact_input,
        "ownership": ownership_report,
        "attribution": attribution,
        "summary_proof": summary_proof,
    }
