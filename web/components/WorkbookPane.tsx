"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Spinner, Tab, TabList } from "@fluentui/react-components";
import { ArrowDownload20Regular, DocumentTableRegular } from "@fluentui/react-icons";
import { workbook } from "../lib/api";

export function WorkbookPane({ runId, hasOutput, revision, select }: {
  runId: string | null; hasOutput: boolean; revision: number; select: (range: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [which, setWhich] = useState("prior");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => { if (hasOutput) setWhich("output"); }, [hasOutput, revision]);
  useEffect(() => {
    if (!runId || !host.current) return;
    let cancelled = false;
    let dispose: (() => void) | undefined;
    setLoading(true);
    setError("");
    async function load() {
      try {
        const [response, { createUniver, LocaleType, mergeLocales }, { UniverSheetsCorePreset }, { default: enUS }] = await Promise.all([
          workbook(runId!, which),
          import("@univerjs/presets"),
          import("@univerjs/preset-sheets-core"),
          import("@univerjs/preset-sheets-core/locales/en-US"),
        ]);
        if (cancelled || !host.current) return;
        for (const change of response.changed_cells) {
          const sheet = Object.values(response.workbook.sheets).find(s => s.name === change.sheet);
          const cell = sheet?.cellData?.[change.row]?.[change.column];
          if (cell) {
            const style = typeof cell.s === "object" ? cell.s : {};
            cell.s = { ...style, bg: { rgb: "#fff0bc" }, cl: { rgb: "#5c4a16" } };
          }
        }
        const { univerAPI, univer } = createUniver({
          locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: mergeLocales(enUS) },
          presets: [UniverSheetsCorePreset({
            container: host.current, header: false, toolbar: false, formulaBar: false,
            contextMenu: false, disableAutoFocus: true,
            footer: { addSheetButtonConfig: { show: false } },
          })],
        });
        dispose = () => { queueMicrotask(() => univer.dispose()); };
        const book = univerAPI.createWorkbook(response.workbook);
        const listener = book.onSelectionChange(selections => {
          const worksheet = book.getActiveSheet();
          const range = selections[0];
          if (worksheet && range) select(`${worksheet.getSheetName()}!${worksheet.getRange(range).getA1Notation()}`);
        });
        dispose = () => { listener.dispose(); queueMicrotask(() => univer.dispose()); };
        await book.getWorkbookPermission().setReadOnly();
        setNotice(response.truncated_sheets.length ? `Preview limited to 2,000 rows × 60 columns: ${response.truncated_sheets.join(", ")}. Download includes all cells.` : "");
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; dispose?.(); };
  }, [runId, which, revision, select]);
  return <section className="workbook-pane">
    <div className="workbook-toolbar">
      <TabList selectedValue={which} onTabSelect={(_, data) => setWhich(String(data.value))}>
        <Tab value="prior">Last year</Tab><Tab value="output" disabled={!hasOutput}>This year</Tab>
      </TabList>
      <Button as="a" href={runId && hasOutput ? `/api/runs/${runId}/download` : undefined} disabled={!hasOutput} icon={<ArrowDownload20Regular />}>Download</Button>
    </div>
    {hasOutput && which === "output" && <div className="change-legend"><span /> Changed cells · read-only preview</div>}
    {error && <div className="error" role="alert">{error}</div>}
    {notice && <div className="preview-notice">{notice}</div>}
    {!runId && <div className="workbook-empty"><div className="sheet-illustration"><DocumentTableRegular /></div><h2>Your workbook, right here</h2><p>Upload a submission to see its sheets and formatting.<br />Review every update before you download.</p><span>ORIGINAL PRESERVED · CHANGES HIGHLIGHTED</span></div>}
    {loading && <div className="viewer-loading"><Spinner label="Opening workbook..." /></div>}
    <div ref={host} className="univer-host" style={{ visibility: loading ? "hidden" : "visible" }} />
  </section>;
}
