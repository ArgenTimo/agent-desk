"""Paths and settings, resolved once.

Every path this program touches is here, which is what makes the rules of docs/07-security.md
checkable by reading one file: what is absent from this module is what the program cannot open.

Note what is deliberately NOT here: `~/.claude/.credentials.json` and `~/.claude/sessions/*.key`.
The key files sit beside the registry entries with the same stem, so the registry glob is
`*.json` and never `*` — a widened glob would read an authentication key into a process whose
whole job is to render things.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Resolved once at startup. Every field has a working default; nothing is required."""

    model_config = SettingsConfigDict(env_prefix="AGENT_DESK_", frozen=True)

    # --- What we read. Read-only, always. ---------------------------------------------------
    claude_home: Path = Path.home() / ".claude"

    # --- What we own. The only tree this program writes to. ---------------------------------
    data_dir: Path = Path.home() / ".local" / "share" / "agent-desk"

    # --- The console. Loopback is load-bearing, not a default: anything that can reach this
    # port can already read ~/.claude/ as the same OS user, which is the entire v1 security
    # model (docs/07-security.md).
    host: str = "127.0.0.1"
    port: int = 8787

    # --- Observation cadence. The registry is five small files; polling it is cheap. ---------
    registry_poll_seconds: float = 2.0
    transcript_tail_lines: int = 40
    # A transcript reaches tens of megabytes, so the reader seeks from the end and stops. The
    # budget is bytes rather than lines because a single line holding a tool result can be
    # hundreds of kilobytes, and because the board's headline (`ai-title`) is rewritten once a
    # turn — a window measured in lines can miss it after one long turn.
    transcript_tail_bytes: int = 256 * 1024

    # --- The inference of docs/03-session-observation.md, rendered as an inference. ----------
    idle_hint_seconds: int = 300

    # --- The shared view of docs/09-roadmap.md Phase 4. Empty means it is not served at all,
    # which is the safe default and the state this tool spends most of its life in: the day this
    # is set, the loopback argument of docs/07-security.md stops covering everything and the
    # named-viewer links become the security model.
    share_host: str = ""
    share_port: int = 8788

    # --- The answer engine: one headless `claude -p` run per block (docs/04). The CLI is
    # resolved from PATH; when it is absent the board still works and blocks say so
    # (docs/02-architecture.md, failure posture). There is no --max-turns in the CLI, so the
    # timeout is the only bound on a run.
    claude_bin: str = "claude"
    # A second engine to fall back to when the first is *unavailable* — out of budget, not
    # installed, unreachable. Empty by default, which is every install until somebody sets it: a
    # local model is a thing you have to have running, and a default naming one that is not there
    # would turn every rate limit into two failures instead of one.
    #
    # It is asked the same question with the same flags, so it has to speak the same
    # `--output-format stream-json` the primary does. It is never reached for on a *refusal* —
    # that is an answer, not a failure (docs/08-non-goals.md, agent_desk/answer/session.py).
    local_model_bin: str = ""
    answer_timeout_seconds: float = 180.0

    @property
    def registry_glob(self) -> str:
        """`*.json`, never `*`. See the module docstring."""
        return str(self.claude_home / "sessions" / "*.json")

    @property
    def transcripts_root(self) -> Path:
        return self.claude_home / "projects"

    @property
    def jobs_root(self) -> Path:
        """Where `claude --bg` keeps what became of each background job. See `observe/jobs.py`."""
        return self.claude_home / "jobs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agent-desk.db"

    @property
    def security_patterns(self) -> Path:
        """The secret shapes the store redacts with.

        One source of them, and it is the file the skillset already ships and the commit hook
        already reads — not a second list that drifts from it (docs/07-security.md).

        Two places are looked in, in this order, because this program is meant to run from
        somebody's checkout *and* from an installed copy that has no `.claude/` above it. The
        checkout wins when there is one, so the file the commit hook reads is the file the store
        redacts with; the packaged copy is what makes an install work at all. Neither existing is
        a loud failure rather than a quiet one — see `store/redact.py`, because redaction that
        silently matched nothing is the worst outcome available here.
        """
        beside = Path(__file__).resolve().parents[1] / ".claude" / "security-patterns.yaml"
        if beside.exists():
            return beside
        return Path(__file__).resolve().parent / "security-patterns.yaml"


settings = Settings()
