"""What an agent worked out survives its session (01M21NAVE2Q54EJTYYQ2TRNDYG).

«Каждая сессия начинается с нуля и заново выясняет то же самое: почему здесь так, что уже пробовали,
что решили и почему. Ответы существуют — они в коммитах, в решениях, в головах, — но их дешевле
вывести заново, чем найти, и поэтому их выводят заново.»
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


# --- a fact with a reason, not a note ------------------------------------------------------------
async def test_a_fact_keeps_its_reason_and_what_breaks_without_it(desk: Store) -> None:
    """ "Причина — половина записи и та половина, которая делает её полезной." A note saying "check
    procStart" is a line somebody deletes while tidying; the same note with why is one they leave
    alone."""
    one = await desk.record_known(
        "the registry reader verifies a pid against procStart",
        why="pids are reused",
        otherwise="a dead session shows on the board as busy",
        source="docs/03-session-observation.md",
        files=["agent_desk/observe/registry.py"],
    )

    (back,) = await desk.known()
    assert back.id == one.id
    assert back.why == "pids are reused"
    assert back.otherwise == "a dead session shows on the board as busy"
    assert back.about == ["agent_desk/observe/registry.py"]


async def test_a_fact_with_no_source_is_not_written_down(desk: Store) -> None:
    """ "Факт без источника не записывается." A fact nobody can chase is a rumour with a timestamp,
    and a store full of those is worse than an empty one because it looks like knowledge."""
    with pytest.raises(ValueError, match="source"):
        await desk.record_known("it has always been like that", source="   ")

    assert await desk.known() == []


async def test_a_fact_that_says_nothing_is_not_written_down(desk: Store) -> None:
    with pytest.raises(ValueError):
        await desk.record_known("  ", source="a commit")


# --- what relates to the work in front of you ----------------------------------------------------
async def test_only_what_names_the_files_the_work_touches_comes_back(desk: Store) -> None:
    """ "Сто фактов в контексте не лучше нуля. Отдаётся то, что называет файлы, которых касается
    работа.\" """
    await desk.record_known("about the reader", source="a commit", files=["observe/registry.py"])
    await desk.record_known("about the store", source="a commit", files=["store/repo.py"])

    found = await desk.known(touching=["store/repo.py"])

    assert [one.what for one in found] == ["about the store"]


async def test_a_fact_about_no_file_in_particular_reaches_every_reader(desk: Store) -> None:
    """Naming no file is not an oversight: it is a fact about the project rather than about a part
    of it, and it is true wherever somebody is working."""
    await desk.record_known(
        "this program never writes into an observed repository", source="CLAUDE.md"
    )
    await desk.record_known("about the store", source="a commit", files=["store/repo.py"])

    found = await desk.known(touching=["observe/registry.py"])

    assert [one.what for one in found] == ["this program never writes into an observed repository"]


# --- through MCP ---------------------------------------------------------------------------------
async def test_an_agent_writes_a_fact_down_and_reads_it_back(desk: Store) -> None:
    written = _said(
        await tools.call(
            desk,
            "know",
            {
                "what": "the reader verifies a pid against procStart",
                "why": "pids are reused",
                "otherwise": "a dead session reads as busy",
                "source": "docs/03-session-observation.md",
                "files": ["agent_desk/observe/registry.py"],
            },
        )
    )
    said = _said(
        await tools.call(desk, "what_is_known", {"files": ["agent_desk/observe/registry.py"]})
    )

    assert "agent_desk/observe/registry.py" in written
    assert "the reader verifies a pid against procStart" in said
    assert "because pids are reused" in said
    assert "otherwise a dead session reads as busy" in said
    assert "docs/03-session-observation.md" in said


async def test_an_agent_is_told_why_a_fact_was_refused(desk: Store) -> None:
    """The fix is one sentence and the caller is the one who can write it, so it is said in full
    rather than returned as a failure."""
    said = _said(await tools.call(desk, "know", {"what": "it has always been like that"}))

    assert "source" in said
    assert await desk.known() == []


async def test_nothing_written_down_is_said_in_words(desk: Store) -> None:
    said = _said(await tools.call(desk, "what_is_known", {"files": ["store/repo.py"]}))

    assert "Nothing has been written down" in said
    assert "store/repo.py" in said


# --- and through the page, the same way ----------------------------------------------------------
async def test_the_page_writes_a_fact_through_the_same_function(desk: Store) -> None:
    """ "Запись через MCP и через страницу одинаково." A page that recorded facts a second way would
    be a second set of rules about what a fact has to carry."""
    back = await routes.write_down_what_is_known(
        _a_form(
            {
                "what": "the console is one process",
                "why": "a second one would fight over the file",
                "source": "docs/adr/0003",
                "files": "agent_desk/web/app.py",
            }
        )
    )

    assert back.status_code == 204
    (one,) = await desk.known()
    assert one.about == ["agent_desk/web/app.py"]


async def test_the_page_refuses_a_fact_with_no_source_and_says_so(desk: Store) -> None:
    """A form that quietly discards what somebody typed is worse than one that refuses it, because
    they walk away believing it was written down."""
    back = await routes.write_down_what_is_known(_a_form({"what": "something", "source": ""}))

    assert back.status_code == 422
    assert "source" in back.body.decode()
    assert await desk.known() == []


async def test_a_file_card_shows_what_is_known_about_that_file(desk: Store) -> None:
    """The moment a fact about a file is worth reading is the moment somebody has that file in
    front of them. Read as a browser reads it."""
    await desk.record_known(
        "this one is parsed nowhere else",
        why="the format is not a contract",
        source="docs/adr/0004",
        files=["/tmp/observe/transcript.py"],
    )
    await desk.record_known("about something else", source="a commit", files=["/tmp/other.py"])

    said = (await routes.card(kind="file", id="/tmp/observe/transcript.py")).body.decode()

    assert "this one is parsed nowhere else" in said
    assert "the format is not a contract" in said
    assert "about something else" not in said


async def test_a_file_card_offers_the_same_write(desk: Store) -> None:
    said = (await routes.card(kind="file", id="/tmp/observe/transcript.py")).body.decode()

    assert 'action="/known"' in said
    assert 'name="source"' in said
