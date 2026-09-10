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


@pytest.mark.unit
async def test_a_test_that_forgets_to_fake_the_engine_asks_nobody() -> None:
    """The one path out of the suite that is not a read. `stream_answer` with nothing overridden
    would exec whatever `claude` PATH resolves to, spend money on it, and put the question in front
    of a real model — so the redirect points it at a name in the empty tree, and this is the error
    a forgetful test gets instead."""
    from agent_desk.answer.session import AnswerFailed, stream_answer

    with pytest.raises(AnswerFailed) as caught:
        [chunk async for chunk in stream_answer("q")]

    assert "needs_toolchain" in str(caught.value)


@pytest.mark.unit
def test_a_test_that_forgets_to_fake_the_engine_starts_no_agent(tmp_path: Path) -> None:
    """The same redirect on the surface with the worse ending: `dispatch.start` execs the CLI to
    leave a headless agent running in a directory, and a test that forgot which directory would
    leave it in this one."""
    from agent_desk import dispatch

    started = dispatch.start("do something", cwd=str(tmp_path), name="a-name")

    assert not started.started
    assert "is not installed here" in started.detail
