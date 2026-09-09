-- An MCP server a project lends to the agents this console starts in it.
--
-- «Возможность подключить MCP сервер… Когда накидываешь какую-то задачу для agent-deck, у тебя
-- должна быть возможность как у пользователя подключать и добавлять различные mcp.»
--
-- A project already keeps a list of places it also lives (`project_link`, docs/adr/0005). An MCP
-- server is the half of that list which is not a link: something an agent can actually call. This
-- table is that half, and it is per project for the same reason connectors are — a server that
-- reads one company's board is noise in another checkout.
--
-- ## Where the configuration goes, and why it is not the repository
--
-- The second of the five rules in CLAUDE.md is that this program never writes anything into an
-- observed repository or its worktree. `.mcp.json` in somebody's checkout is exactly that, so it is
-- never written. What is written is one file under `data_dir` — "the only tree this program writes
-- to" (config.py) — handed to the CLI as `--mcp-config`. The agent gets the servers; the repository
-- is untouched, and a person who looks at their checkout afterwards finds it as they left it.
--
-- ## No secret is stored here, and there is no field to type one into
--
-- The same decision `project_link` was built under (docs/07-security.md): this is a plain SQLite
-- file that a second application already serves a redacted view out of. What is stored is the *name*
-- of an environment variable, so the console can say what a server would be given without ever
-- holding it.
--
-- ## Two kinds, because there are two the CLI takes
--
-- `stdio` is a command this machine runs; `http` is a URL it calls. A third kind would be a control
-- that fails when pressed, which is the failure `allowed.py` exists to prevent.

CREATE TABLE mcp_server (
    repo_key  TEXT NOT NULL,
    name      TEXT NOT NULL,
    -- stdio | http
    kind      TEXT NOT NULL,
    -- The command line for stdio, the URL for http.
    address   TEXT NOT NULL,
    -- The name of an environment variable holding whatever it needs. Never the value.
    token_env TEXT NOT NULL DEFAULT '',
    at        INTEGER NOT NULL,
    PRIMARY KEY (repo_key, name)
);
