#!/usr/bin/env python3
"""PRAEVA SPIKE-003 R2 churn raw evidence collector.

Consumes already-recorded mutation timestamps/nonce and captures the frozen R2
Prometheus interval. It does not mutate Kubernetes, classify risk, or change
product semantics.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

import collect

RUN_ID = "R2-churn-rollout"
PRE_MUTATION_ANALYSIS = Decimal("300")
POST_MUTATION_ANALYSIS = Decimal("600")


def compute_r2_interval(*, mutation_before: str, mutation_after: str) -> dict[str, str]:
    before = Decimal(mutation_before)
    after = Decimal(mutation_after)
    if not before.is_finite() or not after.is_finite():
        raise collect.CollectionError("mutation timestamps must be finite")
    if after < before:
        raise collect.CollectionError("mutation_after must be >= mutation_before")

    step = collect.STEP
    before_grid = (before // step) * step
    after_grid = (after / step).to_integral_value(rounding=ROUND_CEILING) * step

    short_seconds = collect.parse_prometheus_duration(collect.SHORT_WINDOW)
    long_seconds = collect.parse_prometheus_duration(collect.LONG_WINDOW)
    w_max = max(short_seconds, long_seconds)
    extension_steps = (w_max / step).to_integral_value(rounding=ROUND_CEILING)

    start = before_grid - PRE_MUTATION_ANALYSIS
    end = after_grid + POST_MUTATION_ANALYSIS
    extended_start = start - extension_steps * step
    earliest_collection = end + collect.INGESTION_LAG

    return {
        "mutation_before": collect.canonical_decimal(before),
        "mutation_after": collect.canonical_decimal(after),
        "mutation_grid_before": collect.canonical_decimal(before_grid),
        "mutation_grid_after": collect.canonical_decimal(after_grid),
        "start": collect.canonical_decimal(start),
        "end": collect.canonical_decimal(end),
        "step": collect.canonical_decimal(step),
        "short_window": collect.SHORT_WINDOW,
        "long_window": collect.LONG_WINDOW,
        "w_max_seconds": collect.canonical_decimal(w_max),
        "pre_mutation_analysis_seconds": collect.canonical_decimal(
            PRE_MUTATION_ANALYSIS
        ),
        "post_mutation_analysis_seconds": collect.canonical_decimal(
            POST_MUTATION_ANALYSIS
        ),
        "ingestion_lag_seconds": collect.canonical_decimal(
            collect.INGESTION_LAG
        ),
        "extension_steps": collect.canonical_decimal(extension_steps),
        "extended_ownership_start": collect.canonical_decimal(extended_start),
        "earliest_collection": collect.canonical_decimal(earliest_collection),
    }


def _collect_status(
    *,
    prometheus_url: str,
    output_dir: Path,
    manifest: dict[str, Any],
) -> None:
    for status_name, path, required in (
        ("buildinfo", "/api/v1/status/buildinfo", True),
        ("flags", "/api/v1/status/flags", False),
    ):
        started = time.monotonic_ns()
        try:
            raw = collect.http_get_bytes(prometheus_url, path)
            payload = collect.parse_json_payload(raw, label=status_name)
            collect.validate_success(payload, label=status_name)
            collect.save_bytes(output_dir / f"{status_name}.json", raw)
            manifest["responses"][status_name] = {
                "status": "CAPTURED",
                "bytes": len(raw),
                "elapsed_ms": (time.monotonic_ns() - started) // 1_000_000,
            }
        except collect.CollectionError as exc:
            if required:
                raise
            manifest["responses"][status_name] = {
                "status": "UNAVAILABLE",
                "error": str(exc),
                "elapsed_ms": (time.monotonic_ns() - started) // 1_000_000,
            }
        collect.save_json(output_dir / "manifest.json", manifest)


def _collect_queries(
    *,
    prometheus_url: str,
    output_dir: Path,
    manifest: dict[str, Any],
    interval: dict[str, str],
    queries: dict[str, dict[str, str]],
) -> None:
    for key, spec in queries.items():
        query_start = (
            interval["start"]
            if spec["scope"] == "verify"
            else interval["extended_ownership_start"]
        )
        started = time.monotonic_ns()
        raw = collect.query_range(
            base_url=prometheus_url,
            query=spec["promql"],
            start=query_start,
            end=interval["end"],
            step=interval["step"],
        )
        payload = collect.parse_json_payload(raw, label=key)
        data = collect.validate_success(payload, label=key)
        if data.get("resultType") != "matrix":
            raise collect.CollectionError(
                f"{key} resultType must be matrix, got {data.get('resultType')!r}"
            )

        filename = f"{key}.json"
        collect.save_bytes(output_dir / filename, raw)
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
        collect.save_json(output_dir / "manifest.json", manifest)


def collect_r2(
    *,
    prometheus_url: str,
    output_root: Path | None,
    mutation_before: str,
    mutation_after: str,
    nonce: str,
    dry_run: bool,
) -> int:
    if not nonce:
        raise collect.CollectionError("nonce must be non-empty")

    interval = compute_r2_interval(
        mutation_before=mutation_before,
        mutation_after=mutation_after,
    )
    queries = collect.query_set()

    if output_root is None:
        output_root = Path(__file__).resolve().parent / "evidence"
    output_dir = output_root / f"{RUN_ID}-{interval['mutation_grid_after']}"

    metadata: dict[str, Any] = {
        "run_id": RUN_ID,
        "mutation": {
            "nonce": nonce,
            "annotation_key": "praeva-spike-003-churn",
            "mutation_before": interval["mutation_before"],
            "mutation_after": interval["mutation_after"],
            "intentional_mutations": 1,
        },
        "semantic_parameters": {
            "namespace": collect.NAMESPACE,
            "api_group": collect.API_GROUP,
            "kind": collect.KIND,
            "workload": collect.WORKLOAD,
            "container": collect.CONTAINER,
            "pod_regex": collect.POD_REGEX,
        },
        "transport": {"prometheus_url": prometheus_url},
        "interval": interval,
        "collector": {
            "kubernetes_mutation_performed": False,
            "risk_classification": False,
            "product_semantics_changed": False,
        },
    }

    if dry_run:
        print("PRAEVA SPIKE-003 R2 CHURN COLLECTOR DRY RUN")
        print("============================================")
        print(json.dumps(metadata, indent=2, sort_keys=True))
        print("\nQueries:")
        for key, spec in queries.items():
            print(f"\n[{key}] scope={spec['scope']}")
            print(spec["promql"])
        print("No network I/O or Kubernetes mutation was performed.")
        return 0

    now = Decimal(time.time_ns() // 1_000_000_000)
    earliest = Decimal(interval["earliest_collection"])
    if now < earliest:
        remaining = earliest - now
        raise collect.CollectionError(
            "R2 collection is too early for the frozen ingestion lag: "
            f"earliest_collection={interval['earliest_collection']} "
            f"remaining_seconds={collect.canonical_decimal(remaining)}"
        )

    if output_dir.exists():
        raise collect.CollectionError(
            f"refusing to overwrite existing evidence directory: {output_dir}"
        )
    output_dir.mkdir(parents=True)

    collect.save_json(output_dir / "metadata.json", metadata)
    collect.save_json(output_dir / "queries.json", queries)
    manifest: dict[str, Any] = {"status": "IN_PROGRESS", "responses": {}}
    collect.save_json(output_dir / "manifest.json", manifest)

    try:
        _collect_status(
            prometheus_url=prometheus_url,
            output_dir=output_dir,
            manifest=manifest,
        )
        _collect_queries(
            prometheus_url=prometheus_url,
            output_dir=output_dir,
            manifest=manifest,
            interval=interval,
            queries=queries,
        )
    except Exception as exc:
        manifest["status"] = "FAILED"
        manifest["error"] = str(exc)
        collect.save_json(output_dir / "manifest.json", manifest)
        raise

    manifest["status"] = "COMPLETE"
    collect.save_json(output_dir / "manifest.json", manifest)

    total_bytes = sum(
        item.get("bytes", 0)
        for item in manifest["responses"].values()
        if isinstance(item, dict)
    )
    print("PRAEVA SPIKE-003 R2 CHURN COLLECTION COMPLETE")
    print("==============================================")
    print(f"Evidence: {output_dir}")
    print(f"mutation_before: {interval['mutation_before']}")
    print(f"mutation_after:  {interval['mutation_after']}")
    print(f"start:           {interval['start']}")
    print(f"end:             {interval['end']}")
    print(f"extended:        {interval['extended_ownership_start']}")
    print(f"bytes:           {total_bytes}")
    print(
        "No Kubernetes mutation, risk classification, or product-semantic change "
        "was performed."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect frozen PRAEVA SPIKE-003 R2 churn evidence"
    )
    parser.add_argument(
        "--mutation-before",
        required=True,
        help="Unix seconds immediately before the single rollout patch",
    )
    parser.add_argument(
        "--mutation-after",
        required=True,
        help="Unix seconds immediately after the single rollout patch returns",
    )
    parser.add_argument(
        "--nonce",
        required=True,
        help="exact R2 annotation nonce used for the rollout",
    )
    parser.add_argument(
        "--prometheus-url",
        default=collect.DEFAULT_PROMETHEUS_URL,
        help="Prometheus transport endpoint (default: %(default)s)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="optional evidence root; defaults to spike-003/evidence",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print mechanically derived R2 interval/query metadata without network I/O",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return collect_r2(
            prometheus_url=args.prometheus_url,
            output_root=args.output_root,
            mutation_before=args.mutation_before,
            mutation_after=args.mutation_after,
            nonce=args.nonce,
            dry_run=args.dry_run,
        )
    except (ArithmeticError, collect.CollectionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
