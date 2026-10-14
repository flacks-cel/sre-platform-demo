import json

from praeva.verify import cli
from praeva.verify.prometheus_adapter import PrometheusAdapterError


def normalized_evidence() -> dict:
    return {
        "pods": [
            {
                "name": "pod-a",
                "cpu_short": [{"timestamp": 0, "value": 0.4}],
                "cpu_long": [{"timestamp": 0, "value": 0.3}],
                "cpu_limit": [{"timestamp": 0, "value": 1.0}],
                "request_rate": None,
                "sample_count": 1,
                "coverage": 1.0,
                "restart_delta": 0,
                "node": None,
                "owner": None,
            }
        ],
        "short_window": "2m",
        "long_window": "5m",
    }


def prometheus_args() -> list[str]:
    return [
        "verify",
        "cpu",
        "--prometheus-url",
        "http://prometheus:9090",
        "--namespace",
        "custom-ns",
        "--pod-regex",
        "worker-.*",
        "--container",
        "worker",
        "--start",
        "0",
        "--end",
        "30",
        "--step",
        "15",
        "--short-window",
        "2m",
        "--long-window",
        "5m",
    ]


def test_cli_prometheus_mode_delegates_to_adapter_and_core(monkeypatch, capsys):
    calls = []

    def fake_collect(**kwargs):
        calls.append(kwargs)
        return normalized_evidence()

    monkeypatch.setattr(cli, "collect_normalized_evidence", fake_collect, raising=False)

    exit_code = cli.main(prometheus_args())

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["status"] == "VALID"
    assert calls == [
        {
            "prometheus_url": "http://prometheus:9090",
            "namespace": "custom-ns",
            "pod_regex": "worker-.*",
            "container": "worker",
            "start": 0.0,
            "end": 30.0,
            "step": 15.0,
            "short_window": "2m",
            "long_window": "5m",
            "request_rate_query": None,
        }
    ]


def test_cli_prometheus_mode_passes_request_query_unchanged(monkeypatch, capsys):
    calls = []

    def fake_collect(**kwargs):
        calls.append(kwargs)
        return normalized_evidence()

    monkeypatch.setattr(cli, "collect_normalized_evidence", fake_collect, raising=False)

    args = prometheus_args() + ["--request-rate-query", "CUSTOM_REQUEST_QUERY"]
    assert cli.main(args) == 0
    capsys.readouterr()

    assert calls[0]["request_rate_query"] == "CUSTOM_REQUEST_QUERY"


def test_cli_rejects_input_and_prometheus_modes_together(tmp_path, capsys):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(normalized_evidence()), encoding="utf-8")

    exit_code = cli.main(["verify", "cpu", "--input", str(path), *prometheus_args()[2:]])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert captured.err


def test_cli_rejects_incomplete_prometheus_argument_set(capsys):
    exit_code = cli.main(
        [
            "verify",
            "cpu",
            "--prometheus-url",
            "http://prometheus:9090",
            "--namespace",
            "custom-ns",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert captured.err


def test_cli_prometheus_adapter_failure_is_process_failure(monkeypatch, capsys):
    def fake_collect(**kwargs):
        raise PrometheusAdapterError("Prometheus exploded")

    monkeypatch.setattr(cli, "collect_normalized_evidence", fake_collect, raising=False)

    exit_code = cli.main(prometheus_args())

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "Prometheus exploded" in captured.err
