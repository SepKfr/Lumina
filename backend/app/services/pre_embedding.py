from pathlib import Path

from app.services.llm_client import chat_json

ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT / "clustering" / "embedding_enrichment_prompt.txt"


def classify_embedding_context(text: str, type_label: str) -> dict:
    system_prompt = PROMPT_PATH.read_text()
    user_prompt = (
        f"Type label: {type_label}\n\n"
        f"Insight:\n{text}\n\n"
        "Return topic_label, stance_hint, canonical_claim."
    )
    result = chat_json(system_prompt, user_prompt)
    required = {"topic_label", "stance_hint", "canonical_claim"}
    if not required.issubset(result.keys()):
        raise ValueError("Embedding context classification missing required fields.")
    return result
