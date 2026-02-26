"""
Voice-to-text (Whisper), optional emotion-from-transcript, and text-to-speech (TTS).
OpenAI Whisper does not output emotion; we infer it from the transcript via LLM.
OpenAI TTS: use voice + speed (+ instructions on newer models) for idea-embodied tone.
"""
import json
from typing import BinaryIO

import httpx

from app.settings import settings


def _headers() -> dict:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set.")
    return {"Authorization": f"Bearer {settings.openai_api_key}"}


# Allowed emotion labels we pass to chat (and optionally TTS)
EMOTION_LABELS = ("neutral", "calm", "frustrated", "angry", "excited", "sad", "curious", "uncertain")


def transcribe(audio_file: BinaryIO, filename: str = "audio.webm") -> str:
    """Transcribe audio with OpenAI Whisper. Returns plain text."""
    url = f"{settings.openai_base_url}/audio/transcriptions"
    headers = _headers()
    # Whisper expects multipart: file + model
    files = {"file": (filename, audio_file, "audio/webm")}
    data = {"model": "whisper-1"}
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, headers=headers, files=files, data=data)
        resp.raise_for_status()
    out = resp.json()
    if isinstance(out, dict):
        return out.get("text", "")
    return str(out) if out else ""


def infer_emotion_from_transcript(transcript: str) -> str:
    """
    Infer likely user emotion from transcript text (no audio).
    Use this when you don't have an audio-based emotion model.
    Returns one of EMOTION_LABELS.
    """
    if not transcript or not transcript.strip():
        return "neutral"
    prompt = (
        "Given this short user message from a voice conversation, pick the single word that best describes "
        "the speaker's likely tone/emotion. Choose exactly one from: neutral, calm, frustrated, angry, excited, sad, curious, uncertain. "
        "Reply with JSON only: {\"emotion\": \"neutral\"}."
    )
    from app.services.llm_client import chat_json
    try:
        result = chat_json(
            "You are a minimal classifier. Output only valid JSON.",
            f"{prompt}\n\nUser message: {transcript[:500]}",
        )
        emotion = (result.get("emotion") or "neutral").strip().lower()
        return emotion if emotion in EMOTION_LABELS else "neutral"
    except Exception:
        return "neutral"


def text_to_speech(
    text: str,
    voice_profile: str = "support",
    *,
    voice: str | None = None,
    speed: float = 1.0,
) -> bytes:
    """
    Generate speech from text. voice_profile drives default voice + speed to match idea persona.
    - support: warmer, slightly slower (e.g. nova, 0.95)
    - debate: sharper, normal or slightly faster (e.g. onyx, 1.05)
    Optional: use TTS model that supports 'instructions' for emotional tone (e.g. gpt-4o-mini-tts).
    """
    # Map idea-embodied profile to voice + speed (OpenAI voices: alloy, echo, fable, onyx, nova, shimmer, etc.)
    if voice_profile == "debate":
        voice = voice or "onyx"
        speed = speed if speed != 1.0 else 1.05
    else:
        voice = voice or "nova"
        speed = speed if speed != 1.0 else 0.95

    url = f"{settings.openai_base_url}/audio/speech"
    headers = _headers()
    headers["Content-Type"] = "application/json"
    payload = {
        "model": settings.openai_tts_model,
        "input": text[:4096],
        "voice": voice,
        "speed": min(4.0, max(0.25, speed)),
        "response_format": "mp3",
    }
    # Newer TTS models support instructions for tone (not tts-1/tts-1-hd)
    tts_model = payload["model"]
    if "gpt-4o" in tts_model or "tts-2025" in tts_model:
        if voice_profile == "debate":
            payload["instructions"] = "Speak in a direct, slightly assertive tone. Not hostile, but confident and engaged."
        else:
            payload["instructions"] = "Speak in a warm, supportive tone. Casual and natural."

    with httpx.Client(timeout=30) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
    return resp.content
