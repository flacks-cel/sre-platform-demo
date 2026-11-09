#!/usr/bin/env python3
"""Run POPULATION-ENUMERATION-001 against a local raw Prometheus capture.

Scenario 18 of the contract validates enumeration against real telemetry --
the 2026-11-05 rollout capture, which lives outside the repository. This
script feeds that capture to the enumerator and prints a verdict per
timestamp.

It reads nothing from the cluster and issues no query. It only replays JSON
already on disk.

Usage:

    python experiments/praeva/population/enumerate_capture.py \\
        --capture-dir .runtime/praeva-rollout-20261105-185041-1794227910 \\
        --namespace app --name jobs-api

The grid is derived from the capture itself, so start, end and step need not
be supplied. Pass them only to narrow the window.

Files are discovered by their content, not their names: any *.json holding a
kube_pod_owner or kube_replicaset_owner matrix is picked up.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from praeva.ownership.population import enumerate_population  # noqa: E402
from praeva.ownership.prometheus_adapter import (  # noqa: E402
    collect_ownership_evidence,
)


def _payloads(capture_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    pod_payload: dict[str, Any] | None = None
    replicaset_payload: dict[str, Any] | None = None

    for path in sorted(capture_dir.rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue

        payload = document.get("payload", document)
        if not isinstance(payload, dict):
            continue
        result = payload.get("data", {}).get("result")
        if not isinstance(result, list) or not result:
            continue

        labels = result[0].get("metric", {})
        if not isinstance(labels, dict):
            continue
        text = json.dumps(document)
        if "replicaset" in labels and "kube_replicaset_owner" in text:
            replicaset_payload = payload
            print(f"  replicaset_owner <- {path.relative_to(capture_dir)}")
        elif "pod" in labels and "uid" in labels and "kube_pod_owner" in text:
            pod_payload = payload
            print(f"  pod_owner        <- {path.relative_to(capture_dir)}")

    if pod_payload is None or replicaset_payload is None:
        missing = []
        if pod_payload is None:
            missing.append("kube_pod_owner")
        if replicaset_payload is None:
            missing.append("kube_replicaset_owner")
        raise SystemExit(f"capture is missing: {', '.join(missing)}")
    return pod_payload, replicaset_payload


def _derive_grid(payloads: tuple[dict[str, Any], ...]) -> tuple[int, int, int]:
    """Read the evaluation grid off the capture.

    The window is a property of the data already on disk, so asking the
    operator to retype it only invites a mismatch between what was captured
    and what is replayed.
    """

    stamps: set[int] = set()
    for payload in payloads:
        for series in payload.get("data", {}).get("result", []):
            for point in series.get("values", []):
                stamps.add(int(Decimal(str(point[0]))))

    if len(stamps) < 2:
        raise SystemExit("capture does not contain enough samples to derive a grid")

    ordered = sorted(stamps)
    diffs = [b - a for a, b in zip(ordered, ordered[1:], strict=False) if b > a]
    step = min(diffs)
    return ordered[0], ordered[-1], step


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--start", help="default: derived from the capture")
    parser.add_argument("--end", help="default: derived from the capture")
    parser.add_argument("--step", help="default: derived from the capture")
    parser.add_argument(
        "--observed",
        help="optional comma-separated pod names the Verify observed",
    )
    args = parser.parse_args()

    capture_dir = Path(args.capture_dir)
    print(f"capture: {capture_dir}")
    pod_payload, replicaset_payload = _payloads(capture_dir)

    derived_start, derived_end, derived_step = _derive_grid(
        (pod_payload, replicaset_payload)
    )
    start_text = args.start or str(derived_start)
    end_text = args.end or str(derived_end)
    step_text = args.step or str(derived_step)
    print(f"  grid             <- start={start_text} end={end_text} step={step_text}")

    def replay(*, query: str, **_: Any) -> dict[str, Any]:
        if "kube_pod_owner" in query:
            return pod_payload
        if "kube_replicaset_owner" in query:
            return replicaset_payload
        raise AssertionError(f"unexpected query: {query}")

    evidence = collect_ownership_evidence(
        prometheus_url="replay://capture",
        namespace=args.namespace,
        start=start_text,
        end=end_text,
        step=step_text,
        query_range=replay,
    )

    start, end, step = int(start_text), int(end_text), int(step_text)
    grid = [str(t) for t in range(start, end + 1, step)]

    observed = None
    if args.observed:
        names = [name.strip() for name in args.observed.split(",") if name.strip()]
        observed = {timestamp: names for timestamp in grid}

    report = enumerate_population(
        evidence=evidence,
        target_workload={
            "api_group": "apps",
            "kind": "Deployment",
            "namespace": args.namespace,
            "name": args.name,
        },
        timestamps=grid,
        observed_pods_by_timestamp=observed,
    )

    enumerated = unknown = 0
    reasons: dict[str, int] = {}
    print(f"\n{len(grid)} timestamps on the grid\n")
    for timestamp in grid:
        entry = report["timestamps"][timestamp]
        if entry["status"] == "UNKNOWN":
            unknown += 1
            reasons[entry["reason"]] = reasons.get(entry["reason"], 0) + 1
            print(f"  {timestamp}  UNKNOWN  {entry['reason']}")
            continue
        enumerated += 1
        pods = ",".join(item["pod"] for item in entry["owned_pods"]) or "(empty)"
        line = f"  {timestamp}  ENUMERATED  rs={','.join(entry['replicasets'])}  pods={pods}"
        if "comparison" in entry:
            line += f"  -> {entry['comparison']['verdict']}"
        print(line)

    print(f"\nenumerated={enumerated}  unknown={unknown}")
    for reason, count in sorted(reasons.items()):
        print(f"  {reason}: {count}")

    print("\nJSON report follows:")
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
