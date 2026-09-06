"""The security arguments this program makes, asserted rather than argued.

Every one of these is a claim written in a docstring or a comment somewhere. A claim in a comment
is true until somebody edits the code under it; a claim in a test is true until somebody edits the
code *and* the test, which is a different thing.

The five rules in CLAUDE.md have their own tests elsewhere. This file is about the surfaces a
static analyser flags and a reviewer then has to reason about by hand: escaping, path building,
URL schemes, and what a subprocess is handed.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
from agent_desk import dispatch, land
from agent_desk.observe import jobs, transcript
from agent_desk.tracker import jira
from agent_desk.web.routes import _prose

SOURCE = pathlib.Path(__file__).resolve().parents[2] / "agent_desk"


# --- escaping ------------------------------------------------------------------------------
@pytest.mark.unit
def test_the_two_marks_it_renders_cannot_carry_anything_else() -> None:
    """`_prose` turns `**bold**` and `` `code` `` into tags and wraps the result in `Markup`,
    which is the one place in this program that bypasses the template's escaping. It is safe
    because the escape happens *first* — and that ordering is the whole of it."""
    for attack in (
        "<script>alert(1)</script>",
        "**<script>alert(1)</script>**",
        "`<img src=x onerror=alert(1)>`",
        '<a href="javascript:alert(1)">click</a>',
        "**bold** and <b>not bold</b>",
        "</strong><script>x</script>",
    ):
        rendered = str(_prose(attack))
        # The property is not "these words are absent" — `onerror` is perfectly safe as *text*
        # inside a code span, and asserting it away would be asserting the wrong thing. It is that
        # no tag exists in the output except the two this function creates. Everything the input
        # contained is escaped, so it is text, whatever it says.
        tags = set(re.findall(r"</?[a-zA-Z][^>]*>", rendered))
        assert tags <= {"<strong>", "</strong>", "<code>", "</code>"}, f"{attack} → {tags}"


@pytest.mark.unit
def test_the_marks_it_does_render_still_work() -> None:
    """A guard that broke the feature would be noticed; one that quietly did not, would not."""
    assert "<strong>yes</strong>" in str(_prose("**yes**"))
    assert "<code>make verify</code>" in str(_prose("`make verify`"))


# --- paths ---------------------------------------------------------------------------------
@pytest.mark.unit
def test_a_session_id_cannot_walk_out_of_the_transcripts_directory(
    tmp_path: pathlib.Path,
) -> None:
    """The id reaches this from a URL. A reader that globbed it raw would read any file on the
    machine ending in `.jsonl`."""
    outside = tmp_path / "secret.jsonl"
    outside.write_text('{"type":"assistant"}\n')
    root = tmp_path / "projects"
    (root / "a-project").mkdir(parents=True)

    for bad in ("../secret", "..%2Fsecret", "a/../../secret", "*", "**/*", "'"):
        assert transcript.read_tail(bad, root=root) is None, bad


@pytest.mark.unit
def test_a_short_id_cannot_walk_out_of_the_jobs_directory() -> None:
    """It arrives from a database row that a dispatch wrote, and a reader that followed `../..`
    on a bad one is a thing somebody has to think about later."""
    root = jobs.settings.jobs_root
    for bad in ("", ".", "..", "../../etc", "a/b", "../"):
        assert jobs.read_job(bad) is None, bad
        assert root in jobs.state_path(bad).parents, bad


@pytest.mark.unit
def test_a_worktree_name_cannot_become_a_path() -> None:
    """It becomes a directory under the repository, so a name with a slash in it is a directory
    somewhere else."""
    for typed in ("../../etc/passwd", "a/b/c", "..", "/absolute", "~/home"):
        name = dispatch._worktree_name(typed)
        assert "/" not in name, typed
        assert not name.startswith("."), typed
        assert land.worktree_for("/repo", name).is_relative_to("/repo"), typed


# --- the network ----------------------------------------------------------------------------
@pytest.mark.unit
def test_neither_request_can_be_made_over_anything_but_https() -> None:
    """Both carry an Authorization header. A `file://` followed with one attached is how a
    credential ends up in a log somewhere."""
    for bad in ("http://example.com", "file:///etc/passwd", "ftp://x", "gopher://x"):
        with pytest.raises(ValueError, match="not https"):
            jira._https_only(bad)
        # The refusal never quotes the whole URL back.
        try:
            jira._https_only(bad)
        except ValueError as exc:
            assert "passwd" not in str(exc)

    jira._https_only("https://example.atlassian.net/rest/api/3/search")


@pytest.mark.unit
def test_only_the_tracker_readers_open_a_socket() -> None:
    """Two modules, and both are a tracker this console was given a credential for.

    The point is not the number — it is that the list is short enough to read and that adding to
    it is a decision somebody makes on purpose. A console that reads transcripts and starts agents
    has no other business on the network, and every one of these carries an Authorization header.
    """
    opens: list[str] = []
    for module in SOURCE.rglob("*.py"):
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "urlopen":
                opens.append(module.relative_to(SOURCE).as_posix())

    assert sorted(set(opens)) == ["tracker/github.py", "tracker/jira.py"], opens


@pytest.mark.unit
def test_every_request_this_program_makes_is_https() -> None:
    """Each carries a credential, and each checks the scheme next to the call rather than trusting
    a pattern three functions away."""
    from agent_desk.tracker import github as gh

    for bad in ("http://api.github.com/x", "file:///etc/passwd"):
        with pytest.raises(ValueError, match="not https"):
            gh._get(bad, "Bearer x")


# --- subprocesses ---------------------------------------------------------------------------
@pytest.mark.unit
def test_nothing_is_ever_handed_to_a_shell() -> None:
    """`shell=True` with anything a human typed in it is the oldest hole there is."""
    for module in SOURCE.rglob("*.py"):
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    raise AssertionError(f"{module.name} passes shell= to a subprocess")


@pytest.mark.unit
def test_the_flags_that_would_hand_over_the_machine_are_never_passed() -> None:
    """docs/adr/0006: an agent that cannot ask a human for permission is an agent nobody is
    standing behind. Asserted against every command this program can build."""
    commands = [
        dispatch.argv("do the thing", worktree="a-name"),
        dispatch.resume_argv("11111111-2222-4333-8444-555555555555", "carry on"),
    ]
    for command in commands:
        for never in dispatch.NEVER:
            assert never not in command, command
        # And nothing that looks like one either.
        assert not [flag for flag in command if "dangerous" in flag or "bypass" in flag.lower()]
