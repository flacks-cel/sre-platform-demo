from collections.abc import Callable

import pytest

from praeva.verify.prometheus_adapter import (
    PrometheusAdapterError,
    collect_normalized_evidence,
)


def matrix(*series: tuple[str, list[tuple[int, str]]]) -> dict:
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


def collector(
    responses: list[dict],
) -> tuple[Callable[..., dict], list[dict]]:
    calls: list[dict] = []
    remaining = list(responses)

    def query_range(**kwargs) -> dict:
        calls.append(kwargs)
        return remaining.pop(0)

    return query_range, calls


def collect(query_range, **kwargs):
    return collect_normalized_evidence(
        prometheus_url="http://prometheus:9090",
        namespace="custom-ns",
        pod_regex="worker-.*",
        container="worker",
        start=0,
        end=30,
        step=15,
        short_window="2m",
        long_window="5m",
        query_range=query_range,
        **kwargs,
    )


def test_adapter_builds_explicit_generic_prometheus_queries():
    query_range, calls = collector(
        [
            matrix(("worker-a", [(0, "0.4"), (15, "0.5"), (30, "0.4")])),
            matrix(("worker-a", [(0, "0.3"), (15, "0.4"), (30, "0.3")])),
            matrix(("worker-a", [(0, "1"), (15, "1"), (30, "1")])),
            matrix(("worker-a", [(0, "2"), (15, "2"), (30, "2")])),
        ]
    )

    collect(query_range, request_rate_query="CUSTOM_REQUEST_QUERY")

    assert len(calls) == 4
    short_query = calls[0]["query"]
    long_query = calls[1]["query"]
    limit_query = calls[2]["query"]

    for query in (short_query, long_query, limit_query):
        assert 'namespace="custom-ns"' in query
        assert 'pod=~"worker-.*"' in query
        assert 'container="worker"' in query
        assert "jobs-api" not in query

    assert "[2m]" in short_query
    assert "[5m]" in long_query
    assert 'resource="cpu"' in limit_query
    assert calls[3]["query"] == "CUSTOM_REQUEST_QUERY"
    assert all(call["prometheus_url"] == "http://prometheus:9090" for call in calls)


def test_adapter_normalizes_per_pod_points_and_coverage():
    query_range, _ = collector(
        [
            matrix(
                ("worker-a", [(0, "0.4"), (15, "0.5"), (30, "0.4")]),
                ("worker-b", [(0, "0.2"), (15, "0.3")]),
            ),
            matrix(
                ("worker-a", [(0, "0.3"), (15, "0.4"), (30, "0.3")]),
                ("worker-b", [(0, "0.1"), (15, "0.2")]),
            ),
            matrix(
                ("worker-a", [(0, "1"), (15, "1"), (30, "1")]),
                ("worker-b", [(0, "0.5"), (15, "0.5")]),
            ),
        ]
    )

    normalized = collect(query_range)
    pods = {pod["name"]: pod for pod in normalized["pods"]}

    assert normalized["short_window"] == "2m"
    assert normalized["long_window"] == "5m"
    assert set(pods) == {"worker-a", "worker-b"}
    assert pods["worker-a"]["sample_count"] == 3
    assert pods["worker-a"]["coverage"] == {"observed_points": 3, "expected_points": 3}
    assert pods["worker-b"]["sample_count"] == 2
    assert pods["worker-b"]["coverage"] == {"observed_points": 2, "expected_points": 3}
    assert pods["worker-a"]["cpu_short"][1] == {
        "timestamp": "15",
        "value": "0.5",
        "query_key": "cpu_short",
    }
    assert pods["worker-a"]["request_rate"] is None


def test_adapter_uses_union_of_pods_and_preserves_missing_limit():
    query_range, _ = collector(
        [
            matrix(
                ("worker-a", [(0, "0.4")]),
                ("worker-b", [(0, "0.2")]),
            ),
            matrix(
                ("worker-a", [(0, "0.3")]),
                ("worker-b", [(0, "0.1")]),
            ),
            matrix(("worker-a", [(0, "1")])),
        ]
    )

    normalized = collect(query_range)
    pods = {pod["name"]: pod for pod in normalized["pods"]}

    assert pods["worker-a"]["cpu_limit"] == [
        {"timestamp": "0", "value": "1", "query_key": "cpu_limit"}
    ]
    assert pods["worker-b"]["cpu_limit"] is None


def test_adapter_preserves_exact_timestamps_without_interpolation():
    query_range, _ = collector(
        [
            matrix(("worker-a", [(7, "0.4"), (22, "0.5")])),
            matrix(("worker-a", [(7, "0.3"), (22, "0.4")])),
            matrix(("worker-a", [(8, "1"), (23, "1")])),
        ]
    )

    normalized = collect(query_range)
    pod = normalized["pods"][0]

    assert [point["timestamp"] for point in pod["cpu_short"]] == ["7", "22"]
    assert [point["timestamp"] for point in pod["cpu_limit"]] == ["8", "23"]


def test_adapter_rejects_duplicate_series_for_same_pod_metric():
    query_range, _ = collector(
        [
            matrix(
                ("worker-a", [(0, "0.4")]),
                ("worker-a", [(0, "0.5")]),
            ),
            matrix(),
            matrix(),
        ]
    )

    with pytest.raises(PrometheusAdapterError, match="duplicate"):
        collect(query_range)


def test_adapter_rejects_prometheus_api_failure():
    query_range, _ = collector(
        [
            {"status": "error", "error": "bad query"},
            matrix(),
            matrix(),
        ]
    )

    with pytest.raises(PrometheusAdapterError, match="Prometheus"):
        collect(query_range)


def test_adapter_rejects_non_matrix_result():
    query_range, _ = collector(
        [
            {
                "status": "success",
                "data": {"resultType": "vector", "result": []},
            },
            matrix(),
            matrix(),
        ]
    )

    with pytest.raises(PrometheusAdapterError, match="matrix"):
        collect(query_range)
