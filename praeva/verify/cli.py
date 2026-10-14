from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from praeva.verify.cpu_evidence import build_report
from praeva.verify.prometheus_adapter import (
    PrometheusAdapterError,
    collect_normalized_evidence,
)


class CliInputError(ValueError):
    """Raised when CLI input is malformed or incomplete."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="praeva")
    commands = parser.add_subparsers(dest="command", required=True)

    verify = commands.add_parser("verify")
    verify_commands = verify.add_subparsers(dest="verify_command", required=True)

    cpu = verify_commands.add_parser("cpu")
    source = cpu.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", dest="input_path")
    source.add_argument("--prometheus-url")

    cpu.add_argument("--namespace")
    cpu.add_argument("--pod-regex")
    cpu.add_argument("--container")
    cpu.add_argument("--start", type=float)
    cpu.add_argument("--end", type=float)
    cpu.add_argument("--step", type=float)
    cpu.add_argument("--short-window")
    cpu.add_argument("--long-window")
    cpu.add_argument("--request-rate-query")

    return parser


def _load_payload(path: str) -> dict[str, Any]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CliInputError(f"cannot read input file: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliInputError(f"input is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise CliInputError("input JSON must be an object")

    required = ("pods", "short_window", "long_window")
    missing = [key for key in required if key not in payload]
    if missing:
        raise CliInputError(f"missing required input fields: {', '.join(missing)}")

    if not isinstance(payload["pods"], list):
        raise CliInputError("pods must be a list")
    if not payload["pods"]:
        raise CliInputError("pods must contain at least one pod")
    if not isinstance(payload["short_window"], str) or not payload["short_window"]:
        raise CliInputError("short_window must be a non-empty string")
    if not isinstance(payload["long_window"], str) or not payload["long_window"]:
        raise CliInputError("long_window must be a non-empty string")

    return payload


def _run_verify_cpu(payload: dict[str, Any]) -> dict[str, Any]:
    live_context = payload.get("live_context")
    if live_context is not None and not isinstance(live_context, dict):
        raise CliInputError("live_context must be an object when provided")

    return build_report(
        pods=payload["pods"],
        short_window=payload["short_window"],
        long_window=payload["long_window"],
        live_context=live_context,
    )


def _prometheus_payload(args: argparse.Namespace) -> dict[str, Any]:
    required = {
        "namespace": args.namespace,
        "pod_regex": args.pod_regex,
        "container": args.container,
        "start": args.start,
        "end": args.end,
        "step": args.step,
        "short_window": args.short_window,
        "long_window": args.long_window,
    }
    missing = [name.replace("_", "-") for name, value in required.items() if value is None]
    if missing:
        raise CliInputError(
            "Prometheus mode is missing required arguments: " + ", ".join(missing)
        )

    return collect_normalized_evidence(
        prometheus_url=args.prometheus_url,
        namespace=args.namespace,
        pod_regex=args.pod_regex,
        container=args.container,
        start=args.start,
        end=args.end,
        step=args.step,
        short_window=args.short_window,
        long_window=args.long_window,
        request_rate_query=args.request_rate_query,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    try:
        if args.command != "verify" or args.verify_command != "cpu":
            raise CliInputError("unsupported command")

        if args.input_path is not None:
            payload = _load_payload(args.input_path)
        else:
            payload = _prometheus_payload(args)

        report = _run_verify_cpu(payload)
    except (
        CliInputError,
        PrometheusAdapterError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0
