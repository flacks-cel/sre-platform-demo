from __future__ import annotations

import importlib

import pytest


def _api():
    return importlib.import_module("praeva.risk.vocabulary")


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
    api = _api()

    assert api.ClassificationStatus.CLASSIFIED.value == "CLASSIFIED"
    assert api.ClassificationStatus.UNKNOWN.value == "UNKNOWN"
    assert api.RiskLevel.LOW.value == "LOW"
    assert api.RiskLevel.MEDIUM.value == "MEDIUM"
    assert api.RiskLevel.HIGH.value == "HIGH"
    assert api.RiskLevel.CRITICAL.value == "CRITICAL"


def test_risk_levels_are_not_orderable() -> None:
    api = _api()

    with pytest.raises(TypeError):
        _ = api.RiskLevel.LOW < api.RiskLevel.MEDIUM

    with pytest.raises(TypeError):
        max([api.RiskLevel.LOW, api.RiskLevel.CRITICAL])


def test_unknown_is_not_orderable_against_a_risk_level() -> None:
    api = _api()

    with pytest.raises(TypeError):
        _ = api.ClassificationStatus.UNKNOWN < api.RiskLevel.LOW


def test_classified_result_requires_named_hazard() -> None:
    api = _api()

    with pytest.raises(api.RiskVocabularyError, match="hazard_id"):
        api.validate_risk_result(_classified(hazard_id=""))


def test_hazard_id_is_machine_readable_not_free_text() -> None:
    api = _api()

    with pytest.raises(api.RiskVocabularyError, match="hazard_id"):
        api.validate_risk_result(_classified(hazard_id="CPU limit insufficiency"))


def test_classified_result_requires_risk_level_and_evidence_reference() -> None:
    api = _api()
    missing_level = _classified()
    del missing_level["risk_level"]

    with pytest.raises(api.RiskVocabularyError, match="risk_level"):
        api.validate_risk_result(missing_level)

    with pytest.raises(api.RiskVocabularyError, match="evidence_refs"):
        api.validate_risk_result(_classified(evidence_refs=[]))


def test_classified_result_rejects_unknown_reasons() -> None:
    api = _api()

    with pytest.raises(api.RiskVocabularyError, match="unknown_reasons"):
        api.validate_risk_result(
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
    api = _api()

    with pytest.raises(api.RiskVocabularyError, match="risk_level"):
        api.validate_risk_result(_unknown(risk_level="LOW"))


def test_unknown_result_requires_named_reason_and_failed_precondition() -> None:
    api = _api()

    with pytest.raises(api.RiskVocabularyError, match="unknown_reasons"):
        api.validate_risk_result(_unknown(unknown_reasons=[]))

    with pytest.raises(api.RiskVocabularyError, match="precondition"):
        api.validate_risk_result(
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
    api = _api()

    api.validate_risk_result(_classified())
    api.validate_risk_result(_unknown())
