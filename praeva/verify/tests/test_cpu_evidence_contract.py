from praeva.verify.cpu_evidence import build_report


def point(timestamp: int, value: float) -> dict[str, float | int]:
    return {"timestamp": timestamp, "value": value}


def pod(
    name: str,
    *,
    cpu_short: list[dict[str, float | int]],
    cpu_long: list[dict[str, float | int]] | None = None,
    cpu_limit: list[dict[str, float | int]] | None = None,
    request_rate: list[dict[str, float | int]] | None = None,
    sample_count: int = 10,
    coverage: float = 1.0,
    restart_delta: int = 0,
    node: str = "worker-1",
    owner: str = "rs-a",
) -> dict:
    return {
        "name": name,
        "cpu_short": cpu_short,
        "cpu_long": cpu_long if cpu_long is not None else cpu_short,
        "cpu_limit": cpu_limit,
        "request_rate": request_rate,
        "sample_count": sample_count,
        "coverage": coverage,
        "restart_delta": restart_delta,
        "node": node,
        "owner": owner,
    }


def build(pods: list[dict], **kwargs) -> dict:
    return build_report(
        pods=pods,
        short_window="2m",
        long_window="5m",
        **kwargs,
    )


def test_named_selectors_can_choose_three_different_pods():
    report = build(
        [
            pod(
                "cpu-pod",
                cpu_short=[point(10, 0.9)],
                cpu_limit=[point(10, 2.0)],
                request_rate=[point(10, 10.0)],
            ),
            pod(
                "ratio-pod",
                cpu_short=[point(10, 0.6)],
                cpu_limit=[point(10, 0.5)],
                request_rate=[point(10, 10.0)],
            ),
            pod(
                "cost-pod",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 1.0)],
                request_rate=[point(10, 0.1)],
            ),
        ]
    )

    selectors = report["selectors"]
    assert selectors["max_cpu_usage_pod"]["pod"] == "cpu-pod"
    assert selectors["max_cpu_limit_ratio_pod"]["pod"] == "ratio-pod"
    assert selectors["max_cpu_cost_rate_pod"]["pod"] == "cost-pod"
    assert "worst_pod" not in report
    assert "worst_pod" not in selectors


def test_missing_historical_limit_only_makes_limit_selector_unknown():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.4)],
                cpu_limit=None,
                request_rate=[point(10, 2.0)],
            )
        ]
    )

    selectors = report["selectors"]
    assert report["status"] == "VALID"
    assert selectors["max_cpu_usage_pod"]["status"] == "VALID"
    assert selectors["max_cpu_limit_ratio_pod"]["status"] == "UNKNOWN"
    assert selectors["max_cpu_cost_rate_pod"]["status"] == "VALID"


def test_missing_request_telemetry_only_makes_cost_selector_unknown():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 0.5)],
                request_rate=None,
            )
        ]
    )

    selectors = report["selectors"]
    assert report["status"] == "VALID"
    assert selectors["max_cpu_usage_pod"]["status"] == "VALID"
    assert selectors["max_cpu_limit_ratio_pod"]["status"] == "VALID"
    assert selectors["max_cpu_cost_rate_pod"]["status"] == "UNKNOWN"


def test_missing_cpu_telemetry_is_unknown_and_never_low():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[],
                cpu_long=[],
                cpu_limit=[point(10, 0.5)],
                request_rate=[point(10, 2.0)],
            )
        ]
    )

    assert report["status"] == "UNKNOWN"
    assert report["unknown_reasons"]
    assert "risk" not in report
    assert "LOW" not in repr(report)


def test_short_and_long_windows_remain_labeled_separately():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.7)],
                cpu_long=[point(10, 0.5)],
                cpu_limit=[point(10, 1.0)],
                request_rate=[point(10, 2.0)],
            )
        ]
    )

    evidence = report["pods"]["pod-a"]["cpu_usage"]
    assert report["windows"] == {"short": "2m", "long": "5m"}
    assert evidence["short"]["window"] == "2m"
    assert evidence["long"]["window"] == "5m"
    assert evidence["short"]["max"] == 0.7
    assert evidence["long"]["max"] == 0.5
    assert report["selectors"]["max_cpu_usage_pod"]["window"] == "2m"


def test_limit_ratio_requires_timestamp_alignment():
    report = build(
        [
            pod(
                "misaligned",
                cpu_short=[point(10, 0.9)],
                cpu_limit=[point(20, 0.2)],
                request_rate=[point(10, 2.0)],
            ),
            pod(
                "aligned",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 0.5)],
                request_rate=[point(10, 2.0)],
            ),
        ]
    )

    selector = report["selectors"]["max_cpu_limit_ratio_pod"]
    assert selector["status"] == "UNKNOWN"
    assert "timestamp" in selector["reason"].lower()


def test_per_pod_evidence_is_not_replaced_by_replica_sum():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.6)],
                cpu_limit=[point(10, 1.0)],
                request_rate=[point(10, 2.0)],
            ),
            pod(
                "pod-b",
                cpu_short=[point(10, 0.6)],
                cpu_limit=[point(10, 1.0)],
                request_rate=[point(10, 2.0)],
            ),
        ]
    )

    assert set(report["pods"]) == {"pod-a", "pod-b"}
    assert report["selectors"]["max_cpu_usage_pod"]["value"] == 0.6
    assert report["selectors"]["max_cpu_usage_pod"]["value"] != 1.2


def test_partial_coverage_is_reported_without_an_80_percent_cutoff():
    report = build(
        [
            pod(
                "young-pod",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 1.0)],
                request_rate=[point(10, 2.0)],
                sample_count=4,
                coverage=0.4,
            )
        ]
    )

    pod_report = report["pods"]["young-pod"]
    selector = report["selectors"]["max_cpu_usage_pod"]
    assert pod_report["coverage"] == 0.4
    assert pod_report["sample_count"] == 4
    assert selector["status"] == "VALID"
    assert selector["coverage"] == 0.4


def test_zero_request_denominator_only_makes_cost_selector_unknown():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 1.0)],
                request_rate=[point(10, 0.0)],
            )
        ]
    )

    selectors = report["selectors"]
    assert report["status"] == "VALID"
    assert selectors["max_cpu_usage_pod"]["status"] == "VALID"
    assert selectors["max_cpu_limit_ratio_pod"]["status"] == "VALID"
    assert selectors["max_cpu_cost_rate_pod"]["status"] == "UNKNOWN"


def test_live_context_is_separate_from_historical_evidence():
    live = {"observed_at": "2026-10-14T17:00:00Z", "replicas": 5}
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 1.0)],
                request_rate=[point(10, 2.0)],
            )
        ],
        live_context=live,
    )

    assert report["live_context"] == live
    assert "replicas" not in report["pods"]["pod-a"]
    assert "replicas" not in report["selectors"]["max_cpu_usage_pod"]


def test_restart_is_reported_without_automatically_invalidating_cpu_evidence():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 1.0)],
                request_rate=[point(10, 2.0)],
                restart_delta=1,
            )
        ]
    )

    assert report["status"] == "VALID"
    assert report["pods"]["pod-a"]["restart_delta"] == 1
    assert report["selectors"]["max_cpu_usage_pod"]["status"] == "VALID"
