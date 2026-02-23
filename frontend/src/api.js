const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function fetchGraph(params = {}) {
  const query = new URLSearchParams(params);
  const res = await fetch(`${API_BASE}/v1/graph?${query.toString()}`);
  if (!res.ok) throw new Error("Failed to load graph.");
  return res.json();
}

export async function submitInsight(text) {
  const res = await fetch(`${API_BASE}/v1/insights`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = err?.detail;
    const guardrail = detail?.guardrail || {};
    if (detail?.decision === "revise") {
      const suggestion = guardrail?.suggested_revision || "Try rewriting your idea as one clear sentence.";
      throw new Error(`Needs revision: ${suggestion}`);
    }
    if (detail?.decision === "reject") {
      const reason = guardrail?.categories?.quality || "The submission was rejected by moderation reasoning.";
      throw new Error(`Rejected: ${reason}`);
    }
    throw new Error(detail || "Submission failed. Please try another one-sentence insight.");
  }
  return res.json();
}

export async function sendChat(mode, seedInsightId, userMessage, conversationState, userBelief = null, counterpartyBelief = null) {
  const body = {
    mode,
    seed_insight_id: seedInsightId,
    user_message: userMessage,
    conversation_state: conversationState,
  };
  if (userBelief != null && userBelief !== "") {
    body.user_belief = userBelief;
  }
  if (counterpartyBelief != null && counterpartyBelief !== "") {
    body.counterparty_belief = counterpartyBelief;
  }
  const res = await fetch(`${API_BASE}/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Chat request failed.");
  return res.json();
}
