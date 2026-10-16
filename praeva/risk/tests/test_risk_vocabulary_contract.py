from __future__ import annotations

import pytest

from praeva.risk.vocabulary import (
    ClassificationStatus,
    RiskLevel,
    RiskVocabularyError,
    validate_risk_result,
)


def _classified(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "classification_status": "CLASSIFIED",
        "hazard_id": "cpu_limit_insufficiency",
        "risk_level": "HIGH",
        "evidence_refs": ["pods.jobs-api-a.windows.short.comparison"],
    }
    result.update(overrides)
    return result


def _unknown(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "classification_status": "UNKNOWN",
        "hazard_id": "cpu_limit_insufficiency",
        "unknown_reasons": [
            {
                "code": "required_evidence_missing",
                "precondition": "short_window_cpu_valid",
            }
        ],
    }
    result.update(overrides)
    return result


def test_classification_status_and_risk_level_are_separate_enums() -> None:
    assert ClassificationStatus.CLASSIFIED.value == "CLASSIFIED"
    assert ClassificationStatus.UNKNOWN.value == "UNKNOWN"
    assert RiskLevel.LOW.value == "LOW"
    assert RiskLevel.MEDIUM.value == "MEDIUM"
    assert RiskLevel.HIGH.value == "HIGH"
    assert RiskLevel.CRITICAL.value == "CRITICAL"


def test_risk_levels_are_not_orderable() -> None:
    with pytest.raises(TypeError):
        _ = RiskLevel.LOW < RiskLevel.MEDIUM

    with pytest.raises(TypeError):
        max([RiskLevel.LOW, RiskLevel.CRITICAL])


def test_unknown_is_not_orderable_against_a_risk_level() -> None:
    with pytest.raises(TypeError):
        _ = ClassificationStatus.UNKNOWN < RiskLevel.LOW


def test_classified_result_requires_named_hazard() -> None:
    with pytest.raises(RiskVocabularyError, match="hazard_id"):
        validate_risk_result(_classified(hazard_id=""))


def test_hazard_id_is_machine_readable_not_free_text() -> None:
    with pytest.raises(RiskVocabularyError, match="hazard_id"):
        validate_risk_result(_classified(hazard_id="CPU limit insufficiency"))


def test_classified_result_requires_risk_level_and_evidence_reference() -> None:
    missing_level = _classified()
    del missing_level["risk_level"]
    with pytest.raises(RiskVocabularyError, match="risk_level"):
        validate_risk_result(missing_level)

    with pytest.raises(RiskVocabularyError, match="evidence_refs"):
        validate_risk_result(_classified(evidence_refs=[]))


def test_classified_result_rejects_unknown_reasons() -> None:
    with pytest.raises(RiskVocabularyError, match="unknown_reasons"):
        validate_risk_result(
            _classified(
                unknown_reasons=[
                    {
                        "code": "required_evidence_missing",
                        "precondition": "short_window_cpu_valid",
                    }
                ]
            )
        )


def test_unknown_result_has_no_risk_level() -> None:
    with pytest.raises(RiskVocabularyError, match="risk_level"):
        validate_risk_result(_unknown(risk_level="LOW"))


def test_unknown_result_requires_named_reason_and_failed_precondition() -> None:
    with pytest.raises(RiskVocabularyError, match="unknown_reasons"):
        validate_risk_result(_unknown(unknown_reasons=[]))

    with pytest.raises(RiskVocabularyError, match="precondition"):
        validate_risk_result(
            _unknown(
                unknown_reasons=[
                    {
                        "code": "required_evidence_missing",
                        "precondition": "",
                    }
                ]
            )
        )


def test_valid_classified_and_unknown_shapes_are_accepted() -> None:
    validate_risk_result(_classified())
    validate_risk_result(_unknown())
