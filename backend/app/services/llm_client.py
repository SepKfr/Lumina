import json

import httpx

from app.settings import settings


def _headers() -> dict:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set.")
    return {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }


def chat_json(system_prompt: str, user_prompt: str) -> dict:
    with httpx.Client(timeout=90) as client:
        resp = client.post(
            f"{settings.openai_base_url}/chat/completions",
            headers=_headers(),
            json={
                "model": settings.openai_llm_model,
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    return json.loads(content)


def embed_text(text: str) -> list[float]:
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{settings.openai_base_url}/embeddings",
            headers=_headers(),
            json={
                "model": settings.openai_embed_model,
                "input": text,
                "dimensions": settings.embedding_dim,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    embedding = data.get("data", [{}])[0].get("embedding")
    if not isinstance(embedding, list):
        raise ValueError("Embedding endpoint returned invalid payload.")
    return embedding
