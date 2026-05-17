# JARVIS Desktop Backend

Python WebSocket server that connects to the OpenAI Realtime API and exposes tools (mail, calendar, music, memory, search) to the voice frontend.

---

## What You Need

- **macOS** (most tools are AppleScript-based)
- **Python 3.10+**
- **Homebrew** (for `portaudio`)
- **Docker** (optional, for Qdrant vector DB)
- An **OpenAI API key** - the only hard requirement

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
brew install portaudio
```

> `pyaudio` needs the `portaudio` C library. Skip this and audio playback will fail.

### 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and set at least:

```
OPENAI_API_KEY=sk-your-key-here
```

Everything else is optional. See [`.env.example`](.env.example) for the full list.

### Speaker verification

Speaker verification is optional. When enabled, the backend will preload the current speaker profile on startup so the first verification check is faster.

Configure these environment variables if you want to use it:

```bash
JARVIS_SPEAKER_VERIFICATION_ENABLED=true
JARVIS_SPEAKER_PROFILE_PATH=~/.jarvis/voice/speaker_profile.json
JARVIS_SPEAKER_VERIFICATION_THRESHOLD=0.35
JARVIS_SPEAKER_VERIFICATION_MODEL_NAME=speechbrain/spkrec-ecapa-voxceleb
```

Behavior notes:

- **Startup preload** - If a profile exists, JARVIS warms the verifier model and speaker embedding in the background at launch.
- **Profile updates** - Re-enrollment clears the cached embedding and reloads the new profile immediately.
- **Missing profile** - The app does not crash; it falls back to lazy loading and continues running normally.

### Voice activation flow

The voice layer now supports both wake-word and clap activation.

- **Wake word** - `Hey JARVIS` by default, configurable in Settings.
- **Clap trigger** - Optional secondary trigger that arms the same activation sequence.
- **Intro sound** - Point `voice.introSoundPath` or `JARVIS_ACTIVATION_SOUND_PATH` to a local audio file if you want a short intro sting before the greeting.
- **Greeting / status** - Configure the spoken greeting and whether JARVIS should read a short connection summary and the next calendar items after activation.

The intro sound is played locally on macOS with `afplay`, so use a file that exists on your machine.

### 3. Start Qdrant (optional)

Qdrant powers the Obsidian knowledge base and long-term memory. You can skip it - JARVIS falls back to a local JSON file for memory.

```bash
docker run -d -p 6333:6333 qdrant/qdrant
```

Verify: `curl http://localhost:6333`

---

## Run

```bash
./run.sh
```

You should see:

```
🤖 J.A.R.V.I.S. WebSocket Edition
==================================
✅ Loaded .env from ...
🌐 Starting WebSocket bridge on ws://localhost:8000
...
🔌 Connected to OpenAI Realtime API
🛠️  Tools registered: 14
```

- **WebSocket** (frontend): `ws://localhost:8000/ws`
- **HTTP API** (settings & probes): `http://localhost:8001`

Then start the frontend in another terminal:

```bash
cd ../jarvis-ui && npm install && npm run dev
```

Open http://localhost:5173 and press the mic button.

---

## Testing

### Health check
```bash
curl http://localhost:8001/api/health
```
Expected: `{"status":"ok"}`

### Qdrant
```bash
curl http://localhost:8001/api/qdrant/status
curl -X POST http://localhost:8001/api/qdrant/test
```

### Obsidian sync (if vault path is set)
```bash
curl -X POST http://localhost:8001/api/obsidian/sync
```

### Apple Calendar
```bash
curl http://localhost:8001/api/apple_calendar/status
curl -X POST http://localhost:8001/api/apple_calendar/test
```

---

## Architecture

```
┌──────────────┐    WS     ┌────────────────┐   WS    ┌──────────────┐
│  React UI    │ ────────▶ │ WebSocketBridge│ ──────▶ │ OpenAI       │
│  (jarvis-ui) │ ◀──────── │  + HTTP API    │ ◀────── │ Realtime API │
└──────────────┘           └────────────────┘         └──────┬───────┘
                                  │                          │  tool call
                                  │                          ▼
                                  │                  ┌───────────────┐
                                  │                  │ agent router  │
                                  │                  └───────┬───────┘
                                  │                          │
                              settings.json              dispatch to…
                              (~/.jarvis)
                                                    ┌────────┼────────┐
                                                    ▼        ▼        ▼
                                                 workspace knowledge computer
                                                  memory    websearch  meta
```

## Tool surface (what the model sees)

| Tool | Does |
|------|------|
| `mail_list`, `mail_search`, `mail_send` | Unified Gmail + Zimbra. `mail_send` uses preview-then-confirm. |
| `calendar_list`, `calendar_create` | Unified Google + Apple Calendar. Same confirm pattern. |
| `computer_play_music` | AppleScript on library; escalates to UI automation for catalog. |
| `computer_music_control`, `computer_set_volume`, `computer_open_app`, `computer_open_url` | Pure AppleScript. |
| `computer_do_task` | Last-resort Computer Use (gpt-5.4-mini). |
| `knowledge_ask`, `knowledge_search`, `knowledge_list` | RAG over the Obsidian vault (Qdrant). |
| `memory_remember`, `memory_recall` | Durable facts about the user. |
| `web_search` | Tavily. |
| `get_time`, `get_date` | Trivial. |

## Project layout

```
jarvis_desktop/
├── main_ws.py                  # entry point
├── app/
│   ├── core/
│   │   ├── realtime_session.py # OpenAI Realtime client + JARVIS persona
│   │   ├── websocket_bridge.py # frontend WS + HTTP API + Obsidian sync
│   │   ├── speaker_verification.py # speaker profile loading, caching, and verification
│   │   ├── config.py
│   │   └── logging.py
│   ├── agents/
│   │   ├── router.py           # dict dispatch by tool name
│   │   ├── tools_schema.py     # LLM-facing tool declarations
│   │   ├── workspace_agent.py  # unified mail + calendar fan-out
│   │   ├── knowledge_agent.py
│   │   ├── computer_agent.py   # AppleScript + Computer Use fallback
│   │   ├── computer_use.py     # gpt-5.4-mini computer-use client
│   │   ├── memory_agent.py
│   │   ├── websearch_agent.py
│   │   └── meta_agent.py
│   └── tools/
│       ├── gmail_tool.py, zimbra_tool.py
│       ├── calendar_tool.py, apple_calendar_tool.py
│       ├── knowledge_tool.py, memory_tool.py
│       └── web_search.py
├── requirements.txt
└── .env.example
```

## macOS Permissions

Grant access in **System Settings → Privacy & Security**:

| Feature | Permission |
|---------|-----------|
| Apple Calendar | *Calendars* |
| UI automation (`computer_do_task`) | *Automation* + *Accessibility* |
| Computer Use screenshots | *Screen Recording* |

Grant access to whichever app launches the script - Terminal, iTerm, VS Code, etc.

---

## HTTP API Reference

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness probe |
| GET/POST | `/api/settings/load` \| `/save` | Settings UI persistence |
| POST | `/api/qdrant/test`, GET `/api/qdrant/status` | Qdrant health |
| POST | `/api/obsidian/sync`, GET `/api/obsidian/status` | Vault ingestion |
| GET | `/api/speaker/profile/status` | Speaker profile status and cache summary |
| POST | `/api/speaker/profile/enroll` | Enroll or replace the speaker profile |
| DELETE | `/api/speaker/profile` | Clear the persisted speaker profile |
| GET | `/api/google/status` | Google OAuth state |
| POST | `/api/zimbra/test`, GET `/api/zimbra/status` | IMAP/SMTP login |
| POST | `/api/apple_calendar/test`, GET `/api/apple_calendar/status`, `/calendars` | macOS Calendar probe |
| GET | `/auth/callback` | Google OAuth redirect |
