"use client";

import { useState } from "react";
import { Button, Input, Spinner } from "@fluentui/react-components";
import { ArrowUpload24Regular } from "@fluentui/react-icons";

export function Upload({ start, busy }: { start: (prior: File, raw: File[], name: string) => void; busy: boolean }) {
  const [name, setName] = useState("");
  const [prior, setPrior] = useState<File | null>(null);
  const [raw, setRaw] = useState<File[]>([]);
  return <section className="upload-card">
    <span className="eyebrow">YOUR NEXT SUBMISSION, TOGETHER</span>
    <h1>A fresh year.<br />A familiar workbook.</h1>
    <p>Bring last year&apos;s template and this year&apos;s data. We&apos;ll make a plan before changing a single cell.</p>
    <label className="submission-name">Submission name (optional)
      <Input value={name} onChange={(_, data) => setName(data.value)} maxLength={120}
        disabled={busy} placeholder="e.g. Harborview renewal 2026" aria-label="Submission name" />
    </label>
    <label className="drop-zone" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); setPrior(e.dataTransfer.files[0] ?? null); }}>
      <ArrowUpload24Regular /><strong>Last year&apos;s submission</strong>
      <span>{prior?.name ?? "Choose or drop an .xlsx workbook"}</span>
      <input aria-label="Last year's submission" type="file" accept=".xlsx" disabled={busy} onChange={e => setPrior(e.target.files?.[0] ?? null)} />
    </label>
    <label className="drop-zone" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); setRaw(Array.from(e.dataTransfer.files)); }}>
      <ArrowUpload24Regular /><strong>This year&apos;s raw data</strong>
      <span>{raw.length ? raw.map(f => f.name).join(", ") : "Excel, CSV, notes or emails (.txt / .md)"}</span>
      <input aria-label="This year's raw data" type="file" accept=".xlsx,.csv,.txt,.md" multiple disabled={busy} onChange={e => setRaw(Array.from(e.target.files ?? []))} />
    </label>
    <Button appearance="primary" size="large" disabled={!prior || !raw.length || busy} onClick={() => prior && start(prior, raw, name)}>
      {busy ? <Spinner size="tiny" /> : "Build my submission"}
    </Button>
    <small>Your original workbook stays untouched. You approve the plan.</small>
  </section>;
}
