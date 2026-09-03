"""The net at the store boundary.

Every secret shape in this test is assembled from pieces rather than written whole. A test file
holding a literal that matches a token pattern is a test file the commit hook blocks — and it
would be right to: the repository cannot tell a fixture from the real thing, and neither can a
grep six months later (tests/fixtures/README.md makes the same argument about recordings).
"""

from __future__ import annotations

import re

import pytest
import yaml
from agent_desk.config import settings
from agent_desk.store import redact


@pytest.mark.unit
def test_every_shipped_pattern_compiles_in_python() -> None:
    """The loud half of docs/07-security.md's "the patterns are the ones the skillset ships".

    That file is maintained for a shell hook as well, and a pattern that only `grep -E` can read
    would be silently inert here — which is precisely the failure a secret scanner must not have.
    This test fails on the day such a pattern is added without a Python-readable twin.
    """
    document = yaml.safe_load(settings.security_patterns.read_text())
    for pattern in document["categories"]["hardcoded_secrets"]["patterns"]:
        if "[[:" in pattern:
            continue  # a POSIX-class duplicate, kept for the shell fallback
        re.compile(pattern)


@pytest.mark.unit
def test_the_posix_duplicates_are_skipped_rather_than_misread() -> None:
    """Python's `re` reads `[[:space:]]` as a character class of `[`, `:`, `s`… and says nothing."""
    assert not any("[[:" in p.pattern for p in redact.patterns())
    assert redact.patterns()


@pytest.mark.unit
@pytest.mark.parametrize(
    "secret",
    [
        "ghp_" + "a" * 36,
        "AKIA" + "B" * 16,
        "sk-ant-" + "c" * 24,
        "xoxb-" + "1" * 20,
        "postgresql://user:hunter2@db.example/agent",
        "-----BEGIN RSA PRIVATE KEY-----",
    ],
)
def test_a_known_shape_does_not_survive(secret: str) -> None:
    scrubbed = redact.scrub(f"the answer mentioned {secret} in passing")
    assert secret not in scrubbed
    assert redact.REDACTED in scrubbed


@pytest.mark.unit
def test_ordinary_prose_and_code_are_left_alone() -> None:
    """The categories about dangerous *code* are deliberately not applied here.

    An answer that discusses `eval(` or `.innerHTML =` is exactly the answer this tool is for;
    scrubbing those shapes would mangle the product to catch nothing.
    """
    for text in (
        "the migration added an index on block(thread_id)",
        "it calls eval() on the parsed value, which is the bug",
        "row.innerHTML = tail — that is the injection sink",
        "verify=False in the client, which explains the TLS error",
    ):
        assert redact.scrub(text) == text


@pytest.mark.unit
def test_scrub_optional_passes_absence_through() -> None:
    assert redact.scrub_optional(None) is None
