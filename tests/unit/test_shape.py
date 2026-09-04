"""What the sessions on this machine add up to.

The board was a flat list because the registry is one. A person has projects, each of which is one
or more checkouts, each of which may have a console or two open, and each of those may have farmed
work out. Every one of those levels is derived rather than declared — a level somebody had to keep
up to date would be wrong the first time they forgot.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from agent_desk.observe.model import Session, TranscriptTail
from agent_desk.observe.shape import repository_of
from agent_desk.observe.transcript import read_tail
from agent_desk.store.repo import Group
from agent_desk.web.routes import AttentionHint, BoardRow, shape

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


def _row(cwd: str, session_id: str = "s", waiting: bool = False) -> BoardRow:
    entry: dict[str, Any] = json.loads((FIXTURES / "registry_entry.json").read_text())
    entry.update(cwd=cwd, sessionId=session_id)
    return BoardRow(
        session=Session.model_validate(entry),
        tail=None,
        hint=AttentionHint(waiting=waiting, observation="idle 1m · last entry: assistant"),
    )


# --- what a directory belongs to ----------------------------------------------------------------
@pytest.mark.unit
def test_a_directory_with_no_git_is_its_own_project(tmp_path: pathlib.Path) -> None:
    """Which is right for a folder somebody is working in without git, and stops this from
    pretending it knows something it does not."""
    repo = repository_of(str(tmp_path / "scratch"))
    assert repo.key.startswith("dir:")
    assert repo.name == "scratch"
    assert repo.origin is None


@pytest.mark.unit
def test_two_clones_of_one_repository_are_one_project(tmp_path: pathlib.Path) -> None:
    """The default grouping, and the reason nobody has to declare the common case."""
    for name in ("one", "two"):
        checkout = tmp_path / name / ".git"
        checkout.mkdir(parents=True)
        (checkout / "config").write_text(
            '[remote "origin"]\n\turl = git@github.com:owner/product.git\n'
        )

    first = repository_of(str(tmp_path / "one"))
    second = repository_of(str(tmp_path / "two"))
    assert first.key == second.key
    assert first.name == "owner/product"


@pytest.mark.unit
def test_a_worktree_belongs_to_the_checkout_it_came_from(tmp_path: pathlib.Path) -> None:
    """A worktree's `.git` is a file pointing back at the repository, which is what stops one
    branch of one project from looking like a project of its own."""
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "feature").mkdir(parents=True)
    (main / ".git" / "config").write_text('[remote "origin"]\n\turl = https://x.example/o/p\n')

    worktree = tmp_path / "feature"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'feature'}\n")

    assert repository_of(str(worktree)).key == repository_of(str(main)).key
    assert repository_of(str(worktree)).name == "o/p"


@pytest.mark.unit
def test_a_repository_with_no_remote_is_still_one_repository(tmp_path: pathlib.Path) -> None:
    """This repository has no origin, and two worktrees of it still have to be one project."""
    checkout = tmp_path / "local" / ".git"
    checkout.mkdir(parents=True)
    (checkout / "config").write_text("[core]\n\tbare = false\n")

    repo = repository_of(str(tmp_path / "local"))
    assert repo.key.startswith("git:")
    assert repo.origin is None


# --- folding the board --------------------------------------------------------------------------
@pytest.mark.unit
def test_two_consoles_in_one_folder_are_one_instance(tmp_path: pathlib.Path) -> None:
    rows = [_row(str(tmp_path / "alpha"), "a"), _row(str(tmp_path / "alpha"), "b")]

    (project,) = shape(rows, [])
    (instance,) = project.instances
    assert len(instance.rows) == 2
    assert instance.name == "alpha"


@pytest.mark.unit
def test_a_declared_project_holds_repositories_the_default_would_have_separated(
    tmp_path: pathlib.Path,
) -> None:
    """The case the default cannot know: an API and an app in two repositories, one product."""
    api, app = tmp_path / "api", tmp_path / "app"
    for path, origin in ((api, "owner/api"), (app, "owner/ios")):
        (path / ".git").mkdir(parents=True)
        (path / ".git" / "config").write_text(
            f'[remote "origin"]\n\turl = git@github.com:{origin}.git\n'
        )

    rows = [_row(str(api), "a"), _row(str(app), "b")]
    assert len(shape(rows, [])) == 2

    group = Group(
        id="g1",
        name="The product",
        created_at=0,
        repo_keys=["origin:owner/api", "origin:owner/ios"],
    )
    (project,) = shape(rows, [group])
    assert project.name == "The product"
    assert project.sessions == 2
    assert {instance.name for instance in project.instances} == {"api", "app"}


@pytest.mark.unit
def test_a_project_is_as_urgent_as_its_most_urgent_session(tmp_path: pathlib.Path) -> None:
    """The board's order is who needs a human first, and folding must not lose it."""
    calm = _row(str(tmp_path / "calm"), "calm")
    urgent = _row(str(tmp_path / "urgent"), "urgent", waiting=True)

    projects = shape([urgent, calm], [])
    assert [project.name for project in projects] == ["urgent", "calm"]
    assert projects[0].flagged == 1


@pytest.mark.unit
def test_every_row_knows_which_card_it_ended_up_under(tmp_path: pathlib.Path) -> None:
    """A question aimed at a card has to find its sessions, and rebuilding the shape to answer
    that would be a second chance to disagree with the board the human is looking at."""
    (project,) = shape([_row(str(tmp_path / "alpha"), "a")], [])
    row = project.instances[0].rows[0]

    assert row.project_key == project.key
    assert row.project_name == project.name


# --- what a session farmed out --------------------------------------------------------------------
@pytest.mark.unit
def test_the_subagents_a_session_started_are_visible(tmp_path: pathlib.Path) -> None:
    """A session farms work out with the `Agent` tool, and the tail carries both halves: the call
    with its type and description, and the result that says it came back."""
    root = tmp_path / "projects" / "-somewhere"
    root.mkdir(parents=True)
    lines = [
        {
            "type": "assistant",
            "isSidechain": False,
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Agent",
                        "input": {
                            "subagent_type": "Explore",
                            "description": "inventory the skills",
                            "prompt": "a long prompt nobody needs on a card",
                        },
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_2",
                        "name": "Agent",
                        "input": {"subagent_type": "reviewer", "description": "review the diff"},
                    },
                ],
            },
        },
        {
            "type": "user",
            "isSidechain": False,
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "done"}],
            },
        },
    ]
    (root / "s.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))

    tail = read_tail("s", root=tmp_path / "projects")
    assert tail is not None
    assert [(agent.kind, agent.running) for agent in tail.agents] == [
        ("reviewer", True),
        ("Explore", False),
    ]
    assert tail.agents[0].description == "review the diff"
    # The prompt it was given is the session's business, not a card's.
    assert "a long prompt" not in str(tail.agents)


@pytest.mark.unit
def test_a_session_that_farmed_out_nothing_says_nothing(tmp_path: pathlib.Path) -> None:
    tail = TranscriptTail(session_id="s")
    assert tail.agents == []
