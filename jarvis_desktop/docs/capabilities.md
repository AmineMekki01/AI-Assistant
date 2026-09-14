# Capabilities

The registry is the list of functions the Realtime model may call. It loads
registered capability modules from `app/runtime/catalog.py` at startup.

| Kind | Location | Use it for |
| --- | --- | --- |
| Tool | `app/tools/` | One integration or small deterministic operation. |
| Action | `app/actions/` | A user-visible operation that combines tools or has a side effect. |
| Skill | A capability module | A callable procedure that is neither an integration nor a delegated agent. |
| Agent | `app/agents/` | A bounded reasoning workflow that can use selected tools. |

## Add a tool

Create a module in `app/tools/` and register an async function. The JSON schema
is what the model sees, so make parameter names and descriptions concrete.

```python
from app.runtime import tool

@tool(
    name="project_lookup",
    description="Find the current status of one named project.",
    parameters={
        "type": "object",
        "properties": {"project": {"type": "string"}},
        "required": ["project"],
    },
)
async def project_lookup(project: str) -> dict:
    return {"project": project, "status": "active"}
```

Add `app.tools.project_lookup` to `BUILTIN_CAPABILITY_MODULES` in
`app/runtime/catalog.py`. The registry rejects duplicate capability names and
returns handler failures as tool results, so a broken integration cannot crash
the Realtime session.

## Add an action or agent

Use `@action` for a workflow that changes user data or systems. Ask for
confirmation inside the workflow before performing irreversible work.

Use `Agent` for a focused reasoning task with a named tool allowlist. Do not
give every agent every tool. The allowlist is both easier to audit and less
likely to produce unrelated calls.

## Enable local extensions

Do not edit the built-in catalogue for a private local module. Set:

```bash
JARVIS_CAPABILITY_MODULES=my_jarvis_extensions.weather,my_jarvis_extensions.home
```

To temporarily remove a built-in capability from the model's tool list, set:

```bash
JARVIS_DISABLED_CAPABILITIES=computer_open_app,mail_send
```

Disabled capabilities are hidden from the model and rejected if a stale tool
call reaches the backend.

## Timeouts and output

`JARVIS_CAPABILITY_TIMEOUT_SECONDS` sets the per-capability timeout and
defaults to 90 seconds. Keep a tool response concise and structured. If an
operation takes a long time, return progress through the appropriate app flow
or delegate it to a bounded agent; do not block microphone or playback loops.
