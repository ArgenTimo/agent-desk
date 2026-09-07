"""What a run is doing while it is not saying anything (agent_desk/answer/session.py).

"Длинный ответ, который возникает целиком через сорок секунд, читается как зависание. То же самое
нужно для сценария 10, где по ходу прогона надо видеть вызовы инструментов — механизм один: поток,
который наполняет карточку."

The answer already streamed into the card. What it could not do was fill the silence: a turn that
only used a tool carries no text, so a run that spends thirty seconds reading a repository streams
nothing at all, and a caret blinking on an empty line for half a minute is indistinguishable from a
console that has stopped.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk.answer import session


def _using(name: str, given: dict[str, object]) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": name, "input": given}]},
    }


# --- what it says --------------------------------------------------------------------------------
@pytest.mark.unit
def test_a_tool_call_is_said_in_ordinary_words() -> None:
    """docs/06-console.md: this window is for somebody who often does not read code. "Read" and a
    JSON blob is the thing they were trying to avoid opening a terminal for."""
    assert session._step_of(_using("Read", {"file_path": "/home/dev/p/store/repo.py"})).startswith(
        "reading"
    )
    assert session._step_of(_using("Grep", {"pattern": "keep_bench"})) == "searching keep_bench"
    assert session._step_of(_using("Glob", {"pattern": "**/*.sql"})) == "looking for **/*.sql"


@pytest.mark.unit
def test_a_path_is_shown_by_the_end_that_identifies_it() -> None:
    """The beginning of a path is `/home/somebody/projects`, which is the same on every line and is
    what pushes the half that says which file off the edge of a card."""
    said = session._step_of(_using("Read", {"file_path": "/home/dev/projects/x/store/repo.py"}))

    assert said == "reading store/repo.py"


@pytest.mark.unit
def test_a_tool_nobody_planned_for_says_its_own_name() -> None:
    """The allowlist is three tools. A fourth appearing here means it has moved, and the honest
    thing to show is what it actually used rather than nothing."""
    assert session._step_of(_using("Bash", {"command": "ls"})) == "bash"


@pytest.mark.unit
def test_a_long_pattern_is_trimmed_to_a_line() -> None:
    """This sits inside a card, not in a log."""
    said = session._step_of(_using("Grep", {"pattern": "x" * 300}))

    assert len(said) <= session.STEP_CHARS + len("searching ")
    assert said.endswith("…")


@pytest.mark.unit
def test_an_ordinary_answer_is_not_a_step() -> None:
    """A note about the run must never be mistaken for part of it."""
    answering = {"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}}

    assert session._step_of(answering) == ""


@pytest.mark.unit
def test_an_event_of_a_shape_nobody_promised_says_nothing() -> None:
    """docs/adr/0004: the CLI's format is not a contract, and a reader that raised on a shape it
    did not expect would fail the answer over a line about the answer."""
    for odd in ({}, {"message": "words"}, {"message": {"content": "words"}}, _using("Read", {})):
        assert session._step_of(odd) == "" or isinstance(session._step_of(odd), str)
    assert session._step_of(_using("Read", {})) == "reading"


# --- and it reaches the card ---------------------------------------------------------------------
@pytest.mark.unit
async def test_a_run_that_only_reads_files_still_says_something(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: this turn has no text in it, and it is exactly these turns that make the
    silence somebody reads as a hang."""
    from agent_desk.config import Settings

    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read",'
        '"input":{"file_path":"/home/dev/p/store/repo.py"}}]}}\\n\'\n'
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}\\n\'\n'
        'printf \'{"type":"result","result":"done"}\\n\'\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(fake), daily_usd=0.0))

    steps: list[str] = []
    said = [c async for c in session.stream_answer("q", on_step=steps.append)]

    assert steps == ["reading store/repo.py"]
    assert said == ["done"], "the note about the run leaked into its answer"


@pytest.mark.unit
async def test_what_it_is_doing_is_dropped_when_the_run_ends(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A note about a run in progress answers no question once the run is over, and a stale line
    under a finished answer says the console is still working."""
    from agent_desk.config import Settings
    from agent_desk.store.repo import Store
    from agent_desk.web import blocks

    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read",'
        '"input":{"file_path":"a/b.py"}}]}}\\n\'\n'
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}\\n\'\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(fake), daily_usd=0.0))

    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    try:
        thread = await store.create_thread("a chat")
        block = await store.create_block(
            thread_id=thread.id, kind="question", input="q", thread_set_by="human"
        )
        # Through the console's own runner, because that is where the cleanup lives — and a test
        # that wired up its own `on_step` would prove the callback works and nothing about whether
        # anybody ever clears it.
        await blocks._run(store, block, "q", [])

        assert block.id not in blocks.DOING
        assert (await store.block(block.id)).answer == "done", "the run did not actually finish"
    finally:
        blocks.DOING.pop(block.id, None)
        await store.close()


@pytest.mark.unit
def test_the_line_is_rendered_where_the_caret_blinks() -> None:
    """Stored and never shown would be a fact the console keeps and nobody benefits from."""
    where = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "templates"
    said = (where / "_blocks.html").read_text(encoding="utf-8")

    assert "doing.get(block.id)" in said
    assert said.index("caret") < said.index("doing.get(block.id)"), (
        "the note about the run is rendered above the answer it is a note about"
    )


@pytest.mark.unit
def test_it_is_scrubbed_on_the_way_out_like_the_answer_is() -> None:
    """A path or a pattern a model wrote about files it was pointed at. It never passes through the
    store, which is where docs/07-security.md puts the filter, so it is filtered here."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web" / "blocks.py"
    ).read_text(encoding="utf-8")

    assert "on_step=lambda step: DOING.__setitem__(block.id, scrub(step))" in source
