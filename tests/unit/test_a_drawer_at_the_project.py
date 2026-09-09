"""Drafts and small scripts live at the project, not at the session (01M21KTYEK383P3ZWT6WC7VB8B).

«Три раза за смену я писал заново одни и те же три скрипта, потому что каталог сессии исчезает вместе
с сессией.»
"""

from __future__ import annotations

import pathlib
import urllib.parse
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk.mcp import tools
from agent_desk.store.repo import Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _said(back: dict[str, object]) -> str:
    return back["content"][0]["text"]  # type: ignore[index,return-value]


def _a_form(fields: dict[str, str]) -> object:
    body = urllib.parse.urlencode(fields).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


SCRIPT = "import asyncio\nprint('the open ideas')\n"


# --- it outlives the conversation -----------------------------------------------------------------
async def test_a_script_comes_back_by_name(desk: Store) -> None:
    await desk.keep_script("open_ideas.py", SCRIPT, project_key="agent-desk")

    one = await desk.script("open_ideas.py", project_key="agent-desk")

    assert one is not None and one.body == SCRIPT


async def test_the_same_name_twice_is_one_script(desk: Store) -> None:
    """What this replaces is a file, and writing a file twice does not leave two of them."""
    await desk.keep_script("open_ideas.py", "the first try")
    await desk.keep_script("open_ideas.py", SCRIPT)

    kept = await desk.scripts()

    assert [one.body for one in kept] == [SCRIPT]


async def test_a_script_with_no_name_is_refused(desk: Store) -> None:
    """The name is the thing somebody will ask for it by, and a drawer of unnamed rows is a
    drawer nobody opens twice."""
    with pytest.raises(ValueError, match="name"):
        await desk.keep_script("  ", SCRIPT)


async def test_one_project_s_drawer_is_not_another_s(desk: Store) -> None:
    """A script that lists this console's ideas is no use in another checkout, and a drawer full of
    somebody else's is one nobody opens."""
    await desk.keep_script("open_ideas.py", SCRIPT, project_key="agent-desk")

    assert await desk.scripts(project_key="something-else") == []
    assert await desk.script("open_ideas.py") is None


async def test_a_script_about_no_project_is_a_real_answer(desk: Store) -> None:
    """The empty key is "about nothing in particular", not a missing one."""
    await desk.keep_script("scratch.py", SCRIPT)

    assert [one.name for one in await desk.scripts()] == ["scratch.py"]


async def test_one_can_be_thrown_away(desk: Store) -> None:
    await desk.keep_script("scratch.py", SCRIPT)

    assert await desk.forget_script("scratch.py")
    assert not await desk.forget_script("scratch.py")
    assert await desk.scripts() == []


# --- the rule: nothing lands on disk ---------------------------------------------------------------
def test_the_drawer_is_a_column_and_never_a_file() -> None:
    """ "Это не репозиторий и не код проекта" (CLAUDE.md, rule two). A drawer of scripts sitting
    next to somebody's code is exactly the shape that rule refuses, so it does not land on disk at
    all — and this is the test that keeps it that way as the surface grows."""
    here = pathlib.Path(__file__).resolve().parents[2] / "agent_desk"
    sql = (here / "store" / "071-a-drawer-at-the-project.sql").read_text(encoding="utf-8")

    assert "body        TEXT NOT NULL" in sql
    for module in ("mcp/tools.py",):
        said = (here / module).read_text(encoding="utf-8")
        assert "write_text" not in said
        assert "mkdir" not in said


# --- through MCP -----------------------------------------------------------------------------------
async def test_an_agent_keeps_one_and_reads_it_back(desk: Store) -> None:
    kept = _said(await tools.call(desk, "keep_script", {"name": "open_ideas.py", "body": SCRIPT}))

    assert "open_ideas.py" in kept
    assert _said(await tools.call(desk, "script", {"name": "open_ideas.py"})) == SCRIPT


async def test_naming_nothing_lists_what_is_there_without_the_bodies(desk: Store) -> None:
    """A caller that wanted one script and got four has spent the saving."""
    await desk.keep_script("open_ideas.py", SCRIPT)
    await desk.keep_script("close.py", "print('closed')")

    said = _said(await tools.call(desk, "script", {}))

    assert "open_ideas.py" in said and "close.py" in said
    assert SCRIPT not in said


async def test_asking_for_one_that_is_not_there_names_the_ones_that_are(desk: Store) -> None:
    await desk.keep_script("open_ideas.py", SCRIPT)

    said = _said(await tools.call(desk, "script", {"name": "openideas.py"}))

    assert "open_ideas.py" in said


async def test_an_empty_drawer_says_so(desk: Store) -> None:
    assert _said(await tools.call(desk, "script", {})) == "The drawer is empty."


# --- and the routes ---------------------------------------------------------------------------------
async def test_the_routes_read_and_write_it(desk: Store) -> None:
    written = await routes.keep_a_script(_a_form({"name": "open_ideas.py", "body": SCRIPT}))

    assert written.status_code == 200
    assert (await routes.kept_script("open_ideas.py")).body.decode() == SCRIPT
    assert b"open_ideas.py" in (await routes.kept_scripts()).body


async def test_the_route_says_why_it_refused(desk: Store) -> None:
    back = await routes.keep_a_script(_a_form({"name": " ", "body": SCRIPT}))

    assert back.status_code == 422
    assert await desk.scripts() == []


async def test_a_script_that_is_not_there_is_a_404_and_not_an_empty_body(desk: Store) -> None:
    """An empty body and a missing script read the same to a caller, and they mean opposite
    things."""
    back = await routes.kept_script("nope")

    assert back.status_code == 404
    assert b"nope" in back.body


async def test_an_empty_drawer_says_so_over_http(desk: Store) -> None:
    assert b"empty" in (await routes.kept_scripts()).body
