import React, { useState } from "react";

export default function InsightForm({ onSubmit }) {
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (!value.trim()) return;
    setLoading(true);
    try {
      await onSubmit(value.trim());
      setValue("");
    } catch (err) {
      setError(err.message || "Submission failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="insight-form" onSubmit={handleSubmit}>
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="What's on your mind? (one sentence)"
        maxLength={320}
      />
      <p className="insight-hint">Share a single sentence—one idea at a time.</p>
      <button type="submit" disabled={loading}>
        Submit
      </button>
      {loading && (
        <div className="ingestion-progress" aria-live="polite">
          <span className="spinner" />
          <span>Ingesting your insight... extracting topic, embedding, and graph links.</span>
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </form>
  );
}
