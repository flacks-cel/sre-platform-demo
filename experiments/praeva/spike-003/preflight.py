#!/usr/bin/env python3
"""PRAEVA SPIKE-003 R1 lab-readiness preflight.

Added after finding F1. This helper checks evaluation-grid presence of the metric
families required by the frozen R1 before another evidential collection is
attempted. It is experiment-only and does not prove population completeness,
ownership semantics, raw-scrape continuity, or product eligibility.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import collect


class PreflightError(RuntimeError):
    """Raised when the experimental availability preflight cannot complete."""


def utc_iso(value: Decimal | str | int | float) -> str:
    return (
        datetime.fromtimestamp(float(value), tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def probe_set() -> dict[str, dict[str, str]]:
    namespace = collect.escape_label_value(collect.NAMESPACE)
    pod_regex = collect.escape_label_value(collect.POD_REGEX)
    container = collect.escape_label_value(collect.CONTAINER)
    workload = collect.escape_label_value(collect.WORKLOAD)
    target_container = (
        f'namespace="{namespace}",pod=~"{pod_regex}",container="{container}"'
    )

    return {
        "cpu_raw": {
            "required_from": "extended",
            "promql": (
                "count(container_cpu_usage_seconds_total{"
                f"{target_container}}}) or vector(0)"
            ),
        },
        "cfs_throttled_raw": {
            "required_from": "extended",
            "promql": (
                "count(container_cpu_cfs_throttled_periods_total{"
                f"{target_container}}}) or vector(0)"
            ),
        },
        "cpu_limit_verify": {
            "required_from": "analysis",
            "promql": (
                "count(kube_pod_container_resource_limits{"
                f'{target_container},resource="cpu"}}) or vector(0)'
            ),
        },
        "cpu_limit_uid": {
            "required_from": "extended",
            "promql": (
                "count(kube_pod_container_resource_limits{"
                f'{target_container},resource="cpu",uid!=""}}) or vector(0)'
            ),
        },
        "pod_owner": {
            "required_from": "extended",
            "promql": (
                "count(kube_pod_owner{"
                f'namespace="{namespace}",pod=~"{pod_regex}",uid!="",'
                'owner_is_controller="true"}) or vector(0)'
            ),
        },
        "replicaset_owner": {
            "required_from": "extended",
            "promql": (
                "count(kube_replicaset_owner{"
                f'namespace="{namespace}",owner_is_controller="true",'
                f'owner_kind="Deployment",owner_name="{workload}"}}) or vector(0)'
            ),
        },
        "pod_created": {
            "required_from": "extended",
            "promql": (
                "count(kube_pod_created{"
                f'namespace="{namespace}",pod=~"{pod_regex}",uid!=""}}) or vector(0)'
            ),
        },
    }


def expected_grid(start: Decimal, end: Decimal, step: Decimal) -> list[Decimal]:
    if end < start:
        raise PreflightError("grid end precedes start")
    points: list[Decimal] = []
    current = start
    while current <= end:
        points.append(current)
        current += step
    return points


def matrix_values(data: dict[str, Any], *, label: str) -> list[list[Any]]:
    if data.get("resultType") != "matrix":
        raise PreflightError(
            f"{label} resultType must be matrix, got {data.get('resultType')!r}"
        )
    result = data.get("result")
    if not isinstance(result, list) or len(result) != 1:
        count = len(result) if isinstance(result, list) else "non-list"
        raise PreflightError(
            f"{label} presence probe must return exactly one series, got {count}"
        )
    values = result[0].get("values")
    if not isinstance(values, list):
        raise PreflightError(f"{label} presence probe is missing matrix values")
    return values


def parse_presence(values: list[list[Any]]) -> dict[Decimal, bool]:
    output: dict[Decimal, bool] = {}
    for item in values:
        if not isinstance(item, list) or len(item) != 2:
            raise PreflightError(f"invalid matrix value: {item!r}")
        try:
            timestamp = Decimal(str(item[0]))
            count = Decimal(str(item[1]))
        except Exception as exc:
            raise PreflightError(f"invalid matrix value: {item!r}") from exc
        output[timestamp] = count > 0
    return output


def trailing_positive_start(
    grid: list[Decimal],
    presence: dict[Decimal, bool],
) -> Decimal | None:
    if not grid or not presence.get(grid[-1], False):
        return None
    start = grid[-1]
    for timestamp in reversed(grid[:-1]):
        if not presence.get(timestamp, False):
            break
        start = timestamp
    return start


def collect_probe(
    *,
    prometheus_url: str,
    label: str,
    promql: str,
    start: str,
    end: str,
    step: str,
) -> dict[Decimal, bool]:
    raw = collect.query_range(
        base_url=prometheus_url,
        query=promql,
        start=start,
        end=end,
        step=step,
    )
    payload = collect.parse_json_payload(raw, label=label)
    data = collect.validate_success(payload, label=label)
    return parse_presence(matrix_values(data, label=label))


def run_preflight(*, prometheus_url: str, dry_run: bool) -> int:
    interval = collect.compute_interval(time.time_ns() // 1_000_000_000)
    probes = probe_set()

    if dry_run:
        print("PRAEVA SPIKE-003 R1 AVAILABILITY PREFLIGHT DRY RUN")
        print("=================================================")
        print(json.dumps({"interval": interval, "probes": probes}, indent=2, sort_keys=True))
        print("No network I/O or product-semantic decision was performed.")
        return 0

    candidate_extended = Decimal(interval["extended_ownership_start"])
    candidate_start = Decimal(interval["start"])
    candidate_end = Decimal(interval["end"])
    step = Decimal(interval["step"])
    w_max = Decimal(interval["w_max_seconds"])
    duration = Decimal(interval["analysis_duration_seconds"])
    lag = Decimal(interval["ingestion_lag_seconds"])
    grid = expected_grid(candidate_extended, candidate_end, step)

    print("PRAEVA SPIKE-003 R1 AVAILABILITY PREFLIGHT")
    print("=========================================")
    print(f"candidate extended: {utc_iso(candidate_extended)}")
    print(f"candidate start:    {utc_iso(candidate_start)}")
    print(f"candidate end:      {utc_iso(candidate_end)}")

    trailing_by_probe: dict[str, Decimal | None] = {}
    ready = True

    for label, spec in probes.items():
        presence = collect_probe(
            prometheus_url=prometheus_url,
            label=label,
            promql=spec["promql"],
            start=interval["extended_ownership_start"],
            end=interval["end"],
            step=interval["step"],
        )
        required_start = (
            candidate_extended
            if spec["required_from"] == "extended"
            else candidate_start
        )
        required_grid = [timestamp for timestamp in grid if timestamp >= required_start]
        missing = [timestamp for timestamp in required_grid if not presence.get(timestamp, False)]
        trailing = trailing_positive_start(grid, presence)
        trailing_by_probe[label] = trailing
        probe_ready = not missing
        ready = ready and probe_ready

        print(f"\n{label}")
        print(f"  required_from: {spec['required_from']}")
        print(f"  covered:       {str(probe_ready).lower()}")
        print(f"  missing_points:{len(missing):>5}")
        print(
            "  trailing_from: "
            + (utc_iso(trailing) if trailing is not None else "UNAVAILABLE_AT_END")
        )
        if missing:
            print(f"  first_missing: {utc_iso(missing[0])}")
            print(f"  last_missing:  {utc_iso(missing[-1])}")

    trailing_extended = [
        trailing_by_probe[label]
        for label, spec in probes.items()
        if spec["required_from"] == "extended"
    ]
    trailing_analysis = [
        trailing_by_probe[label]
        for label, spec in probes.items()
        if spec["required_from"] == "analysis"
    ]

    boundaries_known = all(value is not None for value in trailing_by_probe.values())
    print("\nDecision")
    print("--------")
    print(f"candidate_ready: {str(ready).lower()}")

    if boundaries_known:
        extended_boundary = max(value for value in trailing_extended if value is not None)
        analysis_boundary = max(value for value in trailing_analysis if value is not None)
        earliest_start = max(analysis_boundary, extended_boundary + w_max)
        earliest_end = earliest_start + duration
        earliest_collection = earliest_end + lag
        print(f"latest extended-series boundary: {utc_iso(extended_boundary)}")
        print(f"latest analysis-series boundary: {utc_iso(analysis_boundary)}")
        print(f"earliest safe analysis start:    {utc_iso(earliest_start)}")
        print(f"earliest safe analysis end:      {utc_iso(earliest_end)}")
        print(f"earliest safe collection:        {utc_iso(earliest_collection)}")
    else:
        print("earliest safe collection:        UNKNOWN (required series absent at end)")

    print(
        "\nThis is an experimental evaluation-grid availability preflight only; "
        "it is not an ownership or population proof."
    )
    return 0 if ready else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SPIKE-003 R1 series-availability preflight")
    parser.add_argument(
        "--prometheus-url",
        default=collect.DEFAULT_PROMETHEUS_URL,
        help="Prometheus transport endpoint (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the candidate interval and probes without network I/O",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run_preflight(
            prometheus_url=args.prometheus_url,
            dry_run=args.dry_run,
        )
    except (collect.CollectionError, PreflightError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
