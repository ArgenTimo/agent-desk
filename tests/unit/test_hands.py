"""A console with hands off starts no agent, runs no loop that would, and offers no button for it.

A6 in _research/06_backlog.md (and S2: the idea pool is read in the background only when asked). The suite runs with AGENT_DESK_HANDS=on (tests/conftest.py) so the
agent-starting paths keep their tests; here each is switched off and asserted refused.
"""

from __future__ import annotations

import asyncio
import pathlib
from types import SimpleNamespace

import pytest
from agent_desk import dispatch
from agent_desk.config import Settings
from agent_desk.store.repo import Store
from agent_desk.web import app as app_module
from agent_desk.web import autostart, engine, kicking, later, routes

pytestmark = pytest.mark.unit


def _off() -> Settings:
    return Settings(hands=False)


def test_a_console_nobody_configured_has_no_hands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_DESK_HANDS", raising=False)

    assert Settings().hands is False


def test_nor_reads_the_idea_pool_on_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """S2: a sweep is model calls charged to the day's ceiling, made while nobody asked."""
    monkeypatch.delenv("AGENT_DESK_APPRAISE", raising=False)

    assert Settings().appraise is False


def test_start_refuses_before_anything_is_run(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one door every path goes through: routes, blocks, autostart and the engine all call it."""
    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\necho started >> " + str(tmp_path / "ran") + "\n")
    cli.chmod(0o755)
    monkeypatch.setattr(dispatch, "settings", Settings(hands=False, claude_bin=str(cli)))

    said = dispatch.start("fix the parser", cwd=str(tmp_path), name="parser")

    assert said.started is False
    assert "AGENT_DESK_HANDS" in said.detail
    assert not (tmp_path / "ran").exists()


async def test_the_workbench_engine_starts_no_run(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(engine, "settings", _off())
    try:
        made, why = await engine.begin(store, names=["a"], repo_key="k", cwd=str(tmp_path))
    finally:
        await store.close()

    assert made is None
    assert "AGENT_DESK_HANDS" in why


@pytest.mark.parametrize(
    ("appraise", "expected"),
    [
        # S2: reading the idea pool costs model calls, so it runs only when asked for.
        (False, ["agent_desk.web.later.run"]),
        (True, ["agent_desk.web.kicking.appraising", "agent_desk.web.later.run"]),
    ],
)
async def test_the_loops_that_start_work_are_not_run(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, appraise: bool, expected: list[str]
) -> None:
    ran: list[str] = []

    def recorder(name: str):  # type: ignore[no-untyped-def]
        async def loop(store: Store) -> None:
            ran.append(name)
            await asyncio.Event().wait()

        return loop

    for module, name in (
        (autostart, "run"),
        (kicking, "run"),
        (engine, "run"),
        (kicking, "appraising"),
        (later, "run"),
    ):
        monkeypatch.setattr(module, name, recorder(f"{module.__name__}.{name}"))
    monkeypatch.setattr(app_module, "settings", Settings(hands=False, appraise=appraise))
    monkeypatch.setattr(routes, "store", Store(tmp_path / "agent-desk.db"))

    async with app_module.app.router.lifespan_context(app_module.app):
        await asyncio.sleep(0)

    assert sorted(ran) == expected


@pytest.mark.parametrize("hands", [True, False])
def test_the_refusal_panel_offers_an_agent_only_when_it_could_start_one(
    monkeypatch: pytest.MonkeyPatch, hands: bool
) -> None:
    monkeypatch.setitem(routes.env.globals, "hands", hands)
    row = SimpleNamespace(session=SimpleNamespace(project="alpha", session_id="s1"))

    page = routes.env.get_template("_message.html").render(
        stage="refused", row=row, detail="it is busy", text="run the tests", directive_id=""
    )

    assert ("Have an agent do it instead" in page) is hands
    assert "Copy it" in page


@pytest.mark.parametrize("hands", [True, False])
async def test_the_board_tells_the_script_whether_to_offer_a_run(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, hands: bool
) -> None:
    """`showRunFrom` in console.js reads this: a run-from-here button on a console that refuses
    runs would be a button that always says no."""
    monkeypatch.setitem(routes.env.globals, "hands", hands)
    store = Store(tmp_path / "agent-desk.db")
    monkeypatch.setattr(routes, "store", store)
    await store.open()
    try:
        page = await routes.render_page()
    finally:
        await store.close()

    assert f'data-hands="{"on" if hands else "off"}"' in page
