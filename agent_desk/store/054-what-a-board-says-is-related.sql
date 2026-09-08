-- The links a board recorded between its own tickets, in the board's own words.
--
-- "Если тикеты связаны с github — связь показана, название связей — PRs и так далее… подпись связи
-- для таких линий — не одно из наших пяти слов, а то, что сказал источник."
--
-- Jira holds these as issue links with a type whose wording it supplies: "blocks", "is blocked
-- by", "relates to", "duplicates". That wording is the data. Mapping it onto one of the five
-- process words would throw away the only thing the line was worth drawing for, and inventing a
-- sixth process word for each phrase a board can produce is a vocabulary nobody closed.
--
-- ## The rule this table exists to keep
--
-- "Линию рисуем только если её кто-то записал — там или здесь. Связь по совпадению названий
-- рисовать нельзя, это догадка." A row here is a link the board has. Two tickets that mention each
-- other's keys in their titles produce no row, and therefore no line. That is the same rule the
-- blockers are held to and the same one in CLAUDE.md: a thing is shown because it was recorded,
-- not because it is plausible.
--
-- Replaced whole with the tickets they belong to, because they are part of the same read.

CREATE TABLE ticket_link (
    repo_key TEXT NOT NULL,
    key      TEXT NOT NULL,
    says     TEXT NOT NULL,
    other    TEXT NOT NULL,
    PRIMARY KEY (repo_key, key, says, other)
);
