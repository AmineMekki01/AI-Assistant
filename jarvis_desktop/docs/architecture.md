# Architecture

`main.py` loads `.env`, creates the application, and starts it. It keeps a
small adapter for older imports, but new backend code should use
`AssistantApplication` directly.

```text
React UI
   │ WebSocket events, audio level, transcripts
   ▼
WebSocketBridge
   │ browser input and UI events
   ▼
AssistantApplication
   ├── NativeVoiceController ── MicrophoneCapture
   ├── AudioPlayback
   ├── ActivationController
   ├── MailController
   ├── ReminderScheduler
   └── RealtimeSession ── ToolRegistry
                              ├── tools
                              ├── actions
                              ├── skills
                              └── agents
```

## Ownership

`AssistantApplication` is the composition root. It creates the shared session,
event loop, bridge, and application controllers. It does not decide how a wake
word is detected or how audio is played.

`NativeVoiceController` owns listener state: wake word, follow-up window,
speaker verification, and the current recording. `MicrophoneCapture` owns the
PortAudio loop and feeds accepted PCM audio to the controller.

`AudioPlayback` owns streamed assistant PCM, the speaking state reported to the
UI, and temporary music-volume ducking. It is the only component that releases
the playback speaking state after queued audio ends.

`RealtimeSession` is the direct OpenAI Realtime connection. It streams model
audio and transcripts, sends user audio or text, and dispatches model tool
calls through the registry.

`WebSocketBridge` transports browser events and serves the small HTTP API. It
does not reason, decide when a spoken turn ends, or maintain the conversation.

## A voice turn

1. The native listener hears the wake word, or accepts ordinary speech while a
   follow-up window is open.
2. It starts a recording and sends 16 kHz PCM chunks to `RealtimeInputStream`.
3. The input stream verifies the speaker when verification is enabled, converts
   accepted PCM to the Realtime format, then commits the turn.
4. `RealtimeSession` streams transcript and assistant audio events back.
5. `AudioPlayback` writes audio to the output device and marks JARVIS as
   speaking. When playback ends, it opens the follow-up listening window.

Typed requests use the same `RealtimeSession`; they are queued if a response
is still active so one conversation owns all turns.

## Boundaries that matter

- Keep integrations in `app/tools/` small and deterministic.
- Put multi-step side effects in `app/actions/`.
- Put delegated, tool-using reasoning workflows in `app/agents/`.
- Keep storage and external I/O out of microphone and audio-playback loops.
- Do not add another conversation engine beside `RealtimeSession`; it is the
  source of truth for the live conversation.
