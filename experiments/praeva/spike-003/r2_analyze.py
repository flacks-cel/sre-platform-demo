#!/usr/bin/env python3
"""Offline analyzer for PRAEVA SPIKE-003 R2 churn evidence.

The analyzer replays the captured Prometheus matrices through the real
WORKLOAD-OWNERSHIP-001 normalization/resolution path, then applies only the
experimental SPIKE-003 support/population reducers. It performs no network I/O,
Kubernetes mutation, risk classification, or product-semantic change.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from praeva.ownership.historical import build_ownership_report
from praeva.ownership.prometheus_adapter import collect_ownership_evidence

SPIKE_DIR = Path(__file__).resolve().parent
SUPPORT_MODEL_PATH = SPIKE_DIR / "support_model.py"
POPULATION_MODEL_PATH = SPIKE_DIR / "population_model.py"

VERIFY_QUERY_WINDOWS = {
    "cpu_short": "120",
    "cpu_long": "300",
}
VERIFY_QUERY_KEYS = (
    "cpu_short",
    "cpu_long",
    "cfs_throttled_short",
    "cfs_throttled_long",
    "cpu_limit",
)
SOURCE_TIMESTAMP_KEYS = (
    "pod_owner_source_timestamp",
    "replicaset_owner_source_timestamp",
    "pod_created_source_timestamp",
)


class R2AnalysisError(RuntimeError):
    """Raised when captured R2 evidence cannot be replayed deterministically."""


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise R2AnalysisError(f"{field} must not be represented as float")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise R2AnalysisError(f"{field} must be numeric") from exc
    else:
        raise R2AnalysisError(f"{field} must be numeric")
    if not number.is_finite():
        raise R2AnalysisError(f"{field} must be finite")
    return number


def _decimal_text(value: Any, *, field: str = "value") -> str:
    number = _decimal(value, field=field)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except (OSError, json.JSONDecodeError) as exc:
        raise R2AnalysisError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise R2AnalysisError(f"JSON root must be an object: {path}")
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    return value


def _save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(_json_safe(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _load_model(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise R2AnalysisError(f"cannot load experimental model: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _matrix_result(payload: dict[str, Any], *, label: str) -> list[dict[str, Any]]:
    if payload.get("status") != "success":
        raise R2AnalysisError(f"{label} Prometheus response is not successful")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "matrix":
        raise R2AnalysisError(f"{label} must contain a Prometheus matrix")
    result = data.get("result")
    if not isinstance(result, list):
        raise R2AnalysisError(f"{label} matrix result must be a list")
    return result


def _grid(start: Any, end: Any, step: Any) -> list[str]:
    start_value = _decimal(start, field="grid start")
    end_value = _decimal(end, field="grid end")
    step_value = _decimal(step, field="grid step")
    if step_value <= 0 or end_value < start_value:
        raise R2AnalysisError("invalid analysis grid")
    output: list[str] = []
    current = start_value
    while current <= end_value:
        output.append(_decimal_text(current))
        current += step_value
    return output


def _observed_pods_by_timestamp(payload: dict[str, Any], *, label: str) -> dict[str, set[str]]:
    observed: dict[str, set[str]] = {}
    for series in _matrix_result(payload, label=label):
        metric = series.get("metric")
        values = series.get("values")
        if not isinstance(metric, dict) or not isinstance(values, list):
            raise R2AnalysisError(f"malformed {label} matrix series")
        pod = metric.get("pod")
        if not isinstance(pod, str) or not pod:
            raise R2AnalysisError(f"{label} series is missing pod label")
        for sample in values:
            if not isinstance(sample, list) or len(sample) != 2:
                raise R2AnalysisError(f"malformed {label} matrix sample")
            timestamp = _decimal_text(sample[0], field=f"{label} timestamp")
            observed.setdefault(timestamp, set()).add(pod)
    return observed


def _pods_from_owner_payload(payload: dict[str, Any], *, namespace: str) -> list[str]:
    pods: set[str] = set()
    for series in _matrix_result(payload, label="pod_owner"):
        metric = series.get("metric")
        if not isinstance(metric, dict):
            raise R2AnalysisError("malformed pod_owner matrix series")
        if metric.get("namespace") != namespace:
            continue
        pod = metric.get("pod")
        if isinstance(pod, str) and pod:
            pods.add(pod)
    return sorted(pods)


def _creation_by_identity(payload: dict[str, Any]) -> dict[tuple[str, str], str]:
    values_by_identity: dict[tuple[str, str], set[str]] = {}
    for series in _matrix_result(payload, label="pod_created"):
        metric = series.get("metric")
        values = series.get("values")
        if not isinstance(metric, dict) or not isinstance(values, list):
            raise R2AnalysisError("malformed pod_created matrix series")
        pod = metric.get("pod")
        uid = metric.get("uid")
        if not isinstance(pod, str) or not pod or not isinstance(uid, str) or not uid:
            raise R2AnalysisError("pod_created series is missing pod/uid identity")
        identity = (pod, uid)
        for sample in values:
            if not isinstance(sample, list) or len(sample) != 2:
                raise R2AnalysisError("malformed pod_created matrix sample")
            raw_value = sample[1]
            values_by_identity.setdefault(identity, set()).add(
                _decimal_text(raw_value, field="pod_created value")
            )

    output: dict[tuple[str, str], str] = {}
    for identity, observed in values_by_identity.items():
        if len(observed) != 1:
            raise R2AnalysisError(
                f"pod_created value is not stable for {identity[0]} uid={identity[1]}"
            )
        output[identity] = next(iter(observed))
    return output


def _population_transitions(population_by_timestamp: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []
    previous: tuple[str, ...] | None = None
    for timestamp in sorted(population_by_timestamp, key=Decimal):
        current = tuple(population_by_timestamp[timestamp]["target_owned"])
        if previous is not None and current != previous:
            transitions.append(
                {
                    "timestamp": timestamp,
                    "from_target_owned": list(previous),
                    "to_target_owned": list(current),
                }
            )
        previous = current
    return transitions


def _identity_summary(ownership_report: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for pod, pod_report in sorted(ownership_report.get("pods", {}).items()):
        matches: list[tuple[str, dict[str, Any]]] = []
        for timestamp, fact in pod_report.get("ownership", {}).items():
            if (
                isinstance(fact, dict)
                and fact.get("evidence_status") == "VALID"
                and fact.get("relation") == "TARGET_MATCH"
            ):
                matches.append((timestamp, fact))
        if not matches:
            continue
        matches.sort(key=lambda item: Decimal(item[0]))
        uids = sorted(
            {
                fact["pod_identity"]["uid"]
                for _, fact in matches
                if isinstance(fact.get("pod_identity"), dict)
            }
        )
        replicasets = sorted(
            {
                fact["pod_owner"]["name"]
                for _, fact in matches
                if isinstance(fact.get("pod_owner"), dict)
            }
        )
        output.append(
            {
                "pod": pod,
                "uids": uids,
                "replicasets": replicasets,
                "first_target_match": matches[0][0],
                "last_target_match": matches[-1][0],
            }
        )
    return output


def _population_summary(population_by_timestamp: dict[str, dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    last_seen: dict[str, str] = {}

    def mark(name: str, timestamp: str) -> None:
        counts[name] += 1
        first_seen.setdefault(name, timestamp)
        last_seen[name] = timestamp

    for timestamp in sorted(population_by_timestamp, key=Decimal):
        value = population_by_timestamp[timestamp]
        if value.get("selector_omissions"):
            mark("selector_omission", timestamp)
        for query_name, query_value in value.get("per_query", {}).items():
            if query_value.get("derived_evidence_missing"):
                mark(f"derived_evidence_missing:{query_name}", timestamp)
            if query_value.get("extra_observed"):
                mark(f"extra_observed:{query_name}", timestamp)
            if query_value.get("foreign_target_differs"):
                mark(f"foreign_target_differs:{query_name}", timestamp)
            if query_value.get("ownership_unresolved"):
                mark(f"ownership_unresolved:{query_name}", timestamp)

    return {
        name: {
            "timestamps": count,
            "first": first_seen[name],
            "last": last_seen[name],
        }
        for name, count in sorted(counts.items())
    }


def _source_age_summary(payload: dict[str, Any], *, label: str) -> dict[str, Any]:
    ages: list[Decimal] = []
    for series in _matrix_result(payload, label=label):
        values = series.get("values")
        if not isinstance(values, list):
            raise R2AnalysisError(f"malformed {label} matrix series")
        for sample in values:
            if not isinstance(sample, list) or len(sample) != 2:
                raise R2AnalysisError(f"malformed {label} matrix sample")
            evaluation = _decimal(sample[0], field=f"{label} evaluation timestamp")
            source = _decimal(sample[1], field=f"{label} source timestamp")
            ages.append(evaluation - source)
    if not ages:
        return {"samples": 0}
    return {
        "samples": len(ages),
        "min_age_seconds": _decimal_text(min(ages)),
        "max_age_seconds": _decimal_text(max(ages)),
    }


def _support_summary(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for evaluation in evaluations:
        continuity = evaluation["identity_continuity"]
        counts[f"identity_continuity:{continuity['identity_continuity']}"] += 1
        diagnostic = continuity.get("diagnostic")
        if diagnostic:
            counts[f"identity_diagnostic:{diagnostic}"] += 1
        creation = evaluation["creation_bound"]
        counts[f"creation_bound:{creation['creation_bound']}"] += 1
        creation_diagnostic = creation.get("diagnostic")
        if creation_diagnostic:
            counts[f"creation_diagnostic:{creation_diagnostic}"] += 1
    return dict(sorted(counts.items()))


def _build_real_ownership_report(
    *,
    evidence_dir: Path,
    metadata: dict[str, Any],
    ownership_grid: list[str],
) -> dict[str, Any]:
    semantic = metadata["semantic_parameters"]
    interval = metadata["interval"]
    pod_owner_payload = _load_json(evidence_dir / "pod_owner.json")
    rs_owner_payload = _load_json(evidence_dir / "replicaset_owner.json")

    def replay_query_range(**kwargs: Any) -> dict[str, Any]:
        query = kwargs["query"]
        if "kube_pod_owner" in query:
            return pod_owner_payload
        if "kube_replicaset_owner" in query:
            return rs_owner_payload
        raise R2AnalysisError(f"unexpected ownership replay query: {query}")

    normalized = collect_ownership_evidence(
        prometheus_url="http://r2-replay.invalid",
        namespace=semantic["namespace"],
        start=interval["extended_ownership_start"],
        end=interval["end"],
        step=interval["step"],
        query_range=replay_query_range,
    )
    pods = _pods_from_owner_payload(
        pod_owner_payload,
        namespace=semantic["namespace"],
    )
    required = {pod: ownership_grid for pod in pods}
    target = {
        "api_group": semantic["api_group"],
        "kind": semantic["kind"],
        "namespace": semantic["namespace"],
        "name": semantic["workload"],
    }
    return build_ownership_report(
        evidence=normalized,
        target_workload=target,
        required_timestamps_by_pod=required,
    )


def analyze_r2(*, evidence_dir: Path, output_path: Path | None = None) -> dict[str, Any]:
    metadata = _load_json(evidence_dir / "metadata.json")
    manifest = _load_json(evidence_dir / "manifest.json")
    if metadata.get("run_id") != "R2-churn-rollout":
        raise R2AnalysisError("evidence is not an R2 churn collection")
    if manifest.get("status") != "COMPLETE":
        raise R2AnalysisError("R2 manifest must be COMPLETE before analysis")

    interval = metadata.get("interval")
    semantic = metadata.get("semantic_parameters")
    mutation = metadata.get("mutation")
    if not isinstance(interval, dict) or not isinstance(semantic, dict):
        raise R2AnalysisError("R2 metadata is missing interval/semantic parameters")
    if not isinstance(mutation, dict):
        raise R2AnalysisError("R2 metadata is missing mutation provenance")

    analysis_grid = _grid(interval["start"], interval["end"], interval["step"])
    ownership_grid = _grid(
        interval["extended_ownership_start"],
        interval["end"],
        interval["step"],
    )
    ownership_report = _build_real_ownership_report(
        evidence_dir=evidence_dir,
        metadata=metadata,
        ownership_grid=ownership_grid,
    )

    verify_observed: dict[str, dict[str, set[str]]] = {}
    for query_name in VERIFY_QUERY_KEYS:
        verify_observed[query_name] = _observed_pods_by_timestamp(
            _load_json(evidence_dir / f"{query_name}.json"),
            label=query_name,
        )

    population_model = _load_model(
        POPULATION_MODEL_PATH,
        "spike003_population_model_r2",
    )
    population_by_timestamp: dict[str, dict[str, Any]] = {}
    for timestamp in analysis_grid:
        population_by_timestamp[timestamp] = population_model.evaluate_population_at_timestamp(
            ownership_report=ownership_report,
            timestamp=timestamp,
            pod_regex=semantic["pod_regex"],
            verify_pods_by_query={
                query_name: values.get(timestamp, set())
                for query_name, values in verify_observed.items()
            },
        )

    creation_by_identity = _creation_by_identity(
        _load_json(evidence_dir / "pod_created.json")
    )
    support_model = _load_model(SUPPORT_MODEL_PATH, "spike003_support_model_r2")
    support_evaluations: dict[str, list[dict[str, Any]]] = {}

    for query_name, window_seconds in VERIFY_QUERY_WINDOWS.items():
        evaluations: list[dict[str, Any]] = []
        for timestamp in analysis_grid:
            for pod in sorted(verify_observed[query_name].get(timestamp, set())):
                geometry = support_model.evaluate_support_geometry(
                    analysis_start=interval["start"],
                    analysis_end=interval["end"],
                    step=interval["step"],
                    w_max_seconds=interval["w_max_seconds"],
                    witness_timestamp=timestamp,
                    window_seconds=window_seconds,
                )
                continuity = support_model.evaluate_identity_continuity(
                    ownership_report=ownership_report,
                    pod=pod,
                    required_timestamps=geometry["support_grid"],
                )

                fact = (
                    ownership_report.get("pods", {})
                    .get(pod, {})
                    .get("ownership", {})
                    .get(timestamp)
                )
                uid = None
                if isinstance(fact, dict) and isinstance(fact.get("pod_identity"), dict):
                    uid = fact["pod_identity"].get("uid")
                creation_timestamp = (
                    creation_by_identity.get((pod, uid))
                    if isinstance(uid, str) and uid
                    else None
                )
                if creation_timestamp is None:
                    creation_bound = {
                        "model_id": "SPIKE-003-CANDIDATE",
                        "creation_bound": "NOT_EVALUATED",
                        "reason": "pod_uid_or_creation_timestamp_unavailable_at_witness",
                    }
                else:
                    creation_bound = support_model.evaluate_creation_bound(
                        creation_timestamp=creation_timestamp,
                        support_start=geometry["support_start"],
                    )

                evaluations.append(
                    {
                        "pod": pod,
                        "witness_timestamp": timestamp,
                        "support_start": geometry["support_start"],
                        "support_grid": geometry["support_grid"],
                        "identity_continuity": continuity,
                        "creation_bound": creation_bound,
                    }
                )
        support_evaluations[query_name] = evaluations

    source_age = {
        key: _source_age_summary(
            _load_json(evidence_dir / f"{key}.json"),
            label=key,
        )
        for key in SOURCE_TIMESTAMP_KEYS
    }

    result: dict[str, Any] = {
        "analysis_id": "SPIKE-003-R2-OFFLINE-ANALYSIS",
        "run_id": metadata["run_id"],
        "mutation": mutation,
        "interval": interval,
        "evidence_manifest_status": manifest["status"],
        "ownership_path": {
            "normalizer": "collect_ownership_evidence",
            "resolver": "build_ownership_report",
            "product_contract": "WORKLOAD-OWNERSHIP-001",
        },
        "identity_summary": _identity_summary(ownership_report),
        "ownership_report": ownership_report,
        "population": {
            "transitions": _population_transitions(population_by_timestamp),
            "diagnostic_summary": _population_summary(population_by_timestamp),
            "by_timestamp": population_by_timestamp,
        },
        "creation_by_identity": [
            {"pod": pod, "uid": uid, "creation_timestamp": created}
            for (pod, uid), created in sorted(creation_by_identity.items())
        ],
        "support": {
            query_name: {
                "summary": _support_summary(evaluations),
                "evaluations": evaluations,
            }
            for query_name, evaluations in support_evaluations.items()
        },
        "source_sample_age": source_age,
        "application_version_relation": "UNVERIFIED",
        "product_semantics_changed": False,
    }

    if output_path is None:
        output_path = evidence_dir / "r2-analysis.json"
    _save_json(output_path, result)
    return result


def _print_summary(result: dict[str, Any], *, output_path: Path) -> None:
    print("PRAEVA SPIKE-003 R2 OFFLINE ANALYSIS COMPLETE")
    print("==============================================")
    print(f"Output: {output_path}")
    print("\nTarget-match identities")
    print("-----------------------")
    for identity in result["identity_summary"]:
        print(
            f"{identity['pod']}: uids={','.join(identity['uids'])} "
            f"replicasets={','.join(identity['replicasets'])} "
            f"first={identity['first_target_match']} last={identity['last_target_match']}"
        )

    print("\nTarget-owned population transitions")
    print("-----------------------------------")
    transitions = result["population"]["transitions"]
    if not transitions:
        print("none")
    for transition in transitions:
        print(
            f"{transition['timestamp']}: {transition['from_target_owned']} "
            f"-> {transition['to_target_owned']}"
        )

    print("\nPopulation diagnostics")
    print("----------------------")
    diagnostics = result["population"]["diagnostic_summary"]
    if not diagnostics:
        print("none")
    for name, value in diagnostics.items():
        print(
            f"{name}: timestamps={value['timestamps']} "
            f"first={value['first']} last={value['last']}"
        )

    print("\nSupport summaries")
    print("-----------------")
    for query_name in VERIFY_QUERY_WINDOWS:
        print(f"{query_name}: {result['support'][query_name]['summary']}")

    print("\nSource-sample age")
    print("-----------------")
    for key, value in result["source_sample_age"].items():
        print(f"{key}: {value}")

    print("\napplication_version_relation: UNVERIFIED")
    print("No network I/O, risk classification, or product-semantic change was performed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze captured SPIKE-003 R2 churn evidence offline")
    parser.add_argument(
        "evidence_dir",
        type=Path,
        help="R2-churn-rollout evidence directory produced by r2_collect.py",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="optional output JSON path; defaults to <evidence_dir>/r2-analysis.json",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_path = args.output or args.evidence_dir / "r2-analysis.json"
    try:
        result = analyze_r2(evidence_dir=args.evidence_dir, output_path=output_path)
        _print_summary(result, output_path=output_path)
        return 0
    except (KeyError, R2AnalysisError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
