import React, { useRef, useState } from "react";
import { getSpeech, sendChat, transcribeAudio } from "../api";

export default function ChatPanel({ visible, mode, seedNode, userBelief, counterpartyBelief, conversation, setConversation, onClose }) {
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [userEmotion, setUserEmotion] = useState(null);
  const [playingAudio, setPlayingAudio] = useState(false);
  const [transcribeError, setTranscribeError] = useState(null);
  const [agentVoiceOn, setAgentVoiceOn] = useState(true);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const mimeTypeRef = useRef("audio/webm");
  const streamIntervalRef = useRef(null);
  const counterpartLabel = mode === "support" ? "Supporting Perspective" : "Challenging Perspective";

  if (!visible || !seedNode) return null;

  async function onSend(e) {
    e.preventDefault();
    if (!message.trim() || loading) return;
    const userMessage = message.trim();
    setMessage("");
    setLoading(true);
    setUserEmotion(null);
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
        userEmotion ?? undefined,
      );
      if (agentVoiceOn && result.response) {
        setConversation((prev) => [
          ...prev.filter((t) => t.role !== "typing"),
          { role: "agent", content: "" },
        ]);
        playAgentReplyWithStreaming(result.response, result.conversation_state);
      } else {
        setConversation(result.conversation_state);
      }
    } catch (err) {
      setConversation((prev) => [
        ...prev.filter((turn) => turn.role !== "typing"),
        { role: "agent", content: "I lost the thread for a second. Try that again." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function toggleRecord() {
    setTranscribeError(null);
    if (recording) {
      mediaRecorderRef.current?.stop();
      mediaRecorderRef.current = null;
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      mimeTypeRef.current = recorder.mimeType || "audio/webm";
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setTranscribing(true);
        if (chunksRef.current.length === 0) {
          setTranscribeError("No audio recorded. Speak then tap the mic again to stop.");
          setTranscribing(false);
          return;
        }
        const blob = new Blob(chunksRef.current, { type: mimeTypeRef.current });
        const filename = mimeTypeRef.current.includes("webm") ? "audio.webm" : "audio.m4a";
        try {
          const data = await transcribeAudio(blob, filename, true);
          setTranscribeError(null);
          if (data.text) setMessage((m) => (m ? `${m} ${data.text}` : data.text).trim());
          else setTranscribeError("No speech detected. Try speaking clearly and recording again.");
          if (data.emotion) setUserEmotion(data.emotion);
        } catch (err) {
          setTranscribeError(err.message || "Transcription failed. Try again.");
        } finally {
          setTranscribing(false);
        }
      };
      recorder.start(1000);
      mediaRecorderRef.current = recorder;
      setRecording(true);
    } catch (err) {
      setTranscribeError("Microphone access denied or unavailable.");
    }
  }

  async function playAgentReply(text) {
    if (!text?.trim() || playingAudio) return;
    setPlayingAudio(true);
    try {
      const blob = await getSpeech(text, mode);
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => {
        URL.revokeObjectURL(url);
        setPlayingAudio(false);
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        setPlayingAudio(false);
      };
      await audio.play();
    } catch (err) {
      console.error("Play error:", err);
      setPlayingAudio(false);
    }
  }

  function playAgentReplyWithStreaming(fullText, finalConversationState) {
    if (!fullText?.trim() || playingAudio) return;
    setPlayingAudio(true);
    const words = fullText.trim().split(/\s+/);
    let wordIndex = 0;
    const clearStreamInterval = () => {
      if (streamIntervalRef.current) {
        clearInterval(streamIntervalRef.current);
        streamIntervalRef.current = null;
      }
    };
    getSpeech(fullText, mode)
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.onended = () => {
          clearStreamInterval();
          setConversation(finalConversationState);
          URL.revokeObjectURL(url);
          setPlayingAudio(false);
        };
        audio.onerror = () => {
          clearStreamInterval();
          setConversation(finalConversationState);
          URL.revokeObjectURL(url);
          setPlayingAudio(false);
        };
        const tryStart = () => {
          const duration = audio.duration;
          if (!Number.isFinite(duration) || duration <= 0) {
            setConversation(finalConversationState);
            audio.play().catch(() => setPlayingAudio(false));
            return;
          }
          const intervalMs = Math.max(50, (duration * 1000) / words.length);
          streamIntervalRef.current = setInterval(() => {
            wordIndex += 1;
            if (wordIndex >= words.length) {
              clearStreamInterval();
              return;
            }
            setConversation((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === "agent") {
                next[next.length - 1] = { ...last, content: words.slice(0, wordIndex).join(" ") };
              }
              return next;
            });
          }, intervalMs);
          audio.play().catch(() => {});
        };
        audio.addEventListener("loadedmetadata", tryStart, { once: true });
        audio.addEventListener("durationchange", tryStart, { once: true });
        audio.load();
        if (audio.readyState >= 1) tryStart();
      })
      .catch((err) => {
        console.error("TTS error:", err);
        setConversation(finalConversationState);
        setPlayingAudio(false);
      });
  }

  async function playLastAgentReply() {
    const lastAgent = [...conversation].reverse().find((t) => t.role === "agent" && t.content);
    if (!lastAgent?.content || playingAudio || loading) return;
    await playAgentReply(lastAgent.content);
  }

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <h3>{mode === "support" ? "Support mode" : "Debate mode"}</h3>
        <label className="chat-agent-voice-toggle">
          <input
            type="checkbox"
            checked={agentVoiceOn}
            onChange={(e) => setAgentVoiceOn(e.target.checked)}
          />
          Agent speaks reply
        </label>
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
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={transcribing ? "Transcribing..." : "Say your next point or type..."}
          disabled={transcribing}
        />
        <button
          type="button"
          className="chat-mic"
          onClick={toggleRecord}
          disabled={loading || transcribing}
          title={recording ? "Stop recording" : "Voice input (transcribe + optional emotion)"}
          aria-label={recording ? "Stop recording" : "Voice input"}
        >
          {recording ? "⏹" : "🎤"}
        </button>
        <button
          type="button"
          className="chat-speaker"
          onClick={playLastAgentReply}
          disabled={loading || playingAudio || !conversation.some((t) => t.role === "agent" && t.content)}
          title="Play last reply aloud (idea-embodied voice)"
          aria-label="Play last reply"
        >
          {playingAudio ? "⏳" : "🔊"}
        </button>
        <button type="submit" disabled={loading}>
          Send
        </button>
      </form>
      {transcribeError && (
        <div className="chat-transcribe-error" role="alert">
          {transcribeError}
        </div>
      )}
    </div>
  );
}
