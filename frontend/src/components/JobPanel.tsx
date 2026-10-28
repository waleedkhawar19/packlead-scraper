"use client";
import { AlertTriangle, CheckCircle2, ExternalLink, Pause, Play, XCircle, Square } from "lucide-react";
import Link from "next/link";
import React, { useCallback, useEffect, useState } from "react";
import { LeadsTable } from "@/components/LeadsTable";
import { Badge, Button, Card, CardHeader, ErrorBlock, LoadingBlock, ProgressBar, StatusBadge } from "@/components/ui";
import { ConfirmDialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { api, ApiError } from "@/lib/api";
import { duration, fmtNum, JOB_TYPE_LABEL } from "@/lib/format";
import { usePolling } from "@/lib/hooks";
import type { Job, JobProgress, JobUrl, Page } from "@/lib/types";

const ACTIVE = ["queued", "running", "paused"];

function Counter({ label, value, tone }: { label: string; value: number; tone?: "green" | "red" | "amber" }) {
  const color = tone === "green" ? "text-emerald-600" : tone === "red" ? "text-red-600" : tone === "amber" ? "text-amber-600" : "text-navy-900";
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2.5">
      <p className={`text-xl font-semibold tabular-nums ${color}`}>{fmtNum(value)}</p>
      <p className="text-xs text-slate-500">{label}</p>
    </div>
  );
}

/** Live progress, controls, problem URLs and the results table (with Excel export) for one job. */
export function JobPanel({ jobId, showResults = true, title }: { jobId: number; showResults?: boolean; title?: string }) {
  const toast = useToast();
  const [job, setJob] = useState<Job | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [problems, setProblems] = useState<JobUrl[]>([]);
  const [problemTotal, setProblemTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [acting, setActing] = useState(false);

  const status = progress?.status ?? job?.status;
  const active = !status || ACTIVE.includes(status);

  const refresh = useCallback(async () => {
    try {
      const [p, j] = await Promise.all([api.get<JobProgress>(`/api/jobs/${jobId}/progress`), api.get<Job>(`/api/jobs/${jobId}`)]);
      setProgress(p);
      setJob(j);
      const bad = await api.get<Page<JobUrl>>(`/api/jobs/${jobId}/urls?status=failed,skipped&page_size=100`);
      setProblems(bad.items);
      setProblemTotal(bad.total);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the job");
    }
  }, [jobId]);

  usePolling(refresh, 1500, active);
  useEffect(() => {
    setJob(null);
    setProgress(null);
    refresh();
  }, [jobId, refresh]);

  async function control(action: "pause" | "resume" | "cancel") {
    setActing(true);
    try {
      await api.post(`/api/jobs/${jobId}/${action}`);
      toast.success(action === "pause" ? "Job paused" : action === "resume" ? "Job resumed" : "Job cancelled");
      setConfirmCancel(false);
      await refresh();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Action failed");
    } finally {
      setActing(false);
    }
  }

  if (error && !job) return <Card><ErrorBlock message={error} onRetry={refresh} /></Card>;
  if (!job || !progress) return <Card><LoadingBlock label="Loading job…" /></Card>;

  const tone = job.status === "completed" ? "green" : job.status === "paused" ? "amber" : "brand";
  const pct = progress.percent;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={
            <span className="flex flex-wrap items-center gap-2">
              {title ?? job.name} <StatusBadge status={job.status} />
              {job.is_test && <Badge tone="amber">TEST DATA</Badge>}
            </span>
          }
          description={`${JOB_TYPE_LABEL[job.type] ?? job.type} · Job #${job.id}${job.input_filename ? ` · ${job.input_filename}` : ""} · ${job.status === "completed" || job.status === "cancelled" || job.status === "failed" ? "took" : "running for"} ${duration(job.started_at ?? job.created_at, job.finished_at)}`}
          action={
            <div className="flex flex-wrap gap-2">
              {(job.status === "running" || job.status === "queued") && <Button size="sm" variant="outline" icon={<Pause className="h-4 w-4" />} loading={acting} onClick={() => control("pause")}>Pause</Button>}
              {job.status === "paused" && <Button size="sm" icon={<Play className="h-4 w-4" />} loading={acting} onClick={() => control("resume")}>Resume</Button>}
              {ACTIVE.includes(job.status) && <Button size="sm" variant="outline" className="!text-red-600" icon={<Square className="h-4 w-4" />} onClick={() => setConfirmCancel(true)}>Cancel</Button>}
              <Link href={`/jobs/${job.id}`} className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-300 px-3 text-xs font-medium text-slate-700 hover:bg-slate-50">Details <ExternalLink className="h-3 w-3" /></Link>
            </div>
          }
        />
        <div className="space-y-4 p-5">
          <div>
            <div className="mb-1.5 flex justify-between text-sm">
              <span className="font-medium text-slate-700">{fmtNum(progress.processed_urls)} of {fmtNum(progress.total_urls)} {job.type === "directory" ? "directories" : "websites"} processed</span>
              <span className="tabular-nums text-slate-500">{pct.toFixed(0)}%</span>
            </div>
            <ProgressBar percent={pct} tone={tone} />
            {job.status === "queued" && <p className="mt-2 text-xs text-slate-500">Waiting for the worker to pick this job up…</p>}
            {job.status === "paused" && <p className="mt-2 text-xs text-amber-700">Paused — pages already in flight finish, then nothing new starts until you resume.</p>}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
            <Counter label="Successful" value={progress.successful_urls} tone="green" />
            <Counter label="Failed" value={progress.failed_urls} tone={progress.failed_urls ? "red" : undefined} />
            <Counter label="Skipped sites" value={progress.skipped_urls} tone={progress.skipped_urls ? "amber" : undefined} />
            <Counter label="Pages visited" value={progress.pages_visited} />
            <Counter label="Pages skipped" value={progress.pages_skipped} />
            <Counter label="Emails found" value={progress.emails_found} />
            <Counter label="New unique leads" value={progress.unique_leads} tone="green" />
            <Counter label="Duplicates merged" value={progress.duplicates_removed} />
          </div>
          {job.error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"><b>Job error:</b> {job.error}</div>}
          {job.status === "completed" && progress.emails_found === 0 && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">The job finished but no public email addresses were found. Many sites hide emails behind contact forms — check the skipped/failed list below.</div>}
        </div>
      </Card>

      {progress.recent.length > 0 && (
        <Card>
          <CardHeader title="Recent activity" description={active ? "Updates live while the job runs" : "Last results"} />
          <ul className="divide-y divide-slate-100">
            {progress.recent.map((r) => (
              <li key={r.id} className="flex flex-wrap items-start gap-3 px-5 py-2.5 text-sm">
                {r.status === "success" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> : r.status === "failed" ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />}
                <div className="min-w-0 flex-1">
                  <p className="break-all font-medium text-slate-800">{r.url}</p>
                  <p className="text-xs text-slate-500">{r.status === "success" ? `${r.pages_visited} pages visited, ${r.emails_found} emails${r.pages_skipped ? `, ${r.pages_skipped} pages skipped` : ""}` : r.error || r.note}{r.status === "success" && r.note ? ` · ${r.note}` : ""}</p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {problemTotal > 0 && (
        <Card>
          <CardHeader title={`Failed or skipped websites (${fmtNum(problemTotal)})`} description="These were not scraped successfully. Nothing was bypassed — restricted, blocked or unreachable sites are reported here." />
          <div className="max-h-80 overflow-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-slate-50"><tr><th className="table-th">URL</th><th className="table-th">Status</th><th className="table-th">Reason</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {problems.map((p) => (
                  <tr key={p.id}>
                    <td className="table-td break-all">{p.original_input || p.url}</td>
                    <td className="table-td"><StatusBadge status={p.status} /></td>
                    <td className="table-td text-slate-600">{p.error || p.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {showResults && (
        <div>
          <h2 className="mb-2 text-base font-semibold text-navy-900">Results</h2>
          <LeadsTable
            fixedFilters={{ job_id: job.id, include_test: job.is_test }}
            refreshKey={progress.unique_leads + progress.processed_urls + (active ? 0 : 1)}
            exportScopeJobId={job.id}
            pageSize={10}
            emptyHint={active ? "Leads will appear here as websites are processed." : "This job did not produce any leads."}
          />
        </div>
      )}

      <ConfirmDialog open={confirmCancel} danger title="Cancel this job?" confirmLabel="Cancel job" loading={acting} message="Work stops as soon as the pages in flight finish. Leads already collected are kept." onConfirm={() => control("cancel")} onCancel={() => setConfirmCancel(false)} />
    </div>
  );
}
