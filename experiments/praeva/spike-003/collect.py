#!/usr/bin/env python3
"""PRAEVA SPIKE-003 raw evidence collector.

Collects the frozen R1 Prometheus wire only. It performs no risk classification,
no ownership reduction, and no product-semantic mutation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

RUN_ID = "R1-stable-wire"
DEFAULT_PROMETHEUS_URL = "http://localhost:9091"
NAMESPACE = "app"
API_GROUP = "apps"
KIND = "Deployment"
WORKLOAD = "jobs-api"
CONTAINER = "jobs-api"
POD_REGEX = "jobs-api-.*"
STEP = Decimal("15")
SHORT_WINDOW = "2m"
LONG_WINDOW = "5m"
ANALYSIS_DURATION = Decimal("1800")
INGESTION_LAG = Decimal("120")

_DURATION_TOKEN = re.compile(r"(\d+)(ms|[smhdwy])")
_DURATION_MULTIPLIERS = {
    "ms": Decimal("0.001"),
    "s": Decimal("1"),
    "m": Decimal("60"),
    "h": Decimal("3600"),
    "d": Decimal("86400"),
    "w": Decimal("604800"),
    "y": Decimal("31536000"),
}


class CollectionError(RuntimeError):
    """Raised when the frozen SPIKE-003 collection cannot complete."""


def canonical_decimal(value: Decimal | int | str) -> str:
    try:
        number = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CollectionError(f"invalid decimal value: {value!r}") from exc
    if not number.is_finite():
        raise CollectionError(f"decimal value must be finite: {value!r}")
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def parse_prometheus_duration(value: str) -> Decimal:
    """Parse a simple Prometheus duration literal such as 2m, 5m, or 1h30m."""
    if not isinstance(value, str) or not value:
        raise CollectionError("duration must be a non-empty string")

    position = 0
    total = Decimal(0)
    previous_seconds: Decimal | None = None
    seen_units: set[str] = set()

    for match in _DURATION_TOKEN.finditer(value):
        if match.start() != position:
            raise CollectionError(f"unsupported Prometheus duration literal: {value!r}")
        position = match.end()
        magnitude = Decimal(match.group(1))
        unit = match.group(2)
        if unit in seen_units:
            raise CollectionError(f"duplicate duration unit in {value!r}")
        seen_units.add(unit)
        multiplier = _DURATION_MULTIPLIERS[unit]
        if previous_seconds is not None and multiplier >= previous_seconds:
            raise CollectionError(
                f"duration units must be ordered longest to shortest: {value!r}"
            )
        previous_seconds = multiplier
        total += magnitude * multiplier

    if position != len(value) or total <= 0:
        raise CollectionError(f"unsupported Prometheus duration literal: {value!r}")
    return total


def escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def query_set() -> dict[str, dict[str, str]]:
    namespace = escape_label_value(NAMESPACE)
    pod_regex = escape_label_value(POD_REGEX)
    container = escape_label_value(CONTAINER)
    selector = f'namespace="{namespace}",pod=~"{pod_regex}",container="{container}"'
    owner_selector = f'namespace="{namespace}",owner_is_controller="true"'
    created_selector = f'namespace="{namespace}"'

    pod_owner_group = "namespace, pod, uid, owner_kind, owner_name, owner_is_controller"
    rs_owner_group = "namespace, replicaset, owner_kind, owner_name, owner_is_controller"

    return {
        "cpu_short": {
            "scope": "verify",
            "promql": (
                "sum by (pod) (rate(container_cpu_usage_seconds_total"
                f"{{{selector}}}[{SHORT_WINDOW}]))"
            ),
        },
        "cpu_long": {
            "scope": "verify",
            "promql": (
                "sum by (pod) (rate(container_cpu_usage_seconds_total"
                f"{{{selector}}}[{LONG_WINDOW}]))"
            ),
        },
        "cfs_throttled_short": {
            "scope": "verify",
            "promql": (
                "sum by (pod) (rate(container_cpu_cfs_throttled_periods_total"
                f"{{{selector}}}[{SHORT_WINDOW}]))"
            ),
        },
        "cfs_throttled_long": {
            "scope": "verify",
            "promql": (
                "sum by (pod) (rate(container_cpu_cfs_throttled_periods_total"
                f"{{{selector}}}[{LONG_WINDOW}]))"
            ),
        },
        "cpu_limit": {
            "scope": "verify",
            "promql": (
                "max by (pod) (kube_pod_container_resource_limits{"
                f'{selector},resource="cpu"}})'
            ),
        },
        "cpu_limit_uid": {
            "scope": "ownership",
            "promql": (
                "max by (namespace, pod, uid, container, resource, unit) "
                "(kube_pod_container_resource_limits{"
                f'{selector},resource="cpu"}})'
            ),
        },
        "pod_owner": {
            "scope": "ownership",
            "promql": (
                f"max by ({pod_owner_group}) "
                f"(kube_pod_owner{{{owner_selector}}})"
            ),
        },
        "replicaset_owner": {
            "scope": "ownership",
            "promql": (
                f"max by ({rs_owner_group}) "
                f"(kube_replicaset_owner{{{owner_selector}}})"
            ),
        },
        "pod_created": {
            "scope": "ownership",
            "promql": (
                "max by (namespace, pod, uid) "
                f"(kube_pod_created{{{created_selector}}})"
            ),
        },
        "pod_owner_source_timestamp": {
            "scope": "ownership",
            "promql": (
                f"max by ({pod_owner_group}) "
                f"(timestamp(kube_pod_owner{{{owner_selector}}}))"
            ),
        },
        "replicaset_owner_source_timestamp": {
            "scope": "ownership",
            "promql": (
                f"max by ({rs_owner_group}) "
                f"(timestamp(kube_replicaset_owner{{{owner_selector}}}))"
            ),
        },
        "pod_created_source_timestamp": {
            "scope": "ownership",
            "promql": (
                "max by (namespace, pod, uid) "
                f"(timestamp(kube_pod_created{{{created_selector}}}))"
            ),
        },
    }


def compute_interval(now_seconds: int) -> dict[str, str]:
    short_seconds = parse_prometheus_duration(SHORT_WINDOW)
    long_seconds = parse_prometheus_duration(LONG_WINDOW)
    w_max = max(short_seconds, long_seconds)
    raw_end = Decimal(now_seconds) - INGESTION_LAG
    end = (raw_end // STEP) * STEP
    start = end - ANALYSIS_DURATION
    extension_steps = (w_max / STEP).to_integral_value(rounding=ROUND_CEILING)
    extended_start = start - extension_steps * STEP

    return {
        "start": canonical_decimal(start),
        "end": canonical_decimal(end),
        "step": canonical_decimal(STEP),
        "short_window": SHORT_WINDOW,
        "long_window": LONG_WINDOW,
        "w_max_seconds": canonical_decimal(w_max),
        "analysis_duration_seconds": canonical_decimal(ANALYSIS_DURATION),
        "ingestion_lag_seconds": canonical_decimal(INGESTION_LAG),
        "extension_steps": canonical_decimal(extension_steps),
        "extended_ownership_start": canonical_decimal(extended_start),
    }


def http_get_bytes(
    base_url: str,
    path: str,
    params: dict[str, str] | None = None,
) -> bytes:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise CollectionError(f"HTTP {exc.code} for {url}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise CollectionError(f"Prometheus request failed for {url}: {exc}") from exc


def parse_json_payload(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectionError(f"{label} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise CollectionError(f"{label} response must be a JSON object")
    return payload


def validate_success(payload: dict[str, Any], *, label: str) -> dict[str, Any]:
    if payload.get("status") != "success":
        detail = payload.get("error") or "unknown error"
        raise CollectionError(f"{label} returned non-success: {detail}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise CollectionError(f"{label} response is missing data")
    return data


def save_bytes(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)


def save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def query_range(
    *,
    base_url: str,
    query: str,
    start: str,
    end: str,
    step: str,
) -> bytes:
    return http_get_bytes(
        base_url,
        "/api/v1/query_range",
        {
            "query": query,
            "start": start,
            "end": end,
            "step": step,
        },
    )


def collect_r1(*, prometheus_url: str, output_root: Path | None, dry_run: bool) -> int:
    interval = compute_interval(time.time_ns() // 1_000_000_000)
    queries = query_set()

    if output_root is None:
        output_root = Path(__file__).resolve().parent / "evidence"
    output_dir = output_root / f"{RUN_ID}-{interval['end']}"

    metadata: dict[str, Any] = {
        "run_id": RUN_ID,
        "semantic_parameters": {
            "namespace": NAMESPACE,
            "api_group": API_GROUP,
            "kind": KIND,
            "workload": WORKLOAD,
            "container": CONTAINER,
            "pod_regex": POD_REGEX,
        },
        "transport": {"prometheus_url": prometheus_url},
        "interval": interval,
        "collector": {
            "risk_classification": False,
            "product_semantics_changed": False,
        },
    }

    if dry_run:
        print("PRAEVA SPIKE-003 R1 DRY RUN")
        print("===========================")
        print(json.dumps(metadata, indent=2, sort_keys=True))
        print("\nQueries:")
        for key, spec in queries.items():
            print(f"\n[{key}] scope={spec['scope']}")
            print(spec["promql"])
        return 0

    if output_dir.exists():
        raise CollectionError(
            f"refusing to overwrite existing evidence directory: {output_dir}"
        )
    output_dir.mkdir(parents=True)

    save_json(output_dir / "metadata.json", metadata)
    save_json(output_dir / "queries.json", queries)

    manifest: dict[str, Any] = {"status": "IN_PROGRESS", "responses": {}}
    save_json(output_dir / "manifest.json", manifest)

    try:
        for status_name, path, required in (
            ("buildinfo", "/api/v1/status/buildinfo", True),
            ("flags", "/api/v1/status/flags", False),
        ):
            started = time.monotonic_ns()
            try:
                raw = http_get_bytes(prometheus_url, path)
                payload = parse_json_payload(raw, label=status_name)
                validate_success(payload, label=status_name)
                save_bytes(output_dir / f"{status_name}.json", raw)
                manifest["responses"][status_name] = {
                    "status": "CAPTURED",
                    "bytes": len(raw),
                    "elapsed_ms": (time.monotonic_ns() - started) // 1_000_000,
                }
            except CollectionError as exc:
                if required:
                    raise
                manifest["responses"][status_name] = {
                    "status": "UNAVAILABLE",
                    "error": str(exc),
                    "elapsed_ms": (time.monotonic_ns() - started) // 1_000_000,
                }
            save_json(output_dir / "manifest.json", manifest)

        for key, spec in queries.items():
            if spec["scope"] == "verify":
                query_start = interval["start"]
            else:
                query_start = interval["extended_ownership_start"]

            started = time.monotonic_ns()
            raw = query_range(
                base_url=prometheus_url,
                query=spec["promql"],
                start=query_start,
                end=interval["end"],
                step=interval["step"],
            )
            payload = parse_json_payload(raw, label=key)
            data = validate_success(payload, label=key)
            if data.get("resultType") != "matrix":
                raise CollectionError(
                    f"{key} resultType must be matrix, got {data.get('resultType')!r}"
                )

            filename = f"{key}.json"
            save_bytes(output_dir / filename, raw)
            manifest["responses"][key] = {
                "status": "CAPTURED",
                "scope": spec["scope"],
                "start": query_start,
                "end": interval["end"],
                "step": interval["step"],
                "result_series": (
                    len(data.get("result", []))
                    if isinstance(data.get("result"), list)
                    else None
                ),
                "bytes": len(raw),
                "elapsed_ms": (time.monotonic_ns() - started) // 1_000_000,
                "file": filename,
            }
            save_json(output_dir / "manifest.json", manifest)

    except Exception as exc:
        manifest["status"] = "FAILED"
        manifest["error"] = str(exc)
        save_json(output_dir / "manifest.json", manifest)
        raise

    manifest["status"] = "COMPLETE"
    save_json(output_dir / "manifest.json", manifest)

    total_bytes = sum(
        item.get("bytes", 0)
        for item in manifest["responses"].values()
        if isinstance(item, dict)
    )
    print("PRAEVA SPIKE-003 R1 COLLECTION COMPLETE")
    print("========================================")
    print(f"Evidence: {output_dir}")
    print(f"start:    {interval['start']}")
    print(f"end:      {interval['end']}")
    print(f"step:     {interval['step']}")
    print(f"extended: {interval['extended_ownership_start']}")
    print(f"bytes:    {total_bytes}")
    print("No risk classification or product-semantic change was performed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect frozen PRAEVA SPIKE-003 evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    r1 = subparsers.add_parser("r1", help="collect the frozen R1 stable-wire run")
    r1.add_argument(
        "--prometheus-url",
        default=DEFAULT_PROMETHEUS_URL,
        help="Prometheus transport endpoint (default: %(default)s)",
    )
    r1.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="optional evidence root; defaults to spike-003/evidence",
    )
    r1.add_argument(
        "--dry-run",
        action="store_true",
        help="print the frozen interval metadata and queries without network I/O",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "r1":
            return collect_r1(
                prometheus_url=args.prometheus_url,
                output_root=args.output_root,
                dry_run=args.dry_run,
            )
        raise CollectionError(f"unknown command: {args.command}")
    except CollectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
