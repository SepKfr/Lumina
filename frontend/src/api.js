// Use env so production (e.g. EC2) can set VITE_API_BASE_URL=/lumina/api or full URL.
// Default /api works with Vite dev proxy (see vite.config.js); never hardcode localhost.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export async function fetchGraph(params = {}) {
  const query = new URLSearchParams(params);
  const res = await fetch(`${API_BASE}/v1/graph?${query.toString()}`);
  if (!res.ok) throw new Error("Failed to load graph.");
  return res.json();
}

export async function fetchRelations(id, topK = 2, candidatePool = 24) {
  const query = new URLSearchParams({
    id: String(id),
    top_k: String(topK),
    candidate_pool: String(candidatePool),
  });
  const res = await fetch(`${API_BASE}/relations?${query.toString()}`);
  if (!res.ok) throw new Error("Failed to load relation buckets.");
  return res.json();
}

/** Fast path: topic + stance only, no LLM. Returns at most 2 supportive and 2 opposing (leaves-first). */
export async function fetchSupportiveAndOpposing(id, topK = 2) {
  const [supportRes, opposeRes] = await Promise.all([
    fetch(`${API_BASE}/supportive?id=${encodeURIComponent(id)}&top_k=${topK}`),
    fetch(`${API_BASE}/opposing?id=${encodeURIComponent(id)}&top_k=${topK}`),
  ]);
  if (!supportRes.ok) throw new Error("Failed to load supportive ideas.");
  if (!opposeRes.ok) throw new Error("Failed to load opposing ideas.");
  const [supportData, opposeData] = await Promise.all([supportRes.json(), opposeRes.json()]);
  return {
    supportive: supportData.neighbors || [],
    opposing: opposeData.neighbors || [],
  };
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

export async function sendChat(mode, seedInsightId, userMessage, conversationState, userBelief = null, counterpartyBelief = null, userEmotion = null) {
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
  if (userEmotion != null && userEmotion !== "") {
    body.user_emotion = userEmotion;
  }
  const res = await fetch(`${API_BASE}/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Chat request failed.");
  return res.json();
}

/** Voice: send audio file, get { text, emotion }. */
export async function transcribeAudio(file, filename = "audio.webm", inferEmotion = true) {
  const form = new FormData();
  form.append("file", file, filename);
  const res = await fetch(`${API_BASE}/v1/audio/transcribe?infer_emotion=${inferEmotion}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail || "Transcription failed.");
  }
  return res.json();
}

/** Voice: get MP3 audio for agent reply. voiceProfile = "support" | "debate". */
export async function getSpeech(text, voiceProfile = "support") {
  const res = await fetch(`${API_BASE}/v1/audio/speech`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice_profile: voiceProfile }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail || "Speech failed.");
  }
  return res.blob();
}
