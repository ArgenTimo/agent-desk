"""Capture, the card, and the three draft actions.

Problem 3 of docs/01-vision.md: an idea arrives while agents are running and every place to put it
is wrong. Typing it into a running session spends that session's context; typing it into the
repository's documentation makes a decision nobody agreed to; keeping it in your head costs the
idea.

Two rules from docs/05-ideas.md shape this module.

**The thought is stored before anything is generated.** The summary is a convenience for scanning
a list, and a capture that waited for a model would be a capture that fails when the model is
unavailable — losing the one thing this tool exists to keep. So the idea is written with a summary
taken from its own first line, and a generated one replaces it afterwards if a run succeeds.

**All three draft actions produce text in this tool.** None writes into another repository, opens
a pull request, or files a ticket. The information lost between an idea and a written artefact is
a human deciding it is worth doing, and a tool that closes that gap has not saved the step — it
has removed the review that made the artefact worth reading.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_desk.store.repo import DraftKind, Idea, SourceKind, Store

# A fallback summary is a trimmed first line. Long enough to recognise the thought in a list, short
# enough that nobody mistakes it for the thought itself.
SUMMARY_CHARS = 80


def fallback_summary(text: str) -> str:
    """What the card says before — and instead of, if need be — a generated line."""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first if len(first) <= SUMMARY_CHARS else first[: SUMMARY_CHARS - 1].rstrip() + "…"


async def capture(
    store: Store,
    text: str,
    *,
    source_kind: SourceKind = "typed",
    source_ref: str | None = None,
    context: dict[str, Any] | None = None,
    block_id: str | None = None,
    parent_id: str | None = None,
    project_key: str | None = None,
) -> Idea:
    """Record the thought. No model call, no second question, no way to fail on a busy machine."""
    return await store.create_idea(
        text_=text.strip(),
        summary=fallback_summary(text),
        source_kind=source_kind,
        source_ref=source_ref,
        context=context,
        block_id=block_id,
        parent_id=parent_id,
        project_key=project_key,
    )


def summary_prompt(text: str) -> str:
    """One line, in the idea's own words where possible.

    The instruction against inventing scope is not decoration: a summary that adds a reason the
    human did not give is a summary that will be remembered as what they meant.
    """
    return (
        "Summarise the following idea in one line of at most 12 words. Reply with the line and "
        "nothing else: no quotes, no preamble, no trailing full stop. Do not add a rationale, a "
        "priority or a scope that is not in the text.\n\n"
        f"{text}"
    )


# One message can hold several thoughts — "add A, and B is broken, and we should probably C" — and
# a person typing at speed does not stop to send three messages. More than this in one message is
# a review queue rather than a capture, and that shape is docs/10-meeting-intake.md's question,
# not this one's.
MOST_IDEAS = 8


def split_prompt(text: str) -> str:
    """Cut one message into the thoughts it actually contains, and no more than it contains.

    The instruction against inventing is the whole of this prompt. A splitter that turns one
    thought into three has not helped anybody remember anything: it has put two things in the
    notebook that nobody said, and a week later they read exactly like the one that was said.
    """
    return (
        "A developer typed one message into a notebook. Split it into the separate ideas it "
        "contains — one per line, in their words, each a line that stands on its own.\n\n"
        "Rules, and the first two matter more than the split:\n"
        "- Never invent an idea that is not in the text. One thought is one line; reply with one "
        "line.\n"
        "- Never drop anything. Every part of what they wrote belongs to one of the lines.\n"
        f"- At most {MOST_IDEAS} lines. No numbering, no bullets, no preamble, no blank lines.\n\n"
        f"{text}"
    )


def read_split(reply: str, text: str) -> list[str]:
    """The lines the reply names, or the whole message when it named nothing usable.

    Anything unparsed is one idea, because one idea is what was typed and losing the thought is
    the only failure this module has (docs/05-ideas.md).
    """
    lines = [
        stripped.lstrip("-*•0123456789.) ").strip()
        for line in reply.splitlines()
        if (stripped := line.strip())
    ]
    lines = [line for line in lines if line][:MOST_IDEAS]
    return lines if len(lines) > 1 else [text.strip()]


def _context_lines(idea: Idea) -> list[str]:
    """Where it came from, which is most of an idea's meaning a week later (docs/05)."""
    lines = [f"- captured: {idea.source_kind}"]
    if idea.source_ref:
        lines.append(f"- source: {idea.source_ref}")
    lines += [f"- {key}: {value}" for key, value in sorted(idea.context.items())]
    return lines


def paste_body(idea: Idea) -> str:
    """ "Copy for a session": the text, formatted to paste yourself, at a moment you choose.

    Generated by nothing. It is the idea and its context, and the human is the transport
    (docs/adr/0002 — a message to a session is a deliberate human act).
    """
    return "\n".join([idea.text, "", "Captured by agent-desk:", *_context_lines(idea)])


def proposal_prompt(idea: Idea) -> str:
    return "\n".join(
        [
            "Write a short markdown proposal from the idea below. Four sections and no more:",
            "the idea in one paragraph, the context it was captured in, what it would change,",
            "and what it would cost. Where the cost is unclear, say that it is unclear rather",
            "than estimating. Do not write a plan, a schedule or an owner.",
            "",
            "## The idea, verbatim",
            idea.text,
            "",
            "## Where it came from",
            *_context_lines(idea),
        ]
    )


def ticket_prompt(idea: Idea) -> str:
    return "\n".join(
        [
            "Write the body of a ticket from the idea below: a one-line summary, a short",
            "description, and acceptance criteria that can be checked. No priority, no estimate,",
            "no assignee — this is a notebook entry becoming a draft, not a backlog item.",
            "",
            "## The idea, verbatim",
            idea.text,
            "",
            "## Where it came from",
            *_context_lines(idea),
        ]
    )


# The two drafts a model writes. `paste` is not here because nothing generates it: it is the idea
# and its context, and the human is the transport.
PROMPTS: dict[DraftKind, Callable[[Idea], str]] = {
    "proposal": proposal_prompt,
    "ticket": ticket_prompt,
}
