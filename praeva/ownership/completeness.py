"""POPULATION-COMPLETENESS-001: compose the proof of population completeness.

Produces the PROVEN_COMPLETE value the CHANGE-RISK-001 population gate reads
and that nothing produces today.

Two things must hold, and they fail differently: every pod the target owned
must have been observed (S5), and every one of them must carry usable
evidence for the families the rule quantifies over (S6).

Scope comes from the rule's declarative, versioned requirements -- never from
evidence_refs, risk_level or the trajectory a particular evaluation took
(contract section 5.1). Pure function: no query, no network.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

COMPLETENESS_ID = "POPULATION-COMPLETENESS-001"

STATUS_PROVEN_COMPLETE = "PROVEN_COMPLETE"
STATUS_UNPROVEN = "UNPROVEN"

REASON_OMISSION = "population_omission"
REASON_FOREIGN = "population_foreign_pod"
REASON_ENUMERATION_UNKNOWN = "population_enumeration_unknown"
REASON_EVIDENCE_MISSING = "population_evidence_missing"

# The gate reads one scalar with no rung stamp, so the proof must cover the
# union of every non-CRITICAL conclusion it can unlock. A declaration missing
# one of them would let a proof computed for HIGH be reused for LOW.
REQUIRED_RUNGS = frozenset({"HIGH", "MEDIUM", "LOW"})

_FORBIDDEN_INPUT_KEYS = frozenset(
    {"identity_assertion", "population_completeness", "pod_regex", "selector"}
)


class PopulationCompletenessInputError(ValueError):
    """Raised when completeness composition receives malformed input."""


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PopulationCompletenessInputError(f"{field} must be an object")
    return value


def _int(value: Any, *, field: str) -> int:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PopulationCompletenessInputError(f"{field} must be an integer") from exc
    if parsed != parsed.to_integral_value():
        raise PopulationCompletenessInputError(f"{field} must be an integer")
    return int(parsed)


def _required_families(universal_requirements: Any) -> tuple[str, ...]:
    requirements = _mapping(universal_requirements, field="universal_requirements")
    if not requirements:
        raise PopulationCompletenessInputError(
            "universal_requirements must not be empty: a proof about nothing is not a proof"
        )

    unknown = sorted(set(requirements) - REQUIRED_RUNGS)
    if unknown:
        raise PopulationCompletenessInputError(
            "unknown rung(s) in universal_requirements: " + ", ".join(unknown)
        )

    missing = sorted(REQUIRED_RUNGS - set(requirements))
    if missing:
        raise PopulationCompletenessInputError(
            "universal_requirements must declare every non-CRITICAL rung; missing: "
            + ", ".join(missing)
            + ". The gate reads one scalar, so a proof restricted to one rung "
            "cannot be reused for another"
        )

    families: set[str] = set()
    for rung, declared in requirements.items():
        if not isinstance(declared, list | tuple):
            raise PopulationCompletenessInputError(
                f"universal_requirements[{rung}] must be a sequence of families"
            )
        for family in declared:
            if not isinstance(family, str) or not family:
                raise PopulationCompletenessInputError(
                    f"universal_requirements[{rung}] must hold non-empty family names"
                )
            families.add(family)

    if not families:
        raise PopulationCompletenessInputError(
            "universal_requirements declares no evidence family"
        )
    return tuple(sorted(families))


def _reject_declared_proof(*documents: Any) -> None:
    """A caller's assertion is never evidence, at any depth."""

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            present = _FORBIDDEN_INPUT_KEYS.intersection(node)
            if present:
                raise PopulationCompletenessInputError(
                    "completeness inputs must not carry "
                    + ", ".join(sorted(present))
                    + ": a declaration is not evidence"
                )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for document in documents:
        walk(document)


def _evaluation_grid(fact_input: dict[str, Any]) -> list[str]:
    acquisition = _mapping(fact_input.get("acquisition"), field="fact_input.acquisition")
    start = _int(acquisition.get("start"), field="fact_input.acquisition.start")
    end = _int(acquisition.get("end"), field="fact_input.acquisition.end")
    step = _int(acquisition.get("step"), field="fact_input.acquisition.step")
    if step <= 0:
        raise PopulationCompletenessInputError("fact_input.acquisition.step must be positive")
    if end < start:
        raise PopulationCompletenessInputError("fact_input.acquisition.end precedes start")
    return [str(point) for point in range(start, end + 1, step)]


def _observed_by_timestamp(
    fact_input: dict[str, Any],
    *,
    families: tuple[str, ...],
) -> dict[str, set[str]]:
    facts = fact_input.get("facts")
    if not isinstance(facts, list):
        raise PopulationCompletenessInputError("fact_input.facts must be a list")

    observed: dict[str, set[str]] = {}
    for fact in facts:
        entry = _mapping(fact, field="fact_input.facts[]")
        if entry.get("evidence_family") not in families:
            continue
        pod = entry.get("pod")
        timestamp = entry.get("evaluated_at")
        if not isinstance(pod, str) or not isinstance(timestamp, str):
            raise PopulationCompletenessInputError("fact must carry pod and evaluated_at")
        observed.setdefault(timestamp, set()).add(pod)
    return observed


def _domain_is_complete(capability: Any) -> bool:
    """A family is usable for a universal claim only with a complete domain.

    Covers both halves of contract section 5.2: every expected evaluation
    point present, and every fact of the series attributable, which is where
    an incomplete [T-W,T] support or a UID discontinuity surfaces.
    """

    if not isinstance(capability, dict):
        return False
    domain = capability.get("domain")
    if not isinstance(domain, dict):
        return False
    return domain.get("status") == "COMPLETE"


def prove_population_completeness(
    *,
    enumeration: dict,
    fact_input: dict,
    summary_proof: dict,
    universal_requirements: dict,
) -> dict[str, Any]:
    """Decide whether the observed population is provably the target's."""

    enumeration_map = _mapping(enumeration, field="enumeration")
    fact_input_map = _mapping(fact_input, field="fact_input")
    summary_proof_map = _mapping(summary_proof, field="summary_proof")
    _reject_declared_proof(enumeration_map, fact_input_map, summary_proof_map)

    families = _required_families(universal_requirements)
    grid = _evaluation_grid(fact_input_map)
    observed = _observed_by_timestamp(fact_input_map, families=families)
    enumerated = _mapping(enumeration_map.get("timestamps"), field="enumeration.timestamps")
    proof_pods = _mapping(summary_proof_map.get("pods"), field="summary_proof.pods")

    findings: dict[str, Any] = {}
    reasons: list[str] = []
    target_pods: set[str] = set()

    def note(timestamp: str, key: str, values: list[str]) -> None:
        findings.setdefault(timestamp, {})[key] = values

    for timestamp in grid:
        entry = enumerated.get(timestamp)
        if not isinstance(entry, dict) or entry.get("status") != "ENUMERATED":
            reason = (
                entry.get("reason", "absent") if isinstance(entry, dict) else "absent"
            )
            note(timestamp, "enumeration_unknown", [str(reason)])
            if REASON_ENUMERATION_UNKNOWN not in reasons:
                reasons.append(REASON_ENUMERATION_UNKNOWN)
            continue

        owned_entries = entry.get("owned_pods")
        if not isinstance(owned_entries, list):
            raise PopulationCompletenessInputError(
                f"enumeration.timestamps.{timestamp}.owned_pods must be a list"
            )
        owned = {str(item["pod"]) for item in owned_entries if isinstance(item, dict)}
        target_pods |= owned

        seen = observed.get(timestamp, set())
        missing = sorted(owned - seen)
        foreign = sorted(seen - owned)

        if missing:
            note(timestamp, "missing_pods", missing)
            if REASON_OMISSION not in reasons:
                reasons.append(REASON_OMISSION)
        if foreign:
            note(timestamp, "foreign_pods", foreign)
            if REASON_FOREIGN not in reasons:
                reasons.append(REASON_FOREIGN)

    # Evidence usability is a property of the series, not of one timestamp, so
    # it is checked once per pod of the target across the required families.
    pods_without_evidence: dict[str, list[str]] = {}
    for pod in sorted(target_pods):
        capabilities = proof_pods.get(pod)
        if not isinstance(capabilities, dict):
            pods_without_evidence[pod] = list(families)
            continue
        unusable = [
            family
            for family in families
            if not _domain_is_complete(capabilities.get(family))
        ]
        if unusable:
            pods_without_evidence[pod] = unusable

    if pods_without_evidence:
        findings["pods_without_evidence"] = pods_without_evidence
        if REASON_EVIDENCE_MISSING not in reasons:
            reasons.append(REASON_EVIDENCE_MISSING)

    result: dict[str, Any] = {
        "completeness_id": COMPLETENESS_ID,
        "status": STATUS_UNPROVEN if reasons else STATUS_PROVEN_COMPLETE,
        "required_families": list(families),
        "evaluated_timestamps": grid,
    }
    if reasons:
        result["reasons"] = reasons
        result["findings"] = findings
    return result
