"""Merging what an agent finished, and the five times it refuses to (docs/adr/0008).

Real repositories in a temporary directory rather than a mock of git: what is being tested is
whether a merge happens, and a stubbed `git` would prove only that this file agrees with itself.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest
from agent_desk import land


def _run(where: pathlib.Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603
        list(args), cwd=where, capture_output=True, text=True, check=False
    )
    return (done.stdout + done.stderr).strip()


def _repo(tmp_path: pathlib.Path, *, gate_passes: bool = True) -> pathlib.Path:
    """A checkout with a Makefile whose `verify` does what the test needs it to."""
    root = tmp_path / "project"
    root.mkdir()
    _run(root, "git", "init", "-q", "-b", "main", ".")
    _run(root, "git", "config", "user.email", "t@t")
    _run(root, "git", "config", "user.name", "t")
    (root / "Makefile").write_text(
        "verify:\n\t@" + ("true" if gate_passes else "echo 'a test failed' && false") + "\n"
    )
    (root / "README.md").write_text("a project\n")
    _run(root, "git", "add", "-A")
    _run(root, "git", "commit", "-qm", "init")
    return root


def _agent_worked(root: pathlib.Path, name: str, *, change: bool = True) -> None:
    """What a dispatched agent leaves behind: a worktree under `.claude/worktrees/`."""
    where = land.worktree_for(str(root), name)
    where.parent.mkdir(parents=True, exist_ok=True)
    _run(root, "git", "worktree", "add", "-q", "-b", land.branch_for(name), str(where))
    if change:
        (where / "fixed.md").write_text("the thing it found\n")
        _run(where, "git", "add", "-A")
        _run(where, "git", "commit", "-qm", "fix the thing it found")


@pytest.mark.unit
def test_a_branch_that_passes_the_gate_is_merged(tmp_path: pathlib.Path) -> None:
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")

    result = land.land(str(root), "found-project", push=False)

    assert result.landed, result.detail
    assert "`make verify` passed" in result.detail
    assert (root / "fixed.md").exists()
    assert "agent: found-project" in _run(root, "git", "log", "-1", "--pretty=%s")


@pytest.mark.unit
def test_a_branch_that_fails_the_gate_is_left_alone(tmp_path: pathlib.Path) -> None:
    """Not a judgement: the project's own command and its own exit code."""
    root = _repo(tmp_path, gate_passes=False)
    _agent_worked(root, "found-project")

    result = land.land(str(root), "found-project", push=False)

    assert not result.landed
    assert "`make verify` failed" in result.detail
    assert not (root / "fixed.md").exists()
    # The branch is exactly where it was, for somebody to look at.
    assert land.branch_for("found-project") in _run(root, "git", "branch", "--list")


@pytest.mark.unit
def test_a_dirty_checkout_is_never_merged_into(tmp_path: pathlib.Path) -> None:
    """Somebody else's half-finished work does not belong in a merge commit."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    (root / "README.md").write_text("edited, and not committed\n")

    result = land.land(str(root), "found-project", push=False)

    assert not result.landed
    assert "uncommitted changes" in result.detail
    assert not (root / "fixed.md").exists()


@pytest.mark.unit
def test_an_agent_that_found_nothing_leaves_nothing_to_merge(tmp_path: pathlib.Path) -> None:
    """Finding nothing worth changing is a good outcome, and an empty merge commit is noise."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project", change=False)

    result = land.land(str(root), "found-project", push=False)

    assert not result.landed
    assert "committed nothing" in result.detail


@pytest.mark.unit
def test_a_branch_that_is_not_there_is_not_an_error(tmp_path: pathlib.Path) -> None:
    root = _repo(tmp_path)

    result = land.land(str(root), "never-ran", push=False)

    assert not result.landed
    assert "no branch" in result.detail


@pytest.mark.unit
def test_a_repository_with_no_gate_is_not_landed_automatically(tmp_path: pathlib.Path) -> None:
    """ "No gate" is not the same as "passes"."""
    root = _repo(tmp_path)
    (root / "Makefile").unlink()
    _run(root, "git", "add", "-A")
    _run(root, "git", "commit", "-qm", "no gate here")
    _agent_worked(root, "found-project")

    result = land.land(str(root), "found-project", push=False)

    assert not result.landed
    assert "no gate" in result.detail or "no Makefile" in result.detail


@pytest.mark.unit
def test_a_conflict_is_undone_rather_than_left_half_merged(tmp_path: pathlib.Path) -> None:
    """A repository left mid-merge is a repository nobody else can use."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    where = land.worktree_for(str(root), "found-project")
    (where / "README.md").write_text("the agent's version\n")
    _run(where, "git", "commit", "-aqm", "and it touched the readme")
    (root / "README.md").write_text("and so did somebody here\n")
    _run(root, "git", "commit", "-aqm", "a change on main")

    result = land.land(str(root), "found-project", push=False)

    assert not result.landed
    assert "not merged" in result.detail
    assert not (root / ".git" / "MERGE_HEAD").exists()
    assert "and so did somebody here" in (root / "README.md").read_text()


@pytest.mark.unit
def test_a_directory_that_is_not_a_checkout_is_refused(tmp_path: pathlib.Path) -> None:
    result = land.land(str(tmp_path), "found-project", push=False)

    assert not result.landed
    assert "not a git checkout" in result.detail


@pytest.mark.unit
def test_the_branch_name_is_the_cli_s_convention_written_down_once() -> None:
    """Checked against a real `claude --bg --worktree` session: the branch is `worktree-<name>`
    and the checkout is `<repo>/.claude/worktrees/<name>`. When that changes, one line moves."""
    assert land.branch_for("found-project") == "worktree-found-project"
    assert land.worktree_for("/repo", "found-project") == pathlib.Path(
        "/repo/.claude/worktrees/found-project"
    )


@pytest.mark.unit
def test_a_gate_that_hangs_is_given_up_on(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate that never returns must not hold the queue open all night."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    monkeypatch.setattr(land, "GATE_TIMEOUT_SECONDS", 0.2)
    (land.worktree_for(str(root), "found-project") / "Makefile").write_text(
        "verify:\n\t@sleep 30\n"
    )

    result = land.land(str(root), "found-project", push=False)

    assert not result.landed
    assert "did not finish" in result.detail


@pytest.mark.unit
def test_a_repository_whose_only_target_is_test_is_still_checked(
    tmp_path: pathlib.Path,
) -> None:
    """`verify`, `gate`, `test` — the first one this repository actually has."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    (land.worktree_for(str(root), "found-project") / "Makefile").write_text("test:\n\t@true\n")

    result = land.land(str(root), "found-project", push=False)

    assert result.landed, result.detail
    assert "`make test` passed" in result.detail


@pytest.mark.unit
def test_a_worktree_that_has_been_removed_is_not_landed_blind(tmp_path: pathlib.Path) -> None:
    """Its work cannot be checked, so it is not merged — the branch stays for a person."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    _run(
        root,
        "git",
        "worktree",
        "remove",
        "--force",
        str(land.worktree_for(str(root), "found-project")),
    )

    result = land.land(str(root), "found-project", push=False)

    assert not result.landed
    assert "worktree is gone" in result.detail


@pytest.mark.unit
def test_a_merge_that_cannot_be_pushed_is_still_a_merge(
    tmp_path: pathlib.Path,
) -> None:
    """It landed here; the remote is a separate problem and the console says which happened."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")

    result = land.land(str(root), "found-project", push=True)

    assert result.landed
    assert "not pushed" in result.detail
    assert (root / "fixed.md").exists()


@pytest.mark.unit
def test_the_dependencies_are_installed_before_the_gate_is_believed(
    tmp_path: pathlib.Path,
) -> None:
    """A worktree is a fresh directory: a project keyed by path has no environment in it yet, and
    its gate would fail on a missing runner rather than on the work."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    where = land.worktree_for(str(root), "found-project")
    # `verify` only passes once `install` has been run: the file it looks for is made by it.
    (where / "Makefile").write_text(
        "install:\n\t@touch .installed\nverify:\n\t@test -f .installed\n"
    )

    result = land.land(str(root), "found-project", push=False)

    assert result.landed, result.detail
    assert "`make verify` passed" in result.detail


@pytest.mark.unit
def test_an_install_that_fails_stops_before_the_gate(tmp_path: pathlib.Path) -> None:
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    (land.worktree_for(str(root), "found-project") / "Makefile").write_text(
        "install:\n\t@echo 'no network' && false\nverify:\n\t@true\n"
    )

    result = land.land(str(root), "found-project", push=False)

    assert not result.landed
    assert "`make install` failed" in result.detail


@pytest.mark.unit
def test_a_git_that_is_not_there_is_a_refusal_rather_than_a_crash(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`land` is called from a loop. A loop that dies on a missing binary takes the console."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    monkeypatch.setattr(
        land.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no git here")),
    )

    result = land.land(str(root), "found-project", push=False)

    assert not result.landed
    assert result.detail


@pytest.mark.unit
def test_a_gate_that_cannot_be_run_at_all_is_not_a_pass(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Could not run it" and "it passed" must never be the same outcome."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    where = land.worktree_for(str(root), "found-project")

    real = land.subprocess.run

    def make_explodes(command, **kwargs):  # type: ignore[no-untyped-def]
        if command and command[0] == land.MAKE:
            raise OSError("make is not installed")
        return real(command, **kwargs)

    monkeypatch.setattr(land.subprocess, "run", make_explodes)

    passed, said = land._gate(where)

    assert not passed
    assert "could not run" in said or "install" in said


@pytest.mark.unit
def test_a_worktree_that_stopped_being_a_checkout_is_not_gated(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Somebody removed it between the agent finishing and this running."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    where = land.worktree_for(str(root), "found-project")
    monkeypatch.setattr(land, "_git", lambda *args, **kwargs: (1, "not a git repository"))

    passed, said = land._gate(where)

    assert not passed
    assert "not a checkout" in said


@pytest.mark.unit
def test_a_repository_whose_gate_says_nothing_at_all_still_fails_clearly(
    tmp_path: pathlib.Path,
) -> None:
    """A gate that exits non-zero and prints nothing is the least helpful failure there is, so the
    message says which target it was rather than nothing."""
    root = _repo(tmp_path)
    _agent_worked(root, "found-project")
    (land.worktree_for(str(root), "found-project") / "Makefile").write_text("verify:\n\t@exit 1\n")

    result = land.land(str(root), "found-project", push=False)

    assert not result.landed
    assert "`make verify` failed" in result.detail
