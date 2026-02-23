import json
import re


def normalize_insight_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned.endswith((".", "!", "?")):
        cleaned += "."
    return cleaned


def insight_text_key(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    cleaned = re.sub(r"[.!?]+$", "", cleaned)
    return cleaned


def parse_json_object(raw_text: str) -> dict:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
        if not match:
            raise ValueError("Model did not return JSON.")
        return json.loads(match.group(0))


def is_opposing_stance(a: str, b: str) -> bool:
    return (a == "pro" and b == "con") or (a == "con" and b == "pro")
