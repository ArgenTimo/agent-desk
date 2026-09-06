"""The routes added after Phase 4: projects, instances, the queue, the arming, the agents.

Every one of these is a button somebody presses, and most of them start or stop something. The
tests are shaped around the two questions that matter for such a route: does the thing it claims
to do happen, and does it refuse cleanly when it cannot.

`dispatch` is replaced everywhere here. A test that reached the real one would start a background
agent on this machine, which is the sort of thing a test suite must never do by accident.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import pytest
from agent_desk import dispatch
from agent_desk.config import Settings
from agent_desk.observe import registry, transcript
from agent_desk.store.repo import Store
from agent_desk.web import autostart, routes, sse

from tests.unit.test_board import Home, _entry


@pytest.fixture
def home(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Home:
    """A fake `~/.claude` with one live session, wired into every module that reads a path."""
    fake = Settings(
        claude_home=tmp_path / "claude",
        data_dir=tmp_path / "data",
        registry_poll_seconds=0.0,
        idle_hint_seconds=300,
    )
    for module in (registry, transcript, routes, sse):
        monkeypatch.setattr(module, "settings", fake)
    return Home(tmp_path / "claude")


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Every dispatch this test made, and none of them left the process."""
    calls: list[dict[str, str]] = []

    def fake_start(
        instruction: str, *, cwd: str, name: str, env: object = None
    ) -> dispatch.Started:
        calls.append({"instruction": instruction, "cwd": cwd, "name": name})
        return dispatch.Started(True, agent_id=f"agent{len(calls)}")

    def fake_stop(agent_id: str) -> dispatch.Started:
        calls.append({"stopped": agent_id})
        return dispatch.Started(True, agent_id=agent_id)

    monkeypatch.setattr(dispatch, "start", fake_start)
    monkeypatch.setattr(dispatch, "stop", fake_stop)
    return calls


async def _get(path: str) -> tuple[int, str]:
    from tests.unit.test_board import _request

    return await _request(path, "127.0.0.1")


async def _post(path: str, fields: dict[str, str] | None = None) -> tuple[int, str]:
    from tests.unit.test_input import _post as post_form

    status, body, _ = await post_form(path, fields or {}, htmx=True)
    return status, body


def _a_session(home: Home) -> str:
    import os
    import time

    now = int(time.time() * 1000)
    session_id = "aaaaaaaa-0000-4000-8000-000000000001"
    home.session(os.getpid(), session_id, cwd=str(home.root.parent), updatedAt=now)
    home.transcript(session_id, _entry("assistant", "doing something"))
    return session_id


async def _the_project(home: Home) -> str:
    """The repository key of the one project on the board."""
    _a_session(home)
    rows, _ = routes.board()
    projects = routes.shape(rows, await routes.store.groups())
    return projects[0].key


# --- a project's own page and its menu ------------------------------------------------------------
@pytest.mark.unit
async def test_a_project_has_a_page_of_its_own(home: Home, desk: Store) -> None:
    key = await _the_project(home)

    status, body = await _get(f"/projects/page?key={urlencode({'k': key})[2:]}")

    assert status == 200
    assert "work queued here" in body
    assert "environment this project expects" in body
    # A page, not a fragment: it has to stand on its own on a second screen.
    assert "<!doctype html>" in body.lower()


@pytest.mark.unit
async def test_the_environment_a_project_expects_is_names_and_never_values(
    home: Home, desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/07-security.md: this file has no encryption and a second application reads out of it."""
    key = await _the_project(home)
    monkeypatch.setenv("DESK_TEST_URL", "postgres://not-in-the-database")

    status, panel = await _post(
        "/project-env", {"key": key, "name": "DESK_TEST_URL", "note": "where the data is"}
    )

    assert status == 200
    assert "DESK_TEST_URL" in panel
    assert "set here" in panel
    assert "postgres://" not in panel
    (named,) = await desk.env(key)
    assert named.name == "DESK_TEST_URL"
    assert named.note == "where the data is"

    status, panel = await _post(
        "/project-env", {"key": key, "name": "DESK_TEST_URL", "remove": "yes"}
    )
    assert status == 200
    assert await desk.env(key) == []


# --- new instances --------------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_new_instance_is_offered_before_it_is_made(home: Home, desk: Store) -> None:
    key = await _the_project(home)

    status, panel = await _get(f"/projects/instance?key={key}")

    assert status == 200
    assert "new instance in" in panel
    assert "Create it" in panel


@pytest.mark.unit
async def test_a_new_instance_starts_an_agent_that_reads_before_it_writes(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    """It is a new pair of hands in a repository nobody has introduced it to (docs/adr/0006)."""
    key = await _the_project(home)
    await desk.set_env(repo_key=key, name="DESK_NEEDS_THIS")

    status, panel = await _post(
        "/projects/instance", {"key": key, "name": "biba", "doing": "the api half"}
    )

    assert status == 200
    assert "biba is set up" in panel
    assert "agent1" in panel

    (call,) = started
    assert call["name"] == "biba"
    assert "You are biba" in call["instruction"]
    assert "Start by reading" in call["instruction"]
    assert "the api half" in call["instruction"]
    # It is told what the project expects, by name, and told to check rather than assume.
    assert "DESK_NEEDS_THIS" in call["instruction"]


@pytest.mark.unit
async def test_an_instance_in_a_project_that_is_not_here_says_so(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    status, panel = await _post("/projects/instance", {"key": "origin:nobody/nothing"})

    assert status == 200
    assert "no checkout on this machine" in panel
    assert started == []


# --- the queue and the arming ---------------------------------------------------------------------
@pytest.mark.unit
async def test_work_is_queued_started_and_dropped_by_the_buttons_that_say_so(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    key = await _the_project(home)

    status, panel = await _post("/tasks", {"key": key, "instruction": "check the ports"})
    assert status == 200
    assert "check the ports" in panel
    (task,) = await desk.tasks()
    assert task.waiting

    status, panel = await _post(f"/tasks/{task.id}/start", {"key": key})
    assert status == 200
    assert len(started) == 1
    after = next(one for one in await desk.tasks() if one.id == task.id)
    assert after.agent_id == "agent1"

    status, panel = await _post(f"/tasks/{task.id}/drop", {"key": key})
    assert status == 200
    assert await desk.tasks() == []


@pytest.mark.unit
async def test_a_failed_task_goes_back_in_the_queue_only_when_asked(
    home: Home, desk: Store
) -> None:
    """Nothing retries by itself: a task that failed stays failed and says why (docs/adr/0007)."""
    key = await _the_project(home)
    task = await desk.queue_task(
        repo_key=key,
        cwd=str(home.root),
        title="check the ports",
        instruction="check the ports",
        source_kind="typed",
    )
    await desk.take_next_task(key)
    await desk.task_failed(task.id, "no disk space")

    status, panel = await _post(f"/tasks/{task.id}/retry", {"key": key})

    assert status == 200
    waiting = [one for one in await desk.tasks() if one.waiting]
    assert [one.title for one in waiting] == ["check the ports"]


@pytest.mark.unit
async def test_an_action_the_queue_does_not_have_is_not_a_shrug(home: Home, desk: Store) -> None:
    status, _ = await _post("/tasks/whatever/explode", {"key": "k"})
    assert status == 404


@pytest.mark.unit
async def test_arming_and_disarming_a_project_says_what_it_will_do(home: Home, desk: Store) -> None:
    key = await _the_project(home)

    status, panel = await _post("/autostart", {"key": key, "armed": "yes", "per_hour": "3"})
    assert status == 200
    assert "Armed" in panel
    assert (await desk.autostart(key)).per_hour == 3

    status, panel = await _post("/autostart", {"key": key, "armed": "no"})
    assert status == 200
    assert "Nothing here starts without you" in panel
    assert (await desk.autostart(key)).armed is False


@pytest.mark.unit
async def test_a_budget_that_is_not_a_number_falls_back_rather_than_failing(
    home: Home, desk: Store
) -> None:
    key = await _the_project(home)

    status, _ = await _post("/autostart", {"key": key, "armed": "yes", "per_hour": "lots"})

    assert status == 200
    assert (await desk.autostart(key)).per_hour == 2


# --- agents ----------------------------------------------------------------------------------------
@pytest.mark.unit
async def test_stopping_an_agent_frees_the_seat_it_was_holding(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    key = await _the_project(home)
    task = await desk.queue_task(
        repo_key=key, cwd=str(home.root), title="one", instruction="one", source_kind="typed"
    )
    await desk.take_next_task(key)
    await desk.task_started(task.id, "agent9")

    status, panel = await _post("/agents/agent9/stop", {})

    assert status == 200
    assert "was stopped" in panel
    assert started == [{"stopped": "agent9"}]
    settled = next(one for one in await desk.tasks() if one.id == task.id)
    assert settled.finished_at is not None
    # The seat is free again: with the project armed, the only thing left to say is that the
    # queue is empty.
    await desk.arm(key, per_hour=2)
    assert await autostart.why_not(desk, key, live=set()) == "nothing is queued"


@pytest.mark.unit
async def test_an_agent_that_will_not_stop_says_what_came_back(
    home: Home, desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dispatch, "stop", lambda agent_id: dispatch.Started(False, detail="no such session")
    )

    status, panel = await _post("/agents/nope/stop", {})

    assert status == 200
    assert "would not stop" in panel
    assert "no such session" in panel


@pytest.mark.unit
async def test_dispatching_from_a_session_card_starts_work_in_its_checkout(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    session_id = _a_session(home)

    status, panel = await _post(f"/sessions/{session_id}/dispatch", {"text": "run the tests again"})

    assert status == 200
    assert "an agent is on it" in panel
    (call,) = started
    assert "run the tests again" in call["instruction"]
    assert call["cwd"] == str(home.root.parent)


@pytest.mark.unit
async def test_dispatching_at_a_session_that_has_gone_says_so(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    status, panel = await _post("/sessions/no-such-session/dispatch", {"text": "do it"})

    assert status == 200
    assert "not on the board any more" in panel
    assert started == []


# --- ideas, from the other side ---------------------------------------------------------------------
@pytest.mark.unit
async def test_implementing_the_ideas_a_message_is_about(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    await _the_project(home)
    idea = await desk.create_idea(
        text_="cache the probe results", summary="cache probes", source_kind="typed"
    )
    block = await desk.create_block(
        thread_id=(await desk.create_thread("s")).id,
        kind="instruction",
        input="do the caching thing",
        thread_set_by="human",
    )
    await desk.link_block_ideas(block.id, [idea.id])

    status, panel = await _post(f"/blocks/{block.id}/implement", {})

    assert status == 200
    assert "an agent is on it" in panel
    (call,) = started
    # The thought as it was written, not the line that summarises it.
    assert "cache the probe results" in call["instruction"]
    (task,) = await desk.tasks()
    assert task.source_ref == idea.id
    assert task.block_id == block.id


@pytest.mark.unit
async def test_implementing_nothing_is_refused_rather_than_started(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    block = await desk.create_block(
        thread_id=(await desk.create_thread("s")).id,
        kind="question",
        input="what is happening",
        thread_set_by="human",
    )

    status, panel = await _post(f"/blocks/{block.id}/implement", {})

    assert status == 200
    assert "nothing here to build" in panel
    assert started == []


@pytest.mark.unit
async def test_grouping_an_idea_under_another_and_taking_it_back_out(
    home: Home, desk: Store
) -> None:
    parent = await desk.create_idea(text_="the whole", summary="the whole", source_kind="typed")
    child = await desk.create_idea(text_="a part", summary="a part", source_kind="typed")

    status, column = await _post(f"/ideas/{child.id}/parent", {"parent": parent.id})
    assert status == 200
    assert (await desk.idea(child.id)).parent_id == parent.id  # type: ignore[union-attr]

    status, column = await _post(f"/ideas/{child.id}/parent", {"parent": ""})
    assert status == 200
    assert (await desk.idea(child.id)).parent_id is None  # type: ignore[union-attr]


@pytest.mark.unit
async def test_an_idea_is_a_card_that_opens_on_the_workbench(home: Home, desk: Store) -> None:
    idea = await desk.create_idea(
        text_="cache the probe results per project",
        summary="cache probes",
        source_kind="typed",
        context={"project": "alpha"},
    )

    status, card = await _get(f"/cards/idea?id={idea.id}")
    assert status == 200
    assert "cache the probe results per project" in card
    assert "alpha" in card

    status, card = await _get("/cards/idea?id=no-such-idea")
    assert status == 404
    assert "not in the inbox any more" in card


# --- chats ------------------------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_chat_is_opened_and_closed_and_the_last_one_stays(home: Home, desk: Store) -> None:
    """An interaction area with no tab has nowhere to put an answer."""
    first = await routes.open_chats()
    assert len(first) == 1

    status, tabs = await _post("/threads", {})
    assert status == 200
    assert tabs.count("data-thread=") == 2

    (newest,) = [thread for thread in await routes.open_chats() if thread.id != first[0].id]
    status, tabs = await _post(f"/threads/{newest.id}/close", {})
    assert status == 200
    assert tabs.count("data-thread=") == 1

    # The last one cannot be closed: there would be nowhere to put an answer.
    status, tabs = await _post(f"/threads/{first[0].id}/close", {})
    assert status == 200
    assert tabs.count("data-thread=") == 1


# --- links, projects, and the one write path's neighbours -------------------------------------------
@pytest.mark.unit
async def test_a_link_is_added_and_removed_and_only_a_real_address_is_kept(
    home: Home, desk: Store
) -> None:
    key = await _the_project(home)

    status, panel = await _post(
        "/project-links",
        {
            "key": key,
            "name": "jira",
            "url": "https://acme.atlassian.net/browse/API",
            "token_env": "ACME_JIRA",
        },
    )
    assert status == 200
    assert "acme.atlassian.net" in panel
    (link,) = await desk.links(key)
    assert link.token_env == "ACME_JIRA"

    # Not an address: nothing is stored, and the panel comes back unchanged rather than erroring.
    status, _ = await _post("/project-links", {"key": key, "name": "bad", "url": "javascript:x"})
    assert status == 200
    assert [one.name for one in await desk.links(key)] == ["jira"]

    status, panel = await _post("/project-links/remove", {"key": key, "name": "jira"})
    assert status == 200
    assert await desk.links(key) == []


@pytest.mark.unit
async def test_a_project_is_declared_dissolved_and_carries_its_first_member(
    home: Home, desk: Store
) -> None:
    key = await _the_project(home)

    status, board = await _post("/projects", {"name": "one product", "repo_key": key})
    assert status == 200
    assert "one product" in board
    (group,) = await desk.groups()
    assert list(group.repo_keys) == [key]

    status, board = await _post(f"/projects/{group.id}/dissolve", {})
    assert status == 200
    assert await desk.groups() == []


@pytest.mark.unit
async def test_dispatching_a_directive_once_and_then_not_again(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    """Twice is two agents in two worktrees editing one repository."""
    session_id = _a_session(home)
    block = await desk.create_block(
        thread_id=(await desk.create_thread("s")).id,
        kind="instruction",
        input="run the tests",
        thread_set_by="human",
    )
    directive = await desk.record_directive(
        block_id=block.id, session_id=session_id, session_name="alpha", text_="run the tests"
    )

    status, panel = await _post(f"/directives/{directive.id}/dispatch", {})
    assert status == 200
    assert "an agent is on it" in panel
    assert len(started) == 1

    status, _ = await _post(f"/directives/{directive.id}/dispatch", {})
    assert status == 200
    assert len(started) == 1

    status, _ = await _post("/directives/no-such-directive/dispatch", {})
    assert status == 404


@pytest.mark.unit
async def test_a_directive_whose_session_has_gone_starts_nothing(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    block = await desk.create_block(
        thread_id=(await desk.create_thread("s")).id,
        kind="instruction",
        input="run the tests",
        thread_set_by="human",
    )
    directive = await desk.record_directive(
        block_id=block.id, session_id="gone", session_name="gone", text_="run the tests"
    )

    status, panel = await _post(f"/directives/{directive.id}/dispatch", {})

    assert status == 200
    assert "not on the board any more" in panel
    assert started == []


# --- and all of it without JavaScript ----------------------------------------------------------
@pytest.mark.unit
async def test_every_control_still_works_with_no_javascript_at_all(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    """htmx upgrades this console; it does not enable it (docs/06-console.md).

    Each of these posts arrives without the header htmx sends, which is what a browser with no
    script does. The answer must be a whole page or a redirect to one — never a fragment somebody
    would see on its own, and never a 500.
    """
    from tests.unit.test_input import _post as post_form

    key = await _the_project(home)
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    task = await desk.queue_task(
        repo_key=key, cwd=str(home.root), title="one", instruction="one", source_kind="typed"
    )
    thread = await desk.create_thread("chat 1")
    await desk.create_thread("chat 2")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="what now", thread_set_by="human"
    )

    plain = [
        ("/threads", {}),
        (f"/threads/{thread.id}/close", {}),
        ("/projects", {"name": "one product"}),
        ("/project-links", {"key": key, "name": "jira", "url": "https://example.invalid/browse/A"}),
        ("/project-links/remove", {"key": key, "name": "jira"}),
        ("/project-env", {"key": key, "name": "SOME_VAR"}),
        ("/tasks", {"key": key, "instruction": "check the ports"}),
        (f"/tasks/{task.id}/drop", {"key": key}),
        ("/autostart", {"key": key, "armed": "yes", "per_hour": "2"}),
        ("/projects/instance", {"key": key, "name": "biba"}),
        ("/agents/agent1/stop", {}),
        (f"/ideas/{idea.id}/keep", {}),
        (f"/ideas/{idea.id}/parent", {"parent": ""}),
        (f"/blocks/{block.id}/as-idea", {}),
        (f"/blocks/{block.id}/implement", {}),
        (f"/sessions/{_a_session(home)}/dispatch", {"text": "do it"}),
    ]

    for path, fields in plain:
        status, body, headers = await post_form(path, fields, htmx=False)
        assert status in (200, 303), f"{path} answered {status}"
        if status == 303:
            assert headers["location"].startswith("/"), path
        else:
            assert "<!doctype html>" in body.lower(), f"{path} answered a fragment"


@pytest.mark.unit
async def test_a_card_dropped_on_a_project_joins_it(home: Home, desk: Store) -> None:
    """The other half of declaring a project: dragging a repository into one that exists."""
    key = await _the_project(home)
    group = await desk.create_group("one product")

    status, board = await _post(f"/projects/{group.id}/members", {"repo_key": key})

    assert status == 200
    assert "one product" in board
    (declared,) = await desk.groups()
    assert list(declared.repo_keys) == [key]


@pytest.mark.unit
async def test_a_viewer_link_is_minted_once_and_shown_once(home: Home, desk: Store) -> None:
    """A refresh must not mint a second credential for the same person (docs/07-security.md)."""
    from tests.unit.test_input import _post as post_form

    status, _, headers = await post_form("/viewers", {"name": "a teammate"}, htmx=False)
    assert status == 303
    shown = headers["location"]
    assert shown.startswith("/viewers?shown=")
    (viewer,) = await desk.viewers()

    status, page = await _get(shown)
    assert status == 200
    assert "a teammate" in page
    # Shown once: the slot is emptied by the render that used it.
    status, again = await _get(shown)
    assert status == 200
    assert page != again

    status, _, _ = await post_form(f"/viewers/{viewer.id}/revoke", {}, htmx=False)
    assert status == 303
    (revoked,) = await desk.viewers()
    assert revoked.revoked_at is not None

    # A name is required: nothing is minted for an empty one.
    status, _, headers = await post_form("/viewers", {"name": "  "}, htmx=False)
    assert status == 303
    assert len(await desk.viewers()) == 1


@pytest.mark.unit
async def test_the_write_path_panel_opens_on_a_full_page_too(home: Home, desk: Store) -> None:
    session_id = _a_session(home)

    status, page = await _get(f"/sessions/{session_id}/message")

    assert status == 200
    assert "<!doctype html>" in page.lower()
    assert "message to" in page


@pytest.mark.unit
async def test_filing_a_ticket_answers_a_page_when_the_browser_has_no_script(
    home: Home, desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_input import _post as post_form

    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    await desk.set_idea_state(idea.id, "kept")
    await desk.create_draft(idea_id=idea.id, kind="ticket", body="A thought")

    # No destination configured: the panel says which step is missing, on a whole page.
    status, page = await _get(f"/ideas/{idea.id}/file")
    assert status == 200
    assert "<!doctype html>" in page.lower()
    assert "no project has a Jira link" in page

    status, page, _ = await post_form(f"/ideas/{idea.id}/file", {}, htmx=False)
    assert status == 200
    assert "<!doctype html>" in page.lower()


# --- the board as a file, and what a project has got through ---------------------------------------
@pytest.mark.unit
async def test_the_board_can_be_taken_away_as_a_spreadsheet(home: Home, desk: Store) -> None:
    """ "How much of last week was that session" is a spreadsheet question, and a console that
    refuses to hand over its rows makes somebody screenshot them."""
    _a_session(home)

    status, body = await _get("/board.csv")

    assert status == 200
    lines = body.strip().splitlines()
    assert lines[0].startswith("project,checkout,session,name,status,kind,branch,context_tokens")
    assert len(lines) == 2
    assert "aaaaaaaa-0000-4000-8000-000000000001" in lines[1]
    # Nothing inferred: the flag is a guess and guesses do not belong in a column somebody sums.
    assert "may want you" not in body
    assert "waiting" not in lines[0]


@pytest.mark.unit
async def test_a_project_card_counts_what_this_console_started(home: Home, desk: Store) -> None:
    key = await _the_project(home)
    waiting = await desk.queue_task(
        repo_key=key, cwd=str(home.root), title="one", instruction="one", source_kind="typed"
    )
    running = await desk.queue_task(
        repo_key=key, cwd=str(home.root), title="two", instruction="two", source_kind="typed"
    )
    await desk.take_next_task(key)  # claims "one"
    await desk.task_started(waiting.id, "agent1")
    await desk.take_next_task(key)  # claims "two"
    await desk.task_started(running.id, "agent2")
    await desk.finish_task(running.id)

    counted = await routes.board_work()

    assert counted[key] == {"waiting": 0, "running": 1, "done": 1, "stuck": 0}
    board = await asyncio.to_thread(
        routes.render_board, await desk.groups(), await routes.board_links(), counted
    )
    assert "1/0/1" in board

    # And the same work counted against the agent that did it, which is what a session card shows:
    # "показывать к-во закрытых и заблокированных задач у каждой сессии/агента".
    assert counted["agent1"] == {"waiting": 0, "running": 1, "done": 0, "stuck": 0}
    assert counted["agent2"] == {"waiting": 0, "running": 0, "done": 1, "stuck": 0}


@pytest.mark.unit
async def test_what_is_stuck_is_counted_apart_from_what_is_running(home: Home, desk: Store) -> None:
    """ "Закрытых и заблокированных" — a failed task and a running one are not the same news, and a
    card that added them together would say a project is busy when it is stuck."""
    key = await _the_project(home)
    fell_over = await desk.queue_task(
        repo_key=key, cwd=str(home.root), title="one", instruction="one", source_kind="typed"
    )
    await desk.take_next_task(key)
    await desk.task_started(fell_over.id, "agent9")
    await desk.task_failed(fell_over.id, "it fell over")
    await desk.replace_tracker_blockers(key, [("DUCK-3", "the import", "Blocked on a vendor.")])

    counted = await routes.board_work()

    # One failed task and one ticket that says it is blocked.
    assert counted[key]["stuck"] == 2
    assert counted[key]["running"] == 0
    assert counted["agent9"]["stuck"] == 1

    board = await asyncio.to_thread(
        routes.render_board, await desk.groups(), await routes.board_links(), counted
    )
    assert "stuck" in board


@pytest.mark.unit
async def test_the_second_switch_says_what_it_will_do_before_it_is_pressed(
    home: Home, desk: Store
) -> None:
    """docs/adr/0008: what it authorises is a machine deciding what is worth doing, so the page
    says so in a sentence and the queue marks everything it produces."""
    key = await _the_project(home)

    status, panel = await _post("/explore", {"key": key, "exploring": "yes", "per_day": "2"})
    assert status == 200
    assert "Exploring:" in panel
    assert "It fixes; it does not design, and it never merges." in panel
    arming = await desk.autostart(key)
    assert arming.exploring is True
    assert arming.per_day == 2
    # Two switches, two decisions: this one did not arm the queue.
    assert arming.armed is False

    status, panel = await _post("/explore", {"key": key, "exploring": "no"})
    assert status == 200
    assert "It starts only what you put in the queue." in panel
    assert (await desk.autostart(key)).exploring is False

    # A budget that is not a number falls back rather than failing.
    status, _ = await _post("/explore", {"key": key, "exploring": "yes", "per_day": "lots"})
    assert (await desk.autostart(key)).per_day == 3


@pytest.mark.unit
async def test_work_an_agent_found_is_marked_as_its_own_in_the_queue(
    home: Home, desk: Store
) -> None:
    key = await _the_project(home)
    await desk.queue_task(
        repo_key=key,
        cwd=str(home.root),
        title="looking for something to fix",
        instruction="go and look",
        source_kind="found",
    )

    panel = await routes.render_project(key)

    assert "found by an agent" in panel


@pytest.mark.unit
async def test_the_switch_records_where_the_project_is(home: Home, desk: Store) -> None:
    """An exploration is the first task in a project and has no earlier one to take a directory
    from, so the panel that knows which project the button belongs to writes it down."""
    key = await _the_project(home)

    await _post("/explore", {"key": key, "exploring": "yes", "per_day": "2"})

    arming = await desk.autostart(key)
    assert arming.cwd == str(home.root.parent)
    assert await autostart.why_not_explore(desk, key, live=set()) == ""


@pytest.mark.unit
async def test_the_switch_that_will_not_let_a_session_idle_says_what_it_does(
    home: Home, desk: Store
) -> None:
    """docs/adr/0009: this is the explicit click docs/adr/0002 requires, and what it buys is a
    standing permission — so the button says so before it is pressed."""
    import os
    import time

    session_id = "bbbbbbbb-0000-4000-8000-000000000002"
    home.session(
        os.getpid(),
        session_id,
        cwd=str(home.root.parent),
        kind="bg",
        status="idle",
        updatedAt=int(time.time() * 1000),
    )

    board = await asyncio.to_thread(
        routes.render_board, await desk.groups(), {}, {}, await routes.board_kicks()
    )
    assert "don&#39;t let it idle" in board or "don't let it idle" in board

    status, _ = await _post(f"/sessions/{session_id}/kicking", {"kicking": "yes"})
    assert status == 200
    arming = await desk.kicking("bbbbbbbb")
    assert arming.armed
    # Recorded when the button is pressed, because a kick stops the session first and a stopped
    # session has no registry entry to read them back from.
    assert arming.session_id == session_id
    assert arming.cwd == str(home.root.parent)

    board = await asyncio.to_thread(
        routes.render_board, await desk.groups(), {}, {}, await routes.board_kicks()
    )
    assert "keeping it going" in board

    status, _ = await _post(f"/sessions/{session_id}/kicking", {"kicking": "no"})
    assert status == 200
    assert not (await desk.kicking("bbbbbbbb")).armed


@pytest.mark.unit
async def test_a_terminal_session_is_offered_no_button_and_told_why(
    home: Home, desk: Store
) -> None:
    """A button that would lie is worse than a sentence that explains (docs/adr/0009)."""
    _a_session(home)  # the fixture's session is interactive

    board = await asyncio.to_thread(
        routes.render_board, await desk.groups(), {}, {}, await routes.board_kicks()
    )

    assert "cannot be continued from here" in board
    assert "let it idle" not in board


@pytest.mark.unit
async def test_switching_one_off_works_for_a_session_that_has_since_gone(desk: Store) -> None:
    """Otherwise the row stays armed forever and the loop keeps saying it is not running."""
    gone = "cccccccc-0000-4000-8000-000000000003"
    await desk.kick_session("cccccccc", on=True, session_id=gone, cwd="/somewhere")

    status, _ = await _post(f"/sessions/{gone}/kicking", {"kicking": "no"})

    assert status == 200
    assert not (await desk.kicking("cccccccc")).armed


@pytest.mark.unit
async def test_a_whole_project_can_be_told_not_to_idle_one_session_at_a_time(
    home: Home, desk: Store
) -> None:
    """docs/adr/0009: "all of them" is a click repeated, not a wider switch — so this writes the
    same per-session rows the card's own button writes."""
    import os
    import time

    now = int(time.time() * 1000)
    background = "dddddddd-0000-4000-8000-000000000004"
    # A different pid: the registry is one file per pid, and the fixture's own session takes
    # os.getpid().
    home.session(os.getppid(), background, cwd=str(home.root.parent), kind="bg", updatedAt=now)
    terminal = _a_session(home)
    key = await _the_project(home)

    status, _ = await _post("/projects/kicking", {"key": key, "kicking": "yes"})

    assert status == 200
    assert (await desk.kicking("dddddddd")).armed
    # And the one in a terminal is left out: there is no door into it (docs/adr/0009).
    assert not (await desk.kicking(terminal.split("-")[0])).armed

    status, _ = await _post("/projects/kicking", {"key": key, "kicking": "no"})
    assert status == 200
    assert not (await desk.kicking("dddddddd")).armed


@pytest.mark.unit
async def test_the_ideas_column_can_be_ordered_and_the_choice_survives_a_push(
    home: Home, desk: Store
) -> None:
    """Sixty ideas are not read from the end, they are searched. The choice lives in the store
    because a server-sent event replaces this column every couple of seconds."""
    first = await desk.create_idea(text_="the older one", summary="older", source_kind="typed")
    await desk.set_idea_project(first.id, "b:project")
    second = await desk.create_idea(text_="the newer one", summary="newer", source_kind="typed")
    await desk.set_idea_project(second.id, "a:project")

    # The order of the *cards*, not of the words: every card carries a select naming every other
    # idea, so an index of the summary text says nothing about which card came first.
    def order(html: str) -> list[str]:
        return [one.split('"')[0] for one in html.split('data-kind="idea" data-id="')[1:]]

    # Newest first without anybody choosing.
    assert order(await routes.render_ideas()) == [second.id, first.id]

    status, column = await _post("/ideas/sort", {"how": "oldest"})
    assert status == 200
    assert order(column) == [first.id, second.id]
    # And it is still that way on the next push, which is what a query parameter could not do.
    assert order(await routes.render_ideas()) == [first.id, second.id]

    status, column = await _post("/ideas/sort", {"how": "project"})
    assert order(column) == [second.id, first.id]  # a:project before b:project

    # A sort nobody offers changes nothing rather than raising.
    await _post("/ideas/sort", {"how": "by vibes"})
    assert await desk.setting(routes.IDEA_SORT_KEY) == "project"


@pytest.mark.unit
async def test_an_idle_row_says_why_it_is_idle_when_the_console_knows(
    home: Home, desk: Store
) -> None:
    """Not an inference: this console tried to continue the session and the account said there
    was nothing left to spend, so the time on the card is the one it was given."""
    import os
    import time

    now = int(time.time() * 1000)
    session_id = "eeeeeeee-0000-4000-8000-000000000005"
    home.session(os.getpid(), session_id, cwd=str(home.root.parent), kind="bg", updatedAt=now)
    await desk.kick_session("eeeeeeee", on=True, session_id=session_id, cwd="/somewhere")

    # Before: it is just idle, and the board says only what the registry says.
    board = await asyncio.to_thread(
        routes.render_board, await desk.groups(), {}, {}, await routes.board_kicks()
    )
    assert "having a smoke" in board
    assert "on a break" not in board

    await desk.kick_waits_until("eeeeeeee", now + 30 * 60 * 1000)

    board = await asyncio.to_thread(
        routes.render_board, await desk.groups(), {}, {}, await routes.board_kicks()
    )
    assert "on a break until" in board
    assert "having a smoke" not in board


@pytest.mark.unit
async def test_what_anybody_working_here_should_know_reaches_every_agent(
    home: Home, desk: Store, started: list[dict[str, str]]
) -> None:
    """The second entity next to the ideas. An idea is a thing somebody had and will one day be
    built; this is a thing that is simply true and never will be — so it goes into the briefing
    rather than into the pool."""
    key = await _the_project(home)

    status, panel = await _post(
        "/project-note", {"key": key, "note": "  We never add a build step here.  "}
    )
    assert status == 200
    assert "We never add a build step here." in panel
    assert await desk.project_note(key) == "We never add a build step here."

    # And it is in what the agent is actually told, verbatim and under a heading that says whose
    # it is — an agent has to tell a standing preference from the task it was given.
    said = dispatch.build_task(
        "do the thing", project="a-project", standing=await desk.project_note(key)
    )
    assert "asked anybody working here to know" in said
    assert "We never add a build step here." in said
    assert said.index("do the thing") < said.index("We never add a build step")

    # Cleared rather than left as a heading with nothing under it.
    await _post("/project-note", {"key": key, "note": "   "})
    assert await desk.project_note(key) == ""
    assert "asked anybody working here" not in dispatch.build_task("do the thing", standing="")


@pytest.mark.unit
async def test_the_words_somebody_uses_are_told_to_every_agent_started_here(
    home: Home, desk: Store
) -> None:
    """An agent dispatched into a project does not have its vocabulary, and today that costs a
    paragraph in every instruction or a wrong guess."""
    key = await _the_project(home)

    status, panel = await _post(
        "/glossary", {"key": key, "term": "верстак", "means": "the middle column"}
    )
    assert status == 200
    assert "верстак" in panel

    # A word that means the same thing everywhere is written once, not into each project.
    await _post(
        "/glossary", {"key": key, "term": "the pool", "means": "the ideas", "everywhere": "yes"}
    )
    assert [t.term for t in await desk.terms(key)] == ["the pool", "верстак"]
    assert [t.term for t in await desk.terms("some:other")] == ["the pool"]

    # Half an entry is worse than none, because it reads as one.
    await _post("/glossary", {"key": key, "term": "блокер", "means": "  "})
    assert len(await desk.terms(key)) == 2

    said = dispatch.build_task(
        "do the thing",
        glossary=[(t.term, t.means) for t in await desk.terms(key)],
    )
    assert "Words they use here" in said
    assert "**верстак** — the middle column" in said

    dropped = next(t for t in await desk.terms(key) if t.term == "верстак")
    await _post("/glossary", {"key": key, "drop": dropped.id})
    assert [t.term for t in await desk.terms(key)] == ["the pool"]


@pytest.mark.unit
async def test_every_path_that_starts_an_agent_carries_the_same_context(
    home: Home, desk: Store
) -> None:
    """One helper, so a word added on a project's page reaches the queue, an exploration and a
    session being kept going — rather than the one path somebody remembered to wire it into."""
    key = await _the_project(home)
    await desk.set_project_note(key, "no build step here")
    await desk.add_term(repo_key=key, term="верстак", means="the middle column")

    about = await autostart.about(desk, key)

    assert about["standing"] == "no build step here"
    assert about["glossary"] == [("верстак", "the middle column")]
    said = dispatch.build_task("do the thing", **about)  # type: ignore[arg-type]
    assert "no build step here" in said and "верстак" in said


@pytest.mark.unit
async def test_what_a_pass_made_of_an_idea_shows_as_a_reading_not_a_state(
    home: Home, desk: Store
) -> None:
    """A colour and a word, and nothing is hidden or reordered away."""
    ready = await desk.create_idea(text_="a small fix", summary="a small fix", source_kind="typed")
    await desk.appraise_idea(ready.id, size="small", shape="ready")
    waiting = await desk.create_idea(text_="a big one", summary="a big one", source_kind="typed")
    await desk.appraise_idea(waiting.id, size="large", shape="decide")

    column = await routes.render_ideas()

    assert "needs-decide" in column
    assert "needs you to decide something" in column
    assert "small" in column and "big" in column
    # Both are still there: the pass never hides a row.
    assert "a small fix" in column and "a big one" in column

    _, column = await _post("/ideas/sort", {"how": "needs"})
    assert column.index("a big one") < column.index("a small fix")


@pytest.mark.unit
async def test_an_idea_that_reads_as_already_built_is_a_question_not_a_claim(
    home: Home, desk: Store
) -> None:
    """ "This is already built" from a reading of the text is exactly the claim CLAUDE.md's fifth
    rule says not to make, so it is offered with a button rather than applied."""
    idea = await desk.create_idea(text_="add hotkeys", summary="add hotkeys", source_kind="typed")
    await desk.appraise_idea(idea.id, size="small", shape="built")

    column = await routes.render_ideas()

    assert "is it?" in column
    assert (await desk.idea(idea.id)).state == "new"  # type: ignore[union-attr]
    # And the button that would settle it is the one a person presses.
    assert f"/ideas/{idea.id}/done" in column


@pytest.mark.unit
async def test_a_background_session_can_be_answered_from_its_card(
    home: Home, desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case docs/adr/0002 was written *for*: "a message to a session is a deliberate human act
    with a button behind it, never a side effect of a background loop"."""
    import os
    import time

    sent: list[tuple[str, str]] = []

    def fake_kick(
        session_id: str, instruction: str, *, cwd: str, agent_id: str = ""
    ) -> dispatch.Started:
        sent.append((session_id, instruction))
        return dispatch.Started(True, agent_id=agent_id)

    monkeypatch.setattr(dispatch, "kick", fake_kick)
    session_id = "ffffffff-0000-4000-8000-000000000006"
    home.session(
        os.getpid(),
        session_id,
        cwd=str(home.root.parent),
        kind="bg",
        status="idle",
        updatedAt=int(time.time() * 1000),
    )

    board = await asyncio.to_thread(routes.render_board, await desk.groups(), {}, {}, {})
    assert "answer it, or tell it what to do next" in board

    status, panel = await _post(f"/sessions/{session_id}/say", {"text": "  use the other one  "})

    assert status == 200
    assert sent == [(session_id, "use the other one")]
    assert "started" in panel or "agent" in panel

    # Nothing typed sends nothing.
    await _post(f"/sessions/{session_id}/say", {"text": "   "})
    assert len(sent) == 1


@pytest.mark.unit
async def test_a_session_that_is_working_is_offered_no_field(home: Home, desk: Store) -> None:
    """A message into work in progress is the half of docs/adr/0002 that stands whole."""
    import os
    import time

    session_id = "0a0a0a0a-0000-4000-8000-000000000007"
    home.session(
        os.getpid(),
        session_id,
        cwd=str(home.root.parent),
        kind="bg",
        status="busy",
        updatedAt=int(time.time() * 1000),
    )

    board = await asyncio.to_thread(routes.render_board, await desk.groups(), {}, {}, {})

    assert "answer it, or tell it what to do next" not in board


@pytest.mark.unit
async def test_a_terminal_session_is_told_the_rule_rather_than_the_symptom(
    home: Home, desk: Store
) -> None:
    session_id = _a_session(home)  # the fixture's session is interactive

    status, panel = await _post(f"/sessions/{session_id}/say", {"text": "hello"})

    assert status == 200
    assert "only a background session" in panel


@pytest.mark.unit
async def test_a_session_that_stopped_signing_is_flagged_and_never_closed_for_it(
    home: Home, desk: Store
) -> None:
    """Closing a session throws away whatever it has not committed, and that is not a call a
    background loop gets to make (docs/adr/0002) — so the board says so and offers a click."""
    import os
    import time

    session_id = "0b0b0b0b-0000-4000-8000-000000000008"
    home.session(
        os.getpid(),
        session_id,
        cwd=str(home.root.parent),
        kind="bg",
        updatedAt=int(time.time() * 1000),
    )
    home.transcript(session_id, _entry("assistant", "biba: still reading the parser"))
    await desk.keep_canary("0b0b0b0b", "biba")

    board = await asyncio.to_thread(
        routes.render_board, await desk.groups(), {}, {}, {}, await routes.board_canaries()
    )
    assert "lost the thread" not in board

    home.transcript(session_id, _entry("assistant", "I have finished the parser."))
    board = await asyncio.to_thread(
        routes.render_board, await desk.groups(), {}, {}, {}, await routes.board_canaries()
    )

    assert "lost the thread" in board
    assert "has stopped signing" in board
    # A session nobody told to sign is never flagged for not signing.
    assert routes.signed(object(), "") is True


@pytest.mark.unit
async def test_the_map_draws_the_whole_pool_including_what_is_built(
    home: Home, desk: Store
) -> None:
    """A list cannot show the thing that makes the links worth recording, and half the shape of a
    pool is what is already there."""
    first = await desk.create_idea(text_="the parser", summary="the parser", source_kind="typed")
    second = await desk.create_idea(text_="the cache", summary="the cache", source_kind="typed")
    built = await desk.create_idea(text_="hotkeys", summary="hotkeys", source_kind="typed")
    await desk.set_idea_state(built.id, "done")
    gone = await desk.create_idea(text_="never mind", summary="never mind", source_kind="typed")
    await desk.set_idea_state(gone.id, "dropped")
    await desk.link_ideas(from_id=second.id, to_id=first.id, kind="needs")

    status, page = await _get("/ideas/map")

    assert status == 200
    assert "<svg" in page
    assert "the parser" in page and "the cache" in page
    # What is built is drawn, and drawn differently.
    assert "hotkeys" in page
    assert "node done built" in page
    # What was discarded is not: the map is the pool, and a discarded thought left it.
    assert "never mind" not in page


@pytest.mark.unit
async def test_the_plans_page_declares_one_and_moves_a_session_onto_it(
    home: Home, desk: Store
) -> None:
    """A subscription holds sessions from more than one project, which is what makes it the block
    above them (025-subscriptions.sql)."""
    session_id = _a_session(home)

    status, page = await _get("/plans")
    assert status == 200
    assert "Declare one" in page

    status, page = await _post(
        "/plans", {"name": "Claude Max", "service": "claude code", "limit_tokens": "1000000"}
    )
    assert status == 200
    (plan,) = await desk.subscriptions()
    assert plan.limit_tokens == 1_000_000

    status, page = await _post(f"/sessions/{session_id}/plan", {"plan": plan.id})
    assert status == 200
    assert await desk.session_subscriptions() == {session_id.split("-")[0]: plan.id}

    # The strip on the board shows it, and says which number is which.
    strip = await routes.board_plans(*await routes.board_rows_and_kicks())
    assert "Claude Max" in strip
    assert "in the air" in strip

    # A limit that is not a number is left out rather than crashing the page.
    await _post("/plans", {"name": "Team", "limit_tokens": "lots"})
    team = next(one for one in await desk.subscriptions() if one.name == "Team")
    assert team.limit_tokens is None

    status, _ = await _post("/plans", {"drop": plan.id})
    assert status == 200
    assert [one.name for one in await desk.subscriptions()] == ["Team"]


@pytest.mark.unit
async def test_the_workbench_draws_what_is_on_it(home: Home, desk: Store) -> None:
    """A stack of cards says what each one is; it cannot say how they stand to each other, which
    is usually the question when four things were dragged there at once."""
    session_id = _a_session(home)
    rows, _ = routes.board()
    key = (routes.shape(rows, []))[0].key

    status, page = await _get(f"/workbench?cards=project:{key},session:{session_id}")

    assert status == 200
    assert "<svg" in page
    assert "runs in" in page

    # Nothing on it draws nothing, and says so rather than showing an empty frame.
    status, page = await _get("/workbench?cards=")
    assert status == 200
    assert "Drop a card or two" in page


@pytest.mark.unit
async def test_choosing_a_project_narrows_the_right_hand_column(home: Home, desk: Store) -> None:
    """ "Выбор проекта слева фильтрует блокеры и идеи; без выбора — всё." A board with six
    projects has a column about all six, and when you are working on one that is mostly noise."""
    key = await _the_project(home)
    mine = await desk.create_idea(
        text_="about this one", summary="about this one", source_kind="typed"
    )
    await desk.set_idea_project(mine.id, key)
    theirs = await desk.create_idea(
        text_="about another", summary="about another", source_kind="typed"
    )
    await desk.set_idea_project(theirs.id, "origin:someone/else")
    # One with no project at all: it must survive the narrowing.
    await desk.create_idea(text_="about nothing", summary="about nothing", source_kind="typed")

    # Without a choice: everything.
    column = await routes.render_ideas()
    assert "about this one" in column and "about another" in column and "about nothing" in column

    status, column = await _post("/projects/focus", {"key": key})

    assert status == 200
    assert "about this one" in column
    assert "about another" not in column
    # A thought with no project is about whatever is in front of you, so it survives the
    # narrowing — hiding it behind a filter it was never part of would lose it.
    assert "about nothing" in column
    assert "showing" in column and "show everything" in column

    # And it survives a push, which is what a query parameter could not do.
    assert "about another" not in await routes.render_ideas()

    status, column = await _post("/projects/focus", {"key": ""})
    assert "about another" in column


@pytest.mark.unit
async def test_the_blockers_narrow_with_the_ideas_and_the_loose_ones_stay(
    home: Home, desk: Store, tmp_path: pathlib.Path
) -> None:
    """One decision moves both columns; a failed question belongs to no repository at all."""
    key = await _the_project(home)
    mine = await desk.queue_task(
        repo_key=key,
        cwd=str(tmp_path),
        title="this project",
        instruction="x",
        source_kind="instruction",
    )
    await desk.task_failed(mine.id, "it fell over")
    theirs = await desk.queue_task(
        repo_key="origin:someone/else",
        cwd=str(tmp_path),
        title="another project",
        instruction="x",
        source_kind="instruction",
    )
    await desk.task_failed(theirs.id, "it fell over too")

    await _post("/projects/focus", {"key": key})
    column = await routes.render_blockers()

    assert "this project" in column
    assert "another project" not in column
    assert "for this project only" in column


@pytest.mark.unit
async def test_the_right_hand_column_switches_between_the_pool_and_the_board(
    home: Home, desk: Store, tmp_path: pathlib.Path
) -> None:
    """ "В столбце с идеями можно переключить режим на jira таски." Two things one column can be
    about, kept apart rather than merged: an idea is a thought somebody had here and a ticket is
    work somebody decided elsewhere."""
    key = await _the_project(home)
    await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    await desk.queue_task(
        repo_key=key,
        cwd=str(tmp_path),
        title="DUCK-7 · the export is wrong",
        instruction="fix the export",
        source_kind="tracker",
        source_ref="DUCK-7",
    )
    await desk.replace_tracker_blockers(key, [("DUCK-9", "the import", "Blocked on the vendor.")])

    # The pool by default, and a ticket never appears in it.
    pool = await routes.render_column()
    assert "a thought" in pool
    assert "DUCK-7" not in pool

    status, column = await _post("/column", {"shows": "tickets"})

    assert status == 200
    assert "DUCK-7" in column
    assert "take it on" in column
    # And a thought never appears among the tickets.
    assert "a thought" not in column
    # A ticket that says it is stuck is shown as waiting on a person, not offered as work.
    assert "DUCK-9" in column
    assert "Blocked on the vendor" in column

    # The choice survives a push, like every other choice about this column.
    assert "DUCK-7" in await routes.render_column()

    status, column = await _post("/column", {"shows": "ideas"})
    assert "a thought" in column and "DUCK-7" not in column


@pytest.mark.unit
async def test_the_board_column_narrows_with_the_project_filter_too(
    home: Home, desk: Store, tmp_path: pathlib.Path
) -> None:
    key = await _the_project(home)
    for repo, ref in ((key, "DUCK-1"), ("origin:someone/else", "OTHER-1")):
        await desk.queue_task(
            repo_key=repo,
            cwd=str(tmp_path),
            title=f"{ref} · something",
            instruction="x",
            source_kind="tracker",
            source_ref=ref,
        )
    await _post("/column", {"shows": "tickets"})

    await _post("/projects/focus", {"key": key})
    column = await routes.render_column()

    assert "DUCK-1" in column
    assert "OTHER-1" not in column


@pytest.mark.unit
async def test_a_project_can_be_added_by_pointing_at_a_folder(
    home: Home, desk: Store, tmp_path: pathlib.Path
) -> None:
    """ "При добавлении проекта можно просто указать папку на устройстве." Running `claude` in one
    still needs no form; this is for the moment somebody has the address in their hand."""
    where = tmp_path / "a-project"
    where.mkdir()

    status, panel = await _post("/projects/attach", {"where": str(where)})

    assert status == 200
    assert "a-project" in panel
    assert [group.name for group in await desk.groups()] == ["a-project"]
    # The directory is recorded, so the queue and an exploration have somewhere to work before a
    # session has ever run there.
    arming = await desk.autostart(routes.repository_of(str(where)).key)
    assert arming.cwd == str(where)


@pytest.mark.unit
async def test_a_project_can_be_added_by_its_repository_url(home: Home, desk: Store) -> None:
    status, panel = await _post("/projects/attach", {"where": "git@github.com:someone/a-thing.git"})

    assert status == 200
    (group,) = await desk.groups()
    assert group.name == "a-thing"
    # The URL is kept as a link, and nothing was cloned.
    (link,) = await desk.links("origin:someone/a-thing")
    assert link.url == "https://github.com/someone/a-thing"


@pytest.mark.unit
async def test_pointing_at_nothing_says_what_is_wrong(home: Home, desk: Store) -> None:
    status, panel = await _post("/projects/attach", {"where": "/nowhere/at/all"})

    assert status == 200
    assert "is not a folder on this machine" in panel
    assert await desk.groups() == []


@pytest.mark.unit
async def test_a_card_says_which_project_it_is_about(
    home: Home, desk: Store, tmp_path: pathlib.Path
) -> None:
    """ "При наведении на идею/блокер подсвечивается проект к которому он относится." The relation
    is in the data already; the page needs it on the card to be able to point at it."""
    key = await _the_project(home)
    idea = await desk.create_idea(text_="a thought", summary="a thought", source_kind="typed")
    await desk.set_idea_project(idea.id, key)
    task = await desk.queue_task(
        repo_key=key,
        cwd=str(tmp_path),
        title="a task",
        instruction="x",
        source_kind="instruction",
    )
    await desk.task_failed(task.id, "it fell over")

    assert f'data-about="{key}"' in await routes.render_ideas()
    assert f'data-about="{key}"' in await routes.render_blockers()

    # An idea about nothing in particular claims nothing.
    loose = await desk.create_idea(text_="about nothing", summary="loose", source_kind="typed")
    column = await routes.render_ideas()
    assert f'data-id="{loose.id}"' in column
    assert column.count("data-about") == 1


@pytest.mark.unit
async def test_the_bench_reports_which_cards_are_related(home: Home, desk: Store) -> None:
    """The lines are drawn behind the real cards, so the page needs the pairs rather than a
    picture: "я хочу видеть блоки на верстаке как связанные карточки"."""
    session_id = _a_session(home)
    rows, _ = routes.board()
    key = routes.shape(rows, [])[0].key
    first = await desk.create_idea(text_="the parser", summary="the parser", source_kind="typed")
    second = await desk.create_idea(text_="the cache", summary="the cache", source_kind="typed")
    await desk.link_ideas(from_id=second.id, to_id=first.id, kind="needs")

    status, body = await _get(
        f"/workbench/ties?cards=project:{key},session:{session_id},idea:{first.id},idea:{second.id}"
    )

    assert status == 200
    ties = json.loads(body)
    said = {(tie["from"], tie["to"], tie["says"]) for tie in ties}
    assert (f"project:{key}", f"session:{session_id}", "runs in") in said
    assert (f"idea:{first.id}", f"idea:{second.id}", "needs") in said

    # Nothing on the bench is no lines rather than an error.
    status, body = await _get("/workbench/ties?cards=")
    assert status == 200 and json.loads(body) == []


@pytest.mark.unit
async def test_a_meeting_pasted_into_the_pool_comes_back_immediately(
    home: Home, desk: Store
) -> None:
    """It is read in passes and each one is a model call, so the field must not wait for it."""
    status, panel = await _post("/ideas/meeting", {"transcript": "   "})
    assert status == 200
    assert await desk.ideas() == []

    # With something in it, the column comes straight back and the reading happens behind it —
    # and where there is nothing to run it in, it answers a page rather than raising a 500.
    status, panel = await _post("/ideas/meeting", {"transcript": "someone: we need a grid"})
    assert status == 200
    assert "idea" in panel or "Nothing recorded" in panel


@pytest.mark.unit
async def test_a_card_carries_the_sentence_written_about_it(
    home: Home, desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Метадата — созданное ЛЛМ описание элемента." The board can say what it reads; this is
    what it cannot say without a model."""
    from agent_desk.ideas import describe

    async def fake(prompt: str):
        yield "A session reading the parser in agent-desk."

    monkeypatch.setattr(describe, "stream_answer", fake)
    session_id = _a_session(home)

    said = await routes.describe_card("session", session_id)
    assert said == "A session reading the parser in agent-desk."

    card = routes.render_card("session", session_id, [], said)
    assert "A session reading the parser" in card

    # And a card with nothing written about it renders as an ordinary card, not a hole.
    plain = routes.render_card("session", session_id, [], "")
    assert "card-said" not in plain


@pytest.mark.unit
async def test_everything_about_a_session_is_a_route_of_its_own(home: Home, desk: Store) -> None:
    """A transcript tail is tens of kilobytes; a board of twenty cards must not carry twenty of
    them until somebody presses for one."""
    session_id = _a_session(home)

    status, page = await _get(f"/cards/session/full?id={session_id}")

    assert status == 200
    assert "Everything it has said" in page
    assert "running for" in page
    assert "carrying" in page
    # The console is rendered as the console: what was said, by whom, when.
    assert "console-line" in page or "Nothing has been read" in page

    # Only the kinds that have a console.
    assert (await _get("/cards/project/full?id=whatever"))[0] == 404
    assert (await _get("/cards/session/full?id=nobody"))[0] == 404
