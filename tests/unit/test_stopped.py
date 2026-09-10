"""Saying "no, and here is why" so that it cannot be scrolled past (01M1XC4Z1301… and 01M1XC1DCJ9D…).

"Отказ, падение, лимит, недоступный коннектор должны становиться карточкой на верстаке рядом с тем,
что их вызвало, а не строчкой в логе или молчанием."

"Это самая важная часть всей идеи… Сегодня отказ выглядит как обычный ответ, а значит читается как
обычный ответ."
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import telling

WEB = pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "web"


# --- what stopped, and what would change it ------------------------------------------------------
@pytest.mark.unit
def test_a_failure_is_said_in_words_and_comes_with_a_next_step() -> None:
    """What a run reports is written for whoever wrote the runner. Each of these is true and none
    of them says what to do, which is the half a person needs at the moment something stopped."""
    what, act = telling.stopped("the day's budget is spent: $30.00 of $25.00")

    assert "budget" in what.lower() and "$" not in what
    assert "AGENT_DESK_DAILY_USD" in act


@pytest.mark.unit
def test_the_failures_this_program_can_actually_produce_are_all_covered() -> None:
    """Not a general translator — a list of the things that actually stop this console, each
    with the one thing that changes it."""
    for error, expected in (
        ("needs_toolchain: claude is not on PATH", "not on this machine"),
        ("the answer engine could not be started: claude — Text file busy", "would not start"),
        ("rate limit reached", "rate limited"),
        ("usage limit reached for this account", "out of budget"),
        ("no answer within 180s", "longer than it is allowed"),
        ("the run was killed (SIGKILL)", "killed before it answered"),
    ):
        what, act = telling.stopped(error)
        assert expected in what, error
        assert act, f"{error} suggests nothing"


@pytest.mark.unit
def test_a_failure_nobody_has_met_keeps_its_own_words_and_suggests_nothing() -> None:
    """Inventing a next step for a failure this program has never seen is exactly the guess the
    fifth rule forbids. Saying nothing reads as "something went wrong and this console does not
    know what to suggest", which is honest and visibly different from the ones it does know."""
    what, act = telling.stopped("the run exited 4")

    assert what == "the run exited 4"
    assert act == ""


@pytest.mark.unit
def test_a_failure_that_said_nothing_still_says_something() -> None:
    """Silence is the one thing worse than jargon."""
    what, act = telling.stopped("")

    assert what and act == ""


# --- and it looks like a refusal -----------------------------------------------------------------
@pytest.mark.unit
def test_only_a_run_that_actually_stopped_shouts() -> None:
    """A block that reached an end *and* left something in `error` behind it is not a refusal.

    Found in a browser: an answered block carrying a stale `error` of "success" rendered as a red
    box. Shouting at somebody about a run that finished is how they learn to scroll past the ones
    that did not — which is the exact failure this whole change is against.
    """
    said = (WEB / "templates" / "_blocks.html").read_text(encoding="utf-8")

    assert '{% elif block.state in ("failed", "cancelled") and block.error %}' in said
    assert said.index('block.state in ("failed", "cancelled") and block.error') < said.index(
        "{% elif block.error %}"
    ), "the quiet branch comes first, so nothing reaches the loud one"


@pytest.mark.unit
def test_the_refusal_is_the_only_block_that_changes_colour_all_the_way_through() -> None:
    """Every other state on this page is a line down the left edge, and one more of those is one
    more thing to look for. Red already means stopped here, so nothing is overloaded."""
    css = (WEB / "static" / "console.css").read_text(encoding="utf-8")

    stopped = css[css.index(".stopped {") :]
    stopped = stopped[: stopped.index("}")]
    assert "background:" in stopped and "var(--flag)" in stopped
    assert ".pin.block-card:has(.stopped)" in css, "the card on the workbench does not show it"


@pytest.mark.unit
def test_the_blockers_column_says_the_same_thing() -> None:
    """A person reading the blockers column and a person reading the conversation are the same
    person, and "the run exited 4" is no more use in one than in the other. It is why this is a
    filter rather than a value prepared once for one template."""
    said = (WEB / "blockers.py").read_text(encoding="utf-8")

    assert said.count("telling.stopped(") == 2, (
        "a failure reaching the blockers column in the runner's own words again"
    )


@pytest.mark.unit
async def test_a_blocker_for_a_failed_question_reads_like_a_sentence() -> None:
    """End to end, because the two halves are joined with a space and that is easy to get wrong."""
    import pathlib as _p
    import tempfile

    from agent_desk.store.repo import Store
    from agent_desk.web import blockers

    with tempfile.TemporaryDirectory() as where:
        store = Store(_p.Path(where) / "agent-desk.db")
        await store.open()
        try:
            thread = await store.create_thread("a chat")
            block = await store.create_block(
                thread_id=thread.id, kind="question", input="what now", thread_set_by="human"
            )
            await store.fail_block(block.id, "the day's budget is spent: $30.00 of $25.00")

            found = [one for one in await blockers.blockers(store) if one.kind == "answer"]
        finally:
            await store.close()

    (only,) = found
    assert only.why.startswith("The day's budget for asking is spent.")
    assert "AGENT_DESK_DAILY_USD" in only.why


# --- a block is settled once, when everything about it is written --------------------------------
@pytest.mark.unit
def test_a_dispatched_message_is_marked_before_the_block_says_answered() -> None:
    """Marked afterwards there is a window where the block reads "answered" and the message beside
    it still says nobody has taken it — and a page rendered in that window shows exactly that.

    Found as a test that failed once in a full run and passed alone: the suite polls ten times
    faster since it stopped sleeping, so the window went from unlikely to ordinary. The same rule
    `record_idea` was fixed under, in the other branch that starts work.
    """
    said = (WEB / "blocks.py").read_text(encoding="utf-8")

    starting = said[said.index("async def _start_work(") :]
    starting = starting[: starting.index("\nasync def ", 10)]

    assert "mark_directive_dispatched" in starting, (
        "the message is marked outside the function that settles the block again"
    )
    # Against the settle on the *success* path. There is an earlier `finish_block` in the branch
    # where no agent could be started, and comparing with that one would pass whatever the order.
    assert starting.index("mark_directive_dispatched") < starting.index('"On it —'), (
        "the block is settled before the message beside it is marked"
    )
