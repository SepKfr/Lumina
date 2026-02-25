from pathlib import Path

from app.services.llm_client import chat_json

def _resolve_root(required_dir: str) -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[3], here.parents[2]]
    for root in candidates:
        if (root / required_dir).exists():
            return root
    return candidates[-1]


ROOT = _resolve_root("clustering")
PROMPT_PATH = ROOT / "clustering" / "embedding_enrichment_prompt.txt"


"""
Unused by Lumina ingestion (POST /ideas): embedding is computed on raw text only.
Kept for optional v1/insights enrichment if needed.
"""

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
