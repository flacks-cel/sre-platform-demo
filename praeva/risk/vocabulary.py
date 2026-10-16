from __future__ import annotations

import re
from enum import Enum
from typing import Any

_MACHINE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class ClassificationStatus(Enum):
    CLASSIFIED = "CLASSIFIED"
    UNKNOWN = "UNKNOWN"


class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskVocabularyError(ValueError):
    """Raised when a risk result violates RISK-VOCABULARY-001."""


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _require_machine_id(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _MACHINE_ID_RE.fullmatch(value):
        raise RiskVocabularyError(f"{field} must be a non-empty lower_snake_case identifier")
    return value


def _validate_evidence_refs(value: Any, *, required: bool) -> None:
    if value is None and not required:
        return
    if not isinstance(value, list) or not value:
        raise RiskVocabularyError("evidence_refs must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in value):
        raise RiskVocabularyError("evidence_refs entries must be non-empty strings")


def _validate_unknown_reasons(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise RiskVocabularyError("unknown_reasons must be a non-empty list")

    for reason in value:
        if not isinstance(reason, dict):
            raise RiskVocabularyError("unknown_reasons entries must be objects")
        _require_machine_id(reason.get("code"), field="unknown_reasons.code")
        _require_machine_id(
            reason.get("precondition"),
            field="unknown_reasons.precondition",
        )


def validate_risk_result(result: dict[str, Any]) -> None:
    """Validate only the shared structural vocabulary, never rule policy."""

    if not isinstance(result, dict):
        raise RiskVocabularyError("risk result must be an object")

    hazard_id = result.get("hazard_id")
    _require_machine_id(hazard_id, field="hazard_id")

    raw_status = _enum_value(result.get("classification_status"))
    try:
        status = ClassificationStatus(raw_status)
    except (TypeError, ValueError) as exc:
        raise RiskVocabularyError(
            "classification_status must be CLASSIFIED or UNKNOWN"
        ) from exc

    if status is ClassificationStatus.CLASSIFIED:
        if "unknown_reasons" in result:
            raise RiskVocabularyError(
                "unknown_reasons must be absent when classification_status is CLASSIFIED"
            )

        raw_level = _enum_value(result.get("risk_level"))
        try:
            RiskLevel(raw_level)
        except (TypeError, ValueError) as exc:
            raise RiskVocabularyError(
                "risk_level must be LOW, MEDIUM, HIGH or CRITICAL when classified"
            ) from exc

        _validate_evidence_refs(result.get("evidence_refs"), required=True)
        return

    if "risk_level" in result:
        raise RiskVocabularyError(
            "risk_level must be absent when classification_status is UNKNOWN"
        )

    _validate_unknown_reasons(result.get("unknown_reasons"))
    _validate_evidence_refs(result.get("evidence_refs"), required=False)
