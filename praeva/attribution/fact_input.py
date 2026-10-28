from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

FACT_INPUT_ID = "ATTRIBUTION-FACT-INPUT-001"

_RATE_FAMILIES = {
    "cpu_short": "short",
    "cpu_long": "long",
    "cfs_throttled_short": "short",
    "cfs_throttled_long": "long",
}
_POINT_FAMILIES = {"cpu_limit"}
_SUPPORTED_FAMILIES = {*_RATE_FAMILIES, *_POINT_FAMILIES}
_DURATION_RE = re.compile(r"^([1-9][0-9]*)([smhdw])$")
_DURATION_SECONDS = {
    "s": Decimal(1),
    "m": Decimal(60),
    "h": Decimal(3600),
    "d": Decimal(86400),
    "w": Decimal(604800),
}


class AttributionFactInputError(ValueError):
    """Raised when ATTRIBUTION-FACT-INPUT-001 receives inconsistent input."""


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise AttributionFactInputError(f"{field} must not be represented as float")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise AttributionFactInputError(f"{field} must be numeric") from exc
    else:
        raise AttributionFactInputError(f"{field} must be numeric")
    if not number.is_finite():
        raise AttributionFactInputError(f"{field} must be finite")
    return number


def _canonical_decimal(value: Any, *, field: str) -> str:
    number = _decimal(value, field=field)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _non_empty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AttributionFactInputError(f"{field} must be a non-empty string")
    return value


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AttributionFactInputError(f"{field} must be an object")
    return value


def _duration_seconds(value: Any, *, field: str) -> Decimal:
    text = _non_empty_string(value, field=field)
    match = _DURATION_RE.fullmatch(text)
    if match is None:
        raise AttributionFactInputError(
            f"{field} must use a positive integer with one of s, m, h, d, w"
        )
    amount = Decimal(match.group(1))
    return amount * _DURATION_SECONDS[match.group(2)]


def _ceil_div(numerator: Decimal, denominator: Decimal) -> int:
    quotient = numerator // denominator
    if numerator % denominator:
        quotient += 1
    return int(quotient)


def _validate_acquisition(normalized: dict[str, Any]) -> dict[str, Any]:
    acquisition = _mapping(normalized.get("acquisition"), field="normalized_evidence.acquisition")
    namespace = _non_empty_string(
        acquisition.get("namespace"),
        field="normalized_evidence.acquisition.namespace",
    )
    start = _decimal(acquisition.get("start"), field="normalized_evidence.acquisition.start")
    end = _decimal(acquisition.get("end"), field="normalized_evidence.acquisition.end")
    step = _decimal(acquisition.get("step"), field="normalized_evidence.acquisition.step")
    if step <= 0:
        raise AttributionFactInputError("normalized_evidence.acquisition.step must be positive")
    if end < start:
        raise AttributionFactInputError(
            "normalized_evidence.acquisition.end must not be before start"
        )
    return {
        "namespace": namespace,
        "start": start,
        "end": end,
        "step": step,
    }


def _validate_queries(
    normalized: dict[str, Any],
    *,
    short_window: str,
    long_window: str,
) -> None:
    queries = _mapping(normalized.get("queries"), field="normalized_evidence.queries")
    expected_windows = {
        "cpu_short": short_window,
        "cpu_long": long_window,
        "cfs_throttled_short": short_window,
        "cfs_throttled_long": long_window,
    }
    for family, expected_window in expected_windows.items():
        query = queries.get(family)
        if query is None:
            continue
        query_map = _mapping(query, field=f"normalized_evidence.queries.{family}")
        if query_map.get("rate_window") != expected_window:
            raise AttributionFactInputError(
                f"normalized_evidence.queries.{family}.rate_window is inconsistent"
            )

    limit_query = queries.get("cpu_limit")
    if limit_query is not None:
        _mapping(limit_query, field="normalized_evidence.queries.cpu_limit")


def _validate_creation_by_pod_uid(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise AttributionFactInputError("creation_by_pod_uid must be an object")

    result: dict[str, dict[str, str]] = {}
    for raw_pod, raw_uid_map in value.items():
        pod = _non_empty_string(raw_pod, field="creation_by_pod_uid pod")
        if not isinstance(raw_uid_map, dict):
            raise AttributionFactInputError(f"creation_by_pod_uid.{pod} must be an object")
        uid_map: dict[str, str] = {}
        for raw_uid, raw_timestamp in raw_uid_map.items():
            uid = _non_empty_string(raw_uid, field=f"creation_by_pod_uid.{pod} uid")
            uid_map[uid] = _canonical_decimal(
                raw_timestamp,
                field=f"creation_by_pod_uid.{pod}.{uid}",
            )
        result[pod] = uid_map
    return result


def _validate_pods(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AttributionFactInputError("normalized_evidence.pods must be a list")

    pods: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_pod in enumerate(value):
        if not isinstance(raw_pod, dict):
            raise AttributionFactInputError(f"normalized_evidence.pods[{index}] must be an object")
        pod_name = _non_empty_string(
            raw_pod.get("name"),
            field=f"normalized_evidence.pods[{index}].name",
        )
        if pod_name in seen:
            raise AttributionFactInputError(f"duplicate normalized pod {pod_name}")
        seen.add(pod_name)
        pods.append(raw_pod)
    return pods


def _series_points(pod: dict[str, Any], *, family: str, pod_name: str) -> list[dict[str, Any]]:
    raw_points = pod.get(family)
    if raw_points is None:
        return []
    if not isinstance(raw_points, list):
        raise AttributionFactInputError(f"pods.{pod_name}.{family} must be a list or null")
    points: list[dict[str, Any]] = []
    for index, point in enumerate(raw_points):
        if not isinstance(point, dict):
            raise AttributionFactInputError(
                f"pods.{pod_name}.{family}[{index}] must be an object"
            )
        points.append(point)
    return points


def _validate_sample_timestamp(
    raw_timestamp: Any,
    *,
    field: str,
    analysis_start: Decimal,
    analysis_end: Decimal,
    step: Decimal,
) -> tuple[Decimal, str]:
    timestamp = _decimal(raw_timestamp, field=field)
    if timestamp < analysis_start or timestamp > analysis_end:
        raise AttributionFactInputError(f"{field} is outside the acquisition interval")
    if (timestamp - analysis_start) % step != 0:
        raise AttributionFactInputError(f"{field} is off the acquisition grid")
    return timestamp, _canonical_decimal(timestamp, field=field)


def _grid_points(
    *,
    grid_start: Decimal,
    grid_step: Decimal,
    support_start: Decimal,
    support_end: Decimal,
) -> tuple[list[str], bool]:
    offset = support_start - grid_start
    first_index = _ceil_div(offset, grid_step)
    first = grid_start + Decimal(first_index) * grid_step
    boundary_proven = offset % grid_step == 0

    points: list[str] = []
    current = first
    while current <= support_end:
        points.append(_canonical_decimal(current, field="ownership required timestamp"))
        current += grid_step
    if not points:
        raise AttributionFactInputError("fact support contains no ownership evaluation point")
    return points, boundary_proven


def _rate_support(
    *,
    timestamp: Decimal,
    window_seconds: Decimal,
    ownership_start: Decimal,
    step: Decimal,
) -> dict[str, Any]:
    support_start = timestamp - window_seconds
    required, boundary_proven = _grid_points(
        grid_start=ownership_start,
        grid_step=step,
        support_start=support_start,
        support_end=timestamp,
    )
    return {
        "start": _canonical_decimal(support_start, field="support.start"),
        "end": _canonical_decimal(timestamp, field="support.end"),
        "required_timestamps": required,
        "boundary_proven": boundary_proven,
    }


def _point_support(timestamp: Decimal) -> dict[str, Any]:
    timestamp_text = _canonical_decimal(timestamp, field="support timestamp")
    return {
        "start": timestamp_text,
        "end": timestamp_text,
        "required_timestamps": [timestamp_text],
        "boundary_proven": True,
    }


def build_attribution_fact_inputs(
    *,
    normalized_evidence: dict,
    creation_by_pod_uid: dict,
) -> dict[str, Any]:
    """Build pointwise attribution facts and an aligned historical ownership plan."""

    normalized = _mapping(normalized_evidence, field="normalized_evidence")
    acquisition = _validate_acquisition(normalized)
    short_window = _non_empty_string(
        normalized.get("short_window"),
        field="normalized_evidence.short_window",
    )
    long_window = _non_empty_string(
        normalized.get("long_window"),
        field="normalized_evidence.long_window",
    )
    short_seconds = _duration_seconds(short_window, field="normalized_evidence.short_window")
    long_seconds = _duration_seconds(long_window, field="normalized_evidence.long_window")
    _validate_queries(
        normalized,
        short_window=short_window,
        long_window=long_window,
    )

    creation = _validate_creation_by_pod_uid(creation_by_pod_uid)
    pods = _validate_pods(normalized.get("pods"))

    max_window = max(short_seconds, long_seconds)
    extension_steps = _ceil_div(max_window, acquisition["step"])
    ownership_start = (
        acquisition["start"] - Decimal(extension_steps) * acquisition["step"]
    )

    facts: list[dict[str, Any]] = []
    required_by_pod: dict[str, set[Decimal]] = {}

    window_seconds = {
        "short": short_seconds,
        "long": long_seconds,
    }

    for pod in pods:
        pod_name = str(pod["name"])
        creation_map = dict(creation.get(pod_name, {}))
        for family in sorted(_SUPPORTED_FAMILIES):
            points = _series_points(pod, family=family, pod_name=pod_name)
            seen_timestamps: set[Decimal] = set()
            for index, point in enumerate(points):
                timestamp, timestamp_text = _validate_sample_timestamp(
                    point.get("timestamp"),
                    field=f"pods.{pod_name}.{family}[{index}].timestamp",
                    analysis_start=acquisition["start"],
                    analysis_end=acquisition["end"],
                    step=acquisition["step"],
                )
                if timestamp in seen_timestamps:
                    raise AttributionFactInputError(
                        f"duplicate timestamp for {family} and pod {pod_name}"
                    )
                seen_timestamps.add(timestamp)

                if family in _RATE_FAMILIES:
                    support = _rate_support(
                        timestamp=timestamp,
                        window_seconds=window_seconds[_RATE_FAMILIES[family]],
                        ownership_start=ownership_start,
                        step=acquisition["step"],
                    )
                else:
                    support = _point_support(timestamp)

                fact = {
                    "fact_id": f"{family}:{pod_name}:{timestamp_text}",
                    "pod": pod_name,
                    "evidence_family": family,
                    "evaluated_at": timestamp_text,
                    "support": {
                        "nominal": support,
                        "observed_sample": None,
                    },
                    "creation_by_uid": creation_map,
                }
                facts.append(fact)
                required = required_by_pod.setdefault(pod_name, set())
                required.update(
                    _decimal(item, field="required timestamp")
                    for item in support["required_timestamps"]
                )

    facts.sort(
        key=lambda item: (
            item["pod"],
            item["evidence_family"],
            _decimal(item["evaluated_at"], field="fact evaluated_at"),
        )
    )

    required_output = {
        pod: [
            _canonical_decimal(timestamp, field="required timestamp")
            for timestamp in sorted(timestamps)
        ]
        for pod, timestamps in sorted(required_by_pod.items())
    }

    return {
        "fact_input_id": FACT_INPUT_ID,
        "ownership_acquisition": {
            "namespace": acquisition["namespace"],
            "start": _canonical_decimal(ownership_start, field="ownership start"),
            "end": _canonical_decimal(acquisition["end"], field="ownership end"),
            "step": _canonical_decimal(acquisition["step"], field="ownership step"),
        },
        "required_timestamps_by_pod": required_output,
        "facts": facts,
    }
