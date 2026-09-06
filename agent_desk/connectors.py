"""What a link to another service actually lets this console do (docs/adr/0005, docs/adr/0010).

Asked for as: *"конекторы, больше коннекторов, гугл диск/slack/gmail и прочее. Сейчас например
что-то похожее есть в jira и github — коннекторы необходимо вынести отдельной сущностью для
каждого проекта."*

A project already keeps a list of places it also lives. What that list could not say is the thing
somebody most needs to know about it: **which of these can this console actually do something
with, and what.** A Jira link with a credential is a board this program reads and files into. A
GitHub link is a link. Both were rendered identically, which is how a list of five connectors
becomes five things nobody can predict the behaviour of.

So a connector says what it is, and this module is the one place that decides what that means.

**What is deliberately not here is an integration.** Naming Google Drive as a kind does not make
this program able to read a Drive, and the card says so in as many words — "a link; nothing reads
it yet". Writing a connector for a service is a piece of work per service, with a credential flow
and a recorded response behind it, and pretending otherwise with an icon would be worse than the
undifferentiated list this replaces.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    """One kind of connector, and the truth about what it does here."""

    name: str
    label: str
    # What this console does with it today, in a sentence somebody can act on.
    does: str
    # Whether anything in this program actually talks to it, as opposed to linking to it.
    integrated: bool = False
    # The environment variable a working one needs, where it needs one.
    wants_token: bool = False


KINDS: tuple[Kind, ...] = (
    Kind(
        name="jira",
        label="Jira",
        does=(
            "reads this project's unfinished tickets into the queue, records the ones that say "
            "they are blocked, and files an idea as an issue when you press the button"
        ),
        integrated=True,
        wants_token=True,
    ),
    Kind(
        name="github",
        label="GitHub",
        does="opens the repository. Nothing here reads it — git does that locally",
    ),
    Kind(name="confluence", label="Confluence", does="opens the space. A link; nothing reads it"),
    Kind(name="drive", label="Google Drive", does="opens the folder. A link; nothing reads it yet"),
    Kind(name="slack", label="Slack", does="opens the channel. A link; nothing reads it yet"),
    Kind(name="gmail", label="Gmail", does="opens the mailbox. A link; nothing reads it yet"),
    Kind(name="dashboard", label="A dashboard", does="opens it. A link; nothing reads it"),
    Kind(name="other", label="Something else", does="opens it. A link; nothing reads it"),
)

BY_NAME = {one.name: one for one in KINDS}

# What a URL suggests, so the field arrives filled in. A guess, and every one of them is
# overridable — the point is to save a choice, not to make it.
_HINTS: tuple[tuple[str, str], ...] = (
    ("atlassian.net/wiki", "confluence"),
    ("atlassian.net", "jira"),
    ("jira.", "jira"),
    ("github.com", "github"),
    ("drive.google.com", "drive"),
    ("docs.google.com", "drive"),
    ("slack.com", "slack"),
    ("mail.google.com", "gmail"),
    ("gmail.com", "gmail"),
)


def guess(url: str, name: str = "") -> str:
    """Which kind a URL looks like. `other` when nothing suggests itself.

    The name is consulted second and only as a whole word, because "the github mirror of our jira
    exports" is a name that contains two of them and means neither.
    """
    lowered = url.lower()
    for fragment, kind in _HINTS:
        if fragment in lowered:
            return kind
    named = name.strip().lower()
    return named if named in BY_NAME else "other"


def kind_of(name: str) -> Kind:
    """The kind a stored connector is, falling back to the one that promises nothing."""
    return BY_NAME.get(name, BY_NAME["other"])
