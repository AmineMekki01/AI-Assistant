"""Speaker verification enrollment handlers."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from aiohttp import web

from ...core.config import get_settings
from ...core.speaker_verification import SpeakerProfile, SpeakerVerifier


async def handle_speaker_profile_status(request):
    """Return the current speaker profile status."""
    try:
        settings = get_settings()
        verifier = SpeakerVerifier()
        summary = verifier.profile_summary()
        summary.update(
            {
                "verificationEnabled": settings.speaker_verification_enabled,
                "profilePath": str(verifier.profile_path),
            }
        )
        return web.json_response(summary)
    except Exception as e:
        print(f"X [BACKEND] Speaker profile status error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_speaker_profile_enroll(request):
    """Enroll or replace the speaker profile from uploaded audio files."""
    verifier = SpeakerVerifier()
    temp_dir = tempfile.mkdtemp(prefix="jarvis_speaker_enroll_")
    temp_paths: list[str] = []

    try:
        threshold = verifier.threshold
        profile_path = verifier.profile_path

        audio_paths: list[str] = []
        content_type = (request.content_type or "").lower()

        if content_type.startswith("multipart/"):
            reader = await request.multipart()
            while True:
                field = await reader.next()
                if field is None:
                    break

                if field.name in {"threshold", "profilePath"}:
                    value = (await field.text()).strip()
                    if field.name == "threshold" and value:
                        try:
                            threshold = float(value)
                        except Exception:
                            raise ValueError("Invalid threshold value")
                    elif field.name == "profilePath" and value:
                        profile_path = Path(value).expanduser()
                    continue

                filename = getattr(field, "filename", None)
                if not filename:
                    continue

                suffix = Path(filename).suffix or ".wav"
                safe_name = Path(filename).name.replace(os.sep, "_")
                temp_path = Path(temp_dir) / f"{len(temp_paths):02d}_{safe_name}"
                if temp_path.suffix != suffix:
                    temp_path = temp_path.with_suffix(suffix)

                with open(temp_path, "wb") as handle:
                    while True:
                        chunk = await field.read_chunk()
                        if not chunk:
                            break
                        handle.write(chunk)

                temp_paths.append(str(temp_path))
                audio_paths.append(str(temp_path))
        else:
            try:
                payload = await request.json()
            except Exception:
                payload = {}

            raw_audio_paths = payload.get("audioPaths") or payload.get("audio_paths") or []
            if isinstance(raw_audio_paths, str):
                raw_audio_paths = [raw_audio_paths]
            audio_paths = [str(Path(path).expanduser()) for path in raw_audio_paths if str(path).strip()]

            if payload.get("threshold") is not None:
                try:
                    threshold = float(payload["threshold"])
                except Exception:
                    raise ValueError("Invalid threshold value")
            if payload.get("profilePath"):
                profile_path = Path(str(payload["profilePath"])).expanduser()

        if not audio_paths:
            return web.json_response({"success": False, "error": "No enrollment audio received"}, status=400)

        profile: SpeakerProfile = SpeakerVerifier.enroll_from_audio_paths(
            audio_paths,
            profile_path=profile_path,
            threshold=threshold,
        )

        return web.json_response(
            {
                "success": True,
                "profile": {
                    "profilePath": str(profile_path),
                    "embeddingCount": len(profile.embeddings),
                    "threshold": profile.threshold,
                    "modelName": profile.model_name,
                    "createdAt": profile.created_at,
                    "verificationEnabled": get_settings().speaker_verification_enabled,
                    "profileExists": True,
                },
            }
        )
    except Exception as e:
        print(f"X [BACKEND] Speaker profile enrollment error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def handle_speaker_profile_clear(request):
    """Delete the persisted speaker profile."""
    try:
        verifier = SpeakerVerifier()
        removed = verifier.clear_profile()
        return web.json_response(
            {
                "success": True,
                "removed": removed,
                "profilePath": str(verifier.profile_path),
            }
        )
    except Exception as e:
        print(f"X [BACKEND] Speaker profile clear error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)
