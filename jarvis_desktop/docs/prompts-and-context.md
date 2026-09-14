# Prompts and context

JARVIS has one live conversation prompt and several small task prompts. Each has a clear job, so a detailed instruction for a briefing does not change how a simple calendar lookup behaves.

## Live conversation

`app/core/realtime_session.py` builds the Realtime prompt from reusable blocks in `app/realtime/persona_context.py`. It contains JARVIS's speaking style, tool-use rules, current time, available integrations, and a small durable profile primer.

The user name is available for transcription accuracy and a first natural greeting. It must not appear as a routine greeting or be paired with `sir`. Ordinary replies start with the answer.

## Context limits

The live conversation keeps at most 12 recent text items, with each item limited to 900 characters. This history is only replayed when the Realtime connection is rebuilt; tool calls and raw tool output are never replayed.

At the start of a session, JARVIS adds at most four durable memories and caps that primer at 900 characters. Superseded memories are excluded. The memory block is reference data, never an instruction.

The Realtime session reserves 12,000 tokens after its instructions and tool schemas, and limits a single response to 1,024 tokens. Normal voice replies should still be one or two sentences; larger answers are allowed only when the user asks for detail or invokes a briefing.

## Delegated tasks

The prompts in `app/agents/` are purpose-specific: daily briefing, focus, meeting preparation, research, startup briefing, and workspace triage. They only receive their allowed tool schemas, a task, and optionally 1,200 characters of current-conversation reference context.

Each delegated task caps cumulative tool-result context at 8,000 characters. This prevents long mail threads or search results from crowding out the task or causing an unnecessary latency increase.

`app/runtime/orchestrator.py` applies the same history and context limits for the reasoning path, and refreshes its time-, service-, and memory-aware prompt every five minutes rather than freezing it at application start.
