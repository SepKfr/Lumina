from pathlib import Path

from app.models import Insight
from app.services.guardrails import run_chat_guardrail
from app.services.llm_client import chat_json

ROOT = Path(__file__).resolve().parents[3]
SUPPORT_PROMPT_PATH = ROOT / "chat" / "support_agent_prompt.txt"
DEBATE_PROMPT_PATH = ROOT / "chat" / "debate_agent_prompt.txt"


def generate_chat_reply(
    mode: str,
    seed_insight: Insight,
    user_message: str,
    conversation_state: list[dict] | None,
    user_belief: str | None = None,
    counterparty_belief: str | None = None,
) -> tuple[str, dict]:
    guardrail = run_chat_guardrail(user_message)
    if guardrail["decision"] != "allow":
        return guardrail["safe_rewrite"], guardrail

    prompt_path = SUPPORT_PROMPT_PATH if mode == "support" else DEBATE_PROMPT_PATH
    system_prompt = prompt_path.read_text()

    user_belief_text = (user_belief or "").strip() or (seed_insight.text or "").strip()
    seed_belief = (counterparty_belief or "").strip()
    if not seed_belief:
        if mode == "debate":
            seed_belief = f'I disagree with this claim and believe the opposite: "{user_belief_text}"'
        else:
            seed_belief = f'I agree with this claim and support it: "{user_belief_text}"'

    system_prompt = (
        system_prompt.replace("{user_belief}", user_belief_text)
        .replace("{seed_belief}", seed_belief)
        .replace("{user_message}", user_message)
    )

    history_lines = []
    for turn in conversation_state or []:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        history_lines.append(f"{role.upper()}: {content}")
    history = "\n".join(history_lines) if history_lines else "(none)"

    user_prompt = (
        f"Conversation so far:\n{history}\n\n"
        f"User says:\n{user_message}\n\n"
        "Respond with JSON: {\"response\":\"...\"}."
    )
    result = chat_json(system_prompt, user_prompt)
    reply = result.get("response", "I want to answer that more clearly. Say it again in one sentence.")
    return reply, guardrail
