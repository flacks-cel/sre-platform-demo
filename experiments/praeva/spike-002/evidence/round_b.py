#!/usr/bin/env python3
"""Praeva Spike 002 - Round B collector.

Round B observes HPA scale-out from one pod to N=3 and compares the resulting
per-pod CPU evidence with the mature Round A baseline.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence import (
    COLLECTION_SECONDS,
    CONTAINER,
    COVERAGE_FLOOR,
    EXPECTED_N,
    LONG_WINDOW_SECONDS,
    NAMESPACE,
    SCRAPE_SECONDS,
    WORKLOAD,
    application_state,
    current_pods,
    eligible_endpoints_live,
    first_after,
    git_head,
    hpa_bounds,
    iso_utc,
    kubectl,
    last_before,
    metrics_api_available,
    nearest,
    parse_iso,
    pod_map,
    prom_query_range,
    prom_ready,
    scrape_interval,
    series_queries,
)


@dataclass(frozen=True)
class Phase:
    name: str
    start: float
    end: float


def _current_hpa_replicas() -> tuple[int, int]:
    raw = kubectl(["get", "hpa", WORKLOAD, "-n", NAMESPACE, "-o", "json"])
    hpa = json.loads(raw)
    status = hpa.get("status", {})
    return int(status.get("currentReplicas", 0) or 0), int(status.get("desiredReplicas", 0) or 0)


def preflight_b(args: argparse.Namespace) -> int:
    deadline = time.time() + args.wait_seconds
    expected_revision = args.expected_revision or git_head()
    stable_streak = 0

    while True:
        reasons: list[str] = []
        if not prom_ready(args.prometheus_url):
            reasons.append("Prometheus not ready")

        app = application_state()
        if app["sync"] != "Synced" or app["health"] != "Healthy":
            reasons.append(f"ArgoCD {app['sync']}/{app['health']}")
        if app["revision"] != expected_revision:
            reasons.append(
                f"ArgoCD revision={app['revision'][:12]} expected={expected_revision[:12]}"
            )

        min_rep, max_rep = hpa_bounds()
        if (min_rep, max_rep) != (1, EXPECTED_N):
            reasons.append(f"HPA bounds={min_rep}/{max_rep}, expected=1/{EXPECTED_N}")

        current_rep, desired_rep = _current_hpa_replicas()
        if current_rep != 1 or desired_rep != 1:
            reasons.append(
                f"HPA current/desired={current_rep}/{desired_rep}, expected=1/1 before T0(B)"
            )

        pods = current_pods()
        pod_names = {item["metadata"]["name"] for item in pods}
        ready_names: set[str] = set()
        bad_restarts: list[str] = []

        for item in pods:
            statuses = item.get("status", {}).get("containerStatuses", [])
            status = next((s for s in statuses if s.get("name") == CONTAINER), None)
            if status and status.get("ready") is True:
                ready_names.add(item["metadata"]["name"])
            if status and int(status.get("restartCount", 0)) != 0:
                bad_restarts.append(f"{item['metadata']['name']}={status.get('restartCount')}")

        if len(pod_names) != 1 or len(ready_names) != 1:
            reasons.append(f"pods={len(pod_names)} ready={len(ready_names)}, expected=1/1")
        if bad_restarts:
            reasons.append("restarts: " + ", ".join(bad_restarts))

        endpoints = eligible_endpoints_live()
        if endpoints != ready_names or len(endpoints) != 1:
            reasons.append(f"eligible endpoints={len(endpoints)} ready pods={len(ready_names)}")

        if scrape_interval() != "15s":
            reasons.append(f"scrape interval={scrape_interval()}, expected=15s")
        if not metrics_api_available():
            reasons.append("Metrics API unavailable")

        if reasons:
            stable_streak = 0
        else:
            stable_streak += 1

        stamp = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        print(f"[{stamp}] Round B preflight", flush=True)
        print(
            f"  ArgoCD={app['sync']}/{app['health']} revision={app['revision'][:12]} "
            f"target={app['target_revision']}",
            flush=True,
        )
        print(
            f"  HPA min/max={min_rep}/{max_rep} current/desired={current_rep}/{desired_rep}",
            flush=True,
        )
        print(f"  pods={sorted(pod_names)}", flush=True)
        print(f"  eligible endpoints={sorted(endpoints)}", flush=True)
        print(f"  stable streak={stable_streak}/{args.stable_polls}", flush=True)

        if not reasons and stable_streak >= args.stable_polls:
            print("PRE-FLIGHT B: PASS", flush=True)
            return 0

        if reasons:
            print("  waiting: " + "; ".join(reasons), flush=True)

        if time.time() >= deadline:
            print("PRE-FLIGHT B: FAIL (timeout)", file=sys.stderr, flush=True)
            return 1

        time.sleep(args.poll_seconds)


def _series_by_label(series: list[Any], label: str) -> dict[str, list[tuple[float, float]]]:
    result: dict[str, list[tuple[float, float]]] = {}
    for item in series:
        key = item.metric.get(label)
        if key:
            result[key] = item.values
    return result


def _metric_metadata(series: list[Any], key_label: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for item in series:
        key = item.metric.get(key_label)
        if key and key not in result:
            result[key] = dict(item.metric)
    return result


def _endpoint_sets(
    endpoint_series: list[Any], start: float, end: float
) -> list[tuple[float, set[str]]]:
    timestamps: set[float] = set()
    for item in endpoint_series:
        timestamps.update(ts for ts, _ in item.values if start <= ts <= end)

    points: list[tuple[float, set[str]]] = []
    for ts in sorted(timestamps):
        active: set[str] = set()
        for item in endpoint_series:
            target = item.metric.get("targetref_name")
            if not target:
                continue
            value = nearest(item.values, ts, tolerance=1.0)
            if value is not None and value > 0:
                active.add(target)
        points.append((ts, active))
    return points


def _phase_summary(
    phase: Phase,
    pods: list[str],
    matrices: dict[str, dict[str, list[tuple[float, float]]]],
    created: dict[str, float],
    owners: dict[str, dict[str, str]],
) -> dict[str, Any]:
    expected_samples = LONG_WINDOW_SECONDS / SCRAPE_SECONDS
    result: dict[str, Any] = {}

    for pod in pods:
        cpu_short = matrices["cpu_rate_short"].get(pod, [])
        req_short = matrices["request_rate_short"].get(pod, [])
        coverage = matrices["coverage_long"].get(pod, [])
        limits = matrices["limit_cpu"].get(pod, [])
        throttle = matrices["throttle_short"].get(pod, [])
        cpu_counter = matrices["cpu_counter"].get(pod, [])
        req_counter = matrices["request_counter"].get(pod, [])
        restart_series = matrices["restarts"].get(pod, [])

        cost_samples: list[float] = []
        covered_cost_samples: list[float] = []
        coverage_samples: list[float] = []
        throttle_samples: list[float] = []
        unknown_limit = 0
        worst_cpu_utilization: float | None = None
        worst_cpu_point: dict[str, Any] | None = None

        for ts, cpu_rate in cpu_short:
            if not (phase.start <= ts <= phase.end):
                continue

            req_rate = nearest(req_short, ts)
            cov_count = nearest(coverage, ts)
            limit = nearest(limits, ts)
            thr = nearest(throttle, ts)
            cov_ratio = cov_count / expected_samples if cov_count is not None else 0.0
            coverage_samples.append(cov_ratio)

            if thr is not None:
                throttle_samples.append(thr)

            if req_rate is not None and req_rate > 0:
                cost = cpu_rate / req_rate
                if math.isfinite(cost):
                    cost_samples.append(cost)
                    if cov_ratio >= COVERAGE_FLOOR:
                        covered_cost_samples.append(cost)

            if limit is None or limit <= 0:
                unknown_limit += 1
            else:
                utilization = cpu_rate / limit
                if worst_cpu_utilization is None or utilization > worst_cpu_utilization:
                    worst_cpu_utilization = utilization
                    worst_cpu_point = {
                        "time": iso_utc(ts),
                        "cpu_rate_cores": cpu_rate,
                        "cpu_limit_cores": limit,
                        "cpu_limit_ratio": utilization,
                        "coverage": cov_ratio,
                        "request_rate": req_rate,
                    }

        cpu_first = first_after(cpu_counter, phase.start)
        cpu_last = last_before(cpu_counter, phase.end)
        req_first = first_after(req_counter, phase.start)
        req_last = last_before(req_counter, phase.end)

        span_cost: float | None = None
        cpu_delta: float | None = None
        request_delta: float | None = None

        if cpu_first and cpu_last and req_first and req_last:
            effective_start = max(cpu_first[0], req_first[0])
            effective_end = min(cpu_last[0], req_last[0])
            if effective_end > effective_start:
                cpu_start = first_after(cpu_counter, effective_start)
                cpu_end = last_before(cpu_counter, effective_end)
                req_start = first_after(req_counter, effective_start)
                req_end = last_before(req_counter, effective_end)
                if cpu_start and cpu_end and req_start and req_end:
                    cpu_delta = cpu_end[1] - cpu_start[1]
                    request_delta = req_end[1] - req_start[1]
                    if cpu_delta >= 0 and request_delta > 0:
                        span_cost = cpu_delta / request_delta

        restart_values = [value for ts, value in restart_series if phase.start <= ts <= phase.end]

        creation = created.get(pod)
        owner = owners.get(pod, {})
        result[pod] = {
            "created_at": iso_utc(creation) if creation else None,
            "age_seconds_at_phase_start": max(0.0, phase.start - creation) if creation else None,
            "replicaset": owner.get("owner_name"),
            "cpu_cost_rate_samples": len(cost_samples),
            "cpu_cost_rate_median": statistics.median(cost_samples) if cost_samples else None,
            "cpu_cost_rate_max": max(cost_samples) if cost_samples else None,
            "covered_cpu_cost_rate_samples": len(covered_cost_samples),
            "covered_cpu_cost_rate_median": (
                statistics.median(covered_cost_samples) if covered_cost_samples else None
            ),
            "coverage_min": min(coverage_samples) if coverage_samples else None,
            "coverage_median": statistics.median(coverage_samples) if coverage_samples else None,
            "throttle_ratio_max": max(throttle_samples) if throttle_samples else None,
            "unknown_limit_points": unknown_limit,
            "cpu_limit_ratio_max": worst_cpu_utilization,
            "worst_cpu_point": worst_cpu_point,
            "span_cpu_seconds": cpu_delta,
            "span_requests": request_delta,
            "span_cost": span_cost,
            "restart_max": max(restart_values) if restart_values else None,
        }

    return result


def _pooled_distribution(per_pod: dict[str, Any]) -> dict[str, Any]:
    requests = {
        pod: float(data["span_requests"])
        for pod, data in per_pod.items()
        if data.get("span_requests") is not None and data["span_requests"] > 0
    }
    n_total = sum(requests.values())
    k = len(requests)
    output: dict[str, Any] = {"n": n_total, "k": k, "pods": requests}

    if k > 1 and n_total > 0:
        expected = n_total / k
        sigma = math.sqrt(expected * (1.0 - 1.0 / k))
        low = max(0.0, expected - 3.0 * sigma)
        high = expected + 3.0 * sigma
        output.update(
            {
                "expected_per_pod": expected,
                "sigma": sigma,
                "low": low,
                "high": high,
                "within_band": {pod: low <= value <= high for pod, value in requests.items()},
            }
        )
    return output


def _compare_to_baseline(value: float | None, baseline: dict[str, Any]) -> str:
    if value is None:
        return "UNKNOWN"
    low = baseline.get("low")
    high = baseline.get("high")
    if low is None or high is None:
        return "UNKNOWN"
    if value < float(low):
        return "below"
    if value > float(high):
        return "above"
    return "within"


def collect_b(args: argparse.Namespace) -> int:
    start = parse_iso(args.start)
    end = parse_iso(args.end)
    if end <= start:
        raise RuntimeError("end must be after start")

    baseline_path = Path(args.baseline_json)
    if not baseline_path.exists():
        raise RuntimeError(f"baseline JSON not found: {baseline_path}")
    baseline_report = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline = baseline_report.get("baseline", {})
    baseline_cost = baseline.get("cpu_cost_rate", {})
    baseline_span = baseline.get("span_cost", {})

    queries = series_queries()
    matrices = {
        name: pod_map(prom_query_range(args.prometheus_url, query, start, end))
        for name, query in queries.items()
    }

    endpoint_query = (
        'kube_endpointslice_endpoints{namespace="app",targetref_kind="Pod",'
        'ready="true",serving="true",terminating="false"}'
    )
    endpoint_series = prom_query_range(args.prometheus_url, endpoint_query, start, end)
    endpoint_points = _endpoint_sets(endpoint_series, start, end)

    created_series = prom_query_range(
        args.prometheus_url,
        'kube_pod_created{namespace="app",pod=~"jobs-api-.*"}',
        start,
        end,
    )
    owner_series = prom_query_range(
        args.prometheus_url,
        'kube_pod_owner{namespace="app",pod=~"jobs-api-.*",owner_kind="ReplicaSet"}',
        start,
        end,
    )
    created_map_raw = _series_by_label(created_series, "pod")
    created = {pod: values[0][1] for pod, values in created_map_raw.items() if values}
    owners = _metric_metadata(owner_series, "pod")

    pods = sorted(
        set(matrices["cpu_rate_short"])
        | set(matrices["request_rate_short"])
        | set(matrices["cpu_counter"])
        | set(created)
    )

    changes: list[dict[str, Any]] = []
    previous: set[str] | None = None
    first_scale: float | None = None
    last_change: float | None = None

    for ts, endpoints in endpoint_points:
        if previous is None or endpoints != previous:
            changes.append({"time": iso_utc(ts), "pods": sorted(endpoints), "k": len(endpoints)})
            if previous is not None:
                last_change = ts
            previous = set(endpoints)
        if first_scale is None and len(endpoints) > 1:
            first_scale = ts

    coverage_matrix = matrices["coverage_long"]
    expected_samples = LONG_WINDOW_SECONDS / SCRAPE_SECONDS
    steady_start: float | None = None

    for ts, endpoints in endpoint_points:
        if len(endpoints) != EXPECTED_N:
            continue
        if last_change is not None and ts <= last_change:
            continue

        complete = True
        for pod in endpoints:
            cov_count = nearest(coverage_matrix.get(pod, []), ts)
            cov_ratio = cov_count / expected_samples if cov_count is not None else 0.0
            if cov_ratio < COVERAGE_FLOOR:
                complete = False
                break
        if complete:
            steady_start = ts
            break

    phases: list[Phase] = []
    if first_scale is None:
        phases.append(Phase("pre-scale", start, end))
    else:
        if first_scale > start:
            phases.append(Phase("pre-scale", start, first_scale))
        if steady_start is not None and steady_start > first_scale:
            phases.append(Phase("scale-up", first_scale, steady_start))
            if end > steady_start:
                phases.append(Phase("steady-state", steady_start, end))
        else:
            phases.append(Phase("scale-up", first_scale, end))

    phase_reports: dict[str, Any] = {}
    for phase in phases:
        per_pod = _phase_summary(phase, pods, matrices, created, owners)
        phase_report: dict[str, Any] = {
            "start": iso_utc(phase.start),
            "end": iso_utc(phase.end),
            "per_pod": per_pod,
        }
        if phase.name == "steady-state":
            phase_report["pooled_request_distribution"] = _pooled_distribution(per_pod)
        phase_reports[phase.name] = phase_report

    scale_report = phase_reports.get("scale-up", {})
    scale_pods = scale_report.get("per_pod", {})
    worst_scale_pod: str | None = None
    worst_scale_ratio = -1.0
    for pod, data in scale_pods.items():
        value = data.get("cpu_limit_ratio_max")
        if value is not None and float(value) > worst_scale_ratio:
            worst_scale_ratio = float(value)
            worst_scale_pod = pod

    scale_interpretation: dict[str, Any] = {
        "worst_pod": worst_scale_pod,
        "request_test": "low-power-not-decisive-by-preregistered-limitation",
        "matrix": "UNKNOWN",
    }
    if worst_scale_pod:
        data = scale_pods[worst_scale_pod]
        point = data.get("worst_cpu_point") or {}
        coverage = point.get("coverage")
        span_cmp = _compare_to_baseline(data.get("span_cost"), baseline_span)
        scale_interpretation.update(
            {
                "coverage_at_worst_cpu": coverage,
                "span_cost": data.get("span_cost"),
                "span_cost_vs_baseline": span_cmp,
                "cpu_limit_ratio_max": data.get("cpu_limit_ratio_max"),
            }
        )
        if coverage is not None and coverage < COVERAGE_FLOOR:
            if span_cmp == "within":
                scale_interpretation["matrix"] = "A1-compatible"
            elif span_cmp == "above":
                scale_interpretation["matrix"] = "A2-compatible"
            else:
                scale_interpretation["matrix"] = "B/UNKNOWN"

    steady_report = phase_reports.get("steady-state", {})
    steady_pods = steady_report.get("per_pod", {})
    steady_interpretation: dict[str, Any] = {"matrix": "not-available"}
    if steady_pods:
        candidates = [
            (pod, data.get("covered_cpu_cost_rate_median"))
            for pod, data in steady_pods.items()
            if data.get("covered_cpu_cost_rate_median") is not None
        ]
        if candidates:
            worst_steady_pod, worst_cost = max(candidates, key=lambda item: float(item[1]))
            cost_cmp = _compare_to_baseline(float(worst_cost), baseline_cost)
            distribution = steady_report.get("pooled_request_distribution", {})
            within_band = distribution.get("within_band", {})
            requests_within = bool(within_band) and all(
                bool(value) for value in within_band.values()
            )
            worst_req_above = False
            high = distribution.get("high")
            if high is not None:
                pod_requests = distribution.get("pods", {}).get(worst_steady_pod)
                if pod_requests is not None:
                    worst_req_above = float(pod_requests) > float(high)

            matrix = "UNKNOWN"
            if requests_within and cost_cmp == "within":
                matrix = "C"
            elif worst_req_above and cost_cmp == "within":
                matrix = "D"
            elif requests_within and cost_cmp == "above":
                matrix = "E"

            steady_interpretation = {
                "matrix": matrix,
                "worst_pod": worst_steady_pod,
                "worst_pod_cost_median": worst_cost,
                "cost_vs_baseline": cost_cmp,
                "requests_within_band": requests_within,
                "pooled_request_distribution": distribution,
            }

    reached_n = any(len(pods_at_t) == EXPECTED_N for _, pods_at_t in endpoint_points)
    restarts = {
        pod: max((value for _, value in matrices["restarts"].get(pod, [])), default=0.0)
        for pod in pods
    }
    unknown_points = sum(
        int(data.get("unknown_limit_points", 0))
        for phase in phase_reports.values()
        for data in phase.get("per_pod", {}).values()
    )

    report = {
        "spike": "002",
        "round": "B",
        "git_head": git_head(),
        "baseline_json": str(baseline_path),
        "start": iso_utc(start),
        "end": iso_utc(end),
        "parameters": {
            "N": EXPECTED_N,
            "arrival_rate_rps": 0.75,
            "iterations_per_request": 1_000_000,
            "short_window": "2m",
            "long_window": "5m",
            "scrape_seconds": SCRAPE_SECONDS,
            "collection_seconds": COLLECTION_SECONDS,
            "coverage_floor": COVERAGE_FLOOR,
        },
        "endpoint_changes": changes,
        "first_scale": iso_utc(first_scale) if first_scale else None,
        "steady_state_start": iso_utc(steady_start) if steady_start else None,
        "reached_N": reached_n,
        "unknown_limit_points": unknown_points,
        "restarts": restarts,
        "phases": phase_reports,
        "scale_up_interpretation": scale_interpretation,
        "steady_state_interpretation": steady_interpretation,
        "comparison_status": "comparable"
        if reached_n and steady_start is not None
        else "inconclusive-for-AxB",
    }

    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print("===== ROUND B EVIDENCE =====")
    print(f"start={report['start']}")
    print(f"end={report['end']}")
    print(f"git_head={report['git_head']}")
    print(f"baseline_json={report['baseline_json']}")
    print(f"reached_N={report['reached_N']}")
    print(f"first_scale={report['first_scale']}")
    print(f"steady_state_start={report['steady_state_start']}")
    print(f"comparison_status={report['comparison_status']}")
    print(f"unknown_limit_points={report['unknown_limit_points']}")
    print("endpoint_changes=" + json.dumps(changes, sort_keys=True))
    print()

    for phase_name, phase in phase_reports.items():
        print(f"--- phase={phase_name} {phase['start']} .. {phase['end']} ---")
        for pod, data in phase["per_pod"].items():
            print(
                f"{pod}: age_start={data['age_seconds_at_phase_start']} "
                f"coverage_min={data['coverage_min']} "
                f"cost_median={data['cpu_cost_rate_median']} "
                f"covered_cost_median={data['covered_cpu_cost_rate_median']} "
                f"span_cost={data['span_cost']} "
                f"cpu_limit_ratio_max={data['cpu_limit_ratio_max']} "
                f"throttle_max={data['throttle_ratio_max']} "
                f"restarts={data['restart_max']} "
                f"unknown_limit={data['unknown_limit_points']}"
            )
        if "pooled_request_distribution" in phase:
            print(
                "pooled_request_distribution="
                + json.dumps(phase["pooled_request_distribution"], sort_keys=True)
            )
        print()

    print("scale_up_interpretation=" + json.dumps(scale_interpretation, sort_keys=True))
    print("steady_state_interpretation=" + json.dumps(steady_interpretation, sort_keys=True))
    if args.output:
        print(f"output={args.output}")

    if any(value > 0 for value in restarts.values()):
        print("ERROR: restart observed in Round B", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Praeva Spike 002 Round B evidence collector")
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight-b", help="wait until Round B is synced and stably at k=1")
    preflight.add_argument("--prometheus-url", default="http://localhost:19091")
    preflight.add_argument("--expected-revision", default=None)
    preflight.add_argument("--wait-seconds", type=int, default=900)
    preflight.add_argument("--poll-seconds", type=int, default=15)
    preflight.add_argument("--stable-polls", type=int, default=4)
    preflight.set_defaults(func=preflight_b)

    collect = sub.add_parser("collect-b", help="collect and phase Round B evidence")
    collect.add_argument("--prometheus-url", default="http://localhost:19091")
    collect.add_argument("--start", required=True)
    collect.add_argument("--end", required=True)
    collect.add_argument("--baseline-json", required=True)
    collect.add_argument("--output", default=None)
    collect.set_defaults(func=collect_b)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
