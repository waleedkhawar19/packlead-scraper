"use client";
import { ExternalLink, Trash2 } from "lucide-react";
import React, { useEffect, useState } from "react";
import { Badge, Button, ErrorBlock, Field, Input, LoadingBlock, Select, Textarea, VerificationBadge } from "@/components/ui";
import { ConfirmDialog, Modal } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { LeadDetail } from "@/lib/types";

const FIELDS = ["business_name", "website", "contact_page_url", "category", "city", "state", "country", "address", "phone", "tags", "notes", "verification_status"] as const;
type FormState = Record<(typeof FIELDS)[number], string>;

export function LeadDrawer({ leadId, categories, statuses, onClose, onChanged }: { leadId: number | null; categories: string[]; statuses: string[]; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (leadId === null) return;
    setLead(null);
    setForm(null);
    setError(null);
    api.get<LeadDetail>(`/api/leads/${leadId}`).then(
      (l) => {
        setLead(l);
        setForm(Object.fromEntries(FIELDS.map((f) => [f, (l[f as keyof LeadDetail] as string | null) ?? ""])) as FormState);
      },
      (e) => setError(e instanceof ApiError ? e.message : "Could not load this lead"),
    );
  }, [leadId]);

  async function save() {
    if (!lead || !form) return;
    setSaving(true);
    try {
      await api.patch(`/api/leads/${lead.id}`, form);
      toast.success("Lead updated");
      onChanged();
      onClose();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not save the lead");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!lead) return;
    try {
      await api.post("/api/leads/bulk-delete", { ids: [lead.id] });
      toast.success("Lead deleted");
      setConfirmDelete(false);
      onChanged();
      onClose();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not delete the lead");
    }
  }

  const set = (k: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setForm((f) => (f ? { ...f, [k]: e.target.value } : f));

  return (
    <>
      <Modal
        open={leadId !== null}
        onClose={onClose}
        wide
        title={lead ? lead.email : "Lead"}
        footer={
          lead && form ? (
            <>
              <Button variant="ghost" className="mr-auto text-red-600 hover:bg-red-50" icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirmDelete(true)}>Delete</Button>
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button onClick={save} loading={saving}>Save changes</Button>
            </>
          ) : undefined
        }
      >
        {error && <ErrorBlock message={error} />}
        {!error && (!lead || !form) && <LoadingBlock />}
        {lead && form && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <VerificationBadge status={lead.verification_status} />
              {lead.is_role_based && <Badge tone="violet">Role-based address</Badge>}
              {lead.is_test && <Badge tone="amber">TEST DATA</Badge>}
              <Badge>{lead.source_type}</Badge>
              <span className="text-xs text-slate-500">Collected {fmtDate(lead.collected_at)}</span>
            </div>
            {lead.verification_detail && <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">{lead.verification_detail}</p>}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Business name"><Input value={form.business_name} onChange={set("business_name")} /></Field>
              <Field label="Phone"><Input value={form.phone} onChange={set("phone")} /></Field>
              <Field label="Website"><Input value={form.website} onChange={set("website")} /></Field>
              <Field label="Contact page URL"><Input value={form.contact_page_url} onChange={set("contact_page_url")} /></Field>
              <Field label="Business category" hint={lead.category_source === "auto" ? "Suggested automatically — edit to override." : lead.category_source === "manual" ? "Set by you." : undefined}>
                <Input list="category-options" value={form.category} onChange={set("category")} />
                <datalist id="category-options">{categories.map((c) => <option key={c} value={c} />)}</datalist>
              </Field>
              <Field label="Verification status">
                <Select value={form.verification_status} onChange={set("verification_status")}>{statuses.map((s) => <option key={s}>{s}</option>)}</Select>
              </Field>
              <Field label="City"><Input value={form.city} onChange={set("city")} /></Field>
              <Field label="State"><Input value={form.state} onChange={set("state")} /></Field>
              <Field label="Country"><Input value={form.country} onChange={set("country")} /></Field>
              <Field label="Address"><Input value={form.address} onChange={set("address")} /></Field>
              <Field label="Tags" hint="Comma separated" className="sm:col-span-2"><Input value={form.tags} onChange={set("tags")} /></Field>
              <Field label="Notes" className="sm:col-span-2"><Textarea rows={3} value={form.notes} onChange={set("notes")} className="font-sans" /></Field>
            </div>

            {lead.category_evidence?.keywords && (
              <div className="rounded-lg border border-blue-100 bg-blue-50/50 p-3">
                <p className="text-sm font-medium text-navy-900">Why “{lead.category_evidence.category}” was suggested</p>
                <p className="mt-1 text-xs text-slate-600">Matched keywords: {lead.category_evidence.keywords.join(", ")} · confidence {lead.category_evidence.confidence}</p>
                <ul className="mt-2 space-y-1 text-xs italic text-slate-600">
                  {lead.category_evidence.snippets?.map((s, i) => <li key={i}>“{s}”</li>)}
                </ul>
              </div>
            )}

            <div>
              <p className="mb-2 text-sm font-medium text-navy-900">Where this email was found ({lead.sources.length})</p>
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
                {lead.sources.map((s) => (
                  <li key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                    {s.source_url ? (
                      <a href={s.source_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 break-all text-brand-700 hover:underline">
                        {s.source_url} <ExternalLink className="h-3 w-3 shrink-0" />
                      </a>
                    ) : (
                      <span className="font-medium">{s.source_filename}</span>
                    )}
                    {s.sheet_name && <Badge>sheet {s.sheet_name}</Badge>}
                    {s.row_number ? <Badge>{s.sheet_name || s.source_filename?.match(/\.(txt|md|xml|json)$/i) ? "row/line" : "row"} {s.row_number}</Badge> : null}
                    {s.page_number ? <Badge>page {s.page_number}</Badge> : null}
                    <span className="ml-auto text-xs text-slate-500">{fmtDate(s.collected_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </Modal>
      <ConfirmDialog open={confirmDelete} danger title="Delete this lead?" confirmLabel="Delete lead" message="This permanently removes the lead and its source records. This cannot be undone." onConfirm={remove} onCancel={() => setConfirmDelete(false)} />
    </>
  );
}
