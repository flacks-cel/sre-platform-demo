import copy
import importlib

import pytest

HAZARD_ID = "cpu_limit_insufficiency"
MARGIN = {"numerator": 11, "denominator": 10}


def _valid_cpu(value: str, *, window: str) -> dict:
    return {
        "status": "VALID",
        "value_millicores": value,
        "timestamp": "30",
        "query_key": f"cpu_{window}",
        "rate_window": "2m" if window == "short" else "5m",
    }


def _unknown_cpu(*, window: str) -> dict:
    return {
        "status": "UNKNOWN",
        "reason_code": "missing_cpu",
        "reason": "CPU evidence is missing",
        "rate_window": "2m" if window == "short" else "5m",
    }


def _throttling(
    *,
    window: str,
    positive: bool = False,
    complete: bool = True,
    acquired: bool = True,
) -> dict:
    rate_window = "2m" if window == "short" else "5m"
    if not acquired:
        return {
            "status": "UNKNOWN",
            "reason_code": "throttling_not_acquired",
            "reason": "CFS throttling evidence was not acquired",
            "rate_window": rate_window,
        }

    observed = 3 if complete else 2
    return {
        "status": "VALID",
        "any_positive": positive,
        "max_rate": "0.01" if positive else "0",
        "max_timestamp": "30",
        "query_key": f"cfs_throttled_{window}",
        "points": observed,
        "coverage": {"observed_points": observed, "expected_points": 3},
        "coverage_complete": complete,
        "rate_window": rate_window,
    }


def _pod(
    *,
    short: str = "400",
    long: str = "350",
    short_valid: bool = True,
    long_valid: bool = True,
    throttle_short: dict | None = None,
    throttle_long: dict | None = None,
    relation: str = "MATCH",
) -> dict:
    short_cpu = _valid_cpu(short, window="short") if short_valid else _unknown_cpu(window="short")
    long_cpu = _valid_cpu(long, window="long") if long_valid else _unknown_cpu(window="long")
    if throttle_short is None:
        throttle_short = _throttling(window="short")
    if throttle_long is None:
        throttle_long = _throttling(window="long")

    if relation == "UNKNOWN":
        relation_fact = {
            "status": "UNKNOWN",
            "reason_code": "missing_limit",
            "reason": "historical CPU limit is missing",
        }
    else:
        relation_fact = {
            "status": "VALID",
            "relation": relation,
            "current_declared_cpu_limit_millicores": "500",
            "effective_observed_cpu_limit_millicores": "500",
        }

    return {
        "metadata": {
            "coverage": {"observed_points": 3, "expected_points": 3},
            "sample_count": 3,
            "restart_delta": 0,
            "node": "worker-1",
            "owner": "rs-a",
        },
        "windows": {
            "short": {
                "observed_cpu": short_cpu,
                "comparison": {"status": "VALID"},
                "cfs_throttling": throttle_short,
            },
            "long": {
                "observed_cpu": long_cpu,
                "comparison": {"status": "VALID"},
                "cfs_throttling": throttle_long,
            },
        },
        "effective_limit_witness": {"status": "VALID"},
        "current_declared_effective_relation": relation_fact,
    }


def _joined(
    *,
    proposed: int | str = 440,
    current: int | str = 500,
    direction: str = "DECREASE",
    pods: dict | None = None,
) -> dict:
    if pods is None:
        pods = {"pod-a": _pod()}
    return {
        "join_id": "CHANGE-JOIN-001",
        "identity_assertion": {
            "status": "CALLER_ASSERTED",
            "workload_to_pod_selector_relation": "UNVERIFIED",
            "change_workload": {
                "group": "apps",
                "kind": "Deployment",
                "namespace": "app",
                "name": "jobs-api",
            },
            "verify_scope": {
                "namespace": "app",
                "pod_selector": {"type": "regex", "value": "jobs-api-.*"},
                "container": "jobs-api",
            },
        },
        "change_facts": {
            "current_declared_cpu_limit": current,
            "proposed_declared_cpu_limit": proposed,
            "direction": direction,
            "change_ratio": "UNDEFINED",
        },
        "historical_context": {
            "start": "0",
            "end": "30",
            "step": "15",
            "windows": {"short": "2m", "long": "5m"},
            "application_version_relation": "UNVERIFIED",
        },
        "queries": {},
        "pods": pods,
    }


def _evaluate(joined: dict, *, margin: dict = MARGIN) -> dict:
    module = importlib.import_module("praeva.risk.cpu_limit_insufficiency")
    return module.evaluate_cpu_limit_insufficiency(joined=joined, margin=margin)


def _assert_input_error(joined: dict, *, margin: dict) -> None:
    module = importlib.import_module("praeva.risk.cpu_limit_insufficiency")
    with pytest.raises(module.ChangeRiskInputError):
        module.evaluate_cpu_limit_insufficiency(joined=joined, margin=margin)


def _reason_codes(result: dict) -> set[str]:
    return {item["code"] for item in result["unknown_reasons"]}


def test_long_contradiction_is_critical_even_with_unknown_other_evidence() -> None:
    pod = _pod(
        long="500",
        short_valid=False,
        throttle_short=_throttling(window="short", acquired=False),
        throttle_long=_throttling(window="long", acquired=False),
    )
    result = _evaluate(_joined(proposed=450, pods={"pod-a": pod}))

    assert result["hazard_id"] == HAZARD_ID
    assert result["classification_status"] == "CLASSIFIED"
    assert result["risk_level"] == "CRITICAL"
    assert result["classification_basis"] == "sustained_window_contradiction"


def test_short_only_contradiction_is_high_when_long_is_complete() -> None:
    pod = _pod(
        short="400",
        long="300",
        throttle_short=_throttling(window="short", acquired=False),
        throttle_long=_throttling(window="long", acquired=False),
    )
    result = _evaluate(_joined(proposed=350, pods={"pod-a": pod}))

    assert result["classification_status"] == "CLASSIFIED"
    assert result["risk_level"] == "HIGH"
    assert result["classification_basis"] == "short_window_only_contradiction"


def test_short_contradiction_with_unknown_long_is_unknown_not_high() -> None:
    pod = _pod(short="400", long_valid=False)
    result = _evaluate(_joined(proposed=350, pods={"pod-a": pod}))

    assert result["classification_status"] == "UNKNOWN"
    assert "risk_level" not in result
    assert "long_window_cpu_incomplete" in _reason_codes(result)


def test_noncontradiction_with_incomplete_cpu_is_unknown() -> None:
    pod = _pod(short_valid=False, long="350")
    result = _evaluate(_joined(proposed=500, pods={"pod-a": pod}))

    assert result["classification_status"] == "UNKNOWN"
    assert "cpu_evidence_incomplete" in _reason_codes(result)


def test_noncontradiction_with_positive_throttling_is_censored_unknown() -> None:
    pod = _pod(throttle_short=_throttling(window="short", positive=True))
    result = _evaluate(_joined(proposed=500, pods={"pod-a": pod}))

    assert result["classification_status"] == "UNKNOWN"
    assert "censored_evidence" in _reason_codes(result)
    assert "risk_level" not in result


def test_noncontradiction_with_unacquired_throttling_is_unknown() -> None:
    pod = _pod(throttle_long=_throttling(window="long", acquired=False))
    result = _evaluate(_joined(proposed=500, pods={"pod-a": pod}))

    assert result["classification_status"] == "UNKNOWN"
    assert "uncensored_evidence_unproven" in _reason_codes(result)


def test_partial_zero_throttling_changes_low_to_unknown_not_medium() -> None:
    complete = _evaluate(_joined(proposed=500))
    partial_pod = _pod(throttle_short=_throttling(window="short", complete=False))
    partial = _evaluate(_joined(proposed=500, pods={"pod-a": partial_pod}))

    assert complete["risk_level"] == "LOW"
    assert partial["classification_status"] == "UNKNOWN"
    assert "risk_level" not in partial
    assert "uncensored_evidence_unproven" in _reason_codes(partial)


def test_medium_uses_exact_margin_boundary() -> None:
    result = _evaluate(_joined(proposed=430))

    assert result["classification_status"] == "CLASSIFIED"
    assert result["risk_level"] == "MEDIUM"
    assert result["classification_basis"] == "headroom_below_margin"


def test_low_includes_exact_margin_equality() -> None:
    result = _evaluate(_joined(proposed=440))

    assert result["classification_status"] == "CLASSIFIED"
    assert result["risk_level"] == "LOW"
    assert result["classification_basis"] == "headroom_at_or_above_margin"


def test_long_greater_than_short_is_evaluated_independently() -> None:
    pod = _pod(short="400", long="500")
    result = _evaluate(_joined(proposed=450, pods={"pod-a": pod}))

    assert result["risk_level"] == "CRITICAL"


def test_increase_remains_applicable_and_can_be_critical() -> None:
    pod = _pod(short="500", long="500")
    result = _evaluate(
        _joined(current=100, proposed=200, direction="INCREASE", pods={"pod-a": pod})
    )

    assert result["applicability"] == "APPLICABLE"
    assert result["risk_level"] == "CRITICAL"


def test_known_declared_effective_divergence_blocks_classification() -> None:
    pod = _pod(long="500", relation="DIFFERS")
    result = _evaluate(_joined(proposed=200, pods={"pod-a": pod}))

    assert result["classification_status"] == "UNKNOWN"
    assert "declared_effective_divergence" in _reason_codes(result)
    assert "risk_level" not in result


def test_limit_added_with_effective_present_is_unknown_divergence() -> None:
    pod = _pod(relation="DECLARED_ABSENT_EFFECTIVE_PRESENT")
    joined = _joined(
        current="ABSENT",
        proposed=500,
        direction="LIMIT_ADDED",
        pods={"pod-a": pod},
    )
    result = _evaluate(joined)

    assert result["applicability"] == "APPLICABLE"
    assert result["classification_status"] == "UNKNOWN"
    assert "declared_effective_divergence" in _reason_codes(result)


def test_limit_removed_is_not_applicable() -> None:
    result = _evaluate(_joined(proposed="ABSENT", direction="LIMIT_REMOVED"))

    assert result["applicability"] == "NOT_APPLICABLE"
    assert result["not_applicable_reason"]["code"] == "limit_removed"
    assert "classification_status" not in result
    assert "risk_level" not in result


def test_unchanged_is_not_applicable() -> None:
    result = _evaluate(_joined(proposed=500, direction="UNCHANGED"))

    assert result["applicability"] == "NOT_APPLICABLE"
    assert result["not_applicable_reason"]["code"] == "limit_unchanged"
    assert "classification_status" not in result


def test_zero_proposed_limit_is_semantic_unknown() -> None:
    result = _evaluate(_joined(proposed=0))

    assert result["classification_status"] == "UNKNOWN"
    assert "non_positive_proposed_limit" in _reason_codes(result)
    assert "risk_level" not in result


def test_no_pods_is_semantic_unknown() -> None:
    result = _evaluate(_joined(proposed=500, pods={}))

    assert result["classification_status"] == "UNKNOWN"
    assert "no_pod_evidence" in _reason_codes(result)


def test_margin_equal_to_one_is_input_error_not_unknown() -> None:
    _assert_input_error(_joined(), margin={"numerator": 1, "denominator": 1})


def test_margin_float_is_input_error_not_binary_float_policy() -> None:
    _assert_input_error(_joined(), margin={"numerator": 1.1, "denominator": 1})


def test_caller_asserted_provenance_is_preserved_and_does_not_block_low() -> None:
    result = _evaluate(_joined(proposed=500))

    assert result["risk_level"] == "LOW"
    assert result["provenance"] == {
        "identity_assertion": "CALLER_ASSERTED",
        "workload_to_pod_selector_relation": "UNVERIFIED",
        "application_version_relation": "UNVERIFIED",
    }


def test_classified_result_passes_shared_vocabulary_and_cites_evidence() -> None:
    from praeva.risk.vocabulary import validate_risk_result

    result = _evaluate(_joined(proposed=430))
    validate_risk_result(result)

    assert "change_facts.proposed_declared_cpu_limit" in result["evidence_refs"]
    assert any(ref.startswith("pods.pod-a.windows") for ref in result["evidence_refs"])


def test_unknown_never_contains_risk_level_and_has_named_reason() -> None:
    pod = _pod(throttle_short=_throttling(window="short", positive=True))
    result = _evaluate(_joined(proposed=500, pods={"pod-a": pod}))

    assert result["classification_status"] == "UNKNOWN"
    assert "risk_level" not in result
    reason = result["unknown_reasons"][0]
    assert reason["code"]
    assert reason["precondition"]


def test_output_has_no_score_probability_recommendation_target_or_worst_pod() -> None:
    result = _evaluate(_joined(proposed=430))
    serialized = repr(result).lower()

    for forbidden in (
        "score",
        "probability",
        "recommendation",
        "target_cpu",
        "worst_pod",
    ):
        assert forbidden not in serialized


def test_unknown_relation_does_not_invent_declared_effective_divergence() -> None:
    pod = _pod(relation="UNKNOWN")
    result = _evaluate(_joined(proposed=500, pods={"pod-a": pod}))

    assert result["classification_status"] == "CLASSIFIED"
    assert result["risk_level"] == "LOW"
    assert "declared_effective_divergence" not in repr(result)


def test_high_is_unchanged_when_throttling_quality_changes() -> None:
    complete_pod = _pod(short="400", long="300")
    missing_pod = copy.deepcopy(complete_pod)
    missing_pod["windows"]["short"]["cfs_throttling"] = _throttling(
        window="short",
        acquired=False,
    )
    missing_pod["windows"]["long"]["cfs_throttling"] = _throttling(
        window="long",
        acquired=False,
    )

    complete = _evaluate(_joined(proposed=350, pods={"pod-a": complete_pod}))
    missing = _evaluate(_joined(proposed=350, pods={"pod-a": missing_pod}))

    assert complete["risk_level"] == "HIGH"
    assert missing["risk_level"] == "HIGH"
