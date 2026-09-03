"""The one write path: a message to a named session.

Everything else in this program reads. This module is the single exception of
docs/adr/0002-read-first-never-interrupt.md, and it exists behind a route a human reaches by
clicking a button that names the session and shows the message first. No background loop may
import it, and a test asserts that no module outside `web/` does.

**It does not deliver today, and it says so rather than pretending.**

Delivery would mean speaking the cross-session messaging protocol on the socket the registry
names. Three facts, established by reading — the socket of a running session was never touched:

1. The `claude` CLI exposes no client for it: no subcommand, no flag, no SDK entry point.
2. The protocol is internal to the CLI binary, versioned (`peerProtocol`), framed, and
   undocumented. A message that arrives is routed into the receiving session's queue as a prompt,
   which means a malformed guess does not fail quietly — it lands in the middle of somebody's
   work.
3. Authentication is by kernel peer credentials rather than by a secret this program would hold.
   The CLI's own schema says the connecting pid is read "from the connection (SO_PEERCRED /
   LOCAL_PEERPID) — never from the payload", which is why the rule against opening
   `~/.claude/sessions/*.key` costs this module nothing: it would not have used one.

So the refusal here is not a stub waiting for someone to finish it. It is the honest state of a
path whose only safe implementation is a client the tool that owns the protocol has not published
(docs/09-roadmap.md, Phase 3).
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_desk.observe.model import Session


@dataclass(frozen=True)
class Delivery:
    """What happened to one message. `delivered` is a fact, never an assumption."""

    delivered: bool
    detail: str


# The word this project uses for "the toolchain cannot do this", rather than an error that reads
# like a bug in the console (docs/02-architecture.md, failure posture).
NEEDS_CLIENT = (
    "needs_toolchain: the installed claude CLI publishes no way to send a message to a running "
    "session — no subcommand, no flag, no SDK entry point. Speaking its internal socket protocol "
    "by guesswork would put a malformed prompt into that session's queue, which is the one thing "
    "this tool refuses to risk (docs/adr/0002). Copy the message and paste it yourself, at a "
    "moment you choose."
)


def send(session: Session, message: str) -> Delivery:
    """Attempt to deliver `message` to `session`, and report honestly.

    The signature is the one a real client will have, and the call site is already a human click.
    When a supported client exists, this function changes and nothing else does.
    """
    return Delivery(delivered=False, detail=NEEDS_CLIENT)
