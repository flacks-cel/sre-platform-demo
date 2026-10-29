from __future__ import annotations

import pytest

from praeva.attribution.summary_proof import (
    AttributionSummaryProofInputError,
    project_summary_proof,
)


def test_valid_ratio_max_timestamp_missing_component_fact_is_structural_error():
    verify_report = {
        "status": "VALID",
        "windows": {"short": "2m", "long": "5m"},
        "acquisition": {
            "namespace": "app",
            "start": "0",
            "end": "30",
            "step": "15",
        },
        "pods": {
            "pod-a": {
                "cpu_usage": {
                    "short": {
                        "status": "VALID",
                        "window": "2m",
                        "max": "0.4",
                        "max_timestamp": "30",
                        "query_key": "cpu_short",
                        "points": 3,
                        "min": "0.1",
                    },
                    "long": {
                        "status": "UNKNOWN",
                        "window": "5m",
                        "reason_code": "missing_cpu",
                    },
                },
                "cpu_limit_ratio": {
                    "status": "VALID",
                    "window": "2m",
                    "max": {"numerator": "0.4", "denominator": "0.5"},
                    "max_timestamp": "30",
                    "query_keys": {
                        "numerator": "cpu_short",
                        "denominator": "cpu_limit",
                    },
                    "points": 3,
                },
            }
        },
    }
    facts = [
        {
            "fact_id": f"cpu_short:pod-a:{timestamp}",
            "pod": "pod-a",
            "evidence_family": "cpu_short",
            "evaluated_at": timestamp,
        }
        for timestamp in ("0", "15", "30")
    ] + [
        {
            "fact_id": f"cpu_limit:pod-a:{timestamp}",
            "pod": "pod-a",
            "evidence_family": "cpu_limit",
            "evaluated_at": timestamp,
        }
        for timestamp in ("0", "15", "45")
    ]
    fact_input = {
        "fact_input_id": "ATTRIBUTION-FACT-INPUT-001",
        "facts": facts,
    }
    attribution_projection = {
        "facts": {
            fact["fact_id"]: {
                "status": "ATTRIBUTED",
                "support_source": "NOMINAL",
                "evidence_refs": [],
            }
            for fact in facts
        }
    }

    with pytest.raises(AttributionSummaryProofInputError):
        project_summary_proof(
            verify_report=verify_report,
            fact_input=fact_input,
            attribution_projection=attribution_projection,
        )
