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

    @property
    def registry_glob(self) -> str:
        """`*.json`, never `*`. See the module docstring."""
        return str(self.claude_home / "sessions" / "*.json")

    @property
    def transcripts_root(self) -> Path:
        return self.claude_home / "projects"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agent-desk.db"


settings = Settings()
