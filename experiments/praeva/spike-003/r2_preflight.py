#!/usr/bin/env python3
"""PRAEVA SPIKE-003 R2 churn readiness preflight.

Checks only evaluation-grid availability of the Prometheus metric families needed
before the controlled rollout. It does not mutate Kubernetes and does not prove
ownership, population completeness, raw-scrape continuity, or product eligibility.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal

import collect
import preflight

RUN_ID = "R2-churn-rollout"
REQUIRED_TRAILING_SECONDS = Decimal("600")


def compute_preflight_interval(now_seconds: int) -> dict[str, str]:
    raw_end = Decimal(now_seconds) - collect.INGESTION_LAG
    end = (raw_end // collect.STEP) * collect.STEP
    start = end - REQUIRED_TRAILING_SECONDS
    return {
        "start": collect.canonical_decimal(start),
        "end": collect.canonical_decimal(end),
        "step": collect.canonical_decimal(collect.STEP),
        "required_trailing_seconds": collect.canonical_decimal(
            REQUIRED_TRAILING_SECONDS
        ),
        "ingestion_lag_seconds": collect.canonical_decimal(
            collect.INGESTION_LAG
        ),
    }


def run_preflight(*, prometheus_url: str, dry_run: bool) -> int:
    interval = compute_preflight_interval(time.time_ns() // 1_000_000_000)
    probes = preflight.probe_set()

    if dry_run:
        print("PRAEVA SPIKE-003 R2 CHURN PREFLIGHT DRY RUN")
        print("==========================================")
        print(
            json.dumps(
                {"run_id": RUN_ID, "interval": interval, "probes": probes},
                indent=2,
                sort_keys=True,
            )
        )
        print(
            "No network I/O, Kubernetes mutation, or product-semantic decision "
            "was performed."
        )
        return 0

    start = Decimal(interval["start"])
    end = Decimal(interval["end"])
    step = Decimal(interval["step"])
    grid = preflight.expected_grid(start, end, step)

    print("PRAEVA SPIKE-003 R2 CHURN AVAILABILITY PREFLIGHT")
    print("================================================")
    print(f"required start: {preflight.utc_iso(start)}")
    print(f"required end:   {preflight.utc_iso(end)}")
    print(f"points:         {len(grid)}")

    ready = True
    for label, spec in probes.items():
        presence = preflight.collect_probe(
            prometheus_url=prometheus_url,
            label=label,
            promql=spec["promql"],
            start=interval["start"],
            end=interval["end"],
            step=interval["step"],
        )
        missing = [
            timestamp for timestamp in grid if not presence.get(timestamp, False)
        ]
        probe_ready = not missing
        ready = ready and probe_ready

        print(f"\n{label}")
        print(f"  covered:       {str(probe_ready).lower()}")
        print(f"  missing_points:{len(missing):>5}")
        if missing:
            print(f"  first_missing: {preflight.utc_iso(missing[0])}")
            print(f"  last_missing:  {preflight.utc_iso(missing[-1])}")

    print("\nDecision")
    print("--------")
    print(f"preflight_ready: {str(ready).lower()}")
    print(
        "\nThis gate proves only 10 minutes of evaluation-grid presence ending behind "
        "the frozen ingestion lag. It does not prove churn-time availability, ownership, "
        "population completeness, or raw-scrape continuity."
    )
    return 0 if ready else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SPIKE-003 R2 churn series-availability preflight"
    )
    parser.add_argument(
        "--prometheus-url",
        default=collect.DEFAULT_PROMETHEUS_URL,
        help="Prometheus transport endpoint (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the frozen readiness geometry and probes without network I/O",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run_preflight(
            prometheus_url=args.prometheus_url,
            dry_run=args.dry_run,
        )
    except (collect.CollectionError, preflight.PreflightError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
