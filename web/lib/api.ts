"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { IWorkbookData } from "@univerjs/presets";

export type WorkbookResponse = {
  workbook: IWorkbookData;
  changed_cells: { sheet: string; cell: string; row: number; column: number }[];
  truncated_sheets: string[];
};
export type Message = { role: "user" | "assistant"; text: string };
export type ProgressStep = { text: string; status?: "failed"; details?: string };
export type SubmissionSummary = {
  run_id: string; name: string; created_at: string; updated_at: string;
  has_output: boolean; busy: boolean; unavailable: string | null;
};
export type SavedSubmission = SubmissionSummary & {
  messages: Message[]; progress: ProgressStep[]; error: string | null; notice: string | null;
};

export async function submissions(): Promise<SubmissionSummary[]> {
  const response = await fetch("/api/runs", { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function submission(runId: string): Promise<SavedSubmission> {
  const response = await fetch(`/api/runs/${runId}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export async function deleteSubmission(runId: string): Promise<void> {
  const response = await fetch(`/api/runs/${runId}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await response.text());
}

export async function rerunSubmission(runId: string): Promise<string> {
  const response = await fetch(`/api/runs/${runId}/rerun`, { method: "POST" });
  if (!response.ok) throw new Error(await response.text());
  return (await response.json()).run_id;
}

export async function upload(prior: File, raw: File[], name: string): Promise<string> {
  const data = new FormData();
  data.append("prior", prior);
  raw.forEach(file => data.append("raw", file));
  data.append("name", name);
  const response = await fetch("/api/runs", { method: "POST", body: data });
  if (!response.ok) throw new Error(await response.text());
  return (await response.json()).run_id;
}

export async function workbook(runId: string, which: string): Promise<WorkbookResponse> {
  const response = await fetch(`/api/runs/${runId}/workbook?which=${which}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

export function useChatStream(runId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [progress, setProgress] = useState<ProgressStep[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hasOutput, setHasOutput] = useState(false);
  const [revision, setRevision] = useState(0);
  const active = useRef(false);
  const [observing, setObserving] = useState(false);

  const restore = useCallback((saved?: SavedSubmission) => {
    setMessages(saved?.messages ?? []);
    setProgress(saved?.progress ?? []);
    setError(saved?.error ?? "");
    setHasOutput(saved?.has_output ?? false);
    setBusy(saved?.busy ?? false);
    setObserving(saved?.busy ?? false);
    setRevision(old => old + 1);
  }, []);

  useEffect(() => {
    if (!observing || !runId) return;
    const identifier = runId;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const saved = await submission(identifier);
        if (cancelled) return;
        setMessages(saved.messages);
        setProgress(saved.progress);
        setError(saved.error ?? "");
        setHasOutput(saved.has_output);
        setBusy(saved.busy);
        if (!saved.busy) {
          setObserving(false);
          setRevision(old => old + 1);
        } else timer = setTimeout(poll, 1500);
      } catch (reason) {
        if (cancelled) return;
        setError(reason instanceof Error ? reason.message : String(reason));
        setBusy(false);
        setObserving(false);
      }
    }
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [observing, runId]);

  async function send(message: string, selection?: string, id = runId) {
    if (!id || active.current) return;
    active.current = true;
    setBusy(true);
    setError("");
    setProgress([]);
    setMessages(old => [...old, { role: "user", text: message }, { role: "assistant", text: "" }]);
    try {
      const response = await fetch(`/api/runs/${id}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, selection }),
      });
      if (!response.ok || !response.body) throw new Error(await response.text());
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const event = block.split("\n").find(line => line.startsWith("event:"))?.slice(6).trim();
          const data = block.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
          if (!data) continue;
          const payload = JSON.parse(data);
          if (event === "text") setMessages(old => old.map((m, i) => i === old.length - 1 ? { ...m, text: m.text + payload.text } : m));
          if (event === "progress") setProgress(old => [...old, { text: payload.text, status: payload.status, details: payload.details }]);
          if (event === "done") {
            completed = true;
            setHasOutput(payload.has_output);
            if (payload.has_output) setRevision(old => old + 1);
            if (payload.error) throw new Error(payload.error);
          }
        }
        if (done) break;
      }
      if (!completed) throw new Error("The connection ended before the agent completed. Please retry.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      active.current = false;
      setBusy(false);
    }
  }
  return { messages, progress, busy, error, hasOutput, revision, send, restore };
}
