"""What a step is doing, on its card while it happens (01M1XA1V955P2DH7CAG0D9DKT8).

«Отслеживать прямо на верстаке, прямо интуитивно понятно и визуально ясно, как, когда, какие скилы
вызываются… Не лог после, а на карточке во время.»

A prompt step that spends forty seconds reading files streams no text at all, and a card that says
nothing for forty seconds is a card somebody reads as a hang.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.answer import session
from agent_desk.store.repo import Store
from agent_desk.web import engine, routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    engine.DOING.clear()
    yield store
    engine.DOING.clear()
    await store.close()


def _reads_a_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An engine whose turn is one tool call and then an answer, which is the shape that is silent."""
    from agent_desk.config import Settings

    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read",'
        '"input":{"file_path":"/home/dev/p/store/repo.py"}}]}}\\n\'\n'
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}\\n\'\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(fake), daily_usd=0.0))


async def test_a_step_says_what_it_is_doing_while_it_is_doing_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tool calls arrive as their own events in the stream the answer already comes in, so this
    costs nothing but the wiring."""
    _reads_a_file(tmp_path, monkeypatch)
    seen: list[str] = []

    said = await engine._ask("q", None, on_step=seen.append)

    assert said.said == "done"
    assert seen == ["reading store/repo.py"]


async def test_it_is_dropped_the_moment_the_step_settles(desk: Store) -> None:
    """A note about a step in progress answers nothing once the step is over, and a stale line on a
    finished card says the console is still working."""
    engine.DOING[engine.doing_key("r1", "step:one")] = "reading store/repo.py"
    engine.DOING.pop(engine.doing_key("r1", "step:one"), None)

    assert engine.DOING == {}


def test_two_runs_of_one_drawing_do_not_share_a_line() -> None:
    """Ten runs of the same pipeline are ten cards, and a key that was only the card name would
    have every one of them showing whatever the last run happened to be doing."""
    assert engine.doing_key("r1", "step:one") != engine.doing_key("r2", "step:one")


async def test_the_page_is_told_what_each_step_is_doing(desk: Store) -> None:
    run = await desk.start_run(cards=["step:one"], repo_key="", cwd="")
    await desk.set_run_step(run_id=run.id, name="step:one", state="going")
    engine.DOING[engine.doing_key(run.id, "step:one")] = "reading store/repo.py"

    back = json.loads((await routes.workbench_runs()).body)

    (one,) = back["runs"]
    assert one["steps"][0]["doing"] == "reading store/repo.py"


async def test_a_step_that_is_doing_nothing_says_nothing(desk: Store) -> None:
    run = await desk.start_run(cards=["step:one"], repo_key="", cwd="")
    await desk.set_run_step(run_id=run.id, name="step:one", state="done", made="an answer")

    back = json.loads((await routes.workbench_runs()).body)

    assert back["runs"][0]["steps"][0]["doing"] == ""


def test_the_line_is_scrubbed_before_it_reaches_a_screen() -> None:
    """A tool call names a path, and a path names things (docs/07-security.md)."""
    source = (HERE / "agent_desk" / "web" / "engine.py").read_text(encoding="utf-8")
    body = source[source.index("def note_step(") :]

    assert "scrub(step)" in body[: body.index("\n\n")]


def test_the_card_shows_it_and_takes_it_away_again() -> None:
    """Read from the script, because what the card does with this is the whole feature."""
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))
    body = code[code.index("function showRuns()") :]
    body = body[: body.index("\n}\n")]

    assert "step.doing" in body
    assert "pin-doing" in body
    assert "busy?.remove()" in body


def test_the_card_has_somewhere_to_put_it() -> None:
    css = (HERE / "agent_desk" / "web" / "static" / "console.css").read_text(encoding="utf-8")

    assert ".pin-doing" in css
