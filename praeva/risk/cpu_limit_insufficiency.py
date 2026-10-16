from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from praeva.risk.vocabulary import validate_risk_result

ABSENT = "ABSENT"
HAZARD_ID = "cpu_limit_insufficiency"
RULE_ID = "CHANGE-RISK-001"

_APPLICABLE_DIRECTIONS = {"DECREASE", "INCREASE", "LIMIT_ADDED"}
_NOT_APPLICABLE_REASONS = {
    "LIMIT_REMOVED": "limit_removed",
    "UNCHANGED": "limit_unchanged",
}
_DIVERGENT_RELATIONS = {"DIFFERS", "DECLARED_ABSENT_EFFECTIVE_PRESENT"}


class ChangeRiskInputError(ValueError):
    """Raised when CHANGE-RISK-001 receives structurally invalid input."""


def _require_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ChangeRiskInputError(f"{field} must be an object")
    return value


def _require_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ChangeRiskInputError(f"{field} must be a non-empty string")
    return value


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ChangeRiskInputError(f"{field} must be exact decimal text or an integer")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ChangeRiskInputError(f"{field} must be numeric") from exc
    else:
        raise ChangeRiskInputError(f"{field} must be numeric")

    if not result.is_finite():
        raise ChangeRiskInputError(f"{field} must be finite")
    return result


def _validate_margin(margin: Any) -> tuple[int, int, dict[str, int]]:
    margin_map = _require_mapping(margin, field="margin")
    if set(margin_map) != {"numerator", "denominator"}:
        raise ChangeRiskInputError("margin must contain exactly numerator and denominator")

    numerator = margin_map["numerator"]
    denominator = margin_map["denominator"]
    if (
        isinstance(numerator, bool)
        or not isinstance(numerator, int)
        or isinstance(denominator, bool)
        or not isinstance(denominator, int)
    ):
        raise ChangeRiskInputError("margin numerator and denominator must be integers")
    if numerator <= 0 or denominator <= 0:
        raise ChangeRiskInputError("margin numerator and denominator must be positive")
    if numerator <= denominator:
        raise ChangeRiskInputError("margin must be greater than one")

    return numerator, denominator, {
        "numerator": numerator,
        "denominator": denominator,
    }


def _provenance(joined: dict[str, Any]) -> dict[str, str]:
    identity = _require_mapping(joined.get("identity_assertion"), field="identity_assertion")
    historical = _require_mapping(joined.get("historical_context"), field="historical_context")
    return {
        "identity_assertion": _require_text(
            identity.get("status"),
            field="identity_assertion.status",
        ),
        "workload_to_pod_selector_relation": _require_text(
            identity.get("workload_to_pod_selector_relation"),
            field="identity_assertion.workload_to_pod_selector_relation",
        ),
        "application_version_relation": _require_text(
            historical.get("application_version_relation"),
            field="historical_context.application_version_relation",
        ),
    }


def _unknown(
    *,
    code: str,
    precondition: str,
    provenance: dict[str, str],
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "rule_id": RULE_ID,
        "hazard_id": HAZARD_ID,
        "applicability": "APPLICABLE",
        "classification_status": "UNKNOWN",
        "unknown_reasons": [{"code": code, "precondition": precondition}],
        "provenance": provenance,
    }
    if evidence_refs:
        result["evidence_refs"] = evidence_refs
    validate_risk_result(result)
    return result


def _classified(
    *,
    risk_level: str,
    classification_basis: str,
    margin: dict[str, int],
    provenance: dict[str, str],
    evidence_refs: list[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "rule_id": RULE_ID,
        "hazard_id": HAZARD_ID,
        "applicability": "APPLICABLE",
        "classification_status": "CLASSIFIED",
        "risk_level": risk_level,
        "classification_basis": classification_basis,
        "policy": {"margin": margin},
        "evidence_refs": evidence_refs,
        "provenance": provenance,
    }
    validate_risk_result(result)
    return result


def _not_applicable(*, code: str, provenance: dict[str, str]) -> dict[str, Any]:
    return {
        "rule_id": RULE_ID,
        "hazard_id": HAZARD_ID,
        "applicability": "NOT_APPLICABLE",
        "not_applicable_reason": {
            "code": code,
            "precondition": "hazard_applicable_direction",
        },
        "provenance": provenance,
    }


def _cpu_fact(
    pod: dict[str, Any],
    *,
    pod_name: str,
    window_name: str,
) -> tuple[str, Decimal | None, str]:
    windows = _require_mapping(pod.get("windows"), field=f"pods.{pod_name}.windows")
    window = _require_mapping(
        windows.get(window_name),
        field=f"pods.{pod_name}.windows.{window_name}",
    )
    observed = _require_mapping(
        window.get("observed_cpu"),
        field=f"pods.{pod_name}.windows.{window_name}.observed_cpu",
    )
    status = observed.get("status")
    ref = f"pods.{pod_name}.windows.{window_name}.observed_cpu"

    if status == "UNKNOWN":
        return "UNKNOWN", None, ref
    if status != "VALID":
        raise ChangeRiskInputError(f"{ref}.status must be VALID or UNKNOWN")

    value = observed.get("value_millicores")
    if not isinstance(value, str):
        raise ChangeRiskInputError(f"{ref}.value_millicores must be exact decimal text")
    return "VALID", _decimal(value, field=f"{ref}.value_millicores"), ref


def _relation_fact(
    pod: dict[str, Any],
    *,
    pod_name: str,
) -> tuple[str, str | None, str]:
    ref = f"pods.{pod_name}.current_declared_effective_relation"
    relation_fact = _require_mapping(
        pod.get("current_declared_effective_relation"),
        field=ref,
    )
    status = relation_fact.get("status")
    if status == "UNKNOWN":
        return "UNKNOWN", None, ref
    if status != "VALID":
        raise ChangeRiskInputError(f"{ref}.status must be VALID or UNKNOWN")

    relation = _require_text(relation_fact.get("relation"), field=f"{ref}.relation")
    if relation not in {"MATCH", *_DIVERGENT_RELATIONS}:
        raise ChangeRiskInputError(f"{ref}.relation is outside CHANGE-JOIN-001")
    return "VALID", relation, ref


def _throttling_fact(
    pod: dict[str, Any],
    *,
    pod_name: str,
    window_name: str,
) -> tuple[str, bool | None, bool | None, str]:
    windows = _require_mapping(pod.get("windows"), field=f"pods.{pod_name}.windows")
    window = _require_mapping(
        windows.get(window_name),
        field=f"pods.{pod_name}.windows.{window_name}",
    )
    ref = f"pods.{pod_name}.windows.{window_name}.cfs_throttling"
    throttling = _require_mapping(window.get("cfs_throttling"), field=ref)
    status = throttling.get("status")

    if status == "UNKNOWN":
        return "UNKNOWN", None, None, ref
    if status != "VALID":
        raise ChangeRiskInputError(f"{ref}.status must be VALID or UNKNOWN")

    any_positive = throttling.get("any_positive")
    coverage_complete = throttling.get("coverage_complete")
    if not isinstance(any_positive, bool):
        raise ChangeRiskInputError(f"{ref}.any_positive must be boolean")
    if not isinstance(coverage_complete, bool):
        raise ChangeRiskInputError(f"{ref}.coverage_complete must be boolean")
    return "VALID", any_positive, coverage_complete, ref


def evaluate_cpu_limit_insufficiency(*, joined: dict, margin: dict) -> dict:
    """Classify proposed CPU-limit insufficiency from CHANGE-JOIN-001 facts."""

    numerator, denominator, margin_policy = _validate_margin(margin)
    joined_map = _require_mapping(joined, field="joined")
    if joined_map.get("join_id") != "CHANGE-JOIN-001":
        raise ChangeRiskInputError("join_id must be CHANGE-JOIN-001")

    provenance = _provenance(joined_map)
    change_facts = _require_mapping(joined_map.get("change_facts"), field="change_facts")
    direction = change_facts.get("direction")
    if not isinstance(direction, str):
        raise ChangeRiskInputError("change_facts.direction must be a string")
    if direction not in _APPLICABLE_DIRECTIONS and direction not in _NOT_APPLICABLE_REASONS:
        raise ChangeRiskInputError("change_facts.direction is outside CHANGE-INPUT-001")

    if direction in _NOT_APPLICABLE_REASONS:
        return _not_applicable(
            code=_NOT_APPLICABLE_REASONS[direction],
            provenance=provenance,
        )

    proposed_raw = change_facts.get("proposed_declared_cpu_limit")
    if proposed_raw == ABSENT:
        raise ChangeRiskInputError("applicable direction requires a declared proposed CPU limit")
    proposed = _decimal(
        proposed_raw,
        field="change_facts.proposed_declared_cpu_limit",
    )
    proposed_ref = "change_facts.proposed_declared_cpu_limit"

    if proposed <= 0:
        return _unknown(
            code="non_positive_proposed_limit",
            precondition="positive_proposed_limit",
            provenance=provenance,
            evidence_refs=[proposed_ref],
        )

    pods = _require_mapping(joined_map.get("pods"), field="pods")
    if not pods:
        return _unknown(
            code="no_pod_evidence",
            precondition="pod_evidence_present",
            provenance=provenance,
        )

    pod_maps: dict[str, dict[str, Any]] = {}
    divergence_refs: list[str] = []
    for pod_name in sorted(pods):
        pod = _require_mapping(pods[pod_name], field=f"pods.{pod_name}")
        pod_maps[pod_name] = pod
        status, relation, relation_ref = _relation_fact(pod, pod_name=pod_name)
        if status == "VALID" and relation in _DIVERGENT_RELATIONS:
            divergence_refs.append(relation_ref)

    if divergence_refs:
        return _unknown(
            code="declared_effective_divergence",
            precondition="no_known_declared_effective_divergence",
            provenance=provenance,
            evidence_refs=divergence_refs,
        )

    long_facts: dict[str, tuple[str, Decimal | None, str]] = {}
    critical_refs: list[str] = []
    for pod_name, pod in pod_maps.items():
        fact = _cpu_fact(pod, pod_name=pod_name, window_name="long")
        long_facts[pod_name] = fact
        status, value, ref = fact
        if status == "VALID" and value is not None and proposed < value:
            critical_refs.append(ref)

    if critical_refs:
        return _classified(
            risk_level="CRITICAL",
            classification_basis="sustained_window_contradiction",
            margin=margin_policy,
            provenance=provenance,
            evidence_refs=[proposed_ref, *critical_refs],
        )

    short_facts: dict[str, tuple[str, Decimal | None, str]] = {}
    high_refs: list[str] = []
    for pod_name, pod in pod_maps.items():
        fact = _cpu_fact(pod, pod_name=pod_name, window_name="short")
        short_facts[pod_name] = fact
        status, value, ref = fact
        if status == "VALID" and value is not None and proposed < value:
            high_refs.append(ref)

    if high_refs:
        incomplete_long_refs = [
            ref
            for status, _value, ref in long_facts.values()
            if status != "VALID"
        ]
        if incomplete_long_refs:
            return _unknown(
                code="long_window_cpu_incomplete",
                precondition="long_window_complete_before_high",
                provenance=provenance,
                evidence_refs=incomplete_long_refs,
            )
        return _classified(
            risk_level="HIGH",
            classification_basis="short_window_only_contradiction",
            margin=margin_policy,
            provenance=provenance,
            evidence_refs=[proposed_ref, *high_refs, *(ref for _s, _v, ref in long_facts.values())],
        )

    incomplete_cpu_refs = [
        ref
        for facts in (short_facts, long_facts)
        for status, _value, ref in facts.values()
        if status != "VALID"
    ]
    if incomplete_cpu_refs:
        return _unknown(
            code="cpu_evidence_incomplete",
            precondition="all_cpu_windows_complete_for_noncontradiction",
            provenance=provenance,
            evidence_refs=incomplete_cpu_refs,
        )

    throttling_refs: list[str] = []
    positive_throttling_refs: list[str] = []
    unproven_throttling_refs: list[str] = []
    for pod_name, pod in pod_maps.items():
        for window_name in ("short", "long"):
            status, any_positive, coverage_complete, ref = _throttling_fact(
                pod,
                pod_name=pod_name,
                window_name=window_name,
            )
            throttling_refs.append(ref)
            if status == "VALID" and any_positive:
                positive_throttling_refs.append(ref)
            elif status != "VALID" or coverage_complete is not True:
                unproven_throttling_refs.append(ref)

    if positive_throttling_refs:
        return _unknown(
            code="censored_evidence",
            precondition="uncensored_evidence_for_noncontradiction",
            provenance=provenance,
            evidence_refs=positive_throttling_refs,
        )
    if unproven_throttling_refs:
        return _unknown(
            code="uncensored_evidence_unproven",
            precondition="uncensored_evidence_for_noncontradiction",
            provenance=provenance,
            evidence_refs=unproven_throttling_refs,
        )

    cpu_values: list[Decimal] = []
    cpu_refs: list[str] = []
    for facts in (short_facts, long_facts):
        for status, value, ref in facts.values():
            if status != "VALID" or value is None:
                raise ChangeRiskInputError("internal CPU completeness invariant violated")
            cpu_values.append(value)
            cpu_refs.append(ref)

    maximum_observed = max(cpu_values)
    evidence_refs = [proposed_ref, *cpu_refs, *throttling_refs]
    if proposed * denominator < maximum_observed * numerator:
        return _classified(
            risk_level="MEDIUM",
            classification_basis="headroom_below_margin",
            margin=margin_policy,
            provenance=provenance,
            evidence_refs=evidence_refs,
        )

    return _classified(
        risk_level="LOW",
        classification_basis="headroom_at_or_above_margin",
        margin=margin_policy,
        provenance=provenance,
        evidence_refs=evidence_refs,
    )
