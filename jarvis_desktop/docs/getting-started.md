# Getting started

## Requirements

JARVIS runs on macOS. Python 3.10 or newer is required. Install Homebrew's
PortAudio package before installing Python dependencies because PyAudio uses it
for microphone input and assistant audio output.

```bash
brew install portaudio
cd jarvis_desktop
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. The remaining services are optional, except
Qdrant when you want durable memory or Obsidian knowledge search.

## Start Qdrant

Long-term memory and Obsidian knowledge both use Qdrant. Start it before using
either feature:

```bash
docker run --name jarvis-qdrant -p 6333:6333 qdrant/qdrant
```

Check that it is available:

```bash
curl http://localhost:6333
```

JARVIS does not write a local memory fallback. If Qdrant is unavailable, a
memory write remains a failed background operation and memory recall reports
that the service is unavailable until it is restored.

## Run the backend

Run this from `jarvis_desktop/`:

```bash
./run.sh
```

The backend opens a WebSocket server on port 8000 and an HTTP API on port 8001
by default. The UI is a separate process; start it from the frontend project
and open `http://localhost:5173`.

```text
WebSocket: ws://localhost:8000/ws
HTTP API:  http://localhost:8001
```

## Check the running system

```bash
curl http://localhost:8001/api/health
curl http://localhost:8001/api/qdrant/status
curl http://localhost:8001/api/apple_calendar/status
```

The health endpoint reports the backend state and its Qdrant probe. The
Calendar endpoint tells you whether macOS access has been granted.

## macOS permissions

macOS asks for permissions the first time a feature uses them. Grant Calendar
access to the process running JARVIS for Apple Calendar. Automation and
Accessibility are needed for AppleScript-based computer controls. Microphone
access is required for native wake-word listening.

Open **System Settings → Privacy & Security** to review or reset a permission.
