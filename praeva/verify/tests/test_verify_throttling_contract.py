from collections.abc import Callable

from praeva.verify.cpu_evidence import build_report
from praeva.verify.prometheus_adapter import collect_normalized_evidence


def _matrix(*series: tuple[str, list[tuple[int | str, str]]]) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"pod": pod},
                    "values": [[timestamp, value] for timestamp, value in values],
                }
                for pod, values in series
            ],
        },
    }


def _collector(responses: list[dict]) -> tuple[Callable[..., dict], list[dict]]:
    calls: list[dict] = []
    remaining = list(responses)

    def query_range(**kwargs) -> dict:
        calls.append(kwargs)
        return remaining.pop(0)

    return query_range, calls


def _collect(query_range, *, include_throttling: bool):
    return collect_normalized_evidence(
        prometheus_url="http://prometheus:9090",
        namespace="app",
        pod_regex="jobs-api-.*",
        container="jobs-api",
        start=0,
        end=30,
        step=15,
        short_window="2m",
        long_window="5m",
        include_throttling=include_throttling,
        query_range=query_range,
    )


def _base_pod(**overrides: object) -> dict[str, object]:
    pod: dict[str, object] = {
        "name": "jobs-api-a",
        "cpu_short": [
            {"timestamp": "0", "value": "0.2", "query_key": "cpu_short"},
            {"timestamp": "15", "value": "0.3", "query_key": "cpu_short"},
        ],
        "cpu_long": [
            {"timestamp": "0", "value": "0.15", "query_key": "cpu_long"},
            {"timestamp": "15", "value": "0.25", "query_key": "cpu_long"},
        ],
        "cpu_limit": [
            {"timestamp": "0", "value": "0.5", "query_key": "cpu_limit"},
            {"timestamp": "15", "value": "0.5", "query_key": "cpu_limit"},
        ],
        "request_rate": None,
        "sample_count": 2,
        "coverage": {"observed_points": 2, "expected_points": 2},
        "restart_delta": 0,
        "node": None,
        "owner": None,
    }
    pod.update(overrides)
    return pod


def _report(pod: dict[str, object]) -> dict:
    return build_report(
        pods=[pod],
        short_window="2m",
        long_window="5m",
        acquisition={
            "namespace": "app",
            "pod_selector": {"type": "regex", "value": "jobs-api-.*"},
            "container": "jobs-api",
            "start": "0",
            "end": "15",
            "step": "15",
        },
        queries={},
    )


def test_adapter_preserves_old_query_set_when_throttling_disabled() -> None:
    query_range, calls = _collector(
        [
            _matrix(("jobs-api-a", [(0, "0.2")])),
            _matrix(("jobs-api-a", [(0, "0.15")])),
            _matrix(("jobs-api-a", [(0, "0.5")])),
        ]
    )

    normalized = _collect(query_range, include_throttling=False)

    assert len(calls) == 3
    assert "cfs_throttled_short" not in normalized["queries"]
    assert "cfs_throttled_short" not in normalized["pods"][0]


def test_adapter_adds_explicit_short_and_long_throttling_queries() -> None:
    query_range, calls = _collector(
        [
            _matrix(("jobs-api-a", [(0, "0.2")])),
            _matrix(("jobs-api-a", [(0, "0.15")])),
            _matrix(("jobs-api-a", [(0, "0.5")])),
            _matrix(("jobs-api-a", [(0, "0")])),
            _matrix(("jobs-api-a", [(0, "0")])),
        ]
    )

    normalized = _collect(query_range, include_throttling=True)

    assert len(calls) == 5
    short_query = calls[3]["query"]
    long_query = calls[4]["query"]
    assert "container_cpu_cfs_throttled_periods_total" in short_query
    assert "container_cpu_cfs_throttled_periods_total" in long_query
    assert "[2m]" in short_query
    assert "[5m]" in long_query
    assert normalized["queries"]["cfs_throttled_short"]["rate_window"] == "2m"
    assert normalized["queries"]["cfs_throttled_long"]["rate_window"] == "5m"


def test_adapter_preserves_exact_throttling_wire_values() -> None:
    query_range, _ = _collector(
        [
            _matrix(("jobs-api-a", [(0, "0.2")])),
            _matrix(("jobs-api-a", [(0, "0.15")])),
            _matrix(("jobs-api-a", [(0, "0.5")])),
            _matrix(("jobs-api-a", [("0.125", "0.003333333333333333")])),
            _matrix(("jobs-api-a", [("0.125", "0.001111111111111111")])),
        ]
    )

    normalized = _collect(query_range, include_throttling=True)
    pod = normalized["pods"][0]

    assert pod["cfs_throttled_short"][0] == {
        "timestamp": "0.125",
        "value": "0.003333333333333333",
        "query_key": "cfs_throttled_short",
    }


def test_adapter_tracks_throttling_coverage_per_window() -> None:
    query_range, _ = _collector(
        [
            _matrix(("jobs-api-a", [(0, "0.2"), (15, "0.2"), (30, "0.2")])),
            _matrix(("jobs-api-a", [(0, "0.15"), (15, "0.15"), (30, "0.15")])),
            _matrix(("jobs-api-a", [(0, "0.5"), (15, "0.5"), (30, "0.5")])),
            _matrix(("jobs-api-a", [(0, "0"), (15, "0")])),
            _matrix(("jobs-api-a", [(0, "0"), (15, "0"), (30, "0")])),
        ]
    )

    normalized = _collect(query_range, include_throttling=True)
    coverage = normalized["pods"][0]["throttling_coverage"]

    assert coverage["short"] == {"observed_points": 2, "expected_points": 3}
    assert coverage["long"] == {"observed_points": 3, "expected_points": 3}


def test_complete_zero_throttling_is_valid_and_not_positive() -> None:
    pod = _base_pod(
        cfs_throttled_short=[
            {"timestamp": "0", "value": "0", "query_key": "cfs_throttled_short"},
            {"timestamp": "15", "value": "0", "query_key": "cfs_throttled_short"},
        ],
        cfs_throttled_long=[
            {"timestamp": "0", "value": "0", "query_key": "cfs_throttled_long"},
            {"timestamp": "15", "value": "0", "query_key": "cfs_throttled_long"},
        ],
        throttling_coverage={
            "short": {"observed_points": 2, "expected_points": 2},
            "long": {"observed_points": 2, "expected_points": 2},
        },
    )

    throttling = _report(pod)["pods"]["jobs-api-a"]["cfs_throttling"]

    assert throttling["short"]["status"] == "VALID"
    assert throttling["short"]["any_positive"] is False
    assert throttling["short"]["coverage_complete"] is True


def test_any_positive_throttling_is_reported_with_deterministic_witness() -> None:
    pod = _base_pod(
        cfs_throttled_short=[
            {"timestamp": "0", "value": "0", "query_key": "cfs_throttled_short"},
            {"timestamp": "15", "value": "0.25", "query_key": "cfs_throttled_short"},
        ],
        cfs_throttled_long=[
            {"timestamp": "0", "value": "0", "query_key": "cfs_throttled_long"},
            {"timestamp": "15", "value": "0.1", "query_key": "cfs_throttled_long"},
        ],
        throttling_coverage={
            "short": {"observed_points": 2, "expected_points": 2},
            "long": {"observed_points": 2, "expected_points": 2},
        },
    )

    short = _report(pod)["pods"]["jobs-api-a"]["cfs_throttling"]["short"]

    assert short["any_positive"] is True
    assert short["max_rate"] == "0.25"
    assert short["max_timestamp"] == "15"
    assert short["query_key"] == "cfs_throttled_short"


def test_partial_throttling_series_remains_valid_but_incomplete() -> None:
    pod = _base_pod(
        cfs_throttled_short=[
            {"timestamp": "0", "value": "0", "query_key": "cfs_throttled_short"}
        ],
        cfs_throttled_long=[
            {"timestamp": "0", "value": "0", "query_key": "cfs_throttled_long"}
        ],
        throttling_coverage={
            "short": {"observed_points": 1, "expected_points": 2},
            "long": {"observed_points": 1, "expected_points": 2},
        },
    )

    short = _report(pod)["pods"]["jobs-api-a"]["cfs_throttling"]["short"]

    assert short["status"] == "VALID"
    assert short["any_positive"] is False
    assert short["coverage_complete"] is False


def test_missing_throttling_is_unknown_without_poisoning_existing_verify_status() -> None:
    pod = _base_pod(
        cfs_throttled_short=[],
        cfs_throttled_long=[],
        throttling_coverage={
            "short": {"observed_points": 0, "expected_points": 2},
            "long": {"observed_points": 0, "expected_points": 2},
        },
    )

    report = _report(pod)
    short = report["pods"]["jobs-api-a"]["cfs_throttling"]["short"]

    assert report["status"] == "VALID"
    assert short["status"] == "UNKNOWN"
    assert short["reason_code"] == "missing_throttling"


def test_non_finite_throttling_sample_is_unknown() -> None:
    pod = _base_pod(
        cfs_throttled_short=[
            {"timestamp": "0", "value": "NaN", "query_key": "cfs_throttled_short"}
        ],
        cfs_throttled_long=[
            {"timestamp": "0", "value": "0", "query_key": "cfs_throttled_long"}
        ],
        throttling_coverage={
            "short": {"observed_points": 1, "expected_points": 1},
            "long": {"observed_points": 1, "expected_points": 1},
        },
    )

    short = _report(pod)["pods"]["jobs-api-a"]["cfs_throttling"]["short"]

    assert short["status"] == "UNKNOWN"
    assert short["reason_code"] == "non_finite_sample"


def test_negative_throttling_rate_is_unknown() -> None:
    pod = _base_pod(
        cfs_throttled_short=[
            {"timestamp": "0", "value": "-0.01", "query_key": "cfs_throttled_short"}
        ],
        cfs_throttled_long=[
            {"timestamp": "0", "value": "0", "query_key": "cfs_throttled_long"}
        ],
        throttling_coverage={
            "short": {"observed_points": 1, "expected_points": 1},
            "long": {"observed_points": 1, "expected_points": 1},
        },
    )

    short = _report(pod)["pods"]["jobs-api-a"]["cfs_throttling"]["short"]

    assert short["status"] == "UNKNOWN"
    assert short["reason_code"] == "negative_throttling_rate"
