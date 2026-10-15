from praeva.verify.cpu_evidence import build_report


def point(timestamp: int, value: float) -> dict[str, float | int]:
    return {"timestamp": timestamp, "value": value}


def pod(
    name: str,
    *,
    cpu_short: list[dict[str, float | int]],
    cpu_limit: list[dict[str, float | int]] | None,
) -> dict:
    return {
        "name": name,
        "cpu_short": cpu_short,
        "cpu_long": cpu_short,
        "cpu_limit": cpu_limit,
        "request_rate": None,
        "sample_count": len(cpu_short),
        "coverage": 1.0,
        "restart_delta": 0,
        "node": "worker-1",
        "owner": "rs-a",
    }


def build(pods: list[dict]) -> dict:
    return build_report(pods=pods, short_window="2m", long_window="5m")


def test_per_pod_limit_ratio_valid_reports_max_timestamp_window_and_points():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.2), point(20, 0.6), point(30, 0.4)],
                cpu_limit=[point(10, 1.0), point(20, 0.5), point(30, 1.0)],
            )
        ]
    )

    ratio = report["pods"]["pod-a"]["cpu_limit_ratio"]
    assert ratio == {
        "status": "VALID",
        "window": "2m",
        "max": 1.2,
        "max_timestamp": 20,
        "points": 3,
    }


def test_missing_limit_is_structured_per_pod_without_hiding_valid_peer():
    report = build(
        [
            pod(
                "complete",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 1.0)],
            ),
            pod(
                "churned",
                cpu_short=[point(10, 0.7)],
                cpu_limit=None,
            ),
        ]
    )

    complete = report["pods"]["complete"]["cpu_limit_ratio"]
    churned = report["pods"]["churned"]["cpu_limit_ratio"]

    assert complete["status"] == "VALID"
    assert churned["status"] == "UNKNOWN"
    assert churned["reason_code"] == "missing_limit"
    assert "limit" in churned["reason"].lower()


def test_timestamp_misalignment_has_structured_reason_code():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.4), point(20, 0.5)],
                cpu_limit=[point(10, 1.0), point(30, 1.0)],
            )
        ]
    )

    ratio = report["pods"]["pod-a"]["cpu_limit_ratio"]
    assert ratio["status"] == "UNKNOWN"
    assert ratio["reason_code"] == "timestamp_misalignment"


def test_non_positive_limit_has_structured_reason_code():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 0.0)],
            )
        ]
    )

    ratio = report["pods"]["pod-a"]["cpu_limit_ratio"]
    assert ratio["status"] == "UNKNOWN"
    assert ratio["reason_code"] == "non_positive_limit"


def test_duplicate_timestamp_has_structured_reason_code():
    report = build(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.4), point(10, 0.5)],
                cpu_limit=[point(10, 1.0)],
            )
        ]
    )

    ratio = report["pods"]["pod-a"]["cpu_limit_ratio"]
    assert ratio["status"] == "UNKNOWN"
    assert ratio["reason_code"] == "duplicate_timestamp"


def test_per_pod_visibility_does_not_change_existing_aggregate_selector_semantics():
    report = build(
        [
            pod(
                "complete",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 1.0)],
            ),
            pod(
                "churned",
                cpu_short=[point(10, 0.8)],
                cpu_limit=None,
            ),
        ]
    )

    assert report["pods"]["complete"]["cpu_limit_ratio"]["status"] == "VALID"
    assert report["pods"]["churned"]["cpu_limit_ratio"]["status"] == "UNKNOWN"
    assert report["selectors"]["max_cpu_limit_ratio_pod"]["status"] == "UNKNOWN"
