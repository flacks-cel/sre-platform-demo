from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from praeva.change.cpu_limit import ChangeInputError, analyze_change


class CliInputError(ValueError):
    """Raised when the CHANGE-INPUT-001 CLI cannot read its file inputs."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="praeva")
    commands = parser.add_subparsers(dest="command", required=True)

    change = commands.add_parser("change")
    change_commands = change.add_subparsers(dest="change_command", required=True)

    cpu = change_commands.add_parser("cpu")
    cpu.add_argument("--current", required=True)
    cpu.add_argument("--proposed", required=True)
    cpu.add_argument("--api-group", required=True)
    cpu.add_argument("--kind", required=True)
    cpu.add_argument("--namespace", required=True)
    cpu.add_argument("--name", required=True)
    cpu.add_argument("--container", required=True)
    cpu.add_argument("--container-space", default="containers")

    return parser


def _read_manifest(path: str, *, side: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CliInputError(f"cannot read {side} manifest file: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = _parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    try:
        if args.command != "change" or args.change_command != "cpu":
            raise CliInputError("unsupported command")

        current_manifest = _read_manifest(args.current, side="current")
        proposed_manifest = _read_manifest(args.proposed, side="proposed")

        result = analyze_change(
            current_manifest=current_manifest,
            proposed_manifest=proposed_manifest,
            api_group=args.api_group,
            kind=args.kind,
            namespace=args.namespace,
            name=args.name,
            container=args.container,
            container_space=args.container_space,
        )
    except (CliInputError, ChangeInputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0
