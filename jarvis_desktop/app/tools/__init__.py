"""Tools - atomic capabilities registered with the Realtime model.

Every module in this package declares one or more ``@tool`` functions. They
are single-call, deterministic, and return a value the caller can render
directly. Multi-step compositions live in ``app/actions/`` instead.
"""

