# JARVIS Desktop

JARVIS is a macOS voice assistant with a browser interface and a Python
backend. It keeps one live Realtime conversation, listens hands-free, streams
its reply as it is generated, and can use calendar, mail, notes, music,
knowledge, and memory capabilities.

The backend is designed for a natural spoken loop: use the wake word for the
first request, then speak normally after JARVIS replies. The follow-up window,
speech end detection, speaker verification, and playback state all run in the
backend so the browser does not need to own the microphone.

## What is included

- Hands-free wake-word listening with an optional clap trigger.
- Streaming audio and transcript updates from the OpenAI Realtime API.
- Follow-up listening and interruption: speak again without a second wake word
  after JARVIS has answered.
- Optional owner-voice verification before audio reaches the model.
- Tools and actions for mail, calendars, reminders, notes, music, web search,
  Obsidian knowledge, and durable memory.
- Qdrant-backed memory with asynchronous writes and duplicate consolidation.
- A small HTTP API for settings, integrations, health checks, and enrollment.

## Quick start

JARVIS requires macOS, Python 3.10 or newer, and an OpenAI API key. Install
PortAudio before Python dependencies because PyAudio uses it for microphone and
speaker access.

```bash
brew install portaudio
cd jarvis_desktop
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`.

Start Qdrant if you want long-term memory or Obsidian knowledge search:

```bash
cd ..
make -C infra up
cd jarvis_desktop
```

Start the backend:

```bash
./run.sh
```

Start the frontend from its own project, then open `http://localhost:5173`.
JARVIS serves the browser WebSocket at `ws://localhost:8000/ws` and its HTTP
API at `http://localhost:8001` by default.

## First checks

```bash
curl http://localhost:8001/api/health
curl http://localhost:8001/api/qdrant/status
curl http://localhost:8001/api/apple_calendar/status
```

For Apple Calendar, microphone, Automation, Accessibility, or Screen Recording
features, macOS grants permission to the process that runs JARVIS. Review it in
**System Settings → Privacy & Security** if an integration is unavailable.

## Documentation

The [documentation index](docs/README.md) links to the complete backend guide.

| Need | Read |
| --- | --- |
| Install and run the system | [Getting started](docs/getting-started.md) |
| Understand the application structure | [Architecture](docs/architecture.md) |
| Diagnose wake word, follow-up, cut-off, and verification issues | [Voice](docs/voice.md) |
| Run and understand Qdrant memory | [Memory](docs/memory.md) |
| Understand Obsidian chunking and hybrid search | [Knowledge retrieval](docs/knowledge.md) |
| Add a tool, action, skill, or agent | [Capabilities](docs/capabilities.md) |
| Configure and operate the backend | [Operations](docs/operations.md) |
| Follow the remaining cleanup work | [Refactoring roadmap](docs/refactoring-roadmap.md) |

## Configuration

Copy `.env.example` to `.env`. The common settings are:

| Setting | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | none | Required for Realtime, embeddings, and model calls. |
| `OPENAI_REALTIME_MODEL` | `gpt-realtime-2.1-mini` | Live conversation model. |
| `QDRANT_URL` | `http://localhost:6333` | Memory and knowledge database. |
| `QDRANT_VAULT_COLLECTION` | `obsidian_vault_hybrid` | Named-vector collection for Obsidian search. |
| `JARVIS_VOICE_FOLLOWUP_SECONDS` | `300` | How long ordinary speech may start the next turn. |
| `JARVIS_VOICE_MAX_RECORDING_SECONDS` | `24` | Maximum native recording duration. |
| `JARVIS_SPEAKER_VERIFICATION_ENABLED` | `false` | Require an enrolled owner voice before accepting a request. |

Saved UI preferences, including wake word and integration settings, live in
`~/.jarvis/settings.json`. See [Operations](docs/operations.md) for all
runtime settings and their defaults.

## Services and API

| Service | Default address | Purpose |
| --- | --- | --- |
| Browser WebSocket | `ws://localhost:8000/ws` | UI events, audio state, transcripts, and assistant audio. |
| HTTP API | `http://localhost:8001` | Settings, integration checks, and local management. |
| Qdrant | `http://localhost:6333` | Durable memory and Obsidian knowledge collections. |

Useful HTTP routes include:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Backend health and Qdrant probe. |
| GET / POST | `/api/settings/load` / `/api/settings/save` | Read and save UI settings. |
| GET / POST | `/api/qdrant/status` / `/api/qdrant/test` | Inspect or test Qdrant. |
| GET / POST | `/api/obsidian/status` / `/api/obsidian/sync` | Inspect or index the Obsidian vault. |
| GET / POST / DELETE | `/api/speaker/profile` / `/api/speaker/profile/enroll` / `/api/speaker/profile` | Inspect, enroll, or clear the speaker profile. |
| GET / POST | `/api/apple_calendar/status` / `/api/apple_calendar/test` | Check Calendar permission and access. |

## Project map

```text
jarvis_desktop/
├── main.py                 launcher and compatibility adapter
├── app/
│   ├── application/        composition root and application workflows
│   ├── realtime/           session configuration and tool dispatch
│   ├── voice/              wake word, capture, playback, and speaker checks
│   ├── core/               Realtime session, bridge, configuration, logging
│   ├── runtime/            capability registry and catalogue
│   ├── tools/              focused integrations
│   ├── actions/            multi-step side-effecting workflows
│   └── agents/             bounded reasoning workflows
├── docs/                   technical documentation
├── tests/
├── .env.example
└── requirements.txt
```

## Development

Run the backend tests from `jarvis_desktop/`:

```bash
python -m pytest tests -q
```

When adding a capability, keep atomic external work in `app/tools/`, place
multi-step actions in `app/actions/`, and add the module to
`app/runtime/catalog.py`. The [capabilities guide](docs/capabilities.md)
includes a working registration example.
