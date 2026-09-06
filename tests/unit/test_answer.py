"""The answer engine, against a fake `claude` that is a real executable.

A fake rather than a mock, for the reason `.claude/skills/fakes-over-mocks` gives: what is under
test here is a subprocess — its argv, its stdin, its exit code and its clock — and a mock of
`create_subprocess_exec` would assert that this module calls a function, which is not the same
statement as "the prompt never reaches argv".
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import time
from collections.abc import AsyncIterator

import pytest
from agent_desk.answer import session
from agent_desk.config import Settings
from agent_desk.store.repo import Block, Store

FAKE = """#!/bin/sh
here=$(dirname "$0")
printf '%s\\n' "$@" > "$here/argv.txt"
prompt=$(cat)
printf '%s' "$prompt" > "$here/stdin.txt"
case "$prompt" in
  *PLEASE_HANG*)
    sleep 30 &
    echo $! > "$here/child.pid"
    wait ;;
  *PLEASE_CRASH*) printf '{"type":"system","subtype":"init"}\\n'; exit 3 ;;
  *PLEASE_ERROR*) printf '{"type":"result","subtype":"error_during_execution","is_error":true}\\n' ;;
  *PLEASE_GARBLE*)
    printf 'this line is not json\\n'
    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"still answered"}]}}\\n' ;;
  *ONLY_RESULT*)
    printf '{"type":"result","subtype":"success","is_error":false,"result":"summarised"}\\n' ;;
  *)
    printf '{"type":"system","subtype":"init"}\\n'
    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"it retries twice "}]}}\\n'
    printf '{"type":"assistant","message":{"content":[{"type":"text","text":"and gives up"}]}}\\n'
    printf '{"type":"result","subtype":"success","is_error":false,"result":"it retries twice and gives up"}\\n' ;;
esac
"""


@pytest.fixture
def fake_claude(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    binary = tmp_path / "fake-cli" / "claude"
    binary.parent.mkdir()
    binary.write_text(FAKE)
    binary.chmod(0o755)
    monkeypatch.setattr(
        session,
        "settings",
        Settings(claude_bin=str(binary), answer_timeout_seconds=2.0),
    )
    return binary


@pytest.fixture
async def store(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


async def _block(store: Store) -> Block:
    thread = await store.create_thread("a subject")
    return await store.create_block(
        thread_id=thread.id, kind="question", input="?", thread_set_by="human"
    )


def _argv(fake: pathlib.Path) -> list[str]:
    return (fake.parent / "argv.txt").read_text().splitlines()


# --- the two properties that are not incidental --------------------------------------------
@pytest.mark.unit
async def test_the_prompt_arrives_on_stdin_and_never_in_argv(
    fake_claude: pathlib.Path, store: Store
) -> None:
    """docs/07-security.md: transcript text never goes into a subprocess argument.

    /proc/<pid>/cmdline is readable by anyone on this machine — including the board that drew the
    tail this prompt is made of.
    """
    secret_shaped_context = "the session pasted DATABASE_URL into its terminal"
    await session.answer_block(store, await _block(store), secret_shaped_context)

    assert (fake_claude.parent / "stdin.txt").read_text() == secret_shaped_context
    assert not any(secret_shaped_context in argument for argument in _argv(fake_claude))


@pytest.mark.unit
async def test_the_run_is_given_no_way_to_write(fake_claude: pathlib.Path, store: Store) -> None:
    """Rule two of CLAUDE.md, as four flags rather than as a hope."""
    await session.answer_block(store, await _block(store), "a question")
    argv = _argv(fake_claude)

    assert "--restricted" in argv
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    for tool in ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "WebFetch"):
        assert tool in argv[argv.index("--disallowedTools") :]
        assert tool not in argv[argv.index("--allowedTools") : argv.index("--disallowedTools")]


@pytest.mark.unit
async def test_the_observed_repositories_are_offered_to_the_run(
    fake_claude: pathlib.Path, store: Store, tmp_path: pathlib.Path
) -> None:
    """docs/04: a block is answered with read access to the repositories being observed."""
    await session.answer_block(
        store, await _block(store), "a question", add_dirs=[tmp_path / "repo-a"]
    )
    argv = _argv(fake_claude)
    assert argv[argv.index("--add-dir") + 1] == str(tmp_path / "repo-a")


# --- the lifecycle -------------------------------------------------------------------------
@pytest.mark.unit
async def test_a_streamed_answer_reaches_the_store_whole(
    fake_claude: pathlib.Path, store: Store
) -> None:
    block = await _block(store)
    await session.answer_block(store, block, "what about timeouts")

    answered = await store.block(block.id)
    assert answered is not None
    assert answered.state == "answered"
    assert answered.answer == "it retries twice and gives up"


@pytest.mark.unit
async def test_a_run_that_exits_badly_leaves_a_block_that_says_why(
    fake_claude: pathlib.Path, store: Store
) -> None:
    block = await _block(store)
    await session.answer_block(store, block, "PLEASE_CRASH")

    failed = await store.block(block.id)
    assert failed is not None
    assert failed.state == "failed"
    assert "exited 3" in (failed.error or "")


@pytest.mark.unit
async def test_a_result_marked_as_an_error_is_a_failure(
    fake_claude: pathlib.Path, store: Store
) -> None:
    block = await _block(store)
    await session.answer_block(store, block, "PLEASE_ERROR")

    failed = await store.block(block.id)
    assert failed is not None
    assert failed.state == "failed"
    assert "error_during_execution" in (failed.error or "")


@pytest.mark.unit
async def test_a_line_this_program_cannot_read_does_not_lose_the_answer(
    fake_claude: pathlib.Path, store: Store
) -> None:
    """The CLI's stream is not a contract either; an unreadable line is not evidence of failure."""
    block = await _block(store)
    await session.answer_block(store, block, "PLEASE_GARBLE")

    answered = await store.block(block.id)
    assert answered is not None
    assert answered.state == "answered"
    assert answered.answer == "still answered"


@pytest.mark.unit
async def test_a_run_that_only_summarises_itself_still_answers(
    fake_claude: pathlib.Path, store: Store
) -> None:
    block = await _block(store)
    await session.answer_block(store, block, "ONLY_RESULT")

    answered = await store.block(block.id)
    assert answered is not None
    assert answered.answer == "summarised"


@pytest.mark.unit
async def test_a_run_that_never_answers_is_bounded_by_the_timeout(
    fake_claude: pathlib.Path, store: Store
) -> None:
    """There is no --max-turns in the CLI, so this clock is the only bound there is."""
    block = await _block(store)
    started = time.monotonic()
    await session.answer_block(store, block, "PLEASE_HANG")
    elapsed = time.monotonic() - started

    failed = await store.block(block.id)
    assert failed is not None
    assert failed.state == "failed"
    assert "no answer within" in (failed.error or "")
    # The fake sleeps for thirty seconds; the point is that this did not.
    assert elapsed < 10


@pytest.mark.unit
async def test_killing_the_process_is_not_enough_and_the_children_go_too(
    fake_claude: pathlib.Path, store: Store
) -> None:
    """`claude` spawns children and they inherit the pipes.

    Measured before this was fixed: the timeout fired at 2s, the parent was killed at 2s, and the
    task then sat inside `wait()` for another 28 — because a grandchild still held stdout open.
    The run is started in its own session and ended as a group, so the claim in this module's
    docstring — that a cancelled block leaves no headless Claude behind — is true.
    """
    await session.answer_block(store, await _block(store), "PLEASE_HANG")

    child = int((fake_claude.parent / "child.pid").read_text().strip())
    await asyncio.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


@pytest.mark.unit
async def test_cancelling_a_block_records_it_and_does_not_leave_a_run_behind(
    fake_claude: pathlib.Path, store: Store
) -> None:
    block = await _block(store)
    task = asyncio.create_task(session.answer_block(store, block, "PLEASE_HANG"))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    cancelled = await store.block(block.id)
    assert cancelled is not None
    assert cancelled.state == "cancelled"


@pytest.mark.unit
async def test_an_absent_cli_is_needs_toolchain_and_not_a_crash(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/02-architecture.md, failure posture: the board still works without the CLI."""
    monkeypatch.setattr(session, "settings", Settings(claude_bin="claude-that-is-not-installed"))
    block = await _block(store)
    await session.answer_block(store, block, "a question")

    failed = await store.block(block.id)
    assert failed is not None
    assert failed.state == "failed"
    assert "needs_toolchain" in (failed.error or "")


# --- what a block is answered from ---------------------------------------------------------
@pytest.mark.unit
def test_the_prompt_carries_the_board_the_thread_and_the_question() -> None:
    prompt = session.build_prompt(
        "is duck-129 pushed",
        board=['llm-developer-2 · boba/duck-129 · busy · "Docker client" · 2m ago'],
        history=[("what about timeouts", "it retries twice")],
    )
    assert "boba/duck-129" in prompt
    assert "what about timeouts" in prompt
    assert "it retries twice" in prompt
    assert "is duck-129 pushed" in prompt


@pytest.mark.unit
def test_the_prompt_says_what_to_do_when_the_evidence_does_not_settle_it() -> None:
    """docs/04: where a block cannot tell, it says so and names the session to go look at."""
    prompt = session.build_prompt("anything", board=[], history=[])
    assert "name the session" in prompt
    assert "(no live sessions)" in prompt


@pytest.mark.unit
async def test_the_parser_reads_a_recorded_run_rather_than_an_idea_of_one(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    """docs/adr/0004, applied to the stream this program's own subprocess emits.

    The fake here is a script that prints `tests/fixtures/stream_json.jsonl`, recorded from one
    real `claude --print --output-format stream-json`. It contains a `rate_limit_event` line that
    nobody would have thought to write, and the parser has to walk past it to the answer.
    """
    fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "stream_json.jsonl"
    binary = tmp_path / "recorded" / "claude"
    binary.parent.mkdir()
    binary.write_text(f'#!/bin/sh\ncat > /dev/null\ncat "{fixture}"\n')
    binary.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(binary)))

    block = await _block(store)
    await session.answer_block(store, block, "reply with the word ok")

    answered = await store.block(block.id)
    assert answered is not None
    assert answered.state == "answered"
    assert answered.answer == "ok"


# --- the deny rules the run had lost --------------------------------------------------------
@pytest.mark.unit
def test_the_run_is_handed_the_deny_rules_restricted_mode_switched_off() -> None:
    """docs/07-security.md names `.claude/settings.json` as the mechanism, not the prose.

    `--restricted` says in its own help that it "ignores user, project and local settings files
    (managed settings and --settings still apply)" — so the one process on this machine that
    reads observed repositories, with `Read` pre-approved over every directory `--add-dir` hands
    it, was the one process those deny rules did not reach. A block asking why a client fails to
    authenticate could have read a `.env` and streamed it into its own answer.
    """
    import json as json_

    command = session.argv()
    assert "--strict-mcp-config" in command

    denials = json_.loads(command[command.index("--settings") + 1])
    denied = denials["permissions"]["deny"]
    assert any(rule.startswith("Read(") and ".env" in rule for rule in denied)
    assert any("credentials" in rule for rule in denied)
    assert any("sessions/" in rule for rule in denied)


@pytest.mark.unit
async def test_the_deny_rules_reach_the_real_command_line(
    fake_claude: pathlib.Path, store: Store
) -> None:
    """Not merely present in a helper: present in what was executed."""
    await session.answer_block(store, await _block(store), "a question")
    argv = _argv(fake_claude)

    assert "--settings" in argv
    assert ".env" in argv[argv.index("--settings") + 1]


@pytest.mark.unit
async def test_a_noisy_run_is_not_reported_as_a_silent_one(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    """stderr used to be a pipe nobody read, so a run that wrote to it blocked on the kernel
    buffer while this program waited on stdout — and the timeout stored "no answer" for a run
    that had one. A status inferred from a silence this program caused itself.
    """
    binary = tmp_path / "noisy" / "claude"
    binary.parent.mkdir()
    binary.write_text(
        "#!/bin/sh\ncat > /dev/null\n"
        "i=0; while [ $i -lt 4000 ]; do printf 'mcp chatter %s\\n' \"$i\" >&2; i=$((i+1)); done\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"answered anyway"}]}}\\n\'\n'
    )
    binary.chmod(0o755)
    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(binary), answer_timeout_seconds=10.0)
    )

    block = await _block(store)
    await session.answer_block(store, block, "a question")

    answered = await store.block(block.id)
    assert answered is not None
    assert answered.state == "answered"
    assert answered.answer == "answered anyway"


@pytest.mark.unit
async def test_a_failed_run_says_more_than_its_exit_code(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    """Discarding stderr made every failure read "the run exited 3" and nothing else — which is a
    console telling you something went wrong and refusing to say what."""
    binary = tmp_path / "complaining" / "claude"
    binary.parent.mkdir()
    binary.write_text(
        "#!/bin/sh\ncat > /dev/null\necho 'error: model provider returned 429' >&2\nexit 3\n"
    )
    binary.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(binary)))

    block = await _block(store)
    await session.answer_block(store, block, "a question")

    failed = await store.block(block.id)
    assert failed is not None
    assert failed.state == "failed"
    assert "exited 3" in (failed.error or "")
    assert "429" in (failed.error or "")


@pytest.mark.unit
async def test_what_a_run_complains_about_is_scrubbed_too(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    """A diagnostic line can quote anything the tool that printed it decided to print."""
    secret = "ghp_" + "k" * 36
    binary = tmp_path / "leaky-stderr" / "claude"
    binary.parent.mkdir()
    binary.write_text(f"#!/bin/sh\ncat > /dev/null\necho 'auth failed for {secret}' >&2\nexit 4\n")
    binary.chmod(0o755)
    monkeypatch.setattr(session, "settings", Settings(claude_bin=str(binary)))

    block = await _block(store)
    await session.answer_block(store, block, "a question")

    failed = await store.block(block.id)
    assert failed is not None
    assert secret not in (failed.error or "")


@pytest.mark.unit
async def test_a_noisy_run_still_does_not_deadlock(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, store: Store
) -> None:
    """The reason stderr was discarded in the first place: a pipe nobody reads fills up."""
    binary = tmp_path / "very-noisy" / "claude"
    binary.parent.mkdir()
    binary.write_text(
        "#!/bin/sh\ncat > /dev/null\n"
        "i=0; while [ $i -lt 8000 ]; do printf 'chatter %s\\n' \"$i\" >&2; i=$((i+1)); done\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"answered"}]}}\\n\'\n'
    )
    binary.chmod(0o755)
    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(binary), answer_timeout_seconds=10.0)
    )

    block = await _block(store)
    await session.answer_block(store, block, "a question")

    answered = await store.block(block.id)
    assert answered is not None
    assert answered.state == "answered"
    assert answered.answer == "answered"


# --- a second engine, for when the first one is not there (docs/08-non-goals.md) -----------------
UNAVAILABLE_CLI = """#!/bin/sh
cat > /dev/null
echo "You have hit your usage limit" >&2
exit 1
"""

LOCAL_CLI = """#!/bin/sh
cat > /dev/null
printf '{"type":"assistant","message":{"content":[{"type":"text","text":"the local one answered"}]}}\\n'
"""

REFUSING_CLI = """#!/bin/sh
cat > /dev/null
printf '{"type":"assistant","message":{"content":[{"type":"text","text":"I can not help with that."}]}}\\n'
"""


def _binary(where: pathlib.Path, name: str, script: str) -> pathlib.Path:
    binary = where / name
    binary.write_text(script)
    binary.chmod(0o755)
    return binary


@pytest.mark.unit
async def test_a_second_engine_answers_when_the_first_is_out_of_budget(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unavailable is out of budget, not installed, or unreachable — a different thing from an
    answer somebody did not like."""
    first = _binary(tmp_path, "claude", UNAVAILABLE_CLI)
    second = _binary(tmp_path, "local-model", LOCAL_CLI)
    monkeypatch.setattr(
        session,
        "settings",
        Settings(claude_bin=str(first), local_model_bin=str(second), answer_timeout_seconds=10.0),
    )

    said = "".join([chunk async for chunk in session.stream_answer("a question")])

    assert said == "the local one answered"


@pytest.mark.unit
async def test_a_refusal_is_an_answer_and_can_never_reach_the_second_engine(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property this feature stands on, and it is structural rather than a rule to remember:
    a refusal arrives as text, nothing raises, and there is no path from here to a fallback
    (docs/08-non-goals.md)."""
    first = _binary(tmp_path, "claude", REFUSING_CLI)
    second = _binary(tmp_path, "local-model", LOCAL_CLI)
    monkeypatch.setattr(
        session,
        "settings",
        Settings(claude_bin=str(first), local_model_bin=str(second), answer_timeout_seconds=10.0),
    )

    said = "".join([chunk async for chunk in session.stream_answer("a question")])

    assert said == "I can not help with that."
    assert "local" not in said


@pytest.mark.unit
def test_only_the_engine_being_unavailable_is_worth_a_second_try() -> None:
    for said in (
        "You have hit your usage limit",
        "needs_toolchain: claude is not on PATH",
        "no answer within 180s",
        "could not reach it",
    ):
        assert session.unavailable(said), said

    for said in (
        "I can not help with that",
        "the run exited 3",
        "the run reported an error",
        "",
    ):
        assert not session.unavailable(said), said


@pytest.mark.unit
async def test_an_answer_that_has_begun_is_never_started_again(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retry after text has streamed would repeat itself, so it does not happen."""
    # It streams, then reports an error — which raises even though it said something, because a
    # `result` event saying `is_error` is the run telling you the answer is not one. A non-zero
    # exit *after* text has streamed does not raise at all: it answered.
    half = """#!/bin/sh
cat > /dev/null
printf '{"type":"assistant","message":{"content":[{"type":"text","text":"half an ans"}]}}\\n'
printf '{"type":"result","is_error":true,"subtype":"usage limit reached"}\\n'
"""
    first = _binary(tmp_path, "claude", half)
    second = _binary(tmp_path, "local-model", LOCAL_CLI)
    monkeypatch.setattr(
        session,
        "settings",
        Settings(claude_bin=str(first), local_model_bin=str(second), answer_timeout_seconds=10.0),
    )

    said = []
    with pytest.raises(session.AnswerFailed):
        async for chunk in session.stream_answer("a question"):
            said.append(chunk)

    assert said == ["half an ans"]


@pytest.mark.unit
async def test_with_no_second_engine_nothing_changes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which is every install until somebody sets one."""
    first = _binary(tmp_path, "claude", UNAVAILABLE_CLI)
    monkeypatch.setattr(
        session, "settings", Settings(claude_bin=str(first), answer_timeout_seconds=10.0)
    )

    with pytest.raises(session.AnswerFailed, match="exited 1"):
        async for _ in session.stream_answer("a question"):
            pass
