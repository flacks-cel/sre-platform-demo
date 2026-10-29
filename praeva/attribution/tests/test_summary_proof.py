from __future__ import annotations

import importlib
import json

import pytest


def _module():
    return importlib.import_module("praeva.attribution.summary_proof")


def _fact(pod: str, family: str, timestamp: str) -> dict:
    return {
        "fact_id": f"{family}:{pod}:{timestamp}",
        "pod": pod,
        "evidence_family": family,
        "evaluated_at": timestamp,
    }


def _decision(status: str = "ATTRIBUTED", classification: str | None = None) -> dict:
    result = {"status": status, "support_source": "NOMINAL", "evidence_refs": []}
    if classification is not None:
        result["class"] = classification
    return result


def _cpu_summary(family: str, *, points: int = 3, max_timestamp: str = "30") -> dict:
    return {
        "status": "VALID",
        "window": "2m" if family == "cpu_short" else "5m",
        "max": "0.4",
        "max_timestamp": max_timestamp,
        "query_key": family,
        "points": points,
        "min": "0.1",
    }


def _cfs_summary(
    family: str,
    *,
    any_positive: bool,
    points: int = 3,
    max_timestamp: str = "30",
    coverage_complete: bool = True,
) -> dict:
    return {
        "status": "VALID",
        "window": "2m" if family.endswith("short") else "5m",
        "any_positive": any_positive,
        "max_rate": "0.2" if any_positive else "0",
        "max_timestamp": max_timestamp,
        "query_key": family,
        "points": points,
        "coverage": {"observed_points": points, "expected_points": 3},
        "coverage_complete": coverage_complete,
    }


def _ratio_summary(*, max_timestamp: str = "30") -> dict:
    return {
        "status": "VALID",
        "window": "2m",
        "max": {"numerator": "0.4", "denominator": "0.5"},
        "max_timestamp": max_timestamp,
        "query_keys": {"numerator": "cpu_short", "denominator": "cpu_limit"},
        "points": 3,
    }


def _fixture(
    *,
    cpu_short_points: list[str] | None = None,
    cpu_long_points: list[str] | None = None,
    cfs_short_points: list[str] | None = None,
    cfs_long_points: list[str] | None = None,
    limit_points: list[str] | None = None,
    cpu_short_summary: dict | None = None,
    cpu_long_summary: dict | None = None,
    cfs_short_summary: dict | None = None,
    cfs_long_summary: dict | None = None,
    ratio_summary: dict | None = None,
    decisions: dict[str, dict] | None = None,
):
    pod = "pod-a"
    cpu_short_points = cpu_short_points if cpu_short_points is not None else ["0", "15", "30"]
    cpu_long_points = cpu_long_points if cpu_long_points is not None else ["0", "15", "30"]
    cfs_short_points = cfs_short_points if cfs_short_points is not None else ["0", "15", "30"]
    cfs_long_points = cfs_long_points if cfs_long_points is not None else ["0", "15", "30"]
    limit_points = limit_points if limit_points is not None else ["0", "15", "30"]

    facts = []
    for family, timestamps in (
        ("cpu_short", cpu_short_points),
        ("cpu_long", cpu_long_points),
        ("cfs_throttled_short", cfs_short_points),
        ("cfs_throttled_long", cfs_long_points),
        ("cpu_limit", limit_points),
    ):
        facts.extend(_fact(pod, family, timestamp) for timestamp in timestamps)

    projection = {"facts": {fact["fact_id"]: _decision() for fact in facts}}
    if decisions:
        projection["facts"].update(decisions)

    short_summary = cpu_short_summary or _cpu_summary(
        "cpu_short",
        points=len(cpu_short_points),
    )
    long_summary = cpu_long_summary or _cpu_summary(
        "cpu_long",
        points=len(cpu_long_points),
    )
    verify_report = {
        "status": "VALID",
        "windows": {"short": "2m", "long": "5m"},
        "acquisition": {
            "namespace": "app",
            "pod_selector": {"type": "regex", "value": "pod-.*"},
            "container": "jobs-api",
            "start": "0",
            "end": "30",
            "step": "15",
        },
        "pods": {
            pod: {
                "cpu_usage": {
                    "short": short_summary,
                    "long": long_summary,
                },
                "cpu_limit_ratio": ratio_summary or _ratio_summary(),
                "cfs_throttling": {
                    "short": cfs_short_summary
                    or _cfs_summary(
                        "cfs_throttled_short",
                        any_positive=False,
                        points=len(cfs_short_points),
                        coverage_complete=len(cfs_short_points) == 3,
                    ),
                    "long": cfs_long_summary
                    or _cfs_summary(
                        "cfs_throttled_long",
                        any_positive=False,
                        points=len(cfs_long_points),
                        coverage_complete=len(cfs_long_points) == 3,
                    ),
                },
            }
        },
    }

    fact_input = {
        "fact_input_id": "ATTRIBUTION-FACT-INPUT-001",
        "facts": facts,
    }
    return verify_report, fact_input, projection


def _project(**kwargs):
    verify_report, fact_input, projection = _fixture(**kwargs)
    return _module().project_summary_proof(
        verify_report=verify_report,
        fact_input=fact_input,
        attribution_projection=projection,
    )


def test_cpu_max_attributed_and_complete_has_usable_witness_and_complete_domain():
    result = _project()
    summary = result["pods"]["pod-a"]["cpu_short"]
    assert summary["witness"] == {
        "status": "USABLE",
        "fact_refs": ["cpu_short:pod-a:30"],
        "blocked_by": [],
    }
    assert summary["domain"]["status"] == "COMPLETE"
    assert summary["domain"]["observed_fact_count"] == 3
    assert summary["domain"]["expected_point_count"] == 3
    assert summary["domain"]["unusable_fact_refs"] == []


def test_cpu_argmax_unattributed_makes_witness_unusable_and_domain_incomplete():
    result = _project(
        decisions={
            "cpu_short:pod-a:30": _decision("UNATTRIBUTED", "attribution_unproven")
        }
    )
    summary = result["pods"]["pod-a"]["cpu_short"]
    assert summary["witness"]["status"] == "UNUSABLE"
    assert summary["witness"]["blocked_by"] == ["witness_fact_unattributed"]
    assert summary["domain"]["status"] == "INCOMPLETE"
    assert summary["domain"]["unusable_fact_refs"] == ["cpu_short:pod-a:30"]


def test_cpu_non_argmax_unattributed_preserves_witness_but_breaks_domain():
    result = _project(
        decisions={
            "cpu_short:pod-a:15": _decision("UNATTRIBUTED", "support_predates_pod")
        }
    )
    summary = result["pods"]["pod-a"]["cpu_short"]
    assert summary["witness"]["status"] == "USABLE"
    assert summary["domain"]["status"] == "INCOMPLETE"
    assert summary["domain"]["unusable_fact_refs"] == ["cpu_short:pod-a:15"]


def test_cpu_gap_can_keep_witness_usable_while_domain_is_incomplete():
    result = _project(cpu_short_points=["0", "30"])
    summary = result["pods"]["pod-a"]["cpu_short"]
    assert summary["witness"]["status"] == "USABLE"
    assert summary["domain"]["status"] == "INCOMPLETE"
    assert "series_point_count_incomplete" in summary["domain"]["blocked_by"]


def test_cpu_short_and_long_have_independent_capabilities():
    result = _project(
        decisions={
            "cpu_long:pod-a:15": _decision("UNATTRIBUTED", "identity_discontinuity")
        }
    )
    assert result["pods"]["pod-a"]["cpu_short"]["domain"]["status"] == "COMPLETE"
    assert result["pods"]["pod-a"]["cpu_long"]["domain"]["status"] == "INCOMPLETE"


def test_positive_throttling_witness_can_be_usable_with_incomplete_domain():
    result = _project(
        cfs_short_points=["0", "30"],
        cfs_short_summary=_cfs_summary(
            "cfs_throttled_short",
            any_positive=True,
            points=2,
            max_timestamp="30",
            coverage_complete=False,
        ),
    )
    summary = result["pods"]["pod-a"]["cfs_throttled_short"]
    assert summary["witness"]["status"] == "USABLE"
    assert summary["domain"]["status"] == "INCOMPLETE"


def test_negative_throttling_full_attributed_domain_has_no_witness_and_complete_domain():
    result = _project()
    summary = result["pods"]["pod-a"]["cfs_throttled_short"]
    assert summary["witness"] == {
        "status": "NOT_APPLICABLE",
        "fact_refs": [],
        "blocked_by": [],
    }
    assert summary["domain"]["status"] == "COMPLETE"


def test_negative_throttling_unattributed_point_makes_domain_incomplete():
    result = _project(
        decisions={
            "cfs_throttled_short:pod-a:15": _decision(
                "UNATTRIBUTED", "attribution_unproven"
            )
        }
    )
    summary = result["pods"]["pod-a"]["cfs_throttled_short"]
    assert summary["witness"]["status"] == "NOT_APPLICABLE"
    assert summary["domain"]["status"] == "INCOMPLETE"
    assert summary["domain"]["unusable_fact_refs"] == [
        "cfs_throttled_short:pod-a:15"
    ]


def test_negative_throttling_incomplete_coverage_makes_domain_incomplete():
    result = _project(
        cfs_short_points=["0", "30"],
        cfs_short_summary=_cfs_summary(
            "cfs_throttled_short",
            any_positive=False,
            points=2,
            coverage_complete=False,
        ),
    )
    domain = result["pods"]["pod-a"]["cfs_throttled_short"]["domain"]
    assert domain["status"] == "INCOMPLETE"
    assert "coverage_incomplete" in domain["blocked_by"]


def test_ratio_composite_witness_requires_cpu_and_limit_components():
    result = _project()
    witness = result["pods"]["pod-a"]["cpu_limit_ratio"]["witness"]
    assert witness == {
        "status": "USABLE",
        "fact_refs": ["cpu_short:pod-a:30", "cpu_limit:pod-a:30"],
        "blocked_by": [],
    }
    assert result["pods"]["pod-a"]["cpu_limit_ratio"]["domain"] == {
        "status": "NOT_APPLICABLE"
    }


def test_ratio_limit_component_unattributed_makes_composite_witness_unusable():
    result = _project(
        decisions={
            "cpu_limit:pod-a:30": _decision("UNATTRIBUTED", "support_predates_pod")
        }
    )
    witness = result["pods"]["pod-a"]["cpu_limit_ratio"]["witness"]
    assert witness["status"] == "UNUSABLE"
    assert witness["blocked_by"] == ["composite_witness_component_unattributed"]
    assert witness["fact_refs"] == ["cpu_short:pod-a:30", "cpu_limit:pod-a:30"]


def test_unknown_summary_is_unavailable_not_unusable():
    unknown = {
        "status": "UNKNOWN",
        "window": "2m",
        "reason_code": "missing_cpu",
        "reason": "missing",
    }
    result = _project(cpu_short_summary=unknown)
    summary = result["pods"]["pod-a"]["cpu_short"]
    assert summary["witness"]["status"] == "UNAVAILABLE"
    assert summary["domain"]["status"] == "UNAVAILABLE"
    assert summary["witness"]["reason_code"] == "missing_cpu"


def test_valid_max_timestamp_without_corresponding_fact_is_structural_error():
    module = _module()
    verify_report, fact_input, projection = _fixture(cpu_short_points=["0", "15"])
    verify_report["pods"]["pod-a"]["cpu_usage"]["short"] = _cpu_summary(
        "cpu_short", points=2, max_timestamp="30"
    )
    with pytest.raises(module.AttributionSummaryProofInputError):
        module.project_summary_proof(
            verify_report=verify_report,
            fact_input=fact_input,
            attribution_projection=projection,
        )


def test_fact_set_must_match_projection_exactly():
    module = _module()
    verify_report, fact_input, projection = _fixture()
    projection["facts"].pop("cpu_short:pod-a:15")
    with pytest.raises(module.AttributionSummaryProofInputError):
        module.project_summary_proof(
            verify_report=verify_report,
            fact_input=fact_input,
            attribution_projection=projection,
        )


def test_summary_points_must_match_observed_fact_count():
    module = _module()
    verify_report, fact_input, projection = _fixture()
    verify_report["pods"]["pod-a"]["cpu_usage"]["short"]["points"] = 2
    with pytest.raises(module.AttributionSummaryProofInputError):
        module.project_summary_proof(
            verify_report=verify_report,
            fact_input=fact_input,
            attribution_projection=projection,
        )


def test_query_key_must_match_summary_family():
    module = _module()
    verify_report, fact_input, projection = _fixture()
    verify_report["pods"]["pod-a"]["cpu_usage"]["short"]["query_key"] = "cpu_long"
    with pytest.raises(module.AttributionSummaryProofInputError):
        module.project_summary_proof(
            verify_report=verify_report,
            fact_input=fact_input,
            attribution_projection=projection,
        )


def test_consistent_gap_is_incomplete_not_structural_error():
    result = _project(cpu_long_points=["0", "30"])
    domain = result["pods"]["pod-a"]["cpu_long"]["domain"]
    assert domain["status"] == "INCOMPLETE"
    assert domain["observed_fact_count"] == 2
    assert domain["expected_point_count"] == 3


def test_output_is_deterministic_for_same_input():
    verify_report, fact_input, projection = _fixture()
    module = _module()
    first = module.project_summary_proof(
        verify_report=verify_report,
        fact_input=fact_input,
        attribution_projection=projection,
    )
    second = module.project_summary_proof(
        verify_report=verify_report,
        fact_input=fact_input,
        attribution_projection=projection,
    )
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )
