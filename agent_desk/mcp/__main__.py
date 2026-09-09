"""`python -m agent_desk.mcp` — the server on stdin and stdout.

A module rather than a console script: this is started by whatever is attaching to it, with a
command line in that client's own configuration, and a path that works without installing anything
is the one that keeps working (docs/adr/0003).
"""

from agent_desk.mcp.server import main

main()
