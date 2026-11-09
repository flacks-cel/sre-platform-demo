"""POPULATION-COMPLETENESS-001: preregistered RED contract tests.

Scenario numbering follows section 8 of
praeva/ownership/POPULATION-COMPLETENESS-001.md, including the regressions
section 8.1 requires.

Inputs are built as minimal documents in the shape each upstream contract
publishes, so a scenario is readable without running the whole pipeline.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

START, END, STEP = 0, 30, 15
GRID = ("0", "15", "30")
POD_A, POD_B = "jobs-api-a", "jobs-api-b"

FAMILIES = ("cpu_short", "cpu_long", "cfs_throttled_short", "cfs_throttled_long")

REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "HIGH": ("cpu_long",),
    "MEDIUM": FAMILIES,
    "LOW": FAMILIES,
}


def _prove() -> Any:
    module = importlib.import_module("praeva.ownership.completeness")
    return module.prove_population_completeness


def _error() -> type[Exception]:
    module = importlib.import_module("praeva.ownership.completeness")
    return module.PopulationCompletenessInputError


def _enumeration(
    *,
    owned: dict[str, list[str]] | None = None,
    unknown_at: dict[str, str] | None = None,
) -> dict[str, Any]:
    owned = owned or {timestamp: [POD_A, POD_B] for timestamp in GRID}
    unknown_at = unknown_at or {}
    timestamps: dict[str, Any] = {}
    for timestamp in GRID:
        if timestamp in unknown_at:
            timestamps[timestamp] = {
                "status": "UNKNOWN",
                "reason": unknown_at[timestamp],
            }
            continue
        timestamps[timestamp] = {
            "status": "ENUMERATED",
            "replicasets": ["jobs-api-rs"],
            "owned_pods": [
                {"pod": pod, "uid": f"uid-{pod}"} for pod in owned[timestamp]
            ],
        }
    return {"population_id": "POPULATION-ENUMERATION-001", "timestamps": timestamps}


def _fact_input(*, observed: dict[str, list[str]] | None = None) -> dict[str, Any]:
    observed = observed or {timestamp: [POD_A, POD_B] for timestamp in GRID}
    facts = [
        {
            "fact_id": f"{family}:{pod}:{timestamp}",
            "pod": pod,
            "evidence_family": family,
            "evaluated_at": timestamp,
        }
        for timestamp, pods in observed.items()
        for pod in pods
        for family in FAMILIES
    ]
    return {
        "fact_input_id": "ATTRIBUTION-FACT-INPUT-001",
        "acquisition": {"namespace": "app", "start": START, "end": END, "step": STEP},
        "facts": facts,
    }


def _summary_proof(
    *,
    pods: tuple[str, ...] = (POD_A, POD_B),
    incomplete: dict[str, tuple[str, ...]] | None = None,
    blocked_by: str = "series_point_count_incomplete",
) -> dict[str, Any]:
    incomplete = incomplete or {}
    return {
        "summary_proof_id": "ATTRIBUTION-SUMMARY-PROOF-001",
        "pods": {
            pod: {
                family: {
                    "witness": {"status": "USABLE", "fact_refs": [], "blocked_by": []},
                    "domain": {
                        "status": (
                            "INCOMPLETE"
                            if family in incomplete.get(pod, ())
                            else "COMPLETE"
                        ),
                        "blocked_by": (
                            [blocked_by] if family in incomplete.get(pod, ()) else []
                        ),
                    },
                }
                for family in FAMILIES
            }
            for pod in pods
        },
    }


def _run(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "enumeration": _enumeration(),
        "fact_input": _fact_input(),
        "summary_proof": _summary_proof(),
        "universal_requirements": REQUIREMENTS,
    }
    kwargs.update(overrides)
    return _prove()(**kwargs)


# ---------------------------------------------------------------------------
# 1-5: the four ways a proof fails, and the one way it holds.
# ---------------------------------------------------------------------------


def test_01_matching_sets_with_complete_domains_are_proven() -> None:
    result = _run()

    assert result["status"] == "PROVEN_COMPLETE"
    assert "reasons" not in result
    assert sorted(result["required_families"]) == sorted(FAMILIES)


def test_02_unobserved_target_pod_is_omission() -> None:
    result = _run(fact_input=_fact_input(observed={t: [POD_A] for t in GRID}))

    assert result["status"] == "UNPROVEN"
    assert "population_omission" in result["reasons"]
    assert result["findings"]["15"]["missing_pods"] == [POD_B]


def test_03_observed_pod_the_target_does_not_own_is_foreign() -> None:
    observed = {t: [POD_A, POD_B, "intruder"] for t in GRID}

    result = _run(fact_input=_fact_input(observed=observed))

    assert "population_foreign_pod" in result["reasons"]
    assert result["findings"]["15"]["foreign_pods"] == ["intruder"]


def test_04_unknown_enumeration_at_a_required_timestamp_blocks() -> None:
    enumeration = _enumeration(
        unknown_at={"15": "pod_series_absent_at_timestamp"},
    )

    result = _run(enumeration=enumeration)

    assert "population_enumeration_unknown" in result["reasons"]


def test_05_target_pod_without_required_evidence_blocks() -> None:
    result = _run(summary_proof=_summary_proof(incomplete={POD_B: ("cpu_long",)}))

    assert "population_evidence_missing" in result["reasons"]
    assert result["findings"]["pods_without_evidence"][POD_B] == ["cpu_long"]


# ---------------------------------------------------------------------------
# 6: a gap outside every required domain does not block (section 5.3).
# ---------------------------------------------------------------------------


def test_06_gap_outside_every_required_family_does_not_block() -> None:
    # cpu_limit has domain NOT_APPLICABLE and is not declared universally,
    # so an incomplete domain there cannot block a proof on its own.
    proof = _summary_proof()
    for pod in (POD_A, POD_B):
        proof["pods"][pod]["cpu_limit"] = {
            "witness": {"status": "UNUSABLE", "fact_refs": [], "blocked_by": ["x"]},
            "domain": {"status": "NOT_APPLICABLE", "blocked_by": []},
        }

    result = _run(summary_proof=proof)

    assert result["status"] == "PROVEN_COMPLETE"


# ---------------------------------------------------------------------------
# 7-9: inputs.
# ---------------------------------------------------------------------------


def test_07_empty_requirements_is_an_input_error() -> None:
    with pytest.raises(_error()):
        _run(universal_requirements={})


@pytest.mark.parametrize(
    "poisoned",
    ["identity_assertion", "population_completeness", "pod_regex", "selector"],
)
def test_08_a_declaration_is_never_accepted_as_evidence(poisoned: str) -> None:
    enumeration = _enumeration()
    enumeration[poisoned] = "PROVEN_COMPLETE"

    with pytest.raises(_error()):
        _run(enumeration=enumeration)


def test_09_same_input_produces_the_same_output() -> None:
    assert _run() == _run()


# ---------------------------------------------------------------------------
# 11-15: the regressions section 8.1 requires.
# ---------------------------------------------------------------------------


def test_11_gap_at_a_non_max_point_of_the_series_blocks() -> None:
    # The series max is at "30"; the hole is at "0". Checking only
    # max_timestamp would turn a lost point into false completeness.
    observed = {"0": [POD_A], "15": [POD_A, POD_B], "30": [POD_A, POD_B]}

    result = _run(fact_input=_fact_input(observed=observed))

    assert result["status"] == "UNPROVEN"
    assert "population_omission" in result["reasons"]
    assert result["findings"]["0"]["missing_pods"] == [POD_B]
    assert "15" not in result["findings"]


def test_12_incomplete_historical_support_blocks_even_when_sets_match() -> None:
    # O(T) == V(T) at every timestamp, so set comparison alone says complete.
    # The support of one series is not attributable, which the summary proof
    # reports as an incomplete domain, and that must still block.
    proof = _summary_proof(
        incomplete={POD_A: ("cpu_short",)},
        blocked_by="series_fact_unattributed",
    )

    result = _run(summary_proof=proof)

    assert result["status"] == "UNPROVEN"
    assert "population_evidence_missing" in result["reasons"]
    assert "population_omission" not in result["reasons"]


def test_13_requirements_restricted_to_one_rung_is_an_input_error() -> None:
    with pytest.raises(_error(), match="MEDIUM|LOW|rung"):
        _run(universal_requirements={"HIGH": ("cpu_long",)})


def test_14_unknown_rung_in_the_declaration_is_an_input_error() -> None:
    declaration = {**REQUIREMENTS, "SEVERE": ("cpu_long",)}

    with pytest.raises(_error(), match="SEVERE"):
        _run(universal_requirements=declaration)


def test_15_the_rule_declaration_is_accepted_as_is() -> None:
    from praeva.risk.cpu_limit_insufficiency import (  # noqa: PLC0415
        UNIVERSAL_POPULATION_REQUIREMENTS,
    )

    result = _run(universal_requirements=UNIVERSAL_POPULATION_REQUIREMENTS)

    assert result["status"] == "PROVEN_COMPLETE"
    assert "cpu_limit" not in result["required_families"]
