import json

from praeva.verify.cli import main


def evidence_input(*, request_rate=True) -> dict:
    pod = {
        "name": "pod-a",
        "cpu_short": [{"timestamp": 10, "value": 0.4}],
        "cpu_long": [{"timestamp": 10, "value": 0.3}],
        "cpu_limit": [{"timestamp": 10, "value": 1.0}],
        "sample_count": 4,
        "coverage": 0.4,
        "restart_delta": 0,
        "node": "worker-1",
        "owner": "rs-a",
    }
    pod["request_rate"] = (
        [{"timestamp": 10, "value": 2.0}] if request_rate else None
    )
    return {
        "pods": [pod],
        "short_window": "2m",
        "long_window": "5m",
    }


def write_input(tmp_path, payload) -> str:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_cli_writes_one_machine_readable_json_document(tmp_path, capsys):
    path = write_input(tmp_path, evidence_input())

    exit_code = main(["verify", "cpu", "--input", path])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["status"] == "VALID"
    assert report["windows"] == {"long": "5m", "short": "2m"}
    assert captured.out.count("\n") == 1


def test_cli_unknown_selector_is_still_successful_execution(tmp_path, capsys):
    path = write_input(tmp_path, evidence_input(request_rate=False))

    exit_code = main(["verify", "cpu", "--input", path])

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert exit_code == 0
    assert report["status"] == "VALID"
    assert report["selectors"]["max_cpu_cost_rate_pod"]["status"] == "UNKNOWN"


def test_cli_output_is_deterministic(tmp_path, capsys):
    path = write_input(tmp_path, evidence_input())

    assert main(["verify", "cpu", "--input", path]) == 0
    first = capsys.readouterr().out
    assert main(["verify", "cpu", "--input", path]) == 0
    second = capsys.readouterr().out

    assert first == second


def test_cli_malformed_json_returns_nonzero_without_stdout(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text("{not-json", encoding="utf-8")

    exit_code = main(["verify", "cpu", "--input", str(path)])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert captured.err


def test_cli_invalid_structure_returns_nonzero_without_stdout(tmp_path, capsys):
    path = write_input(tmp_path, {"pods": []})

    exit_code = main(["verify", "cpu", "--input", path])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert captured.err


def test_cli_does_not_emit_worst_pod_risk_or_recommendation(tmp_path, capsys):
    path = write_input(tmp_path, evidence_input())

    assert main(["verify", "cpu", "--input", path]) == 0

    report = json.loads(capsys.readouterr().out)
    serialized = repr(report)
    assert "worst_pod" not in serialized
    assert "risk" not in report
    assert "recommendation" not in report
    assert "target_cpu_limit" not in report
