"""One message read into its parts: a repository, a secret, links, files.

"Я просто условно кидаю в ввод ссылку на пустой реп и токен + разные ссылки/файлы/референсы —
прошу сделать прототип на основе."

That is four different things in one paste, and three of them are ordinary. The fourth is not:

**A token must not be stored, and must not be sent.** The input of a block goes into the SQLite
file, onto the page, into the thread history that travels with the next question, and into the
prompt. A credential in it is in all four places, and deleting the message afterwards does not take
it out of the two that already left (docs/07-security.md). So it is taken out of the text at the
door — before a block exists — kept in the secret store that was built for exactly this, and what
stays in the message is a trace saying a token was here and what it is now called.

The trace matters as much as the removal. A message that silently lost a word is a message somebody
re-pastes the token into, and the second paste is the one that gets stored.

## What a token looks like

`store/redact.py`'s patterns, which come from `.claude/security-patterns.yaml`. One list, read by
the redaction that runs at the store boundary and by this — a second list would be a second answer
to "is this a secret", and the shapes it did not have would be the ones that got through.

## Read here rather than asked of a model

A repository address, a URL and an absolute path are shapes, not judgements, and a message holding
a credential must not wait on a model call to have it removed — least of all one that would be
given the credential in order to decide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent_desk.store.redact import patterns

# A git remote, in the two forms people paste: an https URL, and the same with `.git` on the end.
# `git@host:owner/name` is deliberately absent — an SSH remote carries no credential to go with it
# and nothing here could clone it without a key nobody typed.
_REPO = re.compile(
    r"https://[A-Za-z0-9.\-]+/[A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+?(?:\.git)?(?=[\s,)]|$)"
)
_LINK = re.compile(r"https?://[^\s<>\"]+")
# An absolute path, which is the only kind this program accepts anywhere else either.
_FILE = re.compile(r"(?<![\w/])/(?:[\w.\-]+/)*[\w.\-]+\.[A-Za-z0-9]{1,8}(?=[\s,)]|$)")

# Hosts whose URLs are repositories rather than references. Not "anything that looks like
# owner/name": a link to a documentation page on a docs site has that shape too, and calling it a
# repository would start a clone of somebody's blog.
REPO_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")


@dataclass(frozen=True)
class Pasted:
    """What one message turned out to be made of."""

    said: str
    repos: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    # The secret, and only in memory. It is never in `said`, never returned to a page, and the
    # caller's one job with it is to hand it to `agent_desk/secrets.py` and drop it.
    token: str = ""
    kept_as: str = ""
    said_parts: tuple[str, ...] = field(default=(), repr=False)


def name_for(repos: tuple[str, ...]) -> str:
    """What to call the secret. The repository it arrived with, upper snake, or a plain default.

    Named after the repository because that is what it is for and what somebody will look for it
    under — the same rule the project links already follow, where the variable's name is the name
    of the secret.
    """
    if not repos:
        return "PASTED_TOKEN"
    owner, _, name = repos[0].rstrip("/").removesuffix(".git").rpartition("/")
    where = f"{owner.rpartition('/')[2]}_{name}"
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", where).strip("_").upper()
    return f"TOKEN_{cleaned}" if cleaned else "PASTED_TOKEN"


def read(text: str) -> Pasted:
    """The parts of one message, with any credential taken out of the words.

    The token is found first and removed first, so that everything below it reads a message with no
    secret in it. A link matcher run over the raw text could otherwise return a URL with a token in
    its query string, and that URL is then in the parts as well.
    """
    token, said = "", text
    for shape in patterns():
        found = shape.search(said)
        if found is None:
            continue
        token = found.group(0)
        break

    kept_as = ""
    repos = tuple(
        one.rstrip("/") for one in _REPO.findall(said) if any(host in one for host in REPO_HOSTS)
    )
    if token:
        kept_as = name_for(repos)
        said = said.replace(token, f"‹a token was here — kept as {kept_as}›")

    links = tuple(one for one in _LINK.findall(said) if one.rstrip("/") not in repos)
    files = tuple(_FILE.findall(said))
    return Pasted(
        said=said,
        repos=repos,
        links=links,
        files=files,
        token=token,
        kept_as=kept_as,
    )


def as_lines(found: Pasted) -> list[str]:
    """What the message turned out to hold, for the line a block already shows about its context.

    Said rather than assumed: somebody who pasted four things and got an answer about two of them
    needs to be able to see which two, and a secret that was moved needs to say where it went.
    """
    lines = []
    for one in found.repos:
        lines.append(f"repository · {one}")
    for one in found.links:
        lines.append(f"link · {one}")
    for one in found.files:
        lines.append(f"file · {one} — its name only, until you say it may be read")
    if found.kept_as:
        lines.append(f"a token · taken out of the message and kept as {found.kept_as}")
    return lines
