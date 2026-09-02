"""One headless `claude -p` run per block.

It starts its own session. It never messages a running one — that path exists once, in `web`, behind
a human click (docs/adr/0002-read-first-never-interrupt.md).
"""
