#!/usr/bin/env python3
"""Praeva Spike 001 - CPU Evidence.

Collect reproducible CPU evidence for jobs-api from Prometheus and Kubernetes.
No risk classification is performed in this spike.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DEFAULT_PROMETHEUS_URL = "http://localhost:9091"
DEFAULT_API_URL = "http://localhost:8081"
DEFAULT_NAMESPACE = "app"
DEFAULT_WORKLOAD = "jobs-api"
DEFAULT_CONTAINER = "jobs-api"
DEFAULT_WINDOW = "6h"
DEFAULT_LAG_SECONDS = 120


@dataclass(frozen=True)
class PromResult:
    metric: dict[str, str]
    value: float | None
    raw_value: str


def utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def parse_iso8601(value: str) -> float:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def parse_duration_seconds(value: str) -> float | None:
    value = value.strip()
    multipliers = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    for suffix in ("ms", "s", "m", "h"):
        if value.endswith(suffix):
            try:
                return float(value[: -len(suffix)]) * multipliers[suffix]
            except ValueError:
                return None
    return None


def prom_get(
    base_url: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    url = base_url.rstrip("/") + path
    if params:
        encoded = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{encoded}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Prometheus request failed: {url}: {exc}") from exc
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus returned non-success for {url}: {payload}")
    return payload.get("data")


def prom_query(
    base_url: str,
    query: str,
    evaluation_time: float,
) -> list[PromResult]:
    params = {"query": query, "time": f"{evaluation_time:.3f}"}
    data = prom_get(base_url, "/api/v1/query", params)
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected Prometheus response: {data!r}")
    if data.get("resultType") != "vector":
        result_type = data.get("resultType")
        raise RuntimeError(
            f"Expected vector result, got {result_type!r} for query: {query}"
        )

    results: list[PromResult] = []
    for item in data.get("result", []):
        raw_value = str(item.get("value", [None, ""])[1])
        try:
            number = float(raw_value)
            if math.isnan(number) or math.isinf(number):
                number = None
        except (TypeError, ValueError):
            number = None
        results.append(
            PromResult(
                metric=dict(item.get("metric", {})),
                value=number,
                raw_value=raw_value,
            )
        )
    return results


def run_kubectl(args: list[str], *, allow_failure: bool = False) -> str:
    command = ["kubectl", *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        if allow_failure:
            return f"<kubectl unavailable: {exc}>"
        raise RuntimeError(f"kubectl failed to execute: {exc}") from exc

    if completed.returncode != 0:
        if allow_failure:
            stderr = completed.stderr.strip() or f"exit {completed.returncode}"
            return f"<kubectl failed: {stderr}>"
        raise RuntimeError(
            f"{' '.join(command)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def kubernetes_deployment(
    namespace: str,
    workload: str,
) -> dict[str, Any] | None:
    text = run_kubectl(
        ["get", "deployment", workload, "-n", namespace, "-o", "json"],
        allow_failure=True,
    )
    if text.startswith("<kubectl"):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def find_container(
    deployment: dict[str, Any] | None,
    container_name: str,
) -> dict[str, Any] | None:
    if not deployment:
        return None
    pod_spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
    containers = pod_spec.get("containers", [])
    for container in containers:
        if container.get("name") == container_name:
            return container
    return None


def group_by_pod(
    results: Iterable[PromResult],
    *,
    choose: str = "max",
) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for result in results:
        pod = result.metric.get("pod", "<no-pod>")
        if result.value is not None:
            grouped[pod].append(result.value)

    output: dict[str, float] = {}
    for pod, values in grouped.items():
        output[pod] = max(values) if choose == "max" else min(values)
    return output


def series_identity(metric: dict[str, str]) -> str:
    interesting = ["pod", "container", "instance", "id", "image", "name"]
    parts = [f"{key}={metric[key]}" for key in interesting if key in metric]
    return ", ".join(parts) if parts else json.dumps(metric, sort_keys=True)


def metric_selector(
    namespace: str,
    pod_regex: str,
    container: str,
    metric_name: str,
) -> str:
    return (
        f'{metric_name}{{namespace="{namespace}",pod=~"{pod_regex}",'
        f'container="{container}",container!="",container!="POD"}}'
    )


def relevant_scrape_targets(base_url: str) -> list[dict[str, Any]]:
    data = prom_get(base_url, "/api/v1/targets", {"state": "active"})
    targets = data.get("activeTargets", []) if isinstance(data, dict) else []
    relevant = []
    for target in targets:
        scrape_url = str(target.get("scrapeUrl", ""))
        labels = target.get("labels", {}) or {}
        job = str(labels.get("job", ""))
        scrape_pool = str(target.get("scrapePool", ""))
        is_cadvisor = "/metrics/cadvisor" in scrape_url
        is_kubelet = "kubelet" in job.lower() or "kubelet" in scrape_pool.lower()
        if is_cadvisor or is_kubelet:
            relevant.append(target)
    return relevant


def print_header(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def print_mapping(mapping: dict[str, float], suffix: str = "") -> None:
    if not mapping:
        print("<no data>")
        return
    for pod, value in sorted(mapping.items()):
        print(f"{pod}: {value:.3f}{suffix}")


def collect(args: argparse.Namespace) -> int:
    if args.evaluation_time:
        evaluation_time = parse_iso8601(args.evaluation_time)
        time_source = "explicit"
    else:
        evaluation_time = time.time() - args.lag_seconds
        time_source = f"now - {args.lag_seconds}s"

    pod_regex = args.pod_regex or f"{args.workload}-.*"
    cpu_selector = metric_selector(
        args.namespace,
        pod_regex,
        args.container,
        "container_cpu_usage_seconds_total",
    )
    throttled_selector = metric_selector(
        args.namespace,
        pod_regex,
        args.container,
        "container_cpu_cfs_throttled_periods_total",
    )
    periods_selector = metric_selector(
        args.namespace,
        pod_regex,
        args.container,
        "container_cpu_cfs_periods_total",
    )

    build = prom_get(args.prometheus_url, "/api/v1/status/buildinfo")
    version = build.get("version", "<unknown>") if isinstance(build, dict) else "<unknown>"

    print("PRAEVA SPIKE 001 - CPU EVIDENCE")
    print("================================")
    print(f"Evaluation time: {utc_iso(evaluation_time)} ({time_source})")
    print(f"Prometheus:      {args.prometheus_url}")
    print(f"Prometheus ver.: {version}")
    print(f"Window:          {args.window}")
    print(f"Namespace:       {args.namespace}")
    print(f"Workload:        {args.workload}")
    print(f"Container:       {args.container}")
    print(f"Pod regex:       {pod_regex}  [spike-only selector]")

    print_header("KUBERNETES FACTS")
    deployment = kubernetes_deployment(args.namespace, args.workload)
    container = find_container(deployment, args.container)
    if deployment:
        spec_replicas = deployment.get("spec", {}).get("replicas")
        ready_replicas = deployment.get("status", {}).get("readyReplicas", 0)
        available = deployment.get("status", {}).get("availableReplicas", 0)
        print(
            "Deployment replicas (spec/ready/available): "
            f"{spec_replicas}/{ready_replicas}/{available}"
        )
    else:
        print("Deployment: <unavailable>")

    current_cpu_limit = None
    current_cpu_request = None
    if container:
        resources = container.get("resources", {})
        current_cpu_limit = resources.get("limits", {}).get("cpu")
        current_cpu_request = resources.get("requests", {}).get("cpu")
    print(f"Current CPU request: {current_cpu_request or '<not set/unavailable>'}")
    print(f"Current CPU limit:   {current_cpu_limit or '<not set/unavailable>'}")
    print("Current HPA snapshot:")
    hpa = run_kubectl(
        ["get", "hpa", args.workload, "-n", args.namespace],
        allow_failure=True,
    )
    print(hpa or "<none>")

    print_header("CADVISOR SCRAPE TARGETS")
    targets = relevant_scrape_targets(args.prometheus_url)
    if not targets:
        print("No kubelet/cAdvisor target detected via /api/v1/targets.")
    else:
        for target in targets:
            labels = target.get("labels", {}) or {}
            job = labels.get("job", "<unknown>")
            instance = labels.get("instance", "<unknown>")
            interval = target.get("scrapeInterval", "<unknown>")
            scrape_url = target.get("scrapeUrl", "<unknown>")
            print(
                f"job={job} instance={instance} interval={interval} "
                f"url={scrape_url}"
            )
        intervals = [
            parse_duration_seconds(str(target.get("scrapeInterval", "")))
            for target in targets
        ]
        numeric_intervals = [value for value in intervals if value is not None]
        if numeric_intervals and max(numeric_intervals) >= 60:
            print("WARNING: scrape interval >= 60s; rate[2m] may be unstable.")

    print_header("RAW SERIES AND SAMPLE COVERAGE")
    count_query = f"count(count_over_time({cpu_selector}[{args.window}]))"
    series_count = prom_query(args.prometheus_url, count_query, evaluation_time)
    count_value = 0.0
    if series_count and series_count[0].value is not None:
        count_value = series_count[0].value
    print(f"Historical series count: {int(count_value)}")

    sample_query = f"count_over_time({cpu_selector}[{args.window}])"
    sample_results = prom_query(args.prometheus_url, sample_query, evaluation_time)
    if not sample_results:
        print("No CPU samples found in the selected window.")
    for result in sorted(sample_results, key=lambda item: series_identity(item.metric)):
        value_text = result.raw_value
        if result.value is not None:
            value_text = str(int(result.value))
        print(f"samples={value_text:<6} {series_identity(result.metric)}")

    first_query = f"min_over_time(timestamp({cpu_selector})[{args.window}:1m])"
    last_query = f"max_over_time(timestamp({cpu_selector})[{args.window}:1m])"
    first_results = prom_query(args.prometheus_url, first_query, evaluation_time)
    last_results = prom_query(args.prometheus_url, last_query, evaluation_time)
    first_by_pod = group_by_pod(first_results, choose="min")
    last_by_pod = group_by_pod(last_results, choose="max")

    print("\nCoverage by pod (approximate from 1m subquery step):")
    pods = sorted(set(first_by_pod) | set(last_by_pod))
    if not pods:
        print("<no pod coverage data>")
    for pod in pods:
        first = first_by_pod.get(pod)
        last = last_by_pod.get(pod)
        first_text = utc_iso(first) if first is not None else "<unknown>"
        last_text = utc_iso(last) if last is not None else "<unknown>"
        print(f"{pod}: first={first_text} last={last_text}")

    print_header("REPLICASET HISTORY")
    owner_query = (
        f'max_over_time(kube_pod_owner{{namespace="{args.namespace}",'
        f'pod=~"{pod_regex}",owner_kind="ReplicaSet"}}[{args.window}])'
    )
    owner_results = prom_query(args.prometheus_url, owner_query, evaluation_time)
    if not owner_results:
        print("<no kube_pod_owner history available>")
    else:
        seen: set[tuple[str, str]] = set()
        for result in owner_results:
            pod = result.metric.get("pod", "<unknown>")
            owner = result.metric.get("owner_name", "<unknown>")
            key = (pod, owner)
            if key not in seen:
                seen.add(key)
                print(f"{pod}: {owner}")

    print_header("CPU RATE - PER POD")
    rate_summaries: dict[str, dict[str, float]] = {}
    for rate_window in args.rate_windows:
        p95_query = (
            "quantile_over_time(0.95, "
            f"rate({cpu_selector}[{rate_window}])[{args.window}:1m]) * 1000"
        )
        max_query = (
            "max_over_time("
            f"rate({cpu_selector}[{rate_window}])[{args.window}:1m]) * 1000"
        )
        p95_results = prom_query(args.prometheus_url, p95_query, evaluation_time)
        max_results = prom_query(args.prometheus_url, max_query, evaluation_time)
        p95 = group_by_pod(p95_results, choose="max")
        max_rate = group_by_pod(max_results, choose="max")
        rate_summaries[rate_window] = {
            "p95_worst": max(p95.values()) if p95 else math.nan,
            "max_worst": max(max_rate.values()) if max_rate else math.nan,
        }
        print(f"\nrate[{rate_window}] P95 (millicores):")
        print_mapping(p95, "m")
        print(f"rate[{rate_window}] maximum (millicores):")
        print_mapping(max_rate, "m")

    if "2m" in rate_summaries and "5m" in rate_summaries:
        max2 = rate_summaries["2m"]["max_worst"]
        max5 = rate_summaries["5m"]["max_worst"]
        if not math.isnan(max2) and not math.isnan(max5) and max2 != 0:
            hidden = (max2 - max5) / max2 * 100.0
            print(
                f"\n5m smoothing vs 2m max: {hidden:.2f}% lower "
                "(for this observed workload only)"
            )

    print_header("CPU THROTTLING - PER POD")
    throttle_query = (
        f"increase({throttled_selector}[{args.window}]) "
        f"/ increase({periods_selector}[{args.window}])"
    )
    throttle_results = prom_query(
        args.prometheus_url,
        throttle_query,
        evaluation_time,
    )
    throttling = group_by_pod(throttle_results, choose="max")
    if throttling:
        for pod, ratio in sorted(throttling.items()):
            print(f"{pod}: {ratio * 100:.3f}% throttled periods")
    else:
        print("<no throttling data>")

    print_header("SATURATION SANITY FACTS")
    print("No pass/fail or risk classification is performed.")
    if current_cpu_limit:
        print(f"Configured CPU limit: {current_cpu_limit}")
    for rate_window in args.rate_windows:
        max_value = rate_summaries.get(rate_window, {}).get("max_worst", math.nan)
        if not math.isnan(max_value):
            print(f"Worst observed max rate[{rate_window}]: {max_value:.3f}m")
    if throttling:
        worst_ratio = max(throttling.values()) * 100
        print(f"Worst throttled-period ratio: {worst_ratio:.3f}%")

    print_header("REFERENCE SNAPSHOT")
    print(
        "kubectl top is a sanity reference only; its sampling/window can differ "
        "from Prometheus."
    )
    top_output = run_kubectl(
        [
            "top",
            "pod",
            "-n",
            args.namespace,
            "-l",
            f"app={args.workload}",
            "--containers",
        ],
        allow_failure=True,
    )
    print(top_output or "<no output>")

    print_header("SPIKE NOTES")
    print("- No risk classification performed.")
    print("- No evidence-quality grade performed.")
    print("- No safe CPU capacity recommendation performed.")
    print("- The default pod regex is spike-only and must not become the product selector.")
    return 0


def replica_snapshot(namespace: str, workload: str) -> str:
    deployment = kubernetes_deployment(namespace, workload)
    if not deployment:
        return "unavailable"
    spec = deployment.get("spec", {}).get("replicas")
    status = deployment.get("status", {})
    ready = status.get("readyReplicas", 0)
    available = status.get("availableReplicas", 0)
    return f"spec={spec} ready={ready} available={available}"


def top_sampler(
    stop: threading.Event,
    namespace: str,
    workload: str,
    interval: float,
    observations: list[tuple[float, str]],
) -> None:
    while not stop.is_set():
        ts = time.time()
        text = run_kubectl(
            [
                "top",
                "pod",
                "-n",
                namespace,
                "-l",
                f"app={workload}",
                "--containers",
            ],
            allow_failure=True,
        )
        observations.append((ts, text))
        stop.wait(interval)


def burn_once(url: str, seconds: float) -> tuple[bool, str]:
    query = urllib.parse.urlencode({"seconds": f"{seconds:g}"})
    full_url = f"{url.rstrip('/')}/simulate/cpu?{query}"
    try:
        with urllib.request.urlopen(full_url, timeout=seconds + 15) as response:
            body = response.read().decode("utf-8", errors="replace")
        return True, body
    except Exception as exc:
        return False, str(exc)


def run_load(args: argparse.Namespace) -> int:
    if args.duration <= 0:
        raise RuntimeError("--duration must be > 0")
    if args.call_seconds <= 0 or args.call_seconds > 30:
        raise RuntimeError(
            "--call-seconds must be > 0 and <= 30 (jobs-api endpoint limit)"
        )

    print("PRAEVA SPIKE 001 - CONTROLLED CPU LOAD")
    print("========================================")
    print(f"API URL:          {args.api_url}")
    print(f"Target duration:  {args.duration:.0f}s")
    print(f"CPU call length:  {args.call_seconds:.0f}s")
    print(f"Top interval:     {args.top_interval:.0f}s")
    print(f"Replicas before:  {replica_snapshot(args.namespace, args.workload)}")

    stop = threading.Event()
    observations: list[tuple[float, str]] = []
    sampler = threading.Thread(
        target=top_sampler,
        args=(stop, args.namespace, args.workload, args.top_interval, observations),
        daemon=True,
    )
    sampler.start()

    start = time.time()
    calls: list[tuple[float, float, bool, str]] = []
    try:
        while time.time() - start < args.duration:
            remaining = args.duration - (time.time() - start)
            call_seconds = min(args.call_seconds, max(0.1, remaining))
            call_start = time.time()
            ok, detail = burn_once(args.api_url, call_seconds)
            call_end = time.time()
            calls.append((call_start, call_end, ok, detail))
    finally:
        stop.set()
        sampler.join(timeout=args.top_interval + 2)

    end = time.time()
    success_count = sum(1 for call in calls if call[2])
    failure_count = sum(1 for call in calls if not call[2])
    print(f"Started:          {utc_iso(start)}")
    print(f"Finished:         {utc_iso(end)}")
    print(f"Actual duration:  {end - start:.1f}s")
    print(
        f"Calls:            {len(calls)} "
        f"(success={success_count}, failed={failure_count})"
    )
    print(f"Replicas after:   {replica_snapshot(args.namespace, args.workload)}")

    print_header("KUBECTL TOP OBSERVATIONS")
    if not observations:
        print("<none>")
    for ts, text in observations:
        print(f"\n[{utc_iso(ts)}]\n{text}")

    failures = [call for call in calls if not call[2]]
    if failures:
        print_header("LOAD CALL FAILURES")
        for call_start, call_end, _, detail in failures:
            print(f"{utc_iso(call_start)} -> {utc_iso(call_end)}: {detail}")

    suggested_collect_at = end + max(args.collect_delay, 0)
    print_header("NEXT COLLECTION")
    print(
        "To avoid ingestion-edge instability, collect after "
        f"{utc_iso(suggested_collect_at)} with an evaluation T a little before "
        "collection time."
    )
    print("Example after the delay:")
    print(
        "  python experiments/praeva/spike-001/cpu_evidence.py collect "
        f"--lag-seconds {args.lag_seconds}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Praeva Spike 001 - CPU evidence"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    collect_p = sub.add_parser(
        "collect",
        help="Collect reproducible CPU evidence from Prometheus",
    )
    collect_p.add_argument("--prometheus-url", default=DEFAULT_PROMETHEUS_URL)
    collect_p.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    collect_p.add_argument("--workload", default=DEFAULT_WORKLOAD)
    collect_p.add_argument("--container", default=DEFAULT_CONTAINER)
    collect_p.add_argument("--pod-regex", default=None)
    collect_p.add_argument("--window", default=DEFAULT_WINDOW)
    collect_p.add_argument("--rate-windows", nargs="+", default=["2m", "5m"])
    collect_p.add_argument(
        "--evaluation-time",
        default=None,
        help="ISO-8601 UTC timestamp, e.g. 2026-10-09T12:30:00Z",
    )
    collect_p.add_argument(
        "--lag-seconds",
        type=int,
        default=DEFAULT_LAG_SECONDS,
    )
    collect_p.set_defaults(func=collect)

    load_p = sub.add_parser(
        "load",
        help="Run one controlled CPU-load round while sampling kubectl top",
    )
    load_p.add_argument("--api-url", default=DEFAULT_API_URL)
    load_p.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    load_p.add_argument("--workload", default=DEFAULT_WORKLOAD)
    load_p.add_argument(
        "--duration",
        type=float,
        required=True,
        help="Total round duration in seconds (30 burst, 600 sustained)",
    )
    load_p.add_argument(
        "--call-seconds",
        type=float,
        default=30.0,
        help="Each /simulate/cpu request duration, max 30s",
    )
    load_p.add_argument("--top-interval", type=float, default=10.0)
    load_p.add_argument(
        "--collect-delay",
        type=float,
        default=180.0,
        help="Suggested wait before collection, seconds",
    )
    load_p.add_argument(
        "--lag-seconds",
        type=int,
        default=DEFAULT_LAG_SECONDS,
    )
    load_p.set_defaults(func=run_load)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
