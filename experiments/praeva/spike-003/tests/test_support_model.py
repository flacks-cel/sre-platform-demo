from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from praeva.ownership.historical import build_ownership_report
from praeva.ownership.prometheus_adapter import collect_ownership_evidence

SPIKE_DIR = Path(__file__).resolve().parents[1]
FIXTURE = SPIKE_DIR / "fixtures" / "S3-uid-change.json"
SUPPORT_MODEL = SPIKE_DIR / "support_model.py"


def _support_model():
    spec = importlib.util.spec_from_file_location("spike003_support_model", SUPPORT_MODEL)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load support model: {SUPPORT_MODEL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


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


def test_s3_uid_change_is_detected_even_when_every_point_target_matches() -> None:
    fixture = _load_fixture()
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
    fixture = _load_fixture()
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
