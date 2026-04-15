from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    default_whisper_model: str
    default_llm_provider: str
    default_gemini_model: str
    default_groq_model: str
    max_transcript_chars: int


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.getenv("DATA_DIR", "data")).resolve(),
        default_whisper_model=os.getenv("WHISPER_MODEL", "base"),
        default_llm_provider=os.getenv("LLM_PROVIDER", "auto"),
        default_gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        default_groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        max_transcript_chars=int(os.getenv("MAX_TRANSCRIPT_CHARS", "120000")),
    )


def ensure_data_dirs(settings: Settings) -> None:
    for path in (
        settings.data_dir,
        settings.data_dir / "jobs",
        settings.data_dir / "results",
    ):
        path.mkdir(parents=True, exist_ok=True)
