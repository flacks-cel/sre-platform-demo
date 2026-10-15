from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"
CURRENT = "00_current_cases.yaml"
PROPOSED = "00_proposed_cases.yaml"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _api():
    from praeva.change.cpu_limit import ChangeInputError, analyze_change

    return ChangeInputError, analyze_change


def _analyze(
    name: str,
    *,
    current: str = CURRENT,
    proposed: str = PROPOSED,
    container: str = "jobs-api",
    container_space: str = "containers",
    api_group: str = "apps",
    kind: str = "Deployment",
    namespace: str = "app",
):
    _, analyze_change = _api()
    return analyze_change(
        current_manifest=_fixture(current),
        proposed_manifest=_fixture(proposed),
        api_group=api_group,
        kind=kind,
        namespace=namespace,
        name=name,
        container=container,
        container_space=container_space,
    )


def test_non_terminating_ratio_is_exact_and_reduced():
    result = _analyze("ratio-third")

    assert result["current_declared_cpu_limit"] == 300
    assert result["proposed_declared_cpu_limit"] == 100
    assert result["direction"] == "DECREASE"
    assert result["change_ratio"] == {"numerator": 1, "denominator": 3}


def test_500m_to_250m_is_decrease_with_proposed_over_current_ratio():
    result = _analyze("decrease")

    assert result["direction"] == "DECREASE"
    assert result["change_ratio"] == {"numerator": 1, "denominator": 2}


def test_250m_to_500m_is_reciprocal_increase():
    result = _analyze("increase")

    assert result["direction"] == "INCREASE"
    assert result["change_ratio"] == {"numerator": 2, "denominator": 1}


def test_equivalent_cpu_syntax_normalizes_to_unchanged():
    result = _analyze("equivalent")

    assert result["current_declared_cpu_limit"] == 500
    assert result["proposed_declared_cpu_limit"] == 500
    assert result["direction"] == "UNCHANGED"
    assert result["change_ratio"] == {"numerator": 1, "denominator": 1}


def test_absent_limit_to_declared_limit_is_limit_added():
    result = _analyze("limit-added")

    assert result["current_declared_cpu_limit"] == "ABSENT"
    assert result["proposed_declared_cpu_limit"] == 500
    assert result["direction"] == "LIMIT_ADDED"
    assert result["change_ratio"] == "UNDEFINED"


def test_declared_limit_to_absent_limit_is_limit_removed():
    result = _analyze("limit-removed")

    assert result["current_declared_cpu_limit"] == 500
    assert result["proposed_declared_cpu_limit"] == "ABSENT"
    assert result["direction"] == "LIMIT_REMOVED"
    assert result["change_ratio"] == "UNDEFINED"


def test_valid_dollar_parentheses_in_args_is_not_template_detection():
    result = _analyze("dollar-args")

    assert result["direction"] == "UNCHANGED"
    assert result["change_ratio"] == {"numerator": 1, "denominator": 1}


def test_unrendered_template_is_input_error():
    ChangeInputError, analyze_change = _api()
    invalid = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.name }}
  namespace: app
spec:
  template:
    spec:
      containers:
        - name: jobs-api
          image: example/jobs-api:test
"""

    with pytest.raises(ChangeInputError, match="render"):
        analyze_change(
            current_manifest=_fixture(CURRENT),
            proposed_manifest=invalid,
            api_group="apps",
            kind="Deployment",
            namespace="app",
            name="decrease",
            container="jobs-api",
        )


def test_identity_must_resolve_in_both_bundles():
    ChangeInputError, _ = _api()

    with pytest.raises(ChangeInputError):
        _analyze("identity-current")


def test_container_is_required_even_for_single_container():
    ChangeInputError, _ = _api()

    with pytest.raises(ChangeInputError):
        _analyze("decrease", container="")


def test_explicit_container_resolves_in_multi_container_podspec():
    result = _analyze("multi-container")

    assert result["container"] == {"name": "jobs-api", "space": "containers"}
    assert result["direction"] == "UNCHANGED"


def test_init_container_name_does_not_fallback_from_default_container_space():
    ChangeInputError, _ = _api()

    with pytest.raises(ChangeInputError):
        _analyze("init-only", container="bootstrap")


@pytest.mark.parametrize("name", ["submilli-decimal", "submilli-micro"])
def test_sub_millicore_precision_is_rejected_without_rounding(name: str):
    ChangeInputError, _ = _api()

    with pytest.raises(ChangeInputError):
        _analyze(name)


def test_request_only_change_keeps_limit_unchanged_and_captures_requests():
    result = _analyze("request-only")

    assert result["direction"] == "UNCHANGED"
    assert result["current_declared_cpu_request"] == 100
    assert result["proposed_declared_cpu_request"] == 200


def test_duplicate_identity_in_multidocument_bundle_is_input_error():
    ChangeInputError, _ = _api()

    with pytest.raises(ChangeInputError):
        _analyze("duplicate-target", current="duplicate_current.yaml")


def test_kubernetes_list_resolves_exactly_one_target():
    result = _analyze(
        "list-target",
        current="list_current.yaml",
        proposed="list_proposed.yaml",
    )

    assert result["direction"] == "DECREASE"
    assert result["change_ratio"] == {"numerator": 1, "denominator": 2}


def test_explicit_namespace_supplies_context_when_manifest_omits_namespace():
    result = _analyze("namespace-absent")

    assert result["workload_identity"] == {
        "group": "apps",
        "kind": "Deployment",
        "namespace": "app",
        "name": "namespace-absent",
    }


def test_zero_current_preserves_numeric_direction_but_ratio_is_undefined():
    result = _analyze("zero-up")

    assert result["current_declared_cpu_limit"] == 0
    assert result["proposed_declared_cpu_limit"] == 500
    assert result["direction"] == "INCREASE"
    assert result["change_ratio"] == "UNDEFINED"


def test_zero_proposed_preserves_numeric_direction_but_ratio_is_undefined():
    result = _analyze("zero-down")

    assert result["current_declared_cpu_limit"] == 500
    assert result["proposed_declared_cpu_limit"] == 0
    assert result["direction"] == "DECREASE"
    assert result["change_ratio"] == "UNDEFINED"


def test_zero_to_zero_is_unchanged_with_undefined_ratio():
    result = _analyze("zero-same")

    assert result["direction"] == "UNCHANGED"
    assert result["change_ratio"] == "UNDEFINED"


def test_absent_to_absent_is_unchanged_with_undefined_ratio():
    result = _analyze("absent-same")

    assert result["current_declared_cpu_limit"] == "ABSENT"
    assert result["proposed_declared_cpu_limit"] == "ABSENT"
    assert result["direction"] == "UNCHANGED"
    assert result["change_ratio"] == "UNDEFINED"


def test_unsupported_workload_kind_is_input_error():
    ChangeInputError, _ = _api()

    with pytest.raises(ChangeInputError):
        _analyze("decrease", kind="StatefulSet")


def test_output_uses_direction_not_renamed_change_kind():
    result = _analyze("decrease")

    assert "direction" in result
    assert "limit_change_kind" not in result
