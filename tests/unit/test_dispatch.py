"""The third door: starting an agent on a written instruction (docs/adr/0006).

The rules this file exists to hold are the ones an innocent-looking convenience would break: the
permission flags, the worktree, the click, and once.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import dispatch
from agent_desk.config import Settings
from agent_desk.store.repo import Store
from agent_desk.web import routes


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _fake_cli(tmp_path: pathlib.Path, script: str) -> pathlib.Path:
    """A stand-in for the CLI. The real one starts a session; these only print like it."""
    binary = tmp_path / "cli" / "claude"
    binary.parent.mkdir(exist_ok=True)
    binary.write_text(script)
    binary.chmod(0o755)
    return binary


@pytest.mark.unit
def test_the_command_never_carries_a_flag_that_hands_over_the_machine() -> None:
    """docs/adr/0006: an agent that cannot ask a human for permission is an agent nobody is
    standing behind. The check is a string search, which is crude and exactly right for a rule
    that must never be true."""
    command = dispatch.argv("do the thing", worktree="a-name")

    for flag in dispatch.NEVER:
        assert flag not in command
    assert not any("skip-permissions" in part for part in command)
    assert not any("bypassPermissions" in part for part in command)


@pytest.mark.unit
def test_the_work_happens_in_a_worktree_of_its_own() -> None:
    """The observed checkout is not where a dispatched agent works — that is the substance of
    CLAUDE.md's second rule surviving this ADR."""
    command = dispatch.argv("do the thing", worktree="fix-the-ports")

    assert "--bg" in command
    assert "--worktree" in command
    assert command[command.index("--worktree") + 1] == "fix-the-ports"
    assert command[-1] == "do the thing"


@pytest.mark.unit
def test_a_name_becomes_a_directory_so_it_is_shaped_like_one() -> None:
    assert dispatch._worktree_name("Tell Biba to test it again!") == "tell-biba-to-test-it-again"
    assert dispatch._worktree_name("  ---  ") == "desk-task"
    assert dispatch._worktree_name("a" * 80) == "a" * 40
    assert "/" not in dispatch._worktree_name("../../etc/passwd")


@pytest.mark.unit
def test_a_russian_name_survives_as_something_the_cli_will_accept() -> None:
    """The CLI exits 1 before the model starts on a worktree name outside `[A-Za-z0-9._-]`, and
    `str.isalnum` is true for every alphabet — which is how six dispatched agents died at once."""
    assert dispatch._worktree_name("берём в работу") == "berem-v-rabotu"
    assert dispatch._worktree_name("проанализируй jira") == "proanaliziruy-jira"
    # Anything with no letter to transliterate to still yields a name, never an empty one.
    assert dispatch._worktree_name("刷新 ✨") == "desk-task"
    for typed in ("берём в работу", "Сейчас доска заточена под нетехнического заказчика", "汉字"):
        name = dispatch._worktree_name(typed)
        assert name and name.isascii()
        assert all(character.isalnum() or character in "._-" for character in name)
        assert not name.startswith("-") and not name.endswith("-")


@pytest.mark.unit
def test_the_id_is_read_from_the_line_that_names_one() -> None:
    """The CLI prints a help block after it, and a format that grows a line must not break this."""
    assert dispatch._read_id("backgrounded · 79586f63\n  claude agents  list\n") == "79586f63"
    assert dispatch._read_id("Starting\nbackgrounded · abc12345\n") == "abc12345"
    assert dispatch._read_id("something else entirely") == ""


@pytest.mark.unit
def test_nothing_is_started_when_there_is_nothing_to_start(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatch, "settings", Settings(claude_bin="not-installed-anywhere"))

    assert not dispatch.start("  ", cwd=str(tmp_path), name="x").started
    assert "nothing written" in dispatch.start("  ", cwd=str(tmp_path), name="x").detail

    gone = dispatch.start("do it", cwd=str(tmp_path / "not-here"), name="x")
    assert not gone.started
    assert "not a directory" in gone.detail

    missing = dispatch.start("do it", cwd=str(tmp_path), name="x")
    assert not missing.started
    assert "not installed" in missing.detail


@pytest.mark.unit
def test_the_cli_saying_no_is_reported_rather_than_swallowed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dirty worktree, a name in use — the CLI says useful things and they reach the person."""
    binary = _fake_cli(
        tmp_path,
        "#!/bin/sh\necho 'fatal: a worktree named that already exists' >&2\nexit 128\n",
    )
    monkeypatch.setattr(dispatch, "settings", Settings(claude_bin=str(binary)))

    result = dispatch.start("do it", cwd=str(tmp_path), name="a name")

    assert not result.started
    assert "already exists" in result.detail


@pytest.mark.unit
def test_a_started_agent_reports_its_id(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _fake_cli(
        tmp_path, "#!/bin/sh\nprintf 'Starting\\nbackgrounded \\302\\267 1a2b3c4d\\n'\n"
    )
    monkeypatch.setattr(dispatch, "settings", Settings(claude_bin=str(binary)))

    result = dispatch.start("test everything again", cwd=str(tmp_path), name="test everything")

    assert result.started
    assert result.agent_id == "1a2b3c4d"


@pytest.mark.unit
def test_what_the_agent_is_told_carries_the_context_and_not_the_console(
    tmp_path: pathlib.Path,
) -> None:
    """It is a session starting cold in a repository: it needs what was asked and what it is
    about, and none of the machinery that asked it (docs/adr/0006)."""
    task = dispatch.build_task(
        "add a CSV export to the board",
        project="agent-desk",
        branch="main",
        notes=["- the board should remember which sessions hit their limit"],
    )

    assert "add a CSV export to the board" in task
    assert "agent-desk" in task
    assert "the board should remember" in task
    # Its own conventions are the ones that apply: this says where to read them, not what they are.
    assert "CLAUDE.md" in task
    # And it is told the one thing it cannot find out for itself.
    assert "cannot be asked anything once you start" in task


@pytest.mark.unit
async def test_an_instruction_starts_one_agent_and_only_one(desk: Store) -> None:
    """A second click is two agents in two worktrees editing one repository."""
    block = await desk.create_block(
        thread_id=(await desk.create_thread("s")).id,
        kind="instruction",
        input="test it again",
        thread_set_by="human",
    )
    directive = await desk.record_directive(
        block_id=block.id, session_id="s-1", session_name="alpha · alpha-d0", text_="test it again"
    )
    assert directive.agent_id is None

    await desk.mark_directive_dispatched(directive.id, "1a2b3c4d")
    await desk.mark_directive_dispatched(directive.id, "9z8y7x6w")

    again = await desk.directive(directive.id)
    assert again is not None
    assert again.agent_id == "1a2b3c4d"
    assert again.dispatched_at is not None


@pytest.mark.unit
def test_stopping_an_agent_asks_the_cli_and_reports_what_it_said(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its conversation is kept — `claude attach` opens it again — so this is not a delete."""
    binary = _fake_cli(tmp_path, '#!/bin/sh\ntest "$1" = stop && echo stopped $2\n')
    monkeypatch.setattr(dispatch, "settings", Settings(claude_bin=str(binary)))

    assert dispatch.stop("1a2b3c4d").started is True

    refusing = _fake_cli(tmp_path, "#!/bin/sh\necho 'no such session' >&2\nexit 1\n")
    monkeypatch.setattr(dispatch, "settings", Settings(claude_bin=str(refusing)))
    said = dispatch.stop("nope")
    assert not said.started
    assert "no such session" in said.detail

    monkeypatch.setattr(dispatch, "settings", Settings(claude_bin="not-installed-anywhere"))
    missing = dispatch.stop("nope")
    assert not missing.started
    assert "could not stop it" in missing.detail


@pytest.mark.unit
def test_a_started_agent_that_prints_nothing_useful_is_not_a_success(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit nought and no id is the CLI having changed under this, which is loud rather than
    plausible (docs/adr/0004, one layer out)."""
    binary = _fake_cli(tmp_path, "#!/bin/sh\necho 'started, probably'\n")
    monkeypatch.setattr(dispatch, "settings", Settings(claude_bin=str(binary)))

    result = dispatch.start("do it", cwd=str(tmp_path), name="x")

    assert not result.started
    assert "started, probably" in result.detail


@pytest.mark.unit
def test_an_introduction_says_what_it_is_for_and_what_it_cannot_ask(tmp_path: pathlib.Path) -> None:
    bare = dispatch.introduce("biba", project="alpha")
    assert "You are biba, working in alpha" in bare
    assert "Start by reading" in bare
    assert "cannot be asked anything once you begin" in bare
    assert "The environment this project expects" not in bare

    full = dispatch.introduce("biba", project="alpha", doing="the api half", env_names=["A", "B"])
    assert "What you are here for: the api half" in full
    assert "A, B" in full


@pytest.mark.unit
def test_continuing_a_session_uses_the_cli_s_own_door() -> None:
    """`--bg --resume <id>` "continues that session in the background under the same ID". The full
    id, not the short one: `--resume` takes the first and `stop` takes the second."""
    command = dispatch.resume_argv("abc12345-1111-4222-8333-444444444444", "carry on")

    assert "--bg" in command
    assert command[command.index("--resume") + 1] == "abc12345-1111-4222-8333-444444444444"
    assert command[-1] == "carry on"
    assert not [flag for flag in command if flag in dispatch.NEVER]


@pytest.mark.unit
def test_a_kick_stops_the_session_first_because_resume_needs_it_stopped(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI: "`claude --resume` works once it is stopped". A `--bg` session that has finished a
    turn is still running — it idles at its prompt with its process alive."""
    calls: list[list[str]] = []

    class Done:
        returncode = 0
        stdout = "backgrounded · abc12345\n"
        stderr = ""

    monkeypatch.setattr(dispatch.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(
        dispatch.subprocess, "run", lambda command, **kw: (calls.append(command), Done())[1]
    )

    result = dispatch.kick(
        "abc12345-1111-4222-8333-444444444444", "carry on", cwd=str(tmp_path), agent_id="abc12345"
    )

    assert result.started
    assert calls[0][1:] == ["stop", "abc12345"]
    assert "--resume" in calls[1]


@pytest.mark.unit
def test_a_kick_with_nothing_to_say_or_nowhere_to_go_is_refused(tmp_path: pathlib.Path) -> None:
    assert not dispatch.kick("an-id", "   ", cwd=str(tmp_path)).started
    assert not dispatch.kick("", "carry on", cwd=str(tmp_path)).started
    assert not dispatch.kick("an-id", "carry on", cwd=str(tmp_path / "gone")).started


@pytest.mark.unit
def test_a_limit_is_told_apart_from_something_being_broken() -> None:
    """It decides whether a refusal becomes a wait or counts towards two failures. Loose on
    purpose: this is the one shape here not recorded from a real occurrence."""
    assert dispatch.looks_like_a_limit("usage limit reached · resets at 14:00")
    assert dispatch.looks_like_a_limit("You have hit your rate limit")
    assert dispatch.looks_like_a_limit("out of quota for now")
    assert not dispatch.looks_like_a_limit("Error creating worktree: Invalid worktree name")
    assert not dispatch.looks_like_a_limit("")
