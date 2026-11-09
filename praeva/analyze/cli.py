from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from praeva.analyze.invocation import (
    InvocationInputError,
    load_config,
    resolve_invocation,
)
from praeva.analyze.orchestrator import AnalyzeInputError, analyze
from praeva.change.cpu_limit import ChangeInputError
from praeva.change.join import ChangeJoinInputError
from praeva.risk.cpu_limit_insufficiency import ChangeRiskInputError
from praeva.verify.prometheus_adapter import PrometheusAdapterError, QueryRange

Clock = Any

# ANALYZE-ERGONOMICS-001 §6.2: container_space was already defaulted by the
# CLI before this slice. It is kept for backward compatibility and carried
# as a named legacy default so its origin is auditable in effective_params.
# Explicit --config overrides it; an explicit --container-space overrides both.
LEGACY_DEFAULTS = {"container_space": "containers"}


class CliInputError(ValueError):
    """Raised when PRAEVA-ANALYZE-001 CLI input is malformed."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="praeva")
    commands = parser.add_subparsers(dest="command", required=True)

    analyze_cmd = commands.add_parser("analyze")
    analyze_cmd.add_argument("--current", required=True)
    analyze_cmd.add_argument("--proposed", required=True)

    # ANALYZE-ERGONOMICS-001: identity and policy may come from --config and
    # an explicitly selected --profile, so they are no longer required here.
    # Nothing has a default: a value absent from every source is an input error.
    analyze_cmd.add_argument("--config")
    analyze_cmd.add_argument("--profile")

    analyze_cmd.add_argument("--rule")
    analyze_cmd.add_argument("--api-group")
    analyze_cmd.add_argument("--kind")
    analyze_cmd.add_argument("--namespace")
    analyze_cmd.add_argument("--name")
    analyze_cmd.add_argument("--container")
    analyze_cmd.add_argument("--container-space")
    analyze_cmd.add_argument("--pod-regex")
    analyze_cmd.add_argument("--prometheus-url")

    analyze_cmd.add_argument("--last")
    analyze_cmd.add_argument("--start")
    analyze_cmd.add_argument("--end")
    analyze_cmd.add_argument("--step")
    analyze_cmd.add_argument("--short-window")
    analyze_cmd.add_argument("--long-window")

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


def _cli_values(args: argparse.Namespace, params: dict[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {
        "prometheus_url": args.prometheus_url,
        "namespace": args.namespace,
        "api_group": args.api_group,
        "kind": args.kind,
        "name": args.name,
        "container": args.container,
        "container_space": args.container_space,
        "pod_regex": args.pod_regex,
        "rule": args.rule,
        "step": args.step,
        "short_window": args.short_window,
        "long_window": args.long_window,
        "last": args.last,
        "start": args.start,
        "end": args.end,
        "current_manifest_path": args.current,
        "proposed_manifest_path": args.proposed,
    }
    if params:
        values["rule_params"] = params
    return {key: value for key, value in values.items() if value is not None}


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


def main(
    argv: list[str] | None = None,
    *,
    query_range: QueryRange | None = None,
    now: Clock | None = None,
) -> int:
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

        # The config file is never discovered: it is read only when named.
        config = load_config(args.config) if args.config else None
        resolved_now = int(time.time()) if now is None else int(now)

        resolved = resolve_invocation(
            cli_values=_cli_values(args, params),
            config=config,
            profile=args.profile,
            rule_id=args.rule,
            now=resolved_now,
            legacy_defaults=LEGACY_DEFAULTS,
        )

        identity = resolved["identity"]
        policy = resolved["policy"]
        time_range = resolved["time_range"]

        document = analyze(
            current_manifest=current_manifest,
            proposed_manifest=proposed_manifest,
            api_group=identity["api_group"],
            kind=identity["kind"],
            namespace=identity["namespace"],
            name=identity["name"],
            container=identity["container"],
            container_space=identity["container_space"],
            pod_regex=identity["pod_regex"],
            prometheus_url=identity["prometheus_url"],
            start=time_range["start"],
            end=time_range["end"],
            step=time_range["step"],
            short_window=policy["short_window"],
            long_window=policy["long_window"],
            rule_id=resolved["rule_id"],
            rule_params=policy["rule_params"],
            query_range=query_range,
            invocation=resolved["invocation"],
        )
    except (
        AnalyzeInputError,
        CliInputError,
        InvocationInputError,
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
