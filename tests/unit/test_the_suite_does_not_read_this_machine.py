"""What this suite is allowed to see of the machine it runs on: nothing.

The guard is in `tests/conftest.py`; this is what fails when somebody takes it out. A suite that
goes back to reading the live registry does not fail — it flakes, once a fortnight, on whichever
test happened to assert about text an agent working beside it wrote (01M1ZEN85PA2NYSV70H59ZZFWN).
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
def test_the_paths_it_resolves_are_not_this_account() -> None:
    from agent_desk.config import settings

    assert settings.claude_home != Path.home() / ".claude"
    assert settings.data_dir != Path.home() / ".local" / "share" / "agent-desk"


@pytest.mark.unit
def test_the_board_a_test_renders_without_asking_is_empty() -> None:
    """Not merely elsewhere — empty. The board a forgetful test renders has no rows in it, so what
    it asserts is about that test rather than about somebody's afternoon."""
    from agent_desk.web import routes

    rows, _ = routes.board()
    assert rows == []
