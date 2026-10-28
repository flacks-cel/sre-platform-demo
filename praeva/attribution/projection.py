from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


class AttributionDecisionInputError(ValueError):
    """Raised when ATTRIBUTION-DECISION-001 inputs violate the frozen contract."""


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise AttributionDecisionInputError(f"{field} must not be represented as float")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise AttributionDecisionInputError(f"{field} must be numeric") from exc
    else:
        raise AttributionDecisionInputError(f"{field} must be numeric")
    if not number.is_finite():
        raise AttributionDecisionInputError(f"{field} must be finite")
    return number


def _canonical_decimal(value: Any, *, field: str) -> str:
    number = _decimal(value, field=field)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _non_empty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AttributionDecisionInputError(f"{field} must be a non-empty string")
    return value


def _validate_target_domain_status(value: Any) -> str:
    if value not in {"DETERMINED", "UNDETERMINABLE"}:
        raise AttributionDecisionInputError(
            "target_domain_status must be DETERMINED or UNDETERMINABLE"
        )
    return str(value)


def _validate_ownership_report(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AttributionDecisionInputError("ownership_report must be an object")
    pods = value.get("pods")
    if not isinstance(pods, dict):
        raise AttributionDecisionInputError("ownership_report.pods must be an object")
    return value


def _validate_support_descriptor(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AttributionDecisionInputError(f"{field} must be an object")

    start = _canonical_decimal(value.get("start"), field=f"{field}.start")
    end = _canonical_decimal(value.get("end"), field=f"{field}.end")
    start_number = _decimal(start, field=f"{field}.start")
    end_number = _decimal(end, field=f"{field}.end")
    if end_number < start_number:
        raise AttributionDecisionInputError(f"{field}.end must not be before start")

    required = value.get("required_timestamps")
    if not isinstance(required, list):
        raise AttributionDecisionInputError(f"{field}.required_timestamps must be a list")

    canonical_by_value: dict[Decimal, str] = {}
    for raw_timestamp in required:
        timestamp = _decimal(raw_timestamp, field=f"{field}.required timestamp")
        if timestamp < start_number or timestamp > end_number:
            raise AttributionDecisionInputError(
                f"{field}.required timestamp is outside the support interval"
            )
        canonical_by_value[timestamp] = _canonical_decimal(
            timestamp,
            field=f"{field}.required timestamp",
        )

    boundary_proven = value.get("boundary_proven")
    if not isinstance(boundary_proven, bool):
        raise AttributionDecisionInputError(f"{field}.boundary_proven must be boolean")

    return {
        "start": start,
        "end": end,
        "required_timestamps": [
            canonical_by_value[timestamp] for timestamp in sorted(canonical_by_value)
        ],
        "boundary_proven": boundary_proven,
    }


def _validate_fact(value: Any, *, index: int) -> dict[str, Any]:
    field = f"facts[{index}]"
    if not isinstance(value, dict):
        raise AttributionDecisionInputError(f"{field} must be an object")

    fact_id = _non_empty_string(value.get("fact_id"), field=f"{field}.fact_id")
    pod = _non_empty_string(value.get("pod"), field=f"{field}.pod")
    evidence_family = _non_empty_string(
        value.get("evidence_family"),
        field=f"{field}.evidence_family",
    )
    evaluated_at = _canonical_decimal(
        value.get("evaluated_at"),
        field=f"{field}.evaluated_at",
    )
    creation_timestamp = _canonical_decimal(
        value.get("creation_timestamp"),
        field=f"{field}.creation_timestamp",
    )

    support = value.get("support")
    if not isinstance(support, dict):
        raise AttributionDecisionInputError(f"{field}.support must be an object")
    nominal = _validate_support_descriptor(
        support.get("nominal"),
        field=f"{field}.support.nominal",
    )
    observed_raw = support.get("observed_sample")
    observed = None
    if observed_raw is not None:
        observed = _validate_support_descriptor(
            observed_raw,
            field=f"{field}.support.observed_sample",
        )

    return {
        "fact_id": fact_id,
        "pod": pod,
        "evidence_family": evidence_family,
        "evaluated_at": evaluated_at,
        "support": {
            "nominal": nominal,
            "observed_sample": observed,
        },
        "creation_timestamp": creation_timestamp,
    }


def _validate_facts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AttributionDecisionInputError("facts must be a list")

    facts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_fact in enumerate(value):
        fact = _validate_fact(raw_fact, index=index)
        if fact["fact_id"] in seen_ids:
            raise AttributionDecisionInputError("fact_id values must be unique")
        seen_ids.add(fact["fact_id"])
        facts.append(fact)
    return facts


def _validate_population_evidence(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise AttributionDecisionInputError("population_evidence must be an object")

    result: dict[str, dict[str, Any]] = {}
    for raw_domain, raw_evidence in value.items():
        domain = _non_empty_string(raw_domain, field="population_evidence domain")
        if not isinstance(raw_evidence, dict):
            raise AttributionDecisionInputError(
                f"population_evidence.{domain} must be an object"
            )
        status = raw_evidence.get("status")
        if status not in {"COMPLETE", "INCOMPLETE"}:
            raise AttributionDecisionInputError(
                f"population_evidence.{domain}.status must be COMPLETE or INCOMPLETE"
            )
        diagnostics = raw_evidence.get("diagnostics", [])
        if not isinstance(diagnostics, list) or any(
            not isinstance(item, str) or not item for item in diagnostics
        ):
            raise AttributionDecisionInputError(
                f"population_evidence.{domain}.diagnostics must be a list of strings"
            )
        result[domain] = {
            "status": status,
            "diagnostics": list(diagnostics),
        }
    return result


def _validate_level_requirements(
    value: Any,
    *,
    population_evidence: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    if not isinstance(value, dict):
        raise AttributionDecisionInputError("level_requirements must be an object")

    result: dict[str, list[dict[str, str]]] = {}
    for raw_level, raw_clauses in value.items():
        level = _non_empty_string(raw_level, field="level_requirements level")
        if not isinstance(raw_clauses, list):
            raise AttributionDecisionInputError(
                f"level_requirements.{level} must be a list"
            )
        clauses: list[dict[str, str]] = []
        for index, raw_clause in enumerate(raw_clauses):
            if not isinstance(raw_clause, dict):
                raise AttributionDecisionInputError(
                    f"level_requirements.{level}[{index}] must be an object"
                )
            quantifier = raw_clause.get("quantifier")
            if quantifier not in {"EXISTS", "FORALL"}:
                raise AttributionDecisionInputError(
                    f"level_requirements.{level}[{index}].quantifier "
                    "must be EXISTS or FORALL"
                )
            domain = _non_empty_string(
                raw_clause.get("domain"),
                field=f"level_requirements.{level}[{index}].domain",
            )
            if domain not in population_evidence:
                raise AttributionDecisionInputError(
                    f"level_requirements.{level}[{index}] references unknown domain {domain}"
                )
            clauses.append({"quantifier": quantifier, "domain": domain})
        result[level] = clauses
    return result


def _ownership_for_fact(
    ownership_report: dict[str, Any],
    *,
    pod: str,
) -> dict[str, Any] | None:
    pods = ownership_report["pods"]
    pod_report = pods.get(pod)
    if pod_report is None:
        return None
    if not isinstance(pod_report, dict):
        raise AttributionDecisionInputError(
            f"ownership_report.pods.{pod} must be an object"
        )
    ownership = pod_report.get("ownership")
    if not isinstance(ownership, dict):
        raise AttributionDecisionInputError(
            f"ownership_report.pods.{pod}.ownership must be an object"
        )
    return ownership


def _unattributed(
    classification: str,
    *,
    support_source: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "UNATTRIBUTED",
        "class": classification,
        "support_source": support_source,
        "evidence_refs": list(evidence_refs or []),
    }


def _project_fact(
    *,
    fact: dict[str, Any],
    ownership_report: dict[str, Any],
) -> dict[str, Any]:
    observed = fact["support"]["observed_sample"]
    if observed is not None:
        support = observed
        support_source = "OBSERVED_SAMPLE"
    else:
        support = fact["support"]["nominal"]
        support_source = "NOMINAL"

    if not support["boundary_proven"]:
        return _unattributed(
            "support_boundary_unproven",
            support_source=support_source,
        )

    ownership = _ownership_for_fact(ownership_report, pod=fact["pod"])
    if ownership is None:
        return _unattributed(
            "attribution_unproven",
            support_source=support_source,
        )

    ownership_facts: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    for timestamp in support["required_timestamps"]:
        raw_ownership_fact = ownership.get(timestamp)
        if not isinstance(raw_ownership_fact, dict):
            return _unattributed(
                "attribution_unproven",
                support_source=support_source,
                evidence_refs=evidence_refs,
            )
        ownership_facts.append(raw_ownership_fact)
        raw_refs = raw_ownership_fact.get("evidence_refs", [])
        if isinstance(raw_refs, list):
            evidence_refs.extend(
                ref for ref in raw_refs if isinstance(ref, str) and ref
            )

    if any(item.get("evidence_status") != "VALID" for item in ownership_facts):
        return _unattributed(
            "attribution_unproven",
            support_source=support_source,
            evidence_refs=sorted(set(evidence_refs)),
        )

    uids: set[str] = set()
    for item in ownership_facts:
        identity = item.get("pod_identity")
        if not isinstance(identity, dict):
            return _unattributed(
                "attribution_unproven",
                support_source=support_source,
                evidence_refs=sorted(set(evidence_refs)),
            )
        uid = identity.get("uid")
        if not isinstance(uid, str) or not uid:
            return _unattributed(
                "attribution_unproven",
                support_source=support_source,
                evidence_refs=sorted(set(evidence_refs)),
            )
        uids.add(uid)

    if len(uids) != 1:
        return _unattributed(
            "identity_discontinuity",
            support_source=support_source,
            evidence_refs=sorted(set(evidence_refs)),
        )

    relations = {item.get("relation") for item in ownership_facts}
    if "TARGET_DIFFERS" in relations:
        return _unattributed(
            "foreign_workload",
            support_source=support_source,
            evidence_refs=sorted(set(evidence_refs)),
        )
    if relations != {"TARGET_MATCH"}:
        return _unattributed(
            "attribution_unproven",
            support_source=support_source,
            evidence_refs=sorted(set(evidence_refs)),
        )

    creation = _decimal(
        fact["creation_timestamp"],
        field=f"facts.{fact['fact_id']}.creation_timestamp",
    )
    support_start = _decimal(
        support["start"],
        field=f"facts.{fact['fact_id']}.support.start",
    )
    if creation > support_start:
        return _unattributed(
            "support_predates_pod",
            support_source=support_source,
            evidence_refs=sorted(set(evidence_refs)),
        )

    return {
        "status": "ATTRIBUTED",
        "support_source": support_source,
        "evidence_refs": sorted(set(evidence_refs)),
    }


def _level_eligibility(
    *,
    population_evidence: dict[str, dict[str, Any]],
    level_requirements: dict[str, list[dict[str, str]]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for level, clauses in level_requirements.items():
        blocked_by: list[str] = []
        for clause in clauses:
            if clause["quantifier"] != "FORALL":
                continue
            domain = clause["domain"]
            if population_evidence[domain]["status"] != "COMPLETE":
                reason = f"population_incomplete:{domain}"
                if reason not in blocked_by:
                    blocked_by.append(reason)
        result[level] = {
            "status": "BLOCKED" if blocked_by else "ELIGIBLE",
            "blocked_by": blocked_by,
        }
    return result


def project_attribution_decision(
    *,
    target_domain_status: str,
    ownership_report: dict,
    facts: list[dict],
    population_evidence: dict,
    level_requirements: dict,
) -> dict[str, Any]:
    """Project attribution diagnostics into fact, analysis, and proof-gating decisions."""

    domain_status = _validate_target_domain_status(target_domain_status)
    normalized_ownership = _validate_ownership_report(ownership_report)
    normalized_facts = _validate_facts(facts)
    normalized_population = _validate_population_evidence(population_evidence)
    normalized_requirements = _validate_level_requirements(
        level_requirements,
        population_evidence=normalized_population,
    )

    if domain_status == "UNDETERMINABLE":
        analysis = {
            "status": "INADMISSIBLE",
            "reason": "target_domain_undeterminable",
        }
    else:
        analysis = {"status": "ADMISSIBLE"}

    projected_facts = {
        fact["fact_id"]: _project_fact(
            fact=fact,
            ownership_report=normalized_ownership,
        )
        for fact in normalized_facts
    }

    return {
        "analysis": analysis,
        "facts": projected_facts,
        "level_eligibility": _level_eligibility(
            population_evidence=normalized_population,
            level_requirements=normalized_requirements,
        ),
        "population_evidence": normalized_population,
    }
