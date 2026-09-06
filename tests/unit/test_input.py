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
from dataclasses import replace

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
  # Two classifiers ask before the answer does, and both must be matched first: their prompts
  # quote the line that was typed, so every marker in this file appears inside them too. What
  # kind it is comes first of all, because it decides whether the rest happens at all.
  *"which of three things"*) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"question"}]}}\n' ;;
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
    assert await blocks.cancel(desk, block.id)

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

    # And the one control that opens the write path is a link, which works everywhere. It lives
    # on the card now rather than on the board — the left column carries names and states, and
    # everything you can *do* to a session is on the card it opens (docs/06-console.md).
    card = routes.env.get_template("_card.html").render(
        kind="session", rows=[make_row("alpha", "main")], card_id="session-alpha"
    )
    assert re.search(r'<a class="message-button[^"]*" href="/sessions/[^"]+/message"', card)


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

    blocks.runs.start("a-broken-run", explode)
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
    assert await blocks.cancel(desk, block.id) is True


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


# --- what the second confirmation round found ---------------------------------------------------
@pytest.mark.unit
async def test_a_run_cancelled_before_it_starts_still_leaves_a_settled_block(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """A task cancelled before its first step never enters the coroutine, so the shielded write
    inside it never happened — and the block sat `queued` for ever, with nothing behind it, retry
    offered only for settled blocks, and the crash rule deliberately leaving `queued` alone.
    """
    block = await blocks.submit(desk, "PLEASE_HANG and be cancelled at once", [])
    assert await blocks.cancel(desk, block.id)

    settled = await desk.block(block.id)
    assert settled is not None
    assert settled.state == "cancelled"


@pytest.mark.unit
async def test_a_retry_never_shows_a_cancelled_block_with_a_live_run(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """The old run's shielded `cancelled` used to land after the new run's `running`, so the
    console showed a cancelled block with a subprocess behind it — and offered retry, which
    cancelled the live run and repeated the cycle. Stopping before starting removes the race.
    """
    block = await blocks.submit(desk, "PLEASE_HANG one", [])
    await asyncio.sleep(0.3)

    stored = await desk.block(block.id)
    assert stored is not None
    await blocks.retry(desk, stored, [])
    await asyncio.sleep(0.4)

    after = await desk.block(block.id)
    assert after is not None
    assert after.state == "running", "the replacement run owns the block"
    assert len(blocks.runs) == 1


@pytest.mark.unit
async def test_the_partial_answer_is_redacted_while_it_streams(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The console used to render a running answer verbatim and the identical finished answer
    redacted. The scrub in the callback was the fix, and removing it left the suite green.
    """
    secret = "ghp_" + "v" * 36
    binary = tmp_path / "leaky" / "claude"
    binary.parent.mkdir()
    # It answers the kind question honestly and then leaks into the answer itself: this test is
    # about what the console renders while a run is streaming, not about classification.
    binary.write_text(
        '#!/bin/sh\nprompt=$(cat)\ncase "$prompt" in\n'
        '  *"which of three things"*) printf \'{"type":"assistant","message":{"content":'
        '[{"type":"text","text":"question"}]}}\\n\' ;;\n'
        '  *) printf \'{"type":"assistant","message":{"content":[{"type":"text","text":'
        '"the config had ' + secret + " in it\"}]}}\\n'\n     sleep 30 ;;\nesac\n"
    )
    binary.chmod(0o755)
    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(binary), answer_timeout_seconds=10.0)
    )

    block = await blocks.submit(desk, "what is in the config", [])
    for _ in range(50):
        if blocks.PARTIAL.get(block.id):
            break
        await asyncio.sleep(0.1)

    assert secret not in blocks.PARTIAL[block.id]
    assert "[redacted]" in blocks.PARTIAL[block.id]
    assert secret not in await routes.render_blocks()


@pytest.mark.unit
async def test_a_block_whose_thread_fell_off_the_list_still_shows_it(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """One open subject is created per question, so twenty-one is ordinary use.

    Past the bound the select rendered with nothing selected, a browser displayed the first entry
    — the newest subject — as the block's thread, and the ↵ button posted that: the control for
    correcting a misfile made one, and logged it as a human decision.
    """
    first = await blocks.submit(desk, "the oldest subject", [])
    for _ in range(25):
        await desk.create_thread("a later subject")

    column = await routes.render_blocks()
    thread = await desk.block(first.id)
    assert thread is not None
    assert f'value="{thread.thread_id}" selected' in column


@pytest.mark.unit
async def test_the_idea_card_carries_what_its_buttons_need(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """Deleting the hidden field left the suite green while Keep navigated to the wrong page.

    The route was tested by a test that posted the field by hand; nothing asserted that the card
    that has to send it does.
    """
    await blocks.submit(desk, "/idea a thought", [])
    card = await routes.render_blocks()

    assert card.count('name="from" value="card"') >= 3, "keep, discard and the summary form"
    assert 'action="/ideas/' in card
    # docs/04's action table and docs/05's drawing both give the card an edit control.
    assert 'name="summary"' in card


# --- pointing a question at a card ---------------------------------------------------------------
@pytest.mark.unit
async def test_a_question_can_be_about_one_session_one_project_or_nothing(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """The three cases of docs/06-console.md, and the third is the default.

    Nothing chosen means the run gets the whole board and works out what the question is about,
    which is what somebody who has not chosen wants — rather than a form telling them to choose.
    """
    from agent_desk.web.blocks import aim

    alpha = make_row("alpha", "main")
    beta = make_row("beta", "staging")
    rows = [
        replace(alpha, project_key="p-alpha", project_name="alpha"),
        replace(beta, project_key="p-beta", project_name="beta"),
    ]

    aimed, about = aim(rows)
    assert len(aimed) == 2 and about == ""

    aimed, about = aim(rows, project="p-beta")
    assert [row.session.project for row in aimed] == ["beta"]
    assert "one project: beta" == about

    aimed, about = aim(rows, session=alpha.session.session_id)
    assert [row.session.project for row in aimed] == ["alpha"]
    assert about.startswith("one session: alpha")


@pytest.mark.unit
async def test_a_target_that_has_gone_falls_back_to_the_whole_board(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """Sessions end. A question asked a second after one did is still a question."""
    from agent_desk.web.blocks import aim

    rows = [replace(make_row("alpha", "main"), project_key="p-alpha", project_name="alpha")]

    aimed, about = aim(rows, session="a-session-that-ended")
    assert aimed == rows
    assert about == ""


@pytest.mark.unit
async def test_what_the_question_is_about_reaches_the_run(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """Choosing in the interface has to change the prompt, or the control is decoration."""
    prompt = session.build_prompt(
        "is it done", board=["- alpha · main · busy"], history=[], about="one project: alpha"
    )
    assert "What this question is about" in prompt
    assert "one project: alpha" in prompt


@pytest.mark.unit
def test_the_answer_is_asked_for_in_words_a_person_can_use() -> None:
    """This window is watched by somebody who is not doing the work, and often by somebody who
    does not read code. Four paragraphs of technical prose is a second thing to read, not an
    answer."""
    prompt = session.build_prompt("anything", board=[], history=[])

    assert "Two or three sentences" in prompt
    assert "does not read code" in prompt
    assert "name the session" in prompt


# --- what the middle column does with what is dropped into it -----------------------------------
@pytest.mark.unit
def test_a_card_dropped_into_the_output_is_what_the_next_question_is_about() -> None:
    """The output field carries the cards, and the cards decide what the run reads.

    Four kinds arrive from the tree and three of them are not sessions, because a session is the
    only thing there is evidence about: an agent names the console it runs inside, an instance
    names a checkout, a project names a repository.
    """
    alpha = make_row("alpha", "main")
    beta = make_row("beta", "topic")
    rows = [alpha, beta]

    aimed, about = blocks.aim(rows, targets=["session:session-alpha"])
    assert [row.session.session_id for row in aimed] == ["session-alpha"]
    assert "alpha" in about

    # An agent card is its session: the agent is a thing that session farmed out.
    aimed, _ = blocks.aim(rows, targets=["agent:session-beta"])
    assert [row.session.session_id for row in aimed] == ["session-beta"]

    # Two cards are two subjects, in the order they were dropped, and neither is dropped twice.
    aimed, about = blocks.aim(rows, targets=["session:session-beta", "session:session-alpha"])
    assert [row.session.session_id for row in aimed] == ["session-beta", "session-alpha"]

    # A card whose session has ended falls back to the whole board rather than to nothing: a
    # question asked a second after a session ended should still be answered.
    aimed, about = blocks.aim(rows, targets=["session:gone"])
    assert list(aimed) == rows
    assert about == ""

    # And an instance is a checkout, which is what the tree hangs sessions under.
    aimed, _ = blocks.aim(rows, targets=[f"instance:{alpha.session.cwd}"])
    assert [row.session.session_id for row in aimed] == ["session-alpha"]


@pytest.mark.unit
async def test_a_question_typed_in_a_tab_stays_in_that_tab(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """A tab is a subject somebody chose by typing in it, so nothing classifies it afterwards.

    docs/09-roadmap.md says that if the classifier costs more attention than it saves, the right
    answer is a default and a click. The tabs are that click, and this is what it means: the
    thread is the one the human was looking at, and it is recorded as theirs.
    """
    tab = await desk.create_thread("the migration")
    block = await blocks.submit(desk, "what did it end up doing", [], thread_id=tab.id)

    assert block.thread_id == tab.id
    assert block.thread_set_by == "human"
    await _settled(desk, block.id)
    after = await desk.block(block.id)
    assert after is not None and after.thread_id == tab.id


@pytest.mark.unit
async def test_a_tab_that_no_longer_exists_does_not_lose_the_question(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """A stale page posting a forgotten tab id gets a subject of its own, not an error: the input
    field's first promise is that typing costs nothing."""
    block = await blocks.submit(desk, "still a question", [], thread_id="no-such-thread")
    assert block.thread_id
    assert await desk.block(block.id) is not None


# Twenty seconds rather than five. A block settles by way of a subprocess, and the budget has to
# be for the worst machine this suite runs on rather than for an idle one: this file went red once
# on a laptop with three test runs and twenty agents on it, which is a gate lying about the code.
# Polling means a generous budget costs nothing when things are quick.
SETTLE_SECONDS = 20.0
_POLL = 0.05


async def _settled(store: Store, block_id: str) -> str:
    for _ in range(int(SETTLE_SECONDS / _POLL)):
        state = await _state(store, block_id)
        if state in ("answered", "failed", "cancelled"):
            return state
        await asyncio.sleep(_POLL)
    raise AssertionError("the block never settled")


# --- three things arrive through one field ------------------------------------------------------
KINDS = """#!/bin/sh
prompt=$(cat)
case "$prompt" in
  *"which of three things"*) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"%s"}]}}\\n' "$KIND" ;;
  *"## The sessions"*)
    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"session: 1\\\\nrun the tests again, all of them"}]}}\\n' ;;
  *) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"an answer"}]}}\\n' ;;
esac
"""


@pytest.fixture
def kinds(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """A CLI that says what kind of line it was told to say, and writes a message when asked."""
    binary = tmp_path / "kinds" / "claude"
    binary.parent.mkdir()
    binary.write_text(KINDS)
    binary.chmod(0o755)
    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(binary), answer_timeout_seconds=10.0)
    )
    return binary


@pytest.mark.unit
async def test_a_thought_typed_without_a_prefix_is_still_recorded_as_one(
    desk: Store, kinds: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/05-ideas.md: capture asks no second question — including "was that an idea?".

    `/idea` is for when you already know. This is for when you just typed the thought.
    """
    monkeypatch.setenv("KIND", "idea")
    block = await blocks.submit(desk, "cache the probe results", [])
    assert await _settled(desk, block.id) == "answered"

    after = await desk.block(block.id)
    assert after is not None and after.kind == "idea"
    ideas = await desk.ideas()
    assert [idea.text for idea in ideas] == ["cache the probe results"]
    # Verbatim, never replaced by the generated line (design/02-data-model.md).
    assert ideas[0].block_id == block.id


@pytest.mark.unit
async def test_an_instruction_is_written_out_and_started(
    desk: Store, kinds: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Tell it to test everything again" is written out *and* started (docs/adr/0006).

    The message is still recorded — it is what was asked for, in the words it would be said in —
    but a console whose answer to "do this" is "copy this" has not done the thing it was asked.
    """
    from agent_desk import dispatch

    told: list[str] = []

    def fake_start(
        instruction: str, *, cwd: str, name: str, env: object = None
    ) -> dispatch.Started:
        told.append(instruction)
        return dispatch.Started(True, agent_id="agent3")

    monkeypatch.setattr(dispatch, "start", fake_start)
    monkeypatch.setenv("KIND", "do")
    block = await blocks.submit(
        desk, "tell alpha-d0 to test everything again", [make_row("alpha", "main")]
    )
    assert await _settled(desk, block.id) == "answered"

    after = await desk.block(block.id)
    assert after is not None
    assert after.kind == "instruction"
    assert after.answer and "an agent is working on it" in after.answer
    assert "agent3" in after.answer

    # What it was told is the message that was written, not the line typed at the field.
    assert told and "run the tests again, all of them" in told[0]

    # The message is on the record, against the session it was for and the agent that took it.
    (directive,) = await desk.directives()
    assert directive.session_id == "session-alpha"
    assert directive.text == "run the tests again, all of them"
    assert directive.agent_id == "agent3"
    assert directive.sent_at is None  # nothing was written into that running session


@pytest.mark.unit
async def test_an_instruction_that_names_no_session_prepares_nothing(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable answer produces no message rather than a guess at which console to interrupt."""
    binary = tmp_path / "vague" / "claude"
    binary.parent.mkdir()
    binary.write_text(
        '#!/bin/sh\nprompt=$(cat)\ncase "$prompt" in\n'
        '  *"which of three things"*) printf \'{"type":"assistant","message":{"content":'
        '[{"type":"text","text":"do"}]}}\\n\' ;;\n'
        '  *) printf \'{"type":"assistant","message":{"content":[{"type":"text","text":'
        '"I think session 1 should probably do it"}]}}\\n\' ;;\nesac\n'
    )
    binary.chmod(0o755)
    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(binary), answer_timeout_seconds=10.0)
    )

    block = await blocks.submit(desk, "somebody should run the tests", [make_row("alpha", "main")])
    assert await _settled(desk, block.id) == "answered"
    assert await desk.directives() == []
    after = await desk.block(block.id)
    assert after is not None and "could not tell which project" in (after.answer or "")


# --- what one call to the model is built from ---------------------------------------------------
@pytest.mark.unit
def test_cards_from_two_projects_are_one_question() -> None:
    """ "How would I put this into the other one" is the question this exists for.

    Nothing about a card ties it to its neighbours: two sessions in two repositories dropped into
    the output are two sessions the run is given, and both checkouts are opened for it to read.
    """
    api = make_row("api", "main")
    app = make_row("ios-app", "main")

    aimed, about = blocks.aim(
        [api, app], targets=["session:session-api", "session:session-ios-app"]
    )

    assert [row.session.project for row in aimed] == ["api", "ios-app"]
    assert "api" in about and "ios-app" in about
    # The run reads both working directories, which is what makes an integration question
    # answerable at all. They do not exist on this machine, so the list is what it is; the
    # deduplication and the order are what this asserts.
    assert blocks._add_dirs([row.session for row in aimed]) == []


@pytest.mark.unit
def test_a_card_is_one_line_until_somebody_asks_for_the_whole_transcript() -> None:
    """The default is cheap enough that ten cards cost nothing; `full` is a separate act."""
    row = make_row("alpha", "main")

    assert blocks.transcripts([row], ["session:session-alpha"]) == []

    deep = blocks.transcripts([row], ["session:session-alpha:full"])
    assert any("doing something" in line for line in deep)
    assert any("alpha" in line for line in deep)

    # And a repository key has colons in it, so the suffix is read from the right end only.
    assert blocks._card("project:git:/home/dev/api/.git") == (
        "project",
        "git:/home/dev/api/.git",
        False,
    )
    assert blocks._card("project:git:/home/dev/api/.git:full") == (
        "project",
        "git:/home/dev/api/.git",
        True,
    )


@pytest.mark.unit
async def test_a_question_carries_exactly_what_was_attached_to_it(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """Nothing travels by default, and what does is named one message at a time.

    The thread is still there and still means something — a page with no JavaScript uses it — but
    a page that can say exactly what to carry says it, and then the call is built from that.
    """
    tab = await desk.create_thread("a subject")
    first = await blocks.submit(desk, "the first question", [], thread_id=tab.id)
    await _settled(desk, first.id)
    second = await blocks.submit(desk, "an unrelated one", [], thread_id=tab.id)
    await _settled(desk, second.id)

    # Attached: exactly the one named.
    assert await blocks._attached(desk, [first.id]) == [("the first question", "an answer")]
    assert await blocks._attached(desk, []) == []
    # A block that never answered carries nothing, rather than carrying half of itself.
    empty = await desk.create_block(
        thread_id=tab.id, kind="question", input="still running", thread_set_by="human"
    )
    assert await blocks._attached(desk, [empty.id]) == []

    # And the thread still holds both, for the page that cannot name anything.
    inherited = await blocks._thread_history(desk, tab.id, exclude=second.id)
    assert [asked for asked, _ in inherited] == ["the first question"]


@pytest.mark.unit
def test_the_prompt_says_which_transcripts_it_was_handed() -> None:
    """A section that only exists when somebody asked for it, so its absence is also a fact."""
    plain = session.build_prompt("what now", board=["- alpha"], history=[])
    assert "in full" not in plain

    with_reading = session.build_prompt(
        "what now", board=["- alpha"], history=[], transcripts=["### alpha", "assistant: hello"]
    )
    assert "## The transcripts you were given, in full" in with_reading
    assert "assistant: hello" in with_reading


@pytest.mark.unit
async def test_a_block_says_what_it_was_sent_with(desk: Store, fake_claude: pathlib.Path) -> None:
    """Written before the run starts, so a block still answering can already be asked.

    "Why did it say that" is a question about the context, and the context was a decision made in
    a second and already forgotten (docs/04-threads-and-blocks.md).
    """
    row = make_row("alpha", "main")
    tab = await desk.create_thread("a subject")
    first = await blocks.submit(desk, "the first question", [row], thread_id=tab.id)
    await _settled(desk, first.id)

    second = await blocks.submit(
        desk,
        "and what about the branch",
        [row],
        thread_id=tab.id,
        targets=["session:session-alpha:full"],
        history=[first.id],
    )
    written = await desk.block(second.id)
    assert written is not None and written.context is not None
    carried = written.context.splitlines()
    assert carried[0].startswith("session · alpha")
    assert "whole transcript" in carried[0]
    assert carried[1] == "earlier · the first question"

    # A question sent with nothing says nothing, rather than saying "nothing".
    bare = await blocks.submit(desk, "on its own", [row], thread_id=tab.id)
    plain = await desk.block(bare.id)
    assert plain is not None and plain.context is None


@pytest.mark.unit
async def test_a_message_can_be_thrown_away(desk: Store, fake_claude: pathlib.Path) -> None:
    """A block never vanishes on its own; this is the other case, and then it goes for real.

    What outlives it is what was captured from it: an idea keeps its text and loses the pointer to
    the message, because the thought is the thing the inbox is for (docs/05-ideas.md).
    """
    block = await blocks.submit(desk, "/idea a thought worth keeping", [])
    await _settled(desk, block.id)
    ideas = await desk.ideas()
    assert [idea.block_id for idea in ideas] == [block.id]

    status, _, _ = await _post(f"/blocks/{block.id}/delete", {}, htmx=True)

    assert status == 200
    assert await desk.block(block.id) is None
    kept = await desk.ideas()
    assert [idea.text for idea in kept] == ["a thought worth keeping"]
    assert kept[0].block_id is None


@pytest.mark.unit
async def test_deleting_a_message_takes_the_run_and_the_prepared_message_with_it(
    desk: Store, kinds: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing should offer to send a message whose reason nobody can see any more."""
    monkeypatch.setenv("KIND", "do")
    block = await blocks.submit(desk, "tell alpha-d0 to test it again", [make_row("alpha", "main")])
    await _settled(desk, block.id)
    assert len(await desk.directives()) == 1

    status, _, _ = await _post(f"/blocks/{block.id}/delete", {}, htmx=True)

    assert status == 200
    assert await desk.directives() == []


# --- drop an idea in and say to take it on --------------------------------------------------------
@pytest.mark.unit
async def test_an_idea_dropped_in_with_take_it_on_starts_an_agent(
    desk: Store, kinds: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both halves have to be present: the run read it as an instruction, and the human pointed at
    the thoughts by dropping their cards in (docs/adr/0006)."""
    from agent_desk import dispatch

    told: list[str] = []
    monkeypatch.setattr(
        dispatch,
        "start",
        lambda instruction, *, cwd, name, env=None: (
            told.append(instruction),
            dispatch.Started(True, agent_id="agent7"),
        )[1],
    )
    monkeypatch.setenv("KIND", "do")
    idea = await desk.create_idea(
        text_="cache the probe results per project", summary="cache probes", source_kind="typed"
    )

    block = await blocks.submit(
        desk, "бери в работу", [make_row("alpha", "main")], targets=[f"idea:{idea.id}"]
    )
    assert await _settled(desk, block.id) == "answered"

    # It started, and what it was told carries the thought as it was written rather than the line
    # that summarises it.
    assert len(told) == 1
    assert "cache the probe results per project" in told[0]
    assert "бери в работу" in told[0]

    after = await desk.block(block.id)
    assert after is not None and "an agent is working on 1 idea" in (after.answer or "")

    # A task holds what it was dispatched for, so the sweep can mark it built when the agent goes.
    (task,) = await desk.tasks()
    assert task.source_ref == idea.id
    assert task.agent_id == "agent7"
    # And nothing is built yet: the agent has not finished.
    assert (await desk.idea(idea.id)).state == "new"  # type: ignore[union-attr]


@pytest.mark.unit
async def test_a_question_never_starts_anything(
    desk: Store, kinds: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kind is what decides, and a question is answered rather than acted on.

    This is the one that has to hold: an instruction now starts an agent on a sentence, and the
    sentence is read by a run that can be wrong. A question misread would be a worktree nobody
    asked for.
    """
    from agent_desk import dispatch

    def never(instruction: str, *, cwd: str, name: str, env: object = None) -> dispatch.Started:
        pytest.fail("a question started an agent")

    monkeypatch.setattr(dispatch, "start", never)
    monkeypatch.setenv("KIND", "question")

    block = await blocks.submit(desk, "what did it end up doing", [make_row("alpha", "main")])
    assert await _settled(desk, block.id) == "answered"

    assert await desk.tasks() == []
    assert await desk.directives() == []


@pytest.mark.unit
async def test_a_second_instruction_waits_for_the_seat_rather_than_taking_another(
    desk: Store, kinds: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two agents in two worktrees of one project, started a minute apart, is the mess
    docs/adr/0007 is careful about. The second one is written down and says it is waiting — a
    request is not done until it is done."""
    from agent_desk import dispatch

    starts: list[str] = []

    def once(instruction: str, *, cwd: str, name: str, env: object = None) -> dispatch.Started:
        starts.append(name)
        return dispatch.Started(True, agent_id=f"agent{len(starts)}")

    monkeypatch.setattr(dispatch, "start", once)
    monkeypatch.setenv("KIND", "do")
    rows = [make_row("alpha", "main")]

    first = await blocks.submit(desk, "tell it to run the tests", rows)
    assert await _settled(desk, first.id) == "answered"
    assert len(starts) == 1

    second = await blocks.submit(desk, "and then check the ports", rows)
    assert await _settled(desk, second.id) == "answered"

    # Nothing else was started, and the block says why rather than claiming it is done.
    assert len(starts) == 1
    after = await desk.block(second.id)
    assert after is not None and "waiting" in (after.answer or "")

    # It is a real line in the queue, and the console offers the one thing that changes it.
    waiting = [task for task in await desk.tasks() if task.waiting]
    assert [task.title for task in waiting] == ["and then check the ports"]
    column = await routes.render_blocks()
    assert "Start it now" in column


@pytest.mark.unit
async def test_a_message_read_as_the_wrong_kind_is_corrected_in_one_click(
    desk: Store, kinds: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run that reads what was typed can be wrong, and what it costs is a worktree.

    So the correction is a button on the block itself: the thought is recorded, and whatever was
    started keeps its own separate button to stop it.
    """
    from agent_desk import dispatch

    monkeypatch.setattr(
        dispatch,
        "start",
        lambda instruction, *, cwd, name, env=None: dispatch.Started(True, agent_id="a1"),
    )
    monkeypatch.setenv("KIND", "do")
    block = await blocks.submit(
        desk, "сделать так, чтобы сервис подключался к любому проекту", [make_row("alpha", "main")]
    )
    assert await _settled(desk, block.id) == "answered"
    assert await desk.ideas() == []

    status, column, _ = await _post(f"/blocks/{block.id}/as-idea", {}, htmx=True)

    assert status == 200
    after = await desk.block(block.id)
    assert after is not None and after.kind == "idea"
    (idea,) = await desk.ideas()
    assert idea.text == "сделать так, чтобы сервис подключался к любому проекту"
    assert "recorded as an idea" in column


@pytest.mark.unit
async def test_a_request_about_the_console_is_done_in_the_console(
    desk: Store, kinds: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Tidy up the ideas" is `do` pointed at this program, and it goes to this program's own
    checkout rather than to a project it watches (docs/04-threads-and-blocks.md)."""
    from agent_desk import dispatch

    told: list[str] = []

    def fake_start(
        instruction: str, *, cwd: str, name: str, env: object = None
    ) -> dispatch.Started:
        told.append(cwd)
        return dispatch.Started(True, agent_id="desk1")

    monkeypatch.setattr(dispatch, "start", fake_start)
    monkeypatch.setenv("KIND", "desk")

    block = await blocks.submit(desk, "разгреби текущие идеи", [make_row("alpha", "main")])
    assert await _settled(desk, block.id) == "answered"

    after = await desk.block(block.id)
    assert after is not None and after.kind == "master"
    # Its own checkout, not the session that happened to be on the board.
    assert told == [str(blocks.own_checkout())]
    assert "/projects/alpha" not in told[0]

    (task,) = await desk.tasks()
    assert task.repo_key.startswith("desk:")


@pytest.mark.unit
async def test_a_request_about_a_console_whose_code_is_elsewhere_is_written_down(
    desk: Store, kinds: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An installed copy with no source beside it has nothing to start, and saying so is the only
    honest answer available."""
    from agent_desk import dispatch

    monkeypatch.setattr(
        dispatch,
        "start",
        lambda instruction, *, cwd, name, env=None: pytest.fail("there was nothing to run"),
    )
    monkeypatch.setattr(blocks, "own_checkout", lambda: pathlib.Path("/not/a/checkout"))
    monkeypatch.setenv("KIND", "desk")

    block = await blocks.submit(desk, "убери эту колонку", [])
    assert await _settled(desk, block.id) == "answered"

    after = await desk.block(block.id)
    assert after is not None
    assert "not on this machine" in (after.answer or "")
    # And the thought is kept rather than lost.
    assert [idea.text for idea in await desk.ideas()] == ["убери эту колонку"]


@pytest.mark.unit
async def test_a_chat_takes_the_name_of_the_first_thing_said_in_it(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """ "chat 4" tells nobody which tab held the migration conversation."""
    chat = await desk.create_thread("chat 3")

    await blocks.submit(desk, "what did the migration end up doing", [], thread_id=chat.id)

    renamed = next(one for one in await desk.open_threads() if one.id == chat.id)
    assert renamed.subject == "what did the migration end up doing"

    # And a chat that already has a name keeps it.
    await blocks.submit(desk, "and what about the ports", [], thread_id=chat.id)
    again = next(one for one in await desk.open_threads() if one.id == chat.id)
    assert again.subject == "what did the migration end up doing"


@pytest.mark.unit
async def test_a_desk_agent_is_given_the_facts_and_the_tokens_it_needs(
    desk: Store, kinds: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Write documentation for all the ideas" cannot be done by an agent that has to guess what
    the ideas are, and handing it the database would be handing it a file it has no business
    opening. The facts travel in the prompt; the tokens travel in the environment."""
    from agent_desk import dispatch
    from agent_desk import secrets as kept

    seen: dict[str, object] = {}

    def fake_start(
        instruction: str, *, cwd: str, name: str, env: object = None
    ) -> dispatch.Started:
        seen.update(instruction=instruction, env=env)
        return dispatch.Started(True, agent_id="desk9")

    monkeypatch.setattr(dispatch, "start", fake_start)
    monkeypatch.setenv("KIND", "desk")
    await desk.set_link(
        repo_key="origin:acme/api",
        name="jira",
        url="https://acme.atlassian.net/browse/API",
        token_env="DESK_TEST_JIRA",
    )
    kept.keep("DESK_TEST_JIRA", "a-real-looking-secret")
    await desk.create_idea(
        text_="cache the probe results",
        summary="cache probes",
        source_kind="typed",
        project_key="origin:acme/api",
    )

    try:
        block = await blocks.submit(desk, "составь доки на все идеи", [])
        assert await _settled(desk, block.id) == "answered"
    finally:
        kept.forget("DESK_TEST_JIRA")

    # The thoughts, and which project each is about.
    assert "cache the probe results" in str(seen["instruction"])
    assert "origin:acme/api" in str(seen["instruction"])
    # The token, in the environment, and named on the block rather than hidden.
    assert seen["env"] == {"DESK_TEST_JIRA": "a-real-looking-secret"}
    after = await desk.block(block.id)
    assert after is not None and "DESK_TEST_JIRA" in (after.answer or "")
    # And what it holds is never written into the prompt.
    assert "a-real-looking-secret" not in str(seen["instruction"])


@pytest.mark.unit
async def test_an_idea_typed_with_nothing_in_front_of_it_is_about_the_desk(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """A thought typed with nothing on the workbench is about the thing in front of you."""
    await blocks.submit(desk, "/idea the pool needs sorting", [])
    (idea,) = await desk.ideas()
    assert idea.project_key == blocks.desk_key()

    # With a card on the workbench it is about that card's project, as the board stamped it.
    stamped = replace(make_row("alpha", "main"), project_key="origin:acme/api")
    await blocks.submit(desk, "/idea the api half is slow", [stamped])
    newest = (await desk.ideas())[0]
    assert newest.project_key == "origin:acme/api"


@pytest.mark.unit
async def test_a_block_somebody_wrote_on_the_bench_travels_with_the_message(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """ "Блок может содержать ссылки/документы/просто текст или кусок кода." It is text rather than
    a card this console read, so it is carried as text and named as the person's own — which is
    the difference an agent needs in order to weigh it."""
    block = await blocks.submit(
        desk,
        "what do you make of this",
        [],
        notes_="  https://example.com/spec\n\ndef broken():\n    return None  ",
    )

    stored = await desk.block(block.id)
    assert stored is not None
    assert stored.context is not None
    assert "what they wrote on the workbench" in stored.context
    assert "https://example.com/spec" in stored.context
    assert "def broken()" in stored.context


@pytest.mark.unit
async def test_an_empty_block_carries_nothing(desk: Store, fake_claude: pathlib.Path) -> None:
    """A block somebody added and never typed into is not context."""
    block = await blocks.submit(desk, "a question", [], notes_="   \n  ")

    stored = await desk.block(block.id)
    assert stored is not None
    assert "workbench" not in (stored.context or "")
