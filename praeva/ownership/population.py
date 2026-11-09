"""POPULATION-ENUMERATION-001: enumerate the target workload's population.

WORKLOAD-OWNERSHIP-001 answers "did this pod belong to the target?" about a
pod someone already chose. No number of those answers proves that none is
missing. This module walks the relation the other way, Deployment ->
ReplicaSet -> Pod, over evidence the ownership adapter already acquires for
the whole namespace.

It takes no selector. That is the point: a wrong regex cannot narrow an
enumeration that never sees one.

Pure function over acquired evidence. No Prometheus query, no network.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

POPULATION_ID = "POPULATION-ENUMERATION-001"

STATUS_ENUMERATED = "ENUMERATED"
STATUS_UNKNOWN = "UNKNOWN"

REASON_REPLICASET_ABSENT = "replicaset_series_absent_at_timestamp"
REASON_POD_ABSENT = "pod_series_absent_at_timestamp"
REASON_OUTSIDE_ACQUISITION = "timestamp_outside_acquisition"
REASON_POD_IDENTITY_AMBIGUOUS = "pod_identity_ambiguous_at_timestamp"
REASON_POD_OWNER_AMBIGUOUS = "pod_controller_owner_ambiguous"
REASON_REPLICASET_OWNER_AMBIGUOUS = "replicaset_controller_owner_ambiguous"
REASON_OWNER_METRIC_INVALID = "owner_metric_invalid"

VERDICT_COMPLETE = "COMPLETE"
VERDICT_OMISSION = "OMISSION"
VERDICT_FOREIGN = "FOREIGN"
VERDICT_BOTH = "OMISSION_AND_FOREIGN"


class PopulationEnumerationInputError(ValueError):
    """Raised when population enumeration receives malformed input."""


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PopulationEnumerationInputError(f"{field} must be an object")
    return value


def _decimal(value: Any, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PopulationEnumerationInputError(f"{field} must be an exact decimal") from exc
    if not result.is_finite():
        raise PopulationEnumerationInputError(f"{field} must be finite")
    return result


def _sample_is_valid(raw_value: Any) -> bool:
    """A kube_*_owner sample carries no information in its value, but a
    non-finite or unparseable one means the series cannot be trusted."""

    try:
        parsed = Decimal(str(raw_value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return parsed.is_finite()


def _samples_at(series: dict[str, Any], timestamp: Decimal) -> list[Any]:
    samples = series.get("samples")
    if not isinstance(samples, list):
        raise PopulationEnumerationInputError("owner series samples must be a list")

    found: list[Any] = []
    for point in samples:
        if not isinstance(point, dict):
            raise PopulationEnumerationInputError("owner series samples must be objects")
        if _decimal(point.get("timestamp"), field="sample.timestamp") == timestamp:
            found.append(point.get("value"))
    return found


def _series_list(evidence: dict[str, Any], *, key: str) -> list[dict[str, Any]]:
    series = evidence.get(key)
    if not isinstance(series, list):
        raise PopulationEnumerationInputError(f"evidence {key} must be a list")
    for entry in series:
        if not isinstance(entry, dict):
            raise PopulationEnumerationInputError(f"{key} entries must be objects")
    return series


def _target(target_workload: dict[str, Any], *, namespace: str) -> str:
    target = _mapping(target_workload, field="target_workload")
    for field in ("api_group", "kind", "namespace", "name"):
        if not isinstance(target.get(field), str) or not target[field]:
            raise PopulationEnumerationInputError(f"target_workload.{field} is required")
    if target["kind"] != "Deployment" or target["api_group"] != "apps":
        raise PopulationEnumerationInputError(
            "POPULATION-ENUMERATION-001 supports apps/Deployment only"
        )
    if target["namespace"] != namespace:
        raise PopulationEnumerationInputError(
            "target_workload.namespace must match the acquisition namespace"
        )
    return str(target["name"])


def _replicasets_at(
    series: list[dict[str, Any]],
    *,
    namespace: str,
    deployment: str,
    timestamp: Decimal,
) -> tuple[set[str], bool, str | None]:
    """Return the ReplicaSets owned by the target, whether any sample existed
    at this timestamp at all, and an ambiguity reason if one applies."""

    owners: dict[str, set[str]] = {}
    any_sample = False

    for entry in series:
        if entry.get("namespace") != namespace:
            continue
        name = entry.get("replicaset")
        if not isinstance(name, str) or not name:
            continue
        samples = _samples_at(entry, timestamp)
        if not samples:
            continue
        any_sample = True
        if len(samples) != 1 or not _sample_is_valid(samples[0]):
            return set(), any_sample, REASON_OWNER_METRIC_INVALID
        if entry.get("owner_is_controller") != "true":
            continue
        owner_kind = entry.get("owner_kind")
        owner_name = entry.get("owner_name")
        if not isinstance(owner_kind, str) or not isinstance(owner_name, str):
            return set(), any_sample, REASON_OWNER_METRIC_INVALID
        owners.setdefault(name, set()).add(f"{owner_kind}/{owner_name}")

    for refs in owners.values():
        if len(refs) > 1:
            return set(), any_sample, REASON_REPLICASET_OWNER_AMBIGUOUS

    matched = {
        name
        for name, refs in owners.items()
        if next(iter(refs)) == f"Deployment/{deployment}"
    }
    return matched, any_sample, None


def _pods_at(
    series: list[dict[str, Any]],
    *,
    namespace: str,
    replicasets: set[str],
    timestamp: Decimal,
) -> tuple[list[dict[str, str]], bool, str | None]:
    """Return the pods owned by those ReplicaSets, whether any sample existed
    at this timestamp at all, and an ambiguity reason if one applies."""

    uids_by_pod: dict[str, set[str]] = {}
    owners_by_pod: dict[str, set[str]] = {}
    any_sample = False

    for entry in series:
        if entry.get("namespace") != namespace:
            continue
        pod = entry.get("pod")
        if not isinstance(pod, str) or not pod:
            continue
        samples = _samples_at(entry, timestamp)
        if not samples:
            continue
        any_sample = True
        if len(samples) != 1 or not _sample_is_valid(samples[0]):
            return [], any_sample, REASON_OWNER_METRIC_INVALID
        if entry.get("owner_is_controller") != "true":
            continue
        uid = entry.get("uid")
        owner_kind = entry.get("owner_kind")
        owner_name = entry.get("owner_name")
        if not all(isinstance(value, str) for value in (uid, owner_kind, owner_name)):
            return [], any_sample, REASON_OWNER_METRIC_INVALID
        uids_by_pod.setdefault(pod, set()).add(str(uid))
        owners_by_pod.setdefault(pod, set()).add(f"{owner_kind}/{owner_name}")

    # A pod name resolving to more than one UID at the same instant is the
    # simultaneous reuse case; it is never resolved by choosing one.
    for uids in uids_by_pod.values():
        if len(uids) > 1:
            return [], any_sample, REASON_POD_IDENTITY_AMBIGUOUS

    for refs in owners_by_pod.values():
        if len(refs) > 1:
            return [], any_sample, REASON_POD_OWNER_AMBIGUOUS

    owned = [
        {"pod": pod, "uid": next(iter(uids_by_pod[pod]))}
        for pod, refs in owners_by_pod.items()
        if next(iter(refs)).split("/", 1)[0] == "ReplicaSet"
        and next(iter(refs)).split("/", 1)[1] in replicasets
    ]
    return sorted(owned, key=lambda item: item["pod"]), any_sample, None


def _compare(owned: list[dict[str, str]], observed: Any) -> dict[str, Any] | None:
    if observed is None:
        return None
    if not isinstance(observed, list) or any(
        not isinstance(name, str) or not name for name in observed
    ):
        raise PopulationEnumerationInputError(
            "observed pods must be a list of non-empty pod names"
        )

    # Compared by name: the cAdvisor series the Verify observes carry no UID,
    # so a name is the only key the two sides share. The enumerated UID
    # travels in owned_pods as context for identity continuity.
    owned_names = {entry["pod"] for entry in owned}
    observed_names = set(observed)

    missing = sorted(owned_names - observed_names)
    foreign = sorted(observed_names - owned_names)

    if missing and foreign:
        verdict = VERDICT_BOTH
    elif missing:
        verdict = VERDICT_OMISSION
    elif foreign:
        verdict = VERDICT_FOREIGN
    else:
        verdict = VERDICT_COMPLETE

    return {"verdict": verdict, "missing": missing, "foreign": foreign}


def enumerate_population(
    *,
    evidence: dict[str, Any],
    target_workload: dict[str, Any],
    timestamps: list[str],
    observed_pods_by_timestamp: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Enumerate the pods the target Deployment owned at each timestamp.

    Takes no selector, by contract: enumeration that cannot be narrowed by a
    caller's regex is the whole reason this is trustworthy.
    """

    evidence_map = _mapping(evidence, field="evidence")
    acquisition = _mapping(evidence_map.get("acquisition"), field="evidence.acquisition")
    namespace = acquisition.get("namespace")
    if not isinstance(namespace, str) or not namespace:
        raise PopulationEnumerationInputError("acquisition.namespace is required")

    deployment = _target(target_workload, namespace=namespace)
    start = _decimal(acquisition.get("start"), field="acquisition.start")
    end = _decimal(acquisition.get("end"), field="acquisition.end")
    step = _decimal(acquisition.get("step"), field="acquisition.step")
    if step <= 0:
        raise PopulationEnumerationInputError("acquisition.step must be positive")

    pod_series = _series_list(evidence_map, key="pod_owner_series")
    replicaset_series = _series_list(evidence_map, key="replicaset_owner_series")

    if not isinstance(timestamps, list) or not timestamps:
        raise PopulationEnumerationInputError("timestamps must be a non-empty list")
    observed_map = observed_pods_by_timestamp or {}
    if not isinstance(observed_map, dict):
        raise PopulationEnumerationInputError("observed_pods_by_timestamp must be an object")

    resolved: dict[str, Any] = {}
    for raw_timestamp in timestamps:
        timestamp = _decimal(raw_timestamp, field="timestamp")
        key = str(raw_timestamp)

        on_grid = (timestamp - start) % step == 0
        if timestamp < start or timestamp > end or not on_grid:
            resolved[key] = {
                "status": STATUS_UNKNOWN,
                "reason": REASON_OUTSIDE_ACQUISITION,
            }
            continue

        replicasets, rs_sampled, rs_reason = _replicasets_at(
            replicaset_series,
            namespace=namespace,
            deployment=deployment,
            timestamp=timestamp,
        )
        if rs_reason is not None:
            resolved[key] = {"status": STATUS_UNKNOWN, "reason": rs_reason}
            continue
        # Absence of every sample is a gap in the series. Absence of a match
        # among present samples is a Deployment with no ReplicaSets. Only the
        # first is ignorance, and conflating them would let a gap fabricate a
        # vacuously complete population.
        if not rs_sampled:
            resolved[key] = {
                "status": STATUS_UNKNOWN,
                "reason": REASON_REPLICASET_ABSENT,
            }
            continue

        owned, pod_sampled, pod_reason = _pods_at(
            pod_series,
            namespace=namespace,
            replicasets=replicasets,
            timestamp=timestamp,
        )
        if pod_reason is not None:
            resolved[key] = {"status": STATUS_UNKNOWN, "reason": pod_reason}
            continue
        if not pod_sampled:
            resolved[key] = {"status": STATUS_UNKNOWN, "reason": REASON_POD_ABSENT}
            continue

        entry: dict[str, Any] = {
            "status": STATUS_ENUMERATED,
            "replicasets": sorted(replicasets),
            "owned_pods": owned,
        }
        comparison = _compare(owned, observed_map.get(key))
        if comparison is not None:
            entry["comparison"] = comparison
        resolved[key] = entry

    return {
        "population_id": POPULATION_ID,
        "target": {
            "namespace": namespace,
            "group": str(target_workload["api_group"]),
            "kind": str(target_workload["kind"]),
            "name": deployment,
        },
        "acquisition": {
            "namespace": namespace,
            "start": str(acquisition.get("start")),
            "end": str(acquisition.get("end")),
            "step": str(acquisition.get("step")),
        },
        "timestamps": resolved,
    }
