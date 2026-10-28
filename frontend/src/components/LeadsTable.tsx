"use client";
import { ArrowDown, ArrowUp, ArrowUpDown, ExternalLink, Filter, Plus, RefreshCw, Search, ShieldCheck, Sparkles, Tag, Trash2, Users, X } from "lucide-react";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ExportMenu } from "@/components/ExportMenu";
import { LeadDrawer } from "@/components/LeadDrawer";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorBlock, Field, Input, LoadingBlock, Select, VerificationBadge } from "@/components/ui";
import { ConfirmDialog, Modal } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, qs } from "@/lib/api";
import { fmtDate, fmtNum } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import type { FilterOptions, Lead, LeadFilters, Page } from "@/lib/types";

const COLUMNS: { key: string; label: string; sort?: string }[] = [
  { key: "business_name", label: "Business Name", sort: "business_name" },
  { key: "email", label: "Email Address", sort: "email" },
  { key: "website", label: "Website", sort: "website" },
  { key: "contact_page_url", label: "Contact Page URL" },
  { key: "category", label: "Business Category", sort: "category" },
  { key: "city", label: "City", sort: "city" },
  { key: "state", label: "State", sort: "state" },
  { key: "country", label: "Country", sort: "country" },
  { key: "phone", label: "Phone" },
  { key: "source_type", label: "Source Type", sort: "source_type" },
  { key: "source_filename", label: "Source Filename", sort: "source_filename" },
  { key: "collected_at", label: "Collection Date", sort: "collected_at" },
  { key: "verification_status", label: "Verification Status", sort: "verification_status" },
  { key: "notes", label: "Notes" },
];

export function toApiFilters(f: LeadFilters): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  Object.entries(f).forEach(([k, v]) => {
    if (v === undefined || v === "" || v === null) return;
    if (k === "has_website" || k === "role_based") out[k] = v === "true";
    else out[k] = v;
  });
  return out;
}

const blank = <span className="text-slate-300">—</span>;

function ExtLink({ href, label }: { href: string | null; label?: string }) {
  if (!href) return blank;
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" onClick={(e) => e.stopPropagation()} className="inline-flex max-w-[16rem] items-center gap-1 truncate text-brand-700 hover:underline">
      <span className="truncate">{label ?? href.replace(/^https?:\/\//, "")}</span>
      <ExternalLink className="h-3 w-3 shrink-0" />
    </a>
  );
}

export function LeadsTable({ fixedFilters, refreshKey = 0, showFilters = true, pageSize: initialPageSize = 25, exportScopeJobId, emptyHint }: {
  fixedFilters?: Partial<LeadFilters>;
  refreshKey?: number;
  showFilters?: boolean;
  pageSize?: number;
  exportScopeJobId?: number;
  emptyHint?: React.ReactNode;
}) {
  const toast = useToast();
  const [filters, setFilters] = useState<LeadFilters>({});
  const [showPanel, setShowPanel] = useState(false);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialPageSize);
  const [sortBy, setSortBy] = useState("collected_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [data, setData] = useState<Page<Lead> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [tagOpen, setTagOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const fixedKey = JSON.stringify(fixedFilters ?? {}); // compare by value so parents can pass inline objects
  const combined: LeadFilters = useMemo(() => ({ ...filters, ...(JSON.parse(fixedKey) as Partial<LeadFilters>), q: debouncedSearch || undefined }), [filters, fixedKey, debouncedSearch]);
  const includeTest = !!combined.include_test;

  useEffect(() => setPage(1), [combined, pageSize]); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Page<Lead>>(`/api/leads${qs({ ...(combined as Record<string, string | number | boolean>), page, page_size: pageSize, sort_by: sortBy, sort_dir: sortDir })}`);
      setData(res);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load leads");
    } finally {
      setLoading(false);
    }
  }, [combined, page, pageSize, sortBy, sortDir]);

  useEffect(() => {
    load();
  }, [load, refreshKey, tick]);

  useEffect(() => {
    api.get<FilterOptions>(`/api/leads/filters${qs({ include_test: includeTest })}`).then(setOptions, () => undefined);
  }, [includeTest, refreshKey, tick]);

  const rows = data?.items ?? [];
  const pageIds = rows.map((r) => r.id);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const activeFilterCount = Object.entries(filters).filter(([k, v]) => v !== undefined && v !== "" && k !== "keyword_mode" && !(k === "include_test" && !v)).length;

  function toggleSort(col?: string) {
    if (!col) return;
    if (sortBy === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortBy(col);
      setSortDir("asc");
    }
  }

  async function selectAllMatching() {
    if (!data) return;
    setBusy(true);
    try {
      const ids: number[] = [];
      for (let p = 1; ids.length < data.total && p <= 100; p++) {
        const res = await api.get<Page<Lead>>(`/api/leads${qs({ ...(combined as Record<string, string | number | boolean>), page: p, page_size: 500, sort_by: "id" })}`);
        ids.push(...res.items.map((l) => l.id));
        if (res.items.length === 0) break;
      }
      setSelected(new Set(ids));
      toast.info(`Selected all ${fmtNum(ids.length)} matching leads`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not select all leads");
    } finally {
      setBusy(false);
    }
  }

  async function bulkDelete() {
    setBusy(true);
    try {
      const res = await api.post<{ deleted: number }>("/api/leads/bulk-delete", { ids: [...selected] });
      toast.success(`Deleted ${fmtNum(res.deleted)} lead${res.deleted === 1 ? "" : "s"}`);
      setSelected(new Set());
      setConfirmDelete(false);
      setTick((t) => t + 1);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  async function runAction(path: string, body: object, okMsg: (r: any) => string) {
    setBusy(true);
    try {
      toast.success(okMsg(await api.post(path, body)));
      setTick((t) => t + 1);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  const exportChoices = useMemo(() => {
    const apiFilters = toApiFilters(combined);
    if (exportScopeJobId) {
      return [
        { label: "Export this job's results", description: "Leads, unique emails, failed URLs and summary", body: { scope: "job", job_id: exportScopeJobId } },
        { label: "Export selected leads", description: selected.size ? `${selected.size} selected` : "Select rows first", body: { scope: "selected", ids: [...selected], include_test: includeTest }, disabled: selected.size === 0 },
        { label: "Unique email addresses only", body: { scope: "job", job_id: exportScopeJobId, format: "unique_emails" } },
        { label: "Emails grouped by domain", body: { scope: "job", job_id: exportScopeJobId, format: "by_domain" } },
      ];
    }
    return [
      { label: "Export all leads", description: includeTest ? "Includes sample/test data" : "Excludes sample/test data", body: { scope: "all", include_test: includeTest } },
      { label: "Export filtered leads", description: "Whatever the table currently shows", body: { scope: "filtered", filters: apiFilters, include_test: includeTest } },
      { label: "Export selected leads", description: selected.size ? `${selected.size} selected` : "Select rows first", body: { scope: "selected", ids: [...selected], include_test: includeTest }, disabled: selected.size === 0 },
      { label: "Unique email addresses only", description: "Filtered, one row per email", body: { scope: "filtered", filters: apiFilters, format: "unique_emails", include_test: includeTest } },
      { label: "Emails grouped by domain", description: "Filtered, sorted by email domain", body: { scope: "filtered", filters: apiFilters, format: "by_domain", include_test: includeTest } },
    ];
  }, [combined, selected, includeTest, exportScopeJobId]);

  const setF = (k: keyof LeadFilters, v: string | boolean | undefined) => setFilters((f) => ({ ...f, [k]: v === "" ? undefined : v }));
  const opt = (list: string[] | undefined) => (list ?? []).map((x) => <option key={x} value={x}>{x}</option>);

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
        <div className="relative min-w-[14rem] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input className="pl-9" placeholder="Search email, business, website, notes…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search leads" />
        </div>
        {showFilters && (
          <Button variant="outline" icon={<Filter className="h-4 w-4" />} onClick={() => setShowPanel((s) => !s)}>
            Filters {activeFilterCount > 0 && <Badge tone="blue">{activeFilterCount}</Badge>}
          </Button>
        )}
        <Button variant="outline" icon={<Plus className="h-4 w-4" />} onClick={() => setAddOpen(true)}>Add lead</Button>
        <Button variant="ghost" aria-label="Refresh" icon={<RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />} onClick={() => setTick((t) => t + 1)} />
        <ExportMenu choices={exportChoices} />
      </div>

      {showFilters && showPanel && (
        <div className="grid gap-3 border-b border-slate-100 bg-slate-50/60 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Business category"><Select value={filters.category ?? ""} onChange={(e) => setF("category", e.target.value)}><option value="">All</option>{opt(options?.categories)}</Select></Field>
          <Field label="State"><Select value={filters.state ?? ""} onChange={(e) => setF("state", e.target.value)}><option value="">All</option>{opt(options?.states)}</Select></Field>
          <Field label="City"><Select value={filters.city ?? ""} onChange={(e) => setF("city", e.target.value)}><option value="">All</option>{opt(options?.cities)}</Select></Field>
          <Field label="Email domain"><Select value={filters.domain ?? ""} onChange={(e) => setF("domain", e.target.value)}><option value="">All</option>{opt(options?.domains)}</Select></Field>
          <Field label="Source type"><Select value={filters.source_type ?? ""} onChange={(e) => setF("source_type", e.target.value)}><option value="">All</option>{opt(options?.source_types)}</Select></Field>
          <Field label="Verification status"><Select value={filters.verification_status ?? ""} onChange={(e) => setF("verification_status", e.target.value)}><option value="">All</option>{opt(options?.verification_statuses)}</Select></Field>
          <Field label="Collected from"><Input type="date" value={filters.date_from ?? ""} onChange={(e) => setF("date_from", e.target.value)} /></Field>
          <Field label="Collected to"><Input type="date" value={filters.date_to ?? ""} onChange={(e) => setF("date_to", e.target.value)} /></Field>
          <Field label="Website"><Select value={filters.has_website ?? ""} onChange={(e) => setF("has_website", e.target.value)}><option value="">With or without</option><option value="true">Has a website</option><option value="false">No website</option></Select></Field>
          <Field label="Address type"><Select value={filters.role_based ?? ""} onChange={(e) => setF("role_based", e.target.value)}><option value="">All</option><option value="true">Role-based (info@, sales@…)</option><option value="false">Personal / other</option></Select></Field>
          <Field label="Tag"><Input value={filters.tag ?? ""} onChange={(e) => setF("tag", e.target.value)} placeholder="e.g. hot" /></Field>
          <div className="flex items-end"><Checkbox label="Show sample / test data" checked={!!filters.include_test} onChange={(v) => setF("include_test", v)} /></div>
          <div className="sm:col-span-2 lg:col-span-3">
            <Field label="Prospect keyword search" hint="Comma-separated terms matched against saved page text, e.g. “custom packaging, shipping boxes”.">
              <Input value={filters.keywords ?? ""} onChange={(e) => setF("keywords", e.target.value)} placeholder="custom packaging, ecommerce brand, food manufacturer" />
            </Field>
          </div>
          <Field label="Keyword match"><Select value={filters.keyword_mode ?? "any"} onChange={(e) => setF("keyword_mode", e.target.value)}><option value="any">Any term</option><option value="all">All terms</option></Select></Field>
          <div className="flex items-end sm:col-span-2 lg:col-span-4">
            <Button variant="ghost" size="sm" icon={<X className="h-4 w-4" />} onClick={() => setFilters({})}>Clear all filters</Button>
          </div>
        </div>
      )}

      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-brand-100 bg-brand-50 px-4 py-2.5 text-sm">
          <span className="font-medium text-navy-900">{fmtNum(selected.size)} selected</span>
          {allOnPage && data && data.total > selected.size && <button className="text-brand-700 underline" onClick={selectAllMatching}>Select all {fmtNum(data.total)} matching</button>}
          <span className="mx-1 hidden h-4 w-px bg-brand-200 sm:block" />
          <Button size="sm" variant="outline" icon={<Tag className="h-4 w-4" />} onClick={() => setTagOpen(true)}>Tag</Button>
          <Button size="sm" variant="outline" icon={<ShieldCheck className="h-4 w-4" />} loading={busy} onClick={() => runAction("/api/leads/validate", { ids: [...selected].slice(0, 500), only_unverified: false }, (r) => `Checked ${r.checked} addresses (DNS only): ${Object.entries(r.by_status).map(([k, v]) => `${v} ${k}`).join(", ") || "none"}`)}>Check email domains</Button>
          <Button size="sm" variant="outline" icon={<Sparkles className="h-4 w-4" />} loading={busy} onClick={() => runAction("/api/leads/classify", { ids: [...selected] }, (r) => `Suggested categories for ${r.classified} leads`)}>Suggest categories</Button>
          <Button size="sm" variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirmDelete(true)}>Delete</Button>
          <button className="ml-auto text-slate-500 hover:text-slate-800" onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      )}

      {error ? (
        <ErrorBlock message={error} onRetry={() => setTick((t) => t + 1)} />
      ) : loading && !data ? (
        <LoadingBlock label="Loading leads…" />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Users className="h-6 w-6" />}
          title={data && Object.keys(combined).filter((k) => combined[k as keyof LeadFilters] !== undefined).length > (includeTest ? 1 : 0) ? "No leads match these filters" : "No leads yet"}
          description={emptyHint ?? "Run a website scrape, directory scrape or file import and the leads will appear here."}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-[1500px] w-full border-collapse">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className="w-10 px-3 py-2.5"><input type="checkbox" aria-label="Select all rows on this page" className="h-4 w-4 rounded border-slate-300" checked={allOnPage} onChange={() => setSelected((s) => { const n = new Set(s); allOnPage ? pageIds.forEach((id) => n.delete(id)) : pageIds.forEach((id) => n.add(id)); return n; })} /></th>
                {COLUMNS.map((c) => (
                  <th key={c.key} className="table-th" aria-sort={c.sort && sortBy === c.sort ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    {c.sort ? (
                      <button className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-navy-900" onClick={() => toggleSort(c.sort)}>
                        {c.label}
                        {sortBy === c.sort ? (sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />) : <ArrowUpDown className="h-3 w-3 opacity-40" />}
                      </button>
                    ) : c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className={`divide-y divide-slate-100 ${loading ? "opacity-60" : ""}`}>
              {rows.map((l) => (
                <tr key={l.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setOpenId(l.id)}>
                  <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" aria-label={`Select ${l.email}`} className="h-4 w-4 rounded border-slate-300" checked={selected.has(l.id)} onChange={() => setSelected((s) => { const n = new Set(s); n.has(l.id) ? n.delete(l.id) : n.add(l.id); return n; })} />
                  </td>
                  <td className="table-td max-w-[14rem] font-medium text-navy-900"><div className="truncate">{l.business_name || blank}</div>{l.is_test && <Badge tone="amber">TEST</Badge>}</td>
                  <td className="table-td whitespace-nowrap">
                    <span className="font-mono text-[13px]">{l.email}</span>
                    {l.is_role_based && <Badge tone="violet" className="ml-1.5">role</Badge>}
                    {l.matched_keywords && l.matched_keywords.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{l.matched_keywords.map((k) => <Badge key={k} tone="green">{k}</Badge>)}</div>}
                  </td>
                  <td className="table-td"><ExtLink href={l.website} /></td>
                  <td className="table-td"><ExtLink href={l.contact_page_url} label="Contact page" /></td>
                  <td className="table-td whitespace-nowrap">{l.category ? <span title={l.category_source === "auto" ? "Suggested from page text — click the row to see the evidence" : "Set manually"}>{l.category}{l.category_source === "auto" && <span className="ml-1 text-[10px] uppercase text-slate-400">auto</span>}</span> : blank}</td>
                  <td className="table-td">{l.city || blank}</td>
                  <td className="table-td whitespace-nowrap">{l.state || blank}</td>
                  <td className="table-td whitespace-nowrap">{l.country || blank}</td>
                  <td className="table-td whitespace-nowrap">{l.phone || blank}</td>
                  <td className="table-td"><Badge>{l.source_type}</Badge></td>
                  <td className="table-td max-w-[12rem] truncate">{l.source_filename || blank}</td>
                  <td className="table-td whitespace-nowrap text-xs">{fmtDate(l.collected_at)}</td>
                  <td className="table-td"><VerificationBadge status={l.verification_status} /></td>
                  <td className="table-td max-w-[14rem] truncate text-slate-500">{l.notes || blank}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-4 py-3 text-sm text-slate-600">
          <span>{fmtNum((page - 1) * pageSize + 1)}–{fmtNum(Math.min(page * pageSize, data.total))} of {fmtNum(data.total)} leads</span>
          <div className="flex items-center gap-2">
            <Select className="!h-8 w-auto text-xs" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))} aria-label="Rows per page">
              {[10, 25, 50, 100, 250].map((n) => <option key={n} value={n}>{n} / page</option>)}
            </Select>
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
            <span className="tabular-nums">Page {page} / {totalPages}</span>
            <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        </div>
      )}

      <LeadDrawer leadId={openId} categories={options?.categories ?? []} statuses={options?.verification_statuses ?? []} onClose={() => setOpenId(null)} onChanged={() => setTick((t) => t + 1)} />
      <ConfirmDialog open={confirmDelete} danger title={`Delete ${selected.size} lead${selected.size === 1 ? "" : "s"}?`} confirmLabel="Delete" loading={busy} message="The selected leads and their source records will be permanently removed. This cannot be undone." onConfirm={bulkDelete} onCancel={() => setConfirmDelete(false)} />
      <TagModal open={tagOpen} count={selected.size} onClose={() => setTagOpen(false)} onSubmit={async (tags, mode) => { await runAction("/api/leads/bulk-tag", { ids: [...selected], tags, mode }, (r) => `Updated tags on ${r.updated} leads`); setTagOpen(false); }} />
      <AddLeadModal open={addOpen} onClose={() => setAddOpen(false)} onAdded={() => setTick((t) => t + 1)} />
    </Card>
  );
}

function TagModal({ open, count, onClose, onSubmit }: { open: boolean; count: number; onClose: () => void; onSubmit: (tags: string[], mode: string) => Promise<void> }) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState("add");
  const tags = text.split(",").map((t) => t.trim()).filter(Boolean);
  return (
    <Modal open={open} onClose={onClose} title={`Tag ${count} lead${count === 1 ? "" : "s"}`} footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button disabled={tags.length === 0} onClick={() => onSubmit(tags, mode)}>Apply</Button></>}>
      <div className="space-y-4">
        <Field label="Tags" hint="Comma separated, e.g. hot, q4-outreach"><Input value={text} onChange={(e) => setText(e.target.value)} autoFocus /></Field>
        <Field label="Action"><Select value={mode} onChange={(e) => setMode(e.target.value)}><option value="add">Add these tags</option><option value="remove">Remove these tags</option><option value="set">Replace all tags with these</option></Select></Field>
      </div>
    </Modal>
  );
}

function AddLeadModal({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ email: "", business_name: "", website: "", phone: "", notes: "" });
  const [saving, setSaving] = useState(false);
  async function submit() {
    setSaving(true);
    try {
      await api.post("/api/leads", f);
      toast.success("Lead added");
      setF({ email: "", business_name: "", website: "", phone: "", notes: "" });
      onAdded();
      onClose();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not add the lead");
    } finally {
      setSaving(false);
    }
  }
  const bind = (k: keyof typeof f) => ({ value: f[k], onChange: (e: React.ChangeEvent<HTMLInputElement>) => setF((s) => ({ ...s, [k]: e.target.value })) });
  return (
    <Modal open={open} onClose={onClose} title="Add a lead manually" footer={<><Button variant="outline" onClick={onClose}>Cancel</Button><Button loading={saving} disabled={!f.email.includes("@")} onClick={submit}>Add lead</Button></>}>
      <div className="space-y-3">
        <Field label="Email address *"><Input type="email" {...bind("email")} autoFocus /></Field>
        <Field label="Business name"><Input {...bind("business_name")} /></Field>
        <Field label="Website"><Input {...bind("website")} /></Field>
        <Field label="Phone"><Input {...bind("phone")} /></Field>
        <Field label="Notes"><Input {...bind("notes")} /></Field>
      </div>
    </Modal>
  );
}
