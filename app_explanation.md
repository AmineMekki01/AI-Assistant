# JARVIS - System Architecture Overview

A voice-first AI assistant for macOS that combines local wake-word detection, speaker verification, and OpenAI's Realtime API for natural conversational interactions.

---

## 1. High-Level Architecture

```
┌─────────────────┐         WebSocket         ┌─────────────────────┐
│   jarvis-ui     │ ◄───────────────────────► │    jarvis_desktop   │
│  (React + TS)   │      (React frontend)       │   (Python backend)  │
└────────┬────────┘                             └─────────────────────┘
         │                                               │
         │                    ┌────────────────────────┘
         │                    │
         ▼                    ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  User Speaks    │───►│  Native Voice   │───►│  OpenAI Realtime│
│  (Microphone)   │    │  Loop (local)   │    │  API (WebSocket)│
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                          │
                                                          ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Audio Output   │◄───│  Audio Player   │◄───│  JARVIS Response│
│  (Speakers)     │    │  (pyaudio)      │    │  (voice + text) │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

---

## 2. Project Structure

```
AI-Assistant/
├── jarvis_desktop/          # Python backend (the brain)
│   ├── main.py              # Entry point, voice loop, audio pipeline
│   ├── app/
│   │   ├── core/            # Core systems
│   │   │   ├── realtime_session.py   # OpenAI Realtime API session
│   │   │   ├── websocket_bridge.py   # WebSocket server for UI
│   │   │   ├── music_state.py        # Apple Music playback state
│   │   │   ├── speaker_verification.py # Voice enrollment / auth
│   │   │   ├── config.py             # Settings & env vars
│   │   │   └── logging.py            # Structured logging
│   │   ├── runtime/         # Agent & tool runtime
│   │   │   ├── registry.py            # Tool/action registry
│   │   │   ├── agent_base.py          # Base agent class
│   │   │   └── orchestrator.py        # Main reasoning coordinator
│   │   ├── tools/           # Available tools (decorator pattern)
│   │   │   ├── music_playback.py      # Play/pause/stop music
│   │   │   ├── music_library.py       # Local Apple Music search
│   │   │   ├── websearch.py           # Tavily web search
│   │   │   ├── system_control.py      # Volume, DND, open apps
│   │   │   ├── reminders.py           # Create/manage reminders
│   │   │   └── mail_templates.py      # Email composition
│   │   ├── actions/         # High-level actions (orchestrator calls)
│   │   │   └── music_play.py          # Smart music playback
│   │   ├── agents/          # Specialized agents
│   │   │   └── focus.py               # Startup briefing agent
│   │   ├── api/             # REST API handlers
│   │   ├── services/        # External service integrations
│   │   └── memory/          # Long-term memory & knowledge
│   └── tests/               # pytest suite
│
└── jarvis-ui/               # React frontend
    ├── src/
    │   ├── App.tsx          # Main UI component
    │   ├── components/      # UI components
    │   └── hooks/           # React hooks
    └── index.html           # Entry point
```

---

## 3. How Agents & Tools Work

### 3.1 The Registry Pattern

Tools and actions are registered using **Python decorators**. The `ToolRegistry` automatically collects them at import time.

```python
# Example: app/tools/music_playback.py
@tool(
    name="computer_music_control",
    description="Control music playback: play, pause, stop, next, previous",
    parameters={...}
)
async def computer_music_control(action: str) -> str:
    # Implementation here
    ...
```

When the app starts, `load_all_capabilities()` scans all modules and registers every decorated function. The registry then converts them into **OpenAI function schemas** so the Realtime model knows what it can call.

### 3.2 The Orchestrator (Central Brain)

The `Orchestrator` is the single reasoning core:

1. **Receives** transcribed user text
2. **Decides** whether to use a tool, delegate to an agent, or reply directly
3. **Executes** the chosen path via the `ToolRegistry`
4. **Returns** a text response that gets spoken aloud

```
User Speech → Transcription → Orchestrator.handle()
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
               Direct Reply     Tool Call      Delegate to Agent
                    │               │               │
                    ▼               ▼               ▼
               "Here's..."    Play Music     Startup Briefing
```

### 3.3 Tools vs Actions

| Type | Purpose | Example |
|------|---------|---------|
| **Tools** | Atomic operations the model can call | `computer_music_control("stop")` |
| **Actions** | Higher-level logic, may call multiple tools | `computer_play_music(query)` — searches library, then catalog, then plays |
| **Agents** | Specialized reasoning modules | Startup briefing agent generates daily summary |

---

## 4. Audio Flow (Voice Interaction)

### 4.1 Step-by-Step Voice Command

```
Step 1: LISTENING (always-on)
┌─────────────────────────────────────────────┐
│ Native Voice Loop (main.py)                 │
│ • Reads mic at 16kHz mono                   │
│ • Runs openWakeWord model locally           │
│ • Detects "Hey JARVIS" wake word            │
│ • Detects clap trigger as alternative       │
└─────────────────────────────────────────────┘
                      │
                      ▼
Step 2: RECORDING
┌─────────────────────────────────────────────┐
│ • Starts recording user speech               │
│ • Buffers audio chunks                       │
│ • Detects silence → auto-stop                │
│ • Optional: speaker verification             │
└─────────────────────────────────────────────┘
                      │
                      ▼
Step 3: TRANSCRIPTION
┌─────────────────────────────────────────────┐
│ • Audio sent to OpenAI Realtime API          │
│ • Realtime model transcribes ( Whisper )     │
│ • Transcript forwarded to Orchestrator       │
└─────────────────────────────────────────────┘
                      │
                      ▼
Step 4: REASONING
┌─────────────────────────────────────────────┐
│ Orchestrator.handle(user_text)               │
│ • Parses intent                              │
│ • Calls appropriate tools/actions            │
│ • Generates response text                    │
└─────────────────────────────────────────────┘
                      │
                      ▼
Step 5: RESPONSE
┌─────────────────────────────────────────────┐
│ • Response text sent to speak()              │
│ • On macOS: direct OpenAI TTS → afplay       │
│ • Fallback: Realtime API voice generation    │
│ • Audio played through speakers (pyaudio)    │
└─────────────────────────────────────────────┘
```

### 4.2 Key Audio Behaviors

| Scenario | Behavior |
|----------|----------|
| **Music playing + voice command** | System volume auto-ducks to 30% while listening, restores after |
| **JARVIS speaking + user interrupts** | Audio queue cleared, mic resumes immediately |
| **Speaker not enrolled** | Graceful fallback (no rejection, just logs) |
| **Follow-up within 5 min** | No wake word needed — passive listening mode |
| **Clap detected** | Alternative activation when music is NOT playing |

---

## 5. Core Components Explained

### 5.1 `realtime_session.py`

Manages the WebSocket connection to OpenAI's Realtime API:
- **Session config**: Disables auto-responses (`create_response=false`) so the orchestrator controls all speech
- **Audio commit**: Sends recorded audio for transcription
- **Tool handling**: Receives function calls from the model, executes via registry, returns results
- **Speech**: Uses direct TTS on macOS for verbatim playback (avoids model paraphrasing)

### 5.2 `websocket_bridge.py`

WebSocket server connecting backend to React frontend:
- Receives: recording toggle, audio chunks, mail confirmations
- Sends: transcripts, status updates, audio output, mail drafts
- Enables browser-based interaction alongside voice

### 5.3 `music_state.py`

Tracks Apple Music playback state:
- `is_music_playing()` — cached query to avoid AppleScript overhead
- `set_voice_followup_override()` — allows passive listening for 8s after starting music
- Prevents clap triggers during music while still allowing wake words

### 5.4 `speaker_verification.py`

Voice biometric authentication:
- Enrolls speaker voiceprint on first run
- Compares incoming audio against stored profile
- Configurable threshold for similarity matching

---

## 6. Startup Flow

```
1. main.py starts
   ├── Load environment variables (.env)
   ├── Initialize Orchestrator
   ├── Start WebSocket bridge (port 8000)
   ├── Start Realtime API session (background thread)
   ├── Start native voice listener (background thread)
   ├── Start reminder poller (background thread)
   └── Wait for user interaction

2. On first voice activation:
   ├── Play activation sound (optional)
   ├── Run startup briefing agent (daily summary)
   └── Enter listening mode (5-min follow-up window)
```

---

## 7. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Orchestrator as single brain** | All reasoning flows through one place; Realtime model is voice-only (transcription + speech) |
| **Direct TTS on macOS** | Prevents the Realtime model from reinterpreting/rephrasing orchestrator responses |
| **Turn detection disabled** | `create_response=false` prevents the model from speaking before the orchestrator is ready |
| **Volume ducking** | Lets the mic hear commands over music without pausing playback entirely |
| **Registry pattern** | Adding a new tool = adding a decorated function; zero boilerplate registration |

---

## 8. Quick Command Reference

```bash
# Start the backend
cd jarvis_desktop && python main.py

# Or use the run script
./run.sh

# Start the frontend (separate terminal)
cd jarvis-ui && npm run dev

# Run tests
cd jarvis_desktop && pytest
```

---

*JARVIS = Just A Rather Very Intelligent System*
