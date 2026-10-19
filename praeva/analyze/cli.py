from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from praeva.analyze.orchestrator import AnalyzeInputError, analyze
from praeva.change.cpu_limit import ChangeInputError
from praeva.change.join import ChangeJoinInputError
from praeva.risk.cpu_limit_insufficiency import ChangeRiskInputError
from praeva.verify.prometheus_adapter import PrometheusAdapterError, QueryRange


class CliInputError(ValueError):
    """Raised when PRAEVA-ANALYZE-001 CLI input is malformed."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="praeva")
    commands = parser.add_subparsers(dest="command", required=True)

    analyze_cmd = commands.add_parser("analyze")
    analyze_cmd.add_argument("--rule", required=True)
    analyze_cmd.add_argument("--current", required=True)
    analyze_cmd.add_argument("--proposed", required=True)
    analyze_cmd.add_argument("--api-group", required=True)
    analyze_cmd.add_argument("--kind", required=True)
    analyze_cmd.add_argument("--namespace", required=True)
    analyze_cmd.add_argument("--name", required=True)
    analyze_cmd.add_argument("--container", required=True)
    analyze_cmd.add_argument("--container-space", default="containers")
    analyze_cmd.add_argument("--pod-regex", required=True)
    analyze_cmd.add_argument("--prometheus-url", required=True)
    analyze_cmd.add_argument("--start", required=True)
    analyze_cmd.add_argument("--end", required=True)
    analyze_cmd.add_argument("--step", required=True)
    analyze_cmd.add_argument("--short-window", required=True)
    analyze_cmd.add_argument("--long-window", required=True)
    analyze_cmd.add_argument("--rule-param", action="append", default=[])
    analyze_cmd.add_argument("--summary", action="store_true")

    return parser


def _read_manifest(path: str, *, side: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CliInputError(f"cannot read {side} manifest file: {exc}") from exc


def _rule_params(values: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise CliInputError("--rule-param must use key=value syntax")
        key, raw = value.split("=", 1)
        if not key or not raw:
            raise CliInputError("--rule-param must use non-empty key=value syntax")
        if key in params:
            raise CliInputError(f"duplicate --rule-param: {key}")
        params[key] = raw
    return params


def _summary(document: dict[str, Any]) -> str:
    result = document["result"]
    rule_id = result.get("rule_id", "UNKNOWN_RULE")
    hazard_id = result.get("hazard_id", "UNKNOWN_HAZARD")
    applicability = result.get("applicability")

    if applicability == "NOT_APPLICABLE":
        reason = result.get("not_applicable_reason", {}).get("code", "not_applicable")
        return f"{rule_id} {hazard_id}: NOT_APPLICABLE ({reason})"

    if result.get("classification_status") == "UNKNOWN":
        reasons = result.get("unknown_reasons", [])
        codes = [item.get("code", "unknown") for item in reasons if isinstance(item, dict)]
        suffix = ",".join(codes) if codes else "unknown"
        return f"{rule_id} {hazard_id}: UNKNOWN ({suffix})"

    return f"{rule_id} {hazard_id}: {result.get('risk_level', 'UNKNOWN')}"


def main(argv: list[str] | None = None, *, query_range: QueryRange | None = None) -> int:
    parser = _parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    try:
        if args.command != "analyze":
            raise CliInputError("unsupported command")

        current_manifest = _read_manifest(args.current, side="current")
        proposed_manifest = _read_manifest(args.proposed, side="proposed")
        params = _rule_params(args.rule_param)

        document = analyze(
            current_manifest=current_manifest,
            proposed_manifest=proposed_manifest,
            api_group=args.api_group,
            kind=args.kind,
            namespace=args.namespace,
            name=args.name,
            container=args.container,
            container_space=args.container_space,
            pod_regex=args.pod_regex,
            prometheus_url=args.prometheus_url,
            start=args.start,
            end=args.end,
            step=args.step,
            short_window=args.short_window,
            long_window=args.long_window,
            rule_id=args.rule,
            rule_params=params,
            query_range=query_range,
        )
    except (
        AnalyzeInputError,
        CliInputError,
        ChangeInputError,
        ChangeJoinInputError,
        ChangeRiskInputError,
        PrometheusAdapterError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.summary:
        print(_summary(document))
    else:
        print(json.dumps(document, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
