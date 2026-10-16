import pytest


ABSENT = "ABSENT"


def change_facts(*, current=200, proposed=150, container_space="containers") -> dict:
    if current == ABSENT or proposed == ABSENT or current == 0 or proposed == 0:
        ratio = "UNDEFINED"
    else:
        from fractions import Fraction

        reduced = Fraction(proposed, current)
        ratio = {"numerator": reduced.numerator, "denominator": reduced.denominator}

    if current == ABSENT and proposed != ABSENT:
        direction = "LIMIT_ADDED"
    elif current != ABSENT and proposed == ABSENT:
        direction = "LIMIT_REMOVED"
    elif current == ABSENT and proposed == ABSENT:
        direction = "UNCHANGED"
    elif proposed < current:
        direction = "DECREASE"
    elif proposed > current:
        direction = "INCREASE"
    else:
        direction = "UNCHANGED"

    return {
        "workload_identity": {
            "group": "apps",
            "kind": "Deployment",
            "namespace": "app",
            "name": "jobs-api",
        },
        "container": {"name": "jobs-api", "space": container_space},
        "current_declared_cpu_limit": current,
        "proposed_declared_cpu_limit": proposed,
        "direction": direction,
        "change_ratio": ratio,
        "current_declared_cpu_request": 100,
        "proposed_declared_cpu_request": 100,
    }


def valid_summary(value: str, *, timestamp: str, query_key: str, window: str) -> dict:
    return {
        "status": "VALID",
        "window": window,
        "max": value,
        "max_timestamp": timestamp,
        "query_key": query_key,
        "points": 3,
        "min": value,
    }


def valid_ratio(*, cpu: str, limit: str, timestamp: str = "30") -> dict:
    return {
        "status": "VALID",
        "window": "2m",
        "max": {"numerator": cpu, "denominator": limit},
        "max_timestamp": timestamp,
        "query_keys": {"numerator": "cpu_short", "denominator": "cpu_limit"},
        "points": 3,
    }


def pod_report(
    *,
    short="0.1491020848282956",
    long="0.1400000000000001",
    effective_limit="0.2",
) -> dict:
    return {
        "sample_count": 3,
        "coverage": {"observed_points": 3, "expected_points": 3},
        "restart_delta": 0,
        "node": "worker-1",
        "owner": "rs-a",
        "cpu_usage": {
            "short": valid_summary(
                short,
                timestamp="30",
                query_key="cpu_short",
                window="2m",
            ),
            "long": valid_summary(
                long,
                timestamp="30",
                query_key="cpu_long",
                window="5m",
            ),
        },
        "cpu_limit_ratio": valid_ratio(cpu=short, limit=effective_limit),
    }


def verify_report(*, pods=None, status="VALID") -> dict:
    if pods is None:
        pods = {"pod-a": pod_report()}
    return {
        "status": status,
        "windows": {"short": "2m", "long": "5m"},
        "acquisition": {
            "namespace": "app",
            "pod_selector": {"type": "regex", "value": "jobs-api-.*"},
            "container": "jobs-api",
            "start": "0",
            "end": "30",
            "step": "15",
        },
        "queries": {
            "cpu_short": {"promql": "short-query", "rate_window": "2m"},
            "cpu_long": {"promql": "long-query", "rate_window": "5m"},
            "cpu_limit": {"promql": "limit-query", "rate_window": None},
        },
        "pods": pods,
        "selectors": {
            "max_cpu_usage_pod": {"status": "VALID", "pod": "pod-a"},
            "max_cpu_limit_ratio_pod": {"status": "VALID", "pod": "pod-a"},
            "max_cpu_cost_rate_pod": {"status": "UNKNOWN"},
        },
        "unknown_reasons": [],
    }


def join(change=None, report=None, assertion="CALLER_ASSERTED"):
    from praeva.change.join import join_change_evidence

    return join_change_evidence(
        change=change or change_facts(),
        verify_report=report or verify_report(),
        identity_assertion=assertion,
    )


def assert_join_input_error(**kwargs):
    with pytest.raises(Exception) as exc_info:
        join(**kwargs)
    assert exc_info.value.__class__.__name__ == "ChangeJoinInputError"


def contains_float(value) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(contains_float(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_float(item) for item in value)
    return False


def test_identity_assertion_is_required_and_explicit_in_output():
    result = join()

    assertion = result["identity_assertion"]
    assert assertion["status"] == "CALLER_ASSERTED"
    assert assertion["workload_to_pod_selector_relation"] == "UNVERIFIED"
    assert assertion["change_workload"]["name"] == "jobs-api"
    assert assertion["verify_scope"]["pod_selector"] == {
        "type": "regex",
        "value": "jobs-api-.*",
    }

    assert_join_input_error(assertion="")
    assert_join_input_error(assertion="VERIFIED")


def test_namespace_mismatch_is_input_error():
    report = verify_report()
    report["acquisition"]["namespace"] = "other"

    assert_join_input_error(report=report)


def test_container_mismatch_is_input_error():
    report = verify_report()
    report["acquisition"]["container"] = "sidecar"

    assert_join_input_error(report=report)


def test_non_standard_container_space_is_out_of_scope():
    assert_join_input_error(change=change_facts(container_space="initContainers"))


def test_short_and_long_are_parallel_per_pod():
    result = join()

    windows = result["pods"]["pod-a"]["windows"]
    assert windows["short"]["observed_cpu"]["rate_window"] == "2m"
    assert windows["short"]["observed_cpu"]["query_key"] == "cpu_short"
    assert windows["long"]["observed_cpu"]["rate_window"] == "5m"
    assert windows["long"]["observed_cpu"]["query_key"] == "cpu_long"


def test_cores_to_millicores_and_delta_are_exact_decimal_text():
    result = join(change=change_facts(current=200, proposed=150))

    short = result["pods"]["pod-a"]["windows"]["short"]
    assert short["observed_cpu"]["value_millicores"] == "149.1020848282956"
    assert short["comparison"] == {
        "status": "VALID",
        "proposed_declared_cpu_limit_millicores": "150",
        "delta_millicores": "0.8979151717044",
    }


def test_join_output_contains_no_float_recursively():
    result = join()

    assert not contains_float(result)


def test_proposed_absent_is_undefined_not_unknown():
    result = join(change=change_facts(current=200, proposed=ABSENT))

    comparison = result["pods"]["pod-a"]["windows"]["short"]["comparison"]
    assert comparison == {
        "status": "UNDEFINED",
        "proposed_declared_cpu_limit_millicores": "ABSENT",
        "reason_code": "proposed_limit_absent",
        "reason": "proposed manifest does not declare a CPU limit",
    }


def test_unknown_short_window_does_not_poison_valid_long_window():
    pod = pod_report()
    pod["cpu_usage"]["short"] = {
        "status": "UNKNOWN",
        "window": "2m",
        "reason_code": "non_finite_sample",
        "reason": "series contains a non-finite sample",
    }
    report = verify_report(pods={"pod-a": pod}, status="UNKNOWN")

    result = join(report=report)
    windows = result["pods"]["pod-a"]["windows"]

    assert windows["short"]["observed_cpu"]["status"] == "UNKNOWN"
    assert windows["short"]["comparison"]["status"] == "UNKNOWN"
    assert windows["long"]["observed_cpu"]["status"] == "VALID"
    assert windows["long"]["comparison"]["status"] == "VALID"


def test_top_level_verify_unknown_does_not_poison_valid_dependencies():
    result = join(report=verify_report(status="UNKNOWN"))

    assert result["pods"]["pod-a"]["windows"]["short"]["comparison"]["status"] == "VALID"
    assert result["pods"]["pod-a"]["windows"]["long"]["comparison"]["status"] == "VALID"


def test_effective_limit_relation_remains_per_pod():
    pods = {
        "pod-a": pod_report(effective_limit="0.2"),
        "pod-b": pod_report(effective_limit="0.25"),
    }
    result = join(change=change_facts(current=200, proposed=150), report=verify_report(pods=pods))

    relation_a = result["pods"]["pod-a"]["current_declared_effective_relation"]
    relation_b = result["pods"]["pod-b"]["current_declared_effective_relation"]
    assert relation_a["relation"] == "MATCH"
    assert relation_b["relation"] == "DIFFERS"
    assert "current_declared_effective_relation" not in result


def test_current_declared_absent_with_effective_witness_is_explicit():
    result = join(change=change_facts(current=ABSENT, proposed=150))

    relation = result["pods"]["pod-a"]["current_declared_effective_relation"]
    assert relation["status"] == "VALID"
    assert relation["relation"] == "DECLARED_ABSENT_EFFECTIVE_PRESENT"
    assert relation["current_declared_cpu_limit_millicores"] == "ABSENT"
    assert relation["effective_observed_cpu_limit_millicores"] == "200"


def test_missing_effective_witness_is_unknown_without_erasing_cpu():
    pod = pod_report()
    pod["cpu_limit_ratio"] = {
        "status": "UNKNOWN",
        "window": "2m",
        "reason_code": "missing_limit",
        "reason": "historical CPU limit is missing",
    }
    result = join(report=verify_report(pods={"pod-a": pod}))

    joined = result["pods"]["pod-a"]
    assert joined["effective_limit_witness"]["status"] == "UNKNOWN"
    assert joined["current_declared_effective_relation"]["status"] == "UNKNOWN"
    assert joined["windows"]["short"]["observed_cpu"]["status"] == "VALID"


def test_historical_provenance_is_preserved_without_freshness_policy():
    result = join()

    assert result["historical_context"] == {
        "start": "0",
        "end": "30",
        "step": "15",
        "windows": {"short": "2m", "long": "5m"},
        "application_version_relation": "UNVERIFIED",
    }
    assert result["queries"]["cpu_short"]["promql"] == "short-query"
    assert "fresh" not in repr(result).lower()


def test_selector_divergence_does_not_change_per_pod_join():
    report = verify_report(
        pods={
            "pod-a": pod_report(short="0.1"),
            "pod-b": pod_report(short="0.2"),
        }
    )
    report["selectors"]["max_cpu_usage_pod"]["pod"] = "pod-b"
    report["selectors"]["max_cpu_limit_ratio_pod"]["pod"] = "pod-a"

    result = join(report=report)

    assert set(result["pods"]) == {"pod-a", "pod-b"}
    assert result["pods"]["pod-a"]["windows"]["short"]["observed_cpu"]["value_millicores"] == "100"
    assert result["pods"]["pod-b"]["windows"]["short"]["observed_cpu"]["value_millicores"] == "200"


def test_query_window_mismatch_is_input_error():
    report = verify_report()
    report["queries"]["cpu_short"]["rate_window"] = "5m"

    assert_join_input_error(report=report)


def test_output_has_no_risk_recommendation_target_or_worst_pod():
    result = join()
    serialized = repr(result)

    assert "risk" not in result
    assert "recommendation" not in result
    assert "target_cpu_limit" not in result
    assert "worst_pod" not in serialized
