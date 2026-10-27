from __future__ import annotations

import importlib.util
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parents[1]
R2_ANALYZER = SPIKE_DIR / "r2_analyze.py"


def _analyzer():
    spec = importlib.util.spec_from_file_location("spike003_r2_analyze", R2_ANALYZER)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load R2 analyzer: {R2_ANALYZER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _matrix(result):
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": result,
        },
    }


def test_observed_pods_are_indexed_per_evaluation_timestamp() -> None:
    analyzer = _analyzer()
    payload = _matrix(
        [
            {
                "metric": {"pod": "jobs-api-old"},
                "values": [[0, "1"], [15, "1"]],
            },
            {
                "metric": {"pod": "jobs-api-new"},
                "values": [[15, "1"], [30, "1"]],
            },
        ]
    )

    observed = analyzer._observed_pods_by_timestamp(payload, label="cpu_short")

    assert observed == {
        "0": {"jobs-api-old"},
        "15": {"jobs-api-old", "jobs-api-new"},
        "30": {"jobs-api-new"},
    }


def test_pod_creation_is_keyed_by_pod_and_uid() -> None:
    analyzer = _analyzer()
    payload = _matrix(
        [
            {
                "metric": {"pod": "jobs-api-old", "uid": "uid-old"},
                "values": [[0, "-100"], [15, "-100"]],
            },
            {
                "metric": {"pod": "jobs-api-new", "uid": "uid-new"},
                "values": [[15, "10"], [30, "10"]],
            },
        ]
    )

    created = analyzer._creation_by_identity(payload)

    assert created == {
        ("jobs-api-old", "uid-old"): "-100",
        ("jobs-api-new", "uid-new"): "10",
    }


def test_population_transition_preserves_rollout_overlap() -> None:
    analyzer = _analyzer()
    population = {
        "0": {"target_owned": ["jobs-api-old"]},
        "15": {"target_owned": ["jobs-api-new", "jobs-api-old"]},
        "30": {"target_owned": ["jobs-api-new"]},
    }

    transitions = analyzer._population_transitions(population)

    assert transitions == [
        {
            "timestamp": "15",
            "from_target_owned": ["jobs-api-old"],
            "to_target_owned": ["jobs-api-new", "jobs-api-old"],
        },
        {
            "timestamp": "30",
            "from_target_owned": ["jobs-api-new", "jobs-api-old"],
            "to_target_owned": ["jobs-api-new"],
        },
    ]


def test_source_age_summary_is_descriptive_only() -> None:
    analyzer = _analyzer()
    payload = _matrix(
        [
            {
                "metric": {"pod": "jobs-api-old"},
                "values": [[30, "20"], [45, "35"]],
            }
        ]
    )

    summary = analyzer._source_age_summary(payload, label="pod_owner_source_timestamp")

    assert summary == {
        "samples": 2,
        "min_age_seconds": "10",
        "max_age_seconds": "10",
    }
