"""One sentence about a card, written once and kept (agent_desk/ideas/describe.py).

The board is good at saying what it reads. What it cannot say is what a thing *is*, in words
somebody who has not read the code would use — and that is the middle of the three views a card
has. Most of these assert the three rules that keep it from being in the way.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.ideas import describe
from agent_desk.store.repo import Store


@pytest.fixture
async def store(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    desk = Store(tmp_path / "agent-desk.db")
    await desk.open()
    yield desk
    await desk.close()


def _answers(reply: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    async def fake(prompt: str) -> AsyncIterator[str]:
        asked.append(prompt)
        yield reply

    monkeypatch.setattr(describe, "stream_answer", fake)
    return asked


@pytest.mark.unit
async def test_a_card_is_described_once_and_the_sentence_is_kept(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A board of twenty cards would otherwise be twenty model calls every two seconds."""
    asked = _answers(
        "The console's own repository, being rewritten around one workbench.", monkeypatch
    )

    first = await describe.describe(store, "project:acme", "project", "name: acme\nbranch: main")
    again = await describe.describe(store, "project:acme", "project", "name: acme\nbranch: main")

    assert first.startswith("The console's own repository")
    assert again == first
    assert len(asked) == 1, "it was described a second time for the same facts"


@pytest.mark.unit
async def test_it_is_written_again_when_what_we_know_has_really_changed(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise a session's description is about whatever it happened to be doing the first time
    somebody looked at it."""
    _answers("Doing the first thing.", monkeypatch)
    await describe.describe(store, "session:s1", "session", "status: busy\nlast said: reading")

    asked = _answers("Doing something else entirely now.", monkeypatch)
    fresh = await describe.describe(
        store,
        "session:s1",
        "session",
        "status: busy\nlast said: " + "rewriting the parser and its tests, which is a long line",
    )

    assert fresh == "Doing something else entirely now."
    assert len(asked) == 1


@pytest.mark.unit
async def test_a_small_change_is_not_worth_a_model_call(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session's last line changes constantly."""
    _answers("A session reading a repository.", monkeypatch)
    await describe.describe(store, "session:s1", "session", "status: busy\nlast said: reading a")

    asked = _answers("Something new.", monkeypatch)
    same = await describe.describe(
        store, "session:s1", "session", "status: busy\nlast said: reading b"
    )

    assert same == "A session reading a repository."
    assert asked == []


@pytest.mark.unit
async def test_an_unavailable_model_leaves_the_card_as_it_was(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A description that has not been written is an ordinary card, not a hole."""

    async def broken(prompt: str) -> AsyncIterator[str]:
        raise describe.AnswerFailed("no model here")
        yield ""  # pragma: no cover

    monkeypatch.setattr(describe, "stream_answer", broken)

    assert await describe.describe(store, "project:acme", "project", "name: acme") == ""


@pytest.mark.unit
async def test_nothing_to_say_is_a_normal_answer(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers("nothing", monkeypatch)

    assert await describe.describe(store, "project:acme", "project", "name: acme") == ""
    assert await store.card_said("project:acme") == ("", "")


@pytest.mark.unit
async def test_a_card_with_nothing_known_about_it_is_not_described(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _answers("Something.", monkeypatch)

    assert await describe.describe(store, "project:acme", "project", "   ") == ""
    assert asked == []


@pytest.mark.unit
def test_the_prompt_asks_for_a_description_and_forbids_a_verdict() -> None:
    """The board has its own checked words for whether something is stuck, and a model's opinion
    next to them would be indistinguishable from a fact (CLAUDE.md, rule five)."""
    prompt = describe.describe_prompt("session", "status: idle")

    assert "Describe; do not judge" in prompt
    assert "no priorities" in prompt.lower()
    assert "do not invent" in prompt.lower()
    assert "`nothing`" in prompt


@pytest.mark.unit
def test_a_reply_that_is_not_a_sentence_is_nothing() -> None:
    assert describe.read_description("") == ""
    assert describe.read_description("nothing") == ""
    assert describe.read_description("Nothing.") == ""
    assert describe.read_description("A console over Claude Code sessions.").startswith("A console")
