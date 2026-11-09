"""ANALYZE-ERGONOMICS-001: invocation resolution.

Resolution of relative time, configuration file and explicitly selected
policy profiles. Kept apart from the CLI so it is testable without a
subprocess, and apart from the orchestrator so no clock is read inside
the analysis path.

This module resolves inputs. It never decides policy: every value it
produces was declared by the caller, in the command line, in the
configuration file or in an explicitly named profile.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

IDENTITY_KEYS = (
    "prometheus_url",
    "namespace",
    "api_group",
    "kind",
    "name",
    "container",
    "container_space",
    "pod_regex",
)

POLICY_KEYS = (
    "step",
    "short_window",
    "long_window",
    "rule",
    "rule_params",
)

RULE_REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    "CHANGE-RISK-001": ("margin",),
}

_DURATION = re.compile(r"^([1-9][0-9]*)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

ORIGIN_CLI = "CLI"
ORIGIN_PROFILE = "PROFILE"
ORIGIN_CONFIG = "CONFIG"
# §6.2: a default that predates this slice is auditable as such, never as
# an input the caller actually provided.
ORIGIN_LEGACY_DEFAULT = "LEGACY_DEFAULT"

SOURCE_KEY = "__source__"


class InvocationInputError(ValueError):
    """Raised when ANALYZE-ERGONOMICS-001 receives malformed invocation input."""


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def _as_int(value: Any, *, field: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise InvocationInputError(f"{field} must be an integer") from exc


def parse_duration(spec: Any) -> int:
    """Parse a duration such as 6h into seconds. Integer + s|m|h|d only."""

    if not isinstance(spec, str):
        raise InvocationInputError("--last duration must be a string such as 6h")

    match = _DURATION.match(spec)
    if match is None:
        raise InvocationInputError(
            f"invalid --last duration {spec!r}: expected a positive integer "
            "followed by s, m, h or d (for example 6h)"
        )

    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def resolve_time_range(
    *,
    last: Any = None,
    start: Any = None,
    end: Any = None,
    step: Any,
    now: Any = None,
) -> dict[str, Any]:
    """Resolve the evidence interval. Either absolute or relative, never both."""

    step_seconds = _as_int(step, field="step")
    if step_seconds <= 0:
        raise InvocationInputError("step must be a positive integer")

    has_absolute = start is not None or end is not None

    if last is not None and has_absolute:
        raise InvocationInputError(
            "--last and --start/--end are mutually exclusive"
        )

    if last is None and not has_absolute:
        raise InvocationInputError(
            "a time range is required: pass --last, or --start and --end"
        )

    if last is None:
        if start is None or end is None:
            raise InvocationInputError("--start and --end must be given together")
        return {
            "time_source": "EXPLICIT",
            "start": _as_int(start, field="start"),
            "end": _as_int(end, field="end"),
            "step": step_seconds,
        }

    duration = parse_duration(last)
    if duration % step_seconds != 0:
        raise InvocationInputError(
            f"--last {last} is {duration}s, which is not a multiple of step "
            f"{step_seconds}s; the resolved range would not fall on the grid"
        )

    resolved_at = _as_int(now, field="now")
    resolved_end = (resolved_at // step_seconds) * step_seconds

    return {
        "time_source": "RELATIVE",
        "last_spec": last,
        "resolved_at": resolved_at,
        "start": resolved_end - duration,
        "end": resolved_end,
        "step": step_seconds,
    }


# ---------------------------------------------------------------------------
# Configuration file
# ---------------------------------------------------------------------------


def _reject_unknown(mapping: dict[str, Any], allowed: tuple[str, ...], *, where: str) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise InvocationInputError(
            f"unknown key(s) in {where}: " + ", ".join(unknown)
        )


def load_config(path: Any) -> dict[str, Any]:
    """Read and validate a configuration file. Never discovered automatically."""

    config_path = Path(path)
    try:
        raw = config_path.read_bytes()
    except OSError as exc:
        raise InvocationInputError(f"cannot read config file: {exc}") from exc

    try:
        document = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise InvocationInputError(f"config file is not valid YAML: {exc}") from exc

    if document is None:
        document = {}
    if not isinstance(document, dict):
        raise InvocationInputError("config file must contain a mapping at the root")

    _reject_unknown(document, (*IDENTITY_KEYS, "profiles"), where="config root")

    profiles = document.get("profiles", {})
    if profiles is None:
        profiles = {}
    if not isinstance(profiles, dict):
        raise InvocationInputError("profiles must be a mapping of profile names")

    for profile_name, profile in profiles.items():
        if not isinstance(profile, dict):
            raise InvocationInputError(f"profile {profile_name!r} must be a mapping")
        _reject_unknown(profile, POLICY_KEYS, where=f"profile {profile_name!r}")
        rule_params = profile.get("rule_params")
        if rule_params is not None and not isinstance(rule_params, dict):
            raise InvocationInputError(
                f"rule_params in profile {profile_name!r} must be a mapping"
            )

    resolved: dict[str, Any] = {
        key: value for key, value in document.items() if key in IDENTITY_KEYS
    }
    resolved["profiles"] = profiles
    resolved[SOURCE_KEY] = {
        "path": str(config_path),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return resolved


# ---------------------------------------------------------------------------
# Full invocation
# ---------------------------------------------------------------------------


def _sha256_of_file(path: Any) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise InvocationInputError(f"cannot read manifest file: {exc}") from exc


def _select_profile(config: dict[str, Any] | None, profile: str | None) -> dict[str, Any]:
    if profile is None:
        return {}

    if config is None:
        raise InvocationInputError("--profile requires --config")

    profiles = config.get("profiles") or {}
    if profile not in profiles:
        available = ", ".join(sorted(profiles)) or "none"
        raise InvocationInputError(
            f"unknown profile {profile!r}; available profiles: {available}"
        )

    selected = dict(profiles[profile])
    missing = [key for key in POLICY_KEYS if key not in selected]
    if missing:
        raise InvocationInputError(
            f"profile {profile!r} is incomplete: missing " + ", ".join(sorted(missing))
        )
    return selected


def _merge_rule_params(
    profile_params: Any,
    cli_params: Any,
) -> tuple[dict[str, str], str]:
    merged: dict[str, str] = {}
    origin = ORIGIN_PROFILE

    if isinstance(profile_params, dict):
        merged.update({str(key): str(value) for key, value in profile_params.items()})
    if isinstance(cli_params, dict) and cli_params:
        merged.update({str(key): str(value) for key, value in cli_params.items()})
        origin = ORIGIN_CLI if not profile_params else "CLI+PROFILE"

    return merged, origin


def resolve_invocation(
    *,
    cli_values: dict[str, Any],
    config: dict[str, Any] | None,
    profile: str | None,
    rule_id: str | None = None,
    now: Any = None,
    legacy_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve identity, policy and time from CLI, config and selected profile."""

    if not isinstance(cli_values, dict):
        raise InvocationInputError("cli_values must be a mapping")

    cli = {key: value for key, value in cli_values.items() if value is not None}
    selected_profile = _select_profile(config, profile)
    effective: dict[str, dict[str, Any]] = {}

    # Policy first: an incomplete profile or missing policy must be reported
    # before a missing identity field, so the user sees the cause they can act on.
    policy: dict[str, Any] = {}
    missing_policy: list[str] = []
    for key in POLICY_KEYS:
        if key == "rule_params":
            continue
        if key in cli:
            policy[key] = cli[key]
            effective[key] = {"value": cli[key], "origin": ORIGIN_CLI}
        elif key in selected_profile:
            policy[key] = selected_profile[key]
            effective[key] = {"value": selected_profile[key], "origin": ORIGIN_PROFILE}
        else:
            missing_policy.append(key)

    if missing_policy:
        raise InvocationInputError(
            "missing policy parameter(s): "
            + ", ".join(sorted(missing_policy))
            + "; pass them explicitly or select a profile with --profile"
        )

    rule_params, rule_params_origin = _merge_rule_params(
        selected_profile.get("rule_params"),
        cli.get("rule_params"),
    )
    policy["rule_params"] = rule_params
    effective["rule_params"] = {"value": rule_params, "origin": rule_params_origin}

    effective_rule = rule_id or policy.get("rule")
    required = RULE_REQUIRED_PARAMS.get(str(effective_rule), ())
    missing_params = [param for param in required if param not in rule_params]
    if missing_params:
        raise InvocationInputError(
            f"rule {effective_rule} requires rule_params: "
            + ", ".join(sorted(missing_params))
        )

    legacy = legacy_defaults or {}
    identity: dict[str, Any] = {}
    missing_identity: list[str] = []
    for key in IDENTITY_KEYS:
        if key in cli:
            identity[key] = cli[key]
            effective[key] = {"value": cli[key], "origin": ORIGIN_CLI}
        elif config is not None and key in config:
            identity[key] = config[key]
            effective[key] = {"value": config[key], "origin": ORIGIN_CONFIG}
        elif key in legacy:
            identity[key] = legacy[key]
            effective[key] = {"value": legacy[key], "origin": ORIGIN_LEGACY_DEFAULT}
        else:
            missing_identity.append(key)

    if missing_identity:
        raise InvocationInputError(
            "missing target identity field(s): " + ", ".join(sorted(missing_identity))
        )

    time_range = resolve_time_range(
        last=cli.get("last"),
        start=cli.get("start"),
        end=cli.get("end"),
        step=policy["step"],
        now=now,
    )
    for key in ("start", "end", "step"):
        effective[key] = {
            "value": time_range[key],
            "origin": ORIGIN_CLI if time_range["time_source"] == "EXPLICIT" else "RESOLVED",
        }

    invocation: dict[str, Any] = {
        "time_source": time_range["time_source"],
        "start": time_range["start"],
        "end": time_range["end"],
        "step": time_range["step"],
    }
    if time_range["time_source"] == "RELATIVE":
        invocation["last_spec"] = time_range["last_spec"]
        invocation["resolved_at"] = time_range["resolved_at"]

    if config is not None and SOURCE_KEY in config:
        invocation["config_path"] = config[SOURCE_KEY]["path"]
        invocation["config_sha256"] = config[SOURCE_KEY]["sha256"]
    if profile is not None:
        invocation["profile_name"] = profile

    for side in ("current", "proposed"):
        path = cli.get(f"{side}_manifest_path")
        if path is not None:
            invocation[f"{side}_manifest_sha256"] = _sha256_of_file(path)

    invocation["effective_params"] = effective

    return {
        "identity": identity,
        "policy": policy,
        "rule_id": str(effective_rule),
        "time_range": time_range,
        "effective_params": effective,
        "invocation": invocation,
        "profile_name": profile,
    }
