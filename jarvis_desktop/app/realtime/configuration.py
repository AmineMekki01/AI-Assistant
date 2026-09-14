"""Build the OpenAI Realtime ``session.update`` payload."""
from __future__ import annotations

from typing import Any, Callable


INPUT_SAMPLE_RATE = 24000
OUTPUT_SAMPLE_RATE = 24000


class RealtimeSessionConfiguration:
    """Compose a Realtime configuration from settings and prompt providers."""

    def __init__(
        self,
        *,
        settings_provider: Callable[[], Any],
        persona_provider: Callable[[], str],
        transcription_prompt_provider: Callable[[str], str],
    ) -> None:
        self._settings_provider = settings_provider
        self._persona_provider = persona_provider
        self._transcription_prompt_provider = transcription_prompt_provider

    def build(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        settings = self._settings_provider()
        personal = settings.personal_info
        transcription_prompt = self._transcription_prompt_provider(personal.get("name") or "")
        transcription: dict[str, Any] = {"model": "whisper-1", "language": "en"}
        if transcription_prompt:
            transcription["prompt"] = transcription_prompt

        return {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": settings.openai_realtime_model,
                "instructions": self._persona_provider(),
                "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": INPUT_SAMPLE_RATE},
                        "transcription": transcription,
                        "turn_detection": None,
                    },
                    "output": {
                        "format": {"type": "audio/pcm", "rate": OUTPUT_SAMPLE_RATE},
                        "voice": settings.openai_realtime_voice,
                        "speed": 1,
                    },
                },
                "tools": tools,
                "tool_choice": "auto",
                # Voice replies are intentionally short. This leaves room for
                # the conversation and tool schemas instead of reserving a
                # large completion budget on every live turn.
                "max_output_tokens": 1024,
                "truncation": {
                    "type": "retention_ratio",
                    "retention_ratio": 0.8,
                    "token_limits": {"post_instructions": 12000},
                },
            },
        }
