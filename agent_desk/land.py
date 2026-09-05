"""Merge what an agent finished, when the repository's own gate says it is safe (docs/adr/0008).

The fourth door out of this program, and it has the same shape as the other three: importable only
from `agent_desk/web/`, and it does one thing.

docs/adr/0008 shipped with "it never merges — every result is a branch somebody reads", and named
that as the clause not to relax. The owner relaxed it, and what replaced the review is mechanical
rather than a smaller version of the same promise: **nothing lands that the project's own gate
fails.** That is a weaker guarantee about taste and a stronger one about breakage, and it is
checkable, which a promise about reading is not.

Five things it refuses to do, and each is the shape of a mess somebody would have to unpick:

- **A dirty checkout.** Merging into a working tree with uncommitted changes in it puts somebody
  else's half-finished work into a merge commit.
- **A branch that is not there.** A session that never made one, or made one and it was removed.
- **A branch that changed nothing.** An agent that found nothing worth fixing is a good outcome
  (docs/adr/0008), and an empty merge commit is noise pretending otherwise.
- **A gate that fails, or that cannot be run.** Not a judgement: the project's own command, its
  own exit code.
- **A merge that conflicts.** It is undone immediately and the branch is left where it was.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# The whole of a landing is bounded: a gate that hangs must not hold a queue open all night.
GATE_TIMEOUT_SECONDS = 900.0
GIT_TIMEOUT_SECONDS = 120.0
# A fresh worktree usually has no dependencies installed in it, and installing them is slower than
# running them.
INSTALL_TIMEOUT_SECONDS = 900.0

# What a repository's own gate is called, in the order they are looked for. `make verify` is this
# project's, and a repository with neither is not landed automatically — there is nothing to check
# it with, and "no gate" is not the same as "passes".
# Resolved once, on the PATH of the process that started this console — the same `git` and `make`
# a person would get in that shell. Not an absolute path in a constant: this program runs on
# somebody's laptop, not in an image whose layout it decided.
GIT = shutil.which("git") or "git"
MAKE = shutil.which("make") or "make"

GATES: tuple[tuple[str, ...], ...] = (
    (MAKE, "verify"),
    (MAKE, "gate"),
    (MAKE, "test"),
)


@dataclass(frozen=True)
class Landed:
    """What happened, in words the console can show against the task."""

    landed: bool
    detail: str = ""
    branch: str = ""


def branch_for(worktree_name: str) -> str:
    """The branch `claude --bg --worktree <name>` puts the work on.

    Recorded here rather than guessed at the call site: it is the CLI's convention, it is checked
    against a real session in the tests, and when it changes this is the one line that moves.
    """
    return f"worktree-{worktree_name}"


def worktree_for(cwd: str, worktree_name: str) -> Path:
    """Where that branch is checked out: inside the repository, under `.claude/worktrees/`."""
    return Path(cwd) / ".claude" / "worktrees" / worktree_name


def _git(cwd: Path | str, *args: str, timeout: float = GIT_TIMEOUT_SECONDS) -> tuple[int, str]:
    try:
        done = subprocess.run(  # noqa: S603 — a list, no shell, and the binary is resolved above
            [GIT, *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}"
    return done.returncode, (done.stdout + done.stderr).strip()


def _theirs(status: str) -> bool:
    """Is anything in `git status` somebody's own uncommitted work?

    The worktrees the CLI makes live *inside* the repository, so a checkout with an agent in it
    reads as dirty to a plain status — and this program may not fix that by editing a `.gitignore`
    in a repository it only watches (CLAUDE.md). So the directory the CLI itself creates is
    discounted, and everything else counts.
    """
    lines = [line for line in status.splitlines() if line.strip()]
    return any(".claude/worktrees/" not in line for line in lines)


def _make(where: Path, target: str, timeout: float) -> tuple[int, str]:
    try:
        done = subprocess.run(  # noqa: S603 — a list, no shell, and the binary is resolved above
            [MAKE, target],
            cwd=str(where),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "it did not finish in time"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, type(exc).__name__
    return done.returncode, (done.stdout + done.stderr).strip()


def _gate(where: Path) -> tuple[bool, str]:
    """Run the repository's own gate in the worktree. Its command, its exit code, no judgement.

    A worktree is a fresh directory, so the dependencies are usually not installed in it yet: a
    Python project keyed by path has no environment there, and its gate fails on a missing runner
    rather than on the work. So `make install` runs first where the repository has one — its own
    command again, and a repository that does not have one simply does not get it.
    """
    if not (where / "Makefile").exists():
        return False, "no Makefile, so there is no gate to check this against"

    code, said = _make(where, "install", INSTALL_TIMEOUT_SECONDS)
    if code != 0 and "No rule to make target" not in said and "no rule to make target" not in said:
        return False, f"`make install` failed: {said.splitlines()[-1][:200] if said else ''}"

    for command in GATES:
        code, said = _git(where, "rev-parse", "--git-dir")  # cheap check that it is a checkout
        if code != 0:
            return False, "not a checkout any more"
        try:
            done = subprocess.run(  # noqa: S603 — a list, no shell
                list(command),
                cwd=str(where),
                capture_output=True,
                text=True,
                timeout=GATE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, f"`make {command[-1]}` did not finish in fifteen minutes"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"`make {command[-1]}` could not run: {type(exc).__name__}"
        if done.returncode == 0:
            return True, f"`make {command[-1]}` passed"
        # A target this repository does not have is not a failure; the next one is tried.
        if "No rule to make target" in done.stderr or "no rule to make target" in done.stderr:
            continue
        tail = (done.stdout + done.stderr).strip().splitlines()
        return False, f"`make {command[-1]}` failed: {tail[-1][:200] if tail else 'no output'}"
    return False, "this repository has no verify, gate or test target"


def land(cwd: str, worktree_name: str, *, push: bool = True) -> Landed:
    """Merge one finished agent's branch into the checkout it came from.

    Never raises: this is called from a loop, and a loop that dies on a bad merge takes the console
    with it.
    """
    branch = branch_for(worktree_name)
    repository = Path(cwd)
    if not (repository / ".git").exists():
        return Landed(False, "that project is not a git checkout", branch)

    code, _ = _git(repository, "rev-parse", "--verify", f"refs/heads/{branch}")
    if code != 0:
        return Landed(
            False, "there is no branch: it made no changes, or its worktree is gone", branch
        )

    # `--untracked-files=all` so that an agent's worktree reads as the files inside it rather than
    # as one `?? .claude/` line, which would be indistinguishable from somebody's own new folder.
    code, dirty = _git(repository, "status", "--porcelain", "--untracked-files=all")
    if code == 0 and _theirs(dirty):
        return Landed(False, "the checkout has uncommitted changes, so nothing was merged", branch)

    code, ahead = _git(repository, "rev-list", "--count", f"HEAD..{branch}")
    if code != 0 or ahead.strip() in ("", "0"):
        return Landed(False, "it committed nothing — a good outcome, and nothing to merge", branch)

    where = worktree_for(cwd, worktree_name)
    if not where.is_dir():
        return Landed(False, "its worktree is gone, so its work cannot be checked", branch)

    passed, said = _gate(where)
    if not passed:
        return Landed(False, f"not merged: {said}", branch)

    code, merged = _git(repository, "merge", "--no-ff", "-m", f"agent: {worktree_name}", branch)
    if code != 0:
        # Undone at once: a repository left mid-merge is a repository nobody else can use.
        _git(repository, "merge", "--abort")
        first = merged.splitlines()[0] if merged else "it conflicted"
        return Landed(False, f"not merged: {first[:200]}", branch)

    if push:
        code, pushed = _git(repository, "push", "origin", "HEAD")
        if code != 0:
            first = pushed.splitlines()[-1] if pushed else "the push failed"
            return Landed(True, f"merged here, not pushed: {first[:200]}", branch)
    return Landed(True, f"merged and pushed — {said}", branch)
