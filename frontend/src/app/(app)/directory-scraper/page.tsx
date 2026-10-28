"use client";
import { FlaskConical, Play } from "lucide-react";
import React, { useState } from "react";
import { JobPanel } from "@/components/JobPanel";
import { useCrawlDefaults } from "@/components/CrawlSettingsForm";
import { Button, Card, Checkbox, Field, Input, Notice, PageHeader, Textarea } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";
import { splitLines } from "@/lib/format";
import type { JobCreated } from "@/lib/types";

export default function DirectoryScraperPage() {
  const toast = useToast();
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [maxPages, setMaxPages] = useState(5);
  const [delay, setDelay] = useState(1.5);
  const [crawlSites, setCrawlSites] = useState(false);
  const [maxSites, setMaxSites] = useState(25);
  const [validate, setValidate] = useState(true);
  const [settings] = useCrawlDefaults();
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const urls = splitLines(text);

  async function start() {
    setBusy(true);
    try {
      const res = await api.post<JobCreated>("/api/jobs/directory", { name: name || undefined, urls, max_pages: maxPages, delay, crawl_websites: crawlSites, max_sites: maxSites, validate_mx: validate, tags: settings.tags });
      setJobId(res.job.id);
      toast.success(`Directory job started (${res.valid_urls} director${res.valid_urls === 1 ? "y" : "ies"})`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not start the job");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Directory Scraper" description="Extract business names, websites, emails, phone numbers and addresses from public directory listing pages — one page layout at a time." />
      <div className="space-y-6">
        <Card>
          <div className="space-y-5 p-5">
            <Field label={`Public directory URLs${urls.length ? ` (${urls.length})` : ""}`} hint="Paste the URL of a listing page (one per line). Pagination is followed when a “next” link or ?page=N is present.">
              <Textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="https://directory.example.com/packaging-suppliers/" spellCheck={false} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Job name (optional)"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <Field label="Max pages per directory" hint="1–100"><Input type="number" min={1} max={100} value={maxPages} onChange={(e) => setMaxPages(Math.min(100, Math.max(1, Number(e.target.value) || 1)))} /></Field>
              <Field label="Delay between pages (s)" hint="Minimum 0.5"><Input type="number" step="0.5" min={0.5} max={30} value={delay} onChange={(e) => setDelay(Math.min(30, Math.max(0.5, Number(e.target.value) || 1.5)))} /></Field>
            </div>
            <div className="space-y-3">
              <Checkbox label="Also visit each business’s own website when the directory shows no email" hint="Uses the website crawler (same-site only, up to 6 pages each)." checked={crawlSites} onChange={setCrawlSites} />
              {crawlSites && <Field label="Maximum websites to visit per directory" className="max-w-xs"><Input type="number" min={1} max={200} value={maxSites} onChange={(e) => setMaxSites(Math.min(200, Math.max(1, Number(e.target.value) || 1)))} /></Field>}
              <Checkbox label="Check email domains (DNS/MX) when finished" checked={validate} onChange={setValidate} />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button size="lg" icon={<Play className="h-5 w-5" />} loading={busy} disabled={urls.length === 0} onClick={start}>Start directory scrape</Button>
              <Button variant="ghost" icon={<FlaskConical className="h-4 w-4" />} onClick={() => setText("http://127.0.0.1:8099/directory/")}>Fill with local test directory</Button>
            </div>
            <Notice tone="amber" title="What this will not do">
              Directories that need a login, payment or CAPTCHA, that block bots (HTTP 401/403/429), or whose robots.txt disallows automated access are <b>skipped and explained</b> in the job results — never bypassed. The generic parser handles common “card” layouts and schema.org data; unusual layouts may need a custom adapter (see README).
            </Notice>
          </div>
        </Card>
        {jobId !== null && <JobPanel jobId={jobId} />}
      </div>
    </>
  );
}
