"""Agents - LLM-powered sub-agents (populated in Phase 2).

An agent is a capability with its own reasoning loop, its own private tool
set, and a handoff contract. It registers via ``@agent`` from
``app.runtime`` and is exposed to the Realtime orchestrator as a single
``delegate_to_<name>`` entry. Phase 1 intentionally contains no agents; the
existing behaviour is covered by tools and actions.
"""

