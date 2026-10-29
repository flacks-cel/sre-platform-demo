from __future__ import annotations

import pytest

from praeva.attribution.fact_input import AttributionFactInputError, build_attribution_fact_inputs


def _point(timestamp: str, *, query_key: str) -> dict:
    return {"timestamp": timestamp, "value": "1", "query_key": query_key}


def _normalized() -> dict:
    return {
        "pods": [
            {
                "name": "pod-a",
                "cpu_short": [],
                "cpu_long": [_point("600", query_key="cpu_long")],
                "cpu_limit": None,
                "cfs_throttled_short": [],
                "cfs_throttled_long": [],
            }
        ],
        "short_window": "2m",
        "long_window": "5m",
        "acquisition": {
            "namespace": "app",
            "pod_selector": {"type": "regex", "value": "jobs-api-.*"},
            "container": "jobs-api",
            "start": "600",
            "end": "900",
            "step": "15",
        },
        "queries": {
            "cpu_short": {"promql": "cpu short", "rate_window": "2m"},
            "cpu_long": {"promql": "cpu long", "rate_window": "5m"},
            "cpu_limit": {"promql": "cpu limit", "rate_window": None},
        },
    }


def test_emitted_family_requires_query_provenance():
    normalized = _normalized()
    del normalized["queries"]["cpu_long"]

    with pytest.raises(AttributionFactInputError):
        build_attribution_fact_inputs(
            normalized_evidence=normalized,
            creation_by_pod_uid={},
        )


def test_point_query_key_must_match_emitted_family():
    normalized = _normalized()
    normalized["pods"][0]["cpu_long"][0]["query_key"] = "cpu_short"

    with pytest.raises(AttributionFactInputError):
        build_attribution_fact_inputs(
            normalized_evidence=normalized,
            creation_by_pod_uid={},
        )
