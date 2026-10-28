"use client";
import { FlaskConical, Play } from "lucide-react";
import React, { useState } from "react";
import { CrawlSettingsForm, useCrawlDefaults } from "@/components/CrawlSettingsForm";
import { JobPanel } from "@/components/JobPanel";
import { UploadWizard } from "@/components/UploadWizard";
import { Button, Card, CardHeader, Field, Input, Notice, PageHeader, Textarea } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";
import { splitLines } from "@/lib/format";
import type { JobCreated } from "@/lib/types";
import clsx from "clsx";

export default function WebsiteScraperPage() {
  const toast = useToast();
  const [tab, setTab] = useState<"paste" | "file">("paste");
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [settings, setSettings, limits] = useCrawlDefaults();
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const count = splitLines(text).length;

  async function start() {
    setBusy(true);
    try {
      const res = await api.post<JobCreated>("/api/jobs/website", { ...settings, name: name || undefined, urls: splitLines(text) });
      setJobId(res.job.id);
      const notes = [res.invalid_urls && `${res.invalid_urls} invalid`, res.duplicate_urls && `${res.duplicate_urls} duplicates removed`].filter(Boolean).join(", ");
      toast.success(`Job started for ${res.valid_urls} website${res.valid_urls === 1 ? "" : "s"}${notes ? ` (${notes})` : ""}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not start the job");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Website Scraper" description="Crawl company websites for publicly listed business emails. Each email is saved with the page it was found on and the time it was collected." />
      <div className="space-y-6">
        <Card>
          <div className="flex border-b border-slate-100 px-2 pt-2" role="tablist">
            {([["paste", "Paste URLs"], ["file", "Upload a file (CSV / Excel / TXT)"]] as const).map(([k, label]) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={clsx("rounded-t-lg px-4 py-2.5 text-sm font-medium", tab === k ? "border-b-2 border-brand-600 text-brand-700" : "text-slate-500 hover:text-slate-800")}>{label}</button>
            ))}
          </div>
          {tab === "paste" ? (
            <div className="space-y-5 p-5">
              <Field label={`Website URLs${count ? ` (${count} entered)` : ""}`} hint="One per line. Bare domains like acme-packaging.com are fine. Duplicates and invalid entries are reported, not silently dropped.">
                <Textarea rows={7} value={text} onChange={(e) => setText(e.target.value)} placeholder={"company1.com\ncompany2.com\nhttps://example.org/contact"} spellCheck={false} />
              </Field>
              <Field label="Job name (optional)" className="max-w-md"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Reno e-commerce brands" /></Field>
              <CrawlSettingsForm value={settings} onChange={setSettings} limits={limits} />
              <div className="flex flex-wrap items-center gap-3">
                <Button size="lg" icon={<Play className="h-5 w-5" />} loading={busy} disabled={count === 0} onClick={start}>Start scraping</Button>
                <Button variant="ghost" icon={<FlaskConical className="h-4 w-4" />} onClick={() => setText("http://127.0.0.1:8099/\nhttp://localhost:8099/")}>Fill with local test site</Button>
              </div>
              <Notice title="Testing without the internet?">
                Run <code className="rounded bg-white/70 px-1">python -m tests.fixture_server</code> in the backend folder and set <code className="rounded bg-white/70 px-1">TEST_FIXTURE_HOSTS=127.0.0.1:8099,localhost:8099</code> in <code className="rounded bg-white/70 px-1">backend/.env</code>. Leads from it are flagged <b>TEST DATA</b> and hidden from the dashboard and exports unless you opt in.
              </Notice>
            </div>
          ) : (
            <div className="p-2"><UploadWizard mode="urls" /></div>
          )}
        </Card>
        {jobId !== null && tab === "paste" && <JobPanel jobId={jobId} />}
      </div>
    </>
  );
}
