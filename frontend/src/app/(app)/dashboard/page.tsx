"use client";
import { Activity, AlertTriangle, CalendarPlus, CheckCircle2, Copy, Globe, Hourglass, Mail, Building2, Users } from "lucide-react";
import Link from "next/link";
import React, { useCallback, useState } from "react";
import { ExportMenu } from "@/components/ExportMenu";
import { Button, Card, CardHeader, Checkbox, EmptyState, ErrorBlock, LoadingBlock, PageHeader, Stat, StatusBadge } from "@/components/ui";
import { api, ApiError, qs } from "@/lib/api";
import { fmtDate, fmtNum, JOB_TYPE_LABEL } from "@/lib/format";
import { usePolling } from "@/lib/hooks";
import type { DashboardStats } from "@/lib/types";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [includeTest, setIncludeTest] = useState(false);

  const load = useCallback(async () => {
    try {
      setStats(await api.get<DashboardStats>(`/api/dashboard/stats${qs({ include_test: includeTest })}`));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the dashboard");
    }
  }, [includeTest]);
  usePolling(load, 5000);
  React.useEffect(() => { load(); }, [load]);

  const isEmpty = stats && stats.unique_emails === 0 && stats.recent_jobs.length === 0;
  const maxCat = Math.max(1, ...(stats?.categories.map((c) => c.count) ?? [1]));

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="A live overview of everything collected so far."
        actions={
          <>
            <Checkbox label="Include sample/test data" checked={includeTest} onChange={setIncludeTest} />
            <ExportMenu choices={[
              { label: "Export all leads", description: "Leads, unique emails, failed URLs, summary", body: { scope: "all", include_test: includeTest } },
              { label: "Unique email addresses only", body: { scope: "all", format: "unique_emails", include_test: includeTest } },
              { label: "Emails grouped by domain", body: { scope: "all", format: "by_domain", include_test: includeTest } },
            ]} />
          </>
        }
      />
      {error && <Card><ErrorBlock message={error} onRetry={load} /></Card>}
      {!stats && !error && <LoadingBlock label="Loading dashboard…" />}
      {stats && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <Stat label="Total leads collected" value={fmtNum(stats.total_leads_collected)} hint="Every sighting incl. duplicates" icon={<Users className="h-5 w-5" />} />
            <Stat label="Unique email addresses" value={fmtNum(stats.unique_emails)} icon={<Mail className="h-5 w-5" />} />
            <Stat label="Unique businesses" value={fmtNum(stats.unique_businesses)} icon={<Building2 className="h-5 w-5" />} />
            <Stat label="Websites processed" value={fmtNum(stats.websites_processed)} icon={<Globe className="h-5 w-5" />} />
            <Stat label="Successful crawls" value={fmtNum(stats.successful_crawls)} icon={<CheckCircle2 className="h-5 w-5" />} />
            <Stat label="Failed websites" value={fmtNum(stats.failed_websites)} hint={stats.skipped_websites ? `+ ${fmtNum(stats.skipped_websites)} skipped` : undefined} icon={<AlertTriangle className="h-5 w-5" />} />
            <Stat label="Pending jobs" value={fmtNum(stats.pending_jobs)} hint="Queued, running or paused" icon={<Hourglass className="h-5 w-5" />} />
            <Stat label="Leads collected today" value={fmtNum(stats.leads_today)} hint="UTC day" icon={<CalendarPlus className="h-5 w-5" />} />
            <Stat label="Duplicate records removed" value={fmtNum(stats.duplicates_removed)} hint="Merged, sources kept" icon={<Copy className="h-5 w-5" />} />
          </div>

          {isEmpty ? (
            <Card>
              <EmptyState icon={<Activity className="h-6 w-6" />} title="Nothing collected yet" description="Start with a handful of company websites, or upload a spreadsheet of URLs. Results appear here as soon as the first job runs. (Leads from the bundled local test site are hidden here unless you tick “Include sample/test data”.)"
                action={<div className="flex gap-2"><Link href="/website-scraper"><Button>Start scraping</Button></Link><Link href="/upload"><Button variant="outline">Upload a file</Button></Link></div>} />
            </Card>
          ) : (
            <div className="grid gap-6 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <CardHeader title="Recent jobs" action={<Link href="/jobs" className="text-sm font-medium text-brand-700 hover:underline">View all</Link>} />
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-slate-50"><tr><th className="table-th">Job</th><th className="table-th">Status</th><th className="table-th">Progress</th><th className="table-th">New leads</th></tr></thead>
                    <tbody className="divide-y divide-slate-100">
                      {stats.recent_jobs.map((j) => (
                        <tr key={j.id} className="hover:bg-slate-50">
                          <td className="table-td"><Link href={`/jobs/${j.id}`} className="font-medium text-navy-900 hover:underline">{j.name}</Link><p className="text-xs text-slate-500">{JOB_TYPE_LABEL[j.type] ?? j.type} · {fmtDate(j.created_at)}</p></td>
                          <td className="table-td"><StatusBadge status={j.status} /></td>
                          <td className="table-td tabular-nums">{fmtNum(j.processed_urls)} / {fmtNum(j.total_urls)}</td>
                          <td className="table-td tabular-nums">{fmtNum(j.unique_leads)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <Card>
                <CardHeader title="Leads by category" description="Evidence-based suggestions you can edit" />
                <div className="space-y-3 p-5">
                  {stats.categories.length === 0 && <p className="text-sm text-slate-500">No categories yet.</p>}
                  {stats.categories.map((c) => (
                    <div key={c.name}>
                      <div className="mb-1 flex justify-between text-sm"><span className="text-slate-700">{c.name}</span><span className="tabular-nums text-slate-500">{fmtNum(c.count)}</span></div>
                      <div className="h-2 rounded-full bg-slate-100"><div className="h-2 rounded-full bg-brand-500" style={{ width: `${(c.count / maxCat) * 100}%` }} /></div>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          )}
        </div>
      )}
    </>
  );
}
