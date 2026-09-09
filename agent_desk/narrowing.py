"""Which tests could possibly be about this change.

*«За смену я прогнал `make verify` больше тридцати раз, по четыре с лишним минуты. Это часы стенных
часов, потраченные почти всегда на то, чтобы узнать про два-три файла.»*

Not coverage and not a guess: which symbols the diff touched, and which test files name them.

## Approximate in one direction only

«Лучше прогнать лишнее, чем пропустить.» Every judgement here errs towards running more. A symbol
that could not be resolved widens the answer to the whole file; a test that names nothing this
program defines is always in; a changed file that is not Python puts every test in. The failure this
must never have is a test that should have run and did not, because that failure is invisible — the
run is green and the defect ships.

## Symbols from the syntax tree, not from the lines

«Разбор изменённых символов из диффа через ast, а не по строкам.» A diff hunk is a set of line
numbers, and a line number means nothing on its own: it moves when somebody adds an import. What a
changed line is *inside* is a function or a class, and that is what a test names. So the changed
lines are mapped through the file's own syntax tree onto the names that enclose them — and a change
outside every definition, at module level, is the whole file changing, because module level is what
every name in it is built on.

## This is not the gate, and it says so

«Узкий прогон никогда не отчитывается как гейт.» One rule and one sentence: what this prints says
how many tests were *not* run. A narrow run that reported like a gate would be called green by
somebody within a week, and the whole argument for having it rests on the two being told apart.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# A file header in a unified diff, and a hunk header inside it.
_FILE = re.compile(r"^\+\+\+ b/(.+)$")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# Names too common to mean anything. A test that says `id` or `text` is not a test about
# `agent_desk.something.id`, and treating it as one would put every test in every answer — which is
# the gate with extra steps.
TOO_COMMON = {"id", "at", "text", "name", "said", "when", "read", "run", "one", "two", "kind"}


@dataclass(frozen=True)
class Changed:
    """What a diff did, in names rather than in line numbers."""

    # Which files it touched at all, as they are written in the diff.
    files: frozenset[str]
    # The names it changed, from every Python file in it.
    symbols: frozenset[str]
    # Whether anything in it could not be read as Python — a template, a stylesheet, the script.
    # Something this cannot reason about at all, which is a reason to run everything.
    opaque: frozenset[str]


def changed_lines(diff: str) -> dict[str, set[int]]:
    """The line numbers a unified diff adds or changes, per file, on the new side.

    The new side because that is what is on disk to be parsed. A line the diff only deleted leaves
    nothing to name, and the definition it was deleted from is named by the lines around it.
    """
    found: dict[str, set[int]] = {}
    where = ""
    at = 0
    for line in diff.splitlines():
        named = _FILE.match(line)
        if named:
            where = named.group(1)
            found.setdefault(where, set())
            continue
        hunk = _HUNK.match(line)
        if hunk:
            at = int(hunk.group(1))
            continue
        if not where or not at:
            continue
        if line.startswith("+"):
            found[where].add(at)
            at += 1
        elif not line.startswith("-"):
            at += 1
    return found


def symbols_at(source: str, lines: set[int]) -> set[str]:
    """The names that enclose these lines, from the file's own syntax tree.

    A change that belongs to no name at all — an import, a decorator, a statement between two
    definitions — returns every name in the file: module level is what everything in it is built
    on, and narrowing there would be guessing. A constant is a name like any other and narrows to
    itself.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # A file that does not parse is a file this cannot reason about, and the honest answer is
        # the widest one.
        return set()
    named: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            named.append((node.name, node.lineno, node.end_lineno or node.lineno))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    named.append((target.id, node.lineno, node.end_lineno or node.lineno))
    inside = {name for name, first, last in named for line in lines if first <= line <= last}
    outside = {line for line in lines if not any(f <= line <= la for _, f, la in named)}
    if outside:
        return {name for name, _, _ in named}
    return inside


def names_in(source: str) -> set[str]:
    """Every name a test file mentions: what it imports, calls, or reaches through an attribute."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    said: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            said.add(node.id)
        elif isinstance(node, ast.Attribute):
            said.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            said.update(one.name for one in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A structural test names what it is about in a string — a module path, a function
            # name it greps for. Those are the tests most worth running on a change to the thing
            # they name, and they are exactly the ones an import-only index misses.
            said.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", node.value))
    return said


def read_the_diff(diff: str, *, root: Path) -> Changed:
    """Turn a unified diff into the names it changed."""
    lines = changed_lines(diff)
    symbols: set[str] = set()
    opaque: set[str] = set()
    for where, at in lines.items():
        if not where.endswith(".py"):
            opaque.add(where)
            continue
        found = root / where
        if not found.is_file():
            # Deleted, or renamed away. Nothing to parse and nothing to narrow by.
            opaque.add(where)
            continue
        got = symbols_at(found.read_text(encoding="utf-8"), at)
        if not got:
            opaque.add(where)
        symbols |= got
    return Changed(files=frozenset(lines), symbols=frozenset(symbols), opaque=frozenset(opaque))


def what_to_run(changed: Changed, tests: dict[str, str]) -> tuple[list[str], list[str]]:
    """The test files worth running, and the ones always run whatever changed.

    `tests` is each test file's path against its source. Returned separately so that what is
    printed can say which is which: a reader deciding whether to trust a narrow run wants to see
    that the structural tests are in it.
    """
    always = sorted(where for where, source in tests.items() if not _names_anything(source))
    if changed.opaque:
        # Something this cannot read. Every test, and the caller says why.
        return sorted(tests), always
    wanted = {
        where
        for where, source in tests.items()
        if names_in(source) & (changed.symbols - TOO_COMMON)
    }
    return sorted(wanted | set(always)), always


# How a test says it is about the source rather than about a symbol: it walks a directory. Not
# `read_text` — nearly every test reads a fixture, and treating that as structural put a hundred
# and four of a hundred and twenty-eight files in the "always" list, which is the gate wearing a
# different name. Walking a directory is the narrow signal: it asserts a rule over whatever is
# found there, so a change anywhere is a change it is about.
_WALKS_THE_TREE = {"rglob", "glob", "iterdir"}


def _names_anything(source: str) -> bool:
    """Whether this test is about particular symbols at all.

    «Ответ всегда включает файлы, которые ничего не называют явно — структурные тесты.» Two kinds
    are not, and both are always run:

    - a test that imports nothing from this package — it is about a template or the console's own
      script, and no symbol in a diff will ever name it;
    - a test that walks a directory and asserts a rule over what it finds — the rule holds over
      whatever is there, so a change anywhere is a change it is about.

    The second used to be missed, and the one it missed was `test_structure.py`: the test that
    holds every structural rule in this repository, left out of a narrow run because it happens to
    import the package it walks.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    imports = any(
        isinstance(node, ast.ImportFrom) and (node.module or "").startswith("agent_desk")
        for node in ast.walk(tree)
    )
    reads = any(
        isinstance(node, ast.Attribute) and node.attr in _WALKS_THE_TREE for node in ast.walk(tree)
    )
    return imports and not reads


def as_text(wanted: list[str], always: list[str], every: int) -> str:
    """What to print, including the sentence that keeps this from being called a gate.

    «Сообщение узкого прогона говорит, сколько тестов НЕ прогонялось. Иначе через неделю кто-нибудь
    назовёт его зелёным.»
    """
    left = every - len(wanted)
    said = [f"{len(wanted)} of {every} test files could be about this change."]
    said += [f"  {one}" for one in wanted]
    if always:
        said.append(
            f"{len(always)} of those name nothing in particular and are always run: "
            "they are the ones a change breaks without mentioning it."
        )
    said.append("")
    said.append(
        f"This is NOT the gate. {left} test file{'' if left == 1 else 's'} "
        f"{'was' if left == 1 else 'were'} not run. Run `make verify` before you commit."
    )
    return "\n".join(said)
