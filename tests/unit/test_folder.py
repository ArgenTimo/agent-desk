"""A folder read as a list of what is in it (agent_desk/observe/folder.py).

The reading is the easy half. What matters is what it does *not* do: this program is a reader of
other people's directories (CLAUDE.md, rule two), and a folder somebody points at may hold keys,
exports or somebody else's data.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from agent_desk.observe import folder


@pytest.mark.unit
def test_it_lists_what_is_there_with_what_each_thing_is(tmp_path: pathlib.Path) -> None:
    (tmp_path / "parser.py").write_text("x = 1\n")
    (tmp_path / "notes.md").write_text("# notes\n")
    (tmp_path / "inner").mkdir()

    found = folder.read(str(tmp_path))

    assert found.ok
    names = {one.name: one for one in found.entries}
    assert names["parser.py"].kind == "python"
    assert names["notes.md"].kind == "notes"
    assert names["inner"].is_folder and names["inner"].kind == "folder"
    # Folders first, then files, each alphabetically — a list somebody scans, not a random order.
    assert found.entries[0].name == "inner"


@pytest.mark.unit
def test_it_never_opens_a_file(tmp_path: pathlib.Path) -> None:
    """The difference between listing a filename and reading it is the whole of why this is safe
    to offer for a directory that may hold anything."""
    (tmp_path / "secrets.env").write_text("TOKEN=hunter2\n")

    found = folder.read(str(tmp_path))
    assert found.ok
    assert "hunter2" not in folder.about(found)

    # And structurally: nothing in this module reads a file.
    tree = ast.parse(pathlib.Path(folder.__file__).read_text())
    called = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for reading in ("read_text", "read_bytes", "open", "walk", "rglob"):
        assert reading not in called, reading


@pytest.mark.unit
def test_hidden_things_are_left_alone(tmp_path: pathlib.Path) -> None:
    """A dotfile is usually configuration, and the ones that are not are the ones most likely to
    hold a credential."""
    (tmp_path / ".env").write_text("TOKEN=x\n")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / "visible.py").write_text("x = 1\n")

    found = folder.read(str(tmp_path))

    assert [one.name for one in found.entries] == ["visible.py"]


@pytest.mark.unit
def test_one_level_only(tmp_path: pathlib.Path) -> None:
    """Walking the whole tree of somebody's home directory because they dropped it on the
    workbench is not a feature."""
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "buried.py").write_text("x = 1\n")

    found = folder.read(str(tmp_path))

    assert [one.name for one in found.entries] == ["a"]


@pytest.mark.unit
def test_a_directory_with_four_hundred_files_is_not_a_card(tmp_path: pathlib.Path) -> None:
    for number in range(folder.MOST_ENTRIES + 20):
        (tmp_path / f"file{number:03}.txt").write_text("x")

    assert len(folder.read(str(tmp_path)).entries) == folder.MOST_ENTRIES


@pytest.mark.unit
def test_something_that_is_not_a_folder_says_so(tmp_path: pathlib.Path) -> None:
    (tmp_path / "a-file.txt").write_text("x")

    assert "not a folder" in folder.read(str(tmp_path / "a-file.txt")).detail
    assert "not a folder" in folder.read(str(tmp_path / "nope")).detail
    assert "full path" in folder.read("some/where").detail
    assert folder.read("   ").detail == "nothing was typed"


@pytest.mark.unit
def test_what_a_model_is_shown_is_names_and_kinds(tmp_path: pathlib.Path) -> None:
    """It writes a sentence about what the folder is for, from the shape of it — never from what
    is inside the files."""
    (tmp_path / "parser.py").write_text("secret contents\n")
    (tmp_path / "docs").mkdir()

    said = folder.about(folder.read(str(tmp_path)))

    assert "parser.py (python)" in said
    assert "docs/ (folder)" in said
    assert "secret contents" not in said
