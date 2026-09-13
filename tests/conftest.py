"""What every test runs under."""

from __future__ import annotations

import pytest
from agent_desk import dispatch
from agent_desk.config import Settings


@pytest.fixture(autouse=True)
def no_real_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test never starts a real agent, whether or not it remembered to fake one.

    `take_it_as(..., "master")` in a test that patched nothing ran `claude --bg "бери в работу"` in
    this checkout, and each agent started that way ran `make gate` and started the next. A test that
    wants `dispatch.start` to run patches `dispatch.settings` itself, which overrides this.
    """
    monkeypatch.setattr(dispatch, "settings", Settings(claude_bin="not-installed-anywhere"))
