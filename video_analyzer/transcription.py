from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import whisper


class TranscriptionError(RuntimeError):
    """Raised when transcription fails."""


_MODEL_CACHE: dict[str, Any] = {}


def _get_model(model_name: str):
    if model_name not in _MODEL_CACHE:
        _MODEL_CACHE[model_name] = whisper.load_model(model_name)
    return _MODEL_CACHE[model_name]


def transcribe_audio(
    *,
    audio_path: Path,
    model_name: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        model = _get_model(model_name)
        kwargs: Dict[str, Any] = {"fp16": False, "verbose": False}
        if language:
            kwargs["language"] = language
        result = model.transcribe(str(audio_path), **kwargs)
    except Exception as exc:  # pragma: no cover - runtime/model dependent
        raise TranscriptionError(f"Whisper transcription failed: {exc}") from exc

    text = (result.get("text") or "").strip()
    if not text:
        raise TranscriptionError("Whisper returned an empty transcript.")

    segments = []
    for segment in result.get("segments", []):
        segments.append(
            {
                "start": float(segment.get("start", 0.0)),
                "end": float(segment.get("end", 0.0)),
                "text": (segment.get("text") or "").strip(),
            }
        )

    return {
        "text": text,
        "language": result.get("language"),
        "segments": segments,
    }

