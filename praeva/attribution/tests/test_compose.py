from __future__ import annotations

import copy
import importlib
import json

import pytest

from praeva.ownership.prometheus_adapter import collect_ownership_evidence
from praeva.verify.cpu_evidence import build_report


POD = "jobs-api-abc"
UID = "uid-a"
TIMESTAMPS = ["570", "585", "600", "615", "630"]
TARGET = {
    "api_group": "apps",
    "kind": "Deployment",
    "namespace": "app",
    "name": "jobs-api",
}


def _module():
    return importlib.import_module("praeva.attribution.compose")


def _points(family: str, values: list[str]) -> list[dict]:
    return [
        {"timestamp": timestamp, "value": value, "query_key": family}
        for timestamp, value in zip(["600", "615", "630"], values, strict=True)
    ]


def _normalized() -> dict:
    short, long = "15s", "30s"
    return {
        "pods": [{
            "name": POD,
            "cpu_short": _points("cpu_short", ["0.2", "0.3", "0.4"]),
            "cpu_long": _points("cpu_long", ["0.2", "0.3", "0.4"]),
            "cpu_limit": _points("cpu_limit", ["0.5", "0.5", "0.5"]),
            "cfs_throttled_short": _points(
                "cfs_throttled_short", ["0", "0", "0"]
            ),
            "cfs_throttled_long": _points(
                "cfs_throttled_long", ["0", "0", "0"]
            ),
            "request_rate": [],
            "sample_count": 3,
            "coverage": {"observed_points": 3, "expected_points": 3},
            "throttling_coverage": {
                "short": {"observed_points": 3, "expected_points": 3},
                "long": {"observed_points": 3, "expected_points": 3},
            },
        }],
        "short_window": short,
        "long_window": long,
        "acquisition": {
            "namespace": "app",
            "container": "jobs-api",
            "pod_selector": {"type": "regex", "value": "jobs-api-.*"},
            "start": "600",
            "end": "630",
            "step": "15",
        },
        "queries": {
            family: {"promql": family, "rate_window": window}
            for family, window in (
                ("cpu_short", short),
                ("cpu_long", long),
                ("cpu_limit", None),
                ("cfs_throttled_short", short),
                ("cfs_throttled_long", long),
            )
        },
    }


def _matrix(metric: dict, *, missing_timestamp: str | None = None) -> dict:
    values = [
        [timestamp, "1"]
        for timestamp in TIMESTAMPS
        if timestamp != missing_timestamp
    ]
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [{"metric": metric, "values": values}],
        },
    }


def _ownership(
    *,
    start: str = "570",
    step: str = "15",
    missing_pod_timestamp: str | None = None,
    deployment: str = "jobs-api",
) -> dict:
    pod_metric = {
        "namespace": "app",
        "pod": POD,
        "uid": UID,
        "owner_kind": "ReplicaSet",
        "owner_name": "jobs-api-rs",
        "owner_is_controller": "true",
    }
    rs_metric = {
        "namespace": "app",
        "replicaset": "jobs-api-rs",
        "owner_kind": "Deployment",
        "owner_name": deployment,
        "owner_is_controller": "true",
    }

    def transport(**kwargs: str) -> dict:
        query = kwargs["query"]
        if "kube_pod_owner" in query:
            return _matrix(pod_metric, missing_timestamp=missing_pod_timestamp)
        if "kube_replicaset_owner" in query:
            return _matrix(rs_metric)
        raise AssertionError(f"unexpected query: {query}")

    return collect_ownership_evidence(
        prometheus_url="http://prometheus.test",
        namespace="app",
        start=start,
        end="630",
        step=step,
        query_range=transport,
    )


def _inputs() -> dict:
    normalized = _normalized()
    return {
        "normalized_evidence": normalized,
        "verify_report": build_report(
            pods=normalized["pods"],
            short_window=normalized["short_window"],
            long_window=normalized["long_window"],
            acquisition=normalized["acquisition"],
            queries=normalized["queries"],
        ),
        "ownership_evidence": _ownership(),
        "creation_by_pod_uid": {POD: {UID: "100"}},
        "target_workload": TARGET,
        "target_domain_status": "DETERMINED",
        "population_evidence": {
            "cpu_short": {"status": "COMPLETE", "diagnostics": []},
            "cpu_long": {"status": "COMPLETE", "diagnostics": []},
        },
        "level_requirements": {
            "CRITICAL": [{"quantifier": "EXISTS", "domain": "cpu_long"}],
            "HIGH": [
                {"quantifier": "EXISTS", "domain": "cpu_short"},
                {"quantifier": "FORALL", "domain": "cpu_long"},
            ],
        },
    }


def _compose(**changes):
    inputs = _inputs()
    inputs.update(changes)
    return _module().compose_attribution(**inputs)


def test_integrates_four_existing_layers_without_risk_or_analyze():
    result = _compose()
    assert result["compose_id"] == "ATTRIBUTION-COMPOSE-001"
    assert result["fact_input"]["ownership_acquisition"] == {
        "namespace": "app",
        "start": "570",
        "end": "630",
        "step": "15",
    }
    assert len(result["fact_input"]["facts"]) == 15
    assert result["ownership"]["ownership_id"] == "WORKLOAD-OWNERSHIP-001"
    assert result["attribution"]["analysis"]["status"] == "ADMISSIBLE"
    assert set(result["attribution"]["facts"]) == {
        fact["fact_id"] for fact in result["fact_input"]["facts"]
    }
    assert all(
        fact["status"] == "ATTRIBUTED"
        for fact in result["attribution"]["facts"].values()
    )
    assert result["summary_proof"]["pods"][POD]["cpu_long"]["witness"]["status"] == "USABLE"
    assert result["summary_proof"]["pods"][POD]["cpu_long"]["domain"]["status"] == "COMPLETE"
    assert (
        result["summary_proof"]["pods"][POD]["cpu_limit_ratio"]["witness"]["status"]
        == "USABLE"
    )


def test_composition_is_deterministic_and_does_not_mutate_inputs():
    inputs = _inputs()
    original = copy.deepcopy(inputs)
    first = _module().compose_attribution(**inputs)
    second = _module().compose_attribution(**inputs)
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )
    assert inputs == original


@pytest.mark.parametrize(
    ("field", "value"),
    [("start", "585"), ("step", "10"), ("end", "615"), ("namespace", "other")],
)
def test_ownership_acquisition_must_match_exact_fact_input_plan(field, value):
    inputs = _inputs()
    inputs["ownership_evidence"]["acquisition"][field] = value
    with pytest.raises(_module().AttributionComposeInputError):
        _module().compose_attribution(**inputs)


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    [
        ("windows", "short", "30s"),
        ("acquisition", "namespace", "elsewhere"),
        ("acquisition", "step", "30"),
        ("queries", "cpu_long", {"promql": "other", "rate_window": "30s"}),
    ],
)
def test_verify_report_must_match_normalized_source(section, field, replacement):
    inputs = _inputs()
    inputs["verify_report"][section][field] = replacement
    with pytest.raises(_module().AttributionComposeInputError):
        _module().compose_attribution(**inputs)


def test_missing_ownership_sample_is_not_structural_error_and_keeps_all_facts():
    result = _compose(ownership_evidence=_ownership(missing_pod_timestamp="585"))
    assert len(result["attribution"]["facts"]) == 15
    assert (
        result["attribution"]["facts"]["cpu_long:jobs-api-abc:600"]["status"]
        == "UNATTRIBUTED"
    )
    assert result["attribution"]["facts"]["cpu_long:jobs-api-abc:630"]["status"] == "ATTRIBUTED"
    long_proof = result["summary_proof"]["pods"][POD]["cpu_long"]
    assert long_proof["witness"]["status"] == "USABLE"
    assert long_proof["domain"]["status"] == "INCOMPLETE"
    assert result["attribution"]["level_eligibility"]["CRITICAL"]["status"] == "ELIGIBLE"
    assert result["attribution"]["level_eligibility"]["HIGH"]["status"] == "BLOCKED"
    assert result["attribution"]["effective_population_evidence"]["cpu_long"]["status"] == (
        "INCOMPLETE"
    )


def test_explicit_incomplete_population_blocks_only_forall_requirement():
    inputs = _inputs()
    inputs["population_evidence"]["cpu_long"]["status"] = "INCOMPLETE"
    result = _module().compose_attribution(**inputs)
    assert result["summary_proof"]["pods"][POD]["cpu_long"]["domain"]["status"] == "COMPLETE"
    assert result["attribution"]["level_eligibility"]["CRITICAL"]["status"] == "ELIGIBLE"
    assert result["attribution"]["level_eligibility"]["HIGH"]["status"] == "BLOCKED"


def test_undeterminable_target_is_semantic_inadmissibility_not_input_error():
    result = _compose(target_domain_status="UNDETERMINABLE")
    assert result["attribution"]["analysis"] == {
        "status": "INADMISSIBLE",
        "reason": "target_domain_undeterminable",
    }


def test_creation_missing_makes_facts_unattributed_without_fabricated_uid():
    result = _compose(creation_by_pod_uid={})
    facts = result["attribution"]["facts"]
    assert all(fact["status"] == "UNATTRIBUTED" for fact in facts.values())
    assert {fact["class"] for fact in facts.values()} == {"attribution_unproven"}
    assert (
        result["summary_proof"]["pods"][POD]["cpu_limit_ratio"]["witness"]["status"]
        == "UNUSABLE"
    )


def test_foreign_workload_is_not_silently_recast_as_missing_population():
    result = _compose(ownership_evidence=_ownership(deployment="foreign"))
    assert all(
        item["class"] == "foreign_workload"
        for item in result["attribution"]["facts"].values()
    )
    assert (
        result["attribution"]["effective_population_evidence"]["cpu_long"]["status"]
        == "COMPLETE"
    )
    assert (
        result["summary_proof"]["pods"][POD]["cpu_long"]["witness"]["status"]
        == "UNUSABLE"
    )
