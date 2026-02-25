import React from "react";

export default function SidePanel({ node, yourInsightNode, selectionContext, supporters, challengers, relationsLoading = false, onOpenChat, onClose, onFocusYourInsight, debugMode = false }) {
  const supporterCount = (supporters || []).length;
  const challengerCount = (challengers || []).length;
  const hasSupporters = supporterCount > 0;
  const hasChallengers = challengerCount > 0;
  const fromSubmission = selectionContext === "submission";
  const isViewingYourInsight = yourInsightNode && node?.id === yourInsightNode.id;
  const showYourInsightReminder = yourInsightNode && !isViewingYourInsight;

  const level1 = node?.level1 ?? node?.metadata_json?.level1;
  const level2 = node?.level2 ?? node?.metadata_json?.level2;
  const level3 = node?.level3 ?? node?.metadata_json?.level3;
  const hasTopicDebug = debugMode && (level1 || level2 || level3);

  function topicDebugBlock(n) {
    const l1 = n?.level1 ?? n?.metadata_json?.level1;
    const l2 = n?.level2 ?? n?.metadata_json?.level2;
    const l3 = n?.level3 ?? n?.metadata_json?.level3;
    if (!debugMode || (!l1 && !l2 && !l3)) return null;
    return (
      <div className="topic-debug">
        <span className="topic-debug-label">L1:</span> {l1 || "—"} · <span className="topic-debug-label">L2:</span> {l2 || "—"} · <span className="topic-debug-label">L3:</span> {l3 || "—"}
      </div>
    );
  }

  return (
    <div className="side-panel">
      <div className="side-panel-header">
        <h2>Insight</h2>
        <button type="button" className="close-insight" onClick={onClose} aria-label="Close insight and return to graph">
          Close
        </button>
      </div>
      {showYourInsightReminder && (
        <div className="your-insight-reminder">
          <p className="your-insight-label">This is what you think:</p>
          <p className="your-insight-text">{yourInsightNode.text}</p>
          <button type="button" className="focus-your-insight" onClick={onFocusYourInsight}>
            Go to my insight
          </button>
        </div>
      )}
      {isViewingYourInsight && <p className="you-are-here-badge">This is your insight — you are here on the map.</p>}
      <p className="insight-text">{node.text}</p>
      {hasTopicDebug && (
        <div className="topic-debug-block">
          <strong>Topic (debug)</strong>
          <p className="topic-debug"><span className="topic-debug-label">L1:</span> {level1 || "—"}</p>
          <p className="topic-debug"><span className="topic-debug-label">L2:</span> {level2 || "—"}</p>
          <p className="topic-debug"><span className="topic-debug-label">L3:</span> {level3 || "—"}</p>
        </div>
      )}

      {relationsLoading ? (
        <div className="relations-loading-wrap">
          <div className="relations-loading">
            <span className="spinner" aria-hidden />
            <p className="relations-loading-text">Finding nearby ideas…</p>
          </div>
        </div>
      ) : (
        <>
          <h3>{fromSubmission ? "People who think similar to you" : "People who think similarly about this idea"}</h3>
          {hasSupporters ? (
            (supporters || []).map((s, idx) => (
              <div key={`${s.id || s.text}-${idx}`} className="compact-idea">
                <p>{s.text}</p>
                {topicDebugBlock(s)}
                <button type="button" onClick={() => onOpenChat("support", s.text)}>
                  Chat with this view
                </button>
              </div>
            ))
          ) : (
            <p className="compact-idea">No similar nearby belief found yet.</p>
          )}

          <h3>{fromSubmission ? "People who think opposite to you" : "People who think differently about this idea"}</h3>
          {hasChallengers ? (
            (challengers || []).map((c, idx) => (
              <div key={`${c.id || c.text}-${idx}`} className="compact-idea">
                <p>{c.text}</p>
                {topicDebugBlock(c)}
                <button type="button" className="debate" onClick={() => onOpenChat("debate", c.text)}>
                  Debate this view
                </button>
              </div>
            ))
          ) : (
            <p className="compact-idea">No opposing nearby belief found yet.</p>
          )}
        </>
      )}
    </div>
  );
}
