import importlib

import pytest

from praeva.verify.cpu_evidence import build_report


def point(timestamp: int, value: float) -> dict[str, float | int]:
    return {"timestamp": timestamp, "value": value}


def pod(
    name: str,
    *,
    cpu_short: list[dict[str, float | int]],
    cpu_limit: list[dict[str, float | int]] | None,
    cpu_long: list[dict[str, float | int]] | None = None,
    request_rate: list[dict[str, float | int]] | None = None,
    sample_count: int | None = None,
    coverage: float = 1.0,
    restart_delta: int = 0,
) -> dict:
    return {
        "name": name,
        "cpu_short": cpu_short,
        "cpu_long": cpu_short if cpu_long is None else cpu_long,
        "cpu_limit": cpu_limit,
        "request_rate": request_rate,
        "sample_count": len(cpu_short) if sample_count is None else sample_count,
        "coverage": coverage,
        "restart_delta": restart_delta,
        "node": "worker-1",
        "owner": "rs-a",
    }


def verify(pods: list[dict]) -> dict:
    return build_report(pods=pods, short_window="2m", long_window="5m")


def rule_module():
    return importlib.import_module("praeva.rules.cpu_limit_ceiling")


def evaluate(report: dict, ceiling_ratio):
    return rule_module().evaluate_rule(report=report, ceiling_ratio=ceiling_ratio)


def excluded_by_name(result: dict, name: str) -> dict:
    return next(item for item in result["excluded_pods"] if item["pod"] == name)


def evaluated_by_name(result: dict, name: str) -> dict:
    return next(item for item in result["evaluated_pods"] if item["pod"] == name)


def test_all_complete_and_within_ceiling_returns_within():
    report = verify(
        [
            pod("pod-a", cpu_short=[point(10, 0.4)], cpu_limit=[point(10, 1.0)]),
            pod("pod-b", cpu_short=[point(10, 0.8)], cpu_limit=[point(10, 1.0)]),
        ]
    )

    result = evaluate(report, "0.8")

    assert result["rule_id"] == "RULE-001"
    assert result["ceiling_ratio"] == "0.8"
    assert result["conclusion"] == "WITHIN_CEILING"
    assert result["excluded_pods"] == []
    assert result["witness"] is None
    assert "worst_pod" not in result


def test_complete_exceedance_returns_named_witness():
    report = verify(
        [
            pod("pod-a", cpu_short=[point(10, 0.4)], cpu_limit=[point(10, 1.0)]),
            pod("pod-b", cpu_short=[point(10, 0.9)], cpu_limit=[point(10, 0.5)]),
        ]
    )

    result = evaluate(report, "1.0")

    assert result["conclusion"] == "EXCEEDS_CEILING"
    assert result["witness"] == {
        "pod": "pod-b",
        "ratio": {"numerator": "0.9", "denominator": "0.5"},
        "timestamp": "10",
        "window": "2m",
    }


def test_churned_missing_limit_blocks_within_when_no_exceedance_witness():
    report = verify(
        [
            pod("complete", cpu_short=[point(10, 0.4)], cpu_limit=[point(10, 1.0)]),
            pod("churned", cpu_short=[point(10, 0.7)], cpu_limit=None),
        ]
    )

    result = evaluate(report, "0.8")

    assert result["conclusion"] == "UNKNOWN"
    assert result["reason_code"] == "incomplete_cpu_limit_ratio"
    excluded = excluded_by_name(result, "churned")
    assert excluded["reason_code"] == "missing_limit"
    assert "limit" in excluded["reason"].lower()


def test_complete_exceedance_survives_other_churned_incomplete_pod():
    report = verify(
        [
            pod("witness", cpu_short=[point(10, 0.9)], cpu_limit=[point(10, 0.5)]),
            pod("churned", cpu_short=[point(10, 0.7)], cpu_limit=None),
        ]
    )

    result = evaluate(report, "1.0")

    assert result["conclusion"] == "EXCEEDS_CEILING"
    assert result["witness"]["pod"] == "witness"
    assert excluded_by_name(result, "churned")["reason_code"] == "missing_limit"


def test_selector_divergence_does_not_block_rule():
    report = verify(
        [
            pod("cpu-pod", cpu_short=[point(10, 0.9)], cpu_limit=[point(10, 2.0)]),
            pod("ratio-pod", cpu_short=[point(10, 0.6)], cpu_limit=[point(10, 0.4)]),
        ]
    )
    selectors = report["selectors"]
    assert selectors["max_cpu_usage_pod"]["pod"] == "cpu-pod"
    assert selectors["max_cpu_limit_ratio_pod"]["pod"] == "ratio-pod"

    result = evaluate(report, "2.0")

    assert result["conclusion"] == "WITHIN_CEILING"


def test_unknown_cost_rate_selector_does_not_block_rule():
    report = verify(
        [pod("pod-a", cpu_short=[point(10, 0.4)], cpu_limit=[point(10, 1.0)])]
    )
    assert report["selectors"]["max_cpu_cost_rate_pod"]["status"] == "UNKNOWN"

    result = evaluate(report, "0.8")

    assert result["conclusion"] == "WITHIN_CEILING"
    assert result["selectors"]["max_cpu_cost_rate_pod"]["status"] == "UNKNOWN"


def test_no_complete_cpu_limit_ratio_is_unknown_never_headroom():
    report = verify(
        [
            pod("pod-a", cpu_short=[point(10, 0.4)], cpu_limit=None),
            pod("pod-b", cpu_short=[point(10, 0.6)], cpu_limit=None),
        ]
    )

    result = evaluate(report, "0.8")

    assert result["conclusion"] == "UNKNOWN"
    assert result["reason_code"] == "no_complete_cpu_limit_ratio"
    assert len(result["excluded_pods"]) == 2


def test_timestamp_misalignment_blocks_within_without_exceedance_witness():
    report = verify(
        [
            pod("complete", cpu_short=[point(10, 0.4)], cpu_limit=[point(10, 1.0)]),
            pod(
                "misaligned",
                cpu_short=[point(10, 0.5), point(20, 0.6)],
                cpu_limit=[point(10, 1.0), point(30, 1.0)],
            ),
        ]
    )

    result = evaluate(report, "0.8")

    assert result["conclusion"] == "UNKNOWN"
    assert result["reason_code"] == "incomplete_cpu_limit_ratio"
    assert excluded_by_name(result, "misaligned")["reason_code"] == "timestamp_misalignment"


def test_restart_is_metadata_and_does_not_block_rule():
    report = verify(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 1.0)],
                restart_delta=1,
            )
        ]
    )

    result = evaluate(report, "0.8")

    assert result["conclusion"] == "WITHIN_CEILING"
    assert evaluated_by_name(result, "pod-a")["restart_delta"] == 1


def test_partial_coverage_is_metadata_when_ratio_is_computable():
    report = verify(
        [
            pod(
                "young-pod",
                cpu_short=[point(10, 0.4)],
                cpu_limit=[point(10, 1.0)],
                sample_count=4,
                coverage=0.4,
            )
        ]
    )

    result = evaluate(report, "0.8")

    assert result["conclusion"] == "WITHIN_CEILING"
    evaluated = evaluated_by_name(result, "young-pod")
    assert evaluated["coverage"] == {"observed_points": 4, "expected_points": 10}
    assert evaluated["sample_count"] == 4


def test_invalid_ceiling_ratio_is_input_error_not_unknown():
    module = rule_module()
    invalid_values = [None, True, 0, -1, "0", "-1", "nan", "inf", 0.8]

    for value in invalid_values:
        with pytest.raises(module.RuleInputError):
            module.evaluate_rule(report=verify([]), ceiling_ratio=value)


def test_missing_long_window_does_not_block_when_short_ratio_is_complete():
    report = verify(
        [
            pod(
                "pod-a",
                cpu_short=[point(10, 0.4)],
                cpu_long=[],
                cpu_limit=[point(10, 1.0)],
            )
        ]
    )
    assert report["status"] == "UNKNOWN"
    assert report["pods"]["pod-a"]["cpu_limit_ratio"]["status"] == "VALID"

    result = evaluate(report, "0.8")

    assert result["conclusion"] == "WITHIN_CEILING"
