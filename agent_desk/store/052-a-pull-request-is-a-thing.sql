-- A pull request, as a thing rather than as a reason something stopped.
--
-- "PR-ы читаются и складываются в блокеры… Это правда про PR, который ждёт ревью, и неправда про
-- PR вообще — на верстаке он нужен как вещь, про которую спрашивают, рядом с сессией, которая его
-- написала."
--
-- Both readings are true at once and they are different rows. A pull request open for three days
-- waiting on a review is work that has stopped on a person, which is what the blockers column is
-- for and stays exactly as it was. A pull request is also a thing: it has a number, a title, an
-- author waiting on somebody, and a branch a session on this machine probably wrote — and that is
-- what somebody puts on a workbench next to that session and asks a question about.
--
-- ## Why not keep reading it out of tracker_blocker
--
-- Because it is not all in there. `said` is `"<waiting for> · <url>"` — two facts in one column,
-- joined by a separator, to be split apart by whoever needs one of them. That was the right size
-- when a pull request was only ever a line in a column; a card that shows what it is waiting for
-- *and* links to it would have to take that string back apart, and the day a title contains " · "
-- it takes it apart wrongly. `draft` is not in there at all: `github.Pull` reads it and
-- `replace_pull_blockers` drops it, because a blocker does not need it and a card does.
--
-- ## The key
--
-- (repo_key, number). A pull request number is unique within a repository and means nothing
-- outside one, and the console has more than one repository — so neither half is a key on its own.
--
-- Read-only, like everything else that comes from outside: nothing here reviews, comments on,
-- approves or merges (docs/adr/0010).

CREATE TABLE pull (
    repo_key    TEXT    NOT NULL,
    number      INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    url         TEXT    NOT NULL DEFAULT '',
    waiting_for TEXT    NOT NULL DEFAULT '',
    draft       INTEGER NOT NULL DEFAULT 0,
    seen_at     INTEGER NOT NULL,
    PRIMARY KEY (repo_key, number)
);
