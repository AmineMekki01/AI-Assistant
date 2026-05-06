"""
OpenAI Realtime API Session for Desktop App
"""

import asyncio
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import textwrap
from typing import Any, AsyncIterator, Callable, Optional

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from .logging import StructuredLog
from ..runtime import REGISTRY, load_all_capabilities

log = StructuredLog(__name__)

INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000


def _realtime_url() -> str:
    from .config import get_settings
    model = get_settings().openai_realtime_model
    return f"wss://api.openai.com/v1/realtime?model={model}"

def _detect_integrations() -> dict:
    """Inspect on-disk state to figure out which integrations are live."""
    import json as _json
    from pathlib import Path as _Path

    home = _Path.home()
    settings_path = home / ".jarvis" / "settings.json"
    settings: dict = {}
    try:
        if settings_path.exists():
            settings = _json.loads(settings_path.read_text()) or {}
    except Exception:
        settings = {}

    google_connected = (home / ".jarvis" / "google_token.json").exists()
    z = settings.get("zimbra") or {}
    zimbra_configured = bool(z.get("enabled") and z.get("email") and z.get("password"))
    ac = settings.get("appleCalendar") or {}
    apple_cal_enabled = bool(ac.get("enabled"))

    obsidian_count = 0
    try:
        ob_status = home / ".jarvis" / "obsidian_status.json"
        if ob_status.exists():
            data = _json.loads(ob_status.read_text()) or {}
            if data.get("synced"):
                obsidian_count = int(data.get("fileCount") or 0)
    except Exception:
        pass

    return {
        "google": google_connected,
        "zimbra": zimbra_configured,
        "apple_calendar": apple_cal_enabled,
        "obsidian_notes": obsidian_count,
        "default_apple_calendar": ac.get("defaultCalendar", ""),
    }


def _fetch_apple_calendars() -> list:
    """List the user's macOS Calendar names (best effort, silent on failure)."""
    import subprocess as _subprocess
    import sys as _sys
    if _sys.platform != "darwin":
        return []
    try:
        proc = _subprocess.run(
            ["osascript", "-e", 'tell application "Calendar" to return name of every calendar'],
            capture_output=True, text=True, timeout=6,
        )
        if proc.returncode != 0:
            return []
        return [n.strip() for n in (proc.stdout or "").split(",") if n.strip()]
    except Exception:
        return []


def _fetch_memory_primer(limit: int = 8) -> str:
    """Best-effort fetch of the most recent memories for the system prompt.

    Uses sync ``httpx`` so it's safe to call from within an async ``configure()``
    path. Falls back to the local JSON file if Qdrant is down.
    """
    import os as _os
    qdrant_url = _os.getenv("QDRANT_URL", "http://localhost:6333")
    collection = _os.getenv("QDRANT_MEMORY_COLLECTION", "long_term_memory")
    user_id = _os.getenv("JARVIS_USER_ID", "user")
    try:
        import httpx as _httpx
        with _httpx.Client(timeout=4.0) as http:
            resp = http.post(
                f"{qdrant_url}/collections/{collection}/points/scroll",
                json={
                    "limit": max(1, min(int(limit), 50)),
                    "with_payload": True,
                    "with_vector": False,
                    "filter": {"must": [{"key": "user_id", "match": {"value": user_id}}]},
                },
            )
            if resp.status_code == 200:
                points = (resp.json().get("result") or {}).get("points") or []
                points.sort(
                    key=lambda p: (p.get("payload", {}) or {}).get("timestamp", ""),
                    reverse=True,
                )
                lines = []
                for p in points[:limit]:
                    pl = p.get("payload", {}) or {}
                    lines.append(f"- [{pl.get('category', 'other')}] {pl.get('content', '')}")
                return "\n".join(lines)
    except Exception:
        pass

    try:
        import json as _json
        from pathlib import Path as _Path
        path = _Path.home() / ".jarvis" / "memories.json"
        if not path.exists():
            return ""
        data = _json.loads(path.read_text()) or []
        data.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
        return "\n".join(
            f"- [{m.get('category', 'other')}] {m.get('content', '')}" for m in data[:limit]
        )
    except Exception:
        return ""


def _response_style_block() -> str:
    return """── Response style ────────────────────────────────────────────────
  • Answer the user's question first.
  • Avoid reintroducing yourself or repeating "Certainly, sir" unless the user has
    just made a request that needs a brief acknowledgment.
  • Prefer plain, natural English over ornate or overly ceremonial wording.
  • If the answer is simple, keep it simple. Do not pad with extra reassurance.
  • This brevity rule does NOT apply to delegated briefings or other
    explicitly requested multi-part summaries. In those cases, speak the full
    answer clearly and do not compress it into a one-line recap.
  • For delegated briefings, the briefing result is already the final answer.
    Speak it back as-is, in full, without adding a wrapper like "That’s your
    daily briefing", without summarising it, and without appending a question.
  • If the user asks for a greeting or says something like "say hi", answer with
    one short greeting sentence only. Do not add a follow-up question unless the user
    explicitly asks for conversation.
  • If the user asks "how are you" / "how are you doing" / similar status checks,
    answer with a brief status only and do not start with "good morning/afternoon/evening".
    Do not add a follow-up question.
"""


def _current_context_block(date_str: str, time_str: str, tz_str: str, location: str) -> str:
    return f"""── Current context ──────────────────────────────────────────────
  • Date: {date_str}
  • Time: {time_str} ({tz_str})
  • Location: {location or 'unknown'}
"""


def _connected_services_block(integrations: dict[str, Any], apple_calendars: list[str]) -> str:
    int_lines = [
        f"  • Gmail / Google Calendar: {'connected' if integrations['google'] else 'NOT connected'}",
        f"  • Zimbra / OVH mail: {'connected' if integrations['zimbra'] else 'not configured'}",
        f"  • Apple Calendar: {'enabled' if integrations['apple_calendar'] else 'disabled'}"
        + (f" (calendars: {', '.join(apple_calendars[:8])})" if apple_calendars else ""),
        f"  • Obsidian vault: {integrations['obsidian_notes']} note(s) indexed"
        if integrations['obsidian_notes'] else "  • Obsidian vault: not synced",
    ]

    return f"""── Connected services ───────────────────────────────────────────
{chr(10).join(int_lines)}
"""


def _memory_block(memory_primer: str) -> str:
    mem_block = memory_primer.strip() if memory_primer and memory_primer.strip() else "(none yet)"
    return f"""── What you already know about the user ─────────────────────────
{mem_block}
"""


def _transcription_prompt(user_name: str) -> str:
    cleaned_name = user_name.strip()
    if not cleaned_name or cleaned_name.lower() == "sir":
        return ""

    return (
        "Transcribe the user's speech verbatim. "
        "Preserve names and proper nouns exactly as spoken. "
        "Preserve the wake word 'Jarvis' exactly if it is spoken. "
        f"Preserve the user's name '{cleaned_name}' exactly if it is spoken. "
        "Do not substitute similar names when audio is unclear."
    )


def get_jarvis_persona() -> str:
    """Generate the JARVIS system prompt with live context injected at session start."""
    from datetime import datetime
    from .config import get_settings

    settings = get_settings()
    personal = settings.personal_info

    user_name = personal.get("name") or "sir"
    location = personal.get("defaultLocation", "")
    timezone = personal.get("timezone", "")

    now = datetime.now().astimezone()
    date_str = now.strftime("%A, %B %d %Y")
    time_str = now.strftime("%H:%M")
    tz_str = timezone or str(now.tzinfo)

    integrations = _detect_integrations()
    apple_calendars = _fetch_apple_calendars() if integrations["apple_calendar"] else []
    memory_primer = _fetch_memory_primer(8)

    persona = f"""You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the refined
British AI butler modelled on Tony Stark's personal assistant. You address the user as
"{user_name}" or "sir". Speak with a calm, composed, sophisticated British tone - polite,
articulate, and subtly dry-witted. Use slightly formal phrasing sparingly; do not
repeat the same opener in every reply. Never use casual filler words.
Keep spoken replies brief and direct (usually 1-2 sentences) unless the user asks
for detail.

{_response_style_block()}

{_current_context_block(date_str, time_str, tz_str, location)}

{_connected_services_block(integrations, apple_calendars)}

{_memory_block(memory_primer)}

── Tool-argument faithfulness (CRITICAL) ────────────────────────
  • Pass the user's words into tool arguments VERBATIM. Never silently correct,
    "fix", translate, or substitute values. If the user says "Play Good 4 U by
    Selena Gomez", the `query` is literally "Good 4 U by Selena Gomez" - do NOT
    swap it for a different song just because you think the artist is wrong.
  • If something seems ambiguous or wrong, ASK ONE clarifying question out loud
    before calling the tool. Do not guess on the user's behalf.

── Tool-usage policy ────────────────────────────────────────────
  • Mail: ALWAYS use `mail_list` / `mail_search` (they fan out across Gmail and Zimbra).
    For ANY request to compose, draft, write, or send an email, call `mail_send` first
    WITHOUT `confirmed` - you will receive a DRAFT preview. Do NOT freeform-compose the
    email in your own reply. Read the preview aloud, ask "Shall I send it?", and only
    after the user clearly says yes call `mail_send` again with `confirmed: true`.
  • Calendar: ALWAYS use `calendar_list` (fans out over Google + Apple Calendar -
    iCloud, Holidays, Birthdays, Fêtes and subscribed calendars only exist on Apple).
    For creating events, use `calendar_create` with the same preview-then-confirm
    pattern as mail. Default `source: "google"`, switch to `"apple"` if the user
    names a local calendar like "Personnel" or "Travail".
  • Music: Default path is a single call to `computer_play_music` with the user's
    phrase verbatim as `query` (e.g. "Good 4 U by Selena Gomez", even if the artist
    attribution seems wrong). The tool first fuzzy-matches against the cached local
    library and plays the best match by database ID; if no confident library match
    exists it falls through to the Apple Music catalog. If the tool returns "not
    found", or the user says the wrong track played, call `music_library_search`
    with a shorter query (song title alone, or artist alone) to inspect the library,
    then retry `computer_play_music` passing the chosen `database_id`. Use
    `computer_music_control` for play/pause/next/prev and `computer_set_volume`
    for volume.
  • Obsidian: Use `knowledge_ask` for grounded answers from the user's vault,
    `knowledge_search` for raw matches.
  • Memory (hybrid):
    - STORING: When the user states a DURABLE fact about themselves
      (preference, relationship, goal, schedule, identity), acknowledge it and
      silently call `memory_remember` with the appropriate category. Do NOT
      remember transient or one-off info (today's weather, a single task).
    - RECALLING: When the user asks anything self-referential - "what do you
      know about me", "who am I", "tell me about myself", "what are my
      preferences", "remind me who X is" - ALWAYS call `memory_recall` FIRST
      with the user's phrasing, then answer from the result. If nothing
      relevant comes back, say so honestly and offer to remember something.
      Also call `memory_recall` before acting on any personal preference.
  • Delegation to sub-agents (for COMPLEX, multi-step tasks only):
    - `delegate_to_research` - open-ended questions that benefit from
      consulting multiple sources (notes + web, memory + web, etc.). Example
      triggers: "what's the weather where my sister lives", "remind me what
      I wrote about the Taipei trip and find related articles".
    - `delegate_to_briefing` - ALWAYS use this for daily briefing and catch-up
      requests that need a structured spoken briefing across calendar, mail,
      reminders, and notes. Example triggers: "give me my daily briefing",
      "what's my day", "catch me up this morning".
      Before calling it, first say one short acknowledgement out loud such as
      "Hang on — I’m looking into your calendar and mail now." Then call the
      tool. When the briefing comes back, speak the result directly and in full.
      Do not replace it with "That’s your daily briefing" or any shorter
      paraphrase, and do not add a follow-up question unless the briefing itself
      explicitly requires one.
      Only use this tool when the user has clearly asked for a briefing or catch-
      up. Do NOT use it for vague partial utterances such as "latest information
      about..." or unfinished fragments that do not name a specific subject.
      If the utterance sounds incomplete or could just as easily be a general
      research query, ask a clarifying question instead of delegating. If the
      user is asking about a specific topic or current facts outside their own
      calendar/mail context, prefer `delegate_to_research` instead.
    - `delegate_to_workspace` - multi-step triage across mail/calendar/notes.
      Example triggers: "what do I have this week and what should I prep",
      "summarise unread emails that need action", "anything conflicting with
      the dentist tomorrow". If the workspace agent returns a line starting
      with "Proposed action:", read it to the user, ask for confirmation,
      then execute via `mail_send` / `calendar_create` yourself.
    - Do NOT delegate single-source lookups - `web_search`, `knowledge_ask`,
      `memory_recall`, `mail_list`, `calendar_list` etc. are faster direct.
  • If a request can't be satisfied with the available tools, say so briefly -
    there is no generic UI-automation fallback. Don't pretend to perform
    actions you can't actually execute.

Always respond in English, regardless of what language the user speaks.
"""

    return persona


def _parse_mail_draft_preview(output: str) -> dict[str, Any] | None:
    """Parse the structured draft preview returned by mail_send."""
    if not output.startswith("DRAFT (not sent yet - ask the user to confirm):"):
        return None

    pattern = re.compile(
        r"^DRAFT \(not sent yet - ask the user to confirm\):\n"
        r"\s+Account:\s*(?P<account>gmail|zimbra)\n"
        r"\s+To:\s*(?P<to>.+)\n"
        r"\s+Subject:\s*(?P<subject>.+)\n"
        r"\s+Body:\n"
        r"(?P<body>[\s\S]*?)(?:\n\nRead this draft back|\Z)",
        re.IGNORECASE,
    )
    match = pattern.match(output)
    if not match:
        return None

    body = textwrap.dedent(match.group("body")).rstrip()
    return {
        "account": match.group("account").lower(),
        "to": match.group("to").strip(),
        "subject": match.group("subject").strip(),
        "body": body,
        "rawText": output,
    }


class RealtimeSession:
    """Direct WebSocket connection to OpenAI Realtime API."""
    
    def __init__(self, on_transcript: Optional[Callable[[str, str], None]] = None,
                 on_audio: Optional[Callable[[bytes], None]] = None,
                 on_status: Optional[Callable[[str, str], None]] = None,
                 on_speaking: Optional[Callable[[bool], None]] = None,
                 on_mail_draft: Optional[Callable[[dict[str, Any]], None]] = None):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.ws: Optional[ClientConnection] = None
        self._pump_task: Optional[asyncio.Task] = None
        self.on_transcript = on_transcript
        self.on_audio = on_audio
        self.on_status = on_status
        self.on_speaking = on_speaking
        self.on_mail_draft = on_mail_draft
        load_all_capabilities()
        self.tools = REGISTRY.as_openai_tool_list()
        self._reconnect_lock: Optional[asyncio.Lock] = None
        self._intentional_close = False
        self._tool_tasks: set[asyncio.Task] = set()
        self._reset_runtime_state()

    def _reset_runtime_state(self) -> None:
        self._recv_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        self._closed = asyncio.Event()
        self.response_buffer = ""
        self.has_responded = False
        self._response_active = False
        self._last_response_create_at: float = 0.0
        self._push_to_queue = True
        self._commit_ack_event: Optional[asyncio.Event] = None

    def reset_turn(self) -> None:
        """Reset the assistant turn state without touching the socket."""
        self.has_responded = False
        self.response_buffer = ""

    async def interrupt_active_response(self) -> None:
        """Cancel any in-progress assistant response when the user starts speaking."""
        self.reset_turn()

        if not self._response_active:
            return

        log.info("realtime.response_interrupted")
        await self.send_event({"type": "response.cancel"})
        self._response_active = False
        
    async def connect(self) -> None:
        """Connect to OpenAI Realtime API."""
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        
        log.info("realtime.connecting")
        
        headers = [
            ("Authorization", f"Bearer {self.api_key}"),
            ("OpenAI-Beta", "realtime=v1"),
        ]
        
        self.ws = await websockets.connect(
            _realtime_url(),
            additional_headers=headers,
            max_size=16 * 1024 * 1024,
            ping_interval=15,
            ping_timeout=45,
        )
        
        log.info("realtime.connected")
        self._reset_runtime_state()
        self._commit_ack_event = asyncio.Event()
        self._pump_task = asyncio.create_task(self._pump(), name="realtime-pump")
    
    async def configure(self) -> None:
        """Configure the session with JARVIS persona and tools."""
        log.info("realtime.configuring")
        
        async for evt in self.events():
            if evt.get("type") == "session.created":
                log.info("realtime.session_created")
                break
            if evt.get("type") == "error":
                raise RuntimeError(f"OpenAI error: {evt}")


        self._push_to_queue = False

        while not self._recv_queue.empty():
            try:
                self._recv_queue.get_nowait()
            except Exception:
                break

        realtime_tools = self.tools
        self._log_tool_catalog(realtime_tools)

        await self.send_event(self._build_session_config(realtime_tools))
        
        self.has_responded = False
        
        log.info("realtime.configured")

    def _build_session_config(self, realtime_tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the session.update payload sent to the Realtime API."""
        from app.core.config import get_settings

        app_settings = get_settings()
        personal = app_settings.personal_info
        user_name = personal.get("name") or ""
        transcription_prompt = _transcription_prompt(user_name)

        input_audio_transcription: dict[str, Any] = {
            "model": "whisper-1",
            "language": "en",
        }
        if transcription_prompt:
            input_audio_transcription["prompt"] = transcription_prompt

        session = {
            "modalities": ["audio", "text"],
            "voice": app_settings.openai_realtime_voice,
            "instructions": get_jarvis_persona(),
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": input_audio_transcription,
            "turn_detection": None,
            "tool_choice": "auto",
            "temperature": 0.6,
        }
        if realtime_tools:
            session["tools"] = realtime_tools
        return {
            "type": "session.update",
            "session": session,
        }

    def _log_tool_catalog(self, realtime_tools: list[dict[str, Any]]) -> None:
        """Validate the tool list before sending it to OpenAI."""
        if not realtime_tools:
            return

        log.info(
            "🔧 TOOLS_REGISTERED",
            count=len(realtime_tools),
            names=[t.get("name", "EMPTY") for t in realtime_tools],
        )

        for i, tool in enumerate(realtime_tools):
            name = tool.get("name", "")
            if not name:
                log.error(f"X EMPTY_TOOL_NAME at index {i}", tool=tool)

    @staticmethod
    def _parse_tool_arguments(arguments: str) -> dict[str, Any]:
        """Safely decode the model-provided tool arguments."""
        try:
            return json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _stringify_tool_output(output_data: Any) -> str:
        """Convert a registry result into the string payload OpenAI expects."""
        if isinstance(output_data, (dict, list)):
            return json.dumps(output_data, ensure_ascii=False, default=str)
        return str(output_data)

    async def _speak_direct_text(self, text: str) -> None:
        """Speak text directly so briefing output is not paraphrased.

        Prefer OpenAI text-to-speech with the same configured JARVIS voice so
        the briefing sounds consistent with the rest of the assistant.
        """
        if self.on_transcript:
            self.on_transcript("assistant", text)

        if self.on_speaking:
            try:
                self.on_speaking(True)
            except Exception as e:
                log.debug("direct_speech.speaking_start_failed", error=str(e))

        try:
            from .config import get_settings

            app_settings = get_settings()
            if sys.platform == "darwin" and app_settings.openai_api_key:
                tts_url = "https://api.openai.com/v1/audio/speech"
                payload = {
                    "model": "tts-1",
                    "voice": app_settings.openai_realtime_voice,
                    "input": text,
                    "response_format": "mp3",
                }

                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(
                        tts_url,
                        headers={
                            "Authorization": f"Bearer {app_settings.openai_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    response.raise_for_status()

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp.write(response.content)
                    audio_path = tmp.name

                try:
                    if shutil.which("afplay"):
                        process = await asyncio.create_subprocess_exec(
                            "afplay",
                            audio_path,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        await process.wait()
                    else:
                        log.warning("direct_speech.player_missing", player="afplay")
                finally:
                    try:
                        os.unlink(audio_path)
                    except Exception:
                        pass
            elif sys.platform == "darwin" and shutil.which("say"):
                process = await asyncio.create_subprocess_exec(
                    "say",
                    text,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await process.wait()
            else:
                log.warning("direct_speech.unavailable", platform=sys.platform)
        finally:
            if self.on_speaking:
                try:
                    self.on_speaking(False)
                except Exception as e:
                    log.debug("direct_speech.speaking_end_failed", error=str(e))

    def _handle_binary_pump_message(self, msg: bytes) -> None:
        if not self.on_audio:
            return

        try:
            self.on_audio(msg)
        except Exception as e:
            log.error("audio_callback_error", error=str(e))

    async def _handle_text_pump_message(self, msg: str) -> None:
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            log.warning("non_json_message", preview=msg[:120])
            return

        await self._handle_pump_event(data)

    def _handle_response_event(self, evt_type: str, data: dict[str, Any]) -> None:
        if evt_type == "response.created":
            self._response_active = True
            rid = (data.get("response") or {}).get("id", "?")
            log.info(f"🎬 response.created | id={rid}")
            return

        if evt_type == "response.cancelled":
            self._response_active = False
            log.info("response.cancelled")
            return

        if evt_type == "response.audio.delta":
            audio_delta = data.get("delta", "")
            if audio_delta and self.on_audio:
                try:
                    audio_bytes = base64.b64decode(audio_delta)
                    self.on_audio(audio_bytes)
                except Exception as e:
                    log.error("audio_delta_callback_error", error=str(e))
            return

        if evt_type == "response.audio.done":
            log.info("response.audio.done")
            self.has_responded = True
            return

        if evt_type == "response.done":
            log.info("response.done")
            self.has_responded = True
            self._response_active = False

            resp = data.get("response") or {}
            status = resp.get("status")
            if status and status != "completed":
                log.error(
                    "🚨 response.done non-completed",
                    status=status,
                    status_details=resp.get("status_details"),
                )

    def _handle_commit_event(self, evt_type: str, data: dict[str, Any]) -> None:
        if evt_type == "input_audio_buffer.committed":
            item_id = data.get("item_id", "?")
            log.info(f"📝 input_audio_buffer.committed | item_id={item_id}")
            if self._commit_ack_event is not None:
                self._commit_ack_event.set()
            return

        if evt_type == "input_audio_buffer.speech_started":
            log.info("input_audio_buffer.speech_started")
            return

        if evt_type == "input_audio_buffer.speech_stopped":
            log.info("input_audio_buffer.speech_stopped")

    def _handle_item_event(self, evt_type: str, data: dict[str, Any]) -> None:
        if evt_type != "conversation.item.created":
            return

        item = data.get("item") or {}
        log.info(
            f"conversation.item.created | type={item.get('type','?')} "
            f"role={item.get('role','?')}"
        )

    def _handle_transcript_event(self, evt_type: str, data: dict[str, Any]) -> None:
        if evt_type == "conversation.item.input_audio_transcription.completed":
            transcript = data.get("transcript", "")
            if transcript:
                log.info("🎤 USER_SAID", text=transcript)
                if self.on_transcript:
                    self.on_transcript("user", transcript)
                if os.getenv("MEMORY_AUTO_EXTRACT", "true").lower() == "true":
                    asyncio.create_task(self._extract_and_maybe_store_memory(transcript))
            return

        if evt_type == "response.audio_transcript.delta":
            delta = data.get("delta", "")
            self.response_buffer += delta
            if self.on_transcript:
                self.on_transcript("assistant", self.response_buffer)
            return

        if evt_type == "response.audio_transcript.done":
            if self.response_buffer:
                log.info("🤖 JARVIS_SAID", text=self.response_buffer[:200])
            self.response_buffer = ""

    async def _handle_tool_call_event(self, evt_type: str, data: dict[str, Any]) -> None:
        if evt_type != "response.function_call_arguments.done":
            return

        task = asyncio.create_task(self._handle_tool_call(data))
        self._tool_tasks.add(task)
        task.add_done_callback(self._tool_tasks.discard)

    def _queue_pump_event(self, data: dict[str, Any]) -> None:
        if not self._push_to_queue:
            return

        try:
            self._recv_queue.put_nowait(data)
        except asyncio.QueueFull:
            try:
                self._recv_queue.get_nowait()
                self._recv_queue.put_nowait(data)
            except Exception:
                pass

    async def _handle_pump_event(self, data: dict[str, Any]) -> None:
        evt_type = data.get("type", "")

        if evt_type == "error":
            log.error("realtime.error", error=data)

        self._handle_response_event(evt_type, data)
        self._handle_commit_event(evt_type, data)
        self._handle_item_event(evt_type, data)
        self._handle_transcript_event(evt_type, data)
        await self._handle_tool_call_event(evt_type, data)
        self._queue_pump_event(data)
    
    async def _pump(self) -> None:
        """Pump messages from WebSocket to queue."""
        assert self.ws is not None
        
        try:
            async for msg in self.ws:
                if isinstance(msg, bytes):
                    self._handle_binary_pump_message(msg)
                    continue

                await self._handle_text_pump_message(msg)
                
        except websockets.exceptions.ConnectionClosed:
            log.info("realtime.connection_closed")
        except Exception as e:
            log.error("realtime.pump_error", error=str(e))
        finally:
            self._closed.set()
    
    async def _handle_tool_call(self, data: dict) -> None:
        """Handle a tool/action/agent call from the model via the registry."""
        call_id = data.get("call_id", "")
        name = data.get("name", "")
        arguments = data.get("arguments", "{}")

        log.info("🔧 TOOL_CALL_START", name=name, call_id=call_id)
        log.info("📥 TOOL_CALL_ARGS", name=name, args=arguments)

        args = self._parse_tool_arguments(arguments)
        if arguments and not args:
            log.error("X TOOL_CALL_PARSE_ERROR", name=name, raw_arguments=arguments)

        dispatch_start = asyncio.get_event_loop().time()
        briefing_status_sent = False
        if name == "delegate_to_briefing" and self.on_status:
            try:
                self.on_status(
                    "connected",
                    "Hang on please while i look into that for you...",
                )
                briefing_status_sent = True
            except Exception as e:
                log.debug("status.emit_failed", name=name, error=str(e))

        result: dict[str, Any] = {"ok": False, "error": "Unknown error"}
        try:
            result = await REGISTRY.call(name, args)
        finally:
            dispatch_time = asyncio.get_event_loop().time() - dispatch_start
            if briefing_status_sent and self.on_status:
                try:
                    self.on_status("connected", "J.A.R.V.I.S. SYSTEM ONLINE")
                except Exception as e:
                    log.debug("status.restore_failed", name=name, error=str(e))

        log.info(
            "⏱️ TOOL_CALL_DURATION",
            name=name, kind=REGISTRY.kind_of(name) or "?",
            seconds=f"{dispatch_time:.2f}",
        )

        if result.get("ok"):
            output = self._stringify_tool_output(result.get("result"))
            log.info("✅ TOOL_CALL_SUCCESS", name=name, output_preview=output[:300])
        else:
            error_msg = result.get("error", "Unknown error")
            output = f"Error: {error_msg}"
            log.error("X TOOL_CALL_FAILED", name=name, error=error_msg)

        if name == "mail_send" and result.get("ok"):
            draft = _parse_mail_draft_preview(output)
            if draft and self.on_mail_draft:
                try:
                    self.on_mail_draft(draft)
                except Exception as e:
                    log.debug("mail_draft_callback_failed", error=str(e))

        await self.send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": output,
            }
        })

        await self.send_event({"type": "response.create"})

        log.info("tool_result", name=name, result=output[:200])

    async def _extract_and_maybe_store_memory(self, transcript: str) -> None:
        """Extract durable facts from user utterance and optionally store them.

        Runs asynchronously so it doesn't block the voice response.
        High-confidence extractions are stored silently.
        Medium-confidence extractions are queued for confirmation.
        """
        try:
            from ..memory.extractor import extract_memory_candidates
            from ..tools.memory import memory_remember

            candidates = await extract_memory_candidates(transcript, use_llm=False)

            if not candidates:
                return

            high_confidence_threshold = float(os.getenv("MEMORY_EXTRACT_THRESHOLD", "0.85"))
            auto_confirm_threshold = float(os.getenv("MEMORY_AUTO_CONFIRM_THRESHOLD", "0.92"))

            for candidate in candidates:
                if candidate.confidence >= auto_confirm_threshold:
                    result = await memory_remember(candidate.content, candidate.category)
                    log.info(
                        "memory.auto_stored",
                        category=candidate.category,
                        content_preview=candidate.content[:50],
                        confidence=candidate.confidence,
                    )
                elif candidate.confidence >= high_confidence_threshold:
                    log.info(
                        "memory.candidate_queued",
                        category=candidate.category,
                        content_preview=candidate.content[:50],
                        confidence=candidate.confidence,
                        source=candidate.source,
                    )


        except Exception as e:
            log.debug("memory.extraction_failed", error=str(e), transcript_preview=transcript[:50])

    def _ws_alive(self) -> bool:
        return bool(self.ws) and self.ws.close_code is None

    async def _ensure_connected(self) -> bool:
        """Reconnect to the Realtime API if the socket died.

        Thread-safe via a lock so simultaneous audio chunks only trigger one
        reconnect. Returns True if the socket is usable afterwards.
        """
        if self._intentional_close:
            return False
        if self._ws_alive():
            return True

        if self._reconnect_lock is None:
            self._reconnect_lock = asyncio.Lock()

        async with self._reconnect_lock:
            if self._ws_alive():
                return True

            if self._pump_task and not self._pump_task.done():
                self._pump_task.cancel()
                try:
                    await self._pump_task
                except Exception:
                    pass
            self._pump_task = None
            self.ws = None

            backoff = 1.0
            for attempt in range(1, 4):
                try:
                    log.warning(f"🔄 realtime.reconnecting attempt={attempt}")
                    await self.connect()
                    await self.configure()
                    log.info(f"✅ realtime.reconnected attempt={attempt}")
                    return True
                except Exception as e:
                    log.error(f"X realtime.reconnect_failed attempt={attempt} error={e}")
                    self.ws = None
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)

            log.error("💥 realtime.reconnect_exhausted")
            return False

    async def send_event(self, event: dict[str, Any]) -> None:
        """Send an event to OpenAI, reconnecting transparently if needed."""
        if not self._ws_alive() and not await self._ensure_connected():
            log.error("X send_event dropped: no socket after reconnect attempts")
            return
        try:
            await self.ws.send(json.dumps(event))
        except Exception as e:
            log.error(f"X send_event failed: {e}")
            if await self._ensure_connected():
                try:
                    await self.ws.send(json.dumps(event))
                except Exception as e2:
                    log.error(f"X send_event retry failed: {e2}")

    async def send_user_text(self, text: str) -> None:
        """Inject a user text turn into the Realtime conversation."""
        cleaned = (text or "").strip()
        if not cleaned:
            return

        await self.send_event({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": cleaned,
                    }
                ],
            },
        })
        await self.send_event({"type": "response.create"})
    
    async def append_audio(self, pcm16_bytes: bytes) -> None:
        """Send audio data to OpenAI."""

        if not hasattr(self, '_audio_buffer_size'):
            self._audio_buffer_size = 0
            self._audio_chunks = 0
        self._audio_buffer_size += len(pcm16_bytes)
        self._audio_chunks += 1
        
        if self._audio_chunks <= 3 or self._audio_chunks % 20 == 0:
            log.info(f"📤 append_audio: chunk #{self._audio_chunks}, {len(pcm16_bytes)} bytes, ws={'OK' if self.ws else 'NONE'}")
        
        if not self._ws_alive():
            if self._audio_chunks <= 3 or self._audio_chunks % 20 == 0:
                log.warning(
                    f"⚠️ append_audio: socket closed (code="
                    f"{self.ws.close_code if self.ws else 'None'}), reconnecting…"
                )
            if not await self._ensure_connected():
                log.error(f"X Cannot append audio chunk #{self._audio_chunks} - reconnect failed")
                return

        try:
            audio_b64 = base64.b64encode(pcm16_bytes).decode("ascii")
            if self._audio_chunks <= 3:
                log.info(f"🎵 Sending audio chunk #{self._audio_chunks}: {len(pcm16_bytes)} bytes -> {len(audio_b64)} chars")
                log.info(f"🔌 WebSocket state: open={self.ws.state.name if hasattr(self.ws, 'state') else 'unknown'}, close_code={self.ws.close_code}")
            
            message = json.dumps({
                "type": "input_audio_buffer.append",
                "audio": audio_b64,
            })
            
            await self.ws.send(message)
            
            if self._audio_chunks <= 3:
                log.info(f"✅ Audio chunk #{self._audio_chunks} sent successfully ({len(message)} chars)")
        except Exception as e:
            log.error(f"X Failed to send audio chunk #{self._audio_chunks}: {e}")
    
    async def commit_audio(self) -> None:
        """Commit audio buffer."""
        buffer_size = getattr(self, '_audio_buffer_size', 0)
        chunk_count = getattr(self, '_audio_chunks', 0)
        
        log.info(f"🎯 [COMMIT] Committing audio: {chunk_count} chunks, {buffer_size} bytes")
        log.info(f"🔌 [COMMIT] WebSocket state: open={self.ws.state.name if self.ws and hasattr(self.ws, 'state') else 'unknown'}, close_code={self.ws.close_code if self.ws else 'N/A'}")
        
        if not self._ws_alive():
            log.warning("⚠️ [COMMIT] Socket closed - reconnecting before commit")
            if not await self._ensure_connected():
                log.error("X [COMMIT] Cannot commit - reconnect failed")
                return

        if buffer_size == 0:
            log.warning("⚠️ [COMMIT] No audio to commit! Skipping response creation.")
            return

        if self._response_active:
            log.warning("⚠️ [COMMIT] prior response still active - cancelling")
            await self.send_event({"type": "response.cancel"})
            await asyncio.sleep(0.2)
            self._response_active = False

        log.info("🎯 [COMMIT] Sending commit event...")
        if self._commit_ack_event is not None:
            self._commit_ack_event.clear()
        await self.send_event({"type": "input_audio_buffer.commit"})

        if self._commit_ack_event is not None:
            try:
                await asyncio.wait_for(self._commit_ack_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                log.warning("⏱️ [COMMIT] commit ack not seen within 1.0s (continuing)")

        log.info("🎯 [COMMIT] Creating response…")
        self._last_response_create_at = asyncio.get_event_loop().time()
        await self.send_event({"type": "response.create"})

        self._audio_buffer_size = 0
        self._audio_chunks = 0
        log.info("🎯 [COMMIT] Audio counters reset")
    
    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Async iterator over incoming events."""
        while not (self._closed.is_set() and self._recv_queue.empty()):
            try:
                evt = await asyncio.wait_for(self._recv_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                if self._closed.is_set():
                    return
                continue
            yield evt
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            await self.ws.close()
        log.info("realtime.closed")

    async def close(self) -> None:
        """Close the realtime session gracefully."""
        self._intentional_close = True
        self._closed.set()

        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.debug("realtime.close.pump_error", error=str(e))

        self._pump_task = None

        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                log.debug("realtime.close.ws_error", error=str(e))
            finally:
                self.ws = None

        log.info("realtime.closed")
