from __future__ import annotations

from collections.abc import Callable
from typing import Any

from praeva.change.cpu_limit import analyze_change
from praeva.change.join import join_change_evidence
from praeva.risk.cpu_limit_insufficiency import evaluate_cpu_limit_insufficiency
from praeva.verify.cpu_evidence import build_report
from praeva.verify.prometheus_adapter import QueryRange, collect_normalized_evidence

SCHEMA_VERSION = "PRAEVA-ANALYZE-001"
CALLER_ASSERTED = "CALLER_ASSERTED"

RuleEvaluator = Callable[[dict[str, Any], dict[str, str]], dict[str, Any]]


class AnalyzeInputError(ValueError):
    """Raised when PRAEVA-ANALYZE-001 receives invalid orchestration input."""


def _parse_margin_text(value: Any) -> dict[str, int]:
    if not isinstance(value, str) or not value:
        raise AnalyzeInputError("margin must be provided as numerator/denominator")
    if value.count("/") != 1:
        raise AnalyzeInputError("margin must use numerator/denominator syntax")

    numerator_text, denominator_text = value.split("/", 1)
    try:
        numerator = int(numerator_text)
        denominator = int(denominator_text)
    except ValueError as exc:
        raise AnalyzeInputError("margin numerator and denominator must be integers") from exc

    return {"numerator": numerator, "denominator": denominator}


def _evaluate_change_risk_001(
    joined: dict[str, Any],
    rule_params: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(rule_params, dict):
        raise AnalyzeInputError("rule_params must be an object")
    if set(rule_params) != {"margin"}:
        if "margin" not in rule_params:
            raise AnalyzeInputError("CHANGE-RISK-001 requires rule parameter margin")
        unknown = sorted(set(rule_params) - {"margin"})
        raise AnalyzeInputError(
            "CHANGE-RISK-001 received unknown rule parameters: " + ", ".join(unknown)
        )

    return evaluate_cpu_limit_insufficiency(
        joined=joined,
        margin=_parse_margin_text(rule_params["margin"]),
    )


_RULES: dict[str, RuleEvaluator] = {
    "CHANGE-RISK-001": _evaluate_change_risk_001,
}


def _select_rule(rule_id: str) -> RuleEvaluator:
    if not isinstance(rule_id, str) or not rule_id:
        raise AnalyzeInputError("rule_id is required")
    try:
        return _RULES[rule_id]
    except KeyError as exc:
        raise AnalyzeInputError(f"unknown rule: {rule_id}") from exc


def analyze(
    *,
    current_manifest: str,
    proposed_manifest: str,
    api_group: str,
    kind: str,
    namespace: str,
    name: str,
    container: str,
    container_space: str,
    pod_regex: str,
    prometheus_url: str,
    start: Any,
    end: Any,
    step: Any,
    short_window: str,
    long_window: str,
    rule_id: str,
    rule_params: dict[str, str],
    query_range: QueryRange | None,
) -> dict[str, Any]:
    """Run Change Input -> Verify -> Change Join -> selected risk rule."""

    rule = _select_rule(rule_id)

    change = analyze_change(
        current_manifest=current_manifest,
        proposed_manifest=proposed_manifest,
        api_group=api_group,
        kind=kind,
        namespace=namespace,
        name=name,
        container=container,
        container_space=container_space,
    )

    normalized = collect_normalized_evidence(
        prometheus_url=prometheus_url,
        namespace=namespace,
        pod_regex=pod_regex,
        container=container,
        start=start,
        end=end,
        step=step,
        short_window=short_window,
        long_window=long_window,
        include_throttling=True,
        query_range=query_range,
    )

    verify_report = build_report(
        pods=normalized["pods"],
        short_window=normalized["short_window"],
        long_window=normalized["long_window"],
        acquisition=normalized["acquisition"],
        queries=normalized["queries"],
    )

    joined = join_change_evidence(
        change=change,
        verify_report=verify_report,
        identity_assertion=CALLER_ASSERTED,
    )
    risk = rule(joined, rule_params)

    return {
        "schema_version": SCHEMA_VERSION,
        "result": risk,
        "unknown_reasons": risk.get("unknown_reasons", []),
        "evidence_refs": risk.get("evidence_refs", []),
        "layers": {
            "change_input": change,
            "verify": verify_report,
            "change_join": joined,
            "risk": risk,
        },
    }
