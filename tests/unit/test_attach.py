"""Adding a project by pointing at it (agent_desk/observe/attach.py).

The property that matters most is the boring one: a project added this way and the same project
discovered when a session starts in it must be *one* project.
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk.observe import attach
from agent_desk.observe.shape import repository_of


@pytest.mark.unit
def test_a_remote_gets_the_key_a_checkout_of_it_would_get() -> None:
    """Otherwise a project added by URL and the same project discovered later are two rows that
    look identical and share nothing."""
    for said in (
        "git@github.com:ArgenTimo/agent-desk.git",
        "git@github.com:ArgenTimo/agent-desk",
        "https://github.com/ArgenTimo/agent-desk",
        "https://github.com/ArgenTimo/agent-desk.git",
        "ssh://git@github.com/ArgenTimo/agent-desk.git",
    ):
        pointed = attach.read(said)
        assert pointed.ok, said
        assert pointed.repo_key == "origin:ArgenTimo/agent-desk", said
        assert pointed.name == "agent-desk"
        assert pointed.url.startswith("https://")


@pytest.mark.unit
def test_a_folder_gets_the_board_s_own_answer_rather_than_a_second_one(
    tmp_path: pathlib.Path,
) -> None:
    """`repository_of` is what the board files a session under, and this asks it rather than
    inventing a parallel key."""
    pointed = attach.read(str(tmp_path))

    assert pointed.ok
    assert pointed.repo_key == repository_of(str(tmp_path)).key
    assert pointed.path == str(tmp_path)
    assert pointed.url == ""


@pytest.mark.unit
def test_a_folder_that_is_not_there_says_so_now_rather_than_later(
    tmp_path: pathlib.Path,
) -> None:
    """A path that is not there is a typo, and saying so now is cheaper than a project card that
    never fills in."""
    pointed = attach.read(str(tmp_path / "nope"))

    assert not pointed.ok
    assert "is not a folder on this machine" in pointed.detail


@pytest.mark.unit
def test_a_relative_path_is_refused_because_relative_to_what() -> None:
    pointed = attach.read("some/where")

    assert not pointed.ok
    assert "full path" in pointed.detail


@pytest.mark.unit
def test_a_url_that_names_no_repository_is_told_apart_from_a_folder() -> None:
    """Otherwise it would be looked for on disk and reported as a missing folder, which is a
    confusing thing to be told about a URL."""
    pointed = attach.read("https://example.com")

    assert not pointed.ok
    assert "not one naming a repository" in pointed.detail


@pytest.mark.unit
def test_nothing_typed_is_not_an_error_worth_a_stack_trace() -> None:
    assert attach.read("   ").detail == "nothing was typed"


@pytest.mark.unit
def test_it_never_fetches_creates_or_writes() -> None:
    """This program records where a repository lives; it does not clone it (CLAUDE.md, rule two)."""
    # Against the code rather than the prose: the module docstring says "it will not fetch it,
    # create it, or write a line into it", which a naive search for those words would trip over.
    import ast

    tree = ast.parse(pathlib.Path(attach.__file__).read_text())
    imported = {
        node.module.split(".")[0] if isinstance(node, ast.ImportFrom) and node.module else ""
        for node in ast.walk(tree)
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "subprocess" not in imported
    assert "urllib" not in imported
    assert "socket" not in imported
    for writing in ("mkdir", "write_text", "open", "unlink", "rmtree"):
        assert writing not in used, writing
