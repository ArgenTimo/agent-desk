"""The working console runs from a copy of a tag, without --reload, and comes back when killed (A2).

R3 in _research/04_dogfooding_gaps.md: it used to be `--reload` in the checkout sessions commit
into. What is asserted is the unit `scripts/prod.sh install` writes.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

BASH = shutil.which("bash")
pytestmark = [pytest.mark.unit, pytest.mark.skipif(BASH is None, reason="bash is not installed")]

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "prod.sh"


def _unit(prod_dir: pathlib.Path) -> str:
    assert BASH is not None
    command = [BASH, str(SCRIPT), "unit"]
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(prod_dir.parent),
        "AGENT_DESK_PROD_DIR": str(prod_dir),
    }
    return subprocess.run(command, capture_output=True, text=True, check=True, env=env).stdout  # noqa: S603


def test_the_unit_runs_the_installed_copy_and_never_reloads(tmp_path: pathlib.Path) -> None:
    unit = _unit(tmp_path / "agent-desk-prod")

    assert f"ExecStart={tmp_path}/agent-desk-prod/.venv/bin/python -m agent_desk" in unit
    assert f"WorkingDirectory={tmp_path}/agent-desk-prod" in unit
    exec_line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "--reload" not in exec_line
    assert "uvicorn" not in exec_line


def test_a_killed_console_is_started_again(tmp_path: pathlib.Path) -> None:
    """uvicorn exits 0 on SIGTERM, which on-failure would take as a reason to stay down."""
    unit = _unit(tmp_path / "agent-desk-prod")

    assert "\nRestart=always\n" in unit
