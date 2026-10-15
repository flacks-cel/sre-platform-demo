import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
CURRENT = FIXTURES / "00_current_cases.yaml"
PROPOSED = FIXTURES / "00_proposed_cases.yaml"


def _main():
    from praeva.change.cli import main

    return main


def _args(
    name: str,
    *,
    current: Path = CURRENT,
    proposed: Path = PROPOSED,
    container: str = "jobs-api",
    container_space: str | None = None,
) -> list[str]:
    args = [
        "change",
        "cpu",
        "--current",
        str(current),
        "--proposed",
        str(proposed),
        "--api-group",
        "apps",
        "--kind",
        "Deployment",
        "--namespace",
        "app",
        "--name",
        name,
        "--container",
        container,
    ]
    if container_space is not None:
        args.extend(["--container-space", container_space])
    return args


def test_cli_happy_path_emits_core_result_as_json(capsys):
    exit_code = _main()(_args("decrease"))
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""

    payload = json.loads(captured.out)
    assert payload["direction"] == "DECREASE"
    assert payload["change_ratio"] == {"numerator": 1, "denominator": 2}


def test_cli_output_is_single_compact_deterministic_document_without_risk(capsys):
    exit_code = _main()(_args("ratio-third"))
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    expected = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    assert captured.out == expected
    assert len(captured.out.splitlines()) == 1

    lowered = captured.out.lower()
    for forbidden in ("risk", "recommendation", "critical", "worst_pod"):
        assert forbidden not in lowered


def test_cli_missing_manifest_file_is_nonzero_with_empty_stdout(tmp_path, capsys):
    missing = tmp_path / "missing-current.yaml"

    exit_code = _main()(_args("decrease", current=missing))
    captured = capsys.readouterr()

    assert exit_code != 0
    assert captured.out == ""
    assert "current" in captured.err.lower()


def test_cli_unrendered_manifest_is_nonzero_without_partial_json(tmp_path, capsys):
    proposed = tmp_path / "proposed.yaml"
    proposed.write_text(
        """
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
""".lstrip(),
        encoding="utf-8",
    )

    exit_code = _main()(_args("decrease", proposed=proposed))
    captured = capsys.readouterr()

    assert exit_code != 0
    assert captured.out == ""
    assert "render" in captured.err.lower()


def test_cli_missing_required_container_argument_is_nonzero(capsys):
    args = _args("decrease")
    index = args.index("--container")
    del args[index : index + 2]

    exit_code = _main()(args)
    captured = capsys.readouterr()

    assert exit_code != 0
    assert captured.out == ""
    assert "--container" in captured.err


def test_cli_respects_explicit_init_container_space(tmp_path, capsys):
    current = tmp_path / "current.yaml"
    proposed = tmp_path / "proposed.yaml"
    current.write_text(_init_manifest("200m"), encoding="utf-8")
    proposed.write_text(_init_manifest("100m"), encoding="utf-8")

    exit_code = _main()(
        _args(
            "init-cli",
            current=current,
            proposed=proposed,
            container="bootstrap",
            container_space="initContainers",
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["container"] == {"name": "bootstrap", "space": "initContainers"}
    assert payload["direction"] == "DECREASE"


def test_cli_does_not_reject_legitimate_dollar_parentheses(capsys):
    exit_code = _main()(_args("dollar-args"))
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert json.loads(captured.out)["direction"] == "UNCHANGED"


def _init_manifest(limit: str) -> str:
    return f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: init-cli
  namespace: app
spec:
  template:
    spec:
      initContainers:
        - name: bootstrap
          image: example/bootstrap:test
          resources:
            limits:
              cpu: {limit!r}
      containers:
        - name: jobs-api
          image: example/jobs-api:test
""".lstrip()
