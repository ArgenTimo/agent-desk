"""A project stays on the board once this console has seen it (01M21GV49Q6DSCSDNWK6VN93N5).

«Проекты, которые были добавлены в нашу систему, остаются висеть в ней до тех пор, пока мы их не
удалим отсюда. Даже если в проекте в конкретный момент нет ни одной ллм сессии.»
"""

from __future__ import annotations

import pathlib
import urllib.parse
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk.observe.model import Session
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


def _a_form(fields: dict[str, str]) -> object:
    body = urllib.parse.urlencode(fields).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


def _a_row(cwd: str) -> routes.BoardRow:
    return routes.BoardRow(
        session=Session(
            pid=1,
            procStart="1",
            sessionId="s-1",
            cwd=cwd,
            name="biba",
            kind="interactive",
            version="1.0.0",
            status="idle",
            updatedAt=0,
            statusUpdatedAt=0,
        ),
        tail=None,
        hint=None,
    )


# --- it survives its sessions ending ------------------------------------------------------------
async def test_a_project_with_nothing_running_is_still_on_the_board(desk: Store) -> None:
    """The registry is a picture of right now, and a project whose last session ended took its
    ideas, its queue and its links off the board with it."""
    await desk.note_project("dir:/tmp/thing", "thing", "/tmp/thing")

    projects = routes.shape([], [], await desk.seen_projects())

    assert [one.name for one in projects] == ["thing"]
    assert projects[0].sessions == 0


async def test_it_keeps_the_checkout_it_was_last_seen_in(desk: Store) -> None:
    """A card dragged onto an empty project still has somewhere to run. One that cannot be used is
    a row, not a project."""
    await desk.note_project("dir:/tmp/thing", "thing", "/tmp/thing")

    (project,) = routes.shape([], [], await desk.seen_projects())

    assert [one.path for one in project.instances] == ["/tmp/thing"]


async def test_a_project_that_is_running_is_not_listed_twice(desk: Store) -> None:
    """The remembered row and the live one are the same project, and two cards for it would be two
    places to drag the same card into."""
    await desk.note_project("dir:/tmp/thing", "thing", "/tmp/thing")
    rows = [_a_row("/tmp/thing")]

    projects = routes.shape(rows, [], await desk.seen_projects())

    assert len(projects) == 1
    assert projects[0].sessions == 1


async def test_when_it_was_last_running_is_what_moves(desk: Store) -> None:
    """What somebody deciding whether to take a project off wants to know is when it last actually
    ran, so `first_at` is kept and `last_at` moves."""
    await desk.note_project("dir:/tmp/thing", "thing", "/tmp/thing")
    (first,) = await desk.seen_projects()
    await desk.note_project("dir:/tmp/thing", "thing renamed", "/tmp/thing")

    (again,) = await desk.seen_projects()
    assert again.first_at == first.first_at
    assert again.last_at >= first.last_at
    assert again.name == "thing renamed"


async def test_a_checkout_it_is_no_longer_seen_in_is_kept(desk: Store) -> None:
    """An empty path is "nothing was known this time", not "it moved to nowhere"."""
    await desk.note_project("dir:/tmp/thing", "thing", "/tmp/thing")
    await desk.note_project("dir:/tmp/thing", "thing", "")

    (one,) = await desk.seen_projects()
    assert one.cwd == "/tmp/thing"


async def test_a_project_with_no_key_is_not_written_down(desk: Store) -> None:
    await desk.note_project("", "nothing")

    assert await desk.seen_projects() == []


# --- and it is written from the read that happens anyway ----------------------------------------
async def test_a_running_project_is_written_down(desk: Store) -> None:
    projects = routes.shape([_a_row("/tmp/thing")], [], ())

    await routes._note_what_is_here(projects)

    assert [one.name for one in await desk.seen_projects()] == ["thing"]


async def test_a_project_that_is_only_remembered_does_not_have_its_time_moved(
    desk: Store,
) -> None:
    """Otherwise `last_at` would move every two seconds, and "when was it last actually running"
    is the one thing the row is for."""
    await desk.note_project("dir:/tmp/thing", "thing", "/tmp/thing")
    (before,) = await desk.seen_projects()

    await routes._note_what_is_here(routes.shape([], [], await desk.seen_projects()))

    (after,) = await desk.seen_projects()
    assert after.last_at == before.last_at


# --- and taking one off is a person's -----------------------------------------------------------
async def test_taking_it_off_stops_it_being_shown(desk: Store) -> None:
    await desk.note_project("dir:/tmp/thing", "thing", "/tmp/thing")

    assert await desk.forget_project("dir:/tmp/thing")
    assert routes.shape([], [], await desk.seen_projects()) == []


async def test_taking_it_off_removes_nothing_else(desk: Store) -> None:
    """A control that quietly deleted its ideas would be a delete button wearing "hide" as a
    label."""
    await desk.note_project("dir:/tmp/thing", "thing", "/tmp/thing")
    idea = await desk.create_idea(
        text_="about that project",
        summary="about that project",
        source_kind="typed",
        project_key="dir:/tmp/thing",
    )
    await desk.queue_task(
        repo_key="dir:/tmp/thing",
        cwd="/tmp/thing",
        title="a job",
        instruction="do it",
        source_kind="idea",
    )

    await routes.take_a_project_off_the_board(_a_form({"key": "dir:/tmp/thing"}))

    assert await desk.idea(idea.id) is not None
    assert len(await desk.tasks()) == 1


async def test_one_that_is_running_comes_straight_back(desk: Store) -> None:
    """Which is right: it is here."""
    await desk.note_project("dir:/tmp/thing", "thing", "/tmp/thing")
    await desk.forget_project("dir:/tmp/thing")

    projects = routes.shape([_a_row("/tmp/thing")], [], await desk.seen_projects())

    assert [one.name for one in projects] == ["thing"]


def test_the_control_is_offered_on_the_project_and_says_what_it_leaves() -> None:
    here = pathlib.Path(__file__).resolve().parents[2]
    said = (here / "agent_desk" / "web" / "templates" / "_project.html").read_text(encoding="utf-8")

    assert 'action="/projects/forget"' in said
    assert "queue and its connectors stay" in said
