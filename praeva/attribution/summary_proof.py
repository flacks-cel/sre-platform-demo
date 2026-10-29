from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

SUMMARY_PROOF_ID = "ATTRIBUTION-SUMMARY-PROOF-001"
FACT_INPUT_ID = "ATTRIBUTION-FACT-INPUT-001"

_CPU_FAMILIES = {
    "short": "cpu_short",
    "long": "cpu_long",
}
_CFS_FAMILIES = {
    "short": "cfs_throttled_short",
    "long": "cfs_throttled_long",
}
_SUPPORTED_FACT_FAMILIES = {
    "cpu_short",
    "cpu_long",
    "cfs_throttled_short",
    "cfs_throttled_long",
    "cpu_limit",
}


class AttributionSummaryProofInputError(ValueError):
    """Raised when ATTRIBUTION-SUMMARY-PROOF-001 receives inconsistent input."""


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AttributionSummaryProofInputError(f"{field} must be an object")
    return value


def _non_empty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AttributionSummaryProofInputError(f"{field} must be a non-empty string")
    return value


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise AttributionSummaryProofInputError(
            f"{field} must be exact decimal text or an integer"
        )
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise AttributionSummaryProofInputError(f"{field} must be numeric") from exc
    else:
        raise AttributionSummaryProofInputError(f"{field} must be numeric")
    if not result.is_finite():
        raise AttributionSummaryProofInputError(f"{field} must be finite")
    return result


def _canonical_decimal(value: Any, *, field: str) -> str:
    number = _decimal(value, field=field)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AttributionSummaryProofInputError(
            f"{field} must be a non-negative integer"
        )
    return value


def _expected_points(verify_report: dict[str, Any]) -> int:
    acquisition = _mapping(verify_report.get("acquisition"), field="verify_report.acquisition")
    start = _decimal(acquisition.get("start"), field="verify_report.acquisition.start")
    end = _decimal(acquisition.get("end"), field="verify_report.acquisition.end")
    step = _decimal(acquisition.get("step"), field="verify_report.acquisition.step")
    if step <= 0:
        raise AttributionSummaryProofInputError(
            "verify_report.acquisition.step must be positive"
        )
    if end < start:
        raise AttributionSummaryProofInputError(
            "verify_report.acquisition.end must not be before start"
        )
    return int((end - start) // step) + 1


def _validate_fact_input(
    value: Any,
) -> tuple[list[dict[str, str]], dict[tuple[str, str], list[dict[str, str]]]]:
    fact_input = _mapping(value, field="fact_input")
    if fact_input.get("fact_input_id") != FACT_INPUT_ID:
        raise AttributionSummaryProofInputError(
            f"fact_input.fact_input_id must be {FACT_INPUT_ID}"
        )
    raw_facts = fact_input.get("facts")
    if not isinstance(raw_facts, list):
        raise AttributionSummaryProofInputError("fact_input.facts must be a list")

    facts: list[dict[str, str]] = []
    by_domain: dict[tuple[str, str], list[dict[str, str]]] = {}
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, Decimal]] = set()
    for index, raw_fact in enumerate(raw_facts):
        fact = _mapping(raw_fact, field=f"fact_input.facts[{index}]")
        fact_id = _non_empty_string(
            fact.get("fact_id"),
            field=f"fact_input.facts[{index}].fact_id",
        )
        pod = _non_empty_string(
            fact.get("pod"),
            field=f"fact_input.facts[{index}].pod",
        )
        family = _non_empty_string(
            fact.get("evidence_family"),
            field=f"fact_input.facts[{index}].evidence_family",
        )
        if family not in _SUPPORTED_FACT_FAMILIES:
            raise AttributionSummaryProofInputError(
                f"unsupported evidence family in fact_input: {family}"
            )
        timestamp_number = _decimal(
            fact.get("evaluated_at"),
            field=f"fact_input.facts[{index}].evaluated_at",
        )
        timestamp = _canonical_decimal(
            timestamp_number,
            field=f"fact_input.facts[{index}].evaluated_at",
        )

        if fact_id in seen_ids:
            raise AttributionSummaryProofInputError("fact_input.fact_id values must be unique")
        key = (pod, family, timestamp_number)
        if key in seen_keys:
            raise AttributionSummaryProofInputError(
                "fact_input contains duplicate pod/family/evaluated_at"
            )
        expected_id = f"{family}:{pod}:{timestamp}"
        if fact_id != expected_id:
            raise AttributionSummaryProofInputError(
                f"fact_id {fact_id} does not match point identity {expected_id}"
            )

        normalized = {
            "fact_id": fact_id,
            "pod": pod,
            "evidence_family": family,
            "evaluated_at": timestamp,
        }
        facts.append(normalized)
        by_domain.setdefault((pod, family), []).append(normalized)
        seen_ids.add(fact_id)
        seen_keys.add(key)

    for domain_facts in by_domain.values():
        domain_facts.sort(
            key=lambda item: _decimal(item["evaluated_at"], field="fact evaluated_at")
        )
    return facts, by_domain


def _validate_projection(
    value: Any,
    *,
    fact_ids: set[str],
) -> dict[str, dict[str, Any]]:
    projection = _mapping(value, field="attribution_projection")
    raw_decisions = _mapping(
        projection.get("facts"),
        field="attribution_projection.facts",
    )
    decision_ids = set(raw_decisions)
    if decision_ids != fact_ids:
        raise AttributionSummaryProofInputError(
            "fact_input facts and attribution_projection.facts must match exactly"
        )

    decisions: dict[str, dict[str, Any]] = {}
    for fact_id in sorted(fact_ids):
        decision = _mapping(
            raw_decisions[fact_id],
            field=f"attribution_projection.facts.{fact_id}",
        )
        status = decision.get("status")
        if status not in {"ATTRIBUTED", "UNATTRIBUTED"}:
            raise AttributionSummaryProofInputError(
                f"attribution decision for {fact_id} must be ATTRIBUTED or UNATTRIBUTED"
            )
        decisions[fact_id] = decision
    return decisions


def _unavailable(summary: dict[str, Any]) -> dict[str, Any]:
    reason_code = summary.get("reason_code")
    witness: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "fact_refs": [],
        "blocked_by": ["summary_unknown"],
    }
    domain: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "blocked_by": ["summary_unknown"],
    }
    if isinstance(reason_code, str) and reason_code:
        witness["reason_code"] = reason_code
        domain["reason_code"] = reason_code
    return {"witness": witness, "domain": domain}


def _validate_valid_summary_common(
    summary: dict[str, Any],
    *,
    family: str,
    fact_count: int,
) -> tuple[int, str, str]:
    query_key = _non_empty_string(summary.get("query_key"), field=f"{family}.query_key")
    if query_key != family:
        raise AttributionSummaryProofInputError(
            f"{family}.query_key must match evidence family"
        )
    points = _non_negative_int(summary.get("points"), field=f"{family}.points")
    if points != fact_count:
        raise AttributionSummaryProofInputError(
            f"{family}.points does not match observed fact count"
        )
    max_timestamp = _canonical_decimal(
        summary.get("max_timestamp"),
        field=f"{family}.max_timestamp",
    )
    fact_id = f"{family}:{{pod}}:{max_timestamp}"
    return points, max_timestamp, fact_id


def _domain_capability(
    *,
    facts: list[dict[str, str]],
    decisions: dict[str, dict[str, Any]],
    expected_points: int,
    extra_blocked_by: list[str] | None = None,
) -> dict[str, Any]:
    blocked_by: list[str] = []
    if len(facts) != expected_points:
        blocked_by.append("series_point_count_incomplete")
    for reason in extra_blocked_by or []:
        if reason not in blocked_by:
            blocked_by.append(reason)

    unusable = sorted(
        fact["fact_id"]
        for fact in facts
        if decisions[fact["fact_id"]].get("status") != "ATTRIBUTED"
    )
    if unusable and "series_fact_unattributed" not in blocked_by:
        blocked_by.append("series_fact_unattributed")

    return {
        "status": "INCOMPLETE" if blocked_by else "COMPLETE",
        "observed_fact_count": len(facts),
        "expected_point_count": expected_points,
        "unusable_fact_refs": unusable,
        "blocked_by": blocked_by,
    }


def _single_witness(
    *,
    fact_id: str,
    decisions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    decision = decisions.get(fact_id)
    if decision is None:
        raise AttributionSummaryProofInputError(
            f"summary witness references missing fact {fact_id}"
        )
    if decision.get("status") == "ATTRIBUTED":
        return {"status": "USABLE", "fact_refs": [fact_id], "blocked_by": []}
    return {
        "status": "UNUSABLE",
        "fact_refs": [fact_id],
        "blocked_by": ["witness_fact_unattributed"],
    }


def _cpu_capability(
    *,
    pod: str,
    family: str,
    summary: Any,
    facts: list[dict[str, str]],
    decisions: dict[str, dict[str, Any]],
    expected_points: int,
) -> dict[str, Any]:
    summary_map = _mapping(summary, field=f"verify_report.pods.{pod}.{family}")
    status = summary_map.get("status")
    if status == "UNKNOWN":
        return _unavailable(summary_map)
    if status != "VALID":
        raise AttributionSummaryProofInputError(
            f"{family}.status must be VALID or UNKNOWN"
        )

    _points, max_timestamp, _template = _validate_valid_summary_common(
        summary_map,
        family=family,
        fact_count=len(facts),
    )
    fact_id = f"{family}:{pod}:{max_timestamp}"
    return {
        "witness": _single_witness(fact_id=fact_id, decisions=decisions),
        "domain": _domain_capability(
            facts=facts,
            decisions=decisions,
            expected_points=expected_points,
        ),
    }


def _validate_throttling_coverage(
    summary: dict[str, Any],
    *,
    family: str,
    points: int,
    expected_points: int,
) -> list[str]:
    coverage = _mapping(summary.get("coverage"), field=f"{family}.coverage")
    observed = _non_negative_int(
        coverage.get("observed_points"),
        field=f"{family}.coverage.observed_points",
    )
    expected = _non_negative_int(
        coverage.get("expected_points"),
        field=f"{family}.coverage.expected_points",
    )
    coverage_complete = summary.get("coverage_complete")
    if not isinstance(coverage_complete, bool):
        raise AttributionSummaryProofInputError(
            f"{family}.coverage_complete must be boolean"
        )
    if observed != points:
        raise AttributionSummaryProofInputError(
            f"{family}.coverage.observed_points must equal summary.points"
        )
    if expected != expected_points:
        raise AttributionSummaryProofInputError(
            f"{family}.coverage.expected_points is inconsistent with acquisition"
        )
    if coverage_complete != (observed == expected):
        raise AttributionSummaryProofInputError(
            f"{family}.coverage_complete is inconsistent with coverage counts"
        )
    return [] if coverage_complete else ["coverage_incomplete"]


def _cfs_capability(
    *,
    pod: str,
    family: str,
    summary: Any,
    facts: list[dict[str, str]],
    decisions: dict[str, dict[str, Any]],
    expected_points: int,
) -> dict[str, Any]:
    summary_map = _mapping(summary, field=f"verify_report.pods.{pod}.{family}")
    status = summary_map.get("status")
    if status == "UNKNOWN":
        return _unavailable(summary_map)
    if status != "VALID":
        raise AttributionSummaryProofInputError(
            f"{family}.status must be VALID or UNKNOWN"
        )

    points, max_timestamp, _template = _validate_valid_summary_common(
        summary_map,
        family=family,
        fact_count=len(facts),
    )
    any_positive = summary_map.get("any_positive")
    if not isinstance(any_positive, bool):
        raise AttributionSummaryProofInputError(f"{family}.any_positive must be boolean")
    coverage_blockers = _validate_throttling_coverage(
        summary_map,
        family=family,
        points=points,
        expected_points=expected_points,
    )

    if any_positive:
        fact_id = f"{family}:{pod}:{max_timestamp}"
        witness = _single_witness(fact_id=fact_id, decisions=decisions)
    else:
        witness = {"status": "NOT_APPLICABLE", "fact_refs": [], "blocked_by": []}

    return {
        "witness": witness,
        "domain": _domain_capability(
            facts=facts,
            decisions=decisions,
            expected_points=expected_points,
            extra_blocked_by=coverage_blockers,
        ),
    }


def _ratio_capability(
    *,
    pod: str,
    summary: Any,
    facts_by_domain: dict[tuple[str, str], list[dict[str, str]]],
    decisions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    summary_map = _mapping(summary, field=f"verify_report.pods.{pod}.cpu_limit_ratio")
    status = summary_map.get("status")
    if status == "UNKNOWN":
        unavailable = _unavailable(summary_map)
        unavailable["domain"] = {"status": "NOT_APPLICABLE"}
        return unavailable
    if status != "VALID":
        raise AttributionSummaryProofInputError(
            "cpu_limit_ratio.status must be VALID or UNKNOWN"
        )

    timestamp = _canonical_decimal(
        summary_map.get("max_timestamp"),
        field="cpu_limit_ratio.max_timestamp",
    )
    query_keys = _mapping(
        summary_map.get("query_keys"),
        field="cpu_limit_ratio.query_keys",
    )
    if query_keys.get("numerator") != "cpu_short":
        raise AttributionSummaryProofInputError(
            "cpu_limit_ratio numerator query_key must be cpu_short"
        )
    if query_keys.get("denominator") != "cpu_limit":
        raise AttributionSummaryProofInputError(
            "cpu_limit_ratio denominator query_key must be cpu_limit"
        )

    ratio_points = _non_negative_int(
        summary_map.get("points"),
        field="cpu_limit_ratio.points",
    )
    cpu_facts = facts_by_domain.get((pod, "cpu_short"), [])
    limit_facts = facts_by_domain.get((pod, "cpu_limit"), [])
    if ratio_points != len(cpu_facts) or ratio_points != len(limit_facts):
        raise AttributionSummaryProofInputError(
            "cpu_limit_ratio.points must match cpu_short and cpu_limit fact counts"
        )

    fact_refs = [
        f"cpu_short:{pod}:{timestamp}",
        f"cpu_limit:{pod}:{timestamp}",
    ]
    missing = [fact_id for fact_id in fact_refs if fact_id not in decisions]
    if missing:
        raise AttributionSummaryProofInputError(
            "cpu_limit_ratio max_timestamp must reference both component facts"
        )
    if any(decisions[fact_id].get("status") != "ATTRIBUTED" for fact_id in fact_refs):
        witness = {
            "status": "UNUSABLE",
            "fact_refs": fact_refs,
            "blocked_by": ["composite_witness_component_unattributed"],
        }
    else:
        witness = {"status": "USABLE", "fact_refs": fact_refs, "blocked_by": []}

    return {"witness": witness, "domain": {"status": "NOT_APPLICABLE"}}


def project_summary_proof(
    *,
    verify_report: dict,
    fact_input: dict,
    attribution_projection: dict,
) -> dict[str, Any]:
    """Project point attribution into witness and series-domain proof capabilities."""

    report = _mapping(verify_report, field="verify_report")
    expected_points = _expected_points(report)
    facts, facts_by_domain = _validate_fact_input(fact_input)
    decisions = _validate_projection(
        attribution_projection,
        fact_ids={fact["fact_id"] for fact in facts},
    )
    pods = _mapping(report.get("pods"), field="verify_report.pods")

    fact_pods = {fact["pod"] for fact in facts}
    unknown_fact_pods = sorted(fact_pods - set(pods))
    if unknown_fact_pods:
        raise AttributionSummaryProofInputError(
            "fact_input contains pods absent from verify_report: "
            + ", ".join(unknown_fact_pods)
        )

    output_pods: dict[str, Any] = {}
    for pod in sorted(pods):
        pod_report = _mapping(pods[pod], field=f"verify_report.pods.{pod}")
        usage = _mapping(
            pod_report.get("cpu_usage"),
            field=f"verify_report.pods.{pod}.cpu_usage",
        )
        pod_output: dict[str, Any] = {}
        for window_name, family in _CPU_FAMILIES.items():
            pod_output[family] = _cpu_capability(
                pod=pod,
                family=family,
                summary=usage.get(window_name),
                facts=facts_by_domain.get((pod, family), []),
                decisions=decisions,
                expected_points=expected_points,
            )

        throttling = pod_report.get("cfs_throttling")
        if throttling is not None:
            throttling_map = _mapping(
                throttling,
                field=f"verify_report.pods.{pod}.cfs_throttling",
            )
            for window_name, family in _CFS_FAMILIES.items():
                pod_output[family] = _cfs_capability(
                    pod=pod,
                    family=family,
                    summary=throttling_map.get(window_name),
                    facts=facts_by_domain.get((pod, family), []),
                    decisions=decisions,
                    expected_points=expected_points,
                )

        pod_output["cpu_limit_ratio"] = _ratio_capability(
            pod=pod,
            summary=pod_report.get("cpu_limit_ratio"),
            facts_by_domain=facts_by_domain,
            decisions=decisions,
        )
        output_pods[pod] = pod_output

    return {
        "summary_proof_id": SUMMARY_PROOF_ID,
        "pods": output_pods,
    }
