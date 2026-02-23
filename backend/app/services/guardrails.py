from pathlib import Path

from app.services.llm_client import chat_json

def _resolve_root(required_dir: str) -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[3], here.parents[2]]
    for root in candidates:
        if (root / required_dir).exists():
            return root
    return candidates[-1]


ROOT = _resolve_root("guardrails")
SUBMISSION_PROMPT_PATH = ROOT / "guardrails" / "submission_guardrail_prompt.txt"
CHAT_PROMPT_PATH = ROOT / "guardrails" / "chat_message_guardrail_prompt.txt"


def run_submission_guardrail(text: str) -> dict:
    system_prompt = SUBMISSION_PROMPT_PATH.read_text()
    user_prompt = f"Evaluate this one-sentence insight:\n\n{text}"
    result = chat_json(system_prompt, user_prompt)
    required = {"decision", "categories", "type_label"}
    if not required.issubset(result.keys()):
        raise ValueError("Guardrail result missing required fields.")
    return result


def run_chat_guardrail(user_message: str) -> dict:
    system_prompt = CHAT_PROMPT_PATH.read_text()
    user_prompt = f"Evaluate this chat message for conversational safety:\n\n{user_message}"
    result = chat_json(system_prompt, user_prompt)
    required = {"decision", "reason", "safe_rewrite"}
    if not required.issubset(result.keys()):
        raise ValueError("Chat guardrail result missing required fields.")
    return result
