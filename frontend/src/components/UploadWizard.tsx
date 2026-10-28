"use client";
import { AlertTriangle, ArrowLeft, FileUp, Globe, Mail, RotateCcw, Trash2, UploadCloud } from "lucide-react";
import React, { useCallback, useRef, useState } from "react";
import { CrawlSettingsForm, useCrawlDefaults } from "@/components/CrawlSettingsForm";
import { JobPanel } from "@/components/JobPanel";
import { Badge, Button, Card, CardHeader, Checkbox, Field, Input, Notice, Select, Spinner, Stat } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";
import { fmtBytes, fmtNum } from "@/lib/format";
import type { PreviewResult, Sheet, UploadInfo } from "@/lib/types";

const ACCEPT = ".pdf,.docx,.xlsx,.xls,.csv,.txt,.md,.html,.htm,.json,.xml";
const ALL_SHEETS = "__all__";

interface CommitResult {
  filename: string;
  extract_job?: { id: number; created: number; duplicates: number; rejected: number };
  crawl_job?: { id: number; valid: number; invalid: number; duplicates: number };
  file_deleted?: boolean;
}

export function UploadWizard({ mode }: { mode: "extract" | "urls" }) {
  const toast = useToast();
  const [settings, setSettings, limits] = useCrawlDefaults();
  const inputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<"pick" | "map" | "review" | "done">("pick");
  const [uploading, setUploading] = useState(false);
  const [drag, setDrag] = useState(false);
  const [upload, setUpload] = useState<UploadInfo | null>(null);
  const [sheet, setSheet] = useState<string>(ALL_SHEETS);
  const [urlCols, setUrlCols] = useState<number[]>([]);
  const [nameCol, setNameCol] = useState<number | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saveEmails, setSaveEmails] = useState(true);
  const [crawl, setCrawl] = useState(mode === "urls");
  const [deleteAfter, setDeleteAfter] = useState(true);
  const [committing, setCommitting] = useState(false);
  const [result, setResult] = useState<CommitResult | null>(null);

  const maxMb = Number(limits?.max_upload_mb ?? 25);
  const activeSheet: Sheet | undefined = upload?.sheets.find((s) => s.name === sheet);

  const reset = useCallback(() => {
    setStep("pick"); setUpload(null); setPreview(null); setResult(null); setSheet(ALL_SHEETS); setUrlCols([]); setNameCol(null);
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  const body = (extra: object = {}) => ({
    sheet: sheet !== ALL_SHEETS ? sheet : null,
    url_columns: sheet !== ALL_SHEETS ? urlCols : null,
    name_column: sheet !== ALL_SHEETS ? nameCol : null,
    ...extra,
  });

  async function runPreview(u: UploadInfo, payload: object) {
    setPreviewing(true);
    try {
      const p = await api.post<PreviewResult>(`/api/uploads/${u.upload_id}/preview`, payload);
      setPreview(p);
      setSaveEmails(p.unique_emails > 0);
      setCrawl(mode === "urls" ? p.urls_total > 0 : false);
      setStep("review");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not read this file");
      if (e instanceof ApiError && (e.status === 422 || e.status === 408)) {
        await api.del(`/api/uploads/${u.upload_id}`).catch(() => undefined);
        reset();
      }
    } finally {
      setPreviewing(false);
    }
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    if (file.size > maxMb * 1024 * 1024) return toast.error(`${file.name} is larger than the ${maxMb} MB limit.`);
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const u = await api.upload<UploadInfo>("/api/uploads", form);
      setUpload(u);
      if (u.kind === "tabular" && u.sheets.length) {
        const first = u.sheets[0];
        setSheet(u.sheets.length > 1 ? first.name : first.name);
        setUrlCols(first.suggested_url_columns);
        setNameCol(first.suggested_name_column);
        setStep("map");
      } else {
        await runPreview(u, {});
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function chooseSheet(name: string) {
    setSheet(name);
    const s = upload?.sheets.find((x) => x.name === name);
    setUrlCols(s?.suggested_url_columns ?? []);
    setNameCol(s?.suggested_name_column ?? null);
  }

  async function commit() {
    if (!upload || !preview) return;
    setCommitting(true);
    try {
      const res = await api.post<CommitResult>(`/api/uploads/${upload.upload_id}/commit`, {
        ...body(), ...settings, save_emails: saveEmails, crawl_urls: crawl, delete_after: deleteAfter,
        name: `${crawl && !saveEmails ? "Crawl" : "Extract"}: ${upload.filename}`,
      });
      setResult(res);
      setStep("done");
      toast.success(crawl ? "Import saved — crawl started" : `Saved ${res.extract_job?.created ?? 0} new leads`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not process the file");
    } finally {
      setCommitting(false);
    }
  }

  async function discard() {
    if (upload) await api.del(`/api/uploads/${upload.upload_id}`).catch(() => undefined);
    toast.info("Uploaded file deleted from the server");
    reset();
  }

  // ------------------------------------------------------------------ steps
  if (step === "done" && result) {
    return (
      <div className="space-y-5">
        <Notice tone="green" title="Done">
          {result.extract_job && <p>Saved <b>{result.extract_job.created}</b> new leads from <b>{result.filename}</b> ({result.extract_job.duplicates} duplicates merged{result.extract_job.rejected ? `, ${result.extract_job.rejected} invalid/placeholder addresses ignored` : ""}).</p>}
          {result.crawl_job && <p>Crawling <b>{result.crawl_job.valid}</b> websites{result.crawl_job.invalid ? ` (${result.crawl_job.invalid} invalid URLs reported)` : ""}{result.crawl_job.duplicates ? `, ${result.crawl_job.duplicates} duplicates removed` : ""}.</p>}
          {result.file_deleted && <p>The uploaded file was deleted from the server.</p>}
        </Notice>
        {result.extract_job && <JobPanel jobId={result.extract_job.id} title="Extracted from file" />}
        {result.crawl_job && <JobPanel jobId={result.crawl_job.id} title="Website crawl" />}
        <Button variant="outline" icon={<RotateCcw className="h-4 w-4" />} onClick={reset}>Import another file</Button>
      </div>
    );
  }

  if (step === "map" && upload) {
    return (
      <Card>
        <CardHeader title={`Map columns — ${upload.filename}`} description="We guessed the website and name columns. Change them if the guess is wrong." action={<Button variant="ghost" size="sm" icon={<Trash2 className="h-4 w-4" />} onClick={discard}>Discard file</Button>} />
        <div className="space-y-5 p-5">
          {upload.sheets.length > 1 && (
            <Field label="Worksheet" className="max-w-sm">
              <Select value={sheet} onChange={(e) => chooseSheet(e.target.value)}>
                {upload.sheets.map((s) => <option key={s.name} value={s.name}>{s.name} ({fmtNum(s.rows)} rows)</option>)}
                <option value={ALL_SHEETS}>All sheets (automatic detection)</option>
              </Select>
            </Field>
          )}
          {activeSheet ? (
            <>
              {activeSheet.suggested_url_columns.length === 0 && <Notice tone="amber" title="No website column detected">Tick the column(s) that contain website links below, or continue to extract only the emails already in the file.</Notice>}
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="w-full">
                  <thead className="bg-slate-50"><tr><th className="table-th w-24">Website URLs</th><th className="table-th">Column</th><th className="table-th">Sample values</th><th className="table-th">Detected</th></tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {activeSheet.columns.map((c) => (
                      <tr key={c.index}>
                        <td className="table-td"><input type="checkbox" aria-label={`Use ${c.name} as a URL column`} className="h-4 w-4 rounded border-slate-300" checked={urlCols.includes(c.index)} onChange={(e) => setUrlCols((cols) => e.target.checked ? [...cols, c.index] : cols.filter((x) => x !== c.index))} /></td>
                        <td className="table-td font-medium">{c.name}</td>
                        <td className="table-td max-w-xs truncate text-slate-500">{c.sample.join(" · ") || "—"}</td>
                        <td className="table-td">
                          {c.url_ratio >= 0.5 && <Badge tone="green">{Math.round(c.url_ratio * 100)}% URLs</Badge>}
                          {c.email_ratio >= 0.5 && <Badge tone="blue">{Math.round(c.email_ratio * 100)}% emails</Badge>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Field label="Business name column (optional)" hint="Used as the business name for leads found on that row." className="max-w-sm">
                <Select value={nameCol ?? ""} onChange={(e) => setNameCol(e.target.value === "" ? null : Number(e.target.value))}>
                  <option value="">None</option>
                  {activeSheet.columns.map((c) => <option key={c.index} value={c.index}>{c.name}</option>)}
                </Select>
              </Field>
            </>
          ) : (
            <p className="text-sm text-slate-600">Every worksheet will be scanned and website/email columns detected automatically.</p>
          )}
          <div className="flex gap-2">
            <Button loading={previewing} onClick={() => runPreview(upload, body())}>Preview extraction</Button>
            <Button variant="outline" onClick={reset}>Start over</Button>
          </div>
        </div>
      </Card>
    );
  }

  if (step === "review" && preview && upload) {
    const nothing = preview.unique_emails === 0 && preview.urls_total === 0;
    return (
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Emails found" value={fmtNum(preview.emails_total)} icon={<Mail className="h-5 w-5" />} hint={preview.pages ? `${preview.pages} PDF pages` : undefined} />
          <Stat label="Unique emails" value={fmtNum(preview.unique_emails)} />
          <Stat label="Duplicates" value={fmtNum(preview.duplicate_emails)} hint="Merged, sources kept" />
          <Stat label="Websites found" value={fmtNum(preview.urls_total)} icon={<Globe className="h-5 w-5" />} />
        </div>

        {preview.needs_ocr && (
          <Notice tone="amber" title="This looks like a scanned PDF">
            There is no selectable text to read. Install the free <b>Tesseract OCR</b> program (see README → “Scanned PDFs”) and upload again, or run the PDF through OCR first. Nothing was guessed.
          </Notice>
        )}
        {preview.warnings.filter((w) => !w.includes("scanned")).length > 0 && (
          <Notice tone="amber" title="Heads-up"><ul className="list-disc pl-5">{preview.warnings.filter((w) => !w.includes("scanned")).map((w, i) => <li key={i}>{w}</li>)}</ul></Notice>
        )}

        {nothing ? (
          <Card><div className="p-8 text-center text-sm text-slate-600">No email addresses or website links were found in <b>{preview.filename}</b>.<div className="mt-4 flex justify-center gap-2">{upload.kind === "tabular" && <Button variant="outline" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => setStep("map")}>Change column mapping</Button>}<Button variant="outline" onClick={discard}>Discard file</Button></div></div></Card>
        ) : (
          <>
            {preview.emails.length > 0 && (
              <Card>
                <CardHeader title={`Email preview (${fmtNum(preview.unique_emails)} unique)`} description={preview.truncated ? "Showing the first 1,000 rows." : "Duplicates are merged; every source reference is kept."} />
                <div className="max-h-96 overflow-auto">
                  <table className="w-full">
                    <thead className="sticky top-0 bg-slate-50"><tr><th className="table-th">Email</th><th className="table-th">Business</th><th className="table-th">Seen</th><th className="table-th">Source</th></tr></thead>
                    <tbody className="divide-y divide-slate-100">
                      {preview.emails.map((e) => (
                        <tr key={e.email}>
                          <td className="table-td font-mono text-[13px]">{e.email}{e.original !== e.email && <span className="ml-2 text-xs text-slate-400">as written: {e.original}</span>}</td>
                          <td className="table-td">{e.business_name || <span className="text-slate-300">—</span>}</td>
                          <td className="table-td">{e.occurrences}×</td>
                          <td className="table-td text-xs text-slate-600">{e.sources.map((s, i) => <div key={i}>{[s.filename, s.sheet && `sheet ${s.sheet}`, s.row && `row ${s.row}`, s.page && `page ${s.page}`].filter(Boolean).join(" · ")}</div>)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
            {preview.urls.length > 0 && (
              <Card>
                <CardHeader title={`Websites found (${fmtNum(preview.urls_total)})`} description="These are normalised and checked again before any request is made. Private or unsafe addresses are blocked." />
                <div className="max-h-72 overflow-auto">
                  <table className="w-full">
                    <thead className="sticky top-0 bg-slate-50"><tr><th className="table-th">URL</th><th className="table-th">Business</th><th className="table-th">Location in file</th></tr></thead>
                    <tbody className="divide-y divide-slate-100">
                      {preview.urls.map((u, i) => (
                        <tr key={i}><td className="table-td break-all">{u.url}</td><td className="table-td">{u.business_name || <span className="text-slate-300">—</span>}</td><td className="table-td text-xs text-slate-600">{[u.sheet && `sheet ${u.sheet}`, u.row && `row ${u.row}`, u.page && `page ${u.page}`].filter(Boolean).join(" · ") || "—"}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            <Card>
              <CardHeader title="What should happen next?" />
              <div className="space-y-4 p-5">
                <Checkbox label={`Save ${fmtNum(preview.unique_emails)} unique email${preview.unique_emails === 1 ? "" : "s"} from this file as leads`} hint="Placeholder and invalid addresses are ignored automatically." checked={saveEmails} disabled={preview.unique_emails === 0} onChange={setSaveEmails} />
                <Checkbox label={`Crawl the ${fmtNum(preview.urls_total)} website${preview.urls_total === 1 ? "" : "s"} found in this file to look for more public emails`} hint="Runs as a background job. robots.txt is respected." checked={crawl} disabled={preview.urls_total === 0} onChange={setCrawl} />
                {crawl && (
                  <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-4">
                    <CrawlSettingsForm value={settings} onChange={setSettings} limits={limits} />
                  </div>
                )}
                <Field label="Tags for saved leads (optional)" className="max-w-sm"><Input value={settings.tags} onChange={(e) => setSettings({ ...settings, tags: e.target.value })} /></Field>
                <Checkbox label="Delete the uploaded file from the server afterwards" hint="Recommended. Extracted leads stay; the original document does not." checked={deleteAfter} onChange={setDeleteAfter} />
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button size="lg" loading={committing} disabled={!saveEmails && !crawl} icon={<FileUp className="h-5 w-5" />} onClick={commit}>
                    {crawl ? "Save & start crawl" : "Save leads"}
                  </Button>
                  {upload.kind === "tabular" && <Button size="lg" variant="outline" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => setStep("map")}>Back</Button>}
                  <Button size="lg" variant="ghost" icon={<Trash2 className="h-4 w-4" />} onClick={discard}>Discard</Button>
                </div>
              </div>
            </Card>
          </>
        )}
      </div>
    );
  }

  // step === "pick"
  return (
    <Card>
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); onFile(e.dataTransfer.files?.[0]); }}
        className={`m-4 flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-14 text-center transition-colors ${drag ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-slate-50/50"}`}
      >
        {uploading || previewing ? (
          <div className="flex items-center gap-3 text-sm text-slate-600"><Spinner /> {uploading ? "Uploading and checking the file…" : "Reading the file…"}</div>
        ) : (
          <>
            <div className="mb-3 rounded-full bg-brand-50 p-3 text-brand-600"><UploadCloud className="h-7 w-7" /></div>
            <p className="text-base font-semibold text-navy-900">{mode === "urls" ? "Drop a file containing website links" : "Drop a document to extract emails from"}</p>
            <p className="mt-1 max-w-xl text-sm text-slate-500">
              PDF, Word (.docx), Excel (.xlsx/.xls), CSV, TXT, Markdown, HTML, JSON or XML — up to {maxMb} MB. Legacy .doc files must be saved as .docx first.
            </p>
            <input ref={inputRef} type="file" accept={ACCEPT} className="sr-only" id={`file-${mode}`} onChange={(e) => onFile(e.target.files?.[0])} />
            <label htmlFor={`file-${mode}`} className="mt-5 inline-flex h-10 cursor-pointer items-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-medium text-white hover:bg-brand-700">
              <FileUp className="h-4 w-4" /> Choose a file
            </label>
            <p className="mt-4 flex items-center gap-1.5 text-xs text-slate-500"><AlertTriangle className="h-3.5 w-3.5" /> Files are only read, never executed, and are deleted after processing by default.</p>
          </>
        )}
      </div>
    </Card>
  );
}
