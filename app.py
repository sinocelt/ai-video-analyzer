from __future__ import annotations

import json
import os
from typing import Optional

import streamlit as st
from dotenv import load_dotenv

from video_analyzer.config import Settings, ensure_data_dirs, load_settings
from video_analyzer.generation import GenerationError, generate_marketing_assets
from video_analyzer.media import (
    MediaError,
    create_job_dir,
    download_video_from_url,
    ensure_ffmpeg_installed,
    extract_audio_from_video,
    save_uploaded_video,
)
from video_analyzer.storage import (
    build_analysis_record,
    build_markdown_export,
    save_analysis_record,
)
from video_analyzer.transcription import TranscriptionError, transcribe_audio

load_dotenv()
settings: Settings = load_settings()
ensure_data_dirs(settings)

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large", "turbo"]
LLM_PROVIDER_OPTIONS = [
    ("auto", "Auto (Gemini -> Groq fallback)"),
    ("gemini", "Gemini only"),
    ("groq", "Groq only"),
]
LLM_PROVIDER_LABELS = {key: label for key, label in LLM_PROVIDER_OPTIONS}


def _default_index(options: list[str], desired: str, fallback: int = 0) -> int:
    if desired in options:
        return options.index(desired)
    return fallback


def _validate_provider_inputs(
    *,
    llm_provider: str,
    gemini_api_key: str,
    gemini_model: str,
    groq_api_key: str,
    groq_model: str,
) -> Optional[str]:
    provider = llm_provider.strip().lower()
    if provider == "gemini":
        if not gemini_api_key.strip():
            return "Gemini API key is required for Gemini mode."
        if not gemini_model.strip():
            return "Gemini model is required for Gemini mode."
        return None

    if provider == "groq":
        if not groq_api_key.strip():
            return "Groq API key is required for Groq mode."
        if not groq_model.strip():
            return "Groq model is required for Groq mode."
        return None

    # auto mode
    if not gemini_api_key.strip() and not groq_api_key.strip():
        return "Auto mode requires at least one API key (Gemini or Groq)."
    if gemini_api_key.strip() and not gemini_model.strip():
        return "Gemini model is required when Gemini API key is set."
    if groq_api_key.strip() and not groq_model.strip():
        return "Groq model is required when Groq API key is set."
    return None


def _clip_transcript(transcript_text: str, max_chars: int) -> tuple[str, bool]:
    if len(transcript_text) <= max_chars:
        return transcript_text, False
    return transcript_text[:max_chars], True


def _initialize_session_state() -> None:
    st.session_state.setdefault("analysis_record", None)
    st.session_state.setdefault("assets", None)
    st.session_state.setdefault("transcript_text", "")
    st.session_state.setdefault("source_label", "")
    st.session_state.setdefault("last_saved_path", "")


def _render_outputs() -> None:
    assets = st.session_state.get("assets")
    transcript_text = st.session_state.get("transcript_text", "")
    source_label = st.session_state.get("source_label", "")
    last_saved_path = st.session_state.get("last_saved_path", "")
    analysis_record = st.session_state.get("analysis_record")

    if not assets:
        return

    st.success("Analysis complete.")
    if last_saved_path:
        st.caption(f"Saved to: {last_saved_path}")
    if analysis_record:
        metadata = analysis_record.get("metadata") or {}
        llm_provider_used = metadata.get("llm_provider_used")
        if llm_provider_used:
            st.caption(f"LLM provider used: {str(llm_provider_used).upper()}")

    st.subheader("3 SEO-Optimized Titles")
    for index, title in enumerate(assets["titles"], start=1):
        st.markdown(f"{index}. {title}")
    st.code("\n".join(assets["titles"]), language="text")

    st.subheader("Engaging Description")
    st.write(assets["description"])
    st.code(assets["description"], language="text")

    st.subheader("Relevant Hashtags")
    hashtags_line = " ".join(assets["hashtags"])
    st.write(hashtags_line)
    st.code(hashtags_line, language="text")

    st.subheader("Thumbnail Prompt")
    st.write(assets["thumbnail_prompt"])
    st.code(assets["thumbnail_prompt"], language="text")

    with st.expander("Transcript"):
        st.text_area(
            "Transcript text",
            transcript_text,
            height=280,
            disabled=True,
            label_visibility="collapsed",
        )

    if analysis_record:
        json_payload = json.dumps(analysis_record, indent=2, ensure_ascii=False)
        markdown_payload = build_markdown_export(
            source_label=source_label,
            transcript_text=transcript_text,
            assets=assets,
        )

        col_a, col_b = st.columns(2)
        with col_a:
            st.download_button(
                "Download JSON",
                data=json_payload,
                file_name="video-analysis.json",
                mime="application/json",
            )
        with col_b:
            st.download_button(
                "Download Markdown",
                data=markdown_payload,
                file_name="marketing-assets.md",
                mime="text/markdown",
            )


def _run_full_analysis(
    *,
    input_mode: str,
    uploaded_file,
    video_url: str,
    whisper_model: str,
    language_code: Optional[str],
    llm_provider: str,
    gemini_api_key: str,
    gemini_model: str,
    groq_api_key: str,
    groq_model: str,
    temperature: float,
) -> None:
    ensure_ffmpeg_installed()
    job_dir = create_job_dir(settings.data_dir)

    with st.status("Running pipeline...", expanded=True) as status:
        if input_mode == "Upload Video":
            status.write("Saving uploaded file...")
            source_path = save_uploaded_video(uploaded_file, job_dir)
            source_label = uploaded_file.name
        else:
            status.write("Downloading video/audio from link...")
            source_path = download_video_from_url(video_url, job_dir)
            source_label = video_url

        status.write("Extracting audio with ffmpeg...")
        audio_path = extract_audio_from_video(source_path, job_dir)

        status.write(f"Transcribing with Whisper ({whisper_model})...")
        transcript_result = transcribe_audio(
            audio_path=audio_path,
            model_name=whisper_model,
            language=language_code,
        )
        transcript_text = transcript_result["text"]
        clipped_transcript, was_clipped = _clip_transcript(
            transcript_text=transcript_text,
            max_chars=settings.max_transcript_chars,
        )

        if was_clipped:
            status.write(
                "Transcript is large, so generation uses a clipped version to stay reliable."
            )

        provider_label = LLM_PROVIDER_LABELS.get(llm_provider, llm_provider)
        status.write(f"Generating assets with {provider_label}...")
        assets, provider_used = generate_marketing_assets(
            transcript_text=clipped_transcript,
            llm_provider=llm_provider,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            groq_api_key=groq_api_key,
            groq_model=groq_model,
            temperature=temperature,
        )
        if llm_provider == "auto" and provider_used == "groq":
            status.write("Gemini was unavailable, so auto mode used Groq fallback.")

        record = build_analysis_record(
            source_label=source_label,
            input_mode=input_mode,
            transcript=transcript_result,
            assets=assets,
            metadata={
                "whisper_model": whisper_model,
                "llm_provider_mode": llm_provider,
                "llm_provider_used": provider_used,
                "gemini_model": gemini_model,
                "groq_model": groq_model,
                "transcript_clipped_for_generation": was_clipped,
                "clip_limit_chars": settings.max_transcript_chars,
            },
        )
        saved_path = save_analysis_record(settings.data_dir, record)

        st.session_state["analysis_record"] = record
        st.session_state["assets"] = assets
        st.session_state["transcript_text"] = transcript_text
        st.session_state["source_label"] = source_label
        st.session_state["last_saved_path"] = str(saved_path)

        status.update(label="Finished", state="complete")

    if was_clipped:
        st.info(
            "Transcript was clipped before LLM generation. "
            "You still have the full transcript saved in the JSON result."
        )


def _regenerate_only(
    *,
    llm_provider: str,
    gemini_api_key: str,
    gemini_model: str,
    groq_api_key: str,
    groq_model: str,
    temperature: float,
) -> None:
    transcript_text = st.session_state.get("transcript_text", "").strip()
    source_label = st.session_state.get("source_label", "unknown")
    if not transcript_text:
        st.warning("No transcript is loaded yet. Run analysis first.")
        return

    clipped_transcript, was_clipped = _clip_transcript(
        transcript_text=transcript_text,
        max_chars=settings.max_transcript_chars,
    )

    with st.status("Regenerating assets...", expanded=True) as status:
        provider_label = LLM_PROVIDER_LABELS.get(llm_provider, llm_provider)
        status.write(f"Generating assets with {provider_label}...")
        assets, provider_used = generate_marketing_assets(
            transcript_text=clipped_transcript,
            llm_provider=llm_provider,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            groq_api_key=groq_api_key,
            groq_model=groq_model,
            temperature=temperature,
        )
        if llm_provider == "auto" and provider_used == "groq":
            status.write("Gemini was unavailable, so auto mode used Groq fallback.")

        record = build_analysis_record(
            source_label=source_label,
            input_mode="Regenerate",
            transcript={
                "text": transcript_text,
                "language": None,
                "segments": [],
            },
            assets=assets,
            metadata={
                "llm_provider_mode": llm_provider,
                "llm_provider_used": provider_used,
                "gemini_model": gemini_model,
                "groq_model": groq_model,
                "transcript_clipped_for_generation": was_clipped,
                "clip_limit_chars": settings.max_transcript_chars,
            },
        )
        saved_path = save_analysis_record(settings.data_dir, record)

        st.session_state["analysis_record"] = record
        st.session_state["assets"] = assets
        st.session_state["last_saved_path"] = str(saved_path)
        status.update(label="Finished", state="complete")

    if was_clipped:
        st.info(
            "Transcript was clipped before LLM generation. "
            "You still have the full transcript saved in the JSON result."
        )


def main() -> None:
    st.set_page_config(page_title="AI Video Analyzer", page_icon="🎬", layout="wide")
    _initialize_session_state()
    st.title("AI Video Analyzer (Self-Hosted MVP)")
    st.caption(
        "Upload a video file or paste a link, then get titles, description, hashtags, "
        "and a thumbnail prompt in one click."
    )

    with st.sidebar:
        st.header("Settings")

        llm_provider_values = [key for key, _ in LLM_PROVIDER_OPTIONS]
        llm_provider = st.selectbox(
            "LLM provider mode",
            options=llm_provider_values,
            index=_default_index(
                options=llm_provider_values,
                desired=settings.default_llm_provider,
                fallback=0,
            ),
            format_func=lambda key: LLM_PROVIDER_LABELS.get(key, key),
            help="Auto mode tries Gemini first, then Groq if Gemini fails.",
        )

        default_key = os.getenv("GEMINI_API_KEY", "")
        gemini_api_key = st.text_input(
            "Gemini API Key",
            value=default_key,
            type="password",
            help="Create a key in Google AI Studio and set it here or in .env.",
        )

        gemini_model = st.text_input(
            "Gemini model",
            value=settings.default_gemini_model,
            help="Example: gemini-2.5-flash",
        )

        default_groq_key = os.getenv("GROQ_API_KEY", "")
        groq_api_key = st.text_input(
            "Groq API Key",
            value=default_groq_key,
            type="password",
            help="Create a key in Groq Console and set it here or in .env.",
        )

        groq_model = st.text_input(
            "Groq model",
            value=settings.default_groq_model,
            help="Example: llama-3.3-70b-versatile",
        )

        whisper_model = st.selectbox(
            "Whisper model",
            options=WHISPER_MODELS,
            index=_default_index(
                options=WHISPER_MODELS,
                desired=settings.default_whisper_model,
                fallback=1,
            ),
        )

        language_code = st.text_input(
            "Transcription language (optional)",
            value="",
            help="Leave blank for auto-detection. Example: en, es, pt.",
        ).strip()

        temperature = st.slider(
            "Creativity",
            min_value=0.0,
            max_value=1.0,
            value=0.4,
            step=0.05,
        )

        st.caption(
            "Tip: use Auto mode to reduce downtime when Gemini has temporary 503 spikes."
        )
        st.caption("Tip: `base` is a good speed/quality Whisper default on CPU.")

    st.markdown("### Input")
    input_mode = st.radio("Choose input type", ["Upload Video", "Video URL"], horizontal=True)

    uploaded_file = None
    video_url = ""
    if input_mode == "Upload Video":
        uploaded_file = st.file_uploader(
            "Upload a video",
            type=["mp4", "mov", "mkv", "avi", "webm", "m4v"],
        )
    else:
        video_url = st.text_input(
            "Paste a video URL",
            placeholder="https://www.youtube.com/watch?v=...",
        ).strip()
        st.caption("Use only links you have rights to process.")

    col1, col2 = st.columns([1, 1])
    with col1:
        analyze_clicked = st.button("Analyze Video", type="primary", use_container_width=True)
    with col2:
        regenerate_clicked = st.button(
            "Regenerate Assets",
            use_container_width=True,
            disabled=not bool(st.session_state.get("transcript_text", "").strip()),
        )

    if analyze_clicked:
        provider_error = _validate_provider_inputs(
            llm_provider=llm_provider,
            gemini_api_key=gemini_api_key.strip(),
            gemini_model=gemini_model.strip(),
            groq_api_key=groq_api_key.strip(),
            groq_model=groq_model.strip(),
        )
        if provider_error:
            st.error(provider_error)
        elif input_mode == "Upload Video" and uploaded_file is None:
            st.error("Please upload a video file.")
        elif input_mode == "Video URL" and not video_url:
            st.error("Please paste a video URL.")
        else:
            try:
                _run_full_analysis(
                    input_mode=input_mode,
                    uploaded_file=uploaded_file,
                    video_url=video_url,
                    whisper_model=whisper_model,
                    language_code=language_code or None,
                    llm_provider=llm_provider,
                    gemini_api_key=gemini_api_key.strip(),
                    gemini_model=gemini_model.strip(),
                    groq_api_key=groq_api_key.strip(),
                    groq_model=groq_model.strip(),
                    temperature=temperature,
                )
            except (MediaError, TranscriptionError, GenerationError) as exc:
                st.error(str(exc))
            except Exception as exc:  # pragma: no cover - defensive fallback
                st.error(f"Unexpected error: {exc}")

    if regenerate_clicked:
        provider_error = _validate_provider_inputs(
            llm_provider=llm_provider,
            gemini_api_key=gemini_api_key.strip(),
            gemini_model=gemini_model.strip(),
            groq_api_key=groq_api_key.strip(),
            groq_model=groq_model.strip(),
        )
        if provider_error:
            st.error(provider_error)
        else:
            try:
                _regenerate_only(
                    llm_provider=llm_provider,
                    gemini_api_key=gemini_api_key.strip(),
                    gemini_model=gemini_model.strip(),
                    groq_api_key=groq_api_key.strip(),
                    groq_model=groq_model.strip(),
                    temperature=temperature,
                )
            except GenerationError as exc:
                st.error(str(exc))
            except Exception as exc:  # pragma: no cover - defensive fallback
                st.error(f"Unexpected error: {exc}")

    _render_outputs()


if __name__ == "__main__":
    main()
