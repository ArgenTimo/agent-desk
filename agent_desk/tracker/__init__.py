"""The one door out of this program to somebody else's queue (docs/adr/0005).

Importable from `agent_desk/web/` and nowhere else, like `agent_desk/peer.py` and for the same
reason: both are doors, both are opened by a human clicking a button, and a background task that
could reach either one would make that sentence untrue without anybody noticing.
"""

from agent_desk.tracker.jira import Destination, Filed, destination_of, file_issue

__all__ = ["Destination", "Filed", "destination_of", "file_issue"]
