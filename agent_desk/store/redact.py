"""Redaction, applied where text leaves the store.

docs/07-security.md: a view that forgets to call a filter renders correctly and leaks, so the
filter is not in the template. Text this program stored — a model's answer, an idea's context —
can carry anything the agent it was built from had seen.

**This is a net, not the mechanism.** It catches shapes it knows. The real protection is that
transcript content does not leave this machine and is not copied into a second store.

The patterns are the ones the skillset already ships, and only the category that describes *secret
shapes*. The other categories in that file describe dangerous *code* — `eval(`, `.innerHTML =`,
`verify=False` — and an answer that discusses code is exactly the answer this tool is for.
Redacting those would mangle the product to catch nothing.
"""

from __future__ import annotations

import re
from functools import lru_cache

import yaml

from agent_desk.config import settings

REDACTED = "[redacted]"

# The one category that describes a secret rather than a smell.
_CATEGORY = "hardcoded_secrets"

# The file carries duplicates of its own patterns written in POSIX character classes, because the
# shell hook that also reads it falls back to `grep -E`. Python's `re` does not understand
# `[[:space:]]` and would compile it into something quietly different, so the duplicates are
# skipped here and the `(?i)` originals they duplicate are used instead.
_POSIX_CLASS = "[[:"


@lru_cache(maxsize=1)
def patterns() -> tuple[re.Pattern[str], ...]:
    """Every secret shape in `.claude/security-patterns.yaml`, compiled once."""
    document = yaml.safe_load(settings.security_patterns.read_text())
    raw = document["categories"][_CATEGORY]["patterns"]
    return tuple(re.compile(p) for p in raw if _POSIX_CLASS not in p)


def scrub(text: str) -> str:
    """Replace every known secret shape. Returns the text unchanged when nothing matches."""
    for pattern in patterns():
        text = pattern.sub(REDACTED, text)
    return text


def scrub_optional(text: str | None) -> str | None:
    return None if text is None else scrub(text)
