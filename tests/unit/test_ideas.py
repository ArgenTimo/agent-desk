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
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

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
            blocks.runs.cancel_all()
            blocks.runs.attach(None)
    await store.close()


async def _settle(check: object, tries: int = 60) -> None:
    for _ in range(tries):
        if await check():  # type: ignore[operator]
            return
        await asyncio.sleep(0.1)


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
    """docs/05: keep or discard, one click. Anything more and the tool is competing with the run."""
    await blocks.submit(desk, "/idea a thought", [])
    card = await routes.render_blocks()

    assert "Idea recorded" in card
    assert "Keep it?" in card
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
    """`promoted` is one of the four states, and the second number docs/09 says is measured."""
    await blocks.submit(desk, "/idea cache the probes", [])
    (idea,) = await desk.ideas()

    await _card_post(f"/ideas/{idea.id}/paste", {})

    stored = await desk.idea(idea.id)
    assert stored is not None
    assert stored.state == "promoted"
    assert [d.kind for d in await desk.drafts_for(idea.id)] == ["paste"]


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
    assert "Idea recorded" in html  # the block column, not the inbox
