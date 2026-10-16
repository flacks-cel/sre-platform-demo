import pytest


def _change() -> dict:
    return {
        "workload_identity": {
            "group": "apps",
            "kind": "Deployment",
            "namespace": "app",
            "name": "jobs-api",
        },
        "container": {"name": "jobs-api", "space": "containers"},
        "current_declared_cpu_limit": 200,
        "proposed_declared_cpu_limit": 150,
        "direction": "DECREASE",
        "change_ratio": {"numerator": 3, "denominator": 4},
        "current_declared_cpu_request": 100,
        "proposed_declared_cpu_request": 100,
    }


def _summary(value: str, *, window: str, query_key: str) -> dict:
    return {
        "status": "VALID",
        "window": window,
        "max": value,
        "max_timestamp": "30",
        "query_key": query_key,
        "points": 3,
        "min": value,
    }


def _ratio() -> dict:
    return {
        "status": "VALID",
        "window": "2m",
        "max": {"numerator": "0.149", "denominator": "0.2"},
        "max_timestamp": "30",
        "query_keys": {"numerator": "cpu_short", "denominator": "cpu_limit"},
        "points": 3,
    }


def _pod() -> dict:
    return {
        "sample_count": 3,
        "coverage": {"observed_points": 3, "expected_points": 3},
        "restart_delta": 0,
        "node": "worker-1",
        "owner": "rs-a",
        "cpu_usage": {
            "short": _summary("0.149", window="2m", query_key="cpu_short"),
            "long": _summary("0.140", window="5m", query_key="cpu_long"),
        },
        "cpu_limit_ratio": _ratio(),
    }


def _throttling_valid(
    *,
    window: str,
    query_key: str,
    rate: str = "0",
    positive: bool = False,
    complete: bool = True,
) -> dict:
    observed = 3 if complete else 2
    return {
        "status": "VALID",
        "window": window,
        "any_positive": positive,
        "max_rate": rate,
        "max_timestamp": "30",
        "query_key": query_key,
        "points": observed,
        "coverage": {"observed_points": observed, "expected_points": 3},
        "coverage_complete": complete,
    }


def _report(*, include_throttling: bool = False) -> dict:
    pod = _pod()
    queries = {
        "cpu_short": {"promql": "short-query", "rate_window": "2m"},
        "cpu_long": {"promql": "long-query", "rate_window": "5m"},
        "cpu_limit": {"promql": "limit-query", "rate_window": None},
    }
    if include_throttling:
        queries.update(
            {
                "cfs_throttled_short": {
                    "promql": "throttle-short-query",
                    "rate_window": "2m",
                },
                "cfs_throttled_long": {
                    "promql": "throttle-long-query",
                    "rate_window": "5m",
                },
            }
        )
        pod["cfs_throttling"] = {
            "short": _throttling_valid(
                window="2m",
                query_key="cfs_throttled_short",
            ),
            "long": _throttling_valid(
                window="5m",
                query_key="cfs_throttled_long",
            ),
        }

    return {
        "status": "VALID",
        "windows": {"short": "2m", "long": "5m"},
        "acquisition": {
            "namespace": "app",
            "pod_selector": {"type": "regex", "value": "jobs-api-.*"},
            "container": "jobs-api",
            "start": "0",
            "end": "30",
            "step": "15",
        },
        "queries": queries,
        "pods": {"pod-a": pod},
        "selectors": {},
        "unknown_reasons": [],
    }


def _join(report: dict) -> dict:
    from praeva.change.join import join_change_evidence

    return join_change_evidence(
        change=_change(),
        verify_report=report,
        identity_assertion="CALLER_ASSERTED",
    )


def _assert_input_error(report: dict) -> None:
    with pytest.raises(Exception) as exc_info:
        _join(report)
    assert exc_info.value.__class__.__name__ == "ChangeJoinInputError"


def _contains_float(value) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_float(item) for item in value)
    return False


def test_not_acquired_is_explicit_unknown_without_poisoning_cpu() -> None:
    result = _join(_report())
    windows = result["pods"]["pod-a"]["windows"]

    for name, rate_window in (("short", "2m"), ("long", "5m")):
        throttling = windows[name]["cfs_throttling"]
        assert throttling == {
            "status": "UNKNOWN",
            "reason_code": "throttling_not_acquired",
            "reason": "CFS throttling evidence was not acquired",
            "rate_window": rate_window,
        }
        assert windows[name]["observed_cpu"]["status"] == "VALID"
        assert windows[name]["comparison"]["status"] == "VALID"


def test_complete_zero_throttling_is_preserved() -> None:
    result = _join(_report(include_throttling=True))
    short = result["pods"]["pod-a"]["windows"]["short"]["cfs_throttling"]

    assert short["status"] == "VALID"
    assert short["any_positive"] is False
    assert short["max_rate"] == "0"
    assert short["coverage_complete"] is True
    assert short["rate_window"] == "2m"


def test_positive_throttling_witness_is_preserved_exactly() -> None:
    report = _report(include_throttling=True)
    report["pods"]["pod-a"]["cfs_throttling"]["short"] = _throttling_valid(
        window="2m",
        query_key="cfs_throttled_short",
        rate="0.003333333333333333",
        positive=True,
    )

    short = _join(report)["pods"]["pod-a"]["windows"]["short"]["cfs_throttling"]

    assert short["any_positive"] is True
    assert short["max_rate"] == "0.003333333333333333"
    assert short["max_timestamp"] == "30"
    assert short["query_key"] == "cfs_throttled_short"


def test_partial_valid_throttling_remains_valid_and_incomplete() -> None:
    report = _report(include_throttling=True)
    report["pods"]["pod-a"]["cfs_throttling"]["short"] = _throttling_valid(
        window="2m",
        query_key="cfs_throttled_short",
        complete=False,
    )

    short = _join(report)["pods"]["pod-a"]["windows"]["short"]["cfs_throttling"]

    assert short["status"] == "VALID"
    assert short["any_positive"] is False
    assert short["coverage"] == {"observed_points": 2, "expected_points": 3}
    assert short["coverage_complete"] is False


def test_upstream_unknown_is_preserved_without_poisoning_cpu() -> None:
    report = _report(include_throttling=True)
    report["pods"]["pod-a"]["cfs_throttling"]["short"] = {
        "status": "UNKNOWN",
        "window": "2m",
        "reason_code": "missing_throttling",
        "reason": "CFS throttling series is missing or empty",
        "coverage": {"observed_points": 0, "expected_points": 3},
    }

    result = _join(report)
    short = result["pods"]["pod-a"]["windows"]["short"]

    assert short["cfs_throttling"]["status"] == "UNKNOWN"
    assert short["cfs_throttling"]["reason_code"] == "missing_throttling"
    assert short["observed_cpu"]["status"] == "VALID"
    assert short["comparison"]["status"] == "VALID"


def test_throttling_query_window_mismatch_is_input_error() -> None:
    report = _report(include_throttling=True)
    report["queries"]["cfs_throttled_short"]["rate_window"] = "5m"

    _assert_input_error(report)


def test_valid_throttling_query_key_mismatch_is_input_error() -> None:
    report = _report(include_throttling=True)
    report["pods"]["pod-a"]["cfs_throttling"]["short"]["query_key"] = "wrong"

    _assert_input_error(report)


def test_invalid_throttling_status_is_input_error() -> None:
    report = _report(include_throttling=True)
    report["pods"]["pod-a"]["cfs_throttling"]["short"]["status"] = "PARTIAL"

    _assert_input_error(report)


def test_join_with_throttling_contains_no_float_recursively() -> None:
    result = _join(_report(include_throttling=True))

    assert not _contains_float(result)


def test_throttling_join_adds_no_risk_policy_or_worst_pod() -> None:
    result = _join(_report(include_throttling=True))
    serialized = repr(result)

    assert "risk" not in result
    assert "risk_level" not in result
    assert "recommendation" not in result
    assert "worst_pod" not in serialized
