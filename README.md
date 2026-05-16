# J.A.R.V.I.S. - Desktop AI Assistant

A voice-first AI assistant that runs on your Mac. Think of it as a local bridge between you and OpenAI's Realtime API: you speak, it listens, it can read your email, check your calendar, search the web, control Apple Music, and remember things about you.

**This repo contains two parts:**

- `jarvis_desktop/` - Python backend (WebSocket + HTTP API + tools)
- `jarvis-ui/` - React frontend (voice interface + settings)

---

## Quick Start

You need **macOS**, **Python 3.10+**, **Node.js 18+**, and an **OpenAI API key**.

```bash
# 1. Backend setup
cd jarvis_desktop
pip install -r requirements.txt
brew install portaudio           # audio driver
cp .env.example .env              # add your OPENAI_API_KEY

# 2. Start Qdrant (optional, for memory + Obsidian RAG)
docker run -d -p 6333:6333 qdrant/qdrant

# 3. Start the backend
./run.sh

# 4. In a new terminal, start the frontend
cd ../jarvis-ui
npm install
npm run dev
```

Open http://localhost:5173 and start talking.

> **Tip:** Only `OPENAI_API_KEY` is required. Everything else (Google, Tavily, Qdrant, Obsidian) is optional and can be configured later in the Settings UI.

---

## What's Inside

| Feature | What it does |
|---------|-------------|
| 🎤 Realtime voice | Streams PCM16 audio to OpenAI's Realtime API |
| �️ Speaker verification | Optional voice enrollment and cached verification on startup |
| �📧 Mail | Unified Gmail + Zimbra/OVH (one tool, fan-out) |
| 📅 Calendar | Unified Google + Apple Calendar |
| 🎵 Apple Music | AppleScript control with UI-automation fallback |
| 📚 Knowledge | Obsidian vault RAG via Qdrant |
| 🧠 Memory | Long-term facts about you |
| 🌐 Web search | Tavily integration |

All tools use a **write-before-confirm** gate for destructive actions (sending mail, creating events).

---

## Docs

- [`jarvis_desktop/README.md`](jarvis_desktop/README.md) - Backend setup, env vars, macOS permissions, HTTP API reference
- [`jarvis-ui/README.md`](jarvis-ui/README.md) - Frontend setup, WebSocket protocol, project structure

Speaker verification setup, enrollment, and cache warmup are documented in the backend README.

---

## Architecture at a Glance

```
┌──────────────┐    WS     ┌────────────────┐   WS    ┌──────────────┐
│  React UI    │ ────────▶ │ WebSocketBridge│ ──────▶ │ OpenAI       │
│  (jarvis-ui) │ ◀──────── │  + HTTP API    │ ◀────── │ Realtime API │
└──────────────┘           └────────────────┘         └──────┬───────┘
                                  │                          │ tool call
                                  │                          ▼
                                  │                  ┌───────────────┐
                                  │                  │  Agent Router │
                                  │                  └───────┬─────┘
                                  │                          │
                              settings.json              dispatch to tools
                              (~/.jarvis)
```
