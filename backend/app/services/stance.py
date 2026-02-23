from pathlib import Path

from app.services.llm_client import chat_json

def _resolve_root(required_dir: str) -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[3], here.parents[2]]
    for root in candidates:
        if (root / required_dir).exists():
            return root
    return candidates[-1]


ROOT = _resolve_root("chat")
STANCE_PROMPT_PATH = ROOT / "chat" / "stance_extraction_prompt.txt"


def extract_stance(text: str, cluster_summary: str) -> dict:
    system_prompt = STANCE_PROMPT_PATH.read_text()
    user_prompt = (
        "Cluster context:\n"
        f"{cluster_summary}\n\n"
        "Insight:\n"
        f"{text}\n\n"
        "Return canonical claim, stance label, and counterclaim."
    )
    result = chat_json(system_prompt, user_prompt)
    required = {"canonical_claim", "stance_label", "counterclaim"}
    if not required.issubset(result.keys()):
        raise ValueError("Stance extraction missing required fields.")
    return result
