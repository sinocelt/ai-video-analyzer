from __future__ import annotations

import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from yt_dlp import YoutubeDL


class MediaError(RuntimeError):
    """Raised when video/audio intake or conversion fails."""


def create_job_dir(data_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    job_dir = data_dir / "jobs" / f"{timestamp}-{uuid.uuid4().hex[:8]}"
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return cleaned or "source"


def save_uploaded_video(uploaded_file, job_dir: Path) -> Path:
    extension = Path(uploaded_file.name).suffix or ".mp4"
    target_name = f"{sanitize_filename(Path(uploaded_file.name).stem)}{extension}"
    target_path = job_dir / target_name
    target_path.write_bytes(uploaded_file.getbuffer())
    return target_path


def download_video_from_url(url: str, job_dir: Path) -> Path:
    try:
        output_template = str(job_dir / "source.%(ext)s")
        options = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "outtmpl": output_template,
        }
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            candidate_path = Path(ydl.prepare_filename(info))

            requested = info.get("requested_downloads") or []
            if requested:
                possible = requested[0].get("filepath")
                if possible:
                    candidate_path = Path(possible)

        if candidate_path.exists():
            return candidate_path

        matches = sorted(job_dir.glob("source.*"))
        if matches:
            return matches[0]
    except Exception as exc:  # pragma: no cover - runtime/network dependent
        raise MediaError(f"Unable to download video from URL: {exc}") from exc

    raise MediaError("Download finished but no media file was found.")


def ensure_ffmpeg_installed() -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise MediaError("ffmpeg is not installed or not on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise MediaError(f"ffmpeg is not available: {exc.stderr.strip()}") from exc


def extract_audio_from_video(video_path: Path, job_dir: Path) -> Path:
    audio_path = job_dir / "audio.wav"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_path),
    ]
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        detail = process.stderr.strip().splitlines()
        tail = "\n".join(detail[-12:]) if detail else "No ffmpeg details provided."
        raise MediaError(f"Audio extraction failed.\n{tail}")
    if not audio_path.exists():
        raise MediaError("Audio extraction did not produce an output file.")
    return audio_path

