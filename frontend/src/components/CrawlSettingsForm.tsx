"use client";
import React, { useEffect, useState } from "react";
import { Checkbox, Field, Input, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import type { CrawlSettings, SettingsPayload } from "@/lib/types";

export const FALLBACK_SETTINGS: CrawlSettings = {
  max_pages: 10, max_depth: 2, delay: 1, concurrency: 3, follow_external: false, keywords: [], keyword_filter: false, validate_mx: true, tags: "",
};

/** Loads the user's saved defaults (Settings page) once. */
export function useCrawlDefaults(): [CrawlSettings, React.Dispatch<React.SetStateAction<CrawlSettings>>, SettingsPayload["server_limits"] | null] {
  const [value, setValue] = useState<CrawlSettings>(FALLBACK_SETTINGS);
  const [limits, setLimits] = useState<SettingsPayload["server_limits"] | null>(null);
  useEffect(() => {
    api.get<SettingsPayload>("/api/settings").then(
      (s) => {
        setLimits(s.server_limits);
        setValue((v) => ({ ...v, max_pages: s.settings.default_max_pages, max_depth: s.settings.default_max_depth, delay: s.settings.default_delay_seconds, concurrency: s.settings.default_concurrency, validate_mx: s.settings.default_validate_mx, tags: s.settings.default_tags }));
      },
      () => undefined, // the page still works with the built-in defaults if settings can't be read
    );
  }, []);
  return [value, setValue, limits];
}

export function CrawlSettingsForm({ value, onChange, limits, showKeywords = true }: {
  value: CrawlSettings;
  onChange: (v: CrawlSettings) => void;
  limits?: SettingsPayload["server_limits"] | null;
  showKeywords?: boolean;
}) {
  const num = (k: keyof CrawlSettings, min: number, max: number) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const n = Number(e.target.value);
    onChange({ ...value, [k]: Number.isFinite(n) ? Math.min(Math.max(n, min), max) : min });
  };
  const maxPages = Number(limits?.max_pages_limit ?? 100);
  const maxDepth = Number(limits?.max_depth_limit ?? 4);
  const maxConc = Number(limits?.max_job_concurrency ?? 10);
  const minDelay = Number(limits?.min_domain_delay ?? 0.5);
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Max pages per website" hint={`1–${maxPages}`}><Input type="number" min={1} max={maxPages} value={value.max_pages} onChange={num("max_pages", 1, maxPages)} /></Field>
        <Field label="Crawl depth" hint={`0 = homepage only (max ${maxDepth})`}><Input type="number" min={0} max={maxDepth} value={value.max_depth} onChange={num("max_depth", 0, maxDepth)} /></Field>
        <Field label="Delay between requests (s)" hint={`Per website, min ${minDelay}s`}><Input type="number" step="0.5" min={minDelay} max={30} value={value.delay} onChange={num("delay", minDelay, 30)} /></Field>
        <Field label="Websites in parallel" hint={`1–${maxConc}`}><Input type="number" min={1} max={maxConc} value={value.concurrency} onChange={num("concurrency", 1, maxConc)} /></Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Checkbox label="Follow links to other websites" hint="Off by default. When off, only the same site is crawled." checked={value.follow_external} onChange={(v) => onChange({ ...value, follow_external: v })} />
        <Checkbox label="Check email domains (DNS/MX) when finished" hint="Free DNS lookup only. It never contacts a mail server." checked={value.validate_mx} onChange={(v) => onChange({ ...value, validate_mx: v })} />
      </div>
      {showKeywords && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Prospect keywords (optional)" hint="One per line or comma-separated, e.g. “custom packaging”. Matches are recorded in each lead’s notes.">
            <Textarea rows={3} className="font-sans" value={value.keywords.join("\n")} onChange={(e) => onChange({ ...value, keywords: e.target.value.split(/[\n,]/).map((s) => s.trim()).filter(Boolean) })} placeholder={"custom packaging\nshipping boxes"} />
          </Field>
          <div className="space-y-4">
            <Checkbox label="Only keep websites that match a keyword" hint="Sites without any keyword on their pages are skipped (their emails are discarded)." checked={value.keyword_filter} disabled={value.keywords.length === 0} onChange={(v) => onChange({ ...value, keyword_filter: v })} />
            <Field label="Tags for these leads (optional)"><Input value={value.tags} onChange={(e) => onChange({ ...value, tags: e.target.value })} placeholder="e.g. october-batch" /></Field>
          </div>
        </div>
      )}
    </div>
  );
}
