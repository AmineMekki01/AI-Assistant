# JARVIS UI

React + TypeScript + Vite voice interface for the JARVIS assistant. Hold the mic button, speak, and JARVIS responds.

---

## What You Need

- **Node.js 18+**
- The **Python backend** running on `ws://localhost:8000`

If you want to use speaker verification, the backend must also have speaker verification enabled and an enrolled profile available. The Voice tab can manage that profile directly.

---

## Setup

```bash
npm install
```

---

## Run

```bash
npm run dev
```

Open http://localhost:5173.

> The Vite dev server proxies WebSocket traffic to `ws://localhost:8000` automatically (see `vite.config.ts`). No CORS headaches.

---

## Testing

### 1. Check the backend is alive

```bash
curl http://localhost:8001/api/health
```

If you don't get `{"status":"ok"}`, start the backend first:

```bash
cd ../jarvis_desktop
./run.sh
```

### 2. Open the browser console

Look for:
- `WebSocket connected` - the UI reached the backend
- `Speaking state: true` - JARVIS is talking
- Audio level meter moving when you hold the mic button - your microphone works

### 3. Talk to JARVIS

- Press and hold the **mic button**
- Say something (e.g. "What time is it?")
- Release - JARVIS should respond within a second or two

---

## WebSocket Protocol

The UI connects to `ws://localhost:8000/ws` and exchanges:

### Outgoing Messages (to backend)
```json
{"type": "toggle_recording"}           # Start/stop recording
{"type": "audio_chunk", "data": "..."}  # Base64 audio data
```

### Incoming Messages (from backend)
```json
{"type": "message", "role": "assistant", "text": "Hello Amine"}
{"type": "user_transcript", "text": "What time is it?"}
{"type": "recording", "isRecording": true}
{"type": "jarvis_speaking", "isSpeaking": true}
{"type": "status", "connected": true}
```

## Project Structure

```
jarvis-ui/
├── src/
│   ├── components/
│   │   ├── SettingsModal.tsx   # Settings UI (personal info, integrations)
│   │   └── SettingsModal.css   # Settings styles
│   ├── hooks/
│   │   ├── useWebSocket.ts     # WebSocket connection management
│   │   ├── useAudio.ts         # Audio recording and streaming
│   │   └── useSettings.ts      # Settings state and persistence
│   ├── App.tsx                 # Main application component
│   ├── App.css                 # Main application styles
│   ├── index.css               # Global styles
│   └── main.tsx                # Entry point
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

## Settings

Settings are persisted to `~/.jarvis/settings.json` via the backend:

- **Personal Info** - Name, default location, timezone
- **Integrations** - Google OAuth, Tavily API key, Qdrant settings
- **Obsidian Vault** - Path for knowledge base sync
- **Voice tab** - Speaker verification enrollment, profile status, and profile clearing

The Voice tab uploads or records sample speech, then sends it to the backend to create or replace the speaker profile. When a profile is saved, the backend refreshes its in-memory cache automatically.

