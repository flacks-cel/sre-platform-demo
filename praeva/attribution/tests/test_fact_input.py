from __future__ import annotations

import importlib

import pytest

from praeva.attribution.projection import project_attribution_decision


def _module():
    return importlib.import_module("praeva.attribution.fact_input")


def _point(timestamp, value="1", query_key=None):
    result = {"timestamp": timestamp, "value": value}
    if query_key is not None:
        result["query_key"] = query_key
    return result


def _normalized(
    *,
    start="600",
    end="900",
    step="15",
    short_window="2m",
    long_window="5m",
    pods=None,
):
    if pods is None:
        pods = [
            {
                "name": "pod-a",
                "cpu_short": [],
                "cpu_long": [],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    return {
        "pods": pods,
        "short_window": short_window,
        "long_window": long_window,
        "acquisition": {
            "namespace": "app",
            "pod_selector": {"type": "regex", "value": "jobs-api-.*"},
            "container": "jobs-api",
            "start": start,
            "end": end,
            "step": step,
        },
        "queries": {
            "cpu_short": {"promql": "cpu short", "rate_window": short_window},
            "cpu_long": {"promql": "cpu long", "rate_window": long_window},
            "cpu_limit": {"promql": "cpu limit", "rate_window": None},
            "cfs_throttled_short": {
                "promql": "cfs short",
                "rate_window": short_window,
            },
            "cfs_throttled_long": {
                "promql": "cfs long",
                "rate_window": long_window,
            },
        },
    }


def _build(*, normalized=None, creation=None):
    return _module().build_attribution_fact_inputs(
        normalized_evidence=normalized or _normalized(),
        creation_by_pod_uid=creation or {},
    )


def _fact(result, fact_id):
    return next(item for item in result["facts"] if item["fact_id"] == fact_id)


def test_five_minute_rate_on_fifteen_second_grid_has_21_required_points():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [],
                "cpu_long": [_point("600", query_key="cpu_long")],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    result = _build(normalized=normalized)
    fact = _fact(result, "cpu_long:pod-a:600")

    assert result["ownership_acquisition"] == {
        "namespace": "app",
        "start": "300",
        "end": "900",
        "step": "15",
    }
    assert fact["support"]["nominal"]["start"] == "300"
    assert fact["support"]["nominal"]["end"] == "600"
    assert fact["support"]["nominal"]["boundary_proven"] is True
    assert len(fact["support"]["nominal"]["required_timestamps"]) == 21
    assert fact["support"]["nominal"]["required_timestamps"][0] == "300"
    assert fact["support"]["nominal"]["required_timestamps"][-1] == "600"


def test_non_divisible_window_marks_boundary_unproven_without_rounding():
    normalized = _normalized(
        short_window="125s",
        long_window="125s",
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [_point("600", query_key="cpu_short")],
                "cpu_long": [],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ],
    )

    result = _build(normalized=normalized)
    fact = _fact(result, "cpu_short:pod-a:600")
    support = fact["support"]["nominal"]

    assert result["ownership_acquisition"]["start"] == "465"
    assert support["start"] == "475"
    assert support["boundary_proven"] is False
    assert support["required_timestamps"][0] == "480"
    assert "475" not in support["required_timestamps"]


def test_short_and_long_at_same_timestamp_are_independent_facts():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [_point("600", query_key="cpu_short")],
                "cpu_long": [_point("600", query_key="cpu_long")],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    result = _build(normalized=normalized)
    ids = {item["fact_id"] for item in result["facts"]}

    assert "cpu_short:pod-a:600" in ids
    assert "cpu_long:pod-a:600" in ids
    assert len(ids) == 2


def test_every_observed_cpu_point_becomes_a_fact_not_only_the_maximum():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [],
                "cpu_long": [
                    _point("600", "0.1", "cpu_long"),
                    _point("615", "0.9", "cpu_long"),
                    _point("630", "0.2", "cpu_long"),
                ],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    result = _build(normalized=normalized)

    assert [item["evaluated_at"] for item in result["facts"]] == ["600", "615", "630"]


def test_cfs_point_becomes_its_own_family_fact():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [],
                "cpu_long": [],
                "cpu_limit": None,
                "cfs_throttled_short": [_point("600", "0", "cfs_throttled_short")],
                "cfs_throttled_long": [],
            }
        ]
    )

    result = _build(normalized=normalized)

    fact = _fact(result, "cfs_throttled_short:pod-a:600")
    assert fact["evidence_family"] == "cfs_throttled_short"
    assert fact["support"]["nominal"]["start"] == "480"


def test_cpu_limit_has_singleton_support():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [],
                "cpu_long": [],
                "cpu_limit": [_point("600", "0.5", "cpu_limit")],
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    result = _build(normalized=normalized)
    support = _fact(result, "cpu_limit:pod-a:600")["support"]["nominal"]

    assert support == {
        "start": "600",
        "end": "600",
        "required_timestamps": ["600"],
        "boundary_proven": True,
    }


def test_multiple_creation_uids_are_copied_without_uid_selection():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [_point("600", query_key="cpu_short")],
                "cpu_long": [],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    result = _build(
        normalized=normalized,
        creation={"pod-a": {"uid-a": "100", "uid-b": "500"}},
    )

    assert _fact(result, "cpu_short:pod-a:600")["creation_by_uid"] == {
        "uid-a": "100",
        "uid-b": "500",
    }


def test_missing_creation_map_becomes_empty_map_not_a_synthetic_timestamp():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [_point("600", query_key="cpu_short")],
                "cpu_long": [],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    result = _build(normalized=normalized, creation={})

    assert _fact(result, "cpu_short:pod-a:600")["creation_by_uid"] == {}


def test_off_grid_sample_is_structural_error():
    module = _module()
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [_point("601", query_key="cpu_short")],
                "cpu_long": [],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    with pytest.raises(module.AttributionFactInputError):
        _build(normalized=normalized)


def test_duplicate_family_pod_timestamp_is_structural_error():
    module = _module()
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [
                    _point("600", "0.1", "cpu_short"),
                    _point("600", "0.2", "cpu_short"),
                ],
                "cpu_long": [],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    with pytest.raises(module.AttributionFactInputError):
        _build(normalized=normalized)


def test_float_timestamp_is_structural_error():
    module = _module()
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [_point(600.0, query_key="cpu_short")],
                "cpu_long": [],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    with pytest.raises(module.AttributionFactInputError):
        _build(normalized=normalized)


def test_unsupported_duration_is_structural_error():
    module = _module()

    with pytest.raises(module.AttributionFactInputError):
        _build(normalized=_normalized(short_window="1m30s"))


def test_missing_points_do_not_create_synthetic_unknown_facts():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [_point("600", query_key="cpu_short")],
                "cpu_long": [],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    result = _build(normalized=normalized)

    assert [item["fact_id"] for item in result["facts"]] == ["cpu_short:pod-a:600"]


def test_required_timestamp_union_is_sorted_and_deduplicated():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [
                    _point("600", query_key="cpu_short"),
                    _point("615", query_key="cpu_short"),
                ],
                "cpu_long": [],
                "cpu_limit": [_point("600", query_key="cpu_limit")],
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )

    result = _build(normalized=normalized)
    required = result["required_timestamps_by_pod"]["pod-a"]

    assert required == sorted(set(required), key=int)
    assert required[0] == "480"
    assert required[-1] == "615"
    assert required.count("600") == 1


def test_request_rate_is_ignored_in_this_slice():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [],
                "cpu_long": [],
                "cpu_limit": None,
                "request_rate": [_point("600", "10", "request_rate")],
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )
    normalized["queries"]["request_rate"] = {"promql": "requests", "rate_window": None}

    result = _build(normalized=normalized)

    assert result["facts"] == []
    assert result["required_timestamps_by_pod"] == {}


def test_output_fact_shape_is_accepted_by_attribution_decision_002():
    normalized = _normalized(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [],
                "cpu_long": [],
                "cpu_limit": [_point("600", "0.5", "cpu_limit")],
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ]
    )
    result = _build(
        normalized=normalized,
        creation={"pod-a": {"uid-a": "100"}},
    )
    ownership_report = {
        "ownership_id": "WORKLOAD-OWNERSHIP-001",
        "target_workload": {
            "api_group": "apps",
            "kind": "Deployment",
            "namespace": "app",
            "name": "jobs-api",
        },
        "pods": {
            "pod-a": {
                "required_timestamps": ["600"],
                "ownership": {
                    "600": {
                        "evidence_status": "VALID",
                        "relation": "TARGET_MATCH",
                        "pod_identity": {
                            "namespace": "app",
                            "name": "pod-a",
                            "uid": "uid-a",
                        },
                        "evidence_refs": ["pod_owner", "replicaset_owner"],
                    }
                },
            }
        },
    }

    projected = project_attribution_decision(
        target_domain_status="DETERMINED",
        ownership_report=ownership_report,
        facts=result["facts"],
        population_evidence={},
        level_requirements={},
    )

    assert projected["facts"]["cpu_limit:pod-a:600"]["status"] == "ATTRIBUTED"
