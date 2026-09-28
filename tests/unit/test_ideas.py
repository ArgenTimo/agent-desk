"""Capture, the card, and the three draft actions.

docs/05-ideas.md is short and every paragraph of it is a requirement. The two that decide whether
this module is worth having are tested first: the thought survives a machine where nothing else
works, and no action here writes anywhere but this program's own store.
"""

from __future__ import annotations

import asyncio
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.answer import session
from agent_desk.config import Settings
from agent_desk.ideas import inbox
from agent_desk.store.repo import Idea, Store
from agent_desk.web import blocks, routes

from tests.unit.waiting import until

FAKE = """#!/bin/sh
prompt=$(cat)
case "$prompt" in
  *"Open subjects"*) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"new"}]}}\n' ;;
  *"Summarise the following"*)
    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"Cache tracker probes per project"}]}}\\n' ;;
  *"short markdown proposal"*)
    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"# Proposal\\\\n\\\\nIt would change the probe cache."}]}}\\n' ;;
  *"body of a ticket"*)
    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"Cache probes\\\\n\\\\nAcceptance: one call per project."}]}}\\n' ;;
  *) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"an answer"}]}}\\n' ;;
esac
"""


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
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    async with asyncio.TaskGroup() as group:
        blocks.runs.attach(group)
        try:
            yield store
        finally:
            await blocks.runs.stop_all()
            blocks.runs.attach(None)
    await store.close()


async def _settle(check: object) -> None:
    """Wait for a background pass to have done its thing.

    This used to give up silently after six seconds and let the test carry on, so a busy machine
    produced a failure three lines later about whatever the pass had not written yet — with nothing
    saying that the waiting was what went wrong. It says so now, and it waits for a fact rather than
    for a length of time (tests/unit/waiting.py).
    """
    await until(check, getattr(check, "__name__", "the background pass finishes"))  # type: ignore[arg-type]


# --- capture --------------------------------------------------------------------------------
@pytest.mark.unit
async def test_an_idea_is_recorded_before_any_model_is_asked_anything(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The capture must not depend on a run, because the run is the part that can fail.

    Here there is no CLI at all. The thought is still stored, verbatim, with a summary taken from
    its own first line — losing it to an unavailable model would be the tool failing at the one
    job it has (docs/05-ideas.md).
    """
    monkeypatch.setattr(session, "settings", Settings(claude_bin="not-installed-anywhere"))
    await blocks.submit(desk, "/idea cache the probe results per project", [])

    (idea,) = await desk.ideas()
    assert idea.text == "cache the probe results per project"
    assert idea.summary == "cache the probe results per project"
    assert idea.state == "new"


@pytest.mark.unit
async def test_a_generated_line_replaces_the_fallback_and_the_thought_is_untouched(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    await blocks.submit(
        desk, "/idea cache the probe results per project so onboarding is quick", []
    )

    async def summarised() -> bool:
        (idea,) = await desk.ideas()
        return idea.summary == "Cache tracker probes per project"

    await _settle(summarised)
    (idea,) = await desk.ideas()
    assert idea.summary == "Cache tracker probes per project"
    assert idea.text == "cache the probe results per project so onboarding is quick"


@pytest.mark.unit
async def test_the_card_asks_once_and_offers_two_answers(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """docs/05: keep or discard, one click. Anything more and the tool is competing with the run.

    One line per thought, saying that it was written down, with the two answers beside it. A
    message that held three thoughts says it three times.
    """
    await blocks.submit(desk, "/idea a thought", [])
    card = await routes.render_blocks()

    assert "recorded as an idea" in card
    assert "Keep" in card and "Discard" in card
    assert "a thought" in card


@pytest.mark.unit
async def test_a_long_thought_keeps_its_summary_short_and_itself_whole(desk: Store) -> None:
    long_thought = "cache " * 40
    assert len(inbox.fallback_summary(long_thought)) <= inbox.SUMMARY_CHARS
    assert inbox.fallback_summary(long_thought).endswith("…")


# --- the context an idea carries ---------------------------------------------------------------
@pytest.mark.unit
async def test_one_live_session_is_attached_and_several_are_described(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/05 wants the project, the branch and the session. With several running, which one the
    human meant is a guess — and an idea remembered against the wrong branch is worse a week later
    than one remembered against none."""
    monkeypatch.setattr(session, "settings", Settings(claude_bin="not-installed-anywhere"))
    from tests.unit.test_input import make_row

    await blocks.submit(desk, "/idea with one session", [make_row("alpha", "boba/duck-129")])
    await blocks.submit(
        desk, "/idea with two", [make_row("alpha", "main"), make_row("beta", "staging")]
    )

    two, one = await desk.ideas()
    assert one.source_kind == "session"
    assert one.context["branch"] == "boba/duck-129"
    assert two.source_kind == "typed"
    assert two.context["sessions"] == "2"
    assert "alpha" in two.context["projects"] and "beta" in two.context["projects"]


# --- keep, discard, and the four states ---------------------------------------------------------
@pytest.mark.unit
async def test_an_idea_has_four_states_and_no_backlog_around_it(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    await blocks.submit(desk, "/idea a thought", [])
    (idea,) = await desk.ideas()

    await desk.set_idea_state(idea.id, "kept")
    kept = await desk.idea(idea.id)
    assert kept is not None and kept.state == "kept"
    # No priority, no assignee, no estimate: that is a backlog (docs/08-non-goals.md §4).
    assert not hasattr(kept, "priority")
    assert not hasattr(kept, "assignee")


# --- the three drafts ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_copy_for_a_session_is_generated_by_nothing(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The human is the transport, and this action works on a machine with no model at all."""
    monkeypatch.setattr(session, "settings", Settings(claude_bin="not-installed-anywhere"))
    await blocks.submit(desk, "/idea cache the probes", [])
    (idea,) = await desk.ideas()

    await blocks.draft(desk, idea, "paste")
    (draft,) = await desk.drafts_for(idea.id)
    assert draft.kind == "paste"
    assert "cache the probes" in draft.body
    assert "Captured by agent-desk" in draft.body


@pytest.mark.unit
async def test_a_proposal_and_a_ticket_are_written_into_this_store_and_nowhere_else(
    desk: Store, fake_claude: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The rule docs/05-ideas.md exists for: the draft is the deliverable, and it stays here."""
    await blocks.submit(desk, "/idea cache the probes", [])
    (idea,) = await desk.ideas()
    before = {p for p in tmp_path.rglob("*") if p.is_file()}

    await blocks.draft(desk, idea, "proposal")
    await blocks.draft(desk, idea, "ticket")

    async def both_written() -> bool:
        return len(await desk.drafts_for(idea.id)) == 2

    await _settle(both_written)
    kinds = {draft.kind for draft in await desk.drafts_for(idea.id)}
    assert kinds == {"proposal", "ticket"}

    # Nothing appeared on disk outside the store — no markdown file, no repository, no ticket.
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert {p.name for p in after - before} <= {"agent-desk.db", "agent-desk.db-journal"}


@pytest.mark.unit
async def test_a_draft_that_could_not_be_written_says_so_and_keeps_the_idea(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session, "settings", Settings(claude_bin="not-installed-anywhere"))
    await blocks.submit(desk, "/idea cache the probes", [])
    (idea,) = await desk.ideas()

    await blocks.draft(desk, idea, "proposal")

    async def written() -> bool:
        return bool(await desk.drafts_for(idea.id))

    await _settle(written)
    (draft,) = await desk.drafts_for(idea.id)
    assert "could not be written" in draft.body
    stored = await desk.idea(idea.id)
    assert stored is not None and stored.text == "cache the probes"


@pytest.mark.unit
def test_the_summary_prompt_forbids_inventing_what_the_human_did_not_say() -> None:
    prompt = inbox.summary_prompt("cache the probes")
    assert "Do not add a rationale" in prompt
    assert "cache the probes" in prompt


# --- the card's actions, which had markup and no behaviour --------------------------------------
async def _card_post(path: str, fields: dict[str, str], *, htmx: bool = False) -> tuple[int, str]:
    from tests.unit.test_input import _post

    status, html, headers = await _post(path, fields, htmx=htmx)
    return status, html if htmx else headers.get("location", "")


@pytest.mark.unit
async def test_keep_and_discard_do_different_things(desk: Store, fake_claude: pathlib.Path) -> None:
    """A reviewer replaced the whole branch with `"dropped"` and the suite stayed green."""
    await blocks.submit(desk, "/idea keep this one", [])
    await blocks.submit(desk, "/idea drop this one", [])
    dropped, kept = await desk.ideas()

    await _card_post(f"/ideas/{kept.id}/keep", {"from": "card"})
    await _card_post(f"/ideas/{dropped.id}/drop", {"from": "card"})

    assert (await desk.idea(kept.id)).state == "kept"  # type: ignore[union-attr]
    assert (await desk.idea(dropped.id)).state == "dropped"  # type: ignore[union-attr]


@pytest.mark.unit
async def test_the_summary_can_be_edited_by_hand(desk: Store, fake_claude: pathlib.Path) -> None:
    """ "Edit summary" is in the docs/04 action table and in the docs/05 card, and had no test."""
    await blocks.submit(desk, "/idea a thought", [])
    (idea,) = await desk.ideas()

    await _card_post(f"/ideas/{idea.id}/summary", {"summary": "a line a human wrote"})

    stored = await desk.idea(idea.id)
    assert stored is not None
    assert stored.summary == "a line a human wrote"
    assert stored.text == "a thought"


@pytest.mark.unit
async def test_asking_for_a_draft_promotes_the_idea(desk: Store, fake_claude: pathlib.Path) -> None:
    """`promoted` is one of the four states, and the second number docs/09 says is measured.

    A draft is offered to a *kept* idea: the inbox shows those buttons only after Keep, and the
    route now agrees with the template rather than accepting a walk backwards through the states.
    """
    await blocks.submit(desk, "/idea cache the probes", [])
    (idea,) = await desk.ideas()
    await _card_post(f"/ideas/{idea.id}/keep", {"from": "card"})

    await _card_post(f"/ideas/{idea.id}/paste", {})

    stored = await desk.idea(idea.id)
    assert stored is not None
    assert stored.state == "promoted"

    # Keeping it wrote the proposal on its own — "каждая идея при апруве преобразуется как минимум
    # в часть документации" — and that is a run, so it lands when it lands. Both are there; which
    # arrived first is not the subject of this test.
    async def written() -> bool:
        return len(blocks.runs) == 0

    await _settle(written)
    assert {d.kind for d in await desk.drafts_for(idea.id)} == {"proposal", "paste"}


@pytest.mark.unit
async def test_an_action_this_program_does_not_have_is_not_a_shrug(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """It used to answer 303 and do nothing, which is how a typo becomes a mystery."""
    await blocks.submit(desk, "/idea a thought", [])
    (idea,) = await desk.ideas()

    status, _ = await _card_post(f"/ideas/{idea.id}/publish-to-github", {})
    assert status == 404


@pytest.mark.unit
async def test_the_card_works_the_same_with_htmx_and_without(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """Keep used to navigate to the inbox without htmx, because the origin travelled in a header
    that only htmx sends."""
    await blocks.submit(desk, "/idea one", [])
    await blocks.submit(desk, "/idea two", [])
    second, first = await desk.ideas()

    status, location = await _card_post(f"/ideas/{first.id}/keep", {"from": "card"})
    assert status == 303
    assert location == "/"

    status, html = await _card_post(f"/ideas/{second.id}/keep", {"from": "card"}, htmx=True)
    assert status == 200
    assert "recorded as an idea" in html  # the block column, not the inbox


@pytest.mark.unit
async def test_a_generated_summary_never_overwrites_one_a_human_wrote(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """Found by a test that failed only sometimes, which is the bug talking.

    Capture stores a fallback line and starts a run to improve it. A human can edit the card in
    the seconds that takes, and the generated line used to land afterwards and win. docs/05-ideas
    is explicit that the summary is the human's to edit; a tool that overwrites the person it is
    for has the relationship backwards.
    """
    await blocks.submit(
        desk, "/idea cache the probe results per project so onboarding is quick", []
    )
    (idea,) = await desk.ideas()

    await desk.set_idea_summary(idea.id, "what I actually meant")

    async def generated_arrived() -> bool:
        return len(blocks.runs) == 0

    await _settle(generated_arrived)

    stored = await desk.idea(idea.id)
    assert stored is not None
    assert stored.summary == "what I actually meant"


@pytest.mark.unit
async def test_an_idea_action_without_the_card_field_lands_in_the_inbox(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """Replacing the whole branch with `True` left the suite green: no test posted without the
    field and asserted where it ended up, so both directions of the same choice were unasserted.
    """
    await blocks.submit(desk, "/idea a thought", [])
    (idea,) = await desk.ideas()

    status, location = await _card_post(f"/ideas/{idea.id}/keep", {})
    assert status == 303
    assert location == "/ideas"

    status, html = await _card_post(f"/ideas/{idea.id}/drop", {}, htmx=True)
    assert status == 200
    # The inbox fragment, not the block column.
    assert "Idea recorded" not in html


@pytest.mark.unit
async def test_an_idea_cannot_walk_backwards_through_its_states(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """The templates hide a button that does not apply; the route has to mean it.

    Keeping an already promoted idea quietly reverted it, and a draft could be asked of an idea
    nobody had kept — four states are only four states if something enforces them.
    """
    await blocks.submit(desk, "/idea a thought", [])
    (idea,) = await desk.ideas()
    await _card_post(f"/ideas/{idea.id}/keep", {"from": "card"})
    await _card_post(f"/ideas/{idea.id}/paste", {})
    assert (await desk.idea(idea.id)).state == "promoted"  # type: ignore[union-attr]

    status, _ = await _card_post(f"/ideas/{idea.id}/keep", {"from": "card"})
    assert status == 409
    assert (await desk.idea(idea.id)).state == "promoted"  # type: ignore[union-attr]

    await blocks.submit(desk, "/idea another thought", [])
    fresh = (await desk.ideas())[0]
    status, _ = await _card_post(f"/ideas/{fresh.id}/proposal", {})
    assert status == 409, "a draft is for an idea somebody kept"
    assert await desk.drafts_for(fresh.id) == []


# --- one message, several thoughts ---------------------------------------------------------------
SPLITTER = """#!/bin/sh
prompt=$(cat)
case "$prompt" in
  *"Split it into the separate ideas"*)
    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"cache the probe results\\\\nthe ports are still hardcoded"}]}}\\n' ;;
  *) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"an answer"}]}}\\n' ;;
esac
"""


@pytest.fixture
def splitter(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    binary = tmp_path / "split" / "claude"
    binary.parent.mkdir()
    binary.write_text(SPLITTER)
    binary.chmod(0o755)
    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(binary), answer_timeout_seconds=10.0)
    )
    return binary


@pytest.mark.unit
async def test_one_message_can_hold_several_thoughts(desk: Store, splitter: pathlib.Path) -> None:
    """ "Add A, and B is broken" is one message and two ideas, and all three are written down.

    The whole message is recorded first, before any model is asked anything — that is the
    guarantee — and it stays as the thing the two thoughts hang under, because it is one thing
    somebody typed and several things they meant (docs/05-ideas.md).
    """
    block = await blocks.submit(
        desk, "/idea cache the probe results, and the ports are still hardcoded", []
    )

    # Immediately: one idea, the whole message, with no run having happened yet.
    (whole,) = await desk.ideas()
    assert whole.text == "cache the probe results, and the ports are still hardcoded"

    async def split() -> bool:
        return len(await desk.ideas()) == 3

    await _settle(split)
    second, first, message = await desk.ideas()
    assert first.text == "cache the probe results"
    assert second.text == "the ports are still hardcoded"
    # The two hang under the message, and the message is the one that was typed.
    assert message.id == whole.id
    assert message.parent_id is None
    assert {idea.parent_id for idea in (first, second)} == {whole.id}
    assert {idea.block_id for idea in (first, second)} == {block.id}

    card = await routes.render_blocks()
    assert card.count("recorded as an idea") == 3

    # And the column shows one group with two under it, rather than three cards in a row.
    column = await routes.render_ideas()
    assert column.count('data-kind="idea"') == 3
    assert "3 ideas" in column and "1 group" in column


@pytest.mark.unit
async def test_a_card_a_human_has_touched_is_not_split_underneath_them(
    desk: Store, splitter: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same rule the generated summary follows: they have said what they want it to be."""
    monkeypatch.setattr(session, "settings", Settings(claude_bin="not-installed-anywhere"))
    await blocks.submit(desk, "/idea cache the probes, and the ports are hardcoded", [])
    (whole,) = await desk.ideas()
    await desk.set_idea_state(whole.id, "kept")

    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(splitter), answer_timeout_seconds=10.0)
    )
    await blocks._write_ideas(desk, await desk.block(whole.block_id), whole, [])  # type: ignore[arg-type]

    assert [idea.id for idea in await desk.ideas()] == [whole.id]


@pytest.mark.unit
async def test_an_idea_dropped_into_a_question_travels_as_what_was_written(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An idea has no session and no transcript: what it contributes is the thought itself."""
    monkeypatch.setattr(session, "settings", Settings(claude_bin="not-installed-anywhere"))
    await blocks.submit(desk, "/idea cache the probe results", [])
    (idea,) = await desk.ideas()

    assert await blocks.notes(desk, [f"idea:{idea.id}"]) == [
        "- cache the probe results: cache the probe results"
    ]
    assert await blocks.notes(desk, ["idea:no-such-idea"]) == []
    # And it is named in what the block says it carried — which is now derived from the cards the
    # prompt was built from rather than from a second walk over the targets.
    assert await blocks._context_lines(
        desk, [], [f"idea:{idea.id}"], [], carried=[f"idea:{idea.id}"]
    ) == ["idea · cache the probe results"]


# --- where a project also lives ------------------------------------------------------------------
@pytest.mark.unit
async def test_a_project_keeps_its_links_and_never_a_token(desk: Store) -> None:
    """docs/07-security.md: this file has no encryption and a second application reads out of it.

    So a link is stored and a token is not. What is recorded is the *name* of the environment
    variable the token would come from, which lets the console say what it would use without ever
    holding it.
    """
    await desk.set_link(
        repo_key="origin:acme/api",
        url="https://acme.atlassian.net/browse/API",
        name="jira",
        token_env="ACME_JIRA_TOKEN",
    )
    (link,) = await desk.links("origin:acme/api")

    assert link.url == "https://acme.atlassian.net/browse/API"
    assert link.token_env == "ACME_JIRA_TOKEN"
    assert link.token_present is False

    # Setting the variable changes what the console says, and nothing about what it stores.
    import os

    os.environ["ACME_JIRA_TOKEN"] = "not-a-real-token"
    try:
        (again,) = await desk.links("origin:acme/api")
        assert again.token_present is True
        assert again.token_env == "ACME_JIRA_TOKEN"
    finally:
        del os.environ["ACME_JIRA_TOKEN"]

    # One name per project: a second "jira" is a typo, not a second board.
    await desk.set_link(repo_key="origin:acme/api", url="https://elsewhere", name="jira")
    (only,) = await desk.links("origin:acme/api")
    assert only.url == "https://elsewhere"
    assert only.token_env is None

    await desk.remove_link("origin:acme/api", "jira")
    assert await desk.links("origin:acme/api") == []


@pytest.mark.unit
async def test_the_settings_panel_takes_a_token_and_never_gives_one_back(desk: Store) -> None:
    """A field that asks for a secret is fine; a field that shows one back is not.

    The token is written to this machine's own file and the panel can say only whether there is
    one — which is what somebody needs to know (agent_desk/secrets.py, docs/07-security.md).
    """
    from agent_desk import secrets as kept

    await desk.set_link(
        repo_key="k", name="jira", url="https://example.invalid", token_env="DESK_TEST_TOKEN"
    )
    kept.keep("DESK_TEST_TOKEN", "a-real-looking-secret")
    try:
        panel = await routes.render_project("k")
    finally:
        kept.forget("DESK_TEST_TOKEN")

    # It says there is one, and never what it is.
    assert "DESK_TEST_TOKEN" in panel
    assert "set here" in panel
    assert "a-real-looking-secret" not in panel
    # The field that takes it is a password field, and the page says where it goes.
    assert 'type="password"' in panel
    assert "stays on this machine" in panel
    assert "https://example.invalid" in panel


@pytest.mark.unit
async def test_ideas_can_be_grouped_by_hand_and_never_into_a_loop(desk: Store) -> None:
    """A human who sees that two ideas are one piece of work says so by dragging one onto the
    other. What the store refuses is the shape that would render forever."""
    one = await desk.create_idea(text_="the api half", summary="the api half", source_kind="typed")
    two = await desk.create_idea(text_="the app half", summary="the app half", source_kind="typed")
    three = await desk.create_idea(text_="a third", summary="a third", source_kind="typed")

    assert await desk.set_idea_parent(two.id, one.id) is True
    assert await desk.set_idea_parent(three.id, two.id) is True

    # Its own parent, its child's parent, its grandchild's parent — each would be a cycle.
    assert await desk.set_idea_parent(one.id, one.id) is False
    assert await desk.set_idea_parent(one.id, two.id) is False
    assert await desk.set_idea_parent(one.id, three.id) is False

    # And out of the group again.
    assert await desk.set_idea_parent(two.id, None) is True
    fresh = {idea.id: idea for idea in await desk.ideas()}
    assert fresh[two.id].parent_id is None
    assert fresh[three.id].parent_id == two.id


@pytest.mark.unit
async def test_a_child_whose_group_was_discarded_is_shown_rather_than_hidden(desk: Store) -> None:
    """An idea that vanished from the inbox is the one failure this module has."""
    parent = await desk.create_idea(text_="the message", summary="the message", source_kind="typed")
    child = await desk.create_idea(
        text_="a thought", summary="a thought", source_kind="typed", parent_id=parent.id
    )
    await desk.set_idea_state(parent.id, "dropped")

    column = await routes.render_ideas()

    assert child.id in column
    assert parent.id not in column


@pytest.mark.unit
async def test_an_idea_an_agent_has_in_hand_says_so_wherever_it_is_drawn(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    """One word, one colour, in the request that took it on and in the list it came from.

    Derived from the task rather than stored on the idea: a sixth state would be a second copy of
    the same fact, and a second copy goes wrong quietly (design/02-data-model.md).
    """
    idea = await desk.create_idea(text_="cache probes", summary="cache probes", source_kind="typed")
    quiet = await desk.create_idea(text_="untouched", summary="untouched", source_kind="typed")
    block = await desk.create_block(
        thread_id=(await desk.create_thread("s")).id,
        kind="instruction",
        input="бери в работу",
        thread_set_by="human",
    )
    await desk.link_block_ideas(block.id, [idea.id, quiet.id])
    task = await desk.queue_task(
        repo_key="k",
        cwd=str(tmp_path),
        title="take it on",
        instruction="take it on",
        source_kind="idea",
        source_ref=idea.id,
    )
    await desk.take_next_task("k")
    await desk.task_started(task.id, "agent5")

    assert await desk.ideas_in_flight() == {idea.id}

    column = await routes.render_ideas()
    assert "in progress" in column

    said = await routes.render_blocks()
    assert "taken on" in said
    assert "cache probes · in progress" in said
    # The one nobody started is still just an idea, and still offered.
    assert "implement these ideas" in said

    # And when its agent has gone, nothing is in flight any more.
    await desk.finish_task(task.id)
    assert await desk.ideas_in_flight() == set()


# --- the two runs that read what was typed -----------------------------------------------------
KINDS = """#!/bin/sh
prompt=$(cat)
case "$prompt" in
  *"One token, nothing else"*) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"%s"}]}}\\n' "$SAY" ;;
  *"which of them this request is about"*) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"%s"}]}}\\n' "$SAY" ;;
  *) printf '{"type":"assistant","message":{"content":[{"type":"text","text":"an answer"}]}}\\n' ;;
esac
"""


@pytest.fixture
def says(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    binary = tmp_path / "says" / "claude"
    binary.parent.mkdir()
    binary.write_text(KINDS)
    binary.chmod(0o755)
    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(binary), answer_timeout_seconds=10.0)
    )
    return binary


@pytest.mark.unit
async def test_what_the_kind_run_says_is_read_strictly(
    says: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One token, and the whole reply. Anything else is a question, which is the safe reading."""
    from agent_desk.answer import classify

    monkeypatch.setenv("SAY", "idea")
    assert await classify.kind("cache the probes") == "idea"

    monkeypatch.setenv("SAY", "do")
    assert await classify.kind("бери в работу") == "instruction"

    monkeypatch.setenv("SAY", "I think it is an idea")
    assert await classify.kind("something") == "question"


@pytest.mark.unit
async def test_a_kind_run_that_cannot_run_says_question(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable model must not turn a question into an agent (docs/adr/0006)."""
    from agent_desk.answer import classify

    monkeypatch.setattr(session, "settings", Settings(claude_bin="not-installed-anywhere"))

    assert await classify.kind("do the thing") == "question"


@pytest.mark.unit
async def test_which_ideas_a_request_is_about_is_read_as_numbers_or_nothing(
    says: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_desk.answer import classify

    ideas = ["cache the probes", "fix the ports", "add an export"]

    monkeypatch.setenv("SAY", "1, 3")
    assert await classify.related("do the caching and the export", ideas) == [1, 3]

    monkeypatch.setenv("SAY", "none")
    assert await classify.related("something else", ideas) == []

    # A reply that is prose names nothing: a wrong number here puts somebody else's thought in
    # front of a button that says built.
    monkeypatch.setenv("SAY", "probably the first one")
    assert await classify.related("something", ideas) == []

    # And with nothing written down, the run does not happen at all.
    assert await classify.related("anything", []) == []


@pytest.mark.unit
async def test_a_related_run_that_cannot_run_names_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_desk.answer import classify

    monkeypatch.setattr(session, "settings", Settings(claude_bin="not-installed-anywhere"))

    assert await classify.related("do the thing", ["an idea"]) == []


@pytest.mark.unit
async def test_keeping_an_idea_writes_it_up_without_a_second_click(
    desk: Store, fake_claude: pathlib.Path
) -> None:
    """ "Каждая идея при апруве преобразуется как минимум в часть документации." Keeping an idea is
    somebody saying it is worth doing, and the smallest useful thing to have afterwards is it
    written up — so the proposal is drafted there and then."""
    await blocks.submit(desk, "/idea cache the probes", [])
    (idea,) = await desk.ideas()

    await _card_post(f"/ideas/{idea.id}/keep", {"from": "card"})

    # The write-up is a run, so it lands when it lands.
    async def written() -> bool:
        return len(blocks.runs) == 0

    await _settle(written)

    assert [d.kind for d in await desk.drafts_for(idea.id)] == ["proposal"]
    # And it stays `kept`: a write-up nobody asked for does not promote it past what a person said.
    assert (await desk.idea(idea.id)).state == "kept"  # type: ignore[union-attr]


@pytest.mark.unit
async def test_discarding_an_idea_writes_nothing(desk: Store, fake_claude: pathlib.Path) -> None:
    """The maximum the idea asks for — a list of Jira tickets — stays a click, and so does every
    other door out of this program (docs/adr/0005)."""
    await blocks.submit(desk, "/idea never mind", [])
    (idea,) = await desk.ideas()

    await _card_post(f"/ideas/{idea.id}/drop", {"from": "card"})

    async def nothing_running() -> bool:
        return len(blocks.runs) == 0

    await _settle(nothing_running)

    assert await desk.drafts_for(idea.id) == []


@pytest.mark.unit
async def test_one_idea_can_be_said_to_need_another(desk: Store, fake_claude: pathlib.Path) -> None:
    """Grouping says "this is part of that". These two say what it cannot: a dependency between
    whole ideas, and a pair whose combination is worth more than either (024-idea-links.sql)."""
    first = await desk.create_idea(text_="the parser", summary="the parser", source_kind="typed")
    second = await desk.create_idea(text_="the cache", summary="the cache", source_kind="typed")

    await _card_post("/ideas/link", {"from_id": second.id, "to_id": first.id, "kind": "needs"})

    (link,) = await desk.idea_links()
    assert (link.from_id, link.to_id, link.kind) == (second.id, first.id, "needs")

    column = await routes.render_ideas()
    assert "needs" in column and "the parser" in column

    await _card_post("/ideas/link", {"drop": link.id})
    assert await desk.idea_links() == []


@pytest.mark.unit
async def test_an_idea_cannot_need_itself_and_a_link_is_stored_once(desk: Store) -> None:
    """Both are a misclick rather than something to store."""
    idea = await desk.create_idea(text_="one", summary="one", source_kind="typed")
    other = await desk.create_idea(text_="two", summary="two", source_kind="typed")

    assert await desk.link_ideas(from_id=idea.id, to_id=idea.id, kind="needs") is None
    await desk.link_ideas(from_id=idea.id, to_id=other.id, kind="needs")
    await desk.link_ideas(from_id=idea.id, to_id=other.id, kind="needs")

    assert len(await desk.idea_links()) == 1
    # The same pair related a different way is a different statement, and both are kept.
    await desk.link_ideas(from_id=idea.id, to_id=other.id, kind="touches")
    assert len(await desk.idea_links()) == 2


@pytest.mark.unit
async def test_the_pool_is_read_whole_unless_somebody_asks_for_fewer(desk: Store) -> None:
    """The default used to be two hundred, and every caller took it without meaning to. On a pool
    of four hundred and fifty-eight that is a console showing half of somebody's thoughts, a count
    above the list wrong by two hundred, and an idea recorded last month whose card no longer
    appears on the bench that recorded it — none of it said anything.

    A silent cap a caller inherits is the fifth rule at the bottom of a query."""
    for at in range(205):
        await desk.create_idea(text_=f"thought {at}", summary=f"thought {at}", source_kind="typed")

    assert len(await desk.ideas()) == 205
    assert len(await desk.ideas(limit=5)) == 5


@pytest.mark.unit
async def test_a_bound_belongs_to_whoever_has_a_reason_for_one(desk: Store) -> None:
    """The pass that spends a model call per idea has one and asks for five. Reading a person's own
    list does not."""
    source = (
        pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "store" / "repo.py"
    ).read_text(encoding="utf-8")
    start = source.index("    async def ideas(")
    head = source[start : source.index('"""', start)]

    assert "limit: int | None = None" in head


# --- a model that could not answer is a delay, not a scar -----------------------------------------
@pytest.mark.unit
async def test_a_summary_that_never_landed_is_tried_again(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Если в момент записи идеи модель не может ответить — обработка откладывается до того
    момента, как модель сможет ответить."

    Appraisal already worked that way. The summary did not: one failed run and the card kept a
    truncated first line for ever, which on a machine that was out of quota for ten minutes is a
    permanent scar from a temporary fault."""
    from agent_desk.ideas import appraise

    long = "a very long first line that will certainly be cut short by the fallback " * 3
    idea = await desk.create_idea(text_=long, summary="", source_kind="typed")
    await desk.set_idea_summary(idea.id, inbox.fallback_summary(long))

    async def answers(prompt: str):  # type: ignore[no-untyped-def]
        yield "read the log before deciding"

    monkeypatch.setattr(appraise, "stream_answer", answers)
    await appraise.sweep(desk)

    again = await desk.idea(idea.id)
    assert again is not None and again.summary == "read the log before deciding"


@pytest.mark.unit
async def test_a_line_somebody_edited_is_not_replaced(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A human editing the card *while a run was in flight* has said what they want it to be, and a
    generated line arriving afterwards does not get to disagree.

    Written as the race it guards: the run starts from the line as it was, the person edits it, and
    the answer lands after."""
    from agent_desk.ideas import appraise

    idea = await desk.create_idea(
        text_="a long thought about the reader", summary="", source_kind="typed"
    )
    await desk.set_idea_summary(idea.id, "the fallback line")
    started_from = await desk.idea(idea.id)
    await desk.set_idea_summary(idea.id, "what I actually meant")

    async def answers(prompt: str):  # type: ignore[no-untyped-def]
        yield "something else entirely"

    monkeypatch.setattr(appraise, "stream_answer", answers)
    assert started_from is not None
    await appraise.better_summary(desk, started_from)

    again = await desk.idea(idea.id)
    assert again is not None and again.summary == "what I actually meant"


@pytest.mark.unit
async def test_a_model_that_is_still_away_leaves_the_line_alone(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The honest thing for a card nobody has read."""
    from agent_desk.answer.session import AnswerFailed
    from agent_desk.ideas import appraise

    long = "a very long first line that will certainly be cut short by the fallback " * 3
    idea = await desk.create_idea(text_=long, summary="", source_kind="typed")
    await desk.set_idea_summary(idea.id, inbox.fallback_summary(long))

    async def away(prompt: str):  # type: ignore[no-untyped-def]
        raise AnswerFailed("out of quota")
        yield ""

    monkeypatch.setattr(appraise, "stream_answer", away)
    assert await appraise.better_summary(desk, (await desk.idea(idea.id))) is False  # type: ignore[arg-type]

    again = await desk.idea(idea.id)
    assert again is not None and again.summary == inbox.fallback_summary(long)


@pytest.mark.unit
async def test_a_card_whose_whole_text_fits_is_not_retried_for_ever(desk: Store) -> None:
    """The fallback is the first line, cut. If nothing was cut there is nothing to improve, and
    asking a model every minute for the same answer is what a bound is for."""
    from agent_desk.ideas import appraise

    idea = await desk.create_idea(text_="add hotkeys", summary="add hotkeys", source_kind="typed")

    assert appraise._still_a_truncation(await desk.idea(idea.id)) is False  # type: ignore[arg-type]


# --- a list of tickets, not one -------------------------------------------------------------------
@pytest.mark.unit
def test_an_idea_can_be_broken_into_tickets() -> None:
    """ "Каждая идея при апруве преобразуется как минимум в часть документации, как максимум в
    перечень тикетов" — именно перечень, а не один тикет.

    That is the difference between "we wrote it down" and "we planned it"."""
    from agent_desk.store.repo import DRAFT_KINDS

    assert "tickets" in DRAFT_KINDS
    assert "tickets" in inbox.PROMPTS


@pytest.mark.unit
def test_the_cut_is_the_one_that_can_be_finished_on_its_own() -> None:
    """The same rule this repository uses for its own commits. A big idea filed as one ticket is a
    ticket nobody can finish."""
    idea = Idea(
        id="01M1X",
        block_id=None,
        text="rework the console and also add hotkeys",
        summary="rework the console",
        state="kept",
        source_kind="typed",
        source_ref=None,
        context={},
        created_at=1,
    )

    said = inbox.tickets_prompt(idea)

    assert "finished on their own" in said
    assert "rework the console and also add hotkeys" in said


@pytest.mark.unit
def test_an_idea_that_is_one_piece_gets_one_ticket_and_says_so() -> None:
    """A list of one dressed up as three is worse than no list."""
    idea = Idea(
        id="01M1X",
        block_id=None,
        text="add hotkeys",
        summary="add hotkeys",
        state="kept",
        source_kind="typed",
        source_ref=None,
        context={},
        created_at=1,
    )

    said = inbox.tickets_prompt(idea)

    assert "one ticket and say so" in said


@pytest.mark.unit
def test_it_is_offered_only_once_somebody_has_kept_the_idea() -> None:
    """The step between a thought and a plan is somebody deciding it is worth doing."""
    markup = (
        pathlib.Path(__file__).resolve().parents[2]
        / "agent_desk"
        / "web"
        / "templates"
        / "_blocks.html"
    ).read_text(encoding="utf-8")
    at = markup.index('{% if idea.state in ("kept", "promoted") %}')
    around = markup[at : markup.index("{% endif %}", at + 100)]

    assert "/tickets" in around


# --- what deleting one does to everything pointing at it ------------------------------------------
@pytest.mark.unit
async def test_nothing_written_down_is_not_an_idea(desk: Store) -> None:
    """The asymmetry of 039 is about a bare "билд", which is a note somebody wrote to themselves
    and costs nobody anything. A row with no words at all is not that: it is a line in the pool its
    own author cannot recognise, and nine callers guarding it is eight more than the one function
    that should."""
    for nothing in ("", "   ", "\n\t\n"):
        with pytest.raises(ValueError, match="nothing written"):
            await inbox.capture(desk, nothing)


@pytest.mark.unit
async def test_a_bare_word_from_a_person_is_still_an_idea(desk: Store) -> None:
    """The other half of the same rule, and the reason the guard above is about emptiness only."""
    made = await inbox.capture(desk, "билд")

    assert made.summary == "билд"


@pytest.mark.unit
async def test_deleting_an_idea_leaves_its_children_as_ideas_of_their_own(desk: Store) -> None:
    """A message that turned out to be three thoughts is a parent with children (docs/05-ideas.md),
    and removing the message must not depend on nobody having kept one of them.

    Found by probing: this raised `FOREIGN KEY constraint failed`, which reached the console as a
    500 from "this was not an idea — answer it instead".
    """
    whole = await inbox.capture(desk, "add A, B is broken, and we should C")
    kids = [await inbox.capture(desk, part, parent_id=whole.id) for part in ("add A", "fix B")]
    await desk.set_idea_state(kids[1].id, "kept")

    await desk.delete_idea(whole.id)

    assert await desk.idea(whole.id) is None
    left = await desk.idea(kids[1].id)
    assert left is not None, "an idea somebody kept was taken with its parent"
    assert left.parent_id is None, "it still points at a parent that is gone"


@pytest.mark.unit
async def test_an_idea_that_was_filed_is_not_deleted(desk: Store) -> None:
    """A filing says an issue exists in somebody else's tracker, and this row is the only record
    this console has of it. Losing that to a correction is worse than leaving a line in the pool.

    Filing sets the state to `done` two lines later in the route that files, so this is belt as
    well as braces — but the braces are an ordering in another file.
    """
    made = await inbox.capture(desk, "worth filing")
    await desk.record_filing(idea_id=made.id, tracker="jira", issue_key="AB-1", url="http://x/")

    await desk.delete_idea(made.id)

    assert await desk.idea(made.id) is not None


@pytest.mark.unit
async def test_an_idea_somebody_drafted_is_not_deleted(desk: Store) -> None:
    made = await inbox.capture(desk, "worth drafting")
    await desk.create_draft(idea_id=made.id, kind="proposal", body="a proposal")

    await desk.delete_idea(made.id)

    assert await desk.idea(made.id) is not None
