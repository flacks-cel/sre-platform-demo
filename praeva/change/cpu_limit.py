from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

import yaml

ABSENT = "ABSENT"
UNDEFINED = "UNDEFINED"
_ALLOWED_CONTAINER_SPACES = {"containers", "initContainers", "ephemeralContainers"}


class ChangeInputError(ValueError):
    """Raised when CHANGE-INPUT-001 receives invalid manifest input."""


def _parse_bundle(manifest: str, *, side: str) -> list[dict[str, Any]]:
    if not isinstance(manifest, str) or not manifest.strip():
        raise ChangeInputError(f"{side} manifest is empty")

    try:
        documents = list(yaml.load_all(manifest, Loader=yaml.BaseLoader))
    except yaml.YAMLError as exc:
        raise ChangeInputError(
            f"{side} manifest is not a concrete rendered Kubernetes manifest"
        ) from exc

    resources: list[dict[str, Any]] = []

    def add_resource(value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, dict):
            raise ChangeInputError(
                f"{side} manifest contains a non-concrete resource; render it first"
            )

        if value.get("kind") == "List":
            items = value.get("items")
            if not isinstance(items, list):
                raise ChangeInputError(f"{side} Kubernetes List has invalid items")
            for item in items:
                add_resource(item)
            return

        resources.append(value)

    for document in documents:
        add_resource(document)

    if not resources:
        raise ChangeInputError(f"{side} manifest contains no Kubernetes resources")

    return resources


def _api_group(api_version: str) -> str:
    return api_version.split("/", 1)[0] if "/" in api_version else ""


def _resource_identity(
    resource: dict[str, Any],
    *,
    side: str,
    namespace_context: str,
) -> tuple[str, str, str, str]:
    api_version = resource.get("apiVersion")
    kind = resource.get("kind")
    metadata = resource.get("metadata")

    if (
        not isinstance(api_version, str)
        or not isinstance(kind, str)
        or not isinstance(metadata, dict)
    ):
        raise ChangeInputError(
            f"{side} manifest contains a non-concrete resource; render it first"
        )

    name = metadata.get("name")
    declared_namespace = metadata.get("namespace")

    if not isinstance(name, str):
        raise ChangeInputError(
            f"{side} manifest contains a non-concrete resource name; render it first"
        )
    if declared_namespace is not None and not isinstance(declared_namespace, str):
        raise ChangeInputError(
            f"{side} manifest contains a non-concrete namespace; render it first"
        )

    namespace = declared_namespace if declared_namespace is not None else namespace_context
    return _api_group(api_version), kind, namespace, name


def _select_resource(
    resources: list[dict[str, Any]],
    *,
    side: str,
    api_group: str,
    kind: str,
    namespace: str,
    name: str,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    wanted = (api_group, kind, namespace, name)

    for resource in resources:
        identity = _resource_identity(resource, side=side, namespace_context=namespace)
        if identity == wanted:
            matches.append(resource)

    if not matches:
        raise ChangeInputError(
            f"{side} manifest does not contain exactly one selected workload {wanted}"
        )
    if len(matches) > 1:
        raise ChangeInputError(f"{side} manifest contains multiple resources matching {wanted}")

    return matches[0]


def _select_container(
    resource: dict[str, Any],
    *,
    side: str,
    container: str,
    container_space: str,
) -> dict[str, Any]:
    spec = resource.get("spec")
    template = spec.get("template") if isinstance(spec, dict) else None
    template_spec = template.get("spec") if isinstance(template, dict) else None

    if not isinstance(template_spec, dict):
        raise ChangeInputError(f"{side} Deployment has no concrete PodSpec")

    entries = template_spec.get(container_space)
    if not isinstance(entries, list):
        raise ChangeInputError(
            f"container {container!r} was not found in {side} {container_space}"
        )

    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("name") == container
    ]

    if len(matches) != 1:
        raise ChangeInputError(
            f"container {container!r} was not found exactly once in {side} {container_space}"
        )

    return matches[0]


def _decimal_to_millicores(value: str) -> int:
    text = value.strip()
    if not text:
        raise ChangeInputError("CPU quantity is empty")

    multiplier = Decimal(1)
    numeric_text = text
    if text.endswith("m"):
        numeric_text = text[:-1]
    else:
        multiplier = Decimal(1000)

    try:
        quantity = Decimal(numeric_text)
    except InvalidOperation as exc:
        raise ChangeInputError(f"invalid CPU quantity: {value!r}") from exc

    if not quantity.is_finite() or quantity < 0:
        raise ChangeInputError(f"invalid CPU quantity: {value!r}")

    millicores = quantity * multiplier
    if millicores != millicores.to_integral_value():
        raise ChangeInputError(f"CPU quantity has sub-millicore precision: {value!r}")

    return int(millicores)


def _declared_cpu(container: dict[str, Any], section: str) -> int | str:
    resources = container.get("resources")
    if resources is None:
        return ABSENT
    if not isinstance(resources, dict):
        raise ChangeInputError("container resources must be a mapping")

    values = resources.get(section)
    if values is None:
        return ABSENT
    if not isinstance(values, dict):
        raise ChangeInputError(f"container resources.{section} must be a mapping")

    raw_cpu = values.get("cpu")
    if raw_cpu is None:
        return ABSENT
    if not isinstance(raw_cpu, str):
        raise ChangeInputError(f"container resources.{section}.cpu must be a scalar quantity")

    return _decimal_to_millicores(raw_cpu)


def _direction(current: int | str, proposed: int | str) -> str:
    if current == ABSENT and proposed == ABSENT:
        return "UNCHANGED"
    if current == ABSENT:
        return "LIMIT_ADDED"
    if proposed == ABSENT:
        return "LIMIT_REMOVED"

    if proposed < current:
        return "DECREASE"
    if proposed > current:
        return "INCREASE"
    return "UNCHANGED"


def _change_ratio(current: int | str, proposed: int | str) -> dict[str, int] | str:
    if current == ABSENT or proposed == ABSENT or current == 0 or proposed == 0:
        return UNDEFINED

    ratio = Fraction(proposed, current)
    return {"numerator": ratio.numerator, "denominator": ratio.denominator}


def analyze_change(
    *,
    current_manifest: str,
    proposed_manifest: str,
    api_group: str,
    kind: str,
    namespace: str,
    name: str,
    container: str,
    container_space: str = "containers",
) -> dict[str, Any]:
    """Return declared CPU change facts for one explicit Deployment/container."""

    if api_group != "apps" or kind != "Deployment":
        raise ChangeInputError("CHANGE-INPUT-001 supports only apps/Deployment")
    if not namespace:
        raise ChangeInputError("namespace is required")
    if not name:
        raise ChangeInputError("workload name is required")
    if not container:
        raise ChangeInputError("container is required")
    if container_space not in _ALLOWED_CONTAINER_SPACES:
        raise ChangeInputError(f"unsupported container space: {container_space}")

    current_resources = _parse_bundle(current_manifest, side="current")
    proposed_resources = _parse_bundle(proposed_manifest, side="proposed")

    current_resource = _select_resource(
        current_resources,
        side="current",
        api_group=api_group,
        kind=kind,
        namespace=namespace,
        name=name,
    )
    proposed_resource = _select_resource(
        proposed_resources,
        side="proposed",
        api_group=api_group,
        kind=kind,
        namespace=namespace,
        name=name,
    )

    current_container = _select_container(
        current_resource,
        side="current",
        container=container,
        container_space=container_space,
    )
    proposed_container = _select_container(
        proposed_resource,
        side="proposed",
        container=container,
        container_space=container_space,
    )

    current_limit = _declared_cpu(current_container, "limits")
    proposed_limit = _declared_cpu(proposed_container, "limits")
    current_request = _declared_cpu(current_container, "requests")
    proposed_request = _declared_cpu(proposed_container, "requests")

    return {
        "workload_identity": {
            "group": api_group,
            "kind": kind,
            "namespace": namespace,
            "name": name,
        },
        "container": {"name": container, "space": container_space},
        "current_declared_cpu_limit": current_limit,
        "proposed_declared_cpu_limit": proposed_limit,
        "direction": _direction(current_limit, proposed_limit),
        "change_ratio": _change_ratio(current_limit, proposed_limit),
        "current_declared_cpu_request": current_request,
        "proposed_declared_cpu_request": proposed_request,
    }
