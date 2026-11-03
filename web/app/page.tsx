"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, FluentProvider, Select, webLightTheme } from "@fluentui/react-components";
import { DocumentTable24Regular, ShieldCheckmark20Regular } from "@fluentui/react-icons";
import { Upload } from "../components/Upload";
import { Chat } from "../components/Chat";
import { WorkbookPane } from "../components/WorkbookPane";
import { deleteSubmission, rerunSubmission, submission, submissions, upload, useChatStream } from "../lib/api";
import type { SubmissionSummary } from "../lib/api";

const inspectionPrompt = "Read the template and all raw data. Explain your findings, propose the update plan, then STOP for my approval. Do not write the workbook yet.";

function rememberSubmission(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("submission", id);
  else url.searchParams.delete("submission");
  window.history.replaceState(null, "", url);
}

export default function Page() {
  const [runId, setRunId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState("");
  const [saved, setSaved] = useState<SubmissionSummary[]>([]);
  const [opening, setOpening] = useState(false);
  const [notice, setNotice] = useState("");
  const [managing, setManaging] = useState<"rerunning" | "deleting" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const chat = useChatStream(runId);
  const restore = chat.restore;
  const select = useCallback((range: string) => setSelection(range), []);
  const refresh = useCallback(async () => {
    try { setSaved(await submissions()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }, []);
  const open = useCallback(async (id: string) => {
    setOpening(true);
    setError("");
    try {
      const detail = await submission(id);
      restore(detail);
      setRunId(id);
      setSelection("");
      setNotice(detail.notice ?? "");
      rememberSubmission(id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setOpening(false); }
  }, [restore]);
  useEffect(() => { if (!chat.busy) void refresh(); }, [refresh, chat.busy]);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("submission");
    if (id) void open(id);
  }, [open]);
  function newSubmission() {
    restore();
    setRunId(null);
    setSelection("");
    setError("");
    setNotice("");
    rememberSubmission(null);
  }
  async function start(prior: File, raw: File[], name: string) {
    setUploading(true);
    setError("");
    try {
      const id = await upload(prior, raw, name);
      restore(await submission(id));
      setRunId(id);
      rememberSubmission(id);
      await refresh();
      await chat.send(inspectionPrompt, undefined, id);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setUploading(false); }
  }
  async function rerun() {
    if (!runId || chat.busy || managing) return;
    setManaging("rerunning");
    setError("");
    try {
      const id = await rerunSubmission(runId);
      restore(await submission(id));
      setRunId(id);
      setSelection("");
      setNotice("Fresh rerun created from the original uploads. The previous submission is unchanged.");
      rememberSubmission(id);
      await refresh();
      await chat.send(inspectionPrompt, undefined, id);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setManaging(null); }
  }
  async function remove() {
    if (!runId || chat.busy || managing) return;
    setManaging("deleting");
    setError("");
    try {
      await deleteSubmission(runId);
      newSubmission();
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setConfirmDelete(false);
      setManaging(null);
    }
  }
  const disabled = chat.busy || uploading || opening || managing !== null;
  return <FluentProvider theme={{ ...webLightTheme, colorBrandBackground: "#315c50", colorBrandBackgroundHover: "#254a40", colorBrandForeground1: "#315c50" }}>
    <div className="workspace">
      <header><div className="brand"><DocumentTable24Regular /><strong>Submission Builder</strong><span>WORKSPACE</span></div><div className="privacy"><ShieldCheckmark20Regular /> Original always preserved</div></header>
      <nav className="submission-toolbar" aria-label="Saved submissions">
        <label htmlFor="saved-submission">Submission</label>
        <Select id="saved-submission" aria-label="Saved submission" value={runId ?? ""}
          disabled={disabled}
          onChange={(_, data) => { if (data.value) void open(data.value); else newSubmission(); }}>
          <option value="">New submission</option>
          {saved.map(item => <option key={item.run_id} value={item.run_id} disabled={!!item.unavailable}>
            {item.name} · {new Date(item.updated_at).toLocaleString()} · {item.run_id.slice(0, 8)}{item.unavailable ? " (unavailable)" : ""}
          </option>)}
        </Select>
        <Button disabled={disabled} onClick={newSubmission}>New submission</Button>
        <Button disabled={disabled} onClick={() => { setError(""); void refresh(); }}>Refresh list</Button>
        <Button disabled={!runId || disabled} onClick={() => void rerun()}>Re-run submission</Button>
        <Button disabled={!runId || disabled} onClick={() => setConfirmDelete(true)}>Delete submission</Button>
        <span role="status">{opening ? "Opening saved submission..." : managing === "deleting" ? "Deleting submission..." : runId ? chat.busy ? "Running — progress is saved live" : managing === "rerunning" ? "Preparing rerun..." : chat.error ? "Review the error below" : chat.hasOutput ? "Workbook ready — saved locally" : "Saved locally" : "Your work is saved on this computer"}</span>
      </nav>
      {saved.some(item => item.unavailable) && <div role="alert" className="error">Some saved submissions could not be read and are marked unavailable. Their files have not been changed.</div>}
      <main>
        <section className="chat-pane">
          {notice && <div className="preview-notice" role="status">{notice}</div>}
          {!runId ? <Upload start={start} busy={disabled} /> : <Chat key={runId} {...chat} busy={disabled} selection={selection} clearSelection={() => setSelection("")} send={text => { void chat.send(text, selection || undefined).then(refresh); }} />}
          {(error || chat.error) && <div role="alert" className="error">{error || chat.error}</div>}
        </section>
        <WorkbookPane key={runId ?? "new"} runId={runId} hasOutput={chat.hasOutput} revision={chat.revision} select={select} />
      </main>
      <footer><span>A little less spreadsheet work. A little more confidence.</span><span>Powered by Microsoft Foundry · gpt-6.1-sol</span></footer>
    </div>
    <Dialog open={confirmDelete} onOpenChange={(_, data) => { if (!managing) setConfirmDelete(data.open); }}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>Delete this submission?</DialogTitle>
          <DialogContent>
            Permanently delete {saved.find(item => item.run_id === runId)?.name ?? "this submission"}, including its uploads, chat, generated work and workbook. This cannot be undone. Other submissions will not be changed.
          </DialogContent>
          <DialogActions>
            <Button disabled={managing !== null} onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button appearance="primary" disabled={managing !== null} onClick={() => void remove()}>Delete permanently</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  </FluentProvider>;
}
