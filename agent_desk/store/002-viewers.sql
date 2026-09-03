-- Phase 4: a named viewer, and the link that is their whole identity.
--
-- One row per person who may open the shared ideas list. The token itself is never stored — only
-- its hash — so this file leaking is not the same event as the links leaking, and a token that
-- was shown once and lost is replaced rather than recovered.
--
-- Revocation is a timestamp rather than a delete: "who could see this, and until when" is the
-- question an audit asks, and a deleted row answers it with silence.

CREATE TABLE viewer (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,          -- who this link is for, in a human's words
    token_hash  TEXT NOT NULL UNIQUE,   -- sha256 of a 256-bit random token; the token is not here
    created_at  INTEGER NOT NULL,
    revoked_at  INTEGER
);

CREATE INDEX viewer_by_token ON viewer (token_hash);
