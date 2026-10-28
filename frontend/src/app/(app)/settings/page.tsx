"use client";
import { Plus, RotateCcw, Save, X } from "lucide-react";
import React, { useEffect, useState } from "react";
import { Button, Card, CardHeader, Checkbox, ErrorBlock, Field, Input, LoadingBlock, Notice, PageHeader } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";
import type { SettingsPayload } from "@/lib/types";

type Form = SettingsPayload["settings"];

export default function SettingsPage() {
  const toast = useToast();
  const [payload, setPayload] = useState<SettingsPayload | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [newCat, setNewCat] = useState("");

  async function load() {
    try {
      const p = await api.get<SettingsPayload>("/api/settings");
      setPayload(p);
      setForm(p.settings);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load settings");
    }
  }
  useEffect(() => { load(); }, []);

  async function save() {
    if (!form) return;
    setSaving(true);
    try {
      const p = await api.put<SettingsPayload>("/api/settings", form);
      setPayload(p);
      setForm(p.settings);
      toast.success("Settings saved");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not save settings");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <Card><ErrorBlock message={error} onRetry={load} /></Card>;
  if (!payload || !form) return <LoadingBlock label="Loading settings…" />;

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm({ ...form, [k]: v });
  const num = (k: "default_max_pages" | "default_max_depth" | "default_delay_seconds" | "default_concurrency", min: number, max: number) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const n = Number(e.target.value);
    set(k, (Number.isFinite(n) ? Math.min(Math.max(n, min), max) : min) as never);
  };
  const cats = form.category_keywords;
  const setCat = (name: string, kws: string[]) => set("category_keywords", { ...cats, [name]: kws });
  const limits = payload.server_limits;
  const limitRows: [string, React.ReactNode][] = [
    ["Environment", String(limits.environment)], ["Database", String(limits.database)],
    ["Max pages per site (server cap)", String(limits.max_pages_limit)], ["Max crawl depth (server cap)", String(limits.max_depth_limit)],
    ["Max URLs per job", String(limits.max_urls_per_job)], ["Max upload size", `${limits.max_upload_mb} MB`],
    ["Minimum delay per website", `${limits.min_domain_delay}s`], ["Global concurrent requests", String(limits.global_concurrency)],
    ["Request timeout", `${limits.request_timeout}s`], ["Obeys robots.txt", limits.respect_robots_txt ? "Yes" : "No"],
    ["Background worker", limits.embedded_worker ? "Embedded in API" : "Separate process"], ["OCR for scanned PDFs", limits.ocr_enabled ? "Enabled" : "Off"],
    ["User-Agent", <code key="ua" className="break-all text-xs">{String(limits.user_agent)}</code>],
  ];

  return (
    <>
      <PageHeader title="Settings" description="Defaults for new jobs and the keywords used to suggest lead categories." actions={<Button icon={<Save className="h-4 w-4" />} loading={saving} onClick={save}>Save settings</Button>} />
      <div className="space-y-6">
        <Card>
          <CardHeader title="Crawl defaults" description="Pre-filled on the scraper pages. You can still change them per job." />
          <div className="space-y-4 p-5">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Max pages per website"><Input type="number" min={1} max={Number(limits.max_pages_limit)} value={form.default_max_pages} onChange={num("default_max_pages", 1, Number(limits.max_pages_limit))} /></Field>
              <Field label="Crawl depth"><Input type="number" min={0} max={Number(limits.max_depth_limit)} value={form.default_max_depth} onChange={num("default_max_depth", 0, Number(limits.max_depth_limit))} /></Field>
              <Field label="Delay between requests (s)"><Input type="number" step="0.5" min={Number(limits.min_domain_delay)} max={30} value={form.default_delay_seconds} onChange={num("default_delay_seconds", Number(limits.min_domain_delay), 30)} /></Field>
              <Field label="Websites in parallel"><Input type="number" min={1} max={Number(limits.max_job_concurrency)} value={form.default_concurrency} onChange={num("default_concurrency", 1, Number(limits.max_job_concurrency))} /></Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Checkbox label="Check email domains (DNS/MX) when a job finishes" hint="Free DNS lookups only; no mail server is contacted." checked={form.default_validate_mx} onChange={(v) => set("default_validate_mx", v)} />
              <Field label="Default tags"><Input value={form.default_tags} onChange={(e) => set("default_tags", e.target.value)} placeholder="optional" /></Field>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Category keywords"
            description="A lead is only assigned a category when its pages contain at least two different keywords for it (or one repeated three times). Edit, add or remove categories freely."
            action={<Button size="sm" variant="outline" icon={<RotateCcw className="h-4 w-4" />} onClick={() => set("category_keywords", payload.default_category_keywords)}>Reset to defaults</Button>}
          />
          <div className="space-y-5 p-5">
            {Object.entries(cats).map(([name, kws]) => (
              <div key={name} className="rounded-lg border border-slate-200 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <p className="font-medium text-navy-900">{name}</p>
                  <Button size="sm" variant="ghost" icon={<X className="h-4 w-4" />} aria-label={`Remove ${name}`} onClick={() => { const c = { ...cats }; delete c[name]; set("category_keywords", c); }} />
                </div>
                <Field label="Keywords (comma separated)">
                  <Input defaultValue={kws.join(", ")} key={kws.join("|")} onBlur={(e) => setCat(name, e.target.value.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean))} />
                </Field>
              </div>
            ))}
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); const n = newCat.trim(); if (n && !(n in cats)) { setCat(n, []); setNewCat(""); } }}>
              <Field label="Add a category" className="w-72"><Input value={newCat} onChange={(e) => setNewCat(e.target.value)} placeholder="e.g. Sustainable packaging" /></Field>
              <Button type="submit" variant="outline" icon={<Plus className="h-4 w-4" />} disabled={!newCat.trim()}>Add</Button>
            </form>
          </div>
        </Card>

        <Card>
          <CardHeader title="Server limits" description="Set by environment variables in backend/.env — shown here for reference." />
          <dl className="divide-y divide-slate-100">
            {limitRows.map(([k, v]) => (
              <div key={k} className="grid gap-1 px-5 py-2.5 text-sm sm:grid-cols-3"><dt className="text-slate-500">{k}</dt><dd className="sm:col-span-2 text-slate-800">{v}</dd></div>
            ))}
          </dl>
          <div className="p-5 pt-0">
            <Notice tone="amber" title="No login is built in">Anyone who can reach this app can see and export its data. Keep it on localhost, or put it behind your host’s access controls before exposing it publicly.</Notice>
          </div>
        </Card>
      </div>
    </>
  );
}
