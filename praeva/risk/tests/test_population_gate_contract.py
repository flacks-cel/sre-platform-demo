"""CHANGE-RISK-001-POPULATION-GATE-001: preregistered RED contract tests.

Scenario numbering follows section 9 of
praeva/risk/CHANGE-RISK-001-POPULATION-GATE-001.md.

The gate blocks the risk levels whose logical form contains a universal
quantifier when the observed pod population is not proven complete.
CRITICAL is existential and survives; NOT_APPLICABLE comes from direction
and is untouched.

No production implementation belongs in this commit.
"""

from __future__ import annotations

from typing import Any

import pytest

from praeva.risk.cpu_limit_insufficiency import evaluate_cpu_limit_insufficiency
from praeva.risk.tests.test_change_risk_001_contract import (
    _joined,
    _pod,
    _throttling,
)

MARGIN = {"numerator": 11, "denominator": 10}

GATE_CODE = "population_completeness_unproven"
GATE_PRECONDITION = "proven_complete_target_population"

# Default pod evidence is short=400, long=350 millicores, so the proposed
# limit selects the candidate rung deterministically.
PROPOSED_CRITICAL = 300  # below long
PROPOSED_HIGH = 380  # between long and short
PROPOSED_MEDIUM = 430  # above short, inside the margin
PROPOSED_LOW = 440  # at the exact margin boundary


def _evaluate(**kwargs: Any) -> dict[str, Any]:
    return evaluate_cpu_limit_insufficiency(joined=_joined(**kwargs), margin=MARGIN)


def _reason_codes(result: dict[str, Any]) -> list[str]:
    return [entry["code"] for entry in result.get("unknown_reasons", [])]


def _gate_entry(result: dict[str, Any]) -> dict[str, Any]:
    matches = [
        entry for entry in result.get("unknown_reasons", []) if entry["code"] == GATE_CODE
    ]
    assert len(matches) == 1, f"gate reason must appear exactly once: {matches}"
    return matches[0]


def _assert_gated(result: dict[str, Any]) -> None:
    assert result["classification_status"] == "UNKNOWN"
    assert "risk_level" not in result
    assert _gate_entry(result)["precondition"] == GATE_PRECONDITION


# ---------------------------------------------------------------------------
# 1-2: CRITICAL is existential and survives an unproven population.
# ---------------------------------------------------------------------------


def test_01_critical_survives_unproven_population() -> None:
    result = _evaluate(proposed=PROPOSED_CRITICAL, population_completeness=None)

    assert result["classification_status"] == "CLASSIFIED"
    assert result["risk_level"] == "CRITICAL"
    assert GATE_CODE not in _reason_codes(result)


def test_02_critical_is_unchanged_with_proven_population() -> None:
    result = _evaluate(proposed=PROPOSED_CRITICAL)

    assert result["risk_level"] == "CRITICAL"


# ---------------------------------------------------------------------------
# 3-8: the three universal rungs are gated without proof, intact with it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("proposed", "level"),
    [
        (PROPOSED_HIGH, "HIGH"),
        (PROPOSED_MEDIUM, "MEDIUM"),
        (PROPOSED_LOW, "LOW"),
    ],
)
def test_03_05_07_universal_rungs_are_gated_without_proof(
    proposed: int,
    level: str,
) -> None:
    del level  # named for readability of the parametrisation

    result = _evaluate(proposed=proposed, population_completeness=None)

    _assert_gated(result)


@pytest.mark.parametrize(
    ("proposed", "level"),
    [
        (PROPOSED_HIGH, "HIGH"),
        (PROPOSED_MEDIUM, "MEDIUM"),
        (PROPOSED_LOW, "LOW"),
    ],
)
def test_04_06_08_universal_rungs_survive_with_proof(proposed: int, level: str) -> None:
    result = _evaluate(proposed=proposed)

    assert result["classification_status"] == "CLASSIFIED"
    assert result["risk_level"] == level


# ---------------------------------------------------------------------------
# 9: reasons accumulate. Censorship and unproven population block
# independently and have different remedies.
# ---------------------------------------------------------------------------


def test_09_censored_evidence_and_unproven_population_report_both_reasons() -> None:
    censored = {"pod-a": _pod(throttle_long=_throttling(window="long", positive=True))}
    result = _evaluate(
        proposed=PROPOSED_LOW,
        pods=censored,
        population_completeness=None,
    )

    codes = _reason_codes(result)
    assert "censored_evidence" in codes
    assert GATE_CODE in codes
    assert result["classification_status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# 10-11: fail closed. Absence is never proof.
# ---------------------------------------------------------------------------


def test_10_absent_field_is_treated_as_unproven() -> None:
    result = _evaluate(proposed=PROPOSED_LOW, population_completeness=None)

    _assert_gated(result)


@pytest.mark.parametrize(
    "value",
    ["UNPROVEN", "proven_complete", "", "PARTIAL", "TRUE"],
)
def test_11_unrecognised_value_is_treated_as_unproven(value: str) -> None:
    result = _evaluate(proposed=PROPOSED_LOW, population_completeness=value)

    _assert_gated(result)


# ---------------------------------------------------------------------------
# 12: applicability comes from direction, not from evidence.
# ---------------------------------------------------------------------------


def test_12_not_applicable_is_untouched_by_the_gate() -> None:
    result = _evaluate(
        proposed="ABSENT",
        direction="LIMIT_REMOVED",
        population_completeness=None,
    )

    assert result["applicability"] == "NOT_APPLICABLE"
    assert GATE_CODE not in _reason_codes(result)


# ---------------------------------------------------------------------------
# 13-14: the S9 pair. The same evidence, with and without proof, and in
# neither case is the answer HIGH.
# ---------------------------------------------------------------------------


def _s9_pods(*, hidden: bool) -> dict[str, Any]:
    """Two observed pods yielding HIGH, plus a hidden pod with a long
    contradiction that makes the complete population CRITICAL."""

    pods = {
        "pod-a": _pod(short="400", long="350"),
        "pod-b": _pod(short="400", long="350"),
    }
    if hidden:
        pods["pod-c"] = _pod(short="400", long="390")
    return pods


def test_13_s9_subset_is_unknown_never_high() -> None:
    result = _evaluate(
        proposed=PROPOSED_HIGH,
        pods=_s9_pods(hidden=False),
        population_completeness=None,
    )

    assert result.get("risk_level") != "HIGH"
    _assert_gated(result)


def test_14_s9_complete_population_is_critical() -> None:
    result = _evaluate(
        proposed=PROPOSED_HIGH,
        pods=_s9_pods(hidden=True),
        population_completeness="PROVEN_COMPLETE",
    )

    assert result["classification_status"] == "CLASSIFIED"
    assert result["risk_level"] == "CRITICAL"
