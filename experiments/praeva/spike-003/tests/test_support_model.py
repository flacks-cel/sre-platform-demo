from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from praeva.ownership.historical import build_ownership_report
from praeva.ownership.prometheus_adapter import collect_ownership_evidence

SPIKE_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = SPIKE_DIR / "fixtures"
SUPPORT_MODEL = SPIKE_DIR / "support_model.py"


def _support_model():
    spec = importlib.util.spec_from_file_location("spike003_support_model", SUPPORT_MODEL)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load support model: {SUPPORT_MODEL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _report_from_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    def query_range(**kwargs: Any) -> dict[str, Any]:
        query = kwargs["query"]
        if "kube_pod_owner" in query:
            return fixture["pod_owner"]
        if "kube_replicaset_owner" in query:
            return fixture["replicaset_owner"]
        raise AssertionError(f"unexpected query: {query}")

    grid = fixture["grid"]
    evidence = collect_ownership_evidence(
        prometheus_url="http://synthetic.invalid",
        namespace=fixture["target"]["namespace"],
        start=grid["start"],
        end=grid["end"],
        step=grid["step"],
        query_range=query_range,
    )
    return build_ownership_report(
        evidence=evidence,
        target_workload=fixture["target"],
        required_timestamps_by_pod={
            fixture["pod"]: grid["required_timestamps"],
        },
    )


def _single_creation_timestamp(fixture: dict[str, Any]) -> str:
    series = fixture["pod_created"]["data"]["result"]
    assert len(series) == 1
    metric = series[0]["metric"]
    assert metric["pod"] == fixture["pod"]
    assert metric["uid"] == fixture["uid"]

    creation_values = {str(value) for _, value in series[0]["values"]}
    assert len(creation_values) == 1
    return creation_values.pop()


def test_s3_uid_change_is_detected_even_when_every_point_target_matches() -> None:
    fixture = _load_fixture("S3-uid-change.json")
    report = _report_from_fixture(fixture)
    pod = fixture["pod"]
    timestamps = fixture["grid"]["required_timestamps"]

    facts = report["pods"][pod]["ownership"]
    assert [facts[t]["evidence_status"] for t in timestamps] == ["VALID"] * 6
    assert [facts[t]["relation"] for t in timestamps] == ["TARGET_MATCH"] * 6

    result = _support_model().evaluate_identity_continuity(
        ownership_report=report,
        pod=pod,
        required_timestamps=timestamps,
    )

    assert result["identity_continuity"] == "NOT_PROVEN"
    assert result["diagnostic"] == "uid_change_within_support_grid"
    assert result["observed_uids"] == ["pod-uid-a", "pod-uid-b"]


def test_s3_control_subset_with_one_uid_is_proven() -> None:
    fixture = _load_fixture("S3-uid-change.json")
    report = _report_from_fixture(fixture)
    pod = fixture["pod"]

    result = _support_model().evaluate_identity_continuity(
        ownership_report=report,
        pod=pod,
        required_timestamps=["0", "15", "30"],
    )

    assert result["identity_continuity"] == "PROVEN"
    assert result["observed_uids"] == ["pod-uid-a"]
    assert "diagnostic" not in result


def test_s2_young_pod_fails_creation_bound_inside_rate_support() -> None:
    fixture = _load_fixture("S2-young-pod.json")
    report = _report_from_fixture(fixture)
    pod = fixture["pod"]
    timestamps = fixture["grid"]["required_timestamps"]

    facts = report["pods"][pod]["ownership"]
    assert facts["0"]["evidence_status"] == "UNKNOWN"
    assert facts["0"]["reason_code"] == "pod_owner_missing_at_timestamp"

    post_creation = timestamps[1:]
    assert [facts[t]["evidence_status"] for t in post_creation] == ["VALID"] * 8
    assert [facts[t]["relation"] for t in post_creation] == ["TARGET_MATCH"] * 8

    continuity = _support_model().evaluate_identity_continuity(
        ownership_report=report,
        pod=pod,
        required_timestamps=post_creation,
    )
    assert continuity["identity_continuity"] == "PROVEN"
    assert continuity["observed_uids"] == [fixture["uid"]]

    creation = _support_model().evaluate_creation_bound(
        creation_timestamp=_single_creation_timestamp(fixture),
        support_start=fixture["support"]["support_start"],
    )
    assert creation == {
        "model_id": "SPIKE-003-CANDIDATE",
        "creation_bound": "NOT_PROVEN",
        "creation_timestamp": "10",
        "support_start": "0",
        "diagnostic": "uid_not_present_at_support_start",
    }


def test_s2_creation_bound_accepts_creation_at_support_start() -> None:
    result = _support_model().evaluate_creation_bound(
        creation_timestamp="10.000",
        support_start="10",
    )

    assert result["creation_bound"] == "PROVEN"
    assert result["creation_timestamp"] == "10.000"
    assert result["support_start"] == "10"
    assert "diagnostic" not in result
