# Operations and troubleshooting

## Configuration

Put secrets and local choices in `jarvis_desktop/.env`. Saved UI preferences,
including wake-word settings and service configuration, live in
`~/.jarvis/settings.json`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | none | Required for Realtime, embeddings, and model calls. |
| `OPENAI_REALTIME_MODEL` | `gpt-realtime-2.1-mini` | Realtime conversation model. |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint for memory and knowledge. |
| `JARVIS_HOST` | `localhost` | Network interface for backend services. |
| `JARVIS_WEBSOCKET_PORT` | `8000` | Browser WebSocket port. |
| `JARVIS_API_PORT` | `8001` | HTTP API port. |
| `JARVIS_VOICE_FOLLOWUP_SECONDS` | `300` | How long ordinary speech can start the next turn. |
| `JARVIS_VOICE_MAX_RECORDING_SECONDS` | `24` | Maximum length of one native recording. |
| `JARVIS_VOICE_MIC_RESUME_SECONDS` | `0.2` | Playback-tail guard before listening resumes. |
| `JARVIS_MUSIC_DUCK_TARGET_VOLUME` | `38` | macOS output volume while listening over Music.app. |
| `JARVIS_CAPABILITY_TIMEOUT_SECONDS` | `90` | Maximum run time for one capability. |
| `JARVIS_DISABLED_CAPABILITIES` | empty | Comma-separated capability names to hide. |
| `JARVIS_CAPABILITY_MODULES` | empty | Comma-separated local extension modules. |

## Useful checks

```bash
curl http://localhost:8001/api/health
curl http://localhost:8001/api/qdrant/status
curl -X POST http://localhost:8001/api/apple_calendar/test
```

The browser status panel and backend logs are the best place to inspect the
voice state. The listener emits a heartbeat every few seconds with its armed,
speaking, music, follow-up, cooldown, and microphone-resume state.

## Failure guide

| Problem | Likely cause | What to do |
| --- | --- | --- |
| Browser is blank or cannot connect | Backend or frontend is on a different port. | Check the two configured port values and the browser developer console. |
| No native transcript | Microphone permission, listener dependency, or wake word is unavailable. | Check backend startup logs; install PortAudio, PyAudio, and openWakeWord. |
| Assistant stops hearing mid-sentence | Voice activity detected silence too early or the recording limit was reached. | Check input level and raise the recording limit if necessary. |
| No memory is saved | Qdrant or the embedding request failed. | Probe Qdrant, verify the OpenAI key, then check `memory.persist_failed` logs. |
| Calendar access does not work | macOS granted the wrong process or denied Calendar access. | Reset Calendar permission for the terminal or application that runs JARVIS, then run the Apple Calendar test. |
| Voice commands are rejected | Speaker verification is enabled without a usable profile, or the voice did not match. | Enroll again and verify the profile path and speaker packages. |
