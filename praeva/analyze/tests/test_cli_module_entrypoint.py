from __future__ import annotations

import subprocess
import sys


def test_analyze_cli_module_is_invokable() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "praeva.analyze.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "analyze" in completed.stdout
