"use client";
import { Eye, Pause, Play, Square, Trash2 } from "lucide-react";
import Link from "next/link";
import React, { useCallback, useState } from "react";
import { useExporter } from "@/components/ExportMenu";
import { Button, Card, Checkbox, EmptyState, ErrorBlock, LoadingBlock, PageHeader, ProgressBar, Select, StatusBadge } from "@/components/ui";
import { ConfirmDialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, qs } from "@/lib/api";
import { duration, fmtDate, fmtNum, JOB_TYPE_LABEL } from "@/lib/format";
import { usePolling } from "@/lib/hooks";
import type { Job, Page } from "@/lib/types";

export default function JobsPage() {
  const toast = useToast();
  const exporter = useExporter();
  const [data, setData] = useState<Page<Job> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const [toDelete, setToDelete] = useState<Job | null>(null);
  const [alsoLeads, setAlsoLeads] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const pageSize = 20;

  const load = useCallback(async () => {
    try {
      setData(await api.get<Page<Job>>(`/api/jobs${qs({ status, type, page, page_size: pageSize })}`));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load jobs");
    }
  }, [status, type, page]);
  usePolling(load, 3000);
  React.useEffect(() => { load(); }, [load]);

  async function act(job: Job, action: "pause" | "resume" | "cancel") {
    try {
      await api.post(`/api/jobs/${job.id}/${action}`);
      toast.success(`Job #${job.id} ${action === "cancel" ? "cancelled" : action === "pause" ? "paused" : "resumed"}`);
      load();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : `Could not ${action} the job`);
    }
  }

  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await api.del(`/api/jobs/${toDelete.id}${qs({ delete_leads: alsoLeads })}`);
      toast.success(`Job #${toDelete.id} deleted`);
      setToDelete(null);
      setAlsoLeads(false);
      load();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not delete the job");
    } finally {
      setDeleting(false);
    }
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const active = (s: string) => s === "running" || s === "queued" || s === "paused";

  return (
    <>
      <PageHeader title="Job History" description="Every scrape and import, with its settings, progress and results. Jobs keep running in the background if you leave this page." />
      <Card>
        <div className="flex flex-wrap gap-3 border-b border-slate-100 p-4">
          <Select className="w-44" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Filter by status">
            <option value="">All statuses</option>
            {["queued", "running", "paused", "completed", "failed", "cancelled"].map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}
          </Select>
          <Select className="w-52" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} aria-label="Filter by type">
            <option value="">All job types</option>
            {Object.entries(JOB_TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <span className="ml-auto self-center text-sm text-slate-500">{data ? `${fmtNum(data.total)} job${data.total === 1 ? "" : "s"}` : ""}</span>
        </div>
        {error && <ErrorBlock message={error} onRetry={load} />}
        {!data && !error && <LoadingBlock label="Loading jobs…" />}
        {data && data.items.length === 0 && (
          <EmptyState title="No jobs yet" description="Jobs appear here as soon as you start a scrape or import." action={<Link href="/website-scraper"><Button>Start scraping</Button></Link>} />
        )}
        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-50">
                <tr>
                  <th className="table-th">Job</th><th className="table-th">Status</th><th className="table-th min-w-[160px]">Progress</th>
                  <th className="table-th">Emails</th><th className="table-th">Failed / skipped</th><th className="table-th">Duration</th><th className="table-th text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((j) => (
                  <tr key={j.id} className="hover:bg-slate-50">
                    <td className="table-td">
                      <Link href={`/jobs/${j.id}`} className="font-medium text-navy-900 hover:underline">#{j.id} {j.name}</Link>
                      <p className="text-xs text-slate-500">{JOB_TYPE_LABEL[j.type] ?? j.type} · {fmtDate(j.created_at)}{j.is_test ? " · TEST DATA" : ""}</p>
                    </td>
                    <td className="table-td"><StatusBadge status={j.status} /></td>
                    <td className="table-td">
                      <ProgressBar percent={j.total_urls ? (j.processed_urls / j.total_urls) * 100 : 0} />
                      <p className="mt-1 text-xs tabular-nums text-slate-500">{fmtNum(j.processed_urls)} / {fmtNum(j.total_urls)}</p>
                    </td>
                    <td className="table-td tabular-nums">{fmtNum(j.unique_leads)} <span className="text-xs text-slate-400">unique</span></td>
                    <td className="table-td tabular-nums">{fmtNum(j.failed_urls)} / {fmtNum(j.skipped_urls)}</td>
                    <td className="table-td tabular-nums">{duration(j.started_at, j.finished_at)}</td>
                    <td className="table-td">
                      <div className="flex justify-end gap-1">
                        <Link href={`/jobs/${j.id}`}><Button size="sm" variant="ghost" icon={<Eye className="h-4 w-4" />} aria-label="View job" /></Link>
                        {j.status === "running" && <Button size="sm" variant="ghost" icon={<Pause className="h-4 w-4" />} aria-label="Pause" onClick={() => act(j, "pause")} />}
                        {j.status === "paused" && <Button size="sm" variant="ghost" icon={<Play className="h-4 w-4" />} aria-label="Resume" onClick={() => act(j, "resume")} />}
                        {active(j.status) && <Button size="sm" variant="ghost" icon={<Square className="h-4 w-4" />} aria-label="Cancel" onClick={() => act(j, "cancel")} />}
                        {j.unique_leads > 0 && <Button size="sm" variant="outline" onClick={() => exporter.run({ scope: "job", job_id: j.id })} loading={exporter.busy}>Export</Button>}
                        {!active(j.status) && <Button size="sm" variant="ghost" icon={<Trash2 className="h-4 w-4 text-red-600" />} aria-label="Delete job" onClick={() => setToDelete(j)} />}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > pageSize && (
          <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-sm">
            <span className="text-slate-500">Page {page} of {pages}</span>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          </div>
        )}
      </Card>
      <ConfirmDialog
        open={!!toDelete} danger loading={deleting} confirmLabel="Delete job"
        title={`Delete job #${toDelete?.id ?? ""}?`}
        message="The job record and its per-URL results are removed. Collected leads are kept unless you tick the box below."
        onConfirm={confirmDelete} onCancel={() => { setToDelete(null); setAlsoLeads(false); }}
      >
        <div className="mt-3"><Checkbox label="Also delete leads that were first found by this job" checked={alsoLeads} onChange={setAlsoLeads} /></div>
      </ConfirmDialog>
    </>
  );
}
