"""ANALYZE-ERGONOMICS-001: preregistered RED contract tests.

Imports are delayed until each test to produce independent RED failures
rather than an import-time collection error. No production implementation
belongs in this commit.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

CURRENT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jobs-api
  namespace: app
spec:
  template:
    spec:
      containers:
        - name: jobs-api
          resources:
            requests:
              cpu: 100m
            limits:
              cpu: 500m
"""
PROPOSED = CURRENT.replace("cpu: 500m", "cpu: 250m")
IDENTITY = {
    "prometheus_url": "http://prometheus.test",
    "namespace": "app",
    "api_group": "apps",
    "kind": "Deployment",
    "name": "jobs-api",
    "container": "jobs-api",
    "container_space": "containers",
    "pod_regex": "jobs-api-.*",
}
POLICY = {
    "step": 15,
    "short_window": "2m",
    "long_window": "5m",
    "rule": "CHANGE-RISK-001",
    "rule_params": {"margin": "11/10"},
}


def _resolver() -> Any:
    return importlib.import_module("praeva.analyze.invocation")


def _time(
    *,
    last: str | None = None,
    start: str | None = None,
    end: str | None = None,
    step: str = "15",
    now: int = 100,
) -> dict[str, Any]:
    return _resolver().resolve_time_range(
        last=last, start=start, end=end, step=step, now=now
    )


def _config(tmp_path: Path, *, extra: str = "") -> Path:
    path = tmp_path / "praeva.yaml"
    root = "\n".join(f"{key}: {value}" for key, value in IDENTITY.items())
    profile = (
        "profiles:\n"
        "  lab:\n"
        "    step: 15\n"
        "    short_window: 2m\n"
        "    long_window: 5m\n"
        "    rule: CHANGE-RISK-001\n"
        "    rule_params:\n"
        "      margin: 11/10\n"
    )
    path.write_text(root + "\n" + profile + extra, encoding="utf-8")
    return path


def _resolve(
    *,
    config: dict[str, Any] | None,
    profile: str | None = None,
    cli_values: dict[str, Any] | None = None,
    rule_id: str | None = None,
    now: int = 100,
) -> dict[str, Any]:
    return _resolver().resolve_invocation(
        cli_values=cli_values or {},
        config=config,
        profile=profile,
        rule_id=rule_id,
        now=now,
    )


def _transport(**kwargs: Any) -> dict[str, Any]:
    query = kwargs["query"]
    value = "0.5" if "kube_pod_container_resource_limits" in query else "0.4"
    if "container_cpu_cfs_throttled_periods_total" in query:
        value = "0"
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"pod": "jobs-api-abc"},
                    "values": [["0", value], ["15", value], ["30", value]],
                }
            ],
        },
    }


def _manifests(tmp_path: Path) -> tuple[Path, Path]:
    current = tmp_path / "current.yaml"
    proposed = tmp_path / "proposed.yaml"
    current.write_text(CURRENT, encoding="utf-8")
    proposed.write_text(PROPOSED, encoding="utf-8")
    return current, proposed


def _args(current: Path, proposed: Path) -> list[str]:
    return [
        "analyze",
        "--current", str(current),
        "--proposed", str(proposed),
        "--rule", "CHANGE-RISK-001",
        "--api-group", "apps",
        "--kind", "Deployment",
        "--namespace", "app",
        "--name", "jobs-api",
        "--container", "jobs-api",
        "--pod-regex", "jobs-api-.*",
        "--prometheus-url", "http://prometheus.test",
        "--start", "0",
        "--end", "30",
        "--step", "15",
        "--short-window", "2m",
        "--long-window", "5m",
        "--rule-param", "margin=11/10",
    ]


def _cli(
    args: list[str],
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    main = importlib.import_module("praeva.analyze.cli").main
    code = main(args, query_range=_transport)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _analyze() -> Any:
    return importlib.import_module("praeva.analyze.orchestrator").analyze


def _analyze_kwargs() -> dict[str, Any]:
    return {
        "current_manifest": CURRENT,
        "proposed_manifest": PROPOSED,
        **IDENTITY,
        "start": "0",
        "end": "30",
        "step": "15",
        "short_window": "2m",
        "long_window": "5m",
        "rule_id": "CHANGE-RISK-001",
        "rule_params": {"margin": "11/10"},
        "query_range": _transport,
    }


# §9, cases 1-9: temporal parameter resolution.


def test_01_absolute_interval_is_explicit() -> None:
    result = _time(start="0", end="30")
    assert str(result["start"]) == "0"
    assert str(result["end"]) == "30"
    assert result["time_source"] == "EXPLICIT"


def test_02_no_temporal_form_is_an_input_error() -> None:
    with pytest.raises(ValueError, match="last|start|time"):
        _time()


def test_03_relative_and_absolute_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="last|start|exclusive"):
        _time(last="6h", start="0", end="30")


def test_04_six_hours_resolves_to_phase_aligned_grid() -> None:
    result = _time(last="6h", now=100)
    assert int(result["end"]) == 90
    assert int(result["start"]) == 90 - 21600
    assert result["time_source"] == "RELATIVE"


def test_05_off_grid_now_never_becomes_end() -> None:
    result = _time(last="30s", now=101)
    assert int(result["end"]) == 90
    assert int(result["end"]) != 101


def test_06_100_minutes_is_exact_multiple_of_15_seconds() -> None:
    result = _time(last="100m", now=100)
    assert int(result["end"]) - int(result["start"]) == 6000


def test_07_61_seconds_is_not_multiple_of_step() -> None:
    with pytest.raises(ValueError, match="step|multiple|duration"):
        _time(last="61s")


@pytest.mark.parametrize("duration", ["0.5h", "1h30m", "6 hours"])
def test_08_invalid_duration_grammar_is_rejected(duration: str) -> None:
    with pytest.raises(ValueError, match="duration|last|invalid"):
        _time(last=duration)


def test_09_clocks_resolve_independently_not_by_delta() -> None:
    first = _time(last="30s", now=100)
    second = _time(last="30s", now=110)
    assert (int(first["start"]), int(first["end"])) == (60, 90)
    assert (int(second["start"]), int(second["end"])) == (75, 105)
    assert int(second["end"]) - int(first["end"]) == 15


# §9, cases 10-11: deterministic invocation and canonical output.


def test_10_fixed_clock_produces_identical_resolution_wire() -> None:
    first = _time(last="6h", now=1794227910)
    second = _time(last="6h", now=1794227910)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_11_absolute_replay_is_byte_identical() -> None:
    first = _analyze()(**_analyze_kwargs())
    second = _analyze()(**_analyze_kwargs())
    assert "invocation" in first
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# §9, cases 12-22: configuration and explicitly selected profile.


def test_12_config_supplies_eight_identity_fields(tmp_path: Path) -> None:
    loaded = _resolver().load_config(_config(tmp_path))
    for key, value in IDENTITY.items():
        assert str(loaded[key]) == value


@pytest.mark.parametrize("extra", ["margin: 11/10\n", "short_window: 2m\n"])
def test_13_root_policy_is_rejected(tmp_path: Path, extra: str) -> None:
    path = _config(tmp_path)
    path.write_text(extra + path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="margin|short_window|unknown|forbidden"):
        _resolver().load_config(path)


@pytest.mark.parametrize(
    "extra",
    ["namesapce: typo\n", "profiles:\n  lab:\n    strange: nope\n"],
)
def test_14_unknown_config_keys_are_rejected(tmp_path: Path, extra: str) -> None:
    if "profiles:" in extra:
        path = tmp_path / "praeva.yaml"
        path.write_text(extra, encoding="utf-8")
    else:
        path = _config(tmp_path)
        path.write_text(extra + path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="namesapce|strange|unknown"):
        _resolver().load_config(path)


def test_15_config_is_not_discovered_automatically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current, proposed = _manifests(tmp_path)
    (tmp_path / "praeva.yaml").write_text("namesapce: wrong\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code, output, _ = _cli(_args(current, proposed), capsys)
    assert code == 0
    assert json.loads(output)["result"]["risk_level"] == "CRITICAL"


def test_16_cli_overrides_config_by_key(tmp_path: Path) -> None:
    config = _resolver().load_config(_config(tmp_path))
    resolved = _resolve(
        config=config,
        profile="lab",
        cli_values={"namespace": "override", "last": "6h"},
    )
    text = json.dumps(resolved, sort_keys=True)
    assert "override" in text
    assert "CLI" in text


def test_17_selected_profile_supplies_effective_policy(tmp_path: Path) -> None:
    config = _resolver().load_config(_config(tmp_path))
    resolved = _resolve(config=config, profile="lab", cli_values={"last": "6h"})
    rendered = json.dumps(resolved, sort_keys=True)
    assert "2m" in rendered
    assert "5m" in rendered
    assert "11/10" in rendered


def test_18_unselected_profile_does_not_supply_policy(tmp_path: Path) -> None:
    config = _resolver().load_config(_config(tmp_path))
    with pytest.raises(ValueError, match="rule|step|short_window|long_window"):
        _resolve(config=config, profile=None, cli_values={"last": "6h"})


def test_19_profile_without_config_is_input_error() -> None:
    with pytest.raises(ValueError, match="config|profile"):
        _resolve(config=None, profile="lab", cli_values={"last": "6h"})


def test_20_unknown_profile_is_named_input_error(tmp_path: Path) -> None:
    config = _resolver().load_config(_config(tmp_path))
    with pytest.raises(ValueError, match="missing|lab|profile"):
        _resolve(config=config, profile="missing", cli_values={"last": "6h"})


def test_21_incomplete_profile_is_input_error(tmp_path: Path) -> None:
    path = tmp_path / "praeva.yaml"
    path.write_text(
        "profiles:\n"
        "  bad:\n"
        "    step: 15\n"
        "    short_window: 2m\n"
        "    long_window: 5m\n"
        "    rule: CHANGE-RISK-001\n",
        encoding="utf-8",
    )
    config = _resolver().load_config(path)
    with pytest.raises(ValueError, match="margin|rule_params|incomplete"):
        _resolve(config=config, profile="bad", cli_values={"last": "6h"})


def test_22_rule_param_cli_wins_without_discarding_profile(tmp_path: Path) -> None:
    config = _resolver().load_config(_config(tmp_path))
    resolved = _resolve(
        config=config,
        profile="lab",
        cli_values={"last": "6h", "rule_params": {"margin": "12/10"}},
    )
    rendered = json.dumps(resolved, sort_keys=True)
    assert "12/10" in rendered
    assert "2m" in rendered


# §9, cases 23-26: single canonical document producer.


def test_23_cli_document_always_contains_absolute_invocation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current, proposed = _manifests(tmp_path)
    code, output, _ = _cli(_args(current, proposed), capsys)
    assert code == 0
    invocation = json.loads(output)["invocation"]
    assert str(invocation["start"]) == "0"
    assert str(invocation["end"]) == "30"
    assert str(invocation["step"]) == "15"


def test_24_config_source_and_hash_are_audited(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current, proposed = _manifests(tmp_path)
    path = _config(tmp_path)
    args = [
        "analyze", "--config", str(path), "--profile", "lab",
        "--current", str(current), "--proposed", str(proposed),
        "--start", "0", "--end", "30",
    ]
    code, output, error = _cli(args, capsys)
    assert code == 0, error
    invocation = json.loads(output)["invocation"]
    assert invocation["config_path"]
    assert invocation["config_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_25_manifest_hashes_are_recorded(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current, proposed = _manifests(tmp_path)
    code, output, error = _cli(_args(current, proposed), capsys)
    assert code == 0, error
    invocation = json.loads(output)["invocation"]
    assert invocation["current_manifest_sha256"] == hashlib.sha256(
        current.read_bytes()
    ).hexdigest()
    assert invocation["proposed_manifest_sha256"] == hashlib.sha256(
        proposed.read_bytes()
    ).hexdigest()


def test_26_programmatic_analyze_has_same_canonical_document_shape() -> None:
    result = _analyze()(**_analyze_kwargs(), invocation=None)
    assert "invocation" in result
    assert result["invocation"]["time_source"] == "EXPLICIT"
    for key in ("start", "end", "step", "current_manifest_sha256"):
        assert key in result["invocation"]
    assert "config_path" not in result["invocation"]
