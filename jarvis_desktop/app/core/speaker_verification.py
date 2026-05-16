from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np


@dataclass
class SpeakerVerificationResult:
    active: bool
    allowed: bool
    similarity: float | None = None
    threshold: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class SpeakerProfile:
    embeddings: list[list[float]]
    threshold: float
    model_name: str = ""
    created_at: str = ""


class SpeakerVerifier:
    _profile_cache_lock = threading.RLock()
    _profile_cache: dict[str, dict[str, object]] = {}

    def __init__(self, profile_path: str | Path | None = None, threshold: float = 0.35, model_name: str = ""):
        if profile_path is None or not str(profile_path).strip():
            try:
                from app.core.config import get_settings

                settings = get_settings()
                profile_path = settings.speaker_profile_path
                threshold = settings.speaker_verification_threshold
                model_name = model_name or settings.speaker_verification_model_name
            except Exception:
                profile_path = os.getenv("JARVIS_SPEAKER_PROFILE_PATH", "~/.jarvis/voice/speaker_profile.json")

        self.profile_path = Path(profile_path).expanduser()
        self.threshold = threshold
        self.model_name = model_name
        self._classifier = None
        self._reference_embedding = None
        self._profile_threshold = threshold
        self._reference_signature = None
        self._load_error = ""

    @property
    def enabled(self) -> bool:
        return bool(self.profile_path)

    @classmethod
    def from_environment(cls) -> SpeakerVerifier | None:
        try:
            from app.core.config import get_settings

            settings = get_settings()
            if not settings.speaker_verification_enabled:
                return None
            return cls(
                settings.speaker_profile_path,
                settings.speaker_verification_threshold,
                settings.speaker_verification_model_name,
            )
        except Exception:
            enabled_raw = os.getenv("JARVIS_SPEAKER_VERIFICATION_ENABLED", "").strip().lower()
            if enabled_raw in {"", "0", "false", "no", "off"}:
                return None

            threshold_raw = os.getenv("JARVIS_SPEAKER_VERIFICATION_THRESHOLD", "0.35")
            profile_path = os.getenv("JARVIS_SPEAKER_PROFILE_PATH", "~/.jarvis/voice/speaker_profile.json")
            model_name = os.getenv("JARVIS_SPEAKER_VERIFICATION_MODEL_NAME", "speechbrain/spkrec-ecapa-voxceleb")
            try:
                threshold = float(threshold_raw)
            except Exception:
                threshold = 0.35
            return cls(profile_path, threshold, model_name)

    def _load_classifier(self):
        if self._classifier is not None:
            return self._classifier

        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except Exception as exc:
            self._load_error = f"speechbrain import failed: {exc}"
            return None

        try:
            source = self.model_name or "speechbrain/spkrec-ecapa-voxceleb"
            self._classifier = EncoderClassifier.from_hparams(source=source)
        except Exception as exc:
            self._load_error = f"speechbrain model failed: {exc}"
            return None

        return self._classifier

    @staticmethod
    def _profile_signature(path: Path) -> tuple[int, int] | None:
        if not path.exists():
            return None
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    @classmethod
    def _cache_key(cls, profile_path: str | Path) -> str:
        return str(Path(profile_path).expanduser())

    @classmethod
    def _get_cached_profile(cls, profile_path: str | Path) -> dict[str, object] | None:
        key = cls._cache_key(profile_path)
        path = Path(key)
        signature = cls._profile_signature(path)
        if signature is None:
            return None

        with cls._profile_cache_lock:
            cached = cls._profile_cache.get(key)
            if not cached or cached.get("signature") != signature:
                return None
            return cached

    @classmethod
    def _store_cached_profile(
        cls,
        profile_path: str | Path,
        *,
        payload: dict | None = None,
        reference_embedding: np.ndarray | None = None,
    ) -> None:
        key = cls._cache_key(profile_path)
        path = Path(key)
        signature = cls._profile_signature(path)
        if signature is None:
            return

        entry: dict[str, object] = {"signature": signature}
        if payload is not None:
            entry["payload"] = payload
        if reference_embedding is not None:
            entry["reference_embedding"] = reference_embedding.astype(np.float32)

        with cls._profile_cache_lock:
            cls._profile_cache[key] = entry

    @classmethod
    def invalidate_cached_profile(cls, profile_path: str | Path | None = None) -> None:
        with cls._profile_cache_lock:
            if profile_path is None:
                cls._profile_cache.clear()
                return
            cls._profile_cache.pop(cls._cache_key(profile_path), None)

    def preload(self) -> bool:
        """Warm the verifier model and speaker profile into memory if available."""
        if not self.profile_path.exists():
            return False

        classifier = self._load_classifier()
        reference_embedding = self._load_reference_embedding()
        return classifier is not None and reference_embedding is not None

    def _load_profile_payload(self) -> dict | None:
        signature = self._profile_signature(self.profile_path)
        if signature is None:
            self._load_error = f"speaker profile not found at {self.profile_path}"
            return None

        if self._reference_signature != signature:
            self._reference_embedding = None

        cached = self._get_cached_profile(self.profile_path)
        if cached is not None:
            payload = cached.get("payload")
            if isinstance(payload, dict):
                self._profile_threshold = float(payload.get("threshold", self.threshold))
                self._reference_signature = signature
                return payload

        try:
            payload = json.loads(self.profile_path.read_text())
        except Exception as exc:
            self._load_error = f"failed to read speaker profile: {exc}"
            return None

        if not isinstance(payload, dict):
            self._load_error = "speaker profile must be a JSON object"
            return None

        embeddings = payload.get("embeddings")
        if embeddings is None and "embedding" in payload:
            embeddings = [payload.get("embedding")]

        if not embeddings:
            self._load_error = "speaker profile does not contain embeddings"
            return None

        try:
            self._profile_threshold = float(payload.get("threshold", self.threshold))
        except Exception:
            self._profile_threshold = self.threshold

        self._reference_signature = signature
        self._store_cached_profile(self.profile_path, payload=payload)

        return payload

    def _load_reference_embedding(self):
        signature = self._profile_signature(self.profile_path)
        if signature is None:
            self._reference_embedding = None
            self._reference_signature = None
            return None

        if self._reference_signature != signature:
            self._reference_embedding = None

        if self._reference_embedding is not None and self._reference_signature == signature:
            return self._reference_embedding

        cached = self._get_cached_profile(self.profile_path)
        if cached is not None:
            cached_embedding = cached.get("reference_embedding")
            if isinstance(cached_embedding, np.ndarray):
                self._reference_embedding = cached_embedding.astype(np.float32)
                self._reference_signature = signature
                return self._reference_embedding

        payload = self._load_profile_payload()
        if payload is None:
            return None

        embeddings = payload.get("embeddings") or []
        vectors: list[np.ndarray] = []
        expected_size: int | None = None
        for embedding in embeddings:
            vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
            if vector.size == 0:
                continue
            if expected_size is None:
                expected_size = int(vector.size)
            elif vector.size != expected_size:
                self._load_error = "speaker profile embeddings must all have the same size"
                return None

            norm = float(np.linalg.norm(vector))
            if norm > 0:
                vector = vector / norm
            vectors.append(vector)

        if not vectors:
            self._load_error = "speaker profile has no valid embeddings"
            return None

        reference_embedding = np.mean(np.stack(vectors, axis=0), axis=0)
        norm = float(np.linalg.norm(reference_embedding))
        if norm > 0:
            reference_embedding = reference_embedding / norm

        self._reference_embedding = reference_embedding.astype(np.float32)
        self._reference_signature = signature
        self._store_cached_profile(
            self.profile_path,
            payload=payload,
            reference_embedding=self._reference_embedding,
        )
        return self._reference_embedding

    def _write_profile(self, profile: SpeakerProfile) -> Path:
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "model_name": profile.model_name,
                    "threshold": profile.threshold,
                    "created_at": profile.created_at,
                    "embeddings": profile.embeddings,
                },
                indent=2,
                sort_keys=True,
            )
        )
        self.invalidate_cached_profile(self.profile_path)
        return self.profile_path

    def profile_summary(self) -> dict:
        """Return a lightweight description of the current speaker profile."""
        summary = {
            "verificationEnabled": True,
            "profileExists": self.profile_path.exists(),
            "profilePath": str(self.profile_path),
            "threshold": self.threshold,
            "modelName": self.model_name or "speechbrain/spkrec-ecapa-voxceleb",
            "embeddingCount": 0,
            "createdAt": None,
            "loadError": None,
        }

        if not summary["profileExists"]:
            summary["loadError"] = f"speaker profile not found at {self.profile_path}"
            return summary

        payload = self._load_profile_payload()
        if payload is None:
            summary["loadError"] = self._load_error or "speaker profile unavailable"
            return summary

        embeddings = payload.get("embeddings") or []
        summary.update(
            {
                "embeddingCount": len(embeddings),
                "threshold": float(payload.get("threshold", self.threshold)),
                "modelName": payload.get("model_name", summary["modelName"]),
                "createdAt": payload.get("created_at"),
                "loadError": None,
            }
        )
        return summary

    def clear_profile(self) -> bool:
        """Remove the persisted speaker profile if it exists."""
        removed = False
        if self.profile_path.exists():
            self.profile_path.unlink()
            removed = True

        self.invalidate_cached_profile(self.profile_path)

        self._reference_embedding = None
        self._reference_signature = None
        self._load_error = ""
        return removed

    @classmethod
    def enroll_from_audio_paths(
        cls,
        audio_paths: Sequence[str],
        profile_path: str | Path | None = None,
        threshold: float = 0.35,
    ) -> SpeakerProfile:
        verifier = cls(profile_path=profile_path, threshold=threshold)
        classifier = verifier._load_classifier()
        if classifier is None:
            raise RuntimeError(verifier._load_error or "speaker embedding model unavailable")

        try:
            import torch
            import torchaudio
        except Exception as exc:
            raise RuntimeError(f"speaker enrollment dependencies unavailable: {exc}") from exc

        embeddings: list[list[float]] = []
        for audio_path in audio_paths:
            try:
                signal, sample_rate = torchaudio.load(str(audio_path))
                if signal.shape[0] > 1:
                    signal = signal.mean(dim=0, keepdim=True)
                if sample_rate != 16000:
                    signal = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)(signal)
                embedding = classifier.encode_batch(signal).flatten().detach().cpu().numpy().astype(np.float32)
                norm = float(np.linalg.norm(embedding))
                if norm > 0:
                    embedding = embedding / norm
                embeddings.append(embedding.tolist())
            except Exception:
                continue

        if not embeddings:
            raise RuntimeError("no valid enrollment audio could be loaded")

        profile = SpeakerProfile(
            embeddings=embeddings,
            threshold=threshold,
            model_name=verifier.model_name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        verifier._write_profile(profile)
        verifier._reference_embedding = None
        verifier._reference_signature = None
        verifier._load_reference_embedding()
        return profile

    def verify_audio(self, audio_bytes: bytes) -> SpeakerVerificationResult:
        print(f"Verifying audio... profile={self.profile_path}")
        if not self.profile_path.exists():
            return SpeakerVerificationResult(active=True, allowed=False, reason="no_speaker_profile")

        classifier = self._load_classifier()
        if classifier is None:
            return SpeakerVerificationResult(active=True, allowed=False, reason=self._load_error or "classifier_unavailable")

        reference_embedding = self._load_reference_embedding()
        if reference_embedding is None:
            return SpeakerVerificationResult(active=True, allowed=False, reason=self._load_error or "profile_embedding_unavailable")

        if not audio_bytes:
            return SpeakerVerificationResult(active=True, allowed=False, reason="empty_audio")

        samples = np.frombuffer(audio_bytes, dtype=np.int16)
        if samples.size < 8000:
            return SpeakerVerificationResult(active=True, allowed=False, reason="audio_too_short")

        try:
            import torch
        except Exception as exc:
            self._load_error = f"torch unavailable: {exc}"
            return SpeakerVerificationResult(active=True, allowed=False, reason=self._load_error)

        try:
            signal = torch.from_numpy(samples.astype(np.float32) / 32768.0).unsqueeze(0)
            embedding = classifier.encode_batch(signal).flatten().detach().cpu().numpy().astype(np.float32)
            embedding_norm = float(np.linalg.norm(embedding))
            if embedding_norm > 0:
                embedding = embedding / embedding_norm
            similarity = float(np.dot(embedding.reshape(-1), reference_embedding.reshape(-1)))
        except Exception as exc:
            self._load_error = f"verification failed: {exc}"
            return SpeakerVerificationResult(active=True, allowed=False, reason=self._load_error)

        allowed = similarity >= self._profile_threshold
        return SpeakerVerificationResult(
            active=True,
            allowed=allowed,
            similarity=similarity,
            threshold=self._profile_threshold,
            reason="matched" if allowed else "rejected",
        )
