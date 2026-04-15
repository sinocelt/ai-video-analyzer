from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Sequence, Tuple

import requests

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GenerationError(RuntimeError):
    """Raised when generation or output parsing fails."""


def _build_prompt(transcript_text: str) -> str:
    return f"""
You are a video marketing assistant.
Based on the transcript below, produce ONLY valid JSON with this schema:
{{
  "titles": ["title 1", "title 2", "title 3"],
  "description": "concise and engaging description",
  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
  "thumbnail_prompt": "detailed text-to-image prompt for a clickable thumbnail"
}}

Rules:
- Return exactly 3 unique titles.
- Titles should be SEO-friendly and click-worthy, but not clickbait spam.
- Description should be 2-4 sentences.
- Hashtags should be 5-10 relevant tags.
- Start each hashtag with # and avoid spaces.
- Thumbnail prompt should include subject, style, lighting, composition, emotion, and color direction.
- Output JSON only. No markdown. No extra keys.

Transcript:
\"\"\"
{transcript_text}
\"\"\"
""".strip()


def _extract_text_from_gemini_response(payload: Dict[str, Any]) -> str:
    feedback = payload.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise GenerationError(f"Gemini blocked request: {feedback['blockReason']}")

    candidates = payload.get("candidates") or []
    for candidate in candidates:
        parts = (candidate.get("content") or {}).get("parts") or []
        chunks = [part.get("text", "") for part in parts if part.get("text")]
        if chunks:
            return "".join(chunks).strip()
    raise GenerationError("Gemini response did not include text output.")


def _extract_text_from_groq_response(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    for choice in choices:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    raise GenerationError("Groq response did not include message content.")


def _extract_json_block(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if match:
        return match.group(0)
    return stripped


def _normalize_hashtag(tag: str) -> str:
    token = tag.strip().replace("#", "")
    token = token.replace(" ", "")
    token = re.sub(r"[^A-Za-z0-9_]", "", token)
    if not token:
        return ""
    return f"#{token[:64]}"


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _validate_and_normalize_assets(raw: Dict[str, Any]) -> Dict[str, Any]:
    titles = [str(item).strip() for item in raw.get("titles", []) if str(item).strip()]
    titles = _dedupe_keep_order(titles)[:3]
    if len(titles) != 3:
        raise GenerationError("Model did not return exactly 3 valid titles.")

    description = str(raw.get("description", "")).strip()
    if not description:
        raise GenerationError("Model did not return a valid description.")

    hashtags_raw = [str(item) for item in raw.get("hashtags", [])]
    hashtags = [_normalize_hashtag(tag) for tag in hashtags_raw]
    hashtags = [tag for tag in hashtags if tag]
    hashtags = _dedupe_keep_order(hashtags)

    fallback_hashtags = ["#content", "#video", "#marketing", "#creator", "#socialmedia"]
    if len(hashtags) < 5:
        hashtags.extend([tag for tag in fallback_hashtags if tag not in hashtags])
    hashtags = hashtags[:10]
    if len(hashtags) < 5:
        raise GenerationError("Model did not return enough valid hashtags.")

    thumbnail_prompt = str(raw.get("thumbnail_prompt", "")).strip()
    if not thumbnail_prompt:
        raise GenerationError("Model did not return a thumbnail prompt.")

    return {
        "titles": titles,
        "description": description,
        "hashtags": hashtags,
        "thumbnail_prompt": thumbnail_prompt,
    }


def _post_with_retries(
    *,
    endpoint: str,
    provider_name: str,
    payload: Dict[str, Any],
    headers: Dict[str, str] | None = None,
    params: Dict[str, str] | None = None,
    timeout_seconds: int = 120,
    max_retries: int = 2,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                params=params,
                json=payload,
                timeout=timeout_seconds,
            )
        except requests.RequestException as exc:  # pragma: no cover - network dependent
            last_error = exc
            if attempt < max_retries:
                time.sleep(2**attempt)
                continue
            raise GenerationError(f"{provider_name} request failed: {exc}") from exc

        if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
            time.sleep(2**attempt)
            continue
        return response

    if last_error:
        raise GenerationError(f"{provider_name} request failed: {last_error}") from last_error
    raise GenerationError(f"{provider_name} request failed unexpectedly.")


def _response_error_detail(response: requests.Response) -> str:
    try:
        return json.dumps(response.json(), ensure_ascii=False)[:800]
    except Exception:
        return response.text[:800]


def _parse_generated_json(text: str) -> Dict[str, Any]:
    json_text = _extract_json_block(text)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GenerationError("Model returned JSON, but not an object.")
    return parsed


def _generate_with_gemini(
    *,
    transcript_text: str,
    api_key: str,
    model: str,
    temperature: float,
    max_retries: int,
) -> Dict[str, Any]:
    if not api_key.strip():
        raise GenerationError("Gemini API key is required.")
    if not model.strip():
        raise GenerationError("Gemini model is required.")

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": _build_prompt(transcript_text)}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
    }

    response = _post_with_retries(
        endpoint=endpoint,
        provider_name="Gemini",
        payload=payload,
        params={"key": api_key},
        max_retries=max_retries,
    )
    if response.status_code != 200:
        raise GenerationError(
            f"Gemini API error ({response.status_code}). Details: {_response_error_detail(response)}"
        )

    body = response.json()
    generated_text = _extract_text_from_gemini_response(body)
    return _validate_and_normalize_assets(_parse_generated_json(generated_text))


def _generate_with_groq(
    *,
    transcript_text: str,
    api_key: str,
    model: str,
    temperature: float,
    max_retries: int,
) -> Dict[str, Any]:
    if not api_key.strip():
        raise GenerationError("Groq API key is required.")
    if not model.strip():
        raise GenerationError("Groq model is required.")

    endpoint = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": _build_prompt(transcript_text)}],
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    response = _post_with_retries(
        endpoint=endpoint,
        provider_name="Groq",
        payload=payload,
        headers=headers,
        max_retries=max_retries,
    )
    if response.status_code != 200:
        raise GenerationError(
            f"Groq API error ({response.status_code}). Details: {_response_error_detail(response)}"
        )

    body = response.json()
    generated_text = _extract_text_from_groq_response(body)
    return _validate_and_normalize_assets(_parse_generated_json(generated_text))


def _provider_chain(
    *,
    llm_provider: str,
    gemini_api_key: str,
    groq_api_key: str,
) -> Sequence[str]:
    provider = llm_provider.strip().lower()
    if provider not in {"auto", "gemini", "groq"}:
        raise GenerationError("Provider must be one of: auto, gemini, groq.")

    if provider == "gemini":
        return ["gemini"]
    if provider == "groq":
        return ["groq"]

    # auto mode
    chain: list[str] = []
    if gemini_api_key.strip():
        chain.append("gemini")
    if groq_api_key.strip():
        chain.append("groq")
    if not chain:
        raise GenerationError("Auto mode requires at least one API key (Gemini or Groq).")
    return chain


def generate_marketing_assets(
    *,
    transcript_text: str,
    llm_provider: str,
    gemini_api_key: str,
    gemini_model: str,
    groq_api_key: str,
    groq_model: str,
    temperature: float = 0.4,
    max_retries: int = 2,
) -> Tuple[Dict[str, Any], str]:
    if not transcript_text.strip():
        raise GenerationError("Transcript is empty.")

    providers = _provider_chain(
        llm_provider=llm_provider,
        gemini_api_key=gemini_api_key,
        groq_api_key=groq_api_key,
    )

    errors: List[str] = []
    for provider in providers:
        try:
            if provider == "gemini":
                assets = _generate_with_gemini(
                    transcript_text=transcript_text,
                    api_key=gemini_api_key,
                    model=gemini_model,
                    temperature=temperature,
                    max_retries=max_retries,
                )
                return assets, "gemini"
            assets = _generate_with_groq(
                transcript_text=transcript_text,
                api_key=groq_api_key,
                model=groq_model,
                temperature=temperature,
                max_retries=max_retries,
            )
            return assets, "groq"
        except GenerationError as exc:
            errors.append(f"{provider}: {exc}")

    raise GenerationError("All configured providers failed. " + " | ".join(errors))

