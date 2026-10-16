from decimal import Decimal

from praeva.verify import cli
from praeva.verify.cpu_evidence import build_report
from praeva.verify.prometheus_adapter import collect_normalized_evidence


def matrix(*series: tuple[str, list[tuple[int, str]]]) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"pod": pod},
                    "values": [[timestamp, value] for timestamp, value in values],
                }
                for pod, values in series
            ],
        },
    }


def collector(responses: list[dict]):
    remaining = list(responses)

    def query_range(**_kwargs):
        return remaining.pop(0)

    return query_range


def collect(query_range, **kwargs):
    return collect_normalized_evidence(
        prometheus_url="http://prometheus:9090",
        namespace="app",
        pod_regex="jobs-api-.*",
        container="jobs-api",
        start=0,
        end=30,
        step=15,
        short_window="2m",
        long_window="5m",
        query_range=query_range,
        **kwargs,
    )


def test_adapter_preserves_decimal_string_timestamp_and_query_provenance():
    query_range = collector(
        [
            matrix(("pod-a", [(0, "0.1491020848282956"), (15, "0.2"), (30, "0.1")])),
            matrix(("pod-a", [(0, "0.1"), (15, "0.1"), (30, "0.1")])),
            matrix(("pod-a", [(0, "0.5"), (15, "0.5"), (30, "0.5")])),
        ]
    )

    normalized = collect(query_range)
    point = normalized["pods"][0]["cpu_short"][0]

    assert point == {
        "timestamp": "0",
        "value": "0.1491020848282956",
        "query_key": "cpu_short",
    }
    assert normalized["acquisition"] == {
        "namespace": "app",
        "pod_selector": {"type": "regex", "value": "jobs-api-.*"},
        "container": "jobs-api",
        "start": "0",
        "end": "30",
        "step": "15",
    }
    assert normalized["queries"]["cpu_short"]["rate_window"] == "2m"
    assert "[2m]" in normalized["queries"]["cpu_short"]["promql"]
    assert normalized["queries"]["cpu_limit"]["rate_window"] is None


def test_adapter_coverage_is_exact_point_counts_not_float_ratio():
    query_range = collector(
        [
            matrix(("pod-a", [(0, "0.2"), (15, "0.3")])),
            matrix(("pod-a", [(0, "0.2"), (15, "0.3")])),
            matrix(("pod-a", [(0, "0.5"), (15, "0.5")])),
        ]
    )

    normalized = collect(query_range)
    pod = normalized["pods"][0]

    assert pod["sample_count"] == 2
    assert pod["coverage"] == {"observed_points": 2, "expected_points": 3}


def test_report_preserves_exact_cpu_selector_value_and_provenance():
    query_range = collector(
        [
            matrix(("pod-a", [(0, "0.1491020848282956"), (15, "0.2"), (30, "0.1")])),
            matrix(("pod-a", [(0, "0.1"), (15, "0.1"), (30, "0.1")])),
            matrix(("pod-a", [(0, "0.5"), (15, "0.5"), (30, "0.5")])),
        ]
    )
    normalized = collect(query_range)

    report = build_report(**normalized)
    selector = report["selectors"]["max_cpu_usage_pod"]

    assert selector["value"] == "0.2"
    assert selector["timestamp"] == "15"
    assert selector["window"] == "2m"
    assert selector["query_key"] == "cpu_short"
    assert report["acquisition"] == normalized["acquisition"]
    assert report["queries"] == normalized["queries"]


def test_derived_ratio_and_cost_keep_exact_operands_without_division():
    report = build_report(
        pods=[
            {
                "name": "pod-a",
                "cpu_short": [
                    {"timestamp": "10", "value": "1", "query_key": "cpu_short"}
                ],
                "cpu_long": [
                    {"timestamp": "10", "value": "1", "query_key": "cpu_long"}
                ],
                "cpu_limit": [
                    {"timestamp": "10", "value": "3", "query_key": "cpu_limit"}
                ],
                "request_rate": [
                    {"timestamp": "10", "value": "7", "query_key": "request_rate"}
                ],
                "sample_count": 1,
                "coverage": {"observed_points": 1, "expected_points": 1},
                "restart_delta": 0,
                "node": None,
                "owner": None,
            }
        ],
        short_window="2m",
        long_window="5m",
    )

    ratio = report["pods"]["pod-a"]["cpu_limit_ratio"]
    cost = report["selectors"]["max_cpu_cost_rate_pod"]

    assert ratio["max"] == {"numerator": "1", "denominator": "3"}
    assert cost["value"] == {"numerator": "1", "denominator": "7"}


def test_non_finite_cpu_is_unknown_evidence_not_transport_failure():
    query_range = collector(
        [
            matrix(("pod-a", [(0, "NaN")])),
            matrix(("pod-a", [(0, "0.1")])),
            matrix(("pod-a", [(0, "0.5")])),
        ]
    )

    normalized = collect(query_range)
    report = build_report(**normalized)

    short = report["pods"]["pod-a"]["cpu_usage"]["short"]
    usage = report["selectors"]["max_cpu_usage_pod"]

    assert short["status"] == "UNKNOWN"
    assert short["reason_code"] == "non_finite_sample"
    assert usage["status"] == "UNKNOWN"
    assert "non-finite" in usage["reason"].lower()


def test_cli_prometheus_temporal_arguments_reach_adapter_without_float(monkeypatch, capsys):
    calls = []

    def fake_collect(**kwargs):
        calls.append(kwargs)
        return {
            "pods": [],
            "short_window": "2m",
            "long_window": "5m",
            "acquisition": {},
            "queries": {},
        }

    monkeypatch.setattr(cli, "collect_normalized_evidence", fake_collect)

    exit_code = cli.main(
        [
            "verify",
            "cpu",
            "--prometheus-url",
            "http://prometheus:9090",
            "--namespace",
            "app",
            "--pod-regex",
            "jobs-api-.*",
            "--container",
            "jobs-api",
            "--start",
            "0.1",
            "--end",
            "30.1",
            "--step",
            "0.1",
            "--short-window",
            "2m",
            "--long-window",
            "5m",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert calls[0]["start"] == Decimal("0.1")
    assert calls[0]["end"] == Decimal("30.1")
    assert calls[0]["step"] == Decimal("0.1")
    assert not isinstance(calls[0]["start"], float)


def test_cli_report_keeps_acquisition_and_query_provenance(monkeypatch, capsys):
    def fake_collect(**_kwargs):
        return {
            "pods": [
                {
                    "name": "pod-a",
                    "cpu_short": [
                        {"timestamp": "0", "value": "0.2", "query_key": "cpu_short"}
                    ],
                    "cpu_long": [
                        {"timestamp": "0", "value": "0.1", "query_key": "cpu_long"}
                    ],
                    "cpu_limit": [
                        {"timestamp": "0", "value": "0.5", "query_key": "cpu_limit"}
                    ],
                    "request_rate": None,
                    "sample_count": 1,
                    "coverage": {"observed_points": 1, "expected_points": 1},
                    "restart_delta": 0,
                    "node": None,
                    "owner": None,
                }
            ],
            "short_window": "2m",
            "long_window": "5m",
            "acquisition": {
                "namespace": "app",
                "pod_selector": {"type": "regex", "value": "jobs-api-.*"},
                "container": "jobs-api",
                "start": "0",
                "end": "30",
                "step": "15",
            },
            "queries": {
                "cpu_short": {"promql": "SHORT_QUERY", "rate_window": "2m"},
                "cpu_long": {"promql": "LONG_QUERY", "rate_window": "5m"},
                "cpu_limit": {"promql": "LIMIT_QUERY", "rate_window": None},
            },
        }

    monkeypatch.setattr(cli, "collect_normalized_evidence", fake_collect)

    exit_code = cli.main(
        [
            "verify",
            "cpu",
            "--prometheus-url",
            "http://prometheus:9090",
            "--namespace",
            "app",
            "--pod-regex",
            "jobs-api-.*",
            "--container",
            "jobs-api",
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
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"value":"0.2"' in captured.out
    assert '"acquisition"' in captured.out
    assert '"queries"' in captured.out
