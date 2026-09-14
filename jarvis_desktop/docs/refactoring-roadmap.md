# Refactoring roadmap

This is the order for making JARVIS easier to change before adding major new
features. Each step should preserve behavior, keep the existing tests passing,
and add a focused regression test when it changes a boundary.

## Completed boundaries

| Area | Current ownership |
| --- | --- |
| Application startup and lifecycle | `app/application/assistant.py` |
| Native voice listener and microphone capture | `app/voice/listener.py`, `app/voice/capture.py` |
| Assistant PCM playback and music ducking | `app/voice/playback.py` |
| Activation, mail confirmation, and reminders | `app/application/` |
| Qdrant management and Obsidian indexing | `app/api/handlers/qdrant.py`, `app/api/handlers/obsidian.py` |
| Mail draft preview contract | `app/actions/mail_draft.py` |
| Capability loading | `app/runtime/catalog.py`, `app/runtime/registry.py` |
| Realtime configuration and tool calls | `app/realtime/configuration.py`, `app/realtime/tool_dispatcher.py` |
| Realtime persona context | `app/realtime/persona_context.py` |

Compatibility modules remain where tests or local integrations still import the
old path. They should contain forwarding code only; new code must use the
domain-specific module.

## Next: split the Realtime session

`app/core/realtime_session.py` still owns too many jobs. Split it without
changing the WebSocket protocol:

1. Move the remaining persona instruction text into a prompt module.
2. Move model-event parsing into a dedicated event router that receives
   callbacks and session state explicitly.
3. Move `RealtimeSession` itself into `app/realtime/` and leave a compatibility
   import at `app/core/realtime_session.py`.
4. Keep `RealtimeSession` responsible only for connection lifecycle, sending
   events, reconnecting, and coordinating those parts.

The acceptance checks are reconnect recovery, transcript ordering, one response
per committed audio turn, streamed audio, and no repeated action after a
reconnect.

## Then: split speaker verification

`app/core/speaker_verification.py` currently combines model loading, profile
file I/O, enrollment, cache management, and verification. Divide it into:

- profile data and atomic profile file writes;
- classifier/model loading and its shared cache;
- enrollment audio normalization and embedding creation;
- a small verifier facade used by the voice input stream.

The public behavior stays the same: verification must fail closed when enabled,
profile changes must invalidate cached embeddings, and enrollment must not leave
a partial profile file behind.

## Then: make settings explicit

`Settings` should become an instance-based configuration object with clear
precedence: environment values for runtime configuration, saved UI settings for
user preferences, and explicit constructor values for tests. Remove import-time
environment reads as modules move to this object.

This makes local development, packaged builds, and tests use the same settings
rules and avoids hidden global state.

## Before feature work

Complete these checks after the three steps above:

- The backend starts and stops all background tasks cleanly.
- A disconnected dependency produces a clear status and does not stop voice
  capture or the event loop.
- Capability failures are contained and visible in logs.
- The full test suite passes without a live microphone, OpenAI request, Qdrant
  server, or macOS automation permission.
- Every capability has one module, one registration entry, and a documented
  owner.

Once these checks hold, new features can be added as tools, actions, skills, or
agents without changing the voice and conversation foundations.
