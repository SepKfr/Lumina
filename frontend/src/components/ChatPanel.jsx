import React, { useState } from "react";
import { sendChat } from "../api";

export default function ChatPanel({ visible, mode, seedNode, userBelief, counterpartyBelief, conversation, setConversation, onClose }) {
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const counterpartLabel = mode === "support" ? "Supporting Perspective" : "Challenging Perspective";

  if (!visible || !seedNode) return null;

  async function onSend(e) {
    e.preventDefault();
    if (!message.trim() || loading) return;
    const userMessage = message.trim();
    setMessage("");
    setLoading(true);
    setConversation((prev) => [
      ...prev,
      { role: "user", content: userMessage },
      { role: "typing", content: "" },
    ]);
    try {
      const result = await sendChat(
        mode,
        seedNode.id,
        userMessage,
        conversation,
        userBelief ?? undefined,
        counterpartyBelief ?? undefined,
      );
      setConversation(result.conversation_state);
    } catch (err) {
      setConversation((prev) => [
        ...prev.filter((turn) => turn.role !== "typing"),
        { role: "agent", content: "I lost the thread for a second. Try that again." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <h3>{mode === "support" ? "Support mode" : "Debate mode"}</h3>
        <button onClick={onClose}>Close</button>
      </div>
      <div className="chat-body">
        {conversation.map((turn, idx) => (
          <div key={idx} className={`turn ${turn.role}`}>
            <strong>{turn.role === "agent" || turn.role === "typing" ? counterpartLabel : "You"}:</strong>{" "}
            {turn.role === "typing" ? (
              <span className="typing-dots" aria-label={`${counterpartLabel} is typing`}>
                <span />
                <span />
                <span />
              </span>
            ) : (
              turn.content
            )}
          </div>
        ))}
      </div>
      <form onSubmit={onSend} className="chat-input">
        <input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Say your next point..." />
        <button type="submit" disabled={loading}>
          Send
        </button>
      </form>
    </div>
  );
}
