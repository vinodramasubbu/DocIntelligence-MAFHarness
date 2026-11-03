"use client";

import { useEffect, useState } from "react";
import { Spinner, tokens } from "@fluentui/react-components";
import { DismissCircle16Regular } from "@fluentui/react-icons";
import type { ProgressStep } from "../lib/api";

export function PlanCard({ progress, busy }: { progress: ProgressStep[]; busy: boolean }) {
  const [elapsed, setElapsed] = useState(0);
  const [showAll, setShowAll] = useState(false);
  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  if (!progress.length && !busy) return null;
  const visible = progress.filter((step, index) => showAll || step.status === "failed" || index >= progress.length - 6);
  return <section className="plan-card" aria-label="Agent progress">
    <strong>{busy ? `Working with your files · ${elapsed}s elapsed` : "Activity"}</strong>
    {progress.length > visible.length && <button type="button" onClick={() => setShowAll(true)}>Show all {progress.length} activity entries</button>}
    {showAll && progress.length > 6 && <button type="button" onClick={() => setShowAll(false)}>Show recent activity</button>}
    {visible.map(({ text, status, details }, index, list) => <div key={`${index}-${text}`}>
      {status === "failed"
        ? <DismissCircle16Regular aria-label="Failed step" style={{ color: tokens.colorPaletteRedForeground1, flexShrink: 0 }} />
        : busy && index === list.length - 1 ? <Spinner size="extra-tiny" /> : <span aria-label="Activity">•</span>}
      <div style={{ minWidth: 0 }}>
        <span>{text}</span>
        {details && <details>
          <summary>Show error details</summary>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", overflow: "auto", maxHeight: "18rem" }}>{details}</pre>
        </details>}
      </div>
    </div>)}
  </section>;
}
