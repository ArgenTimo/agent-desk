"""What an agent can call, over MCP (01M1YY2QHY512RZWTJWTPQXRY8 and its children).

"Возможность подключаться к этому проекту по MCP."

This program's stated purpose is "an idea inbox that costs no agent any context". Until now only a
person could write into it.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.mcp import saying, server, tools
from agent_desk.store.repo import Store

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


def _said(back: dict[str, object]) -> str:
    return back["content"][0]["text"]  # type: ignore[index,return-value]


# --- the pool, which is the first thing here ------------------------------------------------------
async def test_a_thought_can_be_written_down(desk: Store) -> None:
    back = await tools.call(desk, "keep_idea", {"text": "read the registry before the transcript"})

    (only,) = await desk.ideas()
    assert only.text == "read the registry before the transcript"
    assert only.id in _said(back)


async def test_the_same_words_twice_are_one_idea(desk: Store) -> None:
    """An agent restarted mid-task writes its list again and has no way of knowing whether the
    first attempt landed. Doubling the pool for that is a pool nobody trusts."""
    said = "read the registry before trusting the transcript"
    await tools.call(desk, "keep_idea", {"text": said})

    back = await tools.call(desk, "keep_idea", {"text": said})

    assert len(await desk.ideas()) == 1
    assert "Already here" in _said(back)


async def test_nothing_written_down_says_so(desk: Store) -> None:
    back = await tools.call(desk, "keep_idea", {"text": "   "})

    assert await desk.ideas() == []
    assert "was empty" in _said(back)


async def test_what_is_open_is_lines_rather_than_objects(desk: Store) -> None:
    """What a caller does with this is read it, and a JSON array of objects costs three times the
    tokens to say the same thing."""
    made = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")

    back = _said(await tools.call(desk, "open_ideas", {}))

    assert back == f"{made.id} [new] a thought"


async def test_an_empty_pool_says_so_rather_than_nothing(desk: Store) -> None:
    assert _said(await tools.call(desk, "open_ideas", {})) == "Nothing is open."


async def test_a_closed_idea_is_not_open(desk: Store) -> None:
    made = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")

    await tools.call(desk, "close_idea", {"id": made.id, "note": "built in abc1234"})

    again = await desk.idea(made.id)
    assert again is not None and again.state == "done"
    assert _said(await tools.call(desk, "open_ideas", {})) == "Nothing is open."


async def test_closing_without_saying_what_closed_it_is_refused(desk: Store) -> None:
    """An idea closed with nothing pointing at what closed it is a row that says work happened and
    cannot show it."""
    made = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")

    back = await tools.call(desk, "close_idea", {"id": made.id, "note": ""})

    assert "Say what closed it" in _said(back)
    assert (await desk.idea(made.id)).state == "new"  # type: ignore[union-attr]


async def test_an_id_that_is_not_here_says_so(desk: Store) -> None:
    assert "no idea with that id" in _said(await tools.call(desk, "idea", {"id": "01M1NO"}))
    assert "no idea with that id" in _said(
        await tools.call(desk, "close_idea", {"id": "01M1NO", "note": "x"})
    )


# --- and nothing here removes anything ------------------------------------------------------------
def test_no_tool_deletes() -> None:
    """The worst a mistaken agent can do is add a row to a list, and that is what makes this
    surface safe to call without asking first."""
    for tool in tools.TOOLS:
        assert "delete" not in tool.name and "drop" not in tool.name
        assert not tool.says.lower().startswith("delete")


def test_every_tool_says_whether_it_changes_anything() -> None:
    """A caller deciding whether to ask first deserves to know, and a surface where that is obvious
    per tool cannot grow a destructive one by accident."""
    said = server._tools_said()["tools"]

    assert {one["name"] for one in said} == {one.name for one in tools.TOOLS}
    for one in said:
        assert one["annotations"]["destructiveHint"] is False
    writing = {one["name"] for one in said if not one["annotations"]["readOnlyHint"]}
    assert writing == {"keep_idea", "close_idea"}


async def test_a_tool_that_raises_answers_rather_than_breaking_the_transport(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller that asked for something reasonable and got a transport failure cannot tell that
    from the server being down."""

    async def falls_over(store: Store, given: dict[str, object]) -> str:
        raise RuntimeError("the disk went away")

    broken = tools.Tool(name="open_ideas", says="x", takes={}, run=falls_over)
    monkeypatch.setattr(tools, "named", lambda name: broken)

    assert "did not work" in _said(await tools.call(desk, "open_ideas", {}))


async def test_a_tool_nobody_has_answers_rather_than_failing(desk: Store) -> None:
    assert "no tool called" in _said(await tools.call(desk, "nonsense", {}))


async def test_a_thought_a_reader_could_not_understand_is_refused_with_the_reason(
    desk: Store,
) -> None:
    """An idea written by an agent is a proposal, and a proposal arrives with nobody. If its first
    line cannot be understood without opening the card, the work of getting into its context has
    been handed to whoever reads it — which is the work it was meant to save."""
    back = _said(await tools.call(desk, "keep_idea", {"text": "hotkeys"}))

    assert "Not written down" in back and "at a glance" in back
    assert await desk.ideas() == []


# --- every answer fits in a context window --------------------------------------------------------
def test_a_long_answer_is_cut_and_says_how_much_was_cut() -> None:
    """A truncated answer with a number on it is a fact; one without is a lie."""
    said = saying.within("\n".join(f"line {at}" for at in range(500)))

    assert len(said) <= saying.MOST_CHARS
    assert "more line" in said.splitlines()[-1]


def test_a_short_answer_is_untouched() -> None:
    assert saying.within("two\nlines") == "two\nlines"


def test_one_line_longer_than_the_budget_is_cut_rather_than_refused() -> None:
    """An instrument that returns nothing when asked something is one nobody calls twice."""
    said = saying.within("x" * 9000)

    assert len(said) <= saying.MOST_CHARS
    assert "more line" in said


async def test_every_answer_goes_through_the_ceiling(desk: Store) -> None:
    for at in range(400):
        await desk.create_idea(
            text_=f"thought {at}", summary=f"thought number {at}", source_kind="typed"
        )

    back = _said(await tools.call(desk, "open_ideas", {}))

    assert len(back) <= saying.MOST_CHARS


# --- the protocol ---------------------------------------------------------------------------------
async def test_it_says_which_protocol_it_speaks(desk: Store) -> None:
    """Named rather than echoed back from the client: a server that agrees to whatever it is told
    is one that will one day agree to something it cannot do."""
    back = await server.answer(desk, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})

    assert back is not None
    assert back["result"]["protocolVersion"] == server.PROTOCOL


async def test_a_notification_is_answered_with_nothing(desk: Store) -> None:
    """Which is what JSON-RPC says, and what a client waiting for a reply to `initialized` would
    hang on."""
    assert (
        await server.answer(desk, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    )


async def test_a_method_this_does_not_have_is_refused_by_code(desk: Store) -> None:
    """A client that asked for something this does not have should find out now, not by waiting."""
    back = await server.answer(desk, {"jsonrpc": "2.0", "id": 2, "method": "resources/list"})

    assert back is not None and back["error"]["code"] == -32601


async def test_a_line_that_is_not_json_does_not_take_the_server_down(desk: Store) -> None:
    """One malformed message is not a reason to stop a server another tool call is about to use."""
    said = []
    reader = _lines([b"not json\n", b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n', b""])

    await server.serve(reader, said.append, desk)

    assert json.loads(said[0])["error"]["code"] == -32700
    assert json.loads(said[1])["id"] == 1


async def test_stdin_closing_ends_it(desk: Store) -> None:
    said = []

    await server.serve(_lines([b""]), said.append, desk)

    assert said == []


def _lines(rows: list[bytes]):  # type: ignore[no-untyped-def]
    class Reader:
        def __init__(self) -> None:
            self.left = list(rows)

        async def readline(self) -> bytes:
            return self.left.pop(0) if self.left else b""

    return Reader()


async def test_the_tools_can_be_listed_and_called_through_the_protocol(desk: Store) -> None:
    """The three messages a client actually sends, in order."""
    listed = await server.answer(desk, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed is not None
    assert {one["name"] for one in listed["result"]["tools"]} == {one.name for one in tools.TOOLS}

    called = await server.answer(
        desk,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "open_ideas", "arguments": {}},
        },
    )
    assert called is not None
    assert _said(called["result"]) == "Nothing is open."


async def test_a_call_with_no_arguments_at_all_still_works(desk: Store) -> None:
    """A client that sends `params` without `arguments` is not a client that has done anything
    wrong."""
    back = await server.answer(
        desk, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "open_ideas"}}
    )

    assert back is not None and "Nothing is open" in _said(back["result"])


async def test_a_request_that_is_not_an_object_is_refused(desk: Store) -> None:
    said = []

    await server.serve(_lines([b"[1,2,3]\n", b""]), said.append, desk)

    assert json.loads(said[0])["error"]["code"] == -32600


async def test_one_idea_in_full_says_what_it_is_part_of(desk: Store) -> None:
    """A sub-idea read on its own is half a thought without the line that says which whole."""
    whole = await desk.create_idea(text_="rework it", summary="rework it", source_kind="typed")
    part = await desk.create_idea(text_="and a grid", summary="and a grid", source_kind="typed")
    await desk.set_idea_parent(part.id, whole.id)

    back = _said(await tools.call(desk, "idea", {"id": part.id}))

    assert "and a grid" in back
    assert f"part of {whole.id}" in back
