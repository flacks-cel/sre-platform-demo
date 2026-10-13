#!/usr/bin/env python3
"""Praeva Spike 002 evidence collector.

This collector is intentionally separate from Spike 001. It implements the
preflight and baseline calculations required for Round A. It does not classify
risk or recommend CPU values.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_PROMETHEUS_URL = "http://localhost:19091"
NAMESPACE = "app"
WORKLOAD = "jobs-api"
CONTAINER = "jobs-api"
EXPECTED_N = 3
SCRAPE_SECONDS = 15
COLLECTION_SECONDS = 15
COVERAGE_FLOOR = 0.80
SHORT_WINDOW = "2m"
LONG_WINDOW = "5m"
LONG_WINDOW_SECONDS = 300
WARMUP_SECONDS = 60
LOAD_HANDLER = "/simulate/cpu-work"


@dataclass(frozen=True)
class Series:
    metric: dict[str, str]
    values: list[tuple[float, float]]


def iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> float:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def prom_get(base_url: str, path: str, params: dict[str, Any] | None = None) -> Any:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Prometheus request failed: {url}: {exc}") from exc
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus returned non-success: {payload}")
    return payload.get("data")


def prom_ready(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/-/ready", timeout=5) as response:
            return response.status == 200
    except urllib.error.URLError:
        return False


def prom_query(base_url: str, query: str, evaluation_time: float | None = None) -> list[Series]:
    params: dict[str, Any] = {"query": query}
    if evaluation_time is not None:
        params["time"] = f"{evaluation_time:.3f}"
    data = prom_get(base_url, "/api/v1/query", params)
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        raise RuntimeError(f"Expected vector for query: {query}")
    output: list[Series] = []
    for item in data.get("result", []):
        raw = item.get("value", [None, None])
        try:
            value = float(raw[1])
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            output.append(Series(dict(item.get("metric", {})), [(float(raw[0]), value)]))
    return output


def prom_query_range(
    base_url: str,
    query: str,
    start: float,
    end: float,
    step: int = COLLECTION_SECONDS,
) -> list[Series]:
    data = prom_get(
        base_url,
        "/api/v1/query_range",
        {
            "query": query,
            "start": f"{start:.3f}",
            "end": f"{end:.3f}",
            "step": str(step),
        },
    )
    if not isinstance(data, dict) or data.get("resultType") != "matrix":
        raise RuntimeError(f"Expected matrix for query: {query}")
    output: list[Series] = []
    for item in data.get("result", []):
        values: list[tuple[float, float]] = []
        for raw_ts, raw_value in item.get("values", []):
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values.append((float(raw_ts), value))
        output.append(Series(dict(item.get("metric", {})), values))
    return output


def kubectl(args: list[str], *, allow_failure: bool = False) -> str:
    completed = subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        if allow_failure:
            return ""
        raise RuntimeError(completed.stderr.strip() or f"kubectl exit={completed.returncode}")
    return completed.stdout.strip()


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return completed.stdout.strip()


def pod_map(series: list[Series], label: str = "pod") -> dict[str, list[tuple[float, float]]]:
    result: dict[str, list[tuple[float, float]]] = {}
    for item in series:
        pod = item.metric.get(label)
        if pod:
            result[pod] = item.values
    return result


def instant_map(series: list[Series], label: str = "pod") -> dict[str, float]:
    result: dict[str, float] = {}
    for item in series:
        key = item.metric.get(label)
        if key and item.values:
            result[key] = item.values[-1][1]
    return result


def nearest(values: list[tuple[float, float]], ts: float, tolerance: float = 8.0) -> float | None:
    if not values:
        return None
    point = min(values, key=lambda pair: abs(pair[0] - ts))
    return point[1] if abs(point[0] - ts) <= tolerance else None


def first_after(values: list[tuple[float, float]], ts: float) -> tuple[float, float] | None:
    for point in values:
        if point[0] >= ts:
            return point
    return None


def last_before(values: list[tuple[float, float]], ts: float) -> tuple[float, float] | None:
    for point in reversed(values):
        if point[0] <= ts:
            return point
    return None


def robust_range(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "n": 0,
            "median": None,
            "mad": None,
            "robust_sigma": None,
            "low": None,
            "high": None,
        }
    median = statistics.median(values)
    mad = statistics.median([abs(value - median) for value in values])
    robust_sigma = 1.4826 * mad
    return {
        "n": len(values),
        "median": median,
        "mad": mad,
        "robust_sigma": robust_sigma,
        "low": max(0.0, median - 3.0 * robust_sigma),
        "high": median + 3.0 * robust_sigma,
    }


def current_pods() -> list[dict[str, Any]]:
    raw = kubectl(["get", "pods", "-n", NAMESPACE, "-l", f"app={WORKLOAD}", "-o", "json"])
    return json.loads(raw).get("items", [])


def eligible_endpoints_live() -> set[str]:
    raw = kubectl(
        [
            "get",
            "endpointslice",
            "-n",
            NAMESPACE,
            "-l",
            f"kubernetes.io/service-name={WORKLOAD}",
            "-o",
            "json",
        ]
    )
    result: set[str] = set()
    for slice_item in json.loads(raw).get("items", []):
        for endpoint in slice_item.get("endpoints", []):
            conditions = endpoint.get("conditions", {})
            target = endpoint.get("targetRef", {})
            if (
                target.get("kind") == "Pod"
                and conditions.get("ready") is True
                and conditions.get("serving", True) is True
                and conditions.get("terminating", False) is not True
            ):
                name = target.get("name")
                if name:
                    result.add(name)
    return result


def application_state() -> dict[str, str]:
    raw = kubectl(["get", "application", WORKLOAD, "-n", "argocd", "-o", "json"])
    app = json.loads(raw)
    return {
        "sync": app.get("status", {}).get("sync", {}).get("status", ""),
        "health": app.get("status", {}).get("health", {}).get("status", ""),
        "revision": app.get("status", {}).get("sync", {}).get("revision", ""),
        "target_revision": app.get("spec", {}).get("source", {}).get("targetRevision", ""),
    }


def hpa_bounds() -> tuple[int, int]:
    raw = kubectl(["get", "hpa", WORKLOAD, "-n", NAMESPACE, "-o", "json"])
    hpa = json.loads(raw)
    return int(hpa["spec"]["minReplicas"]), int(hpa["spec"]["maxReplicas"])


def metrics_api_available() -> bool:
    raw = kubectl(["get", "apiservice", "v1beta1.metrics.k8s.io", "-o", "json"])
    api = json.loads(raw)
    for condition in api.get("status", {}).get("conditions", []):
        if condition.get("type") == "Available":
            return condition.get("status") == "True"
    return False


def scrape_interval() -> str:
    return kubectl(
        [
            "get",
            "servicemonitor",
            WORKLOAD,
            "-n",
            NAMESPACE,
            "-o",
            "jsonpath={.spec.endpoints[0].interval}",
        ]
    )


def coverage_now(base_url: str) -> dict[str, float]:
    expected = LONG_WINDOW_SECONDS / SCRAPE_SECONDS
    query = (
        'max by (pod) (count_over_time(container_cpu_usage_seconds_total{namespace="app",'
        'pod=~"jobs-api-.*",container="jobs-api",container!="POD"}[5m]))'
    )
    return {
        pod: value / expected for pod, value in instant_map(prom_query(base_url, query)).items()
    }


def preflight_a(args: argparse.Namespace) -> int:
    deadline = time.time() + args.wait_seconds
    expected_revision = args.expected_revision or git_head()

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
        if (min_rep, max_rep) != (EXPECTED_N, EXPECTED_N):
            reasons.append(f"HPA bounds={min_rep}/{max_rep}, expected=3/3")

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

        if len(pod_names) != EXPECTED_N or len(ready_names) != EXPECTED_N:
            reasons.append(f"pods={len(pod_names)} ready={len(ready_names)}, expected=3/3")
        if bad_restarts:
            reasons.append("restarts: " + ", ".join(bad_restarts))

        endpoints = eligible_endpoints_live()
        if endpoints != ready_names or len(endpoints) != EXPECTED_N:
            reasons.append(f"eligible endpoints={len(endpoints)} ready pods={len(ready_names)}")

        if scrape_interval() != "15s":
            reasons.append(f"scrape interval={scrape_interval()}, expected=15s")
        if not metrics_api_available():
            reasons.append("Metrics API unavailable")

        coverages = coverage_now(args.prometheus_url) if prom_ready(args.prometheus_url) else {}
        for pod in sorted(ready_names):
            value = coverages.get(pod, 0.0)
            if value < COVERAGE_FLOOR:
                reasons.append(f"coverage {pod}={value:.2%} < {COVERAGE_FLOOR:.0%}")

        stamp = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
        print(f"[{stamp}] Round A preflight")
        print(
            f"  ArgoCD={app['sync']}/{app['health']} revision={app['revision'][:12]} "
            f"target={app['target_revision']}"
        )
        print(f"  HPA min/max={min_rep}/{max_rep}; pods={sorted(pod_names)}")
        print(f"  eligible endpoints={sorted(endpoints)}")
        print(
            "  coverage="
            + ", ".join(f"{pod}:{coverages.get(pod, 0.0):.0%}" for pod in sorted(ready_names))
        )

        if not reasons:
            print("PRE-FLIGHT A: PASS")
            return 0

        print("  waiting: " + "; ".join(reasons))
        if time.time() >= deadline:
            print("PRE-FLIGHT A: FAIL (timeout)", file=sys.stderr)
            return 1
        time.sleep(args.poll_seconds)


def series_queries() -> dict[str, str]:
    container_selector = (
        'namespace="app",pod=~"jobs-api-.*",' 'container="jobs-api",container!="POD"'
    )
    req_selector = 'namespace="app",pod=~"jobs-api-.*",' 'handler="/simulate/cpu-work",method="GET"'

    cpu_metric = "container_cpu_usage_seconds_total"
    throttled_metric = "container_cpu_cfs_throttled_periods_total"
    periods_metric = "container_cpu_cfs_periods_total"

    return {
        "cpu_rate_short": (
            f"sum by (pod) (rate({cpu_metric}" f"{{{container_selector}}}[{SHORT_WINDOW}]))"
        ),
        "cpu_rate_long": (
            f"sum by (pod) (rate({cpu_metric}" f"{{{container_selector}}}[{LONG_WINDOW}]))"
        ),
        "request_rate_short": (
            "sum by (pod) (rate(http_requests_total" f"{{{req_selector}}}[{SHORT_WINDOW}]))"
        ),
        "request_rate_long": (
            "sum by (pod) (rate(http_requests_total" f"{{{req_selector}}}[{LONG_WINDOW}]))"
        ),
        "coverage_long": (
            "max by (pod) (count_over_time("
            f"{cpu_metric}{{{container_selector}}}[{LONG_WINDOW}]))"
        ),
        "limit_cpu": (
            "max by (pod) (kube_pod_container_resource_limits{"
            'namespace="app",container="jobs-api",resource="cpu"})'
        ),
        "throttle_short": (
            f"sum by (pod) (rate({throttled_metric}"
            f"{{{container_selector}}}[{SHORT_WINDOW}])) "
            f"/ sum by (pod) (rate({periods_metric}"
            f"{{{container_selector}}}[{SHORT_WINDOW}]))"
        ),
        "cpu_counter": (f"sum by (pod) ({cpu_metric}{{{container_selector}}})"),
        "request_counter": (f"sum by (pod) (http_requests_total{{{req_selector}}})"),
        "restarts": (
            "max by (pod) (kube_pod_container_status_restarts_total{"
            'namespace="app",container="jobs-api",pod=~"jobs-api-.*"})'
        ),
    }


def collect_a(args: argparse.Namespace) -> int:
    start = parse_iso(args.start)
    end = parse_iso(args.end)
    if end <= start:
        raise RuntimeError("end must be after start")
    analysis_start = start + args.warmup_seconds

    queries = series_queries()
    matrices = {
        name: pod_map(prom_query_range(args.prometheus_url, query, start, end))
        for name, query in queries.items()
    }

    expected_samples = LONG_WINDOW_SECONDS / SCRAPE_SECONDS
    pods = sorted(
        set(matrices["cpu_rate_short"])
        | set(matrices["request_rate_short"])
        | set(matrices["cpu_counter"])
    )

    per_pod: dict[str, Any] = {}
    all_cost_samples: list[float] = []
    all_span_costs: list[float] = []
    pooled_requests: dict[str, float] = {}

    for pod in pods:
        cpu_short = matrices["cpu_rate_short"].get(pod, [])
        req_short = matrices["request_rate_short"].get(pod, [])
        coverage = matrices["coverage_long"].get(pod, [])
        limits = matrices["limit_cpu"].get(pod, [])
        throttle = matrices["throttle_short"].get(pod, [])

        cost_samples: list[float] = []
        coverage_samples: list[float] = []
        throttle_samples: list[float] = []
        unknown_limit = 0

        for ts, cpu_rate in cpu_short:
            if ts < analysis_start:
                continue
            req_rate = nearest(req_short, ts)
            cov_count = nearest(coverage, ts)
            limit = nearest(limits, ts)
            thr = nearest(throttle, ts)
            cov_ratio = (cov_count / expected_samples) if cov_count is not None else 0.0
            coverage_samples.append(cov_ratio)
            if thr is not None:
                throttle_samples.append(thr)
            if limit is None:
                unknown_limit += 1
                continue
            if cov_ratio < COVERAGE_FLOOR or req_rate is None or req_rate <= 0:
                continue
            cost = cpu_rate / req_rate
            if math.isfinite(cost):
                cost_samples.append(cost)
                all_cost_samples.append(cost)

        cpu_counter = matrices["cpu_counter"].get(pod, [])
        req_counter = matrices["request_counter"].get(pod, [])
        cpu_first = first_after(cpu_counter, analysis_start)
        cpu_last = last_before(cpu_counter, end)
        req_first = first_after(req_counter, analysis_start)
        req_last = last_before(req_counter, end)

        span_cost: float | None = None
        request_delta: float | None = None
        cpu_delta: float | None = None
        if cpu_first and cpu_last and req_first and req_last:
            cpu_delta = cpu_last[1] - cpu_first[1]
            request_delta = req_last[1] - req_first[1]
            if cpu_delta >= 0 and request_delta > 0:
                span_cost = cpu_delta / request_delta
                all_span_costs.append(span_cost)
                pooled_requests[pod] = request_delta

        restart_values = [
            value for ts, value in matrices["restarts"].get(pod, []) if analysis_start <= ts <= end
        ]
        per_pod[pod] = {
            "cpu_cost_rate_samples": len(cost_samples),
            "cpu_cost_rate_median": statistics.median(cost_samples) if cost_samples else None,
            "cpu_cost_rate_max": max(cost_samples) if cost_samples else None,
            "coverage_min": min(coverage_samples) if coverage_samples else None,
            "coverage_median": statistics.median(coverage_samples) if coverage_samples else None,
            "throttle_ratio_max": max(throttle_samples) if throttle_samples else None,
            "unknown_limit_points": unknown_limit,
            "span_cpu_seconds": cpu_delta,
            "span_requests": request_delta,
            "span_cost": span_cost,
            "restart_max": max(restart_values) if restart_values else None,
        }

    n_total = sum(pooled_requests.values())
    k = len(pooled_requests)
    distribution: dict[str, Any] = {"n": n_total, "k": k, "pods": pooled_requests}
    if k > 1 and n_total > 0:
        expected = n_total / k
        sigma = math.sqrt(expected * (1.0 - 1.0 / k))
        low = max(0.0, expected - 3.0 * sigma)
        high = expected + 3.0 * sigma
        distribution.update(
            {
                "expected_per_pod": expected,
                "sigma": sigma,
                "low": low,
                "high": high,
                "within_band": {
                    pod: low <= value <= high for pod, value in pooled_requests.items()
                },
            }
        )

    baseline_cost = robust_range(all_cost_samples)
    baseline_span = robust_range(all_span_costs)

    report = {
        "spike": "002",
        "round": "A",
        "git_head": git_head(),
        "start": iso_utc(start),
        "end": iso_utc(end),
        "analysis_start_after_warmup": iso_utc(analysis_start),
        "parameters": {
            "N": EXPECTED_N,
            "arrival_rate_rps": 0.75,
            "iterations_per_request": 1_000_000,
            "warmup_seconds": args.warmup_seconds,
            "short_window": SHORT_WINDOW,
            "long_window": LONG_WINDOW,
            "scrape_seconds": SCRAPE_SECONDS,
            "collection_seconds": COLLECTION_SECONDS,
            "coverage_floor": COVERAGE_FLOOR,
        },
        "baseline": {
            "cpu_cost_rate": baseline_cost,
            "span_cost": baseline_span,
        },
        "pooled_request_distribution": distribution,
        "per_pod": per_pod,
    }

    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print("===== ROUND A EVIDENCE =====")
    print(f"start={report['start']}")
    print(f"end={report['end']}")
    print(f"analysis_start={report['analysis_start_after_warmup']}")
    print(f"git_head={report['git_head']}")
    print()
    for pod, data in per_pod.items():
        print(
            f"{pod}: samples={data['cpu_cost_rate_samples']} "
            f"cost_median={data['cpu_cost_rate_median']} span_cost={data['span_cost']} "
            f"coverage_min={data['coverage_min']} throttle_max={data['throttle_ratio_max']} "
            f"restarts={data['restart_max']} unknown_limit={data['unknown_limit_points']}"
        )
    print()
    print("baseline_cpu_cost_rate=" + json.dumps(baseline_cost, sort_keys=True))
    print("baseline_span_cost=" + json.dumps(baseline_span, sort_keys=True))
    print("pooled_request_distribution=" + json.dumps(distribution, sort_keys=True))
    if args.output:
        print(f"output={args.output}")

    if k != EXPECTED_N:
        print(f"ERROR: pooled baseline has k={k}, expected {EXPECTED_N}", file=sys.stderr)
        return 1
    if not all_span_costs or not all_cost_samples:
        print("ERROR: insufficient baseline evidence", file=sys.stderr)
        return 1
    if any((data.get("restart_max") or 0) > 0 for data in per_pod.values()):
        print("ERROR: restart observed in baseline", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Praeva Spike 002 evidence collector")
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight-a", help="wait for Round A maturity preconditions")
    preflight.add_argument("--prometheus-url", default=DEFAULT_PROMETHEUS_URL)
    preflight.add_argument("--expected-revision", default=None)
    preflight.add_argument("--wait-seconds", type=int, default=600)
    preflight.add_argument("--poll-seconds", type=int, default=15)
    preflight.set_defaults(func=preflight_a)

    collect = sub.add_parser("collect-a", help="collect Round A baseline after the load")
    collect.add_argument("--prometheus-url", default=DEFAULT_PROMETHEUS_URL)
    collect.add_argument("--start", required=True)
    collect.add_argument("--end", required=True)
    collect.add_argument("--warmup-seconds", type=int, default=WARMUP_SECONDS)
    collect.add_argument("--output", default=None)
    collect.set_defaults(func=collect_a)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
