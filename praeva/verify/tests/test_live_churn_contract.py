from praeva.verify.cpu_evidence import build_report
from praeva.verify.prometheus_adapter import collect_normalized_evidence


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


def test_recently_terminated_pod_can_keep_cpu_rate_but_lose_denominators():
    responses = iter(
        [
            matrix(
                ("live-pod", [(0, "0.4"), (15, "0.4"), (30, "0.4")]),
                ("old-pod", [(0, "0.9"), (15, "0.9"), (30, "0.9")]),
            ),
            matrix(
                ("live-pod", [(0, "0.3"), (15, "0.3"), (30, "0.3")]),
                ("old-pod", [(0, "0.8"), (15, "0.8"), (30, "0.8")]),
            ),
            matrix(("live-pod", [(0, "1"), (15, "1"), (30, "1")])),
            matrix(("live-pod", [(0, "2"), (15, "2"), (30, "2")])),
        ]
    )

    def query_range(**_kwargs):
        return next(responses)

    normalized = collect_normalized_evidence(
        prometheus_url="http://prometheus:9090",
        namespace="app",
        pod_regex="jobs-api-.*",
        container="jobs-api",
        start=0,
        end=30,
        step=15,
        short_window="2m",
        long_window="5m",
        request_rate_query="REQUEST_QUERY",
        query_range=query_range,
    )

    pods = {pod["name"]: pod for pod in normalized["pods"]}
    assert set(pods) == {"live-pod", "old-pod"}
    assert pods["old-pod"]["cpu_short"]
    assert pods["old-pod"]["cpu_limit"] is None
    assert pods["old-pod"]["request_rate"] is None

    report = build_report(
        pods=normalized["pods"],
        short_window=normalized["short_window"],
        long_window=normalized["long_window"],
    )

    assert report["status"] == "VALID"
    assert report["selectors"]["max_cpu_usage_pod"]["status"] == "VALID"
    assert report["selectors"]["max_cpu_usage_pod"]["pod"] == "old-pod"

    limit_selector = report["selectors"]["max_cpu_limit_ratio_pod"]
    assert limit_selector["status"] == "UNKNOWN"
    assert "historical CPU limit missing" in limit_selector["reason"]

    cost_selector = report["selectors"]["max_cpu_cost_rate_pod"]
    assert cost_selector["status"] == "UNKNOWN"
    assert "request telemetry missing" in cost_selector["reason"]
