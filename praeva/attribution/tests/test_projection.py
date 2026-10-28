from __future__ import annotations

import importlib

import pytest


def _projection():
    return importlib.import_module("praeva.attribution.projection")


def _ownership_fact(*, uid: str = "uid-a", relation: str = "TARGET_MATCH") -> dict:
    return {
        "evidence_status": "VALID",
        "relation": relation,
        "pod_identity": {
            "namespace": "app",
            "name": "pod-a",
            "uid": uid,
        },
        "evidence_refs": ["pod_owner", "replicaset_owner"],
    }


def _unknown_ownership(reason_code: str = "pod_owner_missing_at_timestamp") -> dict:
    return {
        "evidence_status": "UNKNOWN",
        "reason_code": reason_code,
        "reason": "ownership is unavailable at required timestamp",
        "evidence_refs": [],
    }


def _ownership_report(points: dict[str, dict]) -> dict:
    return {
        "ownership_id": "WORKLOAD-OWNERSHIP-001",
        "target_workload": {
            "api_group": "apps",
            "kind": "Deployment",
            "namespace": "app",
            "name": "jobs-api",
        },
        "pods": {
            "pod-a": {
                "required_timestamps": sorted(points, key=int),
                "ownership": points,
            }
        },
    }


def _support(
    *,
    start: str = "0",
    end: str = "30",
    required: list[str] | None = None,
    boundary_proven: bool = True,
) -> dict:
    return {
        "start": start,
        "end": end,
        "required_timestamps": required or ["0", "15", "30"],
        "boundary_proven": boundary_proven,
    }


def _fact(
    *,
    family: str = "cpu_long",
    evaluated_at: str | float = "30",
    creation_timestamp: str = "-100",
    nominal: dict | None = None,
    observed_sample: dict | None = None,
    extra: dict | None = None,
) -> dict:
    result = {
        "fact_id": f"{family}:pod-a:{evaluated_at}",
        "pod": "pod-a",
        "evidence_family": family,
        "evaluated_at": evaluated_at,
        "support": {
            "nominal": nominal or _support(),
            "observed_sample": observed_sample,
        },
        "creation_by_uid": {"uid-a": creation_timestamp},
    }
    if extra:
        result.update(extra)
    return result


def _population(*, long_status: str = "COMPLETE", short_status: str = "COMPLETE") -> dict:
    return {
        "cpu_short": {"status": short_status, "diagnostics": []},
        "cpu_long": {"status": long_status, "diagnostics": []},
    }


def _requirements() -> dict:
    return {
        "CRITICAL": [{"quantifier": "EXISTS", "domain": "cpu_long"}],
        "HIGH": [
            {"quantifier": "EXISTS", "domain": "cpu_short"},
            {"quantifier": "FORALL", "domain": "cpu_long"},
        ],
        "MEDIUM": [
            {"quantifier": "FORALL", "domain": "cpu_short"},
            {"quantifier": "FORALL", "domain": "cpu_long"},
        ],
        "LOW": [
            {"quantifier": "FORALL", "domain": "cpu_short"},
            {"quantifier": "FORALL", "domain": "cpu_long"},
        ],
    }


def _project(
    *,
    report: dict,
    facts: list[dict],
    target_domain_status: str = "DETERMINED",
    population: dict | None = None,
    requirements: dict | None = None,
) -> dict:
    module = _projection()
    return module.project_attribution_decision(
        target_domain_status=target_domain_status,
        ownership_report=report,
        facts=facts,
        population_evidence=population or _population(),
        level_requirements=requirements or _requirements(),
    )


def test_r1_stable_nominal_support_is_attributed_and_levels_are_eligible():
    report = _ownership_report(
        {
            "0": _ownership_fact(),
            "15": _ownership_fact(),
            "30": _ownership_fact(),
        }
    )

    result = _project(report=report, facts=[_fact()])

    assert result["analysis"] == {"status": "ADMISSIBLE"}
    assert result["facts"]["cpu_long:pod-a:30"]["status"] == "ATTRIBUTED"
    assert result["facts"]["cpu_long:pod-a:30"]["support_source"] == "NOMINAL"
    assert all(
        item["status"] == "ELIGIBLE"
        for item in result["level_eligibility"].values()
    )


def test_s2_young_pod_is_unattributed_without_invalidating_analysis():
    report = _ownership_report(
        {
            "0": _ownership_fact(),
            "15": _ownership_fact(),
            "30": _ownership_fact(),
        }
    )

    result = _project(
        report=report,
        facts=[_fact(creation_timestamp="10")],
    )

    fact = result["facts"]["cpu_long:pod-a:30"]
    assert result["analysis"]["status"] == "ADMISSIBLE"
    assert fact["status"] == "UNATTRIBUTED"
    assert fact["class"] == "support_predates_pod"


def test_s3_uid_change_is_identity_discontinuity_even_when_all_points_target_match():
    report = _ownership_report(
        {
            "0": _ownership_fact(uid="uid-a"),
            "15": _ownership_fact(uid="uid-a"),
            "30": _ownership_fact(uid="uid-b"),
        }
    )

    result = _project(report=report, facts=[_fact()])

    fact = result["facts"]["cpu_long:pod-a:30"]
    assert fact["status"] == "UNATTRIBUTED"
    assert fact["class"] == "identity_discontinuity"


def test_s4_s7_foreign_pod_is_unattributed_but_analysis_remains_admissible():
    report = _ownership_report(
        {
            "0": _ownership_fact(relation="TARGET_DIFFERS"),
            "15": _ownership_fact(relation="TARGET_DIFFERS"),
            "30": _ownership_fact(relation="TARGET_DIFFERS"),
        }
    )

    result = _project(report=report, facts=[_fact()])

    assert result["analysis"]["status"] == "ADMISSIBLE"
    fact = result["facts"]["cpu_long:pod-a:30"]
    assert fact["status"] == "UNATTRIBUTED"
    assert fact["class"] == "foreign_workload"


def test_s5_selector_omission_blocks_forall_but_not_exists_on_incomplete_domain():
    report = _ownership_report({"0": _ownership_fact()})
    requirements = {
        "EXISTENTIAL_LEVEL": [{"quantifier": "EXISTS", "domain": "cpu_long"}],
        "UNIVERSAL_LEVEL": [{"quantifier": "FORALL", "domain": "cpu_long"}],
    }
    population = {
        "cpu_long": {
            "status": "INCOMPLETE",
            "diagnostics": ["selector_omission"],
        }
    }

    result = _project(
        report=report,
        facts=[],
        population=population,
        requirements=requirements,
    )

    assert result["level_eligibility"]["EXISTENTIAL_LEVEL"]["status"] == "ELIGIBLE"
    assert result["level_eligibility"]["UNIVERSAL_LEVEL"] == {
        "status": "BLOCKED",
        "blocked_by": ["population_incomplete:cpu_long"],
    }


def test_s6_derived_evidence_missing_has_same_gating_consequence_as_s5():
    report = _ownership_report({"0": _ownership_fact()})
    requirements = {
        "EXISTENTIAL_LEVEL": [{"quantifier": "EXISTS", "domain": "cpu_long"}],
        "UNIVERSAL_LEVEL": [{"quantifier": "FORALL", "domain": "cpu_long"}],
    }
    population = {
        "cpu_long": {
            "status": "INCOMPLETE",
            "diagnostics": ["derived_evidence_missing"],
        }
    }

    result = _project(
        report=report,
        facts=[],
        population=population,
        requirements=requirements,
    )

    assert result["level_eligibility"]["EXISTENTIAL_LEVEL"]["status"] == "ELIGIBLE"
    assert result["level_eligibility"]["UNIVERSAL_LEVEL"]["status"] == "BLOCKED"


def test_s9_incomplete_long_domain_keeps_critical_eligible_and_blocks_high():
    report = _ownership_report({"0": _ownership_fact()})

    result = _project(
        report=report,
        facts=[],
        population=_population(long_status="INCOMPLETE"),
    )

    assert result["level_eligibility"]["CRITICAL"]["status"] == "ELIGIBLE"
    assert result["level_eligibility"]["HIGH"] == {
        "status": "BLOCKED",
        "blocked_by": ["population_incomplete:cpu_long"],
    }


def test_s10_unproven_support_boundary_degrades_fact_not_analysis():
    report = _ownership_report(
        {
            "0": _ownership_fact(),
            "15": _ownership_fact(),
            "30": _ownership_fact(),
        }
    )
    nominal = _support(boundary_proven=False)

    result = _project(report=report, facts=[_fact(nominal=nominal)])

    assert result["analysis"]["status"] == "ADMISSIBLE"
    fact = result["facts"]["cpu_long:pod-a:30"]
    assert fact["status"] == "UNATTRIBUTED"
    assert fact["class"] == "support_boundary_unproven"


def test_r2_residual_with_current_wire_is_unattributed_when_nominal_support_is_unproven():
    report = _ownership_report(
        {
            "0": _ownership_fact(),
            "15": _ownership_fact(),
            "30": _unknown_ownership(),
        }
    )

    result = _project(report=report, facts=[_fact()])

    fact = result["facts"]["cpu_long:pod-a:30"]
    assert fact["status"] == "UNATTRIBUTED"
    assert fact["class"] == "attribution_unproven"
    assert fact["support_source"] == "NOMINAL"


def test_r2_residual_can_be_attributed_with_explicit_observed_sample_support():
    report = _ownership_report(
        {
            "0": _ownership_fact(),
            "15": _ownership_fact(),
            "30": _unknown_ownership(),
        }
    )
    observed = _support(end="15", required=["0", "15"])

    result = _project(
        report=report,
        facts=[_fact(observed_sample=observed)],
    )

    fact = result["facts"]["cpu_long:pod-a:30"]
    assert fact["status"] == "ATTRIBUTED"
    assert fact["support_source"] == "OBSERVED_SAMPLE"


def test_coverage_complete_field_does_not_shorten_or_redefine_support():
    report = _ownership_report(
        {
            "0": _ownership_fact(),
            "15": _ownership_fact(),
            "30": _unknown_ownership(),
        }
    )

    result = _project(
        report=report,
        facts=[_fact(extra={"coverage_complete": True})],
    )

    fact = result["facts"]["cpu_long:pod-a:30"]
    assert fact["status"] == "UNATTRIBUTED"
    assert fact["class"] == "attribution_unproven"
    assert fact["support_source"] == "NOMINAL"


def test_same_window_families_can_have_independent_support_attribution():
    report = _ownership_report(
        {
            "0": _ownership_fact(),
            "15": _ownership_fact(),
            "30": _unknown_ownership(),
        }
    )
    observed = _support(end="15", required=["0", "15"])

    result = _project(
        report=report,
        facts=[
            _fact(family="cpu_long", observed_sample=observed),
            _fact(family="cfs_throttled_long"),
        ],
    )

    assert result["facts"]["cpu_long:pod-a:30"]["status"] == "ATTRIBUTED"
    throttling = result["facts"]["cfs_throttled_long:pod-a:30"]
    assert throttling["status"] == "UNATTRIBUTED"
    assert throttling["class"] == "attribution_unproven"


def test_undeterminable_target_domain_is_semantically_inadmissible():
    report = _ownership_report({})

    result = _project(
        report=report,
        facts=[],
        target_domain_status="UNDETERMINABLE",
    )

    assert result["analysis"] == {
        "status": "INADMISSIBLE",
        "reason": "target_domain_undeterminable",
    }


def test_determined_empty_population_is_admissible_not_unknown_domain():
    report = _ownership_report({})

    result = _project(report=report, facts=[], target_domain_status="DETERMINED")

    assert result["analysis"] == {"status": "ADMISSIBLE"}


def test_arbitrary_level_names_use_generic_quantifier_gating():
    report = _ownership_report({})
    requirements = {
        "PURPLE": [{"quantifier": "EXISTS", "domain": "signal_x"}],
        "ORANGE": [{"quantifier": "FORALL", "domain": "signal_x"}],
    }
    population = {
        "signal_x": {"status": "INCOMPLETE", "diagnostics": ["synthetic"]}
    }

    result = _project(
        report=report,
        facts=[],
        population=population,
        requirements=requirements,
    )

    assert result["level_eligibility"]["PURPLE"]["status"] == "ELIGIBLE"
    assert result["level_eligibility"]["ORANGE"]["status"] == "BLOCKED"


def test_float_timestamp_is_structural_input_error():
    module = _projection()
    report = _ownership_report(
        {
            "0": _ownership_fact(),
            "15": _ownership_fact(),
            "30": _ownership_fact(),
        }
    )

    with pytest.raises(module.AttributionDecisionInputError):
        module.project_attribution_decision(
            target_domain_status="DETERMINED",
            ownership_report=report,
            facts=[_fact(evaluated_at=30.0)],
            population_evidence=_population(),
            level_requirements=_requirements(),
        )
