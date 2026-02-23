import React from "react";

export default function SidePanel({ node, yourInsightNode, selectionContext, supporters, challengers, onOpenChat, onClose, onFocusYourInsight }) {
  const supporterCount = (supporters || []).length;
  const challengerCount = (challengers || []).length;
  const hasSupporters = supporterCount > 0;
  const hasChallengers = challengerCount > 0;
  const topSupporter = (supporters || [])[0];
  const topChallenger = (challengers || [])[0];
  const supporterPreview = (supporters || []).slice(0, 2);
  const challengerPreview = (challengers || []).slice(0, 2);
  const fromSubmission = selectionContext === "submission";
  const isViewingYourInsight = yourInsightNode && node?.id === yourInsightNode.id;
  const showYourInsightReminder = yourInsightNode && !isViewingYourInsight;

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

      <h3>{fromSubmission ? "People who think similar to you" : "People who think similarly about this idea"}</h3>
      {hasSupporters ? (
        supporterPreview.map((s, idx) => (
          <p key={`${s.id || s.text}-${idx}`} className="compact-idea">
            {s.text}
          </p>
        ))
      ) : (
        <p className="compact-idea">No similar nearby belief found yet.</p>
      )}

      <h3>{fromSubmission ? "People who think opposite to you" : "People who think differently about this idea"}</h3>
      {hasChallengers ? (
        challengerPreview.map((c, idx) => (
          <p key={`${c.id || c.text}-${idx}`} className="compact-idea">
            {c.text}
          </p>
        ))
      ) : (
        <p className="compact-idea">No opposing nearby belief found yet.</p>
      )}

      <div className="actions">
        <button onClick={() => onOpenChat("support", topSupporter?.text ?? null)} disabled={!topSupporter}>
          Up for a chat?
        </button>
        <button className="debate" onClick={() => onOpenChat("debate", topChallenger?.text ?? null)} disabled={!topChallenger}>
          Up for a debate?
        </button>
      </div>
    </div>
  );
}
