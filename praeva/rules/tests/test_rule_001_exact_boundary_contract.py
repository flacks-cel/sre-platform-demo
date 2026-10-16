import pytest

from praeva.rules import cpu_limit_ceiling
from praeva.verify.cpu_evidence import build_report


def report_for(cpu: str, limit: str = "1") -> dict:
    return build_report(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [
                    {"timestamp": "10", "value": cpu, "query_key": "cpu_short"}
                ],
                "cpu_long": [
                    {"timestamp": "10", "value": cpu, "query_key": "cpu_long"}
                ],
                "cpu_limit": [
                    {"timestamp": "10", "value": limit, "query_key": "cpu_limit"}
                ],
                "request_rate": None,
                "sample_count": 1,
                "coverage": {"observed_points": 1, "expected_points": 1},
                "restart_delta": 0,
                "node": None,
                "owner": None,
            }
        ],
        short_window="2m",
        long_window="5m",
    )


def test_rule_exact_decimal_boundary_triad():
    equal = cpu_limit_ceiling.evaluate_rule(
        report=report_for("0.8"),
        ceiling_ratio="0.8",
    )
    above = cpu_limit_ceiling.evaluate_rule(
        report=report_for("0.8000000000000000001"),
        ceiling_ratio="0.8",
    )
    below = cpu_limit_ceiling.evaluate_rule(
        report=report_for("0.7999999999999999999"),
        ceiling_ratio="0.8",
    )

    assert equal["conclusion"] == "WITHIN_CEILING"
    assert above["conclusion"] == "EXCEEDS_CEILING"
    assert below["conclusion"] == "WITHIN_CEILING"


def test_rule_accepts_exact_text_and_rejects_float_policy_input():
    result = cpu_limit_ceiling.evaluate_rule(
        report=report_for("0.4"),
        ceiling_ratio="0.8",
    )
    assert result["ceiling_ratio"] == "0.8"

    with pytest.raises(cpu_limit_ceiling.RuleInputError):
        cpu_limit_ceiling.evaluate_rule(
            report=report_for("0.4"),
            ceiling_ratio=0.8,
        )


def test_rule_non_terminating_ratio_needs_no_decimal_division():
    result = cpu_limit_ceiling.evaluate_rule(
        report=report_for("1", limit="3"),
        ceiling_ratio="0.3333333333333333333",
    )

    assert result["conclusion"] == "EXCEEDS_CEILING"
    assert result["witness"]["ratio"] == {
        "numerator": "1",
        "denominator": "3",
    }
