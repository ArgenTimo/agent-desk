"""The input field: what it produces, and what it refuses to make you wait for.

docs/04-threads-and-blocks.md is the whole specification of this file. Its first claim is the one
worth testing hardest — submitting frees the field — because every other property here follows
from questions being independent errands rather than a queue.
"""

from __future__ import annotations

import asyncio
import pathlib
import time
from collections.abc import AsyncIterator

import pytest
from agent_desk.answer import session
from agent_desk.config import Settings
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes
from agent_desk.web.app import app

FAKE = """#!/bin/sh
here=$(dirname "$0")
prompt=$(cat)
case "$prompt" in
  # The classifier asks first, and it must be matched first: its prompt quotes the subjects of the
  # open threads, so every marker in this file appears inside it too.
  *"Open subjects"*) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"new"}]}}\n' ;;
  *PLEASE_HANG*)
    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"thinking"}]}}\\n'
    sleep 30 ;;
  *PLEASE_FAIL_ONCE*)
    if [ -f "$here/failed-once" ]; then
      printf '{"type":"assistant","message":{"content":[{"type":"text","text":"an answer"}]}}\n'
    else
      touch "$here/failed-once"
      exit 4
    fi ;;
  *) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"an answer"}]}}\\n' ;;
esac
"""


def make_row(project: str, branch: str) -> object:
    """One board row, built the way `routes.board()` builds them."""
    from agent_desk.observe.model import AttentionHint, Session, TailEntry, TranscriptTail
    from agent_desk.web.routes import BoardRow

    return BoardRow(
        session=Session.model_validate(
            {
                "pid": abs(hash(project)) % 100000,
                "procStart": "1",
                "sessionId": f"session-{project}",
                "cwd": f"/home/dev/projects/{project}",
                "name": f"{project}-d0",
                "kind": "interactive",
                "version": "2.1.259",
                "status": "busy",
                "updatedAt": 0,
                "statusUpdatedAt": 0,
            }
        ),
        tail=TranscriptTail(
            session_id=f"session-{project}",
            title="a title",
            git_branch=branch,
            entries=[TailEntry(role="assistant", text="doing something")],
        ),
        hint=AttentionHint(waiting=False, observation="busy 0s"),
    )


@pytest.fixture
def fake_claude(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    binary = tmp_path / "cli" / "claude"
    binary.parent.mkdir()
    binary.write_text(FAKE)
    binary.chmod(0o755)
    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(binary), answer_timeout_seconds=5.0)
    )
    return binary


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    """A store and a task group, wired the way the application wires them."""
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    async with asyncio.TaskGroup() as group:
        blocks.runs.attach(group)
        try:
            yield store
        finally:
            blocks.runs.cancel_all()
            blocks.runs.attach(None)
    await store.close()


async def _state(store: Store, block_id: str) -> str:
    block = await store.block(block_id)
    assert block is not None
    return block.state


@pytest.mark.unit
async def test_submitting_frees_the_field(desk: Store, fake_claude: pathlib.Path) -> None:
    """The field is free before the answer exists, which is the point of a block."""
    started = time.monotonic()
    block = await blocks.submit(desk, "PLEASE_HANG — what about timeouts", [])
    elapsed = time.monotonic() - started

    # The fake sleeps for thirty seconds. Accepting the input took none of them.
    assert elapsed < 2
    assert await _state(desk, block.id) in ("queued", "running")


@pytest.mark.unit
async def test_several_questions_run_at_once_and_nothing_waits(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    first = await blocks.submit(desk, "PLEASE_HANG one", [])
    second = await blocks.submit(desk, "PLEASE_HANG two", [])
    await asyncio.sleep(0.4)

    assert await _state(desk, first.id) == "running"
    assert await _state(desk, second.id) == "running"
    assert len(blocks.runs) == 2


@pytest.mark.unit
async def test_an_answer_reaches_the_column(desk: Store, fake_claude: pathlib.Path) -> None:
    block = await blocks.submit(desk, "what about timeouts", [])
    for _ in range(50):
        if await _state(desk, block.id) == "answered":
            break
        await asyncio.sleep(0.1)

    assert await _state(desk, block.id) == "answered"
    column = await routes.render_blocks()
    assert "what about timeouts" in column
    assert "an answer" in column


@pytest.mark.unit
async def test_a_running_block_shows_what_it_has_said_so_far(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """docs/04: the question, then the answer as it streams.

    The partial lives in memory and nowhere else — an answer copied into a second place is a
    second thing to redact (design/02-data-model.md).
    """
    block = await blocks.submit(desk, "PLEASE_HANG and stream", [])
    for _ in range(50):
        if blocks.PARTIAL.get(block.id):
            break
        await asyncio.sleep(0.1)

    assert blocks.PARTIAL[block.id] == "thinking"
    assert "thinking" in await routes.render_blocks()


@pytest.mark.unit
async def test_cancelling_a_run_leaves_a_block_that_says_it_was_cancelled(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    block = await blocks.submit(desk, "PLEASE_HANG forever", [])
    await asyncio.sleep(0.3)
    assert blocks.cancel(block.id)

    for _ in range(50):
        if await _state(desk, block.id) == "cancelled":
            break
        await asyncio.sleep(0.1)
    assert await _state(desk, block.id) == "cancelled"
    assert block.id not in blocks.PARTIAL


@pytest.mark.unit
async def test_a_failed_block_can_be_retried_and_then_answers(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """It does not disappear, because a question that vanished is one you ask again.

    The fake fails the first time and answers the second, so this asserts that retry actually ran
    the question again rather than that the same input happens to succeed.
    """
    block = await blocks.submit(desk, "PLEASE_FAIL_ONCE", [])
    for _ in range(50):
        if await _state(desk, block.id) == "failed":
            break
        await asyncio.sleep(0.1)
    assert await _state(desk, block.id) == "failed"
    assert "retry" in await routes.render_blocks()

    stored = await desk.block(block.id)
    assert stored is not None
    await blocks.retry(desk, stored, [])
    for _ in range(50):
        if await _state(desk, block.id) == "answered":
            break
        await asyncio.sleep(0.1)
    assert await _state(desk, block.id) == "answered"


@pytest.mark.unit
async def test_the_console_stops_even_with_questions_in_the_air(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, fake_claude: pathlib.Path
) -> None:
    """Shutdown ends runs rather than waiting for them.

    A console that will not close while three questions are in flight is the shutdown hang this
    project already fixed once, wearing a different coat.
    """
    monkeypatch.setattr(routes, "store", Store(tmp_path / "lifespan.db"))
    started = time.monotonic()
    async with app.router.lifespan_context(app):
        await blocks.submit(routes.store, "PLEASE_HANG during shutdown", [])
        await asyncio.sleep(0.3)
    elapsed = time.monotonic() - started

    assert elapsed < 5
    assert len(blocks.runs) == 0


@pytest.mark.unit
def test_the_board_reaches_the_run_as_facts_and_not_as_a_guess() -> None:
    """docs/03-session-observation.md: the inference is this program's guess.

    Feeding a guess to a model that will then reason from it is how a guess becomes a fact, so the
    flag does not travel into the prompt — the status, the branch and the last entry do.
    """
    from agent_desk.observe.model import AttentionHint, Session, TailEntry, TranscriptTail
    from agent_desk.web.routes import BoardRow

    row = BoardRow(
        session=Session.model_validate(
            {
                "pid": 1,
                "procStart": "1",
                "sessionId": "s",
                "cwd": "/home/dev/projects/alpha",
                "name": "alpha-d0",
                "kind": "interactive",
                "version": "2.1.259",
                "status": "idle",
                "updatedAt": 0,
                "statusUpdatedAt": 0,
            }
        ),
        tail=TranscriptTail(
            session_id="s",
            title="Docker client",
            git_branch="boba/duck-129",
            entries=[TailEntry(role="assistant", text="reading the client")],
        ),
        hint=AttentionHint(waiting=True, observation="idle 14m · last entry: assistant"),
    )

    (line,) = blocks.board_lines([row])
    assert "alpha" in line
    assert "boba/duck-129" in line
    assert "reading the client" in line
    assert "waiting" not in line
    assert "may be waiting" not in line


async def _post(
    path: str, fields: dict[str, str], *, htmx: bool = False
) -> tuple[int, str, dict[str, str]]:
    """One urlencoded POST through the real ASGI stack — middleware, routing and form parsing.

    Every other test in this file calls `submit()` directly, and that is exactly how a route-level
    bug survived them: the browser found a 500 from `request.form()`, which asserts that
    `python-multipart` is installed before it will read even an urlencoded body. The fix was three
    lines of `urllib`; this test is the reason it stays fixed.
    """
    from urllib.parse import urlencode

    from agent_desk.web.app import asgi

    body = urlencode(fields).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"127.0.0.1:8787"),
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"content-length", str(len(body)).encode()),
        ]
        + ([(b"hx-request", b"true")] if htmx else []),
        "client": ("127.0.0.1", 54321),
        "server": ("127.0.0.1", 8787),
    }
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await asgi(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    html = b"".join(bytes(m.get("body", b"")) for m in sent if m["type"] == "http.response.body")
    headers = {k.decode(): v.decode() for k, v in start.get("headers", [])}  # type: ignore[union-attr]
    return int(start["status"]), html.decode(), headers  # type: ignore[arg-type]


@pytest.mark.unit
async def test_a_typed_line_survives_the_route_and_not_only_the_function(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """The htmx path: the column comes back as a fragment and the page never moves."""
    status, html, _ = await _post("/blocks", {"text": "what about timeouts"}, htmx=True)

    assert status == 200
    assert "what about timeouts" in html
    assert len(await desk.blocks()) == 1


@pytest.mark.unit
async def test_a_typed_line_works_with_no_htmx_at_all(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """The same form, submitted by a browser that never loaded the library.

    A console that cannot be used without a vendored file has the dependency the wrong way round,
    and this repository has spent three days without that file.
    """
    status, _, headers = await _post("/blocks", {"text": "what about timeouts"})

    # Post/redirect/get: a refresh after asking must not ask again.
    assert status == 303
    assert headers["location"] == "/"
    assert len(await desk.blocks()) == 1

    page = (await routes.page()).body.decode()
    assert "what about timeouts" in page


@pytest.mark.unit
async def test_an_empty_line_is_accepted_and_produces_nothing(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """Pressing enter on an empty field is not an error and is not a block."""
    status, _, _ = await _post("/blocks", {"text": "   "}, htmx=True)

    assert status == 200
    assert await desk.blocks() == []


@pytest.mark.unit
async def test_every_action_in_the_console_is_a_real_form(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """htmx upgrades this console; it does not enable it.

    A `hx-post` with no `action` is a control that does nothing when a vendored file is missing,
    and a page full of those is a page that lies about being usable. Every one of them carries a
    method and an action too, and the routes answer a fragment or a page depending on who asked.
    """
    import re

    await blocks.submit(desk, "a question", [])
    await blocks.submit(desk, "/idea a thought", [])
    body = (await routes.page()).body.decode()

    forms = re.findall(r"<form[^>]*>", body)
    posting = [form for form in forms if "hx-post" in form]
    assert posting, "the page has no actions at all"
    for form in posting:
        assert 'method="post"' in form, form
        assert "action=" in form, form

    # And the one control that opens the write path is a link, which works everywhere.
    assert re.search(r'<a class="message-button" href="/sessions/[^"]+/message"', body)


# --- what a reviewer found by probing the task group ------------------------------------------
@pytest.mark.unit
async def test_one_question_going_wrong_does_not_take_the_others_with_it(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """The module docstring claims this; until a reviewer probed it, it was not true.

    A blank line from the summariser raised IndexError inside a TaskGroup child, which cancels
    every sibling and propagates out of the lifespan — the input field, every run in flight, and
    the console with them.
    """
    healthy = await blocks.submit(desk, "PLEASE_HANG while a sibling explodes", [])
    await asyncio.sleep(0.3)

    async def explode() -> None:
        raise RuntimeError("a run that raises where nobody expected one")

    blocks.runs.start("a-broken-run", explode())
    await asyncio.sleep(0.3)

    # The group is still standing and the other question is still being answered.
    assert await _state(desk, healthy.id) == "running"
    assert await blocks.submit(desk, "and the field still works", []) is not None


@pytest.mark.unit
async def test_a_blank_summary_reply_is_not_a_crash(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The specific trigger: `any([" "])` is True, and `" ".strip().splitlines()` is empty."""
    binary = tmp_path / "blank" / "claude"
    binary.parent.mkdir()
    binary.write_text(
        "#!/bin/sh\ncat > /dev/null\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"   "}]}}\\n\'\n'
    )
    binary.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(binary)))

    block = await blocks.capture_idea(desk, "a thought worth keeping", [])
    await asyncio.sleep(1.0)

    (idea,) = await desk.ideas()
    assert idea.text == "a thought worth keeping"
    assert idea.summary == "a thought worth keeping"  # the fallback survived
    assert await _state(desk, block.id) == "answered"


@pytest.mark.unit
async def test_a_block_never_has_two_runs(desk: Store, fake_claude: pathlib.Path) -> None:
    """Starting a second run for one block used to orphan the first: the map was overwritten, the
    first task's callback removed the second entry, and `cancel` then reported success over a run
    that was no longer there — two `claude -p` processes racing to write one row.
    """
    block = await blocks.submit(desk, "PLEASE_HANG one", [])
    await asyncio.sleep(0.3)
    first = blocks.runs._by_block[block.id]

    stored = await desk.block(block.id)
    assert stored is not None
    await blocks.retry(desk, stored, [])
    await asyncio.sleep(0.3)

    assert len(blocks.runs) == 1
    assert first.cancelled() or first.done()
    assert blocks.cancel(block.id) is True


@pytest.mark.unit
async def test_moving_a_block_to_the_thread_it_is_already_in_is_not_a_correction(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """Submitting the select unchanged used to spend a run and flip `thread_set_by` to `human`,
    quietly corrupting the one number docs/09-roadmap.md says decides the classifier's fate."""
    block = await blocks.submit(desk, "a question", [])
    for _ in range(50):
        if await _state(desk, block.id) == "answered":
            break
        await asyncio.sleep(0.1)

    stored = await desk.block(block.id)
    assert stored is not None
    await blocks.set_thread(desk, stored, stored.thread_id, [])
    await asyncio.sleep(0.2)

    unchanged = await desk.block(block.id)
    assert unchanged is not None
    assert unchanged.thread_id == stored.thread_id
    assert unchanged.state == "answered"
    assert len(blocks.runs) == 0


@pytest.mark.unit
async def test_every_write_route_answers_a_browser_as_well_as_htmx(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """Five of the seven had this contract in a document and nowhere else.

    A reviewer removed the redirect from `/blocks/{id}/thread` — so a refresh would re-submit the
    override and re-run the block — and the suite stayed green. docs/02-architecture.md says htmx
    is an upgrade; that only means something if it is checked.
    """
    block = await blocks.submit(desk, "a question", [])
    for _ in range(50):
        if await _state(desk, block.id) == "answered":
            break
        await asyncio.sleep(0.1)

    stored = await desk.block(block.id)
    assert stored is not None
    routes_under_test = [
        ("/blocks", {"text": "another question"}),
        (f"/blocks/{block.id}/cancel", {}),
        (f"/blocks/{block.id}/retry", {}),
        (f"/blocks/{block.id}/thread", {"thread_id": ""}),
    ]

    for path, fields in routes_under_test:
        status, _, headers = await _post(path, fields)
        assert status == 303, path
        assert headers["location"] == "/", path

        status, html, _ = await _post(path, fields, htmx=True)
        assert status == 200, path
        assert "<article" in html or "nothing asked yet" in html, path
