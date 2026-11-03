"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Textarea } from "@fluentui/react-components";
import { ArrowUp20Regular, Dismiss16Regular } from "@fluentui/react-icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message, ProgressStep } from "../lib/api";
import { PlanCard } from "./PlanCard";

export function Chat({ messages, progress, busy, selection, clearSelection, send }: {
  messages: Message[]; progress: ProgressStep[]; busy: boolean; selection: string;
  clearSelection: () => void; send: (text: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, progress]);
  function submit() {
    if (!draft.trim() || busy) return;
    send(draft.trim());
    setDraft("");
  }
  return <>
    <div className="conversation">
      <div className="conversation-label">SUBMISSION ASSISTANT</div>
      {messages.map((message, index) => <article key={index} className={`message ${message.role}`}>
        <div className="speaker">{message.role === "user" ? "You" : "Submission Builder"}</div>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
      </article>)}
      <PlanCard progress={progress} busy={busy} />
      <div ref={end} />
    </div>
    <div className="composer">
      {selection && <div className="selection-chip">{selection}<Button appearance="transparent" size="small" icon={<Dismiss16Regular />} aria-label="Clear selection" onClick={clearSelection} /></div>}
      <Textarea aria-label="Message the submission assistant" value={draft} resize="vertical" placeholder="Ask a question, approve the plan, or request a fix..."
        onChange={(_, data) => setDraft(data.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }} />
      <div className="composer-footer"><span>Review first. Update with your OK.</span>
        <Button appearance="primary" icon={<ArrowUp20Regular />} aria-label="Send message" disabled={busy || !draft.trim()} onClick={submit} />
      </div>
    </div>
  </>;
}
