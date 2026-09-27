"""`make run` from a checkout never opens the working console's database (A5, _research/06_backlog.md).

Read from `make -n`, which prints the commands without running them: what is asserted is exactly
what a person typing `make run` would start.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

MAKE = shutil.which("make")
pytestmark = [pytest.mark.unit, pytest.mark.skipif(MAKE is None, reason="make is not installed")]

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _planned(*args: str, where: pathlib.Path = ROOT) -> str:
    assert MAKE is not None
    command = [MAKE, "-n", "-C", str(where), *args]
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout  # noqa: S603


def test_a_console_run_from_a_checkout_uses_that_checkouts_own_data() -> None:
    said = _planned("run")

    assert f"export AGENT_DESK_DATA_DIR={ROOT}/.desk-data;" in said
    assert "--port 8787" not in said


def test_the_working_console_is_asked_for_by_name() -> None:
    said = _planned("run", "PROD=1")

    assert "AGENT_DESK_DATA_DIR" not in said
    assert "--port 8787" in said


def test_two_checkouts_get_two_ports(tmp_path: pathlib.Path) -> None:
    """The port comes from the checkout's path, so worktrees side by side do not collide."""
    other = tmp_path / "agent-desk-other"
    other.mkdir()
    (other / "Makefile").write_text((ROOT / "Makefile").read_text())

    here = _planned("run")
    there = _planned("run", where=other)

    port = here.split("--port ")[1].split()[0]
    assert f"--port {port} " not in there
    assert f"{other}/.desk-data" in there
