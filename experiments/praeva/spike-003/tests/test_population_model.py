from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from praeva.ownership.historical import build_ownership_report
from praeva.ownership.prometheus_adapter import collect_ownership_evidence

SPIKE_DIR = Path(__file__).resolve().parents[1]
FIXTURE_S5 = SPIKE_DIR / "fixtures" / "S5-selector-omission.json"
FIXTURE_S6 = SPIKE_DIR / "fixtures" / "S6-derived-evidence-missing.json"
POPULATION_MODEL = SPIKE_DIR / "population_model.py"


def _population_model():
    spec = importlib.util.spec_from_file_location(
        "spike003_population_model", POPULATION_MODEL
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load population model: {POPULATION_MODEL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _report_from_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    def query_range(**kwargs: Any) -> dict[str, Any]:
        query = kwargs["query"]
        if "kube_pod_owner" in query:
            return fixture["pod_owner"]
        if "kube_replicaset_owner" in query:
            return fixture["replicaset_owner"]
        raise AssertionError(f"unexpected query: {query}")

    grid = fixture["grid"]
    pods = [
        series["metric"]["pod"]
        for series in fixture["pod_owner"]["data"]["result"]
    ]
    required = {pod: [grid["timestamp"]] for pod in pods}

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
        required_timestamps_by_pod=required,
    )


def test_s5_selector_omission_is_distinct_from_missing_derived_evidence() -> None:
    fixture = _load_fixture(FIXTURE_S5)
    report = _report_from_fixture(fixture)
    timestamp = fixture["grid"]["timestamp"]

    facts = {
        pod: pod_report["ownership"][timestamp]
        for pod, pod_report in report["pods"].items()
    }
    assert {fact["evidence_status"] for fact in facts.values()} == {"VALID"}
    assert {fact["relation"] for fact in facts.values()} == {"TARGET_MATCH"}

    verify = {
        name: set(pods)
        for name, pods in fixture["verify_pods_by_query"].items()
    }
    result = _population_model().evaluate_population_at_timestamp(
        ownership_report=report,
        timestamp=timestamp,
        pod_regex=fixture["selector"],
        verify_pods_by_query=verify,
    )

    assert result["target_owned"] == [
        "jobs-api-allowed-a",
        "jobs-api-omitted-b",
    ]
    assert result["selector_admitted"] == ["jobs-api-allowed-a"]
    assert result["selector_omissions"] == ["jobs-api-omitted-b"]

    cpu_short = result["per_query"]["cpu_short"]
    assert cpu_short["verify_observed"] == ["jobs-api-allowed-a"]
    assert cpu_short["derived_evidence_missing"] == []
    assert cpu_short["extra_observed"] == []


def test_s5_control_full_selector_has_no_omission() -> None:
    fixture = _load_fixture(FIXTURE_S5)
    report = _report_from_fixture(fixture)
    timestamp = fixture["grid"]["timestamp"]

    result = _population_model().evaluate_population_at_timestamp(
        ownership_report=report,
        timestamp=timestamp,
        pod_regex="jobs-api-.*",
        verify_pods_by_query={
            "cpu_short": {
                "jobs-api-allowed-a",
                "jobs-api-omitted-b",
            }
        },
    )

    assert result["target_owned"] == result["selector_admitted"]
    assert result["selector_omissions"] == []
    assert result["per_query"]["cpu_short"]["derived_evidence_missing"] == []
    assert result["per_query"]["cpu_short"]["extra_observed"] == []


def test_s6_selector_admitted_missing_derived_evidence_is_detected() -> None:
    fixture = _load_fixture(FIXTURE_S6)
    report = _report_from_fixture(fixture)
    timestamp = fixture["grid"]["timestamp"]

    verify = {
        name: set(pods)
        for name, pods in fixture["verify_pods_by_query"].items()
    }
    result = _population_model().evaluate_population_at_timestamp(
        ownership_report=report,
        timestamp=timestamp,
        pod_regex=fixture["selector"],
        verify_pods_by_query=verify,
    )

    assert result["target_owned"] == ["jobs-api-a", "jobs-api-b"]
    assert result["selector_admitted"] == ["jobs-api-a", "jobs-api-b"]
    assert result["selector_omissions"] == []

    cpu_short = result["per_query"]["cpu_short"]
    assert cpu_short["verify_observed"] == ["jobs-api-a"]
    assert cpu_short["derived_evidence_missing"] == ["jobs-api-b"]
    assert cpu_short["extra_observed"] == []

    cpu_long = result["per_query"]["cpu_long"]
    assert cpu_long["verify_observed"] == ["jobs-api-a", "jobs-api-b"]
    assert cpu_long["derived_evidence_missing"] == []
    assert cpu_long["extra_observed"] == []
