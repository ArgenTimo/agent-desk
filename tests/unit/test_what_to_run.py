"""Which tests could be about this change, and the sentence that keeps it from being a gate.

«За смену я прогнал `make verify` больше тридцати раз, по четыре с лишним минуты. Это часы стенных
часов, потраченные почти всегда на то, чтобы узнать про два-три файла.»
"""

from __future__ import annotations

import pathlib

import pytest
from agent_desk import narrowing

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]


# --- the diff, in names rather than in line numbers ----------------------------------------------
def test_the_changed_lines_come_off_the_new_side() -> None:
    """The new side, because that is what is on disk to be parsed."""
    diff = "--- a/x.py\n+++ b/x.py\n@@ -3,0 +4,2 @@\n+one\n+two\n"

    assert narrowing.changed_lines(diff) == {"x.py": {4, 5}}


def test_a_deletion_moves_the_count_on_without_naming_a_line() -> None:
    diff = "--- a/x.py\n+++ b/x.py\n@@ -3,2 +3,1 @@\n-gone\n context\n+added\n"

    assert narrowing.changed_lines(diff) == {"x.py": {4}}


def test_a_changed_line_is_named_by_what_encloses_it(tmp_path: pathlib.Path) -> None:
    """ "Разбор изменённых символов из диффа через ast, а не по строкам." A line number moves when
    somebody adds an import; what the line is inside is what a test names."""
    source = "def one():\n    return 1\n\n\ndef two():\n    return 2\n"

    assert narrowing.symbols_at(source, {2}) == {"one"}
    assert narrowing.symbols_at(source, {6}) == {"two"}


def test_a_change_belonging_to_no_name_at_all_is_the_whole_file() -> None:
    """An import, a decorator, a stray statement. Module level is what everything in the file is
    built on, and narrowing there is guessing."""
    source = "import os\n\n\ndef one():\n    return os\n\n\ndef two():\n    return 2\n"

    assert narrowing.symbols_at(source, {1}) == {"one", "two"}


def test_a_constant_is_a_name_like_any_other() -> None:
    """`ALIKE = 0.82` is a thing a test names, and a change to it is about the tests that do."""
    source = "ALIKE = 0.82\n\n\ndef one():\n    return ALIKE\n"

    assert narrowing.symbols_at(source, {1}) == {"ALIKE"}


def test_a_file_that_does_not_parse_narrows_to_nothing() -> None:
    """Which the caller reads as "run everything": the honest answer about a file this cannot
    reason about is the widest one."""
    assert narrowing.symbols_at("def (:", {1}) == set()


def test_something_that_is_not_python_puts_every_test_in(tmp_path: pathlib.Path) -> None:
    """A template, a stylesheet, the console's script. This cannot narrow by any of them."""
    diff = "--- a/x.css\n+++ b/x.css\n@@ -1,0 +2,1 @@\n+.pin { color: red }\n"

    changed = narrowing.read_the_diff(diff, root=tmp_path)

    assert changed.opaque == frozenset({"x.css"})


# --- the reverse index ---------------------------------------------------------------------------
def test_a_test_names_what_it_imports_calls_and_reaches() -> None:
    """ "Обратный индекс: какой тест называет какой символ.\" """
    said = "from agent_desk.looking import as_lines\n\n\ndef test_it():\n    assert as_lines([])\n"

    assert "as_lines" in narrowing.names_in(said)


def test_a_structural_test_names_things_in_strings() -> None:
    """Those are the tests most worth running on a change to the thing they name, and exactly the
    ones an index built only from imports misses."""
    said = 'def test_it():\n    assert "carried_from_the_bench" in source\n'

    assert "carried_from_the_bench" in narrowing.names_in(said)


def test_only_the_tests_naming_a_changed_symbol_are_wanted(tmp_path: pathlib.Path) -> None:
    """ "Не покрытие и не угадывание: какие символы изменились и какие тесты их называют.\" """
    changed = narrowing.Changed(
        files=frozenset({"agent_desk/looking.py"}),
        symbols=frozenset({"as_lines"}),
        opaque=frozenset(),
    )
    tests = {
        "tests/test_looking.py": "from agent_desk.looking import as_lines\nx = as_lines\n",
        "tests/test_other.py": "from agent_desk.ties import KINDS\nx = KINDS\n",
    }

    wanted, _ = narrowing.what_to_run(changed, tests)

    assert wanted == ["tests/test_looking.py"]


def test_a_name_too_common_to_mean_anything_pulls_nothing_in() -> None:
    """A test that says `text` is not a test about `agent_desk.something.text`, and treating it as
    one would put every test in every answer — which is the gate with extra steps."""
    changed = narrowing.Changed(
        files=frozenset({"x.py"}), symbols=frozenset({"text"}), opaque=frozenset()
    )
    tests = {"tests/test_other.py": "from agent_desk.ties import KINDS\ntext = 1\n"}

    wanted, _ = narrowing.what_to_run(changed, tests)

    assert wanted == []


# --- and what is always in ------------------------------------------------------------------------
def test_a_test_that_imports_nothing_from_the_package_is_always_run() -> None:
    """It is about a template or the console's script, and no symbol in a diff will name it."""
    changed = narrowing.Changed(
        files=frozenset({"x.py"}), symbols=frozenset({"nothing_here"}), opaque=frozenset()
    )
    tests = {"tests/test_page.py": 'x = open("board.html").read()\n'}

    wanted, always = narrowing.what_to_run(changed, tests)

    assert wanted == always == ["tests/test_page.py"]


def test_a_test_that_walks_a_directory_is_always_run() -> None:
    """The rule it asserts holds over whatever is there, so a change anywhere is a change it is
    about. This was the one that was missed: the file holding every structural rule in this
    repository, left out because it happens to import the package it walks."""
    changed = narrowing.Changed(
        files=frozenset({"x.py"}), symbols=frozenset({"nothing_here"}), opaque=frozenset()
    )
    tests = {
        "tests/test_structure.py": (
            "from agent_desk.config import settings\n"
            "def test_it():\n"
            "    for one in PKG.rglob('*.py'):\n"
            "        assert one\n"
        )
    }

    wanted, always = narrowing.what_to_run(changed, tests)

    assert always == ["tests/test_structure.py"]
    assert wanted == always


def test_reading_a_fixture_does_not_make_a_test_structural() -> None:
    """Nearly every test reads one. Counting that put a hundred and four of a hundred and
    twenty-eight files in the always list, which is the gate wearing a different name."""
    said = "from agent_desk.observe import transcript\nx = (HERE / 'one.jsonl').read_text()\n"

    assert narrowing._names_anything(said)


# --- and it is never the gate -----------------------------------------------------------------------
def test_what_it_prints_says_how_many_were_not_run() -> None:
    """ "Сообщение узкого прогона говорит, сколько тестов НЕ прогонялось. Иначе через неделю
    кто-нибудь назовёт его зелёным.\" """
    said = narrowing.as_text(["tests/test_one.py"], [], every=40)

    assert "NOT the gate" in said
    assert "39 test files were not run" in said
    assert "make verify" in said


def test_the_target_exists_and_is_not_part_of_verify() -> None:
    """Both are wanted and the difference between them has to be in the words. A narrow run inside
    `verify` would be `verify` claiming to have run what it did not."""
    makefile = (HERE / "Makefile").read_text(encoding="utf-8")

    assert "what-to-run:" in makefile
    assert "what-to-run" not in makefile.split("verify:")[1].splitlines()[0]


def test_it_narrows_this_repository_to_something_worth_narrowing() -> None:
    """Run against a one-symbol change to a real module: if this answered with most of the suite
    it would be a slower way to run the gate."""
    diff = (
        "--- a/agent_desk/looking.py\n+++ b/agent_desk/looking.py\n"
        "@@ -140,0 +141,1 @@\n+def as_lines(look_):\n"
    )
    changed = narrowing.read_the_diff(diff, root=HERE)
    tests = {
        str(one.relative_to(HERE)): one.read_text(encoding="utf-8")
        for one in sorted((HERE / "tests").rglob("test_*.py"))
    }

    wanted, always = narrowing.what_to_run(changed, tests)

    assert changed.symbols == frozenset({"as_lines"})
    assert len(wanted) < len(tests) // 3
    assert "tests/unit/test_structure.py" in wanted
