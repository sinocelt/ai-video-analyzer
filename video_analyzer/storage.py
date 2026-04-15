from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def build_analysis_record(
    *,
    source_label: str,
    input_mode: str,
    transcript: Dict[str, Any],
    assets: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_label": source_label,
        "input_mode": input_mode,
        "transcript": transcript,
        "assets": assets,
        "metadata": metadata,
    }


def save_analysis_record(data_dir: Path, record: Dict[str, Any]) -> Path:
    output_path = data_dir / "results" / f"analysis-{_timestamp()}.json"
    output_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path


def build_markdown_export(
    *,
    source_label: str,
    transcript_text: str,
    assets: Dict[str, Any],
) -> str:
    titles_block = "\n".join(
        [f"{index}. {title}" for index, title in enumerate(assets["titles"], start=1)]
    )
    hashtags_line = " ".join(assets["hashtags"])
    return (
        f"# AI Video Analyzer Output\n\n"
        f"## Source\n"
        f"{source_label}\n\n"
        f"## 3 SEO-Optimized Titles\n"
        f"{titles_block}\n\n"
        f"## Engaging Description\n"
        f"{assets['description']}\n\n"
        f"## Relevant Hashtags\n"
        f"{hashtags_line}\n\n"
        f"## Thumbnail Prompt\n"
        f"{assets['thumbnail_prompt']}\n\n"
        f"## Transcript\n"
        f"{transcript_text}\n"
    )

