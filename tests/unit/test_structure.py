"""The two structural rules of design/01-module-layout.md, enforced rather than remembered.

Both are written before the code they constrain. That order is deliberate: a boundary added after
the first violation is a boundary that has already failed once, and these two are the mechanisms
behind docs/adr/0002 and docs/adr/0004 — the reasons this tool is safe to point at a working
session at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "agent_desk"

# The rule below is about the *on-disk* formats Claude Code writes, and JSON is the proxy for
# reading them. Two modules parse JSON that is not that, and each is named here rather than left
# to trip a check whose subject it is not:
#
#   store/repo.py       `idea.context`, a JSON column in this program's own SQLite file, required
#                       by name in design/02-data-model.md.
#   answer/session.py   the stream-json of a subprocess this program started itself, which
#                       design/01-module-layout.md names as this module's job.
#   tracker/jira.py     the answer to a request this program made a second earlier, which is the
#                       only thing that module does at all (docs/adr/0005).
#   secrets.py          this program's own file of secrets, on this machine, which it writes
#                       itself and never renders (docs/07-security.md).
#
# All three are paths, not categories. A fourth module that starts parsing JSON still fails this
# test, which is the point of it.
# Modules that parse JSON which is *not* one of the formats under ~/.claude/. The rule those
# formats live behind is docs/adr/0004's, and it is about a format nobody promised is stable
# changing quietly underneath five call sites. A tracker's HTTP response is somebody else's API
# with its own versioning, and this program's own database rows are its own.
_NOT_AN_ON_DISK_FORMAT = {
    "store/repo.py",
    "answer/session.py",
    "tracker/jira.py",
    "tracker/github.py",
    "secrets.py",
}


def _modules() -> list[Path]:
    return sorted(p for p in PKG.rglob("*.py"))


def _imported_names(path: Path) -> set[str]:
    """Every module named by an import in `path`, as a dotted string."""
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


# The one assignment whose strings name credential paths in order to *forbid* them. The run this
# program starts has the project's settings file switched off by `--restricted`, so the deny rules
# are handed to it on the command line — and a rule against naming a path cannot be allowed to
# stop the code that denies it. Only the elements of this assignment are excused; every other
# literal in that same file still fails these tests.
_DENIAL_ASSIGNMENTS = {"DENIED_PATHS"}


def _denial_literals(tree: ast.Module) -> set[int]:
    excused: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id in _DENIAL_ASSIGNMENTS
            for target in node.targets
        ):
            continue
        for element in ast.walk(node.value):
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                excused.add(id(element))
    return excused


def _string_literals(path: Path) -> list[str]:
    """Every string constant in `path` except docstrings and the deny rules.

    A path named in a docstring is an explanation; a path named in code is an open() waiting to
    happen. Only the second is what these rules are about.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    excused = docstrings | _denial_literals(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in excused
    ]


@pytest.mark.unit
def test_only_web_imports_the_write_path() -> None:
    """docs/adr/0002: the one path that messages a running session is reached by a human click.

    `peer` is that path. If `observe`, `store`, `answer` or `ideas` can import it, then a
    background loop can message a session, and the property the whole tool rests on — that reading
    is invisible to the agent being read — stops being structural and becomes a habit.
    """
    offenders = []
    for path in _modules():
        rel = path.relative_to(PKG)
        if rel.parts[0] in {"web"} or rel.name == "peer.py":
            continue
        if any(n == "agent_desk.peer" or n.endswith(".peer") for n in _imported_names(path)):
            offenders.append(str(rel))

    assert not offenders, (
        "only agent_desk/web/ may import the peer-messaging path (docs/adr/0002); "
        f"found in: {offenders}"
    )


@pytest.mark.unit
def test_only_web_imports_the_door_to_a_tracker() -> None:
    """docs/adr/0005: filing an idea is a human clicking a button, structurally.

    `tracker` is the second door out of this program, and it gets the second half of the rule that
    guards the first. A background task that could reach it would make "one direction, once, on a
    click" a sentence in a document rather than a property of the code.
    """
    offenders = []
    for path in _modules():
        rel = path.relative_to(PKG)
        if rel.parts[0] in {"web", "tracker"}:
            continue
        if any(
            name.startswith(("agent_desk.tracker", "tracker.")) for name in _imported_names(path)
        ):
            offenders.append(str(rel))

    assert not offenders, (
        f"only agent_desk/web/ may import the tracker path (docs/adr/0005); found in: {offenders}"
    )


@pytest.mark.unit
def test_only_web_imports_the_door_that_merges() -> None:
    """docs/adr/0008: what lands is decided by a gate, and reached from one place.

    `land` is the fourth door. An observer or an answer run that could reach it would be a program
    that merges as a side effect of reading, which is the whole of what these tests exist to stop.
    """
    offenders = [
        str(path.relative_to(PKG))
        for path in _modules()
        if path.relative_to(PKG).parts[0] != "web"
        and path.name != "land.py"
        and any(
            name in ("agent_desk.land", "land") or name.startswith("agent_desk.land.")
            for name in _imported_names(path)
        )
    ]

    assert not offenders, (
        f"only agent_desk/web/ may import the landing path (docs/adr/0008); found in: {offenders}"
    )


def _calls_json_load(path: Path) -> bool:
    """Whether this module actually calls `json.load` or `json.loads`.

    Both spellings that reach it: `json.loads(...)` as an attribute, and a `loads` pulled in by
    `from json import loads` and then called by bare name.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bare = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "json"
        for alias in node.names
        if alias.name in ("load", "loads")
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Attribute) and called.attr in ("load", "loads"):
            if isinstance(called.value, ast.Name) and called.value.id == "json":
                return True
        if isinstance(called, ast.Name) and called.id in bare:
            return True
    return False


@pytest.mark.unit
def test_the_json_check_reads_calls_and_not_the_word() -> None:
    """The check above is only as good as what it counts, and it used to count the word.

    Written as a test rather than trusted, because the failure mode is silent in the direction
    that matters: a check that stops recognising a real call passes for ever.
    """
    written = Path(__file__).parent / "_json_check.py"
    try:
        written.write_text("# json.loads is refused here\nx = 1\n", encoding="utf-8")
        assert not _calls_json_load(written), "a comment about json.loads is read as a call"
        written.write_text("import json\nx = json.loads('{}')\n", encoding="utf-8")
        assert _calls_json_load(written), "an ordinary json.loads call is not seen"
        written.write_text("from json import loads\nx = loads('{}')\n", encoding="utf-8")
        assert _calls_json_load(written), "an imported loads is not seen"
    finally:
        written.unlink(missing_ok=True)


@pytest.mark.unit
def test_only_observe_parses_the_on_disk_formats() -> None:
    """docs/adr/0004: the formats under ~/.claude/ live behind one parser.

    The failure this prevents is not "the format changed" — that is expected. It is the format
    changing quietly, `.get()` returning None at five call sites, and the board rendering a
    plausible, wrong picture. One parser turns that into one loud failure.
    """
    offenders = []
    for path in _modules():
        rel = path.relative_to(PKG)
        if rel.parts[0] == "observe":
            continue
        # Read from the syntax tree, not from the text. A substring search over the source also
        # matches the *word* in a comment explaining why a module does not do it — which is how
        # this last failed: a note saying "json.load anywhere outside observe/ is refused" was
        # itself read as a call. Prose about a rule is not a breach of it, and the same
        # correction has been made here before, for the same reason.
        uses_json = _calls_json_load(path) and rel.as_posix() not in _NOT_AN_ON_DISK_FORMAT
        # Literals only, docstrings excluded — the same line the credential test draws, and for
        # the same reason: naming a path in order to explain why this module never opens it is
        # the documentation the rule wants, not a violation of it. A path named in *code* is an
        # open() waiting to happen and still fails here.
        literals = _string_literals(path)
        touches_claude = any(
            ".claude/sessions" in literal or ".claude/projects" in literal for literal in literals
        )
        # config.py names the paths for everyone; naming is not parsing.
        if touches_claude and rel.name != "config.py":
            offenders.append(f"{rel} (references ~/.claude paths)")
        elif uses_json:
            offenders.append(f"{rel} (parses JSON)")

    assert not offenders, (
        "only agent_desk/observe/ may read or parse what Claude Code writes to disk "
        f"(docs/adr/0004); found in: {offenders}"
    )


@pytest.mark.unit
def test_no_code_names_a_credential_path() -> None:
    """docs/07-security.md: the key files sit beside the registry entries with the same stem.

    `~/.claude/sessions/` holds `<pid>.json`, which is the board's backbone, and `<pid>.<hash>.key`,
    which authenticates that session's messaging socket. A glob of `sessions/*` where
    `sessions/*.json` was meant reads an authentication key into a process whose whole job is to
    render things, and nothing else in the system would notice.

    Docstrings and comments are excluded on purpose: naming a path in order to explain why it is
    never opened is the documentation this rule wants, not a violation of it.
    """
    forbidden = (".credentials.json", ".key", "cc-socks")
    offenders = [
        f"{path.relative_to(PKG)}: {literal!r}"
        for path in _modules()
        for literal in _string_literals(path)
        for token in forbidden
        if token in literal
    ]
    assert not offenders, f"no string literal may name a credential path: {offenders}"


@pytest.mark.unit
def test_the_registry_glob_is_never_widened() -> None:
    """`sessions/*.json`, never `sessions/*` — the single character that separates the two.

    This is the concrete form of the rule above, and it is the one that would be broken by an
    innocent-looking simplification rather than by a deliberate choice.
    """
    offenders = [
        f"{path.relative_to(PKG)}: {literal!r}"
        for path in _modules()
        for literal in _string_literals(path)
        if "sessions" in literal and literal.rstrip("/").endswith("*")
    ]
    assert not offenders, f"the registry glob must end in *.json: {offenders}"
